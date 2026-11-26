"""矿物品质档位（4.8 起）：每种矿只有固定的 7 档品质（社区叫法 F 最低 … S 最高，不是官方叫法），另有少见的 1000 完美。

档位表本身（数据来源、和游戏数据的核对记录）在 contracts/ore_tiers.py（2026-11-26 挪过去，制造倒推品质也用）；
这里是采矿用的读法：tiers 列出档位名、tier_of 认出一个品质是第几档。
4.8 之前挖的矿品质是 245~1000 之间的随机数，所以对不上档位的品质照常可用，只是标不出第几档。
"""

# 档位表 2026-11-26 挪到 contracts/ore_tiers（制造倒推品质也用，不再引用采矿）。
# 采矿内部（parse、扫描结果）和别处照旧从这里拿，长期保留这些名字
from ..contracts.ore_tiers import (
    LETTERS as LETTERS,
    PERFECT as PERFECT,
    TIER_VALUES as TIER_VALUES,
    TIERS as TIERS,
    _key as _key,
    tier_values as tier_values,
)


def tiers(material):
    """[(档位名, 品质)]，从低到高，最后是「完美」1000；没有这种矿的数据返回 []"""
    k = _key(material)
    if not k:
        return []
    return [(f"{l} 档", q) for l, q in zip(LETTERS, TIERS[k]) if q] + [  # noqa: E741
        ("完美", PERFECT)
    ]  # noqa: E741


def tier_of(material, q):
    """品质正好是这种矿的某一档：返回 (档位字母或「完美」, 第几档 1~7, 共几档)；对不上返回 None"""
    try:
        q = int(round(float(q)))
    except (TypeError, ValueError):
        return None
    if q == PERFECT:
        return ("完美", 8, 7)
    k = _key(material)
    if not k:
        return None
    for i, (l, v) in enumerate(zip(LETTERS, TIERS[k]), 1):  # noqa: E741
        if v == q:
            return (l, i, len(LETTERS))
    return None
