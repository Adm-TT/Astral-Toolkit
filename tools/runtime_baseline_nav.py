"""导航行为基线（NV-B0）：用本机真实星图数据跑 8 个导航函数，把输出录成 JSON；改完再跑，逐项比较。

用法（在项目根目录）：
  .venv\\Scripts\\python.exe -X utf8 tools\\runtime_baseline_nav.py --out <输出.json>
  .venv\\Scripts\\python.exe -X utf8 tools\\runtime_baseline_nav.py --compare <改前.json> <改后.json>

输入尽量照现有测试的造法：地面用 test_tools.py 的静止定位，站内用真实星图 / 城镇地点里能走通的空间站目标，
太空用 test_nav_session.py 的停着转镜头位置。造不出来的项写成 {"skipped": "原因"}，改前改后应一致跳过。
不联网、不写 userdata、不导入 overlay；日志、自转校准都写到临时目录。
"""

import argparse
import copy
import importlib
import json
import math
import platform
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import runtime_baseline_mining as base  # noqa: E402

GROUND_G = (22462326485.3, 37186368633.8, 744084.3)
GROUND_WHEN = 1792500000.0
GROUND_ZONE = "OOC Stanton 4 Microtech"

SPACE_G = (8163210720.5, 18591214824.5, -4288975.1)
SPACE_TARGET = {
    "space": True,
    "n": "1",
    "zh": "1",
    "x": 8163217.9574,
    "y": 18591209.2105,
    "z": -4278.6308,
}

GEOM_A = {"left": 0, "top": 0, "width": 2560, "height": 1440}
GEOM_B = {"left": 100, "top": 50, "width": 1920, "height": 1080}
DEFAULT_SETTINGS = {
    "nav_marker": True,
    "fov_axis": "v",
    "nav_mode": "auto",
    "debug_mode": False,
}

MARKER_CAM = (0.0, 0.0, -90.0)
MARKER_TARGET = {"space": True, "n": "1", "x": 1.0, "y": 0.0, "z": 0.0}
MARKER_SCENARIOS = [
    "no_position",
    "no_camera",
    "cam_hold_0_5s",
    "cam_hold_1_5s",
    "stale",
    "arrived",
    "far",
    "not_foreground",
    "foreground_raises",
    "mining_running",
    "setting_off",
    "visible_v_A",
    "visible_h_B",
    "same_t_no_redraw",
    "project_raises",
    "hidden_after_shown",
]
NAV_NAMES = [
    "nav_view.other_body",
    "nav_view.same_body",
    "nav_view.same_body_prev",
    "nav_view.arrived",
    "nav_view.hint",
    "nav_view.city",
]
SPACE_NAMES = ["space_view.same_system", "space_view.other_system"]
STATION_NAMES = [
    "station_view.near",
    "station_view.far_50km",
    "station_view.other_system",
    "station_view.arrived_prev",
]


# ---------------------------------------------------------------- 调用适配
def call_nav_view(here, target, data, steady=None, prev=None):
    from astral_toolkit.tasks import mining

    return mining._nav_view(here, target, data, steady=steady, prev=prev)


def call_station_view(g, target, data, when=None, prev=None, info=None):
    from astral_toolkit.tasks import mining

    return mining._station_view(g, target, data, when=when, prev=prev, info=info)


def call_space_view(g, target, data):
    from astral_toolkit.tasks import mining

    return mining._space_view(g, target, data)


def call_marker_tick(target, data, state, shown, ref=None):
    from astral_toolkit.tasks import mining

    return mining._marker_tick(target, data, state, shown, ref=ref)


def call_nav_log(here, info, view):
    from astral_toolkit.tasks import mining

    return mining._nav_log(here, info, view)


def call_mark_diag(why):
    from astral_toolkit.tasks import mining

    return mining._mark_diag(why)


# ---------------------------------------------------------------- 假时钟与替身
class _Clock:
    def __init__(self, now=GROUND_WHEN):
        self.now = now

    def time(self):
        return self.now

    def strftime(self, _fmt):
        return "12:00:00"


class _FakeLive:
    def __init__(self):
        self.is_running = False

    def running(self):
        return self.is_running

    def config_changed(self):
        pass

    @property
    def prev_stop_pending(self):
        return False


