"""地点总表 topic（后端架构第 1 步，2026-11-13；方案 docs/superpowers/specs/2026-11-13-places-registry-visibility.md）：
place_registry 表（places.json，一行一个地点，pid 是固定编号）、place_navkeys（导航列表里的一条 → 编号）、
place_visible（place_visibility.json：对玩家可见的编号）。

全项目只有这里读「可见清单」。清单生效的条件：库里有总表（places.json）而且有清单文件；缺任何一个 = 不过滤、全部可见
（开发环境没有清单文件，就是这样）。清单是白名单：有清单时，对不上编号的、清单里没有的地点都不可见；路标不受限制。"""

import json
from typing import Any, Callable

from ._cache import VersionCache
from ._ready import use


def poi_key(b: Any, n: Any, x: Any, y: Any, z: Any) -> str:
    """星图地面点的 navkey：星球 + 英文名 + 坐标（千米，3 位小数）。建库和查询都用它"""
    try:
        return f"poi|{b}|{n}|{float(x):.3f}|{float(y):.3f}|{float(z):.3f}"
    except (TypeError, ValueError):
        return f"poi|{b}|{n}|||"


def navkey(p: dict[str, Any]) -> str | None:
    """导航列表里的一条（搜索 / 列表用的那种 dict）→ 查总表的键；路标返回 None（玩家自己的东西，不受可见清单限制）"""
    t = p.get("t")
    if t == "Waypoint":
        return None
    if t == "City":
        return f"ct|{p.get('id')}"
    if t == "Mining Spot":
        return f"ms|{p.get('sys')}|{p.get('n')}"
    if p.get("space"):
        return f"pt|{p.get('sys')}|{p.get('n')}"
    return poi_key(p.get("b"), p.get("n"), p.get("x"), p.get("y"), p.get("z"))


def _load(s) -> dict[str, Any]:
    meta = s.execute("select value from meta where key = 'place_visibility'")
    n = s.execute("select count(*) from place_registry")[0][0]
    active = bool(meta) and n > 0
    keys: dict[str, tuple[str, ...]] = {}
    visible: frozenset[str] = frozenset()
    if active:
        visible = frozenset(r[0] for r in s.execute("select pid from place_visible"))
        tmp: dict[str, list[str]] = {}
        for k, pid in s.execute("select navkey, pid from place_navkeys"):
            tmp.setdefault(k, []).append(pid)
        keys = {k: tuple(v) for k, v in tmp.items()}
    return {
        "active": active,
        "rows": n,
        "visible": visible,
        "keys": keys,
        "meta": json.loads(meta[0][0]) if meta else None,
    }


_state: VersionCache[dict[str, Any]] = VersionCache()


def state(snap=None) -> dict[str, Any]:
    """{"active": 清单生不生效, "rows": 总表行数, "visible": 可见编号, "keys": navkey → 编号, "meta": 清单版本和条数或 None}；
    按内容版本缓存一份（调用方别改它）"""
    with use(snap) as s:
        return _state.get(s, _load)


def checker(snap=None) -> Callable[[dict[str, Any]], bool]:
    """拿一个「这一条对玩家可不可见」的函数（一次列表 / 搜索拿一次，里面不再查库）。清单不生效时永远返回 True"""
    st = state(snap)
    if not st["active"]:
        return lambda p: True
    visible, keys = st["visible"], st["keys"]

    def shown(p: dict[str, Any]) -> bool:
        k = navkey(p)
        if k is None:
            return True
        return any(pid in visible for pid in keys.get(k, ()))

    return shown
