"""矿物品质档位（4.8 起）：每种矿只有固定的 7 档品质（社区叫法 F 最低 … S 最高，不是官方叫法），另有少见的 1000 完美。

数据：starcitizen.tools「Ore quality」页（矿石为实测，矿物为 4.9 游戏数据；2026-10-23 抄录）。
4.8 之前挖的矿品质是 245~1000 之间的随机数，所以对不上档位的品质照常可用，只是标不出第几档。
制造那边也用这张表：做出来的东西说明框里只有属性加成，按蓝图曲线倒推每个材料槽用的品质时只在这些值里找
（用户那把视差「血红」：钨 858、金 916、科力晶 959，和 +17.50% / ±28.64% 一分不差）。
以前 quality_tiers.py 另存了一份同样的表（列表、末尾带 1000），2026-11-06 合进这里（CL-C3）。
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
