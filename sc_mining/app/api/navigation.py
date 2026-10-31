"""导航 Controller（2026-10-30 重构阶段 2）

地点搜索、路线规划、导航开关、路标、原矿记录、小行星带航线的接口：收关键字参数，原样转给 tasks/navigation.py 里同名函数。
只做转发，不加校验（校验留在 tasks 里，改行为要 NGU 定）。router 自动收集文件末尾的 ROUTES。
"""
from ...tasks import navigation as _t


def nav_search(**kw):
    return _t.nav_search(**kw)


def nav_near(**kw):
    return _t.nav_near(**kw)


def nav_site(**kw):
    return _t.nav_site(**kw)


def nav_plan(**kw):
    return _t.nav_plan(**kw)


def nav_start(**kw):
    return _t.nav_start(**kw)


def nav_mode(**kw):
    return _t.nav_mode(**kw)


def sig_name(**kw):
    return _t.sig_name(**kw)


def sig_names(**kw):
    return _t.sig_names(**kw)


def nav_stop(**kw):
    return _t.nav_stop(**kw)


def nav_refresh(**kw):
    return _t.nav_refresh(**kw)


def waypoints(**kw):
    return _t.waypoints(**kw)


def waypoint_add(**kw):
    return _t.waypoint_add(**kw)


def waypoint_preview(**kw):
    return _t.waypoint_preview(**kw)


def waypoint_from_text(**kw):
    return _t.waypoint_from_text(**kw)


def waypoint_delete(**kw):
    return _t.waypoint_delete(**kw)


def ore_record(**kw):
    return _t.ore_record(**kw)


def ore_list(**kw):
    return _t.ore_list(**kw)


def ore_delete(**kw):
    return _t.ore_delete(**kw)


def ore_restore(**kw):
    return _t.ore_restore(**kw)


def ore_go(**kw):
    return _t.ore_go(**kw)


def halo_options(**kw):
    return _t.halo_options(**kw)


def halo_routes(**kw):
    return _t.halo_routes(**kw)


def halo_pin(**kw):
    return _t.halo_pin(**kw)


def halo_unpin(**kw):
    return _t.halo_unpin(**kw)


ROUTES = {
    "nav_search": nav_search,
    "nav_near": nav_near,
    "nav_site": nav_site,
    "nav_plan": nav_plan,
    "nav_start": nav_start,
    "nav_mode": nav_mode,
    "sig_name": sig_name,
    "sig_names": sig_names,
    "nav_stop": nav_stop,
    "nav_refresh": nav_refresh,
    "waypoints": waypoints,
    "waypoint_add": waypoint_add,
    "waypoint_preview": waypoint_preview,
    "waypoint_from_text": waypoint_from_text,
    "waypoint_delete": waypoint_delete,
    "ore_record": ore_record,
    "ore_list": ore_list,
    "ore_delete": ore_delete,
    "ore_restore": ore_restore,
    "ore_go": ore_go,
    "halo_options": halo_options,
    "halo_routes": halo_routes,
    "halo_pin": halo_pin,
    "halo_unpin": halo_unpin,
}
