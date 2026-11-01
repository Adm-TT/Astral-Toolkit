"""旧版本天枢（0.x 绿色压缩包版）扫描、数据迁移与清理"""

import threading
import time

_legacy = {"rows": None}


def legacy_scan():
    """安装版：电脑上的旧版天枢（压缩包版），以及哪些正开着。ask=True 表示还没问过要不要导入"""
    from ...core import settings
    from ...core.paths import FROZEN
    from ...update import legacy

    if not FROZEN:
        return {"found": [], "running": [], "ask": False}
    if _legacy["rows"] is None:
        try:
            _legacy["rows"] = legacy.find()
        except Exception:
            _legacy["rows"] = []
    rows = _legacy["rows"]
    try:
        run = legacy.running(rows)
    except Exception:
        run = []
    return {
        "found": rows,
        "running": run,
        "ask": bool(rows) and not settings.load().get("legacy_checked"),
    }


def legacy_import(path=""):
    """把旧版的设置、路标、目标等复制过来，然后重新打开 AT（热键、悬浮窗按新设置重新挂）"""
    from ...core import settings
    from ...update import legacy

    if path not in [r["path"] for r in (_legacy["rows"] or [])]:
        return {"error": "未找到这个旧版"}
    try:
        done = legacy.import_from(path)
    except Exception as e:
        return {"error": f"导入失败：{e}"}
    settings.update(legacy_checked=True)

    def later():
        time.sleep(1.5)
        from ...app.server import _relaunch

        _relaunch()

    threading.Thread(target=later, daemon=True).start()
    return {"done": done}


def legacy_skip():
    from ...core import settings

    settings.update(legacy_checked=True)
    return {"ok": True}


def legacy_quit(path=""):
    """关掉正在运行的旧版天枢（请它自己退出）"""
    from ...update import legacy

    if path not in [r["path"] for r in (_legacy["rows"] or [])]:
        return {"error": "未找到这个旧版"}
    try:
        legacy.quit_old(path)
    except Exception:
        return {"error": "旧版未响应：在屏幕右下角托盘右键旧版天枢图标，选「退出」"}
    return {"ok": True}
