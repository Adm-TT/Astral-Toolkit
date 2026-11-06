"""维科洛兑换的应用用例（CR-B4，架构稿 §4.2）：找兑换、取材料来源，交给 app/presenters/wikelo.py 排版。
接口在 app/api/wikelo.py；tasks/goals.py 的 wikelo_* 是旧壳（全局搜索、目标页、测试还在调）。不 import app / runtime / bootstrap。"""

from ..crafting import wikelo
from ..crafting.wikelo_rules import note_for, rewarding
from ..crafting.acquire import material_source

_wk_cache = {}


def clear_caches():
    """更新数据后清掉接口层的缓存"""
    _wk_cache.clear()


try:
    from ..update.data_pack import CACHE_HOOKS as _CACHE_HOOKS

    _CACHE_HOOKS.append(clear_caches)
except Exception:
    pass


def search_exchanges(q=""):
    rows = wikelo.search(q or "")[:60]
    for c in rows:
        # 兑换自己的 id 当 key：流水号会在清缓存后重号，指到别的兑换
        _wk_cache[c["id"]] = c
    return rows


def exchange_detail(key=""):
    c = _wk_cache.get(key) or next((x for x in wikelo.load() if x["id"] == key), None)
    if not c:
        return None
    groups = []
    for r in c["req"]:
        k = (r["z"], r["q"], r["u"]) if note_for(r["n"]) else (r["n"],)
        if groups and groups[-1][0] == k:
            groups[-1][1].append(r)
        else:
            groups.append((k, [r]))
    out = []
    for _, rs in groups:
        try:
            tip = material_source(rs[0]["n"])
        except Exception:
            tip = ""
        out.append((rs, tip))
    return {"c": c, "groups": out}


def rewards_for(name, zh):
    """能换到这件东西的维科洛兑换（F8「可通过维科洛兑换获得」），按兑换原来的顺序"""
    return rewarding(wikelo.load(), name, zh)
