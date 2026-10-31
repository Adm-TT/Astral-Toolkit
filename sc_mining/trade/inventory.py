from collections import defaultdict
from datetime import datetime, timezone
import sqlite3  # noqa: F401
import uuid
from .models import StockKey, StockLine, ImportPreview


def _qty(value, zero=False):
    if type(value) is not int or not (0 if zero else 1) <= value <= 2**53 - 1:
        raise ValueError('数量必须为有效整数，不能为负数')
    return value


def _parts(key):
    if not all(isinstance(v, str) and v.strip() for v in (key.item_id, key.quality, key.location, key.unit)):
        raise ValueError('物品、品质、地点和单位不能为空')
    return key.item_id, key.quality, key.location, key.unit


class Inventory:
    def __init__(self, db, workspace=None):
        from .storage import PERSONAL
        self.db = db
        self.ws = workspace or PERSONAL          # 工作区：个人库存是 personal；舰队以后接服务器再加

    @staticmethod
    def _revision(c):
        r = c.execute("SELECT value FROM settings WHERE key='inventory_revision'").fetchone()
        return int(r[0]) if r else 0

    def _quantity(self, c, key):
        row = c.execute('SELECT quantity FROM stocks WHERE workspace_id=? AND item_id=? AND quality=? AND location=? AND unit=?',
                        (self.ws, *_parts(key))).fetchone()
        return row[0] if row else 0

    # ---- 1.6.67：制造出来的东西，每个材料槽的品质（品质栏显示平均，详情显示「框架 858 · 线缆 916 · …」）
    def set_craft(self, item_id, quality, slots):
        import json
        with self.db.connection() as c:
            c.execute('INSERT OR REPLACE INTO craft_details VALUES (?,?,?,?)',
                      (self.ws, item_id, quality, json.dumps(slots, ensure_ascii=False)))

    def craft_map(self):
        """{(物品, 品质键): [槽…]}"""
        import json
        with self.db.connection() as c:
            return {(r[0], r[1]): json.loads(r[2]) for r in
                    c.execute('SELECT item_id, quality, detail FROM craft_details WHERE workspace_id=?', (self.ws,))}

    def migrate_cscu(self, backup=None):
        """以前矿和材料按 0.01 SCU（cSCU）记，游戏里显示到 0.001 SCU（0.495 SCU），存不下。
        改成按 uSCU（百万分之一 SCU）记：数量 ×10000，历史记录一起换算（撤销照常能用）。
        backup：换算前把数据库备份到这个路径（只在真有旧记录要换算时备份）。返回换算了几行"""
        with self.db.connection() as c:
            n = c.execute("SELECT COUNT(*) FROM stocks WHERE unit='cSCU'").fetchone()[0] \
                + c.execute("SELECT COUNT(*) FROM movements WHERE unit='cSCU'").fetchone()[0]
            if not n:
                return 0
            if backup:
                self.db.backup_to(backup)
            W = "workspace_id=? AND item_id=? AND quality=? AND location=?"
            for r in c.execute("SELECT workspace_id, item_id, quality, location, quantity FROM stocks WHERE unit='cSCU'").fetchall():
                k = (r['workspace_id'], r['item_id'], r['quality'], r['location'])
                if c.execute(f"SELECT 1 FROM stocks WHERE {W} AND unit='uSCU'", k).fetchone():
                    c.execute(f"UPDATE stocks SET quantity=quantity+? WHERE {W} AND unit='uSCU'", (r['quantity'] * 10000, *k))
                    c.execute(f"DELETE FROM stocks WHERE {W} AND unit='cSCU'", k)
                else:
                    c.execute(f"UPDATE stocks SET unit='uSCU', quantity=quantity*10000 WHERE {W} AND unit='cSCU'", k)
            c.execute("UPDATE movements SET unit='uSCU', delta=delta*10000, before_qty=before_qty*10000, after_qty=after_qty*10000 "
                      "WHERE unit='cSCU'")
            c.execute("INSERT OR REPLACE INTO settings VALUES ('inventory_revision',?)", (str(self._revision(c) + 1),))
        return n

    def list_stock(self, query=''):
        with self.db.connection() as c:
            rows = c.execute('SELECT s.*,i.name FROM stocks s JOIN items i ON i.id=s.item_id WHERE s.workspace_id=? AND quantity>0 '
                             'ORDER BY i.name,s.location,s.quality', (self.ws,))
            return [StockLine(StockKey(r['item_id'], r['quality'], r['location'], r['unit']), r['quantity']) for r in rows if query.casefold() in (r['name'] + ' ' + r['location']).casefold()]

    def prepare(self, lines, mode, image_hash=None):
        if mode not in ('add', 'count'):
            raise ValueError('无效入库模式')
        totals = defaultdict(int)
        for line in lines:
            _parts(line.key)
            totals[line.key] += _qty(line.quantity)
            _qty(totals[line.key])
        if not totals:
            raise ValueError('请至少添加一行物品')
        merged = tuple(StockLine(k, n) for k, n in totals.items())
        with self.db.connection() as c:
            before = tuple(StockLine(line.key, self._quantity(c, line.key)) for line in merged)
            duplicate = bool(image_hash and c.execute('SELECT 1 FROM batches WHERE image_hash=?', (image_hash,)).fetchone())
            return ImportPreview(merged, before, mode, image_hash, duplicate, self._revision(c))

    def _write(self, c, changes, mode, image_hash=None, op_id=None, undo_of=None):
        """一笔库存变动（一个批次）。op_id：这次操作的编号，同一个编号再来一次（连点、重发）直接返回第一次的批次，不重复记"""
        if op_id:
            hit = c.execute('SELECT id FROM batches WHERE op_id=?', (op_id,)).fetchone()
            if hit:
                return hit[0]
        # Prevalidate every row; the enclosing transaction remains the final safety boundary.
        changes=list(changes)
        if len({key for key,_ in changes})!=len(changes):
            raise ValueError('同一库存组不能在一笔变更中重复出现')
        checked = []
        for key, delta in changes:
            _parts(key)
            if type(delta) is not int:
                raise ValueError('数量必须为整数')
            if not c.execute('SELECT 1 FROM items WHERE id=?', (key.item_id,)).fetchone():
                raise ValueError('物品不在目录中，请先添加物品')
            before = self._quantity(c, key)
            after = _qty(before + delta, zero=True)
            checked.append((key, delta, before, after))
        batch = uuid.uuid4().hex
        from .device import device
        dev, dev_name = device()
        c.execute('INSERT INTO batches(id,workspace_id,at,mode,image_hash,op_id,device,device_name,undo_of) VALUES (?,?,?,?,?,?,?,?,?)',
                  (batch, self.ws, datetime.now(timezone.utc).isoformat(), mode, image_hash, op_id, dev, dev_name, undo_of))
        for key, delta, before, after in checked:
            c.execute('INSERT INTO stocks VALUES (?,?,?,?,?,?) ON CONFLICT(workspace_id,item_id,quality,location,unit) '
                      'DO UPDATE SET quantity=excluded.quantity', (self.ws, *_parts(key), after))
            c.execute('INSERT INTO movements(batch_id,workspace_id,item_id,quality,location,unit,delta,before_qty,after_qty) '
                      'VALUES (?,?,?,?,?,?,?,?,?)', (batch, self.ws, *_parts(key), delta, before, after))
        c.execute("INSERT OR REPLACE INTO settings VALUES ('inventory_revision',?)", (str(self._revision(c) + 1),))
        return batch

    def commit(self, preview, allow_duplicate=False):
        if preview.mode not in ('add', 'count'):
            raise ValueError('无效入库模式')
        with self.db.connection() as c:
            if self._revision(c) != preview.revision:
                raise ValueError('库存已经变化，请重新预览')
            is_duplicate = preview.image_hash and c.execute('SELECT 1 FROM batches WHERE image_hash=?', (preview.image_hash,)).fetchone()
            if is_duplicate and not allow_duplicate:
                raise ValueError('此截图已导入，请核对重复记录')
            if not preview.lines or len({l.key for l in preview.lines}) != len(preview.lines):  # noqa: E741
                raise ValueError('请重新生成入库预览')
            changes = []
            for line in preview.lines:
                _qty(line.quantity)
                delta = line.quantity if preview.mode == 'add' else line.quantity - self._quantity(c, line.key)
                changes.append((line.key, delta))
            return self._write(c, changes, preview.mode, preview.image_hash)

    def adjust(self, key, delta):
        if type(delta) is not int or delta == 0:
            raise ValueError('请填写非零整数变动量')
        with self.db.connection() as c:
            return self._write(c, [(key, delta)], 'adjust')

    # ---------------------------------------------------------------- 天枢 1.6.39：出库 / 改数量 / 移库 / 改品质，每笔可以带备注
    # 记录类型（batches.mode）：add 入库、out 出库、set 改数量、move 移库、quality 改品质、undo:… 撤销
    # （以前的 adjust 是改数量或改品质，count 是盘点）

    @staticmethod
    def _note(c, batch, note='', reason='', source=''):
        note, reason, source = (str(v or '').strip()[:200] for v in (note, reason, source))
        if note or reason or source:
            c.execute('UPDATE batches SET note=?,reason=?,source=? WHERE id=?', (note, reason, source, batch))

    def set_note(self, batch, note='', reason='', source=''):
        with self.db.connection() as c:
            self._note(c, batch, note, reason, source)

    def _enough(self, c, key, quantity):
        _qty(quantity)
        have = self._quantity(c, key)
        if quantity > have:
            raise ValueError('库存不够：这一行没有这么多了，刷新一下')
        return have

    def out(self, key, quantity, reason='', note='', source=''):
        """出库（卖了、用掉、交了维科洛……）"""
        with self.db.connection() as c:
            self._enough(c, key, quantity)
            batch = self._write(c, [(key, -quantity)], 'out')
            self._note(c, batch, note, reason, source)
            return batch

    def out_many(self, items, reason='', note='', source=''):
        """一笔出库好几行（目标「做完了」扣掉用掉的材料）。items: [(StockKey, 数量)]，同一行出现两次合在一起扣"""
        merged = defaultdict(int)
        for key, quantity in items:
            merged[key] += _qty(quantity)
        if not merged:
            raise ValueError('没有要出库的东西')
        with self.db.connection() as c:
            for key, quantity in merged.items():
                self._enough(c, key, quantity)
            batch = self._write(c, [(k, -q) for k, q in merged.items()], 'out')
            self._note(c, batch, note, reason, source)
            return batch

    def rename_location(self, old, new, note=''):
        """仓位改名 / 删仓位时，把这个位置的东西整个换到新位置（一笔移库，能撤销）。没东西返回 0"""
        try:
            return self.relocate(old, new, note=note)
        except ValueError as e:
            if '没有东西' in str(e):
                return 0
            raise

    def _quantity_of(self, key):
        with self.db.connection() as c:
            return self._quantity(c, key)

    def revision(self):
        """库存版本号：每写一笔 +1。盘点对账时记下，确认时核对，中间有人改过账就不能按旧账改（老大审查 2026-10-28 第 8 条）"""
        with self.db.connection() as c:
            return self._revision(c)

    def apply_count(self, targets, revision, source='盘点'):
        """盘点确认：targets=[(key, 游戏里的实际数), …]，一笔事务改成一个批次（mode='count'）；
        revision 和对账时不一样（中间改过账）就抛 ValueError，一行都不改。返回批次号；没有要改的返回 None"""
        with self.db.connection() as c:
            if self._revision(c) != revision:
                raise ValueError('盘点后库存变过了，重新盘点一次再确认')
            changes = []
            for key, target in targets:
                _qty(target, zero=True)
                delta = target - self._quantity(c, key)
                if delta:
                    changes.append((key, delta))
            if not changes:
                return None
            batch = self._write(c, changes, 'count')
            self._note(c, batch, '', '', source)
            return batch

    def set_quantity(self, key, quantity, note='', source='', mode='set'):
        """改数量：在游戏里数完，直接改成实际数（可以改成 0）。mode='count'：盘点改的，记录里显示「盘点」"""
        _qty(quantity, zero=True)
        with self.db.connection() as c:
            delta = quantity - self._quantity(c, key)
            if not delta:
                raise ValueError('数量没变')
            batch = self._write(c, [(key, delta)], mode)
            self._note(c, batch, note, '', source)
            return batch

    def move(self, key, destination, quantity, note='', source=''):
        _qty(quantity)
        destination=destination.strip()
        if not destination or destination == key.location:
            raise ValueError('请选择不同的目标位置')
        target = StockKey(key.item_id, key.quality, destination, key.unit)
        with self.db.connection() as c:
            self._enough(c, key, quantity)
            batch = self._write(c, [(key, -quantity), (target, quantity)], 'move')
            self._note(c, batch, note, '', source)
            return batch

    def relocate(self, location, destination, note=''):
        """一个地点的东西整个搬到另一个地点（以前手打的位置对不上，归到列表里的地点）。返回搬了几行"""
        destination = destination.strip()
        if not destination or destination == location:
            raise ValueError('请选择不同的目标位置')
        with self.db.connection() as c:
            rows = c.execute('SELECT item_id,quality,unit,quantity FROM stocks WHERE workspace_id=? AND location=? AND quantity>0',
                             (self.ws, location)).fetchall()
            if not rows:
                raise ValueError('这个地点已经没有东西了')
            changes = []
            for r in rows:
                changes.append((StockKey(r['item_id'], r['quality'], location, r['unit']), -r['quantity']))
                changes.append((StockKey(r['item_id'], r['quality'], destination, r['unit']), r['quantity']))
            batch = self._write(c, changes, 'move')
            self._note(c, batch, note, '', '')
            return len(rows)

    def requality(self, key, quality, note=''):
        """改品质：这一行整批从旧品质挪到新品质（一笔记录，撤销时一起回去）"""
        if quality == key.quality:
            raise ValueError('品质没变')
        target = StockKey(key.item_id, quality, key.location, key.unit)
        with self.db.connection() as c:
            have = self._quantity(c, key)
            if have <= 0:
                raise ValueError('这一行库存已经变了，刷新一下')
            batch = self._write(c, [(key, -have), (target, have)], 'quality')
            self._note(c, batch, note, '', '')
            return batch

    def normalize_locations(self, canon, backup=None):
        """以前手打的位置能对上地点列表的（英文名、空格大小写不同：New Babbage、Area18），改成列表里的叫法。
        canon(位置) → 标准叫法或 None（对不上的不动，库存页里放「未归类」）。真要改时先备份数据库；记一笔移库，能撤销。返回改了几个位置"""
        with self.db.connection() as c:
            locs = [r[0] for r in c.execute('SELECT DISTINCT location FROM stocks WHERE workspace_id=? AND quantity>0', (self.ws,))]
            todo = {a: canon(a) for a in locs}
            todo = {a: b for a, b in todo.items() if b and b != a}
            if not todo:
                return 0
            if backup:
                self.db.backup_to(backup)
            deltas = defaultdict(int)
            for a, b in todo.items():
                for r in c.execute('SELECT item_id,quality,unit,quantity FROM stocks WHERE workspace_id=? AND location=? AND quantity>0',
                                   (self.ws, a)).fetchall():
                    deltas[StockKey(r['item_id'], r['quality'], a, r['unit'])] -= r['quantity']
                    deltas[StockKey(r['item_id'], r['quality'], b, r['unit'])] += r['quantity']
            batch = self._write(c, [(k, d) for k, d in deltas.items() if d], 'move')
            self._note(c, batch, '地点自动归位：' + '，'.join(f'{a} → {b}' for a, b in todo.items()), '', 'AT')
            return len(todo)

    def last_changes(self):
        """{(物品, 品质, 位置, 单位): 最后一次变动的时间}（库存页按「最近变动」排序用）"""
        with self.db.connection() as c:
            return {(r['item_id'], r['quality'], r['location'], r['unit']): r['at'] for r in c.execute(
                'SELECT m.item_id,m.quality,m.location,m.unit,MAX(b.at) AS at FROM movements m JOIN batches b ON b.id=m.batch_id '
                'WHERE m.workspace_id=? GROUP BY m.item_id,m.quality,m.location,m.unit', (self.ws,))}

    def locations(self):
        """库存里用到的所有位置（有东西的）"""
        with self.db.connection() as c:
            return [r[0] for r in c.execute('SELECT DISTINCT location FROM stocks WHERE workspace_id=? AND quantity>0', (self.ws,))]

    def _undo_changes(self, c, batch_id):
        batch = c.execute('SELECT * FROM batches WHERE id=? AND workspace_id=?', (batch_id, self.ws)).fetchone()
        if not batch or batch['undone'] or batch['mode'].startswith('undo:'):
            raise ValueError('该批次已撤销或不支持再次撤销')
        rows = c.execute('SELECT * FROM movements WHERE batch_id=?', (batch_id,)).fetchall()
        # 依赖检查（2026-10-25 定：有依赖的撤销一律禁止）：同一行库存在这笔之后还有没撤销的操作，就不能单独撤这笔
        # （已撤销的批次和撤销批次本身不算：它们互相抵消了）
        for r in rows:
            later = c.execute(
                "SELECT 1 FROM movements m JOIN batches b ON b.id=m.batch_id WHERE m.workspace_id=? AND m.item_id=? AND m.quality=? "
                "AND m.location=? AND m.unit=? AND m.id>? AND b.undone=0 AND b.mode NOT LIKE 'undo:%' LIMIT 1",
                (self.ws, r['item_id'], r['quality'], r['location'], r['unit'], r['id'])).fetchone()
            if later:
                raise ValueError('无法撤销：此记录之后同一行库存还有其他操作（出库、移库或修改数量），需先撤销之后的记录，或使用「改数量」调整')
        return [(StockKey(r['item_id'], r['quality'], r['location'], r['unit']), -r['delta']) for r in rows]

    def preview_undo(self, batch_id):
        with self.db.connection() as c:
            changes = self._undo_changes(c, batch_id)
            before = tuple(StockLine(k, self._quantity(c, k)) for k, _ in changes)
            lines = tuple(StockLine(k, _qty(self._quantity(c, k) + d, zero=True)) for k, d in changes)
            return ImportPreview(lines, before, 'undo:' + batch_id, revision=self._revision(c))

    def undo(self, batch_id):
        with self.db.connection() as c:
            changes = self._undo_changes(c, batch_id)
            self._write(c, changes, 'undo:' + batch_id, undo_of=batch_id)
            c.execute('UPDATE batches SET undone=1 WHERE id=?', (batch_id,))

    def history(self):
        with self.db.connection() as c:
            return [dict(r) for r in c.execute(
                "SELECT m.*,b.at,b.mode,b.undone,i.name,b.note,b.reason,b.source,b.device,b.device_name "
                "FROM movements m JOIN batches b ON m.batch_id=b.id JOIN items i ON m.item_id=i.id "
                "WHERE m.workspace_id=? ORDER BY m.id DESC", (self.ws,))]
