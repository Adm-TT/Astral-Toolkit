"""热键线程和 F8 要的东西"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..app.inputs.hotkeys import HotkeyCommands
from ..runtime.workers.hotkeys import HotkeyLinks, HotkeyWorker

if TYPE_CHECKING:
    from ..tasks.hover import HoverLinks


def _hotkeys(commands: HotkeyCommands) -> HotkeyWorker:
    """热键线程（目录迁移 R4 起在 runtime/workers/hotkeys，只管看键）：绑定、按下去做什么、出错清「忙」都接键盘入口
    （app/inputs/hotkeys 的 HotkeyCommands），读键接 infrastructure/platform/keys；只有 Windows 起线程"""
    import sys

    from ..infrastructure.platform import keys

    return HotkeyWorker(
        HotkeyLinks(
            bindings=commands.bindings,
            code=keys.code,
            down=keys.down,
            pressed=commands.pressed,
            failed=commands.failed,
        ),
        enabled=sys.platform == "win32",
    )


def _hover_links() -> HoverLinks:
    """F8 要用的物品查询（IQ-B6）：物品卡片和窗口物品查询页同一份（tasks/catalog 用例 + app/presenters/catalog 排版）；
    掉落、玩家市场经 tasks/catalog（Trade 只在那里的市场会话里用，第一次用才造，和以前一样）；
    「可通过维科洛兑换获得」「可制造：有蓝图」经 tasks/wikelo、tasks/crafting，CR-B5"""
    from ..app.presenters import catalog as present_catalog
    from ..tasks import catalog as catalog_tasks
    from ..tasks import crafting as crafting_tasks
    from ..tasks import wikelo as wikelo_tasks
    from ..tasks.hover import HoverLinks

    def item_card(name="", zh="", id=None, loot=True, exact=False):
        return present_catalog.present_item_info(
            catalog_tasks.get_item_info(name, zh, id, loot, exact)
        )

    return HoverLinks(
        item_card=item_card,
        loot=catalog_tasks.get_item_loot,
        market=catalog_tasks.open_market,
        market_rows=catalog_tasks.market_rows,
        hud_market=catalog_tasks.market_hud_text,
        wikelo_rewards=wikelo_tasks.rewards_for,
        has_blueprint=crafting_tasks.has_blueprint,
    )
