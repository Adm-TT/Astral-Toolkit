"""维科洛兑换黄金测试：不读本机数据，锁住任务接口和 crafting.wikelo 现在的输出。

维科洛链拆代码时，下面这些字面量应当一个字都不变。
"""

from contextlib import contextmanager

from astral_toolkit import gamedata
from astral_toolkit.contracts.textkeys import fold_mixed_loose
from astral_toolkit.crafting import wikelo
from astral_toolkit.crafting import wikelo_rules
from astral_toolkit.gamedata import wikelo as gd_wikelo
from astral_toolkit.tasks import goals
from astral_toolkit.tasks.catalog_queries import acquire as QA
from astral_toolkit.trade import names

_VEHICLE = {
    "id": "veh-1",
    "type": "载具",
    "t": "极地巡逻车",
    "te": "Polaris Rover",
    "rz": "极地涂装 巡逻车",
    "rewards": [],
    "req": [
        {"n": "Polaris Bit", "z": "Polaris 点数", "q": 15, "u": "个"},
    ],
    "systems": ["Pyro"],
}
_GEAR = {
    "id": "gear-1",
    "type": "装备/物品",
    "t": "探索护甲",
    "te": "Explorer Armor",
    "rz": "",
    "rewards": ["探索头盔", "Explorer Chest", "探索手套"],
    "req": [{"n": "Kopion Horn", "z": "寇骈角", "q": 2, "u": "个"}],
    "systems": [],
}
_COLLECTION = {
    "id": "col-1",
    "type": "收集",
    "t": "收集样本",
    "te": "Collection Run",
    "rz": "",
    "rewards": [],
    "req": [{"n": "Blue Moon Fungus", "z": "蓝月菌", "q": 1, "u": "个"}],
    "systems": [],
}
_RECOMB = {
    "id": "recomb-1",
    "type": "装备/物品",
    "t": "重组样本兑换",
    "te": "Recombination Exchange",
    "rz": "",
    "rewards": ["重组奖励"],
    "req": [
        {"n": "RCMBNT-XTL", "z": "重组样本", "q": 5, "u": "个"},
        {"n": "RCMBNT-PWL", "z": "重组样本", "q": 5, "u": "个"},
        {"n": "RCMBNT-RGL", "z": "重组样本", "q": 5, "u": "个"},
        {"n": "RCMBNT-SPC", "z": "重组样本", "q": 3, "u": "个"},
    ],
    "systems": [],
}
_ORE = {
    "id": "ore-1",
    "type": "收集",
    "t": "杰金样本",
    "te": "Jaclium Sample",
    "rz": "杰金奖励",
    "rewards": [],
    "req": [{"n": "Jaclium (Ore)", "z": "杰金矿石", "q": 0, "u": "个"}],
    "systems": [],
}
_FAVOR = {
    "id": "favor-1",
    "type": "装备/物品",
    "t": "换人情",
    "te": "Trade Favor",
    "rz": "",
    "rewards": [],
    "req": [{"n": "Wikelo Favor", "z": "维科洛人情", "q": 1, "u": "个"}],
    "systems": [],
}
_ROWS = [_VEHICLE, _GEAR, _COLLECTION, _RECOMB, _ORE, _FAVOR]

_RCMBNT_NOTE = (
    "重组样本",
    "玛瑙设施（Onyx Facility）任务里在终端合成："
    "催化剂 XTL/PWL/RGL 配反应物，做出的样本送到设施货梯",
)


@contextmanager
def _clean_caches():
    goals.clear_caches()
    try:
        yield
    finally:
        goals.clear_caches()


def _make_contracts(rows=None):
    rows = list(_ROWS if rows is None else rows)
    by_req = {}
    for c in rows:
        for i, r in enumerate(c["req"]):
            by_req[(c["id"], i)] = (c, r)
    return gd_wikelo.Contracts(rows, by_req)


def _fake_requiring(rows):
    def require(norm_en, norm_zh, snap=None):
        out = []
        for c in rows:
            for r in c["req"]:
                if (norm_en is not None and fold_mixed_loose(r["n"]) == norm_en) or (
                    norm_zh is not None and fold_mixed_loose(r["z"]) == norm_zh
                ):
                    out.append((c, r))
        return out

    return require


def _patch_data(monkeypatch, rows=None, calls=None):
    contracts = _make_contracts(rows)

    def contracts_fn(snap=None):
        if calls is not None:
            calls.append(1)
        return contracts.rows  # 真的 contracts() 返回 rows 列表

    monkeypatch.setattr(gd_wikelo, "contracts", contracts_fn)
    monkeypatch.setattr(gd_wikelo, "requiring", _fake_requiring(contracts.rows))
    return contracts


