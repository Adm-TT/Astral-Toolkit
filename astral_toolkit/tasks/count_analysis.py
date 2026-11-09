"""盘点线程一轮要用的分析（目录迁移 R5）：光标在截图上的哪儿、认鼠标指着的物品、鼠标所在格的框（11-09 加）、收尾时和账上对。

原样转给 trade/inspector._cursor_on_image、tasks/count._read_item、trade/cell_grid、tasks/count._count_review（账还是旧库存那份，
本批不动库存）；每个函数调用时才导入，导入本模块不带进读屏、文字识别、库存。由 bootstrap 接给盘点线程。
"""

from typing import Any


def cursor_on_image(img: Any) -> Any:
    """光标在这张截图上的位置（trade/inspector._cursor_on_image）"""
    from ..trade import inspector

    return inspector._cursor_on_image(img)


def read_item(img: Any, cursor: Any) -> Any:
    """鼠标指着的物品（tasks/count._read_item）"""
    from . import count

    return count._read_item(img, cursor)


def cell_box(img: Any, cursor: Any) -> Any:
    """鼠标所在物品格的框 (左, 上, 右, 下)；找不到是 None（trade/cell_grid.cell_box）。
    调试模式下每次记一行进 debug 日志（光标、框），实机出错时能对上是哪一格"""
    from ..trade import cell_grid, inspector

    box = cell_grid.cell_box(img, cursor)
    inspector._dbg(f"盘点格子框：光标 {tuple(cursor)} 框 {box}")
    return box


def same_cell(a: Any, b: Any) -> bool:
    """两个格子框是不是同一格：重叠超过一半（trade/cell_grid.overlap）"""
    from ..trade import cell_grid

    return cell_grid.overlap(a, b) > 0.5


def in_gap(img: Any, cursor: Any) -> bool:
    """鼠标是不是停在两格之间的缝上（trade/cell_grid.in_gap）"""
    from ..trade import cell_grid

    return cell_grid.in_gap(img, cursor)


def in_cell(box: Any, point: Any) -> bool:
    """这一点在不在这个格子框里（trade/cell_grid.inside）"""
    from ..trade import cell_grid

    return cell_grid.inside(box, point)


def spot(img: Any, cursor: Any, item: Any) -> Any:
    """鼠标指的那一格在仓库里的身份（页、最左那列、占几列、内容里的纵向位置；trade/count_view.spot）；看不清是 None。
    占几格按游戏数据（gamedata.items.grid_width）：数据包带占格信息才信，不带（旧数据包）当不知道、让它自己看格子"""
    from ..trade import count_view, inspector

    sp = count_view.spot(img, cursor, _width(item))
    inspector._dbg(f"盘点格子身份：光标 {tuple(cursor)} {sp}")
    return sp


def _width(item: Any) -> Any:
    en = (item or {}).get("en") or ""
    try:
        from ..gamedata import items

        return items.grid_width(en) if en and items.has_grid() else None
    except Exception:
        return None


def same_spot(a: Any, b: Any, height: int) -> Any:
    """两个身份是不是同一格：True / False；有一边没认出页码是 None（交给格子框比较）"""
    from ..trade import cell_grid, count_view

    return count_view.same_spot(a, b, height * cell_grid.PITCH)


def review(place: Any, items: Any) -> Any:
    """这轮看到的和账上对（tasks/count._count_review）"""
    from . import count

    return count._count_review(place, items)
