"""IQ-B6：玩家市场会话和 F8 快照（不读本机数据、不联网）。"""

from types import SimpleNamespace

from astral_toolkit.tasks import catalog as C
from astral_toolkit.tasks import hover as Hv
from astral_toolkit.tasks import trade as T
from astral_toolkit.trade import market_text, matching
from tests.bootstrap_helpers import nav_deps


def test_open_market_reuses_one_trade_for_session(monkeypatch):
    """open_market 只取一次 Trade；匹配、别名、显示名都用这一个会话。"""
    alias_calls = []
    label_calls = []

    class FakeCatalog:
        def add_alias(self, item_id, zh):
            alias_calls.append((item_id, zh))

    class FakeTrade:
        catalog = FakeCatalog()

        def label(self, item_id):
            label_calls.append(item_id)
            return f"名字:{item_id}"

    fake_trade = FakeTrade()
    trade_calls = []

    def fake_trade_factory():
        trade_calls.append(True)
        return fake_trade

    monkeypatch.setattr(T, "trade", fake_trade_factory)
    match_calls = []

    def fake_match_tooltip(trade, zh, en):
        match_calls.append((trade, zh, en))
        return "匹配结果"

    monkeypatch.setattr(matching, "match_tooltip", fake_match_tooltip)

    session = C.open_market()
    assert session.match("中", "en") == "匹配结果"
    ((market, zh, en),) = match_calls  # FS-B2：经 Market 窄门，里面还是同一个 Trade
    assert (zh, en) == ("中", "en") and market._t is fake_trade

    session.remember_alias("id1", "中")
    assert alias_calls == [("id1", "中")]

    assert session.label("id1") == "名字:id1"
    assert label_calls == ["id1"]
    assert len(trade_calls) == 1


def test_open_market_propagates_trade_error(monkeypatch):
    """Trade 取不出来时 open_market 照旧抛出去。"""

    class Boom(Exception):
        pass

    def fail():
        raise Boom("坏")

    monkeypatch.setattr(T, "trade", fail)
    caught = False
    try:
        C.open_market()
    except Boom as exc:
        caught = True
        assert str(exc) == "坏"
    assert caught


def test_market_rows_and_hud_text_forward(monkeypatch):
    """报价表、悬浮窗市场行原样转给 tasks/trade 和 console。"""
    expected_prices = {"label": "行情", "rows": []}
    expected_results = ["价格结果"]
    row_calls = []

    def fake_rows(item_id, tier):
        row_calls.append((item_id, tier))
        return expected_prices, expected_results

    monkeypatch.setattr(T, "_market_rows", fake_rows)
    assert C.market_rows("uex:1", "q6") == (expected_prices, expected_results)
    assert row_calls == [("uex:1", "q6")]

    hud_calls = []

    def fake_hud(results):
        hud_calls.append(results)
        return "市场行情"

    monkeypatch.setattr(market_text, "hud_market", fake_hud)
    assert C.market_hud_text(expected_results) == "市场行情"
    assert len(hud_calls) == 1 and hud_calls[0] is expected_results


def test_last_hover_returns_independent_snapshot(monkeypatch):
    """last_hover 给副本：改返回值不影响 F8 的 _last_hover。"""
    state = {"at": "12:00:00", "seq": 3, "id": "uex:1", "lines": ["甲", "乙"]}
    monkeypatch.setattr(Hv, "_last_hover", state)
    snap = Hv.last_hover()
    assert snap == state
    assert snap is not state
    assert snap["lines"] is not state["lines"]
    snap["extra"] = 1
    snap["lines"].append("丙")
    assert Hv._last_hover == {
        "at": "12:00:00",
        "seq": 3,
        "id": "uex:1",
        "lines": ["甲", "乙"],
    }


def test_last_hover_without_lines_does_not_add_it(monkeypatch):
    """没有 lines 时快照也不凭空加。"""
    monkeypatch.setattr(Hv, "_last_hover", {"seq": None})
    assert Hv.last_hover() == {"seq": None}
    monkeypatch.setattr(Hv, "_last_hover", {})
    assert Hv.last_hover() == {}


def test_trade_get_last_hover_returns_snapshot(monkeypatch):
    """tasks/trade._get_last_hover 也读快照。"""
    state = {"seq": 4, "lines": ["行"]}
    monkeypatch.setattr(Hv, "_last_hover", state)
    snap = T._get_last_hover()
    assert snap == state
    assert snap is not state
    assert snap["lines"] is not state["lines"]


