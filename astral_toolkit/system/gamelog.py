"""读游戏日志 Game.log：找日志文件（find_log），顺着读新写的部分认游戏事件（GameEvents / EventTail：
量子目标、量子到达、管辖区、禁火区、监管区域、重生）。只读日志，不碰游戏文件。

以前还有判断坐没坐驾驶位的 GameLog（给「双击 W 自动跑」用，模拟按键 2026-10-31 删了），CL-C2 删掉。
"""

import re
from pathlib import Path

SPAWN = "OnClientSpawned] Spawned!"
COMMON = [
    r"C:\Program Files\Roberts Space Industries\StarCitizen\LIVE",
    r"D:\Roberts Space Industries\StarCitizen\LIVE",
    r"D:\StarCitizen\LIVE",
    r"E:\StarCitizen\LIVE",
    r"C:\StarCitizen\LIVE",
]


def find_log():
    """找 Game.log：先看设置里记住的，再从正在运行的游戏进程位置推，最后试常见安装位置"""
    from ..core import settings
    from . import showloc

    cfg = settings.load()
    p = cfg.get("game_log")
    if p and Path(p).exists():
        return Path(p)
    try:
        hwnd = showloc.find_game_window()
        exe = showloc._exe_path(hwnd) if hwnd else ""
        if exe:
            cand = (
                Path(exe).parent.parent / "Game.log"
            )  # ...\LIVE\Bin64\StarCitizen.exe
            if cand.exists():
                settings.update(game_log=str(cand))
                return cand
    except Exception:
        pass
    for d in COMMON:
        cand = Path(d) / "Game.log"
        if cand.exists():
            settings.update(game_log=str(cand))
            return cand
    return None


# ================================================================ 量子、管辖区、禁火区、重生（2026-10-27）
# 规则按 4.10.2 的真实 Game.log 定；思路参考 all-slain、sc-companion（都是 MIT）读日志的做法
QT_TARGET = re.compile(r"Player has selected point (\S+) as their destination")
QT_ARRIVED = "Quantum Drive has arrived at final destination"
NOTE = re.compile(r"Added notification \"([^\"]+?)(?::\s*)?\"")
JURIS = re.compile(r"^(?:已进入\s*(.+?)\s*管辖区|Entered (.+?) Jurisdiction)$")
ARMI_IN = ("正在进入禁火区", "Entering Armistice Zone")
ARMI_OUT = ("正在远离禁火区", "Leaving Armistice Zone")
MON_IN = ("已进入监管区域", "Entered Monitored Space")
MON_OUT = ("已离开监管区域", "Left Monitored Space")


def _ts(text):
    """<2026-10-24T10:46:36.173Z> → 时间戳（秒）；没有就 None"""
    from datetime import datetime, timezone

    try:
        return (
            datetime.strptime(text[1:24], "%Y-%m-%dT%H:%M:%S.%f")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
    except Exception:
        return None


class GameEvents:
    """顺着日志读游戏事件：→ [(时间戳, 种类, 内容)]，种类：qt_target（选了量子目标，内容是游戏里的点代码）、
    qt_arrived（量子到达）、jurisdiction（进了谁的管辖区）、armistice（True 进禁火区 / False 离开）、
    monitored（True 进监管区域 / False 离开）、spawn（重生）。同时记住每种最后一次的值"""

    def __init__(self):
        self.last = {}

    def feed(self, text):
        out = []
        t = _ts(text)
        m = QT_TARGET.search(text)
        if m:
            out.append((t, "qt_target", m.group(1)))
        elif QT_ARRIVED in text:
            out.append((t, "qt_arrived", True))
        elif SPAWN in text:
            out.append((t, "spawn", True))
        else:
            m = NOTE.search(text)
            if m:
                msg = m.group(1).strip()
                j = JURIS.match(msg)
                if j:
                    out.append((t, "jurisdiction", (j.group(1) or j.group(2)).strip()))
                elif msg.startswith(ARMI_IN):
                    out.append((t, "armistice", True))
                elif msg.startswith(ARMI_OUT):
                    out.append((t, "armistice", False))
                elif msg.startswith(MON_IN):
                    out.append((t, "monitored", True))
                elif msg.startswith(MON_OUT):
                    out.append((t, "monitored", False))
        for t, k, v in out:
            self.last[k] = (t, v)
        return out


class EventTail:
    """只读 Game.log 新增的部分（打开 AT 之前的旧事件不算），交给 GameEvents"""

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.pos = None  # None = 还没接上过：接上时从末尾开始（打开 AT 之前的不算）
        self.ident = None  # 文件身份（编号 + 创建时间）：游戏重开会新建 Game.log
        self.buf = b""
        self.ev = GameEvents()

    def poll(self):
        if self.path is None:
            self.path = find_log()
            if self.path is None:
                return []
        try:
            st = self.path.stat()
        except OSError:  # 游戏重开那一下文件暂时不在：等它回来，不当成第一次
            return []
        ident = (st.st_ino, getattr(st, "st_birthtime", st.st_ctime))
        try:
            size = st.st_size
            if self.pos is None:  # 第一次：从末尾开始
                self.pos, self.ident = size, ident
                return []
            if (
                ident != self.ident or size < self.pos
            ):  # 换了文件（游戏重开）：从头读新日志（审查 2026-10-27）
                self.pos, self.buf, self.ident = 0, b"", ident
            if size == self.pos:
                return []
            with open(self.path, "rb") as f:
                f.seek(self.pos)
                data = f.read(min(size - self.pos, 8_000_000))
            self.pos += len(data)
        except OSError:
            return []
        lines = (self.buf + data).split(b"\n")
        self.buf = lines.pop()
        out = []
        for raw in lines:
            if (
                b"QuantumTravel" in raw
                or b"Added notification" in raw
                or b"Spawned!" in raw
            ):
                out += self.ev.feed(raw.decode("utf-8", "replace"))
        return out
