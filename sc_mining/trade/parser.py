from collections import defaultdict  # noqa: F401
import re
from .models import ImportRow, StockKey, StockLine
from .names import to_english

QUANTITY = re.compile(r'(?:(?<![A-Za-z])[x×]\s*|数量\s*[:：]?\s*|qty\s*[:：]?\s*)(\d+)(?!\d)',re.I)
QUALITY = re.compile(r'(?:(?<![A-Za-z])Q\s*|品质\s*[:：]?\s*)(\d{1,4})(?!\d)',re.I)


def parse_inventory(tokens, catalog):
    lines = []
    # Cluster token baselines by spatial proximity, then read left-to-right.
    for token in sorted(tokens,key=lambda t:(t.box[1]+t.box[3]/2,t.box[0])):
        center = token.box[1]+token.box[3]/2
        target = next((line for line in lines if abs(line[0]-center) <= max(6,token.box[3]*0.45)),None)
        if target is None:
            lines.append([center,[token]])
        else:
            target[1].append(token)
    rows = []
    for _, words in lines:
        text = ' '.join(t.text for t in sorted(words,key=lambda t:t.box[0]))
        quantity_match, quality_match = QUANTITY.search(text), QUALITY.search(text)
        name = QUALITY.sub('',QUANTITY.sub('',text)).strip(' |:：-')
        if not name:
            continue
        candidates = tuple(catalog.search(name))
        english = to_english(name)
        exact = [i for i in candidates if i.name.casefold()==name.casefold()
                 or (len(english)==1 and i.name.casefold()==english[0].casefold())]
        matched = exact[0].id if len(exact)==1 else None
        quality = 'exact:'+quality_match[1] if quality_match and int(quality_match[1])<=1000 else None
        quantity = int(quantity_match[1]) if quantity_match else None
        rows.append(ImportRow(name,matched,quantity,quality,candidates=candidates))
    return rows


def validate_rows(rows, location):
    if not location.strip():
        raise ValueError('需填写存放地点')
    result = []
    for i,row in enumerate(rows,1):
        if not row.confirmed or not row.item_id or type(row.quantity) is not int or not 0 < row.quantity <= 2**53-1 or not row.quality or not row.unit:
            raise ValueError(f'第 {i} 行尚未确认物品、数量或品质')
        quality = row.quality
        if quality.startswith('exact:'):
            try:
                value = int(quality[6:])
                valid = str(value)==quality[6:] and 0<=value<=1000
            except ValueError:
                valid=False
        else:
            valid = quality in ('unknown',*(f'q{i}' for i in range(8)))
        if not valid:
            raise ValueError(f'第 {i} 行品质无效，需选择品质档或填写 0–1000')
        result.append(StockLine(StockKey(row.item_id,quality,location.strip(),row.unit),row.quantity))
    if not result:
        raise ValueError('没有可录入的物品')
    return tuple(result)