def _no_exact(zh="", en=""):
    return None


def _install(monkeypatch, rows=None, calls=None):
    contracts = _patch_data(monkeypatch, rows, calls)
    monkeypatch.setattr(gd_wikelo, "print_places", lambda key, snap=None: [])
    monkeypatch.setattr(QA, "material_source", lambda name: "来源：" + name)
    monkeypatch.setattr(names, "canonical_exact", _no_exact)
    return contracts


def test_wikelo_search_filters_and_rewards(monkeypatch):
    with _clean_caches():
        _install(monkeypatch)

        assert goals.wikelo_search("") == [
            {
                "key": "veh-1",
                "title": "极地巡逻车",
                "type": "载具",
                "reward": "极地涂装 巡逻车",
            },
            {
                "key": "gear-1",
                "title": "探索护甲",
                "type": "装备/物品",
                "reward": "探索头盔、Explorer Chest",
            },
            {
                "key": "col-1",
                "title": "收集样本",
                "type": "收集",
                "reward": "",
            },
            {
                "key": "recomb-1",
                "title": "重组样本兑换",
                "type": "装备/物品",
                "reward": "重组奖励",
            },
            {
                "key": "ore-1",
                "title": "杰金样本",
                "type": "收集",
                "reward": "杰金奖励",
            },
            {
                "key": "favor-1",
                "title": "换人情",
                "type": "装备/物品",
                "reward": "",
            },
        ]
        assert goals.wikelo_search("极地巡逻车") == [
            {
                "key": "veh-1",
                "title": "极地巡逻车",
                "type": "载具",
                "reward": "极地涂装 巡逻车",
            }
        ]
        assert goals.wikelo_search("Polaris Rover") == [
            {
                "key": "veh-1",
                "title": "极地巡逻车",
                "type": "载具",
                "reward": "极地涂装 巡逻车",
            }
        ]
        assert goals.wikelo_search("极地涂装 巡逻车") == [
            {
                "key": "veh-1",
                "title": "极地巡逻车",
                "type": "载具",
                "reward": "极地涂装 巡逻车",
            }
        ]
        assert goals.wikelo_search("Polaris Bit") == [
            {
                "key": "veh-1",
                "title": "极地巡逻车",
                "type": "载具",
                "reward": "极地涂装 巡逻车",
            }
        ]
        assert goals.wikelo_search("探索头盔") == [
            {
                "key": "gear-1",
                "title": "探索护甲",
                "type": "装备/物品",
                "reward": "探索头盔、Explorer Chest",
            }
        ]
        assert goals.wikelo_search("Explorer Chest") == [
            {
                "key": "gear-1",
                "title": "探索护甲",
                "type": "装备/物品",
                "reward": "探索头盔、Explorer Chest",
            }
        ]
        assert goals.wikelo_search("Kopion Horn") == [
            {
                "key": "gear-1",
                "title": "探索护甲",
                "type": "装备/物品",
                "reward": "探索头盔、Explorer Chest",
            }
        ]
        assert goals.wikelo_search("寇骈角") == [
            {
                "key": "gear-1",
                "title": "探索护甲",
                "type": "装备/物品",
                "reward": "探索头盔、Explorer Chest",
            }
        ]
        assert goals.wikelo_search("Jaclium (Ore)") == [
            {
                "key": "ore-1",
                "title": "杰金样本",
                "type": "收集",
                "reward": "杰金奖励",
            }
        ]
        assert goals.wikelo_search("杰金矿石") == [
            {
                "key": "ore-1",
                "title": "杰金样本",
                "type": "收集",
                "reward": "杰金奖励",
            }
        ]
        assert goals.wikelo_search("不存在的东西") == []


def test_wikelo_search_limits_to_sixty(monkeypatch):
    rows = [
        {
            "id": f"c-{i:02d}",
            "type": "收集",
            "t": f"兑换{i:02d}",
            "te": f"Contract {i:02d}",
            "rz": "",
            "rewards": [],
            "req": [],
            "systems": [],
        }
        for i in range(61)
    ]
    with _clean_caches():
        _install(monkeypatch, rows)
        out = goals.wikelo_search("兑换")
        assert len(out) == 60
        assert out[0] == {
            "key": "c-00",
            "title": "兑换00",
            "type": "收集",
            "reward": "",
        }
        assert out[-1] == {
            "key": "c-59",
            "title": "兑换59",
            "type": "收集",
            "reward": "",
        }
        assert [x["key"] for x in out] == [f"c-{i:02d}" for i in range(60)]


