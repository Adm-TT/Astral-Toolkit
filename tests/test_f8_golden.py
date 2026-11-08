"""F8 悬停识别黄金测试：锁住 tasks/hover.py 当前输出。

IQ-B6 起市场、报价、掉落经 bootstrap 接的 HoverLinks → tasks/catalog；
测试照生产接法接，替身换在 Trade / console / crafting 那一层。
"""

import copy
import itertools
from types import SimpleNamespace
from typing import Any

from astral_toolkit import bootstrap
from astral_toolkit.core import run_records
from astral_toolkit.tasks.catalog_queries import loot as loot_mod
from astral_toolkit.crafting import reverse as reverse_mod
from astral_toolkit.crafting import wikelo as wikelo_mod
from astral_toolkit.crafting import wikelo_rules
from astral_toolkit.tasks import crafting as crafting_tasks
from astral_toolkit.tasks import hover as Hv
from astral_toolkit.tasks import trade as T
from astral_toolkit.system import train_data
from astral_toolkit.tasks.system import about
from astral_toolkit.trade import inspector as trade_inspector
from astral_toolkit.trade import market_text as trade_market_text
from astral_toolkit.trade import matching as trade_matching
from astral_toolkit.trade.models import Item


class _Image:
    width = 100
    height = 80


def _hover_log(*args, **kwargs):
    return None


def from_tooltip(*args, **kwargs):
    return None


def update_preview(*args, **kwargs):
    return None


def _basic_info(**kwargs):
    data = {
        "name": "MedPen",
        "zh": "医疗笔",
        "id": "uex:1",
        "buy": [],
        "variants": [],
        "ships": [],
        "how": "",
        "wikelo": [],
        "craft": None,
    }
    data.update(kwargs)
    return data


def _basic_res(**kwargs):
    data = {
        "zh": "医疗笔",
        "en": "MedPen",
        "quality": 650,
        "qty": 2,
        "unit": "个",
        "sure": True,
        "raw": ("医疗笔", "MedPen"),
        "canon": None,
        "craft": None,
        "tokens": ["tok"],
        "where": "body",
    }
    data.update(kwargs)
    return data


class _Catalog:
    def __init__(self, aliases):
        self.aliases = aliases

    def add_alias(self, item_id, zh):
        self.aliases.append((item_id, zh))


class _FakeTrade:
    def __init__(self, labels, aliases):
        self.labels = labels
        self.catalog = _Catalog(aliases)

    def label(self, item_id):
        return self.labels.get(item_id, item_id)


def _thread_namespace(calls):
    class _Thread:
        def __init__(
            self,
            target=None,
            args=(),
            kwargs=None,
            daemon=None,
            name=None,
        ):
            self.target: Any = target
            self.args = args
            self.kwargs = kwargs or {}

        def start(self):
            if self.target is Hv._hover_more:
                self.target(*self.args, **self.kwargs)
            else:
                calls.append(["thread", self.target.__name__])

    return SimpleNamespace(Thread=_Thread)


