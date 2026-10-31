"""独立 OCR 模块 (sc_mining.ocr) 单元测试与兼容性回归"""

import unittest
from unittest.mock import MagicMock, patch
import numpy as np
from PIL import Image


class TestOcrModule(unittest.TestCase):
    def test_imports_and_exports(self):
        from sc_mining.ocr import (
            OcrToken,
            recognize,
            read_line,
            raw_detector,
            raw_recognizer,
        )
        from sc_mining.ocr.models import OcrToken as DirectOcrToken

        # 验证新模块导出
        self.assertIs(OcrToken, DirectOcrToken)
        self.assertTrue(callable(recognize))
        self.assertTrue(callable(read_line))
        self.assertTrue(callable(raw_detector))
        self.assertTrue(callable(raw_recognizer))

        # 验证 trade.ocr 垫片已彻底下线
        import importlib

        with self.assertRaises((ModuleNotFoundError, ImportError)):
            importlib.import_module("sc_mining.trade.ocr")

    def test_ocr_token_properties(self):
        from sc_mining.ocr import OcrToken

        tok = OcrToken("测试文本", 98.5, (10, 20, 100, 30))
        self.assertEqual(tok.text, "测试文本")
        self.assertEqual(tok.confidence, 98.5)
        self.assertEqual(tok.box, (10, 20, 100, 30))

        # 验证 frozen dataclass 特性
        with self.assertRaises(AttributeError):
            tok.text = "新文本"  # type: ignore

    def test_recognize_with_mock_engine(self):
        from sc_mining.ocr import recognize, OcrToken

        mock_eng = MagicMock()
        mock_eng.kind = "rapidocr_onnxruntime"
        # 模拟 RapidOCR 返回: [([[10, 20], [110, 20], [110, 50], [10, 50]], "量子石", 0.95)]
        mock_eng.return_value = (
            [([[10, 20], [110, 20], [110, 50], [10, 50]], "量子石", 0.95)],
            0.01,
        )

        with patch("sc_mining.ocr.engine._get_engine", return_value=mock_eng):
            img = Image.new("RGB", (200, 100), color=(0, 0, 0))
            tokens = recognize(img, offset=(5, 5), native=True)

            self.assertEqual(len(tokens), 1)
            self.assertIsInstance(tokens[0], OcrToken)
            self.assertEqual(tokens[0].text, "量子石")
            self.assertEqual(tokens[0].confidence, 95.0)
            self.assertEqual(tokens[0].box, (15, 25, 100, 30))

    def test_read_line_with_pil_and_numpy(self):
        from sc_mining.ocr import read_line

        mock_eng = MagicMock()
        mock_eng.kind = "rapidocr_onnxruntime"
        mock_eng.return_value = ([("4,280", 0.98)], 0.005)

        with patch("sc_mining.ocr.engine._get_engine", return_value=mock_eng):
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

    def test_raw_detector_and_recognizer(self):
        from sc_mining.ocr import raw_detector, raw_recognizer

        mock_eng = MagicMock()
        mock_eng.kind = "rapidocr_onnxruntime"

        def _side_effect(*args, **kwargs):
            if kwargs.get("use_det") is False:
                return ([("123", 0.99)], 0.005)
            return ([([[0, 0], [10, 0], [10, 10], [0, 10]], "123", 0.99)], 0.01)

        mock_eng.side_effect = _side_effect

        with patch("sc_mining.ocr.engine._get_engine", return_value=mock_eng):
            det = raw_detector()
            self.assertTrue(callable(det))
            arr = np.zeros((50, 50, 3), dtype=np.uint8)
            res = det(arr)
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0][1], "123")

            rec = raw_recognizer()
            self.assertTrue(callable(rec))
            t, c = rec(arr)
            self.assertEqual(t, "123")
            self.assertEqual(c, 0.99)
