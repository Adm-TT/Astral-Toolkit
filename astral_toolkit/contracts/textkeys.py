"""名字的比较键。

这些函数把物品名折成比较用的键；有的结果存进了 gamedata 的列
（掉落 norm_en / norm_zh、wiki 类名 norm_n、维科洛材料 norm_n、制造蓝图 norm_n / norm_z / search_n / search_z、
物品名的键、名字对照表），
改任何一条都要升 gamedata/_schema.IMPORTER_VERSION，否则库里存的键和查询时算的键对不上。
"""

import re
import unicodedata


def fold_en(text):
    """名字比较键：小写、只留 a-z0-9；trade.names、trade.gamekey、crafting.acquire 和 gamedata 物品名 / 名字对照表在用。"""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def fold_en_loose(s):
    """名字比较键：小写、l 当 i、只留 a-z0-9；catalog.shops、crafting.shops 和 gamedata 商店在用（en_key 也走它）。"""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower().replace("l", "i"))


def fold_mixed_loose(s):
    """名字比较键：小写、l 当 i、只留 a-z0-9 和汉字；crafting.loot、crafting.wikelo 和 gamedata 掉落 / wiki / 维科洛在用。"""
    return re.sub(r"[^a-z0-9一-鿿]", "", (s or "").lower().replace("l", "i"))


def fold_mixed(s):
    """名字比较键：小写、只留 a-z0-9 和汉字（l 不当 i）；F8「可制造：有蓝图」比蓝图名用"""
    return re.sub(r"[^a-z0-9一-鿿]", "", (s or "").lower())


def zh_key(s):
    """中文名比较键：全角转半角（NFKC）、小写、去掉非字母数字和标点；catalog.search、gamedata 物品索引在用。"""
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", s or "").lower())


def en_key(s):
    """英文名比较键：全角转半角（NFKC）后按 fold_en_loose 折叠；catalog.search、gamedata 物品名和建库在用。"""
    return fold_en_loose(unicodedata.normalize("NFKC", s or ""))


def norm_zh(text):
    """中文名比较键：半角括号换全角、去半角 / 全角空格、strip；trade.names、gamedata 名字对照表在用。"""
    return (
        (text or "")
        .replace("(", "（")
        .replace(")", "）")
        .replace(" ", "")
        .replace("　", "")
        .strip()
    )


def blueprint_norm(s):
    """制造蓝图 for_item 的比较键：小写、去掉所有非字母数字（汉字留着）；gamedata blueprints.norm_n / norm_z 和
    crafting.for_item 都用它（原 crafting._fold_name）。"""
    return re.sub(r"[\W_]+", "", (s or "").lower())


def blueprint_search_norm(s):
    """制造蓝图 search 的比较键：小写、去半角空格（和 blueprint_norm 不是一个规则，各存各的）；
    gamedata blueprints.search_n / search_z 和 crafting.search 都用它（原 crafting._search_norm）。"""
    return (s or "").lower().replace(" ", "")


# 汉化包里物品「简称」带出来的假英文名（1.6.41）：简称后面跟的是尺寸、型号代码，不是英文名，
# 比如「视差步枪HD」拆成 视差步枪 → HD、「制空-3 Omnisky-3 S1」→ S1、导弹简称「[红外]灾星 XII-IR」、「刀轴Arbor S00」。
# 以前的对照表里有两百多条这种，「视差步枪」搜出来是 HD。真有这个名字的物品（锡 Tin、墨水 INK）照留。
# CODE_NAME / junk_en 的结果存在 gamedata 名字对照表里：改这里要升 gamedata/_schema.IMPORTER_VERSION
CODE_NAME = re.compile(r"(?:[GIVX]+-[A-Z]{1,3}|\d+\s?SCU|.+\sS\d{1,2})")


def junk_en(en, known):
    """汉化包简称带出来的假英文名（尺寸、型号代码），known 里有的真名照留；gamedata 名字对照表建库在用"""
    if fold_en(en) in known:
        return False
    return len(fold_en(en)) <= 3 or bool(CODE_NAME.fullmatch(en.strip()))
