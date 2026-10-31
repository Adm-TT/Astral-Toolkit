"""基础 HUD 与按键状态（从 services.py 原样搬来，2026-10-30 重构阶段 0，逻辑没改）

悬浮窗短提示、物品分区自动收起、功能远程关闭提示、读鼠标位置和按键。
tasks 和引擎直接用这里的（阶段 4 删了 services.py，原来经 services 转的 _note_hud 等名字都在这里）。
"""
import math
import threading
import time


def _hud():
    try:
        from .overlay import hud
        return hud()
    except Exception:
        return None


_ITEM_SEQ = [0]
ITEM_HUD_SECONDS = 60
_OFF_TOLD = set()


def _off(feature):
    """这个功能有没有被远程关掉（latest.json 的 disabled，update_check.disabled）"""
    try:
        from ..update import update_check
        why = update_check.disabled(feature)
    except Exception:
        return None
    if why and feature not in _OFF_TOLD:
        _OFF_TOLD.add(feature)
        try:
            _note_hud("AT", f"{update_check.FEATURES.get(feature, feature)}暂时关闭：{why}", 8)
        except Exception:
            pass
    return why


def _note_hud(section, text, secs=6):
    """悬浮窗上一条短提示，secs 秒后自己收起"""
    h = _hud()
    if not h:
        return
    if hasattr(h, "note"):
        h.note(text, secs)
        return
    h.set(section, text)

    def gone():
        if getattr(_hud(), "sections", {}).get(section) == text:
            _hud().clear(section)
    t = threading.Timer(secs, gone)
    t.daemon = True
    t.start()


ITEM_AWAY_PX = 160
ITEM_AWAY_AFTER = 1.5
_ITEM_MODE = {"pinned": False, "origin": None, "shown_at": 0.0}


def _cursor():
    try:
        import ctypes
        from ctypes import wintypes
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y
    except Exception:
        return None


def _key_down(vk):
    try:
        import ctypes
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
    except Exception:
        return False


def item_key_pressed():
    """按下物品识别键那一刻：记下鼠标位置与 Shift 状态"""
    _ITEM_MODE.update(pinned=_key_down(0x10), origin=_cursor(), shown_at=time.time())


def _item_hud(text, secs=ITEM_HUD_SECONDS):
    """悬浮窗「物品」分区：鼠标移开自动收起（按住 Ctrl 不收，Shift+F8 钉住）"""
    h = _hud()
    if not h:
        return
    _ITEM_SEQ[0] += 1
    my = _ITEM_SEQ[0]
    h.set("物品", text)
    _ITEM_MODE["shown_at"] = time.time()
    if _ITEM_MODE["pinned"]:
        return

    def watch():
        import ctypes
        try:
            h_px = ctypes.windll.user32.GetSystemMetrics(1) or 1080
        except Exception:
            h_px = 1080
        away = ITEM_AWAY_PX * max(1.0, h_px / 1080)
        end = time.time() + secs
        while _ITEM_SEQ[0] == my and time.time() < end:
            time.sleep(0.1)
            o, c = _ITEM_MODE["origin"], _cursor()
            if (o and c and time.time() - _ITEM_MODE["shown_at"] >= ITEM_AWAY_AFTER and not _key_down(0x11)
                    and math.dist(o, c) > away):
                break
            if _key_down(0x11):
                end = max(end, time.time() + 1)
        if _ITEM_SEQ[0] == my:
            h_cur = _hud()
            if h_cur:
                h_cur.clear("物品")
    threading.Thread(target=watch, daemon=True, name="item-hud").start()
