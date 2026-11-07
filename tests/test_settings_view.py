"""NV-B5：settings.View 平时不读盘，save 后才重读；读不到文件时按 RETRY 再试。"""

from types import SimpleNamespace

from astral_toolkit.core import settings


def test_view_reads_file_once_until_settings_saved(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    original_load = settings.load
    calls = []

    def counting_load():
        calls.append(1)
        return original_load()

    monkeypatch.setattr(settings, "load", counting_load)
    view = settings.View()
    assert view.get("debug_mode") is False
    assert view.get("debug_mode") is False
    assert len(calls) == 1

    # 带上 keys_v5：不然 load 会把它当老设置迁移、再存一次（多读一遍）
    settings.save({**settings.DEFAULTS, "keys_v5": True, "debug_mode": True})
    assert view.get("debug_mode") is True
    assert len(calls) == 2
    assert view.get("debug_mode") is True
    assert len(calls) == 2


def test_view_retries_after_unreadable_file(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    clock = [100.0]
    monkeypatch.setattr(settings, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    calls = []

    def fake_load():
        calls.append(1)
        if len(calls) == 1:
            settings._unread.flag = True
            return dict(settings.DEFAULTS)
        return {**settings.DEFAULTS, "debug_mode": True}

    monkeypatch.setattr(settings, "load", fake_load)
    view = settings.View()
    assert view.get("debug_mode") is False
    assert len(calls) == 1

    assert view.get("debug_mode") is False
    assert len(calls) == 1

    clock[0] = 101.0
    assert view.get("debug_mode") is True
    assert len(calls) == 2

    assert view.get("debug_mode") is True
    assert len(calls) == 2


def test_view_without_any_file_uses_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    assert settings.View().all() == settings.load()
    assert settings.View().get("没有的键", 7) == 7


def test_save_bumps_counter(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    before = settings._SAVED[0]
    settings.save(dict(settings.DEFAULTS))
    assert settings._SAVED[0] == before + 1


def test_unreadable_settings_keep_last_read(monkeypatch, tmp_path):
    """这个进程读到过的设置文件后来暂时读不到（被杀毒、同步软件占着）：先用上次读到的，不退回默认值——
    不然窗口会闪回深色、设置页显示默认值、按默认值查撞键（s1 第二轮复查）；这次照样不存盘、要报没存上"""
    import json

    f = tmp_path / "settings.json"
    f.write_text(
        json.dumps({"agreed": True, "keys_v5": True, "ocr_v2": True, "theme": "light"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "FILE", f)
    assert settings.load()["theme"] == "light"
    f.unlink()
    f.mkdir()  # 同一个位置读不出来：和被别的程序占着一样
    assert settings.load()["theme"] == "light"
    try:
        settings.update_checked(theme="dark")
    except settings.NotSaved:
        pass
    else:
        raise AssertionError("读不到时要报没存上")
    assert f.is_dir()  # 没有拿默认值盖掉
