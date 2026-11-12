"""盘点看仓库（trade/count_view）：四列在哪、滚了多少、页码、鼠标指的物品占哪几格、格子身份（2026-11-09）。
用画出来的仓库：2560×1440，四列和真截图一样（1879-2016 / 2023-2164 / 2171-2317 / 2324-2476），行高 125、缝 15"""

from PIL import Image, ImageDraw

COLS = [(1879, 2016), (2023, 2164), (2171, 2317), (2324, 2476)]
ROW0, ROW_H, ROW_GAP = 345, 125, 15


def _row(i):
    top = ROW0 + i * (ROW_H + ROW_GAP)
    return top, top + ROW_H


def _inventory(wide=((2, 1),), thumb=(600, 1010)):
    """wide：哪些 (行, 最左列) 是两格宽的物品"""
    img = Image.new("RGB", (2560, 1440), (20, 30, 35))
    d = ImageDraw.Draw(img)
    skip = set()
    for r, c in wide:
        top, bottom = _row(r)
        d.rectangle((COLS[c][0], top, COLS[c + 1][1], bottom), fill=(55, 70, 75))
        skip |= {(r, c), (r, c + 1)}
    for r in range(6):
        top, bottom = _row(r)
        for c, (a, b) in enumerate(COLS):
            if (r, c) not in skip:
                d.rectangle((a, top, b, bottom), fill=(55, 70, 75))
    if thumb:
        d.rectangle((2480, 312, 2500, 1202), fill=(13, 43, 39))
        d.rectangle((2482, thumb[0], 2498, thumb[1]), fill=(20, 90, 45))
    return img


def test_columns_match_real_layout():
    from astral_toolkit.trade import count_view as V

    cols = V.columns(_inventory())
    assert cols is not None and len(cols) == 4
    for (a, b), (x, y) in zip(cols, COLS):
        assert abs(a - x) <= 3 and abs(b - y) <= 3
    assert V.column_of(cols, 1950) == 0 and V.column_of(cols, 2400) == 3
    assert V.column_of(cols, 2019) in (0, 1)  # 缝里：离得近的那列
    assert V.column_of(cols, 1500) is None
    assert V.columns(Image.new("RGB", (2560, 1440), (20, 30, 35))) is None  # 没有格子


def test_scroll_from_thumb():
    from astral_toolkit.core import screen_regions
    from astral_toolkit.trade import count_view as V

    # 滑块离轨道顶 288 像素、长 411：内容滚了 288 × 格子区高 / 411
    img = _inventory(thumb=(600, 1010))
    g = screen_regions.px_first(
        ("inventory.right.grid", "count.grid"), V.GRID, img.size
    )
    off = V.scroll(img)
    assert off is not None and abs(off - (600 - 312) * (g[3] - g[1]) / 411) < 4
    assert V.scroll(_inventory(thumb=None)) is None  # 没滑块：不知道滚没滚


def test_page_reads_only_clean_numbers(monkeypatch):
    from types import SimpleNamespace

    from astral_toolkit import ocr
    from astral_toolkit.trade import count_view as V

    said = ["2/51"]
    monkeypatch.setattr(
        ocr,
        "recognize",
        lambda crop, urgent=False, native=False: [SimpleNamespace(text=said[0])],
    )
    img = _inventory()
    assert V.page(img) == 2
    for bad in ("1751", "", "0/51", "60/51"):
        said[0] = bad
        assert V.page(img) is None  # 不猜


