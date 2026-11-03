"""run.use_directml：显卡版识别组件的安装 / 回退顺序（与压缩包版无关）"""


def _fake_pip(monkeypatch, ok=True):
    """假 pip：记下装 / 卸的顺序，不真去装"""
    import astral_toolkit.run as run

    calls = []
    monkeypatch.setattr(
        run,
        "_pip",
        lambda *a: (
            calls.append(("install",) + a)
            or (ok if "onnxruntime-directml" in a else True)
        ),
    )
    monkeypatch.setattr(
        run, "_pip_uninstall", lambda *a: calls.append(("uninstall",) + a) or True
    )
    return run, calls


def test_use_directml_installs_before_uninstalling_cpu(monkeypatch):
    run, calls = _fake_pip(monkeypatch)
    assert run.use_directml()
    assert calls == [
        ("install", "onnxruntime-directml"),
        ("uninstall", "onnxruntime"),
        ("install", "--force-reinstall", "--no-deps", "onnxruntime-directml"),
    ]


def test_use_directml_keeps_cpu_when_install_fails(monkeypatch):
    run, calls = _fake_pip(monkeypatch, ok=False)
    assert run.use_directml() is False
    assert calls == [("install", "onnxruntime-directml")]


def test_use_directml_restores_cpu_when_reinstall_fails(monkeypatch):
    """CPU 版已经卸了、显卡版强制重装又失败：把 CPU 版装回来，返回 False"""
    import astral_toolkit.run as run

    calls = []
    monkeypatch.setattr(
        run,
        "_pip",
        lambda *a: calls.append(("install",) + a) or "--force-reinstall" not in a,
    )
    monkeypatch.setattr(
        run, "_pip_uninstall", lambda *a: calls.append(("uninstall",) + a) or True
    )
    assert run.use_directml() is False
    assert calls[-1] == ("install", "onnxruntime")
    assert calls == [
        ("install", "onnxruntime-directml"),
        ("uninstall", "onnxruntime"),
        ("install", "--force-reinstall", "--no-deps", "onnxruntime-directml"),
        ("install", "onnxruntime"),
    ]
