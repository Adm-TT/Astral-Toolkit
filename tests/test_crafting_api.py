"""CR-B4：制造 / 维科洛接口拆到 app/api + tasks 用例 + presenters 后，接口结果仍和 tasks/goals.py 旧壳逐字一样。"""

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
