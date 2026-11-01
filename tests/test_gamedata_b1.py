"""游戏数据层批 1：就绪等待、items / shops / prices 查询主题，以及商店 / 物品搜索 / 库存地点 / 矿价改走数据层

全部用 tmp_path 当 data/ 根（monkeypatch paths.DATA），不读真实 data/、不写 userdata/。"""

from tests.test_gamedata import _write_min_sources


def _setup(monkeypatch, tmp_path, **override):
    """tmp_path 当 data/ 根、写最小源；就绪标记和后台线程记录换成新的（每个测试一个新库目录）"""
    import sc_mining.gamedata as G
    from sc_mining.core import paths
    from sc_mining.gamedata import _ready

    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(_ready, "_state", {"done": False})
    monkeypatch.setattr(G, "_state", {"last_error": None, "warm_thread": None})
    if override is not None:
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
