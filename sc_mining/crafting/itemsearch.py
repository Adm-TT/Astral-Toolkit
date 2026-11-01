"""物品查询搜索（1.6.41）：商店、掉落、汉化包三份物品名合成一份索引，中英文都能搜

以前的毛病（2026-10-23 用户：视差步枪搜不到）：
- 中文先用对照表换成英文再搜，对照表里有「视差步枪 → HD」这种假的（物品简称后面带的型号代码），搜出来不对
- 中文只认连着的一段，「视差步枪」对不上「视差 能量突击步枪」
- 商店搜到 5 个以上就不看掉落数据，只在掉落数据里的东西（很多护甲、衣服）搜不到
- 汉化包里有、商店和掉落数据里都没有的六百多件（任务奖励、活动、涂装……）根本搜不到

现在：
- 中文直接对所有物品的中文名搜，字按顺序出现就算（中间可以隔着别的字）：视差步枪 → 视差 能量突击步枪
- 排序：名字完全一样 > 最后一个字对得上名字结尾（中文名的「是什么」在最后：步枪、头盔）> 连着的一段 > 按顺序出现；
  同一档里基础款排在涂装 / 限定版（名字带引号的）前面，有商店或掉落数据的排在前面，短的在前
- 英文：完全一样 > 开头对得上 > 包含 > 每个词都有（顺序不限）
"""

import re
import unicodedata

from . import shops

_cache = {"key": None, "index": None}
_build_lock = __import__(
    "threading"
).Lock()  # 启动时后台先建索引；玩家这时搜索就等它建完，不重复建


def zh_key(s):
    """比较中文名用：全角半角统一、去掉空格引号标点、英文小写（中文照留）"""
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", s or "").lower())


def en_key(s):
    return shops._fold(unicodedata.normalize("NFKC", s or ""))


def _has_cjk(s):
    return bool(re.search(r"[一-鿿]", s or ""))


def _variant(en, zh):
    """涂装 / 限定版：名字里带引号（Parallax "Hurston" …）"""
    return '"' in (en or "") or "“" in (zh or "") or "”" in (zh or "")


def _trigrams(s):
    return {s[i : i + 3] for i in range(len(s) - 2)}


def _build():
    with _build_lock:
        return _build_locked()


def warm_up():
    """窗口打开后在后台先把搜索索引建好（要读几份几 MB 的数据，第一次约 1–3 秒）：玩家第一次搜索不用等"""
    import threading

    def run():
        try:
            _build()
        except Exception:
            pass

    threading.Thread(target=run, daemon=True, name="search-warmup").start()


def _empty_index():
    return {"rows": [], "by_char": {}, "by_tri": {}, "by_en": {}}


def _build_locked():
    """从游戏数据层的物品目录建内存索引（合并规则在 gamedata/_import.import_items，和以前这里的一样）；
    缓存键是库的内容版本：五份源（商店、掉落、汉化、旧写法、wiki）哪份变了都会重建"""
    from .. import gamedata
    from ..gamedata import items as gd_items

    try:
        gamedata.ensure()
        with gamedata.snapshot() as snap:
            key = (snap.data_version,)
            if _cache["key"] == key:
                return _cache["index"]
            items = gd_items.all(snap)
            zks_of = gd_items.zh_keys_of_all(snap)
            names = gd_items.names_by_kind(("zh_loot", "aka"), snap)
            shop_of = gd_items.first_source_ids("uex", snap)
    except gamedata.GamedataError:
        return (
            _empty_index()
        )  # 库建不出来：和以前没有数据文件一样，搜不到东西，不报错（不缓存，下次再试）
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
        for t in _trigrams(e["ek"]):
            by_tri.setdefault(t, set()).add(i)
        for old in e.get("aka") or []:
            for t in _trigrams(en_key(old)):
                by_tri.setdefault(t, set()).add(i)
    index = {"rows": rows, "by_char": by_char, "by_tri": by_tri, "by_en": by_en}
    _cache.update(key=key, index=index)
    return index