def test_hover_more_stops_when_market_cannot_open(monkeypatch):
    """市场会话开不出来（Trade 造不出来）：和以前 t = trade() 在 try 外一样，这次后台补价整个不做——
    异常抛出去、不发 hover_more、不查掉落"""
    calls = []

    def boom():
        raise RuntimeError("玩家库打不开")

    def item_card(*a, **k):
        calls.append("item_card")
        return {}

    def hud_market(results):
        calls.append("hud_market")
        return ""

    links = Hv.HoverLinks(
        item_card=item_card,
        loot=lambda name, zh: calls.append("loot"),
        market=boom,
        market_rows=lambda item_id, tier: calls.append("market_rows"),
        hud_market=hud_market,
        wikelo_rewards=lambda name, zh: [],
        has_blueprint=lambda *names: False,
    )
    monkeypatch.setattr(Hv, "_last_hover", {"seq": 5, "lines": ["医疗笔"]})
    monkeypatch.setattr(
        Hv,
        "bus",
        SimpleNamespace(
            publish=lambda *a, **k: calls.append("publish"),
            runtime_log=lambda *a, **k: calls.append("log"),
        ),
    )
    caught = None
    try:
        Hv._hover_more(
            links, 5, "12:00:00", "医疗笔", "MedPen", {"name": "MedPen"}, 650, True
        )
    except RuntimeError as e:
        caught = str(e)
    assert caught == "玩家库打不开"
    assert calls == []


_DEPS = (
    nav_deps()
)  # 商店导航的导航后台对象：这里导航不真开始，只看是不是原样交到 _start_nav（F 段 B5）


def _nav_fakes(monkeypatch, search_hits):
    """nav_shop 用的星图换成假的；导航不真的开始，只记下导去哪"""
    from astral_toolkit.navigation import navigate as N

    data = {
        "bodies": {"Hurston": {}, "Yela": {}, "Pyro4": {}},
        "pois": [{"n": "Grim HEX", "b": "Yela", "t": "Orbital Station"}],
    }
    monkeypatch.setattr(N, "load", lambda: data)
    monkeypatch.setattr(N, "city_places", lambda: [])
    monkeypatch.setattr(N, "amenity_targets", lambda kind, d: [])
    monkeypatch.setattr(
        N, "search", lambda q, d=None, limit=15: (list(search_hits.get(q, [])), None)
    )
    started = []

    class Places(dict):
        def __missing__(self, key):
            return key

    def row(hit):
        return {"key": hit["n"], "label": hit["n"]}

    def start(deps, place):
        assert deps is _DEPS, deps
        started.append(place)

    monkeypatch.setattr(T, "_nav_objects", lambda: (row, Places(), start))
    return started


def test_nav_shop_does_not_guess_a_spot_on_a_planet(monkeypatch):
    """BF-2：UEX 只写了星球名 → 不导、说清楚（以前按名字搜，星球上随便一个点都搜得到，就导过去了）"""
    started = _nav_fakes(
        monkeypatch, {"Hurston": [{"n": "Hurston Dynamics Showroom", "b": "Hurston"}]}
    )
    assert T.nav_shop(_DEPS, shop="Shop - X", place="Stanton · Hurston") == {
        "error": "UEX 上这家店只写了在「Hurston」，没写是哪个站、城或前哨，导航不了"
    }
    assert T.nav_shop(_DEPS, shop="Shop - X", place="Pyro") == {
        "error": "UEX 上这家店只写了在「Pyro」，没写是哪个站、城或前哨，导航不了"
    }
    assert started == []


def test_nav_shop_search_fallback_takes_only_exact_names(monkeypatch):
    """BF-2：最后按名字搜只认一模一样的；「Checkmate Station」去掉 Station 后对上照样导"""
    checkmate = [{"n": "Checkmate", "b": "Pyro4"}]
    started = _nav_fakes(
        monkeypatch,
        {
            "Checkmate Station": checkmate,
            "Checkmate": checkmate,
            "Odd Place": [{"n": "Odd Place Annex", "b": "Pyro4"}],
        },
    )
    assert T.nav_shop(_DEPS, shop="Shop - A", place="Pyro · Checkmate Station") == {
        "key": "Checkmate",
        "label": "Checkmate",
    }
    assert T.nav_shop(_DEPS, shop="Shop - B", place="Pyro · Pyro IV · Odd Place") == {
        "error": "导航数据里没有这个地点"
    }
    assert started == ["Checkmate"]


def test_nav_shop_grimhex_full_name(monkeypatch):
    """BF-2：UEX 写 Green Imperial Housing Exchange，星图叫 Grim HEX"""
    started = _nav_fakes(monkeypatch, {})
    place = "Stanton · Crusader · Yela · Green Imperial Housing Exchange"
    assert T.nav_shop(_DEPS, shop="Shop - C", place=place) == {
        "key": "Grim HEX",
        "label": "Grim HEX",
    }
    assert started == ["Grim HEX"]
