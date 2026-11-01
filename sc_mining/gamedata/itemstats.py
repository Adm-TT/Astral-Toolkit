"""物品属性 topic：item_stats 表（item_stats.json：成品基础数值，按实体 uuid）、ship_stock_items 表（ship_items.json：部件 → 自带它出厂的船）

item(uuid) 单条查询，不整表常驻；属性段 s 整段存 JSON，还原成与源同形的 dict。传 snap 时用调用方的快照，不传就自己开一个。"""

import json

from ._cache import VersionCache
from ._ready import use

_COLS = "n, size, grade, cls, type, sub, mass, ver, mfr, cn, stats_json"


def item(uuid: str, snap=None) -> dict | None:
    """一件成品的数据（与 item_stats.json 的 items[uuid] 同形，键顺序同 build_item_stats 的输出）；没有 → None"""
    with use(snap) as s:
        rows = s.execute(f"select {_COLS} from item_stats where uuid = ?", (uuid,))
    if not rows:
        return None
    n, size, grade, cls, typ, sub, mass, ver, mfr, cn, stats = rows[0]
    return {
        "n": n,
        "size": size,
        "grade": grade,
        "cls": cls,
        "type": typ,
        "sub": sub,
        "mass": mass,
        "ver": ver,
        "mfr": mfr,
        "cn": cn,
        "s": json.loads(stats),
    }


def version(snap=None) -> str:
    """item_stats.json 的 version；没有 → ''"""
    with use(snap) as s:
        rows = s.execute("select value from meta where key = 'item_stats_version'")
    return rows[0][0] if rows else ""


_ships: VersionCache[dict] = VersionCache()


def _load_ships(s) -> dict:
    """部件名折叠键（crafting.acquire._ship_fold）→ 船名列表；折叠后撞名的后出现的赢（同原来的 dict 推导式）"""
    from ..crafting.acquire import _ship_fold

    raw: dict[str, list[str]] = {}
    for name, ship in s.execute(
        "select item_name, ship from ship_stock_items order by rowid"
    ):
        raw.setdefault(name, []).append(ship)
    return {_ship_fold(k): v for k, v in raw.items()}


def ships_with(key: str, snap=None) -> list[str]:
    """key 是已经折叠的部件名；返回新列表（调用方改了不影响缓存）；没有 → []"""
    with use(snap) as s:
        return list(_ships.get(s, _load_ships).get(key) or [])
