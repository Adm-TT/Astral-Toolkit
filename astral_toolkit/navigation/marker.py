"""导航记号的纯计算：收起原因、镜头方向保持、视角选择。

只使用参数和标准库，不读时钟、设置、窗口、前台。
"""

WHY_NO_POSITION = "还没算出位置"
WHY_NO_CAMERA = "没有镜头方向"
WHY_STALE = "读数过期"
WHY_ARRIVED = "已到达"
WHY_CROSS_SYSTEM = "跨星系"
WHY_NOT_FOREGROUND = "游戏不在前台"
WHY_MINING_RUNNING = "采矿助手开着"
WHY_SETTING_OFF = "设置里关了"


def camera_hold(cam, t, last, hold):
    """当前帧没有镜头方向时，hold 秒内沿用上一次读到的方向；原地更新 last。

    偶尔一帧镜头方向没读出（坐标照样有）：以前记号当场收起、下一帧再出来，一直闪（老大 11-03 实测）。
    1 秒内读到的接着用；记号按坐标那一帧重画，镜头方向不会因此当成新读的。
    """
    if cam:
        last.update(t=t, cam=cam)
        return cam
    if last["cam"] and 0 <= t - last["t"] < hold:
        return last["cam"]
    return cam


def hidden_reason(
    here,
    g,
    cam,
    t,
    *,
    now,
    stale,
    foreground,
    mining_running,
    enabled,
):
    """按原来的先后判断记号要不要收起；返回原因字符串或 None。"""
    if here is None or not g:
        return WHY_NO_POSITION
    if not cam:
        return WHY_NO_CAMERA
    if now() - t >= stale:
        return WHY_STALE
    if here.get("arrived"):
        return WHY_ARRIVED
    if here.get("far"):
        return WHY_CROSS_SYSTEM
    if not foreground:
        return WHY_NOT_FOREGROUND
    if mining_running():
        return WHY_MINING_RUNNING
    if not enabled():
        return WHY_SETTING_OFF
    return None


def pick_fov(info_fov, last_fov):
    """先信这一帧截图里的视角，没有再用上次的，最后 70；last_fov 惰性调用。"""
    return info_fov or last_fov() or 70.0
