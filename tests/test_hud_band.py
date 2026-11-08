"""悬浮窗客户区视口 / 滚动夹紧（2026-11-08）"""


def test_band_size_and_origin():
    from astral_toolkit.app.overlay import band_origin, band_size

    assert band_size(1920, 1080) == (768, 216)
    assert band_origin({"left": 100, "top": 40, "width": 1920, "height": 1080}) == (
        100 + 576,
        40,
    )


def test_clamp_scroll_from_bottom():
    from astral_toolkit.app.overlay import clamp_scroll_from_bottom

    assert clamp_scroll_from_bottom(0, 500, 200) == 0
    assert clamp_scroll_from_bottom(50, 500, 200) == 50
    assert clamp_scroll_from_bottom(999, 500, 200) == 300
    assert clamp_scroll_from_bottom(-10, 100, 200) == 0


def test_paint_viewport_pins_bottom():
    from astral_toolkit.app.overlay import paint

    lines = "\n".join(f"行{i}" for i in range(40))
    img, busy, content_h = paint(
        {"导航": "标题\n" + lines},
        scale=1.0,
        viewport_w=400,
        viewport_h=120,
        scroll_from_bottom=0,
    )
    assert img.size == (400, 120) and not busy and content_h > 120
    img2, _, _ = paint(
        {"导航": "标题\n" + lines},
        scale=1.0,
        viewport_w=400,
        viewport_h=120,
        scroll_from_bottom=9999,
    )
    assert img2.size == (400, 120)
