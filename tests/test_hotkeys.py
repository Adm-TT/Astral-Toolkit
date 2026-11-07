"""热键（目录迁移 R4）：看键的线程（runtime/workers/hotkeys）和按下去做什么的键盘入口（HotkeyCommands）分开以后照旧——
刚按下才算一次、按住不连发、撞键时排前面的生效、只看认得的键、约 1.8 秒重读一次绑定、出错先清「忙」再 1 秒后重来；
切出游戏按 F8 / 盘点键只提示，占着「忙」的同一时间只跑一个。全用假键盘、假设置，不碰真按键"""

import builtins
import threading
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from astral_toolkit.app import bus, hud_state, task_runner
from astral_toolkit.app.inputs import hotkeys as entry
from astral_toolkit.app.inputs.hotkeys import HotkeyCommands
from astral_toolkit.core import settings
from astral_toolkit.runtime.workers.hotkeys import HotkeyLinks, HotkeyWorker
from astral_toolkit.tasks import mining as mining_tasks
from astral_toolkit.tasks.system.settings import HOTKEYS


class _Ticks(threading.Event):
    """假的 stop_ev：线程每看完一遍键调一次 wait(0.03)，就算过了一遍；过满 limit 遍说「该停了」。出错后的 wait(1) 也记下、
    不算一遍；别的等法也算一遍（间隔改坏了测试照样停得下来，由断言抓）"""

    def __init__(self, limit):
        super().__init__()
        self.limit = limit
        self.polls = 0
        self.waits = []
        self._stop = False

    def is_set(self):
        return self._stop

    def set(self):
        self._stop = True

    def clear(self):
        self._stop = False

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if timeout != 1:
            self.polls += 1
            if self.polls >= self.limit:
                self._stop = True
        return self._stop


_CODES = {"F5": 116, "F6": 117, "F7": 118, "F8": 119, "F9": 120, "F10": 121}


def _worker(bindings: Any, script=None, limit=10, pressed=None):
    """假键盘的热键线程：script = {键码: 第几遍按着（从 0 数）}；got 记 (第几遍, 热键名, 键名) 和
    ("failed", 那时已经等过几次)"""
    ticks = _Ticks(limit)
    script = script or {}
    reads = []
    got = []

    def down(vk):
        reads.append((ticks.polls, vk))
        return ticks.polls in script.get(vk, ())

    read: Callable[[], Any] = bindings if callable(bindings) else (lambda: bindings)
    links = HotkeyLinks(
        bindings=read,
        code=_CODES.get,
        down=down,
        pressed=pressed or (lambda name, key: got.append((ticks.polls, name, key))),
        failed=lambda: got.append(("failed", len(ticks.waits))),
    )
    worker = HotkeyWorker(links, enabled=True)
    worker.stop_ev = ticks
    return worker, ticks, reads, got


def test_worker_reports_a_press_once_while_held():
    """刚按下（上一遍没按着、这一遍按着）才报一次；按住不连发，松开再按再报一次；每遍之间等 0.03 秒"""
    worker, ticks, _, got = _worker(
        [("F8", "trade_capture_key")], {119: {2, 3, 4, 7}}, limit=10
    )
    worker._run()
    assert got == [(2, "trade_capture_key", "F8"), (7, "trade_capture_key", "F8")]
    assert ticks.polls == 10 and set(ticks.waits) == {0.03}


def test_worker_first_binding_of_a_key_wins_and_skips_unknown_keys():
    """撞键时只有排在前面的生效；没绑（空）的键、平台认不了的键不看"""
    binds = [
        ("F8", "trade_capture_key"),
        ("", "mark_key"),
        ("F8", "report_key"),
        ("X1", "ore_key"),
        ("F5", "live_key"),
    ]
    worker, _, reads, got = _worker(binds, {119: {1}, 116: {1}}, limit=3)
    worker._run()
    assert got == [(1, "trade_capture_key", "F8"), (1, "live_key", "F5")]
    assert reads == [(n, vk) for n in range(3) for vk in (119, 116)]  # 每遍只看这两个键


def test_worker_rereads_bindings_every_60_passes():
    """每看 60 遍（约 1.8 秒）重读一次绑定：玩家把 F8 改成 F9，下一轮起看 F9、不再看 F8"""
    state: dict[str, Any] = {"reads": []}

    def bindings():
        n = state["ticks"].polls
        state["reads"].append(n)
        return [("F8" if n < 60 else "F9", "trade_capture_key")]

    worker, ticks, _, got = _worker(bindings, {119: {10, 70}, 120: {10, 70}}, limit=120)
    state["ticks"] = ticks
    worker._run()
    assert state["reads"] == [0, 60]
    assert got == [(10, "trade_capture_key", "F8"), (70, "trade_capture_key", "F9")]


