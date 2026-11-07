"""F8 悬停识别自适应区域与兜底流程测试

2026-11-04 F8 标题带方案（docs/superpowers/specs/2026-11-04-f8-title-band-ocr.md）：
识别顺序改成「高度阶段 × 宽度条带」的级联——标题带 24%~36%（native=True，主路径）
→ 说明框带 24%~70% → 全高 0%~100% → 整屏兜底；标题带要「高把握库命中」（汉化包 / 矿物表精确对上）才停。
"""

import unittest

from astral_toolkit.ocr import OcrToken
from astral_toolkit.trade.inspector import (
    get_hover_regions,
    _read_tooltip,
    HOVER_REGIONS,  # noqa: F401
)


class MockImage:
    def __init__(self, width=1000, height=1000):
        self.size = (width, height)
        self.width = width
        self.height = height

    def crop(self, box):
        w = box[2] - box[0]
        h = box[3] - box[1]
        return MockImage(w, h)


class TestHoverRegions(unittest.TestCase):
    def test_cursor_regions_partition(self):
        w = 1000
        # 1. 0% ~ 30% -> 首选 30%~50%，备选 30%~70%
        r_0_30 = get_hover_regions((100, 500), w)
        self.assertEqual(len(r_0_30), 2)
        self.assertEqual(r_0_30[0][:4], (0.30, 0.0, 0.50, 1.0))
        self.assertEqual(r_0_30[0][4], "30-50%")
        self.assertEqual(r_0_30[1][:4], (0.30, 0.0, 0.70, 1.0))
        self.assertEqual(r_0_30[1][4], "30-70%")

        # 2. 30% ~ 50% -> 首选 50%~70%，备选 30%~70%
        r_30_50 = get_hover_regions((400, 500), w)
        self.assertEqual(len(r_30_50), 2)
        self.assertEqual(r_30_50[0][:4], (0.50, 0.0, 0.70, 1.0))
        self.assertEqual(r_30_50[0][4], "50-70%")
        self.assertEqual(r_30_50[1][:4], (0.30, 0.0, 0.70, 1.0))
        self.assertEqual(r_30_50[1][4], "30-70%")

        # 3. 50% ~ 70% -> 首选 30%~50%，备选 30%~70%
        r_50_70 = get_hover_regions((600, 500), w)
        self.assertEqual(len(r_50_70), 2)
        self.assertEqual(r_50_70[0][:4], (0.30, 0.0, 0.50, 1.0))
        self.assertEqual(r_50_70[0][4], "30-50%")
        self.assertEqual(r_50_70[1][:4], (0.30, 0.0, 0.70, 1.0))
        self.assertEqual(r_50_70[1][4], "30-70%")

        # 4. 70% ~ 100% -> 首选 50%~70%，备选 30%~70%
        r_70_100 = get_hover_regions((800, 500), w)
        self.assertEqual(len(r_70_100), 2)
        self.assertEqual(r_70_100[0][:4], (0.50, 0.0, 0.70, 1.0))
        self.assertEqual(r_70_100[0][4], "50-70%")
        self.assertEqual(r_70_100[1][:4], (0.30, 0.0, 0.70, 1.0))
        self.assertEqual(r_70_100[1][4], "30-70%")

        # 5. 异常鼠标 (None 或越界) -> 中间 30%~70%
        r_none = get_hover_regions(None, w)
        self.assertEqual(len(r_none), 1)
        self.assertEqual(r_none[0][:4], (0.30, 0.0, 0.70, 1.0))
        self.assertEqual(r_none[0][4], "中间")

        r_out = get_hover_regions((-100, 500), w)
        self.assertEqual(len(r_out), 1)
        self.assertEqual(r_out[0][:4], (0.30, 0.0, 0.70, 1.0))
        self.assertEqual(r_out[0][4], "中间")


# 一整套说明框：中文名 + 英文名 + 锚点行（体积）
_ITEM = [
    OcrToken("实准枪口补偿器2", 90, (350, 300, 100, 18)),
    OcrToken("VeraCompensator2", 90, (350, 324, 100, 18)),
    OcrToken("体积：20uSCU", 90, (350, 348, 100, 18)),
]
# 认错一个字的同一件物品（中文弱模糊、英文也不精确）
_WEAK = [
    OcrToken("实准枪口补偿器", 90, (350, 300, 100, 18)),
    OcrToken("VeraCompensato", 90, (350, 324, 100, 18)),
    OcrToken("体积：20uSCU", 90, (350, 348, 100, 18)),
]


def _fake_ocr(monkeypatch, script):
    """假识别：按调用次序返回 script 里的 token 列表（用完就一直返回最后一个）。

    记下每次的 (offset, native, 裁切图尺寸)——尺寸能看出这一档是标题带 (H*0.12) 还是说明框带 (H*0.46) 还是全高。
    """
    from astral_toolkit import ocr

    calls = []

    def fake(img, urgent=False, offset=(0, 0), native=False):
        calls.append((offset, native, img.size))
        return script[min(len(calls) - 1, len(script) - 1)]

    monkeypatch.setattr(ocr, "recognize", fake)
    return calls


