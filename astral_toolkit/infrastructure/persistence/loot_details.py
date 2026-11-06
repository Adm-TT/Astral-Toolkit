"""掉落明细的本机存取（目录迁移 Q3 从 crafting/loot.py 拆出来）

- 整包 loot_details.zip：作者每个游戏版本把 1.3 万件物品的掉落明细全抓一遍、随数据包发布（2026-10-26 用户定），
  国内玩家查看掉落不用再连国外。玩家这边不解压，直接从压缩包里读；打开的句柄按文件修改时间换新，更新整包前先关掉
- 单件缓存 data/loot/<版本>_<编号>.json：整包里没有（抓失败的）、联网现查回来的

只管存取和资源：版本号、编号要拼进路径，由调用方先核过格式再传进来；查不查、联不联网、出错怎么跟玩家说不在这里定。
"""

import json
import threading
import zipfile
from pathlib import Path
from typing import Any

from ...core.paths import DATA

DETAILS = DATA / "loot_details.zip"
CACHE_DIR = DATA / "loot"
MISSING = object()  # 单件缓存里没有这件（和缓存里存的就是 null 分开）
_zip: dict[str, Any] = {"z": None, "mtime": None, "version": None}
_zip_lock = threading.Lock()


def details_version(path=None):
    """整包对应的掉落数据版本（4.10.2LIVE）；没有整包返回空"""
    p = Path(path or DETAILS)
    try:
        with zipfile.ZipFile(p) as z:
            return z.read("version.txt").decode("utf-8").strip()
    except Exception:
        return ""


def from_zip(uuid, version):
    """整包里这件的掉落明细；没有整包、整包版本对不上、整包里没有这件返回 None"""
    try:
        mt = DETAILS.stat().st_mtime
    except OSError:
        return None
    with _zip_lock:
        if _zip["mtime"] != mt:
            if _zip["z"]:
                _zip["z"].close()
            try:
                z = zipfile.ZipFile(DETAILS)
                _zip.update(
                    z=z, mtime=mt, version=z.read("version.txt").decode("utf-8").strip()
                )
            except Exception:
                _zip.update(z=None, mtime=mt, version=None)
        z = _zip["z"]
        if not z or _zip["version"] != version:
            return None
        try:
            return json.loads(z.read(f"{uuid}.json").decode("utf-8"))
        except KeyError:
            return None


def close_bundle():
    """关掉正在读的整包（Windows 上打开着的文件不能替换：更新整包前先调）"""
    with _zip_lock:
        if _zip["z"]:
            _zip["z"].close()
        _zip.update(z=None, mtime=None, version=None)


def read_cached(version, uuid):
    """单件缓存里这件的掉落明细；没有返回 MISSING。
    半个文件（旧版直接写、写到一半被结束）删掉当没有，别永远卡在坏缓存上"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f = CACHE_DIR / f"{version}_{uuid}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            f.unlink(missing_ok=True)
    return MISSING


def write_cached(version, uuid, data):
    """联网现查回来的掉落明细写进单件缓存：先写临时文件再换名，不留半个文件"""
    from ...core.paths import write_json

    write_json(CACHE_DIR / f"{version}_{uuid}.json", data)
