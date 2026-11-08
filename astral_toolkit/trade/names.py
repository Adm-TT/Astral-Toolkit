"""中文物品名 → 英文名（来自用户的游戏汉化包，和挖矿助手的中英对照表同源）

UEX 只认英文名；游戏是中文界面，截图识别和手动搜索得到的是中文名，这里负责换成英文再去查。
"""

import re

from ..contracts.textkeys import (
    fold_en as _fold_en,
    fold_en_loose as _fold_en_loose,
    norm_zh as _norm_zh,
)

CJK = re.compile(r"[一-鿿]")
_PAREN = re.compile(r"\s*[（(][^）)]*[）)]\s*")


# 按游戏数据内容版本缓存（公共工具 gamedata/_cache.VersionCache）：table 跟着 zh_pairs() 那份对象走（topic 已按版本缓存，
# 同一版本同一个对象），_index 跟着 table() 那份 dict 走。本模块顶层不 import gamedata（建库时 gamedata/_import → 本模块，
# 会循环），缓存对象第一次用时才建。
_caches: dict = {}


def _cache(name):
    c = _caches.get(name)
    if c is None:
        from ..gamedata._cache import VersionCache

        c = _caches.setdefault(name, VersionCache(identity=True))
    return c


def table() -> dict[str, str]:
    """{中文: 英文}，汉化包原文拼写；规则（去假英文名、zh_names 优先、zh_only_names 只补 ≥3 字的）在建库时算好
    （gamedata/_import._names_table），顺序同以前。库不可用时返回 {}，不缓存（库好了下次立刻正常）"""
    from .. import gamedata

    try:
        pairs = gamedata.names.zh_pairs()
    except gamedata.GamedataError:
        return {}
    return _cache("table").get_for(pairs, lambda: {p.zh: p.en for p in pairs})


def has_chinese(text: str) -> bool:
    return bool(CJK.search(text or ""))


def _norm(text):
    return re.sub(r"\s+", "", text or "")


def to_english(query: str, limit: int = 8) -> list[str]:
    """中文名对应的英文名：先精确，再去掉括号备注（如 "科力晶（单个矿块）"），最后按包含关系模糊找"""
    if not has_chinese(query):
        return []
    t = table()
    q = _norm(query)
    norm = {_norm(k): v for k, v in t.items()}
    for key in (q, _norm(_PAREN.sub("", query))):
        if key in norm:
            return [norm[key]]
    hits = []
    for zh, en in norm.items():
        if (q in zh or (len(zh) >= 2 and zh in q)) and en not in hits:
            hits.append(en)
            if len(hits) >= limit:
                break
    return hits


# ---------------------------------------------------------------- 认错的名字 → 汉化包里的标准名（2026-10-23）
# F8 认说明框时常有个别字认错或认丢：「冷冻舱（剜度）」认成「冷冻舱（刻度）」「冷冻舱（度）」，「巅峰期」认成「峰期」。
# 名字以玩家游戏里的汉化包为准：先用英文名对（英文很少认错），对不上再找最接近的中文名。


def _index() -> tuple[dict, dict]:
    """({规整的中文名: (中文, 英文)}, {折叠的英文名: (中文, 英文)})；跟着 table() 那份对象缓存"""
    t = table()
    return _cache("index").get_for(t, lambda: _build_index(t))


def _build_index(t):
    zh_map, en_map = {}, {}
    for zh, en in t.items():
        zh_map.setdefault(_norm_zh(zh), (zh, en))
        en_map.setdefault(_fold_en(en), (zh, en))
    return zh_map, en_map


def _loose_en() -> dict:
    """{英文名 l 当 i 折叠（contracts.textkeys.fold_en_loose）: (中文, 英文)}；两个不同的名字折到一起的键记 None（不猜）。
    跟着 _index() 那份英文表缓存"""
    _, en_map = _index()
    return _cache("loose_en").get_for(en_map, lambda: _build_loose_en(en_map))


