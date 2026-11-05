"""物品查询接口黄金测试：不读本机数据，锁住 `tasks/trade.py` 现在的组合与排版。

IQ-B1～B7 拆物品查询链时，这些字面量应当一个字都不变。
"""

from datetime import datetime, timezone
from decimal import Decimal as D
from types import SimpleNamespace
from typing import Any

from astral_toolkit.core import i18n
from astral_toolkit.crafting import acquire, itemsearch, loot
from astral_toolkit.tasks import trade as T
from astral_toolkit.trade.models import Item, PriceKey, PriceStats, ProviderResult

NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
MARKET = "UEX 最低 4,200｜均价 5,000\nSCM 最低 9,500"


def _market_fixture():
    item = Item("uex:4741", "Carinite")
    uex = PriceStats(
        PriceKey("uex", item.id, "q6", "UEC", "scu", "4.3", "buy"),
        D("5000"),
        D("4200"),
        3,
        NOW,
        week_mean=D("4800"),
    )
    scm = PriceStats(
        PriceKey("scm", item.id, "q0", "UEC", "unit", "4.3", "buy"),
        None,
        D("9500"),
        2,
        NOW,
    )
    results = (
        ProviderResult("uex", "ok", (uex,), items=(item,)),
        ProviderResult("scm", "empty"),
        ProviderResult("scm", "ok", (scm,)),
    )
    return item, results


def _market_trade(item, results, price_calls=None):
    def prices(it, quality, op):
        if price_calls is not None:
            price_calls.append((it, quality, op))
        return results

    return SimpleNamespace(
        catalog=SimpleNamespace(get=lambda i: item if i == item.id else None),
        prices=prices,
        label=lambda _i: "科力晶（Carinite）",
    )


def _market_rows():
    return [
        {
            "src": "UEX",
            "quality": "Q6",
            "unit": "scu",
            "currency": "UEC",
            "mean": "5,000",
            "min": "4,200",
            "count": 3,
            "week": "4,800",
            "state": "",
        },
        {"src": "SCM", "state": "暂无报价"},
        {
            "src": "SCM",
            "quality": "Q0",
            "unit": "unit",
            "currency": "UEC",
            "mean": "—",
            "min": "9,500",
            "count": 2,
            "week": "",
            "state": "",
        },
    ]


