"""物品查询展示层（IQ-B5）：只排版，不读数据。"""

from astral_toolkit.app.presenters import catalog as P
from astral_toolkit.catalog.results import ItemInfo, LootLookup
from astral_toolkit.core import i18n


def test_present_search_results_source_and_key_order(monkeypatch):
    monkeypatch.setattr(i18n, "SHOP_CAT_ZH", {"WeaponPersonal": "单兵武器"})
    rows = [
        {
            "en": "Shop Gun",
            "zh": "商店枪",
            "shop": 11,
            "cat": "WeaponPersonal",
            "loot": True,
        },
        {
            "en": "Loot Gun",
            "zh": "掉落炮",
            "shop": None,
            "cat": "",
            "loot": True,
            "wtype": "WeaponGun",
            "wsize": 1,
        },
        {
            "en": "Wiki Missile",
            "zh": "维基导弹",
            "shop": None,
            "cat": "",
            "loot": False,
            "wiki": True,
            "wtype": "MissileLauncher",
            "wsize": 5,
        },
        {
            "en": "Only Loc",
            "zh": "只有汉化",
            "shop": None,
            "cat": "",
            "loot": False,
            "wiki": False,
            "wtype": "",
            "wsize": None,
        },
    ]

    out = P.present_search_results(rows)

    assert [r["src"] for r in out] == ["shop", "loot", "wiki", "loc"]
    assert [r["category"] for r in out] == [
        "单兵武器",
        "舰炮 S1",
        "导弹架 S5",
        "",
    ]
    for row in out:
        assert list(row) == ["id", "name", "zh", "category", "src"]


def test_present_search_results_wiki_categories(monkeypatch):
    monkeypatch.setattr(i18n, "SHOP_CAT_ZH", {})

    def row(wtype, wsize):
        return {
            "en": "X",
            "zh": "",
            "shop": None,
            "cat": "",
            "loot": False,
            "wtype": wtype,
            "wsize": wsize,
        }

    rows = [
        row("MissileLauncher", 2),
        row("QuantumDrive", 1),
        row("Turret", 1),
        row("QuantumDrive", None),
        row("Turret", 0),
        row("Bogus", 3),
        row("", 3),
    ]

    out = P.present_search_results(rows)

    assert [r["category"] for r in out] == [
        "导弹架 S2",
        "量子驱动器 S1",
        "炮塔",
        "量子驱动器",
        "炮塔",
        "Bogus S3",
        "",
    ]


def test_present_search_results_empty():
    assert P.present_search_results([]) == []


def test_present_item_info_copies_and_keeps_facts(monkeypatch):
    monkeypatch.setattr(i18n, "SHOP_CAT_ZH", {"WeaponMining": "采矿激光器"})
    facts = {"name": "X", "zh": "旧中文", "category": "WeaponMining"}
    before = dict(facts)
    info = ItemInfo(facts=facts, zh="新中文", goal="目标提示")

    out = P.present_item_info(info)

    assert facts == before
    assert out is not facts
    assert list(out) == ["name", "zh", "category", "goal"]
    assert out["zh"] == "新中文"
    assert out["category"] == "采矿激光器"
    assert out["goal"] == "目标提示"


def test_present_item_info_category_fallbacks(monkeypatch):
    monkeypatch.setattr(i18n, "SHOP_CAT_ZH", {"WeaponMining": "采矿激光器"})

    empty = ItemInfo(facts={"name": "A", "zh": "", "category": ""}, zh="甲", goal="")
    out_empty = P.present_item_info(empty)
    assert out_empty["category"] == ""
    assert list(out_empty) == ["name", "zh", "category", "goal"]

    none = ItemInfo(facts={"name": "B", "zh": "", "category": None}, zh="乙", goal="")
    out_none = P.present_item_info(none)
    assert out_none["category"] is None

    unknown = ItemInfo(
        facts={"name": "C", "zh": "", "category": "UnknownCat"}, zh="丙", goal=""
    )
    assert P.present_item_info(unknown)["category"] == "UnknownCat"

    missing = ItemInfo(facts={"name": "D", "zh": ""}, zh="丁", goal="")
    out_missing = P.present_item_info(missing)
    assert "category" not in out_missing
    assert list(out_missing) == ["name", "zh", "goal"]


def test_present_item_loot_passes_through_and_error_priority():
    assert P.present_item_loot(LootLookup()) == {"loot": None}

    pending = {"pending": True}
    out = P.present_item_loot(LootLookup(loot=pending))
    assert out == {"loot": {"pending": True}}
    assert out["loot"] is pending

    assert P.present_item_loot(
        LootLookup(loot={"pending": True}, error=ValueError("x"))
    ) == {"loot": {"error": "掉落数据出错：x"}}
