"""测试主进程 OCR 设备切换与设置 (GPU / CPU 模式)"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

from astral_toolkit.core import settings
from astral_toolkit import ocr as OCR
from astral_toolkit.ocr import runtime as OR
from astral_toolkit.tasks.system import set_settings, status


class TestOcrDeviceSwitch(unittest.TestCase):
    def setUp(self):
        OR._engine = None

    def tearDown(self):
        OR._engine = None

    def test_settings_default(self):
        self.assertIn("ocr_device", settings.DEFAULTS)
        self.assertEqual(settings.DEFAULTS["ocr_device"], "cpu")

    def test_is_gpu_preferred(self):
        # 环境变量 DUBHE_OCR_CPU=1 会强制 CPU：前两条先把它设成别的值，在哪台电脑上跑都一样
        with patch.dict(os.environ, {"DUBHE_OCR_CPU": "0"}):
            with patch.object(settings, "load", return_value={"ocr_device": "gpu"}):
                self.assertTrue(OR.is_gpu_preferred())

            with patch.object(settings, "load", return_value={"ocr_device": "cpu"}):
                self.assertFalse(OR.is_gpu_preferred())

            # 都没写：按默认处理器
            with patch.object(settings, "load", return_value={}):
                self.assertFalse(OR.is_gpu_preferred())

        with patch.dict(os.environ, {"DUBHE_OCR_CPU": "1"}):
            self.assertFalse(OR.is_gpu_preferred())

    def test_set_ocr_device_cpu(self):
        mock_eng = MagicMock(spec=["text_det"])
        mock_eng.text_det = MagicMock(spec=["session"])
        mock_eng.text_det.session.get_providers.return_value = ["CPUExecutionProvider"]
        mock_mod = MagicMock()
        mock_mod.RapidOCR.return_value = mock_eng

        with (
            patch.dict(sys.modules, {"rapidocr_onnxruntime": mock_mod}),
            patch.object(settings, "update") as mock_update,
        ):
            dev = OR.set_ocr_device("cpu")
            self.assertEqual(dev, "CPU")
            mock_update.assert_called_with(ocr_device="cpu", always_use_gpu=False)

    def test_set_ocr_device_gpu(self):
        mock_eng = MagicMock(spec=["text_det"])
        mock_eng.text_det = MagicMock(spec=["session"])
        mock_eng.text_det.session.get_providers.return_value = [
            "DmlExecutionProvider",
            "CPUExecutionProvider",
        ]
        mock_mod = MagicMock()
        mock_mod.RapidOCR.return_value = mock_eng

        # 不受环境变量 DUBHE_OCR_CPU 和本机设置影响
        with (
            patch.dict(sys.modules, {"rapidocr_onnxruntime": mock_mod}),
            patch.dict(os.environ, {"DUBHE_OCR_CPU": "0"}),
            patch.object(OR, "USE_GPU", True),
            patch.object(OR, "gpu_available", return_value=True),
            patch.object(settings, "load", return_value={"ocr_device": "gpu"}),
            patch.object(settings, "update") as mock_update,
        ):
            dev = OR.set_ocr_device("gpu")
            self.assertEqual(dev, "显卡")
            mock_update.assert_called_with(ocr_device="gpu", always_use_gpu=True)

    def test_set_settings_integration(self):
        from astral_toolkit import bootstrap
        from tests.bootstrap_helpers import app_for_test

        # status() / set_settings 经 astral_toolkit.ocr 包出口导入，补丁打在包上；
        # RT-B7：set_settings 会推一次状态：用这个 app 的状态源（app_for_test 放最后，补丁都打好了再装配）
        with (
            patch.object(OCR, "set_ocr_device", return_value="显卡") as mock_set,
            patch.object(OCR, "ocr_device", return_value="显卡"),
            patch.object(OCR, "gpu_available", return_value=True),
            patch.object(OCR, "last_ocr_error", return_value=""),
            patch.object(
                settings, "update", side_effect=lambda **kw: {**settings.DEFAULTS, **kw}
            ),
            patch.object(settings, "load", return_value=dict(settings.DEFAULTS)),
            app_for_test() as app,
        ):
            sources = bootstrap.status_sources(app)
            set_settings(sources, ocr_device="gpu")
            mock_set.assert_called_with("gpu")

            set_settings(sources, ocr_device="cpu")
            mock_set.assert_called_with("cpu")

            st = status(sources)
            self.assertIn("ocr_device", st)
            self.assertIn("ocr_mode", st)

    def test_cell_labels_tokens_reuse(self):
        from unittest.mock import MagicMock
        from astral_toolkit.trade.inspector import cell_labels
        from astral_toolkit.ocr import OcrToken

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
        from astral_toolkit.trade.inspector import cell_labels

        mock_img = MagicMock()
        mock_img.size = (1920, 1080)
        mock_img.crop.return_value = mock_img

        with patch("astral_toolkit.ocr.recognize", return_value=[]) as mock_rec:
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

    def __init__(self, gpu=False, fail=False, exc=None):
        self.gpu, self.fail, self.calls = gpu, fail, 0
        self.exc = exc or RuntimeError("DML 设备丢失")

    def __call__(self, *a, **kw):
        self.calls += 1
        if self.fail:
            raise self.exc
        return _FakeResult()


def _fake_engines(monkeypatch, gpu_fails=False):
    """换掉建引擎的那一步：记下每次新建的引擎；默认环境、默认设置都当成「想用显卡、显卡可用」"""
    made = []

    def new(gpu):
        e = _FakeEng(gpu, fail=bool(gpu and gpu_fails))
        made.append(e)
        return e, bool(gpu), ""

    monkeypatch.setattr(OR, "_new_engine", new)
    monkeypatch.setattr(OR, "USE_GPU", True)
    monkeypatch.setattr(OR, "is_gpu_preferred", lambda: True)
    monkeypatch.setattr(OR, "gpu_available", lambda: True)
    monkeypatch.setattr(OR, "_engine", None)
    monkeypatch.setattr(OR, "_cpu_fallback", False)
    monkeypatch.setattr(OR, "_last_error", "")
    monkeypatch.setattr(settings, "update", lambda **kw: dict(kw))
    return made


def test_gpu_error_falls_back_to_cpu(monkeypatch):
    import numpy as np

    made = _fake_engines(monkeypatch, gpu_fails=True)
    eng = OR.rapidocr()
    assert eng.gpu and len(made) == 1
    eng(np.zeros((8, 8, 3)))  # 显卡版报错 → 换 CPU 版重试一次，照样出结果
    assert (
        len(made) == 2 and made[0].calls == 1 and made[1].calls == 1 and not made[1].gpu
    )
    assert not eng.gpu and OR._cpu_fallback
    assert "显卡识别出错" in OR.last_ocr_error() and "DML" in OR.last_ocr_error()
    eng.urgent(np.zeros((8, 8, 3)))  # 之后一直用 CPU，不再重建
    assert len(made) == 2 and made[1].calls == 2
    monkeypatch.setattr(OR, "_engine", None)
    assert not OR.rapidocr().gpu  # 重新加载也还是 CPU，直到玩家再切
    OR.set_ocr_device("gpu")  # 玩家在设置里切回显卡：再试显卡
    assert not OR._cpu_fallback and OR.rapidocr().gpu


def test_gpu_and_cpu_both_fail_keeps_gpu(monkeypatch):
    """显卡版、CPU 版都认不了（多半是图片本身的问题）：报原来的错，不切 CPU、不记「已改用 CPU」"""
    import numpy as np

    made = _fake_engines(monkeypatch)
    eng = OR.rapidocr()
    made[0].fail, made[0].exc = True, ZeroDivisionError("坏图")
    monkeypatch.setattr(
        OR,
        "_new_engine",
        lambda gpu: (_FakeEng(gpu, True, ZeroDivisionError("坏图")), bool(gpu), ""),
    )
    try:
        eng(np.zeros((8, 8, 3)))
        raise AssertionError("应该抛 ZeroDivisionError")
    except ZeroDivisionError:
        pass
    assert eng.gpu is True and eng.eng is made[0] and OR._cpu_fallback is False
    assert "已改用 CPU" not in OR.last_ocr_error()


def test_cpu_engine_cannot_load_raises_gpu_error(monkeypatch):
    """显卡版出错、CPU 版又建不起来：报原来显卡的错，引擎不动"""
    import numpy as np

    made = _fake_engines(monkeypatch, gpu_fails=True)
    eng = OR.rapidocr()

    def no_cpu(gpu):
        raise OSError("缺少模型文件")

    monkeypatch.setattr(OR, "_new_engine", no_cpu)
    try:
        eng(np.zeros((8, 8, 3)))
        raise AssertionError("应该抛原来的显卡错")
    except RuntimeError as e:
        assert "DML" in str(e)
    assert eng.gpu is True and eng.eng is made[0] and OR._cpu_fallback is False


def test_ocr_device_not_blocked_while_switching(monkeypatch):
    """切显卡 / CPU 时要等正在跑的识别（这里慢 1 秒）跑完才换；这段时间里问「在哪算」不能跟着卡住"""
    import threading
    import time as _time
    import numpy as np

    made = _fake_engines(monkeypatch)
    eng = OR.rapidocr()
    started = threading.Event()

    class Slow(_FakeEng):
        def __call__(self, *a, **k):
            started.set()
            _time.sleep(1.0)
            return _FakeResult()

    eng.eng = Slow(True)
    t1 = threading.Thread(target=eng, args=(np.zeros((8, 8, 3)),))
    t1.start()
    started.wait(2)
    t2 = threading.Thread(target=OR.set_ocr_device, args=("cpu",))
    t2.start()
    _time.sleep(0.1)  # 切换已经拿着 OR._lock、在等识别跑完
    t0 = _time.perf_counter()
    OR.ocr_device()
    took = _time.perf_counter() - t0
    t1.join(3)
    t2.join(3)
    assert took < 0.3, took
    assert len(made) == 2 and OR.rapidocr().eng is made[1]


def test_cpu_error_not_retried(monkeypatch):
    import numpy as np

    made = _fake_engines(monkeypatch)
    monkeypatch.setattr(OR, "is_gpu_preferred", lambda: False)
    eng = OR.rapidocr()
    made[0].fail = True
    try:
        eng(np.zeros((8, 8, 3)))
        raise AssertionError("CPU 版出错应该照常报出来")
    except RuntimeError:
        pass
    assert len(made) == 1 and not OR._cpu_fallback


def test_switch_device_reaches_every_caller(monkeypatch):
    """切显卡 / CPU 后，统一 OCR（astral_toolkit.ocr）、采矿读屏（screen._ocr / _recognize）用的都是新引擎：
    它们缓存的是同一个共享对象，切换只换里面的引擎"""
    import numpy as np
    from PIL import Image
    from astral_toolkit import ocr as O
    from astral_toolkit.ocr import engine as OE
    from astral_toolkit.mining import screen as S

    made = _fake_engines(monkeypatch)
    monkeypatch.setattr(OE, "_engine", None)
    monkeypatch.setattr(S, "_engine", None)
    monkeypatch.setattr(S, "_rec", None)
    img, arr = Image.new("RGB", (16, 16)), np.zeros((16, 16, 3), dtype=np.uint8)

    def use_all():
        O.recognize(img)
        O.recognize(img, urgent=True)
        O.read_line(img)
        S._ocr()(arr)
        S._recognize()(arr)

    use_all()  # 各处先各自缓存一次
    assert len(made) == 1 and made[0].gpu and made[0].calls == 5
    shared = OR.rapidocr()
    assert OE._engine is shared
    monkeypatch.setattr(OR, "is_gpu_preferred", lambda: False)
    assert OR.set_ocr_device("cpu") == "CPU"
    assert OR.rapidocr() is shared and len(made) == 2 and not made[1].gpu
    use_all()
    assert made[0].calls == 5 and made[1].calls == 5  # 切换后旧引擎一次都没再用


def test_old_settings_switch_ocr_to_cpu_once(monkeypatch, tmp_path):
    """识别默认改处理器（显卡认过一次字 AT 就多占两三百 MB 内存，2026-11-08 老大定）。老版本存的设置文件里
    「显卡」分不出是不是自己选的：打开时改一次处理器，文件里记下改过了；之后切回显卡就一直是显卡。
    新装的第一次存设置就带着这一项，选了显卡也不改"""
    import json

    f = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "FILE", f)
    old = {"agreed": True, "keys_v5": True, "ocr_device": "gpu", "always_use_gpu": True}
    f.write_text(json.dumps(old), encoding="utf-8")
    cfg = settings.load()
    assert cfg["ocr_device"] == "cpu" and cfg["always_use_gpu"] is False
    on_disk = json.loads(f.read_text(encoding="utf-8"))
    assert on_disk["ocr_device"] == "cpu" and on_disk["ocr_v2"] is True
    assert on_disk["agreed"] is True  # 别的设置照旧
    settings.update(ocr_device="gpu", always_use_gpu=True)  # 玩家在设置页切回显卡
    assert settings.load()["ocr_device"] == "gpu"
    assert json.loads(f.read_text(encoding="utf-8"))["ocr_device"] == "gpu"
    f.unlink()  # 新装的：还没有设置文件，按默认处理器，也不急着写文件
    assert settings.load()["ocr_device"] == "cpu" and not f.exists()
    settings.update(ocr_device="gpu")
    assert settings.load()["ocr_device"] == "gpu"


def test_migration_save_failure_not_retried_every_load(monkeypatch, tmp_path):
    """老格式设置文件一直写不进去（比如带了只读）：迁移只在内存里做，这个进程里不再每次读都重试写盘
    （每次要卡约 0.25 秒，读设置的地方很多）；读到的照样是处理器（s1 第二轮复查）"""
    import json

    f = tmp_path / "settings.json"
    old = {"agreed": True, "keys_v5": True, "ocr_device": "gpu", "always_use_gpu": True}
    f.write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.setattr(settings, "FILE", f)
    tries = []

    def read_only(cfg):
        tries.append(1)
        raise PermissionError("设置文件只读")

    monkeypatch.setattr(settings, "save", read_only)
    assert settings.load()["ocr_device"] == "cpu"
    assert settings.load()["ocr_device"] == "cpu"
    assert len(tries) == 1
    assert json.loads(f.read_text(encoding="utf-8")) == old  # 文件没动


if __name__ == "__main__":
    unittest.main()