class _FakePositions:
    def __init__(self):
        self.current = (0.0, None, None)

    def snapshot(self):
        return SimpleNamespace(current=self.current)


class _HudRecorder:
    def __init__(self):
        self.calls: list[Any] = []

    def marker(self, data):
        self.calls.append(["marker", data])


class _Sandbox:
    """把任务模块和几个外部依赖换成脚本内的替身；退出时逐项还原"""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.clock = _Clock()
        self.live = _FakeLive()
        self.positions = _FakePositions()
        self.hud = _HudRecorder()
        self.settings = dict(DEFAULT_SETTINGS)
        self.geometry = dict(GEOM_A)
        self.last_fov = None
        self.fg_mode = "true"
        self.M = None
        self._saved: list[tuple[Any, str, Any]] = []
        self._mk_cfg0: dict[str, Any] = {}
        self._cam_last0: dict[str, Any] = {}
        self._mk_why0: dict[str, Any] = {}

    def __enter__(self):
        from astral_toolkit.app import hud_state
        from astral_toolkit.core import capture, paths, settings as settings_mod
        from astral_toolkit.navigation import displayinfo
        from astral_toolkit.system import showloc
        from astral_toolkit.tasks import mining as M

        self.M = M
        self._mk_cfg0 = dict(M._MK_CFG)
        self._cam_last0 = dict(M._CAM_LAST)
        self._mk_why0 = dict(M._MK_WHY)

        self._patch(M, "time", self.clock)
        self._patch(M, "_live", self.live)
        self._patch(M, "_positions", self.positions)
        self._patch(M, "_hud", self._hud)
        self._patch(settings_mod, "load", self._load_settings)
        self._patch(paths, "log", self._log)
        self._patch(capture, "game_area", self._game_area)
        self._patch(displayinfo, "last_fov", self._last_fov)
        self._patch(showloc, "game_foreground", self._foreground)
        self._patch(hud_state, "_hud", self._hud)
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        for obj, name, old in reversed(self._saved):
            setattr(obj, name, old)
        if self.M is not None:
            self.M._MK_CFG.clear()
            self.M._MK_CFG.update(self._mk_cfg0)
            self.M._CAM_LAST.clear()
            self.M._CAM_LAST.update(self._cam_last0)
            self.M._MK_WHY.clear()
            self.M._MK_WHY.update(self._mk_why0)
        return False

    def _patch(self, obj, name, value):
        self._saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def _load_settings(self):
        return self.settings

    def _log(self, name):
        return self.tmp / name

    def _game_area(self):
        return dict(self.geometry)

    def _last_fov(self):
        return self.last_fov

    def _foreground(self):
        if self.fg_mode == "false":
            return False
        if self.fg_mode == "raise":
            raise RuntimeError("game_foreground boom")
        return True

    def _hud(self):
        return self.hud

    def reset(self):
        self.clock.now = 1000.0
        self.live.is_running = False
        self.settings.clear()
        self.settings.update(DEFAULT_SETTINGS)
        self.geometry = dict(GEOM_A)
        self.last_fov = None
        self.fg_mode = "true"
        self.hud.calls.clear()


class _CalibSandbox:
    """locate 校准会写 CALIB：照 test_nav_bearing_is_steady_when_standing_still 指到临时文件"""

    def __init__(self, nav, tmp: Path):
        self.nav = nav
        self.path = tmp / "rotation_calib.json"
        self.old_calib_path = None
        self.old_calib = {}
        self.old_offsets = {}
        self.old_remember = None

    def __enter__(self):
        self.old_calib_path = self.nav.CALIB
        self.old_calib = copy.deepcopy(self.nav._calib)
        self.old_offsets = copy.deepcopy(self.nav._offsets)
        self.old_remember = self.nav._remember
        self.nav.CALIB = self.path
        self.nav._remember = _remember_noop
        self.nav._offsets.clear()
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        self.nav._remember = self.old_remember
        self.nav.CALIB = self.old_calib_path
        self.nav._offsets.clear()
        self.nav._offsets.update(self.old_offsets)
        self.nav._calib.clear()
        self.nav._calib.update(self.old_calib)
        return False


def _remember_noop(*_args, **_kwargs):
    return None


# ---------------------------------------------------------------- 小工具
def _reason(exc) -> str:
    if isinstance(exc, str):
        return exc
    return f"{type(exc).__name__}: {exc}"


