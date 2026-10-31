"""物品在哪买（Item Finder）：游戏里哪些商店卖这件东西、多少钱，哪些商店收

数据来自 UEX（玩家众包的商店价格，CIG 3.20 以后游戏文件里没有商店数据，所有 Item Finder 都靠众包，
可能有缺漏；finder.cstone.space 同理）。按物品类别把所有商店价格拉一份缓存在 shops.json，
菜单 5 更新，超过 7 天第一次查时自动更新。
"""

import json
import re
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
from ..core.paths import DATA  # noqa: E402

CACHE = DATA / "shops.json"
BASE = "https://api.uexcorp.uk/2.0/"
MAX_AGE = 7 * 86400
FMT = 2  # 缓存格式版本：2 = 每条价格带结构化位置（按远近排序要用）
# UEX 的物品类别（type=item），商品（矿物等）不在这里，矿物看「找矿点」和精炼/卖价
SKIP_CATEGORIES = {36, 37, 87}

_data = None


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
        )  # 老大审查 2026-10-28：以前会把残缺表写成最新
    data = {
        "fmt": FMT,
        "fetched": time.time(),
        "items": {str(k): v for k, v in items.items()},
        "rows": rows,
    }
    from ..core.paths import write_json

    write_json(CACHE, data, separators=(",", ":"))
    global _data
    _data = data
    if progress:
        progress(f"商店数据已更新：{len(items)} 种物品，{len(rows)} 条商店价格")
    return data


def load(auto_update=True):
    global _data
    if _data is None and CACHE.exists():
        _data = json.loads(CACHE.read_text(encoding="utf-8"))
    if auto_update and (
        _data is None
        or time.time() - _data.get("fetched", 0) > MAX_AGE
        or _data.get("fmt") != FMT
    ):
        print(
            "商店数据"
            + ("未下载" if _data is None else "需要更新")
            + "，从 UEX 更新（约 1–2 分钟）…"
        )
        try:
            update()
        except Exception as e:
            print(f"更新失败（{e}），" + ("使用旧数据" if _data else "暂时无法查询"))
    return _data or {"items": {}, "rows": []}


def _fold(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower().replace("l", "i"))


_folded = {"of": None, "rows": []}


def _folded_items(data):
    """[(id, 英文名, 类别, 折叠后的名字)]：数据没换就不重算（以前每查一次要把 5000 多个名字全折叠一遍）"""
    if _folded["of"] is not data:
        _folded.update(
            of=data,
            rows=[(int(i), n, c, _fold(n)) for i, (n, c) in data["items"].items()],
        )
    return _folded["rows"]


def find(query, limit=12):
    """按名字找物品：[(id, 英文名, 类别)]。中文名先用汉化包对照表换成英文"""
    from ..trade.names import to_english, has_chinese

    rows = _folded_items(
        load(auto_update=False)
    )  # F8 / 哪买走这里：只用本机表，过期也不在这联网（细查 2026-10-28：断网时每次 F8 卡 48 秒）
    keys = to_english(query) if has_chinese(query) else [query]
    out, seen = [], set()
    for key in keys:
        k = _fold(key)
        if not k:
            continue
        exact = [(i, n, c) for i, n, c, f in rows if f == k]
        part = [(i, n, c) for i, n, c, f in rows if k in f and f != k]
        for row in exact + sorted(part, key=lambda r: len(r[1])):
            if row[0] not in seen:
                seen.add(row[0])
                out.append(row)
    return out[:limit]


def find_close(name, cutoff=0.88):
    """OCR 把名字认错一两个字母时（Sol-lI → Sol-III）：找最像的一个，(id, 英文名, 类别) 或 None"""
    import difflib

    k = _fold(name)
    if len(k) < 5:
        return None
    rows = _folded_items(load(auto_update=False))
    best = difflib.get_close_matches(k, [f for *_, f in rows], n=1, cutoff=cutoff)
    if not best:
        return None
    return next((i, n, c) for i, n, c, f in rows if f == best[0])


def where(item_id):
    """这件东西在哪买/卖：(买的地方 [(价格, 商店, 位置)], 收的地方 [...])，各按价格排好"""
    data = load(auto_update=False)
    buy = sorted(
        (r[3], r[1], r[2]) for r in data["rows"] if r[0] == item_id and r[3] > 0
    )
    sell = sorted(
        ((r[4], r[1], r[2]) for r in data["rows"] if r[0] == item_id and r[4] > 0),
        reverse=True,
    )
    return buy, sell


