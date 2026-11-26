"""多少钱：玩家市场最低挂牌价（2026-11-26 从 crafting/goals.py 搬出来，只搬家）。
「去哪弄」（where_to_get）同日挪到 tasks/goals：它要调业务层的 acquire，领域层不往上调（边界拆分）"""


# ---------------------------------------------------------------- 多少钱

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
