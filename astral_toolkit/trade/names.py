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
    以前只查船挖矿物表、而且「最像的就算」：杰金矿石 → 愈金、烁迪银矿石 → 萨维里金属（2026-10-24 用户截图）。
    原矿 / 矿石名（「铁原矿」「金矿石」）不在这里认：它和精炼的是两样东西（老大 2026-11-08 定分开），交给汉化包对照表
    （「铁原矿」Iron (Ore)）；以前这里认成「铁」Iron，F8 查的是精炼铁的价、盘点记成精炼铁"""
    try:
        from ..mining.data import SIGNATURES
        from ..core.i18n import _tables, mineral_en, mineral_zh
    except Exception:
        return None
    by_en = {k.lower(): k for k in SIGNATURES}
    by_en.update({k.lower(): k for k in _tables(False)[1]})
    m = by_en.get((en or "").strip().lower())
    if not m and zh and not en:
        if _raw_name(zh):
            return None
        m = (
            mineral_en(zh, fuzzy=False, ship_only=False)
            if len(_norm_zh(zh)) <= 6
            else None
        )
    return (mineral_zh(m), m) if m else None


def _raw_name(zh):
    """是不是矿物表里的原矿 / 矿石名（core/i18n.raw_names：「塔兰导电石原矿」「铁原矿」「稀钛铁矿」）"""
    try:
        from ..core.i18n import raw_names
    except Exception:
        return False
    return _norm_zh(zh) in raw_names()


def _mineral_near(zh):
    """矿名认错一个字（烁迪银 → 炼迪银）：字数一样、只差一个字、至少 4 个字，才算是那个矿；差得多就不猜。
    差一个字的是原矿名（塔兰导电石原旷 → 塔兰导电石原矿）就用汉化包里的原矿名，汉化包里没有就不认（原矿和精炼分开，
    老大 2026-11-08 定）；原矿名、精炼名都只差一个字也不猜"""
    try:
        from ..core.i18n import _tables, mineral_zh, raw_names
    except Exception:
        return None
    z = _norm_zh(zh)
    if len(z) < 4:
        return None
    hits = {
        k: en
        for k, en in _tables(False)[0].items()
        if len(k) == len(z) and sum(a != b for a, b in zip(k, z)) == 1
    }
    if len(set(hits.values())) != 1:
        return None
    raw = [k for k in hits if k in raw_names()]
    if raw:
        return _index()[0].get(_norm_zh(raw[0])) if len(raw) == len(hits) else None
    en = next(iter(hits.values()))
    return mineral_zh(en), en


def _raw_garbled(z, k):
    """认出的中文名 z 是名字 k 前后多一两个字、多出来的像「原」「矿」「石」（形近字照采矿那边的 CONFUSABLE 换回来，另加「旷」），
    而 k 有原矿名（「k原矿」「k矿石」「k矿」「原k」在汉化包里是原矿、或在矿物表的原矿名里）：「塔兰导电石源护」「萨达瑞晶源护」
    「源欧拉特烃」多半是原矿名认错了字，不近似成精炼的那个（原矿和精炼分开，2026-11-08；以前错两个字的原矿名会被当成
    认准了的精炼矿）。多出来的是别的字（读屏带进来的「丨」「口」这种杂字）照旧近似"""
    if len(z) - len(k) not in (1, 2):
        return False
    if z.startswith(k):
        extra = z[len(k) :]
    elif z.endswith(k):
        extra = z[: len(z) - len(k)]
    else:
        return False
    try:
        from ..core.i18n import CONFUSABLE, raw_names
    except Exception:
        return False
    if not any((CONFUSABLE.get(c) or c) in "原矿石旷" for c in extra):
        return False
    zh_map = _index()[0]
    for r in (k + "原矿", k + "矿石", k + "矿", "原" + k):
        hit = zh_map.get(r)
        if r in raw_names() or (hit and raw_base(hit[1])):
            return True
    return False


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
    → 中文名近似（错一两个字、丢一个字）。原矿 / 矿石名（塔兰导电石原矿、铁原矿）只认汉化包里精确的那条，不认成精炼的矿
    （老大 2026-11-08 定原矿、精炼分开）"""
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
    if zh and not en and _raw_name(zh):
        return None  # 原矿名汉化包里还没有（没按新规则重建）：不认准，也不近似成精炼的那个矿（2026-11-08 原矿精炼分开）
    if zh and not en:
        hit = _mineral_near(zh)
        if hit:
            return hit
    if zh and len(_norm_zh(zh)) >= 3:
        k = _closest(zh_map, _norm_zh(zh), 0.75)
        if k and not _raw_garbled(_norm_zh(zh), k):
            return zh_map[k]
    return None


