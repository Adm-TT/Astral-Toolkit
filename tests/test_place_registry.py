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
