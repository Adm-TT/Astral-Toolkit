"""矿价 topic：prices.json 的 prices（矿物 × 城市 收购价）"""

from ._ready import use


def city_prices(snap=None) -> dict[str, dict[str, float]]:
    """矿物 → 城市 → 价格，顺序同 prices.json；没有 prices 源时 {}"""
    out: dict[str, dict[str, float]] = {}
    with use(snap) as s:
        for mineral, city, price in s.execute(
            "select mineral, city, price from mineral_prices order by rowid"
        ):
            out.setdefault(mineral, {})[city] = price
    return out


def has_live(snap=None) -> bool:
    """库里有没有 UEX 矿价（mineral_prices 非空）"""
    with use(snap) as s:
        return bool(s.execute("select 1 from mineral_prices limit 1"))
