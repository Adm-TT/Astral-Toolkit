"""游戏数据层批 2：星图 / 位置 / 城市与空间站中转 / 地表导航 / 地名对照 改走游戏数据层

全部用 tmp_path 当 data/ 根（monkeypatch paths.DATA），最小数据复用 test_gamedata_nav 的 _NAV_SOURCES；
不读真实 data/、不碰 userdata/、不联网。"""

import json
from contextlib import contextmanager

from tests.test_gamedata_nav import _NAV_SOURCES, _write_all


def _setup(monkeypatch, tmp_path, **override):
    """tmp_path 当 data/ 根、写最小源（物品 + 导航）；就绪标记、后台线程记录换成新的；星图文件路径指到 tmp_path"""
    import sc_mining.gamedata as G
    from sc_mining.core import paths
    from sc_mining.gamedata import _ready
    from sc_mining.navigation import starmap

    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(_ready, "_state", {"done": None, "failed": None})
    monkeypatch.setattr(G, "_state", {"last_error": None, "warm_thread": None})
    monkeypatch.setattr(starmap, "CACHE", tmp_path / "starmap.json")
    _write_all(tmp_path, **override)
    return tmp_path


def _legacy_starmap(tmp_path):
    """以前 starmap.load() 的做法：读 starmap.json、套 starmap_fixes.json、bodies 补 name"""
    from sc_mining.navigation.starmap import fix_points

    data = json.loads((tmp_path / "starmap.json").read_text(encoding="utf-8"))
    fix_points(
        data, json.loads((tmp_path / "starmap_fixes.json").read_text(encoding="utf-8"))
    )
    for name, b in data["bodies"].items():
        b["name"] = name
    return data


# ---------------------------------------------------------------- Task 1：星图


def test_data_dict_shape_matches_legacy(monkeypatch, tmp_path):
    from sc_mining.navigation import starmap

    _setup(monkeypatch, tmp_path)
    d = starmap.load()
    assert set(d) == {"bodies", "pois", "points", "fetched"}
    assert d == _legacy_starmap(tmp_path)
    assert [p["n"] for p in d["points"]] == [
        "Stanton Star",
        "Hurston L1",
        "Dup A",
        "Dup B",
    ]  # 源顺序，同内部名两条都在
    assert d["points"][1]["x"] == 9.0  # 坐标改正套上了
    assert [q["qt"] for q in d["pois"]] == [0, 1, None]  # 没信标的 qt 原样是 None
    assert set(d["bodies"]["Hurston"]) == {
        "sys",
        "x",
        "y",
        "z",
        "rot",
        "adj",
        "r",
        "om",
        "grid",
        "name",
    }
    assert starmap.load() is d  # 同一版本同一个对象


def test_starmap_load_refreshes_after_rebuild(monkeypatch, tmp_path):
    """更新数据后导航立刻用新星图：换代后 load() 返回新内容"""
    import sc_mining.gamedata as G
    from sc_mining.navigation import starmap

    _setup(monkeypatch, tmp_path)
    old = starmap.load()
    new_src = json.loads(json.dumps(_NAV_SOURCES["starmap.json"]))
    new_src["bodies"]["Hurston"]["x"] = 42.0
    new_src["fetched"] = "2026-11-02"
    with G.updating():
        (tmp_path / "starmap.json").write_text(json.dumps(new_src), encoding="utf-8")
    d = starmap.load()
    assert d is not old
    assert d["bodies"]["Hurston"]["x"] == 42.0 and d["fetched"] == "2026-11-02"


def test_starmap_update_runs_inside_updating(monkeypatch, tmp_path):
    """starmap.update() 写 starmap.json 在 gamedata.updating() 里（退出时重建库），联网不在里面"""
    import sc_mining.gamedata as G
    from sc_mining.navigation import starmap

    _setup(monkeypatch, tmp_path)
    (tmp_path / "starmap.json").unlink()
    log = []
    fake = dict(
        source="starmap.space",
        fetched="2026-11-02",
        bodies={f"B{i}": {} for i in range(10)},
        pois=[{"qt": 1}] * 300,
        points=[],
    )
    monkeypatch.setattr(starmap, "_fetch", lambda path: log.append("fetch") or [])
    monkeypatch.setattr(starmap, "compact", lambda oc, pois: fake)

    @contextmanager
    def updating():
        log.append(("enter", starmap.CACHE.exists()))
        yield
        log.append(("exit", starmap.CACHE.exists()))

    monkeypatch.setattr(G, "updating", updating)
    starmap.update()
    assert log == ["fetch", "fetch", ("enter", False), ("exit", True)]


def test_starmap_load_downloads_when_no_file(monkeypatch, tmp_path):
    """还没有 starmap.json：和以前一样先下载一次再读"""
    from sc_mining.navigation import starmap

    _setup(monkeypatch, tmp_path)
    src = (tmp_path / "starmap.json").read_text(encoding="utf-8")
    (tmp_path / "starmap.json").unlink()
    called = []

    def fake_update():
        called.append(1)
        (tmp_path / "starmap.json").write_text(src, encoding="utf-8")

    monkeypatch.setattr(starmap, "update", fake_update)
    d = starmap.load()
    assert called == [1] and "Hurston" in d["bodies"]
