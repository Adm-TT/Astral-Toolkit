"""读游戏日志 Game.log，判断你现在是不是坐在载具（飞船/车）的驾驶位上（双击 W 自动跑要避开）

依据（从你的日志里核对过）：
- 登上载具：HUD 通知「你已加入 频道 '<载具名> : <船主>'」（英文客户端是 joined channel）——只是登船，
  在伊德里斯这种大船里走动也会加入频道，所以不算在开
- 坐在驾驶位：飞船导航模块的日志「[ItemNavigation][CL]… | ANVL_C8R_Pisces_892158680463[…]|」
  （PostInitialize 那种不算：附近任何船初始化都会写，1.6.45）
- 离开驾驶位：「CVehicleMovementBase::ClearDriver: Local client node … releasing control token」
  （上船后频道一直不退，光看频道会一直以为你在船上，所以要看这条）
- 离开载具：「你退出了 频道 '<载具名> : <船主>'」
- 重生：「[CSessionManager::OnClientSpawned] Spawned!」——船炸了没有离开通知，靠这个清掉
- 游戏重启会新建 Game.log，从头读
只读日志，不碰游戏文件。
"""
import re
from pathlib import Path

JOIN = re.compile(r"Added notification \"(?:你已加入 频道|You have joined channel|Joined channel) '([^']+ : [^']+)'")
LEAVE = re.compile(r"Added notification \"(?:你退出了 频道|You have left channel|Left channel) '([^']+ : [^']+)'")
SPAWN = "OnClientSpawned] Spawned!"
SEAT = re.compile(r"\[ItemNavigation\]\[CL\]\[\d+\]\s*\|[^|]*\|\s*([A-Za-z][A-Za-z0-9_]+?)_\d+\[\d+\]\|")
UNSEAT = re.compile(r"ClearDriver: Local client node .*?releasing control token for '([^']+)'")
COMMON = [r"C:\Program Files\Roberts Space Industries\StarCitizen\LIVE",
          r"D:\Roberts Space Industries\StarCitizen\LIVE", r"D:\StarCitizen\LIVE", r"E:\StarCitizen\LIVE",
          r"C:\StarCitizen\LIVE"]


def find_log():
    """找 Game.log：先看设置里记住的，再从正在运行的游戏进程位置推，最后试常见安装位置"""
    from . import settings, showloc
    cfg = settings.load()
    p = cfg.get("game_log")
    if p and Path(p).exists():
        return Path(p)
    try:
        hwnd = showloc.find_game_window()
        exe = showloc._exe_path(hwnd) if hwnd else ""
        if exe:
            cand = Path(exe).parent.parent / "Game.log"          # ...\LIVE\Bin64\StarCitizen.exe
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


class GameLog:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.pos = 0
        self.buf = b""
        self.vehicle = None          # 正坐在驾驶位的载具，None = 没在开（走路、在大船里走动都算 None）
        self.channel = None          # 登上的载具（语音频道名），只做记录
        self.events = []             # 最近的状态变化 [(时间, 说明)]

    @property
    def aboard(self):
        return self.vehicle is not None

    def _reset(self):
        self.pos, self.buf, self.vehicle, self.channel = 0, b"", None, None

    def poll(self):
        """读新增的日志行，更新状态；返回 True 表示状态有变化"""
        if self.path is None or not self.path.exists():
            self.path = find_log() if self.path is None else self.path
            if self.path is None or not self.path.exists():
                return False
        before = self.vehicle
        try:
            size = self.path.stat().st_size
            if size < self.pos:                      # 游戏重启，新日志
                self._reset()
            if size == self.pos:
                return False
            with open(self.path, "rb") as f:         # 分块读（每次 1 MB）：第一次接上时日志可能几百 MB，别整个读进内存（二审 2026-10-28）
                f.seek(self.pos)
                while self.pos < size:
                    chunk = f.read(min(1 << 20, size - self.pos))
                    if not chunk:
                        break
                    self.pos += len(chunk)
                    self._feed(chunk)
        except OSError:
            return False
        return self.vehicle != before

    def _feed(self, data):
        data = self.buf + data
        lines = data.split(b"\n")
        self.buf = lines.pop()                       # 最后一行可能还没写完
        for raw in lines:
            if not (b"Added notification" in raw or b"Spawned!" in raw or b"[ItemNavigation][CL]" in raw
                    or b"ClearDriver" in raw):
                continue
            self.line(raw.decode("utf-8", "replace"))

    def line(self, text):
        m = JOIN.search(text)
        if m:                                        # 登船（含在大船里走动）：只记下来，不算在开
            self.channel = m.group(1)
            self.events.append((text[1:25], f"登上 {m.group(1)}（走动不算开船）"))
            return
        m = UNSEAT.search(text)
        if m:
            if self.vehicle:
                self.events.append((text[1:25], f"离开驾驶位（{m.group(1)}）"))
            self.vehicle = None
            return
        m = SEAT.search(text)
        if m:
            if "PostInitialize" in text:
                # 附近别人的船（或刚刷出来的船）初始化导航模块时也写这条、带船名，不是你坐上了（1.6.45）。
                # 以前当成坐上驾驶位，双击 W 自动跑一直被挡：10-20 以来 26 个日志里 41 次、约 12 小时
                return
            if self.vehicle is None:
                self.vehicle = m.group(1)
                self.events.append((text[1:25], f"坐上驾驶位（{m.group(1)}）"))
            return
        m = LEAVE.search(text)
        if m:
            if self.channel == m.group(1):
                self.channel = None
                self.vehicle = None
                self.events.append((text[1:25], f"下了 {m.group(1)}"))
            return
        if SPAWN in text:
            if self.vehicle:
                self.events.append((text[1:25], "重生，算步行"))
            self.vehicle = None
            self.channel = None


# ================================================================ 量子、管辖区、禁火区、重生（2026-10-27）
# 规则按老大电脑上 4.10.2 的真实 Game.log 定；思路参考 all-slain、sc-companion（都是 MIT）读日志的做法
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
        return datetime.strptime(text[1:24], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc).timestamp()
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
        self.pos = None                          # None = 还没接上过：接上时从末尾开始（打开 AT 之前的不算）
        self.ident = None                        # 文件身份（编号 + 创建时间）：游戏重开会新建 Game.log
        self.buf = b""
        self.ev = GameEvents()

    def poll(self):
        if self.path is None:
            self.path = find_log()
            if self.path is None:
                return []
        try:
            st = self.path.stat()
        except OSError:                          # 游戏重开那一下文件暂时不在：等它回来，不当成第一次
            return []
        ident = (st.st_ino, getattr(st, "st_birthtime", st.st_ctime))
        try:
            size = st.st_size
            if self.pos is None:                 # 第一次：从末尾开始
                self.pos, self.ident = size, ident
                return []
            if ident != self.ident or size < self.pos:   # 换了文件（游戏重开）：从头读新日志（Codex 2026-10-27）
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
            if b"QuantumTravel" in raw or b"Added notification" in raw or b"Spawned!" in raw:
                out += self.ev.feed(raw.decode("utf-8", "replace"))
        return out
