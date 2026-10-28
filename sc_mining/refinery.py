"""精炼站 + 精炼方式 + 卖到哪

精炼后净值 = Σ 原矿 SCU × 产出率 × (1 + 站点加成) × 精炼后收购价 − 精炼费
产出率、精炼费、用时取 SCMiner 4.10.2 精炼模拟器（Dinyx / Ferron 都是 45%）；
站点加成按乘在产出上计算（SCMiner 未说明叠加方式，待游戏终端报价核对）。
收购价只看四大主城（Area18 / Lorville / New Babbage / Orison）和 Levski，取最高。
惰性物质不参与精炼计价。
"""
from .data import REFINERIES, REFINING_METHODS, DEFAULT_METHODS, best_price

INERT = "Inert Materials"


def method_yield(method: str | None) -> float:
    """精炼方式的产出率（0~1）；method 为 None 表示不扣产出损耗"""
    if not method:
        return 1.0
    pct = REFINING_METHODS[method].get("yield_pct")
    return (pct or 100) / 100


def refined_scu(bag: dict, station: str, method: str | None = None) -> dict:
    """精炼后每种矿得到多少 SCU"""
    _, bonus = REFINERIES[station]
    y = method_yield(method)
    return {m: scu * y * (1 + bonus.get(m, 0) / 100) for m, scu in bag.items() if m != INERT}


def refine_fee(bag: dict, method: str | None) -> float:
    if not method:
        return 0.0
    return sum(scu for m, scu in bag.items() if m != INERT) * REFINING_METHODS[method]["fee_per_scu"]


def refine_hours(bag: dict, method: str) -> float:
    return sum(scu for m, scu in bag.items() if m != INERT) / 32 * REFINING_METHODS[method]["hours_per_32"]


def station_value(bag: dict, station: str, method: str | None = None) -> float:
    """精炼后卖出总价 − 精炼费"""
    gross = sum(scu * best_price(m)[0] for m, scu in refined_scu(bag, station, method).items())
    return gross - refine_fee(bag, method)


def best_stations(bag: dict, system: str | None = None, top: int = 3, method: str | None = None):
    """返回 [(站点, 星系, 精炼后估值, 加成明细)]，system 为 None 时全星系比较"""
    rows = []
    for name, (sys_, bonus) in REFINERIES.items():
        if system and sys_ != system:
            continue
        rows.append((name, sys_, station_value(bag, name, method),
                     {m: bonus.get(m, 0) for m in bag if m != INERT}))
    rows.sort(key=lambda r: r[2], reverse=True)
    return rows[:top]


def refined_plan(bag: dict):
    """按默认两种精炼方式，各自给出最佳精炼站：[(方式, 站点, 净值, 精炼后SCU, 精炼费, 用时小时)]"""
    out = []
    for m in DEFAULT_METHODS:
        name, _, value, _ = best_stations(bag, top=1, method=m)[0]
        out.append((m, name, value, sum(refined_scu(bag, name, m).values()),
                    refine_fee(bag, m), refine_hours(bag, m)))
    return out


def sell_plan(bag: dict):
    """每种矿卖去哪个城市：[(矿物, 城市, 单价)]"""
    return [(m, *reversed(best_price(m))) for m in bag if m != INERT]


def unpriced(bag: dict):
    return [m for m in bag if m != INERT and not best_price(m)[0]]


def methods():
    return [(m, REFINING_METHODS[m]) for m in DEFAULT_METHODS]
