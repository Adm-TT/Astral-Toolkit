"""悬浮窗客户区视口 / 滚动夹紧（2026-11-08）"""


def test_band_width_height_and_origin():
    from astral_toolkit.app.overlay import band_max_height, band_origin, band_width

    assert band_width(1920) == 768
    assert band_max_height(1080) == 216
    # 默认落点：客户区左 30%、贴顶
    assert band_origin({"left": 100, "top": 40, "width": 1920, "height": 1080}) == (
        100 + 576,
        40,
    )


def test_keep_off_box_moves_the_panel_away_from_the_position_readout():
    from astral_toolkit.app.overlay import keep_off_box

    area = {"left": 100, "top": 40, "width": 1920, "height": 1080}
    box = (0.66, 0.0, 1.0, 0.22)  # 右上角读位置那块：屏幕上 x 1367~2020、y 40~277
    # 小号 2026-11-14 那次：左缘 713、宽 768，右边压住了那块 → 往左挪到它左边
    assert keep_off_box(100 + 713, 40, 768, 185, area, box) == (1367 - 4 - 768, 40)
    # 默认落点（左 30%、宽 40%）右边也压着 4% → 同样让开
    assert keep_off_box(100 + 576, 40, 768, 185, area, box)[0] == 595
    # 没碰到：原样（在它左边、在它下面）
    assert keep_off_box(300, 40, 768, 185, area, box) == (300, 40)
    assert keep_off_box(1500, 400, 400, 100, area, box) == (1500, 400)
    # 左边放不下（窗比那块左边的空地还宽）→ 挪到它下面
    assert keep_off_box(900, 60, 1400, 100, area, box) == (900, 277 + 4)


def test_clamp_scroll_from_bottom():
    from astral_toolkit.app.overlay import clamp_scroll_from_bottom

    assert clamp_scroll_from_bottom(0, 500, 200) == 0
    assert clamp_scroll_from_bottom(50, 500, 200) == 50
    assert clamp_scroll_from_bottom(999, 500, 200) == 300
    assert clamp_scroll_from_bottom(-10, 100, 200) == 0


def test_paint_height_follows_content_capped_at_max():
    from astral_toolkit.app.overlay import chrome_height, paint

    bar = chrome_height(1.0)
    lines = "\n".join(f"行{i}" for i in range(40))
    # 上限很高：正文高跟内容，整图再加顶栏
    img, busy, content_h = paint(
        {"导航": "标题\n" + lines},
        scale=1.0,
        viewport_w=400,
        viewport_h=5000,
        scroll_from_bottom=0,
    )
    assert img.size == (400, content_h + bar) and not busy and content_h > 120
    # 上限 120：正文再多也只占 120，可滚；整图 + 顶栏
    img2, _, ch2 = paint(
        {"导航": "标题\n" + lines},
        scale=1.0,
        viewport_w=400,
        viewport_h=120,
        scroll_from_bottom=9999,
    )
    assert img2.size == (400, 120 + bar) and ch2 > 120
    # 内容很矮：不撑满上限
    img3, _, ch3 = paint(
        {"导航": "短"},
        scale=1.0,
        viewport_w=400,
        viewport_h=400,
        scroll_from_bottom=0,
    )
    assert img3.height == ch3 + bar and ch3 < 400


def test_dismiss_clears_all_and_hides():
    """点 X：分区与短提示清空，并藏起"""
    from astral_toolkit.app.overlay import Hud

    h = Hud.__new__(Hud)
    h.ok = False
    h.sections = {"物品": "JS-500", "导航": "去 ARC-L1"}
    h.rich = {"物品": {"x": 1}}
    h.note_text = "提示一下"
    h._note_seq = 3
    h._visible = True
    h.dismiss()
    assert h.sections == {} and h.rich == {} and h.note_text == ""
    assert h._note_seq == 4 and h._drawn() is False


def test_chrome_matches_card_width():
    """顶栏与单列文案卡片同宽（不铺满视口）"""
    from astral_toolkit.app.overlay import BASE_W, MARGIN, PAD_X, chrome_geom

    s, vw = 1.0, 768
    card_inner = min(
        (BASE_W - 2 * PAD_X) * s, max(40.0, vw - 2 * MARGIN - 2 * PAD_X * s)
    )
    card_w = int(card_inner + 2 * PAD_X * s)
    x, w, _ = chrome_geom(s, vw, card_w)
    assert x == MARGIN and w == card_w < vw


def test_visible_while_has_text():
    """有文案就显示，全部清空才隐藏；不再空闲超时自动藏"""
    from astral_toolkit.app.overlay import Hud

    h = Hud.__new__(Hud)
    h.ok = False
    h.sections = {}
    h.rich = {}
    h.note_text = ""
    h._visible = False
    h._on_content_change(activity=True)
    assert h._drawn() is False

    h.sections = {"导航": "去 ARC-L1"}
    h._on_content_change(activity=True)
    assert h._drawn() is True and h._has_text() is True

    # 即使很久没操作，有文案仍显示（空闲隐藏已取消）
    h._on_content_change(activity=False)
    assert h._drawn() is True

    h.sections = {}
    h._on_content_change(activity=True)
    assert h._drawn() is False


def test_set_quiet_still_updates_text():
    """F6 轮询 activity=False：改字照旧；有文案时保持显示"""
    from astral_toolkit.app.overlay import Hud

    import queue

    h = Hud.__new__(Hud)
    h.ok = False
    h.sections = {}
    h.rich = {}
    h.note_text = ""
    h._visible = False
    h._q = queue.Queue()

    h.set("盘点", "盘点｜站")
    assert h._drawn() is True

    h.set("盘点", "盘点｜站\n铁矿 ×1", activity=False)
    assert h.sections["盘点"].endswith("铁矿 ×1")
    assert h._drawn() is True

    h.set("盘点", "盘点｜站\n铁矿 ×2", activity=False)
    assert h._drawn() is True