def _names(monkeypatch, pairs):
    """把汉化包名字表换成一小组，canonical / canonical_exact 都只用它（不受本机数据包影响）"""
    from astral_toolkit.trade import names

    t = dict(pairs)
    zh_map = {names._norm_zh(zh): (zh, en) for zh, en in t.items()}
    en_map = {names._fold_en(en): (zh, en) for zh, en in t.items()}
    monkeypatch.setattr(names, "table", lambda: t)
    monkeypatch.setattr(names, "_index", lambda: (zh_map, en_map))


class TestReadTooltipExecution(unittest.TestCase):
    def setUp(self):
        from astral_toolkit import ocr
        from astral_toolkit.trade import names

        self.ocr = ocr
        self._orig_recognize = ocr.recognize
        # 汉化包名字表换成一小组：本机没装数据包时 names.table() 是空的，
        # 「标题带高把握库命中就停」这条路径测不出来
        t = {"实准枪口补偿器2": "VeraCompensator2"}
        self._orig_table, self._orig_index = names.table, names._index
        names.table = lambda: t
        names._index = lambda: (
            {names._norm_zh(zh): (zh, en) for zh, en in t.items()},
            {names._fold_en(en): (zh, en) for zh, en in t.items()},
        )
        self.img = MockImage(1000, 1000)

    def tearDown(self):
        from astral_toolkit.trade import names

        self.ocr.recognize = self._orig_recognize
        names.table, names._index = self._orig_table, self._orig_index

    def test_first_stage_hit(self):
        """标题带（24%~36%，native=True）命中高把握库命中：只认这一次就停"""
        calls = []

        def fake_recognize(img, urgent=False, offset=(0, 0), native=False):
            calls.append((offset, native, img.size))
            # 在 30%~50% 区域（x=300~500）生成有效说明框
            return [
                OcrToken("实准枪口补偿器2", 90, (350, 300, 100, 18)),
                OcrToken("VeraCompensator2", 90, (350, 324, 100, 18)),
                OcrToken("体积：20uSCU", 90, (350, 348, 100, 18)),
            ]

        self.ocr.recognize = fake_recognize
        toks, name, where = _read_tooltip(self.img, (100, 500))  # 鼠标在 10%
        self.assertEqual(where, "30-50%@title")
        self.assertEqual(name, ("实准枪口补偿器2", "VeraCompensator2"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], ((300, 240), True, (200, 120)))  # 标题带顶 0.24H

    def test_second_stage_hit(self):
        """标题带没认到，说明框带（24%~70%）看到完整说明框：停在这一档，不走到全高和整屏"""
        calls = []

        def fake_recognize(img, urgent=False, offset=(0, 0), native=False):
            calls.append((offset, native, img.size))
            if len(calls) <= 2:  # 标题带的两个宽度条带
                return []
            return [
                OcrToken("实准枪口补偿器2", 90, (350, 300, 100, 18)),
                OcrToken("VeraCompensator2", 90, (350, 324, 100, 18)),
                OcrToken("体积：20uSCU", 90, (350, 348, 100, 18)),
            ]

        self.ocr.recognize = fake_recognize
        toks, name, where = _read_tooltip(self.img, (100, 500))  # 鼠标在 10%
        self.assertEqual(where, "30-50%@body")
        self.assertEqual(name, ("实准枪口补偿器2", "VeraCompensator2"))
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[2], ((300, 240), False, (200, 460)))  # 说明框带 24%~70%

    def test_fullscreen_fallback(self):
        """标题带、说明框带、全高都没认到，整屏兜底命中"""
        calls = []

        def fake_recognize(img, urgent=False, offset=(0, 0), native=False):
            calls.append((offset, native, img.size))
            if len(calls) <= 6:  # 3 个高度阶段 × 2 个宽度条带
                return []
            return [
                OcrToken("实准枪口补偿器2", 90, (350, 300, 100, 18)),
                OcrToken("VeraCompensator2", 90, (350, 324, 100, 18)),
                OcrToken("体积：20uSCU", 90, (350, 348, 100, 18)),
            ]

        self.ocr.recognize = fake_recognize
        toks, name, where = _read_tooltip(self.img, (100, 500))  # 鼠标在 10%
        self.assertEqual(where, "整屏")
        self.assertEqual(name, ("实准枪口补偿器2", "VeraCompensator2"))
        self.assertEqual(len(calls), 7)
        self.assertEqual(calls[-1][2], (1000, 1000))  # 整屏是整张图


