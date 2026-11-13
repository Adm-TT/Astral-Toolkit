"""盘点看仓库：第几页、滚了多少、四列在哪、鼠标指的物品占哪几格（老大 2026-11-09）。

盘点要分清「挪进了新的一格」还是「同一格又认了一次」。以前只拿格子框的屏幕坐标比，仓库一滚动、一翻页就对不上，
同一件会再算一次。这里给每一格一个和屏幕无关的身份：(页, 最左那列, 内容里的纵向位置)。
- 页：count.page 里的「2/51」（认不出就没有，不猜：「1751」这种不纠成 1/51）；
- 滚动：count.scrollbar 里绿色滑块离顶多少 × 格子区高 ÷ 滑块长（2560×1440 样本：内容移动 / 滑块移动 ≈ 2.1 ≈ 867 / 411）；
- 列：count.grid 里四列的竖边横向位置是死的（滚动只上下动；样本里 38 张逐像素一样，约 1879-2016 / 2023-2164 /
  2171-2317 / 2324-2476，越往右越宽），每张图现量；格子被盖住、量不出四列的图返回 None，调用方用上一次量到的；
- 占几格：游戏里只有 1×1 和 2×1（整把船炮、长枪横占两格）。占两格时看鼠标那一列左右哪条竖边没了，就往哪边并。
区域都从区域文件 screen_regions.json 取，默认值和第 7 版一样。方案：计划\\盘点接区域_实施计划_1109.md
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple

import cv2
import numpy as np

from ..core import screen_regions
from . import inventory_panel
from .cell_grid import EDGE, PITCH, _runs

GRID = inventory_panel.RIGHT_GRID
SCROLLBAR = inventory_panel.RIGHT_SCROLLBAR
PAGE = inventory_panel.RIGHT_PAGE
N_COLS = 4
COL_W = (0.8, 1.2)  # 一列宽 0.8~1.2 格距（137~152 像素 / 格距 140）
SEAM = 0.1  # 缝两边的两条竖边相隔不到 0.1 格距（样本 6~7 像素）
HAVE = 0.6  # 这一格高度里竖边占到 6 成算「有边」
GONE = 0.2  # 不到 2 成算「没边」（两格宽的物品中间那条）


def _px(key: str, default, size) -> tuple[int, int, int, int]:
    return screen_regions.px(key, default, size)


class Spot(NamedTuple):
    """一格在仓库里的身份：页（认不出是 None）、最左那列（0~3）、占几列、内容里的纵向位置（行顶 + 滚动，像素）"""

    page: int | None
    col: int
    width: int
    y: float


def _grid_box(img: Any, panel: Any = None) -> tuple[int, int, int, int]:
    """格子区像素框：有 Panel 用它的 grid，否则右仓 inventory/count 别名"""
    if panel is not None:
        return panel.grid
    return _px("count.grid", GRID, img.size)


def columns(img: Any, panel: Any = None) -> list[tuple[int, int]] | None:
    """格子区里四列的 (左边, 右边)，截图横坐标；量不全四列返回 None。
    panel：inventory_panel.Panel，左右仓各用各的 grid。"""
    W, H = img.size
    g = _grid_box(img, panel)
    if g[2] - g[0] < 10 or g[3] - g[1] < 10:
        return None
    pitch = H * PITCH
    gray = np.asarray(img.crop(g).convert("L"), dtype=np.uint8)
    edge = (np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)) > EDGE).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(1, int(pitch * 0.4))))
    tall = cv2.morphologyEx(edge, cv2.MORPH_OPEN, kernel)
    prof = tall.sum(axis=0) / max(1, tall.shape[0])
    xs = [(int(a) + int(b)) / 2 + g[0] for a, b in _runs(prof > 0.25)]
    if not xs:
        return None
    cols: list[tuple[int, int]] = []
    i = 0
    while i < len(xs) and len(cols) < N_COLS:
        left = xs[i]
        nxt = next(
            (
                j
                for j in range(i + 1, len(xs))
                if COL_W[0] * pitch <= xs[j] - left <= COL_W[1] * pitch
            ),
            None,
        )
        if nxt is None:
            if cols:
                break
            i += 1  # 最左那条不是列边（面板边框之类）：换下一条当起点
            continue
        cols.append((int(round(left)), int(round(xs[nxt]))))
        # 下一列从缝对面那条边起；缝窄到量成一条时就从这条起
        i = (
            nxt + 1
            if nxt + 1 < len(xs) and xs[nxt + 1] - xs[nxt] <= SEAM * pitch
            else nxt
        )
    return cols if len(cols) == N_COLS else None


def column_of(cols: list[tuple[int, int]] | None, x: float) -> int | None:
    """横坐标在第几列（缝里算离得近的那列）；不在格子区里返回 None"""
    if not cols:
        return None
    for i, (a, b) in enumerate(cols):
        if a <= x <= b:
            return i
    gaps = [(min(abs(x - a), abs(x - b)), i) for i, (a, b) in enumerate(cols)]
    d, i = min(gaps)
    return i if d <= (cols[0][1] - cols[0][0]) * SEAM else None


def scroll(img: Any, panel: Any = None) -> float | None:
    """内容往下滚了多少像素（滑块在最顶上是 0 左右）；找不到滑块返回 None"""
    if panel is not None:
        if panel.scrollbar is None:
            return None
        b = panel.scrollbar
        g = panel.grid
    else:
        b = _px("count.scrollbar", SCROLLBAR, img.size)
        g = _px("count.grid", GRID, img.size)
    if b[2] - b[0] < 2 or b[3] - b[1] < 20:
        return None
    a = np.asarray(img.crop(b).convert("RGB"), dtype=np.float32)
    green = (
        a[..., 1].mean(axis=1) - (a[..., 0].mean(axis=1) + a[..., 2].mean(axis=1)) / 2
    )
    lo, hi = float(green.min()), float(green.max())
    if hi < 15 or hi - lo < 8:
        return None  # 没有绿色滑块（只有一屏、不用滚，或者被挡住了）
    runs = _runs(green > (lo + hi) / 2)
    top, bottom = max(runs, key=lambda r: r[1] - r[0])
    length = bottom - top + 1
    if length < 20:
        return None
    return top * (g[3] - g[1]) / length


_PAGE = re.compile(r"(\d{1,3})\s*[/／]\s*(\d{1,3})")


def page(img: Any, panel: Any = None) -> int | None:
    """仓库底下页码「2/51」的当前页；认不出、或者数不对（0 页、比总页数大）返回 None，不猜"""
    from ..ocr import recognize

    if panel is not None:
        if panel.page is None:
            return None
        b = panel.page
    else:
        b = _px("count.page", PAGE, img.size)
    if b[2] - b[0] < 4 or b[3] - b[1] < 4:
        return None
    text = " ".join(
        t.text for t in recognize(img.crop(b), urgent=True, native=True) or []
    )
    m = _PAGE.search(text)
    if not m:
        return None
    cur, total = int(m.group(1)), int(m.group(2))
    return cur if 1 <= cur <= total else None


def _edge_cover(gray: Any, x: int, top: int, bottom: int) -> float:
    """竖线 x 在 top~bottom 这一段里有边的比例（左右各容 2 像素）"""
    if bottom - top < 5 or x < 3 or x + 3 >= gray.shape[1]:
        return 0.0
    strip = gray[top : bottom + 1, x - 3 : x + 4].astype(np.float32)
    e = np.abs(cv2.Sobel(strip, cv2.CV_32F, 1, 0, ksize=3))[:, 1:-1] > EDGE
    return float(e.any(axis=1).mean())


def rows_at(
    img: Any, cursor: tuple[int, int], cols: list[tuple[int, int]]
) -> tuple[int, int] | None:
    """鼠标那一行的 (上, 下)：在鼠标那一列左右两条列边上找「连着约一整格高、包住鼠标」的那段；找不到返回 None"""
    c = column_of(cols, cursor[0])
    if c is None:
        return None
    W, H = img.size
    pitch = H * PITCH
    y = int(cursor[1])
    y0, y1 = max(0, int(y - pitch * 1.3)), min(H, int(y + pitch * 1.3))
    gray = np.asarray(img.crop((0, y0, W, y1)).convert("L"), dtype=np.uint8)
    best = None
    for x in (cols[c][0], cols[c][1]):
        if x < 3 or x + 3 >= W:
            continue
        strip = gray[:, x - 3 : x + 4].astype(np.float32)
        band = (
            np.abs(cv2.Sobel(strip, cv2.CV_32F, 1, 0, ksize=3))[:, 1:-1] > EDGE
        ).any(axis=1)
        for a, b in _runs(band):
            if a <= y - y0 <= b and 0.75 * pitch <= b - a <= 1.15 * pitch:
                if best is None or abs((a + b) / 2 - (y - y0)) < abs(
                    (best[0] + best[1]) / 2 - (y - y0)
                ):
                    best = (a, b)
    return (best[0] + y0, best[1] + y0) if best else None


def span(
    img: Any,
    cursor: tuple[int, int],
    cols: list[tuple[int, int]],
    rows: tuple[int, int],
    width: int | None,
) -> tuple[int, int] | None:
    """鼠标指的物品占哪几列 → (最左那列, 列数)。width：游戏数据说它占几格（2 / 1 / None 不知道）。
    数据说 1 格就是 1 格，不看边（样本里一格白箱子挨着带锁的暗格，暗格那条边淡得像没有，光看边会并成一件）。
    占两格：鼠标那一列左右两条列边，哪条在这一行里没了就往哪边并；最左列只能往右、最右列只能往左。
    数据不知道（旧数据包没有占格字段、库里没这件）才光看边：正好一边没了、另一边好好的才当两格。看不清返回 None"""
    c = column_of(cols, cursor[0])
    if c is None:
        return None
    if width == 1:
        return (c, 1)
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    top, bottom = rows
    left = _edge_cover(gray, cols[c][0], top, bottom)
    right = _edge_cover(gray, cols[c][1], top, bottom)
    can_l, can_r = c > 0, c < len(cols) - 1
    if width == 2:
        if can_l and left < GONE and (right >= HAVE or not can_r):
            return (c - 1, 2)
        if can_r and right < GONE and (left >= HAVE or not can_l):
            return (c, 2)
        return None  # 说是两格、边又看不出往哪边：不猜
    if left >= HAVE and right >= HAVE:
        return (c, 1)
    if width is None:
        if can_l and left < GONE and right >= HAVE:
            return (c - 1, 2)
        if can_r and right < GONE and left >= HAVE:
            return (c, 2)
    return None


_cols_seen: dict[tuple[int, int], list[tuple[int, int]]] = {}


def spot(
    img: Any,
    cursor: tuple[int, int],
    width: int | None,
    cols: list[tuple[int, int]] | None = None,
    panel: Any = None,
) -> Spot | None:
    """鼠标指的那一格的身份；列量不出、行找不到、占几格看不清 → None（调用方退回格子框比较）。
    这张图量不全四列（一整列都被大物品盖住、半透明背景太亮）时用同样尺寸截图上次量到的：列的横向位置不会变。
    panel：有则用该侧格子区；没有则按光标 resolve，仍没有则按右仓（兼容旧调用）。"""
    if panel is None:
        try:
            from . import inventory_panel

            panel = inventory_panel.resolve(cursor, img.size)
        except Exception:
            panel = None
    if cols is None:
        try:
            cols = columns(img, panel)
        except TypeError:
            cols = columns(img)  # 测试替身只收 img
    if cols:
        _cols_seen[tuple(img.size)] = cols
    else:
        cols = _cols_seen.get(tuple(img.size))
    if not cols:
        return None
    rows = rows_at(img, cursor, cols)
    if rows is None:
        return None
    sp = span(img, cursor, cols, rows, width)
    if sp is None:
        return None
    if panel is not None and panel.scrollbar is None:
        off = 0.0  # 该侧未标定滚动条（如左仓）：不当失败，按未滚动算
    else:
        try:
            off = scroll(img, panel)
        except TypeError:
            off = scroll(img)  # 测试替身只收 img
        if off is None:
            return None  # 滑块看不到（只有一屏不用滚、或被挡住）：分不清滚没滚，交给格子框比较
    try:
        pg = page(img, panel)
    except TypeError:
        pg = page(img)
    return Spot(pg, sp[0], sp[1], rows[0] + off)


def same_spot(a: Spot, b: Spot, pitch: float) -> bool | None:
    """两个身份是不是同一格：页都认出来才比（有一边没页 → None，交给别的判断）；同页、同列、纵向差不到 0.3 格算同一格"""
    if a.page is None or b.page is None:
        return None
    return (
        a.page == b.page
        and a.col == b.col
        and a.width == b.width
        and abs(a.y - b.y) <= 0.3 * pitch
    )


LOCK_DARK = 15  # 带锁（已停用）的格子很暗：格子里靠两边那一圈平均亮度约 9，普通格子最暗也有 21（2560×1440 样本）
LOCK_ICON = (110, 210)  # 正中的锁图标最亮约 155（不是物品图标那种 230~255 的高光）


def locked(
    img: Any, cursor: tuple[int, int], cols: list[tuple[int, int]] | None = None
) -> bool | None:
    """鼠标那一格是不是带锁的「已停用」格（老大 11-09：照算，标已停用）：格子里很暗、正中有一个中等亮度的小锁。
    找不到这一格（列、行）返回 None"""
    cols = cols or columns(img) or _cols_seen.get(tuple(img.size))
    if not cols:
        return None
    rows = rows_at(img, cursor, cols)
    c = column_of(cols, cursor[0])
    if rows is None or c is None:
        return None
    a, b = cols[c]
    top, bottom = rows
    gray = np.asarray(
        img.crop((a + 10, top + 10, b - 10, bottom - 10)).convert("L"), dtype=np.float32
    )
    if gray.size == 0 or gray.shape[1] < 40 or gray.shape[0] < 40:
        return None
    ring = float(np.concatenate([gray[:, :15].ravel(), gray[:, -15:].ravel()]).mean())
    cy, cx = gray.shape[0] // 2, gray.shape[1] // 2
    center = gray[cy - 18 : cy + 18, cx - 18 : cx + 18]
    peak = float(center.max())
    icon = float((center > LOCK_ICON[0]).mean())
    return (
        ring < LOCK_DARK
        and LOCK_ICON[0] <= peak <= LOCK_ICON[1]
        and 0.03 <= icon <= 0.35
    )
