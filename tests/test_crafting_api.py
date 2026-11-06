"""CR-B4：制造 / 维科洛接口拆到 app/api + tasks 用例 + presenters 后，接口结果仍和 tasks/goals.py 旧壳逐字一样。"""

import re
from contextlib import contextmanager
from typing import Any

from astral_toolkit.app.api import crafting as api_crafting
from astral_toolkit.app.api import goals as api_goals
from astral_toolkit.app.api import router
from astral_toolkit.app.api import wikelo as api_wikelo
from astral_toolkit.tasks import crafting as UC
from astral_toolkit.tasks import goals as G
from astral_toolkit.tasks import wikelo as WU
from tests import test_crafting_golden as craft_golden
from tests import test_wikelo_golden as wikelo_golden

_EXPECTED_ROUTES = {
    "craft_effect": "astral_toolkit.app.api.crafting",
    "craft_search": "astral_toolkit.app.api.crafting",
    "craft_browse": "astral_toolkit.app.api.crafting",
    "craft_detail": "astral_toolkit.app.api.crafting",
    "craft_stats": "astral_toolkit.app.api.crafting",
    "craft_mix": "astral_toolkit.app.api.crafting",
    "wikelo_search": "astral_toolkit.app.api.wikelo",
    "wikelo_detail": "astral_toolkit.app.api.wikelo",
}


@contextmanager
def _clean_caches():
    G.clear_caches()
    try:
        yield
    finally:
        G.clear_caches()


def _assert_same(api_fn, legacy_fn, *args, **kwargs):
    G.clear_caches()
    got = api_fn(*args, **kwargs)
    G.clear_caches()
    expected = legacy_fn(*args, **kwargs)
    assert got == expected
    return got


def test_route_module_ownership():
    router.reset()
    routes = router.routes()
    for name, module in _EXPECTED_ROUTES.items():
        assert name in routes
        assert routes[name].__module__ == module
        assert name not in api_goals.ROUTES


def test_crafting_api_matches_legacy(monkeypatch):
    with _clean_caches():
        craft_golden._install(monkeypatch)
        key = UC.bp_key(craft_golden.WEAPON)

        _assert_same(api_crafting.craft_search, G.craft_search, q="Test")
        _assert_same(api_crafting.craft_browse, G.craft_browse)
        _assert_same(api_crafting.craft_browse, G.craft_browse, mat="MineralA", mq=600)
        _assert_same(api_crafting.craft_detail, G.craft_detail, key=key)
        _assert_same(api_crafting.craft_detail, G.craft_detail, key="没有这个蓝图")
        _assert_same(api_crafting.craft_detail, G.craft_detail, key="Test")
        _assert_same(
            api_crafting.craft_effect,
            G.craft_effect,
            key=key,
            qualities={0: 600},
        )
        _assert_same(api_crafting.craft_effect, G.craft_effect, key="没有这个蓝图")
        _assert_same(
            api_crafting.craft_stats,
            G.craft_stats,
            key=key,
            qualities={0: 600},
        )
        _assert_same(api_crafting.craft_stats, G.craft_stats, key="没有这个蓝图")
        _assert_same(
            api_crafting.craft_mix,
            G.craft_mix,
            need=2,
            target=600,
            margin=1,
            boxes=[[500, 1], [1000, 2]],
        )
        _assert_same(
            api_crafting.craft_mix,
            G.craft_mix,
            boxes=[["不是数字", "1"]],
        )


def test_wikelo_api_matches_legacy(monkeypatch):
    with _clean_caches():
        wikelo_golden._install(monkeypatch)

        _assert_same(api_wikelo.wikelo_search, G.wikelo_search, q="")
        _assert_same(api_wikelo.wikelo_search, G.wikelo_search, q="极地")
        _assert_same(
            api_wikelo.wikelo_detail,
            G.wikelo_detail,
            key=wikelo_golden._RECOMB["id"],
        )
        _assert_same(api_wikelo.wikelo_detail, G.wikelo_detail, key="没有这个")


