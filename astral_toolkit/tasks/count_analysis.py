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
    """鼠标所在物品格的框 (左, 上, 右, 下)；找不到是 None（trade/cell_grid.cell_box）"""
    from ..trade import cell_grid

    return cell_grid.cell_box(img, cursor)


def same_cell(a: Any, b: Any) -> bool:
    """两个格子框是不是同一格：重叠超过一半（trade/cell_grid.overlap）"""
    from ..trade import cell_grid

    return cell_grid.overlap(a, b) > 0.5


def in_cell(box: Any, point: Any) -> bool:
    """这一点在不在这个格子框里（trade/cell_grid.inside）"""
    from ..trade import cell_grid

    return cell_grid.inside(box, point)


def review(place: Any, items: Any) -> Any:
    """这轮看到的和账上对（tasks/count._count_review）"""
    from . import count

    return count._count_review(place, items)
