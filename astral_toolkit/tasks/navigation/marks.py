"""路标：增删查、从文字 / 剪贴板导入、/showlocation 记点、热键记点（2026-11-19 从 tasks/navigation.py 按段落拆出来，只搬位置、代码没改）"""

import math
import time

from ...app.hud_state import _note_hud
from ...app import bus
from .base import HERE_WAIT, NavDeps, _HERE, _MARKING, _pos_current, _wp_log
from .search import _place_row, _rt_b6_closing_error


# ---------------------------------------------------------------- 路标管理
def waypoints():
    from ...navigation import navigate as n

    data = n.load()
    out = []
    for p in n.waypoints():
        if n.is_space(p):
            out.append(
                {
                    **_place_row(p),
                    "lat": None,
                    "lon": None,
                    "alt": None,
                    "saved": p.get("saved", ""),
                    "name": p["n"],
                    "system": p["sys"],
                }
            )
            continue
        if p["b"] not in data["bodies"]:
            continue
        lat, lon, r = n.latlon(n.pos(p))
        out.append(
            {
                **_place_row(p),
                "lat": lat,
                "lon": lon,
                "alt": r * 1000 - data["bodies"][p["b"]]["r"],
                "saved": p.get("saved", ""),
                "name": p["n"],
            }
        )
    return out


def waypoint_add(
    deps: NavDeps, /, name="", body="", lat=None, lon=None, alt=0.0, here=False
):
    from ...navigation import navigate as n

    data = n.load()
    if not name.strip():
        return {"error": "需填写路标名称"}
    if here:
        refused = _rt_b6_closing_error()
        if refused:
            return refused
        # 只用 /showlocation 的坐标（不读右上角）：等你在游戏聊天框自己输入 /showlocation（AT 不替你输入）
        _HERE.update(name=name.strip(), until=time.time() + HERE_WAIT)
        if not _MARKING[
            "on"
        ]:  # 热键记路标已经在等 /showlocation：名字交给它，不另起一份（合并后审查）
            _start_here_watch(deps)
        return {
            "pending": True,
            "message": f"切回游戏在聊天框输入 /showlocation 后回车；{HERE_WAIT} 秒内获取到坐标即保存为「{name.strip()}」",
        }
    else:
        body = n._find_body(body, data) if body else None
        if not body:
            return {"error": "无法识别星球名称"}
        b = data["bodies"][body]
        try:
            g = n.from_latlon(float(lat), float(lon), b["r"] / 1000, float(alt or 0))
        except (TypeError, ValueError):
            return {"error": "纬度、经度需为数字"}
        local = g
    n.add_waypoint(name.strip(), body, local)
    return waypoints()


def waypoint_preview(deps: NavDeps, /, text=""):
    """粘贴框里的 /showlocation 结果 → 认出在哪个星球、经纬度、高度（还没保存）；不是坐标返回 error"""
    from ...navigation import navigate as n

    g = n.parse_clip(text or "")
    if not g:
        return {
            "error": "未找到坐标：需粘贴聊天框中 /showlocation 输出的那一行（Coordinates: x:… y:… z:…）"
        }
    data = n.load()
    here = n.locate(g, data=data, use_offset=False)
    if _on_body(here):
        return {
            "ok": True,
            "space": False,
            "body": here["body"],
            "body_zh": n.body_label(here["body"]),
            "lat": round(here["lat"], 4),
            "lon": round(here["lon"], 4),
            "alt": round(here["height_m"]),
            "desc": f"{n.body_label(here['body'])}，纬度 {here['lat']:.3f}°，经度 {here['lon']:.3f}°"
            + (f"，海拔 {here['height_m']:,.0f} m" if n.height_ok(here) else ""),
        }
    system = n.system_of(g, data, **_hints_near(deps, g))
    return {
        "ok": True,
        "space": True,
        "body": "@" + system,
        "body_zh": n.body_label("@" + system),
        "desc": f"太空：{n.body_label('@' + system)} 星系坐标 {tuple(round(v / 1000, 1) for v in g)} km",
    }


def waypoint_from_text(deps: NavDeps, /, name="", text=""):
    """粘贴 /showlocation 的输出新建路标（星球自动认，名字自己起）"""
    from ...navigation import navigate as n

    if not name.strip():
        return {"error": "需填写路标名称"}
    g = n.parse_clip(text or "")
    if not g:
        return {"error": "未找到坐标：需粘贴聊天框中 /showlocation 输出的那一行"}
    desc = _save_here(deps, name.strip(), g)
    _wp_log(
        f"粘贴新建路标「{name.strip()}」：{tuple(round(v / 1000, 3) for v in g)} km → {desc}"
    )
    bus.publish("waypoints", {"changed": True})
    return {"rows": waypoints(), "desc": desc}


