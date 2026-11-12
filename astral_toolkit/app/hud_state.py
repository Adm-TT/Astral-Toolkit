"""基础 HUD 与按键状态

悬浮窗短提示、物品分区自动收起、读鼠标位置和按键。
tasks 和引擎直接用这里的 _note_hud 等名字。
读光标、读键由 bootstrap.bind_all 接进来（infrastructure/platform 的 cursor.pos、keys.down；目录迁移收尾，
以前这里自己调 Win32，和平台层是两份）；没接（测试、test 模式）就当不知道光标在哪、没按。
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


_cursor_reader = None  # () -> (x, y)：bootstrap.bind_all 接平台层的 cursor.pos
_key_reader = None  # (键码) -> 按着没有：bootstrap.bind_all 接平台层的 keys.down


def set_platform(cursor_pos, key_down):
    """装配时接读光标、读键（bootstrap.bind_all；app 层不直接 import infrastructure）"""
    global _cursor_reader, _key_reader
    _cursor_reader, _key_reader = cursor_pos, key_down


def _cursor():
    """鼠标在哪 (x, y)；没接、读不了给 None（出错在这里吞掉，和以前一样）"""
    read = _cursor_reader
    if read is None:
        return None
    try:
        x, y = read()
        return x, y
    except Exception:
        return None


def _key_down(vk):
    """这个键按着没有；没接、读不了当没按（平台层 keys.down 读不了会抛，热键线程要知道；这里照旧吞掉）"""
    read = _key_reader
    if read is None:
        return False
    try:
        return bool(read(vk))
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
            if (
                o
                and c
                and time.time() - _ITEM_MODE["shown_at"] >= ITEM_AWAY_AFTER
                and not _key_down(0x11)
                and math.dist(o, c) > away
            ):
                break
            if _key_down(0x11):
                end = max(end, time.time() + 1)
        if _ITEM_SEQ[0] == my:
            h_cur = _hud()
            if h_cur:
                h_cur.clear("物品")

    threading.Thread(target=watch, daemon=True, name="item-hud").start()
