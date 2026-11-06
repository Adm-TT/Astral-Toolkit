"""商店查询的纯规则：按名字找物品、买卖行排序、最近买点排序、同款候选。

原 crafting/shops.py 里的纯计算搬到这里（目录迁移 Q2 把它其余部分拆开：从 UEX 更新 shops.json 在 update/shops.py，
查 gamedata、算导航距离在 tasks/catalog_queries/shops.py）；catalog 不读文件、不联网、不碰全局缓存。
"""

import difflib
import re

from ..contracts.textkeys import fold_en_loose

_VARIANT = re.compile(r'\s*["“][^"”]+["”]\s*')


def find(rows, keys, limit=12):
    """原 crafting/shops.find 的匹配部分。

    rows 是 (id, 英文名, 类别, 折叠名)，keys 是旧文件解析好的查询键。
    """
    out, seen = [], set()
    for key in keys:
        k = fold_en_loose(key)
        if not k:
            continue
        exact = [(i, n, c) for i, n, c, f in rows if f == k]
        part = [(i, n, c) for i, n, c, f in rows if k in f and f != k]
        for row in exact + sorted(part, key=lambda r: len(r[1])):
            if row[0] not in seen:
                seen.add(row[0])
                out.append(row)
    return out[:limit]


def find_close(rows, name, cutoff=0.88):
    """原 crafting/shops.find_close 的匹配部分。"""
    k = fold_en_loose(name)
    if len(k) < 5:
        return None
    best = difflib.get_close_matches(k, [f for *_, f in rows], n=1, cutoff=cutoff)
    if not best:
        return None
    return next((i, n, c) for i, n, c, f in rows if f == best[0])


def where(rows):
    """原 crafting/shops.where 的排序部分：买价从低到高，卖价从高到低。"""
    buy = sorted(
        (r.price_buy, r.shop_name, r.place_text) for r in rows if r.price_buy > 0
    )
    sell = sorted(
        ((r.price_sell, r.shop_name, r.place_text) for r in rows if r.price_sell > 0),
        reverse=True,
    )
    return buy, sell


def nearest(rows, n=3):
    """原 crafting/shops.nearest 的排序和同地点去重部分。

    rows 是旧文件已经算好距离的 (距离米, 价格, 商店, 位置)。
    """
    out = sorted(rows, key=lambda x: (x[0], x[1]))
    picked, places = [], set()  # 同一个空间站/城市只留一家（最便宜的），凑 3 个不同地点
    for row in out:
        if row[3] not in places:
            places.add(row[3])
            picked.append(row)
        if len(picked) == n:
            break
    return picked


def base_names(name):
    """限定版 → 可能的原型名：去掉引号里的涂装名；再去掉 -II / Mk II 之类的型号后缀。

    原 crafting/shops.base_names。
    """
    b1 = re.sub(r"\s+", " ", _VARIANT.sub(" ", name)).strip()
    b2 = re.sub(
        r"(?i)(-|\s)([il]{2,3}|iv|mk\s*\w+)\b", "", b1
    ).strip()  # OCR 常把 II 认成 ll
    return [b for b in dict.fromkeys([b1, b2]) if b and b != name]


def variant_candidates(rows, base, name):
    """某个原型名 base 下可能的同款 [(id, 名字, 类别)]，按名字长度排序。

    原 crafting/shops.variants 的候选匹配和排序部分；buyable 过滤在 tasks/catalog_queries/shops.variants。
    """
    k = fold_en_loose(base)
    words = [w for w in re.findall(r"[a-z0-9]+", base.lower()) if len(w) > 2]
    self_key = fold_en_loose(name)
    out = []
    for iid, n, c, f in sorted(rows, key=lambda r: len(r[1])):
        if f == self_key:
            continue
        if f == k or (words and all(fold_en_loose(w) in f for w in words)):
            out.append((iid, n, c))
    return out
