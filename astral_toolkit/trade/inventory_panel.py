"""物品栏面板 ROI：按光标落在左/右仓格子区解析 Panel（方案 2026-11-12）。

区域比例来自 screen_regions.json；右仓与 count.* 别名互为回退。1K/2K/4K 同宽高比下等比缩放。
"""

from __future__ import annotations

from typing import NamedTuple

from ..core import screen_regions

# 右仓：与 screen_regions v7 / count_view 默认一致
RIGHT_GRID = (0.7336, 0.2309, 0.9683, 0.8327)
RIGHT_SCROLLBAR = (0.9688, 0.2167, 0.9766, 0.8354)
RIGHT_PAGE = (0.8369, 0.8464, 0.8676, 0.8718)
TOOLTIP = (0.5, 0.1191, 0.7132, 0.8345)

# 左仓：2K 初值，待 readlab 校准
LEFT_GRID = (0.025, 0.2309, 0.265, 0.65)
LEFT_SCROLLBAR = (0.266, 0.2309, 0.274, 0.65)  # 初值；文件没有则 resolve 给 None
LEFT_PAGE = (0.12, 0.65, 0.16, 0.68)

# 角标相对格子（C · 宽松贴角）
CELL_QUALITY = (-0.10, -0.12, 0.48, 0.28)
CELL_STACK = (0.52, -0.12, 1.10, 0.28)

Box = tuple[int, int, int, int]
Frac = tuple[float, float, float, float]


class Panel(NamedTuple):
    """光标所在仓：侧别 + 像素框；scrollbar/page 缺文件或无效时为 None"""

    side: str  # "left" | "right"
    grid: Box
    scrollbar: Box | None
    page: Box | None
    tooltip: Box


def _inside(box: Box, cursor: tuple[float, float]) -> bool:
    x, y = cursor
    return box[0] <= x < box[2] and box[1] <= y < box[3]


def _px_side(side: str, part: str, default: Frac, size: tuple[int, int]) -> Box:
    inv = f"inventory.{side}.{part}"
    if side == "right":
        legacy = f"count.{part}"
        return screen_regions.px_first((inv, legacy), default, size)
    return screen_regions.px(inv, default, size)


def _optional_px(
    side: str, part: str, default: Frac, size: tuple[int, int]
) -> Box | None:
    """文件里没有该键（左仓未标定）→ None；有键则用 px（可回落默认）"""
    inv = f"inventory.{side}.{part}"
    legacy = f"count.{part}" if side == "right" else None
    keys = [inv] + ([legacy] if legacy else [])
    if not any(screen_regions.has_read(k) for k in keys):
        if side == "left":
            return None  # 左仓未进文件：不假装有滚动条/页码
        # 右仓无文件时仍用代码默认（与旧 count_view 一致）
    box = _px_side(side, part, default, size)
    if box[2] - box[0] < 2 or box[3] - box[1] < 2:
        return None
    return box


def resolve(cursor: tuple[float, float] | None, size: tuple[int, int]) -> Panel | None:
    """光标落在左/右 inventory.*.grid → Panel；否则 None。size 为截图 (W,H)。"""
    if cursor is None or not size[0] or not size[1]:
        return None
    left_grid = screen_regions.px("inventory.left.grid", LEFT_GRID, size)
    right_grid = _px_side("right", "grid", RIGHT_GRID, size)
    side = None
    grid = None
    if _inside(left_grid, cursor):
        side, grid = "left", left_grid
    elif _inside(right_grid, cursor):
        side, grid = "right", right_grid
    if side is None or grid is None:
        return None
    tip = screen_regions.px_first(("inventory.tooltip", "count.tooltip"), TOOLTIP, size)
    if side == "left":
        sb = _optional_px("left", "scrollbar", LEFT_SCROLLBAR, size)
        pg = _optional_px("left", "page", LEFT_PAGE, size)
    else:
        sb = _optional_px("right", "scrollbar", RIGHT_SCROLLBAR, size)
        pg = _optional_px("right", "page", RIGHT_PAGE, size)
    return Panel(side=side, grid=grid, scrollbar=sb, page=pg, tooltip=tip)


def cell_badge_frac(kind: str) -> Frac:
    """角标相对格子比例：quality | stack"""
    if kind == "quality":
        return screen_regions.frac("inventory.cell.quality", CELL_QUALITY, None)
    if kind == "stack":
        return screen_regions.frac("inventory.cell.stack", CELL_STACK, None)
    raise ValueError(kind)


def map_cell_roi(cell: Box, rel: Frac, size: tuple[int, int]) -> Box:
    """相对格子框 → 截图像素，再 clamp 到图内"""
    l, t, r, b = cell  # noqa: E741
    cw, ch = max(1, r - l), max(1, b - t)
    rl, rt, rr, rb = rel
    x0 = int(l + rl * cw)
    y0 = int(t + rt * ch)
    x1 = int(l + rr * cw)
    y1 = int(t + rb * ch)
    W, H = size
    x0 = max(0, min(W, x0))
    y0 = max(0, min(H, y0))
    x1 = max(0, min(W, x1))
    y1 = max(0, min(H, y1))
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    return (x0, y0, x1, y1)

