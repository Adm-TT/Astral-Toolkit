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
    monkeypatch.setattr(_ready, "_state", {"done": False})
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
    assert not _ready._state["done"]  # 建失败不能记成已就绪，下次还要再试


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
