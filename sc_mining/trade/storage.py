"""库存数据库（SQLite）：每次操作开一个短连接；打开前检查是不是交易助手的库"""

from contextlib import contextmanager, closing
from pathlib import Path
import json
import re
import sqlite3
import threading

APP_ID = 0x53435443
# 1.6.58 起：天枢自己的库存文件 dubhe_inventory.db，表结构按「库存方案」重新设计（版本 2）。
# 旧的 inventory.db（版本 1，和原来的交易助手共用）一个字节都不动：第一次启动时只读地导一份过来（import_v1）。
# 稳定版 1.6.28 和原来的交易助手照样打开旧文件。
SCHEMA_VERSION = 2
PERSONAL = "personal"  # 个人工作区；舰队工作区以后接服务器再加
SCHEMA = """
CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, name TEXT NOT NULL, uuid TEXT, cls TEXT, game_uuid TEXT);
CREATE TABLE IF NOT EXISTS aliases (item_id TEXT REFERENCES items(id), alias TEXT NOT NULL, PRIMARY KEY(item_id,alias));
CREATE TABLE IF NOT EXISTS source_ids (source TEXT, external_id TEXT, item_id TEXT REFERENCES items(id), PRIMARY KEY(source,external_id));
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS stocks (workspace_id TEXT NOT NULL REFERENCES workspaces(id), item_id TEXT NOT NULL REFERENCES items(id), quality TEXT NOT NULL, location TEXT NOT NULL, unit TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>=0), PRIMARY KEY(workspace_id,item_id,quality,location,unit));
CREATE TABLE IF NOT EXISTS batches (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), at TEXT NOT NULL, mode TEXT NOT NULL, image_hash TEXT, undone INTEGER NOT NULL DEFAULT 0, op_id TEXT UNIQUE, actor TEXT NOT NULL DEFAULT '', device TEXT NOT NULL DEFAULT '', device_name TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '', undo_of TEXT);
CREATE TABLE IF NOT EXISTS movements (id INTEGER PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(id), workspace_id TEXT NOT NULL, item_id TEXT NOT NULL, quality TEXT NOT NULL, location TEXT NOT NULL, unit TEXT NOT NULL, delta INTEGER NOT NULL, before_qty INTEGER NOT NULL, after_qty INTEGER NOT NULL, unit_cost REAL);
CREATE INDEX IF NOT EXISTS movements_row ON movements(workspace_id,item_id,quality,location,unit,id);
CREATE TABLE IF NOT EXISTS snapshots (key TEXT NOT NULL, hour TEXT NOT NULL, at TEXT NOT NULL, mean TEXT NOT NULL, minimum TEXT, PRIMARY KEY(key,hour));
CREATE TABLE IF NOT EXISTS provider_cache (cache_key TEXT PRIMARY KEY, at TEXT NOT NULL, next_at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS craft_details (workspace_id TEXT NOT NULL, item_id TEXT NOT NULL, quality TEXT NOT NULL, detail TEXT NOT NULL, PRIMARY KEY(workspace_id,item_id,quality));
"""
# 1.6.67 新加的表（制造出来的东西每个材料槽的品质）：老文件里没有的表打开时补上，不算「表结构不符」


