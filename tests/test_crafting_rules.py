"""制造纯规则（CR-B2）的纯度和注入测试。

只测新拆出的 labels / classify / materials / quality / mix / listing / reverse：
不碰库、不碰文件、不碰汉化包，也不重复黄金测试已经锁住的旧接口输出。
"""

from types import SimpleNamespace

from astral_toolkit.crafting import (
    classify,
    labels,
    listing,
    materials,
    mix,
    quality,
    reverse,
)


def _bp(n, z, g, t, s, u, m, sec, d, slots, src=None, nsrc=0):
    return {
        "n": n,
        "z": z,
        "g": g,
        "t": t,
        "s": s,
        "u": u,
        "m": m,
        "sec": sec,
        "d": d,
        "slots": slots,
        "src": src or [],
        "nsrc": nsrc,
    }


STATS_BP = _bp(
    "Test Widget",
    "测试部件",
    "fpsgear",
    "weapons",
    "rifle",
    "uuid-stats",
    "MakerA",
    120,
    True,
    [
        (
            "Barrel",
            [("r", "OreA", 5, 1)],
            [
                ("Impact Force", 0, 500, 1.0, 1.2, False),
                ("Impact Force", 500, 1000, 1.2, 1.5, False),
            ],
        ),
        (
            "Cabling",
            [("r", "OreA", 2, 1)],
            [("Fire Rate", 0, 1000, 0.9, 1.1, False)],
        ),
    ],
)

GATED_BP = _bp(
    "Gated Component",
    "门槛部件",
    "vehiclegear",
    "powerplant",
    "size1",
    "uuid-gated",
    "GateCo",
    90,
    False,
    [
        (
            "Core",
            [("r", "OreA", 4, 500)],
            [("Power Pips", 500, 1000, 1, 2, True)],
        )
    ],
)

HELMET_BP = _bp(
    "Test Helmet",
    "测试头盔",
    "fpsgear",
    "armour",
    "combat",
    "uuid-helmet",
    "MakerA",
    60,
    False,
    [("Plating", [("r", "OreB", 2, 1)], [])],
)

LASER_BP = _bp(
    "Test Laser",
    "测试激光",
    "vehiclegear",
    "mininglaser",
    "size2",
    "uuid-laser",
    "Shubin",
    300,
    True,
    [
        (
            "Emitter",
            [("i", "LaserPart", 1, 1)],
            [("Impact Force", 0, 1000, 0.8, 1.2, False)],
        ),
        (
            "Bus Bars",
            [("i", "LaserPart", 1, 1)],
            [("Impact Force", 0, 1000, 0.9, 1.3, False)],
        ),
    ],
)


def _mat_zh(name):
    return {"OreA": "注入矿A", "OreB": "注入矿B", "LaserPart": "注入激光件"}.get(
        name, name
    )


def _block_io(monkeypatch):
    from astral_toolkit.core import i18n
    from astral_toolkit.crafting import itemstats
    from astral_toolkit.gamedata import crafting as gd_crafting
    from astral_toolkit.mining import quality_tiers

    def boom(*args, **kwargs):
        raise AssertionError("纯规则不该触发查询 / 建库 / 汉化")

    for mod, names in (
        (
            gd_crafting,
            ("catalog", "cached", "for_item", "containing", "using_material"),
        ),
        (quality_tiers, ("tiers",)),
        (itemstats, ("base_value", "tags", "version")),
        (i18n, ("mineral_zh",)),
    ):
        for name in names:
            monkeypatch.setattr(mod, name, boom)


