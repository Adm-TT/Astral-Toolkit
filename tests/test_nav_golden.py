"""导航黄金测试：不读本机数据，把导航视图、记号、日志现在的输出逐项锁住。

NV-B1～B4 拆走 `tasks/mining.py` 里的导航函数时，这些字面量应当一个字都不变。
"""

from types import SimpleNamespace

from astral_toolkit.app import nav_marker
from astral_toolkit.app.presenters import nav as present_nav
from astral_toolkit.tasks import navigation as navigation_tasks
from astral_toolkit.navigation import navigate as N


class _Clock:
    def __init__(self, now=0.0, text="12:00:00"):
        self.now = now
        self.text = text

    def time(self):
        return self.now

    def strftime(self, fmt):
        assert fmt == "%H:%M:%S"
        return self.text


def _install_nav(monkeypatch, **over):
    defaults = {
        "here_text": lambda here, data: "这里",
        "body_label": lambda b: {"B1": "本星", "B2": "目标星"}.get(b, b),
        "is_city": lambda target: bool(target.get("city")),
        "pos": lambda x: x.get("p", (0.0, 0.0, 0.0)),
        "bearing": lambda a, t: 100.0,
        "compass": lambda brg: "罗盘",
        "surface_km": lambda a, t, r: 123.45,
        "direct_km": lambda a, t: 200.0,
        "latlon": lambda t: (10.0, 20.0, 0.5),
        "city_metrics": lambda here, target: (12.0, 3.0),
        "city_arrived": lambda d, prev_arrived: False,
        "nearby": lambda here, data: None,
        "label": lambda p: p.get("n", "?") if isinstance(p, dict) else str(p),
        "approaches": lambda target, data, top=1: [],
        "deg_text": lambda brg: f"{brg:.1f}",
        "space_guide": lambda g, target, data: {
            "same_system": True,
            "direct": 1.0,
            "arrived": False,
            "aim": None,
            "qt": None,
        },
        "space_text": lambda g, target, data: "太空",
        "system_info": lambda g, data, **kw: ("S1", True),
        "target_global": lambda target, data, when=None, ref=None: (0.0, 0.0, 0.0),
        "station_text": lambda g, target, data, when, arrived: "站内",
        "SYS_ZH": {"S1": "一号", "S2": "二号"},
        "CITY_NEAR_M": 500.0,
    }
    for key, value in defaults.items():
        monkeypatch.setattr(N, key, over.pop(key, value))
    assert not over


# 记号测试的录制：放模块级对象上（挂在函数上 basedpyright 不认）
_REC = SimpleNamespace(hud=[], diag=[])


def _install_marker(
    monkeypatch,
    *,
    current,
    clock,
    running=False,
    marker_on=True,
    foreground: object = True,
    settings=None,
    last_fov=lambda: 70.0,
    area=None,
):
    if settings is None:
        settings = {
            "nav_marker": True,
            "fov_axis": "v",
            "nav_mode": "auto",
            "debug_mode": False,
        }
    ctl = {
        "current": current,
        "running": running,
        "marker_on": marker_on,
        "foreground": foreground,
    }

    def foreground_func():
        if ctl["foreground"] == "raise":
            raise RuntimeError("foreground")
        return ctl["foreground"]

    _REC.hud = []
    _REC.diag = []
    marker = nav_marker._NavMarker(
        SimpleNamespace(snapshot=lambda: SimpleNamespace(current=ctl["current"])),
        mining_running=lambda: ctl["running"],
        foreground=foreground_func,
        game_area=lambda: area or {"left": 0, "top": 0, "width": 2560, "height": 1440},
        last_fov=last_fov,
        settings=lambda: settings,
        hud=lambda: SimpleNamespace(marker=lambda data: _REC.hud.append(data)),
        diag=lambda why: _REC.diag.append(why),
        clock=clock.time,
    )
    monkeypatch.setattr(marker, "enabled", lambda: ctl["marker_on"])
    return marker, ctl


def _blank_marker(*, settings, clock=None, hud=lambda: None):
    return nav_marker._NavMarker(
        SimpleNamespace(snapshot=lambda: SimpleNamespace(current=(0.0, None, None))),
        mining_running=lambda: False,
        foreground=lambda: True,
        game_area=lambda: {"left": 0, "top": 0, "width": 2560, "height": 1440},
        last_fov=lambda: None,
        settings=settings,
        hud=hud,
        diag=lambda _why: None,
        clock=clock,
    )


