"""掉落查询的纯规则：变体过滤、候选挑选、掉落明细汇总分组、认副本专属矿（原 crafting/loot.py 的计算部分）。

只 import 标准库；查库、整包和缓存、联网在 tasks/catalog_queries/loot.py 和它用的下载 / 存取适配（目录迁移 Q3）。
"""

import re


PLACED = "直接刷在场景里（不在箱子里）"

# 同名的「变体」：NPC 专用、不显示的、测试 / 枪械游戏模式、低模、模板……玩家拿不到，掉落不算它的（2026-10-24 全量核对：
# 「Citadel 胸甲」对到了 _ai_exclusive、「FSK-8 战斗刀」对到了 _gungame）
VARIANT = re.compile(
    r"(_ai_exclusive|^nodraw_|_gungame|_debug|_lowpoly|_template|_dummy|_atls|"
    r"_securitynetwork|_hair_extension|_salvation_|_active$)"
)


def is_variant(cls_lower):
    """类名是否是玩家拿不到的变体；原 crafting/loot._VARIANT 的匹配。"""
    return bool(VARIANT.search(cls_lower))


def partial(ke, kz, r):
    """名字只是开头像 / 包含：英文 ≥6 前缀、≥5 子串，中文 ≥3 子串；原 crafting/loot._partial。"""
    return (
        (ke and len(ke) >= 6 and r.norm_en.startswith(ke))
        or (ke and len(ke) >= 5 and ke in r.norm_en)
        or (kz and len(kz) >= 3 and kz in r.norm_zh)
    )


def exact_candidates(rows):
    """把 gd_loot.exact 的行转成 find 的候选元组；原 find 里的 exact 列表推导。"""
    return [(r.uuid, r.en, r.zh, r.rarity, r.cls_lower, r.n) for r in rows]


def pick_exact(exact, good):
    """精确命中里挑：wiki 类名优先，其次非变体，最后全部；按出现次数降序。原 find 的精确分支。"""
    if not exact:
        return []
    pick = (
        [h for h in exact if h[4] in good]
        or [h for h in exact if not is_variant(h[4])]
        or exact
    )
    pick.sort(key=lambda h: -h[5])
    return [h[:4] for h in pick]


def partial_hits(rows, ke, kz, limit=5):
    """源顺序挑部分匹配的非变体，最多 limit 条；原 find 里 partial 循环。"""
    out = []
    for r in rows:
        if partial(ke, kz, r) and not is_variant(r.cls_lower):
            out.append((r.uuid, r.en, r.zh, r.rarity))
            if len(out) == limit:
                break
    return out


def summary(d, top=5):
    """掉落详情 → [(地区, 最高单箱概率, 箱子/位置说明)]，按概率排；原 crafting/loot.summary。"""
    out = []
    for r in d.get("regions") or []:
        best = r.get("best") or 0
        cs = sorted(
            r.get("containers") or [],
            key=lambda c: c.get("openp") or c.get("p") or 0,
            reverse=True,
        )
        where = ""
        if cs:
            c = cs[0]
            where = c.get("loc") or ""
            raw = (d.get("raw") or "").split(".")[-1].lower()
            name = (c.get("name") or "").split(" · ")[0].strip()
            if raw and name.lower() == raw:
                box = PLACED
            else:
                box = (
                    re.sub(
                        r"^Lootable_(Generated_)?Container_?", "", c.get("name") or ""
                    )
                    .replace("_", " ")
                    .strip()
                )
            where = "｜".join(x for x in (where, box) if x)
        out.append((r.get("name") or r.get("id"), best, where))
    out.sort(key=lambda x: x[1], reverse=True)
    return out[:top]


def group_info(detail, top=5):
    """info 的明细分组：概率取 6 位、同一概率和箱子合成一行，按概率降序取 top。

    返回 (rows, more)；没有任何分组返回 None。原 crafting/loot.info 里不联网的部分。
    """
    groups = {}
    for region, p, where in summary(detail, top=99):
        box = where.split("｜")[-1] if where else ""
        groups.setdefault((round(p, 6), box), []).append(region)
    if not groups:
        return None
    ordered = sorted(groups.items(), key=lambda kv: -kv[0][0])
    rows = [
        {"p": p, "box": box, "regions": regions, "placed": box == PLACED}
        for (p, box), regions in ordered[:top]
    ]
    shown = sum(len(r["regions"]) for r in rows)
    return rows, max(0, len(detail.get("regions") or []) - shown)


def mine_groups(best, top=5):
    """mine_info 的明细分组：地区 → (概率, 位置) 合成按概率排序的行。返回 (rows, more)。"""
    groups = {}
    for region, (p, loc) in best.items():
        groups.setdefault((round(p, 6), loc), []).append(region)
    ordered = sorted(groups.items(), key=lambda kv: -kv[0][0])
    rows = [
        {"p": p, "box": loc, "regions": regions} for (p, loc), regions in ordered[:top]
    ]
    shown = sum(len(r["regions"]) for r in rows)
    return rows, max(0, len(best) - shown)


def ship_groups(pairs, top=5):
    """ship_info 的按概率分组；pairs 是 (百分比, 地点名)。返回 (rows, more)。"""
    groups = {}
    for pct, loc in pairs:
        groups.setdefault(round(pct / 100, 6), []).append(loc)
    ordered = sorted(groups.items(), key=lambda kv: -kv[0])
    rows = [{"p": p, "box": "", "regions": regions} for p, regions in ordered[:top]]
    shown = sum(len(r["regions"]) for r in rows)
    total = sum(len(v) for v in groups.values())
    return rows, max(0, total - shown)


# ---------------------------------------------------------------- 副本专属矿（目录迁移 Q3 从 crafting/loot.py 搬来）
# 不会从箱子里开出来，只能在副本里开采（用户 2026-10-24 告知；掉落站把手采物品挂在挖矿宝石掉落表上，
# 那张表游戏文件里有、实际不刷）。值 = 开采点（可开采岩石）的类名前缀，排除的前缀
INSTANCE_ORES = {
    "carinite": ("mineablerock_fps_carinite", "mineablerock_fps_carinite_pure"),
    "carinitepure": ("mineablerock_fps_carinite_pure", None),
    "janalite": ("mineablerock_fps_janalite", None),
    "jaclium": ("mineablerock_fps_jaclium", None),
    "saldynium": ("mineablerock_fps_saldynium", None),
}
_INSTANCE_ZH = {
    "科力晶": "carinite",
    "科力晶（纯）": "carinitepure",
    "科力晶(纯)": "carinitepure",
    "纯科力晶": "carinitepure",
    "纯净科力晶": "carinitepure",
    "加纳石": "janalite",
    "杰金": "jaclium",
    "杰金矿石": "jaclium",
    "烁迪银": "saldynium",
    "烁迪银矿石": "saldynium",
}


def instance_ore(name_en="", name_zh=""):
    """是不是副本专属矿：返回 INSTANCE_ORES 的键，不是返回 None"""
    k = re.sub(r"[^a-z]", "", (name_en or "").lower().replace("(ore)", ""))
    if k in INSTANCE_ORES:
        return k
    return _INSTANCE_ZH.get((name_zh or "").replace(" ", ""))
