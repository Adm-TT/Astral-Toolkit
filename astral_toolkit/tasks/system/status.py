"""系统运行状态探针、硬件环境监测与日志导出"""

import json
import platform
import sys
import time
import zipfile
from pathlib import Path

from .common import WIN, _engines


def status():
    from ...core import settings
    from ...mining.data import GAME_VERSION
    from ...system import showloc
    from .about import _data_versions, _version
    from .settings import hotkey_conflicts

    cfg = settings.load()
    m = _engines()

    live_running = m.live.running()
    live_paused = bool(live_running and m.live.paused)
    nav_label = m.nav.target_label()
    nav_space = m.nav.space_mode
    pos_reader_active = m.pos.reader.active
    game_events_dict = {k: v for k, (_, v) in list(m.game_events.last.items())}

    out = {
        "settings": cfg,
        "game_version": GAME_VERSION,
        "win": WIN,
        "admin": showloc.is_admin() if WIN else True,
        "game_elevated": bool(WIN and showloc.game_elevated()),
        "live": live_running,
        "live_paused": live_paused,
        "nav": nav_label,
        "nav_space": nav_space,
        "hover_key": cfg.get("trade_capture_key") or "F8",
        "hotkey_warn": hotkey_conflicts(cfg),
        "position": None,
        "data": _data_versions(),
        "displayinfo": pos_reader_active,
        "version": _version(),
        "game_size": None,
        "game_events": game_events_dict,
        "frozen": __import__("astral_toolkit.core.paths", fromlist=["FROZEN"]).FROZEN,
        "vpk": __import__("astral_toolkit.core.paths", fromlist=["VELOPACK"]).VELOPACK,
    }
    try:
        from ...ocr import gpu_available, last_ocr_error, ocr_device

        cur_dev = ocr_device()
        out["ocr_device"] = cur_dev
        out["gpu_available"] = gpu_available()
        out["ocr_mode"] = cfg.get("ocr_device", "gpu")
        out["ocr_error"] = last_ocr_error()
    except Exception:
        out["ocr_device"] = "CPU"
        out["gpu_available"] = False
        out["ocr_mode"] = "cpu"
        out["ocr_error"] = ""
    if WIN:
        from ...core.capture import game_size

        out["game_size"] = (
            game_size()
        )  # 游戏画面多大：低于 1080 高时页面上提醒识别会不准
    try:
        from ...navigation.position import current

        here = current()
        if here:
            out["position"] = {
                "label": here["label"],
                "minutes": int(here["age"] // 60),
                "sys": here["sys"],
            }
            from ...crafting.stockplaces import match

            p = match(
                here["label"], here["sys"]
            )  # 库存入库默认放这里（地点列表里的叫法）
            out["place"] = (
                {
                    "label": p["label"],
                    "path": p["path"],
                    "minutes": int(here["age"] // 60),
                }
                if p
                else None
            )
    except Exception:
        pass
    # 右上角读到的具体地点：记住最后一次读到的，切屏、某一次没认出来都不换（以前会在「附近」和站名之间来回闪）。
    # 只有游戏日志里有更新的地点（比如到别的站开了库存）才换掉它
    lab_t, lab = m.pos.label
    if lab and time.time() - lab_t < 3 * 3600:
        log_t = 0.0
        try:
            from ...navigation.position import from_log

            hit = from_log()
            log_t = hit[0] if hit else 0.0
        except Exception:
            pass
        if lab_t >= log_t:
            sys_t, sysname = m.pos.system
            out["position"] = {
                "label": lab,
                "minutes": int((time.time() - lab_t) // 60),
                "sys": sysname or (out["position"] or {}).get("sys", ""),
                "live": pos_reader_active and time.time() - lab_t < 15,
            }
    if out["position"] is not None:
        out["position"].setdefault("live", False)
    out["gridtext"] = _gridtext_status()
    return out


def _gridtext_status():
    try:
        from ...navigation import gridtext

        return gridtext.status()
    except Exception:
        return {}


def _desktop():
    """桌面文件夹（桌面被 OneDrive 搬走的也能找到）"""
    if WIN:
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(260)
            if (
                ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0
                and buf.value
            ):
                return Path(buf.value)
        except Exception:
            pass
    p = Path.home() / "Desktop"
    return p if p.exists() else Path.home()


def _system_info():
    """导出日志时附带的一页说明：版本、系统、屏幕、数据版本（不含任何个人数据）"""
    from ...core import paths
    from .about import _data_versions, _version

    lines = [
        f"AT 版本：{_version()}",
        f"导出时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Windows：{platform.platform()}",
        f"Python：{sys.version.split()[0]}",
    ]
    try:
        import ctypes

        u32 = ctypes.windll.user32
        lines.append(
            f"屏幕：{u32.GetSystemMetrics(0)} × {u32.GetSystemMetrics(1)}（缩放后）"
        )
    except Exception:
        pass
    try:
        from ...system import showloc

        lines.append(
            f"AT 管理员身份：{'是' if showloc.is_admin() else '否'}；游戏管理员身份：{'是' if showloc.game_elevated() else '否/未运行'}"
        )
    except Exception:
        pass
    try:
        from importlib.metadata import version as v

        def ver(n):
            try:
                return f"{n} {v(n)}"
            except Exception:
                return ""

        # onnxruntime 的显卡版包名是 onnxruntime-directml：哪个装了写哪个
        names = (
            "rapidocr_onnxruntime",
            "onnxruntime",
            "onnxruntime-directml",
            "numpy",
            "pillow",
            "mss",
        )
        lines.append("组件：" + "，".join(x for x in map(ver, names) if x))
        from ...ocr import ocr_device

        lines.append(f"文字识别用：{ocr_device()}")
    except Exception:
        pass
    lines.append("数据：" + json.dumps(_data_versions(), ensure_ascii=False))
    lines.append(
        f"安装位置里有中文：{'是' if any(ord(c) > 127 for c in str(paths.ROOT)) else '否'}"
    )
    return "\n".join(lines) + "\n"


def export_logs():
    """「导出日志」：运行日志 + 设置 + 一页系统说明打成一个压缩包，放到桌面，并在文件夹里选中它"""
    from ...core import paths

    out = _desktop() / time.strftime(
        "AT日志_%Y%m%d_%H%M%S.zip"
    )  # 精确到秒，不会盖掉同一分钟导出的另一份
    files = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        log_files = []
        if paths.LOGS.exists():
            log_files = sorted(
                set(paths.LOGS.glob("*.txt*")) | set(paths.LOGS.glob("runrec_*.log"))
            )  # 含轮换 .txt.old 与运行记录
        for p in log_files:
            z.write(p, f"logs/{p.name}")
            files += 1
        for name in ("settings.json", "goals.json"):
            p = paths.USER / name
            if p.exists():
                z.write(p, name)
                files += 1
        z.writestr("系统信息.txt", _system_info())
    if WIN:
        try:
            import subprocess

            subprocess.Popen(["explorer", "/select,", str(out)])
        except Exception:
            pass
    return {"path": str(out), "files": files, "kb": round(out.stat().st_size / 1024)}
