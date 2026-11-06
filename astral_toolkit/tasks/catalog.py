"""物品查询的应用用例（IQ-B5，架构稿 §4.2、§4.4）：取好数据交给 app/presenters/catalog.py 排版。

- search_items：搜索列表（catalog_queries.search.find 的行原样，最多 30 条）
- get_item_info：一件物品的详情（acquire.info + 中文名 + 目标提示）→ ItemInfo
- get_item_loot：掉落（catalog_queries.loot.info，会上网）→ LootLookup，出错不抛
- MarketSession / open_market / market_rows / market_hud_text：玩家市场（IQ-B6：F8 用 Trade 只经这里，报价留 F 段）
详情一次查询钉一个游戏数据快照（_pinned）；掉落不另钉（见 get_item_loot）。窗口物品查询页经 app/api/trade.py 调这里；
tasks/trade.py 的 item_search 是旧壳（库存联想、全局搜索还在调），也转到这里。
不 import app / runtime / bootstrap。"""

from contextlib import ExitStack, contextmanager
from typing import Iterator

from .. import gamedata
from ..catalog.results import ItemInfo, LootLookup
from ..gamedata._cache import VersionCache


@contextmanager
def _pinned() -> Iterator[None]:
    """一次查询钉在一个游戏数据版本上：里面各处 gamedata 查询（嵌套的 snapshot）都复用这一个（架构稿 §4.4）。
    先 ensure()：升级后库过时要先重建，不然钉在旧那一代。ensure / 开快照出错就不钉，里面各处照旧自己 ensure、
    自己接出错，和以前一样（同 tasks/mining._one_round_facts、navigation.navigate.search）。里面抛的异常原样出去，不重跑"""
    with ExitStack() as stack:
        try:
            gamedata.ensure()
            stack.enter_context(gamedata.snapshot())
        except Exception:
            pass
        yield


def search_items(q=""):
    """物品查询搜索（1.6.41 起商店、掉落、汉化包一起搜，见 catalog_queries/search.py）：find 的行原样，最像的在前，最多 30 条。
    索引在 catalog_queries.search 里自己钉一个快照建，这里不另钉"""
    from .catalog_queries import search

    return search.find(q, limit=30)


# 英文 → 中文反查，跟着 names.table() 那份对象走：更新数据后自己失效（以前挂在函数属性上永不失效）
_ZH_REV: VersionCache = VersionCache(identity=True)


def _zh_of(en):
    try:
        from ..trade.names import table

        t = table()
        rev = _ZH_REV.get_for(t, lambda: {v.lower(): k for k, v in t.items()})
        return rev.get(en.lower(), "")
    except Exception:
        return ""


def _goal_hint(*names):
    """卡片上的目标提示：这件东西在目标里给 tasks/goals 排好的那段文字，不在给 ""。
    别的任务在函数里 import（任务之间互相引用，顶层 import 会循环）；goals 的 _goal_for / _goal_text 照旧用（目标冻着，不给它加名字）"""
    from . import goals

    g = goals._goal_for(*names)
    return goals._goal_text(g) if g else ""


def get_item_info(name="", zh="", id=None, loot=True, exact=False):
    """一件物品的详情。exact=True：从物品查询 / 顶上搜索框的结果点进来的（名字是准的）。
    掉落明细本机没有时不上网等（loot 里给 pending），窗口再调 item_loot 后台取（2026-10-28 用户反馈卡 10 秒）"""
    from ..core.i18n import gear_zh_of_item
    from ..crafting import acquire

    with _pinned():
        d = acquire.info(
            name, zh, id, show_loot=loot, exact=bool(exact), loot_online=False
        )
        zh_name = (
            gear_zh_of_item(d["name"]) or d.get("zh") or _zh_of(d["name"])
        )  # 采矿装备的中文不带型号，和配置区一致
        return ItemInfo(
            facts=d, zh=zh_name, goal=_goal_hint(d.get("name"), name, zh, zh_name)
        )


def get_item_loot(name="", zh=""):
    """物品查询里掉落那一块：明细本机没有时窗口在后面单独调这个（会上网，最多等 15 秒，不挡别的）。
    不另钉快照：loot.info 自己分步钉（找物品、副本矿各钉一个）；副本矿缺掉落索引时会下载索引、重建库，再开新快照读
    新版本，外面钉着旧快照就读不到（见 catalog_queries/loot.mine_info）。出错不抛：异常放进 LootLookup.error，
    展示层写成「掉落数据出错：…」"""
    try:
        from .catalog_queries.loot import info as loot_info

        return LootLookup(loot=loot_info(name, zh))
    except Exception as e:
        return LootLookup(error=e)


# ---------------------------------------------------------------- 玩家市场（IQ-B6：F8 用 Trade 只经这里；报价本身留 F 段）


class MarketSession:
    """一次 F8 后台补价用的玩家市场会话：开的时候取一次市场（tasks/trade.market()，不含库存），
    对名字、记中文别名、显示名都用这一个（和以前 _hover_more 里 t = trade() 之后一样）"""

    def __init__(self, market):
        self._t = market

    def match(self, zh, en):
        """说明框里的名字 → (物品或 None, 候选列表)：trade.matching.match_tooltip 原样（先本机目录，没有才联网搜）"""
        from ..trade import matching

        return matching.match_tooltip(self._t, zh, en)

    def remember_alias(self, item_id, zh):
        """把汉化包里的标准中文名记成这件物品的别名（写玩家库）"""
        self._t.catalog.add_alias(item_id, zh)

    def label(self, item_id):
        """物品的显示名：Market.label（Trade.label 原样）"""
        return self._t.label(item_id)


def open_market():
    """开一个玩家市场会话：取 tasks/trade.market()（Trade 第一次用才造，和以前一样；造不出来照旧抛出去）"""
    from . import trade as trade_tasks

    return MarketSession(trade_tasks.market())


def market_rows(item_id, tier):
    """玩家市场报价表 (prices, results)：tasks/trade._market_rows 原样"""
    from . import trade as trade_tasks

    return trade_tasks._market_rows(item_id, tier)


def market_hud_text(results):
    """报价写成悬浮窗「市场」那一行：trade.market_text.hud_market 原样"""
    from ..trade.market_text import hud_market

    return hud_market(results)
