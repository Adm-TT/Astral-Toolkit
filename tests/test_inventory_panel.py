"""物品栏面板 ROI：resolve 左右仓、角标相对框、1K/4K 等比缩放"""

from astral_toolkit.trade import inventory_panel as P


def test_resolve_left_right_outside():
    size = (2560, 1440)
    left = P.resolve((0.12 * 2560, 0.40 * 1440), size)
    assert left is not None and left.side == "left"
    right = P.resolve((0.85 * 2560, 0.40 * 1440), size)
    assert right is not None and right.side == "right"
    assert P.resolve((0.50 * 2560, 0.40 * 1440), size) is None


def test_resolve_scales_1080_and_4k():
    """同一相对光标在 1080 / 1440 / 4K 上命中同一侧"""
    for dst in ((1920, 1080), (2560, 1440), (3840, 2160)):
        W, H = dst
        panel = P.resolve((0.85 * W, 0.45 * H), dst)
        assert panel is not None and panel.side == "right"
        assert abs(panel.grid[0] / W - 0.7336) < 0.002


def test_map_cell_roi_corner_c_and_clamp():
    cell = (100, 200, 200, 300)  # 100×100
    rel = P.CELL_QUALITY  # (-0.10, -0.12, 0.48, 0.28)
    box = P.map_cell_roi(cell, rel, (1000, 1000))
    # 左上越出格：x0=100-10=90, y0=200-12=188
    assert box == (90, 188, 148, 228)
    # clamp 到图边
    tiny = P.map_cell_roi(cell, (-0.5, -0.5, 0.2, 0.2), (120, 220))
    assert tiny[0] >= 0 and tiny[1] >= 0
    assert tiny[2] <= 120 and tiny[3] <= 220


def test_cell_badge_frac_from_defaults():
    q = P.cell_badge_frac("quality")
    n = P.cell_badge_frac("stack")
    assert q[0] < 0 and n[2] > 1.0
