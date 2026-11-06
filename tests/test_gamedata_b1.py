"""游戏数据层批 1：就绪等待、items / shops / prices 查询主题，以及商店 / 物品搜索 / 库存地点 / 矿价改走数据层

全部用 tmp_path 当 data/ 根（monkeypatch paths.DATA），不读真实 data/、不写 userdata/。"""

from tests.test_gamedata import _write_min_sources
from astral_toolkit.gamedata._cache import VersionCache as _VC


def _setup(monkeypatch, tmp_path, **override):
    """tmp_path 当 data/ 根、写最小源；就绪标记和后台线程记录换成新的（每个测试一个新库目录）"""
    import astral_toolkit.gamedata as G
    from astral_toolkit.core import paths
    from astral_toolkit.gamedata import _ready

    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(_ready, "_state", {"done": None, "failed": None})
    monkeypatch.setattr(G, "_state", {"last_error": None, "warm_thread": None})
    _write_min_sources(tmp_path, **override)
    return tmp_path


# ---------------------------------------------------------------- Task 1：首次查询前的就绪等待


def test_ensure_builds_when_missing(monkeypatch, tmp_path):
    import astral_toolkit.gamedata as G
    from astral_toolkit.gamedata._manifest import read_manifest

    _setup(monkeypatch, tmp_path)
    assert read_manifest() is None
    G.ensure()
    assert read_manifest() is not None
    with G.snapshot() as s:
        assert s.execute("select count(*) from shop_rows")[0][0] == 3


def test_ensure_waits_for_warm_up(monkeypatch, tmp_path):
    import astral_toolkit.gamedata as G
    from astral_toolkit.gamedata._manifest import read_manifest

    _setup(monkeypatch, tmp_path)
    t = G.warm_up()
    G.ensure()
    t.join(10)
    assert read_manifest() is not None
    assert len(list((tmp_path / "gamedata").glob("gamedata-*.db"))) == 1  # 只建了一代


def test_ensure_raises_when_no_sources(monkeypatch, tmp_path):
    import astral_toolkit.gamedata as G
    from astral_toolkit.core import paths
    from astral_toolkit.gamedata import _ready
    from tests.minipytest import raises

    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(paths, "DATA", tmp_path / "empty")  # 没有 shops.json：建不出库
    with raises(G.BuildError):
        G.ensure()
    assert _ready._state["done"] != str(
        tmp_path / "empty" / "gamedata"
    )  # 建失败不能记成已就绪


def test_shops_queries_empty_when_db_unavailable(monkeypatch, tmp_path):
    """库建不出来（没有 shops.json）：F8 / 哪买 / 可买 查不到东西，但不往外抛（和以前读不到文件一样）"""
    from astral_toolkit.core import paths
    from astral_toolkit.crafting import shops

    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(paths, "DATA", tmp_path / "empty")
    assert shops.find("Lawson") == []
    assert shops.find_close("Lawson Arms") is None
    assert shops.where(200) == ([], [])
    assert shops.where_by_name("Lawson") == ""
    assert shops.nearest(200, None) == []
    assert shops.buyable(200) is False
    assert shops.variants("Lawson Arms") == []
    assert shops.buyable(float("nan")) is False and shops.where(float("inf")) == (
        [],
        [],
    )


def test_ensure_backs_off_after_failure(monkeypatch, tmp_path):
    """建库失败后 30 秒内再查：直接抛，不再拿锁读源重试；过了时限再试一次"""
    import astral_toolkit.gamedata as G
    from astral_toolkit.core import paths
    from astral_toolkit.gamedata import _build, _ready
    from tests.minipytest import raises

    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(paths, "DATA", tmp_path / "empty")
    calls = []
    real = _build.rebuild_if_needed

    def counting():
        calls.append(1)
        return real()

    monkeypatch.setattr(_build, "rebuild_if_needed", counting)
    with raises(G.GamedataError):
        G.ensure()
    with raises(G.GamedataError):
        G.ensure()
    assert calls == [1]  # 第二次没重试
    w, _t, e = _ready._state["failed"]
    _ready._state["failed"] = (w, -(10**9), e)  # 当作过了时限
    with raises(G.GamedataError):
        G.ensure()
    assert calls == [1, 1]


def test_ensure_wraps_non_gamedata_errors(monkeypatch, tmp_path):
    """写锁 mkdir / open 这类 OSError 也包成 GamedataError：功能模块只接这一种（GD-B6 审查第 2 条）"""
    import astral_toolkit.gamedata as G
    from astral_toolkit.gamedata import _build
    from tests.minipytest import raises

    _setup(monkeypatch, tmp_path)

    def boom():
        raise PermissionError("数据目录只读")

    monkeypatch.setattr(_build, "rebuild_if_needed", boom)
    with raises(G.GamedataError) as got:
        G.ensure()
    assert got.value is not None and isinstance(got.value.__cause__, PermissionError)
    with raises(G.GamedataError):
        G.ensure()  # 退避期内再来：还是 GamedataError


