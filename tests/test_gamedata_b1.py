"""游戏数据层批 1：就绪等待、items / shops / prices 查询主题，以及商店 / 物品搜索 / 库存地点 / 矿价改走数据层

全部用 tmp_path 当 data/ 根（monkeypatch paths.DATA），不读真实 data/、不写 userdata/。"""

from tests.test_gamedata import _write_min_sources


def _setup(monkeypatch, tmp_path, **override):
    """tmp_path 当 data/ 根、写最小源；就绪标记和后台线程记录换成新的（每个测试一个新库目录）"""
    import sc_mining.gamedata as G
    from sc_mining.core import paths
    from sc_mining.gamedata import _ready

    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(_ready, "_state", {"done": None})
    monkeypatch.setattr(G, "_state", {"last_error": None, "warm_thread": None})
    _write_min_sources(tmp_path, **override)
    return tmp_path


# ---------------------------------------------------------------- Task 1：首次查询前的就绪等待


def test_ensure_builds_when_missing(monkeypatch, tmp_path):
    import sc_mining.gamedata as G
    from sc_mining.gamedata._manifest import read_manifest

    _setup(monkeypatch, tmp_path)
    assert read_manifest() is None
    G.ensure()
    assert read_manifest() is not None
    with G.snapshot() as s:
        assert s.execute("select count(*) from shop_rows")[0][0] == 3


def test_ensure_waits_for_warm_up(monkeypatch, tmp_path):
    import sc_mining.gamedata as G
    from sc_mining.gamedata._manifest import read_manifest

    _setup(monkeypatch, tmp_path)
    t = G.warm_up()
    G.ensure()
    t.join(10)
    assert read_manifest() is not None
    assert len(list((tmp_path / "gamedata").glob("gamedata-*.db"))) == 1  # 只建了一代


def test_ensure_raises_when_no_sources(monkeypatch, tmp_path):
    import sc_mining.gamedata as G
    from sc_mining.core import paths
    from sc_mining.gamedata import _ready
    from tests.minipytest import raises

    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(paths, "DATA", tmp_path / "empty")  # 没有 shops.json：建不出库
    with raises(G.BuildError):
        G.ensure()
    assert _ready._state["done"] != str(
        tmp_path / "empty" / "gamedata"
    )  # 建失败不能记成已就绪


def test_ensure_fast_path_after_first_success(monkeypatch, tmp_path):
    import sc_mining.gamedata as G
    from sc_mining.gamedata import _build

    _setup(monkeypatch, tmp_path)
    G.ensure()
    calls = []
    monkeypatch.setattr(_build, "_db_usable", lambda m: calls.append(m) or True)
    G.ensure()
    assert calls == []  # 确认过一次就不再每次查询都开库校验


# ---------------------------------------------------------------- Task 2：items / shops / prices 查询主题


def test_items_get_all_and_order(monkeypatch, tmp_path):
    from sc_mining.gamedata import items

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
    from sc_mining.gamedata import items

    _setup(monkeypatch, tmp_path)
    c = items.candidates()
    med = next(x for x in c if x.item_id == "medpen")
    assert med.aliases == ("Medi Pen",)
    assert not any(
        "Venture Arms" in x.aliases for x in c
    )  # 已经是另一件物品的旧写法不登记
    assert items.candidates() is c  # 同一版本缓存


def test_items_names_and_zh_keys(monkeypatch, tmp_path):
    from sc_mining.crafting.itemsearch import zh_key
    from sc_mining.gamedata import items

    _setup(monkeypatch, tmp_path)
    kinds = [k for k, _n, _m in items.names_of("medpen")]
    assert kinds[0] == "en" and "zh_loot" in kinds and "aka" in kinds
    zk = items.zh_keys_of_all()
    assert zk["medpen"] == (zh_key("医疗笔"),)
    assert "venturearms" not in zk


def test_items_by_name_and_source_id(monkeypatch, tmp_path):
    from sc_mining.gamedata import items

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
    from sc_mining.gamedata import items

    _setup(monkeypatch, tmp_path)
    hits = items.search("law")
    assert [r.en for r in hits] == ["Lawson Mining Laser"]
    assert {r.item_id for r in items.search("医疗")} == {"medpen"}
    assert len(items.search("e", limit=1)) == 1
    assert len(items.search("e", limit=None)) > 1
    assert items.search("%") == () and items.search("") == ()  # 通配符按字面找


def test_shops_rows_buyable_places(monkeypatch, tmp_path):
    from sc_mining.gamedata import shops

    _setup(monkeypatch, tmp_path)
    rows = shops.rows_for_item(171)
    assert [r.shop_name for r in rows] == ["Shop A", "Shop B"]
    assert rows[0].price_buy == 586.0 and rows[0].fields[5] == "New Babbage"
    assert shops.buyable(171) and shops.buyable(200) and not shops.buyable(201)
    assert len(shops.place_fields()) == 3  # 不去重


def test_shops_lagrange_rows(monkeypatch, tmp_path):
    from sc_mining.gamedata import shops
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
    from sc_mining.gamedata import prices

    _setup(monkeypatch, tmp_path)
    cp = prices.city_prices()
    assert cp["Aluminum"]["Lorville"] == 3000.0 and list(cp["Aluminum"]) == [
        "Area18",
        "Lorville",
    ]
    assert prices.has_live()
    _setup(monkeypatch, tmp_path / "np", **{"prices.json": {"prices": {}}})
    assert prices.city_prices() == {} and not prices.has_live()