def test_wikelo_detail_each_contract(monkeypatch):
    with _clean_caches():
        _install(monkeypatch)

        assert goals.wikelo_detail("veh-1") == {
            "id": "veh-1",
            "title": "极地巡逻车",
            "type": "载具",
            "reward": "极地涂装 巡逻车",
            "req": [
                {
                    "name": "Polaris 点数（Polaris Bit）",
                    "q": "15 个",
                    "tip": "来源：Polaris Bit",
                    "en": "Polaris Bit",
                    "zh": "Polaris 点数",
                }
            ],
        }
        assert goals.wikelo_detail("gear-1") == {
            "id": "gear-1",
            "title": "探索护甲",
            "type": "装备/物品",
            "reward": "探索头盔、Explorer Chest、探索手套",
            "req": [
                {
                    "name": "寇骈角（Kopion Horn）",
                    "q": "2 个",
                    "tip": "来源：Kopion Horn",
                    "en": "Kopion Horn",
                    "zh": "寇骈角",
                }
            ],
        }
        assert goals.wikelo_detail("col-1") == {
            "id": "col-1",
            "title": "收集样本",
            "type": "收集",
            "reward": "Collection Run",
            "req": [
                {
                    "name": "蓝月菌（Blue Moon Fungus）",
                    "q": "1 个",
                    "tip": "来源：Blue Moon Fungus",
                    "en": "Blue Moon Fungus",
                    "zh": "蓝月菌",
                }
            ],
        }
        assert goals.wikelo_detail("recomb-1") == {
            "id": "recomb-1",
            "title": "重组样本兑换",
            "type": "装备/物品",
            "reward": "重组奖励",
            "req": [
                {
                    "name": "重组样本（RCMBNT-XTL、RCMBNT-PWL、RCMBNT-RGL）",
                    "q": "5 个 各",
                    "tip": "来源：RCMBNT-XTL",
                    "en": "RCMBNT-XTL",
                    "zh": "重组样本",
                },
                {
                    "name": "重组样本（RCMBNT-SPC）",
                    "q": "3 个",
                    "tip": "来源：RCMBNT-SPC",
                    "en": "RCMBNT-SPC",
                    "zh": "重组样本",
                },
            ],
        }
        assert goals.wikelo_detail("ore-1") == {
            "id": "ore-1",
            "title": "杰金样本",
            "type": "收集",
            "reward": "杰金奖励",
            "req": [
                {
                    "name": "杰金矿石（Jaclium (Ore)）",
                    "q": "若干",
                    "tip": "来源：Jaclium (Ore)",
                    "en": "Jaclium (Ore)",
                    "zh": "杰金矿石",
                }
            ],
        }
        assert goals.wikelo_detail("favor-1") == {
            "id": "favor-1",
            "title": "换人情",
            "type": "装备/物品",
            "reward": "Trade Favor",
            "req": [
                {
                    "name": "维科洛人情（Wikelo Favor）",
                    "q": "1 个",
                    "tip": "来源：Wikelo Favor",
                    "en": "Wikelo Favor",
                    "zh": "维科洛人情",
                }
            ],
        }


def test_wikelo_detail_reward_takes_first_four(monkeypatch):
    row = {
        "id": "many",
        "type": "装备/物品",
        "t": "多奖励",
        "te": "Fallback Title",
        "rz": "",
        "rewards": ["奖1", "奖2", "奖3", "奖4", "奖5"],
        "req": [],
        "systems": [],
    }
    with _clean_caches():
        _install(monkeypatch, [row])
        assert goals.wikelo_detail("many") == {
            "id": "many",
            "title": "多奖励",
            "type": "装备/物品",
            "reward": "奖1、奖2、奖3、奖4",
            "req": [],
        }


def test_wikelo_detail_tip_exception_is_empty(monkeypatch):
    with _clean_caches():
        _install(monkeypatch)

        def source(name):
            if name == "Kopion Horn":
                raise RuntimeError("来源坏了")
            return "来源：" + name

        monkeypatch.setattr(QA, "material_source", source)
        out = goals.wikelo_detail("gear-1")
        assert out["req"] == [
            {
                "name": "寇骈角（Kopion Horn）",
                "q": "2 个",
                "tip": "",
                "en": "Kopion Horn",
                "zh": "寇骈角",
            }
        ]


