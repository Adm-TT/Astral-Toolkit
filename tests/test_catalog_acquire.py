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
    assert A.here_summary({"label": "NB", "age": 179})["minutes"] == 2  # 往下取整
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
