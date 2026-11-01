"""商店 topic：shops.json 的 rows（shop_rows 表，7 列原样）

商店物品目录（items：uex 编号 → 英文名、类别）等公共层加 shop_items 表后再加 catalog()。"""

from ._ready import use
from ._types import ShopRow

_COLS = "uex_item_id, shop_name, place_text, price_buy, price_sell, version, f0, f1, f2, f3, f4, f5, source_order"


def _row(r: tuple) -> ShopRow:
    return ShopRow(
        r[0],
        r[1],
        r[2],
        r[3],
        r[4],
        r[5],
        (r[6], r[7], r[8], r[9], r[10], r[11]),
        r[12],
    )


def rows_for_item(uex_item_id: int, snap=None) -> tuple[ShopRow, ...]:
    """这件物品的所有商店价格行，按源顺序"""
    with use(snap) as s:
        return tuple(
            _row(r)
            for r in s.execute(
                f"select {_COLS} from shop_rows where uex_item_id = ? order by source_order",
                (int(uex_item_id),),
            )
        )


def buyable(uex_item_id: int, snap=None) -> bool:
    """有没有商店卖（买价 > 0）"""
    with use(snap) as s:
        return bool(
            s.execute(
                "select 1 from shop_rows where uex_item_id = ? and price_buy > 0 limit 1",
                (int(uex_item_id),),
            )
        )


def place_fields(snap=None) -> tuple[tuple[str, str, str, str, str, str], ...]:
    """所有行的结构化位置 (星系, 星球, 轨道, 卫星, 空间站, 城市)，按源顺序，不去重"""
    with use(snap) as s:
        return tuple(
            (a, b, c, d, e, f)
            for a, b, c, d, e, f in s.execute(
                "select f0, f1, f2, f3, f4, f5 from shop_rows order by source_order"
            )
        )


def lagrange_rows(snap=None) -> tuple[ShopRow, ...]:
    """轨道里带 Lagrange、且有空间站或城市名的行（拉格朗日点的休息站），按源顺序"""
    with use(snap) as s:
        return tuple(
            _row(r)
            for r in s.execute(
                f"select {_COLS} from shop_rows where instr(f2, 'Lagrange') > 0 and (f4 <> '' or f5 <> '') "
                "order by source_order"
            )
        )