def _skipped(exc) -> dict[str, str]:
    return {"skipped": _reason(exc)}


def _skip_all(items, names, exc) -> None:
    for name in names:
        items[name] = _skipped(exc)


def _item(items, name, fn) -> None:
    try:
        items[name] = fn()
    except Exception as exc:  # 造不出来就和改后一样跳过
        items[name] = _skipped(exc)


def _git_head() -> str:
    try:
        return base._git_head()
    except Exception:
        return ""


def _file_stamp(path) -> dict[str, Any] | None:
    if path is None:
        return None
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return {"path": str(p), "exists": False}
    return {
        "path": str(p),
        "exists": True,
        "size": st.st_size,
        "mtime": st.st_mtime,
    }


def _gamedata_paths() -> list[Path]:
    found: list[Path] = []
    try:
        from astral_toolkit import gamedata

        for name in dir(gamedata):
            low = name.lower()
            if not any(k in low for k in ("manifest", "database", "db")):
                continue
            value = getattr(gamedata, name, None)
            if isinstance(value, (str, Path)):
                found.append(Path(value))
    except Exception:
        pass
    try:
        from astral_toolkit.core import paths

        found.extend(
            [
                paths.DATA / "gamedata.json",
                paths.DATA / "gamedata_manifest.json",
                paths.DATA / "manifest.json",
                paths.USER / "gamedata.sqlite",
                paths.USER / "gamedata.db",
            ]
        )
    except Exception:
        pass
    out: list[Path] = []
    seen: set[str] = set()
    for p in sorted(found, key=str):
        key = str(p)
        if key in seen or p.is_dir():
            continue
        seen.add(key)
        out.append(p)
    return out


def _data_stamps(nav) -> Any:
    for name in ("_data_stamp", "_data_stamps"):
        fn = getattr(base, name, None)
        if callable(fn):
            try:
                value = fn()
                if value is not None:
                    return value
            except Exception:
                pass
    return {
        "starmap": _file_stamp(getattr(nav, "CACHE", None)),
        "gamedata": [_file_stamp(p) for p in _gamedata_paths()],
    }


def _meta(nav) -> dict[str, Any]:
    return {
        "git": _git_head(),
        "data": _data_stamps(nav),
        "python": platform.python_version(),
    }


# ---------------------------------------------------------------- 真实数据造输入
def _other_body(data, body) -> str | None:
    for key in sorted((data.get("bodies") or {}), key=str):
        if key != body:
            return key
    return None


def _city_here(target) -> dict[str, Any]:
    x, y, z = float(target["x"]), float(target["y"]), float(target["z"])
    r = math.sqrt(x * x + y * y + z * z)
    h = math.hypot(x, y)
    if r <= 0 or h <= 0:
        raise ValueError("城内地点坐标无效")
    k = 1 - 0.012 / r
    tx, ty = y / h, -x / h
    return {
        "body": target["b"],
        "inside": True,
        "x": x * k + 0.05 * tx,
        "y": y * k + 0.05 * ty,
        "z": z * k,
        "lat": 0.0,
        "lon": 0.0,
        "height_m": 0.0,
        "radius_km": r,
    }


def _hint_target(nav, data, here):
    here_pos = nav.pos(here)
    pois = data.get("pois") or []
    ordered = sorted(
        pois,
        key=lambda p: (
            str(p.get("b")),
            str(p.get("n")),
            str(p.get("t")),
            str(p.get("x")),
            str(p.get("y")),
            str(p.get("z")),
        ),
    )
    for p in ordered:
        if p.get("b") != here.get("body"):
            continue
        if not all(k in p for k in ("x", "y", "z")):
            continue
        if nav.is_city(p):
            continue
        try:
            surface = nav.surface_km(here_pos, nav.pos(p), here["radius_km"])
        except Exception:
            continue
        if surface <= 30:
            continue
        try:
            best = nav.approaches(p, data, top=1)
        except Exception:
            continue
        if best and best[0][1] < surface * 0.5:
            return dict(p)
    return None


