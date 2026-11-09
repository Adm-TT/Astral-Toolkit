"""读屏开发工作台：各读屏功能包成统一的「试一下 / 批量」接口。

每个功能给出：用到哪些区域（screen_regions 里的键）、在一张截图上点某处试一下、整张批量跑一下。
结果统一成 Result：要叠在图上的框（Shape）、几行文字、耗时、出错信息。run() 包一层计时和捕获异常，永不抛。
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from astral_toolkit.core import screen_regions

Box = tuple[int, int, int, int]
COLORS = ("read", "exclude", "hit", "miss")


@dataclass
class Shape:
    box: Box
    label: str
    color: str  # read 要认的区域 / exclude 不认的区域 / hit 认到的东西 / miss 没认到


@dataclass
class Result:
    shapes: list[Shape] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    ms: int = 0
    error: str = ""


@dataclass
class Feature:
    key: str
    name: str
    regions: list[str]
    try_at: Callable[[Any, "tuple[int, int] | None"], Result]
    batch: Callable[[Any], Result]


def _region(key: str, default: Any, img: Any, label: str) -> Shape:
    return Shape(screen_regions.px(key, default, img.size), label, "read")


def _centre(img: Any, point: "tuple[int, int] | None") -> tuple[int, int]:
    return point or (img.size[0] // 2, img.size[1] // 2)


# ---------------------------------------------------------------- F8 物品说明框（盘点也用它）
def _tooltip(img: Any, point: "tuple[int, int] | None") -> Result:
    from astral_toolkit.trade import inspector

    cursor = _centre(img, point)
    # whole_screen=False：工作台里不进整屏兜底（一次 3 秒，批量查会卡很久）
    text, name, where = inspector._read_tooltip(img, cursor, whole_screen=False)
    r = Result()
    box = inspector.region_box(where, *img.size)
    if box:
        r.shapes.append(Shape(box, f"停在 {where}", "hit" if name else "miss"))
    if name:
        r.lines.append(f"认出：{name[0]} | {name[1]}（停在 {where}）")
    else:
        r.lines.append(f"没认出（最后试的是 {where}）")
    if text:
        r.lines.append("字：" + " / ".join(str(t) for t in list(text)[:8]))
    return r


# ---------------------------------------------------------------- 盘点：格子框 + 说明框
def _count_try(img: Any, point: "tuple[int, int] | None") -> Result:
    from astral_toolkit.trade import cell_grid

    r = Result()
    if point:
        box = cell_grid.cell_box(img, point)
        if box:
            r.shapes.append(Shape(box, "格子框", "hit"))
            r.lines.append(f"格子框：{box}（{box[2] - box[0]}×{box[3] - box[1]}）")
        else:
            gap = cell_grid.in_gap(img, point)
            r.shapes.append(
                Shape(
                    (point[0] - 6, point[1] - 6, point[0] + 6, point[1] + 6),
                    "没框",
                    "miss",
                )
            )
            r.lines.append(
                "没找到格子框" + ("：停在两格之间的缝上（这次不算）" if gap else "")
            )
    t = _tooltip(img, point)
    r.shapes += t.shapes
    r.lines += t.lines
    return r


# ---------------------------------------------------------------- 采矿扫描面板
def _mining(img: Any, point: "tuple[int, int] | None" = None) -> Result:
    from astral_toolkit.mining import screen

    r = Result(
        shapes=[_region("mining.search", screen.SEARCH, img, "扫描面板找字范围")]
    )
    scan = screen.analyse(img)
    win = screen.PANEL_CACHE.get("win")
    if win and screen.PANEL_CACHE.get("size") == img.size:
        r.shapes.append(Shape(tuple(int(v) for v in win), "面板", "hit"))  # type: ignore[arg-type]
    if scan and (scan.mass is not None or scan.composition):
        r.lines.append(
            f"石头 {scan.rock}｜质量 {scan.mass}｜抗性 {scan.resistance}｜不稳定 {scan.instability}｜"
            f"SCU {scan.total_scu}｜读全 {scan.valid}"
        )
        r.lines += [f"  {n} {pct}%（品质 {q}）" for n, pct, q in scan.composition]
    else:
        r.lines.append("没读到扫描面板")
    return r


# ---------------------------------------------------------------- 雷达信号
def _radar(img: Any, point: "tuple[int, int] | None" = None) -> Result:
    from astral_toolkit.mining import signals

    r = Result(
        shapes=[_region("mining.center_tag", signals.CENTER_TAG, img, "准星标签")]
    )
    found = signals.find_signatures(img) or []
    for value, _fixed, text, box in found:
        r.shapes.append(Shape(tuple(int(v) for v in box), str(value), "hit"))  # type: ignore[arg-type]
        r.lines.append(f"信号 {value}（{text}）")
    if not found:
        r.lines.append("没找到信号")
    return r


# ---------------------------------------------------------------- 右上角调试信息（导航用）
def _nav(img: Any, point: "tuple[int, int] | None" = None) -> Result:
    from astral_toolkit.navigation import displayinfo

    r = Result(shapes=[_region("nav.displayinfo", displayinfo.REGION, img, "调试信息")])
    info = displayinfo.parse(displayinfo.lines_of(img)) or {}
    if info.get("global") or info.get("location") or info.get("zone"):
        r.lines.append(f"地点 {info.get('location')}｜区域 {info.get('zone')}")
        if info.get("global"):
            r.lines.append(f"坐标 {info.get('global')}")
    else:
        r.lines.append("没读到调试信息（游戏里 r_DisplayInfo 要开着）")
    return r


_HOVER_KEYS = [
    "hover.band_30_50",
    "hover.band_50_70",
    "hover.band_30_70",
    "hover.title_rows",
    "hover.body_rows",
]

FEATURES: dict[str, Feature] = {
    f.key: f
    for f in (
        Feature(
            "count",
            "盘点",
            list(_HOVER_KEYS),
            _count_try,
            lambda img: _tooltip(img, None),
        ),
        Feature(
            "hover",
            "F8 物品识别",
            list(_HOVER_KEYS),
            _tooltip,
            lambda img: _tooltip(img, None),
        ),
        Feature("mining", "采矿扫描面板", ["mining.search"], _mining, _mining),
        Feature("radar", "雷达信号", ["mining.center_tag"], _radar, _radar),
        Feature("nav", "右上角调试信息", ["nav.displayinfo"], _nav, _nav),
    )
}


def run(feature: str, img: Any, point: "tuple[int, int] | None", batch: bool) -> Result:
    """跑一个功能：计时、捕获异常写进 error，永不抛"""
    t = time.perf_counter()
    try:
        f = FEATURES[feature]
        r = f.batch(img) if batch else f.try_at(img, point)
    except Exception as e:  # 工作台要能看到出错的那张，不能停
        r = Result(
            error=f"{type(e).__name__}: {e}｜{traceback.format_exc().splitlines()[-3].strip()}"
        )
    r.ms = round((time.perf_counter() - t) * 1000)
    return r