def test_cascade_order_and_cockpit_guard(monkeypatch):
    """级联顺序：标题带 2 个宽度 → 说明框带 2 个 → 全高 2 个（native 只有标题带是 True）；
    鼠标在中间带、一直没见到说明框特征：多半在驾驶位，不整屏"""
    _names(monkeypatch, {})
    calls = _fake_ocr(monkeypatch, [[OcrToken("SCM 220", 90, (60, 300, 60, 18))]])
    toks, name, where = _read_tooltip(MockImage(1000, 1000), (500, 500))
    assert name is None
    assert calls == [
        ((300, 240), True, (200, 120)),  # 标题带 30-50%
        ((300, 240), True, (400, 120)),  # 标题带 30-70%
        ((300, 240), False, (200, 460)),  # 说明框带 30-50%
        ((300, 240), False, (400, 460)),  # 说明框带 30-70%
        ((300, 0), False, (200, 1000)),  # 全高 30-50%
        ((300, 0), False, (400, 1000)),  # 全高 30-70%
    ]


def test_first_pass_skips_full_when_nothing_seen(monkeypatch):
    """F8 第一遍（whole_screen=False）：标题带、说明框带（屏高 24%~70%）里连说明框的样子都没见到（不是锚点、
    凑不成像样名字）——全高那两条也不认，直接回去让 F8 等一下再截（2026-11-07 PR #17 跟进：没有说明框时
    第一遍从 6 次认字少到 4 次）；第二遍（可整屏）照旧六档都认；鼠标不在中间带的第一遍也一样只认四次，
    读不到鼠标位置（只有中间一条）的第一遍只认两次。调试截图记「第一遍·没见到说明框」，第二遍照旧记驾驶位保护"""
    from types import SimpleNamespace

    from astral_toolkit.trade import debug_shots

    shot = SimpleNamespace(add_attempt=lambda *a: None, stop_reason="")
    monkeypatch.setattr(debug_shots, "current", lambda: shot)
    _names(monkeypatch, {})
    calls = _fake_ocr(monkeypatch, [[OcrToken("SCM 220", 90, (60, 300, 60, 18))]])
    toks, name, where = _read_tooltip(
        MockImage(1000, 1000), (500, 500), whole_screen=False
    )
    assert name is None and shot.stop_reason == "第一遍·没见到说明框"
    assert [c[2] for c in calls] == [(200, 120), (400, 120), (200, 460), (400, 460)]
    calls.clear()
    _read_tooltip(MockImage(1000, 1000), (500, 500))
    assert [c[2][1] for c in calls] == [120, 120, 460, 460, 1000, 1000]
    assert shot.stop_reason == "驾驶位保护"
    calls.clear()
    _read_tooltip(MockImage(1000, 1000), (100, 500), whole_screen=False)
    assert [c[2][1] for c in calls] == [120, 120, 460, 460]
    assert shot.stop_reason == "第一遍·没见到说明框"
    calls.clear()
    _read_tooltip(MockImage(1000, 1000), None, whole_screen=False)
    assert [c[2] for c in calls] == [(400, 120), (400, 460)]


def test_first_pass_skips_full_when_name_not_plausible(monkeypatch):
    """第一遍前两档凑出了名字、但不像样（plausible_name 不认）、也没锚点：照样不认全高"""
    from astral_toolkit.trade import inspector as I

    _names(monkeypatch, {})
    calls = _fake_ocr(monkeypatch, [[OcrToken("乱码", 90, (350, 300, 100, 18))]])
    monkeypatch.setattr(
        I,
        "tooltip_pick",
        lambda tokens, cursor=None, img=None: (("乱码", "Junk"), False),
    )
    monkeypatch.setattr(I, "plausible_name", lambda zh, en: False)
    toks, name, where = _read_tooltip(
        MockImage(1000, 1000), (500, 500), whole_screen=False
    )
    assert name is None and len(calls) == 4


def test_first_pass_reads_full_after_anchor_seen(monkeypatch):
    """第一遍里说明框带见到了锚点（说明框只露出下半截，体积那行）：全高照认，全高看到完整说明框就停"""
    _names(monkeypatch, {})
    anchor_only = [OcrToken("体积：20uSCU", 90, (60, 348, 100, 18))]
    calls = _fake_ocr(monkeypatch, [[], [], [], anchor_only, [], _ITEM])
    toks, name, where = _read_tooltip(
        MockImage(1000, 1000), (100, 500), whole_screen=False
    )
    assert where == "30-70%@full" and len(calls) == 6
    assert name == ("实准枪口补偿器2", "VeraCompensator2")


