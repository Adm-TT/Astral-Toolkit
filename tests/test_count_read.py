"""F6 盘点认说明框只在区域文件的 count.tooltip 里认（2026-11-09）：先标题那截、再整块，不走 F8 竖带、不整屏"""

from PIL import Image


def _setup(monkeypatch, strong):
    from astral_toolkit import ocr
    from astral_toolkit.trade import inspector

    calls = {"ocr": [], "inspect": None}

    def recognize(crop, urgent=False, offset=(0, 0), native=False):
        calls["ocr"].append((offset, crop.size, native))
        return [("字", offset)]

    def inspect(
        img,
        cursor,
        tokens=None,
        where=None,
        craft_override=False,
        whole_screen=True,
        body_box=None,
    ):
        calls["inspect"] = dict(
            tokens=tokens, where=where, craft=craft_override, body_box=body_box
        )
        return {"zh": "甲", "en": "A"}

    monkeypatch.setattr(ocr, "recognize", recognize)
    monkeypatch.setattr(inspector, "tooltip_pick", lambda t, c, i: (("甲", "A"), True))
    monkeypatch.setattr(inspector, "_strong_canonical", lambda n: strong)
    monkeypatch.setattr(inspector, "inspect_item", inspect)

    def no_whole(*a, **k):
        raise AssertionError("盘点不该走 F8 的竖带 / 整屏")

    monkeypatch.setattr(inspector, "_read_tooltip", no_whole)
    return calls


def test_title_hit_reads_only_title_strip(monkeypatch):
    from astral_toolkit.tasks import count

    calls = _setup(monkeypatch, strong=True)
    img = Image.new("RGB", (2560, 1440))
    assert count._read_item(img, (2100, 600)) == {"zh": "甲", "en": "A"}
    box, title = count._tooltip_boxes(img.size)
    assert title is not None
    assert (
        len(calls["ocr"]) == 1
        and calls["ocr"][0][0] == title[:2]
        and calls["ocr"][0][2] is True
    )
    assert calls["inspect"]["where"] == "盘点说明框@title"
    assert calls["inspect"]["body_box"] == box and calls["inspect"]["craft"] is True
    # 标题那截在 count.tooltip 里面、高度是屏高 24%~36%
    assert box[0] == title[0] and box[2] == title[2]
    assert title[1] == int(1440 * 0.24) and title[3] == int(1440 * 0.36)


def test_title_miss_reads_whole_region(monkeypatch):
    from astral_toolkit.tasks import count

    calls = _setup(monkeypatch, strong=False)
    img = Image.new("RGB", (2560, 1440))
    count._read_item(img, (2100, 600))
    box, title = count._tooltip_boxes(img.size)
    assert title is not None
    assert [c[0] for c in calls["ocr"]] == [title[:2], box[:2]]
    assert calls["ocr"][1][1] == (box[2] - box[0], box[3] - box[1])
    assert calls["inspect"]["where"] == "盘点说明框"


def test_region_follows_screen_regions(monkeypatch):
    from astral_toolkit.core import screen_regions
    from astral_toolkit.tasks import count

    monkeypatch.setattr(
        screen_regions,
        "frac",
        lambda key, default, size=None: (
            (0.1, 0.3, 0.2, 0.5) if key == "count.tooltip" else default
        ),
    )
    box, title = count._tooltip_boxes((1000, 1000))
    assert box == (100, 300, 200, 500)
    assert title == (100, 300, 200, 360)
    monkeypatch.setattr(
        screen_regions, "frac", lambda key, default, size=None: (0.1, 0.5, 0.2, 0.9)
    )
    assert count._tooltip_boxes((1000, 1000))[1] is None  # 区域在标题那截下面：只认整块


def test_body_rescan_uses_given_box(monkeypatch):
    """标题那截命中的制造品补认加成行：给了框就认那块，不按 F8 竖带"""
    from astral_toolkit import ocr
    from astral_toolkit.trade import inspector

    seen = []
    monkeypatch.setattr(
        ocr,
        "recognize",
        lambda crop, urgent=False, offset=(0, 0), native=False: (
            seen.append(offset) or [("x", offset)]
        ),
    )
    img = Image.new("RGB", (2560, 1440))
    assert inspector._tooltip_body_tokens(
        img, (10, 10), "盘点说明框@title", (5, 6, 50, 60)
    )
    assert seen == [(5, 6)]
    assert (
        inspector._tooltip_body_tokens(img, (10, 10), "盘点说明框", (5, 6, 50, 60))
        is None
    )
    assert (
        inspector._tooltip_body_tokens(img, (10, 10), "盘点说明框@title") is None
    )  # 不给框、标签又不是 F8 的：不补