def _install(
    monkeypatch,
    res,
    *,
    info=None,
    item_info_impl=None,
    match_tooltip=None,
    market_rows=None,
    hud_market=None,
    data_ready=True,
    goal_for=None,
    goal_text=None,
    wikelo_load=None,
    wikelo_same=None,
    blueprints=None,
    craft_text=None,
    loot_impl=None,
    labels=None,
):
    calls = []
    aliases = []
    info_calls = []
    match_calls = []
    market_calls = []
    hud_market_calls = []
    loot_calls = []
    if info is None:
        info = _basic_info()
    labels = labels or {}
    fake_trade = _FakeTrade(labels, aliases)

    def fake_publish(topic, payload):
        calls.append(["publish", topic, copy.deepcopy(payload)])

    def fake_log(text, tag=None, level=None):
        calls.append(["log", level, text])

    def fake_item_hud(text, second=None):
        calls.append(["hud", text, second])

    def fake_item_info(_links, name="", zh="", id=None, loot=True, exact=False):
        info_calls.append([name, zh, id, loot, exact])
        if item_info_impl is None:
            return copy.deepcopy(info)
        return item_info_impl(name, zh, id, loot, exact)

    def default_match(t, zh, en, online=True):
        return None, []

    def fake_match(t, zh, en, online=True):
        match_calls.append([zh, en])
        return (match_tooltip or default_match)(t, zh, en, online)

    def default_market_rows(item_id, tier):
        return {"label": labels.get(item_id, item_id), "rows": []}, ["价格结果"]

    def fake_market_rows(item_id, tier):
        market_calls.append([item_id, tier])
        return (market_rows or default_market_rows)(item_id, tier)

    def default_hud_market(results):
        return "市场行情"

    def fake_hud_market(results):
        hud_market_calls.append([results])
        return (hud_market or default_hud_market)(results)

    def default_loot(name_en="", name_zh="", online=True):
        return {"drop": "固定掉"}

    def fake_loot(name_en="", name_zh="", online=True):
        loot_calls.append([name_en, name_zh])
        return (loot_impl or default_loot)(name_en, name_zh, online)

    def default_goal_for(*names):
        return None

    def default_goal_text(g):
        return ""

    monkeypatch.setattr(
        Hv,
        "time",
        SimpleNamespace(
            time=lambda: 1000.0,
            strftime=lambda fmt: "12:00:00",
        ),
    )
    monkeypatch.setattr(Hv, "_seq", itertools.count(1))
    monkeypatch.setattr(Hv, "_last_hover", {})
    monkeypatch.setattr(Hv, "WIN", False)
    monkeypatch.setattr(
        Hv,
        "inspect_item",
        lambda img, cur: copy.deepcopy(res) if res is not None else None,
    )
    monkeypatch.setattr(Hv, "item_info", fake_item_info)
    monkeypatch.setattr(T, "trade", lambda: fake_trade)
    monkeypatch.setattr(T, "_market_rows", fake_market_rows)
    # 照生产接法：市场会话、报价、掉落走 tasks/catalog
    links = bootstrap._hover_links()
    monkeypatch.setattr(Hv, "_goal_for", goal_for or default_goal_for)
    monkeypatch.setattr(Hv, "_goal_text", goal_text or default_goal_text)
    monkeypatch.setattr(Hv, "_item_hud", fake_item_hud)
    monkeypatch.setattr(
        Hv,
        "bus",
        SimpleNamespace(
            publish=fake_publish,
            runtime_log=fake_log,
            update_preview=update_preview,
        ),
    )
    monkeypatch.setattr(Hv, "threading", _thread_namespace(calls))
    monkeypatch.setattr(about, "data_names_ready", lambda: data_ready)
    monkeypatch.setattr(run_records, "record", lambda *args, **kwargs: None)
    monkeypatch.setattr(trade_inspector, "_hover_log", _hover_log)
    monkeypatch.setattr(trade_matching, "match_tooltip", fake_match)
    monkeypatch.setattr(trade_market_text, "hud_market", fake_hud_market)
    monkeypatch.setattr(train_data, "from_tooltip", from_tooltip)
    monkeypatch.setattr(wikelo_mod, "load", wikelo_load or (lambda: []))
    monkeypatch.setattr(wikelo_rules, "_same", wikelo_same or (lambda a, b: a == b))
    monkeypatch.setattr(crafting_tasks, "blueprints", blueprints or (lambda: []))
    monkeypatch.setattr(reverse_mod, "craft_text", craft_text or (lambda slots: ""))
    monkeypatch.setattr(loot_mod, "info", fake_loot)

    return SimpleNamespace(
        calls=calls,
        aliases=aliases,
        info_calls=info_calls,
        match_calls=match_calls,
        market_calls=market_calls,
        hud_market_calls=hud_market_calls,
        loot_calls=loot_calls,
        trade=fake_trade,
        links=links,
    )


def test_hover_miss(monkeypatch):
    """认字结果 None：发布 working → miss，悬浮窗两段提示，记一条日志线程。"""
    env = _install(monkeypatch, None)

    assert Hv.hover_once(env.links, _Image()) == {"miss": True}
    assert env.calls == [
        ["thread", "update_preview"],
        ["publish", "hover", {"state": "working"}],
        ["hud", "识别中…", 30],
        [
            "log",
            "WARN",
            "F8 未找到物品说明框 (总耗时 0ms: 截图 0ms, 识别 0ms)。"
            "请在说明框弹出后再次按下 F8",
        ],
        [
            "publish",
            "hover",
            {
                "state": "miss",
                "msg": "未找到物品说明框。鼠标停在物品上，等说明框出现后再按",
            },
        ],
        [
            "hud",
            "未识别到物品\n鼠标停在物品上，等说明框出现后再按",
            10,
        ],
        ["thread", "_hover_log"],
    ]
    assert env.aliases == []
    assert Hv._last_hover == {"seq": None}


