"""星图 topic：bodies / pois / points 三张表（starmap.json 已套 starmap_fixes.json）

坐标单位同源文件：bodies、points 是星系坐标（米），pois 是天体局部坐标（千米）。
同一内部名 / 规范化名字可能有好几个点（真实数据里 ab_pyro_final_set_dungeon-001 就有两个），按名字找点一律取源里第一个。"""

from typing import Any

from ._cache import VersionCache
from ._ready import use

_BODY_OPT = ("rot", "adj", "r", "om", "grid")
_POINT_COLS = "n, i, sys, t, x, y, z"


def _point(r: tuple) -> dict[str, Any]:
    return dict(zip(("n", "i", "sys", "t", "x", "y", "z"), r))


def _load_dict(s) -> dict[str, Any]:
    bodies: dict[str, dict[str, Any]] = {}
    for name, sys_, x, y, z, *opt in s.execute(
        f"select name, sys, x, y, z, {', '.join(_BODY_OPT)} from bodies order by source_order"
    ):
        b: dict[str, Any] = dict(sys=sys_, x=x, y=y, z=z)
        b.update((k, v) for k, v in zip(_BODY_OPT, opt) if v is not None)
        b["name"] = name  # 自转相位校准按名字存（rotation_deg 只拿到星球那个 dict）
        bodies[name] = b
    pois = [
        dict(b=b, n=n, t=t, x=x, y=y, z=z, qt=qt)
        for b, n, t, x, y, z, qt in s.execute(
            "select b, n, t, x, y, z, qt from pois order by source_order"
        )
    ]
    points = [
        _point(r)
        for r in s.execute(f"select {_POINT_COLS} from points order by source_order")
    ]
    out: dict[str, Any] = dict(bodies=bodies, pois=pois, points=points)
    got = s.execute("select value from meta where key = 'starmap_fetched'")
    if got:
        out["fetched"] = got[0][0]
    return out


_dict: VersionCache[dict[str, Any]] = VersionCache()


def data_dict(snap=None) -> dict[str, Any]:
    """组装成以前 navigation.starmap.load() 的那个 dict：{bodies: {名: {sys,x,y,z,rot,adj,r,om,grid,name}}, pois, points, fetched}。
    按内容版本缓存一份，同一版本返回同一个对象（和以前一样，调用方别改它）"""
    with use(snap) as s:
        return _dict.get(s, _load_dict)


def point_by_internal(internal: str, snap=None) -> dict[str, Any] | None:
    """内部名（不分大小写）→ 源里第一个这个内部名的点 {n,i,sys,t,x,y,z}；没有返回 None"""
    with use(snap) as s:
        rows = s.execute(
            f"select {_POINT_COLS} from points where i_lower = ? order by source_order limit 1",
            (internal.lower(),),
        )
    return _point(rows[0]) if rows else None


def point_by_name(norm: str, snap=None) -> dict[str, Any] | None:
    """规范化名字（小写去非字母数字，names._norm）→ 源里第一个这个名字的点；没有返回 None"""
    with use(snap) as s:
        rows = s.execute(
            f"select {_POINT_COLS} from points where norm_n = ? order by source_order limit 1",
            (norm,),
        )
    return _point(rows[0]) if rows else None
