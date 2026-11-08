"""说明框里的名字对上物品：名字折叠、像不像、先查本机目录再联网搜（F8、物品查询用；F 段 B1 从 trade/console 搬来）"""

import re as _re

from ..contracts.textkeys import fold_en as _fold_en
from .names import to_english


def _fold(text):
    """比较名字用：忽略大小写、空格、符号；OCR 常把 II 认成 ll，统一成 i。
    contracts.textkeys.fold_en 不动（那边查表要分清 l 和 i），只在这里比较 OCR 认出的名字时放宽"""
    return _fold_en(text).replace("l", "i")


def _similar(a, b):
    import difflib

    if not a or not b:
        return False
    return (
        a.startswith(b[:6])
        or b.startswith(a[:6])
        or difflib.SequenceMatcher(None, a, b).ratio() >= 0.6
    )


_SUFFIX = _re.compile(r"\s*[（(][^（）()]*[)）]\s*$")


def market_base(name):
    """市场上的名字去掉末尾括号里那截：矿在市场上常叫「Taranite (Raw)」「铁（原矿）」。
    console.ore_item 认「是不是矿」、alias_ok 认「是不是同一件」都先这样去掉"""
    return _SUFFIX.sub("", name or "").strip()


def _extends(name, en):
    """name 是不是在 en 后面多接了一截：折叠后以 en 开头、多出来至少 3 个字（变体、配件、颜色款都这么起名：
    Demeco LMG Battery (100 cap)、Arclight Pistol Gold）；只多一两个字母的当错字"""
    a, b = _fold(name), _fold(en)
    return bool(b) and a.startswith(b) and len(a) - len(b) >= 3


def alias_ok(item, zh, en):
    """目录里的这件物品和说明框认出的 (中文, 英文) 算不算同一件：F8 只在算同一件时把中文名记成它的别名，查本机目录时
    按中文别名找到的也要算同一件才用；盘点按中文名带出来的条目也要算同一件才并账。依次看：
    1. 英文名一样（_fold 后）→ 算；
    2. 是矿的市场名：去掉「(Raw)」「（原矿）」这种后缀（market_base）后和认出的一样、又是矿名（names._mineral：船挖、
       地面、手采的都算）→ 算。AT 认矿只认矿名，说明框里原矿、精炼的都认成同一种矿；名字折叠后 8 个字以上的矿
       （Quantainium、Taranite、Laranite…）F8 靠名字前缀档配到市场上带 (Raw) 的那条，这里跟着认，F8、盘点、库存页
       的说法才一致（审查 2026-11-08 第二轮）。名字短的（Gold、Iron、Copper…）F8 配不上 (Raw)、不记中文名，盘点也
       找不到那条（记了待做）。console.ore_item 管的是「按 SCU 还是按个记」，用 inspector._is_mineral（只认船挖矿），
       两边管的事不一样；
    3. 它自己的英文名在汉化包里有中文名 → 汉化包说了算：就是这个中文名才算，别的中文名不算；
    4. 汉化包里没有它（市场上的叫法和游戏里不一样）→ 在认出的英文名后面多接了一截的不算（_extends），别的照旧算
       （错一两个字母、写法不同的同一件）。
    以前模糊、前缀配上就记：前缀那档会把本体配成变体（Demeco LMG 配成 Demeco LMG Battery (100 cap)），中文名一记，
    以后盘点会把变体的库存并进本体、库存页显示成本体的名字（待做 61、125、126，老大 2026-11-08 定直接修）"""
    from .names import _mineral, zh_for

    name = getattr(item, "name", "") or ""
    if en and _fold(name) == _fold(en):
        return True
    base = market_base(name)
    if en and base != name and _fold(base) == _fold(en) and _mineral("", base):
        return True
    own = zh_for(name)
    if own is not None:
        return bool(zh) and own == zh
    return not _extends(name, en)


def name_score(name, target):
    """折叠后的物品名 name 和要找的名字 target 有多像：一样 1.0；name 以 target 开头且 target 至少 8 个字 0.95；
    别的按 difflib 比。≥ 0.85 算配上（F8 配物品用；盘点不拿它并条目——前缀那档会把变体当成本体，审查 2026-11-08 第三轮）"""
    import difflib

    if name == target:
        return 1.0
    if name.startswith(target) and len(target) >= 8:
        return 0.95
    return difflib.SequenceMatcher(None, name, target).ratio()


def match_tooltip(t, zh, en, online=True):
    """说明框里的名字 → 物品。顺序：中文名查汉化包对照表 → 英文名（容忍 OCR 丢空格、II/ll、截断）。
    先查本机目录（以前查到过的物品、记下的中文名），查到就不联网；本机没有才去 UEX/SCM 搜（每次搜要零点几秒到几秒）。
    返回 (物品或 None, 候选列表)"""
    if zh and hasattr(t.catalog, "by_alias"):
        hit = t.catalog.by_alias(zh)
        if hit and alias_ok(
            hit, zh, en
        ):  # 以前模糊配上时记错的别名（记到了变体上）不用，接着按名字找
            return hit, [hit]
    want = []
    if zh:
        want += to_english(zh)[:1] if len(to_english(zh)) == 1 else []
    if en:
        want.append(en)
    best, local = _match_names(t.catalog.search, want)
    if best is not None or not online:
        return best, local
    best, remote = _match_names(lambda q: t.lookup(q)[0], want)
    merged = {i.id: i for i in local + remote}
    return best, list(merged.values())


def _match_names(search, want):
    candidates = {}
    for name in want:
        target = _fold(name)
        # OCR 常把空格丢掉（CQ7Rifle），补回空格再搜
        spaced = _re.sub(
            r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Za-z])(?=")|(?<=")(?=[A-Za-z])', " ", name
        )
        words = _re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}", spaced)
        for q in dict.fromkeys([name, spaced] + words[:1]):
            items = search(q)
            # 搜不到时有的来源会返回一大串不相干的物品，只留名字像的
            items = [i for i in items if _similar(_fold(i.name), target)]
            for i in items:
                candidates.setdefault(i.id, i)
            if items:
                break
        scored = []
        for i in candidates.values():
            score = name_score(_fold(i.name), target)
            scored.append((score, not i.id.startswith("scm:"), i))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        if scored and scored[0][0] >= 0.85:
            return scored[0][2], [x[2] for x in scored]
    return None, list(candidates.values())
