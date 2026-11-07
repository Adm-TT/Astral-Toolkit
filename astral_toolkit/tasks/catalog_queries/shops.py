"""物品在哪买（Item Finder）的查询（目录迁移 Q2 从 crafting/shops.py 搬来）：游戏里哪些商店卖这件东西、多少钱，哪些商店收

数据来自 UEX（玩家众包的商店价格）：「更新数据」时由 update/shops.py 拉一份写 shops.json、导进游戏数据库；
这里只查游戏数据库（gamedata/shops），不读文件、不联网、不起线程。
按名字找、按价格排、按远近取前几、同系列候选这些纯规则在 catalog/shops.py；商店位置 → 星图点（shop_point）在 navigation/position.py。
"""

from ...catalog import shops as _catalog
from ...contracts.textkeys import fold_en_loose as _fold


def _folded_items():
    """[(id, 英文名, 类别, 折叠后的名字)]，按 shops.json 的顺序；来自游戏数据层的商店物品目录（按内容版本缓存）。
    库建不出来（没有 shops.json 等）就是空表：和以前读不到文件一样，查不到但不报错（控制台审查 2026-11-02 第 1 条）"""
    from ...gamedata import GamedataError
    from ...gamedata import shops as gd_shops

    try:
        return [(c.uex_item_id, c.en, c.cat, c.folded) for c in gd_shops.catalog()]
    except GamedataError:
        return []


def _rows_for(item_id):
    """这件物品的商店价格行；不是编号或库建不出来 → 空"""
    if not _is_id(item_id):
        return ()
    from ...gamedata import GamedataError
    from ...gamedata import shops as gd_shops

    try:
        return gd_shops.rows_for_item(item_id)
    except GamedataError:
        return ()


def item_record(item_id):
    """商店数据里这件的 [英文名, 类别]：按 str(编号) 对，和以前读 shops.json 的 items[str(编号)] 一样；
    没有这件、库建不出来 → None（CL-C4 起获取途径 acquire.info 用它，替代 load()["items"]）"""
    key = str(item_id)
    for iid, en, cat, _ in _folded_items():
        if str(iid) == key:
            return [en, cat]
    return None


def find(query, limit=12):
    """按名字找物品：[(id, 英文名, 类别)]。中文名先用汉化包对照表换成英文"""
    from ...trade.names import to_english, has_chinese

    rows = _folded_items()  # F8 / 哪买走这里：只用本机库，过期也不在这联网（细查 2026-10-28：断网时每次 F8 卡 48 秒）
    keys = to_english(query) if has_chinese(query) else [query]
    return _catalog.find(rows, keys, limit)


def find_close(name, cutoff=0.88):
    """OCR 把名字认错一两个字母时（Sol-lI → Sol-III）：找最像的一个，(id, 英文名, 类别) 或 None"""
    if len(_fold(name)) < 5:  # 先折叠再判断，和以前一样不碰库
        return None
    return _catalog.find_close(_folded_items(), name, cutoff)


def where(item_id):
    """这件东西在哪买/卖：(买的地方 [(价格, 商店, 位置)], 收的地方 [...])，各按价格排好"""
    return _catalog.where(_rows_for(item_id))


def _is_id(item_id):
    """以前按 r[0] == item_id 比：和整数编号相等的才对得上（None、字符串一行都对不上）"""
    return (
        isinstance(item_id, (int, float))
        and not isinstance(item_id, bool)
        and float(item_id).is_integer()  # nan / inf 也只是对不上，不报错
    )


def where_by_name(name_en):
    """给维科洛材料等用：按英文名找第一处最便宜的买点，一行说明；找不到返回空"""
    k = _fold(name_en)
    ids = [i for i, _n, _c, f in _folded_items() if f == k]
    for iid in ids:
        buy, _ = where(iid)
        if buy:
            p, shop, place = buy[0]
            return f"可买：{shop}（{place}）{p:,.0f} aUEC"
    return ""


# ---------------------------------------------------------------- 按远近排、同系列变体


def nearest(item_id, here, n=3):
    """离 here 最近的 n 个买点：[(距离米, 价格, 商店, 位置)]"""
    from ...navigation.position import distance, shop_point

    out = []
    for r in _rows_for(item_id):
        if r.price_buy <= 0:
            continue
        p = (
            shop_point(r.fields) if any(r.fields) else None
        )  # 旧数据没有结构化位置：当成很远
        d = distance(here, p) if (here and p) else float("inf")
        out.append((d, r.price_buy, r.shop_name, r.place_text))
    return _catalog.nearest(out, n)


def buyable(item_id):
    """有没有商店卖；库建不出来当没有"""
    from ...gamedata import GamedataError
    from ...gamedata import shops as gd_shops

    if not _is_id(item_id):
        return False
    try:
        return gd_shops.buyable(item_id)
    except GamedataError:
        return False


def variants(name, limit=3):
    """同系列能在商店买到的物品：[(id, 名字, 类别)]，原型排前面"""
    cat = _folded_items()
    out, seen = [], set()
    for b in _catalog.base_names(name):
        for iid, n, c in _catalog.variant_candidates(cat, b, name):
            if iid in seen:
                continue
            if buyable(iid):
                seen.add(iid)
                out.append((iid, n, c))
        if out:
            break
    return out[:limit]
