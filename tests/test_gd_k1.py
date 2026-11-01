"""游戏数据层收口 1（GD-K1）：按版本缓存的公共工具、写源文件进更新边界、数据来源判断的模块名

全部用 tmp_path 当 data/ 根，不读真实 data/、不写 userdata/。"""

from tests.test_gamedata_b1 import _count_updating, _fresh_search, _setup

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


# ---------------------------------------------------------------- Task 2：写源文件进更新边界，删 itemsearch 的补建库钩子


def _fake_localization(monkeypatch, tmp_path, aliases, zh_names=None, with_build=False):
    """让 localization.rebuild 不读真汉化、不联网：汉化源是个假 .ini，各转换函数返回给定内容；
    with_build 时本机"有构建输入"，走 BUILD_LOCK 里的蓝图 + 维科洛重建（也换成记录器）"""
    from sc_mining.crafting import build_crafting
    from sc_mining.crafting import wikelo
    from sc_mining.update import data_pack, localization as L

    ini = tmp_path / "fake.ini"
    ini.write_text("", encoding="utf-8")
    monkeypatch.setattr(L, "names_source", lambda: ini)
    monkeypatch.setattr(L, "read_ini", lambda p: {})
    monkeypatch.setattr(
        L, "zh2en_items", lambda ini, wiki_cls=None: dict(zh_names or {})
    )
    monkeypatch.setattr(L, "places", lambda ini: {})
    monkeypatch.setattr(L, "place_codes", lambda ini: {})
    monkeypatch.setattr(L, "ALIASES", dict(aliases))
    monkeypatch.setattr(L, "DATA", tmp_path)
    monkeypatch.setattr(
        data_pack, "clear_caches", lambda: None
    )  # 真的会读 prices.json、改 mining.data
    built = []
    if with_build:
        bp, merged = tmp_path / "bp.json", tmp_path / "merged.json"
        bp.write_text("{}", encoding="utf-8")
        merged.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(build_crafting, "source_rows", lambda: (bp, merged, "v"))
        monkeypatch.setattr(build_crafting, "build", lambda *a, **k: built.append("bp"))
        monkeypatch.setattr(wikelo, "build", lambda *a, **k: built.append("wk") or 0)
    else:
        monkeypatch.setattr(build_crafting, "source_rows", lambda: None)
        monkeypatch.setattr(build_crafting, "latest_live", lambda it: None)
    return built


def test_localization_rebuild_runs_inside_updating(monkeypatch, tmp_path):
    """汉化重建写的四份源文件和 BUILD_LOCK 里的蓝图重建都在 updating() 里，边界只进一次（updating 在外、BUILD_LOCK 在内）"""
    from sc_mining.crafting import build_crafting
    from sc_mining.update import localization as L

    _setup(monkeypatch, tmp_path)
    state = _count_updating(monkeypatch)
    built = _fake_localization(monkeypatch, tmp_path, {"A": "B"}, with_build=True)
    inside_build = []
    real_build = build_crafting.build
    monkeypatch.setattr(
        build_crafting,
        "build",
        lambda *a, **k: inside_build.append(state["inside"]) or real_build(*a, **k),
    )
    L.rebuild(progress=lambda *_: None)
    assert state["n"] == 1
    assert [p.name for p, _ in state["writes"]] == [
        "zh_names.json",
        "name_aliases.json",
        "places_zh.json",
        "place_codes_zh.json",
    ]
    assert all(inside for _, inside in state["writes"])
    assert built == ["bp", "wk"] and inside_build == [True]


def test_loot_update_runs_inside_updating(monkeypatch, tmp_path):
    from sc_mining.crafting import loot

    _setup(monkeypatch, tmp_path)
    state = _count_updating(monkeypatch)
    monkeypatch.setattr(loot, "INDEX", tmp_path / "loot_index.json")
    monkeypatch.setattr(loot, "latest_version", lambda: "4.10")
    monkeypatch.setattr(
        loot,
        "_get",
        lambda url, timeout=60: (
            {"version": "4.10"} if url.endswith("manifest.json") else []
        ),
    )
    monkeypatch.setattr(loot, "_index", None)
    loot.update(progress=None)
    assert state["n"] == 1 and len(state["writes"]) == 1 and state["writes"][0][1]
    assert loot._index == {"version": "4.10", "rows": []}