def test_quality_rules_are_pure_and_injected(monkeypatch):
    _block_io(monkeypatch)

    calls = []

    def base_value(uuid, key):
        calls.append((uuid, key))
        return 100.0, "U"

    st = quality.stats(STATS_BP, {0: 500}, base_value)
    assert calls == [
        ("uuid-stats", "weapon_damage"),
        ("uuid-stats", "weapon_firerate"),
    ]
    assert st["missing"] == ["线缆"]
    impact = st["props"][0]
    assert impact["name"] == "冲击力"
    assert impact["base"] == 100.0 and impact["unit"] == "U"
    assert impact["now"] == 120.0 and impact["now_best"] == 150.0
    assert impact["delta"] == 0.2 and impact["best"] == 0.5
    assert impact["worst"] == 0.0
    assert impact["text"] == "+20.00%"
    assert impact["slots"] == [{"slot": "枪管", "idx": 0, "q": 500, "part": 0.2}]
    fire = st["props"][1]
    assert fire["now"] == 100.0 and fire["now_best"] == 110.0
    assert fire["text"] == "+0.00%"

    eff = quality.effect(STATS_BP, {0: 500}, _mat_zh)
    assert len(eff) == 1
    first = eff[0]
    assert first["slot"] == "枪管" and first["material"] == "注入矿A"
    assert first["q"] == 500 and first["minq"] == 0 and first["ok"] is True
    prop = first["props"][0]
    assert prop["name"] == "冲击力"
    assert prop["now"] == 1.2 and prop["best"] == 1.5 and prop["worst"] == 1.0
    assert prop["pos"] == 0.4 and prop["next_gate"] is None
    assert prop["text"] == "冲击力 +20.0%（最好 +50.0%）"

    assert quality.laser_total(LASER_BP) == (
        "激光功率合计：发射器 + 汇流排 两个槽的加成相加，品质都 0 时 ×0.70、"
        "都 500 时 ×1.10（和商店买的一样）、都 1000 时 ×1.50。"
        "「采矿助手」页的配置里可以填自造矿头的品质，破碎方案按自造的功率算"
    )
    laser = quality.laser_total(LASER_BP, {0: 1000, 1: 500})
    assert laser == {
        "name": "激光功率",
        "mult": 1.3,
        "text": "激光功率合计 +30.0%（发射器 +20.0% + 汇流排 +10.0%）",
    }

    curves = quality.curves_for(lambda: [STATS_BP, LASER_BP], "OreA")
    assert len(curves) == 2
    impact_key = (
        "Impact Force",
        ((0, 500, 1.0, 1.2, False), (500, 1000, 1.2, 1.5, False)),
    )
    fire_key = ("Fire Rate", ((0, 1000, 0.9, 1.1, False),))
    assert curves[impact_key] == {"个人武器"}
    assert curves[fire_key] == {"个人武器"}

    def curves_of(name):
        assert name == "OreA"
        return {impact_key: {"个人武器"}}

    def uses_of(name):
        assert name == "OreA"
        return [({}, 1, 500), ({}, 1, 900)]

    hints = quality.quality_hints(
        [("OreA", 50, 600), ("Inert Materials", 20, 1000), ("OreB", 20, None)],
        curves_of,
        uses_of,
        _mat_zh,
    )
    assert hints == [
        "注入矿A 品质 600（中，线性属性约达最好效果的 60%）："
        "有品质门槛的蓝图够做 1/2 份"
    ]


def test_material_and_mix_rules_are_pure_and_injected(monkeypatch):
    _block_io(monkeypatch)

    assert materials.needs(STATS_BP, "OreA") == [(5, 1), (2, 1)]
    used = []

    def using(mineral):
        used.append(mineral)
        return [STATS_BP, GATED_BP]

    assert materials.mat_summary(using, "OreA") == {
        "count": 2,
        "ok": None,
        "gated": 1,
        "gates": [500],
        "gated_ok": None,
    }
    assert materials.mat_summary(using, "OreA", 600) == {
        "count": 2,
        "ok": 2,
        "gated": 1,
        "gates": [500],
        "gated_ok": 1,
    }
    assert materials.uses(using, "OreA") == [
        (STATS_BP, 5, 1),
        (STATS_BP, 2, 1),
        (GATED_BP, 4, 500),
    ]
    assert used == ["OreA", "OreA", "OreA"]

    res = mix.mix_plan(10, 900, [(1000, 10), (800, 10)])
    assert res["ok"] is True
    assert res["goal"] == 902.0
    assert [(p["q"], p["have"]) for p in res["plan"]] == [
        (800.0, 10.0),
        (1000.0, 10.0),
    ]
    # 低品质料最多能用 4.9，_floor3 往下取到 0.001 → 4.899，剩下的用高品质料补
    assert [p["use"] for p in res["plan"]] == [4.899, 5.101]
    assert abs(res["avg"] - 902.02) < 1e-9
    assert res["total"] == 10.0
    assert res["high"] == 5.101
    assert res["best"] == 1000.0
    assert res["msg"] == "按 902 混合：平均 902.0，高品质材料 5.101 SCU（占 51%）"

    assert mix.mix_targets(GATED_BP, _mat_zh) == [
        {
            "slot": "核心",
            "material": "OreA",
            "zh": "注入矿A",
            "scu": 4,
            "min": 500,
            "steps": [{"q": 500, "text": "能量格 +1"}],
        }
    ]