def test_wikelo_detail_not_found(monkeypatch):
    with _clean_caches():
        _install(monkeypatch)
        assert goals.wikelo_detail("没有这个") == {"error": "未找到此兑换，需重新搜索"}


def test_wikelo_search_then_detail_uses_cache(monkeypatch):
    with _clean_caches():
        calls = []
        _install(monkeypatch, calls=calls)
        assert goals.wikelo_search("极地巡逻车")[0]["key"] == "veh-1"
        assert calls == [1]
        assert goals.wikelo_detail("veh-1")["title"] == "极地巡逻车"
        assert calls == [1]

        goals.clear_caches()
        assert goals.wikelo_detail("veh-1")["title"] == "极地巡逻车"
        assert calls == [1, 1]


def test_wikelo_module_search(monkeypatch):
    with _clean_caches():
        _install(monkeypatch)
        assert wikelo.search("") == _ROWS
        assert wikelo.search("极地巡逻车") == [_VEHICLE]
        assert wikelo.search("pOlArIs RoVeR") == [_VEHICLE]
        assert wikelo.search("探索头盔") == [_GEAR]
        assert wikelo.search("Explorer Chest") == [_GEAR]
        assert wikelo.search("Kopion Horn") == [_GEAR]
        assert wikelo.search("寇骈角") == [_GEAR]
        assert wikelo.search("Jaclium (Ore)") == [_ORE]
        assert wikelo.search("杰金矿石") == [_ORE]
        assert wikelo.search("不存在") == []


def test_wikelo_uses_exact_names(monkeypatch):
    with _clean_caches():
        _install(monkeypatch)
        assert wikelo.uses("Kopion Horn", "寇骈角") == [(_GEAR, 2, "个")]
        assert wikelo.uses("Kopion Horn", "") == [(_GEAR, 2, "个")]
        assert wikelo.uses("", "寇骈角") == [(_GEAR, 2, "个")]
        assert wikelo.uses("", "") == []


def test_wikelo_uses_empty_chinese_not_compared(monkeypatch):
    row = {
        "id": "empty-zh",
        "type": "收集",
        "t": "空中文",
        "te": "Empty Chinese",
        "rz": "",
        "rewards": [],
        "req": [{"n": "Some Item", "z": "", "q": 1, "u": "个"}],
        "systems": [],
    }
    with _clean_caches():
        _install(monkeypatch, [row])
        assert wikelo.uses("", " ") == []
        assert wikelo.uses("Some Item", "") == [(row, 1, "个")]


def test_wikelo_uses_containment_min_length(monkeypatch):
    with _clean_caches():
        _install(monkeypatch)
        assert wikelo.uses("aris", "") == [(_VEHICLE, 15, "个")]
        assert wikelo.uses("Bit", "") == []


def test_wikelo_uses_full_name_not_loosened_distinct(monkeypatch):
    with _clean_caches():
        _install(monkeypatch)

        def exact(zh="", en=""):
            if en == "Polaris Bit Extra" or zh == "Polaris 点数 扩展":
                return (zh, en)
            return None

        monkeypatch.setattr(names, "canonical_exact", exact)
        assert wikelo.uses("Polaris Bit Extra", "Polaris 点数 扩展") == []


def test_wikelo_uses_full_name_recognises_ore_suffix_distinct(monkeypatch):
    row = {
        "id": "sald",
        "type": "收集",
        "t": "萨德宁兑换",
        "te": "Saldynium Exchange",
        "rz": "",
        "rewards": [],
        "req": [{"n": "Saldynium (Ore)", "z": "萨德宁矿石", "q": 7, "u": "个"}],
        "systems": [],
    }
    with _clean_caches():
        _install(monkeypatch, [row])

        def exact(zh="", en=""):
            if en == "Saldynium" or zh == "萨德宁":
                return (zh, en)
            return None

        monkeypatch.setattr(names, "canonical_exact", exact)
        assert wikelo.uses("Saldynium", "萨德宁") == [(row, 7, "个")]
        assert wikelo.uses("", "萨德宁") == [(row, 7, "个")]


