"""盘点线程要的分析、排版和外面的东西"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..runtime.workers.count import CountAnalysis, CountLinks, CountViews


def _count_analysis() -> CountAnalysis:
    """盘点线程一轮要用的分析（目录迁移 R5）：tasks/count_analysis 这个模块（原样转给 trade/inspector、tasks/count）"""
    from ..tasks import count_analysis

    return count_analysis


def _count_views() -> CountViews:
    """盘点要的排版（目录迁移 R5）：悬浮窗文字在 app/presenters/count，数量写法用的时候现取 tasks/hover.qty_text"""
    from ..app.presenters import count as present_count

    def hud_text(place: Any, items: Any) -> str:
        from ..tasks import hover as hover_tasks

        return present_count.hud_text(place, items, hover_tasks.qty_text)

    def item_line(r: Any) -> str:
        from ..tasks import hover as hover_tasks

        return present_count.item_line(r, hover_tasks.qty_text)

    return CountViews(hud_text=hud_text, item_line=item_line)


def _count_live_place(pos: Any) -> tuple[str, str] | None:
    """右上角最后认出的地点 → (中文名, 星系)；没有名字返回 None。"""
    try:
        _t, lab = pos.label
    except Exception:
        return None
    if not lab:
        return None
    sysname = ""
    try:
        _st, sysname = pos.system
    except Exception:
        pass
    return str(lab), str(sysname or "")


def _count_links(
    options: Mapping[str, Any],
    *,
    live_place_src: list[Any] | None = None,
) -> CountLinks:
    """盘点线程要的外面的东西（目录迁移 R5：以前盘点线程在构造器里自己造、或经 `_T` / `_H` 动态去 tasks、app 取）。
    读光标（infrastructure/platform/cursor）、抓图（mining/screen）、游戏在不在前台（tasks/mining）、热键名（tasks/navigation
    读设置，读不了就是 F6）、调试图目录（trade/debug_shots）、开始时在哪个库存地点（crafting/stockplaces；没有日志地点
    时用右上角实时地点——须对得上库存列表；仍未知返回空，由盘点入口提示玩家手选）、悬浮窗短提示（app/hud_state）、
    正在退出时不让开始（app/lifecycle_gate）都是用的时候才取；
    overrides 给了 cursor_pos / foreground 就用给的（测试用）。
    live_place_src：单元素列表，build 在造好 PositionWorker 后填入「() → (label, sys) | None」。"""

    live_src = live_place_src if live_place_src is not None else [None]

    def cursor_pos() -> tuple[int, int]:
        from ..infrastructure.platform import cursor

        return cursor.pos()

    def grab() -> Any:
        from ..mining import screen

        return screen.grab()

    def foreground() -> bool | None:
        from ..tasks import mining as mining_tasks

        return mining_tasks._game_front()

    def hotkey() -> str:
        try:
            from ..tasks import navigation as navigation_tasks

            return navigation_tasks.settings_key("count_key", "F6")
        except Exception:
            return "F6"

    def debug_bind() -> None:
        from ..trade import debug_shots

        debug_shots.bind_count_run()

    def debug_unbind() -> None:
        from ..trade import debug_shots

        debug_shots.unbind_count_run()

    def place_now() -> str:
        from ..crafting import stockplaces

        here = stockplaces.current_place()
        if here:
            return here["label"]
        # 右上角实时地点：必须对得上库存地点列表才算可靠
        getter = live_src[0]
        if callable(getter):
            try:
                pack = getter()
            except Exception:
                pack = None
            if isinstance(pack, (tuple, list)) and len(pack) == 2:
                lab, sysname = pack
                hit = stockplaces.matched_place(lab, sysname or None)
                if hit:
                    return hit["label"]
        # 仍未知：不读上次入库位置（可能早已不在那儿），交给盘点入口提示玩家手选
        return ""

    def note(section: str, text: str) -> None:
        from ..app import hud_state

        hud_state._note_hud(section, text)

    def refuse() -> dict[str, str] | None:
        from ..app import lifecycle_gate

        return lifecycle_gate.closing_error()

    given_cursor = options.get("cursor_pos")
    given_front = options.get("foreground")
    return CountLinks(
        cursor_pos=given_cursor if given_cursor is not None else cursor_pos,
        grab=grab,
        foreground=given_front if given_front is not None else foreground,
        hotkey=hotkey,
        debug_bind=debug_bind,
        debug_unbind=debug_unbind,
        place_now=place_now,
        note=note,
        refuse=refuse,
    )
