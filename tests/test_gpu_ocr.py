"""测试主进程 OCR 设备切换与设置 (GPU / CPU 模式)"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

from sc_mining.core import perf, settings
from sc_mining.tasks.system import set_settings, status


class TestOcrDeviceSwitch(unittest.TestCase):
    def setUp(self):
        perf._engine = None

    def tearDown(self):
        perf._engine = None

    def test_settings_default(self):
        self.assertIn("ocr_device", settings.DEFAULTS)
        self.assertEqual(settings.DEFAULTS["ocr_device"], "gpu")

    def test_is_gpu_preferred(self):
        with patch.object(settings, "load", return_value={"ocr_device": "gpu"}):
            self.assertTrue(perf.is_gpu_preferred())

        with patch.object(settings, "load", return_value={"ocr_device": "cpu"}):
            self.assertFalse(perf.is_gpu_preferred())

        with patch.dict(os.environ, {"DUBHE_OCR_CPU": "1"}):
            self.assertFalse(perf.is_gpu_preferred())

    def test_set_ocr_device_cpu(self):
        mock_eng = MagicMock(spec=["text_det"])
        mock_eng.text_det = MagicMock(spec=["session"])
        mock_eng.text_det.session.get_providers.return_value = ["CPUExecutionProvider"]
        mock_mod = MagicMock()
        mock_mod.RapidOCR.return_value = mock_eng

        with patch.dict(sys.modules, {"rapidocr_onnxruntime": mock_mod}), \
             patch.object(settings, "update") as mock_update:
            dev = perf.set_ocr_device("cpu")
            self.assertEqual(dev, "CPU")
            mock_update.assert_called_with(ocr_device="cpu", always_use_gpu=False)

    def test_set_ocr_device_gpu(self):
        mock_eng = MagicMock(spec=["text_det"])
        mock_eng.text_det = MagicMock(spec=["session"])
        mock_eng.text_det.session.get_providers.return_value = ["DmlExecutionProvider", "CPUExecutionProvider"]
        mock_mod = MagicMock()
        mock_mod.RapidOCR.return_value = mock_eng

        with patch.dict(sys.modules, {"rapidocr_onnxruntime": mock_mod}), \
             patch.object(perf, "gpu_available", return_value=True), \
             patch.object(settings, "update") as mock_update:
            dev = perf.set_ocr_device("gpu")
            self.assertEqual(dev, "显卡")
            mock_update.assert_called_with(ocr_device="gpu", always_use_gpu=True)

    def test_set_settings_integration(self):
        with patch.object(perf, "set_ocr_device", return_value="显卡") as mock_set, \
             patch.object(settings, "update", side_effect=lambda **kw: {**settings.DEFAULTS, **kw}), \
             patch.object(settings, "load", return_value=dict(settings.DEFAULTS)):
            
            set_settings(ocr_device="gpu")
            mock_set.assert_called_with("gpu")

            set_settings(ocr_device="cpu")
            mock_set.assert_called_with("cpu")

            st = status()
            self.assertIn("ocr_device", st)
            self.assertIn("ocr_mode", st)

    def test_cell_labels_tokens_reuse(self):
        from unittest.mock import MagicMock
        from sc_mining.tasks.hover import cell_labels
        from sc_mining.trade.models import OcrToken

        mock_img = MagicMock()
        mock_img.size = (1920, 1080)
        # 模拟鼠标在 (500, 500)，上方有品质标签 575Q 和数量 200x
        # 盒子定义为 (x, y, w, h)，在鼠标上方 cw=124, ch=118 范围内
        tokens = [
            OcrToken("575Q", 99.0, (460, 430, 40, 20)),
            OcrToken("200x", 99.0, (520, 430, 40, 20)),
        ]
        q, n = cell_labels(mock_img, (500, 500), tokens=tokens)
        self.assertEqual(q, 575)
        self.assertEqual(n, 200)

    def test_cell_labels_native_param(self):
        from unittest.mock import MagicMock, patch
        from sc_mining.tasks.hover import cell_labels

        mock_img = MagicMock()
        mock_img.size = (1920, 1080)
        mock_img.crop.return_value = mock_img

        with patch("sc_mining.trade.ocr.recognize", return_value=[]) as mock_rec:
            cell_labels(mock_img, (500, 500), tokens=None)
            self.assertTrue(mock_rec.called)
            # 确认调用了 native=True
            _, kwargs = mock_rec.call_args
            self.assertTrue(kwargs.get("native"))


if __name__ == "__main__":
    unittest.main()