def test_nav_view_far_city_and_plain(monkeypatch):
    _install_nav(monkeypatch)
    here = {
        "inside": True,
        "body": "B1",
        "radius_km": 100.0,
        "height_m": 12.0,
        "lat": 1.0,
        "lon": 2.0,
    }
    city_target = {
        "b": "B2",
        "city": True,
        "city_zh": "目标城",
    }
    assert present_nav.ground_view_of(here, city_target, {}) == {
        "text": "这里",
        "inside": True,
        "body": "本星",
        "same_body": False,
        "far": "先前往目标城，到达城市后按步行指引前往",
    }

    plain_target = {"b": "B2"}
    assert present_nav.ground_view_of(here, plain_target, {}) == {
        "text": "这里",
        "inside": True,
        "body": "本星",
        "same_body": False,
        "far": "先量子跳跃到 目标星，再按推荐路线前往",
    }


def test_nav_view_same_body_steady_and_arrived(monkeypatch):
    _install_nav(
        monkeypatch,
        bearing=lambda a, t: 350.0,
        compass=lambda brg: "北偏西",
        surface_km=lambda a, t, r: 12.345,
        direct_km=lambda a, t: 13.0,
        latlon=lambda t: (10.0, 20.0, 0.5),
    )
    here = {
        "inside": True,
        "body": "B1",
        "p": (1.0, 2.0, 3.0),
        "radius_km": 100.0,
        "height_m": 12.0,
        "lat": 1.0,
        "lon": 2.0,
    }
    target = {"b": "B1", "p": (4.0, 5.0, 6.0)}
    assert present_nav.ground_view_of(here, target, {}) == {
        "text": "这里",
        "inside": True,
        "body": "本星",
        "same_body": True,
        "raw_bearing": 350.0,
        "bearing": 350.0,
        "compass": "北偏西",
        "surface": 12.345,
        "direct": 13.0,
        "height": 12.0,
        "target_height": -99500.0,
        "lat": 1.0,
        "lon": 2.0,
        "arrived": False,
        "near": None,
    }
    assert present_nav.ground_view_of(
        here, target, {}, steady=lambda brg: brg - 20.0
    ) == {
        "text": "这里",
        "inside": True,
        "body": "本星",
        "same_body": True,
        "raw_bearing": 350.0,
        "bearing": 330.0,
        "compass": "北偏西",
        "surface": 12.345,
        "direct": 13.0,
        "height": 12.0,
        "target_height": -99500.0,
        "lat": 1.0,
        "lon": 2.0,
        "arrived": False,
        "near": None,
    }

    _install_nav(
        monkeypatch,
        surface_km=lambda a, t, r: 0.5,
        compass=lambda brg: "东",
    )
    assert present_nav.ground_view_of(here, target, {}) == {
        "text": "这里",
        "inside": True,
        "body": "本星",
        "same_body": True,
        "raw_bearing": 100.0,
        "bearing": 100.0,
        "compass": "东",
        "surface": 0.5,
        "direct": 200.0,
        "height": 12.0,
        "target_height": -99500.0,
        "lat": 1.0,
        "lon": 2.0,
        "arrived": True,
        "near": None,
    }


def test_nav_view_city_uses_prev(monkeypatch):
    seen = []
    _install_nav(
        monkeypatch,
        city_metrics=lambda here, target: (120.0, 7.5),
        city_arrived=lambda d, prev_arrived: seen.append((d, prev_arrived)) or True,
        CITY_NEAR_M=500.0,
    )
    here = {
        "inside": True,
        "body": "B1",
        "radius_km": 100.0,
        "height_m": 12.0,
        "lat": 1.0,
        "lon": 2.0,
    }
    target = {"b": "B1", "city": True, "up": (0.0, 1.0, 0.0)}
    prev = {"city": True, "arrived": True}
    assert present_nav.ground_view_of(here, target, {}, prev=prev) == {
        "text": "这里",
        "inside": True,
        "body": "本星",
        "same_body": True,
        "raw_bearing": 100.0,
        "bearing": 100.0,
        "compass": "罗盘",
        "surface": 123.45,
        "direct": 200.0,
        "height": 12.0,
        "target_height": -99500.0,
        "lat": 1.0,
        "lon": 2.0,
        "arrived": True,
        "city": True,
        "close": False,
        "direct_m": 120.0,
        "updown": 7.5,
        "near": None,
        "station": True,
    }
    assert seen == [(120.0, True)]


