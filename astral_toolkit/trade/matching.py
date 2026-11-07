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


def name_score(name, target):
    """折叠后的物品名 name 和要找的名字 target 有多像：一样 1.0；name 以 target 开头且 target 至少 8 个字 0.95；
    别的按 difflib 比。≥ 0.85 算同一件（F8 配物品、盘点认同一件东西用同一把尺子）"""
    import difflib

    if name == target:
        return 1.0
    if name.startswith(target) and len(target) >= 8:
        return 0.95
    return difflib.SequenceMatcher(None, name, target).ratio()


def names_alike(name, target):
    """两个英文名像到算同一件东西（折叠后 name_score ≥ 0.85）"""
    return bool(name and target) and name_score(_fold(name), _fold(target)) >= 0.85


def match_tooltip(t, zh, en, online=True):
    """说明框里的名字 → 物品。顺序：中文名查汉化包对照表 → 英文名（容忍 OCR 丢空格、II/ll、截断）。
    先查本机目录（以前查到过的物品、记下的中文名），查到就不联网；本机没有才去 UEX/SCM 搜（每次搜要零点几秒到几秒）。
    返回 (物品或 None, 候选列表)"""
    if zh and hasattr(t.catalog, "by_alias"):
        hit = t.catalog.by_alias(zh)
        if hit:
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
