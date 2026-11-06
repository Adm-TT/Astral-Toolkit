"""定位工作线程（目录迁移章程 R1：原 app/engines/pos.py 的 _Pos / _LogWatch 搬来）

PositionWorker 一直在后台读游戏右上角的调试信息（r_DisplayInfo 2）：有就随时知道你在哪，导航、路标、「离你最近的买点」都用它。
它是「当前位置」的唯一持有者：最后读到的坐标、地点、星系、离哪最近，以及读右上角的快慢。
2026-10-26 起：字模识别（gridtext）几毫秒认一次，游戏在最前面就每 0.2 秒读一次（BASE_FPS）；有模块要更快（导航帧数）就按它要的，最高 30（NV-B5）；
字模还没学好时（第一次用、换了分辨率）用识别引擎认，每 2 秒一次来校准，导航时 1 秒一次。

怎么读、怎么认、往哪发都由 bootstrap 接进来（章程 §6），本模块不导入界面、业务、游戏数据和读屏实现：
- reader：读右上角的读取器（navigation.displayinfo.Reader；调试模式开关在它身上）
- foreground：游戏在不在最前面（判断出错当在）；calibrated：字模学好没有（判断出错当没好）
- label_of / system_of / locate：地点中文名、属于哪个星系、离哪最近（tasks/position.py）
- publish_status：推一次状态给窗口（不给就不推）；log：写一行到窗口日志；fine_timer：读得快时调 Windows 等待精度（None = 不调）
- enabled：这台机器能不能读右上角（只有 Windows 能）

LogWatchWorker 每 5 秒看一眼游戏日志（read_log 给最后一次的地点或 None），变了就推一次状态。
"""

import re
import threading
import time
from collections.abc import Callable
from typing import Any

from ...contracts.position import PositionRead, PositionSnapshot


def _zone_base(info):
    """最里层 Zone 名去掉末尾带数字的那一截（轿厢、机库的随机编号每次不一样，字模还可能把数字认成字母）"""
    return re.sub(
        r"[\s_]+[0-9A-Za-z]*\d[0-9A-Za-z]*$",
        "",
        ((info or {}).get("inner_zone") or "").strip(),
    )


