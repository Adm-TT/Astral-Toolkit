"""定位的分析能力（目录迁移章程 R1）：后台定位线程（runtime/workers/position.py）只管什么时候读、存住当前位置；
读到右上角以后认地点中文名、算属于哪个星系、离哪最近，字模学好没有，游戏日志里最后在哪，都经 bootstrap 接到这里。

本模块不持有「当前位置」、不起线程；实现还在 navigation/ 和 core/capture，在函数里 import（导入本模块不碰它们）。
"""


def label_of(location):
    """右上角那行地点名 → 显示用的中文名（认不出给空）"""
    from ..navigation.position import display_label

    return display_label(location)


def system_of(g, *, zone, location, solar_id):
    """星系坐标 + 右上角的线索 → 属于哪个星系（算不出给 None）"""
    from ..navigation import navigate

    return navigate.system_of(g, zone=zone, location=location, solar_id=solar_id)


def locate(g, *, when, local, zone, local_ok):
    """星系坐标 → 离哪最近（星球、空间站、地表点）；算不出给 None"""
    from ..navigation import navigate

    return navigate.locate(g, when=when, local=local, zone=zone, local_ok=local_ok)


def glyphs_ready():
    """读右上角用的字模，在现在的游戏窗口高度下学好没有"""
    from ..core.capture import game_area
    from ..navigation import gridtext

    return gridtext.ready(game_area()["height"])


def last_log_place():
    """游戏日志里最后一次打开库存的地点：navigation.position.from_log 原样（(时间, 地点名, 点) 或 None）"""
    from ..navigation.position import from_log

    return from_log()
