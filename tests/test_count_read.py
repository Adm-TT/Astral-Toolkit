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


def test_title_hit_accepts_l_for_i_but_not_near_names(monkeypatch):
    """标题那截：英文行 l / I 认混、换回来精确对上的也停（实测点火 II 的英文行是「IgniteIl Missile」）；
    差一个字母的近似名不停，照旧认整块"""
    from astral_toolkit.tasks import count
    from astral_toolkit.trade import inspector, names

    monkeypatch.setattr(inspector, "_strong_canonical", lambda n: None)
    from astral_toolkit.contracts.textkeys import fold_en_loose

    key = fold_en_loose("IgniteIl Missile")
    monkeypatch.setattr(
        names, "_loose_en", lambda: {key: ("点火 II 导弹", "Ignite II Missile")}
    )
    assert count._title_hit(("点火导弹", "IgniteIl Missile")) is True
    assert count._title_hit(("点火导弹", "Ignite Missile")) is False
    assert count._title_hit(("点火导弹", "")) is False


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

    tip = (0.1, 0.3, 0.2, 0.5)

    def _frac(key, default, size=None):
        if key in ("inventory.tooltip", "count.tooltip"):
            return tip
        return default

    monkeypatch.setattr(screen_regions, "frac", _frac)
    monkeypatch.setattr(
        screen_regions,
        "has_read",
        lambda key: key in ("inventory.tooltip", "count.tooltip"),
    )
    box, title = count._tooltip_boxes((1000, 1000))
    assert box == (100, 300, 200, 500)
    assert title == (100, 300, 200, 360)
    tip = (0.1, 0.5, 0.2, 0.9)
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


# ---------------------------------------------------------------- 罗马数字不许认错（老大 11-09）
def test_roman_reads():
    from astral_toolkit.trade.names import roman_reads, roman_swap

    canon = ("点火 II 导弹", "Ignite II Missile")
    assert roman_reads(("点火I导弹", "IgniteIl Missile"), canon) == [
        (0, ["I"], ["II"]),
        (1, ["II"], ["II"]),
    ]
    assert roman_reads(
        ("逮捕者川导弹", "Arrester Ill Missile"),
        ("逮捕者 III 导弹", "Arrester III Missile"),
    ) == [
        (0, ["III"], ["III"]),
        (1, ["III"], ["III"]),
    ]
    assert roman_reads(("点火导弹", "Ignite Missile"), canon) == [
        (0, None, ["II"]),
        (1, None, ["II"]),
    ]
    xii = ("制空 XII 加农炮", "Omnisky XII Cannon")
    assert roman_reads(("制空XII加农炮", "OmniskyXllCannon"), xii)[1] == (
        1,
        ["XII"],
        ["XII"],
    )
    assert roman_reads(("狐火", "Foxfire"), ("狐火", "Foxfire")) == []
    assert (
        roman_reads(("", "AuroraMkII"), ("", "Aurora MkII TS Module")) == []
    )  # 粘在词里的不算
    assert roman_reads(None, None) == []
    assert roman_swap("Ignite II Missile", ["II"], ["I"]) == "Ignite I Missile"
    assert roman_swap("Ignite II Missile", ["II"], ["I", "I"]) == ""


def _tok(text):
    from types import SimpleNamespace

    return SimpleNamespace(text=text)


def test_strict_numeral_marks_unsure(monkeypatch):
    from astral_toolkit.tasks import count

    monkeypatch.setattr(
        count, "_library_size", lambda en: {"Ignite II Missile": 2}.get(en)
    )
    base = {
        "zh": "点火 II 导弹",
        "en": "Ignite II Missile",
        "sure": True,
        "canon": ("点火 II 导弹", "Ignite II Missile"),
        "raw": ("点火II导弹", "IgniteIl Missile"),
        "tokens": [_tok("点火II导弹"), _tok("尺寸：2")],
    }
    none = lambda en: False  # noqa: E731
    has_one = lambda en: en == "Ignite I Missile"  # noqa: E731

    def run(exists=none, **kw):
        return count._strict_numeral({**base, **kw}, exists=exists)

    assert run()["sure"] is True
    # 英文行少一个 I：不认
    r = run(raw=("点火II导弹", "Ignite I Missile"))
    assert r["sure"] is False and "英文行" in r["unsure"]
    # 中文行少一个 I（样本里真这样）：库里没有点火 I → 中文认字毛病，照认；库里真有点火 I → 不认
    assert run(raw=("点火I导弹", "IgniteIl Missile"))["sure"] is True
    r = run(has_one, raw=("点火I导弹", "IgniteIl Missile"))
    assert r["sure"] is False and "中文行" in r["unsure"]
    # 英文行找不到数字：中文行说了算
    assert run(raw=("点火II导弹", "IgniteMissle"))["sure"] is True
    assert run(raw=("点火I导弹", "IgniteMissle"))["sure"] is False
    r = run(raw=("点火导弹", "IgniteMissle"))
    assert r["sure"] is False and "没认出来" in r["unsure"]
    # 尺寸对不上
    r = run(tokens=[_tok("尺寸：3")])
    assert r["sure"] is False and "尺寸" in r["unsure"]
    assert run(tokens=[])["sure"] is True  # 说明框没有尺寸行：只看数字
    # 没罗马数字的不动；本来就没认准的原样
    plain = {
        "zh": "狐火",
        "en": "Foxfire",
        "sure": True,
        "canon": ("狐火", "Foxfire"),
        "raw": ("狐火", "Foxfire"),
        "tokens": [_tok("尺寸：9")],
    }
    assert count._strict_numeral(plain) is plain
    assert count._strict_numeral(None) is None
    weak = {**base, "sure": False}
    assert count._strict_numeral(weak) is weak


def test_tooltip_size():
    from astral_toolkit.tasks import count

    assert count._tooltip_size([_tok("体积：31250uSCU"), _tok("尺寸：2")]) == 2
    assert count._tooltip_size([_tok("Size: 4")]) == 4
    assert count._tooltip_size([_tok("尺寸")]) is None
    assert count._tooltip_size(None) is None