def test_span_trusts_game_data_then_edges():
    from astral_toolkit.trade import count_view as V

    img = _inventory(wide=((2, 1),))
    cols = V.columns(img)
    assert cols is not None
    mid_l = (COLS[1][0] + COLS[1][1]) // 2
    mid_r = (COLS[2][0] + COLS[2][1]) // 2
    top, bottom = _row(2)
    y = (top + bottom) // 2
    rows = V.rows_at(img, (mid_l, y), cols)
    assert rows is not None and abs(rows[0] - top) <= 3 and abs(rows[1] - bottom) <= 3
    # 数据说占两格：指左半边、右半边都是 (1 列起, 2 列)
    assert V.span(img, (mid_l, y), cols, rows, 2) == (1, 2)
    assert V.span(img, (mid_r, y), cols, rows, 2) == (1, 2)
    # 数据不知道：光看边也看得出
    assert V.span(img, (mid_r, y), cols, rows, None) == (1, 2)
    # 数据说 1 格就是 1 格（暗格的边淡得像没有时也不并）
    assert V.span(img, (mid_r, y), cols, rows, 1) == (2, 1)
    # 普通一格
    t1, b1 = _row(1)
    r1 = V.rows_at(img, (mid_l, (t1 + b1) // 2), cols)
    assert r1 is not None and V.span(img, (mid_l, (t1 + b1) // 2), cols, r1, None) == (
        1,
        1,
    )
    # 数据说两格、两边边都在：看不出往哪边并 → 不猜
    assert V.span(img, (mid_l, (t1 + b1) // 2), cols, r1, 2) is None


def test_spot_identity_survives_scroll(monkeypatch):
    from astral_toolkit.trade import count_view as V

    monkeypatch.setattr(V, "page", lambda img: 3)
    a = V.spot(
        _inventory(thumb=(312, 722)),
        ((COLS[0][0] + COLS[0][1]) // 2, _row(3)[0] + 60),
        None,
    )
    assert a is not None and (a.page, a.col, a.width) == (3, 0, 1)
    # 往下滚：滑块下移 68，内容上移约 68 × 867 / 411 ≈ 143（一行）；同一件在上一行的屏幕位置
    img = _inventory(thumb=(380, 790))
    shift = V.scroll(img)
    assert shift is not None
    b = V.spot(img, ((COLS[0][0] + COLS[0][1]) // 2, _row(2)[0] + 60), None)
    assert b is not None
    # 画的仓库没真滚（还是那几行），只看换算：行顶 + 滚动
    assert abs(b.y - (_row(2)[0] + shift)) <= 3
    assert V.same_spot(a, a._replace(y=a.y + 30), 140) is True
    assert V.same_spot(a, a._replace(y=a.y + 60), 140) is False
    assert V.same_spot(a, a._replace(page=4), 140) is False
    assert V.same_spot(a, a._replace(col=1), 140) is False
    assert V.same_spot(a, a._replace(page=None), 140) is None
    assert V.spot(_inventory(thumb=None), (1950, 600), None) is None  # 没滑块：不给身份


def test_spot_reuses_columns_when_hidden(monkeypatch):
    from astral_toolkit.trade import count_view as V

    monkeypatch.setattr(V, "page", lambda img: 1)
    V._cols_seen.clear()
    assert V.spot(_inventory(), (1950, _row(1)[0] + 60), None) is not None
    monkeypatch.setattr(V, "columns", lambda img: None)  # 这张量不出四列：用上次的
    assert V.spot(_inventory(), (1950, _row(1)[0] + 60), None) is not None
    V._cols_seen.clear()
    assert V.spot(_inventory(), (1950, _row(1)[0] + 60), None) is None


def test_locked_tile():
    """带锁的「已停用」格：格子里很暗、正中一个中等亮度的小锁（样本：四周约 9、锁最亮 155）"""
    from astral_toolkit.trade import count_view as V

    img = _inventory(wide=())
    d = ImageDraw.Draw(img)
    top, bottom = _row(1)
    a, b = COLS[2]
    d.rectangle((a, top, b, bottom), fill=(9, 10, 12))
    cx, cy = (a + b) // 2, (top + bottom) // 2
    d.rectangle((cx - 8, cy - 4, cx + 8, cy + 10), fill=(155, 155, 155))
    cols = V.columns(img)
    assert V.locked(img, (cx, cy), cols) is True
    t0, b0 = _row(0)
    assert V.locked(img, (cx, (t0 + b0) // 2), cols) is False  # 普通格
    # 暗格里是亮的物品图标（不是锁）：不算
    d.rectangle((cx - 8, cy - 4, cx + 8, cy + 10), fill=(250, 250, 250))
    assert V.locked(img, (cx, cy), cols) is False
    assert V.locked(img, (1500, 600), cols) is None  # 不在格子区


def test_presenter_marks_disabled():
    from astral_toolkit.app.presenters import count as present

    q = lambda n, u: f"{n} {u}"  # noqa: E731
    r = {"zh": "铁矿", "en": "Iron", "quality": None, "qty": 1, "unit": "个"}
    assert present.item_line({**r, "disabled": True}, q).endswith("已停用")
    assert "已停用" not in present.item_line(r, q)
    items = {"k": {**r, "cells": 3, "disabled": 1}}
    assert "×3（已停用 1）" in present.hud_text("站", items, q)
    assert "已停用" not in present.hud_text("站", {"k": {**r, "cells": 3}}, q)
