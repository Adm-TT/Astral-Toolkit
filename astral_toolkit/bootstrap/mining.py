"""采矿线程要的分析、排版和外面的东西"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..runtime.workers.mining import MiningAnalysis, MiningLinks, MiningViews
from ..app.output import setting_run_flag


def _mining_analysis() -> MiningAnalysis:
    """采矿线程一轮识别要用的分析（目录迁移 R3）：tasks/mining_analysis 这个模块（原样转给 mining/screen、
    mining/signals、tasks/mining 等）"""
    from ..tasks import mining_analysis

    return mining_analysis


def _mining_views() -> MiningViews:
    """采矿线程要的排版（目录迁移 R3）：活动磁贴在 app/presenters/mining"""
    from ..app.presenters import mining as present_mining

    return MiningViews(activity=present_mining.activity)


def _mining_links(options: Mapping[str, Any]) -> MiningLinks:
    """采矿线程要的外面的东西（目录迁移 R3：以前采矿线程在构造器里自己造、或经 `_T` 动态去 tasks 取）。
    抓图（mining/screen）、游戏在不在前台（tasks/mining）、热键名（tasks/navigation 读设置）、日志和截图目录
    （core/paths）、让读位置让出识别引擎（navigation/displayinfo）都是用的时候才取；没出结果的画面交给
    app/miss_shots 的后台队列存（lifecycle 登记它）；设置里的 live_on 跟着开关写。overrides 给了 grab /
    foreground 就用给的（测试用）"""
    from ..app.miss_shots import MissShotsService
    from ..core import paths, settings
    from ..mining.data import focus_keys

    view = settings.View()

    def grab() -> Any:
        from ..mining import screen

        return screen.grab()

    def foreground() -> bool | None:
        from ..tasks import mining as mining_tasks

        return mining_tasks._game_front()

    def hotkey() -> str:
        from ..tasks import navigation as navigation_tasks

        return navigation_tasks.settings_key("live_key", "F5")

    def log_file(name: str) -> Any:
        return paths.log(name)

    def shots(name: str) -> Any:
        return paths.shots(name)

    def yield_ocr() -> None:
        from ..navigation import displayinfo

        displayinfo.yield_ocr()

    given_grab = options.get("grab")
    given_front = options.get("foreground")
    return MiningLinks(
        grab=given_grab if given_grab is not None else grab,
        foreground=given_front if given_front is not None else foreground,
        hotkey=hotkey,
        log_file=log_file,
        shots=shots,
        miss_shots=MissShotsService(),
        yield_ocr=yield_ocr,
        run_flag=setting_run_flag("live_on"),
        idle_seconds=lambda: settings.mining_idle_seconds(
            view.get("mining_idle_close")
        ),
        focus=lambda: focus_keys(view.get("mining_focus")),
    )