def _schema_signature(connection):
    result = {}
    for name, sql in connection.execute(
        "SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ):
        # Names come exclusively from SQLite's internal catalog, not input interpolation.
        quoted = '"' + name.replace('"', '""') + '"'
        columns = tuple(
            tuple(r) for r in connection.execute("PRAGMA table_info(" + quoted + ")")
        )
        foreign_keys = tuple(
            tuple(r)
            for r in connection.execute("PRAGMA foreign_key_list(" + quoted + ")")
        )
        result[name] = (
            columns,
            foreign_keys,
            re.sub(r"\s+", " ", sql).strip().casefold(),
        )
    return result


def _expected_schema():
    with closing(sqlite3.connect(":memory:")) as c:
        c.executescript(SCHEMA)
        return _schema_signature(c)


EXPECTED_SCHEMA = _expected_schema()


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._tls = threading.local()
        if self.path.exists():
            self._validate(self.path)
        with (
            self.lock,
            closing(sqlite3.connect(self.path, timeout=15)) as con,
        ):  # 建表：executescript 自己管事务
            con.executescript(SCHEMA)
            con.execute(f"PRAGMA application_id={APP_ID}")
            con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            con.execute(
                "INSERT OR IGNORE INTO workspaces VALUES (?,?,?,datetime('now'))",
                (PERSONAL, "personal", "个人"),
            )
            con.commit()

    @contextmanager
    def connection(self):
        """一次操作一个短连接、一个事务。一开始就拿写锁（BEGIN IMMEDIATE）：先读后写的操作（算可用量再扣）
        不会和别的写操作交错；出错整笔回滚"""
        cur = getattr(self._tls, "con", None)
        if (
            cur is not None
        ):  # 同一个线程里套着用（一笔操作里又查一次）：用同一个连接、同一个事务
            yield cur
            return
        with self.lock:
            con = sqlite3.connect(self.path, timeout=15, isolation_level=None)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA foreign_keys=ON")
            try:
                con.execute("BEGIN IMMEDIATE")
                self._tls.con = con
                try:
                    yield con
                except BaseException:
                    con.execute("ROLLBACK")
                    raise
                finally:
                    self._tls.con = None
                con.execute("COMMIT")
            finally:
                con.close()

    @staticmethod
    def _validate(path: Path):
        try:
            with closing(
                sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True)
            ) as c:
                if c.execute("PRAGMA application_id").fetchone()[0] != APP_ID:
                    raise ValueError("不是交易助手数据库")
                if c.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                    raise ValueError("不支持该数据库版本")
                if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("数据库完整性检查失败")
                actual = _schema_signature(c)
                if any(
                    name in actual and actual[name] != signature
                    for name, signature in EXPECTED_SCHEMA.items()
                ) or not all(
                    n in actual for n in ("items", "stocks", "batches", "movements")
                ):
                    raise ValueError("数据库表结构或约束与当前版本不符")
                if c.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise ValueError("数据库包含无效物品关联")
        except (sqlite3.Error, OSError) as e:
            raise ValueError("无法读取有效数据库") from e

    def backup_to(self, dest):
        """整个库存文件备份到 dest。用另开的连接读：拿着写锁的事务里直接 backup 会自己等自己（还没提交的改动不在备份里）"""
        with (
            closing(sqlite3.connect(self.path, timeout=15)) as src,
            closing(sqlite3.connect(dest)) as dst,
        ):
            src.backup(dst)

    def get(self, key: str, default=None):
        with self.connection() as c:
            row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set(self, key: str, value) -> None:
        with self.connection() as c:
            c.execute(
                "INSERT OR REPLACE INTO settings VALUES (?,?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )


def import_v1(old_path, db):
    """把旧库存文件（版本 1，inventory.db）的数据导进新库（只读打开旧文件，旧文件不动）。
    旧文件可能是不同年代的：没有 batch_notes / batch_devices / item_keys 的就跳过那部分。
    新库已经有库存记录时不导（只在第一次）。返回 {表: 行数}；出错抛异常，这次导的全部回滚"""
    old_path = Path(old_path)
    if not old_path.exists():
        return {}
    uri = old_path.absolute().as_uri() + "?mode=ro"
    # 连接本身要用 uri=True 打开，ATTACH 才认 file:…?mode=ro（Linux 上默认认，Windows 上不认）
    with (
        db.lock,
        closing(
            sqlite3.connect(
                Path(db.path).absolute().as_uri(),
                timeout=15,
                isolation_level=None,
                uri=True,
            )
        ) as c,
    ):
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("ATTACH DATABASE ? AS old", (uri,))  # ATTACH 不能在事务里做
        c.execute("BEGIN IMMEDIATE")
        try:
            if (
                c.execute("SELECT 1 FROM main.batches LIMIT 1").fetchone()
                or c.execute("SELECT 1 FROM main.stocks LIMIT 1").fetchone()
            ):
                c.execute("ROLLBACK")
                return {}
            have = {
                r[0]
                for r in c.execute(
                    "SELECT name FROM old.sqlite_master WHERE type='table'"
                )
            }
            notes, devs = "batch_notes" in have, "batch_devices" in have
            out = {}
            sqls = [
                (
                    "items",
                    "INSERT OR IGNORE INTO main.items(id,name,uuid) SELECT id,name,uuid FROM old.items",
                ),
                (
                    "aliases",
                    "INSERT OR IGNORE INTO main.aliases SELECT item_id,alias FROM old.aliases WHERE item_id IN (SELECT id FROM main.items)",
                ),
                (
                    "source_ids",
                    "INSERT OR IGNORE INTO main.source_ids SELECT source,external_id,item_id FROM old.source_ids "
                    "WHERE item_id IN (SELECT id FROM main.items)",
                ),
                (
                    "settings",
                    "INSERT OR REPLACE INTO main.settings SELECT key,value FROM old.settings",
                ),
                (
                    "snapshots",
                    "INSERT OR IGNORE INTO main.snapshots SELECT * FROM old.snapshots",
                ),
                (
                    "provider_cache",
                    "INSERT OR IGNORE INTO main.provider_cache SELECT * FROM old.provider_cache",
                ),
                (
                    "stocks",
                    f"INSERT INTO main.stocks SELECT '{PERSONAL}',item_id,quality,location,unit,quantity FROM old.stocks "
                    "WHERE quantity>0 AND item_id IN (SELECT id FROM main.items)",
                ),
                (
                    "batches",
                    "INSERT INTO main.batches(id,workspace_id,at,mode,image_hash,undone,device,device_name,note,reason,source,undo_of) "
                    f"SELECT b.id,'{PERSONAL}',b.at,b.mode,b.image_hash,b.undone,"
                    + (
                        "coalesce(d.device,''),coalesce(d.name,''),"
                        if devs
                        else "'','',"
                    )
                    + (
                        "coalesce(n.note,''),coalesce(n.reason,''),coalesce(n.source,''),"
                        if notes
                        else "'','','',"
                    )
                    + "CASE WHEN b.mode LIKE 'undo:%' THEN substr(b.mode,6) END FROM old.batches b "
                    + (
                        "LEFT JOIN old.batch_devices d ON d.batch_id=b.id "
                        if devs
                        else ""
                    )
                    + (
                        "LEFT JOIN old.batch_notes n ON n.batch_id=b.id"
                        if notes
                        else ""
                    ),
                ),
                (
                    "movements",
                    "INSERT INTO main.movements(id,batch_id,workspace_id,item_id,quality,location,unit,delta,before_qty,after_qty) "
                    f"SELECT id,batch_id,'{PERSONAL}',item_id,quality,location,unit,delta,before_qty,after_qty FROM old.movements "
                    "WHERE batch_id IN (SELECT id FROM main.batches)",
                ),
            ]
            for name, sql in sqls:
                out[name] = c.execute(sql).rowcount
            if "item_keys" in have:
                c.execute(
                    "UPDATE main.items SET cls=(SELECT k.cls FROM old.item_keys k WHERE k.item_id=items.id), "
                    "game_uuid=(SELECT nullif(k.uuid,'') FROM old.item_keys k WHERE k.item_id=items.id) "
                    "WHERE id IN (SELECT item_id FROM old.item_keys)"
                )
            c.execute("COMMIT")
            return out
        except BaseException:
            c.execute("ROLLBACK")
            raise
