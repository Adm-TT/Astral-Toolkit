from collections.abc import Iterable
from .models import Item
from .storage import Database


class Catalog:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, items: Iterable[Item]) -> None:
        items = list(items)
        with self.db.connection() as c:
            c.executemany('INSERT INTO items(id,name,uuid) VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, uuid=coalesce(excluded.uuid, items.uuid)', [(i.id, i.name, i.uuid) for i in items])
        try:
            self.fill_keys([i.id for i in items])
        except Exception:                                 # 对编号失败不影响记物品
            pass

    def fill_keys(self, ids=None, backup=None) -> int:
        """给还没有游戏编号的物品对上游戏类名和 uuid（1.6.55，交易平台用）。ids=None：全部物品。
        backup：第一次填（表还是空的）而且真有要填的，先把数据库备份到这里。返回填了几个"""
        from .gamekey import resolve
        with self.db.connection() as c:
            have = {r[0] for r in c.execute('SELECT id FROM items WHERE cls IS NOT NULL')}
            rows = c.execute('SELECT id, name FROM items').fetchall()
        want = set(ids) if ids is not None else None
        todo = []
        for r in rows:
            if r['id'] in have or (want is not None and r['id'] not in want):
                continue
            hit = resolve(r['name'])
            if hit:
                todo.append((r['id'], *hit))
        if not todo:
            return 0
        with self.db.connection() as c:
            if backup and not have:
                self.db.backup_to(backup)
            c.executemany("UPDATE items SET cls=?, game_uuid=nullif(?, '') WHERE id=? AND cls IS NULL", [(cls, u, i) for i, cls, u in todo])
        return len(todo)

    def game_key(self, item_id: str):
        """物品 → (游戏类名, 游戏 uuid)；没对上返回 None"""
        with self.db.connection() as c:
            r = c.execute('SELECT cls, game_uuid FROM items WHERE id=? AND cls IS NOT NULL', (item_id,)).fetchone()
            return (r['cls'], r['game_uuid'] or '') if r else None

    def search(self, query: str) -> list[Item]:
        found = {i.id: i for i in self._like(query)}
        # 中文名查不到时，用汉化包对照表换成英文名再找（目录里多数物品是英文名）
        from .names import to_english
        for en in to_english(query):
            for item in self._like(en):
                found.setdefault(item.id, item)
        return sorted(found.values(), key=lambda i: i.name)

    def _like(self, query: str) -> list[Item]:
        # Escaping makes percent/underscore literal search characters.
        value = '%' + query.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        with self.db.connection() as c:
            rows = c.execute("SELECT DISTINCT i.* FROM items i LEFT JOIN aliases a ON a.item_id=i.id WHERE i.name LIKE ? ESCAPE '\\' OR a.alias LIKE ? ESCAPE '\\' ORDER BY i.name", (value, value))
            return [Item(r['id'], r['name'], r['uuid']) for r in rows]

    def by_alias(self, alias: str) -> Item | None:
        """以前认过、记成别名的名字（完全一样）→ 物品；UEX 的优先"""
        if not alias or not alias.strip():
            return None
        with self.db.connection() as c:
            r = c.execute("SELECT i.* FROM items i JOIN aliases a ON a.item_id=i.id WHERE a.alias=? "
                          "ORDER BY (i.id LIKE 'scm:%'), i.name LIMIT 1", (alias.strip(),)).fetchone()
            return Item(r['id'], r['name'], r['uuid']) if r else None

    def get(self, item_id: str) -> Item | None:
        with self.db.connection() as c:
            r = c.execute('SELECT * FROM items WHERE id=?', (item_id,)).fetchone()
            return Item(r['id'], r['name'], r['uuid']) if r else None

    def add_alias(self, item_id: str, alias: str) -> None:
        if not alias.strip():
            raise ValueError('别名不能为空')
        with self.db.connection() as c:
            c.execute('INSERT OR IGNORE INTO aliases VALUES (?,?)', (item_id, alias.strip()))

    def map_source(self, source: str, external_id: str, item_id: str) -> None:
        with self.db.connection() as c:
            c.execute('INSERT OR REPLACE INTO source_ids VALUES (?,?,?)', (source, external_id, item_id))

    def source_id(self, source: str, item_id: str) -> str | None:
        with self.db.connection() as c:
            r = c.execute('SELECT external_id FROM source_ids WHERE source=? AND item_id=? ORDER BY external_id', (source, item_id)).fetchone()
            return r[0] if r else None
