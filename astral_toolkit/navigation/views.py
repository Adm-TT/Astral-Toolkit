"""导航视图的「算数」部分（NV-B1，从 tasks/mining.py 的 _space_view / _station_view / _nav_view 拆出）

只放数、元组和布尔；中文文案都在 app/presenters/nav.py。navigate 的函数一律经 n.xxx 调（测试会换模块上的属性）。
"""

import math
from dataclasses import dataclass
from typing import Any

from . import navigate as n


@dataclass(frozen=True)
class SpaceFacts:
    """太空路标：space_guide 的结果（文字由 presenter 加）"""

    same_system: Any
    target_system: Any
    direct: Any
    arrived: Any
    aim: Any
    qt: Any


def space_facts(g, target, data):
    """只调一次 space_guide，取字段的方式和原 _space_view 一样"""
    s = n.space_guide(g, target, data)
    same_system = s["same_system"]
    if not same_system:
        return SpaceFacts(
            same_system,
            s["target_system"],
            None,
            None,
            None,
            None,
        )
    return SpaceFacts(
        same_system,
        None,
        s["direct"],
        s["arrived"],
        s.get("aim"),
        s.get("qt"),
    )


@dataclass(frozen=True)
class StationFacts:
    """拉格朗日点 / 跳跃点空间站里走路：距离按米、按站自己的朝向分上下"""

    other_system: bool
    direct_m: float | None
    too_far: bool
    updown: float | None
    arrived: bool | None
    close: bool | None


def station_facts(g, target, data, when=None, prev=None, info=None):
    """照原 _station_view 的先后算数和分支"""
    try:  # 先核对星系：别的星系同一个坐标也可能有东西（二审 2026-10-27）
        system, _ = n.system_info(
            g,
            data,
            **{k: (info or {}).get(k) or "" for k in ("zone", "location", "solar_id")},
        )
    except Exception:
        system = ""
    if (
        target.get("sys") and system and system != target["sys"]
    ):  # 猜出来的星系不一样也不算到（复审 2026-10-27）
        return StationFacts(True, None, False, None, None, None)
    tg = n.target_global(target, data, when)
    d = math.dist(g, tg)
    if d > 50_000:
        return StationFacts(False, d, True, None, None, None)
    up = sum((t - a) * u for t, a, u in zip(tg, g, target.get("up") or (0, 0, 0)))
    arrived = n.city_arrived(
        d, bool(prev and prev.get("station") and prev.get("arrived"))
    )
    return StationFacts(
        False,
        d,
        False,
        up,
        arrived,
        not arrived and d < n.CITY_NEAR_M,
    )


@dataclass(frozen=True)
class GroundFacts:
    """地面导航：原 _nav_view 里不涉及文字的部分

    arrived 是按表面距离（surface < 1）算的；城市目标的最终到达看 city_arrived。
    near 原样存 n.nearby 的结果（元组或 None）；hint 存满足出提示条件的那条 n.approaches
    （第一个元素不用、距目标 km、方位、量子跳跃点），不满足为 None。
    """

    same_body: Any
    raw_bearing: Any = None
    surface: Any = None
    direct: Any = None
    target_height: Any = None
    arrived: Any = None
    city: bool = False
    city_arrived: Any = None
    close: Any = None
    direct_m: Any = None
    updown: Any = None
    station: Any = None
    near: Any = None
    hint: Any = None


def ground_facts(here, target, data, prev=None):
    """照原 _nav_view 的先后算数和分支，不拼文字"""
    same_body = here["inside"] and here["body"] == target["b"]
    if not same_body:
        return GroundFacts(same_body=same_body)

    a, t = n.pos(here), n.pos(target)
    raw_bearing = n.bearing(a, t)
    surface = n.surface_km(a, t, here["radius_km"])
    direct = n.direct_km(a, t)
    target_height = n.latlon(t)[2] * 1000 - here["radius_km"] * 1000
    arrived = surface < 1

    if n.is_city(target):  # 城里：几米以内才算到，距离按米、加上下楼层（2026-10-27）
        d, up = n.city_metrics(here, target)
        city_arrived = n.city_arrived(
            d, bool(prev and prev.get("city") and prev.get("arrived"))
        )
        return GroundFacts(
            same_body=same_body,
            raw_bearing=raw_bearing,
            surface=surface,
            direct=direct,
            target_height=target_height,
            arrived=arrived,
            city=True,
            city_arrived=city_arrived,
            close=not city_arrived and d < n.CITY_NEAR_M,
            direct_m=d,
            updown=up,
            station=bool(target.get("up")),  # 绕星球轨道的空间站：不给南北方位
            near=None,
        )

    near = n.nearby(here, data)
    best = n.approaches(target, data, top=1)
    hint = None
    if best and best[0][1] < surface * 0.5 and surface > 30:
        hint = best[0]
    return GroundFacts(
        same_body=same_body,
        raw_bearing=raw_bearing,
        surface=surface,
        direct=direct,
        target_height=target_height,
        arrived=arrived,
        city=False,
        near=near,
        hint=hint,
    )
