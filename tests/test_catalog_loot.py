"""catalog/loot 纯规则测试。"""

from types import SimpleNamespace

from astral_toolkit.catalog.loot import (
    PLACED,
    exact_candidates,
    group_info,
    is_variant,
    mine_groups,
    partial_hits,
    pick_exact,
    ship_groups,
    summary,
)


def _row(uuid, en="", zh="", cls="", norm_en=None, norm_zh=None, n=0, rarity="Common"):
    return SimpleNamespace(
        uuid=uuid,
        en=en or uuid,
        zh=zh or uuid,
        rarity=rarity,
        norm_en=en.lower() if norm_en is None else norm_en,
        norm_zh=zh if norm_zh is None else norm_zh,
        cls_lower=cls,
        n=n,
    )


def _detail_region(name, best, box_name, loc):
    return {
        "name": name,
        "best": best,
        "containers": [{"p": best, "loc": loc, "name": box_name}],
    }


def test_variant_filter():
    assert is_variant("item_ai_exclusive")
    assert is_variant("nodraw_screen")
    assert is_variant("gun_gungame")
    assert is_variant("item_debug")
    assert is_variant("item_lowpoly")
    assert is_variant("item_active")
    assert not is_variant("item_regular")


def test_exact_candidates_prefer_wiki_class_and_stable_sort():
    rows = [
        _row("v", "Gladius", "短剑", "item_ai_exclusive", n=100),
        _row("w", "Gladius", "短剑", "item_wiki", n=2),
        _row("r", "Gladius", "短剑", "item_regular", n=50),
    ]
    exact = exact_candidates(rows)
    assert exact == [
        ("v", "Gladius", "短剑", "Common", "item_ai_exclusive", 100),
        ("w", "Gladius", "短剑", "Common", "item_wiki", 2),
        ("r", "Gladius", "短剑", "Common", "item_regular", 50),
    ]
    assert pick_exact(exact, {"item_wiki"}) == [("w", "Gladius", "短剑", "Common")]
    assert [h[0] for h in pick_exact(exact, set())] == ["r", "w"]


def test_partial_hits_filter_variants_and_limit():
    rows = []
    for i in range(1, 7):
        rows.append(
            _row(
                f"p{i}",
                "Zeus",
                "宙斯",
                "item_ai_exclusive" if i == 2 else "item_regular",
                norm_en="zeusexplorer",
                norm_zh="宙斯探索头盔",
            )
        )
    hits = partial_hits(rows, "zeusex", "", limit=5)
    assert [h[0] for h in hits] == ["p1", "p3", "p4", "p5", "p6"]


def test_summary_sorts_best_and_marks_placed():
    detail = {
        "raw": "Ships.AEGS.Gladius",
        "regions": [
            {
                "name": "R1",
                "best": 0.1,
                "containers": [
                    {
                        "openp": 0.2,
                        "loc": "loc1a",
                        "name": "Lootable_Container_Crate",
                    },
                    {
                        "openp": 0.8,
                        "loc": "loc1b",
                        "name": "Lootable_Container_Big_Box",
                    },
                ],
            },
            {
                "name": "R2",
                "best": 0.4,
                "containers": [{"p": 0.2, "loc": "loc2", "name": "Gladius"}],
            },
        ],
    }
    assert summary(detail) == [
        ("R2", 0.4, f"loc2｜{PLACED}"),
        ("R1", 0.1, "loc1b｜Big Box"),
    ]


def test_group_info_groups_rounds_sorts_and_counts_more():
    detail = {
        "raw": "Ships.AEGS.Test",
        "regions": [
            _detail_region("R1", 0.1234567, "Lootable_Container_Crate", "L1"),
            _detail_region("R2", 0.1234568, "Lootable_Container_Crate", "L2"),
            _detail_region("R3", 0.5, "Lootable_Container_Big_Box", "L3"),
            _detail_region("R4", 0.01, "Lootable_Container_Low", "L4"),
        ],
    }
    result = group_info(detail, top=2)
    assert result is not None
    rows, more = result
    assert rows == [
        {"p": 0.5, "box": "Big Box", "regions": ["R3"], "placed": False},
        {
            "p": 0.123457,
            "box": "Crate",
            "regions": [
                "R2",
                "R1",
            ],  # 组内按 summary 的顺序：概率高的 R2 在前（和旧 info 一样）
            "placed": False,
        },
    ]
    assert more == 1


def test_mine_groups_merge_same_probability_and_location():
    best = {
        "A": (0.2, "箱"),
        "B": (0.2, "箱"),
        "C": (0.5, "地面"),
    }
    rows, more = mine_groups(best, top=1)
    assert rows == [{"p": 0.5, "box": "地面", "regions": ["C"]}]
    assert more == 2


def test_ship_groups_merge_and_count_more():
    rows, more = ship_groups([(10.0, "A"), (10.0, "B"), (5.0, "C")], top=1)
    assert rows == [{"p": 0.1, "box": "", "regions": ["A", "B"]}]
    assert more == 1


def test_summary_keeps_only_top_highest():
    """summary 按概率从高到低只留前 top 个地点"""
    d = {
        "raw": "X",
        "regions": [
            _detail_region("R1", 0.1, "Lootable_Container_A", "L1"),
            _detail_region("R2", 0.3, "Lootable_Container_B", "L2"),
            _detail_region("R3", 0.2, "Lootable_Container_C", "L3"),
        ],
    }
    assert [r[0] for r in summary(d, top=2)] == ["R2", "R3"]
