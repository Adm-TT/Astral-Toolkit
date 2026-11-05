"""导航活动的展示映射（UI-K0c）：NavPayload + state_view -> ui.activity；磁贴运行事实 -> status_line。"""

import time
from typing import Any


def _target_label(payload):
    row = getattr(payload, "target_row", None)
    if isinstance(row, dict):
        label = row.get("label")
    else:
        label = getattr(row, "label", None)
    if label:
        return str(label)
    target = getattr(payload, "target", None)
    if not isinstance(target, dict):
        return None
    try:
        from ...navigation import navigate as n

        return str(n.label(target))
    except Exception:
        return None


def space_view(facts, g, target, data):
    from ...navigation import navigate as n

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
    from ...navigation import navigate as n

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
    from ...navigation import navigate as n

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


def activity(session_id, payload, state_view):
    """只映射，不读全局：state_view 由 Worker 按本轮事实填好。"""
    here = state_view.get("here") or {}
    secondary = []
    direct_m = here.get("direct_m")
    if direct_m is not None:
        secondary.append(
            {"label": "距离", "value": round(float(direct_m)), "unit": "m"}
        )
    else:
        direct = here.get("direct")
        if direct is not None:
            secondary.append({"label": "距离", "value": str(direct)})
    status = state_view.get("status")
    if status:
        secondary.append({"label": "状态", "value": str(status)})
    if here.get("arrived"):
        secondary.append({"label": "到达", "value": "已到达"})
    state = state_view.get("state") or "starting"
    stale_since = state_view.get("stale_since") if state == "stale" else None
    return {
        "activity_id": f"nav:{session_id}",
        "kind": "nav",
        "title": "导航",
        "state": state,
        "primary": {"value": _target_label(payload), "unit": ""},
        "secondary": secondary[:3],
        "progress": None,
        "quality": state_view.get("quality") or "partial",
        "action": {"id": "stop", "label": "结束导航"},
        "link": "nav",
        "stale_since": stale_since,
        "error": None,
        "updated_wall": time.strftime("%Y-%m-%d %H:%M:%S"),
        "detail_ref": None,
    }


def tile_status(on: bool, runtime: dict) -> dict:
    """导航磁贴只映射 loop 的运行事实；停止中显示提示，不伪造 activity。"""
    draining = bool(runtime.get("draining"))
    pending_read = bool(runtime.get("pending_read"))
    if on:
        line = "导航中"
        if draining:
            line += "，旧线程仍在收尾"
        return {"status_line": line, "available": {"ok": True}}
    can_start = bool(runtime.get("can_start")) and not pending_read
    if draining:
        line = "正在停止导航，请稍候"
        if can_start:
            line = "正在停止导航，旧线程仍在收尾"
    elif runtime.get("running") or pending_read:
        line = "正在停止导航，请稍候"
        can_start = False
    else:
        line = "已关闭" if can_start else "暂不能开启"
    available: dict[str, object] = {"ok": can_start}
    if not can_start:
        available["reason"] = line
    return {"status_line": line, "available": available}


def marker_label(dist):
    from ...navigation import navigate as n

    return n.dist_text(dist)


def marker_model(area, proj, label):
    return {
        "area": (area["left"], area["top"], area["width"], area["height"]),
        "proj": proj,
        "label": label,
    }
