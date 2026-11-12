"""第 5 条：关注矿物只影响悬浮窗，关闭时间设置保留默认且运行时生效。"""

from astral_toolkit.core import settings
from astral_toolkit.app.presenters import mining as present
from astral_toolkit.mining.analysis import analyze
from astral_toolkit.tasks import mining
from tests.test_mining_analysis import _inputs, _scan
from tests import mining_helpers


def test_focus_changes_hud_only_and_keeps_unselected_window_rows():
    result = analyze(_scan(), _inputs())
    before = present.to_view(result)
    hud, rich = present.to_hud(result, focus=["Gold"])
    # 关注的矿一样都没有：悬浮窗只留标题这一行（老大 2026-11-08 批注验收单：只留标题）
    assert hud == "未发现关注的矿"
    assert rich == {
        "title": "未发现关注的矿",
        "stats": [],
        "comp": [],
        "advice": None,
        "gain": [],
        "minor": [],
        "foot": "",
    }
    assert present.to_view(result) == before
    assert len(before["lots"]) == 3


def test_focus_keeps_original_percent_and_default_hud():
    result = analyze(_scan(), _inputs())
    original = present.to_hud(result)
    assert present.to_hud(result, focus=None) == original
    hud, rich = present.to_hud(result, focus=["Tungsten"])
    assert [g["name"] for g in rich["comp"]] == ["钨"]
    assert rich["comp"][0]["pct"] == original[1]["comp"][0]["pct"]
    assert rich["gain"] == original[1]["gain"]
    assert "整石" in hud
    assert "惰性" not in hud


def test_empty_focus_hides_all_ores():
    result = analyze(_scan(), _inputs())
    hud, rich = present.to_hud(result, focus=[])
    assert rich["comp"] == [] and "钨" not in hud
    assert hud == "未发现关注的矿" and rich["stats"] == [] and rich["advice"] is None


def test_focus_signal_kinds_ground_and_salvage(monkeypatch):
    """关注里能选地面信号、太空残骸（老大 2026-11-08 批注验收单）：地面来源归地面信号、可打捞残骸归太空残骸；
    没选这一类就不显示；选了矿不会把它们带出来"""
    from astral_toolkit.mining import signals

    monkeypatch.setattr(signals, "my_signatures", lambda: {})
    ground = [(8000, False, "8000", None)]  # ROC 车矿 ×2、可采集物 ×4
    full = signals.describe_all(ground, "ground")
    assert any("ROC 车矿" in x for x in full)
    assert signals.describe_all(ground, "ground", focus=["ground"]) == full
    assert signals.describe_all(ground, "ground", focus=["Copper", "salvage"]) == []
    space = [(9000, False, "9000", None)]  # 可打捞残骸 ×3
    got = signals.describe_all(space, "space", focus=["salvage"])
    assert got and all("残骸" in x for x in got)
    assert signals.describe_all(space, "space", focus=["ground", "Copper"]) == []
    # 不知道在地面还是太空：两边都列，各归各的类
    both = signals.describe_all([(6000, False, "6000", None)], None)
    only_ground = signals.describe_all(
        [(6000, False, "6000", None)], None, focus=["ground"]
    )
    only_salvage = signals.describe_all(
        [(6000, False, "6000", None)], None, focus=["salvage"]
    )
    assert only_ground and all("地面：" in x for x in only_ground)
    assert only_salvage and all("太空：" in x for x in only_salvage)
    assert sorted(only_ground + only_salvage) == sorted(both)
    # 地面上比一簇大得多的整千：几处地面小矿叠在一起，归地面信号
    piled = [(80000, False, "80000", None)]
    got = signals.describe_all(piled, "ground", focus=["ground"])
    assert got and all("叠在一起" in x for x in got)
    assert signals.describe_all(piled, "ground", focus=["salvage", "Iron"]) == []
    # 不刷船挖矿的空旷太空：「多半是残骸」归太空残骸
    empty = {"zh": "空旷太空", "rocks": {}}
    lone = [(7000, False, "7000", None)]
    got = signals.describe_all(lone, "space", empty, focus=["salvage"])
    assert got and all("多半是残骸" in x for x in got)
    assert signals.describe_all(lone, "space", empty, focus=["ground", "Iron"]) == []


