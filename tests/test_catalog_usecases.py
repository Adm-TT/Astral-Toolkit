"""物品查询用例（IQ-B5）：只取数据，不排版；不读本机 gamedata。"""

from contextlib import contextmanager, nullcontext
from typing import Any

from astral_toolkit import gamedata
from astral_toolkit.catalog.results import ItemInfo, LootLookup
from astral_toolkit.core import i18n
from astral_toolkit.crafting import acquire, itemsearch, loot
from astral_toolkit.tasks import catalog as C
from astral_toolkit.tasks import goals as G


def _fake_gamedata(monkeypatch, log, *, ensure_error=None, enter_error=None):
    def fake_ensure():
        log.append("ensure")
        if ensure_error is not None:
            raise ensure_error

    @contextmanager
    def fake_snapshot():
        log.append("enter")
        if enter_error is not None:
            raise enter_error
        try:
            yield object()
        finally:
            log.append("exit")

    monkeypatch.setattr(gamedata, "ensure", fake_ensure)
    monkeypatch.setattr(gamedata, "snapshot", fake_snapshot)


def test_get_item_info_pins_snapshot_and_builds_iteminfo(monkeypatch):
    log = []
    _fake_gamedata(monkeypatch, log)
    payload = {"name": "X", "zh": ""}

    def fake_info(
        name_en="",
        name_zh="",
        item_id=None,
        show_loot=True,
        exact=False,
        loot_online=True,
    ):
        log.append("info")
        assert (
            name_en,
            name_zh,
            item_id,
            show_loot,
            exact,
            loot_online,
        ) == ("参数名", "参数中", 7, False, True, False)
        return payload

    def fake_zh(en):
        log.append("zh_of")
        return "反查"

    monkeypatch.setattr(acquire, "info", fake_info)
    monkeypatch.setattr(i18n, "gear_zh_of_item", lambda _en: "")
    monkeypatch.setattr(C, "_zh_of", fake_zh)

    token = object()
    goal_calls = []

    def fake_goal_for(*names):
        log.append("goal_for")
        goal_calls.append(names)
        return token

    text_calls = []

    def fake_goal_text(g):
        log.append("goal_text")
        text_calls.append(g)
        return "目标"

    monkeypatch.setattr(G, "_goal_for", fake_goal_for)
    monkeypatch.setattr(G, "_goal_text", fake_goal_text)

    out = C.get_item_info(name="参数名", zh="参数中", id=7, loot=False, exact=True)

    assert log == [
        "ensure",
        "enter",
        "info",
        "zh_of",
        "goal_for",
        "goal_text",
        "exit",
    ]
    assert out == ItemInfo(facts=payload, zh="反查", goal="目标")
    assert out.facts is payload
    assert goal_calls == [("X", "参数名", "参数中", "反查")]
    assert text_calls == [token]


def test_get_item_info_survives_ensure_error(monkeypatch):
    log = []
    _fake_gamedata(monkeypatch, log, ensure_error=gamedata.GamedataError("坏库"))
    payload = {"name": "X", "zh": "事实"}
    calls = []

    def fake_info(*args, **kwargs):
        log.append("info")
        calls.append((args, kwargs))
        return payload

    monkeypatch.setattr(acquire, "info", fake_info)
    monkeypatch.setattr(i18n, "gear_zh_of_item", lambda _en: "装备中文")
    monkeypatch.setattr(G, "_goal_for", lambda *args: None)

    def never_text(_g):
        raise AssertionError("不该写目标")

    monkeypatch.setattr(G, "_goal_text", never_text)

    out = C.get_item_info()

    assert len(calls) == 1
    assert log == ["ensure", "info"]
    assert "enter" not in log
    assert out.facts is payload
    assert out.zh == "装备中文"
    assert out.goal == ""


def test_get_item_info_survives_snapshot_enter_error(monkeypatch):
    log = []
    _fake_gamedata(monkeypatch, log, enter_error=gamedata.GamedataError("坏库"))
    payload = {"name": "X", "zh": "事实"}
    calls = []

    def fake_info(*args, **kwargs):
        log.append("info")
        calls.append(1)
        return payload

    monkeypatch.setattr(acquire, "info", fake_info)
    monkeypatch.setattr(i18n, "gear_zh_of_item", lambda _en: "装备中文")
    monkeypatch.setattr(G, "_goal_for", lambda *args: None)

    out = C.get_item_info()

    assert calls == [1]
    assert log == ["ensure", "enter", "info"]
    assert out.facts is payload
    assert out.zh == "装备中文"
    assert out.goal == ""


def test_get_item_info_propagates_body_error_once(monkeypatch):
    log = []
    _fake_gamedata(monkeypatch, log)
    calls = []

    def fake_info(*args, **kwargs):
        log.append("info")
        calls.append(1)
        raise RuntimeError("坏了")

    monkeypatch.setattr(acquire, "info", fake_info)

    caught = None
    try:
        C.get_item_info()
    except RuntimeError as e:
        caught = e

    assert isinstance(caught, RuntimeError)
    assert str(caught) == "坏了"
    assert calls == [1]
    assert log == ["ensure", "enter", "info", "exit"]


