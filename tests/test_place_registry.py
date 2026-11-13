"""地点总表 + 对玩家可见清单（后端架构第 1 步，2026-11-13）：建库导入、navkey 对照、清单什么时候生效、导航搜索过滤。
用最小源在 tmp_path 建库（沿用 test_gamedata_nav 的那套源）。"""

from tests.test_gamedata_nav import _built

_C = {"frame": "body_local", "unit": "km", "x": 0.0, "y": 0.0, "z": 0.0}
_PLACES = {
    "version": 1,
    "game": "test",
    "places": [
        {
            "id": "sys:Stanton",
            "kind": "system",
            "parent": None,
            "system": "Stanton",
            "coord": None,
            "en": "Stanton",
            "legacy": {"t": "system", "n": "Stanton"},
        },
        {
            "id": "poi:Hurston/ent_lorville",
            "kind": "city",
            "parent": "body:Stanton/Hurston",
            "system": "Stanton",
            "coord": _C,
            "en": "Lorville",
            "legacy": {
                "t": "pois",
                "b": "Hurston",
                "n": "Lorville",
                "x": 3.0,
                "y": 4.0,
                "z": 0.0,
            },
        },
        {
            "id": "x:Hurston/Outpost/No Marker",
            "kind": "outpost",
            "parent": "body:Stanton/Hurston",
            "system": "Stanton",
            "coord": _C,
            "en": "No Marker",
            "legacy": {
                "t": "pois",
                "b": "Hurston",
                "n": "No Marker",
                "x": 6.0,
                "y": 6.0,
                "z": 0.0,
            },
        },
        {
            "id": "pt:Stanton/HUR_L1",
            "kind": "lagrange_point",
            "parent": "sys:Stanton",
            "system": "Stanton",
            "coord": _C,
            "en": "Hurston L1",
            "legacy": {"t": "points", "i": "HUR_L1"},
        },
        {
            "id": "site:Lorville",
            "kind": "city",
            "parent": "body:Stanton/Hurston",
            "system": "Stanton",
            "coord": None,
            "en": "Lorville",
            "legacy": {"t": "city", "city": "Lorville"},
        },
        {
            "id": "spot:Lorville/lor_hab",
            "kind": "spot",
            "parent": "site:Lorville",
            "system": "Stanton",
            "coord": {
                "frame": "site_local",
                "unit": "raw",
                "x": 1.0,
                "y": 2.0,
                "z": 3.0,
            },
            "en": "Hab Lobby",
            "legacy": {"t": "city_places", "row": 0},
        },
        {
            "id": "mine:ab_mine_pyro_001",
            "kind": "mining_mining_base",
            "parent": "sys:Pyro",
            "system": "Pyro",
            "coord": _C,
            "en": "RMB-DARI",
            "legacy": {"t": "mining_spots", "id": "ab_mine_pyro_001"},
        },
        {
            "id": "poi:Hurston/ent_lorville",
            "kind": "dup",
            "parent": None,
            "system": "",
            "coord": None,
            "en": "重复编号，应该丢掉",
            "legacy": {},
        },
        "不是 dict，应该跳过",
    ],
}
_VIS = {
    "version": "t-1",
    "mode": "allow",
    "ids": [
        "poi:Hurston/ent_lorville",
        "spot:Lorville/lor_hab",
        "pt:Stanton/HUR_L1",
        7,
        "",
    ],
}

_LORVILLE = {
    "b": "Hurston",
    "n": "Lorville",
    "t": "Landing Zone",
    "x": 3.0,
    "y": 4.0,
    "z": 0.0,
    "qt": 1,
}
_NOMARK = {
    "b": "Hurston",
    "n": "No Marker",
    "t": "Outpost",
    "x": 6.0,
    "y": 6.0,
    "z": 0.0,
    "qt": None,
}


