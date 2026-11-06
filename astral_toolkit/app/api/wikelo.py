"""维科洛 Controller（CR-B4）

维科洛接口调 tasks/wikelo.py 的用例，结果交 app/presenters/wikelo.py 排版。
只做转发，不加校验（校验留在 tasks 里，改行为要 NGU 定）。router 自动收集文件末尾的 ROUTES。
"""

from ...tasks import wikelo as _uc
from ..presenters import wikelo as _present


def wikelo_search(**kw):
    return _present.present_search(_uc.search_exchanges(**kw))


def wikelo_detail(**kw):
    return _present.present_detail(_uc.exchange_detail(**kw))


ROUTES = {
    "wikelo_search": wikelo_search,
    "wikelo_detail": wikelo_detail,
}
