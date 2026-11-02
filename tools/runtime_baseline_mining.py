"""运行结构 RT-B1（采矿呈现）拆分前后的行为基线：固定输入跑 scan_view，完整返回值存 JSON；拆分后再跑一次逐字比对

用法（在项目根目录）：.venv\\Scripts\\python.exe -X utf8 tools\\runtime_baseline_mining.py --out <输出.json>
  输入：tests/samples 里能读出扫描面板的截图 + 几组写死的扫描 × cut 两种 × 目标清单（空 / 有一条）× 矿袋（有 / 没读到）。
  全程断网、时间写死；配装和目标在进程内换掉（settings.load / goals.goal_short），不写 userdata。
  JSON 不排序键：字段顺序变了也算差异。不合法的扫描只记异常类型（见 BAD_SCANS）。
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

BAG = ({"Inert Materials": 0.3}, 0.3, 96.0)
NO_BAG = ({}, None, None)
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
    from sc_mining.core import net, settings
    from sc_mining.navigation import starmap
    from sc_mining.update import uex

    def no_net(*a, **k):
        raise OSError("基线工具不联网")

    uex._get = no_net
    net.read = no_net
    starmap.read = no_net
    time.strftime = lambda *a, **k: "12:00:00"
    real = settings.load
    settings.load = lambda: {
        **real(),
        "mining_ship": SHIP,
        "mining_loadouts": {SHIP: LOADOUT},
    }


def _fixed_scans():
    from sc_mining.mining.parse import Scan, parse_scan

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
    from sc_mining.mining import screen

    out = {}
    for p in sorted((ROOT / "tests" / "samples").iterdir()):
        if p.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            continue
        try:
            with Image.open(p) as img:
                scan = screen.analyse(img.convert("RGB"))[0]
        except Exception:
            continue
        if scan and scan.mass is not None and scan.resistance is not None:
            out[f"样本:{p.name}"] = scan
    return out


def _goal_map(scan):
    """目标清单有一条：石头里第一种矿缺 2 SCU、品质门槛 600"""
    from sc_mining.tasks import goals

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


def _view(scan, bag, cut):
    from sc_mining.tasks import mining

    return mining.scan_view(scan, bag, cut=cut)


def collect():
    _freeze_world()
    from sc_mining.mining.parse import Scan
    from sc_mining.tasks import goals

    scans = {**_fixed_scans(), **_sample_scans()}
    out: dict[str, Any] = {"scan 清单": {k: repr(s) for k, s in scans.items()}}
    for name, scan in scans.items():
        for cut in (False, True):
            for bag_name, bag in (("矿袋", BAG), ("没读到矿袋", NO_BAG)):
                for goal_name, m in (("无目标", {}), ("有目标", _goal_map(scan))):
                    goals.goal_short = lambda force=False, _m=m: _m
                    key = f"{name}|cut={cut}|{bag_name}|{goal_name}"
                    out[key] = _view(scan, bag, cut)

    # 目标查询出错：制造提示留着，目标和悬浮窗里的目标行都没有（scan_view 里那段 try 的语义）
    def boom(force=False):
        raise RuntimeError("目标读不到")

    goals.goal_short = boom
    first = next(iter(_fixed_scans().values()))
    out["目标查询出错"] = _view(first, BAG, False)

    # 不合法的扫描：只比异常类型（调用方都先判过 mass，这条路线上用户看不到异常文字）
    goals.goal_short = lambda force=False: {}
    for label, kw in (
        ("没质量", {"mass": None, "resistance": 1, "instability": 1}),
        ("没抗性", {"mass": 1, "resistance": None, "instability": 1}),
        ("没不稳定性", {"mass": 1, "resistance": 1, "instability": None}),
    ):
        try:
            _view(Scan(rock="Gold", **kw), BAG, False)
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
