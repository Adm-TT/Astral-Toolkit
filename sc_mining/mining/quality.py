"""矿物品质档位（4.8 起）：每种矿只有固定的 7 档品质（社区叫法 F 最低 … S 最高，不是官方叫法），另有少见的 1000 完美。

数据：starcitizen.tools「Ore quality」页（矿石为实测，矿物为 4.9 拆包；2026-10-23 抄录）。
4.8 之前挖的矿品质是 245~1000 之间的随机数，所以对不上档位的品质照常可用，只是标不出第几档。
"""
LETTERS = ("F", "E", "D", "C", "B", "A", "S")
PERFECT = 1000

# 矿物英文名（和 SCMiner / 扫描结果一致）→ F, E, D, C, B, A, S 七档；None = 没有这一档的数据
# 2026-10-27 和解包（crafting/qualityquantization）逐个核对：刚玉、金、石英、科力晶、加纳石 5 种以前抄错/过时，已改成游戏数据
TIERS = {
    # 矿石（船挖）
    "Agricium": (346, 588, 667, 796, 852, 943, 971),
    "Aluminum": (318, 511, 614, 783, 896, 919, 953),
    "Aslarite": (287, 575, 602, 741, 854, 927, 963),
    "Beryl": (324, 547, 677, 717, 860, 937, 955),
    "Bexalite": (302, 597, 632, 756, 875, 941, 959),
    "Borase": (359, 584, 676, 743, 892, 903, 976),
    "Copper": (359, 593, 652, 742, 855, 917, 958),
    "Corundum": (309, 504, 665, 793, 886, 904, 971),
    "Gold": (264, 553, 644, 786, 864, 916, 959),
    "Hephaestanite": (330, 572, 692, 758, 896, 916, 975),
    "Iron": (325, 521, 664, 710, 874, 907, 970),
    "Laranite": (298, 510, 698, 707, 858, 910, 975),
    "Lindinium": (305, 585, 618, 729, 853, 930, 954),
    "Ouratite": (310, 523, 647, 779, 860, 912, 960),
    "Pressurized Ice": (322, 561, 659, 714, 873, 922, 966),
    "Quantainium": (344, 514, 669, 762, 852, 901, 974),
    "Quartz": (330, 522, 641, 710, 899, 914, 969),
    "Riccite": (325, 525, 671, 743, 870, 942, 965),
    "Saldynium": (301, 575, 674, 757, 861, 938, 955),
    "Savrilium": (322, 580, 636, 776, 878, 905, 967),
    "Silicon": (310, 510, 672, 782, 889, 926, 968),
    "Stileron": (330, 517, 681, 747, 874, 947, 972),
    "Taranite": (310, 525, 646, 718, 853, 925, 957),
    "Tin": (340, 537, 664, 704, 880, 940, 964),
    "Titanium": (295, 516, 622, 784, 866, 916, 959),
    "Torite": (262, 528, 661, 785, 873, 944, 951),
    "Tungsten": (363, 530, 662, 787, 858, 902, 964),
    # 矿物（手挖 / 地面车挖，4.9 拆包）
    "Aphorite": (348, 523, 686, 717, 861, 916, 975),
    "Beradom": (287, 578, 656, 723, 881, 937, 969),
    "Carinite": (273, 554, 647, 716, 880, 909, 959),
    "Dolivine": (304, 577, 621, 743, 886, 901, 957),
    "Feynmaline": (371, 561, 682, 769, 880, 906, 965),
    "Glacosite": (360, 567, 678, 724, 857, 916, 972),
    "Hadanite": (274, 526, 665, 762, 867, 916, 959),
    "Janalite": (269, 596, 632, 732, 898, 926, 964),
    "Sadaryx": (258, 510, 688, 797, 865, 940, 971),
}
_LOWER = {k.lower(): k for k in TIERS}


def _key(material):
    name = str(material or "").strip()
    if name in TIERS:
        return name
    low = name.lower()
    for suffix in (" (ore)", " (raw)", " ore", " raw"):
        if low.endswith(suffix):
            low = low[: -len(suffix)]
    low = {"ice": "pressurized ice"}.get(low, low)     # 制造表里叫 Ice（老大审查 2026-10-28）
    return _LOWER.get(low)


def tiers(material):
    """[(档位名, 品质)]，从低到高，最后是「完美」1000；没有这种矿的数据返回 []"""
    k = _key(material)
    if not k:
        return []
    return [(f"{l} 档", q) for l, q in zip(LETTERS, TIERS[k]) if q] + [("完美", PERFECT)]


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
    for i, (l, v) in enumerate(zip(LETTERS, TIERS[k]), 1):
        if v == q:
            return (l, i, len(LETTERS))
    return None