def waypoint_delete(name=""):
    from ...navigation.navigate import delete_waypoint

    delete_waypoint(name)
    return waypoints()


def _surface_limit(here):
    """离地多高以内算「在星球上」（跟着星球自转记坐标）；再高就当太空，记星系坐标"""
    return max(100_000, here.get("radius_km", 0) * 1000 * 0.25)


STATION_NEAR_M = 20_000  # 离跟着星球转的站里的点这么近，就算在这个站里（和 transit.site_at 认站用的一样）


def _on_body(here):
    """这个坐标按星球坐标记（跟着星球自转），还是按星系坐标记（太空）。
    离地 _surface_limit 以内算在星球上。再高的，要是就在一个跟着星球转的空间站里，也按星球坐标记：
    派罗的轨道讣闻站离地 429 km、废墟空间站 163 km，都超过界限——2026-11-14 老大在轨道讣闻站记的路标被当成太空点，
    星球一转，路标就以每秒几公里离开"""
    if not here.get("inside"):
        return False
    if here.get("height_m", 0) < _surface_limit(here):
        return True
    from ...navigation import navigate as n

    a = n.pos(here)
    return any(
        not q.get("space")
        and q["b"] == here["body"]
        and math.dist(n.pos(q), a) * 1000 < STATION_NEAR_M
        for q in n.city_places()
    )


def _site_here(deps: NavDeps, g, here, data, system=None):
    """g 在不在一个主城 / 空间站里（2026-11-14 站内自定义点）→ {"city", "area_id", "space", "sys", "desc"}；不在 None。
    在站里记的路标按站内方式带路：米、上下楼、坐电梯。区域先看右上角的 Zone（就是现在的位置时才可信），
    没有就取离得最近的已知点的区域，都认不出就不记区域（只给方向和上下楼，不带坐电梯的步骤）"""
    from ...navigation import navigate as n

    try:
        system = system or n.system_of(g, data, **_hints_near(deps, g))
        s = n.site_at(g, here, None, data, system, hidden=True)
        if not s:
            return None
        q = next(q for q in n.city_places() if q.get("city") == s["site"])
        space = bool(q.get("space"))
        a = tuple(v / 1000 for v in g) if space else n.pos(here)
        st = n.station_lifts().get(s["site"])
        area = None
        if st:
            _t, live, info = _pos_current(deps)
            if live is not None and math.dist(live, g) < 100:
                area = n.zone_kind(str((info or {}).get("inner_zone") or ""), st)
            if area != "hangar" and area not in st["areas"]:
                area = n.site_area_at(s["site"], a)
        name = s["zh"] or s["en"]
        zh = ((st or {}).get("areas") or {}).get(area or "", {}).get("zh") or ""
        return {
            "city": s["site"],
            "area_id": area,
            "space": space,
            "sys": q.get("sys") or system,
            "desc": name + (f" · {zh}" if zh else ""),
        }
    except (
        Exception
    ) as e:  # 认站出错：照老办法记成星球上 / 太空里的点，不丢这个路标；记一笔好查
        _wp_log(f"认站出错，按普通路标记：{e!r}")
        return None


def _hints_near(deps: NavDeps, g, km=100):
    """右上角线索（定星系用）只在 g 就是你现在的位置时才可信：粘贴别人给的坐标、事后补存的原矿坐标，
    线索说的是你现在在哪个星系，不是那个坐标在哪个星系（审查 2026-10-31）"""
    pos = deps.pos
    try:
        _, live, _ = _pos_current(deps)
        if live is None or math.dist(live, g) > km * 1000:
            return {}
        return pos.hints()
    except Exception:
        return {}


def _save_here(deps: NavDeps, name, g, info=None, system=None):
    """在 g（/showlocation 给的星系坐标，米）记一个路标：星球上/贴地记星球坐标，太空或高轨道记星系坐标。返回说明。
    只用 /showlocation 的坐标换算，不掺右上角调试信息（也不用从右上角学来的偏差）。
    system = 记录时就定下的星系（原矿记录），不给就现在判断"""
    from ...navigation import navigate as n

    data = n.load()
    here = n.locate(g, data=data, use_offset=False)
    site = _site_here(deps, g, here, data, system)
    if site and site["space"]:  # 太空里的站（L 点站、星门站）：站不动，记星系坐标
        n.add_space_waypoint(name, site["sys"], g, site=site)
        desc = site["desc"]
    elif site:  # 跟着星球转的站 / 主城：记星球坐标
        n.add_waypoint(name, here["body"], n.pos(here), site=site)
        desc = site["desc"]
    elif _on_body(here):
        n.add_waypoint(name, here["body"], n.pos(here))
        desc = n.body_label(here["body"]) + (
            f"，海拔 {here['height_m']:,.0f} m" if n.height_ok(here) else ""
        )
    else:
        system = system or n.system_of(g, data, **_hints_near(deps, g))
        n.add_space_waypoint(name, system, g)
        desc = f"{n.body_label('@' + system)}"
    _wp_log(f"已记下「{name}」：{desc}，坐标 {tuple(round(v, 1) for v in g)}")
    return desc


