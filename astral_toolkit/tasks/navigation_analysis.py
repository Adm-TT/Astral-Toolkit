"""导航线程一轮要用的分析（目录迁移 R2，章程 §5、§6）：定位、选路、站内 / 城里分段、转向、太空定位，
以及目前还和分析写在 navigation/navigate.py 里的几句文字（label、fix_text、station_text、space_text、near_text、
short、steer_text；挪去展示层另开一批）。

导航线程在 runtime/workers，不能 import 这里；bootstrap 把本模块当成 NavAnalysis 接进去。这里只原样转给
navigation/navigate.py：调用时才取（导入时机和以前线程里现 import 一样），不另存状态、不另做缓存。
"""

from typing import Any


def _n() -> Any:
    from ..navigation import navigate

    return navigate


def load(*args: Any, **kwargs: Any) -> Any:
    """导航数据（地点、城市、路标）"""
    return _n().load(*args, **kwargs)


def label(*args: Any, **kwargs: Any) -> Any:
    """目标的名字"""
    return _n().label(*args, **kwargs)


def read_clipboard(*args: Any, **kwargs: Any) -> Any:
    """读剪贴板（玩家复制的 /showlocation）"""
    return _n().read_clipboard(*args, **kwargs)


def parse_clip(*args: Any, **kwargs: Any) -> Any:
    """从剪贴板文字里认出坐标"""
    return _n().parse_clip(*args, **kwargs)


def fix_guide(*args: Any, **kwargs: Any) -> Any:
    """太空路标：几次定位算出的方向、距离、到没到"""
    return _n().fix_guide(*args, **kwargs)


def fix_text(*args: Any, **kwargs: Any) -> Any:
    """太空路标那几行字"""
    return _n().fix_text(*args, **kwargs)


def locate(*args: Any, **kwargs: Any) -> Any:
    """右上角 / 剪贴板坐标 → 在哪个星球表面、经纬度"""
    return _n().locate(*args, **kwargs)


def is_city(*args: Any, **kwargs: Any) -> Any:
    """目标是不是城市 / 空间站里的设施"""
    return _n().is_city(*args, **kwargs)


def is_space(*args: Any, **kwargs: Any) -> Any:
    """目标在不在太空（空间站、路标）"""
    return _n().is_space(*args, **kwargs)


def station_leg(*args: Any, **kwargs: Any) -> Any:
    """空间站里走路：这一段去哪、分几步"""
    return _n().station_leg(*args, **kwargs)


def station_text(*args: Any, **kwargs: Any) -> Any:
    """空间站里走路那几行字"""
    return _n().station_text(*args, **kwargs)


def space_text(*args: Any, **kwargs: Any) -> Any:
    """太空路标那几行字（实时定位）"""
    return _n().space_text(*args, **kwargs)


def city_leg(*args: Any, **kwargs: Any) -> Any:
    """城里走路：这一段去哪、分几步"""
    return _n().city_leg(*args, **kwargs)


def near_text(*args: Any, **kwargs: Any) -> Any:
    """附近有什么"""
    return _n().near_text(*args, **kwargs)


def steer(*args: Any, **kwargs: Any) -> Any:
    """机头 / 镜头要转多少"""
    return _n().steer(*args, **kwargs)


def steer_text(*args: Any, **kwargs: Any) -> Any:
    """转向那一行字"""
    return _n().steer_text(*args, **kwargs)


def target_global(*args: Any, **kwargs: Any) -> Any:
    """目标在星系里的坐标"""
    return _n().target_global(*args, **kwargs)


def short(*args: Any, **kwargs: Any) -> Any:
    """地面导航最上面那一行（方向、距离、到没到）"""
    return _n()._short(*args, **kwargs)


def city_near_m() -> float:
    """城里离目标多近就不给转向了（米）"""
    return _n().CITY_NEAR_M