def test_worker_survives_errors_and_clears_busy_first(monkeypatch):
    """一轮里出错（读绑定、看键、按下去的动作都算）：记一笔、先叫入口清「忙」、等 1 秒再从头来（重读绑定），
    F5 / F6 / F8 不会从此全失效"""
    printed = []
    monkeypatch.setattr(builtins, "print", lambda *a, **k: printed.append(a[0]))
    state = {"n": 0}

    def bindings():
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("设置坏了")
        return [("F8", "trade_capture_key")]

    worker, ticks, _, got = _worker(bindings, {119: {1}}, limit=3)
    worker._guard()
    assert printed == ["热键监听出错，1 秒后重来：RuntimeError('设置坏了')"]
    # 先叫入口清「忙」（那时一次都还没等过），再等 1 秒
    assert got == [("failed", 0), (1, "trade_capture_key", "F8")]
    assert ticks.waits[0] == 1 and state["n"] == 2

    calls = []

    def pressed(name, key):
        calls.append(name)
        if len(calls) == 1:
            raise ValueError("动作坏了")

    worker, ticks, _, got = _worker(
        [("F8", "trade_capture_key")], {119: {1, 2}}, limit=4, pressed=pressed
    )
    worker._guard()
    # 动作出错也一样：清忙时只等过第 0 遍那一次，1 秒在清忙之后；重来以后从头看，那时还按着的键算新按下（以前也是这样）
    assert got == [("failed", 1)]
    assert calls == ["trade_capture_key", "trade_capture_key"]
    assert ticks.waits[:2] == [0.03, 1] and ticks.waits.count(1) == 1
    assert printed[-1] == "热键监听出错，1 秒后重来：ValueError('动作坏了')"


def test_worker_thread_only_when_enabled():
    """只有 Windows（enabled）才起线程（守护线程，名字照旧 hover-key）；已经在跑就不再起第二个；叫停以后等得到退出"""
    links = HotkeyLinks(
        bindings=lambda: [("F8", "trade_capture_key")],
        code=_CODES.get,
        down=lambda vk: False,
        pressed=lambda name, key: None,
        failed=lambda: None,
    )
    off = HotkeyWorker(links, enabled=False)
    off.start()
    assert off.thread is None and off.join(0.1) is True
    on = HotkeyWorker(links, enabled=True)
    on.start()
    try:
        first = on.thread
        assert first is not None and first.name == "hover-key" and first.daemon
        on.start()
        assert on.thread is first
    finally:
        on.request_stop()
    assert on.join(2.0) is True


def _commands(count_running=False):
    return HotkeyCommands(
        live=SimpleNamespace(running=lambda: False),
        count=SimpleNamespace(running=lambda: count_running),
        links="links",
        feedback=None,
        nav="nav",
    )


def test_f8_and_count_key_only_hint_outside_the_game(monkeypatch):
    """切出游戏按 F8 / 盘点键：只在运行日志里说一声（盘点开着时再提示去窗口结束），不识别、不开关盘点；
    别的键切出游戏照常做；判断不了在不在游戏（None）也照常做"""
    logs = []
    monkeypatch.setattr(bus, "runtime_log", lambda line, **kw: logs.append((line, kw)))
    front: dict[str, bool | None] = {"v": False}
    monkeypatch.setattr(mining_tasks, "_game_front", lambda: front["v"])
    for running, tail in ((True, "，或在窗口点「结束盘点」"), (False, "")):
        cmd = _commands(count_running=running)
        acted = []
        names = ("trade_capture_key", "count_key", "live_key")
        acts = {n: (False, lambda n=n: acted.append(n)) for n in names}
        monkeypatch.setattr(cmd, "_acts", lambda acts=acts: acts)
        logs.clear()
        front["v"] = False
        cmd.pressed("trade_capture_key", "F8")
        cmd.pressed("count_key", "F6")
        cmd.pressed("live_key", "F5")
        assert acted == ["live_key"]
        assert logs == [
            (
                "不在游戏里，F8 识别没响应：回到游戏再按",
                {"tag": "HOVER", "level": "INFO"},
            ),
            (
                f"不在游戏里，F6 盘点没响应：回到游戏再按{tail}",
                {"tag": "COUNT", "level": "INFO"},
            ),
        ]
        front["v"] = None
        cmd.pressed("trade_capture_key", "F8")
        cmd.pressed("count_key", "F6")
        assert (
            acted == ["live_key", "trade_capture_key", "count_key"] and len(logs) == 2
        )