class PositionWorker:
    """后台读右上角的线程和当前位置。debug 开关、读法在 reader 上；分析和发布见模块说明"""

    BASE_FPS = 5  # 平时（没人要更快）字模读右上角每秒 5 次 = 以前的 0.2 秒一次
    MAX_FPS = 30  # 谁要再快也按 30（设置页最高档；60 档实测只读到约 31 次，老大 11-05 改成 5–30）
    CALIB_EVERY = 2.0  # 字模还没校准好：每 2 秒用识别引擎认一次来学（一般 3～5 次就好，好了就停）；读不到会自己放慢

    def __init__(
        self,
        reader: Any,
        *,
        foreground: Callable[[], Any],
        calibrated: Callable[[], Any],
        label_of: Callable[[Any], Any],
        system_of: Callable[..., Any],
        locate: Callable[..., Any],
        publish_status: Callable[[], None] | None = None,
        log: Callable[[str], None] | None = None,
        fine_timer: Callable[[bool], None] | None = None,
        enabled: bool = True,
    ):
        self.reader: Any = reader
        self._foreground = foreground
        self._calibrated = calibrated
        self._label_of = label_of
        self._system_of = system_of
        self._locate = locate
        self._publish_status = publish_status
        self._log = log
        self._enabled = enabled
        self.latest: Any = (
            0.0,
            None,
            None,
        )  # (时间, 星系坐标, 那次读到的全部信息)：坐标变了才换
        self.read_at: float = 0.0  # 最后一次读到位置（坐标没变也算）的截图时间
        self.current: Any = (
            0.0,
            None,
            None,
        )  # 最后一次读到的（时间, 坐标, 全部信息），坐标没变也换
        self.here: Any = None  # 最后一次 locate 结果（原来寄在 nav.last_here）
        self.label: Any = (
            0.0,
            "",
        )  # (时间, 具体地点中文名)：最后一次从右上角认出的地点
        self.system: Any = (0.0, "")  # (时间, 星系)：最后一次从右上角定下的星系
        self.fast: bool = False  # 最近一次是字模认的
        self.reader_active = False
        self.reader_ok_at = 0.0
        self.demand = {}  # key -> until（导航开始放 inf，结束清 0）
        self.rate = {}  # key -> 这个模块要每秒读几次（只在字模好了时按它读）
        self._fine_timer = fine_timer  # 读得快时调 Windows 等待精度（bootstrap 给 infrastructure.platform.timer.fine；None = 不调）
        self._fine_on = False
        self.thread = None
        self.stop_ev = threading.Event()
        self._lock = threading.Lock()
        self._reader_lock = threading.Lock()
        self._pub_at = 0.0

    def start(self):
        if self._enabled and (self.thread is None or not self.thread.is_alive()):
            self.stop_ev.clear()
            self.thread = threading.Thread(
                target=self._run, daemon=True, name="displayinfo"
            )
            self.thread.start()

    def request_stop(self):
        self.stop_ev.set()

    def join(self, timeout=None):
        thread = self.thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return not thread.is_alive()
        thread.join(timeout)
        return not thread.is_alive()

    def snapshot(self):
        with self._lock:
            return PositionSnapshot(
                current=self.current,
                latest=self.latest,
                read_at=self.read_at,
                label=self.label,
                system=self.system,
                fast=self.fast,
                reader_active=self.reader_active,
                reader_ok_at=self.reader_ok_at,
                here=self.here,
            )

    def hints(self, max_age=5.0):
        """给 system_of 用的线索（最近 max_age 秒内读到的）：zone、location、solar_id"""
        with self._lock:
            t, g, info = self.current
        if not info or time.time() - t > max_age:
            return {}
        return {k: info.get(k) or "" for k in ("zone", "location", "solar_id")}

    def request_read_now(self):
        """只置「尽快读」，不在调用线程读"""
        with self._reader_lock:
            self.reader.next_at = 0.0
            self.reader.misses = 0

    def read_now(self, force=True):
        """在调用线程同步读一次；和定位线程共用一把 reader 锁（_where_now 用）"""
        with self._reader_lock:
            if force:
                self.reader.poll(force=True)
            ok_at, info = self.reader.snapshot()
        info = info or {}
        g = tuple(info["global"]) if info.get("global") else None
        return PositionRead(ok_at, info, g)

    def set_demand(self, key, until, fps=None):
        """key 这个模块要位置要到 until（time.time() 的秒数；inf = 一直要，0 = 不要了）。
        fps = 想要每秒读几次右上角（字模学好以后才按它读）：所有没过期的需求里取最高的，最低 BASE_FPS、最高 MAX_FPS；
        不给按 BASE_FPS。导航按设置页的「导航帧数」要；别的模块要更快也调这个（NV-B5）"""
        with self._lock:
            if until:
                self.demand[key] = float(until)
                if fps is not None and float(fps) > 0:
                    self.rate[key] = float(fps)
                else:
                    self.rate.pop(key, None)
            else:
                self.demand.pop(key, None)
                self.rate.pop(key, None)

    def _navigating(self):
        now = time.time()
        with self._lock:
            return any(until > now for until in self.demand.values())

    def fps_wanted(self):
        """现在要每秒读几次：没过期的需求里要得最多的，至少 BASE_FPS，最多 MAX_FPS"""
        now = time.time()
        with self._lock:
            asked = [
                self.rate[key]
                for key, until in self.demand.items()
                if until > now and key in self.rate
            ]
        return min(float(self.MAX_FPS), max([float(self.BASE_FPS), *asked]))

    def _tune(self, ready, navigating):
        """（在 _reader_lock 里调）定读右上角的间隔：字模好了按要的帧数；没好时导航中 1 秒、平时 2 秒校准一次。返回这次按几帧读"""
        fps = self.fps_wanted()
        self.reader.max_gap = 5.0 if navigating else 60.0
        if ready:
            self.reader.every = 1.0 / fps
        elif navigating:
            self.reader.every = 1.0
        else:
            self.reader.every = self.CALIB_EVERY
        return fps

    def _nap(self, ready, next_at, now=None):
        """这一圈完了等多久：字模没好 0.2 秒；好了等到下次该读的时候，最长 0.05 秒（以前固定 0.05，帧数高了会多等一拍）"""
        if not ready:
            return 0.2
        now = time.time() if now is None else now
        return min(0.05, max(0.001, next_at - now))

    def _fine(self, on):
        """读得比平时快时打开 1 毫秒等待精度，不快了关掉；状态没变不重复调，调不了就算了"""
        on = bool(on)
        if on == self._fine_on or self._fine_timer is None:
            return
        self._fine_on = on
        try:
            self._fine_timer(on)
        except Exception:
            pass

    def _absorb(self, ok_at, info):
        g = tuple(info["global"])
        fast = bool(info.get("fast"))
        label_changed = False
        if info.get("location"):
            lab = self._label_of(info["location"])
            with self._lock:
                old = self.label[1]
                self.label = (time.time(), lab or old)
                label_changed = bool(lab and lab != old)
        sysname = None
        try:
            sysname = self._system_of(
                info["global"],
                zone=info.get("zone"),
                location=info.get("location"),
                solar_id=info.get("solar_id"),
            )
        except Exception:
            pass
        system_changed = False
        if sysname is not None:
            with self._lock:
                system_changed = sysname != self.system[1]
                self.system = (time.time(), sysname)
        zb = _zone_base(info)
        need_publish = False
        with self._lock:
            self.fast = fast
            prev = self.latest[1]
            moved = prev is None or max(abs(a - b) for a, b in zip(g, prev)) > 1.0
            moved = moved or bool(zb) and zb != _zone_base(self.latest[2])
            read_at = info.get("t") or ok_at
            self.read_at = read_at
            self.current = (read_at, g, dict(info))
            if moved:
                self.latest = (read_at, g, dict(info))
                need_publish = True
        if need_publish:
            here = None
            try:
                here = self._locate(
                    g,
                    when=info.get("t"),
                    local=info.get("local"),
                    zone=info.get("zone"),
                    local_ok=info.get("local_ok"),
                )
            except Exception:
                here = None
            with (
                self._lock
            ):  # 位置变了就更新，算不出也写 None，别留着上一处的地点（审查 RT-B5b）
                self.here = here
            self._publish()
        if label_changed or system_changed:
            self._publish(force=True)

    def _publish(self, force=False):
        now = time.time()
        if (
            force or now - self._pub_at >= 1.0
        ):  # 坐标每秒变好几次，窗口一秒刷一次就够；地点变了马上刷
            self._pub_at = now
            if self._publish_status is not None:
                self._publish_status()

    def _run(self):
        was = False
        while not self.stop_ev.is_set():
            ready = False
            nap = 0.2
            try:
                try:
                    fg = self._foreground()
                except Exception:
                    fg = True
                try:
                    ready = self._calibrated()
                except Exception:
                    pass
                navigating = self._navigating()
                if not fg:
                    self._fine(False)
                    self.stop_ev.wait(0.5)
                    continue
                with self._reader_lock:
                    fps = self._tune(ready, navigating)
                    seen = self.reader.ok_at
                    self.reader.poll()
                    ok_at, info = self.reader.snapshot()
                    reader_active = bool(self.reader.active)
                    next_at = self.reader.next_at
                self._fine(ready and fps > self.BASE_FPS)
                nap = self._nap(ready, next_at)
                info = info or {}
                if ok_at != seen and info.get("global"):
                    self._absorb(ok_at, info)
                active_changed = reader_active != was
                was = reader_active
                with self._lock:
                    self.reader_active = reader_active
                    if info.get("global"):
                        self.reader_ok_at = ok_at
                if active_changed:
                    self._publish(force=True)
            except Exception as e:
                if self._log is not None:
                    self._log(f"右上角识别失败：{e}")
            self.stop_ev.wait(nap)
        self._fine(False)


