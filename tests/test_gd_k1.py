"""游戏数据层收口 1（GD-K1）：按版本缓存的公共工具、写源文件进更新边界、数据来源判断的模块名

全部用 tmp_path 当 data/ 根，不读真实 data/、不写 userdata/。"""

from tests.test_gamedata_b1 import _setup

# ---------------------------------------------------------------- Task 1：VersionCache


class _Snap:
    def __init__(self, v):
        self.data_version = v


def test_version_cache_rebuilds_on_new_version():
    from sc_mining.gamedata._cache import VersionCache

    c = VersionCache()
    calls = []

    def build(s):
        calls.append(s.data_version)
        return [s.data_version]

    a = c.get(_Snap("v1"), build)
    assert c.get(_Snap("v1"), build) is a and calls == ["v1"]  # 同版本：同一个对象
    b = c.get(_Snap("v2"), build)
    assert b == ["v2"] and calls == ["v1", "v2"]
    assert c.get(_Snap("v1"), build) is not a and calls == [
        "v1",
        "v2",
        "v1",
    ]  # 只留当前版本，回到 v1 要重算


def test_version_cache_clear_and_peek():
    from sc_mining.gamedata._cache import VersionCache

    c = VersionCache()
    assert c.peek() is None
    c.get(_Snap("v1"), lambda s: 1)
    assert c.peek() == 1
    c.clear()
    assert c.peek() is None
    calls = []
    c.get(_Snap("v1"), lambda s: calls.append(1) or 2)
    assert calls == [1]  # 清掉后重算


def test_version_cache_get_for_none_key():
    """还没有库（版本 None）：没 key_after 就不缓存；有 key_after 就用算完后的版本当键（stockplaces 的用法）"""
    from sc_mining.gamedata._cache import VersionCache

    c = VersionCache()
    calls = []
    c.get_for(None, lambda: calls.append(1) or "x")
    c.get_for(None, lambda: calls.append(1) or "x")
    assert calls == [1, 1] and c.peek() is None
    c.get_for(None, lambda: calls.append(1) or "y", key_after=lambda: "v9")
    assert c.peek() == "y"
    assert c.get_for("v9", lambda: calls.append(1) or "z") == "y" and calls == [1, 1, 1]


def test_topics_share_version_cache(monkeypatch, tmp_path):
    """items.candidates / shops.catalog / stockplaces.places / itemsearch 索引：换代后都重算，同代内是同一份"""
    import json

    import sc_mining.gamedata as G
    from sc_mining.crafting import itemsearch as IS
    from sc_mining.crafting import stockplaces as SP
    from sc_mining.gamedata import items as gd_items
    from sc_mining.gamedata import shops as gd_shops
    from sc_mining.gamedata._cache import VersionCache
    from tests.test_gamedata import _write_min_sources

    _setup(monkeypatch, tmp_path)
    for mod, name in (
        (gd_items, "_cand"),
        (gd_shops, "_cat"),
        (SP, "_PLACES"),
        (IS, "_cache"),
    ):
        assert isinstance(getattr(mod, name), VersionCache)
        monkeypatch.setattr(mod, name, VersionCache())
    monkeypatch.setattr(SP, "_INDEX", VersionCache())
    a = (gd_items.candidates(), gd_shops.catalog(), SP.places(), IS._build())
    assert all(
        x is y
        for x, y in zip(
            a, (gd_items.candidates(), gd_shops.catalog(), SP.places(), IS._build())
        )
    )
    src = json.loads((tmp_path / "shops.json").read_text(encoding="utf-8"))
    src["items"]["999"] = ["Brand New Thing", "Misc"]
    _write_min_sources(tmp_path, **{"shops.json": src})
    with G.updating():
        pass
    b = (gd_items.candidates(), gd_shops.catalog(), SP.places(), IS._build())
    assert all(x is not y for x, y in zip(a, b))
    assert any(c.en == "Brand New Thing" for c in b[1])