def test_busy_hotkeys_run_one_at_a_time(monkeypatch):
    """要截屏的（F8、问题反馈）占着「忙」，同一时间只跑一个：忙着再按 F8 说「正在识别中」，再按反馈键不响应；
    不占忙的（记路标等）忙着也照做；热键线程出错重来前 failed() 清掉忙"""
    logs = []
    monkeypatch.setattr(
        bus,
        "runtime_log",
        lambda line, **kw: logs.append((line, kw["tag"], kw["level"])),
    )
    monkeypatch.setattr(mining_tasks, "_game_front", lambda: True)
    cmd = _commands()
    acted = []
    acts = {
        "trade_capture_key": (True, lambda: acted.append("f8")),
        "report_key": (True, lambda: acted.append("report")),
        "mark_key": (False, lambda: acted.append("mark")),
    }
    monkeypatch.setattr(cmd, "_acts", lambda: acts)
    cmd.pressed("trade_capture_key", "F8")
    assert cmd.busy and acted == ["f8"]
    assert logs == [("捕获到 F8 快捷键，触发悬停识别...", "HOVER", "INFO")]
    cmd.pressed("trade_capture_key", "F8")
    cmd.pressed("report_key", "F10")
    cmd.pressed("mark_key", "F7")
    assert acted == ["f8", "mark"]
    assert logs[1:] == [("F8 正在识别中，请稍候...", "HOVER", "WARN")]
    cmd.failed()
    assert not cmd.busy
    cmd.pressed("report_key", "F10")
    assert (
        cmd.busy and acted == ["f8", "mark", "report"] and len(logs) == 2
    )  # 反馈键不往日志里说


def test_each_hotkey_runs_its_own_action(monkeypatch):
    """动作表：设置里能绑的热键都有动作；F8 起识别；记路标 / 一键定位 / 原矿记录同名任务只起一个；问题反馈每次起一个任务；
    采矿助手、盘点开关各起一个短线程（热键线程不跟着等）；占不占「忙」照旧"""
    runs = []
    monkeypatch.setattr(
        task_runner,
        "run_task_once",
        lambda tid, fn, *a, title="", **k: runs.append(("once", tid, fn, title)),
    )
    monkeypatch.setattr(
        task_runner,
        "run_task",
        lambda tid, fn, *a, title="", **k: runs.append(("run", tid, fn, title)),
    )
    threads = []

    class _Thread:
        def __init__(self, target=None, daemon=None, name=None):
            threads.append((target, daemon, name))

        def start(self):
            threads.append("start")

    monkeypatch.setattr(entry, "threading", SimpleNamespace(Thread=_Thread))
    cmd = _commands()
    acts = cmd._acts()
    assert set(acts) == {name for name, _, _ in HOTKEYS}
    assert {n: busy for n, (busy, _) in acts.items()} == {
        "trade_capture_key": True,
        "mark_key": False,
        "fix_key": False,
        "report_key": True,
        "live_key": False,
        "count_key": False,
        "ore_key": False,
    }
    assert acts["trade_capture_key"][1] == cmd._start_hover
    for name in (
        "mark_key",
        "fix_key",
        "report_key",
        "ore_key",
        "live_key",
        "count_key",
    ):
        acts[name][1]()
    assert runs == [
        ("once", "mark", cmd._mark, "记录路标"),
        ("once", "fix", cmd._fix, "一键定位"),
        ("run", "feedback", cmd._report, "问题反馈"),
        ("once", "ore", cmd._ore, "原矿记录"),
    ]
    assert threads == [
        (cmd._toggle_live, True, "live-key"),
        "start",
        (cmd._toggle_count, True, "count-key"),
        "start",
    ]


