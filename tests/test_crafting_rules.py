"""制造纯规则（CR-B2）的纯度和注入测试。

只测新拆出的 labels / classify / materials / quality / mix / listing / reverse：
不碰库、不碰文件、不碰汉化包，也不重复黄金测试已经锁住的旧接口输出。
"""

from types import SimpleNamespace
from typing import Any

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


def test_listing_named_matches_en_and_zh():
    """F8「可制造：有蓝图」：英文名、中文名都能对上，按源顺序；None / 空名字不算，z 是 None 也不出错"""
    bps = [
        _bp("Other", None, "g", "t", "", "", "", 0, False, []),
        _bp("Medical Pen", "医疗笔", "g", "t", "", "", "", 0, False, []),
        _bp("Lima", "利马", "g", "t", "", "", "", 0, False, []),
    ]
    assert listing.named(bps, ("医疗笔",)) == [bps[1]]
    assert listing.named(bps, ("medicalpen",)) == [bps[1]]
    assert listing.named(bps, ("Test Widget", "利马")) == [bps[2]]
    assert listing.named(bps, ("Lima", "Other")) == [bps[0], bps[2]]
    assert listing.named(bps, ("  ", "")) == []
    assert listing.named(bps, (None,)) == []
    assert listing.named(bps, ("不存在",)) == []
    assert listing.named([], ("医疗笔",)) == []


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
    from astral_toolkit.mining import quality as mining_quality

    def boom(*args, **kwargs):
        raise AssertionError("纯规则不该触发查询 / 建库 / 汉化")

    for mod, names in (
        (
            gd_crafting,
            ("catalog", "cached", "for_item", "containing", "using_material"),
        ),
        (mining_quality, ("tier_values",)),
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


def test_solve_slots_signs():
    """CR-C1：显示符号核过的（SHOWN_SIGN）带符号比；没核过的绝对值一样、符号相反时不报 exact；
    几档在说明框上一模一样（台阶）照旧报最低档；说明框上是 0、算出来正好是 0 都不算一种符号"""
    assert reverse.SHOWN_SIGN == {
        "冲击力": 1,
        "后坐力冲击": 1,
        "后坐力平滑度": -1,
        "后坐力操控": -1,
    }

    def bp(*slots):
        return _bp(
            "S", "反推", "fpsgear", "weapons", "rifle", "u", "M", 1, True, list(slots)
        )

    def tiers(name):
        return {"OreA": (0, 500, 1000), "OreB": (0, 300, 1000)}[name]

    def solve(b, *mods):
        res = reverse.solve_slots(b, list(mods), tiers, _mat_zh)
        assert res is not None
        return [x["q"] for x in res["slots"]], res["exact"]

    a = [("r", "OreA", 1, 1)]
    b = [("r", "OreB", 1, 1)]
    # 射速 0 档 -10%、1000 档 +10%；平滑度、后坐力冲击 0 档 +40%、1000 档 -40%；冲击力 0 档 -20%、1000 档 +20%
    fire = ("Barrel", a, [("Fire Rate", 0, 1000, 0.9, 1.1, False)])
    smooth = ("Frame", a, [("Recoil Smoothness", 0, 1000, 1.4, 0.6, False)])
    kick = ("Frame", a, [("Recoil Kick", 0, 1000, 1.4, 0.6, False)])
    force = ("Barrel", a, [("Impact Force", 0, 1000, 0.8, 1.2, False)])

    # 射速没核过：0 档、1000 档都对得上 → 不报 exact（以前报 0 档）
    assert solve(bp(fire), ("射速", 10.0, True, "Fire Rate")) == ([0], False)
    # 平滑度说明框上是反的：+40% 是曲线 -40%，即 1000 档
    assert solve(bp(smooth), ("后坐力平滑度", 40.0, True, "Recoil Smoothness")) == (
        [1000],
        True,
    )
    assert solve(bp(smooth), ("后坐力平滑度", -40.0, True, "Recoil Smoothness")) == (
        [0],
        True,
    )
    # 后坐力冲击和曲线一样：-40% 是 1000 档
    assert solve(bp(kick), ("后坐力冲击", -40.0, True, "Recoil Kick")) == ([1000], True)
    # 冲击力核过；同是 Impact Force 的「激光功率」没核过
    assert solve(bp(force), ("冲击力", 20.0, True, "Impact Force")) == ([1000], True)
    assert solve(bp(force), ("激光功率", 20.0, True, "Impact Force")) == ([0], False)
    # 差 0.1 不算对上（说明框两位小数，门槛 0.02）
    assert solve(bp(force), ("冲击力", 20.1, True, "Impact Force")) == ([1000], False)
    # 核过的那项带符号定下来；没核过的那项只有一档对得上（300 档 -4%，没有 700 档）→ exact
    two = bp(force, ("Cabling", b, [("Fire Rate", 0, 1000, 0.9, 1.1, False)]))
    assert solve(
        two, ("冲击力", 20.0, True, "Impact Force"), ("射速", 4.0, True, "Fire Rate")
    ) == (
        [1000, 300],
        True,
    )
    # 台阶：0 档、300 档都是 +10%，符号也一样 → 说明框上分不出，报最低档、照样 exact
    step = (
        "Cabling",
        b,
        [
            ("Fire Rate", 0, 600, 1.1, 1.1, False),
            ("Fire Rate", 600, 1000, 1.1, 1.3, False),
        ],
    )
    assert solve(bp(step), ("射速", 10.0, True, "Fire Rate")) == ([0], True)
    # 很平的曲线：0 档 -0.01%、500 档 0、1000 档 +0.01% 都在门槛里。说明框 +0.01 → 有正有负，分不出；
    # 说明框是 0 → 不看符号，差最小的 500 档；算出来正好 0 的不算一种符号（0 档 0、500 档 +0.01、1000 档 +0.02）
    tiny = ("Barrel", a, [("Fire Rate", 0, 1000, 0.9999, 1.0001, False)])
    assert solve(bp(tiny), ("射速", 0.01, True, "Fire Rate")) == ([0], False)
    assert solve(bp(tiny), ("射速", 0.0, True, "Fire Rate")) == ([500], True)
    up = ("Barrel", a, [("Fire Rate", 0, 1000, 1.0, 1.0002, False)])
    assert solve(bp(up), ("射速", 0.01, True, "Fire Rate")) == ([500], True)
    # 算出来不到 0.005 的也不算：0 档 -0.004（说明框上是 0.00）、500 档 +0.003、1000 档 +0.01
    near = ("Barrel", a, [("Fire Rate", 0, 1000, 0.99996, 1.0001, False)])
    assert solve(bp(near), ("射速", 0.01, True, "Fire Rate")) == ([1000], True)


def test_spec_tags_and_browse_spec_facets():
    """CR-D1：船零件的尺寸 / 等级 / 类别标签、护甲的轻 / 中 / 重；蓝图字典选了船零件类时按物品属性多给等级、类别
    （子类里没有尺寸时还有尺寸）三组筛选；别的类、没给 spec 时没有这三组，传了也不筛"""
    assert labels.spec_tags({"size": 2, "grade": "A", "cls": "Military"}) == [
        "S2",
        "A 级",
        "军用",
    ]
    assert labels.spec_tags({"grade": "E", "cls": "Stealth"}, "size3") == ["S3", "隐形"]
    assert labels.spec_tags({"size": 2, "grade": "B"}, size=False) == ["B 级"]
    assert labels.spec_tags({"cls": "Odd"}) == ["Odd"]
    assert labels.spec_tags({}) == []
    assert labels.weight_zh({"sub": "Heavy"}) == "重型"
    assert labels.weight_zh({"sub": "LightArmor"}) == "轻型"
    assert labels.weight_zh({"sub": "Personal"}) == labels.weight_zh({}) == ""
    # 只写游戏说明里有的：舰船武器的等级 A、刮削模块的 S1 都是数据默认值（审查 2026-11-08）
    assert labels.spec_tags(
        {"size": 2, "grade": "A", "cls": "Military"}, kind="weapons"
    ) == ["S2"]
    assert labels.spec_tags({"size": 1, "grade": "A"}, "medium", kind="salvage") == []
    assert labels.spec_tags(
        {"size": 1, "grade": "C", "cls": "Competition"}, "size1", kind="cooler"
    ) == ["S1", "C 级", "竞赛"]
    bag = {"sub": "Personal", "type": "Char_Armor_Backpack", "size": 3}
    assert labels.weight_zh(bag) == "重型"
    assert labels.weight_zh({**bag, "size": 1}) == "轻型"
    assert labels.weight_zh(bag, "H4-PBF Ammo Carrier") == ""  # 能配中型、重型护甲
    assert labels.weight_zh({"sub": "Personal", "size": 3}) == ""  # 不是背包
    # 超重型按类名认（BUL-H4 的子类型写的是 Heavy）；同一套的弹药携具按类名认出来，不写，不靠英文名（审查 2026-11-08）
    h4 = {"sub": "Heavy", "type": "Char_Armor_Helmet", "cn": "cds_superheavy_helmet"}
    assert labels.weight_zh(h4) == "超重型"
    assert labels.weight_zh({**bag, "cn": "cds_combat_superheavy_backpack_01"}) == ""
    assert labels.weight_zh({**bag, "cn": "cds_heavy_backpack_01"}) == "重型"

    def bp(n, t, s, u):
        return _bp(n, n, "vehiclegear", t, s, u, "M", 1, True, [])

    bps = [
        bp("PP One", "powerplant", "size1", "u1"),
        bp("PP Two", "powerplant", "size2", "u2"),
        bp("PP Three", "powerplant", "size2", "u3"),
        bp("Gun A", "weapons", "laser", "g1"),
        bp("Gun B", "weapons", "ballistic", "g2"),
        bp("Gun C", "weapons", "laser", "g3"),
        bp("CL One", "cooler", "size1", "c1"),
        bp("CL Odd", "cooler", None, "c2"),
        _bp("Helmet", "头盔", "fpsgear", "armour", "combat", "h1", "M", 1, True, []),
    ]
    stats = {
        "u1": {"size": 1, "grade": "C", "cls": "Military"},
        "u2": {"size": 2, "grade": "A", "cls": "Civilian"},
        "u3": {"size": 2, "grade": "C", "cls": "Military"},
        "g1": {"size": 10, "grade": "A", "cls": None},
        "g2": {"size": 2, "grade": "B", "cls": None},
        "c1": {"size": 1, "grade": "B", "cls": "Civilian"},
        "c2": {"size": 3, "grade": "B", "cls": "Civilian"},
        "h1": {"size": 1, "grade": "A", "cls": None},
    }

    def spec(b):
        return stats.get(b["u"], {})

    def names(**kw: Any):
        return [b["n"] for b in listing.browse(lambda: bps, spec=spec, **kw)["rows"]]

    pp = listing.browse(lambda: bps, cat="vehiclegear/powerplant", spec=spec)
    assert pp["sizes"] == []  # 子类就是 S1 / S2，不另给尺寸
    assert pp["grades"] == [  # 等级按字母排，不按份数；类别按份数
        {"key": "A", "label": "A 级", "count": 1},
        {"key": "C", "label": "C 级", "count": 2},
    ]
    assert pp["clss"] == [
        {"key": "Military", "label": "军用", "count": 2},
        {"key": "Civilian", "label": "民用", "count": 1},
    ]
    assert list(pp)[-3:] == ["sizes", "grades", "clss"]
    assert names(cat="vehiclegear/powerplant", grade="C") == ["PP One", "PP Three"]
    assert names(cat="vehiclegear/powerplant", cls="Civilian") == ["PP Two"]
    assert names(cat="vehiclegear/powerplant", grade="C", cls="Civilian") == []
    # 子类就是尺寸时 size 不筛；有一份子类是尺寸（冷却器里有一份子类空着）也算
    assert names(cat="vehiclegear/powerplant", size="1") == [
        "PP One",
        "PP Three",
        "PP Two",
    ]
    cl = listing.browse(lambda: bps, cat="vehiclegear/cooler", size="3", spec=spec)
    assert cl["sizes"] == [] and cl["total"] == 2
    gun = listing.browse(lambda: bps, cat="vehiclegear/weapons", spec=spec)
    assert gun["sizes"] == [  # 按数字排；Gun C 没有属性数据，不进尺寸、等级
        {"key": "2", "label": "S2", "count": 1},
        {"key": "10", "label": "S10", "count": 1},
    ]
    # 舰船武器游戏里没有等级、分类（数据里的等级是默认值）：不给这两组
    assert gun["grades"] == [] and gun["clss"] == []
    assert names(cat="vehiclegear/weapons", size="10") == ["Gun A"]
    assert names(cat="vehiclegear/weapons", size=2) == ["Gun B"]
    # 后面的筛选跟着前面的算：选了 C 级，类别里就没有民用；选了激光，尺寸里就没有 S2
    assert listing.browse(
        lambda: bps, cat="vehiclegear/powerplant", grade="C", spec=spec
    )["clss"] == [{"key": "Military", "label": "军用", "count": 2}]
    assert listing.browse(
        lambda: bps, cat="vehiclegear/weapons", sub="laser", spec=spec
    )["sizes"] == [{"key": "10", "label": "S10", "count": 1}]
    cases: list[dict[str, Any]] = [
        {"spec": spec},
        {"cat": "fpsgear/armour", "spec": spec},
        {"cat": "vehiclegear/powerplant"},
    ]
    for kw in cases:
        r = listing.browse(lambda: bps, grade="C", cls="Civilian", size="1", **kw)
        assert not {"sizes", "grades", "clss"} & set(r), kw
        want = [
            b for b in bps if not kw.get("cat") or classify.category(b) == kw["cat"]
        ]
        assert r["total"] == len(want), kw


def test_old_names_are_aliases():
    from astral_toolkit.crafting import crafting as C

    assert C.slot_zh is labels.slot_zh
    assert C.laser_total is quality.laser_total
    assert C.parse_mods is reverse.parse_mods
    assert C.craft_text is reverse.craft_text
