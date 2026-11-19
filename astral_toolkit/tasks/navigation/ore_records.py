"""原矿记录：记、列、删、恢复、导航回去（2026-11-19 从 tasks/navigation.py 按段落拆出来，只搬位置、代码没改）"""

from ...runtime.results import MINING_SCAN
from ...app.hud_state import _note_hud
from ...app import bus
from .base import NavDeps
from .search import _rt_b6_closing_error, nav_start
from .marks import _hints_near, _on_body, _save_here, _wait_showloc, waypoints


# ---------------------------------------------------------------- 原矿记录
def _coord_desc(deps: NavDeps, g):
    """/showlocation 坐标 → 「戴玛，海拔 1,234 m」这种说明（只说明，不记路标）"""
    from ...navigation import navigate as n

    data = n.load()
    here = n.locate(g, data=data, use_offset=False)
    if _on_body(here):
        return n.body_label(here["body"]) + (
            f"，海拔 {here['height_m']:,.0f} m" if n.height_ok(here) else ""
        )
    return n.body_label("@" + n.system_of(g, data, **_hints_near(deps, g)))


def ore_record(deps: NavDeps, /, here=False):
    """记下最近这块矿。here=True（游戏里按热键）：等玩家自己输 /showlocation，把坐标一起记下；窗口里点的不记坐标"""
    from ...mining import ore_log

    results = deps.results
    entry = results.get(MINING_SCAN)
    view = entry.value if entry else None
    if not view:
        _note_hud("原矿", "暂无扫描结果，先扫描矿石", 5)
        return {"error": "暂无扫描结果，先在游戏中扫描矿石"}
    rec = ore_log.from_view(view)
    where = ""
    if here:
        try:
            g, why = _wait_showloc()
        except Exception as e:
            g, why = None, str(e)
        if g:
            rec["coords"] = [round(v, 1) for v in g]
            try:
                rec["where"] = where = _coord_desc(deps, g)
            except Exception:
                rec["where"] = ""
            try:  # 星系现在就定下（「去这里」可能是换了星系以后才点）
                from ...navigation import navigate as n

                rec["system"] = n.system_of(g, None, **_hints_near(deps, g))
            except Exception:
                pass
        else:
            rec["where_err"] = why or "未获取到坐标"
    try:
        rec = ore_log.add(rec)
    except Exception as e:
        _note_hud("原矿", f"未记录：{e}", 8)
        return {"error": str(e)}
    _note_hud(
        "原矿",
        f"已记录：{rec['rock']}"
        + (f"｜{where}" if where else "｜未获取到坐标" if here else ""),
        5,
    )
    bus.publish("ore_log", {"changed": True})
    return rec


def ore_list():
    from ...mining import ore_log

    rows = list(reversed(ore_log.load()))
    return {"rows": rows, "rocks": sorted({r.get("rock") or "?" for r in rows})}


def ore_delete(id=""):
    from ...mining import ore_log

    rec = ore_log.delete(id)
    if not rec:
        return {"error": "此记录已不存在"}
    bus.publish("ore_log", {"changed": True})
    return rec


def ore_restore(rec=None):
    from ...mining import ore_log

    rec = ore_log.restore(rec)
    bus.publish("ore_log", {"changed": True})
    return rec


def ore_go(deps: NavDeps, /, id=""):
    refused = _rt_b6_closing_error()
    if refused:
        return refused
    """「去这里」：把这条记录的坐标记成路标（同一条只记一次），然后开始导航"""
    from ...mining import ore_log

    rec = next((r for r in ore_log.load() if r.get("id") == id), None)
    if not rec:
        return {"error": "此记录已不存在"}
    if not rec.get("coords"):
        return {"error": "此记录没有坐标"}
    name = rec.get("waypoint")
    rows = {w["name"]: w for w in waypoints()}
    if not name or name not in rows:
        name = f"原矿 {rec.get('rock') or ''} {(rec.get('at') or '')[5:16]}".strip()
        if (
            name in rows
        ):  # 同一分钟记了两块同种矿：同名会覆盖别的记录的路标（审查 2026-10-31）
            name = f"{name} #{(rec.get('id') or '')[:4]}"
        _save_here(deps, name, tuple(rec["coords"]), system=rec.get("system"))
        ore_log.update(id, waypoint=name)
        bus.publish("waypoints", {"changed": True})
        rows = {w["name"]: w for w in waypoints()}
    w = rows.get(name)
    if not w:
        return {"error": "路标保存失败，详情见导航页"}
    r = nav_start(deps, w["key"])
    if r.get("error"):
        return r
    return {"ok": True, "name": name}
