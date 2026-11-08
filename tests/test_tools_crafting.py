"""制造：蓝图、混料、目标缺口（从 test_tools.py 拆出，CL-C3）"""

import pytest


def test_mix_plan_matches_guide_example():
    """攻略图里的例子：S1 绿柱石 0.14 SCU，860 的低料 + 967 的高料，按 902 混 → 低 0.085 + 高 0.055，高料占 39%"""
    from astral_toolkit.crafting import mix as c

    r = c.mix_plan(0.14, 900, [(860, 1), (967, 1)])
    assert r["ok"] and r["goal"] == 902
    assert [(p["q"], p["use"]) for p in r["plan"]] == [(860, 0.085), (967, 0.055)]
    assert r["avg"] >= 902 and round(r["high"] / 0.14, 2) == 0.39
    # 到不了、料不够、合箱
    assert not c.mix_plan(0.14, 980, [(860, 1), (967, 1)])["ok"]
    assert "材料不足" in c.mix_plan(2, 900, [(860, 1)])["msg"]
    m = c.mix_plan(0, 0, [(860, 1.0), (967, 0.2), (860, 0.5)])
    assert (
        m["ok"]
        and abs(m["avg"] - (860 * 1.5 + 967 * 0.2) / 1.7) < 1e-9
        and len(m["plan"]) == 2
    )


def test_mix_targets_from_blueprint():
    from astral_toolkit import crafting as c

    bp = next((b for b in c.blueprints() if b["n"] == "QuadraCell"), None)
    if bp is None:
        import pytest

        pytest.skip("没有制造数据")
    beryl = next(m for m in c.mix_targets(bp) if m["material"] == "Beryl")
    assert beryl["scu"] == 0.14 and beryl["steps"][-1]["q"] == 900


def test_craft_blueprint_dictionary():
    """制造页的蓝图字典：按类别 / 子类 / 部位 / 厂商筛选、分页，筛选项带数量"""
    import pytest
    from astral_toolkit import crafting

    if not crafting.blueprints():
        pytest.skip("没有制造数据")
    from astral_toolkit.tasks.goals import craft_browse, craft_detail

    r = craft_browse()
    assert r["total"] == len(crafting.blueprints()) and len(r["rows"]) == 60
    assert sum(c["count"] for c in r["cats"]) == r["total"] and any(
        c["label"] == "护甲" for c in r["cats"]
    )
    a = craft_browse(cat="fpsgear/armour")
    assert any(p["key"] == "头盔" for p in a["parts"]) and any(
        x["label"] == "战斗" for x in a["subs"]
    )
    h = craft_browse(cat="fpsgear/armour", part="头盔")
    assert h["total"] == next(p["count"] for p in a["parts"] if p["key"] == "头盔")
    assert all("头盔" in x["tags"] for x in h["rows"])
    more = craft_browse(cat="fpsgear/armour", offset=60)
    assert more["rows"] and more["rows"][0]["key"] != a["rows"][0]["key"]
    s2 = craft_browse(cat="vehiclegear/powerplant", sub="size2")
    assert s2["total"] and all("S2" in x["tags"].split(" · ") for x in s2["rows"])
    # CR-D1：船零件的尺寸 / 等级 / 类别筛选（窗口走 app.api），筛出来的份数和下拉里写的一样
    from astral_toolkit.app.api.crafting import craft_browse as api_browse

    for cat, group, arg in (
        ("vehiclegear/weapons", "sizes", "size"),
        ("vehiclegear/powerplant", "grades", "grade"),
        ("vehiclegear/powerplant", "clss", "cls"),
    ):
        got = api_browse(cat=cat)[group]
        assert got, (cat, group)
        for f in got:
            assert api_browse(cat=cat, **{arg: f["key"]})["total"] == f["count"]
    # 点一份能看详情
    assert "text" in craft_detail(h["rows"][0]["key"])


