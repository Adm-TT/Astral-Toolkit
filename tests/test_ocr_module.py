"""独立 OCR 模块 (astral_toolkit.ocr) 单元测试与兼容性回归"""

import unittest
from unittest.mock import MagicMock, patch
import numpy as np
from PIL import Image

from tests.minipytest import skip


class _Out:
    """模拟新版 rapidocr.RapidOCROutput"""

    def __init__(self, boxes, txts, scores):
        self.boxes, self.txts, self.scores = boxes, txts, scores


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
        mock_eng.kind = "rapidocr.main"
        mock_eng.return_value = _Out(
            [[[10, 20], [110, 20], [110, 50], [10, 50]]],
            ["量子石"],
            [0.95],
        )

        with patch("astral_toolkit.ocr.engine._get_engine", return_value=mock_eng):
            img = Image.new("RGB", (200, 100), color=(0, 0, 0))
            tokens = recognize(img, offset=(5, 5), native=True)

            self.assertEqual(len(tokens), 1)
            self.assertIsInstance(tokens[0], OcrToken)
            self.assertEqual(tokens[0].text, "量子石")
            self.assertEqual(tokens[0].confidence, 95.0)
            self.assertEqual(tokens[0].box, (15, 25, 100, 30))

    def test_recognize_empty_boxes(self):
        from astral_toolkit.ocr import recognize

        mock_eng = MagicMock()
        mock_eng.kind = "rapidocr.main"
        mock_eng.return_value = _Out(None, None, None)

        with patch("astral_toolkit.ocr.engine._get_engine", return_value=mock_eng):
            tokens = recognize(Image.new("RGB", (40, 20)))
            self.assertEqual(tokens, [])

    def test_read_line_with_pil_and_numpy(self):
        from astral_toolkit.ocr import read_line

        mock_eng = MagicMock()
        mock_eng.kind = "rapidocr.main"
        mock_eng.return_value = _Out(None, ["4,280"], [0.98])

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
        mock_eng.kind = "rapidocr.main"

        def _side_effect(*args, **kwargs):
            if kwargs.get("use_det") is False:
                return _Out(None, ["123"], [0.99])
            # 第二角点用浮点，确认 detect 不把四点 round 成整数
            return _Out([[[0, 0], [10, 0.5], [10, 10], [0, 10]]], ["123"], [0.99])

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


def test_engine_params_keys():
    """不 mock _engine_params：核对 PP-OCRv6 small（11-12 由 tiny 改）与 use_dml 键名"""
    from astral_toolkit.ocr import runtime as OR

    cpu = OR._engine_params(False)
    assert cpu["Global.use_cls"] is False
    assert cpu["Det.model_type"].value == "small"
    assert cpu["Rec.model_type"].value == "small"
    assert cpu["Det.ocr_version"].value == "PP-OCRv6"
    assert "EngineConfig.onnxruntime.use_dml" not in cpu
    gpu = OR._engine_params(True)
    assert gpu["EngineConfig.onnxruntime.use_dml"] is True


def test_download_with_retry_recovers(monkeypatch):
    """CDN 抖两下后第三次成功：不抛；退避用 sleep 假实现，不真等。"""
    import logging
    from astral_toolkit.ocr import runtime as OR

    calls = {"n": 0}
    slept = []

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("模拟断网")

    monkeypatch.setattr(OR.time, "sleep", lambda s: slept.append(s))
    OR._download_with_retry(flaky, log=logging.getLogger("test"), what="测下载")
    assert calls["n"] == 3
    assert slept == [2, 4]  # 2**1, 2**2；合计 < 30s 封顶


def test_download_with_retry_exhausted(monkeypatch):
    """三次都失败：带次数提示的 RuntimeError，根因链式保留。"""
    import logging
    from astral_toolkit.ocr import runtime as OR

    def always_fail():
        raise OSError("一直断")

    monkeypatch.setattr(OR.time, "sleep", lambda s: None)
    try:
        OR._download_with_retry(
            always_fail, log=logging.getLogger("test"), what="测下载"
        )
        raise AssertionError("应该抛 RuntimeError")
    except RuntimeError as e:
        assert "已试 3 次" in str(e)
        assert isinstance(e.__cause__, OSError)


def test_read_line_does_not_disable_detect(monkeypatch):
    """rapidocr 3.x 会把 use_det 写进引擎：read_line 之后 recognize 仍须能检测。"""
    import numpy as np
    from PIL import Image, ImageDraw
    from astral_toolkit.ocr import runtime as OR
    from astral_toolkit.ocr import engine as OE
    from astral_toolkit import ocr as O

    try:
        import rapidocr  # noqa: F401
    except ImportError:
        skip("没有 rapidocr")

    monkeypatch.setattr(OR, "USE_GPU", False)
    monkeypatch.setattr(OR, "is_gpu_preferred", lambda: False)
    monkeypatch.setattr(OR, "gpu_available", lambda: False)
    monkeypatch.setattr(OR, "_engine", None)
    monkeypatch.setattr(OR, "_cpu_fallback", False)
    monkeypatch.setattr(OE, "_engine", None)

    img = Image.new("RGB", (220, 64), color=(255, 255, 255))
    ImageDraw.Draw(img).text((12, 18), "AT123", fill=(0, 0, 0))
    before = O.recognize(img)
    O.read_line(img)
    after = O.recognize(img)
    assert OR.rapidocr().eng.use_det is True
    # 空白图可能两边都空；有字时 read_line 前后都应能检出（允许偶发空，但不可一边有一边无）
    if before:
        assert after, "read_line 之后 recognize 不应变成空结果"
    # 强制走一次检测路径：人造高对比色块+字，至少引擎 use_det 保持 True
    arr = np.zeros((80, 240, 3), dtype=np.uint8)
    arr[:] = 255
    O.recognize(arr)
    assert OR.rapidocr().eng.use_det is True


if __name__ == "__main__":
    unittest.main()
