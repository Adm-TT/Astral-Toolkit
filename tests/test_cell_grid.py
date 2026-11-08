"""trade/cell_grid：在画出来的假仓库图上找鼠标所在格的框（不用真截图）。

假图照 2560×1440 真截图量出来的样子画：格子之间有缝，列是竖直的，从左到右越来越宽，
格子有一圈亮边、里面比底色亮一点。
"""

from PIL import Image, ImageDraw

from astral_toolkit.trade import cell_grid

COLS = [(1880, 136), (2023, 141), (2171, 146), (2324, 152)]  # (左边, 宽)
ROWS = [352, 489, 630, 770]  # 上边；格高 125
H = 125


def _inventory(black=None):
    img = Image.new("RGB", (2560, 1440), (10, 10, 10))
    d = ImageDraw.Draw(img)
    for x, w in COLS:
        for y in ROWS:
            d.rectangle(
                (x, y, x + w, y + H), fill=(22, 22, 22), outline=(70, 70, 70), width=2
            )
    if black:
        d.rectangle(black, fill=(0, 0, 0))  # 截图时悬浮窗那块被涂黑
    return img


def _near(box, want, tol=4):
    return box is not None and all(abs(a - b) <= tol for a, b in zip(box, want))


def test_finds_the_cell_under_the_cursor():
    img = _inventory()
    box = cell_grid.cell_box(img, (2240, 700))
    assert _near(box, (2171, 630, 2171 + 146, 630 + H)), box
    # 最右一列更宽，也找得准
    box = cell_grid.cell_box(img, (2400, 400))
    assert _near(box, (2324, 352, 2324 + 152, 352 + H)), box


def test_tall_lines_inside_the_icon_are_not_cell_edges():
    """格子里的物品图标有高竖线（比半格高、但不贯穿整格）：不能当成格子边，否则同一格左右两半给出两个框"""
    img = _inventory()
    d = ImageDraw.Draw(img)
    x, w = COLS[3]
    for lx in (x + 45, x + w - 40):
        d.line((lx, 352 + 20, lx, 352 + 100), fill=(90, 90, 90), width=2)
    want = (x, 352, x + w, 352 + H)
    assert _near(cell_grid.cell_box(img, (x + 20, 400)), want)
    assert _near(cell_grid.cell_box(img, (x + w - 15, 400)), want)


def test_inside_with_margin():
    box = (100, 100, 200, 200)
    assert cell_grid.inside(box, (150, 150)) and cell_grid.inside(box, (202, 98))
    assert not cell_grid.inside(box, (210, 150))


def test_same_cell_from_far_apart_spots_overlaps_and_neighbours_do_not():
    """同一格里从左上挪到右下（离得超过 0.45 格）还是同一格；挨着的两格不重叠"""
    img = _inventory()
    a = cell_grid.cell_box(img, (2030, 640))
    b = cell_grid.cell_box(img, (2155, 748))
    c = cell_grid.cell_box(img, (2180, 640))
    assert a and b and c
    assert cell_grid.overlap(a, b) > 0.9
    assert cell_grid.overlap(a, c) == 0.0


def test_no_box_in_the_gap_or_under_the_blacked_out_overlay():
    """鼠标停在两格之间的缝上、或者那块被悬浮窗涂黑了：找不到框，交给调用方退回别的判断"""
    assert cell_grid.cell_box(_inventory(), (2019, 700)) is None
    img = _inventory(black=(2150, 600, 2560, 900))
    assert cell_grid.cell_box(img, (2240, 700)) is None
    # 只涂黑了下半截：露出来的那截太矮，不当一格（不然悬浮窗挪开后同一格会对不上）
    img = _inventory(black=(2150, 700, 2560, 900))
    assert cell_grid.cell_box(img, (2240, 660)) is None


def test_edge_of_the_blacked_out_overlay_is_not_a_cell_edge():
    """涂黑区的边沿也是一条长竖边；高度正好像一格时，不能和格子左边拼成一个错框"""
    img = _inventory(black=(2171 + 120, 620, 2560, 760))
    assert cell_grid.cell_box(img, (2240, 700)) is None


def test_edges_that_never_break_are_not_a_cell():
    """两条竖边上下一路没断开（面板边框那种，不是格子）：高过一格就不当格子"""
    img = Image.new("RGB", (2560, 1440), (10, 10, 10))
    d = ImageDraw.Draw(img)
    d.rectangle(
        (2171, 200, 2317, 1200), fill=(22, 22, 22), outline=(70, 70, 70), width=2
    )
    assert cell_grid.cell_box(img, (2240, 700)) is None


def test_cursor_off_image_or_on_empty_screen():
    img = _inventory()
    assert cell_grid.cell_box(img, (3000, 700)) is None
    assert cell_grid.cell_box(Image.new("RGB", (2560, 1440)), (1200, 700)) is None


def test_scales_with_resolution():
    """1920×1080：格子跟着缩小，照样找得到"""
    img = _inventory().resize((1920, 1080))
    box = cell_grid.cell_box(img, (int(2240 * 0.75), int(700 * 0.75)))
    assert _near(
        box,
        (int(2171 * 0.75), int(630 * 0.75), int(2317 * 0.75), int(755 * 0.75)),
        tol=5,
    ), box