def test_clear_caches_empties_usecase_caches(monkeypatch):
    with _clean_caches():
        craft_golden._install(monkeypatch)
        wikelo_golden._install(monkeypatch)

        UC.search_blueprints("Test")
        WU.search_exchanges("")
        assert UC._bp_cache
        assert WU._wk_cache

        G.clear_caches()
        assert UC._bp_cache == {}
        assert WU._wk_cache == {}


def test_usecase_keeps_blueprint_identity(monkeypatch):
    with _clean_caches():
        craft_golden._install(monkeypatch)
        key = UC.bp_key(craft_golden.WEAPON)

        hits = UC.search_blueprints("Test")
        assert any(h["bp"] is craft_golden.WEAPON for h in hits)

        G.clear_caches()
        page = UC.browse_blueprints(q="")
        assert any(row["bp"] is craft_golden.WEAPON for row in page["rows"])

        G.clear_caches()
        detail = UC.blueprint_detail(key)
        assert detail is not None
        assert detail["struct"]["bp"] is craft_golden.WEAPON


def test_detail_mine_spots_top_two_rounded(monkeypatch):
    """去哪挖：每种矿只列前两处、百分比取整（黄金测试的假地点只有两处整数，这里给三处带小数的）"""
    with _clean_caches():
        craft_golden._install(monkeypatch)
        spots = [(50.6, "LocA"), (25.4, "LocB"), (10.0, "LocC")]
        monkeypatch.setattr(
            UC,
            "where",
            lambda mineral, system=None: [
                (pct, {"name": name, "parent": "P"}) for pct, name in spots
            ],
        )
        out: Any = G.craft_detail(UC.bp_key(craft_golden.WEAPON))
        assert out["mine"]
        for m in out["mine"]:
            assert [s["pct"] for s in m["spots"]] == [51, 25]


def test_goals_craft_struct_shell_keeps_note(monkeypatch):
    """目标页用的旧壳 _craft_struct：note 照传（默认空），槽位、去哪挖、来源和制造页详情里那份一样"""
    with _clean_caches():
        craft_golden._install(monkeypatch)
        bp = craft_golden.WEAPON
        plain = G._craft_struct(bp)
        assert plain["head"]["note"] == ""
        assert G._craft_struct(bp, "配方 1/2")["head"]["note"] == "配方 1/2"
        detail = G.craft_detail(UC.bp_key(bp))
        keys = ("slots", "mine", "sources", "nsrc")
        assert {k: detail[k] for k in keys} == {k: plain[k] for k in keys}


def test_b5_crafting_usecases_match_direct():
    """CR-B5：采矿 / 物品查询用的三个用例和直接调 crafting.crafting 一样（有没有真数据都成立）"""
    from astral_toolkit.crafting import crafting as crafting_mod

    composition = [("Quantainium", 60.0, 650), ("Gold", 40.0, 700)]
    assert UC.scan_hints(composition) == crafting_mod.quality_hints(composition)
    assert UC.material_summary("Gold") == crafting_mod.mat_summary("Gold")
    assert UC.material_summary("Gold", 600) == crafting_mod.mat_summary("Gold", 600)
    assert UC.mineral_uses_text("Quantainium") == crafting_mod.uses_report(
        "Quantainium"
    )


def test_b5_has_blueprint_matches_old_hover(monkeypatch):
    """CR-B5：F8「可制造：有蓝图」和原来 hover 里 want / bps 那两句一样"""
    bps = [
        {"n": "Test Widget", "z": "测试部件"},
        {"n": "Lima", "z": None},
        {"n": "Other", "z": ""},
    ]
    monkeypatch.setattr(UC, "blueprints", lambda: bps)

    def old(*names):
        def fold(x):
            return re.sub(r"[^a-z0-9一-鿿]", "", (x or "").lower())

        want = {fold(x) for x in names} - {""}
        return bool([b for b in bps if fold(b["n"]) in want or fold(b["z"]) in want])

    for names in (
        ("测试部件",),
        ("Test Widget", "没有"),
        ("没有", "测试部件"),
        (None, "没有", "lima"),
        ("Lima",),
        ("lima",),
        ("没有",),
        (None, ""),
        (),
    ):
        assert UC.has_blueprint(*names) == old(*names), names