def test_wikelo_uses_keeps_order_and_units(monkeypatch):
    """一样东西被 6 个兑换用到：按兑换的顺序全列出来，数量和单位（个 / SCU）照原样"""
    rows = [
        {
            "id": f"u{i}",
            "type": "载具",
            "t": f"兑换{i}",
            "te": "",
            "rz": "",
            "rewards": [],
            "req": [
                {
                    "n": "Kopion Horn",
                    "z": "寇骈角",
                    "q": i + 1,
                    "u": "个" if i % 2 == 0 else "SCU",
                }
            ],
            "systems": [],
        }
        for i in range(6)
    ]
    with _clean_caches():
        _install(monkeypatch, rows)
        got = [(c["t"], q, u) for c, q, u in wikelo.uses("Kopion Horn", "寇骈角")]
        assert got == [
            (f"兑换{i}", i + 1, "个" if i % 2 == 0 else "SCU") for i in range(6)
        ]


def test_wikelo_req_label_and_note_for():
    with _clean_caches():
        assert wikelo_rules.req_label({"n": "Polaris Bit", "z": "Polaris 点数"}) == (
            "Polaris 点数（Polaris Bit）"
        )
        assert wikelo_rules.req_label({"n": "Only English", "z": ""}) == "Only English"
        assert wikelo_rules.note_for("RCMBNT-XTL") == _RCMBNT_NOTE
        assert wikelo_rules.note_for("Wikelo Favor") == (
            "维科洛人情",
            "做维科洛的「换人情」兑换拿到",
        )
        assert wikelo_rules.note_for("别的东西") is None


def test_wikelo_source_note_variants(monkeypatch):
    def places(key, snap=None):
        return {
            "rcmbnt-xtl": ["不该出现"],
            "vanduul metal": ["Area18", "", None, "Orison"],
            "metamaterial test #146": [],
            "unknown": ["Lorville"],
            "dchs-05 with print": ["Ruin Station"],
        }.get(key, [])

    with _clean_caches():
        monkeypatch.setattr(gd_wikelo, "print_places", places)
        assert wikelo.source_note("RCMBNT-XTL") == _RCMBNT_NOTE[1]
        assert wikelo.source_note("Vanduul Metal") == (
            "尼克斯（Nyx）星系的剜度飞行员尸体上搜；"
            "「剜度科技走私者」任务目标"
            "；打印：Area18；Orison"
        )
        assert wikelo.source_note("Metamaterial Test #146") == (
            "只能制造：接维科洛「Extra Special Wolf」兑换得到蓝图，"
            "要钛 Q≥900、愈金 Q≥800"
        )
        assert wikelo.source_note("Unknown") == "打印：Lorville"
        assert wikelo.source_note("DCHS-05 Board") == (
            "派罗争夺区（Contested Zone）内打印"
        )
        assert wikelo.source_note("DCHS-05 With Print") == ("打印：Ruin Station")
        assert wikelo.source_note("Nothing Here") == ""

        def bad(key, snap=None):
            raise gamedata.GamedataError("打印地点库不可用")

        monkeypatch.setattr(gd_wikelo, "print_places", bad)
        assert wikelo.source_note("DCHS-99") == ("派罗争夺区（Contested Zone）内打印")


def test_wikelo_describe_with_and_without_where():
    c = {
        "id": "d-1",
        "type": "载具",
        "t": "试兑换",
        "te": "Test Exchange",
        "rz": "",
        "rewards": ["奖A", "奖B"],
        "req": [
            {"n": "RCMBNT-A", "z": "重组样本", "q": 5, "u": "个"},
            {"n": "RCMBNT-B", "z": "重组样本", "q": 5, "u": "个"},
            {"n": "Jaclium (Ore)", "z": "杰金矿石", "q": 0, "u": "个"},
        ],
        "systems": [],
    }

    def where(name):
        return "终端合成" if name.startswith("RCMBNT") else ""

    with _clean_caches():
        assert wikelo_rules.describe(c) == (
            "【试兑换】载具｜换：奖A、奖B\n"
            "  · 重组样本（RCMBNT-A、RCMBNT-B） 各 × 5 个\n"
            "  · 杰金矿石（Jaclium (Ore)） × 若干"
        )
        assert wikelo_rules.describe(c, where) == (
            "【试兑换】载具｜换：奖A、奖B\n"
            "  · 重组样本（RCMBNT-A、RCMBNT-B） 各 × 5 个｜终端合成\n"
            "  · 杰金矿石（Jaclium (Ore)） × 若干"
        )


def test_wikelo_library_unavailable(monkeypatch):
    def boom(snap=None):
        raise gamedata.GamedataError("维科洛库不可用")

    with _clean_caches():
        monkeypatch.setattr(gd_wikelo, "contracts", boom)
        assert wikelo.load() == []
        assert goals.wikelo_search("") == []
