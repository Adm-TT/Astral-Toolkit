"""采矿结果计算（运行结构 RT-B1）：假输入下不碰任何数据、设置、文件，数值可以单独验"""

from types import SimpleNamespace
from typing import Any

from types import MappingProxyType

from sc_mining.mining.analysis import (
    MiningInputs,
    Rank,
    analyze,
    freeze,
    lots,
    station_bonus,
)
from sc_mining.mining.parse import Scan

ZH = {"Tungsten": "钨", "Gold": "金", "Copper": "铜"}


def _plan(gadget=None, breakable=True):
    return SimpleNamespace(
        names="头 A",
        gadget=gadget,
        short=lambda: "头 A｜功率 50%",
        summary=lambda: "总结",
        ratio=1.5 if breakable else 0.5,
        breakable=breakable,
        comfortable=breakable,
        throttle=0.5,
    )


def _inputs(**over):
    kw: dict[str, Any] = dict(
        at="12:00:00",
        mineral_zh=lambda m: ZH.get(m, m),
        method_zh=lambda m: f"方式{m}",
        station_zh=lambda s: f"站{s}",
        gadget_label=lambda g: f"工具{g}",
        goal_text=lambda g, q, mine=(): f"缺 {g['en']} {len(mine)} 份",
        prices={"Gold": (100, "城"), "Tungsten": (100, "城")},
        refineries={"S": ("星系", {})},
        loadout=None,
        refined_plan=lambda bag, prices=None, refineries=None: [
            ("M", "S", 1234.0, 2.5, 10.0, 1.0)
        ],
        refined_scu=lambda bag, station, method=None, refineries=None: {
            k: v * 0.5 for k, v in bag.items()
        },
        recommend=lambda mass, res, ins, loadout=None: [_plan()],
        craft_hints=("提示",),
        craft_mats=(),
        goal_targets=(),
        goals_complete=True,
    )
    kw.update(over)
    return MiningInputs(**kw)


def _scan(**over):
    kw: dict[str, Any] = dict(
        rock="Tungsten",
        mass=1000,
        resistance=4,
        instability=17.32,
        total_scu=20.0,
        difficulty="简单",
        composition=[
            ("Tungsten", 10.0, 662),
            ("Tungsten", 50.0, 363),
            ("Inert Materials", 40.0, None),
        ],
    )
    kw.update(over)
    return Scan(**kw)


def test_lots_rank_tier_and_refined():
    rows, amounts = lots(_scan(), ("M", "S"), _inputs())
    assert [(r["zh"], r["q"], r["rank"]) for r in rows] == [
        ("钨", 662, Rank.HIGH),
        ("钨", 363, Rank.LOW),
        (None, None, None),
    ]
    assert rows[0]["scu"] == 2.0 and rows[0]["refined"] == 1.0 and amounts[0] == 1.0
    assert rows[2]["inert"] and rows[2]["refined"] is None and amounts[2] is None


def test_station_bonus_texts():
    minerals = {"Gold": 1.0, "Tungsten": 1.0}
    same = _inputs(refineries={"S": ("星系", {"Gold": 3, "Tungsten": 3})})
    assert station_bonus("S", minerals, same) == "+3%"
    diff = _inputs(refineries={"S": ("星系", {"Gold": 3, "Tungsten": -2})})
    assert station_bonus("S", minerals, diff) == "金 +3%、钨 -2%"
    assert station_bonus("S", minerals, _inputs()) == ""


def test_analyze_numbers_and_bag():
    """结果里只有数和中文名：矿袋、精炼方案、卖到哪、方案全从输入来；石头没有矿就不查精炼和制造"""
    bag = ({"Gold": 1.5}, 1.5, 96.0)
    r = analyze(_scan(), bag, _inputs())
    assert r.rock == "钨" and r.at == "12:00:00" and not r.cut
    assert r.minerals == (("钨", "Tungsten", 12.0),)
    assert r.refine[0].value == 1234.0 and r.refine[0].yields == (("钨", 6.0),)
    assert r.sell == (("钨", "城"),) and r.craft == ("提示",)
    assert r.plans[0].throttle == 0.5 and r.plans[0].gadget_label == ""
    assert r.bag is not None and r.bag.used == 1.5 and r.bag.items == (("金", 1.5),)

    def boom(*a, **k):
        raise AssertionError("没有矿不该查")

    empty = _inputs(refined_plan=boom)
    only_inert = _scan(composition=[("Inert Materials", 100.0, None)])
    r = analyze(only_inert, ({}, None, None), empty)
    assert not r.refine and not r.craft and r.bag is None


def test_result_summaries():
    """悬浮窗要的汇总都在结果里算好：惰性占比（0.5% 门槛）、高低品质配对、按矿合计和排序"""
    r = analyze(_scan(), ({}, None, None), _inputs())
    assert r.inert_pct == 40.0
    assert [(h.zh, h.q, h.scu, h.low_q) for h in r.high_lots] == [("钨", 662, 2.0, 363)]
    assert [(g.zh, g.inert, g.pct) for g in r.composition] == [
        ("钨", False, 60.0),
        (None, True, 40.0),
    ]
    assert [(s.q, s.high) for s in r.composition[0].subs] == [(662, True), (363, False)]
    little = _scan(composition=[("Gold", 99.6, 500), ("Inert Materials", 0.4, None)])
    assert analyze(little, ({}, None, None), _inputs()).inert_pct is None


def test_composition_sort_ties_at_two_decimals_keep_order():
    """显示都是 30.00% 的两组，不因为相加的浮点误差换顺序"""
    scan = _scan(
        composition=[
            ("Gold", 30.0, 500),
            ("Tungsten", 10.1, 500),
            ("Tungsten", 19.9, 400),
        ]
    )
    r = analyze(scan, ({}, None, None), _inputs())
    assert [g.zh for g in r.composition] == ["金", "钨"]
    near = _scan(composition=[("Gold", 30.001, 500), ("Tungsten", 30.004, 500)])
    r = analyze(near, ({}, None, None), _inputs())
    assert [g.zh for g in r.composition] == ["金", "钨"]


def test_result_cannot_be_changed():
    target = {
        "en": "Tungsten",
        "zh": "",
        "short": 1,
        "unit": "SCU",
        "minq": 1,
        "goals": ["蓝图"],
    }
    inputs = _inputs(
        goal_targets=(("Tungsten", freeze(target)),),
        craft_mats=(("Tungsten", {"count": 1, "gates": [600]}),),
    )
    r = analyze(_scan(), ({}, None, None), inputs)
    assert isinstance(r.goals[0], MappingProxyType)
    assert isinstance(r.craft_mats[0], MappingProxyType)
    assert r.goals[0]["goals"] == ("蓝图",) and r.craft_mats[0]["gates"] == (600,)
    assert target["goals"] == ["蓝图"]


def test_freeze_detaches_from_source():
    src = {"a": [1, {"b": 2}]}
    got = freeze(src)
    src["a"][1]["b"] = 9
    assert got["a"][1]["b"] == 2 and isinstance(got["a"], tuple)