def test_listing_reverse_and_classify_rules_are_pure(monkeypatch):
    _block_io(monkeypatch)

    exact = _bp(
        "Test Widget", "测试部件", "fpsgear", "weapons", "rifle", "u1", "M", 1, True, []
    )
    short = _bp(
        "A Test Widget",
        "短测试部件",
        "fpsgear",
        "weapons",
        "rifle",
        "u2",
        "M",
        1,
        True,
        [],
    )
    long = _bp(
        "Long Test Widget",
        "长测试部件",
        "fpsgear",
        "weapons",
        "rifle",
        "u3",
        "M",
        1,
        True,
        [],
    )
    assert listing.search_rank([long, exact, short], "testwidget", 2) == [exact, short]

    brow = listing.browse(lambda: [STATS_BP, HELMET_BP, GATED_BP], mat="OreA")
    assert [b["n"] for b in brow["rows"]] == ["Gated Component", "Test Widget"]
    assert brow["total"] == 2
    assert brow["cats"][0] == {
        "key": "fpsgear/weapons",
        "label": "个人武器",
        "count": 1,
    }
    assert brow["subs"] == [
        {"key": "rifle", "label": "突击步枪", "count": 1},
        {"key": "size1", "label": "S1", "count": 1},
    ]
    assert brow["parts"] == []

    other_armor = _bp(
        "Mystery Suit", "神秘服", "fpsgear", "armour", "combat", "u4", "M", 1, False, []
    )
    assert classify.part_of(HELMET_BP) == "头盔"
    assert classify.part_of(STATS_BP) == ""
    assert classify.part_of(other_armor) == "其他"
    assert classify.facet(["a", "b", "a", ""], lambda x: x) == [
        {"key": "a", "count": 2},
        {"key": "b", "count": 1},
    ]

    tokens = [
        SimpleNamespace(text="冲击力：+17.5%", box=(0, 40, 0, 16)),
        SimpleNamespace(text="操控：-2", box=(10, 10, 0, 16)),
        SimpleNamespace(text="后坐力", box=(0, 10, 0, 16)),
        SimpleNamespace(text="射速：200rpm", box=(0, 70, 0, 16)),
    ]
    assert reverse.parse_mods(tokens) == [
        ("后坐力操控", -2.0, False, "Recoil Handling"),
        ("冲击力", 17.5, True, "Impact Force"),
    ]

    solve_bp = _bp(
        "Solve",
        "反推",
        "fpsgear",
        "weapons",
        "rifle",
        "uuid-solve",
        "M",
        1,
        True,
        [
            (
                "Barrel",
                [("r", "OreA", 1, 1)],
                [("Impact Force", 0, 1000, 0.8, 1.2, False)],
            )
        ],
    )
    tier_calls = []

    def tiers(name):
        tier_calls.append(name)
        return (0, 500, 750, 1000)

    mods = [("冲击力", 10.0, True, "Impact Force")]
    assert reverse.solve_slots(solve_bp, mods, tiers, _mat_zh) == {
        "slots": [
            {"idx": 0, "slot": "枪管", "mat": "注入矿A", "mat_en": "OreA", "q": 750}
        ],
        "avg": 750,
        "exact": True,
    }
    assert tier_calls == ["OreA"]

    tier_calls.clear()
    assert reverse.craft_slots(solve_bp, tiers, _mat_zh) == [
        {
            "idx": 0,
            "slot": "枪管",
            "mat": "注入矿A",
            "mat_en": "OreA",
            "tiers": (0, 500, 750, 1000),
        }
    ]
    assert tier_calls == ["OreA"]


def test_old_names_are_aliases():
    from astral_toolkit.crafting import crafting as C

    assert C.GEAR_ZH is labels.GEAR_ZH
    assert C.SUB_ZH is labels.SUB_ZH
    assert C.PROP_KEY is quality.PROP_KEY
    assert C.LOWER_BETTER is quality.LOWER_BETTER
    assert C.prop_zh is labels.prop_zh
    assert C.slot_zh is labels.slot_zh
    assert C.category_zh is classify.category_zh
    assert C.part_of is classify.part_of
    assert C.needs is materials.needs
    assert C.group_mods is quality.group_mods
    assert C.curve_value is quality.curve_value
    assert C.curve_text is quality.curve_text
    assert C.laser_total is quality.laser_total
    assert C.mix_plan is mix.mix_plan
    assert C.parse_mods is reverse.parse_mods
    assert C.craft_text is reverse.craft_text
