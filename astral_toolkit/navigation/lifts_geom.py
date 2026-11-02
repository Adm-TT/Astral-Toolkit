"""空间站电梯数据用到的几何小函数（纯函数）：四元数旋转、电梯门坐标换算、站内点离电梯门的最远距离。
生成 data/station_lifts.json 的数据构建脚本（在仓库外）直接从这里 import，只有这一份实现；测试测的就是它用的这份。"""

import math

AREA_GATE_M = 300  # 站里的点离本区域任一电梯门都超过这么远：这个站的数据不可信，标 ok=False（导航不分段）


def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def qmul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    )


def rot(q, v):
    w, x, y, z = q
    return qmul(qmul(q, (0, *v)), (w, -x, -y, -z))[1:]


def tm_local(mp, mq, rel):
    """TransitManager 的 destinationPos / gatewayPos（在它自己的坐标系里）→ 站局部坐标（米）：先转它的朝向再加它的位置"""
    return add(mp, rot(mq, rel))


def worst_place_gate(places, pmap, lifts):
    """站里的点离本区域任一电梯门的最近距离，取最大的（米）；坐标都是千米"""
    area_gates = {}
    for ln in lifts:
        for s in ln["stops"]:
            if s.get("area") and s["area"] != "hangar":
                area_gates.setdefault(s["area"], []).extend(s["gates"])
    worst = 0.0
    for p in places:
        a = pmap.get(p["id"])
        if area_gates.get(a):
            worst = max(
                worst,
                min(math.dist((p["x"], p["y"], p["z"]), g) for g in area_gates[a])
                * 1000,
            )
    return worst