def test_bindings_follow_settings_in_hotkey_order(monkeypatch):
    """绑定按 tasks/system 热键表的顺序（撞键时排前面的生效）从设置现读：改了键就是新键（统一大写），设成空就是没绑"""
    cfg = {"trade_capture_key": "f9", "report_key": ""}
    monkeypatch.setattr(settings, "load", lambda: dict(cfg))
    cmd = _commands()
    assert cmd.bindings() == [
        ("F9", "trade_capture_key"),
        ("", "mark_key"),
        ("", "fix_key"),
        ("", "report_key"),
        ("F5", "live_key"),
        ("F6", "count_key"),
        ("", "ore_key"),
    ]
    cfg["report_key"] = "F10"
    assert ("F10", "report_key") in cmd.bindings()


def test_f8_retry_waits_for_the_last_run_and_uses_the_pressed_key(monkeypatch):
    """F8：先记下按键那一刻（鼠标位置、Shift），再起识别；起不来（上一次还没收尾）就另起短线程，等上一次 0.3 秒再试。
    重试也起不来：清掉「忙」，提示里说的是玩家按的那个键（如改绑的 F11）；重试起来了：不提示，「忙」留给识别做完再清"""
    logs = []
    monkeypatch.setattr(bus, "runtime_log", lambda line, **kw: logs.append(line))
    monkeypatch.setattr(mining_tasks, "_game_front", lambda: True)
    tries = []
    monkeypatch.setattr(hud_state, "item_key_pressed", lambda: tries.append("item"))
    outcomes = []  # run_task_once 每次回什么：None = 同名任务还在跑、没起来

    def run_task_once(tid, fn, *a, **k):
        tries.append(tid)
        return outcomes.pop(0)

    monkeypatch.setattr(task_runner, "run_task_once", run_task_once)
    running = {}
    monkeypatch.setattr(task_runner, "_running", running)

    class _Now:
        def __init__(self, target, **kw):
            self.target = target

        def start(self):
            self.target()

    class _Last:
        def __init__(self):
            self.joined = []

        def join(self, timeout=None):
            self.joined.append(timeout)

    monkeypatch.setattr(entry, "threading", SimpleNamespace(Thread=_Now))
    cmd = _commands()
    outcomes[:] = [None, None]
    cmd.pressed("trade_capture_key", "F11")
    assert tries == ["item", "hover", "hover"]
    assert logs == ["捕获到 F11 快捷键，触发悬停识别...", "F11 正在识别中，请稍候..."]
    assert cmd.busy is False

    last = _Last()
    running["hover"] = last
    outcomes[:] = [None, "重试起来了"]
    tries.clear()
    logs.clear()
    cmd.pressed("trade_capture_key", "F11")
    assert last.joined == [0.3]
    assert tries == ["item", "hover", "hover"]
    assert logs == ["捕获到 F11 快捷键，触发悬停识别..."]
    assert cmd.busy is True


def test_platform_keys_map_f1_to_f12_and_read_the_high_bit(monkeypatch):
    """平台读键（infrastructure/platform/keys）：只认 F1～F12（大写）；按着没有看 GetAsyncKeyState 的最高位，
    最低位（上次读过以后按过）不算按着。用假的 user32，不读真键盘"""
    from astral_toolkit.infrastructure.platform import keys

    assert [keys.code(f"F{i}") for i in range(1, 13)] == list(range(0x70, 0x7C))
    assert (
        keys.code("F13") is None and keys.code("f8") is None and keys.code("") is None
    )
    states = {0x77: -32768, 0x70: 1, 0x71: 0}
    fake = SimpleNamespace(
        windll=SimpleNamespace(
            user32=SimpleNamespace(GetAsyncKeyState=lambda vk: states[vk])
        )
    )
    monkeypatch.setattr(keys, "ctypes", fake)
    assert keys.down(0x77) is True
    assert keys.down(0x70) is False and keys.down(0x71) is False


def test_recognize_and_report_clear_busy_even_when_they_fail(monkeypatch):
    """F8 识别、问题反馈做完（出错也算）就清掉「忙」，下一次按键才会响应；错照样抛出去"""
    from astral_toolkit.tasks import hover as hover_tasks

    def boom(*a, **k):
        raise RuntimeError("坏了")

    monkeypatch.setattr(hover_tasks, "hover_once", boom)
    cmd = HotkeyCommands(
        live=SimpleNamespace(running=lambda: False),
        count=SimpleNamespace(running=lambda: False),
        links="links",
        feedback=boom,
        nav="nav",
    )
    for run in (cmd._recognize, cmd._report):
        cmd.busy = True
        try:
            run()
        except RuntimeError:
            pass
        else:
            raise AssertionError("错要抛出去")
        assert cmd.busy is False
