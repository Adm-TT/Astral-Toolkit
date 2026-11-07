"""制造黄金测试：不读本机数据，锁住制造相关接口现在的字面量输出。

CR-B1～B6 拆制造代码时，这些输出应当一个字都不变。
"""

import logging
from types import SimpleNamespace

from astral_toolkit.contracts.blueprints import assign_keys
from astral_toolkit.contracts.textkeys import blueprint_norm, blueprint_search_norm
from astral_toolkit.core import i18n
from astral_toolkit.crafting import crafting as C
from astral_toolkit.crafting import itemstats
from astral_toolkit.crafting import quality
from astral_toolkit.crafting import reverse
from astral_toolkit.gamedata import crafting as gd_crafting
from astral_toolkit.gamedata._types import GamedataError
from astral_toolkit.gamedata.crafting import Blueprints
from astral_toolkit.mining import data as mining_data
from astral_toolkit.mining import locations as mining_locations
from astral_toolkit.mining import quality as mining_quality
from astral_toolkit.tasks import crafting as TC
from astral_toolkit.tasks import goals as G

MIN_ZH = {
    "MineralA": "矿A",
    "MineralB": "矿B",
    "MineralC": "矿C",
    "MineralD": "矿D",
    "LaserPart": "激光件",
}

ITEMS = {
    "uuid-weapon": {
        "size": 3,
        "grade": "A",
        "cls": "Military",
        "mfr": "MakerW",
        "type": "Weapon",
        "s": {
            "personal_weapon": {"damage_per_shot": 100, "rpm": 600},
            "durability": {"health": 50},
        },
    },
    "uuid-laser": {
        "size": 2,
        "grade": "B",
        "cls": "Industrial",
        "mfr": "Shubin",
        "type": "Mining",
        "s": {"mining_laser": {"laser_power": {"max": 200}}},
    },
}

TIERS = {
    "MineralA": (0, 250, 500, 750, 1000),
    "MineralB": (0, 500, 1000),
    "MineralC": (0, 1000),
    "MineralD": (0, 500, 1000),
    "LaserPart": (0, 1000),
}


def _bp(n, z, g, t, s, u, m, sec, d, slots, src, nsrc):
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
        "src": src,
        "nsrc": nsrc,
    }


def _build_bps():
    bps = [
        _bp(
            "Test Rifle",
            "测试步枪",
            "fpsgear",
            "weapons",
            "rifle",
            "uuid-weapon",
            "MakerW",
            125,
            True,
            [
                (
                    "Barrel",
                    [("r", "MineralA", 5, 1), ("r", "MineralB", 3, 1)],
                    [
                        ("Impact Force", 0, 500, 1.0, 1.2, False),
                        ("Impact Force", 500, 1000, 1.2, 1.5, False),
                    ],
                ),
                (
                    "Cabling",
                    [("r", "MineralA", 2, 1)],
                    [("Fire Rate", 0, 1000, 0.9, 1.1, False)],
                ),
            ],
            [["~mission(Test) Alpha", "Giver", "Delivery", "Stanton", 0.5]],
            1,
        ),
        _bp(
            "Test Helmet",
            "测试头盔",
            "fpsgear",
            "armour",
            "combat",
            "uuid-armor",
            "MakerA",
            60,
            False,
            [("Plating", [("r", "MineralC", 2, 1)], [])],
            [],
            0,
        ),
        _bp(
            "Hofstede-S2 Mining Laser",
            "霍夫斯泰德 S2 采矿激光器",
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
            [],
            0,
        ),
        _bp(
            "Same Widget",
            "同名部件",
            "vehiclegear",
            "cooler",
            "size1",
            "uuid-dup1",
            "DupCo",
            120,
            True,
            [("Core", [("r", "MineralD", 1, 1)], [])],
            [],
            0,
        ),
        _bp(
            "Same Widget",
            "同名部件",
            "vehiclegear",
            "cooler",
            "size1",
            "uuid-dup2",
            "DupCo",
            180,
            False,
            [("Core", [("r", "MineralD", 2, 1)], [])],
            [],
            0,
        ),
        _bp(
            "Gated Component",
            "门槛部件",
            "vehiclegear",
            "powerplant",
            "size1",
            "uuid-gated",
            "GateCo",
            90,
            False,
            [("Core", [("r", "MineralA", 4, 500)], [])],
            [],
            0,
        ),
    ]
    keys, index, total = assign_keys(bps)
    table = Blueprints(
        {"blueprints": bps},
        keys,
        index,
        total,
        {str(i): b for i, b in enumerate(bps)},
    )
    return bps, table


BPS, TABLE = _build_bps()
WEAPON = BPS[0]
ARMOR = BPS[1]
LASER = BPS[2]
DUP1 = BPS[3]
DUP2 = BPS[4]
GATED = BPS[5]


def _fake_item(uuid):
    return ITEMS.get(uuid)


def _fake_version():
    return "v-test"


def _fake_best_price(mineral, table=None):
    return 1000, "City"


def _fake_where(mineral, system=None):
    return [
        (50, {"name": "Loc1", "parent": "P"}),
        (25, {"name": "Loc2", "parent": "P"}),
    ]


def _fake_zh_name(loc):
    return "地点" + loc["name"]


def _fake_tiers(name):
    return TIERS.get(name)


def _fake_gear_zh(en):
    return "霍夫斯泰德" if en == "Hofstede-S2 Mining Laser" else ""


def _install(monkeypatch):
    G.clear_caches()

    def catalog(snap=None):
        return TABLE

    def cached():
        return TABLE

    def for_item(norm_en, norm_zh, snap=None):
        for key in (norm_en, norm_zh):
            if not key:
                continue
            for bp in BPS:
                if blueprint_norm(bp["n"]) == key or blueprint_norm(bp["z"]) == key:
                    return bp
        return None

    def containing(q, snap=None):
        if not q:
            return []
        return [
            bp
            for bp in BPS
            if q in blueprint_search_norm(bp["n"])
            or q in blueprint_search_norm(bp["z"])
        ]

    def using_material(material, snap=None):
        return [
            bp
            for bp in BPS
            if any(
                kind == "r" and name == material
                for _, opts, _ in bp["slots"]
                for kind, name, _, _ in opts
            )
        ]

    monkeypatch.setattr(gd_crafting, "catalog", catalog)
    monkeypatch.setattr(gd_crafting, "cached", cached)
    monkeypatch.setattr(gd_crafting, "for_item", for_item)
    monkeypatch.setattr(gd_crafting, "containing", containing)
    monkeypatch.setattr(gd_crafting, "using_material", using_material)
    monkeypatch.setattr(itemstats, "item", _fake_item)
    monkeypatch.setattr(itemstats, "version", _fake_version)
    monkeypatch.setattr(i18n, "gear_zh_of_item", _fake_gear_zh)
    monkeypatch.setattr(i18n, "mineral_zh", lambda en: MIN_ZH.get(en, en))
    monkeypatch.setattr(mining_data, "best_price", _fake_best_price)
    monkeypatch.setattr(mining_locations, "where", _fake_where)
    monkeypatch.setattr(mining_locations, "zh_name", _fake_zh_name)
    monkeypatch.setattr(mining_quality, "tier_values", _fake_tiers)
    monkeypatch.setattr(TC, "best_price", _fake_best_price)
    monkeypatch.setattr(TC, "where", _fake_where)
    monkeypatch.setattr(TC, "zh_name", _fake_zh_name)


def _locspots():
    return [
        {"loc": "地点Loc1", "pct": 50},
        {"loc": "地点Loc2", "pct": 25},
    ]


def _mine(en):
    return {
        "en": en,
        "zh": MIN_ZH[en],
        "spots": _locspots(),
        "price": 1000,
        "city": "City",
    }