def test_topic_calls_share_outer_snapshot(monkeypatch, tmp_path):
    import sc_mining.gamedata as G
    from sc_mining.gamedata import items, shops
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
    from sc_mining.crafting import stockplaces as SP

    _setup(monkeypatch, tmp_path)
    assert SP._raw_places() == [
        ("Stanton", "MicroTech", "", "New Babbage", True)
    ]  # 3 行同一地点 → 1 个


def test_raw_places_fallback_when_no_db(monkeypatch, tmp_path):
    from sc_mining.core import paths
    from sc_mining.crafting import stockplaces as SP

    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(paths, "DATA", tmp_path / "empty")  # 建不出库：保底列表
    assert SP._raw_places() == list(SP._FALLBACK)


def test_places_refresh_after_version_change(monkeypatch, tmp_path):
    import sc_mining.gamedata as G
    from sc_mining.crafting import stockplaces as SP

    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(SP, "_PLACES", {"ver": None, "list": None})
    monkeypatch.setattr(SP, "_INDEX", {"of": None, "idx": None})
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


def test_places_cache_clear_still_works(monkeypatch, tmp_path):
    from sc_mining.crafting import stockplaces as SP
    from sc_mining.update.data_pack import clear_caches

    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(SP, "_PLACES", {"ver": None, "list": None})
    monkeypatch.setattr(SP, "_INDEX", {"of": None, "idx": None})
    first = SP.places()
    clear_caches()  # 汉化包换了：data_pack 按名字清 places / _index
    assert SP.places() is not first


def test_station_at_uses_lagrange_rows(monkeypatch, tmp_path):
    from sc_mining.crafting import shops
    from sc_mining.navigation import position

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
        shops,
        "load",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该读 JSON")),
    )
    monkeypatch.setattr(
        shops, "shop_point", lambda f: {"i": "ARC_L1"} if f[4] == "Station X" else None
    )
    assert position._station_at("ARC_L1") == "Station X"
    assert position._station_at("ARC_L2") == ""


# ---------------------------------------------------------------- Task 5：矿价和更新边界


def _fake_data_module():
    import types

    m = types.SimpleNamespace()
    m.CITY_PRICES = {"Aluminum": {"Area18": 1, "Lorville": 2}}
    m.REFINERIES = {"ARC-L1": ("弧 L1", {})}
    return m


def test_apply_live_reads_gamedata(monkeypatch, tmp_path):
    import json

    import sc_mining.gamedata as G
    from sc_mining.update import uex

    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(uex, "OUT", tmp_path / "prices.json")
    G.ensure()
    # 库建好后再改 prices.json 的矿价、不重建：读到的还是库里的（证明矿价不再直接读 JSON）
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
        {"Aluminum": 5},
    )  # 精炼站加成照旧读 prices.json


def test_apply_live_zero_price_keeps_builtin(monkeypatch, tmp_path):
    from sc_mining.update import uex

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
    from sc_mining.update import uex

    _setup(monkeypatch, tmp_path)
    (tmp_path / "prices.json").unlink()
    monkeypatch.setattr(uex, "OUT", tmp_path / "prices.json")
    m = _fake_data_module()
    assert uex.apply_live(m) is False
    assert m.CITY_PRICES["Aluminum"] == {"Area18": 1, "Lorville": 2}


def _count_updating(monkeypatch):
    """把 gamedata.updating 换成计数器；返回 (计数, 写文件时是不是在边界里)"""
    from contextlib import contextmanager

    import sc_mining.gamedata as G
    from sc_mining.core import paths

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
    from sc_mining.update import uex

    _setup(monkeypatch, tmp_path)
    state = _count_updating(monkeypatch)
    monkeypatch.setattr(uex, "_get", lambda endpoint: [])
    monkeypatch.setattr(uex, "OUT", tmp_path / "prices.json")
    uex.refresh()
    assert state["n"] == 1 and len(state["writes"]) == 1 and state["writes"][0][1]


def test_shops_update_runs_inside_updating(monkeypatch, tmp_path):
    from sc_mining.crafting import shops

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
    monkeypatch.setattr(shops, "_data", None)
    shops.update(progress=None)
    assert state["n"] == 1 and len(state["writes"]) == 1 and state["writes"][0][1]


# ---------------------------------------------------------------- Task 2 补：商店物品目录；Task 3：商店查询改走数据层

_F2 = ["Pyro", "Pyro I", "", "", "", "W"]


def _shop_setup(monkeypatch, tmp_path):
    from sc_mining.crafting import shops

    rows = [
        [171, "Shop D", "Stanton · D", 500.0, 0.0, "4.10", _F2],
        [171, "Shop E", "Stanton · E", 0.0, 400.0, "4.10", _F2],
        [200, "Shop C2", "Pyro · Z", 900.0, 0.0, "4.10", _F2],
        [200, "Shop W", "Pyro · W", 1100.0, 0.0, "4.10", _F2],
    ]
    _setup(monkeypatch, tmp_path, **_shops_with_rows(*rows))
    # 查询路径一律不许再读 shops.json（load 只留给更新流程）
    monkeypatch.setattr(
        shops,
        "load",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("查询读了 JSON")),
    )
    return shops


def test_catalog_verbatim_and_folded(monkeypatch, tmp_path):
    from sc_mining.crafting.shops import _fold
    from sc_mining.gamedata import shops as gs

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
    from sc_mining.navigation import position

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