def test_no_registry_no_list_means_everything_visible(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import place_registry as R

    _built(monkeypatch, tmp_path)
    st = R.state()
    assert st["active"] is False and st["rows"] == 0 and st["meta"] is None
    shown = R.checker()
    assert shown(_NOMARK) and shown({"t": "City", "id": "whatever"})


def test_list_needs_registry_and_registry_needs_list(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import place_registry as R

    _built(monkeypatch, tmp_path, **{"places.json": _PLACES})
    assert (
        R.state()["active"] is False and R.state()["rows"] == 7
    )  # 有总表没清单：不过滤
    assert R.checker()(_NOMARK)


def test_list_without_registry_is_ignored(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import place_registry as R

    _built(monkeypatch, tmp_path, **{"place_visibility.json": _VIS})
    st = R.state()
    assert st["active"] is False and st["meta"] == {
        "version": "t-1",
        "count": 3,
    }  # 清单在、总表不在：不能把导航清空
    assert R.checker()(_NOMARK)


def test_bad_list_is_no_list(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import place_registry as R

    _built(
        monkeypatch,
        tmp_path,
        **{"places.json": _PLACES, "place_visibility.json": {"ids": "不是列表"}},
    )
    assert R.state()["active"] is False


def test_allow_list_filters_each_kind_of_entry(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import place_registry as R

    _built(
        monkeypatch, tmp_path, **{"places.json": _PLACES, "place_visibility.json": _VIS}
    )
    st = R.state()
    assert st["active"] is True and st["rows"] == 7 and len(st["visible"]) == 3
    shown = R.checker()
    assert shown(_LORVILLE) is True  # 星图点：星球 + 名字 + 坐标
    assert shown(_NOMARK) is False  # 在总表里、不在清单里
    assert (
        shown({**_LORVILLE, "x": 3.5}) is False
    )  # 坐标对不上总表：白名单，对不上就不显示
    assert (
        shown(
            {
                "b": "Hurston",
                "n": "总表里没有的点",
                "t": "Cave",
                "x": 1.0,
                "y": 1.0,
                "z": 1.0,
            }
        )
        is False
    )
    assert (
        shown({"t": "City", "id": "lor_hab", "b": "Hurston", "n": "Hab Lobby"}) is True
    )  # 城内点：按 _city_rows 的 id
    assert (
        shown({"t": "City", "id": "lor_hab2", "b": "Hurston", "n": "Hab Lobby 2"})
        is False
    )
    assert (
        shown({"t": "Mining Spot", "sys": "Pyro", "n": "RMB-DARI", "space": True})
        is False
    )  # 挖矿点在总表、没进清单
    assert (
        shown({"t": "Mining Spot", "sys": "Stanton", "n": "Hurston L1", "space": True})
        is True
    )  # 拉格朗日点当挖矿点
    assert (
        shown(
            {"t": "Orbital Station", "sys": "Stanton", "n": "Hurston L1", "space": True}
        )
        is True
    )  # 太空点
    assert (
        shown({"t": "Waypoint", "b": "Hurston", "n": "我的路标"}) is True
    )  # 路标不受限制


def test_navkey_shapes():
    from astral_toolkit.gamedata.place_registry import navkey, poi_key

    assert poi_key("Hurston", "A", 1, 2.0, "3") == "poi|Hurston|A|1.000|2.000|3.000"
    assert poi_key("Hurston", "A", None, 2.0, 3.0) == "poi|Hurston|A|||"
    assert navkey({"t": "Waypoint"}) is None
    assert navkey({"t": "City", "id": "x+"}) == "ct|x+"
    assert navkey({"t": "Mining Spot", "sys": "Pyro", "n": "RMB"}) == "ms|Pyro|RMB"
    assert (
        navkey({"t": "Jumppoint", "space": True, "sys": "Nyx", "n": "J"}) == "pt|Nyx|J"
    )


def test_search_hides_places_not_on_the_list(monkeypatch, tmp_path):
    from astral_toolkit.navigation import navigate

    data = {
        "bodies": {"Hurston": {"sys": "Stanton"}},
        "pois": [dict(_LORVILLE), dict(_NOMARK)],
        "points": [],
    }
    _built(monkeypatch, tmp_path, **{"places.json": _PLACES})
    names = {p["n"] for p in navigate.search("hurston", data, limit=1000)[0]}
    assert {"Lorville", "No Marker"} <= names  # 没有清单：都在
    _built(
        monkeypatch, tmp_path, **{"places.json": _PLACES, "place_visibility.json": _VIS}
    )
    names = {p["n"] for p in navigate.search("hurston", data, limit=1000)[0]}
    assert "Lorville" in names and "No Marker" not in names
    assert "Hab Lobby" in names and "Hab Lobby 2" not in names  # 城内点跟着清单走


def _tree_ids(tree):
    return {q["id"] for g in tree["groups"] for it in g["items"] for q in it["points"]}


def test_city_lists_and_site_follow_the_list(monkeypatch, tmp_path):
    from astral_toolkit.navigation import transit

    here = {"inside": True, "body": "Hurston", "x": 1.0, "y": 2.0, "z": 3.0}
    _built(monkeypatch, tmp_path, **{"places.json": _PLACES})
    assert _tree_ids(transit.site_tree("Lorville")) >= {"lor_hab", "lor_hab2"}
    site = transit.site_at(here=here)
    assert site is not None and site["site"] == "Lorville"
    _built(
        monkeypatch, tmp_path, **{"places.json": _PLACES, "place_visibility.json": _VIS}
    )
    assert "lor_hab" in _tree_ids(transit.site_tree("Lorville"))
    assert "lor_hab2" not in _tree_ids(transit.site_tree("Lorville"))
    site = transit.site_at(here=here)
    assert site is not None and site["site"] == "Lorville"  # 站里还有可见的点：照认
    only_poi = {**_VIS, "ids": ["poi:Hurston/ent_lorville"]}
    _built(
        monkeypatch,
        tmp_path,
        **{"places.json": _PLACES, "place_visibility.json": only_poi},
    )
    assert (
        transit.site_at(here=here) is None
    )  # 站里一个可见的点都没有：当作不认识这个站
    assert transit.site_tree("Lorville") is None


def test_nearby_does_not_name_hidden_places(monkeypatch, tmp_path):
    from astral_toolkit.navigation import celestial

    data = {
        "bodies": {"Hurston": {"sys": "Stanton"}},
        "pois": [dict(_LORVILLE), dict(_NOMARK)],
        "points": [],
    }
    here = {
        "inside": True,
        "body": "Hurston",
        "x": 6.0,
        "y": 6.0,
        "z": 0.1,
        "radius_km": 1000.0,
    }
    monkeypatch.setattr(celestial, "waypoints", lambda: [])
    _built(monkeypatch, tmp_path, **{"places.json": _PLACES})
    hit = celestial.nearby(here, data)
    assert hit is not None and hit[1]["n"] == "No Marker"
    _built(
        monkeypatch, tmp_path, **{"places.json": _PLACES, "place_visibility.json": _VIS}
    )
    hit = celestial.nearby(here, data)
    assert hit is None or hit[1]["n"] == "Lorville"  # 不可见的不报；可见的在范围内才报


def test_data_pack_visibility_only_for_players(monkeypatch, tmp_path):
    from astral_toolkit.core import paths
    from astral_toolkit.update import data_pack as P
    from tests.minipytest import raises

    assert "places.json" in P.FILES and P.VISIBILITY in P.FILES
    monkeypatch.setenv("AT_PLAYER_VIEW", "0")
    monkeypatch.setattr(paths, "VELOPACK", False)
    assert P._wanted("places.json") and not P._wanted(P.VISIBILITY)  # 开发机不装清单
    monkeypatch.setenv("AT_PLAYER_VIEW", "1")
    assert P._wanted(P.VISIBILITY)  # 想在开发机上看玩家视角
    monkeypatch.setenv("AT_PLAYER_VIEW", "0")
    monkeypatch.setattr(paths, "VELOPACK", True)
    assert P._wanted(P.VISIBILITY)  # 安装版照装
    monkeypatch.setattr(P, "DATA", tmp_path / "data")
    (tmp_path / "data").mkdir()
    with raises(ValueError):  # 没有清单 / 总表不打数据包，不能把全量地点发出去
        P.make(tmp_path / "out", date="2026.11.13-0000")


def test_duplicate_city_points_do_not_share_visibility(monkeypatch, tmp_path):
    """同城同名同坐标的两个点（_city_rows 给第二个的 id 带 +）：只放行一个编号时，另一个不能跟着显示"""
    from astral_toolkit.gamedata import place_registry as R

    row = {
        "city": "Lorville",
        "body": "Hurston",
        "cat": "货梯",
        "en": "Freight Elevator",
        "src": "lift",
        "zh": "货运电梯",
        "area": "",
        "x": 9.0,
        "y": 9.0,
        "z": 9.0,
        "kinds": [],
        "site_en": "Lorville",
        "site_zh": "洛维尔",
    }
    spot = {
        "kind": "spot",
        "parent": "site:Lorville",
        "system": "Stanton",
        "en": "Freight Elevator",
        "coord": {"frame": "site_local", "unit": "raw", "x": 9.0, "y": 9.0, "z": 9.0},
    }
    places = {
        "version": 1,
        "places": [
            {
                **spot,
                "id": "spot:Lorville/lift#1",
                "legacy": {"t": "city_places", "row": 0},
            },
            {
                **spot,
                "id": "spot:Lorville/lift#2",
                "legacy": {"t": "city_places", "row": 1},
            },
        ],
    }
    vis = {"version": "t", "ids": ["spot:Lorville/lift#2"]}
    _built(
        monkeypatch,
        tmp_path,
        **{
            "city_places.json": [row, dict(row)],
            "places.json": places,
            "place_visibility.json": vis,
        },
    )
    shown = R.checker()
    assert (
        shown({"t": "City", "id": "lift"}) is False
        and shown({"t": "City", "id": "lift+"}) is True
    )


def test_navkey_matches_builder_on_missing_fields():
    from astral_toolkit.gamedata.place_registry import navkey

    assert navkey({"t": "Mining Spot", "sys": None, "n": None}) == "ms||"
    assert navkey({"space": True, "t": "Jumppoint"}) == "pt||"
    assert navkey({"t": "City"}) == "ct|"


def test_check_release_blocks_bad_files(monkeypatch, tmp_path):
    import json

    from astral_toolkit.update import data_pack as P
    from tests.minipytest import raises

    d = tmp_path / "data"
    (d / "release").mkdir(parents=True)
    monkeypatch.setattr(P, "DATA", d)

    def put(places, vis):
        (d / "places.json").write_text(json.dumps(places), encoding="utf-8")
        (d / "release" / P.VISIBILITY).write_text(json.dumps(vis), encoding="utf-8")

    good = {"places": [{"id": "a"}, {"id": "b"}]}
    put(good, {"ids": ["a"]})
    assert P.check_release() == 1
    for places, vis in (
        (good, {"ids": "不是列表"}),
        (good, {"ids": []}),
        (good, ["a"]),
        (good, {"ids": ["a", 3]}),
        (good, {"ids": ["a", "总表里没有"]}),
        ({"places": []}, {"ids": ["a"]}),
        ([], {"ids": ["a"]}),
    ):
        put(places, vis)
        with raises(ValueError):
            P.check_release()
    (d / "release" / P.VISIBILITY).write_text("{坏的", encoding="utf-8")
    with raises(ValueError):
        P.check_release()
