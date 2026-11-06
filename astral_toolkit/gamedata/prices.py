"""矿价 topic：prices.json 的 prices（矿物 × 城市 收购价）和 yields（精炼站加成）"""

import json

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


def refinery_yields(snap=None) -> dict[str, dict]:
    """精炼站 → {矿: 加成%}（int / float 原样，{} 的站也在），按源顺序；每次新建，值会被塞进 REFINERIES"""
    with use(snap) as s:
        return {
            station: json.loads(bonus)
            for station, bonus in s.execute(
                "select station, bonus_json from refinery_yields order by source_order"
            )
        }
