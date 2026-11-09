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


def test_faint_edge_on_one_side_still_gives_the_cell():
    """面板半透明，背后场景亮的地方格子边很淡、只剩一截（老大 11-09 样本第一排第一格左边只连着 77 像素）：
    由贯穿整格的右边定上下，淡的左边在这一格高度里有约半格就认；鼠标停在淡掉那一截旁边也一样"""
    img = _inventory()
    d = ImageDraw.Draw(img)
    x, w = COLS[0]
    fade = (16, 16, 16)  # 盖住格子边、和两边只差 6 个灰度：看不出边
    d.rectangle((x - 6, 352 - 3, x + 6, 352 + 60), fill=fade)
    assert _near(cell_grid.cell_box(img, (x + 60, 360)), (x, 352, x + w, 352 + H))
    # 两边都只剩一小截就不认
    for ex in (x, x + w):
        d.rectangle((ex - 6, 352 - 3, ex + 6, 352 + 90), fill=fade)
    assert cell_grid.cell_box(img, (x + 60, 420)) is None


def test_panel_frame_next_to_a_faint_edge_is_not_taken():
    """老大 11-09 样本第四排第一格：格子左边淡了一截，旁边 10 像素外的面板边框断开处正好约一格高、
    但上下和格子错开。要挑左右两条边上下对得齐的那个框，不能拿面板边框拼出一个跨两排的框"""
    img = _inventory()
    d = ImageDraw.Draw(img)
    x, w = COLS[0]
    top = ROWS[3]
    d.line(
        (x - 11, top - 37, x - 11, top + 96), fill=(90, 90, 90), width=2
    )  # 面板边框断开的一截
    d.rectangle(
        (x - 6, top - 3, x + 6, top + 30), fill=(16, 16, 16)
    )  # 格子左边上面淡掉
    assert _near(cell_grid.cell_box(img, (x + 70, top + 60)), (x, top, x + w, top + H))


def test_in_gap_only_between_two_cells():
    img = _inventory()
    (xa, wa), (xb, _) = COLS[0], COLS[1]
    assert cell_grid.in_gap(img, ((xa + wa + xb) // 2, 400))  # 第一、二列之间的竖缝
    assert cell_grid.in_gap(
        img, (1950, (ROWS[0] + H + ROWS[1]) // 2)
    )  # 第一、二排之间的横缝
    assert cell_grid.in_gap(
        img, (xa + wa + 2, 400)
    )  # 竖缝里贴着左格（审查 11-09：只挪一条缝宽探不到对面）
    assert cell_grid.in_gap(img, (xa + wa + 4, ROWS[0] + H + 4))  # 两条缝交叉的角上
    assert not cell_grid.in_gap(img, (1950, 400))  # 格子中间
    assert not cell_grid.in_gap(img, (1700, 400))  # 仓库外面


def test_icon_line_before_the_real_edge_does_not_shrink_the_box():
    """最外一列：图标里有一条比半格还高的竖线、离格子右边约一格宽，不能拿它当左边把框缩窄（审查 11-09）"""
    img = _inventory()
    d = ImageDraw.Draw(img)
    x, w = COLS[0]
    top = ROWS[1]
    d.line((x + 20, top + 30, x + 20, top + 100), fill=(90, 90, 90), width=2)
    assert _near(cell_grid.cell_box(img, (x + 70, top + 60)), (x, top, x + w, top + H))


def test_inside_margin_is_less_than_half_the_narrowest_gap():
    """框四边只放宽约 2%（贴着边停还算这一格）；缝中间那一点不能同时算进左右两格（审查 11-09：
    放宽到半条缝时，缝里停的一次会把左右两格都当成「同一格」，同样的东西两格只记一格）"""
    a = (1880, 345, 2016, 467)  # 第一排第一格
    b = (2023, 345, 2164, 467)  # 隔着 7 像素的缝，下一格
    assert cell_grid.inside(a, (1950, 400)) and cell_grid.inside(a, (2018, 350))
    assert not (cell_grid.inside(a, (2019, 350)) and cell_grid.inside(b, (2019, 350)))
    assert not cell_grid.inside(a, (2021, 350)) and not cell_grid.inside(a, (1950, 472))


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
