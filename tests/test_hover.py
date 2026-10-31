"""F8 悬停识别自适应区域与兜底流程测试"""
import unittest
from sc_mining.trade.models import OcrToken
from sc_mining.tasks.hover import get_hover_regions, _read_tooltip, HOVER_REGIONS


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


class TestReadTooltipExecution(unittest.TestCase):
    def setUp(self):
        from sc_mining.trade import ocr
        self.ocr = ocr
        self._orig_recognize = ocr.recognize
        self.img = MockImage(1000, 1000)

    def tearDown(self):
        self.ocr.recognize = self._orig_recognize

    def test_first_stage_hit(self):
        """首选区域命中时，直接返回首选区域结果，不触发备选或全屏"""
        calls = []

        def fake_recognize(img, urgent=False, offset=(0, 0)):
            calls.append(offset)
            # 在 30%~50% 区域（x=300~500）生成有效说明框
            return [
                OcrToken("实准枪口补偿器2", 90, (350, 300, 100, 18)),
                OcrToken("VeraCompensator2", 90, (350, 324, 100, 18)),
                OcrToken("体积：20uSCU", 90, (350, 348, 100, 18)),
            ]

        self.ocr.recognize = fake_recognize
        toks, name, where = _read_tooltip(self.img, (100, 500))  # 鼠标在 10%
        self.assertEqual(where, "30-50%")
        self.assertEqual(name, ("实准枪口补偿器2", "VeraCompensator2"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], (300, 0))

    def test_second_stage_hit(self):
        """首选区域未命中，备选 30%~70% 命中"""
        calls = []

        def fake_recognize(img, urgent=False, offset=(0, 0)):
            calls.append(offset)
            if len(calls) == 1:
                return []
            return [
                OcrToken("实准枪口补偿器2", 90, (600, 300, 100, 18)),
                OcrToken("VeraCompensator2", 90, (600, 324, 100, 18)),
                OcrToken("体积：20uSCU", 90, (600, 348, 100, 18)),
            ]

        self.ocr.recognize = fake_recognize
        toks, name, where = _read_tooltip(self.img, (100, 500))  # 鼠标在 10%
        self.assertEqual(where, "30-70%")
        self.assertEqual(name, ("实准枪口补偿器2", "VeraCompensator2"))
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], (300, 0))
        self.assertEqual(calls[1], (300, 0))

    def test_fullscreen_fallback(self):
        """首选和备选均未命中，整屏兜底命中"""
        calls = []

        def fake_recognize(img, urgent=False, offset=(0, 0)):
            calls.append(offset)
            if len(calls) < 3:
                return []
            return [
                OcrToken("实准枪口补偿器2", 90, (800, 300, 100, 18)),
                OcrToken("VeraCompensator2", 90, (800, 324, 100, 18)),
                OcrToken("体积：20uSCU", 90, (800, 348, 100, 18)),
            ]

        self.ocr.recognize = fake_recognize
        toks, name, where = _read_tooltip(self.img, (100, 500))  # 鼠标在 10%
        self.assertEqual(where, "整屏")
        self.assertEqual(name, ("实准枪口补偿器2", "VeraCompensator2"))
        self.assertEqual(len(calls), 3)


def _fake_ocr(monkeypatch, toks):
    """假识别：每次都返回 toks（位置按偏移挪），记下每次认的图多宽"""
    from sc_mining.trade import ocr
    widths = []

    def fake(img, urgent=False, offset=(0, 0), native=False):
        widths.append(img.width)
        return [OcrToken(k.text, k.confidence, (k.box[0] + offset[0], k.box[1] + offset[1], k.box[2], k.box[3])) for k in toks]
    monkeypatch.setattr(ocr, "recognize", fake)
    return widths


def test_cockpit_guard_no_fullscreen_with_candidate(monkeypatch):
    """鼠标在中间、认过的区域里没有说明框特征：不认整屏，有像样的候选名就返回候选"""
    widths = _fake_ocr(monkeypatch, [
        OcrToken("能量突击步枪", 90, (60, 300, 100, 18)),
        OcrToken("P4-AR Rifle", 90, (60, 324, 100, 18)),
    ])
    toks, name, where = _read_tooltip(MockImage(1000, 1000), (500, 500))
    assert 1000 not in widths and len(widths) == 2          # 两个区域都认了，整屏没认
    assert name == ("能量突击步枪", "P4-AR Rifle") and where == "30-50%"


def test_cockpit_guard_no_fullscreen_miss(monkeypatch):
    """鼠标在中间、只认到 HUD 碎字：不认整屏，直接返回认不出"""
    widths = _fake_ocr(monkeypatch, [OcrToken("SCM 220", 90, (60, 300, 60, 18))])
    toks, name, where = _read_tooltip(MockImage(1000, 1000), None)
    assert 1000 not in widths and len(widths) == 1 and name is None


def test_cockpit_guard_allows_fullscreen_when_anchor_seen(monkeypatch):
    """认过的区域里有说明框特征（体积…）但没对上名字：照旧整屏兜底"""
    widths = _fake_ocr(monkeypatch, [OcrToken("体积：20uSCU", 90, (60, 348, 100, 18))])
    _read_tooltip(MockImage(1000, 1000), (500, 500))
    assert widths[-1] == 1000


if __name__ == "__main__":
    unittest.main()
