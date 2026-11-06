"""蓝图搜索排序、蓝图字典筛选的纯规则。

只吃传进来的蓝图（或取蓝图的函数）和筛选条件，不读库、不读文件、不读汉化包。
"""

from ..contracts.textkeys import blueprint_search_norm as _search_norm, fold_mixed
from .classify import category, facet, part_of
from .labels import GEAR_ZH, SUB_ZH
from .materials import needs


def search_rank(rows, q, limit):
    exact, part = [], []
    for bp in rows:
        if q in (_search_norm(bp["n"]), _search_norm(bp["z"])):
            exact.append(bp)
        else:
            part.append(bp)
    part.sort(key=lambda b: (len(b["n"]), b["n"]))
    return (exact + part)[:limit]


def browse(
    blueprints,
    cat="",
    sub="",
    part="",
    maker="",
    q="",
    unlocked=False,
    offset=0,
    limit=60,
    mat="",
):
    """蓝图字典：按条件筛，按名字排（同一系列排在一起）。返回 {rows, total, cats, subs, parts, makers}
    mat：只看用到这种矿的蓝图（从扫描结果、矿物页点过来）"""
    allbp = blueprints()
    if mat:
        allbp = [b for b in allbp if needs(b, mat)]
    cats = [
        {
            "key": k,
            "label": GEAR_ZH.get(
                tuple(None if x == "" else x for x in k.split("/", 1)), k
            ),
            "count": n,
        }
        for k, n in ((f["key"], f["count"]) for f in facet(allbp, category))
    ]
    rows = [b for b in allbp if not cat or category(b) == cat]
    subs = [
        {"key": f["key"], "label": SUB_ZH.get(f["key"], f["key"]), "count": f["count"]}
        for f in facet(rows, lambda b: b["s"] or "")
    ]
    if sub:
        rows = [b for b in rows if (b["s"] or "") == sub]
    parts = [
        {"key": f["key"], "label": f["key"], "count": f["count"]}
        for f in facet(rows, part_of)
    ]
    if part:
        rows = [b for b in rows if part_of(b) == part]
    makers = [
        {"key": f["key"], "label": f["key"], "count": f["count"]}
        for f in facet(rows, lambda b: b["m"] or "")
    ]
    if maker:
        rows = [b for b in rows if (b["m"] or "") == maker]
    if unlocked:
        rows = [b for b in rows if b["d"]]
    qq = q.strip().lower().replace(" ", "")
    if qq:
        rows = [
            b
            for b in rows
            if qq in b["n"].lower().replace(" ", "")
            or qq in (b["z"] or "").lower().replace(" ", "")
        ]
    if mat:  # 按矿筛时，有品质门槛的排前面（玩家最想知道这几份够不够）
        rows = sorted(
            rows,
            key=lambda b: (not any(m > 1 for _, m in needs(b, mat)), b["n"].lower()),
        )
    else:
        rows = sorted(rows, key=lambda b: (b["n"].lower(),))
    return {
        "rows": rows[offset : offset + limit],
        "total": len(rows),
        "cats": cats,
        "subs": subs,
        "parts": parts,
        "makers": makers,
    }


def named(blueprints, names):
    """英文名或中文名的键（contracts.textkeys.fold_mixed）和 names 里某一个一样的蓝图，按源顺序；空名字不算"""
    want = {fold_mixed(x) for x in names} - {""}
    return [
        b
        for b in blueprints
        if fold_mixed(b["n"]) in want or fold_mixed(b["z"]) in want
    ]