def test_hover_normal_with_market(monkeypatch):
    """正常识别：购买、获取、维科洛、可制造、市场价与掉落全部按顺序出现。"""
    info = _basic_info(
        buy=[{"dist": "", "price": 1234, "shop": "商店甲"}],
        ships=["船甲"],
        how="任务奖励",
        wikelo=[{"reward": "奖励甲"}],
    )
    res = _basic_res()

    def match_tooltip(t, zh, en, online=True):
        item = Item("uex:1", "MedPen")
        return item, [item]

    def market_rows(item_id, tier):
        return {"label": "医疗笔（MedPen）", "rows": []}, ["价格结果"]

    env = _install(
        monkeypatch,
        res,
        info=info,
        match_tooltip=match_tooltip,
        market_rows=market_rows,
        goal_for=lambda *names: "goal-1",
        goal_text=lambda g: "目标线",
        wikelo_load=lambda: [{"t": "合约甲", "rz": "MedPen", "rewards": []}],
        blueprints=lambda: [{"n": "MedPen", "z": "医疗笔"}],
        labels={"uex:1": "医疗笔（MedPen）"},
    )

    lines = [
        "医疗笔｜品质 650｜2 个",
        "目标线",
        "购买：1,234｜商店甲",
        "获取：任务奖励",
        "可通过维科洛兑换获得：合约甲",
        "可用于维科洛兑换：奖励甲",
        "可制造：有蓝图（材料见物品查询）",
    ]
    ok_payload = {
        "state": "ok",
        "zh": "医疗笔",
        "en": "MedPen",
        "info": info,
        "market": None,
        "candidates": [],
        "pending": True,
        "at": "12:00:00",
        "seq": 1,
        "quality": 650,
        "qty": 2,
        "unit": "个",
        "tier": "q3",
        "craft": None,
        "sure": True,
        "library_ready": True,
    }
    first_more = {
        "at": "12:00:00",
        "seq": 1,
        "market": {"id": "uex:1", "label": "医疗笔（MedPen）"},
        "candidates": [],
    }
    final_more = {
        "at": "12:00:00",
        "seq": 1,
        "market": {"id": "uex:1", "label": "医疗笔（MedPen）"},
        "candidates": [],
        "prices": {
            "label": "医疗笔（MedPen）",
            "rows": [],
            "quality": "q3",
            "op": "sell",
        },
        "loot": {"drop": "固定掉"},
    }

    assert Hv.hover_once(env.links, _Image()) == {"ok": True, "ms": 0}
    assert env.calls == [
        ["thread", "update_preview"],
        ["publish", "hover", {"state": "working"}],
        ["hud", "识别中…", 30],
        ["hud", "\n".join(lines), None],
        [
            "log",
            "INFO",
            "F8 成功识别: 医疗笔 | 品质 650 | 2 个 "
            "(总耗时 0ms: 截图 0ms, 识别[body] 0ms, 解析 0ms)",
        ],
        ["publish", "hover", ok_payload],
        ["log", "INFO", "F8 匹配市场: MedPen，正在获取价格..."],
        ["publish", "hover_more", first_more],
        ["hud", "\n".join(lines + ["市场行情"]), None],
        ["publish", "hover_more", final_more],
        ["log", "INFO", "F8 价格与数据同步完成: 医疗笔"],
        ["thread", "_hover_log"],
    ]
    assert env.aliases == [("uex:1", "医疗笔")]
    assert env.info_calls == [["MedPen", "医疗笔", None, False, False]]
    assert env.market_calls == [["uex:1", "q3"]]
    assert Hv._last_hover == {
        "at": "12:00:00",
        "seq": 1,
        "id": "uex:1",
        "lines": lines,
    }


