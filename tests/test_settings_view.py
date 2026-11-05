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