def _on_data_changed():
    """data_pack.clear_caches() 调（数据文件换了之后）：汉化包重建（zh_names / name_aliases）、掉落索引更新这几处
    还没经过 gamedata.updating() 写文件，库不会自己重建，索引按库的内容版本缓存就会一直是旧的——这里补建一次库
    （源没变就是空操作）。那几处的写入改进更新边界后（批 4 / 批 6）可以删掉这个钩子（审查 2026-11-02 第 2 条）"""
    from .. import gamedata

    try:
        gamedata.rebuild()
    except Exception:  # noqa: BLE001 —— 清缓存的钩子不能让更新流程报失败；建不出来下次查询再试
        pass


try:
    from ..update.data_pack import CACHE_HOOKS as _CACHE_HOOKS

    _CACHE_HOOKS.append(_on_data_changed)
except Exception:  # noqa: BLE001 —— 和 tasks/goals.py 登记钩子的写法一样
    pass


def wiki_items():
    """data/wiki_items.json：star-citizen.wiki（游戏解包）的物品清单 [{n, t, s, mfr}]；没有这份数据就是空的"""
    from ..core.paths import DATA, cached_json

    return cached_json(DATA / "wiki_items.json", lambda d: d.get("items") or [], [])


def _wiki_noise(e):
    """只在 wiki 清单里、玩家不会去搜的：涂装（物品查询不卖、不掉）、飞船内部件（遥控炮塔、对接舱这种没名字的通用件）"""
    t = (e.get("wtype") or "").lower()
    return t in ("paints", "misc", "flair_surface") or e["en"].lower() in (
        "turret",
        "remote turret",
        "docking bay",
        "fuel tanks",
        "radar",
        "waste",
    )


def _subseq(q, s):
    it = iter(s)
    return all(c in it for c in q)


def _rank_zh(q, keys):
    """0 完全一样；1 字按顺序都有、最后一个字是名字结尾（视差步枪 → 视差 能量突击步枪）；2 开头一样；3 连着的一段；4 按顺序都有"""
    best = None
    for k in keys:
        if k == q:
            return 0
        if not _subseq(q, k):
            continue
        r = 1 if k[-1] == q[-1] else 2 if k.startswith(q) else 3 if q in k else 4
        best = r if best is None else min(best, r)
    return best


def _rank_en(q, tokens, ek):
    """0 完全一样；1 几个词都有、最后一个词是名字结尾（parallax rifle → Parallax Energy Assault Rifle）；
    2 开头一样；3 包含；4 几个词都有（顺序不限）"""
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


def find(query, limit=30):
    """[{en, zh, shop(商店 id 或 None), cat, loot(掉落数据里有), loc(只有汉化包里有名字), variant}]，最像的在前"""
    q = (query or "").strip()
    if not q:
        return []
    index = _build()
    rows = index["rows"]
    hits = []
    if _has_cjk(q):
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
            r = _rank_zh(qk, rows[i]["zks"])
            if r is not None:
                hits.append((r, i))
    else:
        qe = en_key(q)
        if not qe:
            return []
        tokens = [t for t in (en_key(x) for x in re.split(r"[\s/,，、]+", q)) if t]
        # 候选：每个 3 个字母以上的词都得出现（完全一样、开头、包含、几个词都有，这几种都满足）；词都太短就全部过一遍
        grams = {g for t in (tokens or [qe]) if len(t) >= 3 for g in _trigrams(t)}
        if grams:
            cand = None
            for g in grams:
                s = index["by_tri"].get(g, set())
                cand = set(s) if cand is None else cand & s
        else:
            cand = range(len(rows))
        for i in cand:
            r = _rank_en(qe, tokens, rows[i]["ek"])
            for old in rows[i].get("aka") or []:
                r2 = _rank_en(qe, tokens, en_key(old))
                if r2 is not None and (r is None or r2 < r):
                    r = r2
            if r is not None:
                hits.append((r, i))
    size = (
        (lambda e: e["zlen"]) if _has_cjk(q) else (lambda e: len(e["en"]))
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


def lookup(en):
    """按英文名（忽略大小写、空格、标点）找索引里的这一件；没有返回 None"""
    return _build()["by_en"].get(en_key(en))