def test_hover_unsure_missing_library(monkeypatch):
    """sure=False 且库没下全：提示先更新数据，仍不对市场别名。"""
    res = _basic_res(
        zh="乱认的名",
        en="Bogus",
        quality=None,
        qty=None,
        sure=False,
        raw=("乱认的名", "Bogus"),
        canon=None,
        tokens=[],
    )
    info = _basic_info(name="Bogus", zh="乱认的名", id="uex:9")
    head = "乱认的名｜本地数据不完整，请先更新数据"

    def match_tooltip(t, zh, en, online=True):
        item = Item("uex:9", "Bogus")
        return item, [item]

    env = _install(
        monkeypatch,
        res,
        info=info,
        match_tooltip=match_tooltip,
        market_rows=lambda item_id, tier: ({}, None),
        data_ready=False,
        labels={"uex:9": "乱认（Bogus）"},
    )

    ok_payload = {
        "state": "ok",
        "zh": "乱认的名",
        "en": "Bogus",
        "info": info,
        "market": None,
        "candidates": [],
        "pending": True,
        "at": "12:00:00",
        "seq": 1,
        "quality": None,
        "qty": None,
        "unit": "个",
        "tier": "q0",
        "craft": None,
        "sure": False,
        "library_ready": False,
    }
    first_more = {
        "at": "12:00:00",
        "seq": 1,
        "market": {"id": "uex:9", "label": "乱认（Bogus）"},
        "candidates": [],
    }
    final_more = {
        "at": "12:00:00",
        "seq": 1,
        "market": {"id": "uex:9", "label": "乱认（Bogus）"},
        "candidates": [],
        "prices": {"quality": "q0", "op": "sell"},
        "loot": {"drop": "固定掉"},
    }

    assert Hv.hover_once(env.links, _Image()) == {"ok": True, "ms": 0}
    assert env.calls == [
        ["thread", "update_preview"],
        ["publish", "hover", {"state": "working"}],
        ["hud", "识别中…", 30],
        ["hud", head, None],
        [
            "log",
            "INFO",
            "F8 成功识别: 乱认的名 (总耗时 0ms: 截图 0ms, 识别[body] 0ms, 解析 0ms)",
        ],
        ["publish", "hover", ok_payload],
        ["log", "INFO", "F8 匹配市场: Bogus，正在获取价格..."],
        ["publish", "hover_more", first_more],
        ["publish", "hover_more", final_more],
        ["log", "INFO", "F8 价格与数据同步完成: 乱认的名"],
        ["thread", "_hover_log"],
    ]
    assert env.aliases == []
    assert env.market_calls == [["uex:9", "q0"]]
    assert Hv._last_hover == {
        "at": "12:00:00",
        "seq": 1,
        "id": "uex:9",
        "lines": [head],
    }


def test_hover_unsure_library_ready(monkeypatch):
    """sure=False 且库已下全：提示识别结果不确定，仍不对市场别名。"""
    res = _basic_res(
        zh="乱认的名",
        en="Bogus",
        quality=None,
        qty=None,
        sure=False,
        raw=("乱认的名", "Bogus"),
        canon=None,
        tokens=[],
    )
    info = _basic_info(name="Bogus", zh="乱认的名", id="uex:9")
    head = "乱认的名｜识别结果不确定"

    def match_tooltip(t, zh, en, online=True):
        item = Item("uex:9", "Bogus")
        return item, [item]

    env = _install(
        monkeypatch,
        res,
        info=info,
        match_tooltip=match_tooltip,
        market_rows=lambda item_id, tier: ({}, None),
        data_ready=True,
        labels={"uex:9": "乱认（Bogus）"},
    )

    ok_payload = {
        "state": "ok",
        "zh": "乱认的名",
        "en": "Bogus",
        "info": info,
        "market": None,
        "candidates": [],
        "pending": True,
        "at": "12:00:00",
        "seq": 1,
        "quality": None,
        "qty": None,
        "unit": "个",
        "tier": "q0",
        "craft": None,
        "sure": False,
        "library_ready": True,
    }
    first_more = {
        "at": "12:00:00",
        "seq": 1,
        "market": {"id": "uex:9", "label": "乱认（Bogus）"},
        "candidates": [],
    }
    final_more = {
        "at": "12:00:00",
        "seq": 1,
        "market": {"id": "uex:9", "label": "乱认（Bogus）"},
        "candidates": [],
        "prices": {"quality": "q0", "op": "sell"},
        "loot": {"drop": "固定掉"},
    }

    assert Hv.hover_once(env.links, _Image()) == {"ok": True, "ms": 0}
    assert env.calls == [
        ["thread", "update_preview"],
        ["publish", "hover", {"state": "working"}],
        ["hud", "识别中…", 30],
        ["hud", head, None],
        [
            "log",
            "INFO",
            "F8 成功识别: 乱认的名 (总耗时 0ms: 截图 0ms, 识别[body] 0ms, 解析 0ms)",
        ],
        ["publish", "hover", ok_payload],
        ["log", "INFO", "F8 匹配市场: Bogus，正在获取价格..."],
        ["publish", "hover_more", first_more],
        ["publish", "hover_more", final_more],
        ["log", "INFO", "F8 价格与数据同步完成: 乱认的名"],
        ["thread", "_hover_log"],
    ]
    assert env.aliases == []
    assert Hv._last_hover == {
        "at": "12:00:00",
        "seq": 1,
        "id": "uex:9",
        "lines": [head],
    }


