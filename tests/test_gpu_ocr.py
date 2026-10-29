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


if __name__ == "__main__":
    unittest.main()