def _take_here_name():
    """「用当前位置新建」等着的路标名（过期就不算）"""
    if _HERE["name"] and time.time() < _HERE["until"]:
        name, _HERE["name"] = _HERE["name"], None
        return name
    return None


def _saved(name, desc):
    _note_hud("路标", f"📍 已保存：{name}\n{desc}", 6)
    bus.publish("waypoints", {"changed": True})
    from ...core import run_records

    run_records.record("NAV", "保存路标", ui_tag="NAV")


def _start_here_watch(deps: NavDeps):
    """点了「用当前位置新建」：开 here 会话盯剪贴板，你自己打 /showlocation 也能接住（已经在等就不重开）。
    2026-11-09 起会话由 SessionLoop 跑（deps.here），退出时会停、会等它退"""
    deps.here.start()


def _here_state():
    """here 会话开始时：记下剪贴板里原来的内容（开始等之前的旧坐标不算）"""
    from ...navigation.navigate import read_clipboard

    return {"old": read_clipboard()}


def _here_step(deps: NavDeps, st) -> bool:
    """here 会话的一轮：最多等 1 秒剪贴板出现新坐标，拿到就存成等着的那个名字；
    存完、名字被取走（热键记路标用了）、超时都返回 True，会话自己结束"""
    from ...system.showloc import wait_new_coords

    if not (_HERE["name"] and time.time() < _HERE["until"]):
        if _HERE["name"]:
            _HERE["name"] = None
            _note_hud("路标", "未获取到 /showlocation 坐标，路标未保存", 6)
            _wp_log("等 /showlocation 超时")
        return True
    g, clip = wait_new_coords(st["old"], 1.0)
    if g and _HERE["name"]:
        name = _take_here_name()
        if name:
            _wp_log(f"剪贴板读到 {clip!r}")
            try:
                _saved(name, _save_here(deps, name, g))
            except Exception as e:  # 路标文件读不到 / 坏了：和 mark_here 一样提示，不悄悄结束（审查 2026-10-31）
                _note_hud("路标", f"未保存：{e}", 8)
                _wp_log(f"失败：{e}")
        return True
    return False


def _wait_showloc():
    """等玩家自己在聊天框输入 /showlocation（AT 不替你输入，整改第 4 批）：先在悬浮窗上提示一下"""
    from ...system import showloc

    if (
        not showloc._WAITING.locked()
    ):  # 已经有一份在等：不再挂提示，showlocation 会马上说「已经在等」（合并后审查）
        _note_hud(
            "定位",
            f"请在游戏聊天框输入 /showlocation 后回车（{showloc.TYPE_WAIT} 秒内）",
            showloc.TYPE_WAIT,
        )  # 等多久就挂多久（第 4 批审查）
    g, why = showloc.showlocation(log=_wp_log)
    if g:
        _note_hud(
            "定位", "", 1
        )  # 拿到坐标：提示马上收起，免得以为没定上位（合并后审查）
    return g, why


def mark_here(deps: NavDeps, /):
    refused = _rt_b6_closing_error()
    if refused:
        return refused
    """游戏里按热键：等你在聊天框输入 /showlocation，读剪贴板里的坐标记成路标（AT 不替你输入）。
    点过「用当前位置新建」就用那里填的名字，否则按时间和地点起名"""
    if _HERE["name"] and time.time() < _HERE["until"] and deps.here.running():
        # 「用当前位置新建」已经在盯剪贴板：这里再等一份，输一次 /showlocation 会记成两个路标（第 4 批审查）
        _note_hud(
            "路标",
            f"已经在等你输入 /showlocation（保存为「{_HERE['name']}」），在聊天框输入后回车即可",
            8,
        )
        return {"pending": True}
    _MARKING["on"] = True
    try:
        g, why = _wait_showloc()
    finally:
        _MARKING["on"] = False
    if not g:
        _note_hud("路标", f"未保存：{why}", 8)
        _wp_log(f"失败：{why}")
        return {"error": why}
    name = _take_here_name() or time.strftime("路标 %m-%d %H:%M:%S")
    try:
        desc = _save_here(deps, name, g)
    except Exception as e:  # 路标文件读不到 / 坏了：游戏里也要看得到（二审 2026-10-28）
        _note_hud("路标", f"未保存：{e}", 8)
        _wp_log(f"失败：{e}")
        return {"error": str(e)}
    _saved(name, desc)
    return {"name": name, "where": desc}