def test_hover_canon_records_training_thread(monkeypatch):
    """canon 为真：多起一条 train_data.from_tooltip 线程（只记线程名）。"""
    res = _basic_res(canon=("医疗笔", "MedPen"))
    info = _basic_info()
    env = _install(monkeypatch, res, info=info)

    head = "医疗笔｜品质 650｜2 个"
    ok_payload = {
        "state": "ok",
        "zh": "医疗笔",
        "en": "MedPen",
        "info": info,
        "market": None,
        "candidates": [],
        "pending": True,
        "at": "12:00:00",
        "seq": 1,
        "quality": 650,
        "qty": 2,
        "unit": "个",
        "tier": "q3",
        "craft": None,
        "sure": True,
        "library_ready": True,
    }
    final_more = {
        "at": "12:00:00",
        "seq": 1,
        "market": None,
        "candidates": [],
        "loot": {"drop": "固定掉"},
    }

    assert Hv.hover_once(env.links, _Image()) == {"ok": True, "ms": 0}
    assert env.calls == [
        ["thread", "update_preview"],
        ["publish", "hover", {"state": "working"}],
        ["hud", "识别中…", 30],
        ["hud", head, None],
        [
            "log",
            "INFO",
            "F8 成功识别: 医疗笔 | 品质 650 | 2 个 "
            "(总耗时 0ms: 截图 0ms, 识别[body] 0ms, 解析 0ms)",
        ],
        ["publish", "hover", ok_payload],
        ["publish", "hover_more", final_more],
        ["log", "INFO", "F8 价格与数据同步完成: 医疗笔"],
        ["thread", "_hover_log"],
        ["thread", "from_tooltip"],
    ]
    assert env.aliases == []
    assert Hv._last_hover == {
        "at": "12:00:00",
        "seq": 1,
        "id": None,
        "lines": [head],
    }


def test_hover_craft_line(monkeypatch):
    """craft 非空：第二行显示材料品质。"""
    craft = [{"slot": "框架", "q": 858}]
    res = _basic_res(craft=craft)
    info = _basic_info()
    env = _install(
        monkeypatch,
        res,
        info=info,
        craft_text=lambda slots: "CRAFT" if slots == craft else "错了",
    )

    head = "医疗笔｜品质 650｜2 个"
    lines = [head, "材料品质：CRAFT"]
    ok_payload = {
        "state": "ok",
        "zh": "医疗笔",
        "en": "MedPen",
        "info": info,
        "market": None,
        "candidates": [],
        "pending": True,
        "at": "12:00:00",
        "seq": 1,
        "quality": 650,
        "qty": 2,
        "unit": "个",
        "tier": "q3",
        "craft": craft,
        "sure": True,
        "library_ready": True,
    }
    final_more = {
        "at": "12:00:00",
        "seq": 1,
        "market": None,
        "candidates": [],
        "loot": {"drop": "固定掉"},
    }

    assert Hv.hover_once(env.links, _Image()) == {"ok": True, "ms": 0}
    assert env.calls == [
        ["thread", "update_preview"],
        ["publish", "hover", {"state": "working"}],
        ["hud", "识别中…", 30],
        ["hud", "\n".join(lines), None],
        [
            "log",
            "INFO",
            "F8 成功识别: 医疗笔 | 品质 650 | 2 个 "
            "(总耗时 0ms: 截图 0ms, 识别[body] 0ms, 解析 0ms)",
        ],
        ["publish", "hover", ok_payload],
        ["publish", "hover_more", final_more],
        ["log", "INFO", "F8 价格与数据同步完成: 医疗笔"],
        ["thread", "_hover_log"],
    ]
    assert env.aliases == []
    assert Hv._last_hover == {
        "at": "12:00:00",
        "seq": 1,
        "id": None,
        "lines": lines,
    }


