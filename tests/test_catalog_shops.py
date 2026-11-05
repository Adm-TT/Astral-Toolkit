"""catalog/shops 的纯规则测试（乙：商店）。"""

from types import SimpleNamespace

from astral_toolkit.catalog import shops as catalog_shops
from astral_toolkit.contracts.textkeys import fold_en_loose


def _item(iid, name, cat="物品"):
    return (iid, name, cat, fold_en_loose(name))


def _row(buy=0.0, sell=0.0, shop="", place=""):
    return SimpleNamespace(
        price_buy=buy,
        price_sell=sell,
        shop_name=shop,
        place_text=place,
    )


def test_find_exact_folded_and_limit():
    rows = [
        _item(1, "Aurora"),
        _item(2, "Aurora LX"),
        _item(3, "Aurora MR"),
        _item(4, "Constellation"),
    ]
    assert catalog_shops.find(rows, ["Aurora"]) == [
        (1, "Aurora", "物品"),
        (2, "Aurora LX", "物品"),
        (3, "Aurora MR", "物品"),
    ]
    assert catalog_shops.find(rows, ["Aurora"], limit=2) == [
        (1, "Aurora", "物品"),
        (2, "Aurora LX", "物品"),
    ]
    # 折叠后相同（l 当 i）：Sol-ll 和 Sol-II 视为精确
    assert catalog_shops.find([_item(9, "Sol-II")], ["Sol-ll"]) == [
        (9, "Sol-II", "物品")
    ]


def test_find_close_cutoff_and_short_name():
    rows = [_item(1, "Aurora")]
    assert catalog_shops.find_close(rows, "Auror") == (1, "Aurora", "物品")
    assert catalog_shops.find_close(rows, "Auror", cutoff=0.95) is None
    assert catalog_shops.find_close(rows, "Auro") is None


def test_where_sorts_buy_ascending_and_sell_descending():
    rows = [
        _row(buy=30, sell=10, shop="B", place="P2"),
        _row(buy=20, sell=50, shop="A", place="P1"),
        _row(buy=0, sell=0, shop="C", place="P3"),
    ]
    buy, sell = catalog_shops.where(rows)
    assert buy == [(20, "A", "P1"), (30, "B", "P2")]
    assert sell == [(50, "A", "P1"), (10, "B", "P2")]


def test_nearest_same_place_and_price_tie():
    rows = [
        (10.0, 50.0, "离得近但贵", "A"),
        (10.0, 20.0, "同地点最便宜", "A"),
        (20.0, 10.0, "稍远便宜", "C"),
        (20.0, 30.0, "稍远贵", "B"),
    ]
    assert catalog_shops.nearest(rows, 3) == [
        (10.0, 20.0, "同地点最便宜", "A"),
        (20.0, 10.0, "稍远便宜", "C"),
        (20.0, 30.0, "稍远贵", "B"),
    ]


def test_base_names_and_variant_candidates():
    assert catalog_shops.base_names("Aurora Mk II") == ["Aurora"]
    rows = [
        _item(3, "Aurora MR"),
        _item(1, "Aurora"),
        _item(2, "Aurora LN"),
        _item(4, "Aurora Mk II"),
        _item(5, "Aurora LX"),
    ]
    got = catalog_shops.variant_candidates(rows, "Aurora", "Aurora Mk II")
    assert got == [
        (1, "Aurora", "物品"),
        (3, "Aurora MR", "物品"),
        (2, "Aurora LN", "物品"),
        (5, "Aurora LX", "物品"),
    ]


def test_variant_candidates_require_all_words():
    rows = [
        _item(1, "Drake Cutlass Blue"),
        _item(2, "Drake Cutlass Red"),
        _item(3, "Drake"),
        _item(4, "Cutlass"),
    ]
    got = catalog_shops.variant_candidates(rows, "Drake Cutlass", "Other")
    assert {iid for iid, _n, _c in got} == {1, 2}


def test_find_partial_matches_shorter_names_first():
    """只是包含查询词的，按英文名长短排（短的在前），不按原来的顺序"""
    rows = [_item(1, "Long Laser Name"), _item(2, "Laser X")]
    assert [r[1] for r in catalog_shops.find(rows, ["laser"])] == [
        "Laser X",
        "Long Laser Name",
    ]


def test_find_close_needs_five_letters():
    """折叠后不到 5 个字母不做近似匹配"""
    assert catalog_shops.find_close([_item(1, "Abcd")], "abcd") is None
    assert catalog_shops.find_close([_item(1, "Abcde")], "abcde") == (
        1,
        "Abcde",
        "物品",
    )
