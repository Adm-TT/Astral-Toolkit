"""运行结构 RT-B3 / RT-B4（结果状态、会话循环）前后的发布序列基线：假画面驱动采矿助手（只经 start / stop），
录下总线和悬浮窗的完整序列，改完逐字比对

用法（在 worktree 根目录）：.venv\\Scripts\\python.exe -X utf8 tools\\runtime_baseline_live.py --out <输出.json>
  不读屏：screen.grab 换成脚本里的图。两轮：
    样本：tests/samples 每张喂 6 帧（真 OCR），再切出游戏几帧，再空白帧到过期、到自动关闭。
    写死：screen.analyse 也换掉，走面板读全、读不全提示、换石头、配装变化、面板被挡、空白到过期、自动关闭。
  时钟写死：每帧前进固定秒数，文字时间写成 12:00:00。全程断网，设置、目标、远程开关换掉，日志和截图写临时目录。
  驱动只用 start / stop（RT-B4 起线程由会话循环起，工具不再直接调 _Live._run）：自动关闭后线程自己退出，
  这里等录制序列稳定（收尾事件发完）再收工。
  JSON 不排序键：字段顺序、发布顺序变了都算差异。证明的是正常路径；停止和迟到结果由 tests/test_live_commit.py 证明。
"""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import runtime_baseline_mining as base  # noqa: E402

FRAME_SECONDS = 1.1
PAUSE_SECONDS = 0.3
MAX_FRAMES = 2000


class Clock:
    def __init__(self):
        self.t = time.time()

    def __call__(self):
        return self.t


class Recorder:
    """假悬浮窗 + 总线录制"""

    def __init__(self):
        self.seq: list[Any] = []

    def publish(self, kind, data):
        self.seq.append(["bus", kind, json.loads(json.dumps(data, default=str))])

    def hud(self):
        return self

    def set(self, section, text, rich=None):
        self.seq.append(["hud.set", section, text, rich])

    def clear(self, section):
        self.seq.append(["hud.clear", section])

    def note(self, text, secs=6):
        self.seq.append(["hud.note", text, secs])


def _patch(rec, tmp):
    import importlib

    # 全用 Any：这里就是要换模块属性
    bus: Any = importlib.import_module("astral_toolkit.app.bus")
    hud_state: Any = importlib.import_module("astral_toolkit.app.hud_state")
    paths: Any = importlib.import_module("astral_toolkit.core.paths")
    settings: Any = importlib.import_module("astral_toolkit.core.settings")
    goals: Any = importlib.import_module("astral_toolkit.tasks.goals")
    navigation: Any = importlib.import_module("astral_toolkit.tasks.navigation")
    system: Any = importlib.import_module("astral_toolkit.tasks.system")

    bus.publish = rec.publish
    for m in (hud_state, navigation, system):
        m._hud = rec.hud
    hud_state._off = lambda feature: None
    goals.goal_short = lambda force=False: {}
    settings.update = lambda **kw: None
    paths.log = lambda name: tmp / name
    paths.shots = lambda name: tmp


def _settle(rec):
    """等后台线程把收尾事件发完：录制序列连续几次长度不变就算稳定"""
    last, same = -1, 0
    while same < 3:
        time.sleep(0.005)
        n = len(rec.seq)
        same = same + 1 if n == last else 0
        last = n


def _drive(rec, frames, clock, front=None):
    """跑完一轮：frames 用完后喂空白帧，等它自己过期、自动关闭（_auto_off）；到上限还没停就按开关"""
    from PIL import Image
    from astral_toolkit.app.engines import live as live_mod
    from astral_toolkit.mining import screen
    from astral_toolkit.tasks import mining

    blank = Image.new("RGB", (1920, 1080))
    live = live_mod._Live()
    i = {"n": 0}

    def grab():
        n = i["n"]
        i["n"] += 1
        clock.t += FRAME_SECONDS
        if n >= MAX_FRAMES:
            live.stop_ev.set()
        item = frames[n] if n < len(frames) else blank
        if callable(item):  # 脚本里的动作（改配装）
            item(live)
            return blank
        return item

    def game_front():
        if front and front(i["n"]):
            clock.t += PAUSE_SECONDS
            i["n"] += 1
            return False
        return None

    screen.grab = grab
    screen.INTERVAL = 0
    mining._game_front = game_front
    live.start()
    while live.running():
        time.sleep(0.001)
    _settle(rec)
    return i["n"]


def _samples(rec, clock):
    from PIL import Image
    from astral_toolkit.mining import screen
    from astral_toolkit.mining.signals import find_signatures

    frames, used = [], []
    for p in sorted((ROOT / "tests" / "samples").iterdir()):
        if p.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            continue
        with Image.open(p) as f:
            img = f.convert("RGB")
        scan, _ = screen.analyse(img)
        if scan.mass is not None or find_signatures(img):
            frames += [img] * 6
            used.append(p.name)
    away_from = len(frames)
    rec.seq.clear()
    n = _drive(rec, frames, clock, front=lambda k: away_from <= k < away_from + 4)
    return {"样本": used, "帧数": n, "序列": list(rec.seq)}


def _scripted(rec, clock):
    from PIL import Image
    from astral_toolkit.mining import screen
    from astral_toolkit.mining.parse import Scan

    fixed = base._fixed_scans()
    a = next(s for k, s in fixed.items() if k.startswith("文本:"))
    b = Scan(
        rock="Gold",
        mass=9000,
        resistance=35,
        instability=6,
        total_scu=10.0,
        composition=[("Gold", 60.0, 500), ("Inert Materials", 40.0, None)],
    )
    half = Scan(
        rock="Gold",
        composition=[("Gold", 60.0, 500), ("Copper", 40.0, 500)],
    )  # 看得到面板却读不全：出「读不全」提示，下一个结果再收起
    cut = fixed["写死:面板被挡"]
    plan = [a] * 3 + [half] * 6 + [b] * 4 + ["gear"] + [b] * 3 + [cut] * 4
    frames, scans = [], {}
    for k, s in enumerate(plan):
        if s == "gear":
            frames.append(lambda live: setattr(live, "gear_rev", live.gear_rev + 1))
            continue
        img = Image.new("RGB", (1920, 1080), (10 + 15 * (k % 12), 20, 20))
        scans[id(img)] = s
        frames.append(img)

    def analyse(img):
        s = scans.get(id(img))
        screen.LAST_PANEL["cut"] = s is cut
        screen.LAST_RAW.update(t=time.time(), scan=["扫描结果"] if s else [], bag=[])
        return (s or Scan(), base.BAG if s else base.NO_BAG)

    screen.analyse = analyse
    screen.miss_reason = lambda img: "cut"
    rec.seq.clear()
    n = _drive(rec, frames, clock)
    return {"帧数": n, "序列": list(rec.seq)}


def collect():
    base._freeze_world()
    tmp = Path(tempfile.mkdtemp(prefix="at_live_baseline_"))
    rec = Recorder()
    _patch(rec, tmp)
    clock = Clock()
    time.time = clock
    results = {"样本": _samples(rec, clock), "写死": _scripted(rec, clock)}
    return {"git": base._git_head(), "results": results}


def _kinds(seq):
    out: dict[str, int] = {}
    for row in seq:
        key = row[1] if row[0] == "bus" else row[0]
        out[key] = out.get(key, 0) + 1
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="RT-B3 采矿助手发布序列基线")
    ap.add_argument("--out", required=True, help="输出 JSON 路径")
    a = ap.parse_args(argv)
    res = collect()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(
        json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    for name, r in res["results"].items():
        print(name, "帧数", r["帧数"], _kinds(r["序列"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

