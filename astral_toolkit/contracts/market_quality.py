"""玩家市场挂牌的品质档位：品质数值（0–1000）→ 档位 q0–q7，认不出返回 "unknown"。

原来在 trade/providers/http.py，2026-11-26 拆领域互引时挪到这里（制造查市价不再引用交易）；
trade.providers.http.quality_group 还是同一个函数。
"""


def quality_group(value) -> str:
    if value is None or isinstance(value, bool):
        return "unknown"
    try:
        n = int(value)
        if n != float(value) or not 0 <= n <= 1000:
            return "unknown"
        return "q" + str(
            0
            if n == 0
            else 1
            if n < 500
            else 2
            if n < 600
            else 3
            if n < 700
            else 4
            if n < 800
            else 5
            if n < 900
            else 6
            if n < 950
            else 7
        )
    except (ValueError, TypeError, OverflowError):
        return "unknown"
