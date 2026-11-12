"""F8 悬停识别自适应区域与兜底流程测试

2026-11-09：标题带 24%~36%（认名，库精确才停）→ 说明框带 24%~70%（品质/锚点）；
不再全高竖条、不再整屏 OCR（docs/superpowers/specs/2026-11-04-f8-title-band-ocr.md）。
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
# 中文弱模糊 + 英文高把握模糊（≥0.9）：标题带可停
_WEAK_EN_OK = [
    OcrToken("实准枪口补偿器", 90, (350, 300, 100, 18)),
    OcrToken("VeraCompensato", 90, (350, 324, 100, 18)),
    OcrToken("体积：20uSCU", 90, (350, 348, 100, 18)),
]
# 中文弱模糊 + 英文太糊（<0.9）：标题带不停
_WEAK = [
    OcrToken("实准枪口补偿器", 90, (350, 300, 100, 18)),
    OcrToken("VeraCompens", 90, (350, 324, 100, 18)),
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
    monkeypatch.setattr(
        names, "_from_items", lambda en, strict=False: None
    )  # 不走本机物品目录


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

    def test_no_fullscreen_after_title_body(self):
        """标题带、说明框带都没认到：不再整屏，返回未识别"""
        calls = []

        def fake_recognize(img, urgent=False, offset=(0, 0), native=False):
            calls.append((offset, native, img.size))
            return []

        self.ocr.recognize = fake_recognize
        toks, name, where = _read_tooltip(self.img, (100, 500))  # 鼠标在 10%
        self.assertIsNone(name)
        self.assertEqual(len(calls), 4)  # 2 高度 × 2 宽度，无整屏
        self.assertTrue(str(where).endswith("@body") or str(where).endswith("@title"))


def test_cascade_order_and_cockpit_guard(monkeypatch):
    """级联顺序：标题带 2 个宽度 → 说明框带 2 个（native 只有标题带是 True）；不再全高/整屏"""
    _names(monkeypatch, {})
    anchor_only = [OcrToken("体积：20uSCU", 90, (60, 348, 100, 18))]
    calls = _fake_ocr(monkeypatch, [[], [], [], anchor_only, []])
    toks, name, where = _read_tooltip(MockImage(1000, 1000), (500, 500))
    assert name is None
    assert calls[:6] == [
        ((300, 240), True, (200, 120)),  # 标题带 30-50%
        ((300, 240), True, (400, 120)),  # 标题带 30-70%
        ((300, 240), False, (200, 460)),  # 说明框带 30-50%
        ((300, 240), False, (400, 460)),  # 说明框带 30-70%
    ]


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


def test_title_stage_does_not_stop_when_size_lost(monkeypatch):
    """中文弱模糊、英文≥0.9 但丢的正好是末尾的尺寸「2」：标题带不算高把握，不停（11-12 合 PR #18 后收窄：
    尺寸 / 罗马数字是关键数据）；英文≥0.9 且尺寸一样才停，见 test_inspector 的 canonical_title"""
    _names(monkeypatch, {"实准枪口补偿器2": "VeraCompensator2"})
    calls = _fake_ocr(monkeypatch, [_WEAK_EN_OK])
    toks, name, where = _read_tooltip(MockImage(1000, 1000), (100, 500))
    assert not str(where).endswith("@title") and len(calls) > 1


def test_title_stage_does_not_stop_on_weak_fuzzy(monkeypatch):
    """中文弱模糊 + 英文太糊（<0.9）：标题带不停，放大到说明框带靠锚点 sure 停"""
    _names(monkeypatch, {"实准枪口补偿器2": "VeraCompensator2"})
    calls = _fake_ocr(monkeypatch, [_WEAK])
    toks, name, where = _read_tooltip(MockImage(1000, 1000), (100, 500))
    # 标题带两个宽度都没高把握命中；说明框带看到完整说明框（英文下面紧跟体积）才停
    assert where == "30-50%@body" and len(calls) == 3


def test_weak_fuzzy_still_resolved_later(monkeypatch):
    """英文不够糊时标题带已能停；英文太糊时放大后 inspect_item 仍用完整 canonical 纠正"""
    from astral_toolkit.trade.inspector import inspect_item

    _names(monkeypatch, {"实准枪口补偿器2": "VeraCompensator2"})
    _fake_ocr(monkeypatch, [_WEAK_EN_OK])
    res = inspect_item(MockImage(1000, 1000), (100, 500))
    assert res is not None
    assert res["raw"] == ("实准枪口补偿器", "VeraCompensato")
    assert (res["zh"], res["en"]) == ("实准枪口补偿器2", "VeraCompensator2")
    assert res["sure"]
    assert not str(res["where"]).endswith(
        "@title"
    )  # 丢了尺寸：标题带不停，放大后再纠正


def test_body_stage_stops_on_anchor_without_library_hit(monkeypatch):
    """标题带没库命中、说明框带看到完整说明框（英文下紧跟体积）：锚点 sure 停，不整屏"""
    _names(monkeypatch, {})
    calls = _fake_ocr(monkeypatch, [[], [], _ITEM])
    toks, name, where = _read_tooltip(MockImage(1000, 1000), (100, 500))
    assert where == "30-50%@body" and len(calls) == 3
    assert name == ("实准枪口补偿器2", "VeraCompensator2")


def test_no_fullscreen_when_anchor_only(monkeypatch):
    """只有体积锚点、抽不出名字：级联结束也不整屏"""
    _names(monkeypatch, {})
    anchor_only = [OcrToken("体积：20uSCU", 90, (60, 348, 100, 18))]
    calls = _fake_ocr(monkeypatch, [anchor_only])
    toks, name, where = _read_tooltip(MockImage(1000, 1000), (500, 500))
    assert name is None
    assert len(calls) == 4
    assert not any(off == (0, 0) and sz == (1000, 1000) for off, _n, sz in calls)


if __name__ == "__main__":
    unittest.main()
