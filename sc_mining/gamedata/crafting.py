"""制造 topic：blueprints / blueprint_materials 两张表（crafting.json 的蓝图）

蓝图在消费方（目标清单、悬停、库存、采矿激光、读屏）都是当嵌套 dict 传来传去的，所以这里还原成与 crafting.json
逐字一致的 dict，缓存一份：crafting.json 和导入规则没变就一直是同一批对象（crafting.bp_key 靠 id(bp) 查编号，
目标清单等处还会长期拿着这些对象）。别的源文件更新（矿价、商店）换了库版本也不换蓝图对象；建的时候持锁，
两个线程同时第一次取也只建一份。
编号用导入时算好的 bp_key 列（规则在 crafting.assign_keys）。传 snap 时用调用方的快照，不传就自己开一个。"""

import json
import threading
from collections import Counter
from dataclasses import dataclass

from ._ready import use

_COLS = "id, u, n, z, g, t, s, m, sec, d, slots_json, src_json, nsrc, bp_key"


@dataclass(frozen=True)
class Blueprints:
    """一个内容版本的全部蓝图。data = {"blueprints": [bp…]}（和以前读 crafting.json 的形状一样，只带蓝图）；
    keys：id(bp) → 编号；index：编号 → bp；total：名字 → 份数；by_id：表里的 id → bp"""

    data: dict
    keys: dict
    index: dict
    total: Counter
    by_id: dict


_lock = threading.Lock()
_cur: tuple[tuple, Blueprints] | None = None  # (蓝图来源的版本键, 那一版的蓝图)


def _bp(r: tuple) -> dict:
    """一行 → 与源同形的蓝图 dict（键的顺序同 build_crafting 的输出）"""
    _id, u, n, z, g, t, s, m, sec, d, slots, src, nsrc, _key = r
    return {
        "n": n,
        "z": z,
        "g": g,
        "t": t,
        "s": s,
        "u": u,
        "m": m,
        "sec": sec,
        "d": bool(d),
        "slots": json.loads(slots),
        "src": json.loads(src),
        "nsrc": nsrc,
    }


def _load(s) -> Blueprints:
    bps, keys, index, by_id = [], {}, {}, {}
    for r in s.execute(f"select {_COLS} from blueprints order by source_order"):
        b = _bp(r)
        bps.append(b)
        keys[id(b)] = r[13]
        index[r[13]] = b
        by_id[r[0]] = b
    return Blueprints(
        {"blueprints": bps}, keys, index, Counter(b["n"] for b in bps), by_id
    )


def _source_key(s) -> tuple:
    """蓝图内容只由 crafting.json 和导入规则决定：库里记的 crafting.json 哈希 + schema / 导入规则 / 应用版本。
    id 是源下标，同一份源导入出来的 id 一样，所以沿用旧对象时 by_id 照样对得上。没记哈希就退回整库版本"""
    from ..core import version as _v

    m = dict(
        s.execute(
            "select key, value from meta where key in "
            "('src:crafting.json', 'schema_version', 'importer_version')"
        )
    )
    src = m.get("src:crafting.json")
    if not src:
        return ("data", s.data_version)
    return (src, m.get("schema_version"), m.get("importer_version"), _v.VERSION)


def catalog(snap=None) -> Blueprints:
    """全部蓝图（按源顺序）和编号表；蓝图来源没变就返回同一份"""
    global _cur
    with use(snap) as s:
        key = _source_key(s)
        with _lock:
            if _cur is None or _cur[0] != key:
                _cur = (key, _load(s))
            return _cur[1]


def _clear() -> None:
    """只给测试用：丢掉缓存的那份"""
    global _cur
    with _lock:
        _cur = None


def for_item(norm_en: str, norm_zh: str, snap=None) -> dict | None:
    """英文名比较键（crafting._fold_name）对上的第一份；没有再按中文名比较键找第一份。键是空串不比"""
    with use(snap) as s:
        c = catalog(s)
        for col, key in (("norm_n", norm_en), ("norm_z", norm_zh)):
            if not key:
                continue
            rows = s.execute(
                f"select id from blueprints where {col} = ? order by source_order limit 1",
                (key,),
            )
            if rows:
                return c.by_id[rows[0][0]]
    return None


def containing(q: str, snap=None) -> list[dict]:
    """英文名或中文名的搜索键（crafting._search_norm）里含 q 的蓝图，按源顺序；精确 / 包含的分法和排序由调用方做"""
    if not q:
        return []
    with use(snap) as s:
        c = catalog(s)
        return [
            c.by_id[i]
            for (i,) in s.execute(
                "select id from blueprints where instr(search_n, ?) > 0 or instr(search_z, ?) > 0 "
                "order by source_order",
                (q, q),
            )
        ]


def using_material(material: str, snap=None) -> list[dict]:
    """有槽用到这种原料（kind = r）的蓝图，按源顺序，每份一次"""
    with use(snap) as s:
        c = catalog(s)
        return [
            c.by_id[i]
            for (i,) in s.execute(
                "select distinct blueprint_id from blueprint_materials where material = ? and kind = 'r' "
                "order by blueprint_id",
                (material,),
            )
        ]