def test_nav_view_hint_boundary(monkeypatch):
    target = {"b": "B1", "p": (4.0, 5.0, 6.0)}
    here = {
        "inside": True,
        "body": "B1",
        "radius_km": 100.0,
        "height_m": 12.0,
        "lat": 1.0,
        "lon": 2.0,
    }
    q = {"n": "量子点"}
    _install_nav(
        monkeypatch,
        surface_km=lambda a, t, r: 40.0,
        approaches=lambda target, data, top=1: [(0.0, 19.9, 88.8, q)],
        label=lambda p: p["n"],
        deg_text=lambda brg: "88.8",
        nearby=lambda here, data: (3.2, {"n": "附近点"}),
    )
    out = present_nav.ground_view_of(here, target, {})
    assert out["near"] == {"name": "附近点", "km": 3.2}
    assert (
        out["hint"]
        == "距离过远：先量子跳跃到 量子点（距目标 19.9 km），再朝 88.8° 飞行"
    )

    _install_nav(
        monkeypatch,
        surface_km=lambda a, t, r: 40.0,
        approaches=lambda target, data, top=1: [(0.0, 20.0, 88.8, q)],
        label=lambda p: p["n"],
        deg_text=lambda brg: "88.8",
    )
    assert "hint" not in present_nav.ground_view_of(here, target, {})

    _install_nav(
        monkeypatch,
        surface_km=lambda a, t, r: 30.0,
        approaches=lambda target, data, top=1: [(0.0, 1.0, 88.8, q)],
        label=lambda p: p["n"],
        deg_text=lambda brg: "88.8",
    )
    assert "hint" not in present_nav.ground_view_of(here, target, {})


def test_space_view_same_and_other_system(monkeypatch):
    _install_nav(
        monkeypatch,
        space_guide=lambda g, target, data: {
            "same_system": True,
            "direct": 12.5,
            "arrived": True,
            "aim": (0.1, 0.2),
            "qt": "QT",
            "target_system": "S9",
        },
        space_text=lambda g, target, data: "同一星系",
        SYS_ZH={"S1": "一号"},
    )
    assert present_nav.space_view_of((0.0, 0.0, 0.0), {"b": "@S1"}, {}) == {
        "space": True,
        "same_body": False,
        "inside": False,
        "text": "同一星系",
        "direct": 12.5,
        "arrived": True,
        "aim": (0.1, 0.2),
        "qt": "QT",
    }

    def guide_other(g, target, data):
        return {"same_system": False, "target_system": "S1"}

    _install_nav(
        monkeypatch,
        space_guide=guide_other,
        space_text=lambda g, target, data: "另一星系",
        SYS_ZH={"S1": "一号"},
    )
    assert present_nav.space_view_of((0.0, 0.0, 0.0), {"b": "@S1"}, {}) == {
        "space": True,
        "same_body": False,
        "inside": False,
        "text": "另一星系",
        "far": "目标位于 一号星系，需先跃迁到该星系",
    }

    _install_nav(
        monkeypatch,
        space_guide=guide_other,
        space_text=lambda g, target, data: "另一星系",
        SYS_ZH={},
    )
    assert present_nav.space_view_of((0.0, 0.0, 0.0), {"b": "@S1"}, {})["far"] == (
        "目标位于 S1星系，需先跃迁到该星系"
    )


