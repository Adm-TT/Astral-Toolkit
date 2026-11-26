"""导航活动的展示映射（UI-K0c）：NavPayload + state_view -> ui.activity；磁贴运行事实 -> status_line。
目录迁移 R2 起导航线程用的右上角读位置说法（nav_tip、DI_HELP）也在这里，bootstrap 接进导航线程。
太空 / 空间站 / 地面三个视图要查游戏数据配文字，2026-11-26 挪到业务层 tasks/navigation_views；这里不碰 navigation。"""

import time


def _target_label(payload, label_of=None):
    row = getattr(payload, "target_row", None)
    if isinstance(row, dict):
        label = row.get("label")
    else:
        label = getattr(row, "label", None)
    if label:
        return str(label)
    target = getattr(payload, "target", None)
    if not isinstance(target, dict) or label_of is None:
        return None
    try:
        return str(label_of(target))
    except Exception:
        return None


def activity(session_id, payload, state_view, label_of=None):
    """只映射，不读全局：state_view 由 Worker 按本轮事实填好。
    label_of：payload 没带好名字时按目标点现查名字（bootstrap 接 tasks/navigation_views.target_label）"""
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
        "primary": {"value": _target_label(payload, label_of), "unit": ""},
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


def marker_model(area, proj, label):
    return {
        "area": (area["left"], area["top"], area["width"], area["height"]),
        "proj": proj,
        "label": label,
    }


# ---------------------------------------------------------------- 导航线程用的排版（目录迁移 R2 从 app/engines/nav 搬来）
DI_HELP = "未检测到右上角位置信息：在游戏中按 ~ 打开控制台，输入 r_DisplayInfo 2 后回车"


def nav_tip(on, last_ok, now, has_shown, di_help):
    """导航时右上角读位置的说法 → (窗口状态, 悬浮窗末尾那行)。窗口和悬浮窗说法一致（审查 2026-10-30）：
    读得到：实时；8–30 秒前读到过而且有上次结果：标「暂停更新」，不冒充实时；刚开始还没结果：等待；
    更久没读到 / 从没读到：教开调试信息"""
    if on:
        return "右上角调试信息：实时识别位置", ""
    if last_ok and now - last_ok < 30:
        if has_shown:
            return (
                "右上角位置暂时认不出，显示的是上次结果",
                "\n位置暂停更新，以上是上次结果",
            )
        return "等待右上角位置信息…", ""
    return (
        di_help + "（或在聊天框输入 /showlocation）",
        "\n读不到位置：控制台输入 r_DisplayInfo 2，或聊天框输入 /showlocation",
    )