def test_hover_market_candidates_only_final_publish(monkeypatch):
    """市场对不上：三条候选带 label，只发布最后一次 hover_more，不写别名。"""
    res = _basic_res()
    info = _basic_info()
    candidates = [
        Item("uex:2", "Alpha"),
        Item("scm:3", "Beta"),
        Item("uex:4", "Gamma"),
    ]
    head = "医疗笔｜品质 650｜2 个"

    def match_tooltip(t, zh, en, online=True):
        return None, candidates

    env = _install(
        monkeypatch,
        res,
        info=info,
        match_tooltip=match_tooltip,
        labels={
            "uex:2": "候选甲（Alpha）",
            "scm:3": "候选乙（Beta）",
            "uex:4": "候选丙（Gamma）",
        },
    )

    ok_payload = {
        "state": "ok",
        "zh": "医疗笔",
        "en": "MedPen",
        "info": info,
        "market": None,
        "candidates": [],
        "pending": True,
        "at": "12:00:00",
        "seq": 1,
        "quality": 650,
        "qty": 2,
        "unit": "个",
        "tier": "q3",
        "craft": None,
        "sure": True,
        "library_ready": True,
    }
    final_more = {
        "at": "12:00:00",
        "seq": 1,
        "market": None,
        "candidates": [
            {"id": "uex:2", "label": "候选甲（Alpha）"},
            {"id": "scm:3", "label": "候选乙（Beta）"},
            {"id": "uex:4", "label": "候选丙（Gamma）"},
        ],
        "loot": {"drop": "固定掉"},
    }

    assert Hv.hover_once(env.links, _Image()) == {"ok": True, "ms": 0}
    assert env.calls == [
        ["thread", "update_preview"],
        ["publish", "hover", {"state": "working"}],
        ["hud", "识别中…", 30],
        ["hud", head, None],
        [
            "log",
            "INFO",
            "F8 成功识别: 医疗笔 | 品质 650 | 2 个 "
            "(总耗时 0ms: 截图 0ms, 识别[body] 0ms, 解析 0ms)",
        ],
        ["publish", "hover", ok_payload],
        ["publish", "hover_more", final_more],
        ["log", "INFO", "F8 价格与数据同步完成: 医疗笔"],
        ["thread", "_hover_log"],
    ]
    assert env.aliases == []
    assert env.market_calls == []
    assert Hv._last_hover == {
        "at": "12:00:00",
        "seq": 1,
        "id": None,
        "lines": [head],
    }


def test_hover_market_candidates_capped_at_eight(monkeypatch):
    """市场对不上时候选只给前 8 条，每条带 label"""
    items = [Item(f"uex:{i}", f"Name {i}") for i in range(10)]
    labels = {f"uex:{i}": f"标签{i}" for i in range(10)}
    env = _install(
        monkeypatch,
        _basic_res(),
        match_tooltip=lambda t, zh, en, online=True: (None, list(items)),
        labels=labels,
    )
    assert Hv.hover_once(env.links, _Image()) == {"ok": True, "ms": 0}
    more = [c for c in env.calls if c[0] == "publish" and c[1] == "hover_more"]
    assert len(more) == 1
    assert more[0][2]["market"] is None
    assert more[0][2]["candidates"] == [
        {"id": f"uex:{i}", "label": f"标签{i}"} for i in range(8)
    ]
    assert env.aliases == []


