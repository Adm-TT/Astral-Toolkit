"""把 data/ 里的 JSON 建成游戏数据库 data/gamedata/gamedata-<代号>.db 并切换当前版本清单

用法（在项目根目录）：.venv\\Scripts\\python.exe -X utf8 tools\\build_gamedata.py [--force] [--check] [--data <目录>]
  不带参数：源没变就不重建，打印当前清单
  --force   强制重建一代
  --check   只检查：清单、库文件、完整性、meta 对照；有问题退出码 2
  --data    临时指定 data/ 目录（开发用）
只是命令行壳，建库逻辑全在 sc_mining/gamedata/_build.py，程序运行时也调同一份。"""

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _check() -> int:
    from sc_mining.gamedata import GamedataError
    from sc_mining.gamedata._manifest import read_manifest
    from sc_mining.gamedata._paths import db_path

    try:
        m = read_manifest()
    except GamedataError as e:
        print(f"清单坏了：{e}")
        return 2
    if m is None:
        print("还没有游戏数据库（没有清单）")
        return 2
    p = db_path(m.generation_id)
    if not p.exists():
        print(f"清单指向的库不存在：{p}")
        return 2
    try:
        c = sqlite3.connect(f"{p.as_uri()}?mode=ro", uri=True)
        try:
            ok = c.execute("PRAGMA quick_check").fetchone()
            meta = dict(c.execute("select key, value from meta"))
        finally:
            c.close()
    except sqlite3.Error as e:
        print(f"库打不开或已损坏：{e}")
        return 2
    if not ok or ok[0] != "ok":
        print(f"完整性检查不过：{ok}")
        return 2
    bad = [
        k
        for k, v in (
            ("generation_id", m.generation_id),
            ("data_version", m.data_version),
            ("schema_version", str(m.schema_version)),
        )
        if meta.get(k) != v
    ]
    if bad:
        print(f"清单和库里的 meta 对不上：{bad}")
        return 2
    print(f"正常：{m.file}  内容版本 {m.data_version}  schema {m.schema_version}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="建游戏数据库 / 检查游戏数据库")
    ap.add_argument("--force", action="store_true", help="强制重建")
    ap.add_argument("--check", action="store_true", help="只检查不建")
    ap.add_argument("--data", help="临时指定 data/ 目录")
    a = ap.parse_args(argv)
    if a.data:
        from sc_mining.core import paths

        paths.DATA = Path(a.data)
    if a.check:
        return _check()
    from sc_mining.gamedata import GamedataError, rebuild

    try:
        m = rebuild(force=a.force)
    except GamedataError as e:
        print(f"建库失败：{e}")
        return 1
    print(f"当前：{m.file}  内容版本 {m.data_version}  schema {m.schema_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
