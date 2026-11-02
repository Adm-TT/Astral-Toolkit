"""采矿结果计算（运行结构 RT-B1）：假输入下不碰任何数据、设置、文件，数值可以单独验"""

from types import SimpleNamespace
from typing import Any

from sc_mining.mining.analysis import MiningInputs, analyze, lots, station_bonus
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
        best_price=lambda m: (100, "城") if m != "Copper" else (0, None),
        station_bonus=lambda s: {},
        refined_plan=lambda bag: [("M", "S", 1234.0, 2.5, 10.0, 1.0)],
        refined_scu=lambda bag, station, method=None: {
            k: v * 0.5 for k, v in bag.items()
        },
        recommend=lambda mass, res, ins: [_plan()],
        quality_hints=lambda comp: ["提示"],
        mat_summary=lambda m, q=None: {"count": 1, "ok": q},
        goal_for=lambda *names: None,
        goal_text=lambda g, q, mine=(): f"缺 {g['en']} {len(mine)} 份",
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
        ("钨", 662, "高品质"),
        ("钨", 363, "低品质"),
        ("惰性物质", None, ""),
    ]
    assert rows[0]["scu"] == 2.0 and rows[0]["refined"] == 1.0 and amounts[0] == 1.0
    assert rows[2]["inert"] and rows[2]["refined"] is None and amounts[2] is None


def test_station_bonus_texts():
    minerals = {"Gold": 1.0, "Tungsten": 1.0}
    same = _inputs(station_bonus=lambda s: {"Gold": 3, "Tungsten": 3})
    assert station_bonus("S", minerals, same) == "+3%"
    diff = _inputs(station_bonus=lambda s: {"Gold": 3, "Tungsten": -2})
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

    empty = _inputs(refined_plan=boom, quality_hints=boom)
    only_inert = _scan(composition=[("Inert Materials", 100.0, None)])
    r = analyze(only_inert, ({}, None, None), empty)
    assert not r.refine and not r.craft and r.bag is None