def test_get_item_info_passes_acquire_arguments(monkeypatch):
    monkeypatch.setattr(C, "_pinned", nullcontext)
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
        return {"name": "N", "zh": "中文"}

    monkeypatch.setattr(acquire, "info", fake_info)
    monkeypatch.setattr(i18n, "gear_zh_of_item", lambda _en: "")
    monkeypatch.setattr(G, "_goal_for", lambda *args: None)

    exact: Any = 1  # 故意传 1：get_item_info 要把它转成 True 再交给 acquire.info
    C.get_item_info("N", "中", id=9, loot=False, exact=exact)

    assert calls == [("N", "中", 9, False, True, False)]
    assert calls[0][4] is True  # 1 要转成真正的 True（1 == True，只比相等测不出）


def test_get_item_info_zh_fallbacks(monkeypatch):
    monkeypatch.setattr(C, "_pinned", nullcontext)
    facts = {
        "A": {"name": "A", "zh": "事实中文"},
        "B": {"name": "B", "zh": "事实中文"},
        "C": {"name": "C", "zh": ""},
    }

    def fake_info(
        name_en="",
        name_zh="",
        item_id=None,
        show_loot=True,
        exact=False,
        loot_online=True,
    ):
        return dict(facts[name_en])

    def fake_zh(en):
        zh_calls.append(en)
        return "反查"

    zh_calls = []

    monkeypatch.setattr(acquire, "info", fake_info)
    monkeypatch.setattr(
        i18n, "gear_zh_of_item", lambda en: "装备中文" if en == "A" else ""
    )
    monkeypatch.setattr(C, "_zh_of", fake_zh)
    monkeypatch.setattr(G, "_goal_for", lambda *args: None)

    out_a = C.get_item_info(name="A")
    out_b = C.get_item_info(name="B")
    out_c = C.get_item_info(name="C")

    assert [out_a.zh, out_b.zh, out_c.zh] == ["装备中文", "事实中文", "反查"]
    assert zh_calls == ["C"]


def test_get_item_info_goal_arguments_and_text(monkeypatch):
    monkeypatch.setattr(C, "_pinned", nullcontext)
    payload = {"name": "事实名", "zh": "事实中文"}

    monkeypatch.setattr(acquire, "info", lambda *args, **kwargs: payload)
    monkeypatch.setattr(i18n, "gear_zh_of_item", lambda _en: "装备中文")

    goal_calls = []
    text_calls = []

    def fake_text(g):
        text_calls.append((g,))
        return "目标"

    def none_goal(*names):
        goal_calls.append(names)
        return None

    monkeypatch.setattr(G, "_goal_for", none_goal)
    monkeypatch.setattr(G, "_goal_text", fake_text)

    out = C.get_item_info(name="参数名", zh="参数中")

    assert out.goal == ""
    assert text_calls == []
    assert goal_calls == [("事实名", "参数名", "参数中", "装备中文")]

    token = object()

    def token_goal(*names):
        goal_calls.append(names)
        return token

    monkeypatch.setattr(G, "_goal_for", token_goal)

    out2 = C.get_item_info(name="参数名", zh="参数中")

    assert out2.goal == "目标"
    assert text_calls == [(token,)]
    assert goal_calls[-1] == ("事实名", "参数名", "参数中", "装备中文")


def test_get_item_loot_does_not_pin(monkeypatch):
    """掉落不另钉快照：副本矿缺掉落索引时 loot.info 会下载、重建库，再开新快照读新版本；外面钉着就读不到"""
    log = []
    _fake_gamedata(monkeypatch, log)
    payload = {"groups": []}
    calls = []

    def fake_info(name_en="", name_zh=""):
        log.append("loot")
        calls.append((name_en, name_zh))
        return payload

    monkeypatch.setattr(loot, "info", fake_info)

    out = C.get_item_loot(name="A", zh="甲")

    assert out == LootLookup(loot=payload)
    assert out.loot is payload
    assert calls == [("A", "甲")]
    assert log == ["loot"]


def test_get_item_loot_returns_error(monkeypatch):
    boom = OSError("断网")

    def fake_info(*args, **kwargs):
        raise boom

    monkeypatch.setattr(loot, "info", fake_info)

    out = C.get_item_loot(name="A", zh="甲")

    assert out.loot is None
    assert out.error is boom


def test_search_items_returns_find_result_without_pinning(monkeypatch):
    seen = []
    sentinel = object()

    def fake_find(q, limit=30):
        seen.append((q, limit))
        return sentinel

    def never(*args, **kwargs):
        raise AssertionError("搜索不应该钉快照")

    monkeypatch.setattr(itemsearch, "find", fake_find)
    monkeypatch.setattr(gamedata, "ensure", never)
    monkeypatch.setattr(gamedata, "snapshot", never)

    assert C.search_items("abc") is sentinel
    assert seen == [("abc", 30)]
