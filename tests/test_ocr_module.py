"""独立 OCR 模块 (astral_toolkit.ocr) 单元测试与兼容性回归"""

import unittest
from unittest.mock import MagicMock, patch
import numpy as np
from PIL import Image


class TestOcrModule(unittest.TestCase):
    def test_imports_and_exports(self):
        from astral_toolkit.ocr import (
            OcrToken,
            recognize,
            read_line,
            OcrQuad,
            detect,
            warmup,
            set_ocr_device,
            ocr_device,
            gpu_available,
            last_ocr_error,
        )
        from astral_toolkit.ocr.models import OcrToken as DirectOcrToken

        # 验证新模块导出
        self.assertIs(OcrToken, DirectOcrToken)
        self.assertTrue(callable(recognize))
        self.assertTrue(callable(read_line))
        self.assertTrue(callable(detect))
        self.assertNotIn("raw_detector", __import__("astral_toolkit.ocr").ocr.__all__)
        self.assertEqual(OcrQuad._fields, ("quad", "text", "conf"))
        self.assertTrue(callable(warmup))
        self.assertTrue(callable(set_ocr_device))
        self.assertTrue(callable(ocr_device))
        self.assertTrue(callable(gpu_available))
        self.assertTrue(callable(last_ocr_error))

        # 验证 trade.ocr 垫片已彻底下线
        import importlib

        with self.assertRaises((ModuleNotFoundError, ImportError)):
            importlib.import_module("astral_toolkit.trade.ocr")

    def test_ocr_token_properties(self):
        from astral_toolkit.ocr import OcrToken

        tok = OcrToken("测试文本", 98.5, (10, 20, 100, 30))
        self.assertEqual(tok.text, "测试文本")
        self.assertEqual(tok.confidence, 98.5)
        self.assertEqual(tok.box, (10, 20, 100, 30))

        # 验证 frozen dataclass 特性
        with self.assertRaises(AttributeError):
            tok.text = "新文本"  # type: ignore

    def test_recognize_with_mock_engine(self):
        from astral_toolkit.ocr import recognize, OcrToken

        mock_eng = MagicMock()
        mock_eng.kind = "rapidocr_onnxruntime"
        # 模拟 RapidOCR 返回: [([[10, 20], [110, 20], [110, 50], [10, 50]], "量子石", 0.95)]
        mock_eng.return_value = (
            [([[10, 20], [110, 20], [110, 50], [10, 50]], "量子石", 0.95)],
            0.01,
        )

        with patch("astral_toolkit.ocr.engine._get_engine", return_value=mock_eng):
            img = Image.new("RGB", (200, 100), color=(0, 0, 0))
            tokens = recognize(img, offset=(5, 5), native=True)

            self.assertEqual(len(tokens), 1)
            self.assertIsInstance(tokens[0], OcrToken)
            self.assertEqual(tokens[0].text, "量子石")
            self.assertEqual(tokens[0].confidence, 95.0)
            self.assertEqual(tokens[0].box, (15, 25, 100, 30))

    def test_read_line_with_pil_and_numpy(self):
        from astral_toolkit.ocr import read_line

        mock_eng = MagicMock()
        mock_eng.kind = "rapidocr_onnxruntime"
        mock_eng.return_value = ([("4,280", 0.98)], 0.005)

        with patch("astral_toolkit.ocr.engine._get_engine", return_value=mock_eng):
            # 1. 传入 PIL Image
            img = Image.new("RGB", (80, 24), color=(255, 255, 255))
            txt, conf = read_line(img)
            self.assertEqual(txt, "4,280")
            self.assertEqual(conf, 0.98)

            # 2. 传入 numpy ndarray
            arr = np.zeros((24, 80, 3), dtype=np.uint8)
            txt2, conf2 = read_line(arr)
            self.assertEqual(txt2, "4,280")
            self.assertEqual(conf2, 0.98)

    def test_detect_and_read_line(self):
        """detect 给 OcrQuad（四点原样、把握 0~1）；read_line 走同一个引擎的单行识别（跳过检测）"""
        from astral_toolkit.ocr import OcrQuad, detect, read_line

        mock_eng = MagicMock()
        mock_eng.kind = "rapidocr_onnxruntime"

        def _side_effect(*args, **kwargs):
            if kwargs.get("use_det") is False:
                return ([("123", 0.99)], 0.005)
            return ([([[0, 0], [10, 0.5], [10, 10], [0, 10]], "123", 0.99)], 0.01)

        mock_eng.side_effect = _side_effect

        with patch("astral_toolkit.ocr.engine._get_engine", return_value=mock_eng):
            arr = np.zeros((50, 50, 3), dtype=np.uint8)
            res = detect(arr)
            self.assertEqual(len(res), 1)
            self.assertIsInstance(res[0], OcrQuad)
            quad, text, conf = res[0]
            self.assertEqual((text, conf), ("123", 0.99))
            self.assertEqual(quad[1], [10, 0.5])  # 浮点角点原样，采矿靠它算斜度

            t, c = read_line(arr)
            self.assertEqual(t, "123")
            self.assertEqual(c, 0.99)

    def test_no_text_both_engines(self):
        """没字的图：旧引擎给 (None, 耗时)，3.x 给 boxes=None —— detect / recognize 都给空，不出错"""
        from astral_toolkit.ocr import detect, recognize

        arr = np.zeros((20, 20, 3), dtype=np.uint8)
        old = MagicMock(return_value=(None, 0.01))
        old.kind = "rapidocr_onnxruntime"
        new = MagicMock(return_value=MagicMock(boxes=None, txts=(), scores=()))
        new.kind = "rapidocr"
        for eng in (old, new):
            with patch("astral_toolkit.ocr.engine._get_engine", return_value=eng):
                self.assertEqual(detect(arr), [])
                self.assertEqual(recognize(arr), [])

    def test_detect_rapidocr3_object(self):
        """3.x 引擎给对象：boxes 是 numpy，转成列表四点"""
        from astral_toolkit.ocr import detect

        boxes = np.array([[[1.5, 2.0], [9.0, 2.5], [9.0, 8.0], [1.5, 8.0]]])
        eng = MagicMock(
            return_value=MagicMock(boxes=boxes, txts=("AB",), scores=(0.8,))
        )
        eng.kind = "rapidocr"
        with patch("astral_toolkit.ocr.engine._get_engine", return_value=eng):
            res = detect(np.zeros((20, 20, 3), dtype=np.uint8))
        self.assertEqual(res[0].quad, [[1.5, 2.0], [9.0, 2.5], [9.0, 8.0], [1.5, 8.0]])
        self.assertEqual((res[0].text, res[0].conf), ("AB", 0.8))
