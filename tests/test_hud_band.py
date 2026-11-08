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


def test_dock_top_xy_pins_top_and_dodges_di_left():
    """贴顶：Y 永远是客户区 top；盖住右上读屏区时 X 左移"""
    from astral_toolkit.app.overlay import dock_top_xy

    area = {"left": 100, "top": 50, "width": 1920, "height": 1080}
    # 不挡 DI：保持 hint，Y=50
    assert dock_top_xy(area, 400, 200) == (200, 50)
    # 挡 DI（左缘 66%）：往左让到 di_l - win_w
    di_l = 100 + int(1920 * 0.66)
    x, y = dock_top_xy(area, 768, di_l - 100)  # 右缘越过 di_l
    assert y == 50 and x == di_l - 768


def test_clamp_scroll_from_bottom():
    from astral_toolkit.app.overlay import clamp_scroll_from_bottom

    assert clamp_scroll_from_bottom(0, 500, 200) == 0
    assert clamp_scroll_from_bottom(50, 500, 200) == 50
    assert clamp_scroll_from_bottom(999, 500, 200) == 300
    assert clamp_scroll_from_bottom(-10, 100, 200) == 0


def test_paint_height_follows_content_capped_at_max():
    from astral_toolkit.app.overlay import paint

    lines = "\n".join(f"行{i}" for i in range(40))
    # 上限很高：窗口高跟内容
    img, busy, content_h = paint(
        {"导航": "标题\n" + lines},
        scale=1.0,
        viewport_w=400,
        viewport_h=5000,
        scroll_from_bottom=0,
    )
    assert img.size == (400, content_h) and not busy and content_h > 120
    # 上限 120：内容再多也只占 120，可滚
    img2, _, ch2 = paint(
        {"导航": "标题\n" + lines},
        scale=1.0,
        viewport_w=400,
        viewport_h=120,
        scroll_from_bottom=9999,
    )
    assert img2.size == (400, 120) and ch2 > 120
    # 内容很矮：不撑满上限
    img3, _, ch3 = paint(
        {"导航": "短"},
        scale=1.0,
        viewport_w=400,
        viewport_h=400,
        scroll_from_bottom=0,
    )
    assert img3.height == ch3 < 400


def test_idle_hide_after_ops():
    """有文案时显示；模拟空闲超时后隐藏；再写字又显示；note 到期不把已隐藏的再弹出来"""
    import time
    from astral_toolkit.app.overlay import IDLE_HIDE_SECS, Hud

    h = Hud.__new__(Hud)
    h.ok = False
    h.sections = {}
    h.rich = {}
    h.note_text = ""
    h._visible = False
    h._last_op_at = 0.0
    h._on_content_change(activity=True)
    assert h._drawn() is False

    h.sections = {"导航": "去 ARC-L1"}
    h._on_content_change(activity=True)
    assert h._drawn() is True and h._has_text() is True

    h._last_op_at = time.time() - IDLE_HIDE_SECS - 0.1
    if (
        h._visible
        and h._has_text()
        and h._last_op_at
        and time.time() - h._last_op_at >= IDLE_HIDE_SECS
    ):
        h._visible = False
    assert h._drawn() is False
    assert h._has_text() is True  # 文案还在，只是不画

    h.note_text = ""
    h._on_content_change(activity=False)  # 提示到期：保持隐藏
    assert h._drawn() is False

    h._on_content_change(activity=True)  # 功能再次写字
    assert h._drawn() is True

    h.sections = {}
    h._on_content_change(activity=True)
    assert h._drawn() is False


def test_set_quiet_does_not_bump_idle():
    """F6 轮询：activity=False 改字不刷新空闲计时、不重新显示"""
    import time
    from astral_toolkit.app.overlay import IDLE_HIDE_SECS, Hud

    h = Hud.__new__(Hud)
    h.ok = False
    h.sections = {}
    h.rich = {}
    h.note_text = ""
    h._visible = False
    h._last_op_at = 0.0
    h._q = None

    h.set("盘点", "盘点｜站")  # 开始：显示并记时
    assert h._drawn() is True
    started = h._last_op_at

    time.sleep(0.02)
    h.set("盘点", "盘点｜站\n铁矿 ×1", activity=False)
    assert h.sections["盘点"].endswith("铁矿 ×1")
    assert h._last_op_at == started  # 轮询不刷新计时

    h._last_op_at = time.time() - IDLE_HIDE_SECS - 0.1
    h._visible = False
    h.set("盘点", "盘点｜站\n铁矿 ×2", activity=False)
    assert h._drawn() is False  # 已隐藏不因轮询再弹
