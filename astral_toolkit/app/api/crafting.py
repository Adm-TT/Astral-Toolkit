"""制造 Controller（CR-B4）

制造接口调 tasks/crafting.py 的用例，结果交 app/presenters/crafting.py 排版。
只做转发，不加校验（校验留在 tasks 里，改行为要 NGU 定）。router 自动收集文件末尾的 ROUTES。
"""

from ...tasks import crafting as _uc
from ..presenters import crafting as _present


def craft_effect(**kw):
    return _uc.craft_effect(**kw)


def craft_search(**kw):
    return _present.present_search(_uc.search_blueprints(**kw))


def craft_browse(**kw):
    return _present.present_browse(_uc.browse_blueprints(**kw))


def craft_detail(**kw):
    return _present.present_detail(_uc.blueprint_detail(**kw))


def craft_stats(**kw):
    return _uc.craft_stats(**kw)


def craft_mix(**kw):
    return _uc.craft_mix(**kw)


ROUTES = {
    "craft_effect": craft_effect,
    "craft_search": craft_search,
    "craft_browse": craft_browse,
    "craft_detail": craft_detail,
    "craft_stats": craft_stats,
    "craft_mix": craft_mix,
}
