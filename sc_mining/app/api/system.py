"""系统 Controller（2026-10-30 重构阶段 4）

运行状态、设置、在线更新与回滚、旧版迁移、日志导出、问题反馈、关于页、窗口显示与退出的接口：
收关键字参数，原样转给 tasks/system.py 里同名函数。只做转发，不加校验（校验留在 tasks 里，改行为要 NGU 定）。
runtime_capture_now、runtime_clear_logs（实时监控页的手动截图、清日志）原来写在 services.py，原样挪到这里。
router 自动收集文件末尾的 ROUTES。
"""
from ...tasks import system as _t
from .. import bus


def status(**kw):
    return _t.status(**kw)


def upgrade_check(**kw):
    return _t.upgrade_check(**kw)


def upgrade_online(**kw):
    return _t.upgrade_online(**kw)


def upgrade_rollback(**kw):
    return _t.upgrade_rollback(**kw)


def upgrade_mark_stable(**kw):
    return _t.upgrade_mark_stable(**kw)


def legacy_scan(**kw):
    return _t.legacy_scan(**kw)


def legacy_import(**kw):
    return _t.legacy_import(**kw)


def legacy_skip(**kw):
    return _t.legacy_skip(**kw)


def legacy_quit(**kw):
    return _t.legacy_quit(**kw)


def upgrade_apply(**kw):
    return _t.upgrade_apply(**kw)


def upgrade_upload(**kw):
    return _t.upgrade_upload(**kw)


def upgraded(**kw):
    return _t.upgraded(**kw)


def export_logs(**kw):
    return _t.export_logs(**kw)


def feedback_report(**kw):
    return _t.feedback_report(**kw)


def feedback_list(**kw):
    return _t.feedback_list(**kw)


def feedback_export(**kw):
    return _t.feedback_export(**kw)


def feedback_clear(**kw):
    return _t.feedback_clear(**kw)


def overlay_move(**kw):
    return _t.overlay_move(**kw)


def set_settings(**kw):
    return _t.set_settings(**kw)


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


def agree(**kw):
    return _t.agree(**kw)


def show(**kw):
    return _t.show(**kw)


def quit(**kw):
    return _t.quit(**kw)


def runtime_capture_now():
    """手动立即截取一帧画面，更新实时监控"""
    from ...core.perf import grab_screen
    img = grab_screen()
    bus.update_preview(img, source="manual", force=True)
    bus.runtime_log("手动截取屏幕画面", tag="SCREEN", level="INFO")
    _, meta = bus.get_preview_bytes(full=False)
    return meta


def runtime_clear_logs():
    """清空前端实时运行日志"""
    bus.clear_runtime_logs()
    return {"ok": True}


ROUTES = {
    "status": status,
    "upgrade_check": upgrade_check,
    "upgrade_online": upgrade_online,
    "upgrade_rollback": upgrade_rollback,
    "upgrade_mark_stable": upgrade_mark_stable,
    "legacy_scan": legacy_scan,
    "legacy_import": legacy_import,
    "legacy_skip": legacy_skip,
    "legacy_quit": legacy_quit,
    "upgrade_apply": upgrade_apply,
    "upgrade_upload": upgrade_upload,
    "upgraded": upgraded,
    "export_logs": export_logs,
    "feedback_report": feedback_report,
    "feedback_list": feedback_list,
    "feedback_export": feedback_export,
    "feedback_clear": feedback_clear,
    "overlay_move": overlay_move,
    "set_settings": set_settings,
    "update_data": update_data,
    "about_info": about_info,
    "open_source_site": open_source_site,
    "third_party_licenses": third_party_licenses,
    "open_referral": open_referral,
    "agree": agree,
    "show": show,
    "quit": quit,
    "runtime_capture_now": runtime_capture_now,
    "runtime_clear_logs": runtime_clear_logs,
}