def test_ensure_fast_path_after_first_success(monkeypatch, tmp_path):
    import astral_toolkit.gamedata as G
    from astral_toolkit.gamedata import _build

    _setup(monkeypatch, tmp_path)
    G.ensure()
    calls = []
    monkeypatch.setattr(_build, "rebuild_if_needed", lambda *a, **k: calls.append(1))
    G.ensure()
    assert calls == []  # 核对过一次就不再每次查询都读源文件算哈希


# ---------------------------------------------------------------- Task 2：items / shops / prices 查询主题


def test_items_get_all_and_order(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import items

    _setup(monkeypatch, tmp_path)
    rows = items.all()
    assert [r.source_order for r in rows] == sorted(r.source_order for r in rows)
    assert rows[0].en == "Venture Arms" and rows[0].has_shop and rows[0].cat == "Arms"
    med = items.get("medpen")
    assert (
        med is not None
        and med.zh == "医疗笔"
        and med.has_loot
        and med.wiki
        and med.wtype == "Consumable"
    )
    assert items.get("nothing") is None


def test_items_candidates_aliases_and_cache(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import items

    _setup(monkeypatch, tmp_path)
    c = items.candidates()
    med = next(x for x in c if x.item_id == "medpen")
    assert med.aliases == ("Medi Pen",)
    assert not any(
        "Venture Arms" in x.aliases for x in c
    )  # 已经是另一件物品的旧写法不登记
    assert items.candidates() is c  # 同一版本缓存


def test_items_names_and_zh_keys(monkeypatch, tmp_path):
    from astral_toolkit.contracts.textkeys import zh_key
    from astral_toolkit.gamedata import items

    _setup(monkeypatch, tmp_path)
    kinds = [k for k, _n, _m in items.names_of("medpen")]
    assert kinds[0] == "en" and "zh_loot" in kinds and "aka" in kinds
    zk = items.zh_keys_of_all()
    assert zk["medpen"] == (zh_key("医疗笔"),)
    assert "venturearms" not in zk


def test_items_by_name_and_source_id(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import items

    _setup(monkeypatch, tmp_path)

    def iid(x):
        return x.item_id if x else None

    assert iid(items.by_name("MEDPEN")) == "medpen"
    assert iid(items.by_name("Medi Pen")) == "medpen"  # 旧写法
    assert items.by_name("") is None and items.by_name("zzz") is None
    a, b = items.by_source_id("uex", "200"), items.by_source_id("uex", "201")
    assert a is not None and a == b  # 同名两个商店编号是同一件物品
    assert iid(items.by_source_id("loot_uuid", "u1")) == "medpen"
    assert items.by_source_id("uex", "999") is None


def test_items_search(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import items

    _setup(monkeypatch, tmp_path)
    hits = items.search("law")
    assert [r.en for r in hits] == ["Lawson Mining Laser"]
    assert {r.item_id for r in items.search("医疗")} == {"medpen"}
    assert len(items.search("e", limit=1)) == 1
    assert len(items.search("e", limit=None)) > 1
    assert items.search("%") == () and items.search("") == ()  # 通配符按字面找


def test_shops_rows_buyable_places(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import shops

    _setup(monkeypatch, tmp_path)
    rows = shops.rows_for_item(171)
    assert [r.shop_name for r in rows] == ["Shop A", "Shop B"]
    assert rows[0].price_buy == 586.0 and rows[0].fields[5] == "New Babbage"
    assert shops.buyable(171) and shops.buyable(200) and not shops.buyable(201)
    assert len(shops.place_fields()) == 3  # 不去重


def test_shops_lagrange_rows(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import shops
    from tests.test_gamedata import _MIN_SOURCES

    src = dict(_MIN_SOURCES["shops.json"])
    src["rows"] = src["rows"] + [
        [
            171,
            "Shop L",
            "L1",
            1.0,
            0.0,
            "4.10",
            ["Stanton", "ArcCorp", "ArcCorp Lagrange Point 1", "", "Station X", ""],
        ],
        [
            171,
            "Shop M",
            "L2",
            1.0,
            0.0,
            "4.10",
            ["Stanton", "ArcCorp", "ArcCorp Lagrange Point 2", "", "", ""],
        ],
    ]
    _setup(monkeypatch, tmp_path, **{"shops.json": src})
    assert [r.shop_name for r in shops.lagrange_rows()] == ["Shop L"]


def test_prices_city_prices(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import prices

    _setup(monkeypatch, tmp_path)
    cp = prices.city_prices()
    assert cp["Aluminum"]["Lorville"] == 3000.0 and list(cp["Aluminum"]) == [
        "Area18",
        "Lorville",
    ]
    _setup(monkeypatch, tmp_path / "np", **{"prices.json": {"prices": {}}})
    assert prices.city_prices() == {}


def test_topic_calls_share_outer_snapshot(monkeypatch, tmp_path):
    import astral_toolkit.gamedata as G
    from astral_toolkit.gamedata import items, shops
    from tests.test_gamedata import _MIN_SOURCES

    _setup(monkeypatch, tmp_path)
    G.ensure()
    with G.snapshot() as s:
        before = len(shops.place_fields(s))
        src = dict(_MIN_SOURCES["shops.json"])
        src["rows"] = src["rows"] + [
            [171, "Shop N", "N", 1.0, 0.0, "4.10", ["Stanton", "", "", "", "N", ""]]
        ]
        _write_min_sources(tmp_path, **{"shops.json": src})
        G.rebuild()  # 中途发布新代
        assert len(shops.place_fields(s)) == before  # 传进来的快照还是旧代
        assert len(shops.place_fields()) == before  # 不传也复用外层快照（嵌套）
        assert items.get("medpen", s) is not None
    assert len(shops.place_fields()) == before + 1  # 出了快照读到新代


# ---------------------------------------------------------------- Task 4：库存地点和拉格朗日站名


def _shops_with_rows(*extra):
    from tests.test_gamedata import _MIN_SOURCES

    src = dict(_MIN_SOURCES["shops.json"])
    src["rows"] = src["rows"] + [list(r) for r in extra]
    return {"shops.json": src}


def test_raw_places_from_gamedata(monkeypatch, tmp_path):
    from astral_toolkit.crafting import stockplaces as SP

    _setup(monkeypatch, tmp_path)
    assert SP._raw_places() == [
        ("Stanton", "MicroTech", "", "New Babbage", True)
    ]  # 3 行同一地点 → 1 个


def test_raw_places_fallback_when_no_db(monkeypatch, tmp_path):
    from astral_toolkit.core import paths
    from astral_toolkit.crafting import stockplaces as SP

    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(paths, "DATA", tmp_path / "empty")  # 建不出库：保底列表
    assert SP._raw_places() == list(SP._FALLBACK)


def test_places_refresh_after_version_change(monkeypatch, tmp_path):
    import astral_toolkit.gamedata as G
    from astral_toolkit.crafting import stockplaces as SP

    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(SP, "_PLACES", _VC())
    monkeypatch.setattr(SP, "_INDEX", _VC())
    first = SP.places()
    assert [p["en"] for p in first] == [
        "New Babbage"
    ] and SP.places() is first  # 同一版本复用
    assert (SP.match("NewBabbage") or {}).get("en") == "New Babbage"
    row = [
        171,
        "Shop P",
        "P",
        1.0,
        0.0,
        "4.10",
        ["Stanton", "Hurston", "", "", "", "Lorville"],
    ]
    _write_min_sources(tmp_path, **_shops_with_rows(row))
    G.rebuild()
    assert {p["en"] for p in SP.places()} == {
        "New Babbage",
        "Lorville",
    }  # 不用 clear_caches
    assert (SP.match("Lorville") or {}).get("en") == "Lorville"


def test_places_refresh_after_name_files_rebuild(monkeypatch, tmp_path):
    """汉化包换了：名字文件是建库源，重建后版本变，places() 自己换新；不再靠 clear_caches 按名字清（收口 2）"""
    import json

    import astral_toolkit.gamedata as G
    from astral_toolkit.crafting import stockplaces as SP

    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(SP, "_PLACES", _VC())
    monkeypatch.setattr(SP, "_INDEX", _VC())
    first = SP.places()
    assert SP.places() is first and not hasattr(SP.places, "cache_clear")
    with G.updating():
        (tmp_path / "places_zh.json").write_text(
            json.dumps({"X": "换了"}), encoding="utf-8"
        )
    assert SP.places() is not first


def test_station_at_uses_lagrange_rows(monkeypatch, tmp_path):
    from astral_toolkit.crafting import shops
    from astral_toolkit.navigation import position

    row = [
        171,
        "Shop L",
        "L1",
        1.0,
        0.0,
        "4.10",
        ["Stanton", "ArcCorp", "Lagrange Point 1", "", "Station X", ""],
    ]
    _setup(monkeypatch, tmp_path, **_shops_with_rows(row))
    monkeypatch.setattr(
        shops, "shop_point", lambda f: {"i": "ARC_L1"} if f[4] == "Station X" else None
    )
    monkeypatch.setattr(
        position, "_data_version", lambda: str(tmp_path)
    )  # 站名表按库版本缓存：用这个测试自己的键，不拿别的测试建的表
    assert position._station_at("ARC_L1") == "Station X"
    assert position._station_at("ARC_L2") == ""


def _fake_station_rows(monkeypatch, rows, bad=()):
    """假的拉格朗日商店行和 shop_point（按行星认点：Pyro I → P1_L2、Pyro II → P2_L1；站名在 bad 里的那行出错），记调用次数"""
    from types import SimpleNamespace

    from astral_toolkit.crafting import shops
    from astral_toolkit.gamedata import shops as gd_shops

    calls = {"rows": 0, "point": 0}

    def fake_rows():
        calls["rows"] += 1
        return tuple(SimpleNamespace(fields=f) for f in rows)

    def fake_point(f):
        calls["point"] += 1
        if f[4] in bad:
            raise RuntimeError("坏行")
        return {"i": {"Pyro I": "P1_L2", "Pyro II": "P2_L1"}[f[1]]}

    monkeypatch.setattr(gd_shops, "lagrange_rows", fake_rows)
    monkeypatch.setattr(shops, "shop_point", fake_point)
    return calls


def _pyro_row(planet, station="", city=""):
    lp = {"Pyro I": "Lagrange Point 2", "Pyro II": "Lagrange Point 1"}[planet]
    return ["Pyro", planet, lp, "", station, city]


def test_station_table_scans_once_first_row_wins(monkeypatch):
    """站名表：整张商店表只扫一遍（以前每查一个点扫一遍、每行都查星图库，全局搜索第一次要等 4 秒）；
    同一个点有几行取源顺序第一行，没有站名用城市名，同样的位置只算一次星图点，查不到返回空"""
    from astral_toolkit.navigation import position

    rows = [
        _pyro_row("Pyro I", "Station A"),
        _pyro_row("Pyro I", "Station A"),
        _pyro_row("Pyro I", "Station B"),
        _pyro_row("Pyro II", city="City C"),
    ]
    calls = _fake_station_rows(monkeypatch, rows)
    monkeypatch.setattr(position, "_data_version", lambda: "station-test-1")
    assert position._station_at("P1_L2") == "Station A"
    assert position._station_at("P2_L1") == "City C"
    assert position._station_at("P9_L9") == ""
    assert calls == {"rows": 1, "point": 3}


def test_station_table_follows_data_version(monkeypatch):
    """站名表按库版本缓存：同一版本不重扫；换代以后重扫、用上新数据；汉化包更新时 reset_names 也清掉"""
    from astral_toolkit.navigation import position

    rows = [_pyro_row("Pyro I", "Station A")]
    calls = _fake_station_rows(monkeypatch, rows)
    ver = {"v": "station-test-a"}
    monkeypatch.setattr(position, "_data_version", lambda: ver["v"])
    assert position._station_at("P1_L2") == "Station A"
    assert position._station_at("P1_L2") == "Station A" and calls["rows"] == 1
    rows[0] = _pyro_row("Pyro I", "Station Z")
    ver["v"] = "station-test-b"
    assert position._station_at("P1_L2") == "Station Z" and calls["rows"] == 2
    position.reset_names()
    assert position._station_at("P1_L2") == "Station Z" and calls["rows"] == 3


def test_station_table_keeps_rows_before_error(monkeypatch):
    """扫到一半出错：这次用出错前扫到的、后面的当没有（以前从头找，出错前找到的照返回，之后的返回空）；
    出错的不缓存，下次重扫——出错可能是一时的，好了以后要用上整张表"""
    from astral_toolkit.navigation import position

    rows = [
        _pyro_row("Pyro I", "Station A"),
        _pyro_row("Pyro I", "Bad"),
        _pyro_row("Pyro II", "Station C"),
    ]
    bad = {"Bad"}
    calls = _fake_station_rows(monkeypatch, rows, bad)
    monkeypatch.setattr(position, "_data_version", lambda: "station-test-err")
    assert position._station_at("P1_L2") == "Station A"
    assert position._station_at("P2_L1") == "" and calls["rows"] == 2
    bad.clear()
    assert position._station_at("P2_L1") == "Station C" and calls["rows"] == 3
    assert position._station_at("P1_L2") == "Station A" and calls["rows"] == 3


# ---------------------------------------------------------------- Task 5：矿价和更新边界


def _fake_data_module():
    import types

    m = types.SimpleNamespace()
    m.CITY_PRICES = {"Aluminum": {"Area18": 1, "Lorville": 2}}
    m.REFINERIES = {"ARC-L1": ("弧 L1", {})}
    return m


def test_apply_live_reads_gamedata(monkeypatch, tmp_path):
    import json

    import astral_toolkit.gamedata as G
    from astral_toolkit.update import uex

    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(uex, "OUT", tmp_path / "prices.json")
    G.ensure()
    # 库建好后再改 prices.json、不重建：读到的还是库里的（证明矿价和加成都不再直接读 JSON）
    (tmp_path / "prices.json").write_text(
        json.dumps(
            {
                "prices": {"Aluminum": {"Area18": 9999}},
                "yields": {"ARC-L1": {"Aluminum": 5}},
            }
        ),
        encoding="utf-8",
    )
    m = _fake_data_module()
    assert uex.apply_live(m) is True
    assert m.CITY_PRICES["Aluminum"] == {"Area18": 3800, "Lorville": 3000}
    assert type(m.CITY_PRICES["Aluminum"]["Area18"]) is int  # 和以前读 JSON 一样是整数
    assert m.REFINERIES["ARC-L1"] == (
        "弧 L1",
        {},
    )  # 最小源的 prices.json 没有这个站的加成


def test_apply_live_zero_price_keeps_builtin(monkeypatch, tmp_path):
    from astral_toolkit.update import uex

    _setup(
        monkeypatch,
        tmp_path,
        **{"prices.json": {"prices": {"Aluminum": {"Area18": 0, "Lorville": 3100}}}},
    )
    monkeypatch.setattr(uex, "OUT", tmp_path / "prices.json")
    m = _fake_data_module()
    uex.apply_live(m)
    assert m.CITY_PRICES["Aluminum"] == {
        "Area18": 1,
        "Lorville": 3100,
    }  # 0 价不盖内置价


def test_apply_live_false_when_no_prices_file(monkeypatch, tmp_path):
    from astral_toolkit.update import uex

    _setup(monkeypatch, tmp_path)
    (tmp_path / "prices.json").unlink()
    monkeypatch.setattr(uex, "OUT", tmp_path / "prices.json")
    m = _fake_data_module()
    assert uex.apply_live(m) is False
    assert m.CITY_PRICES["Aluminum"] == {"Area18": 1, "Lorville": 2}


def _count_updating(monkeypatch):
    """把 gamedata.updating 换成计数器；返回 (计数, 写文件时是不是在边界里)"""
    from contextlib import contextmanager

    import astral_toolkit.gamedata as G
    from astral_toolkit.core import paths

    state = {"n": 0, "inside": False, "writes": []}

    @contextmanager
    def fake():
        state["n"] += 1
        state["inside"] = True
        try:
            yield
        finally:
            state["inside"] = False

    monkeypatch.setattr(G, "updating", fake)
    monkeypatch.setattr(
        paths,
        "write_json",
        lambda p, obj, **kw: state["writes"].append((p, state["inside"])),
    )
    return state


def test_refresh_runs_inside_updating(monkeypatch, tmp_path):
    from astral_toolkit.update import uex

    _setup(monkeypatch, tmp_path)
    state = _count_updating(monkeypatch)
    monkeypatch.setattr(uex, "_get", lambda endpoint: [])
    monkeypatch.setattr(uex, "OUT", tmp_path / "prices.json")
    uex.refresh()
    assert state["n"] == 1 and len(state["writes"]) == 1 and state["writes"][0][1]


def test_shops_update_runs_inside_updating(monkeypatch, tmp_path):
    from astral_toolkit.crafting import shops

    _setup(monkeypatch, tmp_path)
    state = _count_updating(monkeypatch)

    def fake_get(path, params=None):
        if path == "categories":
            return [{"id": 1, "type": "item", "name": "Arms", "section": "S"}]
        return [
            {
                "id_item": 5,
                "item_name": "Gun",
                "id_category": 1,
                "price_buy": 10,
                "terminal_name": "T",
            }
        ]

    monkeypatch.setattr(shops, "_get", fake_get)
    shops.update(progress=None)
    assert state["n"] == 1 and len(state["writes"]) == 1 and state["writes"][0][1]


# ---------------------------------------------------------------- Task 2 补：商店物品目录；Task 3：商店查询改走数据层

_F2 = ["Pyro", "Pyro I", "", "", "", "W"]


def _shop_setup(monkeypatch, tmp_path):
    from astral_toolkit.crafting import shops

    rows = [
        [171, "Shop D", "Stanton · D", 500.0, 0.0, "4.10", _F2],
        [171, "Shop E", "Stanton · E", 0.0, 400.0, "4.10", _F2],
        [200, "Shop C2", "Pyro · Z", 900.0, 0.0, "4.10", _F2],
        [200, "Shop W", "Pyro · W", 1100.0, 0.0, "4.10", _F2],
    ]
    _setup(monkeypatch, tmp_path, **_shops_with_rows(*rows))
    import astral_toolkit.gamedata as G

    G.ensure()
    # 库建好后删掉源 JSON，模块里 import 时绑好的 CACHE 也指到删掉的那个：查询只能从库读（CL-C4 删了 shops.load）
    for p in tmp_path.glob("*.json"):
        p.unlink()
    monkeypatch.setattr(shops, "CACHE", tmp_path / "shops.json")
    return shops


def test_item_record_reads_from_db(monkeypatch, tmp_path):
    """商店里这件的 [英文名, 类别] 从库里读（源 JSON 删了照样有），字符串编号也认；没有的给 None（CL-C4）"""
    shops = _shop_setup(monkeypatch, tmp_path)
    assert shops.item_record(171) == ["Venture Arms", "Arms"]
    assert shops.item_record("200") == ["Lawson Mining Laser", "Mining"]
    assert shops.item_record(999) is None


def test_catalog_verbatim_and_folded(monkeypatch, tmp_path):
    from astral_toolkit.crafting.shops import _fold
    from astral_toolkit.gamedata import shops as gs

    _setup(monkeypatch, tmp_path)
    c = gs.catalog()
    assert [(x.uex_item_id, x.en, x.cat) for x in c] == [
        (171, "Venture Arms", "Arms"),
        (200, "Lawson Mining Laser", "Mining"),
        (201, "Lawson Mining Laser", "Mining"),
    ]
    assert c[1].folded == _fold("Lawson Mining Laser") and gs.catalog() is c


def test_find_exact_before_partial_and_limit(monkeypatch, tmp_path):
    shops = _shop_setup(monkeypatch, tmp_path)
    assert shops.find("Lawson") == [
        (200, "Lawson Mining Laser", "Mining"),
        (201, "Lawson Mining Laser", "Mining"),
    ]
    assert len(shops.find("arms", limit=1)) == 1
    assert shops.find("") == [] and shops.find("zzz") == []


def test_find_keeps_source_order_for_duplicate_names(monkeypatch, tmp_path):
    shops = _shop_setup(monkeypatch, tmp_path)
    assert [r[0] for r in shops.find("Lawson Mining Laser")] == [200, 201]


def test_find_close_still_folds_l_to_i(monkeypatch, tmp_path):
    shops = _shop_setup(monkeypatch, tmp_path)
    assert shops.find_close("Lawson Mining Iaser") == (
        200,
        "Lawson Mining Laser",
        "Mining",
    )
    assert shops.find_close("abc") is None


def test_where_sorts_buy_asc_sell_desc(monkeypatch, tmp_path):
    shops = _shop_setup(monkeypatch, tmp_path)
    buy, sell = shops.where(171)
    assert buy == [(500.0, "Shop D", "Stanton · D"), (586.0, "Shop A", "Stanton · X")]
    assert sell == [(400.0, "Shop E", "Stanton · E"), (300.0, "Shop B", "Stanton · Y")]
    assert shops.where("171") == ([], []) and shops.where(None) == (
        [],
        [],
    )  # 以前按 == 比，字符串对不上
    assert "500 aUEC｜Shop D" in shops.where_text(171)


def test_nearest_dedups_place(monkeypatch, tmp_path):
    from astral_toolkit.navigation import position

    shops = _shop_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(shops, "shop_point", lambda f: {"i": f[5]})
    monkeypatch.setattr(
        position, "distance", lambda a, b: {"W": 10.0, "New Babbage": 20.0}[b["i"]]
    )
    near = shops.nearest(200, {"x": 0}, 3)
    assert near == [
        (10.0, 900.0, "Shop C2", "Pyro · Z"),
        (10.0, 1100.0, "Shop W", "Pyro · W"),
    ]  # 同一地点只留最便宜的
    assert shops.nearest(200, None, 1) == [(float("inf"), 900.0, "Shop C2", "Pyro · Z")]


def test_buyable(monkeypatch, tmp_path):
    shops = _shop_setup(monkeypatch, tmp_path)
    assert shops.buyable(171) and shops.buyable(200)
    assert (
        not shops.buyable(201) and not shops.buyable("171") and not shops.buyable(None)
    )


def test_variants_prefers_buyable(monkeypatch, tmp_path):
    shops = _shop_setup(monkeypatch, tmp_path)
    assert shops.variants('Lawson Mining Laser "Red"') == [
        (200, "Lawson Mining Laser", "Mining")
    ]


def test_where_by_name_first_buyable(monkeypatch, tmp_path):
    shops = _shop_setup(monkeypatch, tmp_path)
    assert (
        shops.where_by_name("Lawson Mining Laser")
        == "可买：Shop C2（Pyro · Z）900 aUEC"
    )
    assert shops.where_by_name("nothing") == ""


# ---------------------------------------------------------------- Task 6：物品搜索索引改从数据层建


def _legacy_build(monkeypatch, tmp_path):
    """迁移前 itemsearch._build_locked() 的合并规则（只在测试里留一份，对照用）：直接读最小源 JSON"""
    import json

    from astral_toolkit.catalog.search import (
        has_cjk as _has_cjk,
        trigrams as _trigrams,
        variant as _variant,
        wiki_noise as _wiki_noise,
    )
    from astral_toolkit.contracts.textkeys import en_key, zh_key
    from astral_toolkit.core.i18n import gear_zh_of_item
    from astral_toolkit.gamedata._import import _names_table
    from astral_toolkit.gamedata._sources import read_sources

    src = read_sources(tmp_path)
    data = json.loads((tmp_path / "shops.json").read_text(encoding="utf-8"))
    idx = json.loads((tmp_path / "loot_index.json").read_text(encoding="utf-8"))
    table = _names_table(src)
    wiki = json.loads((tmp_path / "wiki_items.json").read_text(encoding="utf-8"))[
        "items"
    ]
    aliases = json.loads((tmp_path / "name_aliases.json").read_text(encoding="utf-8"))
    by_en, rows = {}, []

    def entry(en):
        ek = en_key(en)
        if not ek:
            return None
        e = by_en.get(ek)
        if e is None:
            e = by_en[ek] = {
                "en": en.replace("\xa0", " "),
                "ek": ek,
                "zh": "",
                "zh_loot": "",
                "zks": set(),
                "shop": None,
                "cat": "",
                "loot": False,
                "loc": False,
            }
            rows.append(e)
        return e

    for iid, (en, cat) in data["items"].items():
        e = entry(en)
        if e and e["shop"] is None:
            e["shop"], e["cat"] = int(iid), cat or ""
    for r in idx["rows"]:
        en, zh = r[1], r[5] or ""
        if _has_cjk(en) and not _has_cjk(zh):
            en, zh = zh or en, en
        if not _has_cjk(zh):
            zh = ""
        e = entry(en)
        if e:
            e["loot"] = True
            if zh:
                e["zh_loot"] = e["zh_loot"] or zh
                e["zks"].add(zh_key(zh))
    for zh, en in table.items():
        e = entry(en)
        if e:
            e["loc"] = True
            e["zh"] = e["zh"] or zh
            e["zks"].add(zh_key(zh))
    for w in wiki:
        e = entry(w["n"])
        if e:
            e.setdefault("wiki", True)
            e["wtype"], e["wsize"], e["desc"] = (
                w.get("t") or "",
                w.get("s"),
                w.get("d") or "",
            )
    for old, real in aliases.items():
        e = by_en.get(en_key(real))
        if e and en_key(old) not in by_en:
            e.setdefault("aka", []).append(old)
    taken = {k for e in rows if e["shop"] is not None or e["loot"] for k in e["zks"]}
    rows = [
        e for e in rows if e["shop"] is not None or e["loot"] or not (e["zks"] & taken)
    ]
    rows = [
        e
        for e in rows
        if e["shop"] is not None or e["loot"] or e["loc"] or not _wiki_noise(e)
    ]
    by_en = {e["ek"]: e for e in rows}
    for e in rows:
        for old in e.get("aka") or []:
            by_en.setdefault(en_key(old), e)
    by_char, by_tri = {}, {}
    for i, e in enumerate(rows):
        e["zh"] = e["zh"] or e["zh_loot"]
        gz = gear_zh_of_item(e["en"])
        if gz:
            e["zh"] = gz
            e["zks"] = tuple(dict.fromkeys((*e["zks"], zh_key(gz))))
        e["zks"] = tuple(k for k in e["zks"] if k)
        e["zlen"] = min((len(k) for k in e["zks"]), default=99)
        e["variant"] = _variant(e["en"], e["zh"])
        e["has_data"] = e["shop"] is not None or e["loot"]
        for c in set("".join(e["zks"])):
            by_char.setdefault(c, set()).add(i)
        for t in _trigrams(e["ek"]):
            by_tri.setdefault(t, set()).add(i)
        for old in e.get("aka") or []:
            for t in _trigrams(en_key(old)):
                by_tri.setdefault(t, set()).add(i)
    return {"rows": rows, "by_char": by_char, "by_tri": by_tri, "by_en": by_en}


def _fresh_search(monkeypatch):
    from astral_toolkit.crafting import itemsearch as IS

    monkeypatch.setattr(IS, "_cache", _VC())
    return IS


_QUERIES = [
    "医疗笔",
    "Medpen",
    "Medi Pen",
    "Lawson",
    "荣誉勋章",
    "Venture",
    "夹克",
    "xyz",
    "law min",
]


def test_itemsearch_find_matches_json_build_on_sample(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    IS = _fresh_search(monkeypatch)
    new = [IS.find(q) for q in _QUERIES]
    new_rows = [dict(e, zks=sorted(e["zks"])) for e in (IS._build() or {})["rows"]]
    legacy = _legacy_build(monkeypatch, tmp_path)
    monkeypatch.setattr(IS, "_build", lambda: legacy)
    assert new_rows == [dict(e, zks=sorted(e["zks"])) for e in legacy["rows"]]
    assert [IS.find(q) for q in _QUERIES] == new
    assert any(new)  # 不是全空的比对


def test_itemsearch_cache_keyed_by_version(monkeypatch, tmp_path):
    import json

    import astral_toolkit.gamedata as G

    _setup(monkeypatch, tmp_path)
    IS = _fresh_search(monkeypatch)
    first = IS._build()
    G.rebuild(force=True)  # 新一代、内容版本不变：不重建索引
    assert IS._build() is first
    # 只改 name_aliases.json（以前缓存键漏了它，改了不刷新）
    (tmp_path / "name_aliases.json").write_text(
        json.dumps({"Medi Pen": "Medpen", "MedPack X": "Medpen"}), encoding="utf-8"
    )
    G.rebuild()
    second = IS._build()
    assert second is not first and IS.lookup("MedPack X")["ek"] == "medpen"


def test_query_during_rebuild_sees_old_or_new_never_error(monkeypatch, tmp_path):
    import threading

    import astral_toolkit.gamedata as G

    _setup(monkeypatch, tmp_path)
    IS = _fresh_search(monkeypatch)
    IS._build()
    errors, empty = [], []

    from astral_toolkit.crafting import shops

    def worker():
        for _ in range(200):
            try:
                if not IS.find("Medpen"):
                    empty.append(1)
                if (
                    not shops.find("Lawson") or not shops.where(200)[0]
                ):  # F8 实际走的是 shops
                    empty.append(1)
            except Exception as e:  # noqa: BLE001 —— 测试要看到任何异常
                errors.append(e)

    th = threading.Thread(target=worker)
    th.start()
    G.rebuild(force=True)
    G.rebuild(force=True)
    th.join(60)
    assert not errors and not empty


def test_itemsearch_does_not_read_json(monkeypatch, tmp_path):
    import astral_toolkit.gamedata as G

    _setup(monkeypatch, tmp_path)
    G.ensure()
    for p in tmp_path.glob("*.json"):  # 库建好后把源 JSON 全删掉：索引只从库建
        p.unlink()
    IS = _fresh_search(monkeypatch)
    assert IS.lookup("Medpen")["zh"] == "医疗笔"


def test_itemsearch_empty_when_db_unavailable(monkeypatch, tmp_path):
    from astral_toolkit.core import paths

    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(
        paths, "DATA", tmp_path / "empty"
    )  # 建不出库：和以前没有数据一样搜不到，不报错
    IS = _fresh_search(monkeypatch)
    assert IS.find("Medpen") == [] and IS.lookup("Medpen") is None


# ---------------------------------------------------------------- 审查 2026-11-02 整改


def test_ensure_rebuilds_stale_db(monkeypatch, tmp_path):
    """升级时安装包换了源文件（不经过 updating()）：进程里第一次查询前要按源核对，别用旧库"""
    import json

    import astral_toolkit.gamedata as G
    from astral_toolkit.gamedata import _ready, prices

    _setup(monkeypatch, tmp_path)
    G.ensure()
    (tmp_path / "prices.json").write_text(
        json.dumps({"prices": {"Aluminum": {"Area18": 987654}}}), encoding="utf-8"
    )
    monkeypatch.setattr(_ready, "_state", {"done": None, "failed": None})  # 新进程
    assert prices.city_prices()["Aluminum"]["Area18"] == 987654.0


def test_ensure_rebuilds_old_schema(monkeypatch, tmp_path):
    """清单还是旧表结构（从旧版升级上来）：重建，不拿旧库去查新表"""
    import json

    import astral_toolkit.gamedata as G
    from astral_toolkit.gamedata import _ready, shops
    from astral_toolkit.gamedata._paths import manifest_path

    _setup(monkeypatch, tmp_path)
    G.ensure()
    m = json.loads(manifest_path().read_text(encoding="utf-8"))
    m["schema_version"] = 2
    manifest_path().write_text(json.dumps(m), encoding="utf-8")
    monkeypatch.setattr(_ready, "_state", {"done": None, "failed": None})
    assert len(shops.catalog()) == 3
    assert (
        json.loads(manifest_path().read_text(encoding="utf-8"))["generation_id"]
        != m["generation_id"]
    )


def test_apply_live_db_unavailable_keeps_builtin(monkeypatch, tmp_path):
    """库建不出来（shops.json 坏了）：不覆盖内置表，也不再退回读 prices.json"""
    from astral_toolkit.update import uex

    _setup(monkeypatch, tmp_path)
    (tmp_path / "shops.json").write_text("{坏", encoding="utf-8")
    monkeypatch.setattr(uex, "OUT", tmp_path / "prices.json")
    m = _fake_data_module()
    assert uex.apply_live(m) is False
    assert m.CITY_PRICES["Aluminum"] == {"Area18": 1, "Lorville": 2}
    assert m.REFINERIES["ARC-L1"] == ("弧 L1", {})


def test_query_while_new_content_is_published(monkeypatch, tmp_path):
    """边搜边发布内容不同的新库（索引也跟着重建）：不报错、结果不空"""
    import json
    import threading

    import astral_toolkit.gamedata as G

    _setup(monkeypatch, tmp_path)
    IS = _fresh_search(monkeypatch)
    IS._build()
    errors, empty, stop = [], [], threading.Event()

    def worker():
        while not stop.is_set():
            try:
                if not IS.find("Medpen"):
                    empty.append(1)
            except Exception as e:  # noqa: BLE001 —— 测试要看到任何异常
                errors.append(e)

    th = threading.Thread(target=worker)
    th.start()
    try:
        for n in range(4):
            (tmp_path / "name_aliases.json").write_text(
                json.dumps({f"Med Alias {n}": "Medpen"}), encoding="utf-8"
            )
            G.rebuild()
            assert (IS.lookup(f"Med Alias {n}") or {}).get("ek") == "medpen"
    finally:
        stop.set()
        th.join(60)
    assert not errors and not empty
