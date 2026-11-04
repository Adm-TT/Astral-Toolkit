"""F8 sure=False 时按 pack+loc 是否齐全分流提示
（docs/superpowers/specs/2026-11-04-f8-unsure-data-hint.md）"""


def test_data_names_ready_needs_pack_and_loc(monkeypatch):
    from astral_toolkit.tasks.system import about

    monkeypatch.setattr(about, "_data_versions", lambda: {"pack": "1.0", "loc": "box"})
    assert about.data_names_ready() is True

    monkeypatch.setattr(about, "_data_versions", lambda: {"pack": "", "loc": "box"})
    assert about.data_names_ready() is False

    monkeypatch.setattr(about, "_data_versions", lambda: {"pack": "1.0", "loc": ""})
    assert about.data_names_ready() is False

    monkeypatch.setattr(about, "_data_versions", lambda: {"pack": "", "loc": ""})
    assert about.data_names_ready() is False


def _stub_unsure_hover(monkeypatch, *, library_ready: bool):
    from astral_toolkit.app import bus
    from astral_toolkit.tasks.system import about
    import astral_toolkit.tasks.hover as Hv

    events = []
    hud = []
    monkeypatch.setattr(
        bus, "publish", lambda ch, payload: events.append((ch, payload))
    )
    monkeypatch.setattr(bus, "runtime_log", lambda *a, **k: None)
    monkeypatch.setattr(bus, "update_preview", lambda *a, **k: None)
    monkeypatch.setattr(Hv, "_item_hud", lambda text, *a, **k: hud.append(text))
    monkeypatch.setattr(about, "data_names_ready", lambda: library_ready)
    monkeypatch.setattr(
        Hv,
        "inspect_item",
        lambda *a, **k: {
            "zh": "乱认的名",
            "en": "Bogus",
            "quality": None,
            "qty": 1,
            "unit": "个",
            "sure": False,
            "raw": ("乱认的名", "Bogus"),
            "canon": None,
            "craft": None,
            "tokens": [],
            "where": "30-50%@body",
        },
    )
    monkeypatch.setattr(Hv, "item_info", lambda *a, **k: {})
    monkeypatch.setattr(Hv, "_hover_lines", lambda *a, **k: [])
    monkeypatch.setattr(Hv, "_hover_more", lambda *a, **k: None)
    monkeypatch.setattr("astral_toolkit.trade.console._hover_log", lambda *a, **k: None)
    monkeypatch.setattr(Hv, "WIN", False)
    return Hv, events, hud


def test_hover_unsure_hints_incomplete_data(monkeypatch):
    """库不完整：HUD 提示更新数据，事件带 library_ready=False。"""
    from PIL import Image

    Hv, events, hud = _stub_unsure_hover(monkeypatch, library_ready=False)
    r = Hv.hover_once(Image.new("RGB", (100, 100)))
    assert r.get("ok"), r
    ok_events = [p for ch, p in events if ch == "hover" and p.get("state") == "ok"]
    assert ok_events
    assert ok_events[-1]["sure"] is False
    assert ok_events[-1]["library_ready"] is False
    assert any("本地数据不完整" in t for t in hud)


def test_hover_unsure_keeps_old_copy_when_library_ready(monkeypatch):
    from PIL import Image

    Hv, events, hud = _stub_unsure_hover(monkeypatch, library_ready=True)
    Hv.hover_once(Image.new("RGB", (100, 100)))
    ok_events = [p for ch, p in events if ch == "hover" and p.get("state") == "ok"]
    assert ok_events[-1]["library_ready"] is True
    assert any("识别结果不确定" in t for t in hud)
    assert not any("本地数据不完整" in t for t in hud)
