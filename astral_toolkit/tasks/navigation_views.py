"""导航三个视图的排版（业务层，2026-11-26 从 app/presenters/nav 挪来）：太空 / 空间站 / 地面。

navigation/views 算事实，这里配上要查游戏数据的文字（地名 label、当前位置 here_text、站内 station_text…）排好，
bootstrap 当成 NavViews 接进导航线程；界面层（app/presenters/nav）只管活动磁贴、读位置的说法，不再碰 navigation。
导航记号的投影和距离文字（marker_projection）也在这里，bootstrap 接给 app/nav_marker。
navigate / views 的函数一律调用时经模块属性取（测试会换模块上的属性）。
"""

from typing import Any


def target_label(target):
    """活动磁贴上目标的名字：payload 里没带好名字时，按目标点现查"""
    from ..navigation import navigate as n

    return n.label(target)


def space_view(facts, g, target, data):
    from ..navigation import navigate as n

    out = {
        "space": True,
        "same_body": False,
        "inside": False,
        "text": n.space_text(g, target, data),
    }
    if not facts.same_system:
        out["far"] = (
            f"目标位于 {n.SYS_ZH.get(facts.target_system, facts.target_system)}星系，需先跃迁到该星系"
        )
        return out
    out.update(direct=facts.direct, arrived=facts.arrived, aim=facts.aim, qt=facts.qt)
    return out


def station_view(facts, g, target, data, when=None):
    from ..navigation import navigate as n

    out: dict[str, Any] = {
        "space": True,
        "city": True,
        "station": True,
        "inside": True,
        "same_body": True,
    }
    if facts.other_system:
        out["far"] = (
            f"目标位于 {n.SYS_ZH.get(target['sys'], target['sys'])}星系，需先跃迁到该星系"
        )
        return out

    direct_m = facts.direct_m
    assert direct_m is not None
    out.update(direct=direct_m / 1000, direct_m=direct_m)
    if facts.too_far:
        out["far"] = (
            f"先前往{target.get('city_zh') or target.get('site_en') or '空间站'}，到站后按步行指引前往"
        )
        return out
    out.update(
        arrived=facts.arrived,
        close=facts.close,
        updown=facts.updown,
        text=n.station_text(g, target, data, when, facts.arrived),
    )
    return out


def ground_view(facts, here, target, data, steady=None):
    from ..navigation import navigate as n

    out = {
        "text": n.here_text(here, data),
        "inside": here["inside"],
        "body": n.body_label(here["body"]),
        "same_body": facts.same_body,
    }
    if not facts.same_body:
        out["far"] = (
            f"先前往{target.get('city_zh') or n.body_label(target['b'])}，到达城市后按步行指引前往"
            if n.is_city(target)
            else f"先量子跳跃到 {n.body_label(target['b'])}，再按推荐路线前往"
        )
        return out

    raw_bearing = facts.raw_bearing
    out["raw_bearing"] = raw_bearing
    out["bearing"] = steady(raw_bearing) if steady else raw_bearing
    out["compass"] = n.compass(out["bearing"])
    out["surface"] = facts.surface
    out["direct"] = facts.direct
    out["height"] = here["height_m"]
    out["target_height"] = facts.target_height
    out["lat"], out["lon"] = here["lat"], here["lon"]
    out["arrived"] = facts.arrived
    if facts.city:
        out.update(
            city=True,
            arrived=facts.city_arrived,
            close=facts.close,
            direct_m=facts.direct_m,
            updown=facts.updown,
            near=None,
            station=facts.station,
        )
        return out

    near = facts.near
    out["near"] = {"name": n.label(near[1]), "km": near[0]} if near else None
    hint = facts.hint
    if hint:
        _d3q, dsq, brgq, q = hint
        out["hint"] = (
            f"距离过远：先量子跳跃到 {n.label(q)}（距目标 {dsq:,.1f} km），再朝 {n.deg_text(brgq)}° 飞行"
        )
    return out


def space_view_of(g, target, data):
    """导航去太空路标：没有南北，给直线距离、先量子跳到哪、对准哪个标记偏几度"""
    from ..navigation import views

    return space_view(views.space_facts(g, target, data), g, target, data)


def station_view_of(g, target, data, when=None, prev=None, info=None):
    """拉格朗日点 / 跳跃点空间站里走路：距离按米、按站自己的朝向分上下；转向靠机头那一行和屏幕记号"""
    from ..navigation import views

    return station_view(
        views.station_facts(g, target, data, when, prev, info),
        g,
        target,
        data,
        when,
    )


def ground_view_of(here, target, data, steady=None, prev=None):
    """地面导航：方位、距离、到没到（防抖用导航线程自己的 _Steady）"""
    from ..navigation import views

    return ground_view(
        views.ground_facts(here, target, data, prev), here, target, data, steady
    )


def marker_projection(target, data, when, ref, g, cam, fov, w, h, vertical=True):
    """导航记号：目标投到屏幕上的位置和旁边的距离文字 → (proj, label)"""
    from ..navigation import navigate as n

    tg = n.target_global(target, data, when, ref)
    pr = n.project(g, cam, fov, tg, w, h, vertical=vertical)
    return pr, n.dist_text(pr["dist"])
