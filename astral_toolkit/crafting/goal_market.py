"""去哪弄、多少钱：材料的获取途径和玩家市场最低挂牌价（2026-11-26 从 crafting/goals.py 搬出来，只搬家）"""

from functools import lru_cache


# ---------------------------------------------------------------- 去哪弄、多少钱


@lru_cache(maxsize=512)
def where_to_get(en):
    """去哪弄的事实：商店最便宜在哪 / 去哪挖 / 维科洛特殊材料说明 / 开箱掉落（tasks/catalog_queries/acquire.material_source，
    经 trade/console 转过来）；查不到、出错给 None。那一句话由目标页用例拼（tasks/goals 调 app/presenters/wikelo.source_text，
    目录迁移收尾）"""
    try:
        from ..trade.console import material_source

        return material_source(en) or None
    except Exception:
        return None


# 挂牌单位 → 每 SCU 要乘几（按 SCU 算的需求只认这些；按「个」算的只认 unit）
PER_SCU = {"SCU": 1, "cSCU": 100, "uSCU": 1_000_000}


def market_price(trade, item_id, minq=0, unit=None):
    """玩家市场（UEX / SCM）出售挂牌里最便宜的单价；没有挂牌返回 None。
    unit 是需求的单位（「SCU」「个」）：给了就只比单位对得上的挂牌，并换算成每 SCU / 每个的价（单位对不上的不猜）"""
    from decimal import Decimal
    from ..trade.providers.http import quality_group

    item = trade.catalog.get(item_id)
    if not item:
        return None
    group = quality_group(minq) if minq else "q0"
    best = None
    for r in trade.prices(item, group, "sell"):
        for s in r.stats or []:
            v = s.minimum if s.minimum is not None else s.mean
            if v is None:
                continue
            v, u = Decimal(v), s.key.unit
            if unit == "SCU":
                if u not in PER_SCU:
                    continue
                v, u = v * PER_SCU[u], "SCU"
            elif unit is not None:
                if u != "unit":
                    continue
                u = unit
            if best is None or v < best[0]:
                best = (v, r.source, u, s.key.currency)
    return best