def test_craft_same_name_blueprints_distinct():
    """同名两份配方（比如 Main Powerplant）：列表编号不同，点开看到各自的材料（二审 2026-10-23 发现的 bug）"""
    import pytest
    from collections import Counter
    from astral_toolkit import crafting
    from astral_toolkit.tasks.goals import craft_browse, craft_detail

    dup = next(
        (n for n, c in Counter(b["n"] for b in crafting.blueprints()).items() if c > 1),
        None,
    )
    if not dup:
        pytest.skip("数据里没有同名蓝图")
    rows = [r for r in craft_browse(q=dup)["rows"] if r["key"].startswith(dup)]
    keys = [r["key"] for r in rows]
    assert len(set(keys)) == len(keys) >= 2 and all("配方" in r["tags"] for r in rows)
    texts = [craft_detail(k)["text"] for k in keys]
    assert len(set(texts)) == len(texts)
    assert [craft_detail(k)["key"] for k in keys] == keys
    # 以前存的目标只有名字：取同名第一份，不报错
    assert crafting.by_key(dup) is crafting.by_key(keys[0])


def test_craft_filter_by_mineral_and_item_hud_expires(monkeypatch):
    """扫描 / 矿物页「可制造 N 份蓝图」→ 制造页按这种矿筛选，带品质门槛的标出够不够；
    悬浮窗「物品」结果过一段时间自动收起（2026-10-23 用户：一直挂着不消失）"""
    import time as _t
    from astral_toolkit import crafting
    from astral_toolkit.tasks import goals as t_goals, trade as t_trade
    from astral_toolkit.app import hud_state

    if not crafting.blueprints():
        pytest.skip("没有制造数据")
    gated = next(
        (
            m
            for m in (
                "Titanium",
                "Riccite",
                "Agricium",
                "Quantainium",
                "Laranite",
                "Tungsten",
            )
            if crafting.mat_summary(m)["gated"]
        ),
        None,
    )
    for mat in ("Agricium", gated):
        if not mat:
            continue
        s = crafting.mat_summary(mat, 500)
        r = t_goals.craft_browse(mat=mat, mq=500)
        assert (
            r["total"] == s["count"] > 0
            and r["mat"]["en"] == mat
            and r["mat"]["count"] == s["count"]
        )
        zh = crafting.material_zh(mat)
        assert all(zh in x["need"] for x in r["rows"])
        assert sum(1 for x in r["rows"] if "ok" in x) <= s["gated"]
        assert (
            t_goals.craft_browse(mat=mat, cat=r["cats"][0]["key"])["total"]
            == r["cats"][0]["count"]
        )
    if gated:
        lo, hi = crafting.mat_summary(gated, 1), crafting.mat_summary(gated, 1000)
        assert lo["ok"] <= hi["ok"] == hi["count"]
    assert (
        "craft_count" in t_trade.mineral_info(name="Agricium")
        and t_trade.mineral_info(name="Agricium")["craft_count"] > 0
    )
    assert "mat" not in t_goals.craft_browse()
    # 物品悬浮窗定时收起；中途又写了新内容就按新内容重新计时
    hud = {}
    from astral_toolkit.tasks import (
        navigation as t_nav,
        system as t_sys,
    )

    _v = lambda: type(  # noqa: E731
        "H",
        (),
        {
            "set": lambda self, k, v, *rich: hud.__setitem__(k, v),  # noqa: E731
            "clear": lambda self, k: hud.pop(k, None),
        },
    )()
    for _m in (t_nav, t_sys, hud_state):
        monkeypatch.setattr(_m, "_hud", _v)
    hud_state._item_hud("A", 0.2)
    _t.sleep(0.4)
    assert "物品" not in hud
    hud_state._item_hud("B", 0.2)
    _t.sleep(0.1)
    hud_state._item_hud("C", 0.5)
    _t.sleep(0.25)
    assert hud.get("物品") == "C"  # B 的计时器到了，但已经换成 C，不收
    _t.sleep(0.4)
    assert "物品" not in hud


