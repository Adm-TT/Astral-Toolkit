"""老版本数据文件与目录结构迁移

- 处理 1.0.x Inno 安装版旧目录迁移（import_inno）
- 处理早期平铺在仓库根目录的旧文件搬迁至 data/ 与 userdata/（migrate）
- 启动时按需执行，解耦核心 paths.py
"""

from pathlib import Path
import shutil

from . import paths

# 已经合进主菜单的旧启动器、旧测试结果、合并掉的旧代码
def _get_delete_list():
    return (
        [
            paths.ROOT / n
            for n in (
                "1_安装.bat",
                "2_截图测试.bat",
                "3_实时读屏.bat",
                "4_找矿点.bat",
                "手动输入.bat",
                "刷新矿价.bat",
                "测试结果.txt",
                "test_result.txt",
            )
        ]
        + [
            paths.CODE / n
            for n in ("glossary_names.py", "signature.py", "sigscreen.py", "calibrate.py")
        ]
        + [paths.ROOT / "tests" / "test_core.py", paths.ROOT / "tests" / "trade"]
        + [paths.USER / "restart_request"]
    )

_SAMPLES = ["scan1.png", "sig1.png", "turret1.png", "pilot_fov.png", "inv_sample.png"]
_INNO_SKIP_DIRS = {"window", "updates", "shell"}
_INNO_SKIP_FILES = {"window_url.txt", "instance.lock", "install.log"}


def _get_moves():
    return [
        (paths.CODE / "starmap.json", paths.DATA / "starmap.json"),
        (paths.CODE / "shops.json", paths.DATA / "shops.json"),
        (paths.CODE / "loot_index.json", paths.DATA / "loot_index.json"),
        (paths.ROOT / "loot_cache", paths.DATA / "loot"),
        (paths.ROOT / "loc", paths.DATA / "loc"),
        (paths.CODE / "crafting.json", paths.DATA / "crafting.json"),
        (paths.CODE / "wikelo.json", paths.DATA / "wikelo.json"),
        (paths.CODE / "live_data.json", paths.DATA / "prices.json"),
        (paths.CODE / "places_zh.json", paths.DATA / "places_zh.json"),
        (paths.CODE / "trade" / "zh_names.json", paths.DATA / "zh_names.json"),
        (paths.ROOT / "settings.json", paths.USER / "settings.json"),
        (paths.ROOT / "waypoints.json", paths.USER / "waypoints.json"),
        (paths.ROOT / "last_position.json", paths.USER / "last_position.json"),
        (paths.ROOT / "overlay_pos.json", paths.USER / "overlay_pos.json"),
        (paths.CODE / "observations.csv", paths.USER / "observations.csv"),
        (paths.ROOT / "helpers_log.txt", paths.LOGS / "helpers_log.txt"),
        (paths.ROOT / "trade_log.txt", paths.LOGS / "trade_log.txt"),
        (paths.ROOT / "live_log.txt", paths.LOGS / "live_log.txt"),
        (paths.ROOT / "shots" / "hover", paths.SHOTS / "hover"),
        (paths.ROOT / "shots" / "live", paths.SHOTS / "live"),
    ]


# 兼容既有直接引用
_MOVES = _get_moves()
_DELETE = _get_delete_list()


def import_inno() -> int:
    """Velopack 版：老的 Inno 安装版（%LOCALAPPDATA%\\Programs\\AT\\userdata）还在、还没搬过，就复制过来
    （同名文件新的留着，不拿旧的盖）。搬完写标记，以后不再搬。返回复制了几个文件"""
    if (
        not paths.VELOPACK
        or not paths.INNO_USER
        or paths.MIGRATED.exists()
        or not paths.INNO_USER.is_dir()
    ):
        return 0
    n = 0
    for p in paths.INNO_USER.rglob("*"):
        rel = p.relative_to(paths.INNO_USER)
        if (
            not p.is_file()
            or rel.parts[0] in _INNO_SKIP_DIRS
            or p.name in _INNO_SKIP_FILES
        ):
            continue
        dest = paths.USER / rel
        try:
            if dest.exists() and dest.stat().st_mtime >= p.stat().st_mtime:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
            n += 1
        except OSError:
            return n  # 没搬完：不写标记，下次启动接着搬
    old_loc = paths.INNO_USER.parent / "data" / "loc"
    if old_loc.is_dir():
        for p in old_loc.rglob("*"):
            dest = paths.DATA / "loc" / p.relative_to(old_loc)
            try:
                if p.is_file() and not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, dest)
                    n += 1
            except OSError:
                pass
    paths.MIGRATED.write_text("import_inno", encoding="utf-8")
    return n


def migrate() -> int:
    """把旧位置的文件搬到新位置；返回做了几件事。重复调用没关系"""
    done = 0
    moves = _get_moves()
    for old, new in moves:
        if old.exists() and not new.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(new))
            done += 1
    for name in _SAMPLES:
        old = paths.ROOT / "shots" / name
        if old.exists() and not (paths.SAMPLES / name).exists():
            paths.SAMPLES.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(paths.SAMPLES / name))
            done += 1
    for p in _get_delete_list():
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            done += 1
        elif p.exists():
            p.unlink()
            done += 1
    shots_dir = paths.ROOT / "shots"
    if shots_dir.exists():
        for p in list(shots_dir.iterdir()):
            dest = paths.SHOTS / "old" / p.name
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(dest))
        try:
            shots_dir.rmdir()
        except OSError:
            pass
    return done
