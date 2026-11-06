"""采矿 Controller（2026-10-30 重构阶段 3，NGU 设计 4.4 节）

采矿助手启停、扫描面板、激光头配置、手动输入扫描数据。
启停和改配装要实时读屏：bound(live) 给，bootstrap.routes 接（F 段 B5）。
每个接口只是薄转发：收关键字参数、调 tasks/mining.py 里同名函数、原样返回；校验照旧留在 tasks。
"""

from ...tasks import mining as _t


def scan_view(**kw):
    return _t.scan_view(**kw)


def mining_gear(**kw):
    return _t.mining_gear(**kw)


def manual_scan(**kw):
    return _t.manual_scan(**kw)


def bound(live):
    """要实时读屏的接口（F 段 B5）：bootstrap.routes 把这个 app 的 live 交进来，接口直接拿着，不经 tasks 模块级绑定"""

    def live_start(**kw):
        from ..lifecycle_gate import closing_error

        refused = closing_error()
        if refused:
            return refused
        return _t.live_start(live, **kw)

    def live_stop(**kw):
        return _t.live_stop(live, **kw)

    def set_mining_gear(**kw):
        return _t.set_mining_gear(live, **kw)

    def set_mining_gadgets(**kw):
        return _t.set_mining_gadgets(live, **kw)

    return {
        "live_start": live_start,
        "live_stop": live_stop,
        "set_mining_gear": set_mining_gear,
        "set_mining_gadgets": set_mining_gadgets,
    }


ROUTES = {
    "scan_view": scan_view,
    "mining_gear": mining_gear,
    "manual_scan": manual_scan,
}
