"""物品查询搜索（1.6.41；目录迁移 Q1 从 crafting/itemsearch.py 搬来）：商店、掉落、汉化包三份物品名合成一份索引，中英文都能搜

以前的毛病（2026-10-23 用户：视差步枪搜不到）：
- 中文先用对照表换成英文再搜，对照表里有「视差步枪 → HD」这种假的（物品简称后面带的型号代码），搜出来不对
- 中文只认连着的一段，「视差步枪」对不上「视差 能量突击步枪」
- 商店搜到 5 个以上就不看掉落数据，只在掉落数据里的东西（很多护甲、衣服）搜不到
- 汉化包里有、商店和掉落数据里都没有的六百多件（任务奖励、活动、涂装……）根本搜不到

现在：
- 中文直接对所有物品的中文名搜，字按顺序出现就算（中间可以隔着别的字）：视差步枪 → 视差 能量突击步枪
- 排序：名字完全一样 > 最后一个字对得上名字结尾（中文名的「是什么」在最后：步枪、头盔）> 连着的一段 > 按顺序出现；
  同一档里基础款排在涂装 / 限定版（名字带引号的）前面，有商店或掉落数据的排在前面，短的在前
- 英文：完全一样 > 开头对得上 > 包含 > 每个词都有（顺序不限）

纯匹配、排序、建索引在 catalog/search.py；本文件管 gamedata 取数、按资料版本缓存一份索引、建索引的锁。
全应用共享这一份缓存；库建不出来时给空索引、不进缓存（下次再试）。
窗口打开后在后台先把索引建好（预热，第一次约 1–3 秒）：由 bootstrap 起线程调 build_index，本模块 import 时不起线程。
"""

import threading

from ...catalog import search as _catalog_search
from ...gamedata._cache import VersionCache

_cache = VersionCache()  # 索引按库的内容版本缓存一份（全应用共享）
_build_lock = threading.Lock()  # 启动时后台先建索引；玩家这时搜索就等它建完，不重复建


def build_index():
    """当前资料版本的索引（缓存里没有就建）：预热和每次搜索都走这里，同一时间只建一份"""
    with _build_lock:
        return _build_locked()


def _build_locked():
    """从游戏数据层的物品目录建内存索引（合并规则在 gamedata/_import.import_items，和以前这里的一样）；
    缓存键是库的内容版本：五份源（商店、掉落、汉化、旧写法、wiki）哪份变了都会重建"""
    from ... import gamedata

    try:
        gamedata.ensure()
        with gamedata.snapshot() as snap:
            return _cache.get(snap, _index_from)
    except gamedata.GamedataError:
        return (
            _catalog_search.empty_index()
        )  # 库建不出来：和以前没有数据文件一样，搜不到东西，不报错（不缓存，下次再试）


def _index_from(snap):
    """从一个快照取好物品行，交给 catalog.search.index_from 建索引（VersionCache 按 snap.data_version 缓存）"""
    from ...gamedata import items as gd_items

    items = gd_items.all(snap)
    zks_of = gd_items.zh_keys_of_all(snap)
    names = gd_items.names_by_kind(("zh_loot", "aka"), snap)
    shop_of = gd_items.first_source_ids("uex", snap)
    return _catalog_search.index_from(items, zks_of, names, shop_of)


def find(query, limit=30):
    """[{en, zh, shop(商店 id 或 None), cat, loot(掉落数据里有), loc(只有汉化包里有名字), variant}]，最像的在前"""
    if not (query or "").strip():
        return []
    return _catalog_search.find(build_index(), query, limit)


def lookup(en):
    """按英文名（忽略大小写、空格、标点）找索引里的这一件；没有返回 None"""
    return _catalog_search.lookup(build_index(), en)