def test_goal_shortage_marked_everywhere(monkeypatch):
    """目标还缺的材料：扫描结果、悬浮窗、信号、物品页、矿物页都标出来；精炼后的量给 SCU 和 uSCU（2026-10-23 用户要求）"""
    from astral_toolkit import bootstrap
    from astral_toolkit.mining.parse import parse_scan
    from astral_toolkit.tasks import (
        count as t_count,
        goals as t_goals,
        hover as t_hover,
        mining as t_mining,
        stock as t_stock,
        trade as t_trade,
    )
    from astral_toolkit.crafting import goals as G

    gold = {
        "en": "Gold",
        "zh": "金",
        "short": 2.0,
        "unit": "SCU",
        "minq": 800,
        "goals": ["某蓝图"],
        "item": None,
    }
    tung = {
        "en": "Tungsten",
        "zh": "钨",
        "short": 0.5,
        "unit": "SCU",
        "minq": 1,
        "goals": ["某蓝图"],
        "item": None,
    }
    monkeypatch.setattr(G, "load", lambda: [{"id": "x"}])
    monkeypatch.setattr(
        G, "plan", lambda t=None, goals=None: {"goals": [], "shortfall": [gold, tung]}
    )
    _v = lambda: None  # noqa: E731
    for _m in (t_count, t_goals, t_stock, t_trade):
        monkeypatch.setattr(_m, "trade", _v)
    t_goals._SHORT["t"] = 0.0
    assert t_goals._gkey("Gold (Ore)") == t_goals._gkey("gold") and t_goals._gkey(
        "钨矿石"
    ) == t_goals._gkey("钨")
    assert (
        t_goals._goal_for("钨矿石")["en"] == "Tungsten"
        and t_goals._goal_for("Iron") is None
    )
    s = parse_scan(
        [
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
        ]
    )
    v = t_mining.scan_view(s)
    assert [g["en"] for g in v["goal"]] == ["Tungsten"] and v["goal"][0]["ok"]
    assert "🎯 目标缺少 钨 0.5 SCU" in v["hud"]
    assert "aUEC" in v["hud"] and "净值" not in v["hud"]  # 用户：净值就是 aUEC，写价格
    assert (
        "精炼后" in v["hud"]
        and "uSCU" in v["hud"]
        and v["refine"][0]["amount"]
        and v["refine"][0]["yield"]
    )
    r = v[
        "hud_rich"
    ]  # 1.6.65 悬浮窗按样图：矿物组成按矿合并，各品质从高到低，高品质那份标出来
    assert [c["name"] for c in r["comp"]] == ["钨", "砬兰石", "惰性物质"] and r["comp"][
        0
    ]["pct"] == "62.36%"
    assert [(q["q"], q["pct"], q["hi"]) for q in r["comp"][0]["subs"]] == [
        ("662", "12.95%", True),
        ("363", "49.41%", False),
    ]
    assert r["gain"][1][2] == "aUEC" and r["advice"]["heads"]
    from astral_toolkit.app.presenters.mining import scu_text

    assert scu_text(0.42) == "420,000 uSCU（0.420 SCU）" and scu_text(3.5).startswith(
        "3.50 SCU（3,500,000 uSCU）"
    )
    assert "当前 650 未达标" in t_goals._goal_text(
        gold, 650
    ) and "当前 900 已达标" in t_goals._goal_text(gold, 900)
    lines = t_goals._mark_goal_lines(
        ["信号 13,600 → 林登金 ×4", "信号 8,000 → 金 ×2", "信号 4,000 → 钨 ×1"]
    )
    assert (
        lines[0].startswith("信号")
        and lines[1].startswith("🎯")
        and lines[2].startswith("🎯")
    )
    assert t_trade.mineral_info(name="Gold")["goal"].startswith("🎯 目标缺少 金 2 SCU")
    assert t_hover._hover_lines(
        bootstrap._hover_links(), {"name": "Tungsten"}, "Tungsten", "钨"
    )[0].startswith("🎯")
    t_goals._SHORT["t"] = 0.0
