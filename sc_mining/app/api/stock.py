"""库存 Controller（2026-10-30 重构阶段 1）

库存、货架、出入库、台账的接口：收关键字参数，原样转给 tasks/stock.py 里同名函数。
只做转发，不加校验（校验留在 tasks 里，改行为要 NGU 定）。router 自动收集文件末尾的 ROUTES。
"""
from ...tasks import stock as _t


def stock(**kw):
    return _t.stock(**kw)


def stock_add(**kw):
    return _t.stock_add(**kw)


def craft_slots_for(**kw):
    return _t.craft_slots_for(**kw)


def stock_add_named(**kw):
    return _t.stock_add_named(**kw)


def stock_suggest(**kw):
    return _t.stock_suggest(**kw)


def stock_set_quality(**kw):
    return _t.stock_set_quality(**kw)


def stock_undo(**kw):
    return _t.stock_undo(**kw)


def stock_out(**kw):
    return _t.stock_out(**kw)


def stock_set_qty(**kw):
    return _t.stock_set_qty(**kw)


def stock_move(**kw):
    return _t.stock_move(**kw)


def stock_relocate(**kw):
    return _t.stock_relocate(**kw)


def stock_keep_custom(**kw):
    return _t.stock_keep_custom(**kw)


def stock_places(**kw):
    return _t.stock_places(**kw)


def stock_place_add(**kw):
    return _t.stock_place_add(**kw)


def stock_bin_save(**kw):
    return _t.stock_bin_save(**kw)


def stock_bin_delete(**kw):
    return _t.stock_bin_delete(**kw)


def stock_reserve(**kw):
    return _t.stock_reserve(**kw)


def stock_ledger(**kw):
    return _t.stock_ledger(**kw)


def stock_prices(**kw):
    return _t.stock_prices(**kw)


ROUTES = {
    "stock": stock,
    "stock_add": stock_add,
    "craft_slots_for": craft_slots_for,
    "stock_add_named": stock_add_named,
    "stock_suggest": stock_suggest,
    "stock_set_quality": stock_set_quality,
    "stock_undo": stock_undo,
    "stock_out": stock_out,
    "stock_set_qty": stock_set_qty,
    "stock_move": stock_move,
    "stock_relocate": stock_relocate,
    "stock_keep_custom": stock_keep_custom,
    "stock_places": stock_places,
    "stock_place_add": stock_place_add,
    "stock_bin_save": stock_bin_save,
    "stock_bin_delete": stock_bin_delete,
    "stock_reserve": stock_reserve,
    "stock_ledger": stock_ledger,
    "stock_prices": stock_prices,
}
