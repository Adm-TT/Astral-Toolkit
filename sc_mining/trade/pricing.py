from collections import defaultdict
from decimal import Decimal
from .models import PriceStats
from .providers.http import decimal_price, quality_group
from .decimal_math import precise


def aggregate(quotes, now):
    groups = defaultdict(dict)
    for q in quotes:
        if q.kind != 'fixed' or decimal_price(q.price) is None or (q.expires_at and q.expires_at <= now):
            continue
        groups[q.key][q.id] = q.price
    result=[]
    for key,values in groups.items():
        with precise(values.values()):
            result.append(PriceStats(key,sum(values.values())/len(values),min(values.values()),len(values),now,history_note='有效单件挂牌算术平均'))
    return result


def value_stock(lines, prices, source, version, currency):
    lines=list(lines)
    available = {}
    for p in prices:
        if p.key.source != source or p.key.version != version or p.key.currency != currency or p.key.operation != 'sell' or p.minimum is None or p.count <= 0:
            continue
        key = (p.key.item_id, p.key.quality_group, p.key.unit)
        if key not in available or p.observed_at > available[key].observed_at:
            available[key] = p
    total = Decimal(0)
    priced = unpriced = 0
    with precise([p.minimum for p in available.values()]+[Decimal(row.quantity) for row in lines]):
        for row in lines:
            quality = row.key.quality
            if quality.startswith('exact:'):
                quality = quality_group(quality.removeprefix('exact:'))
            price = available.get((row.key.item_id, quality, row.key.unit))
            if price is None:
                unpriced += 1
            else:
                total += price.minimum * row.quantity
                priced += 1
    return {'total': total, 'priced_rows': priced, 'unpriced_rows': unpriced}
