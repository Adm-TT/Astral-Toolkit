"""第 5 条：关注矿物只影响悬浮窗，关闭时间设置保留默认且运行时生效。"""

from astral_toolkit.core import settings
from astral_toolkit.app.presenters import mining as present
from astral_toolkit.mining.analysis import analyze
from astral_toolkit.tasks import mining
from tests.test_mining_analysis import _inputs, _scan
from tests import mining_helpers


def test_focus_changes_hud_only_and_keeps_unselected_window_rows():
    result = analyze(_scan(), ({}, None, None), _inputs())
    before = present.to_view(result)
    hud, rich = present.to_hud(result, focus=["Gold"])
    assert "钨" not in hud
    assert rich["comp"] == []
    assert "未发现关注的矿" in hud
    assert present.to_view(result) == before
    assert len(before["lots"]) == 3


def test_focus_keeps_original_percent_and_default_hud():
    result = analyze(_scan(), ({}, None, None), _inputs())
    original = present.to_hud(result)
    assert present.to_hud(result, focus=None) == original
    hud, rich = present.to_hud(result, focus=["Tungsten"])
    assert [g["name"] for g in rich["comp"]] == ["钨"]
    assert rich["comp"][0]["pct"] == original[1]["comp"][0]["pct"]
    assert rich["gain"] == original[1]["gain"]
    assert "整石" in hud
    assert "惰性" not in hud


def test_empty_focus_hides_all_ores():
    result = analyze(_scan(), ({}, None, None), _inputs())
    hud, rich = present.to_hud(result, focus=[])
    assert rich["comp"] == [] and "钨" not in hud