def where_text(item_id, top=6):
    buy, sell = where(item_id)
    lines = []
    if buy:
        lines.append(f"  游戏商店有卖（{len(buy)} 处，最便宜在前）：")
        lines += [f"    {p:,.0f} aUEC｜{shop}｜{place}" for p, shop, place in buy[:top]]
        if len(buy) > top:
            lines.append(f"    …还有 {len(buy) - top} 处")
    else:
        lines.append(
            "  UEX 没有这件东西的商店售卖记录（可能只能任务/制造/开箱/玩家交易获得）"
        )
    if sell:
        p, shop, place = sell[0]
        lines.append(f"  卖给商店最高：{p:,.0f} aUEC｜{shop}｜{place}")
    return "\n".join(lines)


def where_by_name(name_en):
    """给维科洛材料等用：按英文名找第一处最便宜的买点，一行说明；找不到返回空"""
    data = load(auto_update=False)
    k = _fold(name_en)
    ids = [int(i) for i, (n, _) in data["items"].items() if _fold(n) == k]
    for iid in ids:
        buy, _ = where(iid)
        if buy:
            p, shop, place = buy[0]
            return f"可买：{shop}（{place}）{p:,.0f} aUEC"
    return ""


# ---------------------------------------------------------------- 按远近排、同系列变体


def shop_point(fields):
    """商店位置 → 星图点（卫星/拉格朗日点/行星）"""
    from ..navigation.position import find_point, PLANET_CODE  # noqa: F401

    system, planet, orbit, moon, station, city = (list(fields) + [""] * 6)[:6]
    if moon:
        p = find_point(name=moon)
        if p:
            return p
    m = re.search(r"Lagrange Point (\d)", orbit or "")
    if m and planet:
        base = find_point(name=planet)
        if base:
            iname = base["i"]
            pm = re.fullmatch(r"(?i)pyro(\d)", iname)
            p = find_point(
                internal=f"P{pm.group(1)}_L{m.group(1)}"
                if pm
                else f"{iname}_L{m.group(1)}"
            )
            if p:
                return p
    for name in (planet, station, system and system + " Star"):
        if name:
            p = find_point(name=name)
            if p:
                return p
    return None


def nearest(item_id, here, n=3):
    """离 here 最近的 n 个买点：[(距离米, 价格, 商店, 位置)]"""
    from ..navigation.position import distance

    data = load(auto_update=False)
    out = []
    for r in data["rows"]:
        if r[0] != item_id or r[3] <= 0:
            continue
        p = shop_point(r[6]) if len(r) > 6 else None
        d = distance(here, p) if (here and p) else float("inf")
        out.append((d, r[3], r[1], r[2]))
    out.sort(key=lambda x: (x[0], x[1]))
    picked, places = [], set()  # 同一个空间站/城市只留一家（最便宜的），凑 3 个不同地点
    for row in out:
        if row[3] not in places:
            places.add(row[3])
            picked.append(row)
        if len(picked) == n:
            break
    return picked


_VARIANT = re.compile(r'\s*["“][^"”]+["”]\s*')


def base_names(name):
    """限定版 → 可能的原型名：去掉引号里的涂装名；再去掉 -II / Mk II 之类的型号后缀"""
    b1 = re.sub(r"\s+", " ", _VARIANT.sub(" ", name)).strip()
    b2 = re.sub(
        r"(?i)(-|\s)([il]{2,3}|iv|mk\s*\w+)\b", "", b1
    ).strip()  # OCR 常把 II 认成 ll
    return [b for b in dict.fromkeys([b1, b2]) if b and b != name]


def buyable(item_id):
    return any(r[0] == item_id and r[3] > 0 for r in load(auto_update=False)["rows"])


def variants(name, limit=3):
    """同系列能在商店买到的物品：[(id, 名字, 类别)]，原型排前面"""
    data = load(auto_update=False)
    out, seen = [], set()
    for b in base_names(name):
        k = _fold(b)
        words = [w for w in re.findall(r"[a-z0-9]+", b.lower()) if len(w) > 2]
        for i, (n, c) in sorted(data["items"].items(), key=lambda kv: len(kv[1][0])):
            iid = int(i)
            if iid in seen or _fold(n) == _fold(name):
                continue
            f = _fold(n)
            if f == k or (words and all(_fold(w) in f for w in words)):
                if buyable(iid):
                    seen.add(iid)
                    out.append((iid, n, c))
        if out:
            break
    return out[:limit]