class LogWatchWorker:
    """每 5 秒看一眼游戏日志有没有变长；变长了只读新增的几行，位置变了就推给窗口。
    （只看文件大小，几乎不占资源；玩家除非退出游戏或死亡，很少一下子跑很远，5 秒够用）
    read_log：最后一次的地点（(时间, 地点名, …) 或 None）；publish_status：推一次状态（不给就不推）"""

    EVERY = 5.0

    def __init__(
        self,
        *,
        read_log: Callable[[], Any],
        publish_status: Callable[[], None] | None = None,
    ):
        self._read_log = read_log
        self._publish_status = publish_status
        self.thread = None
        self.last = None
        self.stop_ev = threading.Event()

    def start(self):
        if self.thread is None or not self.thread.is_alive():
            self.stop_ev.clear()
            self.thread = threading.Thread(
                target=self._run, daemon=True, name="logwatch"
            )
            self.thread.start()

    def request_stop(self):
        self.stop_ev.set()

    def join(self, timeout=None):
        thread = self.thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return not thread.is_alive()
        thread.join(timeout)
        return not thread.is_alive()

    def _run(self):
        while not self.stop_ev.is_set():
            try:
                hit = self._read_log()
                now = (hit[0], hit[1]) if hit else None
                if now != self.last:
                    self.last = now
                    if self._publish_status is not None:
                        self._publish_status()
            except Exception:
                pass
            if self.stop_ev.wait(self.EVERY):
                break