def _head_weapon(note=""):
    return {
        "zh": "测试步枪",
        "en": "Test Rifle",
        "kind": "个人武器",
        "tags": [],
        "maker": "MakerW",
        "sec": 125,
        "unlocked": True,
        "stats_version": "v-test",
        "note": note,
    }


def _head_armor(note=""):
    return {
        "zh": "测试头盔",
        "en": "Test Helmet",
        "kind": "护甲",
        "tags": [],
        "maker": "MakerA",
        "sec": 60,
        "unlocked": False,
        "stats_version": "",
        "note": note,
    }


def _head_laser(note=""):
    return {
        "zh": "霍夫斯泰德 S2 采矿激光器",
        "en": "Hofstede-S2 Mining Laser",
        "kind": "采矿激光器",
        "tags": ["S2"],
        "maker": "Shubin",
        "sec": 300,
        "unlocked": True,
        "stats_version": "v-test",
        "note": note,
    }


def _head_dup1(note=""):
    return {
        "zh": "同名部件",
        "en": "Same Widget",
        "kind": "冷却器",
        "tags": ["S1"],  # 蓝图 s 是 size1，header 补尺寸标签
        "maker": "DupCo",
        "sec": 120,
        "unlocked": True,
        "stats_version": "",
        "note": note,
    }


def _head_dup2(note=""):
    return {
        "zh": "同名部件",
        "en": "Same Widget",
        "kind": "冷却器",
        "tags": ["S1"],  # 蓝图 s 是 size1，header 补尺寸标签
        "maker": "DupCo",
        "sec": 180,
        "unlocked": False,
        "stats_version": "",
        "note": note,
    }


def _head_gated(note=""):
    return {
        "zh": "门槛部件",
        "en": "Gated Component",
        "kind": "发电机",
        "tags": ["S1"],  # 蓝图 s 是 size1，header 补尺寸标签
        "maker": "GateCo",
        "sec": 90,
        "unlocked": False,
        "stats_version": "",
        "note": note,
    }


def _slots_weapon():
    return [
        {
            "idx": 0,
            "slot": "枪管",
            "mats": [
                {
                    "kind": "r",
                    "en": "MineralA",
                    "zh": "矿A",
                    "qty": 5,
                    "unit": "SCU",
                    "minq": 1,
                },
                {
                    "kind": "r",
                    "en": "MineralB",
                    "zh": "矿B",
                    "qty": 3,
                    "unit": "SCU",
                    "minq": 1,
                },
            ],
            "minq": 1,
            "curves": [
                {
                    "prop": "Impact Force",
                    "name": "冲击力",
                    "key": "weapon_damage",
                    "add": False,
                    "lower": False,
                    "segs": [[0, 500, 1.0, 1.2], [500, 1000, 1.2, 1.5]],
                    "text": "冲击力（0–500:×1.00→×1.20，500–1000:×1.20→×1.50）",
                }
            ],
        },
        {
            "idx": 1,
            "slot": "线缆",
            "mats": [
                {
                    "kind": "r",
                    "en": "MineralA",
                    "zh": "矿A",
                    "qty": 2,
                    "unit": "SCU",
                    "minq": 1,
                }
            ],
            "minq": 1,
            "curves": [
                {
                    "prop": "Fire Rate",
                    "name": "射速",
                    "key": "weapon_firerate",
                    "add": False,
                    "lower": False,
                    "segs": [[0, 1000, 0.9, 1.1]],
                    "text": "射速 ×0.90→×1.10",
                }
            ],
        },
    ]


def _slots_armor():
    return [
        {
            "idx": 0,
            "slot": "镀层",
            "mats": [
                {
                    "kind": "r",
                    "en": "MineralC",
                    "zh": "矿C",
                    "qty": 2,
                    "unit": "SCU",
                    "minq": 1,
                }
            ],
            "minq": 1,
            "curves": [],
        }
    ]


def _slots_laser():
    return [
        {
            "idx": 0,
            "slot": "发射器",
            "mats": [
                {
                    "kind": "i",
                    "en": "LaserPart",
                    "zh": "激光件",
                    "qty": 1,
                    "unit": "个",
                    "minq": 1,
                }
            ],
            "minq": 1,
            "curves": [
                {
                    "prop": "Impact Force",
                    "name": "激光功率",
                    "key": "weapon_damage",
                    "add": False,
                    "lower": False,
                    "segs": [[0, 1000, 0.8, 1.2]],
                    "text": "激光功率 ×0.80→×1.20",
                }
            ],
        },
        {
            "idx": 1,
            "slot": "汇流排",
            "mats": [
                {
                    "kind": "i",
                    "en": "LaserPart",
                    "zh": "激光件",
                    "qty": 1,
                    "unit": "个",
                    "minq": 1,
                }
            ],
            "minq": 1,
            "curves": [
                {
                    "prop": "Impact Force",
                    "name": "激光功率",
                    "key": "weapon_damage",
                    "add": False,
                    "lower": False,
                    "segs": [[0, 1000, 0.9, 1.3]],
                    "text": "激光功率 ×0.90→×1.30",
                }
            ],
        },
    ]


def _slots_dup(qty):
    return [
        {
            "idx": 0,
            "slot": "核心",
            "mats": [
                {
                    "kind": "r",
                    "en": "MineralD",
                    "zh": "矿D",
                    "qty": qty,
                    "unit": "SCU",
                    "minq": 1,
                }
            ],
            "minq": 1,
            "curves": [],
        }
    ]


def _slots_gated():
    return [
        {
            "idx": 0,
            "slot": "核心",
            "mats": [
                {
                    "kind": "r",
                    "en": "MineralA",
                    "zh": "矿A",
                    "qty": 4,
                    "unit": "SCU",
                    "minq": 500,
                }
            ],
            "minq": 500,
            "curves": [],
        }
    ]


_WEAPON_TEXT = "\n".join(
    [
        "【测试步枪 Test Rifle】个人武器｜MakerW｜制造 2 分 5 秒｜默认已解锁",
        "  · 枪管：矿A 5 SCU 或 矿B 3 SCU｜品质影响：冲击力（0–500:×1.00→×1.20，500–1000:×1.20→×1.50）",
        "  · 线缆：矿A 2 SCU｜品质影响：射速 ×0.90→×1.10",
        "  去哪挖：",
        "    矿A：地点Loc1 50%，地点Loc2 25%｜精炼后 1,000/SCU（City）",
        "    矿B：地点Loc1 50%，地点Loc2 25%｜精炼后 1,000/SCU（City）",
        "  蓝图来源（1 个任务，列出前 1 个）：",
        "    [地点] Alpha｜Giver｜Delivery｜Stanton，掉率 50%",
    ]
)

_ARMOR_TEXT = "\n".join(
    [
        "【测试头盔 Test Helmet】护甲｜MakerA｜制造 1 分 0 秒",
        "  · 镀层：矿C 2 SCU",
        "  去哪挖：",
        "    矿C：地点Loc1 50%，地点Loc2 25%｜精炼后 1,000/SCU（City）",
        "  蓝图来源：scmdb 的任务数据里没有找到",
    ]
)

_LASER_TEXT = "\n".join(
    [
        "【霍夫斯泰德 Hofstede-S2 Mining Laser】采矿激光器｜Shubin｜制造 5 分 0 秒｜默认已解锁",
        "  · 发射器：激光件 1 个｜品质影响：激光功率 ×0.80→×1.20",
        "  · 汇流排：激光件 1 个｜品质影响：激光功率 ×0.90→×1.30",
        "  · 激光功率合计：发射器 + 汇流排 两个槽的加成相加，品质都 0 时 ×0.70、都 500 时 ×1.10（和商店买的一样）、都 1000 时 ×1.50。「采矿助手」页的配置里可以填自造矿头的品质，破碎方案按自造的功率算",
    ]
)