def _ground_inputs(nav, data):
    ref = nav.locate(GROUND_G, when=GROUND_WHEN, data=data)
    if not ref or not ref.get("inside"):
        raise RuntimeError("定位结果不在星球附近")

    game = (ref["x"] + 0.8, ref["y"] - 0.6, ref["z"])
    target = {
        "b": ref["body"],
        "x": game[0] + 2.0,
        "y": game[1] + 1.2,
        "z": game[2],
        "n": "目标",
    }
    nav_mod = importlib.import_module("astral_toolkit.app.engines.nav")
    steady = nav_mod._Steady()
    here = None
    last_view = None
    for i in range(12):
        local = None if i % 3 == 2 else game
        here = nav.locate(
            GROUND_G,
            when=GROUND_WHEN,
            data=data,
            local=local,
            zone=GROUND_ZONE,
            local_ok=True if local else None,
        )
        if not here or not here.get("inside"):
            raise RuntimeError("定位结果不在星球附近")
        last_view = call_nav_view(here, target, data, steady)
    if here is None or last_view is None:
        raise RuntimeError("没有造出地面定位")
    return here, target, steady, last_view


def _collect_nav(items, nav, data) -> None:
    try:
        here, target, steady, last_view = _ground_inputs(nav, data)
    except Exception as exc:
        _skip_all(items, NAV_NAMES, exc)
        return

    other = _other_body(data, here.get("body"))
    if other is None:
        items["nav_view.other_body"] = {"skipped": "星图里没有别的星球"}
    else:
        target_other = {"b": other, "x": 0.0, "y": 0.0, "z": 0.0, "n": "别处"}
        _item(
            items,
            "nav_view.other_body",
            lambda: call_nav_view(here, target_other, data),
        )

    items["nav_view.same_body"] = last_view
    _item(
        items,
        "nav_view.same_body_prev",
        lambda: call_nav_view(here, target, data, steady, prev=last_view),
    )

    target_arrived = {
        "b": here["body"],
        "x": here["x"] + 0.2,
        "y": here["y"],
        "z": here["z"],
        "n": "脚下",
    }
    _item(
        items,
        "nav_view.arrived",
        lambda: call_nav_view(here, target_arrived, data),
    )

    try:
        hint_target = _hint_target(nav, data, here)
    except Exception as exc:
        items["nav_view.hint"] = _skipped(exc)
    else:
        if hint_target is None:
            items["nav_view.hint"] = {"skipped": "没有找到可用于量子跳跃提示的目标"}
        else:
            _item(
                items,
                "nav_view.hint",
                lambda: call_nav_view(here, hint_target, data),
            )

    try:
        cities = nav.city_places()
    except Exception as exc:
        items["nav_view.city"] = _skipped(exc)
    else:
        if not cities:
            items["nav_view.city"] = {"skipped": "本机没有城内地点"}
        else:
            city = dict(cities[0])
            try:
                city_here = _city_here(city)
            except Exception as exc:
                items["nav_view.city"] = _skipped(exc)
            else:
                _item(
                    items,
                    "nav_view.city",
                    lambda: call_nav_view(city_here, city, data),
                )


def _space_same_target(nav, data):
    target = dict(SPACE_TARGET)
    try:
        guide = nav.space_guide(SPACE_G, target, data)
        if guide.get("same_system"):
            return target
    except Exception:
        pass
    # 从本机太空点里挑第一个和 SPACE_G 同星系的（按星系、名字、坐标排序，确定性）
    points = [
        q
        for q in data.get("points") or []
        if all(k in q for k in ("x", "y", "z", "sys"))
    ]
    points.sort(
        key=lambda q: (
            str(q.get("sys")),
            str(q.get("n")),
            str(q.get("x")),
            str(q.get("y")),
            str(q.get("z")),
        )
    )
    for q in points:
        target = {
            "space": True,
            "b": "@" + str(q["sys"]),
            "sys": q["sys"],
            "n": q.get("n") or "目标",
            "zh": q.get("zh") or "",
            "x": q["x"] / 1000.0,
            "y": q["y"] / 1000.0,
            "z": q["z"] / 1000.0,
        }
        try:
            if nav.space_guide(SPACE_G, target, data).get("same_system"):
                return target
        except Exception:
            continue
    raise RuntimeError("造不出同星系太空目标")


