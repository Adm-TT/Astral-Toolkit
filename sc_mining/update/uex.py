"""在你电脑上联网刷新：5 个城市的精炼矿收购价 + 精炼站加成（UEX 公共接口）

用法：python -m sc_mining.uex      → 生成 data/prices.json，demo 会自动优先读它
"""
import json
import urllib.request
from pathlib import Path  # noqa: F401

API = "https://api.uexcorp.space/2.0/"
from ..core.paths import DATA  # noqa: E402
OUT = DATA / "prices.json"


def _get(endpoint):
    req = urllib.request.Request(API + endpoint, headers={"User-Agent": "sc-mining-assistant"})
    from ..core.net import read
    return json.loads(read(req, timeout=20))["data"]


def _base(name: str) -> str:
    name = name.replace(" (Raw)", "").replace(" (Ore)", "").strip()
    return "Ice" if name == "Pressurized Ice" else name


OUTLIER = 0.25  # 最新报价偏离均价超过 25% 视为异常，改用均价


def _pick_price(row):
    """在最新报价和历史均价之间取更可信的那个，返回 (价格, 是否被修正)"""
    latest = row.get("price_sell") or 0
    avg = row.get("price_sell_avg") or 0
    if latest and avg and abs(latest - avg) / avg > OUTLIER:
        return avg, True
    return latest or avg, False


def refresh():
    from ..mining.data import SELL_TERMINALS, SIGNATURES, CITY_PRICES
    prices, flagged = {}, []
    for tid, city in SELL_TERMINALS.items():
        for row in _get(f"commodities_prices?id_terminal={tid}"):
            m = _base(row["commodity_name"])
            if m not in SIGNATURES:
                continue
            price, fixed = _pick_price(row)
            prices.setdefault(m, {})[city] = price
            if fixed:
                flagged.append(f"{m}@{city}: 最新 {row.get('price_sell')} 偏离均价 {row.get('price_sell_avg')}，已用均价")
            old = CITY_PRICES.get(m, {}).get(city)
            if old and price and abs(price - old) / old > OUTLIER:
                flagged.append(f"{m}@{city}: 与内置快照 {old} 相差较大 → {price}")
    yields = {}
    for row in _get("refineries_yields"):
        station = row["terminal_name"].split(" - ", 1)[-1]
        yields.setdefault(station, {})[_base(row["commodity_name"])] = row["value"]
    from ..core.paths import write_json
    write_json(OUT, {"prices": prices, "yields": yields}, indent=1)
    print(f"已更新 {len(prices)} 种矿的城市收购价、{len(yields)} 个精炼站 → {OUT}")
    for line in flagged:
        print("  ⚠ " + line)


def apply_live(data_module):
    """如果有 data/prices.json，用它覆盖内置数据"""
    if not OUT.exists():
        return False
    live = json.loads(OUT.read_text(encoding="utf-8"))
    prices = {m: dict(c) for m, c in data_module.CITY_PRICES.items()}        # 先组好新表再整体换：采矿线程可能正在遍历旧表
    for m, cities in (live.get("prices") or {}).items():
        prices.setdefault(m, {}).update({c: p for c, p in cities.items() if p})   # 0 价（UEX 没报价）不盖内置价
    data_module.CITY_PRICES = prices                  # 整个换掉（best_price 调用时才取 data.CITY_PRICES；没人在 import 时绑定它）
    refs = data_module.REFINERIES                     # refinery.py 在 import 时绑定了这个 dict：只换已有键的值，不增删键，遍历中也安全
    for station, bonus in (live.get("yields") or {}).items():
        if station not in refs:                       # 不认识的站名（UEX 改名）不加，免得推荐出没中文、没星系的站
            continue
        refs[station] = (refs[station][0], bonus)
    return True


if __name__ == "__main__":
    refresh()