def test_focus_hides_own_named_and_unknown_signals(monkeypatch):
    """自己起名的信号、认不出的「未知」不归类：开了关注（哪怕全选）也不上悬浮窗；不开关注照旧显示"""
    from astral_toolkit.mining import signals
    from astral_toolkit.mining.data import FOCUS_SIGNALS, SIGNATURES

    every = [*SIGNATURES, *FOCUS_SIGNALS]
    monkeypatch.setattr(signals, "my_signatures", lambda: {})
    unknown = [(1234, False, "1234", None)]
    assert any("未知" in x for x in signals.describe_all(unknown, "space"))
    assert signals.describe_all(unknown, "space", focus=every) == []
    monkeypatch.setattr(signals, "my_signatures", lambda: {"1234": "我起的名"})
    assert any("我起的名" in x for x in signals.describe_all(unknown, "space"))
    assert all(
        "我起的名" not in x for x in signals.describe_all(unknown, "space", focus=every)
    )


def test_focus_signal_keys_save_and_show(monkeypatch, tmp_path):
    """两类信号存进关注列表（矿在前、信号在后），页面上的选项带 signal；只选信号时石头的悬浮窗只留标题"""
    from astral_toolkit.mining.data import FOCUS_SIGNALS, focus_keys, focus_ores

    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mining, "collect_inputs", lambda scan: _inputs())
    live = mining_helpers.live()
    out = mining.set_mining_focus(live, keys=["salvage", "Copper", "ground"])
    assert settings.load()["mining_focus"] == ["Copper", "ground", "salvage"]
    sig = [x for x in out["focus"] if x.get("signal")]
    assert [(x["key"], x["name"], x["on"]) for x in sig] == [
        (k, name, True) for k, name in FOCUS_SIGNALS.items()
    ]
    assert not any(x.get("signal") for x in out["focus"] if x["key"] == "Copper")
    assert focus_keys(["ground", "Iron", "bogus"]) == ["Iron", "ground"]
    assert focus_ores(["ground", "Iron"]) == ["Iron"] and focus_ores(None) is None
    for bad in (["Ground"], ["salvage", 1]):
        try:
            mining.set_mining_focus(live, keys=bad)
        except ValueError:
            pass
        else:
            raise AssertionError("认不得的键必须拒绝")
    mining.set_mining_focus(live, keys=["ground"])
    assert mining_helpers.links().focus() == ["ground"]
    view = mining.scan_view(_scan())
    assert view["hud"] == "未发现关注的矿" and view["hud_rich"]["comp"] == []
    assert view["rock"] and view["plans"]  # 窗口照旧完整


def test_focus_panel_draws_signal_row_and_note():
    """采矿页的关注：两类信号另起一行，写明自己起名的、「未知」开了关注不上悬浮窗"""
    from pathlib import Path

    js = (Path(__file__).parents[1] / "astral_toolkit/app/web/app.js").read_text(
        encoding="utf-8"
    )
    start = js.index("function miningFocusRender()")
    body = js[start : js.index("\nfunction ", start)]
    assert "items.filter((x) => !x.signal)" in body
    assert "items.filter((x) => x.signal)" in body
    assert "自己起名的信号和认不出的「未知」信号不上悬浮窗" in body