def test_station_view_branches(monkeypatch):
    g = (0.0, 0.0, 0.0)
    target_same = {"b": "@S1", "sys": "S1", "up": (0.0, 1.0, 0.0)}
    target_other = {"b": "@S2", "sys": "S2"}

    def raise_info(g, data, **kw):
        raise RuntimeError("no system")

    _install_nav(
        monkeypatch,
        system_info=raise_info,
        target_global=lambda target, data, when=None, ref=None: (1000.0, 0.0, 0.0),
        city_arrived=lambda d, prev_arrived: False,
        station_text=lambda g, target, data, when, arrived: "到站",
        CITY_NEAR_M=500.0,
    )
    assert present_nav.station_view_of(g, target_same, {}) == {
        "space": True,
        "city": True,
        "station": True,
        "inside": True,
        "same_body": True,
        "direct": 1.0,
        "direct_m": 1000.0,
        "arrived": False,
        "close": False,
        "updown": 0.0,
        "text": "到站",
    }

    _install_nav(
        monkeypatch,
        system_info=lambda g, data, **kw: ("S9", True),
        target_global=lambda target, data, when=None, ref=None: (999999.0, 0.0, 0.0),
        SYS_ZH={"S2": "二号"},
    )
    assert present_nav.station_view_of(g, target_other, {}) == {
        "space": True,
        "city": True,
        "station": True,
        "inside": True,
        "same_body": True,
        "far": "目标位于 二号星系，需先跃迁到该星系",
    }

    _install_nav(
        monkeypatch,
        system_info=lambda g, data, **kw: ("S1", True),
        target_global=lambda target, data, when=None, ref=None: (60000.0, 0.0, 0.0),
    )
    assert present_nav.station_view_of(g, {"city_zh": "远站"}, {}) == {
        "space": True,
        "city": True,
        "station": True,
        "inside": True,
        "same_body": True,
        "direct": 60.0,
        "direct_m": 60000.0,
        "far": "先前往远站，到站后按步行指引前往",
    }

    _install_nav(
        monkeypatch,
        system_info=lambda g, data, **kw: ("S1", True),
        target_global=lambda target, data, when=None, ref=None: (10000.0, 0.0, 0.0),
        city_arrived=lambda d, prev_arrived: True,
        station_text=lambda g, target, data, when, arrived: f"到了 {arrived}",
        CITY_NEAR_M=20000.0,
    )
    assert present_nav.station_view_of(g, target_same, {}) == {
        "space": True,
        "city": True,
        "station": True,
        "inside": True,
        "same_body": True,
        "direct": 10.0,
        "direct_m": 10000.0,
        "arrived": True,
        "close": False,
        "updown": 0.0,
        "text": "到了 True",
    }

    _install_nav(
        monkeypatch,
        system_info=lambda g, data, **kw: ("S1", True),
        target_global=lambda target, data, when=None, ref=None: (10000.0, 0.0, 0.0),
        city_arrived=lambda d, prev_arrived: False,
        station_text=lambda g, target, data, when, arrived: f"到了 {arrived}",
        CITY_NEAR_M=20000.0,
    )
    assert present_nav.station_view_of(g, target_same, {}) == {
        "space": True,
        "city": True,
        "station": True,
        "inside": True,
        "same_body": True,
        "direct": 10.0,
        "direct_m": 10000.0,
        "arrived": False,
        "close": True,
        "updown": 0.0,
        "text": "到了 False",
    }

    _install_nav(
        monkeypatch,
        system_info=lambda g, data, **kw: ("S1", True),
        target_global=lambda target, data, when=None, ref=None: (10000.0, 0.0, 0.0),
        city_arrived=lambda d, prev_arrived: False,
        station_text=lambda g, target, data, when, arrived: "没到",
        CITY_NEAR_M=1000.0,
    )
    assert present_nav.station_view_of(g, {"b": "@S1"}, {}) == {
        "space": True,
        "city": True,
        "station": True,
        "inside": True,
        "same_body": True,
        "direct": 10.0,
        "direct_m": 10000.0,
        "arrived": False,
        "close": False,
        "updown": 0.0,
        "text": "没到",
    }


def test_marker_hide_reasons_and_precedence(monkeypatch):
    clock = _Clock(100.0)
    marker, ctl = _install_marker(
        monkeypatch,
        current=(
            100.0,
            (0.0, 0.0, 0.0),
            {"camdir": (0.0, 0.0, -90.0), "fov": 70.0, "t": 100.0},
        ),
        clock=clock,
    )
    scenarios = [
        ("no_position", {"h": None, "g": None}, "还没算出位置"),
        (
            "no_camera",
            {
                "h": {"arrived": True, "far": True},
                "g": (1.0, 2.0, 3.0),
                "info": {"t": 100.0},
                "now": 110.0,
                "fg": False,
                "running": True,
                "marker_on": False,
            },
            "没有镜头方向",
        ),
        (
            "stale",
            {
                "h": {"arrived": True, "far": True},
                "g": (1.0, 2.0, 3.0),
                "info": {"camdir": (0.0, 0.0, -90.0), "t": 100.0},
                "now": 104.0,
                "fg": False,
                "running": True,
                "marker_on": False,
            },
            "读数过期",
        ),
        (
            "arrived",
            {
                "h": {"arrived": True, "far": True},
                "g": (1.0, 2.0, 3.0),
                "info": {"camdir": (0.0, 0.0, -90.0), "t": 100.0},
                "now": 100.5,
                "fg": False,
                "running": True,
                "marker_on": False,
            },
            "已到达",
        ),
        (
            "far",
            {
                "h": {"far": True},
                "g": (1.0, 2.0, 3.0),
                "info": {"camdir": (0.0, 0.0, -90.0), "t": 100.0},
                "now": 100.5,
                "fg": False,
                "running": True,
                "marker_on": False,
            },
            "跨星系",
        ),
        (
            "not_foreground",
            {
                "h": {},
                "g": (1.0, 2.0, 3.0),
                "info": {"camdir": (0.0, 0.0, -90.0), "t": 100.0},
                "now": 100.5,
                "fg": False,
                "running": True,
                "marker_on": False,
            },
            "游戏不在前台",
        ),
        (
            "mining_running",
            {
                "h": {},
                "g": (1.0, 2.0, 3.0),
                "info": {"camdir": (0.0, 0.0, -90.0), "t": 100.0},
                "now": 100.5,
                "fg": True,
                "running": True,
                "marker_on": False,
            },
            "采矿助手开着",
        ),
        (
            "setting_off",
            {
                "h": {},
                "g": (1.0, 2.0, 3.0),
                "info": {"camdir": (0.0, 0.0, -90.0), "t": 100.0},
                "now": 100.5,
                "fg": True,
                "running": False,
                "marker_on": False,
            },
            "设置里关了",
        ),
    ]
    for name, case, reason in scenarios:
        marker.why = None
        marker.cam_last.clear()
        marker.cam_last.update(t=0.0, cam=None)
        clock.now = case.get("now", 100.0)
        ctl["current"] = (
            case.get("t", 100.0),
            case.get("g", (0.0, 0.0, 0.0)),
            case.get("info", {"camdir": (0.0, 0.0, -90.0), "t": 100.0}),
        )
        ctl["foreground"] = case.get("fg", True)
        ctl["running"] = case.get("running", False)
        ctl["marker_on"] = case.get("marker_on", True)
        _REC.hud = []
        _REC.diag = []
        assert marker.tick({"b": "@S1"}, {}, {"here": case["h"]}, 7.0) is None, name
        assert _REC.hud == [None], name
        assert _REC.diag == [reason], name
        assert marker.why == reason, name


