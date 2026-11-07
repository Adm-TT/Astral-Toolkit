"""维科洛兑换的展示（CR-B4）：用例取好的东西 → 窗口维科洛页的 JSON（字段、顺序、文字和以前逐字一样）。
只排版，不取数据；原来写在 tasks/goals.py 的 wikelo_search / wikelo_detail 里。
材料去哪弄那一句（source_text）目录迁移收尾从 tasks/catalog_queries/acquire 搬来：维科洛页和目标页的「去哪弄」都用它。"""

import re

from ...crafting.wikelo_rules import req_label


def _loot_text(lt):
    """开箱掉落那一句：地方最多写 3 个（多了或后面还有写「等」）；副本专属矿说只能开采，刷在场景里的不说箱子，
    箱子名是数字开头的不写箱子名"""
    regions = "、".join(lt["regions"][:3]) + (
        "等" if len(lt["regions"]) > 3 or lt["more"] else ""
    )
    if lt["mine"]:  # 副本专属矿：不开箱，只能开采
        return (
            lt["note"].split("：")[0]
            + f"，只能开采：{regions}"
            + (f"（{lt['box']}）" if lt["box"] else "")
        )
    if lt["placed"]:  # 不在箱子里，直接刷在场景里（争夺区奖励室架子上的舰船组件…）
        return f"场景里刷出：{regions}（最高约 {lt['p']:.0%}）"
    box = lt["box"].split(" · ")[0]
    box = "" if re.fullmatch(r"\d+.*", box or "") else box
    return (
        f"开箱：{regions}"
        + (f"（{box} 箱" if box else "（")
        + f"，单箱最高约 {lt['p']:.0%}）"
    )


def source_text(facts):
    """材料去哪弄（tasks/catalog_queries/acquire.material_source 给的事实）→ 一句话；没有给空字符串。
    拼的时候出错（掉落数据缺字段、不是数）也给空字符串：以前这几句在查询里拼，出错由维科洛页 / 目标页取的时候吞成空，
    挪到这里照旧，不让整页出错"""
    try:
        return _source_text(facts)
    except Exception:
        return ""


def _source_text(facts):
    if not facts:
        return ""
    if "note" in facts:
        return facts["note"]
    if "buy" in facts:
        p, shop, place = facts["buy"]
        return f"可买：{shop}（{place}）{p:,.0f} aUEC"
    if "mine" in facts:
        m = facts["mine"]
        return f"挖矿：{m['where']} {m['pct']:.0f}%" + (
            "（要精炼成纯净的）" if m["pure"] else ""
        )
    if "loot" in facts:
        return _loot_text(facts["loot"])
    return ""


def present_search(rows):
    return [
        {
            "key": c["id"],
            "title": c["t"],
            "type": c["type"],
            "reward": c["rz"] or "、".join(c["rewards"][:2]),
        }
        for c in rows
    ]


def present_detail(f):
    if f is None:
        return {"error": "未找到此兑换，需重新搜索"}
    c = f["c"]
    reqs = []
    for rs, tip in f["groups"]:
        r = rs[0]
        name = (
            f"{r['z']}（{'、'.join(x['n'] for x in rs)}）"
            if len(rs) > 1
            else req_label(r)
        )
        reqs.append(
            {
                "name": name,
                "q": (f"{r['q']:g} {r['u']}" if r["q"] else "若干")
                + (" 各" if len(rs) > 1 else ""),
                "tip": source_text(tip),
                "en": r["n"],
                "zh": r["z"],
            }
        )
    return {
        "id": c["id"],
        "title": c["t"],
        "type": c["type"],
        "reward": c["rz"] or "、".join(c["rewards"][:4]) or c["te"],
        "req": reqs,
    }
