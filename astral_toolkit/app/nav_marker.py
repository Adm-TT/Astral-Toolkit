"""导航 HUD 记号（NV-B3 从 tasks/mining 搬到导航引擎；目录迁移 R2 从 app/engines/nav 搬来，逻辑没改）：
按位置、镜头和设置决定画不画，画时把投影交给悬浮窗；收起 / 重新出来的原因写进 logs/di_log.txt。
bootstrap._nav_marker 造好交给导航线程（线程不认识悬浮窗和 navigation）。"""

import time
from typing import Any, Callable

from ..navigation import marker as _marker
from .presenters import nav as _present_nav

MARKER_STALE = 4.0  # 右上角多少秒没读到就收起导航记号（城里偶尔几次读不到，1.5 秒就收会一直闪，2026-10-27 实测）
CAM_HOLD = 1.0  # 这一帧坐标有、镜头方向没读出：这么久以内读到的镜头方向接着用（按它自己的读取时间算，不当成新的）


def marker_diag(why):
    """导航记号收起 / 重新出来时记一行进 logs/di_log.txt（和读右上角的诊断放一起对时间，老大 11-03 实测「记号还会消失」）"""
    try:
        from ..core import paths

        with paths.log("di_log.txt").open("a", encoding="utf-8") as f:
            f.write(
                f"{time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d} "
                f"记号 {'收起：' + why if why else '显示'}\n"
            )
    except Exception:
        pass


class _NavMarker:
    """导航 HUD 记号（NV-B3 从 tasks/mining 搬来，逻辑没改）：按位置、镜头和设置决定画不画，画时把投影交给悬浮窗。"""

    def __init__(
        self,
        positions: Any,
        *,
        mining_running: Callable[[], bool],
        foreground: Callable[[], bool],
        game_area: Callable[[], dict[str, Any]],
        last_fov: Callable[[], Any],
        settings: Callable[[], dict[str, Any]],
        hud: Callable[[], Any],
        diag: Callable[[Any], None],
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._pos = positions
        self._mining_running = mining_running
        self._foreground = foreground
        self._game_area = game_area
        self._last_fov = last_fov
        self._settings = settings
        self._hud = hud
        self._diag = diag
        self._clock = clock if clock is not None else time.time
        self.cfg: dict[str, Any] = {"on": True, "at": 0.0}
        self.cam_last: dict[str, Any] = {"t": 0.0, "cam": None}
        self.why: Any = None

    def enabled(self):
        """设置里的 nav_marker（两秒读一次，导航每 0.1 秒问一次）"""
        if self._clock() - self.cfg["at"] > 2:
            self.cfg["at"] = self._clock()
            try:
                self.cfg["on"] = self._settings().get("nav_marker", True) is not False
            except Exception:
                self.cfg["on"] = True
        return self.cfg["on"]

    def tick(self, target, data, state, shown, ref=None):
        """导航记号（2026-10-27）：每圈先判断该不该显示（还没算出位置、到了、跨星系、1.5 秒没读到、切出游戏、玩家关了、
        采矿助手开着——记号窗口读屏时会被涂黑，会挡住扫描面板和雷达信号），不该显示就收起；
        该显示且右上角有新截图（停着只转镜头也算）就按镜头朝向和视角重算位置。返回这次画的截图时间，收起了返回 None"""
        from ..navigation import navigate as n

        t, g, info = self._pos.snapshot().current
        h = state.get("here")
        # 镜头方向来自读屏，没有类型；走到投影那一步时一定有值
        cam: Any = _marker.camera_hold(
            (info or {}).get("camdir"), t, self.cam_last, CAM_HOLD
        )
        try:
            fg = self._foreground()
        except Exception:
            fg = True
        why = _marker.hidden_reason(
            h,
            g,
            cam,
            t,
            now=self._clock,
            stale=MARKER_STALE,
            foreground=fg,
            mining_running=self._mining_running,
            enabled=self.enabled,
        )
        if why != self.why:
            self.why = why
            self._diag(why)
        if why:
            if shown is not None:
                self._draw(None)
            return None
        if t == shown:
            return shown
        try:
            a = self._game_area()
            fov = _marker.pick_fov(info.get("fov"), self._last_fov)
            tg = n.target_global(target, data, info.get("t"), ref)
            pr = n.project(
                g,
                cam,
                fov,
                tg,
                a["width"],
                a["height"],
                vertical=self._setting("fov_axis", "v") != "h",
            )
            label = _present_nav.marker_label(pr["dist"])
            model = _present_nav.marker_model(a, pr, label)
            self._draw(model)
            return t
        except Exception:
            self._draw(None)
            return None

    def _setting(self, key, default=None):
        try:
            return self._settings().get(key, default)
        except Exception:
            return default

    def _draw(self, data):
        try:
            self._hud().marker(data)
        except Exception:  # 测试里的假悬浮窗没有这个接口
            pass

    def clear(self):
        self._draw(None)