_DUP1_TEXT = "\n".join(
    [
        "【同名部件 Same Widget】冷却器｜DupCo｜制造 2 分 0 秒｜默认已解锁｜配方 1/2 · 2 分钟",
        "  · 核心：矿D 1 SCU",
        "  去哪挖：",
        "    矿D：地点Loc1 50%，地点Loc2 25%｜精炼后 1,000/SCU（City）",
    ]
)

_DUP2_TEXT = "\n".join(
    [
        "【同名部件 Same Widget】冷却器｜DupCo｜制造 3 分 0 秒｜配方 2/2 · 3 分钟",
        "  · 核心：矿D 2 SCU",
        "  去哪挖：",
        "    矿D：地点Loc1 50%，地点Loc2 25%｜精炼后 1,000/SCU（City）",
        "  蓝图来源：scmdb 的任务数据里没有找到",
    ]
)

_GATED_TEXT = "\n".join(
    [
        "【门槛部件 Gated Component】发电机｜GateCo｜制造 1 分 30 秒",
        "  · 核心：矿A 4 SCU（品质 ≥500）",
        "  去哪挖：",
        "    矿A：地点Loc1 50%，地点Loc2 25%｜精炼后 1,000/SCU（City）",
        "  蓝图来源：scmdb 的任务数据里没有找到",
    ]
)


def _mix_weapon():
    return [
        {
            "slot": "枪管",
            "material": "MineralA",
            "zh": "矿A",
            "scu": 5,
            "min": 1,
            "steps": [],
        },
        {
            "slot": "枪管",
            "material": "MineralB",
            "zh": "矿B",
            "scu": 3,
            "min": 1,
            "steps": [],
        },
        {
            "slot": "线缆",
            "material": "MineralA",
            "zh": "矿A",
            "scu": 2,
            "min": 1,
            "steps": [],
        },
    ]


def _mix_armor():
    return [
        {
            "slot": "镀层",
            "material": "MineralC",
            "zh": "矿C",
            "scu": 2,
            "min": 1,
            "steps": [],
        }
    ]


def _mix_dup(qty):
    return [
        {
            "slot": "核心",
            "material": "MineralD",
            "zh": "矿D",
            "scu": qty,
            "min": 1,
            "steps": [],
        }
    ]


def _mix_gated():
    return [
        {
            "slot": "核心",
            "material": "MineralA",
            "zh": "矿A",
            "scu": 4,
            "min": 500,
            "steps": [],
        }
    ]


def _detail_weapon():
    return {
        "key": "Test Rifle",
        "text": _WEAPON_TEXT,
        "mix": _mix_weapon(),
        "head": _head_weapon(),
        "slots": _slots_weapon(),
        "mine": [_mine("MineralA"), _mine("MineralB")],
        "sources": [
            {
                "title": "[地点] Alpha",
                "who": "Giver",
                "kind": "Delivery",
                "systems": "Stanton",
                "chance": 0.5,
            }
        ],
        "nsrc": 1,
    }


def _detail_armor():
    return {
        "key": "Test Helmet",
        "text": _ARMOR_TEXT,
        "mix": _mix_armor(),
        "head": _head_armor(),
        "slots": _slots_armor(),
        "mine": [_mine("MineralC")],
        "sources": [],
        "nsrc": 0,
    }


def _detail_laser():
    return {
        "key": "Hofstede-S2 Mining Laser",
        "text": _LASER_TEXT,
        "mix": [],
        "head": _head_laser(),
        "slots": _slots_laser(),
        "mine": [],
        "sources": [],
        "nsrc": 0,
    }


def _detail_dup1():
    return {
        "key": "Same Widget#1",
        "text": _DUP1_TEXT,
        "mix": _mix_dup(1),
        "head": _head_dup1("配方 1/2 · 2 分钟"),
        "slots": _slots_dup(1),
        "mine": [_mine("MineralD")],
        "sources": [],
        "nsrc": 0,
    }


def _detail_dup2():
    return {
        "key": "Same Widget#2",
        "text": _DUP2_TEXT,
        "mix": _mix_dup(2),
        "head": _head_dup2("配方 2/2 · 3 分钟"),
        "slots": _slots_dup(2),
        "mine": [_mine("MineralD")],
        "sources": [],
        "nsrc": 0,
    }


def _detail_gated():
    return {
        "key": "Gated Component",
        "text": _GATED_TEXT,
        "mix": _mix_gated(),
        "head": _head_gated(),
        "slots": _slots_gated(),
        "mine": [_mine("MineralA")],
        "sources": [],
        "nsrc": 0,
    }


def _brow(key, name, kind, tags, maker, unlocked):
    return {
        "key": key,
        "name": name,
        "kind": kind,
        "tags": tags,
        "maker": maker,
        "unlocked": unlocked,
    }


def _browse_meta_default():
    return {
        "cats": [
            {"key": "vehiclegear/cooler", "label": "冷却器", "count": 2},
            {"key": "fpsgear/armour", "label": "护甲", "count": 1},
            {"key": "fpsgear/weapons", "label": "个人武器", "count": 1},
            {"key": "vehiclegear/mininglaser", "label": "采矿激光器", "count": 1},
            {"key": "vehiclegear/powerplant", "label": "发电机", "count": 1},
        ],
        "subs": [
            {"key": "size1", "label": "S1", "count": 3},
            {"key": "combat", "label": "战斗", "count": 1},
            {"key": "rifle", "label": "突击步枪", "count": 1},
            {"key": "size2", "label": "S2", "count": 1},
        ],
        "parts": [{"key": "头盔", "label": "头盔", "count": 1}],
        "makers": [
            {"key": "DupCo", "label": "DupCo", "count": 2},
            {"key": "GateCo", "label": "GateCo", "count": 1},
            {"key": "MakerA", "label": "MakerA", "count": 1},
            {"key": "MakerW", "label": "MakerW", "count": 1},
            {"key": "Shubin", "label": "Shubin", "count": 1},
        ],
    }


def _browse_rows_default():
    return [
        _brow(
            "Gated Component",
            "门槛部件 Gated Component",
            "发电机",
            "S1",
            "GateCo",
            False,
        ),
        _brow(
            "Hofstede-S2 Mining Laser",
            "霍夫斯泰德 Hofstede-S2 Mining Laser",
            "采矿激光器",
            "S2",
            "Shubin",
            True,
        ),
        _brow(
            "Same Widget#1",
            "同名部件 Same Widget",
            "冷却器",
            "S1 · 配方 1/2 · 2 分钟",
            "DupCo",
            True,
        ),
        _brow(
            "Same Widget#2",
            "同名部件 Same Widget",
            "冷却器",
            "S1 · 配方 2/2 · 3 分钟",
            "DupCo",
            False,
        ),
        _brow(
            "Test Helmet",
            "测试头盔 Test Helmet",
            "护甲",
            "头盔 · 战斗",
            "MakerA",
            False,
        ),
        _brow(
            "Test Rifle",
            "测试步枪 Test Rifle",
            "个人武器",
            "突击步枪",
            "MakerW",
            True,
        ),
    ]


def _browse_default():
    out: dict = _browse_meta_default()
    out["rows"] = _browse_rows_default()
    out["total"] = 6
    return out


def _effect_weapon_barrel(q, now, best, worst, pos, text):
    return {
        "slot": "枪管",
        "idx": 0,
        "material": "矿A/矿B",
        "q": q,
        "minq": 0,
        "ok": True,
        "props": [
            {
                "name": "冲击力",
                "now": now,
                "best": best,
                "worst": worst,
                "pos": pos,
                "next_gate": None,
                "text": text,
            }
        ],
    }


