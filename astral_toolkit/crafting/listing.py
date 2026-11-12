"""蓝图搜索排序、蓝图字典筛选的纯规则。

只吃传进来的蓝图（或取蓝图的函数）和筛选条件，不读库、不读文件、不读汉化包。
"""

from ..contracts.textkeys import blueprint_search_norm as _search_norm, fold_mixed
from .classify import category, facet, part_of
from .labels import CLS_ZH, GEAR_ZH, SUB_ZH, spec_parts
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
    size="",
    grade="",
    cls="",
    spec=None,
):
    """蓝图字典：按条件筛，按名字排（同一系列排在一起）。返回 {rows, total, cats, subs, parts, makers}
    mat：只看用到这种矿的蓝图（从扫描结果、矿物页点过来）
    spec(蓝图) → 物品属性（itemstats.tags 那样的字典）：选了船零件类（vehiclegear/…）时按它再给
    grades / clss 两组筛选（只有冷却器、发电机这些游戏说明里写等级的类才有选项，见 labels.GRADED），
    子类里没有尺寸的（舰船武器是实弹 / 激光……）还给 sizes，返回里多这三个键；
    别的类、没给 spec 时没有这三个键，size / grade / cls 传了也不筛（CR-D1）"""
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
    extra = {}
    if spec is not None and cat.startswith("vehiclegear/"):
        sp = {id(b): spec_parts(spec(b) or {}, b["s"] or "", b["t"]) for b in rows}
        extra["sizes"] = []
        if not any((b["s"] or "").startswith("size") for b in rows):
            # 子类就是 S1 / S2 的（冷却器、发电机……）不重复给尺寸；按数字排（"2" 在 "10" 前面）
            extra["sizes"] = [
                {"key": f["key"], "label": f"S{f['key']}", "count": f["count"]}
                for f in sorted(
                    facet(
                        rows,
                        lambda b: "" if sp[id(b)][0] is None else str(sp[id(b)][0]),
                    ),
                    key=lambda f: (len(f["key"]), f["key"]),
                )
            ]
            if size:
                rows = [b for b in rows if str(sp[id(b)][0]) == str(size)]
        extra["grades"] = [
            {"key": f["key"], "label": f"{f['key']} 级", "count": f["count"]}
            for f in sorted(facet(rows, lambda b: sp[id(b)][1]), key=lambda f: f["key"])
        ]
        if grade:
            rows = [b for b in rows if sp[id(b)][1] == grade]
        extra["clss"] = [
            {
                "key": f["key"],
                "label": CLS_ZH.get(f["key"], f["key"]),
                "count": f["count"],
            }
            for f in facet(rows, lambda b: sp[id(b)][2])
        ]
        if cls:
            rows = [b for b in rows if sp[id(b)][2] == cls]
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
        **extra,
    }


def named(blueprints, names):
    """英文名或中文名的键（contracts.textkeys.fold_mixed）和 names 里某一个一样的蓝图，按源顺序；空名字不算"""
    want = {fold_mixed(x) for x in names} - {""}
    return [
        b
        for b in blueprints
        if fold_mixed(b["n"]) in want or fold_mixed(b["z"]) in want
    ]