def test_itemsearch_sees_new_aliases_after_localization_rebuild(monkeypatch, tmp_path):
    """汉化重建改了 name_aliases.json：靠 updating() 出口重建库，物品搜索下次就看到新旧写法——不再需要 clear_caches 里的补建库钩子"""
    import json

    import sc_mining.gamedata as G
    from sc_mining.update import data_pack, localization as L

    _setup(monkeypatch, tmp_path)
    IS = _fresh_search(monkeypatch)
    G.ensure()
    assert IS.lookup("MedPack X") is None
    zh = json.loads((tmp_path / "zh_names.json").read_text(encoding="utf-8"))
    _fake_localization(monkeypatch, tmp_path, {"MedPack X": "Medpen"}, zh_names=zh)
    L.rebuild(progress=lambda *_: None)
    assert (IS.lookup("MedPack X") or {}).get("ek") == "medpen"
    assert not hasattr(IS, "_on_data_changed")
    assert all(
        getattr(fn, "__module__", "") != IS.__name__ for fn in data_pack.CACHE_HOOKS
    )


# ---------------------------------------------------------------- Task 3：数据来源判断认得 starmap 模块名


def test_is_game_source_recognizes_starmap_update(monkeypatch, tmp_path):
    """navigate.update 其实是 starmap.update：本机 starmap.json 是游戏数据版 → 跳过网站更新；网站版 → 不跳过"""
    import json

    from sc_mining import run
    from sc_mining.core import paths
    from sc_mining.navigation import navigate

    monkeypatch.setattr(paths, "DATA", tmp_path)
    assert navigate.update.__module__ == "sc_mining.navigation.starmap"
    (tmp_path / "starmap.json").write_text(
        json.dumps({"source": paths.SRC_GAME}), encoding="utf-8"
    )
    assert run._is_game_source(navigate.update) is True
    (tmp_path / "starmap.json").write_text(
        json.dumps({"source": "starmap.space"}), encoding="utf-8"
    )
    assert run._is_game_source(navigate.update) is False


def test_make_data_pack_web_ok_names_starmap_too(monkeypatch, tmp_path):
    """设好了构建目录：去网站更新时 web_ok 里两个模块名都有（否则 run.update 会按 starmap 名跳过星图）"""
    import json
    import runpy
    import subprocess
    from pathlib import Path

    from sc_mining import run
    from sc_mining.core import paths
    from sc_mining.update import data_pack
    from tests.minipytest import raises

    M = runpy.run_path(
        str(Path(__file__).resolve().parent.parent / "tools" / "make_data_pack.py")
    )
    monkeypatch.setattr(paths, "DATA", tmp_path)
    (tmp_path / "starmap.json").write_text(
        json.dumps({"source": "starmap.space"}), encoding="utf-8"
    )
    calls = []
    monkeypatch.setattr(run, "update", lambda **kw: calls.append(kw) or {"results": []})
    src = tmp_path / "src"
    (src / "oc_x").mkdir(parents=True)
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "starmap_merge.py").write_text("", encoding="utf-8")
    monkeypatch.setenv("AT_SRC_DIR", str(src))
    monkeypatch.setenv("AT_DATA_TOOLS", str(tools))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)

    class Stop(Exception):
        pass

    def stop(*a, **kw):
        raise Stop

    monkeypatch.setattr(data_pack, "make", stop)  # 走到打包就停，不真打包
    with raises(Stop):
        M["main"](["--no-loot"])
    assert len(calls) == 1 and set(calls[0]["web_ok"]) == {
        "sc_mining.navigation.navigate",
        "sc_mining.navigation.starmap",
    }
