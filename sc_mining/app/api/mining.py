"""采矿 Controller（2026-10-30 重构阶段 3，NGU 设计 4.4 节）

采矿助手启停、扫描面板、激光头配置、手动输入扫描数据。
每个接口只是薄转发：收关键字参数、调 tasks/mining.py 里同名函数、原样返回；校验照旧留在 tasks。
"""
from ...tasks import mining as _t


def scan_view(**kw):
    return _t.scan_view(**kw)


def live_start(**kw):
    return _t.live_start(**kw)


def live_stop(**kw):
    return _t.live_stop(**kw)


def mining_gear(**kw):
    return _t.mining_gear(**kw)


def set_mining_gear(**kw):
    return _t.set_mining_gear(**kw)


def manual_scan(**kw):
    return _t.manual_scan(**kw)


ROUTES = {
    "scan_view": scan_view,
    "live_start": live_start,
    "live_stop": live_stop,
    "mining_gear": mining_gear,
    "set_mining_gear": set_mining_gear,
    "manual_scan": manual_scan,
}
