"""交易 Controller（2026-10-30 重构阶段 1）

物品查询三个接口（item_search / item_info / item_loot）调 tasks/catalog.py 的用例，结果交 app/presenters/catalog.py 排版（IQ-B5）；
其余接口收关键字参数，原样转给 tasks/trade.py 里同名函数；商店导航 nav_shop 要导航后台对象，由 bound(nav_deps) 给，bootstrap.routes 接（F 段 B5）。
只做转发，不加校验（校验留在 tasks 里，改行为要 NGU 定）。router 自动收集文件末尾的 ROUTES。
"""

from ...tasks import catalog as _catalog
from ...tasks import trade as _t
from ..presenters import catalog as _present


def search(**kw):
    return _t.search(**kw)


def item_search(**kw):
    return _present.present_search_results(_catalog.search_items(**kw))


def item_info(**kw):
    return _present.present_item_info(_catalog.get_item_info(**kw))


def item_loot(**kw):
    return _present.present_item_loot(_catalog.get_item_loot(**kw))


def trade(**kw):
    return _t.trade(**kw)


def market_lookup(**kw):
    return _t.market_lookup(**kw)


def market_prices(**kw):
    return _t.market_prices(**kw)


def mineral_search(**kw):
    return _t.mineral_search(**kw)


def mineral_info(**kw):
    return _t.mineral_info(**kw)


def bound(nav_deps):
    """要导航后台对象的接口（F 段 B5）：物品查询里点商店「导航」，用这个 app 的 NavDeps"""

    def nav_shop(**kw):
        return _t.nav_shop(nav_deps, **kw)

    return {"nav_shop": nav_shop}


ROUTES = {
    "search": search,
    "item_search": item_search,
    "item_info": item_info,
    "item_loot": item_loot,
    "trade": trade,
    "market_lookup": market_lookup,
    "market_prices": market_prices,
    "mineral_search": mineral_search,
    "mineral_info": mineral_info,
}
