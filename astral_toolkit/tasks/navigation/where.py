"""位置与区域感知：现在在哪、在哪个产矿区（2026-11-19 从 tasks/navigation.py 按段落拆出来，只搬位置、代码没改）"""

import time

from .base import AREA_MAX_AGE, NavDeps, _AREA, _WHERE, _pos_current, _pos_latest


# ---------------------------------------------------------------- 位置与区域感知
def _where_now(deps: NavDeps):
    """玩家现在在星球表面附近（"ground"）还是太空（"space"），不知道返回 None。
    信号值不在飞船矿表里时才用（地面的 3,000 是手采矿，太空的 3,000 是残骸）。
    需要右上角调试信息（r_DisplayInfo 2）；结果记 60 秒，读不到 20 秒内不再试"""
    import re
    from ...navigation import navigate as n

    pos = deps.pos
    now = time.time()
    if now - _WHERE["t"] < 60:
        return _WHERE["v"]
    t, g, info = _pos_latest(deps)
    if not g or now - t > 60:
        if now - _WHERE["tried"] < 20:
            return None
        _WHERE["tried"] = now
        try:
            rd = pos.read_now(force=True)
        except Exception:
            return None
        info = rd.info or {}
        if not info.get("global") or now - rd.ok_at > 5:
            return None
        g = tuple(info["global"])
    info = info or {}
    if re.search(r"asteroid", info.get("location") or "", re.I):
        v = "space"  # 小行星带
    else:
        try:
            here = n.locate(
                g,
                when=info.get("t"),
                local=info.get("local"),
                zone=info.get("zone"),
                local_ok=info.get("local_ok"),
            )
        except Exception:
            return None
        v = (
            "ground"
            if here.get("inside") and here.get("height_m", 1e12) < 50_000
            else "space"
        )
    _WHERE.update(t=now, v=v)
    return v


def _area_now(deps: NavDeps):
    """玩家现在在哪个产矿区（mining_area.area），认不出返回 None。雷达信号只报当地会刷的矿（2026-10-27 用户要求
    「位置和矿种对得上号」）。只用后台 10 秒内读到的位置；星系必须是右上角线索定下的（只靠坐标猜的不算，
    三个星系坐标系重叠，猜错会把真矿判成「不刷」，2026-10-27 补审）。同一次读数只算一次"""
    from ...navigation import navigate as n
    from ...mining import mining_area

    now = time.time()
    t, g, info = _pos_current(deps)
    if not g or now - t > AREA_MAX_AGE:
        return None
    info = info or {}
    key = (
        tuple(g),
        info.get("location"),
        info.get("zone"),
        info.get("solar_id"),
        mining_area.rocks_stamp(),
    )  # 位置或地名、区域、星系编号、石头表变了才重算
    if _AREA["key"] == key:
        return _AREA["v"]
    v = None
    info = info or {}
    try:
        sysname, sure = n.system_info(
            g,
            zone=info.get("zone") or "",
            location=info.get("location") or "",
            solar_id=info.get("solar_id") or "",
        )
        here = n.locate(
            g,
            when=info.get("t"),
            local=info.get("local"),
            zone=info.get("zone"),
            local_ok=info.get("local_ok"),
        )
        body = here.get("body")
        ground = bool(
            here.get("inside")
            and here.get("height_m", 1e12) < 50_000
            and (n.load()["bodies"].get(body) or {}).get("sys") == sysname
        )
        if sure or ground:
            v = mining_area.area(
                g,
                sysname,
                body=body,
                ground=ground,
                location=info.get("location") or "",
                zone=info.get("zone") or "",
            )
    except Exception:
        v = None
    _AREA.update(key=key, v=v)
    return v
