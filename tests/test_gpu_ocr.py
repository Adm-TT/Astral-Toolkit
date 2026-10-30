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


# ---------------------------------------------------------------- 显卡出错退回 CPU（假引擎，不加载真识别）
class _FakeResult:
    def __init__(self):
        import numpy as np
        self.boxes, self.txts, self.scores = np.zeros((0, 4, 2)), [], []


class _FakeEng:
    """假识别引擎：记被调了几次；fail=True 时一调用就报错（模拟显卡驱动出问题）"""
    def __init__(self, gpu=False, fail=False):
        self.gpu, self.fail, self.calls = gpu, fail, 0

    def __call__(self, *a, **kw):
        self.calls += 1
        if self.fail:
            raise RuntimeError("DML 设备丢失")
        return _FakeResult()


def _fake_engines(monkeypatch, gpu_fails=False):
    """换掉建引擎的那一步：记下每次新建的引擎；默认环境、默认设置都当成「想用显卡、显卡可用」"""
    made = []

    def new(gpu):
        e = _FakeEng(gpu, fail=bool(gpu and gpu_fails))
        made.append(e)
        return e, bool(gpu), ""
    monkeypatch.setattr(perf, "_new_engine", new)
    monkeypatch.setattr(perf, "USE_GPU", True)
    monkeypatch.setattr(perf, "is_gpu_preferred", lambda: True)
    monkeypatch.setattr(perf, "gpu_available", lambda: True)
    monkeypatch.setattr(perf, "_engine", None)
    monkeypatch.setattr(perf, "_cpu_fallback", False)
    monkeypatch.setattr(perf, "_last_error", "")
    monkeypatch.setattr(settings, "update", lambda **kw: dict(kw))
    return made


def test_gpu_error_falls_back_to_cpu(monkeypatch):
    import numpy as np
    made = _fake_engines(monkeypatch, gpu_fails=True)
    eng = perf.rapidocr()
    assert eng.gpu and len(made) == 1
    eng(np.zeros((8, 8, 3)))                              # 显卡版报错 → 换 CPU 版重试一次，照样出结果
    assert len(made) == 2 and made[0].calls == 1 and made[1].calls == 1 and not made[1].gpu
    assert not eng.gpu and perf._cpu_fallback
    assert "显卡识别出错" in perf.last_ocr_error() and "DML" in perf.last_ocr_error()
    eng.urgent(np.zeros((8, 8, 3)))                       # 之后一直用 CPU，不再重建
    assert len(made) == 2 and made[1].calls == 2
    monkeypatch.setattr(perf, "_engine", None)
    assert not perf.rapidocr().gpu                        # 重新加载也还是 CPU，直到玩家再切
    perf.set_ocr_device("gpu")                            # 玩家在设置里切回显卡：再试显卡
    assert not perf._cpu_fallback and perf.rapidocr().gpu


def test_cpu_error_not_retried(monkeypatch):
    import numpy as np
    made = _fake_engines(monkeypatch)
    monkeypatch.setattr(perf, "is_gpu_preferred", lambda: False)
    eng = perf.rapidocr()
    made[0].fail = True
    try:
        eng(np.zeros((8, 8, 3)))
        raise AssertionError("CPU 版出错应该照常报出来")
    except RuntimeError:
        pass
    assert len(made) == 1 and not perf._cpu_fallback


def test_switch_device_reaches_every_caller(monkeypatch):
    """切显卡 / CPU 后，交易识别（trade.ocr）、采矿读屏（screen._ocr / _recognize）用的都是新引擎：
    它们缓存的是同一个共享对象，切换只换里面的引擎"""
    import numpy as np
    from PIL import Image
    from sc_mining.trade import ocr as T
    from sc_mining.mining import screen as S
    made = _fake_engines(monkeypatch)
    monkeypatch.setattr(T, "_engine", None)
    monkeypatch.setattr(S, "_engine", None)
    monkeypatch.setattr(S, "_rec", None)
    img, arr = Image.new("RGB", (16, 16)), np.zeros((16, 16, 3), dtype=np.uint8)

    def use_all():
        T.recognize(img)
        T.recognize(img, urgent=True)
        T.read_line(img)
        S._ocr()(arr)
        S._recognize()(arr)

    use_all()                                             # 各处先各自缓存一次
    assert len(made) == 1 and made[0].gpu and made[0].calls == 5
    shared = perf.rapidocr()
    assert T._engine is shared
    monkeypatch.setattr(perf, "is_gpu_preferred", lambda: False)
    assert perf.set_ocr_device("cpu") == "CPU"
    assert perf.rapidocr() is shared and len(made) == 2 and not made[1].gpu
    use_all()
    assert made[0].calls == 5 and made[1].calls == 5      # 切换后旧引擎一次都没再用


if __name__ == "__main__":
    unittest.main()