def _build_loose_en(en_map):
    out = {}
    for k, v in en_map.items():
        lk = _fold_en_loose(k)
        out[lk] = v if out.get(lk, v) == v else None
    return out


_BILINGUAL = re.compile(r'^(.*[一-鿿）)])\s*([A-Za-z][A-Za-z0-9 \-\'".()/&]*)$')


def split_bilingual(text):
    """「塔兰导电石Taranite」「铁 Iron」这种中英连在一起的 → (中文, 英文)；不是这种的返回 (原文, "")"""
    m = _BILINGUAL.match((text or "").strip())
    return (m.group(1).strip(), m.group(2).strip()) if m else ((text or "").strip(), "")


def _mineral(zh, en):
    """矿物用矿物表（汉化包里同一个中文名常被别的东西占用，比如「铁」）。只认精确的：
    全部矿物（船挖、地面车、手挖、杰金 / 烁迪银这类新矿）的中文名、矿石名、英文名。
    以前只查船挖矿物表、而且「最像的就算」：杰金矿石 → 愈金、烁迪银矿石 → 萨维里金属（2026-10-24 用户截图）"""
    try:
        from ..mining.data import SIGNATURES
        from ..core.i18n import _tables, mineral_en, mineral_zh
    except Exception:
        return None
    by_en = {k.lower(): k for k in SIGNATURES}
    by_en.update({k.lower(): k for k in _tables(False)[1]})
    m = by_en.get((en or "").strip().lower())
    if not m and zh and not en:
        m = (
            mineral_en(zh, fuzzy=False, ship_only=False)
            if len(_norm_zh(zh)) <= 6
            else None
        )
    return (mineral_zh(m), m) if m else None


def _mineral_near(zh):
    """矿名认错一个字（烁迪银 → 炼迪银）：字数一样、只差一个字、至少 4 个字，才算是那个矿；差得多就不猜"""
    try:
        from ..core.i18n import _tables, mineral_zh
    except Exception:
        return None
    z = _norm_zh(zh)
    if len(z) < 4:
        return None
    hits = {
        en
        for k, en in _tables(False)[0].items()
        if len(k) == len(z) and sum(a != b for a, b in zip(k, z)) == 1
    }
    if len(hits) == 1:
        en = hits.pop()
        return mineral_zh(en), en
    return None


