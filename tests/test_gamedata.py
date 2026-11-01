"""游戏数据层地基（sc_mining/gamedata）：路径、类型、写锁、清单、表结构、快照、建库、入口

全部用 tmp_path 当 data/ 根（monkeypatch paths.DATA），不读真实 data/、不写 userdata/。"""

import dataclasses


def _data_root(monkeypatch, tmp_path):
    from sc_mining.core import paths

    monkeypatch.setattr(paths, "DATA", tmp_path)
    return tmp_path


# ---------------------------------------------------------------- Task 1：路径与类型


def test_paths_follow_data_root(monkeypatch, tmp_path):
    from sc_mining.gamedata import _paths

    _data_root(monkeypatch, tmp_path)
    assert _paths.gamedata_dir() == tmp_path / "gamedata"
    assert _paths.db_path("abc") == tmp_path / "gamedata" / "gamedata-abc.db"
    assert _paths.manifest_path().name == "current.json"
    assert _paths.tmp_dir() == tmp_path / "gamedata" / "tmp"
    assert _paths.lock_path() == tmp_path / "gamedata" / ".write.lock"


def test_types_are_frozen():
    from sc_mining.gamedata import ShopRow, Vec3
    from tests.minipytest import raises

    v = Vec3(1.0, 2.0, 3.0)
    with raises(dataclasses.FrozenInstanceError):
        v.x = 9  # type: ignore[misc]
    assert ShopRow.__dataclass_params__.frozen  # type: ignore[attr-defined]


def test_exceptions_hierarchy():
    from sc_mining.gamedata import BuildError, GamedataError, GamedataUnavailable

    assert issubclass(GamedataUnavailable, GamedataError)
    assert issubclass(BuildError, GamedataError)
