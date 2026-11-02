"""采矿结果呈现（运行结构 RT-B1）：同一份计算结果排成窗口 JSON 和悬浮窗内容"""

import json

from astral_toolkit.app.presenters import mining as P
from astral_toolkit.mining.analysis import analyze, freeze, lots
from tests.test_mining_analysis import _inputs, _plan, _scan


def test_lots_refined_text_uses_unrounded_amount():
    """row['refined'] 取 6 位小数，玩家看的文字按未取整的值写（拆分前就是这样）"""
    inputs = _inputs(refined_scu=lambda bag, s, m=None, **k: {"Gold": 0.1234565})
    rows, amounts = lots(_scan(composition=[("Gold", 50.0, 500)]), ("M", "S"), inputs)
    out = P.lot_rows(rows, amounts)
    assert out[0]["refined"] == round(0.1234565, 6)
    assert out[0]["refined_text"] == P.scu_text(0.1234565)


def test_goal_lookup_error_keeps_craft_and_drops_hud_lines():
    """目标查询中途出错：制造提示和已算出的目标留着，悬浮窗不写目标行"""
    gold = {"en": "Gold", "zh": "", "short": 1, "unit": "SCU", "minq": 1, "goals": []}
    scan = _scan(composition=[("Gold", 50.0, 500), ("Tungsten", 50.0, 500)])
    inputs = _inputs(goal_targets=(("Gold", gold),), goals_complete=False)
    r = analyze(scan, ({}, None, None), inputs)
    assert r.craft == ("提示",) and len(r.goals) == 1 and r.goal_lines == ()
    hud, rich = P.to_hud(r)
    assert "缺 Gold" not in hud and "缺 Gold 1 份" not in rich["minor"]
    assert P.to_view(r)["goal"][0]["en"] == "Gold"


def test_view_and_hud_layout():
    goal = {
        "en": "Tungsten",
        "zh": "钨",
        "short": 2,
        "unit": "SCU",
        "minq": 600,
        "goals": ["蓝图"],
    }
    bag = ({"Inert Materials": 0.3}, 0.3, 96.0)
    inputs = _inputs(
        goal_targets=(("Tungsten", goal),),
        recommend=lambda *a, **k: [_plan("sabir")],
    )
    r = analyze(_scan(), bag, inputs)
    hud, rich = P.to_hud(r)
    assert hud.split("\n") == [
        "钨｜1,000 kg｜抗性 4%｜不稳定 17.32",
        "头 A｜功率 50%",
        "精炼后 2.50 SCU（2,500,000 uSCU），价值 1,234 aUEC（建议：方式M，站S精炼）",
        "惰性 40%｜钨 品质 662：2.00 SCU",
        "缺 Tungsten 2 份",
    ]
    assert rich["advice"] == {"heads": "头 A + 工具sabir", "power": "建议功率 50%"}
    assert rich["minor"] == ["方式M · 站S", "缺 Tungsten 2 份"]
    assert [g["name"] for g in rich["comp"]] == ["钨", "惰性物质"]
    assert [s["q"] for s in rich["comp"][0]["subs"]] == ["662", "363"]
    v = P.to_view(r)
    assert v["lots_plan"] == "方式M，站S" and v["at"] == "12:00:00"
    assert v["sell"] == [{"name": "钨", "where": "城"}]
    assert v["goal"][0]["ok"] and v["bag"]["items"] == [
        {"name": "Inert Materials", "scu": 0.3}
    ]
    assert v["bag_text"] == "0.3/96 SCU\nInert Materials 0.3"
    assert [x["q"] for x in v["refine"][0]["lots"]] == [662, 363]


def test_cut_panel_only_plans():
    scan = _scan(
        total_scu=None,
        composition=[("Gold", 50.0, None), ("Inert Materials", 50.0, None)],
    )
    inputs = _inputs(recommend=lambda *a, **k: [_plan(breakable=False)])
    r = analyze(scan, ({}, None, None), inputs, cut=True)
    v = P.to_view(r)
    hud, rich = P.to_hud(r)
    assert v["cut"] and "FOV视野" in v["note"] and not v["refine"]
    assert v["plans"][0]["throttle"] is None and v["bag"] is None
    assert "面板被遮挡：仅计算破碎方案" in hud
    assert rich["advice"]["power"] == "满功率也无法破碎"


def test_view_rows_are_plain_and_texts_come_from_presenter():
    target = {
        "en": "Tungsten",
        "zh": "",
        "short": 1,
        "unit": "SCU",
        "minq": 1,
        "goals": ["蓝图"],
    }
    r = analyze(
        _scan(),
        ({}, None, None),
        _inputs(
            goal_targets=(("Tungsten", freeze(target)),),
            craft_mats=(("Tungsten", {"count": 1, "gates": [600]}),),
        ),
    )
    v = P.to_view(r)
    assert [x["rank"] for x in v["lots"]] == ["高品质", "低品质", ""]
    assert v["lots"][2]["zh"] == "惰性物质" and v["lots"][2]["tier"] == ""
    assert type(v["goal"][0]) is dict and v["goal"][0]["goals"] == ["蓝图"]
    assert v["craft_mats"][0]["gates"] == [600] and type(v["craft"]) is list
    json.dumps(v)
    v["goal"][0]["goals"].append("改")  # 窗口拿到的是新建的，改了不影响结果
    assert r.goals[0]["goals"] == ("蓝图",)


def test_plan_view_matches_to_view():
    r = analyze(_scan(), ({}, None, None), _inputs())
    assert P.to_view(r)["plans"][0] == P.plan_view(r.plans[0])


def test_tier_text():
    assert P._tier_text(None) == ""
    assert P._tier_text(("完美", 7, 7)) == "完美"
    assert P._tier_text(("D", 1, 7)) == "D 档（最低）"
    assert P._tier_text(("A", 7, 7)) == "A 档（最高）"
    assert P._tier_text(("B", 3, 7)) == "B 档"