def _closest(keys, target, floor):
    """keys 里和 target 最像的（相似度 ≥ floor，而且明显比第二名像）；没有返回 None"""
    import difflib

    scored = []
    tset = set(target)
    for k in keys:
        if (
            abs(len(k) - len(target)) > max(2, len(target) // 3)
            or len(tset & set(k)) < len(tset) * 0.5
        ):
            continue
        scored.append((difflib.SequenceMatcher(None, k, target).ratio(), k))
    scored.sort(reverse=True)
    if not scored or scored[0][0] < floor:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.04 and scored[0][0] < 0.95:
        return None  # 两个一样像：不猜
    return scored[0][1]


def _from_items(en: str):
    """物品目录英文名精确（gamedata.items.by_name）：汉化包没有中文名的型号（JS-500）也能算命中。
    库不可用 / 查不到返回 None。顶层不 import gamedata，避免建库时循环。"""
    if not (en or "").strip():
        return None
    try:
        from ..gamedata import items as gd_items

        row = gd_items.by_name(en)
    except Exception:
        return None
    if row is None:
        return None
    return (row.zh or "", row.en or en)


def canonical(zh="", en=""):
    """OCR 认出的名字 → 汉化包里的标准 (中文名, 英文名)；对不上返回 None。
    顺序：拆开中英连写 → 矿物（精确）→ 英文名精确 → 中文名精确 → 物品目录英文精确 → 英文名 l 当 i 精确 → 英文名近似 → 矿名错一个字
    → 中文名近似（错一两个字、丢一个字）"""
    zh, en = (zh or "").strip(), (en or "").strip()
    if zh and not en:
        zh, en = split_bilingual(zh)
    hit = _mineral(zh, en)
    if hit:
        return hit
    zh_map, en_map = _index()
    if en and _fold_en(en) in en_map:
        return en_map[_fold_en(en)]
    if zh and _norm_zh(zh) in zh_map:
        return zh_map[_norm_zh(zh)]
    hit = _from_items(en)
    if hit:
        return hit
    if en:  # 英文行 l 和 I 认混（导弹名里的罗马数字 III 认成 Ill，RD-B2 2026-11-06）：l 当 i 再精确比一次
        hit = _loose_en().get(_fold_en_loose(en))
        if hit:
            return hit
    if en and len(_fold_en(en)) >= 6:
        k = _closest(en_map, _fold_en(en), 0.9)
        if k:
            return en_map[k]
    if zh and not en:
        hit = _mineral_near(zh)
        if hit:
            return hit
    if zh and len(_norm_zh(zh)) >= 3:
        k = _closest(zh_map, _norm_zh(zh), 0.75)
        if k:
            return zh_map[k]
    return None


def canonical_exact(zh="", en=""):
    """标题带「高把握库命中」：精确 + 英文高把握模糊；中文弱模糊不算。

    和 canonical() 的区别：**不算**矿名错一个字、中文近似（ratio≥0.75）。
    英文折叠后长度≥6、相似度≥0.9 且明显比第二名更像时，也算高把握（OCR 偶发错一两个字母；
    见 docs/superpowers/specs/2026-11-04-f8-title-band-ocr.md §4）。
    顺序：拆中英连写 → 矿物（精确）→ 中文名规整精确 → 英文名折叠精确 → 物品目录英文精确
    → 英文名近似（≥0.9 且唯一）。汉化包没有中文名的短型号（JS-500）靠物品目录英文精确。
    """
    zh, en = (zh or "").strip(), (en or "").strip()
    if zh and not en:
        zh, en = split_bilingual(zh)
    hit = _mineral(zh, en)
    if hit:
        return hit
    zh_map, en_map = _index()
    if zh and _norm_zh(zh) in zh_map:
        return zh_map[_norm_zh(zh)]
    if en and _fold_en(en) in en_map:
        return en_map[_fold_en(en)]
    hit = _from_items(en)
    if hit:
        return hit
    if en and len(_fold_en(en)) >= 6:
        k = _closest(en_map, _fold_en(en), 0.9)
        if k:
            return en_map[k]
    return None


def zh_for(en):
    """英文名 → 汉化包里的中文名（只认精确的，忽略大小写、空格、标点）"""
    hit = _mineral("", en) or _index()[1].get(_fold_en(en))
    return hit[0] if hit else None


def suggest(query, limit=8):
    """手动入库的联想：中文 / 英文 / 名字的一部分 / 错一两个字都能找到。返回 [(中文, 英文)]，最像的在前"""
    import difflib

    q = (query or "").strip()
    if not q:
        return []
    zq, eq = _norm_zh(q), _fold_en(q)
    scored = {}
    for zh, en in table().items():
        z, e = _norm_zh(zh), _fold_en(en)
        if has_chinese(q):
            if not (set(zq) & set(z)):
                continue
            s = (
                1.0
                if z == zq
                else 0.9
                if z.startswith(zq)
                else 0.8
                if zq in z
                else difflib.SequenceMatcher(None, z, zq).ratio() * 0.75
            )
        else:
            if not eq or eq[0] not in e:
                continue
            s = (
                1.0
                if e == eq
                else 0.9
                if e.startswith(eq)
                else 0.8
                if eq in e
                else difflib.SequenceMatcher(None, e, eq).ratio() * 0.75
            )
        if s >= 0.5:
            scored[(zh, en)] = max(
                s - len(z) * 0.002, scored.get((zh, en), 0)
            )  # 一样像时短的（更通用的）在前
    return [k for k, _ in sorted(scored.items(), key=lambda kv: -kv[1])[:limit]]
