"""系统设置修改、热键防冲突校验、悬浮窗位置拖拽与进程控制"""

import re

from ...app import bus, task_runner
from .common import StatusSources, _hud

# 游戏里的热键：(设置名, 默认键, 名字)。撞键时排在前面的生效（物品识别 > 记录路标 > 一键定位 > 问题反馈 > 采矿助手 > 盘点 > 原矿记录）；导航「一键定位」的冲突提示也用这一份
HOTKEYS = [
    ("trade_capture_key", "F8", "物品识别"),
    ("mark_key", "", "记录路标"),
    ("fix_key", "", "一键定位"),
    ("report_key", "F10", "问题反馈"),
    ("live_key", "F5", "采矿助手开关"),
    ("count_key", "F6", "盘点"),
    ("ore_key", "", "原矿记录"),
]


def _hotkey_values(cfg):
    """→ [(键, 名字, 设置名)]，按生效顺序；没设的键是空字符串"""
    # 设成空 = 不绑（不回到默认键）
    return [(str(cfg.get(n, d) or "").strip().upper(), lab, n) for n, d, lab in HOTKEYS]


def hotkey_conflicts(cfg=None):
    """热键撞了（settings.json 手改的、旧版本留下的）：只有排在前面的生效，要明确告诉玩家哪个失效"""
    if cfg is None:
        try:
            from ...core import settings

            cfg = settings.load()
        except Exception:
            cfg = {}
    out, seen = [], {}
    for key, lab, name in _hotkey_values(cfg):
        if not key:
            continue
        if key in seen:
            tail = "，或在聊天框输入 /showlocation" if name == "fix_key" else ""
            out.append(
                f"{key} 同时用于「{seen[key]}」和「{lab}」，按下只执行「{seen[key]}」：需在设置页更换「{lab}」的按键{tail}"
            )
        else:
            seen[key] = lab
    return out


def overlay_move(on=False):
    """「移动悬浮窗」：打开时悬浮窗能拖动（不穿透），关上恢复鼠标穿透"""
    h = _hud()
    if h and hasattr(h, "set_movable"):
        h.set_movable(bool(on))
    return {"on": bool(on)}


def set_settings(sources: StatusSources, /, **kw):
    from ...core import settings
    from .status import status

    allowed = {"admin", "hud_scale", "hud_plate", "hud_theme"} | {
        k for k, _, _ in HOTKEYS
    }
    if "stock_mode" in kw and kw["stock_mode"] not in ("simple", "pro"):
        kw.pop("stock_mode")
    allowed.add("stock_mode")
    if "theme" in kw and kw["theme"] not in ("dark", "light"):
        kw.pop("theme")
    allowed.add("theme")
    for k in (
        "ata",
        "update_online",
        "feedback_upload",
        "train_upload",
        "always_use_gpu",
        "debug_mode",
    ):
        if k in kw:
            kw[k] = bool(kw[k])
        allowed.add(k)
    if "ocr_device" in kw:
        allowed.add("ocr_device")
        kw["ocr_device"] = str(kw["ocr_device"]).lower()
    # 导航帧数：取整、限在 5–30（设置页只给五档，直接调接口也不越界）
    if "nav_fps" in kw:
        kw["nav_fps"] = settings.nav_fps(kw["nav_fps"])
    allowed.add("nav_fps")
    clear_train = (
        kw.get("train_upload") is False
    )  # 关掉「帮助改进识别」：先存「关」，再删本地攒着没发的
    if "hud_scale" in kw:
        kw["hud_scale"] = min(1.0, max(0.5, float(kw["hud_scale"])))
    if "hud_plate" in kw:
        kw["hud_plate"] = min(1.0, max(0.3, float(kw["hud_plate"])))
    if "hud_theme" in kw and kw["hud_theme"] not in ("默认", "蓝金", "浅色"):
        kw["hud_theme"] = "默认"
    cur = None
    for name, default, label in HOTKEYS:  # 所有热键都能在设置页改
        if name not in kw:
            continue
        k = str(kw[name] or "").strip().upper()
        if not k and not default:  # 原矿记录这种默认不设的可以清掉
            kw[name] = ""
            continue
        if not re.fullmatch(r"F([1-9]|1[0-2])", k):
            return {"error": "热键仅支持 F1–F12"}
        if cur is None:
            # 设置文件暂时读不到时拿到的只是默认值：拿它查撞键会误报「已用于…」，直接说没存上
            try:
                cur = settings.load_checked()
            except settings.NotSaved as e:
                return {"error": str(e)}
        taken = {key: lab for key, lab, n in _hotkey_values(cur) if n != name and key}
        if k in taken:
            return {"error": f"{k} 已用于「{taken[k]}」，需更换按键"}
        kw[name] = k
    try:
        cfg = settings.update_checked(**{k: v for k, v in kw.items() if k in allowed})
    except OSError as e:  # 没存上：告诉玩家再点一次，别装作存好了（后面跟着改的悬浮窗、识别设备也不动）
        if isinstance(e, settings.NotSaved):
            return {"error": str(e)}
        return {
            "error": "设置文件写不进去（可能被杀毒或同步软件占着），这次没存上，再点一次"
        }
    if clear_train:
        try:
            from ...system import train_data

            train_data.clear()
        except Exception:
            pass
    # 导航帧数变了，悬浮窗也马上按新帧数刷记号
    if any(k in kw for k in ("hud_theme", "hud_plate", "hud_scale", "nav_fps")):
        try:
            h = _hud()
            if h and hasattr(h, "restyle"):
                h.restyle()
        except Exception:
            pass
    if "ocr_device" in kw or "always_use_gpu" in kw:
        target = kw.get("ocr_device")
        if target is None and "always_use_gpu" in kw:
            target = "gpu" if kw["always_use_gpu"] else "cpu"
        if target:
            try:
                from ...ocr import set_ocr_device

                set_ocr_device(target)
            except Exception:
                pass
    bus.publish("status", status(sources))
    return cfg


def update_data():
    from ...run import update

    if (
        task_runner.run_task_once("update", update, title="更新数据") is None
    ):  # 已经在更新：不再起第二份
        return {"started": False, "running": True}
    return {"started": True}


def show():
    """又双击了一次 AT（安装版 AT.exe、源码版 Dubhe.exe）：后台开着的 AT 把窗口打开"""
    from ...app.server import show_window

    show_window()
    return {"ok": True}


def quit():
    """又双击了一次 AT（安装版 AT.exe、源码版 Dubhe.exe）：旧的这个退出，让新的接手"""
    from ...app.server import QUIT

    QUIT.set()
    return {"ok": True}