def _effect_weapon_cabling(q, now, best, worst, pos, text):
    return {
        "slot": "线缆",
        "idx": 1,
        "material": "矿A",
        "q": q,
        "minq": 0,
        "ok": True,
        "props": [
            {
                "name": "射速",
                "now": now,
                "best": best,
                "worst": worst,
                "pos": pos,
                "next_gate": None,
                "text": text,
            }
        ],
    }


def _effect_laser_emitter(q, now, best, worst, pos, text):
    return {
        "slot": "发射器",
        "idx": 0,
        "material": "激光件",
        "q": q,
        "minq": 0,
        "ok": True,
        "props": [
            {
                "name": "激光功率",
                "now": now,
                "best": best,
                "worst": worst,
                "pos": pos,
                "next_gate": None,
                "text": text,
            }
        ],
    }


def _effect_laser_bus(q, now, best, worst, pos, text):
    return {
        "slot": "汇流排",
        "idx": 1,
        "material": "激光件",
        "q": q,
        "minq": 0,
        "ok": True,
        "props": [
            {
                "name": "激光功率",
                "now": now,
                "best": best,
                "worst": worst,
                "pos": pos,
                "next_gate": None,
                "text": text,
            }
        ],
    }


def _stat_impact_weapon(delta, slots, now, now_best, text):
    return {
        "prop": "Impact Force",
        "name": "冲击力",
        "key": "weapon_damage",
        "add": False,
        "lower": False,
        "delta": delta,
        "best": 0.5,
        "worst": 0.0,
        "slots": slots,
        "base": 100,
        "unit": "",
        "now": now,
        "now_best": now_best,
        "text": text,
    }


def _stat_fire_weapon(delta, slots, now, now_best, text):
    return {
        "prop": "Fire Rate",
        "name": "射速",
        "key": "weapon_firerate",
        "add": False,
        "lower": False,
        "delta": delta,
        "best": 0.1,
        "worst": -0.1,
        "slots": slots,
        "base": 600,
        "unit": " RPM",
        "now": now,
        "now_best": now_best,
        "text": text,
    }


def _stat_laser(delta, slots, now, now_best, text):
    return {
        "prop": "Impact Force",
        "name": "激光功率",
        "key": "weapon_damage",
        "add": False,
        "lower": False,
        "delta": delta,
        "best": 0.5,
        "worst": -0.3,
        "slots": slots,
        "base": 200,
        "unit": "",
        "now": now,
        "now_best": now_best,
        "text": text,
    }


def _stats_weapon_default(missing):
    return {
        "props": [
            _stat_impact_weapon(
                0.2,
                [{"slot": "枪管", "idx": 0, "q": 500, "part": 0.2}],
                120.0,
                150.0,
                "+20.00%",
            ),
            _stat_fire_weapon(
                0.0,
                [{"slot": "线缆", "idx": 1, "q": 500, "part": 0.0}],
                600.0,
                660.0,
                "+0.00%",
            ),
        ],
        "missing": missing,
    }


def _stats_weapon_1000():
    return {
        "props": [
            _stat_impact_weapon(
                0.5,
                [{"slot": "枪管", "idx": 0, "q": 1000, "part": 0.5}],
                150.0,
                150.0,
                "+50.00%",
            ),
            _stat_fire_weapon(
                0.1,
                [{"slot": "线缆", "idx": 1, "q": 1000, "part": 0.1}],
                660.0,
                660.0,
                "+10.00%",
            ),
        ],
        "missing": [],
    }


def _stats_weapon_750():
    return {
        "props": [
            _stat_impact_weapon(
                0.35,
                [{"slot": "枪管", "idx": 0, "q": 750, "part": 0.35}],
                135.0,
                150.0,
                "+35.00%",
            ),
            _stat_fire_weapon(
                0.0,
                [{"slot": "线缆", "idx": 1, "q": 500, "part": 0.0}],
                600.0,
                660.0,
                "+0.00%",
            ),
        ],
        "missing": ["线缆"],
    }


def _stats_weapon_mixed():
    return {
        "props": [
            _stat_impact_weapon(
                0.2,
                [{"slot": "枪管", "idx": 0, "q": 500, "part": 0.2}],
                120.0,
                150.0,
                "+20.00%",
            ),
            _stat_fire_weapon(
                0.1,
                [{"slot": "线缆", "idx": 1, "q": 1000, "part": 0.1}],
                660.0,
                660.0,
                "+10.00%",
            ),
        ],
        "missing": [],
    }


def _stats_laser_default(missing):
    return {
        "props": [
            _stat_laser(
                0.1,
                [
                    {"slot": "发射器", "idx": 0, "q": 500, "part": 0.0},
                    {"slot": "汇流排", "idx": 1, "q": 500, "part": 0.1},
                ],
                220.0,
                300.0,
                "+10.00%",
            )
        ],
        "missing": missing,
    }


def _stats_laser_1000():
    return {
        "props": [
            _stat_laser(
                0.5,
                [
                    {"slot": "发射器", "idx": 0, "q": 1000, "part": 0.2},
                    {"slot": "汇流排", "idx": 1, "q": 1000, "part": 0.3},
                ],
                300.0,
                300.0,
                "+50.00%",
            )
        ],
        "missing": [],
    }


def _stats_laser_750():
    return {
        "props": [
            _stat_laser(
                0.2,
                [
                    {"slot": "发射器", "idx": 0, "q": 750, "part": 0.1},
                    {"slot": "汇流排", "idx": 1, "q": 500, "part": 0.1},
                ],
                240.0,
                300.0,
                "+20.00%",
            )
        ],
        "missing": ["汇流排"],
    }


