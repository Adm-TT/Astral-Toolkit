"""所有文件放在哪（统一在这里改）

astral_toolkit/          程序代码 + 随程序带的固定数据（names_zh.json、sc_glossary.json）
data/               下载和自动生成的数据：星图、商店、掉落、汉化包、制造蓝图、维科洛…（菜单 5 更新，可以随便删，会重新下载）
userdata/           你自己的东西：设置、路标、悬浮窗位置、最后位置、日志、截图记录（更新程序不会动）
tests/              自检用（tests/samples 里是测试截图）

旧版本的文件散在外层和 astral_toolkit 里，migrate()（见 core.migration）会在启动时自动搬到新位置。
"""

import os
import shutil
import sys
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
# 独立打包版（PyInstaller，2026-10-26）：程序文件在 AT.exe 旁边的 _internal 里，data / userdata 放在 AT.exe 所在的文件夹
FROZEN = bool(getattr(sys, "frozen", False))
ROOT = Path(sys.executable).resolve().parent if FROZEN else CODE.parent
# Velopack 安装版（2026-10-27）：程序在 %LOCALAPPDATA%\AT\current\，每次升级整个换掉，所以数据和设置放在外面：
#   data      → %LOCALAPPDATA%\AT\data（升级不动；卸载时随 AT 一起删，可以重新下载）
#   userdata  → %LOCALAPPDATA%\AT_userdata（升级、卸载都不动，和以前卸载时默认保留一样）
VELOPACK = (
    FROZEN and ROOT.name.lower() == "current" and (ROOT.parent / "Update.exe").exists()
)
BUNDLED_DATA = ROOT / "data"  # 安装包自带的数据
DATA = ROOT.parent / "data" if VELOPACK else BUNDLED_DATA
# USER 按程序位置推（current → AT → Local），不读 LOCALAPPDATA：用另一个管理员账号提权时那个变量是别人的目录（二审 2026-10-27）
USER = ROOT.parent.parent / "AT_userdata" if VELOPACK else ROOT / "userdata"
INNO_USER = (
    ROOT.parent.parent / "Programs" / "AT" / "userdata" if VELOPACK else None
)  # 老的 Inno 安装版的 userdata
MIGRATED = (
    USER / ".migrated_from_inno"
)  # 老 Inno 版的设置和记录已经搬过来了（桥接安装程序或 import_inno 写）
LOGS = USER / "logs"
SHOTS = USER / "shots"
SAMPLES = ROOT / "tests" / "samples"
for _d in (DATA, USER, LOGS):
    _d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- JSON 文件缓存（2026-10-28 审查后统一，以前各模块手写了 9 份）
import json as _json  # noqa: E402
import threading as _threading  # noqa: E402

_json_cache = {}
_json_lock = _threading.Lock()
_BAD = object()


def file_stamp(path):
    """文件的修改时间（纳秒）；没有文件返回 None"""
    try:
        return Path(path).stat().st_mtime_ns
    except OSError:
        return None


def cached_json(path, transform=None, default=None):
    """读 JSON 文件并按修改时间缓存：文件换了（更新数据）自动重读，不用重启；没有文件或坏了返回 default（不缓存，下次再试）。
    transform：把原始 JSON 变成要用的结构，只在文件变了时跑一次。"""
    path = Path(path)
    mt = file_stamp(path)
    if mt is None:
        return default
    with _json_lock:
        ent = _json_cache.get(path)
    if ent is not None and ent[0] == mt:
        return default if ent[1] is _BAD else ent[1]
    try:
        raw = _json.loads(path.read_text(encoding="utf-8"))
        val = transform(raw) if transform else raw
    except Exception:
        val = _BAD  # 坏文件：也按修改时间记住，文件没变就不再反复读（二审 2026-10-28）
    with _json_lock:
        _json_cache[path] = (mt, val)
    return default if val is _BAD else val


def write_json(path, obj, **kw):
    """把 obj 写成 JSON：先写临时文件再换名，进程中途被结束也不会留下半个文件（2026-10-28 整体审查）。kw 传给 json.dumps"""
    import os

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    kw.setdefault("ensure_ascii", False)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{_threading.get_ident()}.tmp")
    try:
        tmp.write_text(_json.dumps(obj, **kw), encoding="utf-8")
        for i in range(
            6
        ):  # Windows：目标正被别的线程 / 进程读着、杀毒软件在扫时换名会失败，稍等再试
            try:
                tmp.replace(path)
                break
            except PermissionError:
                if i == 5:
                    raise
                import time as _t

                _t.sleep(0.05)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    clear_json_cache(path)


