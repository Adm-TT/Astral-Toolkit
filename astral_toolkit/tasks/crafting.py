"""制造的应用用例（CR-B4，架构稿 §4.2）：找蓝图、取数据（库、采矿地点和价格、汉化名、物品属性），交给 app/presenters/crafting.py 排版。
接口在 app/api/crafting.py；tasks/goals.py 的 craft_* / _craft_struct 是旧壳（全局搜索、目标页、测试还在调）。不 import app / runtime / bootstrap。"""

from ..crafting.crafting import (
    blueprints,
    bp_key,
    browse,
    by_key,
    describe,
    display_name,
    effect,
    header,
    mat_summary,
    material_zh,
    mix_targets,
    name_parts,
    quality_hints,
    search as _craft_search,
    stats,
    uses_report,
    variant_note,
)
from ..crafting.listing import named
from ..crafting.mix import mix_plan
from ..crafting.quality import laser_total
from ..mining.data import best_price
from ..mining.locations import where, zh_name

_bp_cache = {}


def clear_caches():
    """更新数据后清掉接口层的缓存"""
    _bp_cache.clear()


try:
    from ..update.data_pack import CACHE_HOOKS as _CACHE_HOOKS

    _CACHE_HOOKS.append(clear_caches)
except Exception:
    pass


def craft_effect(key="", qualities=None):
    """蓝图在给定材料品质下，每个槽对成品属性的影响（目标页「品质影响」）。qualities：{槽序号: 品质}"""
    bp = _bp_cache.get(key) or by_key(key)
    if not bp:
        return {"error": "未找到此蓝图"}
    slots = effect(bp, qualities or {})
    return {
        "slots": slots,
        "total": laser_total(bp, qualities or {}) if slots else None,
    }


def search_blueprints(q=""):
    out = []
    for bp in _craft_search(q, limit=30):
        key = bp_key(bp)
        _bp_cache[key] = bp
        zh, en = name_parts(bp)
        out.append(
            {
                "bp": bp,
                "key": key,
                "note": variant_note(bp),
                "zh": zh,
                "en": en,
                "name": display_name(bp),
            }
        )
    return out


def browse_blueprints(
    cat="", sub="", part="", maker="", q="", unlocked=False, offset=0, mat="", mq=None
):
    r = browse(cat, sub, part, maker, q, bool(unlocked), int(offset or 0), mat=mat)
    try:
        mq = int(mq) if mq not in (None, "") else None
    except (TypeError, ValueError):
        mq = None
    rows = []
    for bp in r["rows"]:
        key = bp_key(bp)
        _bp_cache[key] = bp
        rows.append(
            {
                "bp": bp,
                "key": key,
                "note": variant_note(bp),
                "name": display_name(bp),
            }
        )
    out = {"page": r, "rows": rows, "mat": mat, "mq": mq}
    if mat:
        out["mat_zh"] = material_zh(mat)
        out["summary"] = mat_summary(mat, mq)
    return out


def struct_facts(bp, note=""):
    head = header(bp)
    mat_zh = {}
    minerals = []
    for _, opts, _ in bp["slots"]:
        for k, name, *_ in opts:
            mat_zh[name] = material_zh(name)
            if k == "r":
                minerals.append(name)
    mine = []
    for m in dict.fromkeys(minerals):
        rows = where(m)[:2]
        price, city = best_price(m)
        mine.append(
            {
                "en": m,
                "spots": [(pct, zh_name(loc)) for pct, loc in rows],
                "price": price,
                "city": city,
            }
        )
    return {"bp": bp, "note": note, "head": head, "mat_zh": mat_zh, "mine": mine}


def blueprint_detail(key=""):
    bp = _bp_cache.get(key) or by_key(key)
    if not bp:
        hits = search_blueprints(key)
        bp = _bp_cache.get(hits[0]["key"]) if hits else None
    if not bp:
        return None
    note = variant_note(bp)
    text = describe(bp)
    return {
        "key": bp_key(bp),
        "text": text,
        "note": note,
        "mix": mix_targets(bp),
        "struct": struct_facts(bp, note),
    }


def craft_stats(key="", qualities=None):
    """成品属性统计（制造 / 目标页）：各槽品质 → 每项属性的基础值、强化后、变化（1.6.47）"""
    bp = _bp_cache.get(key) or by_key(key)
    if not bp:
        return {"error": "未找到此蓝图"}
    qs = qualities or {}
    return {"stats": stats(bp, qs), "slots": effect(bp, qs)}


def craft_mix(need=0, target=0, margin=2, boxes=()):
    """混料计算器：boxes = [[品质, SCU], …]"""
    try:
        rows = [
            (float(q), float(s)) for q, s in boxes if str(q).strip() and str(s).strip()
        ]
    except (TypeError, ValueError):
        return {"ok": False, "msg": "品质和数量需为数字"}
    return mix_plan(float(need or 0), float(target or 0), rows, float(margin or 0))


def scan_hints(composition):
    """采矿助手的制造提示：[(矿物, 百分比, 品质)] → 每种矿的品质对制造意味着什么（tasks/mining 用）"""
    return quality_hints(composition)


def material_summary(mineral, q=None):
    """多少份蓝图用到这种矿；给了品质再算其中多少份品质够（tasks/mining、物品查询矿物页用）"""
    return mat_summary(mineral, q)


def mineral_uses_text(mineral):
    """物品查询矿物页的「制造用途」那段字"""
    return uses_report(mineral)


def has_blueprint(*names):
    """F8「可制造：有蓝图」：有没有英文名或中文名（contracts.textkeys.fold_mixed 比）和这几个名字之一一样的蓝图"""
    return bool(named(blueprints(), names))
