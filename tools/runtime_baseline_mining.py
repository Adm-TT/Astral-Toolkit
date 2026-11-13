"""运行结构 RT-B1（采矿呈现）拆分前后的行为基线：固定输入跑 scan_view，完整返回值存 JSON；拆分后再跑一次逐字比对

用法（在项目根目录）：.venv\\Scripts\\python.exe -X utf8 tools\\runtime_baseline_mining.py --out <输出.json>
  输入：tests/samples 里能读出扫描面板的截图 + 几组写死的扫描 × cut 两种 × 目标清单（空 / 有一条）。
  （矿袋 2026-11-08 删了：以前还乘「矿袋有 / 没读到」两种，键里带「|矿袋|」「|没读到矿袋|」，和旧基线比时去掉这一段）
  全程断网、时间写死；配装和目标在进程内换掉（settings.load / goals.goal_short）。
  在 worktree 里跑：主仓库目录跑时 settings.load 可能迁移写回开发目录的 userdata/settings.json，paths 导入时也会建 userdata 目录。
  JSON 不排序键：字段顺序变了也算差异。不合法的扫描只记异常类型。旧 scan_view 只在基线提交上有：比对时把本工具拷过去出 before。
  RT-B2 加了 manual_scan 一组，和「语义变化:」开头的一组：输入取好之后价格 / 精炼站 / 配装被改，旧代码读计算那一刻的值，
  新代码读 collect_inputs 那一刻的快照，这组前后不同是有意的，比对时单列。
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SHIP = "mole"
LOADOUT = {
    "heads": [
        ["helix_ii", ["rieger_c3", "focus_iii"]],
        ["hofstede_s2", ["torrent_ii"]],
        ["klein_s2", []],
    ],
    "crew": 3,
}
TEXT_SCANS = {
    "两品质带惰性": [
        "扫描结果",
        "钨矿石",
        "质量： 44336",
        "抗性： 4% ",
        "不稳定性： 17.32",
        "组成 23.68 SCU",
        "6.55% 兰石原矿 510",
        "12.95% 钨矿石 662",
        "49.41% 钨矿石 363",
        "31.07% 情性物质 。",
    ],
}


def _git_head():
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except Exception:
        return ""


def _freeze_world():
    """断网、时间写死、配装写死"""
    from astral_toolkit import gamedata
    from astral_toolkit.core import net, settings
    from astral_toolkit.update import uex

    def no_net(*a, **k):
        raise OSError("基线工具不联网")

    uex._get = no_net
    net.read = no_net
    gamedata.ensure()  # 先建好库：建库文件名要用真实时间，写死后冷启动会建库失败
    time.strftime = lambda *a, **k: "12:00:00"
    real = settings.load
    settings.load = lambda: {
        **real(),
        "mining_ship": SHIP,
        "mining_loadouts": {SHIP: LOADOUT},
    }


def _fixed_scans():
    from astral_toolkit.mining.parse import Scan, parse_scan

    out = {f"文本:{k}": parse_scan(v) for k, v in TEXT_SCANS.items()}
    out["写死:面板被挡"] = Scan(
        rock="Ouratite",
        mass=745,
        resistance=20,
        instability=8.2,
        total_scu=None,
        difficulty="简单",
        composition=[
            ("Ouratite", 2.79, None),
            ("Ouratite", 5.04, None),
            ("Agricium", 14.52, None),
            ("Inert Materials", 77.64, None),
        ],
    )
    out["写死:三档品质和未知品质"] = Scan(
        rock="Gold",
        mass=9000,
        resistance=35,
        instability=60.5,
        total_scu=12.5,
        difficulty="困难",
        composition=[
            ("Gold", 10.0, 1000),
            ("Gold", 12.5, 600),
            ("Gold", 7.5, 150),
            ("Copper", 20.0, None),
            ("", 5.0, None),
            ("Inert Materials", 45.0, None),
        ],
    )
    out["写死:破不开"] = Scan(
        rock="Quantainium",
        mass=900000,
        resistance=95,
        instability=500,
        total_scu=0.4,
        difficulty="",
        composition=[("Quantainium", 100.0, 777)],
    )
    return out


def _sample_scans():
    from PIL import Image
    from astral_toolkit.mining import screen

    out = {}
    for p in sorted((ROOT / "tests" / "samples").iterdir()):
        if p.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            continue
        try:
            with Image.open(p) as img:
                scan = screen.analyse(img.convert("RGB"))
        except Exception:
            continue
        if scan and scan.mass is not None and scan.resistance is not None:
            out[f"样本:{p.name}"] = scan
    return out


def _goal_map(scan):
    """目标清单有一条：石头里第一种矿缺 2 SCU、品质门槛 600"""
    from astral_toolkit.tasks import goals

    en = next(
        (n for n, _, _ in scan.composition if n and n != "Inert Materials"), "Gold"
    )
    t = {
        "en": en,
        "zh": "",
        "short": 2.0,
        "unit": "SCU",
        "minq": 600,
        "goals": ["某蓝图"],
        "item": None,
    }
    return {goals._gkey(en): t}


def _view(scan, cut):
    from astral_toolkit.tasks import mining

    return mining.scan_view(scan, cut=cut)


def _branch_cases(out, Scan, goals):
    """真实数据走不到的分支：临时改精炼站表 / 方案 / 目标，跑完还原"""
    from astral_toolkit.mining import data, laser

    copper = Scan(
        rock="Gold",
        mass=9000,
        resistance=35,
        instability=6,
        total_scu=10.0,
        composition=[("Gold", 50.0, 500), ("Copper", 50.0, 500)],
    )
    no_goal = lambda force=False: {}  # noqa: E731
    goals.goal_short = no_goal
    saved = dict(data.REFINERIES)
    try:
        for k, (sys_, _) in saved.items():
            data.REFINERIES[k] = (sys_, {})
        out["分支:精炼站加成为空"] = _view(copper, False)
        for k, (sys_, _) in saved.items():
            data.REFINERIES[k] = (sys_, {"Copper": -100})
        out["分支:某份精炼后为 0"] = _view(copper, False)
    finally:
        data.REFINERIES.update(saved)
    out["分支:卖价无收购"] = _view(
        Scan(
            rock="NotAnOre",
            mass=9000,
            resistance=35,
            instability=6,
            total_scu=10.0,
            composition=[("NotAnOre", 100.0, 500)],
        ),
        False,
    )
    out["分支:高品质但总 SCU 读不到"] = _view(
        Scan(
            rock="Gold",
            mass=9000,
            resistance=35,
            instability=6,
            total_scu=None,
            composition=[("Gold", 30.0, 800), ("Gold", 30.0, 600), ("Gold", 40.0, 300)],
        ),
        True,
    )
    real = laser.recommend
    laser.recommend = lambda *a, **k: []
    try:
        out["分支:没有方案"] = _view(copper, False)
    finally:
        laser.recommend = real
    t = {
        "en": "Gold",
        "zh": "目标自带名",
        "short": 1.5,
        "unit": "",
        "minq": 1,
        "goals": ["某蓝图"],
        "item": None,
    }
    goals.goal_short = lambda force=False: {goals._gkey("Gold"): t}
    out["分支:目标 minq≤1 且自带中文名"] = _view(copper, False)
    goals.goal_short = no_goal


def _manual_cases(out):
    """手动输入：只算破碎方案；不合法的只记异常类型"""
    from astral_toolkit.tasks import mining

    manual: Any = mining.manual_scan  # 故意也传字符串，和接口层一样
    for label, args in (
        ("轻松", (1000, 10, 5)),
        ("贴工具", (9000, 35, 60.5)),
        ("难度高", (44336, 4, 170)),
        ("字符串数字", ("5000", "20", "10")),
        ("破不开", (900000, 95, 500)),
        ("抗性 100", (9000, 100, 0)),
    ):
        out[f"手动:{label}"] = manual(*args)
    for label, args in (
        ("质量 0", (0, 10, 5)),
        ("抗性超范围", (1000, 101, 5)),
        ("不稳定性为负", (1000, 10, -1)),
        ("质量非数字", ("abc", 10, 5)),
    ):
        try:
            manual(*args)
            out[f"手动:{label}"] = "没有异常"
        except Exception as e:
            out[f"手动:{label}"] = type(e).__name__


def _timing_cases(out, Scan):
    """语义变化（有意，RT-B2）：输入取好之后全局表 / 设置被改"""
    from astral_toolkit.app.presenters import mining as present
    from astral_toolkit.core import settings
    from astral_toolkit.mining import analysis, data
    from astral_toolkit.tasks import mining

    scan = Scan(
        rock="Gold",
        mass=9000,
        resistance=35,
        instability=6,
        total_scu=10.0,
        composition=[("Gold", 100.0, 500)],
    )

    def show(inputs):
        v = present.to_view(analysis.analyze(scan, inputs))
        return {"refine": v["refine"], "sell": v["sell"], "plans": v["plans"]}

    inputs = mining.collect_inputs(scan)
    prices = data.CITY_PRICES
    data.CITY_PRICES = {**prices, "Gold": {"Levski": 999999}}
    try:
        out["语义变化:取输入后矿价被改"] = show(inputs)
    finally:
        data.CITY_PRICES = prices

    inputs = mining.collect_inputs(scan)
    saved = dict(data.REFINERIES)
    try:
        for k, (sys_, _) in saved.items():
            data.REFINERIES[k] = (sys_, {"Gold": 50})
        out["语义变化:取输入后精炼站被改"] = show(inputs)
    finally:
        data.REFINERIES.update(saved)

    inputs = mining.collect_inputs(scan)
    load = settings.load
    other = {"heads": [["klein_s2", []], ["klein_s2", []], ["klein_s2", []]], "crew": 1}
    settings.load = lambda: {**load(), "mining_loadouts": {SHIP: other}}
    try:
        out["语义变化:取输入后配装被改"] = show(inputs)
    finally:
        settings.load = load


def collect():
    _freeze_world()
    from astral_toolkit.mining.parse import Scan
    from astral_toolkit.tasks import goals

    scans = {**_fixed_scans(), **_sample_scans()}
    out: dict[str, Any] = {"scan 清单": {k: repr(s) for k, s in scans.items()}}
    for name, scan in scans.items():
        for cut in (False, True):
            for goal_name, m in (("无目标", {}), ("有目标", _goal_map(scan))):
                goals.goal_short = lambda force=False, _m=m: _m
                key = f"{name}|cut={cut}|{goal_name}"
                out[key] = _view(scan, cut)

    # 目标查询出错：制造提示留着，目标和悬浮窗里的目标行都没有（scan_view 里那段 try 的语义）
    def boom(force=False):
        raise RuntimeError("目标读不到")

    goals.goal_short = boom
    first = next(iter(_fixed_scans().values()))
    out["目标查询出错"] = _view(first, False)

    _branch_cases(out, Scan, goals)
    _manual_cases(out)
    goals.goal_short = lambda force=False: {}
    _timing_cases(out, Scan)

    # 不合法的扫描：只比异常类型（调用方都先判过 mass，这条路线上用户看不到异常文字）
    goals.goal_short = lambda force=False: {}
    for label, kw in (
        ("没质量", {"mass": None, "resistance": 1, "instability": 1}),
        ("没抗性", {"mass": 1, "resistance": None, "instability": 1}),
        ("没不稳定性", {"mass": 1, "resistance": 1, "instability": None}),
    ):
        try:
            _view(Scan(rock="Gold", **kw), False)
            out[f"不合法:{label}"] = "没有异常"
        except Exception as e:
            out[f"不合法:{label}"] = type(e).__name__
    return {"git": _git_head(), "results": out}


def main(argv=None):
    ap = argparse.ArgumentParser(description="RT-B1 采矿呈现拆分前后的行为基线")
    ap.add_argument("--out", required=True, help="输出 JSON 路径")
    a = ap.parse_args(argv)
    res = collect()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(
        json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    print(f"基线写到 {a.out}：{len(res['results'])} 项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