def _space_other_target(nav, data, same_target) -> dict[str, Any]:
    current = None
    try:
        if same_target is not None:
            current = nav.space_guide(SPACE_G, same_target, data).get("target_system")
    except Exception:
        pass

    candidates = []
    for q in data.get("points") or []:
        if not all(k in q for k in ("x", "y", "z", "sys")):
            continue
        if current and q.get("sys") == current:
            continue
        candidates.append(q)
    candidates.sort(
        key=lambda q: (
            str(q.get("sys")),
            str(q.get("n")),
            str(q.get("x")),
            str(q.get("y")),
            str(q.get("z")),
        )
    )
    for q in candidates:
        target = {
            "space": True,
            "b": "@" + str(q["sys"]),
            "sys": q["sys"],
            "n": q.get("n") or "目标",
            "zh": q.get("zh") or "",
            "x": q["x"] / 1000.0,
            "y": q["y"] / 1000.0,
            "z": q["z"] / 1000.0,
        }
        try:
            guide = nav.space_guide(SPACE_G, target, data)
        except Exception:
            continue
        if not guide.get("same_system"):
            return target

    other = "Pyro" if current != "Pyro" else "Stanton"
    target = {
        "space": True,
        "b": "@" + other,
        "sys": other,
        "n": "别处",
        "zh": "",
        "x": SPACE_G[0] / 1000.0 + 1e9,
        "y": SPACE_G[1] / 1000.0 + 1e9,
        "z": SPACE_G[2] / 1000.0 + 1e9,
    }
    if nav.space_guide(SPACE_G, target, data).get("same_system"):
        raise RuntimeError("造不出其他星系太空目标")
    return target


def _collect_space(items, nav, data) -> None:
    same_target = None
    try:
        same_target = _space_same_target(nav, data)
    except Exception as exc:
        items["space_view.same_system"] = _skipped(exc)
    else:
        _item(
            items,
            "space_view.same_system",
            lambda: call_space_view(SPACE_G, same_target, data),
        )

    try:
        other_target = _space_other_target(nav, data, same_target)
    except Exception as exc:
        items["space_view.other_system"] = _skipped(exc)
    else:
        _item(
            items,
            "space_view.other_system",
            lambda: call_space_view(SPACE_G, other_target, data),
        )


def _station_inputs(nav, data):
    candidates = []
    try:
        candidates.extend(list(nav.city_places() or []))
    except Exception:
        pass
    candidates.extend(list(data.get("pois") or []))
    candidates.extend(list(data.get("points") or []))
    seen: set[tuple[Any, ...]] = set()
    ordered = []
    for p in candidates:
        if not isinstance(p, dict):
            continue
        key = (
            p.get("b"),
            p.get("n"),
            p.get("x"),
            p.get("y"),
            p.get("z"),
        )
        if key in seen:
            continue
        seen.add(key)
        ordered.append(p)
    ordered.sort(
        key=lambda p: (
            str(p.get("b")),
            str(p.get("n")),
            str(p.get("t")),
            str(p.get("x")),
            str(p.get("y")),
            str(p.get("z")),
        )
    )
    for p in ordered:
        if not all(k in p for k in ("x", "y", "z", "b")):
            continue
        target = dict(p)
        target.pop("sys", None)
        try:
            tg = nav.target_global(target, data, GROUND_WHEN)
        except Exception:
            continue
        if not tg or len(tg) != 3:
            continue
        g_near = (float(tg[0]) + 10.0, float(tg[1]), float(tg[2]))
        try:
            call_station_view(g_near, target, data, when=GROUND_WHEN)
        except Exception:
            continue
        return target, tg, g_near
    raise RuntimeError("没有可用的空间站目标")


def _collect_station(items, nav, data) -> None:
    try:
        target, tg, g_near = _station_inputs(nav, data)
    except Exception as exc:
        _skip_all(items, STATION_NAMES, exc)
        return

    _item(
        items,
        "station_view.near",
        lambda: call_station_view(g_near, target, data, when=GROUND_WHEN),
    )

    g_far = (float(tg[0]) + 60_000.0, float(tg[1]), float(tg[2]))
    _item(
        items,
        "station_view.far_50km",
        lambda: call_station_view(g_far, target, data, when=GROUND_WHEN),
    )

    try:
        system, _sure = nav.system_info(
            g_near,
            data,
            zone="",
            location="",
            solar_id="",
        )
        if not system:
            raise RuntimeError("读不到当前星系")
        other = "Pyro" if system != "Pyro" else "Stanton"
        target_other = dict(target)
        target_other["sys"] = other
    except Exception as exc:
        items["station_view.other_system"] = _skipped(exc)
    else:
        _item(
            items,
            "station_view.other_system",
            lambda: call_station_view(
                g_near,
                target_other,
                data,
                when=GROUND_WHEN,
            ),
        )

    g_arrived = (float(tg[0]), float(tg[1]), float(tg[2]))
    _item(
        items,
        "station_view.arrived_prev",
        lambda: call_station_view(
            g_arrived,
            target,
            data,
            when=GROUND_WHEN,
            prev={"station": True, "arrived": True},
        ),
    )


