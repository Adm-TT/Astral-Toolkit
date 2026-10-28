"""物品的游戏内唯一编号（天枢 1.6.55 起，给交易平台用：不同玩家、不同来源记的同一件东西靠它对上）

库存里的物品编号是查价来源给的（uex:4741、scm:43475、local:…），同一件东西换个来源就不一样。
这里按英文名对到物品查询（star-citizen.wiki 游戏解包清单）的物品，取它的游戏类名（class name）和游戏实体 uuid
（uuid 从掉落数据的索引里按类名取，同样来自游戏文件）。汉化包里写错 / 过时的英文名按 name_aliases.json 先改成正名。
对不上的返回 None，不硬猜。
"""
import json
import re

_IDX = {"key": None, "by_name": {}, "uuid": {}, "alias": {}}


def _fold(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _index():
    from ..itemsearch import wiki_items
    from ..paths import DATA
    rows = wiki_items()
    if _IDX["key"] is rows and _IDX["by_name"]:
        return _IDX
    by_name = {}
    for w in rows:
        by_name.setdefault(_fold(w.get("n")), w)
    uuid = {}
    try:
        for u, en, cls, *_ in json.loads((DATA / "loot_index.json").read_text(encoding="utf-8")).get("rows") or []:
            uuid.setdefault((cls or "").lower(), u)
    except (OSError, ValueError):
        pass
    alias = {}
    try:
        for old, new in (json.loads((DATA / "name_aliases.json").read_text(encoding="utf-8")) or {}).items():
            alias[_fold(old)] = new
    except (OSError, ValueError):
        pass
    _IDX.update(key=rows, by_name=by_name, uuid=uuid, alias=alias)
    return _IDX


def resolve(name_en):
    """英文名 → (游戏类名, 游戏 uuid 或 '')；对不上返回 None"""
    idx = _index()
    k = _fold(name_en)
    if not k:
        return None
    w = idx["by_name"].get(k) or idx["by_name"].get(_fold(idx["alias"].get(k, "")))
    if not w or not w.get("cls"):
        return None
    cls = w["cls"].lower()
    u = idx["uuid"].get(cls) or next((idx["uuid"][a.lower()] for a in w.get("alt") or [] if a.lower() in idx["uuid"]), "")
    return cls, u
