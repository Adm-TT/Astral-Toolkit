"""catalog/acquire：物品详情「怎么弄到」的组合规则（IQ-C2）。纯函数，不碰数据"""

from astral_toolkit.catalog import acquire as A


def test_pick_variants_skips_accessories_unless_item_is_one():
    cands = [
        (1, "MaxLift Tractor Beam Battery", "Attachments"),
        (2, "MaxLift Tractor Beam", "Tractor Beams"),
        (3, "MaxLift Tractor Beam Mk2", "Tractor Beams"),
        (4, "Other", "Misc"),
    ]
    assert [
        v[0] for v in A.pick_variants('MaxLift-II "Keelback" Tractor Beam', cands)
    ] == [2, 3]
    # 要找的这件本身就是电池：电池不算「配件」，照常推荐
    assert [v[0] for v in A.pick_variants("Keelback Battery", cands)] == [1, 2]
    assert A.pick_variants("x", []) == []


def test_nowhere_needs_exact_hit_without_any_source():
    hit = {"has_data": False, "loot": False}
    assert A.is_nowhere(hit, [], "")
    assert not A.is_nowhere(None, [], "")
    assert not A.is_nowhere({**hit, "has_data": True}, [], "")
    assert not A.is_nowhere(hit, ["Aurora"], "")
    assert not A.is_nowhere(hit, [], "维科洛兑换")


def test_shows_loot_skips_exact_hit_without_loot():
    assert A.shows_loot(True, None)
    assert A.shows_loot(True, {"loot": True})
    assert not A.shows_loot(True, {"loot": False})
    assert not A.shows_loot(False, None)


def test_name_and_category_fallbacks():
    assert A.name_and_category(["Arrow", "Missile"], 7, "x", "y") == (
        "Arrow",
        "Missile",
    )
    assert A.name_and_category(None, 7, "Arrow", "箭") == ("Arrow", "")
    assert A.name_and_category(None, 7, "", "箭") == ("箭", "")
    assert A.name_and_category(["ignored", "c"], None, "Arrow", "箭") == ("Arrow", "")


def test_desc_and_aka():
    assert A.desc_and_aka(None) == ("", [])
    assert A.desc_and_aka({"desc": None, "aka": None}) == ("", [])
    assert A.desc_and_aka({"desc": "说明", "aka": ("a", "b")}) == ("说明", ["a", "b"])


def test_here_sell_craft_and_wikelo_shapes():
    assert A.here_summary(None) is None
    assert A.here_summary({"label": "NB", "age": 125}) == {"label": "NB", "minutes": 2}
    # 不足 3 分钟按 2 分钟算（往下取整）
    assert A.here_summary({"label": "NB", "age": 179}) == {"label": "NB", "minutes": 2}
    assert A.sell_summary([]) is None
    assert A.sell_summary([(9000, "Shop", "Place"), (100, "B", "C")]) == {
        "price": 9000,
        "shop": "Shop",
        "place": "Place",
    }
    bp = {"d": 1, "src": [("M1", 1), ("M2", 2), ("M3", 3), ("M4", 4)], "nsrc": 4}
    assert A.craft_summary(bp, "k", "名") == {
        "key": "k",
        "name": "名",
        "unlocked": True,
        "missions": ["M1", "M2", "M3"],
        "nsrc": 4,
    }
    assert A.craft_summary({**bp, "d": 0}, "k", "名")["unlocked"] is False
    uses = [
        ({"t": f"T{i}", "rz": "", "rewards": ["R1", "R2", "R3"]}, i, "SCU")
        for i in range(10)
    ]
    rows = A.wikelo_rows(uses)
    assert len(rows) == 8 and rows[0] == {
        "title": "T0",
        "q": 0,
        "u": "SCU",
        "reward": "R1、R2",
    }
    assert (
        A.wikelo_rows([({"t": "T", "rz": "直接奖励", "rewards": ["R"]}, 1, "")])[0][
            "reward"
        ]
        == "直接奖励"
    )


def test_empty_facts_keys_in_order_and_fresh_lists():
    d = A.empty_facts("n", "z", "c", 1, True, ["s"], "h")
    assert list(d) == [
        "name",
        "zh",
        "category",
        "id",
        "here",
        "buyable",
        "buy",
        "buy_total",
        "variants",
        "sell",
        "loot",
        "wikelo",
        "nowhere",
        "craft",
        "desc",
        "aka",
        "ships",
        "how",
    ]
    assert d["nowhere"] is True and d["ships"] == ["s"] and d["how"] == "h"
    assert (
        d["here"] is None
        and d["sell"] is None
        and d["loot"] is None
        and d["craft"] is None
    )
    assert d["buyable"] is False and d["buy_total"] == 0
    d["buy"].append(1)
    d["variants"].append(1)
    d2 = A.empty_facts("n", "z", "c", 1, True, ["s"], "h")
    assert (
        d2["buy"] == []
        and d2["variants"] == []
        and d2["wikelo"] == []
        and d2["aka"] == []
    )


# ---------------------------------------------------------------- dev 拆分①（2026-11-09）从 tasks/catalog_queries/acquire 搬来的规则
def test_buy_rows_rules():
    inf = float("inf")
    assert A.nearest_usable([(1200.0, 10, "店", "地")]) is True
    assert (
        A.nearest_usable([(inf, 10, "店", "地")]) is False
    )  # 不在一个星系：算不出距离
    assert A.nearest_usable([]) is False
    assert A.near_rows([(1200.0, 10, "店", "地")]) == [
        {"dist_m": 1200.0, "price": 10, "shop": "店", "place": "地"}
    ]
    buy = [(5, "甲", "A"), (6, "乙", "B"), (7, "丙", "C"), (8, "丁", "D")]
    rows = A.cheapest_rows(buy, 3)
    assert [r["shop"] for r in rows] == ["甲", "乙", "丙"]
    assert all(r["dist_m"] is None for r in rows)


def test_exact_id_folds_case_space_and_l_for_i():
    hits = [(1, "Ignite II Missile", "M"), (2, "Ignite III Missile", "M")]
    assert A.exact_id(hits, "ignite ii missile") == 1
    assert A.exact_id(hits, "IgniteIl Missile") == 1  # l 当 I
    assert A.exact_id(hits, "Ignite IV Missile") is None
    assert A.exact_id([], "x") is None


def test_material_facts():
    assert A.ore_base("Quantainium (Raw)") == "Quantainium"
    assert A.ore_base("Gold") == "Gold"
    assert A.mine_fact(0.4, "大熊星", "Carinite (Pure)") == {
        "where": "大熊星",
        "pct": 0.4,
        "pure": True,
    }
    assert A.loot_fact(None) is None
    assert A.loot_fact({"groups": []}) is None
    d = {
        "groups": [{"regions": ["甲"], "box": "箱", "p": 0.1}],
        "more": 1,
        "note": "说明",
    }
    assert A.loot_fact(d) == {
        "regions": ["甲"],
        "more": True,
        "mine": False,
        "note": "说明",
        "box": "箱",
        "placed": False,
        "p": 0.1,
    }