def test_b5_wikelo_rewards_match_old_hover(monkeypatch):
    """CR-B5：F8「可通过维科洛兑换获得」和原来 hover 里那个列表推导一样"""
    from astral_toolkit.crafting import wikelo as wikelo_mod
    from astral_toolkit.crafting import wikelo_rules

    contracts = [
        {"t": "甲", "rz": "极地涂装 巡逻车", "rewards": []},
        {"t": "乙", "rz": "", "rewards": ["测试奖励"]},
        {"t": "丙", "rz": "别的", "rewards": ["医疗笔"]},
    ]
    monkeypatch.setattr(wikelo_mod, "load", lambda: contracts)

    def old(name, zh):
        return [
            c
            for c in wikelo_mod.load()
            if any(
                wikelo_rules._same(x, name) or (zh and wikelo_rules._same(x, zh))
                for x in [c.get("rz", ""), *c.get("rewards", [])]
            )
        ]

    for name, zh in (
        ("极地涂装 巡逻车", ""),
        ("xx", "测试奖励"),
        ("xx", "医疗笔"),
        ("xx", ""),
    ):
        assert WU.rewards_for(name, zh) == old(name, zh), (name, zh)


def test_b5_mining_and_mineral_page_go_through_usecases(monkeypatch):
    """CR-B5：采矿助手的制造提示 / 可造份数、物品查询矿物页的制造用途 / 可造份数都经 tasks/crafting 的用例，参数原样传"""
    from astral_toolkit.tasks import mining as TM
    from astral_toolkit.tasks import trade as TT

    calls = []

    def hints(comp):
        calls.append(("hints", comp))
        return ["提示"]

    def summary(*args):
        calls.append(("summary", args))
        return {"count": 3}

    def uses_text(mineral):
        calls.append(("uses", mineral))
        return "用途"

    monkeypatch.setattr(UC, "scan_hints", hints)
    monkeypatch.setattr(UC, "material_summary", summary)
    monkeypatch.setattr(UC, "mineral_uses_text", uses_text)
    comp = [("Gold", 40.0, 700)]
    assert TM._quality_hints(comp) == ["提示"]
    assert TM._mat_summary("Gold", 700) == {"count": 3}
    assert calls == [("hints", comp), ("summary", ("Gold", 700))]
    info = TT.mineral_info(name="Gold")
    assert info["uses"] == "用途" and info["craft_count"] == 3
    assert ("uses", "Gold") in calls and ("summary", ("Gold",)) in calls


def test_b5_hover_lines_pass_names_to_links(monkeypatch):
    """CR-B5：F8 悬浮窗经 HoverLinks 查「可通过维科洛兑换获得」「可制造：有蓝图」，
    名字原样传：兑换用物品卡片的名字（没有用认出的英文）和中文，蓝图用卡片名字、认出的英文、中文三个"""
    from astral_toolkit.tasks import hover as Hv

    calls = []

    def rewards(name, zh):
        calls.append(("rewards", name, zh))
        return [{"t": "兑换甲"}]

    def has_bp(*names):
        calls.append(("bp", *names))
        return True

    links = Hv.HoverLinks(
        item_card=lambda *a, **k: {},
        loot=lambda *a, **k: None,
        market=lambda: None,
        market_rows=lambda *a, **k: ([], None),
        hud_market=lambda results: "",
        wikelo_rewards=rewards,
        has_blueprint=has_bp,
    )
    monkeypatch.setattr(Hv, "_goal_for", lambda *names: None)
    lines = Hv._hover_lines(links, {"name": "Card Name", "buy": []}, "OCR En", "中文名")
    assert lines == ["可通过维科洛兑换获得：兑换甲", "可制造：有蓝图（材料见物品查询）"]
    assert calls == [
        ("rewards", "Card Name", "中文名"),
        ("bp", "Card Name", "OCR En", "中文名"),
    ]
    calls.clear()
    Hv._hover_lines(links, {"buy": []}, "OCR En", "")
    assert calls[0] == ("rewards", "OCR En", "")
