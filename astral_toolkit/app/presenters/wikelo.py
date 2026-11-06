"""维科洛兑换的展示（CR-B4）：用例取好的东西 → 窗口维科洛页的 JSON（字段、顺序、文字和以前逐字一样）。
只排版，不取数据；原来写在 tasks/goals.py 的 wikelo_search / wikelo_detail 里。"""

from ...crafting.wikelo_rules import req_label


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
                "tip": tip,
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