def clear_json_cache(path=None):
    """清掉缓存（某个文件，或全部）：写完文件、更新数据后调"""
    with _json_lock:
        if path is None:
            _json_cache.clear()
        else:
            _json_cache.pop(Path(path), None)


def self_cmd(entry, *args):
    """启动 AT 自己的另一个入口（重启、管理员身份）的命令行。
    独立打包版：AT.exe <入口> …；Python 版：python -m astral_toolkit.run <入口> …"""
    if FROZEN:
        return [sys.executable, entry, *map(str, args)]
    return [sys.executable, "-X", "utf8", "-m", "astral_toolkit.run", entry, *map(str, args)]


def data(name):
    DATA.mkdir(parents=True, exist_ok=True)
    return DATA / name


# 数据文件的 source 标记：由游戏数据构建的文件写 SRC_GAME，「更新数据」时不拿网站版盖掉它
SRC_GAME = "game"
# 旧写法：已发出的数据包、旧版客户端都只认它，构建脚本目前仍写它；等旧版客户端都淘汰再改写 SRC_GAME
SRC_GAME_OLD = "unpack"
# data/ 下放制造蓝图构建输入的目录名（只在作者电脑上有；不进安装包、不进升级备份）
BUILD_DIR = "unpack"


def from_game(d):
    """读出来的数据文件内容是不是由游戏数据构建的"""
    return isinstance(d, dict) and d.get("source") in (SRC_GAME, SRC_GAME_OLD)


def user(name):
    USER.mkdir(parents=True, exist_ok=True)
    return USER / name


_CRASH = []


def crash_log(name="crash_log.txt"):
    """底层组件（显卡认字、识别、悬浮窗）直接崩溃时 Python 来不及写日志：faulthandler 把各线程最后在跑的代码写进 crash_log.txt。
    怎么看：fatal 段后面同一进程号有「正常退出」行的，是程序自己接住的异常，不是真崩；
    显卡认字小进程写 crash_log_ocr.txt。
    每个进程只认第一次调用时的文件名"""
    if _CRASH:
        return
    try:
        import atexit
        import faulthandler
        import time

        f = open(log(name), "a", encoding="utf-8", buffering=1)
        f.write(f"==== {time.strftime('%F %T')} 启动（进程 {os.getpid()}） ====\n")
        faulthandler.enable(file=f, all_threads=True)
        _CRASH.append(f)  # 文件要一直开着，崩溃时才写得进去
        atexit.register(
            lambda: f.write(
                f"---- {time.strftime('%F %T')} 正常退出（进程 {os.getpid()}） ----\n"
            )
        )
    except Exception:
        pass


LOG_CAP = 3_000_000  # 日志超过这么大就换成 .old 重新写（只留上一份；以前只追加不封顶，2026-10-28 整体审查）


def log(name):
    LOGS.mkdir(parents=True, exist_ok=True)
    p = LOGS / name
    try:
        if p.exists() and p.stat().st_size > LOG_CAP:
            p.replace(p.with_name(name + ".old"))
    except OSError:
        pass
    return p


def shots(sub):
    d = SHOTS / sub
    d.mkdir(parents=True, exist_ok=True)
    return d


def seed_data():
    """Velopack 安装版：换了版本（或第一次装）就把安装包自带的数据复制到外面的 data\（覆盖旧的），
    先删旧的数据包记录：安装包带了记录就复制成新的，没带就保持删除（下次「更新数据」重新下）——和以前 Inno 安装程序做的一样。返回复制了几个文件"""
    if not VELOPACK or not BUNDLED_DATA.exists():
        return 0
    from .version import VERSION

    stamp = DATA / ".bundled_version"
    try:
        if stamp.read_text(encoding="utf-8").strip() == VERSION:
            return 0
    except OSError:
        pass
    n = 0
    (DATA / "data_pack.json").unlink(
        missing_ok=True
    )  # 先删旧标记：安装包带了就复制成和数据一致的版本，没带就保持删掉（下次更新重新下）
    for p in BUNDLED_DATA.rglob("*"):
        if p.is_file():
            dest = DATA / p.relative_to(BUNDLED_DATA)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
            n += 1
    stamp.write_text(VERSION, encoding="utf-8")
    return n


# 历史版本迁移（core.migration）：懒重导出，避免与 migration 循环导入
def import_inno():
    from .migration import import_inno as _import_inno

    return _import_inno()


def migrate():
    from .migration import migrate as _migrate

    return _migrate()
