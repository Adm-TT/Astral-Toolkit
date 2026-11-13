"""读屏区域文件：各读屏功能在截图上看哪一块，统一存在 astral_toolkit/screen_regions.json（随程序发布）。

老大 11-09 定：区域在开发工具「读屏开发工作台」（tools/readlab）里手画，存进这个文件，AT 运行时从这里读，
不再在代码里写死百分比。代码里原来的值留作默认值：文件没有、坏了、缺这一条，都用默认值，照常识别。

文件格式：
    {"version": 3, "regions": {"hover.band_50_70": [
        {"aspect": "16:9", "box": [0.5, 0.0, 0.7, 1.0], "kind": "read", "note": "…"}]}}
- box：左、上、右、下。默认占截图宽高的比例（0~1）；`coord_space` 为 `cell` 时相对格子框，允许超出 [0,1]（角标贴角）；
- aspect：画的时候截图的宽高比（"16:9" "16:10" "21:9"…），同一区域可以按不同比例各存一条，用时挑最接近的；
- kind：read 要认的区域 / exclude 不要认的区域（游戏调试字、悬浮窗之类）；
- coord_space：`screen`（默认）或 `cell`（相对当前格子）；
- version：每存一次加 1，工作台存的时候带上读到的版本号，对不上就拒存（两个页面同时改不会悄悄覆盖）。
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

Frac = tuple[float, float, float, float]

PATH = Path(__file__).resolve().parent.parent / "screen_regions.json"
KINDS = ("read", "exclude")
_ASPECT = re.compile(r"^(\d{1,3}):(\d{1,3})$")
MIN_SIDE = 0.005  # 框至少这么宽、这么高（比例）：再窄裁出来是 0 像素，读屏会出错
MAX_ASPECT_GAP = (
    0.2  # 截图比例和条目比例差太多（|log 比|，16:9 对 21:9 是 0.29）就不借，用默认值
)
_NAMED = {"21:9": (64, 27)}  # 21:9 显示器实际是 64:27（3440×1440、2560×1080）

_lock = threading.Lock()
_save_lock = threading.Lock()  # 查版本到写完是一整步，两个请求同时存不会都通过
_cache: dict[str, Any] = {"key": None, "data": None}


class StaleRegions(Exception):
    """存的时候版本号对不上：区域文件已经被别处改过"""


def aspect_of(size: tuple[int, int]) -> str:
    """截图尺寸 → 宽高比写法：常见的几种叫惯用名，别的写约分后的「宽:高」"""
    w, h = int(size[0]), int(size[1])
    for name, (aw, ah) in (("16:9", (16, 9)), ("16:10", (16, 10)), ("21:9", (64, 27))):
        if abs(w / h - aw / ah) < 0.03:  # 3440×1440（2.39）也算 21:9（64:27 = 2.37）
            return name
    g = math.gcd(w, h) or 1
    return f"{w // g}:{h // g}"


def _ratio(aspect: Any) -> float | None:
    if not isinstance(aspect, str):
        return None
    if aspect in _NAMED:
        aw, ah = _NAMED[aspect]
        return aw / ah
    m = _ASPECT.match(aspect or "")
    if not m or not int(m.group(1)) or not int(m.group(2)):
        return None
    return int(m.group(1)) / int(m.group(2))


def _box_ok(box: Any, *, cell: bool = False) -> bool:
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return False
    if not all(isinstance(v, (int, float)) for v in box):
        return False
    if not cell and not all(0.0 <= float(v) <= 1.0 for v in box):
        return False
    return (
        float(box[2]) - float(box[0]) >= MIN_SIDE
        and float(box[3]) - float(box[1]) >= MIN_SIDE
    )


def _entry_ok(e: Any) -> bool:
    if not isinstance(e, dict):
        return False
    space = e.get("coord_space", "screen")
    if space not in ("screen", "cell"):
        return False
    return (
        _ratio(e.get("aspect", "")) is not None
        and _box_ok(e.get("box"), cell=(space == "cell"))
        and e.get("kind", "read") in KINDS
    )


def load() -> dict:
    """读区域文件 → {"version": int, "regions": {键: [条目, …]}}；没有或坏了给空表（version 0）。
    按文件修改时间缓存，文件变了自动重读"""
    try:
        st = PATH.stat()
        key = (str(PATH), st.st_mtime_ns, st.st_size)
    except OSError:
        return {"version": 0, "regions": {}}
    with _lock:
        if _cache["key"] == key:
            return _cache["data"]
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("regions"), dict):
            raise ValueError("格式不对")
        data = {"version": int(data.get("version", 0)), "regions": data["regions"]}
    except (
        OSError
    ):  # 偶尔读不到（被占用、正在替换）：这次用默认值，不记进缓存，下次再读
        return {"version": 0, "regions": {}}
    except (ValueError, TypeError):
        data = {"version": 0, "regions": {}}
    with _lock:
        _cache.update(key=key, data=data)
    return data


def frac(key: str, default: Frac, size: tuple[int, int] | None = None) -> Frac:
    """要认的区域（比例）：size 给了按截图宽高比挑最接近的一条（差太多不借），没给取第一条；
    找不到、文件被手改坏了，都用 default——读屏不能因为区域文件出错"""
    try:
        entries = load()["regions"].get(key)
        entries = (
            [e for e in entries if _entry_ok(e) and e.get("kind", "read") == "read"]
            if isinstance(entries, list)
            else []
        )
        if not entries:
            return default
        if size and size[0] and size[1]:
            want = math.log(size[0] / size[1])
            gap = lambda e: abs(math.log(_ratio(e["aspect"]) or 1.0) - want)  # noqa: E731
            entries.sort(key=gap)
            if gap(entries[0]) > MAX_ASPECT_GAP:
                return default
        l, t, r, b = (float(v) for v in entries[0]["box"])  # noqa: E741
        return (l, t, r, b)
    except Exception:
        return default


def has_read(key: str) -> bool:
    """区域文件里有没有可用的 read 条目"""
    try:
        entries = load()["regions"].get(key)
        return isinstance(entries, list) and any(
            _entry_ok(e) and e.get("kind", "read") == "read" for e in entries
        )
    except Exception:
        return False


def frac_first(
    keys: list[str] | tuple[str, ...],
    default: Frac,
    size: tuple[int, int] | None = None,
) -> Frac:
    """按 keys 顺序取第一条有有效条目的区域；都没有用 default（别名：inventory.* → count.*）"""
    for key in keys:
        if has_read(key):
            return frac(key, default, size)
    return default


def px(key: str, default: Frac, size: tuple[int, int]) -> tuple[int, int, int, int]:
    """区域（像素）：同 frac，再按截图尺寸换成 (左, 上, 右, 下)"""
    l, t, r, b = frac(key, default, size)  # noqa: E741
    w, h = size
    return (int(w * l), int(h * t), int(w * r), int(h * b))


def px_first(
    keys: list[str] | tuple[str, ...],
    default: Frac,
    size: tuple[int, int],
) -> tuple[int, int, int, int]:
    """同 frac_first，再换成像素"""
    l, t, r, b = frac_first(keys, default, size)  # noqa: E741
    w, h = size
    return (int(w * l), int(h * t), int(w * r), int(h * b))


def save(regions: dict, expect_version: int) -> int:
    """存区域文件：先查格式（不对抛 ValueError），再比版本号（不对抛 StaleRegions），
    写临时文件再替换；返回新版本号"""
    if not isinstance(regions, dict):
        raise ValueError("regions 要是 {键: [条目, …]}")
    for k, entries in regions.items():
        if not isinstance(k, str) or not k or not isinstance(entries, list):
            raise ValueError(f"区域 {k!r} 格式不对")
        for e in entries:
            if not _entry_ok(e):
                raise ValueError(f"区域 {k} 的条目不对：{e!r}")
    with _save_lock:
        with _lock:
            _cache.update(key=None, data=None)
        current = load()["version"]
        if current != expect_version:
            raise StaleRegions(
                f"区域文件已经是第 {current} 版，你手上是第 {expect_version} 版"
            )
        new = current + 1
        text = (
            json.dumps(
                {"version": new, "regions": regions}, ensure_ascii=False, indent=2
            )
            + "\n"
        )
        PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".screen_regions.", dir=str(PATH.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            os.replace(tmp, PATH)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        with _lock:
            _cache.update(key=None, data=None)
        return new