def test_focus_goal_lines_pick_focused_ores_before_cutting_to_two():
    """开了关注：目标缺口先按关注的矿挑、再取前两条，排第三的关注矿那行不会被挤掉；按英文键挑；
    目标没查全不写（审查 2026-11-08）"""
    from dataclasses import replace

    # 石头里要有关注的铜：一样都没有时悬浮窗只留标题、不写目标行（老大 2026-11-08）
    scan = _scan(
        composition=[
            ("Tungsten", 10.0, 662),
            ("Copper", 50.0, 363),
            ("Inert Materials", 40.0, None),
        ]
    )
    result = analyze(scan, _inputs())
    goals = tuple(
        {"en": en, "zh": zh, "text": f"目标缺少 {zh}"}
        for en, zh in (("Gold", "金"), ("Tungsten", "钨"), ("Copper", "铜矿"))
    )
    r = replace(result, goals=goals, goal_lines=tuple(g["text"] for g in goals[:2]))

    def lines(rich):
        return [x for x in rich["minor"] if x.startswith("目标缺少")]

    hud, rich = present.to_hud(r, focus=["Copper"])
    assert lines(rich) == ["目标缺少 铜矿"] and "目标缺少 金" not in hud
    _, rich = present.to_hud(r, focus=["Gold", "Tungsten", "Copper"])
    assert lines(rich) == ["目标缺少 金", "目标缺少 钨"]
    _, rich = present.to_hud(replace(r, goal_lines=()), focus=["Copper"])
    assert lines(rich) == []


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


def test_mining_settings_not_saved_say_so(monkeypatch, tmp_path):
    """关注的矿、配装、手持工具存不上（设置文件被占着读不到、写不进去）：告诉窗口没存上（不带本机路径），
    悬浮窗也不跟着重算（审查 2026-11-08）"""
    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    changes = []
    live = mining_helpers.live()
    monkeypatch.setattr(live, "config_changed", lambda: changes.append(True))

    def unread(**kw):
        raise settings.NotSaved("这次没存上，再点一次")

    def locked(**kw):
        raise PermissionError(
            13, "Permission denied", r"C:\Users\someone\settings.json"
        )

    for boom, want in (
        (unread, "这次没存上，再点一次"),
        (locked, settings.NOT_WRITTEN),
    ):
        monkeypatch.setattr(settings, "update_checked", boom)
        assert mining.set_mining_focus(live, keys=["Copper"]) == {"error": want}
        assert mining.set_mining_gear(live, ship="mole", reset=True) == {"error": want}
        assert mining.set_mining_gadgets(live, keys=[]) == {"error": want}
    assert changes == []


def test_gear_panel_redraws_saved_gear_when_save_fails():
    """配装存不上时照存着的配装重画：选船、人数、矿头、来源、品质这些控件是先在界面上变了才去存的，
    不重画就停在没存上的值上，下面的总功率、读数还是旧配装的，再点同一项也不会触发（审查 2026-11-08）"""
    from pathlib import Path

    js = (Path(__file__).parents[1] / "astral_toolkit/app/web/app.js").read_text(
        encoding="utf-8"
    )
    start = js.index("function gearRender()")
    body = js[start : js.index("\nfunction ", start)]
    assert "catch (e) { toast(e.message); gearRender(); }" in body  # 改配装
    assert "catch (er) { toast(er.message); gearRender(); }" in body  # 换船


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
    hud, _ = _world(monkeypatch, tmp_path, lambda img: Scan())
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

    result = analyze(_scan(), _inputs())
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
    scan = _scan()
    expected_hud = present.to_hud(analyze(scan, _inputs()))
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
        view = mining.scan_view(scan)
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
    view = mining.scan_view(_scan())
    assert [x["name"] for x in view["hud_rich"]["comp"]] == ["钨"]
    found = [(3870, False, "3870", None), (4240, False, "4240", None)]
    assert signals.describe_all(
        found, "space", focus=mining_helpers.links().focus()
    ) == signals.describe_all(found[:1], "space")
    settings.update(mining_focus=["missing", 42, {}])
    assert mining_helpers.links().focus() == []
    assert not any(x["on"] for x in mining.mining_gear()["focus"])
    assert mining.scan_view(_scan())["hud_rich"]["comp"] == []