def test_craft_search_browse_detail(monkeypatch):
    _install(monkeypatch)
    try:
        assert G.craft_search("Test Rifle") == [
            {
                "key": "Test Rifle",
                "name": "测试步枪 Test Rifle",
                "zh": "测试步枪",
                "en": "Test Rifle",
                "note": "",
                "kind": "个人武器",
            }
        ]
        assert G.craft_search("测试步枪")[0]["key"] == "Test Rifle"
        assert G.craft_search("Rifle")[0]["key"] == "Test Rifle"
        assert G.craft_search("Hofstede") == [
            {
                "key": "Hofstede-S2 Mining Laser",
                "name": "霍夫斯泰德 Hofstede-S2 Mining Laser",
                "zh": "霍夫斯泰德",
                "en": "Hofstede-S2 Mining Laser",
                "note": "",
                "kind": "采矿激光器",
            }
        ]
        assert G.craft_search("") == []
        assert G.craft_search("  ") == []
        assert G.craft_search("不存在的东西") == []
        assert G.craft_search("Same Widget") == [
            {
                "key": "Same Widget#1",
                "name": "同名部件 Same Widget｜配方 1/2 · 2 分钟",
                "zh": "同名部件",
                "en": "Same Widget",
                "note": "配方 1/2 · 2 分钟",
                "kind": "冷却器",
            },
            {
                "key": "Same Widget#2",
                "name": "同名部件 Same Widget｜配方 2/2 · 3 分钟",
                "zh": "同名部件",
                "en": "Same Widget",
                "note": "配方 2/2 · 3 分钟",
                "kind": "冷却器",
            },
        ]

        assert G.craft_browse() == _browse_default()

        cat = G.craft_browse(cat="fpsgear/weapons")
        assert cat["total"] == 1
        assert cat["rows"][0]["key"] == "Test Rifle"
        assert cat["subs"] == [{"key": "rifle", "label": "突击步枪", "count": 1}]
        assert cat["parts"] == []
        assert cat["makers"] == [{"key": "MakerW", "label": "MakerW", "count": 1}]

        sub = G.craft_browse(sub="rifle")
        assert sub["total"] == 1
        assert sub["rows"][0]["key"] == "Test Rifle"
        assert sub["parts"] == []
        assert sub["makers"] == [{"key": "MakerW", "label": "MakerW", "count": 1}]

        part = G.craft_browse(part="头盔")
        assert part["total"] == 1
        assert part["rows"] == [
            _brow(
                "Test Helmet",
                "测试头盔 Test Helmet",
                "护甲",
                "头盔 · 战斗",
                "MakerA",
                False,
            )
        ]
        assert part["makers"] == [{"key": "MakerA", "label": "MakerA", "count": 1}]

        maker = G.craft_browse(maker="DupCo")
        assert maker["total"] == 2
        assert [r["key"] for r in maker["rows"]] == ["Same Widget#1", "Same Widget#2"]
        assert maker["parts"] == [{"key": "头盔", "label": "头盔", "count": 1}]

        q = G.craft_browse(q="Test")
        assert q["total"] == 2
        assert [r["key"] for r in q["rows"]] == ["Test Helmet", "Test Rifle"]

        unlocked = G.craft_browse(unlocked=True)
        assert unlocked["total"] == 3
        assert [r["key"] for r in unlocked["rows"]] == [
            "Hofstede-S2 Mining Laser",
            "Same Widget#1",
            "Test Rifle",
        ]

        offset = G.craft_browse(offset=30)
        assert offset["total"] == 6
        assert offset["rows"] == []

        mat_none = G.craft_browse(mat="MineralA")
        assert mat_none["rows"] == [
            {
                "key": "Gated Component",
                "name": "门槛部件 Gated Component",
                "kind": "发电机",
                "tags": "S1",
                "maker": "GateCo",
                "unlocked": False,
                "need": "矿A 4 SCU（品质 ≥500）",
            },
            {
                "key": "Test Rifle",
                "name": "测试步枪 Test Rifle",
                "kind": "个人武器",
                "tags": "突击步枪",
                "maker": "MakerW",
                "unlocked": True,
                "need": "矿A 7 SCU",
            },
        ]
        assert mat_none["total"] == 2
        assert mat_none["cats"] == [
            {"key": "fpsgear/weapons", "label": "个人武器", "count": 1},
            {"key": "vehiclegear/powerplant", "label": "发电机", "count": 1},
        ]
        assert mat_none["subs"] == [
            {"key": "rifle", "label": "突击步枪", "count": 1},
            {"key": "size1", "label": "S1", "count": 1},
        ]
        assert mat_none["parts"] == []
        assert mat_none["makers"] == [
            {"key": "GateCo", "label": "GateCo", "count": 1},
            {"key": "MakerW", "label": "MakerW", "count": 1},
        ]
        assert mat_none["mat"] == {
            "en": "MineralA",
            "zh": "矿A",
            "q": None,
            "count": 2,
            "ok": None,
            "gated": 1,
            "gates": [500],
            "gated_ok": None,
        }

        mat_ok = G.craft_browse(mat="MineralA", mq=500)
        assert mat_ok["rows"][0]["ok"] is True
        assert "ok" not in mat_ok["rows"][1]
        assert mat_ok["mat"] == {
            "en": "MineralA",
            "zh": "矿A",
            "q": 500,
            "count": 2,
            "ok": 2,
            "gated": 1,
            "gates": [500],
            "gated_ok": 1,
        }

        mat_low = G.craft_browse(mat="MineralA", mq=100)
        assert mat_low["rows"][0]["ok"] is False
        assert "ok" not in mat_low["rows"][1]
        assert mat_low["mat"] == {
            "en": "MineralA",
            "zh": "矿A",
            "q": 100,
            "count": 2,
            "ok": 1,
            "gated": 1,
            "gates": [500],
            "gated_ok": 0,
        }

        mat_bad = G.craft_browse(mat="MineralA", mq="abc")
        assert mat_bad["rows"] == mat_none["rows"]
        assert mat_bad["mat"] == mat_none["mat"]

        assert G.craft_detail("Test Rifle") == _detail_weapon()
        assert G.craft_detail("Test Helmet") == _detail_armor()
        assert G.craft_detail("Hofstede-S2 Mining Laser") == _detail_laser()
        assert G.craft_detail("Same Widget#1") == _detail_dup1()
        assert G.craft_detail("Same Widget#2") == _detail_dup2()
        assert G.craft_detail("Gated Component") == _detail_gated()
        assert G.craft_detail("不存在") == {"error": "未找到此蓝图"}
        assert G.craft_detail("Rifle") == _detail_weapon()

        assert C.display_name(WEAPON) == "测试步枪 Test Rifle"
        assert C.display_name(ARMOR) == "测试头盔 Test Helmet"
        assert C.display_name(LASER) == "霍夫斯泰德 Hofstede-S2 Mining Laser"
        assert C.display_name(DUP1) == "同名部件 Same Widget"
        assert C.display_name(GATED) == "门槛部件 Gated Component"

        assert C.name_parts(WEAPON) == ("测试步枪", "Test Rifle")
        assert C.name_parts(LASER) == ("霍夫斯泰德", "Hofstede-S2 Mining Laser")
        assert C.variant_note(DUP1) == "配方 1/2 · 2 分钟"
        assert C.variant_note(DUP2) == "配方 2/2 · 3 分钟"
        assert C.variant_note(WEAPON) == ""
        assert C.bp_key(WEAPON) == "Test Rifle"
        assert C.bp_key(DUP1) == "Same Widget#1"
        assert C.bp_key(DUP2) == "Same Widget#2"
        assert C.by_key("Same Widget") is DUP1
        assert C.by_key("Same Widget#2") is DUP2
        assert C.by_key("不存在") is None

        assert C.for_item("Test Rifle") is WEAPON
        assert C.for_item("", "测试步枪") is WEAPON
        assert C.for_item("testrifle") is WEAPON
        assert C.for_item("Same Widget") is DUP1
        assert C.for_item("", "同名部件") is DUP1
        assert C.for_item("不存在") is None

        assert C.search("Test Rifle") == [WEAPON]
        assert C.search("Rifle") == [WEAPON]
        assert C.search("  ") == []
        assert [b["n"] for b in C.browse()["rows"]] == [
            "Gated Component",
            "Hofstede-S2 Mining Laser",
            "Same Widget",
            "Same Widget",
            "Test Helmet",
            "Test Rifle",
        ]
    finally:
        G.clear_caches()


