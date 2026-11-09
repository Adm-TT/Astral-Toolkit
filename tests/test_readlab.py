"""读屏开发工作台（tools/readlab）：统一接口、本机服务、批量报告。假图，不读真截图、不碰真实设置"""

from PIL import Image

from astral_toolkit.core import screen_regions
from tests.test_cell_grid import _inventory
from tools.readlab import features

KEYS = ("count", "hover", "mining", "radar", "nav")


def test_every_feature_returns_a_result_on_a_blank_image():
    img = Image.new("RGB", (2560, 1440))
    for key in KEYS:
        for batch in (False, True):
            r = features.run(key, img, (1280, 720), batch=batch)
            assert isinstance(r, features.Result) and r.ms >= 0, key
            assert r.error == "", (key, r.error)
            assert r.lines, key  # 认不出也要说一句


def test_errors_are_captured(monkeypatch):
    from astral_toolkit.mining import screen

    monkeypatch.setattr(screen, "analyse", lambda img: 1 / 0)
    r = features.run("mining", Image.new("RGB", (2560, 1440)), None, batch=True)
    assert "ZeroDivisionError" in r.error
    assert features.run(
        "没这个功能", Image.new("RGB", (100, 100)), None, batch=True
    ).error


def test_count_marks_the_cell_box():
    r = features.run("count", _inventory(), (2240, 700), batch=False)
    assert any(s.color == "hit" and abs(s.box[0] - 2171) <= 4 for s in r.shapes), (
        r.shapes
    )
    gap = features.run("count", _inventory(), (2019, 700), batch=False)
    assert any("缝" in line for line in gap.lines)


def test_shapes_use_known_colors():
    for key in KEYS:
        r = features.run(key, _inventory(), (2240, 700), batch=False)
        assert all(s.color in features.COLORS for s in r.shapes), key


def test_regions_listed_exist():
    keys = set(screen_regions.load()["regions"])
    for f in features.FEATURES.values():
        assert f.regions and set(f.regions) <= keys, f.key


def test_non_16_9_images_still_work():
    for size in ((1280, 800), (3440, 1440), (1280, 720)):
        r = features.run(
            "hover", Image.new("RGB", size), (size[0] // 2, size[1] // 2), batch=False
        )
        assert r.error == "", (size, r.error)


def test_report_lists_every_row_and_errors(tmp_path):
    from tools.readlab import report

    img = Image.new("RGB", (2560, 1440))
    ok = features.Result(
        shapes=[features.Shape((10, 10, 200, 200), "框", "hit")],
        lines=["认出 <甲>"],
        ms=12,
    )
    bad = features.Result(error="ZeroDivisionError: x", ms=3)
    rows = [
        ("a.png", (2560, 1440), ok, img),
        ("b.png", (3440, 1440), bad, img),
        ("c.png", (2560, 1440), ok, img),
    ]
    page = report.write("count", rows, tmp_path)
    text = page.read_text(encoding="utf-8")
    assert text.count("<img") == 3
    assert "出错 1 张" in text and "21:9 1 张" in text and "16:9 2 张" in text
    assert "&lt;甲&gt;" in text  # 内容转义
    pics = page.with_suffix("")
    assert len(list(pics.glob("*.jpg"))) == 3