def test_first_pass_reads_full_after_plausible_name_seen(monkeypatch):
    """第一遍里说明框带凑出了像样的名字（没把握、没锚点）：全高照认，全高认准了就用全高的"""
    from astral_toolkit.trade import inspector as I

    _names(monkeypatch, {})
    cand = [OcrToken("候选", 90, (350, 300, 100, 18))]
    sure = [OcrToken("认准", 90, (350, 300, 100, 18))]
    calls = _fake_ocr(monkeypatch, [[], [], cand, [], [], sure])

    def pick(tokens, cursor=None, img=None):
        if tokens and tokens[0].text == "候选":
            return ("候选物品", "Candidate Item"), False
        if tokens and tokens[0].text == "认准":
            return ("认准物品", "Sure Item"), True
        return None, False

    monkeypatch.setattr(I, "tooltip_pick", pick)
    monkeypatch.setattr(I, "plausible_name", lambda zh, en: True)
    toks, name, where = _read_tooltip(
        MockImage(1000, 1000), (500, 500), whole_screen=False
    )
    assert len(calls) == 6 and where == "30-70%@full"
    assert name == ("认准物品", "Sure Item")


def test_title_stage_stops_on_chinese_library_hit(monkeypatch):
    """中文标题行在汉化包里精确对上：标题带第一次就停（中文已经是高把握命中，不再用英文行兜）"""
    _names(monkeypatch, {"实准枪口补偿器2": "VeraCompensator2"})
    calls = _fake_ocr(monkeypatch, [_ITEM])
    toks, name, where = _read_tooltip(MockImage(1000, 1000), (100, 500))
    assert where == "30-50%@title" and len(calls) == 1
    assert name == ("实准枪口补偿器2", "VeraCompensator2")


def test_title_stage_falls_back_to_english_line(monkeypatch):
    """中文认错字（不在库里精确对上）时，用下面那行英文再查，英文精确就停"""
    _names(monkeypatch, {"实准枪口补偿器2": "VeraCompensator2"})
    weak_zh = [
        OcrToken("实准枪口补偿器", 90, (350, 300, 100, 18)),
        OcrToken("VeraCompensator2", 90, (350, 324, 100, 18)),
        OcrToken("体积：20uSCU", 90, (350, 348, 100, 18)),
    ]
    calls = _fake_ocr(monkeypatch, [weak_zh])
    toks, name, where = _read_tooltip(MockImage(1000, 1000), (100, 500))
    assert where == "30-50%@title" and len(calls) == 1
    assert name == ("实准枪口补偿器", "VeraCompensator2")


def test_title_stage_does_not_stop_on_weak_fuzzy(monkeypatch):
    """中文弱模糊（canonical 的 ratio≥0.75 档会命中）+ 英文不精确：标题带不停，放大到说明框带"""
    _names(monkeypatch, {"实准枪口补偿器2": "VeraCompensator2"})
    calls = _fake_ocr(monkeypatch, [_WEAK])
    toks, name, where = _read_tooltip(MockImage(1000, 1000), (100, 500))
    # 标题带两个宽度都没高把握命中；说明框带看到完整说明框（英文下面紧跟体积）才停
    assert where == "30-50%@body" and len(calls) == 3


def test_weak_fuzzy_still_resolved_later(monkeypatch):
    """弱模糊不在窄带停，但认物结果不丢：inspect_item 后面还会用完整 canonical 纠正"""
    from astral_toolkit.trade.inspector import inspect_item

    _names(monkeypatch, {"实准枪口补偿器2": "VeraCompensator2"})
    _fake_ocr(monkeypatch, [_WEAK])
    res = inspect_item(MockImage(1000, 1000), (100, 500))
    assert res is not None
    assert res["raw"] == ("实准枪口补偿器", "VeraCompensato")
    assert (res["zh"], res["en"]) == ("实准枪口补偿器2", "VeraCompensator2")
    assert res["sure"]


def test_full_stage_stops_on_anchor_without_library_hit(monkeypatch):
    """前三档都没认到、全高档看到完整说明框（英文下紧跟体积）：照旧当认到了，不为没入库的物品再跑整屏"""
    _names(monkeypatch, {})
    calls = _fake_ocr(monkeypatch, [[], [], [], [], [], _ITEM])
    toks, name, where = _read_tooltip(MockImage(1000, 1000), (100, 500))
    # 全高第二个宽度条带（30~70%）认到的
    assert where == "30-70%@full" and len(calls) == 6
    assert name == ("实准枪口补偿器2", "VeraCompensator2")


def test_cockpit_guard_allows_fullscreen_when_anchor_seen(monkeypatch):
    """认过的区域里有说明框特征（体积…）但没对上名字：照旧整屏兜底"""
    _names(monkeypatch, {})
    anchor_only = [OcrToken("体积：20uSCU", 90, (60, 348, 100, 18))]
    calls = _fake_ocr(monkeypatch, [[], [], [], [], [], anchor_only])
    _read_tooltip(MockImage(1000, 1000), (500, 500))
    assert calls[-1][2] == (1000, 1000)


if __name__ == "__main__":
    unittest.main()