# ---------------------------------------------------------------- 记号矩阵
def _reset_marker_state(M) -> None:
    M._MK_CFG.clear()
    M._MK_CFG.update({"on": True, "at": 0.0})
    M._CAM_LAST.clear()
    M._CAM_LAST.update({"t": 0.0, "cam": None})
    M._MK_WHY.clear()
    M._MK_WHY.update({"why": None})


def _marker_once(box, nav, tmp: Path, name: str) -> dict[str, Any]:
    M = box.M
    _reset_marker_state(M)
    box.reset()
    t0 = box.clock.now
    info = {"camdir": MARKER_CAM, "t": t0}
    here = {}
    shown = None

    if name == "no_position":
        here = None
    elif name == "no_camera":
        info = {"t": t0}
    elif name == "cam_hold_0_5s":
        info = {"t": t0}
        M._CAM_LAST.update(t=t0 - 0.5, cam=MARKER_CAM)
    elif name == "cam_hold_1_5s":
        info = {"t": t0}
        M._CAM_LAST.update(t=t0 - 1.5, cam=MARKER_CAM)
    elif name == "stale":
        box.clock.now = t0 + 4.0
    elif name == "arrived":
        here = {"arrived": True}
    elif name == "far":
        here = {"far": True}
    elif name == "not_foreground":
        box.fg_mode = "false"
    elif name == "foreground_raises":
        box.fg_mode = "raise"
    elif name == "mining_running":
        box.live.is_running = True
    elif name == "setting_off":
        box.settings["nav_marker"] = False
    elif name == "visible_v_A":
        info = {"camdir": MARKER_CAM, "fov": 70.0, "t": t0}
    elif name == "visible_h_B":
        box.settings["fov_axis"] = "h"
        box.geometry = dict(GEOM_B)
        box.last_fov = None
        info = {"camdir": MARKER_CAM, "t": t0}
    elif name == "same_t_no_redraw":
        shown = t0
        info = {"camdir": MARKER_CAM, "fov": 70.0, "t": t0}
    elif name == "project_raises":
        info = {"camdir": MARKER_CAM, "fov": 70.0, "t": t0}
    elif name == "hidden_after_shown":
        here = {"arrived": True}
        shown = 123.0
    else:
        raise RuntimeError(f"未知记号场景：{name}")

    box.positions.current = (t0, (0.0, 0.0, 0.0), info)
    state = {"here": here}
    diag_path = tmp / "di_log.txt"
    diag_path.write_text("", encoding="utf-8")

    if name == "project_raises":
        old_project = nav.project

        def boom(*_args, **_kwargs):
            raise RuntimeError("project boom")

        nav.project = boom
        try:
            ret = call_marker_tick(MARKER_TARGET, {}, state, shown)
        finally:
            nav.project = old_project
    else:
        ret = call_marker_tick(MARKER_TARGET, {}, state, shown)

    return {
        "return": ret,
        "calls": list(box.hud.calls),
        "di_log": diag_path.read_text(encoding="utf-8") if diag_path.exists() else "",
        "why": M._MK_WHY["why"],
    }


def _collect_markers(items, box, nav, tmp: Path) -> None:
    for name in MARKER_SCENARIOS:
        _item(
            items,
            f"marker.{name}",
            lambda name=name: _marker_once(box, nav, tmp, name),
        )


