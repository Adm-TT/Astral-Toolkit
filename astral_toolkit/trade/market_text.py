"""行情的显示：来源 / 状态的中文、钱数、品质档、悬浮窗「市场」那一行。纯函数，不查网、不读库（F 段 B1 从 trade/console 搬来）"""

SOURCE_ZH = {"uex": "UEX", "scm": "SCM"}
STATE_ZH = {
    "ok": "",
    "empty": "暂无报价",
    "partial": "部分数据",
    "stale": "旧缓存",
    "offline": "离线",
    "forbidden": "拒绝访问",
    "rate_limited": "限流",
    "schema_error": "格式变化",
    "cancelled": "已取消",
}


def hud_market(results):
    """悬浮窗「市场」那一行：最低 / 最高 / 均价，没有的不写；所有来源都没数据返回 ""。
    最低价优先用来源给的；UEX 样本不全时不给最低价，就用能看到的挂牌里最低的（标「已知最低」）"""
    parts = []
    for r in results:
        src = SOURCE_ZH.get(r.source, r.source)
        for st in r.stats:
            prices = [q.price for q in (r.quotes or ()) if q.key == st.key]
            bits = []
            if st.minimum is not None:
                bits.append(f"最低 {_money(st.minimum)}")
            elif prices:
                bits.append(f"已知最低 {_money(min(prices))}")
            if prices and (st.minimum is None or max(prices) > st.minimum):
                bits.append(f"最高 {_money(max(prices))}")
            mean = st.mean if st.mean is not None else st.week_mean
            if mean is not None:
                bits.append(
                    f"{'均价' if st.mean is not None else '7天均价'} {_money(mean)}"
                )
            if bits:
                parts.append(f"{src} " + "｜".join(bits))
                break
    return "\n".join(parts)


def _money(v):
    if v is None:
        return "—"
    try:
        return f"{float(v):,.0f}"
    except (TypeError, ValueError):
        return str(v)


def _group(quality):
    from .providers.http import quality_group

    if quality and quality.startswith("exact:"):
        return quality_group(quality[6:])
    return quality if quality and quality.startswith("q") else "q0"