def test_craft_browse_spec_tags_and_filters(monkeypatch):
    """CR-D1：船零件那行带尺寸 / 等级 / 类别，选了船零件类多三组筛选（窗口走 app.api）；
    护甲那行和标题带轻 / 中 / 重；个人武器照旧不带"""
    from astral_toolkit.app.api import crafting as api

    _install(monkeypatch)
    extra = {
        "uuid-armor": {"size": 1, "grade": "A", "sub": "Heavy", "s": {}},
        "uuid-dup1": {"size": 1, "grade": "C", "cls": "Civilian", "s": {}},
        # 个人武器的子类型是 Small / Medium / Large：不能当成护甲的轻重
        "uuid-weapon": {**ITEMS["uuid-weapon"], "sub": "Medium"},
    }
    monkeypatch.setattr(itemstats, "item", lambda u: extra.get(u) or _fake_item(u))
    try:
        laser = api.craft_browse(cat="vehiclegear/mininglaser")
        # 采矿激光器游戏里只写尺寸：等级、类别不写也不给下拉（审查 2026-11-08）
        assert [r["tags"] for r in laser["rows"]] == ["S2"]
        assert laser["sizes"] == []  # 子类就是 S2
        assert laser["grades"] == [] and laser["clss"] == []
        cooler = api.craft_browse(cat="vehiclegear/cooler")
        assert [r["tags"] for r in cooler["rows"]] == [
            "S1 · C 级 · 民用 · 配方 1/2 · 2 分钟",
            "S1 · 配方 2/2 · 3 分钟",
        ]
        assert cooler["grades"] == [{"key": "C", "label": "C 级", "count": 1}]
        picked = api.craft_browse(cat="vehiclegear/cooler", grade="C")
        assert [r["key"] for r in picked["rows"]] == ["Same Widget#1"]
        assert api.craft_browse(cat="vehiclegear/cooler", cls="Military")["total"] == 0
        armour = api.craft_browse(cat="fpsgear/armour")
        assert [r["tags"] for r in armour["rows"]] == ["头盔 · 战斗 · 重型"]
        assert not {"sizes", "grades", "clss"} & set(armour)
        assert api.craft_browse(cat="fpsgear/weapons")["rows"][0]["tags"] == "突击步枪"
        # 护甲、个人武器的尺寸 / 等级是物品属性里的默认值：标题只写轻重
        assert G.craft_detail("Test Helmet")["head"]["tags"] == ["重型"]
        assert G.craft_detail("Test Rifle")["head"]["tags"] == []
    finally:
        G.clear_caches()


def test_craft_effect_stats_and_mix(monkeypatch):
    _install(monkeypatch)
    try:
        assert G.craft_effect("Test Rifle", None) == {"slots": [], "total": None}
        assert G.craft_effect("Test Rifle", {}) == {"slots": [], "total": None}
        assert G.craft_effect("Test Rifle", {0: 500}) == {
            "slots": [
                _effect_weapon_barrel(
                    500,
                    1.2,
                    1.5,
                    1.0,
                    0.4,
                    "冲击力 +20.0%（最好 +50.0%）",
                )
            ],
            "total": None,
        }
        assert G.craft_effect("Test Rifle", {0: 1000, 1: 1000}) == {
            "slots": [
                _effect_weapon_barrel(
                    1000,
                    1.5,
                    1.5,
                    1.0,
                    1.0,
                    "冲击力 +50.0%（最好 +50.0%）",
                ),
                _effect_weapon_cabling(
                    1000,
                    1.1,
                    1.1,
                    0.9,
                    1.0,
                    "射速 +10.0%（最好 +10.0%）",
                ),
            ],
            "total": None,
        }
        assert G.craft_effect("Test Rifle", {"0": "750"}) == {
            "slots": [
                _effect_weapon_barrel(
                    750,
                    1.35,
                    1.5,
                    1.0,
                    0.7,
                    "冲击力 +35.0%（最好 +50.0%）",
                )
            ],
            "total": None,
        }
        assert G.craft_effect("不存在", {0: 500}) == {"error": "未找到此蓝图"}

        assert G.craft_effect("Hofstede-S2 Mining Laser", None) == {
            "slots": [],
            "total": None,
        }
        assert G.craft_effect("Hofstede-S2 Mining Laser", {0: 500}) == {
            "slots": [
                _effect_laser_emitter(
                    500,
                    1.0,
                    1.2,
                    0.8,
                    0.5,
                    "激光功率 +0.0%（最好 +20.0%）",
                )
            ],
            "total": {
                "name": "激光功率",
                "mult": None,
                "text": "激光功率合计：汇流排的品质还没填",
            },
        }
        assert G.craft_effect("Hofstede-S2 Mining Laser", {0: 1000, 1: 1000}) == {
            "slots": [
                _effect_laser_emitter(
                    1000,
                    1.2,
                    1.2,
                    0.8,
                    1.0,
                    "激光功率 +20.0%（最好 +20.0%）",
                ),
                _effect_laser_bus(
                    1000,
                    1.3,
                    1.3,
                    0.9,
                    1.0,
                    "激光功率 +30.0%（最好 +30.0%）",
                ),
            ],
            "total": {
                "name": "激光功率",
                "mult": 1.5,
                "text": "激光功率合计 +50.0%（发射器 +20.0% + 汇流排 +30.0%）",
            },
        }
        assert G.craft_effect("Hofstede-S2 Mining Laser", {"0": "750"}) == {
            "slots": [
                _effect_laser_emitter(
                    750,
                    1.1,
                    1.2,
                    0.8,
                    0.75,
                    "激光功率 +10.0%（最好 +20.0%）",
                )
            ],
            "total": {
                "name": "激光功率",
                "mult": None,
                "text": "激光功率合计：汇流排的品质还没填",
            },
        }

        assert G.craft_stats("Test Rifle", None) == {
            "stats": _stats_weapon_default(["枪管", "线缆"]),
            "slots": [],
        }
        assert G.craft_stats("Test Rifle", {}) == {
            "stats": _stats_weapon_default(["枪管", "线缆"]),
            "slots": [],
        }
        assert G.craft_stats("Test Rifle", {0: 500}) == {
            "stats": _stats_weapon_default(["线缆"]),
            "slots": [
                _effect_weapon_barrel(
                    500,
                    1.2,
                    1.5,
                    1.0,
                    0.4,
                    "冲击力 +20.0%（最好 +50.0%）",
                )
            ],
        }
        assert G.craft_stats("Test Rifle", {0: 1000, 1: 1000}) == {
            "stats": _stats_weapon_1000(),
            "slots": [
                _effect_weapon_barrel(
                    1000,
                    1.5,
                    1.5,
                    1.0,
                    1.0,
                    "冲击力 +50.0%（最好 +50.0%）",
                ),
                _effect_weapon_cabling(
                    1000,
                    1.1,
                    1.1,
                    0.9,
                    1.0,
                    "射速 +10.0%（最好 +10.0%）",
                ),
            ],
        }
        assert G.craft_stats("Test Rifle", {"0": "750"}) == {
            "stats": _stats_weapon_750(),
            "slots": [
                _effect_weapon_barrel(
                    750,
                    1.35,
                    1.5,
                    1.0,
                    0.7,
                    "冲击力 +35.0%（最好 +50.0%）",
                )
            ],
        }
        assert G.craft_stats("Test Rifle", {0: 500, 1: 1000}) == {
            "stats": _stats_weapon_mixed(),
            "slots": [
                _effect_weapon_barrel(
                    500,
                    1.2,
                    1.5,
                    1.0,
                    0.4,
                    "冲击力 +20.0%（最好 +50.0%）",
                ),
                _effect_weapon_cabling(
                    1000,
                    1.1,
                    1.1,
                    0.9,
                    1.0,
                    "射速 +10.0%（最好 +10.0%）",
                ),
            ],
        }
        assert G.craft_stats("不存在", {0: 500}) == {"error": "未找到此蓝图"}

        assert G.craft_stats("Hofstede-S2 Mining Laser", None) == {
            "stats": _stats_laser_default(["发射器", "汇流排"]),
            "slots": [],
        }
        assert G.craft_stats("Hofstede-S2 Mining Laser", {0: 500}) == {
            "stats": _stats_laser_default(["汇流排"]),
            "slots": [
                _effect_laser_emitter(
                    500,
                    1.0,
                    1.2,
                    0.8,
                    0.5,
                    "激光功率 +0.0%（最好 +20.0%）",
                )
            ],
        }
        assert G.craft_stats("Hofstede-S2 Mining Laser", {0: 1000, 1: 1000}) == {
            "stats": _stats_laser_1000(),
            "slots": [
                _effect_laser_emitter(
                    1000,
                    1.2,
                    1.2,
                    0.8,
                    1.0,
                    "激光功率 +20.0%（最好 +20.0%）",
                ),
                _effect_laser_bus(
                    1000,
                    1.3,
                    1.3,
                    0.9,
                    1.0,
                    "激光功率 +30.0%（最好 +30.0%）",
                ),
            ],
        }
        assert G.craft_stats("Hofstede-S2 Mining Laser", {"0": "750"}) == {
            "stats": _stats_laser_750(),
            "slots": [
                _effect_laser_emitter(
                    750,
                    1.1,
                    1.2,
                    0.8,
                    0.75,
                    "激光功率 +10.0%（最好 +20.0%）",
                )
            ],
        }

        assert G.craft_mix(0, 0, 2, []) == {
            "ok": False,
            "msg": "需填写每箱材料的品质和数量",
        }
        assert G.craft_mix(10, 700, 2, [[600, 5], [900, 10]]) == {
            "ok": True,
            "goal": 702.0,
            "plan": [
                {"q": 600.0, "have": 5.0, "use": 4.999},
                {"q": 900.0, "have": 10.0, "use": 5.001},
            ],
            "avg": 750.03,
            "total": 10.0,
            "high": 5.001,
            "best": 900.0,
            "msg": "按 702 混合：平均 750.0，高品质材料 5.001 SCU（占 50%）",
        }
        assert G.craft_mix(0, 800, 2, [[500, 3], [950, 2], [700, 4]]) == {
            "ok": True,
            "goal": None,
            "plan": [
                {"q": 500.0, "have": 3.0, "use": 3.0},
                {"q": 700.0, "have": 4.0, "use": 4.0},
                {"q": 950.0, "have": 2.0, "use": 2.0},
            ],
            "avg": 6200 / 9,
            "total": 9.0,
            "high": 0.0,
            "best": 6200 / 9,
            "msg": "全部合并为一箱：9 SCU，品质 688.9",
        }
        assert G.craft_mix(50, 700, 2, [[600, 5]]) == {
            "ok": False,
            "msg": "材料不足：需要 50 SCU，现有 5 SCU",
        }
        assert G.craft_mix(5, 1000, 0, [[999, 5]]) == {
            "ok": False,
            "goal": 1000.0,
            "best": 999.0,
            "msg": "现有材料最高可混合到 999.0，无法达到 1000：需要更高品质的材料",
        }
        assert G.craft_mix(1, 1, 2, [["abc", 1]]) == {
            "ok": False,
            "msg": "品质和数量需为数字",
        }
        assert G.craft_mix(1, 1, 2, [["", 3]]) == {
            "ok": False,
            "msg": "需填写每箱材料的品质和数量",
        }
    finally:
        G.clear_caches()


