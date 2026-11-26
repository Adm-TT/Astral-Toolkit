"""蓝图分类、护甲部位和分面统计的纯规则。

只吃传进来的蓝图和键函数，不读库、不读文件、不读汉化包。
"""

import re
from collections import Counter

from .labels import GEAR_ZH, PART_ZH

_PART_RE = re.compile(r"\b(Helmet|Core|Arms|Legs|Backpack|Undersuit)\b")


def category(bp):
    return f"{bp['g']}/{bp['t'] or ''}"


def category_zh(bp):
    return GEAR_ZH.get((bp["g"], bp["t"]), bp["t"] or bp["g"])


def part_of(bp):
    """护甲部位（头盔/胸甲/…）；不是分部位的护甲返回「其他」"""
    if bp["t"] != "armour":
        return ""
    m = _PART_RE.search(bp["n"])
    return PART_ZH[m.group(1)] if m else "其他"


def facet(rows, key):
    c = Counter(key(b) for b in rows)
    return [
        {"key": k, "count": n}
        for k, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))
        if k
    ]
