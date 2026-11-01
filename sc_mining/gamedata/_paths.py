"""游戏数据库放哪：全部从 paths.DATA 派生，运行时取值（测试 monkeypatch paths.DATA 就能换根目录）

data/gamedata/current.json              当前版本清单
data/gamedata/gamedata-<代号>.db         已发布的库，发布后不再改
data/gamedata/tmp/                      建库临时文件
data/gamedata/.write.lock               跨进程写锁文件"""

from pathlib import Path


def gamedata_dir() -> Path:
    from ..core import paths

    return paths.DATA / "gamedata"


def manifest_path() -> Path:
    return gamedata_dir() / "current.json"


def tmp_dir() -> Path:
    return gamedata_dir() / "tmp"


def db_path(generation_id: str) -> Path:
    return gamedata_dir() / f"gamedata-{generation_id}.db"


def lock_path() -> Path:
    return gamedata_dir() / ".write.lock"