def test_marker_reason_not_repeated_and_hidden_only_when_shown(monkeypatch):
    clock = _Clock(100.5)
    marker, ctl = _install_marker(
        monkeypatch,
        current=(100.0, (0.0, 0.0, 0.0), {"t": 100.0}),
        clock=clock,
    )
    ctl["foreground"] = True
    assert marker.tick({}, {}, {"here": {}}, None) is None
    assert marker.tick({}, {}, {"here": {}}, None) is None
    assert _REC.hud == []
    assert _REC.diag == ["没有镜头方向"]

    assert marker.tick({}, {}, {"here": {}}, 12.0) is None
    assert _REC.hud == [None]
    assert _REC.diag == ["没有镜头方向"]


def test_marker_camera_hold_within_and_over_one_second(monkeypatch):
    clock = _Clock(100.1)
    marker, ctl = _install_marker(
        monkeypatch,
        current=(
            100.0,
            (1.0, 2.0, 3.0),
            {"camdir": (0.0, 0.0, -90.0), "fov": 70.0, "t": 100.0},
        ),
        clock=clock,
    )
    calls = []
    monkeypatch.setattr(
        N, "target_global", lambda target, data, when=None, ref=None: ("TG",)
    )
    monkeypatch.setattr(
        N,
        "project",
        lambda g, cam, fov, tg, w, h, vertical=True: (
            calls.append((g, cam, fov, tg, w, h, vertical)) or {"dist": 12.3}
        ),
    )
    monkeypatch.setattr(N, "dist_text", lambda dist: f"{dist} km")
    ctl["foreground"] = True

    shown = marker.tick({"b": "@S1"}, {}, {"here": {}}, None)
    assert shown == 100.0
    assert calls[-1] == (
        (1.0, 2.0, 3.0),
        (0.0, 0.0, -90.0),
        70.0,
        ("TG",),
        2560,
        1440,
        True,
    )
    assert _REC.hud == [
        {
            "area": (0, 0, 2560, 1440),
            "proj": {"dist": 12.3},
            "label": "12.3 km",
        }
    ]

    clock.now = 100.6
    ctl["current"] = (100.5, (1.0, 2.0, 3.0), {"t": 100.5})
    shown = marker.tick({"b": "@S1"}, {}, {"here": {}}, shown)
    assert shown == 100.5
    assert calls[-1][1] == (0.0, 0.0, -90.0)

    clock.now = 101.2
    ctl["current"] = (101.1, (1.0, 2.0, 3.0), {"t": 101.1})
    assert marker.tick({"b": "@S1"}, {}, {"here": {}}, shown) is None
    assert _REC.hud[-1] is None
    assert _REC.diag == ["没有镜头方向"]


