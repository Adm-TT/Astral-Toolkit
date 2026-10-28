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
import json
import re
import unicodedata

from . import shops

_cache = {"key": None, "index": None}
_build_lock = __import__("threading").Lock()     # 启动时后台先建索引；玩家这时搜索就等它建完，不重复建


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
    return {s[i:i + 3] for i in range(len(s) - 2)}


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


def _build_locked():
    from . import loot
    from .i18n import gear_zh_of_item
    from .trade import names
    data = shops.load(auto_update=False)
    idx = loot.load_index(False) or {}
    table = names.table()
    from .paths import DATA as _D, file_stamp
    key = (file_stamp(_D / "shops.json"), file_stamp(_D / "loot_index.json"), file_stamp(_D / "zh_names.json"), id(table))   # 地址会被复用（细查 2026-10-28）
    if _cache["key"] == key:
        return _cache["index"]
    by_en, rows = {}, []

    def entry(en):
        ek = en_key(en)
        if not ek:
            return None
        e = by_en.get(ek)
        if e is None:
            e = by_en[ek] = {"en": en.replace("\xa0", " "), "ek": ek, "zh": "", "zh_loot": "", "zks": set(),
                             "shop": None, "cat": "", "loot": False, "loc": False}
            rows.append(e)
        return e

    for iid, (en, cat) in (data.get("items") or {}).items():
        e = entry(en)
        if e and e["shop"] is None:
            e["shop"], e["cat"] = int(iid), cat or ""
    for r in idx.get("rows") or []:
        en, zh = r[1], r[5] or ""
        if _has_cjk(en) and not _has_cjk(zh):       # 掉落数据里个别中英文填反了（「DYL - 夹克 - 名称」）
            en, zh = zh or en, en
        if not _has_cjk(zh):                         # 「PH - hdh_boots_01_01_13」这种占位名不算中文名
            zh = ""
        e = entry(en)
        if e:
            e["loot"] = True
            if zh:
                e["zh_loot"] = e["zh_loot"] or zh
                e["zks"].add(zh_key(zh))
    for zh, en in table.items():                 # 汉化包（和游戏里看到的名字一样）
        e = entry(en)
        if e:
            e["loc"] = True
            e["zh"] = e["zh"] or zh
            e["zks"].add(zh_key(zh))
    for w in wiki_items():                       # 英文 wiki 的物品清单（1.6.48）：只补别处都没有的英文名，带类型 / 尺寸 / 描述；中文名只信汉化包
        e = entry(w["n"])
        if e:
            e.setdefault("wiki", True)
            e["wtype"], e["wsize"], e["desc"] = w.get("t") or "", w.get("s"), w.get("d") or ""
    aliases = {}                                 # 汉化包里写错 / 过时的英文（1.6.49，localization.rebuild 写的 name_aliases.json）：搜旧写法也能找到正名
    try:
        from .paths import DATA
        aliases = json.loads((DATA / "name_aliases.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    for old, real in aliases.items():
        e = by_en.get(en_key(real))
        if e and en_key(old) not in by_en:
            e.setdefault("aka", []).append(old)
    # 只有汉化包里有、中文名又和一件有数据的物品一样的：是同一件东西的另一种英文写法（「劳森采矿激光器」→ Lawson），不单列
    taken = {k for e in rows if e["shop"] is not None or e["loot"] for k in e["zks"]}
    rows = [e for e in rows if e["shop"] is not None or e["loot"] or not (e["zks"] & taken)]
    rows = [e for e in rows if e["shop"] is not None or e["loot"] or e["loc"] or not _wiki_noise(e)]
    by_en = {e["ek"]: e for e in rows}
    for e in rows:
        for old in e.get("aka") or []:
            by_en.setdefault(en_key(old), e)
    by_char, by_tri = {}, {}
    for i, e in enumerate(rows):
        e["zh"] = e["zh"] or e["zh_loot"]
        gz = gear_zh_of_item(e["en"])              # 采矿装备：中文写不带型号的名字（霍夫斯泰德），中文也搜得到（2026-10-26）
        if gz:
            e["zh"] = gz
            e["zks"] = tuple(dict.fromkeys((*e["zks"], zh_key(gz))))
        e["zks"] = tuple(k for k in e["zks"] if k)
        e["zlen"] = min((len(k) for k in e["zks"]), default=99)
        e["variant"] = _variant(e["en"], e["zh"])
        e["has_data"] = e["shop"] is not None or e["loot"]
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




def wiki_items():
    """data/wiki_items.json：star-citizen.wiki（游戏解包）的物品清单 [{n, t, s, mfr}]；没有这份数据就是空的"""
    from .paths import DATA, cached_json
    return cached_json(DATA / "wiki_items.json", lambda d: d.get("items") or [], [])


def _wiki_noise(e):
    """只在 wiki 清单里、玩家不会去搜的：涂装（物品查询不卖、不掉）、飞船内部件（遥控炮塔、对接舱这种没名字的通用件）"""
    t = (e.get("wtype") or "").lower()
    return t in ("paints", "misc", "flair_surface") or e["en"].lower() in ("turret", "remote turret", "docking bay", "fuel tanks", "radar", "waste")


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
    size = (lambda e: e["zlen"]) if _has_cjk(q) else (lambda e: len(e["en"]))      # 同一档里短的（基础款）在前
    hits.sort(key=lambda h: (h[0], rows[h[1]]["variant"], not rows[h[1]]["has_data"], size(rows[h[1]]), rows[h[1]]["en"].lower()))
    out = []
    for _, i in hits[:limit]:
        e = rows[i]
        out.append({"en": e["en"], "zh": e["zh"], "shop": e["shop"], "cat": e["cat"], "loot": e["loot"],
                    "loc": not e["has_data"], "variant": e["variant"], "wiki": bool(e.get("wiki")) and not e["has_data"] and not e["loc"],
                    "wtype": e.get("wtype") or "", "wsize": e.get("wsize")})
    return out


def lookup(en):
    """按英文名（忽略大小写、空格、标点）找索引里的这一件；没有返回 None"""
    return _build()["by_en"].get(en_key(en))
