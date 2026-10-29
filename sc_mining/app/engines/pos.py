"""实时位置读取（右上角调试信息，_Pos）和日志位置跟踪（_LogWatch）

2026-10-28 从 app/services.py 原样剪出来（逻辑没改）。用到 services 里的函数 / 变量写成 _S().xxx：
运行时才取，避免互相 import；services 里仍保留实例（_nav、_live …）。
用到：WIN, _nav, status
"""
import threading
import time

from .. import bus


def _zone_base(info):
    """最里层 Zone 名去掉末尾带数字的那一截（轿厢、机库的随机编号每次不一样，字模还可能把数字认成字母）"""
    import re
    return re.sub(r"[\s_]+[0-9A-Za-z]*\d[0-9A-Za-z]*$", "", ((info or {}).get("inner_zone") or "").strip())


def _S():
    from .. import services
    return services


class _Pos:
    """一直在后台读游戏右上角的调试信息（r_DisplayInfo 2）：有就随时知道你在哪，导航、路标、「离你最近的买点」都用它。
    2026-10-26 起：字模识别（gridtext）几毫秒认一次，游戏在最前面就每 0.2 秒读一次，顶栏位置是实时的；
    字模还没学好时（第一次用、换了分辨率）用识别引擎认，每 2 秒一次来校准，导航时 1 秒一次"""
    FAST_EVERY = 0.2
    CALIB_EVERY = 2.0          # 字模还没校准好：每 2 秒用识别引擎认一次来学（一般 3～5 次就好，好了就停）；读不到会自己放慢

    def __init__(self):
        from ...navigation.displayinfo import Reader
        self.reader = Reader(every=1.0)
        self.latest = (0.0, None, None)    # (时间, 星系坐标, 那次读到的全部信息)：坐标变了才换
        self.read_at = 0.0                 # 最后一次读到位置（坐标没变也算）的截图时间
        self.current = (0.0, None, None)   # 最后一次读到的（时间, 坐标, 全部信息），坐标没变也换
        self.want_until = 0.0              # 不导航也临时读一会（新建路标要当前位置时）
        self.label = (0.0, "")             # (时间, 具体地点中文名)：最后一次从右上角认出的地点
        self.system = (0.0, "")            # (时间, 星系)：最后一次从右上角定下的星系
        self.fast = False                  # 最近一次是字模认的
        self.thread = None
        self._pub_at = 0.0

    def start(self):
        if _S().WIN and not self.thread:
            self.thread = threading.Thread(target=self._run, daemon=True, name="displayinfo")
            self.thread.start()

    def hints(self, max_age=5.0):
        """给 system_of 用的线索（最近 max_age 秒内读到的）：zone、location、solar_id"""
        t, g, info = self.latest
        if not info or time.time() - t > max_age:
            return {}
        return {k: info.get(k) or "" for k in ("zone", "location", "solar_id")}

    def _publish(self, force=False):
        now = time.time()
        if force or now - self._pub_at >= 1.0:          # 坐标每秒变好几次，窗口一秒刷一次就够；地点变了马上刷
            self._pub_at = now
            bus.publish("status", _S().status())

    def _run(self):
        from ...navigation import navigate as n, gridtext
        from ...system.showloc import game_foreground
        was = False
        while True:
            try:
                fg = game_foreground()
            except Exception:
                fg = True
            ready = False
            try:
                from ...core.perf import game_area
                ready = gridtext.ready(game_area()["height"])
            except Exception:
                pass
            navigating = bool(_S()._nav.target) or time.time() < self.want_until
            if not fg:
                time.sleep(0.5)
                continue
            if ready:
                self.reader.every = self.FAST_EVERY
            elif navigating:
                self.reader.every = 1.0
            else:
                self.reader.every = self.CALIB_EVERY        # 没导航、字模没好：认几帧把字模学出来
            try:
                seen = self.reader.ok_at
                self.reader.poll()
                # 坐标、详情、截图时间都取同一次读数（另一个线程可能在中间读过一次，不能拼两帧，Codex 2026-10-27 复审）
                ok_at, info = self.reader.snapshot()
                info = info or {}
                if ok_at != seen and info.get("global"):
                    self.fast = bool(info.get("fast"))
                    if info.get("location"):
                        from ...navigation.position import display_label
                        lab = display_label(info["location"])
                        old = self.label[1]
                        self.label = (time.time(), lab or old)
                        if lab and lab != old:
                            self._publish(force=True)
                    try:
                        sysname = n.system_of(info["global"], zone=info.get("zone"), location=info.get("location"),
                                              solar_id=info.get("solar_id"))
                        changed = sysname != self.system[1]
                        self.system = (time.time(), sysname)
                        if changed:
                            self._publish(force=True)
                    except Exception:
                        pass
                    g = tuple(info["global"])
                    prev = self.latest[1]
                    moved = prev is None or max(abs(a - b) for a, b in zip(g, prev)) > 1.0
                    # 最里层区域名变了也算（进电梯站着选楼层时坐标不动，区域名变成轿厢，导航要马上提示选哪站，审查 2026-10-28）
                    zb = _zone_base(info)
                    moved = moved or bool(zb) and zb != _zone_base(self.latest[2])     # 读不到（空）不算变
                    # 停着不动也算读到了（read_at 更新）：以前停车扫描 10 秒后就被当成「位置过期」（Codex 2026-10-27 复审）。
                    # latest 照旧只在坐标变了才换（导航按它重算，停着不用每 0.2 秒重算一遍）
                    self.read_at = info.get("t") or ok_at
                    self.current = (self.read_at, g, dict(info))       # 每次读到的完整一份（产矿区用：地名可能后几帧才认出来）
                    if moved:
                        self.latest = (self.read_at, g, dict(info))
                        # 顺便记进 last_position.json；星球局部坐标用游戏给的，比推算准
                        here = n.locate(g, when=info.get("t"), local=info.get("local"), zone=info.get("zone"),
                                        local_ok=info.get("local_ok"))
                        _S()._nav.last_here = here
                        self._publish()
            except Exception as e:
                bus.publish("log", {"task": "displayinfo", "line": f"右上角识别失败：{e}"})
            if self.reader.active != was:
                was = self.reader.active
                self._publish(force=True)
            time.sleep(0.05 if ready else 0.2)


class _LogWatch:
    """每 5 秒看一眼游戏日志有没有变长；变长了只读新增的几行，位置变了就推给窗口。
    （只看文件大小，几乎不占资源；玩家除非退出游戏或死亡，很少一下子跑很远，5 秒够用）"""
    EVERY = 5.0

    def __init__(self):
        self.thread = None
        self.last = None

    def start(self):
        if not self.thread:
            self.thread = threading.Thread(target=self._run, daemon=True, name="logwatch")
            self.thread.start()

    def _run(self):
        from ...navigation.position import from_log
        while True:
            try:
                hit = from_log()
                now = (hit[0], hit[1]) if hit else None
                if now != self.last:
                    self.last = now
                    bus.publish("status", _S().status())
            except Exception:
                pass
            time.sleep(self.EVERY)
