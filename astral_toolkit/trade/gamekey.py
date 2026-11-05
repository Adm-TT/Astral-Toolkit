"""物品的游戏内唯一编号（天枢 1.6.55 起，给交易平台用：不同玩家、不同来源记的同一件东西靠它对上）

库存里的物品编号是查价来源给的（uex:4741、scm:43475、local:…），同一件东西换个来源就不一样。
这里按英文名对到物品查询（star-citizen.wiki 的游戏物品清单）的物品，取它的游戏类名（class name）和游戏实体 uuid
（uuid 从掉落数据的索引里按类名取，同样来自游戏文件）。汉化包里写错 / 过时的英文名按 name_aliases.json 先改成正名。
对不上的返回 None，不硬猜。数据从游戏数据层读（gamedata.names 的原样有序行），索引按内容版本缓存。
"""

from ..contracts.textkeys import fold_en as _fold

# 按游戏数据内容版本缓存一份索引（公共工具 gamedata/_cache.VersionCache）。本模块顶层不 import gamedata，第一次用时才建
_caches: dict = {}


def _cache():
    c = _caches.get("idx")
    if c is None:
        from ..gamedata._cache import VersionCache

        c = _caches.setdefault("idx", VersionCache())
    return c


def _build(s):
    from ..gamedata import names

    by_name = {}
    for w in names.wiki_classes(s):  # 同折叠名首个 wiki 行胜出；涂装等噪声物品也在
        by_name.setdefault(_fold(w.n), w)
    uuid = {}
    for cls, u in names.class_uuids(s):  # 同类名首个掉落行胜出
        uuid.setdefault((cls or "").lower(), u)
    alias = {}
    for old, new in names.alias_pairs(s):  # 后写覆盖，不过滤
        alias[_fold(old)] = new
    return {"by_name": by_name, "uuid": uuid, "alias": alias}


def _index():
    """{by_name: {折叠英文名: WikiClass}, uuid: {类名小写: uuid}, alias: {折叠旧写法: 正名}}；库不可用时抛 GamedataError"""
    from .. import gamedata

    gamedata.ensure()
    with gamedata.snapshot() as s:
        return _cache().get(s, _build)


def resolve(name_en):
    """英文名 → (游戏类名, 游戏 uuid 或 '')；对不上返回 None（库不可用时也是 None，不缓存）"""
    from ..gamedata import GamedataError

    try:
        idx = _index()
    except GamedataError:
        return None
    k = _fold(name_en)
    if not k:
        return None
    w = idx["by_name"].get(k) or idx["by_name"].get(_fold(idx["alias"].get(k, "")))
    if not w or not w.cls:
        return None
    cls = w.cls.lower()
    u = idx["uuid"].get(cls) or next(
        (idx["uuid"][a.lower()] for a in w.alt if a.lower() in idx["uuid"]),
        "",
    )
    return cls, u
