"""仓库物品格的框：盘点用来判断「鼠标挪进了新的一格，还是同一格又认了一次」（老大 2026-11-09）。

借文档表格识别的办法，只在鼠标附近一格半里找：
1. 横向求导、竖向开运算，留下竖着够长的边；
2. 拿鼠标左边或右边最近一条「在鼠标这一行连着约一整格高」的竖边当基准，它的两头就是格子的上下边；
3. 另一边在离基准约一格宽的范围里挑：那条边至少有一头和基准对齐（真格子左右两条边一起开始或一起结束），
   在这一格高度里边越完整分越高。面板是半透明的，背后场景亮的地方格子边会淡掉一截，所以不要求整格；
   面板边框、滚动条、图标里的线两头都和格子对不上，挑不中；
4. 左右两边都试着当基准；两个结果对不上又分不出高下就不认，交给调用方。
星际公民仓库的格子列是竖直的，只是越往右越宽（2560×1440 下从左到右约 136 / 141 / 146 / 152），
行高约 125、缝 7~15 像素，套不了固定网格，只能就地找。格距按截图高度估（UI 跟着高度缩放）；
换了 UI 缩放比例对不上时只会找不到框，不会给错框。悬浮窗被截图涂黑的地方没有边，找不到就返回 None，
由调用方退回别的判断。方案、真截图试验和样本：计划\\盘点重设计_找格子框_1109.md。
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
WEAK = 0.4  # 另一条边在这一格高度里至少有 0.4 格距（约 56 像素）
GAP = 0.1  # 一条缝宽（7~15 像素，约 0.1 格距）：两头算对齐的误差
CLOSE = 0.1  # 左右两个基准得出的框对不上、分数又只差这么点：分不出高下，不认


def _runs(mask: Any) -> list[tuple[int, int]]:
    """一列真假里连着为真的各段 [(起, 止)]"""
    idx = np.flatnonzero(np.diff(np.concatenate(([0], mask.astype(np.int8), [0]))))
    return list(zip(idx[::2].tolist(), (idx[1::2] - 1).tolist()))


def overlap(a: Box, b: Box) -> float:
    """两个框重叠的比例（交集 / 并集，IoU）：同一格约 0.9 以上，相邻两格是 0"""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    area = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1])
    return w * h / (area - w * h)


def cell_box(img: Any, cursor: tuple[int, int]) -> Box | None:
    """鼠标所在那一格的框 (左, 上, 右, 下)，截图坐标；找不到返回 None。img 是 PIL 图。"""
    W, H = img.size
    x, y = int(cursor[0]), int(cursor[1])
    if not (0 <= x < W and 0 <= y < H):
        return None
    pitch = H * PITCH
    lo, hi, gap = pitch * SIDE[0], pitch * SIDE[1], pitch * GAP
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
    left, right = cols[cols < cx][::-1], cols[cols > cx]  # 都按离鼠标从近到远

    def band(c: int) -> Any:
        return edge[:, max(0, c - 2) : c + 3].any(axis=1)  # 边允许左右偏 2 像素

    def blacked(c: int, a: int, b: int) -> bool:
        # 这一段里挨着纯黑（0）：那是截图涂黑悬浮窗的边沿，不是格子边
        return not gray[a : b + 1, max(0, c - 3) : c + 4].min()

    def whole(c: int) -> tuple[int, int] | None:
        """这条边在鼠标这一行连着约一整格高的那一段；不是返回 None"""
        run = next(((a, b) for a, b in _runs(band(c)) if a <= cy <= b), None)
        if run and lo <= run[1] - run[0] <= hi and not blacked(c, *run):
            return run
        return None

    def score(c: int, a: int, b: int) -> float:
        """另一条边配不配得上基准 a~b：至少一头和基准对齐的那段，在 a~b 里占几成；配不上是 0"""
        if blacked(c, a, b):
            return 0.0
        best = 0.0
        for s, e in _runs(band(c)):
            if abs(s - a) <= gap or abs(e - b) <= gap:
                cover = min(e, b) - max(s, a) + 1
                if cover >= pitch * WEAK:
                    best = max(best, cover / (b - a + 1))
        return best

    found: list[tuple[float, Box]] = []
    for mine, other in ((left, right), (right, left)):
        anchor = next(((int(c), run) for c in mine if (run := whole(int(c)))), None)
        if anchor is None:
            continue
        c, (a, b) = anchor
        between = [int(c2) for c2 in other if abs(int(c2) - c) < lo]
        if any(whole(c2) for c2 in between):
            continue  # 基准和鼠标之间（或鼠标对面不到一格）还有整格高的边：鼠标停在缝上
        # 分数差不多的取离基准最近的：远一点那条常是缝对面邻格的边，会把框拉宽一条缝
        picks = [
            (score(int(c2), a, b), int(c2))
            for c2 in other
            if lo <= abs(int(c2) - c) <= hi
        ]
        top = max((p[0] for p in picks), default=0.0)
        s, c2 = next(
            ((sc, c2) for sc, c2 in picks if sc > 0 and sc >= top - CLOSE), (0.0, 0)
        )
        if s > 0:
            x1, x2 = sorted((c, c2))
            found.append((s, (x1 + x0, a + y0, x2 + x0, b + y0)))

    if not found:
        return None
    best = max(found, key=lambda f: f[0])
    if len(found) == 2:
        (sa, ba), (sb, bb) = found
        if overlap(ba, bb) < 0.5 and abs(sa - sb) < CLOSE:
            return None  # 左右两个基准各说各的、又分不出高下
    return best[1]


def in_gap(img: Any, cursor: Any) -> bool:
    """鼠标是不是停在两格之间的缝上（只在这次没找到框时问）：往两个相反方向（左右、上下、两条斜线）
    各自一点点往外试，最多 0.25 格距，两边都碰到框、而且是两个不同的格子，就是在缝上。
    缝本身 7~15 像素，加上边线两框之间最宽约 19 像素，贴着一边停时另一边要试得够远"""
    pitch = img.size[1] * PITCH
    x, y = int(cursor[0]), int(cursor[1])

    def probe(dx: int, dy: int) -> Box | None:
        for k in range(1, 6):  # 0.05、0.1……0.25 格距
            d = pitch * 0.05 * k
            b = cell_box(img, (int(x + dx * d), int(y + dy * d)))
            if b:
                return b
        return None

    for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
        a, b = probe(-dx, -dy), probe(dx, dy)
        if a and b and overlap(a, b) < 0.5:
            return True
    return False


def inside(box: Box, point: tuple[int, int]) -> bool:
    """点在不在框里，四边各放宽框高的 2%（1440 下约 2.5 像素，横竖都按框高算，格子宽高差不多）。
    最窄的缝两边框之间约 9 像素，余量必须小于它的一半：不然缝中间停的一次会同时算进左右两格，
    同样的东西两格只记一格"""
    m = (box[3] - box[1]) * 0.02
    return box[0] - m <= point[0] <= box[2] + m and box[1] - m <= point[1] <= box[3] + m