def canonical_exact(zh="", en=""):
    """精确命中汉化包 / 矿物表 / 物品目录的 (中文名, 英文名)；对不上返回 None。**不做模糊**。

    F8 配物品（matching 的「认准了」）、盘点（库里有没有这件）、维科洛都用它判断「名字认准了」：
    只差一个罗马数字 / 尺寸数字的两件（Ignite I / II）模糊比起来超过 0.9，放进来会配成另一件
    （老大 11-09 定：尺寸是关键数据，不许认错）。F8 标题带「停不停」要宽一点，用 canonical_title。
    顺序：拆中英连写 → 矿物（精确）→ 中文名规整精确 → 英文名折叠精确 → 物品目录英文精确
    （汉化包没有中文名的短型号 JS-500 靠物品目录，PR #18 加）。
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
    return _from_items(en)


def _size_tail(en: str):
    """英文名末尾的尺寸 / 型号：数字（Compensator2、S3 的 3）或单独一截罗马数字（Ignite II，l 当 I）；没有是 None"""
    s = (en or "").strip()
    m = re.search(r"(\d+)$", s)
    if m:
        return ("d", m.group(1))
    m = re.search(r"[\s\-]([IVXl]{1,4})$", s)
    if m:
        return ("r", m.group(1).upper().replace("L", "I"))
    return None


def canonical_title(zh="", en=""):
    """F8 标题带「高把握、可以停」：canonical_exact，加英文高把握模糊——折叠后长度≥6、相似度≥0.9 且明显比
    第二名像（OCR 偶发错一两个字母；PR #18，docs/superpowers/specs/2026-11-04-f8-title-band-ocr.md §4）。
    模糊这一档末尾的尺寸 / 罗马数字两边得一样（都没有也行）：Ignite I 认成 Ignite Il、Compensator2 丢了 2，
    都不算可以停，接着放大认（11-12 合 PR #18 后收窄）。只给标题带判断停不停用，配物品、盘点用 canonical_exact。"""
    hit = canonical_exact(zh, en)
    if hit:
        return hit
    zh, en = (zh or "").strip(), (en or "").strip()
    if zh and not en:
        zh, en = split_bilingual(zh)
    if not en or len(_fold_en(en)) < 6:
        return None
    _zh_map, en_map = _index()
    k = _closest(en_map, _fold_en(en), 0.9)
    if not k:
        return None
    hit = en_map[k]
    if _size_tail(en) != _size_tail(hit[1]):
        return None
    return hit


# 原矿 / 矿石名的写法：末尾「(Raw)」「(Ore)」「(R)」（市场上的中文名也有「（原矿）」「（矿石）」），或开头「Raw 」（原冰 Raw Ice）
_RAW_SUFFIX = re.compile(r"\s*[（(]\s*(?:raw|ore|r|原矿|矿石)\s*[)）]\s*$", re.I)


def raw_base(en):
    """原矿 / 矿石的英文名去掉原矿那截、剩下的矿名：Taranite (Raw)、Gold (Ore)、Sadaryx (Raw) → Taranite、Gold、Sadaryx，
    Raw Ice → Ice；不是原矿返回 None。只认原矿的写法：别的括号（纯净科力晶「Carinite (Pure)」、「(Modified)」）不算；
    开头的「Raw 」要后面是矿名才算"""
    en = (en or "").strip()
    base = _RAW_SUFFIX.sub("", en).strip()
    if base != en:
        return base or None
    if en.lower().startswith("raw "):
        base = en[4:].strip()
        return base if _mineral("", base) else None
    return None


def raw_ore(name):
    """原矿 / 矿石的名字（中文或英文：「塔兰导电石原矿」「Taranite (Raw)」「金矿石」「原冰」）→ 汉化包里的 (中文名, 英文名)；
    不是原矿返回 None。原矿和精炼是两样东西（老大 2026-11-08 定分开）：库存页手动入库、名字联想按原矿记、按 SCU 算"""
    name = (name or "").strip()
    hit = canonical_exact(name, "") if has_chinese(name) else canonical_exact("", name)
    return hit if hit and raw_base(hit[1]) else None


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


# ---------------------------------------------------------------- 罗马数字（盘点：I / II 不许认错，老大 2026-11-09）
_ROMANS = {
    "I",
    "II",
    "III",
    "IV",
    "V",
    "VI",
    "VII",
    "VIII",
    "IX",
    "X",
    "XI",
    "XII",
    "XIII",
    "XIV",
    "XV",
    "XVI",
    "XVII",
    "XVIII",
    "XIX",
    "XX",
}
_ROMAN_LIKE = "[IVXLl1|ı川]+"  # OCR 常把 I 认成 l、1、|；中文行里的 III 常认成「川」


def _roman_fix(s):
    return "".join("I" if c in "lL1|ı" else c for c in s.replace("川", "III")).upper()


def _roman_pattern(name):
    """标准名里单独成词的罗马数字 → (认出的名字里找它们的正则, 应有的数字)；没有罗马数字返回 None。
    别的词照字面比（不分大小写、词间空格可有可无：OCR 常把空格吞掉，「OmniskyXllCannon」）"""
    words = (name or "").split()
    want = [w for w in words if w in _ROMANS]
    if not want:
        return None
    parts = [f"({_ROMAN_LIKE})" if w in _ROMANS else re.escape(w) for w in words]
    return re.compile(r"\s*".join(parts), re.I), want


def roman_reads(raw, canon):
    """认出的名字 raw (中文, 英文) 里、对着标准名 canon 那几个罗马数字的位置读到了什么：
    [(行号 0 中文 / 1 英文, 读到的数字列表或 None 找不到, 标准名的数字列表)]；标准名两行都没有罗马数字返回 []"""
    out = []
    for i, (got, std) in enumerate(zip(raw or ("", ""), canon or ("", ""))):
        pat = _roman_pattern(std)
        if pat is None:
            continue
        rx, want = pat
        m = rx.search(got or "")
        out.append((i, [_roman_fix(g) for g in m.groups()] if m else None, want))
    return out


def roman_swap(name, want, got):
    """把标准名里的罗马数字 want 依次换成 got：「Ignite II Missile」→「Ignite I Missile」（查库里有没有这件）"""
    it = iter(got)
    return (
        " ".join(next(it) if w in _ROMANS else w for w in (name or "").split())
        if len(got) == len(want)
        else ""
    )