def test_marker_visible_projection_uses_info_fov_and_vertical(monkeypatch):
    clock = _Clock(100.5)
    marker, _ = _install_marker(
        monkeypatch,
        current=(
            100.0,
            (1.0, 2.0, 3.0),
            {"camdir": (0.1, 0.2, -0.3), "fov": 80.0, "t": 11.0},
        ),
        clock=clock,
        foreground="raise",
        settings={
            "nav_marker": True,
            "fov_axis": "v",
            "nav_mode": "auto",
            "debug_mode": False,
        },
        last_fov=lambda: 65.0,
        area={"left": 0, "top": 0, "width": 2560, "height": 1440},
    )
    seen = []
    monkeypatch.setattr(
        N,
        "target_global",
        lambda target, data, when=None, ref=None: (
            seen.append(("tg", target, data, when, ref)) or ("TARGET",)
        ),
    )
    monkeypatch.setattr(
        N,
        "project",
        lambda g, cam, fov, tg, w, h, vertical=True: (
            seen.append(("pr", g, cam, fov, tg, w, h, vertical))
            or {"dist": 34.56, "x": 1.0}
        ),
    )
    monkeypatch.setattr(
        N, "dist_text", lambda dist: seen.append(("dist", dist)) or "34.6 km"
    )

    target = {"b": "@S1"}
    data = {"k": "v"}
    assert marker.tick(target, data, {"here": {"x": 1}}, None, ref="REF") == 100.0
    assert seen == [
        ("tg", target, data, 11.0, "REF"),
        ("pr", (1.0, 2.0, 3.0), (0.1, 0.2, -0.3), 80.0, ("TARGET",), 2560, 1440, True),
        ("dist", 34.56),
    ]
    assert _REC.hud == [
        {
            "area": (0, 0, 2560, 1440),
            "proj": {"dist": 34.56, "x": 1.0},
            "label": "34.6 km",
        }
    ]


def test_marker_visible_projection_falls_back_to_last_fov_and_horizontal(monkeypatch):
    clock = _Clock(200.2)
    marker, _ = _install_marker(
        monkeypatch,
        current=(200.0, (1.0, 2.0, 3.0), {"camdir": (0.0, 0.0, -90.0), "t": 200.0}),
        clock=clock,
        foreground=True,
        settings={
            "nav_marker": True,
            "fov_axis": "h",
            "nav_mode": "auto",
            "debug_mode": False,
        },
        last_fov=lambda: 66.0,
        area={"left": 100, "top": 50, "width": 1920, "height": 1080},
    )
    got = []
    monkeypatch.setattr(
        N, "target_global", lambda target, data, when=None, ref=None: ("TG",)
    )
    monkeypatch.setattr(
        N,
        "project",
        lambda g, cam, fov, tg, w, h, vertical=True: (
            got.append((fov, w, h, vertical)) or {"dist": 1.0}
        ),
    )
    monkeypatch.setattr(N, "dist_text", lambda dist: "1.0 km")
    assert marker.tick({"b": "@S1"}, {}, {"here": {}}, None) == 200.0
    assert got == [(66.0, 1920, 1080, False)]
    assert _REC.hud[-1]["area"] == (100, 50, 1920, 1080)


def test_marker_visible_projection_defaults_to_70(monkeypatch):
    clock = _Clock(300.2)
    marker, _ = _install_marker(
        monkeypatch,
        current=(300.0, (1.0, 2.0, 3.0), {"camdir": (0.0, 0.0, -90.0), "t": 300.0}),
        clock=clock,
        foreground=True,
        last_fov=lambda: None,
    )
    got = []
    monkeypatch.setattr(
        N, "target_global", lambda target, data, when=None, ref=None: ("TG",)
    )
    monkeypatch.setattr(
        N,
        "project",
        lambda g, cam, fov, tg, w, h, vertical=True: (
            got.append((fov, w, h, vertical)) or {"dist": 2.0}
        ),
    )
    monkeypatch.setattr(N, "dist_text", lambda dist: "2.0 km")
    assert marker.tick({"b": "@S1"}, {}, {"here": {}}, None) == 300.0
    assert got == [(70.0, 2560, 1440, True)]


def test_marker_project_raises_clears_and_returns_none(monkeypatch):
    clock = _Clock(400.3)
    marker, _ = _install_marker(
        monkeypatch,
        current=(400.0, (1.0, 2.0, 3.0), {"camdir": (0.0, 0.0, -90.0), "t": 400.0}),
        clock=clock,
        foreground=True,
    )
    monkeypatch.setattr(
        N, "target_global", lambda target, data, when=None, ref=None: ("TG",)
    )
    monkeypatch.setattr(
        N,
        "project",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("project")),
    )
    assert marker.tick({"b": "@S1"}, {}, {"here": {}}, None) is None
    assert _REC.hud == [None]
    assert _REC.diag == []


def test_marker_shown_equal_t_does_not_redraw(monkeypatch):
    clock = _Clock(500.1)
    marker, _ = _install_marker(
        monkeypatch,
        current=(500.0, (1.0, 2.0, 3.0), {"camdir": (0.0, 0.0, -90.0), "t": 500.0}),
        clock=clock,
        foreground=True,
    )
    monkeypatch.setattr(
        N,
        "target_global",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not project")),
    )
    assert marker.tick({"b": "@S1"}, {}, {"here": {}}, 500.0) == 500.0
    assert _REC.hud == []
    assert _REC.diag == []


