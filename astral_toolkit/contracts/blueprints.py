"""制造蓝图的编号规则（纯函数）。

编号在 gamedata 导入时算好存进 blueprints.bp_key，crafting 按编号查蓝图，目标清单里存的也是它；
改规则要升 gamedata/_schema.IMPORTER_VERSION，库里的编号才会按新规则重算。
"""

from collections import Counter


def assign_keys(bps):
    """每份蓝图的唯一编号：名字不重复就用名字；
    有十几个名字对应两份不同配方（比如 Main Powerplant），这些用「名字#1」「名字#2」区分（二审 2026-10-23 发现：只按名字会点开别的配方）。
    返回 (keys: {id(bp): 编号}, index: {编号: bp}, total: Counter(名字))（原 crafting.assign_keys）"""
    total = Counter(b["n"] for b in bps)
    seen, keys, index = Counter(), {}, {}
    for b in bps:
        seen[b["n"]] += 1
        k = b["n"] if total[b["n"]] == 1 else f"{b['n']}#{seen[b['n']]}"
        keys[id(b)] = k
        index[k] = b
    return keys, index, total
