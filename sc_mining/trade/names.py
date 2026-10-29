"""中文物品名 → 英文名（来自用户的游戏汉化包，和挖矿助手的中英对照表同源）

UEX 只认英文名；游戏是中文界面，截图识别和手动搜索得到的是中文名，这里负责换成英文再去查。
"""
import json
import re
from functools import lru_cache
from pathlib import Path

CJK = re.compile(r'[一-鿿]')
_PAREN = re.compile(r'\s*[（(][^）)]*[）)]\s*')


@lru_cache(maxsize=1)
def table():
    from ..core.paths import DATA
    path = DATA / 'zh_names.json'
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    known = _known_names()
    out = {zh: en for zh, en in raw.items() if not _junk(en, known)}
    try:                                   # 汉化包只写了中文名的物品（勋章、计算板…）：解包补的英文名（2026-10-27）
        for zh, en in json.loads((DATA / 'zh_only_names.json').read_text(encoding='utf-8')).items():
            if not _junk(en, known) and len(_norm_zh(zh)) >= 3:
                out.setdefault(zh, en)
    except (OSError, ValueError):
        pass
    return out


# 汉化包里物品「简称」带出来的假英文名（1.6.41）：简称后面跟的是尺寸、型号代码，不是英文名，
# 比如「视差步枪HD」拆成 视差步枪 → HD、「制空-3 Omnisky-3 S1」→ S1、导弹简称「[红外]灾星 XII-IR」、「刀轴Arbor S00」。
# 以前的对照表里有两百多条这种，「视差步枪」搜出来是 HD。真有这个名字的物品（锡 Tin、墨水 INK）照留。
_CODE = re.compile(r'(?:[GIVX]+-[A-Z]{1,3}|\d+\s?SCU|.+\sS\d{1,2})')


def _junk(en, known):
    if _fold_en(en) in known:
        return False
    return len(_fold_en(en)) <= 3 or bool(_CODE.fullmatch(en.strip()))


def _known_names():
    """商店和掉落数据里所有物品的英文名（折叠过的）；数据还没下载就是空的"""
    out = set()
    try:
        from ..crafting import shops
        out |= {_fold_en(v[0]) for v in shops.load(auto_update=False).get('items', {}).values()}
    except Exception:
        pass
    try:
        from ..crafting import loot
        out |= {_fold_en(r[1]) for r in (loot.load_index(False) or {}).get('rows') or []}
    except Exception:
        pass
    return out


def has_chinese(text: str) -> bool:
    return bool(CJK.search(text or ''))


def _norm(text):
    return re.sub(r'\s+', '', text or '')


def to_english(query: str, limit: int = 8) -> list[str]:
    """中文名对应的英文名：先精确，再去掉括号备注（如 "科力晶（单个矿块）"），最后按包含关系模糊找"""
    if not has_chinese(query):
        return []
    t = table()
    q = _norm(query)
    norm = {_norm(k): v for k, v in t.items()}
    for key in (q, _norm(_PAREN.sub('', query))):
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

def _fold_en(text):
    return re.sub(r'[^a-z0-9]', '', (text or '').lower())


def _norm_zh(text):
    return (text or '').replace('(', '（').replace(')', '）').replace(' ', '').replace('　', '').strip()


@lru_cache(maxsize=1)
def _index():
    """({规整的中文名: (中文, 英文)}, {折叠的英文名: (中文, 英文)})"""
    zh_map, en_map = {}, {}
    for zh, en in table().items():
        zh_map.setdefault(_norm_zh(zh), (zh, en))
        en_map.setdefault(_fold_en(en), (zh, en))
    return zh_map, en_map


_BILINGUAL = re.compile(r'^(.*[一-鿿）)])\s*([A-Za-z][A-Za-z0-9 \-\'".()/&]*)$')


def split_bilingual(text):
    """「塔兰导电石Taranite」「铁 Iron」这种中英连在一起的 → (中文, 英文)；不是这种的返回 (原文, "")"""
    m = _BILINGUAL.match((text or '').strip())
    return (m.group(1).strip(), m.group(2).strip()) if m else ((text or '').strip(), '')


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
    m = by_en.get((en or '').strip().lower())
    if not m and zh and not en:
        m = mineral_en(zh, fuzzy=False, ship_only=False) if len(_norm_zh(zh)) <= 6 else None
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
    hits = {en for k, en in _tables(False)[0].items()
            if len(k) == len(z) and sum(a != b for a, b in zip(k, z)) == 1}
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
        if abs(len(k) - len(target)) > max(2, len(target) // 3) or len(tset & set(k)) < len(tset) * 0.5:
            continue
        scored.append((difflib.SequenceMatcher(None, k, target).ratio(), k))
    scored.sort(reverse=True)
    if not scored or scored[0][0] < floor:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.04 and scored[0][0] < 0.95:
        return None                                   # 两个一样像：不猜
    return scored[0][1]


def canonical(zh='', en=''):
    """OCR 认出的名字 → 汉化包里的标准 (中文名, 英文名)；对不上返回 None。
    顺序：拆开中英连写 → 矿物（精确）→ 英文名精确 → 中文名精确 → 英文名近似 → 矿名错一个字 → 中文名近似（错一两个字、丢一个字）"""
    zh, en = (zh or '').strip(), (en or '').strip()
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


def zh_for(en):
    """英文名 → 汉化包里的中文名（只认精确的，忽略大小写、空格、标点）"""
    hit = _mineral('', en) or _index()[1].get(_fold_en(en))
    return hit[0] if hit else None


def suggest(query, limit=8):
    """手动入库的联想：中文 / 英文 / 名字的一部分 / 错一两个字都能找到。返回 [(中文, 英文)]，最像的在前"""
    import difflib
    q = (query or '').strip()
    if not q:
        return []
    zq, eq = _norm_zh(q), _fold_en(q)
    scored = {}
    for zh, en in table().items():
        z, e = _norm_zh(zh), _fold_en(en)
        if has_chinese(q):
            if not (set(zq) & set(z)):
                continue
            s = 1.0 if z == zq else 0.9 if z.startswith(zq) else 0.8 if zq in z else \
                difflib.SequenceMatcher(None, z, zq).ratio() * 0.75
        else:
            if not eq or eq[0] not in e:
                continue
            s = 1.0 if e == eq else 0.9 if e.startswith(eq) else 0.8 if eq in e else \
                difflib.SequenceMatcher(None, e, eq).ratio() * 0.75
        if s >= 0.5:
            scored[(zh, en)] = max(s - len(z) * 0.002, scored.get((zh, en), 0))     # 一样像时短的（更通用的）在前
    return [k for k, _ in sorted(scored.items(), key=lambda kv: -kv[1])[:limit]]
