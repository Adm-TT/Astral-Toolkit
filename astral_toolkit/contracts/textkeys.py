"""名字的比较键。

这些函数把物品名折成比较用的键；有的结果存进了 gamedata 的列
（掉落 norm_en / norm_zh、wiki 类名 norm_n、维科洛材料 norm_n、物品名的键、名字对照表），
改任何一条都要升 gamedata/_schema.IMPORTER_VERSION，否则库里存的键和查询时算的键对不上。
"""

import re
import unicodedata


def fold_en(text):
    """名字比较键：小写、只留 a-z0-9；trade.names / gamekey 和 gamedata 物品名、名字对照表在用。"""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def fold_en_loose(s):
    """名字比较键：小写、l 当 i、只留 a-z0-9；crafting.shops、itemsearch.en_key 和 gamedata 商店在用。"""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower().replace("l", "i"))


def fold_mixed_loose(s):
    """名字比较键：小写、l 当 i、只留 a-z0-9 和汉字；crafting.loot / wikelo 和 gamedata 掉落 / wiki / 维科洛在用。"""
    return re.sub(r"[^a-z0-9一-鿿]", "", (s or "").lower().replace("l", "i"))


def zh_key(s):
    """中文名比较键：全角转半角（NFKC）、小写、去掉非字母数字和标点；crafting.itemsearch.zh_key 和 gamedata 物品索引在用。"""
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", s or "").lower())


def en_key(s):
    """英文名比较键：全角转半角（NFKC）后按 fold_en_loose 折叠；crafting.itemsearch.en_key、gamedata 物品名和建库在用。"""
    return fold_en_loose(unicodedata.normalize("NFKC", s or ""))


def norm_zh(text):
    """中文名比较键：半角括号换全角、去半角 / 全角空格、strip；trade.names._norm_zh 和 gamedata 名字对照表在用。"""
    return (
        (text or "")
        .replace("(", "（")
        .replace(")", "）")
        .replace(" ", "")
        .replace("　", "")
        .strip()
    )
