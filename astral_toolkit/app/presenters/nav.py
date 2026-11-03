"""导航活动的展示映射（UI-K0c）：NavPayload + state_view -> ui.activity；磁贴运行事实 -> status_line。"""

import time


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
