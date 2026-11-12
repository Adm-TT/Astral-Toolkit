"""系统 Controller（2026-10-30 重构阶段 4）

运行状态、设置、在线更新与回滚、日志导出、问题反馈、关于页、窗口显示与退出的接口：
收关键字参数，原样转给 tasks/system.py 里同名函数。只做转发，不加校验（校验留在 tasks 里，改行为要 NGU 定）。
runtime_capture_now、runtime_clear_logs（实时监控页的手动截图、清日志）例外：实现直接写在本文件。
运行状态、问题反馈、改设置、同意协议要这个 app 的状态源（同意协议还要启动回调）：bound(sources, start) 给，bootstrap.routes 接（F 段 B5）
router 自动收集文件末尾的 ROUTES。
"""

from ...tasks import system as _t
from .. import bus, preview


def upgrade_check(**kw):
    return _t.upgrade_check(**kw)


def upgrade_online(**kw):
    return _t.upgrade_online(**kw)


def upgrade_rollback(**kw):
    return _t.upgrade_rollback(**kw)


def export_logs(**kw):
    return _t.export_logs(**kw)


def feedback_list(**kw):
    return _t.feedback_list(**kw)


def feedback_export(**kw):
    return _t.feedback_export(**kw)


def feedback_clear(**kw):
    return _t.feedback_clear(**kw)


def update_data(**kw):
    return _t.update_data(**kw)


def about_info(**kw):
    return _t.about_info(**kw)


def open_source_site(**kw):
    return _t.open_source_site(**kw)


def third_party_licenses(**kw):
    return _t.third_party_licenses(**kw)


def open_referral(**kw):
    return _t.open_referral(**kw)


def show(**kw):
    return _t.show(**kw)


def quit(**kw):
    return _t.quit(**kw)


def runtime_capture_now():
    """手动立即截取一帧画面，更新实时监控"""
    from ...infrastructure.platform.capture import grab_screen

    img = grab_screen()
    preview.update_preview(img, source="manual", force=True)
    bus.runtime_log("手动截取屏幕画面", tag="SCREEN", level="INFO")
    _, meta = preview.get_preview_bytes(full=False)
    return meta


def runtime_clear_logs():
    """清空前端实时运行日志"""
    bus.clear_runtime_logs()
    return {"ok": True}


def bound(sources, start):
    """要运行状态源 / 后台启动回调的接口（F 段 B5）：bootstrap.routes 把这个 app 的 status_sources(app)
    和启动回调交进来，接口直接拿着，不经 tasks 模块级绑定"""

    def status(**kw):
        return _t.status(sources, **kw)

    def feedback_report(**kw):
        return _t.feedback_report(sources, **kw)

    def set_settings(**kw):
        return _t.set_settings(sources, **kw)

    def agree(**kw):
        return _t.agree(sources, start, **kw)

    return {
        "status": status,
        "feedback_report": feedback_report,
        "set_settings": set_settings,
        "agree": agree,
    }


ROUTES = {
    "upgrade_check": upgrade_check,
    "upgrade_online": upgrade_online,
    "upgrade_rollback": upgrade_rollback,
    "export_logs": export_logs,
    "feedback_list": feedback_list,
    "feedback_export": feedback_export,
    "feedback_clear": feedback_clear,
    "update_data": update_data,
    "about_info": about_info,
    "open_source_site": open_source_site,
    "third_party_licenses": third_party_licenses,
    "open_referral": open_referral,
    "show": show,
    "quit": quit,
    "runtime_capture_now": runtime_capture_now,
    "runtime_clear_logs": runtime_clear_logs,
}
