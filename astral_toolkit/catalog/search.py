"""物品查询的纯规则：建索引、候选筛选、中英文排序。

原 crafting/itemsearch.py 的 _index_from 纯计算部分、_has_cjk、_variant、_trigrams、
_subseq、_rank_zh、_rank_en、_wiki_noise，以及 find / lookup 的匹配排序搬到这里。
调用方先把物品行、名字表、商店来源取好传进来；本模块不读文件、不联网、不用缓存。
"""

import re

from ..contracts.textkeys import en_key, zh_key


def has_cjk(s):
    """原 crafting/itemsearch._has_cjk。"""
    return bool(re.search(r"[一-鿿]", s or ""))


def variant(en, zh):
    """原 crafting/itemsearch._variant：涂装 / 限定版，名字里带引号。"""
    return '"' in (en or "") or "“" in (zh or "") or "”" in (zh or "")


def trigrams(s):
    """原 crafting/itemsearch._trigrams。"""
    return {s[i : i + 3] for i in range(len(s) - 2)}


def wiki_noise(e):
    """原 crafting/itemsearch._wiki_noise：只在 wiki 清单里、玩家不会去搜的条目。"""
    t = (e.get("wtype") or "").lower()
    return t in ("paints", "misc", "flair_surface") or e["en"].lower() in (
        "turret",
        "remote turret",
        "docking bay",
        "fuel tanks",
        "radar",
        "waste",
    )


def subseq(q, s):
    """原 crafting/itemsearch._subseq。"""
    it = iter(s)
    return all(c in it for c in q)


def rank_zh(q, keys):
    """原 crafting/itemsearch._rank_zh。"""
    best = None
    for k in keys:
        if k == q:
            return 0
        if not subseq(q, k):
            continue
        r = 1 if k[-1] == q[-1] else 2 if k.startswith(q) else 3 if q in k else 4
        best = r if best is None else min(best, r)
    return best


def rank_en(q, tokens, ek):
    """原 crafting/itemsearch._rank_en。"""
    if ek == q:
        return 0
    multi = len(tokens) > 1 and all(t in ek for t in tokens)
    if multi and ek.endswith(tokens[-1]):
        return 1
    if ek.startswith(q):
        return 2
    if q in ek:
        return 3
    return 4 if multi else None


def empty_index():
    """原 crafting/itemsearch._empty_index。"""
    return {"rows": [], "by_char": {}, "by_tri": {}, "by_en": {}}


def index_from(items, zks_of, names, shop_of):
    """原 crafting/itemsearch._index_from 的纯计算部分：从已取好的行建内存索引。"""
    rows = []
    for it in items:
        e = {
            "en": it.en,
            "ek": it.item_id,
            "zh": it.zh,
            "zh_loot": next(
                (n for k, n, _m in names.get(it.item_id, ()) if k == "zh_loot"), ""
            ),
            "zks": zks_of.get(it.item_id, ()),
            "shop": int(shop_of[it.item_id]) if it.item_id in shop_of else None,
            "cat": it.cat,
            "loot": it.has_loot,
            "loc": it.loc,
        }
        if it.wiki:  # 以前只有对上 wiki 清单的才有这几个键
            e.update(wiki=True, wtype=it.wtype, wsize=it.wsize, desc=it.desc)
        aka = [n for k, n, _m in names.get(it.item_id, ()) if k == "aka"]
        if aka:
            e["aka"] = aka
        e["zlen"] = it.zlen
        e["variant"] = it.variant
        e["has_data"] = e["shop"] is not None or e["loot"]
        rows.append(e)
    by_en = {e["ek"]: e for e in rows}
    for e in rows:
        for old in e.get("aka") or []:
            by_en.setdefault(en_key(old), e)
    by_char, by_tri = {}, {}
    for i, e in enumerate(rows):
        for c in set("".join(e["zks"])):
            by_char.setdefault(c, set()).add(i)
        for t in trigrams(e["ek"]):
            by_tri.setdefault(t, set()).add(i)
        for old in e.get("aka") or []:
            for t in trigrams(en_key(old)):
                by_tri.setdefault(t, set()).add(i)
    return {"rows": rows, "by_char": by_char, "by_tri": by_tri, "by_en": by_en}


def find(index, query, limit=30):
    """原 crafting/itemsearch.find 的匹配和排名；索引由调用方取好传入。"""
    q = (query or "").strip()
    if not q:
        return []
    rows = index["rows"]
    hits = []
    if has_cjk(q):
        qk = zh_key(q)
        if not qk:
            return []
        cand = None
        for c in set(qk):
            s = index["by_char"].get(c)
            if not s:
                return []
            cand = set(s) if cand is None else cand & s
        for i in cand or ():
            r = rank_zh(qk, rows[i]["zks"])
            if r is not None:
                hits.append((r, i))
    else:
        qe = en_key(q)
        if not qe:
            return []
        tokens = [t for t in (en_key(x) for x in re.split(r"[\s/,，、]+", q)) if t]
        # 候选：每个 3 个字母以上的词都得出现（完全一样、开头、包含、几个词都有，这几种都满足）；词都太短就全部过一遍
        grams = {g for t in (tokens or [qe]) if len(t) >= 3 for g in trigrams(t)}
        if grams:
            cand = None
            for g in grams:
                s = index["by_tri"].get(g, set())
                cand = set(s) if cand is None else cand & s
        else:
            cand = range(len(rows))
        for i in cand or ():
            r = rank_en(qe, tokens, rows[i]["ek"])
            for old in rows[i].get("aka") or []:
                r2 = rank_en(qe, tokens, en_key(old))
                if r2 is not None and (r is None or r2 < r):
                    r = r2
            if r is not None:
                hits.append((r, i))
    size = (
        (lambda e: e["zlen"]) if has_cjk(q) else (lambda e: len(e["en"]))
    )  # 同一档里短的（基础款）在前
    hits.sort(
        key=lambda h: (
            h[0],
            rows[h[1]]["variant"],
            not rows[h[1]]["has_data"],
            size(rows[h[1]]),
            rows[h[1]]["en"].lower(),
        )
    )
    out = []
    for _, i in hits[:limit]:
        e = rows[i]
        out.append(
            {
                "en": e["en"],
                "zh": e["zh"],
                "shop": e["shop"],
                "cat": e["cat"],
                "loot": e["loot"],
                "loc": not e["has_data"],
                "variant": e["variant"],
                "wiki": bool(e.get("wiki")) and not e["has_data"] and not e["loc"],
                "wtype": e.get("wtype") or "",
                "wsize": e.get("wsize"),
            }
        )
    return out


def lookup(index, en):
    """原 crafting/itemsearch.lookup：按英文名键找索引里的这一件；没有返回 None。"""
    return index["by_en"].get(en_key(en))
