"""成品的基础数值（item_stats.json，来自 star-citizen.wiki 整理的游戏数据，tools/build_item_stats.py 生成；读取走游戏数据层 gamedata.itemstats）

制造页的「属性统计」：基础值 → 按材料品质强化后的值 → 变化。按 uuid 和 scmdb 蓝图对上（bp["u"]）。
property_key 是 scmdb 蓝图里各槽「品质影响」用的键（health_maxhealth、weapon_damage …），这里把它对到 wiki 数据的字段。
数据里没有的属性返回 None：页面上只显示倍率，不显示绝对值。
dev 拆分②（2026-11-09）：取值规则（PROPS、各属性怎么取、标签挑哪几个字段）搬到 catalog/itemstats.py；这里只取数据
（item / version）再调规则，base_value / tags 名字照旧（制造页和测试按它们用、打桩）。
"""

from ..catalog import itemstats as _rules


def item(uuid):
    """一件成品的数据（与 item_stats.json 的 items[uuid] 同形）；没有或库不可用 → None"""
    from .. import gamedata

    try:
        return gamedata.itemstats.item(uuid or "")
    except gamedata.GamedataError:
        return None


def version():
    """属性数据的版本；没有或库不可用 → ''"""
    from .. import gamedata

    try:
        return gamedata.itemstats.version()
    except gamedata.GamedataError:
        return ""


def base_value(uuid, prop_key):
    """成品这项属性的基础值（数据里没有 → None）。返回 (数值, 单位)"""
    return _rules.base_value_of(item(uuid), prop_key)


def tags(uuid):
    """分类标签 {size, grade, cls, mfr, type, sub, cn}，没有数据返回 {}（catalog/itemstats.tags_of）"""
    return _rules.tags_of(item(uuid))