# ---------------------------------------------------------------- 日志
def _collect_logs(items, box, tmp: Path) -> None:
    here = {
        "src": "displayinfo",
        "x": 1.23456,
        "y": 2.34567,
        "z": -3.45678,
    }
    info_local = {
        "local": (1.23456789, -2.3456789, 3.456789),
        "local_ok": True,
    }
    view = {"raw_bearing": 45.67, "bearing": 46.4, "surface": 12.3456}
    nav_path = tmp / "nav_log.txt"
    diag_path = tmp / "di_log.txt"

    def line_item():
        box.clock.now = 1792500000.5
        nav_path.write_text("", encoding="utf-8")
        call_nav_log(here, info_local, view)
        return nav_path.read_text(encoding="utf-8")

    _item(items, "nav_log.line", line_item)

    def trim_item():
        box.clock.now = 1792500000.5
        old = [f"旧{i:04d} " + "x" * 200 for i in range(2000)]
        nav_path.write_text("\n".join(old) + "\n", encoding="utf-8")
        call_nav_log(here, {"local": None, "local_ok": False}, view)
        lines = nav_path.read_text(encoding="utf-8").splitlines()
        return {"lines": len(lines), "last2": lines[-2:]}

    _item(items, "nav_log.trim", trim_item)

    def diag_item():
        box.clock.now = 1792500000.5
        diag_path.write_text("", encoding="utf-8")
        call_mark_diag("读数过期")
        call_mark_diag(None)
        return diag_path.read_text(encoding="utf-8")

    _item(items, "mark_diag.lines", diag_item)


# ---------------------------------------------------------------- 录制与比较
def collect() -> dict[str, Any]:
    tmp = Path(tempfile.mkdtemp(prefix="at_nav_baseline_"))
    nav = importlib.import_module("astral_toolkit.navigation.navigate")
    items: dict[str, Any] = {}
    with _CalibSandbox(nav, tmp), _Sandbox(tmp) as box:
        meta = _meta(nav)
        try:
            data = nav.load()
        except Exception as exc:
            data = None
            load_error = exc
        else:
            load_error = None

        if data is None:
            _skip_all(
                items,
                NAV_NAMES + SPACE_NAMES + STATION_NAMES,
                load_error or "没有星图数据",
            )
        else:
            _collect_nav(items, nav, data)
            _collect_space(items, nav, data)
            _collect_station(items, nav, data)

        _collect_markers(items, box, nav, tmp)
        _collect_logs(items, box, tmp)

    return {"meta": meta, "items": items}


def _load_json(path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _diff(left, right, path: str, out: list[tuple[str, Any, Any]]) -> None:
    if len(out) >= 20:
        return
    if type(left) is not type(right):
        out.append((path, left, right))
        return
    if isinstance(left, dict):
        left_keys = list(left)
        right_keys = list(right)
        if left_keys != right_keys:
            out.append((path + ".<keys>", left_keys, right_keys))
            if len(out) >= 20:
                return
        for key in left_keys:
            if len(out) >= 20:
                return
            if key in right:
                _diff(left[key], right[key], f"{path}.{key}", out)
            else:
                out.append((f"{path}.{key}", left[key], "<缺失>"))
        for key in right_keys:
            if len(out) >= 20:
                return
            if key not in left:
                out.append((f"{path}.{key}", "<缺失>", right[key]))
        return
    if isinstance(left, list):
        if len(left) != len(right):
            out.append((path, left, right))
            return
        for i, (a, b) in enumerate(zip(left, right)):
            if len(out) >= 20:
                return
            _diff(a, b, f"{path}[{i}]", out)
        return
    if left != right:
        out.append((path, left, right))


def _show(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _compare(path_a, path_b) -> int:
    left = _load_json(path_a).get("items", {})
    right = _load_json(path_b).get("items", {})
    diffs: list[tuple[str, Any, Any]] = []
    _diff(left, right, "items", diffs)
    if not diffs:
        print("items 相同")
        return 0
    for path, a, b in diffs:
        print(path)
        print(f"  A = {_show(a)}")
        print(f"  B = {_show(b)}")
    if len(diffs) >= 20:
        print("（最多显示 20 处差异）")
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="NV-B0 导航行为基线")
    ap.add_argument("--out", metavar="JSON", help="录制输出 JSON 路径")
    ap.add_argument(
        "--compare",
        nargs=2,
        metavar=("A", "B"),
        help="比较两个基线 JSON 的 items",
    )
    args = ap.parse_args(argv)

    if args.compare:
        return _compare(args.compare[0], args.compare[1])
    if not args.out:
        ap.error("需要 --out 或 --compare")

    result = collect()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )
    print(f"基线写到 {out}：{len(result['items'])} 项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