def test_hover_typo_name_corrected(monkeypatch):
    """英文错字：用市场英文名重查本机资料，换 info 并重写悬浮窗行。"""
    info_before = _basic_info(name="MedPenn", zh="医疗笔", id=None)
    info_after = _basic_info(
        name="MedPen",
        zh="医疗笔",
        id="uex:1",
        buy=[{"dist": "", "price": 1234, "shop": "商店甲"}],
    )
    res = _basic_res(en="MedPenn")

    def item_info_impl(name="", zh="", id=None, loot=True, exact=False):
        return copy.deepcopy(info_after if name == "MedPen" else info_before)

    def match_tooltip(t, zh, en, online=True):
        item = Item("uex:1", "MedPen")
        return item, [item]

    env = _install(
        monkeypatch,
        res,
        info=info_before,
        item_info_impl=item_info_impl,
        match_tooltip=match_tooltip,
        market_rows=lambda item_id, tier: ({}, None),
        labels={"uex:1": "医疗笔（MedPen）"},
    )

    head = "医疗笔｜品质 650｜2 个"
    lines_after = [head, "购买：1,234｜商店甲"]
    ok_payload = {
        "state": "ok",
        "zh": "医疗笔",
        "en": "MedPenn",
        "info": info_before,
        "market": None,
        "candidates": [],
        "pending": True,
        "at": "12:00:00",
        "seq": 1,
        "quality": 650,
        "qty": 2,
        "unit": "个",
        "tier": "q3",
        "craft": None,
        "sure": True,
        "library_ready": True,
    }
    first_more = {
        "at": "12:00:00",
        "seq": 1,
        "market": {"id": "uex:1", "label": "医疗笔（MedPen）"},
        "candidates": [],
        "info": info_after,
    }
    final_more = {
        "at": "12:00:00",
        "seq": 1,
        "market": {"id": "uex:1", "label": "医疗笔（MedPen）"},
        "candidates": [],
        "info": info_after,
        "prices": {"quality": "q3", "op": "sell"},
        "loot": {"drop": "固定掉"},
    }

    assert Hv.hover_once(env.links, _Image()) == {"ok": True, "ms": 0}
    assert env.calls == [
        ["thread", "update_preview"],
        ["publish", "hover", {"state": "working"}],
        ["hud", "识别中…", 30],
        ["hud", head, None],
        [
            "log",
            "INFO",
            "F8 成功识别: 医疗笔 | 品质 650 | 2 个 "
            "(总耗时 0ms: 截图 0ms, 识别[body] 0ms, 解析 0ms)",
        ],
        ["publish", "hover", ok_payload],
        ["hud", "\n".join(lines_after), None],
        ["log", "INFO", "F8 匹配市场: MedPen，正在获取价格..."],
        ["publish", "hover_more", first_more],
        ["publish", "hover_more", final_more],
        ["log", "INFO", "F8 价格与数据同步完成: 医疗笔"],
        ["thread", "_hover_log"],
    ]
    assert env.aliases == [("uex:1", "医疗笔")]
    assert env.info_calls == [
        ["MedPenn", "医疗笔", None, False, False],
        ["MedPen", "医疗笔", None, False, False],
    ]
    assert env.market_calls == [["uex:1", "q3"]]
    assert env.loot_calls == [["MedPen", "医疗笔"]]
    assert Hv._last_hover == {
        "at": "12:00:00",
        "seq": 1,
        "id": "uex:1",
        "lines": lines_after,
    }


def test_hover_price_and_loot_errors(monkeypatch):
    """查价、掉落都抛异常：发布里的 prices / loot 写成错误形状。"""
    res = _basic_res()
    info = _basic_info()

    def match_tooltip(t, zh, en, online=True):
        item = Item("uex:1", "MedPen")
        return item, [item]

    def market_rows(item_id, tier):
        raise RuntimeError("价格源坏了")

    def loot_impl(name_en="", name_zh="", online=True):
        raise RuntimeError("掉落源坏了")

    env = _install(
        monkeypatch,
        res,
        info=info,
        match_tooltip=match_tooltip,
        market_rows=market_rows,
        loot_impl=loot_impl,
        labels={"uex:1": "医疗笔（MedPen）"},
    )

    head = "医疗笔｜品质 650｜2 个"
    ok_payload = {
        "state": "ok",
        "zh": "医疗笔",
        "en": "MedPen",
        "info": info,
        "market": None,
        "candidates": [],
        "pending": True,
        "at": "12:00:00",
        "seq": 1,
        "quality": 650,
        "qty": 2,
        "unit": "个",
        "tier": "q3",
        "craft": None,
        "sure": True,
        "library_ready": True,
    }
    first_more = {
        "at": "12:00:00",
        "seq": 1,
        "market": {"id": "uex:1", "label": "医疗笔（MedPen）"},
        "candidates": [],
    }
    final_more = {
        "at": "12:00:00",
        "seq": 1,
        "market": {"id": "uex:1", "label": "医疗笔（MedPen）"},
        "candidates": [],
        "prices": {
            "error": "价格查询失败：价格源坏了",
            "quality": "q3",
            "op": "sell",
        },
        "loot": {"error": "掉落数据查询失败：掉落源坏了"},
    }

    assert Hv.hover_once(env.links, _Image()) == {"ok": True, "ms": 0}
    assert env.calls == [
        ["thread", "update_preview"],
        ["publish", "hover", {"state": "working"}],
        ["hud", "识别中…", 30],
        ["hud", head, None],
        [
            "log",
            "INFO",
            "F8 成功识别: 医疗笔 | 品质 650 | 2 个 "
            "(总耗时 0ms: 截图 0ms, 识别[body] 0ms, 解析 0ms)",
        ],
        ["publish", "hover", ok_payload],
        ["log", "INFO", "F8 匹配市场: MedPen，正在获取价格..."],
        ["publish", "hover_more", first_more],
        ["publish", "hover_more", final_more],
        ["log", "INFO", "F8 价格与数据同步完成: 医疗笔"],
        ["thread", "_hover_log"],
    ]
    assert env.aliases == [("uex:1", "医疗笔")]
    assert env.market_calls == [["uex:1", "q3"]]
    assert Hv._last_hover == {
        "at": "12:00:00",
        "seq": 1,
        "id": "uex:1",
        "lines": [head],
    }


