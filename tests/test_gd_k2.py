"""游戏数据层收口 2（GD-K2）：死代码 / 空 cache 门面清掉后，换代仍靠库版本，clear_caches 活枝可调用

全部用 tmp_path 当 data/ 根，不读真实 data/、不写 userdata/。"""

from tests.test_gamedata_b1 import _setup
from tests.test_gamedata import _write_min_sources


def test_folded_and_rocks_gone():
    from sc_mining.crafting import loot
    from sc_mining.mining import mining_area as M

    assert not hasattr(loot, "_folded")
    assert not hasattr(M, "_ROCKS")


def test_names_no_cache_clear_facade(monkeypatch, tmp_path):
    from sc_mining.trade import names

    _setup(monkeypatch, tmp_path)
    assert not hasattr(names.table, "cache_clear")
    assert not hasattr(names._index, "cache_clear")
    assert isinstance(names.table(), dict)
    assert isinstance(names._index(), tuple) and len(names._index()) == 2


def test_clear_caches_keeps_live_branches(monkeypatch, tmp_path):
    """保留理由表里的活枝：调 clear_caches 不炸；旁路索引 / 商店内存可被清掉"""
    from sc_mining.crafting import loot, shops
    from sc_mining.update import data_pack, uex

    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(uex, "apply_live", lambda *a, **k: None)
    shops.load(auto_update=False)
    assert shops._data is not None
    loot._index = {"version": "x", "rows": []}
    data_pack.clear_caches()
    assert loot._index is None
    assert shops._data is None


def test_loot_and_names_refresh_without_clear_caches(monkeypatch, tmp_path):
    """已迁路径：rebuild 后不调 clear_caches 也换代"""
    import sc_mining.gamedata as G
    from sc_mining.crafting import loot
    from sc_mining.trade import names

    _setup(
        monkeypatch,
        tmp_path,
        **{
            "loot_index.json": {
                "version": "t",
                "rows": [["u1", "Old Knife", "cls_a", "common", 1, "旧刀"]],
            },
            "zh_names.json": {"旧刀": "Old Knife"},
            "zh_only_names.json": {},
        },
    )
    assert [h[0] for h in loot.find("Old Knife")] == ["u1"]
    t0 = names.table()
    _write_min_sources(
        tmp_path,
        **{
            "loot_index.json": {
                "version": "t2",
                "rows": [
                    ["u1", "Old Knife", "cls_a", "common", 1, "旧刀"],
                    ["u2", "New Knife", "cls_b", "common", 1, "新刀"],
                ],
            },
            "zh_names.json": {"旧刀": "Old Knife", "新刀": "New Knife"},
            "zh_only_names.json": {},
        },
    )
    G.rebuild()
    assert [h[0] for h in loot.find("New Knife")] == ["u2"]
    assert names.table() is not t0 and names.table().get("新刀") == "New Knife"


def test_mining_spots_stamp_len_two(monkeypatch, tmp_path):
    """缓存键只有 gamedata.version + 星图对象 id，不再叠 rocks_stamp"""
    import sc_mining.gamedata as G
    from sc_mining.navigation import navigate

    _setup(
        monkeypatch,
        tmp_path,
        **{
            "mining_spots.json": [
                {
                    "id": "s1",
                    "en": "Spot1",
                    "zh": "点1",
                    "sys": "Stanton",
                    "x": 0,
                    "y": 0,
                    "z": 0,
                    "kind": "",
                    "area": "",
                }
            ]
        },
    )
    G.ensure()
    monkeypatch.setattr(
        navigate, "load", lambda: (_ for _ in ()).throw(AssertionError("不该下星图"))
    )
    navigate._spots.clear()
    # data or load()：空 dict 是假值会走 load()；给非空壳
    data = {"bodies": {"_": None}, "pois": [], "points": []}
    a = navigate.mining_spots(data)
    b = navigate.mining_spots(data)
    assert a is b
    stamp = navigate._spots.get("stamp")
    assert stamp is not None and len(stamp) == 2