def test_focus_save_validates_and_persists(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    changes = []
    live = mining_helpers.live()
    monkeypatch.setattr(live, "config_changed", lambda: changes.append(True))
    out = mining.set_mining_focus(live, keys=["Copper", "Iron", "Copper"])
    assert {x["key"] for x in out["focus"] if x["on"]} == {"Copper", "Iron"}
    assert settings.load()["mining_focus"] == ["Copper", "Iron"]
    assert changes == [True]
    for bad in ("Copper", ["missing"], 42, True, ["Copper", {}]):
        try:
            mining.set_mining_focus(live, keys=bad)
        except ValueError:
            pass
        else:
            raise AssertionError("错误矿种必须拒绝")
    assert settings.load()["mining_focus"] == ["Copper", "Iron"]
    mining.set_mining_focus(live, keys=[])
    assert settings.load()["mining_focus"] == []
    mining.set_mining_focus(live, keys=None)
    assert settings.load()["mining_focus"] is None


def test_idle_setting_normalizes_and_updates_running_worker(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    for value, expected in [
        (None, 120),
        ("bad", 120),
        ("nan", 120),
        (float("inf"), 120),
        (0, 30),
        (9999, 1800),
        ("300", 300),
    ]:
        assert settings.mining_idle_seconds(value) == expected
    live = mining_helpers.live()
    assert live.idle_close == 120
    settings.update(mining_idle_close=300)
    assert live.idle_close == 300
    settings.update(mining_idle_close=30)
    assert live.idle_close == 30


def test_signal_focus_filters_existing_candidates_without_reinterpreting(monkeypatch):
    from astral_toolkit.mining import signals

    monkeypatch.setattr(signals, "my_signatures", lambda: {})
    found = [(4240, False, "4240", None), (4270, False, "4270", None)]
    full = signals.describe_all(found, "space")
    focused = signals.describe_all(found, "space", focus=["Copper"])
    assert focused and all("铜" in x and "铁" not in x for x in focused)
    assert all(x in full for x in focused)
    assert signals.describe_all(found, "space", focus=[]) == []
    assert signals.describe_all(found, "space", focus=None) == full
    # 关注金不应把铜的既有匹配改报成“最近的金”。
    assert signals.describe_all(found[:1], "space", focus=["Gold"]) == []


def test_mixed_signal_is_hidden_as_a_whole_if_one_ore_is_unselected(monkeypatch):
    from astral_toolkit.mining import signals

    monkeypatch.setattr(signals, "my_signatures", lambda: {})
    local = {"Copper": 50, "Iron": 50}
    monkeypatch.setattr(signals, "_local_table", lambda area: local)
    found = [(4240 + 4270, False, "8510", None)]
    full = signals.describe_all(found, "space", {})
    both = signals.describe_all(found, "space", {}, focus=["Copper", "Iron"])
    assert any("两种混在一团" in x for x in both)
    assert all(x in full for x in both)
    single = signals.describe_all(found, "space", {}, focus=["Copper"])
    assert all("两种混在一团" not in x and "铁" not in x for x in single)


def test_settings_api_persists_idle_timeout(monkeypatch, tmp_path):
    from astral_toolkit import bootstrap
    from astral_toolkit.tasks.system.settings import set_settings
    from tests.bootstrap_helpers import app_for_test

    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    monkeypatch.setattr("astral_toolkit.tasks.system.status.status", lambda sources: {})
    with app_for_test() as app:
        sources = bootstrap.status_sources(app)
        assert set_settings(sources, mining_idle_close=300)["mining_idle_close"] == 300
        assert settings.load()["mining_idle_close"] == 300
        assert (
            set_settings(sources, mining_idle_close=9999)["mining_idle_close"] == 1800
        )


def test_session_stops_with_timeout_changed_during_scan(monkeypatch, tmp_path):
    from astral_toolkit.mining.parse import Scan
    from tests.test_live_commit import _world, _subscribe, _finish, _wait_note

    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    clock = {"t": 1000.0}
    hud, _ = _world(monkeypatch, tmp_path, lambda img: (Scan(), ({}, None, None)))
    live = mining_helpers.live(clock=lambda: clock["t"])
    q = _subscribe()
    try:
        assert live.start() is not None
        settings.update(mining_idle_close=30)
        clock["t"] += 31.0
        assert _wait_note(hud, "已关闭"), hud.notes
        assert live.loop.state().stop_reason == "idle"
    finally:
        _finish(live, q)


def test_focus_hides_other_ore_names_in_refinery_bonus():
    from dataclasses import replace

    result = analyze(_scan(), ({}, None, None), _inputs())
    result = replace(result, refine=(replace(result.refine[0], bonus="金 +3%"),))
    hud, rich = present.to_hud(result, focus=["Tungsten"])
    assert "金" not in hud and all("金" not in x for x in rich["minor"])


def test_bad_persisted_focus_falls_back_to_all_and_recovers_from_gear(
    monkeypatch, tmp_path
):
    import json
    from astral_toolkit.mining import signals

    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mining, "collect_inputs", lambda scan: _inputs())
    monkeypatch.setattr(signals, "my_signatures", lambda: {})
    scan, bag = _scan(), ({}, None, None)
    expected_hud = present.to_hud(analyze(scan, bag, _inputs()))
    found = [(4240, False, "4240", None), (4270, False, "4270", None)]
    expected_signals = signals.describe_all(found, "space")
    live = mining_helpers.live()
    changed = []
    monkeypatch.setattr(live, "config_changed", lambda: changed.append(True))
    for value in (42, True, "Copper", {"Copper": True}):
        settings.FILE.write_text(
            json.dumps({"keys_v5": True, "mining_focus": value}), encoding="utf-8"
        )
        gear = mining.mining_gear()
        assert gear["focus"] and all(x["on"] for x in gear["focus"])
        view = mining.scan_view(scan, bag)
        assert (view["hud"], view["hud_rich"]) == expected_hud
        focus = mining_helpers.links().focus()
        assert focus is None
        assert signals.describe_all(found, "space", focus=focus) == expected_signals
        # 非法值只在读取时回退，保存“全部”才能写回 None，不悄悄改玩家文件。
        assert settings.load()["mining_focus"] == value
        restored = mining.set_mining_focus(live, keys=None)
        assert all(x["on"] for x in restored["focus"])
        assert settings.load()["mining_focus"] is None
    assert len(changed) == 4


def test_persisted_focus_drops_unknown_and_invalid_members_for_both_huds(
    monkeypatch, tmp_path
):
    from astral_toolkit.mining import signals

    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mining, "collect_inputs", lambda scan: _inputs())
    monkeypatch.setattr(signals, "my_signatures", lambda: {})
    settings.save(
        {
            "keys_v5": True,
            "mining_focus": ["Tungsten", "missing", 42, True, {}, [], "Tungsten"],
        }
    )
    gear = mining.mining_gear()
    assert [x["key"] for x in gear["focus"] if x["on"]] == ["Tungsten"]
    assert mining_helpers.links().focus() == ["Tungsten"]
    view = mining.scan_view(_scan(), ({}, None, None))
    assert [x["name"] for x in view["hud_rich"]["comp"]] == ["钨"]
    found = [(3870, False, "3870", None), (4240, False, "4240", None)]
    assert signals.describe_all(
        found, "space", focus=mining_helpers.links().focus()
    ) == signals.describe_all(found[:1], "space")
    settings.update(mining_focus=["missing", 42, {}])
    assert mining_helpers.links().focus() == []
    assert not any(x["on"] for x in mining.mining_gear()["focus"])
    assert mining.scan_view(_scan(), ({}, None, None))["hud_rich"]["comp"] == []