def test_marker_on_reads_every_two_seconds_and_only_false_is_off():
    clock = _Clock(10.0)
    reads = []
    readers = {"load": lambda: {"nav_marker": True}}
    marker = _blank_marker(
        settings=lambda: readers["load"](),
        clock=clock.time,
    )

    def load():
        reads.append(clock.now)
        return {"nav_marker": [False, True][len(reads) - 1]}

    readers["load"] = load
    assert marker.enabled() is False
    assert marker.enabled() is False
    assert reads == [10.0]
    clock.now = 12.0
    assert marker.enabled() is False
    assert reads == [10.0]
    clock.now = 12.1
    assert marker.enabled() is True
    assert reads == [10.0, 12.1]

    for value, expected in [(0, True), (None, True), (False, False)]:
        clock.now += 3.0
        marker.cfg.update(on=not expected, at=0.0)
        readers["load"] = lambda v=value: {"nav_marker": v}
        assert marker.enabled() is expected


def test_marker_on_settings_error_is_on():
    clock = _Clock(20.0)

    def settings():
        raise RuntimeError("settings")

    marker = _blank_marker(settings=settings, clock=clock.time)
    assert marker.enabled() is True
    assert marker.cfg == {"on": True, "at": 20.0}


def test_marker_clear_missing_hud_or_marker_does_not_raise():
    assert _blank_marker(settings=lambda: {}, hud=lambda: None).clear() is None
    assert (
        _blank_marker(
            settings=lambda: {},
            hud=lambda: SimpleNamespace(),
        ).clear()
        is None
    )


def test_nav_log_line_with_and_without_local(monkeypatch, tmp_path):
    clock = _Clock(1234.5)
    monkeypatch.setattr(navigation_tasks, "time", clock)
    monkeypatch.setattr("astral_toolkit.core.paths.log", lambda name: tmp_path / name)
    here = {"src": "ocr", "x": 1.25, "y": 2.5, "z": -3.75}
    view = {"raw_bearing": 12.34, "bearing": 45.6, "surface": 1.239}
    navigation_tasks.nav_log(
        here, {"local_ok": True, "local": [1.23456, 2.34567, 3.0]}, view
    )
    navigation_tasks.nav_log(here, {"local_ok": False, "local": None}, view)
    assert (tmp_path / "nav_log.txt").read_text(encoding="utf-8").splitlines() == [
        "12:00:00 来源=ocr 核对=True 游戏局部=(1.2346, 2.3457, 3.0) "
        "用的=(1.2500, 2.5000, -3.7500) 方位=12.3° 显示=46° 距离=1.24km",
        "12:00:00 来源=ocr 核对=False 游戏局部=None "
        "用的=(1.2500, 2.5000, -3.7500) 方位=12.3° 显示=46° 距离=1.24km",
    ]


def test_nav_log_trims_to_last_thousand_lines_before_append(monkeypatch, tmp_path):
    clock = _Clock(1700000000.125)
    monkeypatch.setattr(navigation_tasks, "time", clock)
    monkeypatch.setattr("astral_toolkit.core.paths.log", lambda name: tmp_path / name)
    log = tmp_path / "nav_log.txt"
    old = [f"old-{i:04d}-" + "x" * 400 for i in range(1, 1101)]
    log.write_text("\n".join(old) + "\n", encoding="utf-8")
    assert log.stat().st_size > 300_000
    here = {"src": "ocr", "x": 1.25, "y": 2.5, "z": -3.75}
    view = {"raw_bearing": 12.34, "bearing": 45.6, "surface": 1.239}
    navigation_tasks.nav_log(here, {"local_ok": True, "local": None}, view)
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1001
    assert lines[0] == old[100]
    assert lines[-2] == old[-1]
    assert lines[-1] == (
        "12:00:00 来源=ocr 核对=True 游戏局部=None "
        "用的=(1.2500, 2.5000, -3.7500) 方位=12.3° 显示=46° 距离=1.24km"
    )


def test_mark_diag_two_lines(monkeypatch, tmp_path):
    clock = _Clock(1234.5)
    monkeypatch.setattr(nav_marker, "time", clock)
    monkeypatch.setattr("astral_toolkit.core.paths.log", lambda name: tmp_path / name)
    nav_marker.marker_diag("读数过期")
    nav_marker.marker_diag(None)
    assert (tmp_path / "di_log.txt").read_text(encoding="utf-8").splitlines() == [
        "12:00:00.500 记号 收起：读数过期",
        "12:00:00.500 记号 显示",
    ]