def test_hover_more_late_seq_drops_everything(monkeypatch):
    """_hover_more 等待期间序号变了：不发布、不写别名、不查价、不查掉落。"""
    info = _basic_info()

    def match_tooltip(t, zh, en, online=True):
        Hv._last_hover["seq"] = 8
        item = Item("uex:1", "MedPen")
        return item, [item]

    env = _install(monkeypatch, None, info=info, match_tooltip=match_tooltip)
    Hv._last_hover.update(
        at="12:00:00",
        seq=7,
        id=None,
        lines=["行一"],
    )

    result = Hv._hover_more(
        env.links, 7, "12:00:00", "医疗笔", "MedPen", info, 650, True
    )

    assert result is None
    assert env.calls == []
    assert env.aliases == []
    assert env.market_calls == []
    assert env.loot_calls == []
    assert Hv._last_hover == {
        "at": "12:00:00",
        "seq": 8,
        "id": None,
        "lines": ["行一"],
    }


def test_hover_more_keeps_alias_off_lookalike_items(monkeypatch):
    """F8 配上的物品算同一件才记中文名（trade.matching.alias_ok）：前缀配上的变体（轻机枪配成它的电池）不记，以后盘点、
    库存页才不会被带偏；名字对上的照记（待做 61，老大 2026-11-08 定直接修）"""
    info = _basic_info()
    for item, want in (
        (Item("uex:2", "Demeco LMG Battery (100 cap)"), []),
        (Item("uex:1", "Demeco LMG"), [("uex:1", "德美科 轻机枪")]),
    ):

        def match_tooltip(t, zh, en, online=True, _i=item):
            return _i, [_i]

        env = _install(monkeypatch, None, info=info, match_tooltip=match_tooltip)
        Hv._last_hover.update(at="12:00:00", seq=7, id=None, lines=["行一"])
        Hv._hover_more(
            env.links, 7, "12:00:00", "德美科 轻机枪", "Demeco LMG", info, 650, True
        )
        assert env.aliases == want, item


def test_hover_lines_ship_and_counts(monkeypatch):
    """_hover_lines：买不到时写随船自带，多个兑换写「等 N 个」。"""
    info = _basic_info(
        name="医疗笔",
        zh="医疗笔",
        buy=[],
        ships=["船甲", "船乙", "船丙", "船丁"],
        how="拾取",
        wikelo=[{"reward": "奖励甲"}, {"reward": "奖励乙"}],
    )
    env = _install(
        monkeypatch,
        None,
        info=info,
        wikelo_load=lambda: [
            {"t": "合约甲", "rz": "医疗笔", "rewards": []},
            {"t": "合约乙", "rz": "医疗笔", "rewards": []},
        ],
    )

    assert Hv._hover_lines(env.links, info, "医疗笔", "医疗笔") == [
        "随船自带：船甲、船乙、船丙 等 4 条船",
        "获取：拾取",
        "可通过维科洛兑换获得：合约甲 等 2 个",
        "可用于维科洛兑换：奖励甲 等 2 个",
    ]


def test_qty_tier_and_short_buy():
    """纯函数：数量、品质档、最近买点三处格式化。"""
    assert Hv.qty_text(None, "SCU") == ""
    assert Hv.qty_text(0.495, "SCU") == "0.495 SCU"
    assert Hv.qty_text(495000, "uSCU") == "495,000 uSCU"
    assert Hv.qty_text(2, "个") == "2 个"

    assert Hv._tier(None) == "q0"
    assert Hv._tier(0) == "q0"
    assert Hv._tier(650) == "q3"
    assert Hv._tier(925) == "q6"
    assert Hv._tier("未知") == "q0"

    assert (
        Hv._short_buy({"buy": [{"dist": "地点", "price": 1234, "shop": "店"}]})
        == "地点｜1,234｜店"
    )
    assert (
        Hv._short_buy(
            {
                "buy": [],
                "variants": [
                    {"buy": [{"dist": "", "price": 999, "shop": "店乙"}]},
                ],
            }
        )
        == "999｜店乙"
    )
    assert Hv._short_buy({}) == ""
    assert Hv._short_buy({"buy": [], "variants": []}) == ""
