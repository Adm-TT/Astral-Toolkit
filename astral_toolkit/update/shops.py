"""商店价格更新（目录迁移 Q2 从 crafting/shops.py 搬来）：从 UEX 拉全部商店价格，写 shops.json

数据来自 UEX（玩家众包的商店价格，CIG 3.20 以后游戏文件里没有商店数据，所有 Item Finder 都靠众包，
可能有缺漏；finder.cstone.space 同理）。按物品类别把所有商店价格拉一份缓存在 shops.json，
「更新数据」时更新（run.update：先下 AT 数据包，不通才用这里的 update 直接从 UEX 拉）。
查询都走游戏数据库（tasks/catalog_queries/shops → gamedata/shops），不读这个文件。
"""

import time

from ..core.paths import DATA

CACHE = DATA / "shops.json"
BASE = "https://api.uexcorp.uk/2.0/"
FMT = 2  # 缓存格式版本：2 = 每条价格带结构化位置（按远近排序要用）
# UEX 的物品类别（type=item），商品（矿物等）不在这里，矿物看「找矿点」和精炼/卖价
SKIP_CATEGORIES = {36, 37, 87}


def _get(path, params=None):
    from ..trade.providers.http import HttpTransport, uex_data

    return uex_data(HttpTransport().get_json(BASE + path, params or {}))


def _place(r):
    parts = [
        r.get("star_system_name"),
        r.get("planet_name"),
        r.get("moon_name"),
        r.get("space_station_name") or r.get("city_name") or r.get("outpost_name"),
    ]
    return " · ".join(p for p in parts if p)


def update(progress=print):
    """拉一遍 UEX 所有物品类别的商店价格（约 60 次请求，4 个并行）"""
    allcats = _get("categories")
    cat_name = {int(c["id"]): c.get("name") or "" for c in allcats}
    cats = [
        c
        for c in allcats
        if c.get("type") == "item" and int(c["id"]) not in SKIP_CATEGORIES
    ]
    items, rows = {}, []

    def fetch(c):
        try:
            return c, _get("items_prices", {"id_category": str(c["id"])}), None
        except Exception as e:
            return c, None, e

    # 4 个一起下（以前一个一个下要 1~2 分钟，访问国外慢的网络下更久）；UEX 有频率限制，别开太多
    from concurrent.futures import ThreadPoolExecutor

    failed = []
    with ThreadPoolExecutor(4) as ex:
        for n, (c, data, err) in enumerate(ex.map(fetch, cats), 1):
            if err:
                failed.append(f"{c.get('name')}：{err}")
            if progress:
                progress(
                    f"  商店价格 {n}/{len(cats)}：{c.get('section')} / {c.get('name')}"
                    + (f"（跳过：{err}）" if err else "")
                )
            for r in data or []:
                iid = int(r["id_item"])
                items[iid] = [
                    r.get("item_name") or "",
                    cat_name.get(int(r.get("id_category") or 0)) or c.get("name") or "",
                ]
                buy, sell = (
                    float(r.get("price_buy") or 0),
                    float(r.get("price_sell") or 0),
                )
                if buy > 0 or sell > 0:
                    rows.append(
                        [
                            iid,
                            r.get("terminal_name") or "",
                            _place(r),
                            buy,
                            sell,
                            r.get("game_version") or "",
                            [
                                r.get(k) or ""
                                for k in (
                                    "star_system_name",
                                    "planet_name",
                                    "orbit_name",
                                    "moon_name",
                                    "space_station_name",
                                    "city_name",
                                )
                            ],
                        ]
                    )
    if failed:
        raise RuntimeError(
            f"商店价格有 {len(failed)} 类下载失败（{failed[0]}），这次不更新，继续用旧表"
        )  # 审查 2026-10-28：以前会把残缺表写成最新
    data = {
        "fmt": FMT,
        "fetched": time.time(),
        "items": {str(k): v for k, v in items.items()},
        "rows": rows,
    }
    from .. import gamedata
    from ..core.paths import write_json

    # 只把写文件这一步放进更新边界（拿数据目录写锁，退出时重建游戏数据库）：联网那一两分钟不占着锁
    with gamedata.updating():
        write_json(CACHE, data, separators=(",", ":"))
    if progress:
        progress(f"商店数据已更新：{len(items)} 种物品，{len(rows)} 条商店价格")
    return data