def test_nav_view_hint_needs_more_than_30_km(monkeypatch):
    """边界：表面距离 30.5 km 出提示（30 km 整不出，见上一条）"""
    target = {"b": "B1", "p": (4.0, 5.0, 6.0)}
    here = {
        "inside": True,
        "body": "B1",
        "radius_km": 100.0,
        "height_m": 12.0,
        "lat": 1.0,
        "lon": 2.0,
    }
    q = {"n": "量子点"}
    _install_nav(
        monkeypatch,
        surface_km=lambda a, t, r: 30.5,
        approaches=lambda target, data, top=1: [(0.0, 1.0, 88.8, q)],
        label=lambda p: p["n"],
        deg_text=lambda brg: "88.8",
    )
    assert present_nav.ground_view_of(here, target, {})["hint"] == (
        "距离过远：先量子跳跃到 量子点（距目标 1.0 km），再朝 88.8° 飞行"
    )


def test_station_view_50_km_boundary(monkeypatch):
    """边界：正好 50 km 还按站内走，多半米就让先去空间站"""
    g = (0.0, 0.0, 0.0)
    for d, far in ((50_000.0, False), (50_000.5, True)):
        _install_nav(
            monkeypatch,
            system_info=lambda g, data, **kw: ("S1", True),
            target_global=lambda target, data, when=None, ref=None, d=d: (d, 0.0, 0.0),
            city_arrived=lambda d, prev_arrived: False,
            station_text=lambda g, target, data, when, arrived: "到站",
            CITY_NEAR_M=500.0,
        )
        out = present_nav.station_view_of(g, {"city_zh": "远站", "sys": "S1"}, {})
        assert ("far" in out) is far, d
        assert out["direct_m"] == d


def test_nav_log_trims_only_above_300000_bytes(monkeypatch, tmp_path):
    """边界：正好 300000 字节不截；多 1 字节就只留最后 1000 行再追加"""
    clock = _Clock(1700000000.125)
    monkeypatch.setattr(navigation_tasks, "time", clock)
    monkeypatch.setattr("astral_toolkit.core.paths.log", lambda name: tmp_path / name)
    log = tmp_path / "nav_log.txt"
    here = {"src": "ocr", "x": 1.25, "y": 2.5, "z": -3.75}
    view = {"raw_bearing": 12.34, "bearing": 45.6, "surface": 1.239}
    body = ("y" * 199 + "\n") * 1500
    for extra, want in ((0, 1501), (1, 1001)):
        log.write_bytes((("z" if extra else "") + body).encode("utf-8"))
        assert log.stat().st_size == 300_000 + extra
        navigation_tasks.nav_log(here, {"local_ok": True, "local": None}, view)
        assert len(log.read_text(encoding="utf-8").splitlines()) == want, extra


def test_station_view_updown_sign(monkeypatch):
    """站内上下：目标在站的「上」方向那一侧为正（变异检查：点积反过来要测得出）"""
    _install_nav(
        monkeypatch,
        system_info=lambda g, data, **kw: ("S1", True),
        target_global=lambda target, data, when=None, ref=None: (1000.0, 300.0, 0.0),
        city_arrived=lambda d, prev_arrived: False,
        station_text=lambda g, target, data, when, arrived: "到站",
        CITY_NEAR_M=500.0,
    )
    out = present_nav.station_view_of(
        (0.0, 0.0, 0.0), {"sys": "S1", "up": (0.0, 1.0, 0.0)}, {}
    )
    assert out["updown"] == 300.0


def test_nav_view_arrived_needs_less_than_1_km(monkeypatch):
    """边界：表面距离正好 1 km 还没到，0.999 km 算到（变异检查：到达阈值改了要测得出）"""
    target = {"b": "B1", "p": (4.0, 5.0, 6.0)}
    here = {
        "inside": True,
        "body": "B1",
        "radius_km": 100.0,
        "height_m": 12.0,
        "lat": 1.0,
        "lon": 2.0,
    }
    for surface, arrived in ((1.0, False), (0.999, True), (1.5, False)):
        _install_nav(monkeypatch, surface_km=lambda a, t, r, s=surface: s)
        assert present_nav.ground_view_of(here, target, {})["arrived"] is arrived, (
            surface
        )


def test_station_view_passes_reading_time_to_target_global(monkeypatch):
    """站内视图把读数时间传给 target_global（站跟着星球转，算目标坐标要用读数那一刻）"""
    seen = []
    _install_nav(
        monkeypatch,
        target_global=lambda target, data, when=None, ref=None: (
            seen.append(when) or (0.0, 0.0, 0.0)
        ),
    )
    present_nav.station_view_of((0.0, 0.0, 0.0), {"sys": "S1"}, {}, when=123.0)
    assert seen == [123.0]
