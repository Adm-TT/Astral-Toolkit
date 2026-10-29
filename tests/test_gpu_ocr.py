"""测试 GPU OCR 常驻模式与状态管理 (方案A)"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

from sc_mining.system import gpu_ocr
from sc_mining.core import settings


class TestGpuOcrPermanent(unittest.TestCase):
    def setUp(self):
        gpu_ocr.shutdown()

    def tearDown(self):
        gpu_ocr.shutdown()

    def test_settings_default(self):
        self.assertIn("always_use_gpu", settings.DEFAULTS)
        self.assertTrue(settings.DEFAULTS["always_use_gpu"])

    def test_permanent_state_management(self):
        # 初始未启动
        self.assertFalse(gpu_ocr.active())
        self.assertTrue(gpu_ocr.is_permanent())

        # 模拟 _start 启动成功
        with patch.object(gpu_ocr, "wanted", return_value=True), \
             patch.object(gpu_ocr, "_start", return_value=True) as mock_start, \
             patch.object(gpu_ocr, "_stop") as mock_stop:
            
            # 开启常驻
            gpu_ocr.ensure_active(blocking=True)
            self.assertTrue(gpu_ocr.is_permanent())
            mock_start.assert_called_once()

            # 模拟采矿助手 acquire 与 release
            # acquire 增加 users
            gpu_ocr.acquire()
            self.assertEqual(gpu_ocr._st["users"], 1)

            # release 减少 users，因为是常驻模式，不应触发 _stop
            gpu_ocr.release()
            self.assertEqual(gpu_ocr._st["users"], 0)
            mock_stop.assert_not_called()

            # 取消常驻模式：users == 0，此时应触发 _stop
            gpu_ocr.release_permanent()
            self.assertFalse(gpu_ocr.is_permanent())
            mock_stop.assert_called_once()

    def test_shutdown(self):
        with patch.object(gpu_ocr, "_stop") as mock_stop:
            gpu_ocr._st["users"] = 2
            gpu_ocr._st["permanent"] = True
            gpu_ocr.shutdown()
            self.assertEqual(gpu_ocr._st["users"], 0)
            self.assertIsNone(gpu_ocr._st["permanent"])
            mock_stop.assert_called_once()

    def test_revive_when_permanent(self):
        with patch.object(gpu_ocr, "wanted", return_value=True), \
             patch.object(gpu_ocr, "_start", return_value=True) as mock_start:
            gpu_ocr._st["permanent"] = True
            gpu_ocr._st["users"] = 0
            gpu_ocr._st["proc"] = None
            gpu_ocr._st["conn"] = None
            gpu_ocr._st["bad_at"] = 0.0

            gpu_ocr.revive()
            import time
            time.sleep(0.1)
            mock_start.assert_called()

    def test_set_settings_integration(self):
        from sc_mining.tasks.system import set_settings, status
        with patch.object(gpu_ocr, "ensure_active") as mock_ensure, \
             patch.object(gpu_ocr, "release_permanent") as mock_release, \
             patch.object(settings, "update", side_effect=lambda **kw: {**settings.DEFAULTS, **kw}), \
             patch.object(settings, "load", return_value=dict(settings.DEFAULTS)):
            
            set_settings(always_use_gpu=True)
            mock_ensure.assert_called_with(blocking=True)

            set_settings(always_use_gpu=False)
            mock_release.assert_called_once()

            st = status()
            self.assertIn("ocr_device", st)


if __name__ == "__main__":
    unittest.main()