def _no_note(head):
    return {k: v for k, v in head.items() if k != "note"}


def test_crafting_helpers(monkeypatch):
    _install(monkeypatch)
    try:
        assert C.describe(WEAPON) == _WEAPON_TEXT
        # header 本身不带 note（_craft_struct 才加），比的时候去掉
        assert C.header(WEAPON) == _no_note(_head_weapon())
        assert C.header(LASER) == _no_note(_head_laser())
        assert C.header(ARMOR) == _no_note(_head_armor())

        assert C.effect(WEAPON, {0: 500, 1: 1000}) == [
            _effect_weapon_barrel(
                500,
                1.2,
                1.5,
                1.0,
                0.4,
                "冲击力 +20.0%（最好 +50.0%）",
            ),
            _effect_weapon_cabling(
                1000,
                1.1,
                1.1,
                0.9,
                1.0,
                "射速 +10.0%（最好 +10.0%）",
            ),
        ]
        assert C.stats(WEAPON, {0: 500, 1: 1000}) == _stats_weapon_mixed()

        assert C.mix_targets(WEAPON) == _mix_weapon()
        assert C.mix_targets(LASER) == []
        assert C.mix_targets(GATED) == _mix_gated()

        assert C.craft_slots(WEAPON) == [
            {
                "idx": 0,
                "slot": "枪管",
                "mat": "矿A",
                "mat_en": "MineralA",
                "tiers": (0, 250, 500, 750, 1000),
            },
            {
                "idx": 1,
                "slot": "线缆",
                "mat": "矿A",
                "mat_en": "MineralA",
                "tiers": (0, 250, 500, 750, 1000),
            },
        ]
        assert C.craft_slots(LASER) == [
            {
                "idx": 0,
                "slot": "发射器",
                "mat": "激光件",
                "mat_en": "LaserPart",
                "tiers": (0, 1000),
            },
            {
                "idx": 1,
                "slot": "汇流排",
                "mat": "激光件",
                "mat_en": "LaserPart",
                "tiers": (0, 1000),
            },
        ]
        assert C.craft_slots(GATED) == []

        assert reverse.craft_text(
            [{"slot": "枪管", "q": 500}, {"slot": "线缆", "q": 1000}]
        ) == ("枪管 500 · 线缆 1000")
        assert reverse.craft_text([]) == ""
        assert reverse.craft_text([{"slot": "核心", "q": 500}]) == "核心 500"

        assert [(C.bp_key(bp), q, m) for bp, q, m in C.uses("MineralA")] == [
            ("Test Rifle", 5, 1),
            ("Test Rifle", 2, 1),
            ("Gated Component", 4, 500),
        ]
        assert [(C.bp_key(bp), q, m) for bp, q, m in C.uses("MineralD")] == [
            ("Same Widget#1", 1, 1),
            ("Same Widget#2", 2, 1),
        ]
        assert [(C.bp_key(bp), q, m) for bp, q, m in C.uses("MineralC")] == [
            ("Test Helmet", 2, 1),
        ]

        assert C.mat_summary("MineralA", None) == {
            "count": 2,
            "ok": None,
            "gated": 1,
            "gates": [500],
            "gated_ok": None,
        }
        assert C.mat_summary("MineralA", 500) == {
            "count": 2,
            "ok": 2,
            "gated": 1,
            "gates": [500],
            "gated_ok": 1,
        }
        assert C.mat_summary("MineralA", 900) == {
            "count": 2,
            "ok": 2,
            "gated": 1,
            "gates": [500],
            "gated_ok": 1,
        }
        assert C.mat_summary("MineralC", None) == {
            "count": 1,
            "ok": None,
            "gated": 0,
            "gates": [],
            "gated_ok": None,
        }

        assert C.uses_report("MineralA") == "\n".join(
            [
                "【矿A】被 3 份蓝图用到：",
                "  个人武器 2 份：测试步枪 Test Rifle",
                "  发电机 1 份（其中 1 份要求品质 ≥500）：门槛部件 Gated Component",
            ]
        )
        assert C.uses_report("MineralC") == "\n".join(
            [
                "【矿C】被 1 份蓝图用到：",
                "  护甲 1 份：测试头盔 Test Helmet",
            ]
        )
        assert C.uses_report("MineralD") == "\n".join(
            [
                "【矿D】被 2 份蓝图用到：",
                "  冷却器 2 份：同名部件 Same Widget",
            ]
        )
        assert C.uses_report("Nope") == "Nope：没有蓝图用到它。"

        assert C.quality_hints([("MineralA", 50, 500)]) == [
            "矿A 品质 500（中，线性属性约达最好效果的 50%）：个人武器冲击力已到最高档；有品质门槛的蓝图够做 1/1 份"
        ]
        assert C.quality_hints([("MineralA", 30, 250)]) == [
            "矿A 品质 250（低，线性属性约达最好效果的 25%）：个人武器冲击力现在 ×1.10，品质 ≥500 可提升；有品质门槛的蓝图够做 0/1 份"
        ]
        assert C.quality_hints([("MineralA", 20, 1000)]) == [
            "矿A 品质 1000（高，线性属性约达最好效果的 100%）：有品质门槛的蓝图够做 1/1 份"
        ]

        mods = [
            ("Impact Force", 500, 1000, 1.2, 1.5, False),
            ("Fire Rate", 0, 1000, 0.9, 1.1, False),
            ("Impact Force", 0, 500, 1.0, 1.2, False),
        ]
        grouped = quality.group_mods(mods)
        assert grouped == {
            "Impact Force": [
                (0, 500, 1.0, 1.2, False),
                (500, 1000, 1.2, 1.5, False),
            ],
            "Fire Rate": [(0, 1000, 0.9, 1.1, False)],
        }
        segs = grouped["Impact Force"]
        assert quality.curve_value(segs, 500) == 1.2
        assert quality.curve_value(segs, -1) == 1.0
        assert quality.curve_value(segs, 1001) == 1.5
        assert round(quality.curve_value(segs, 750), 4) == 1.35

        assert quality.laser_total(LASER) == (
            "激光功率合计：发射器 + 汇流排 两个槽的加成相加，品质都 0 时 ×0.70、"
            "都 500 时 ×1.10（和商店买的一样）、都 1000 时 ×1.50。"
            "「采矿助手」页的配置里可以填自造矿头的品质，破碎方案按自造的功率算"
        )
        assert quality.laser_total(LASER, {0: 0, 1: 0}) == {
            "name": "激光功率",
            "mult": 0.7,
            "text": "激光功率合计 -30.0%（发射器 -20.0% + 汇流排 -10.0%）",
        }
        assert quality.laser_total(LASER, {0: 1000, 1: 1000}) == {
            "name": "激光功率",
            "mult": 1.5,
            "text": "激光功率合计 +50.0%（发射器 +20.0% + 汇流排 +30.0%）",
        }
        assert quality.laser_total(LASER, {0: 500}) == {
            "name": "激光功率",
            "mult": None,
            "text": "激光功率合计：汇流排的品质还没填",
        }
        assert quality.laser_total(WEAPON) is None
    finally:
        G.clear_caches()


