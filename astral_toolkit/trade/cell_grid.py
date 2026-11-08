"""仓库物品格的框：盘点用来判断「鼠标挪进了新的一格，还是同一格又认了一次」（老大 2026-11-09）。

借文档表格识别的办法，只在鼠标附近一格半里找：
1. 横向求导、竖向开运算，留下竖着够长的边；
2. 鼠标左右两边，各找最近一条「在鼠标这一行一路连着、长度够一整格」的竖边——格子边上下贯穿整格，
   物品图标里的竖线短，过不了这一关；竖边断开的地方就是上下两格之间的缝，顺带得到上下边。
星际公民仓库的格子列是竖直的，只是越往右越宽（2560×1440 下从左到右约 136 / 141 / 146 / 152），
行高约 125、缝 7~15 像素，套不了固定网格，只能就地找。格距按截图高度估（UI 跟着高度缩放）；
换了 UI 缩放比例对不上时只会找不到框，不会给错框。悬浮窗被截图涂黑的地方没有边，找不到就返回 None，
由调用方退回别的判断。方案和真截图试验：计划\\盘点重设计_找格子框_1109.md。
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

Box = tuple[int, int, int, int]

PITCH = 0.097  # 格距约是截图高度的 9.7%（1440 下约 140 像素）
EDGE = 40  # Sobel(3×3) 响应约是台阶高度的 4 倍：40 ≈ 明暗台阶约 10 个灰度
NEAR = 1.3  # 只看鼠标周围 1.3 格（够装下鼠标所在的一整格）
SIDE = (0.75, 1.15)  # 框的宽、高要在 0.75~1.15 格距之间（格子 125~152，缝上只有约 10）


def _run_at(band: Any, y: int) -> tuple[int, int] | None:
    """一列真假里，盖住第 y 行的那一段 (起, 止)；第 y 行是假返回 None"""
    if not band[y]:
        return None
    off = np.flatnonzero(~band.astype(bool))
    above, below = off[off < y], off[off > y]
    return (
        int(above.max()) + 1 if len(above) else 0,
        int(below.min()) - 1 if len(below) else len(band) - 1,
    )


def cell_box(img: Any, cursor: tuple[int, int]) -> Box | None:
    """鼠标所在那一格的框 (左, 上, 右, 下)，截图坐标；找不到返回 None。img 是 PIL 图。"""
    W, H = img.size
    x, y = int(cursor[0]), int(cursor[1])
    if not (0 <= x < W and 0 <= y < H):
        return None
    pitch = H * PITCH
    r = int(pitch * NEAR)
    x0, y0 = max(0, x - r), max(0, y - r)
    gray = np.asarray(
        img.crop((x0, y0, min(W, x + r), min(H, y + r))).convert("L"), dtype=np.uint8
    )
    cx, cy = x - x0, y - y0

    edge = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)) > EDGE
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(pitch * 0.4)))
    tall = cv2.morphologyEx(edge.astype(np.uint8), cv2.MORPH_OPEN, kernel)
    cols = np.flatnonzero(tall.any(axis=0))

    def side(xs: Any) -> tuple[int, tuple[int, int]] | None:
        """按离鼠标从近到远，第一条在鼠标这一行贯穿整格的竖边：(x, 竖边那一段)"""
        for c in xs:
            # 紧挨着纯黑（0）的边不认：那是截图涂黑悬浮窗的边沿，不是格子边（游戏里最暗的底色也有 6 左右）
            if not gray[cy, max(0, c - 3) : c + 4].min():
                continue
            run = _run_at(
                edge[:, max(0, c - 2) : c + 3].any(axis=1), cy
            )  # 边允许左右偏 2 像素
            if run and run[1] - run[0] >= pitch * SIDE[0]:
                return int(c), run
        return None

    left, right = side(cols[cols < cx][::-1]), side(cols[cols > cx])
    if not left or not right:
        return None
    (x1, (a1, b1)), (x2, (a2, b2)) = left, right
    y1, y2 = min(a1, a2), max(b1, b2)
    lo, hi = pitch * SIDE[0], pitch * SIDE[1]
    if not (lo <= x2 - x1 <= hi and lo <= y2 - y1 <= hi):
        return None  # 太窄（停在缝上）、太宽、竖边一路不断（面板边框）、被涂黑一截：都不当格子
    return (x1 + x0, y1 + y0, x2 + x0, y2 + y0)


def overlap(a: Box, b: Box) -> float:
    """两个框重叠的比例（交集 / 并集，IoU）：同一格约 0.9 以上，相邻两格是 0"""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    area = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1])
    return w * h / (area - w * h)


def inside(box: Box, point: tuple[int, int], margin: int = 3) -> bool:
    """点在不在框里（边上留几像素余量）。
    余量故意比半条缝（4~8 像素）小：停在缝上还认出旁边那格时宁可多算一格，
    放大到半条缝反过来会把缝另一边后算的邻格吞掉、少算一格"""
    return (
        box[0] - margin <= point[0] <= box[2] + margin
        and box[1] - margin <= point[1] <= box[3] + margin
    )