def test_item_search_maps_rows(monkeypatch):
    rows = [
        {
            "en": "Shop Gun",
            "zh": "商店枪",
            "shop": 11,
            "cat": "WeaponPersonal",
            "loot": False,
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
    seen = []

    def fake_find(q, limit=30):
        seen.append((q, limit))
        return [dict(r) for r in rows]

    monkeypatch.setattr(itemsearch, "find", fake_find)
    monkeypatch.setattr(i18n, "SHOP_CAT_ZH", {"WeaponPersonal": "单兵武器"})

    assert T.item_search("x") == [
        {
            "id": 11,
            "name": "Shop Gun",
            "zh": "商店枪",
            "category": "单兵武器",
            "src": "shop",
        },
        {
            "id": None,
            "name": "Loot Gun",
            "zh": "掉落炮",
            "category": "舰炮 S1",
            "src": "loot",
        },
        {
            "id": None,
            "name": "Wiki Missile",
            "zh": "维基导弹",
            "category": "导弹架 S5",
            "src": "wiki",
        },
        {
            "id": None,
            "name": "Only Loc",
            "zh": "只有汉化",
            "category": "",
            "src": "loc",
        },
    ]
    assert seen == [("x", 30)]


def test_item_info_calls_and_enriches(monkeypatch):
    payload = {
        "name": "Hofstede-S2 Mining Laser",
        "zh": "旧中文",
        "category": "WeaponMining",
    }
    calls = []

    def fake_info(
        name_en="",
        name_zh="",
        item_id=None,
        show_loot=True,
        exact=False,
        loot_online=True,
    ):
        calls.append((name_en, name_zh, item_id, show_loot, exact, loot_online))
        return dict(payload)

    monkeypatch.setattr(acquire, "info", fake_info)
    monkeypatch.setattr(i18n, "gear_zh_of_item", lambda _en: "霍夫斯泰德")
    monkeypatch.setattr(i18n, "SHOP_CAT_ZH", {"WeaponMining": "采矿激光器"})

    def never(_en):
        raise AssertionError("不该走 _zh_of")

    monkeypatch.setattr(T, "_zh_of", never)
    token = object()
    goal_calls = []
    text_calls = []

    def fake_goal_for(*names):
        goal_calls.append(names)
        return token

    def fake_goal_text(g):
        text_calls.append(g)
        return "目标文本"

    monkeypatch.setattr(T, "_goal_for", fake_goal_for)
    monkeypatch.setattr(T, "_goal_text", fake_goal_text)

    exact: Any = 1  # 故意传 1：item_info 要把它转成 True 再交给 acquire.info
    out = T.item_info(
        "Hofstede-S2 Mining Laser", "旧中文", id=7, loot=False, exact=exact
    )

    assert calls == [
        ("Hofstede-S2 Mining Laser", "旧中文", 7, False, True, False),
    ]
    assert goal_calls == [
        (
            "Hofstede-S2 Mining Laser",
            "Hofstede-S2 Mining Laser",
            "旧中文",
            "霍夫斯泰德",
        )
    ]
    assert text_calls == [token]
    assert out["zh"] == "霍夫斯泰德"
    assert out["category"] == "采矿激光器"
    assert out["goal"] == "目标文本"


def test_item_info_keeps_original_zh_and_empty_goal(monkeypatch):
    payload = {"name": "X", "zh": "原名", "category": ""}

    def fake_info(
        name_en="",
        name_zh="",
        item_id=None,
        show_loot=True,
        exact=False,
        loot_online=True,
    ):
        return dict(payload)

    monkeypatch.setattr(acquire, "info", fake_info)
    monkeypatch.setattr(i18n, "gear_zh_of_item", lambda _en: "")

    def never(_en):
        raise AssertionError("不该走 _zh_of")

    monkeypatch.setattr(T, "_zh_of", never)
    monkeypatch.setattr(T, "_goal_for", lambda *args: None)

    def never_text(_g):
        raise AssertionError("没有目标时不该写 goal")

    monkeypatch.setattr(T, "_goal_text", never_text)

    out = T.item_info("X", "参数中文")

    assert out["zh"] == "原名"
    assert out["category"] == ""
    assert out["goal"] == ""


def test_item_info_falls_back_to_zh_of(monkeypatch):
    payload = {"name": "Y", "zh": "", "category": ""}
    seen = []

    def fake_info(
        name_en="",
        name_zh="",
        item_id=None,
        show_loot=True,
        exact=False,
        loot_online=True,
    ):
        return dict(payload)

    def fake_zh(en):
        seen.append(en)
        return "反查中文"

    monkeypatch.setattr(acquire, "info", fake_info)
    monkeypatch.setattr(i18n, "gear_zh_of_item", lambda _en: "")
    monkeypatch.setattr(T, "_zh_of", fake_zh)
    monkeypatch.setattr(T, "_goal_for", lambda *args: None)

    out = T.item_info("Y", "")

    assert seen == ["Y"]
    assert out["zh"] == "反查中文"


def test_item_loot_success(monkeypatch):
    calls = []

    def fake_info(name_en="", name_zh=""):
        calls.append((name_en, name_zh))
        return {"groups": [{"p": 0.5, "box": "箱子", "regions": ["地点"]}]}

    monkeypatch.setattr(loot, "info", fake_info)

    assert T.item_loot("A", "甲") == {
        "loot": {"groups": [{"p": 0.5, "box": "箱子", "regions": ["地点"]}]}
    }
    assert calls == [("A", "甲")]


def test_item_loot_error(monkeypatch):
    def boom(name_en="", name_zh=""):
        raise OSError("断网")

    monkeypatch.setattr(loot, "info", boom)

    assert T.item_loot("A", "甲") == {"loot": {"error": "掉落数据出错：断网"}}


def test_market_lookup_shape_and_limit(monkeypatch):
    items = [
        Item("uex:4741", "Carinite"),
        Item("scm:43475", "Carinite"),
        Item("local:abc", "Local"),
        Item("Plain", "Plain"),
    ] + [Item(f"uex:{i}", f"Item{i}") for i in range(1, 13)]
    lookup_calls = []
    label_calls = []

    def lookup(q):
        lookup_calls.append(q)
        return items, None

    def label(item_id):
        label_calls.append(item_id)
        return f"L:{item_id}"

    monkeypatch.setattr(
        T,
        "trade",
        lambda: SimpleNamespace(lookup=lookup, label=label),
    )

    out = T.market_lookup("Carinite")

    assert lookup_calls == ["Carinite"]
    assert out["err"] == ""
    assert len(out["items"]) == 15
    assert out["items"][0] == {
        "id": "uex:4741",
        "label": "L:uex:4741",
        "src": "UEX",
    }
    assert out["items"][1]["src"] == "SCM"
    assert out["items"][2]["src"] == "LOCAL"
    assert out["items"][3]["src"] == "UEX"
    assert out["items"][-1]["id"] == "uex:11"
    assert label_calls == [i.id for i in items[:15]]


def test_market_lookup_error(monkeypatch):
    monkeypatch.setattr(
        T,
        "trade",
        lambda: SimpleNamespace(
            lookup=lambda _q: ([], "UEX 搜索暂不可用"),
            label=lambda item_id: item_id,
        ),
    )

    assert T.market_lookup("x") == {
        "err": "UEX 搜索暂不可用",
        "items": [],
    }


def test_market_rows_table_and_missing(monkeypatch):
    item, results = _market_fixture()
    price_calls = []
    monkeypatch.setattr(T, "trade", lambda: _market_trade(item, results, price_calls))

    out, raw = T._market_rows(item.id, "q6", "buy")

    assert raw is results
    assert price_calls == [(item, "q6", "buy")]
    assert out == {
        "label": "科力晶（Carinite）",
        "rows": _market_rows(),
    }

    out2, raw2 = T._market_rows("missing", "q6", "sell")

    assert out2 == {"error": "未找到此物品"}
    assert raw2 is None
    assert price_calls == [(item, "q6", "buy")]


def test_market_prices_hud_matching(monkeypatch):
    item, results = _market_fixture()
    hud_calls = []
    monkeypatch.setattr(T, "trade", lambda: _market_trade(item, results))
    monkeypatch.setattr(T, "_item_hud", hud_calls.append)
    monkeypatch.setattr(
        T,
        "_get_last_hover",
        lambda: {
            "id": item.id,
            "lines": ["Carinite｜品质 650｜2 个"],
        },
    )

    out = T.market_prices(item.id, "q6", "sell")

    assert out == {
        "label": "科力晶（Carinite）",
        "rows": _market_rows(),
    }
    assert hud_calls == [f"Carinite｜品质 650｜2 个\n{MARKET}"]


def test_market_prices_hud_label_when_not_last_hover(monkeypatch):
    item, results = _market_fixture()
    hud_calls = []
    monkeypatch.setattr(T, "trade", lambda: _market_trade(item, results))
    monkeypatch.setattr(T, "_item_hud", hud_calls.append)
    monkeypatch.setattr(T, "_get_last_hover", lambda: {"id": "other", "lines": ["旧"]})

    out = T.market_prices(item.id, "q6", "sell")

    assert out == {
        "label": "科力晶（Carinite）",
        "rows": _market_rows(),
    }
    assert hud_calls == [f"科力晶（Carinite）\n{MARKET}"]


def test_market_prices_no_market_does_not_write_hud(monkeypatch):
    item = Item("uex:4741", "Carinite")
    results = (ProviderResult("uex", "empty"),)
    hud_calls = []
    monkeypatch.setattr(T, "trade", lambda: _market_trade(item, results))
    monkeypatch.setattr(T, "_item_hud", hud_calls.append)
    monkeypatch.setattr(T, "_get_last_hover", lambda: {"id": "other", "lines": ["旧"]})

    out = T.market_prices(item.id, "q0", "sell")

    assert out == {
        "label": "科力晶（Carinite）",
        "rows": [{"src": "UEX", "state": "暂无报价"}],
    }
    assert hud_calls == []


def test_market_prices_missing_item_does_not_write_hud(monkeypatch):
    item, results = _market_fixture()
    hud_calls = []
    monkeypatch.setattr(T, "trade", lambda: _market_trade(item, results))
    monkeypatch.setattr(T, "_item_hud", hud_calls.append)

    assert T.market_prices("missing", "q0", "sell") == {"error": "未找到此物品"}
    assert hud_calls == []