def test_parse_mods_and_solve_slots(monkeypatch):
    _install(monkeypatch)
    try:
        tokens = [
            SimpleNamespace(box=(0, 10, 10, 10), text="冲击力："),
            SimpleNamespace(box=(100, 10, 10, 10), text="+17.50%"),
            SimpleNamespace(box=(0, 30, 10, 10), text="后坐力操控：-5%"),
            SimpleNamespace(box=(0, 50, 10, 10), text="后坐力冲击：−1,5"),
            SimpleNamespace(box=(0, 70, 10, 10), text="射速：+3"),
            SimpleNamespace(box=(0, 90, 10, 10), text="射速：200rpm"),
            SimpleNamespace(box=(0, 110, 10, 10), text="未知：+1"),
        ]
        assert reverse.parse_mods(tokens) == [
            ("冲击力", 17.5, True, "Impact Force"),
            ("后坐力操控", -5.0, True, "Recoil Handling"),
            ("后坐力冲击", -1.5, False, "Recoil Kick"),
            ("射速", 3.0, False, "Fire Rate"),
        ]

        assert C.solve_slots(
            WEAPON,
            [
                ("冲击力", 20.0, True, "Impact Force"),
                ("射速", 10.0, True, "Fire Rate"),
            ],
        ) == {
            "slots": [
                {
                    "idx": 0,
                    "slot": "枪管",
                    "mat": "矿A",
                    "mat_en": "MineralA",
                    "q": 500,
                },
                {
                    "idx": 1,
                    "slot": "线缆",
                    "mat": "矿A",
                    "mat_en": "MineralA",
                    # 射速的显示符号没核过：0 档（-10%）和 1000 档（+10%）绝对值一样，分不出是哪档
                    "q": 0,
                },
            ],
            "avg": 250,
            "exact": False,  # CR-C1：以前先找到的 0 档赢、还报 exact，现在报不确定
        }
        assert C.solve_slots(
            WEAPON,
            [("冲击力", 999.0, True, "Impact Force")],
        ) == {
            "slots": [
                {
                    "idx": 0,
                    "slot": "枪管",
                    "mat": "矿A",
                    "mat_en": "MineralA",
                    "q": 1000,
                }
            ],
            "avg": 1000,
            "exact": False,
        }
    finally:
        G.clear_caches()


def test_craft_search_order_limit_and_solve_tolerance(monkeypatch):
    """控制台补：包含匹配按（名字长度, 名字）排、搜索条数上限、反推差一点点就不算 exact"""
    _install(monkeypatch)
    try:
        assert G.craft_search("e") == [
            {
                "key": "Test Rifle",
                "name": "测试步枪 Test Rifle",
                "zh": "测试步枪",
                "en": "Test Rifle",
                "note": "",
                "kind": "个人武器",
            },
            {
                "key": "Same Widget#1",
                "name": "同名部件 Same Widget｜配方 1/2 · 2 分钟",
                "zh": "同名部件",
                "en": "Same Widget",
                "note": "配方 1/2 · 2 分钟",
                "kind": "冷却器",
            },
            {
                "key": "Same Widget#2",
                "name": "同名部件 Same Widget｜配方 2/2 · 3 分钟",
                "zh": "同名部件",
                "en": "Same Widget",
                "note": "配方 2/2 · 3 分钟",
                "kind": "冷却器",
            },
            {
                "key": "Test Helmet",
                "name": "测试头盔 Test Helmet",
                "zh": "测试头盔",
                "en": "Test Helmet",
                "note": "",
                "kind": "护甲",
            },
            {
                "key": "Gated Component",
                "name": "门槛部件 Gated Component",
                "zh": "门槛部件",
                "en": "Gated Component",
                "note": "",
                "kind": "发电机",
            },
            {
                "key": "Hofstede-S2 Mining Laser",
                "name": "霍夫斯泰德 Hofstede-S2 Mining Laser",
                "zh": "霍夫斯泰德",
                "en": "Hofstede-S2 Mining Laser",
                "note": "",
                "kind": "采矿激光器",
            },
        ]
        assert [C.bp_key(b) for b in C.search("e", limit=3)] == [
            "Test Rifle",
            "Same Widget#1",
            "Same Widget#2",
        ]
        assert C.solve_slots(
            WEAPON,
            [
                ("冲击力", 20.1, True, "Impact Force"),
                ("射速", 10.0, True, "Fire Rate"),
            ],
        ) == {
            "slots": [
                {
                    "idx": 0,
                    "slot": "枪管",
                    "mat": "矿A",
                    "mat_en": "MineralA",
                    "q": 500,
                },
                {"idx": 1, "slot": "线缆", "mat": "矿A", "mat_en": "MineralA", "q": 0},
            ],
            "avg": 250,
            "exact": False,
        }
    finally:
        G.clear_caches()


def test_crafting_gamedata_unavailable(monkeypatch):
    G.clear_caches()
    warnings = []

    class _Log:
        def warning(self, msg, *args):
            warnings.append((msg, args))

    def bad_catalog(snap=None):
        raise GamedataError("bad")

    def bad_containing(q, snap=None):
        raise GamedataError("bad")

    monkeypatch.setattr(C, "_WARNED", set())
    monkeypatch.setattr(C, "_EMPTY", None)
    monkeypatch.setattr(gd_crafting, "catalog", bad_catalog)
    monkeypatch.setattr(gd_crafting, "containing", bad_containing)
    monkeypatch.setattr(logging, "getLogger", lambda name: _Log())
    try:
        assert C.blueprints() == []
        assert C.blueprints() == []
        assert len(warnings) == 1
        assert warnings[0] == (
            "制造数据读不到：%s",
            ("游戏数据库不可用：GamedataError",),
        )
        assert G.craft_search("x") == []
    finally:
        G.clear_caches()
