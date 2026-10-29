"""路标、折跃光环与导航业务任务模块（Task: Navigation & Halo）

从 app/services.py 中解耦出来，专职处理：
1. 地点搜索、最近地点推荐、站点识别与导航路线规划；
2. 实时/手动定位模式切换、雷达信号重命名；
3. 路标增删改查、剪贴板坐标导入与 /showlocation 实时抓取；
4. 小行星带（Aaron Halo）航线计算、断开距离监控与 HUD 联动核对；
5. 原矿扫描记录及导航追溯。
"""
import math
import os
import re
import threading
import time

from ..app import bus

# ---------------------------------------------------------------- 基础状态与常量
_places = {}

try:
    from ..data_pack import CACHE_HOOKS as _CACHE_HOOKS
    _CACHE_HOOKS.append(_places.clear)
except Exception:
    pass

POS_FRESH = 120          # 「用当前位置」：位置最多是多少秒前读到的
_WHERE = {"t": 0.0, "v": None, "tried": 0.0}

_AREA = {"key": None, "v": None}
AREA_MAX_AGE = 10         # 位置超过 10 秒没更新就不判断产矿区（不过滤），刚跳跃、读不到时宁可不过滤

HERE_WAIT = 90            # 点「用当前位置新建」后等 /showlocation 坐标多少秒
_HERE = {"name": None, "until": 0.0, "thread": None}

# 游戏里的热键：(设置名, 默认键, 名字)。撞键时排在前面的生效（顺序和以前一样：物品识别 > 记路标 > 一键定位 > 问题反馈 > 采矿助手 > 盘点）
HOTKEYS = [
    ("trade_capture_key", "F8", "物品识别"),
    ("mark_key", "", "记录路标"),
    ("fix_key", "", "一键定位"),
    ("report_key", "F10", "问题反馈"),
    ("live_key", "F5", "采矿助手开关"),
    ("count_key", "F6", "盘点"),
    ("ore_key", "", "原矿记录"),
]

_HALO = {"plan": None, "sess": 0, "seen": None, "last": None, "ev": threading.Event(), "lock": threading.Lock()}

QT_SPEED = 50_000          # 米/秒：比这快就是在量子跳跃（普通飞行最快一千多米每秒）
LIVE_STALE = 3.0           # 右上角多少秒没读到才算读不到（这时才用玩家自己输的 /showlocation）

DI_HELP = "未检测到右上角位置信息：在游戏中按 ~ 打开控制台，输入 r_DisplayInfo 2 后回车"


# ---------------------------------------------------------------- 依赖与辅助
def _services():
    from ..app import services
    return services


def api(fn):
    """API 装饰器：在独立任务模块中保留标记，若 services.API 存在可协助注册"""
    try:
        from ..app import services
        if hasattr(services, "API"):
            services.API[fn.__name__] = fn
    except Exception:
        pass
    return fn


def _hud():
    try:
        return _services()._hud()
    except Exception:
        class _DummyHud:
            def set(self, *a, **k): pass
            def clear(self, *a, **k): pass
            def marker(self, *a, **k): pass
        return _DummyHud()


def _note_hud(section, text, secs=6):
    try:
        _services()._note_hud(section, text, secs)
    except Exception:
        pass


def _off(feature):
    try:
        return _services()._off(feature)
    except Exception:
        return False


class _PosProxy:
    def __getattr__(self, name):
        return getattr(_services()._pos, name)


_pos = _PosProxy()


class _NavProxy:
    def __getattr__(self, name):
        return getattr(_services()._nav, name)


_nav = _NavProxy()


class _GameEventsProxy:
    def __getattr__(self, name):
        return getattr(_services()._game_events, name)


_game_events = _GameEventsProxy()


class _OreLastProxy(dict):
    def __getitem__(self, item):
        try:
            return _services()._ORE_LAST[item]
        except Exception:
            return None

    def get(self, item, default=None):
        try:
            return _services()._ORE_LAST.get(item, default)
        except Exception:
            return default


_ORE_LAST = _OreLastProxy()


# ---------------------------------------------------------------- 导航与地点搜索
def _place_row(p):
    from ..navigate import label, body_label, TYPE_ZH, QT_ZH
    key = f"{p['b']}|{p['t']}|{p.get('id') or p['n']}"     # 城里同名地点靠 id 区分（Codex 2026-10-27）
    _places[key] = p
    typ = (p.get("area") or p.get("city_zh") or TYPE_ZH["City"]) if p["t"] == "City" else TYPE_ZH.get(p["t"], p["t"])
    return {"key": key, "label": label(p), "body": body_label(p["b"]), "type": typ,
            "qt": QT_ZH.get(p["qt"], "信标未确认"), "has_qt": p["qt"] == 1, "waypoint": p["t"] == "Waypoint",
            "space": bool(p.get("space")), "city": p["t"] == "City"}


@api
def nav_search(q=""):
    from ..navigate import search as s
    hits, total = s(q, limit=30)
    return {"rows": [_place_row(p) for p in hits], "total": total}


@api
def nav_near(kind=""):
    """导航页「医院 / 空港 / 买船」：知道当前位置就直接导航到最近的那个，列表按远近排；
    位置不知道就只列出来让玩家自己挑（2026-10-27 老大定）"""
    from .. import navigate as n
    if kind not in n.NEAR_KINDS and kind not in n.SITE_KINDS:
        return {"error": "不支持的分类"}
    data = n.load()
    t, g, info = _pos.current
    info = info or {}
    fresh = bool(g) and time.time() - t < POS_FRESH
    here, system, when, sure = None, "", None, False
    if fresh:
        when = info.get("t")
        try:
            here = n.locate(g, when=when, local=info.get("local"), zone=info.get("zone"), local_ok=info.get("local_ok"))
            # 星系线索用这份位置自己带的（hints 只给 5 秒内的，可能已经过期）；没把握就只列不自动走（二审 2026-10-27）
            system, sure = n.system_info(g, data, **{k: info.get(k) or "" for k in ("zone", "location", "solar_id")})
        except Exception:
            here = None
        if here and here.get("inside"):                     # 站在星球上：星系就是这颗星球的——但右上角明写了别的星系时以它为准（复审 2026-10-27）
            b = data["bodies"].get(here.get("body"))
            if b and (not sure or b["sys"] == system):
                system, sure = b["sys"], True
    site = n.site_at(g, here, when, data, system) if fresh else None     # 站内识别也核对星系（二审 2026-10-27）
    if kind in n.SITE_KINDS and kind not in n.NEAR_KINDS:     # 主城 / 空间站里才有的分类：只找这里的
        if not site:
            return {"rows": [], "total": 0, "started": None, "error": "不在主城或空间站内"}
        hits = n.site_nearest(site["site"], kind, g, when, data, here)      # 星系只是猜的：只列出来，不自动开始（复审 2026-10-27）
    else:
        hits = n.nearest(kind, g if fresh else None, system, when, data, here)
    rows = []
    for d, p in hits[:40]:
        r = _place_row(p)
        r["dist"] = d
        if p.get("t") == "City" and p.get("city_zh"):          # 跨城列出来时分得清是哪个城
            r["label"] = f"{p['city_zh']} · {r['label']}"
        rows.append(r)
    if fresh and sure and rows and rows[0]["dist"] is not None and n.target_system(hits[0][1], data) == system:
        _nav.start(_places[rows[0]["key"]])
        return {"rows": rows, "total": len(rows), "started": rows[0]["key"]}
    return {"rows": rows, "total": len(rows), "started": None}


@api
def nav_site():
    """现在在哪个主城 / 空间站里、这里有哪些分类（导航页那排按钮，2026-10-27）；不在就 site=None"""
    from .. import navigate as n
    t, g, info = _pos.current
    info = info or {}
    if not g or time.time() - t > POS_FRESH:
        return {"site": None, "all": list(n.SITE_KINDS)}
    try:
        data = n.load()
        here = n.locate(g, when=info.get("t"), data=data, local=info.get("local"), zone=info.get("zone"),
                        local_ok=info.get("local_ok"), record=False)
        system, _sure = n.system_info(g, data, **{k: info.get(k) or "" for k in ("zone", "location", "solar_id")})
        s = n.site_at(g, here, info.get("t"), data, system)
    except Exception:
        s = None
    if not s:
        return {"site": None, "all": list(n.SITE_KINDS)}
    name = f"{s['zh']}（{s['en']}）" if s["zh"] and s["zh"] != s["en"] else s["en"]
    return {"site": s["site"], "name": name, "kinds": s["kinds"], "all": list(n.SITE_KINDS)}


@api
def nav_plan(key=""):
    from ..navigate import load, latlon, pos, approaches, label, compass
    p = _places.get(key)
    if not p:
        return {"error": "未找到此地点，需重新搜索"}
    data = load()
    if p.get("space"):
        from ..navigate import space_landmarks
        t = (p["x"], p["y"], p["z"])
        marks = sorted(((math.dist(m[1], t), m[0]) for m in space_landmarks(p["sys"], data)))[:3]
        return {**_place_row(p), "lat": None, "lon": None, "alt": None, "system": p["sys"],
                "routes": [{"kind": "参照点", "name": name, "surface": d, "direct": d, "bearing": None, "compass": ""}
                           for d, name in marks]}
    lat, lon, r = latlon(pos(p))
    b = data["bodies"][p["b"]]
    if p.get("t") == "City":                       # 城里：不给量子跳的参照点（Codex 2026-10-27）
        return {**_place_row(p), "city": True, "city_zh": p.get("city_zh", ""), "area": p.get("area", ""),
                "cat": p.get("cat", ""), "lat": lat, "lon": lon, "alt": r * 1000 - b["r"], "routes": []}
    routes = [{"kind": "轨道标记" if q["t"] == "OM" else "信标", "name": label(q), "surface": ds, "direct": d3,
               "bearing": brg, "compass": compass(brg)} for d3, ds, brg, q in approaches(p, data)]
    return {**_place_row(p), "lat": lat, "lon": lon, "alt": r * 1000 - b["r"], "routes": routes}


@api
def nav_start(key=""):
    p = _places.get(key)
    if not p:
        return {"error": "未找到此地点，需重新搜索"}
    _nav.start(p)
    return {"ok": True}


@api
def nav_mode(mode="auto"):
    """导航页的开关：实时定位（ground / auto）/ 手动定位（space，只用 /showlocation）；正在导航就按新方式重新开始"""
    from .. import settings
    if mode not in ("auto", "ground", "space"):
        return {"error": "导航方式仅支持 实时定位 / 手动定位"}
    settings.update(nav_mode=mode)
    t = _nav.target
    if t:
        _nav.start(t)
    return {"mode": mode, "space": _nav.space_mode if t else None}


@api
def sig_name(value=0, name=""):
    """给雷达信号起名记下（下次认到这个数直接显示）；名字空 = 删掉"""
    from ..signals import set_my_signature
    try:
        v = int(value)
    except (TypeError, ValueError):
        return {"error": "信号值需为数字"}
    if not 100 <= v <= 10_000_000:
        return {"error": "信号值不对"}
    return {"mine": set_my_signature(v, name)}


@api
def sig_names():
    from ..signals import my_signatures
    return {"mine": my_signatures()}


@api
def nav_stop():
    _nav.stop()
    return {"ok": True}


@api
def nav_refresh():
    _nav.refresh()
    return {"ok": True}


# ---------------------------------------------------------------- 路标管理
@api
def waypoints():
    from .. import navigate as n
    data = n.load()
    out = []
    for p in n.waypoints():
        if n.is_space(p):
            out.append({**_place_row(p), "lat": None, "lon": None, "alt": None, "saved": p.get("saved", ""),
                        "name": p["n"], "system": p["sys"]})
            continue
        if p["b"] not in data["bodies"]:
            continue
        lat, lon, r = n.latlon(n.pos(p))
        out.append({**_place_row(p), "lat": lat, "lon": lon, "alt": r * 1000 - data["bodies"][p["b"]]["r"],
                    "saved": p.get("saved", ""), "name": p["n"]})
    return out


@api
def waypoint_add(name="", body="", lat=None, lon=None, alt=0.0, here=False):
    from .. import navigate as n
    data = n.load()
    if not name.strip():
        return {"error": "需填写路标名称"}
    if here:
        # 只用 /showlocation 的坐标（不读右上角）：等你在游戏里按 F7（天枢替你打 /showlocation）或自己打
        _HERE.update(name=name.strip(), until=time.time() + HERE_WAIT)
        _start_here_watch()
        mk = settings_key("mark_key", "")
        how = f"切回游戏按 {mk}（AT 自动输入 /showlocation），或" if mk else "切回游戏"
        return {"pending": True,
                "message": f"{how}在聊天框输入 /showlocation 后回车；{HERE_WAIT} 秒内获取到坐标即保存为「{name.strip()}」"}
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


@api
def waypoint_preview(text=""):
    """粘贴框里的 /showlocation 结果 → 认出在哪个星球、经纬度、高度（还没保存）；不是坐标返回 error"""
    from .. import navigate as n
    g = n.parse_clip(text or "")
    if not g:
        return {"error": "未找到坐标：需粘贴聊天框中 /showlocation 输出的那一行（Coordinates: x:… y:… z:…）"}
    data = n.load()
    here = n.locate(g, data=data, use_offset=False)
    if here.get("inside") and here.get("height_m", 0) < _surface_limit(here):
        return {"ok": True, "space": False, "body": here["body"], "body_zh": n.body_label(here["body"]),
                "lat": round(here["lat"], 4), "lon": round(here["lon"], 4), "alt": round(here["height_m"]),
                "desc": f"{n.body_label(here['body'])}，纬度 {here['lat']:.3f}°，经度 {here['lon']:.3f}°，海拔 {here['height_m']:,.0f} m"}
    system = n.system_of(g, data, **_pos.hints())
    return {"ok": True, "space": True, "body": "@" + system, "body_zh": n.body_label("@" + system),
            "desc": f"太空：{n.body_label('@' + system)} 星系坐标 {tuple(round(v / 1000, 1) for v in g)} km"}


@api
def waypoint_from_text(name="", text=""):
    """粘贴 /showlocation 的输出新建路标（星球自动认，名字自己起）"""
    from .. import navigate as n
    if not name.strip():
        return {"error": "需填写路标名称"}
    g = n.parse_clip(text or "")
    if not g:
        return {"error": "未找到坐标：需粘贴聊天框中 /showlocation 输出的那一行"}
    desc = _save_here(name.strip(), g)
    _wp_log(f"粘贴新建路标「{name.strip()}」：{tuple(round(v / 1000, 3) for v in g)} km → {desc}")
    bus.publish("waypoints", {"changed": True})
    return {"rows": waypoints(), "desc": desc}


@api
def waypoint_delete(name=""):
    from ..navigate import delete_waypoint
    delete_waypoint(name)
    return waypoints()


# ---------------------------------------------------------------- 位置与区域感知
def _where_now():
    """玩家现在在星球表面附近（"ground"）还是太空（"space"），不知道返回 None。
    信号值不在飞船矿表里时才用（地面的 3,000 是手采矿，太空的 3,000 是残骸）。
    需要右上角调试信息（r_DisplayInfo 2）；结果记 60 秒，读不到 20 秒内不再试"""
    import re
    from .. import navigate as n
    now = time.time()
    if now - _WHERE["t"] < 60:
        return _WHERE["v"]
    t, g, info = _pos.latest
    if not g or now - t > 60:
        if now - _WHERE["tried"] < 20:
            return None
        _WHERE["tried"] = now
        try:
            _pos.reader.poll(force=True)
        except Exception:
            return None
        ok_at, info = _pos.reader.snapshot()
        info = info or {}
        if not info.get("global") or now - ok_at > 5:
            return None
        g = info["global"]
    info = info or {}
    if re.search(r"asteroid", info.get("location") or "", re.I):
        v = "space"                       # 小行星带
    else:
        try:
            here = n.locate(g, when=info.get("t"), local=info.get("local"), zone=info.get("zone"),
                            local_ok=info.get("local_ok"))
        except Exception:
            return None
        v = "ground" if here.get("inside") and here.get("height_m", 1e12) < 50_000 else "space"
    _WHERE.update(t=now, v=v)
    return v


def _area_now():
    """玩家现在在哪个产矿区（mining_area.area），认不出返回 None。雷达信号只报当地会刷的矿（2026-10-27 用户要求
    「位置和矿种对得上号」）。只用后台 10 秒内读到的位置；星系必须是右上角线索定下的（只靠坐标猜的不算，
    三个星系坐标系重叠，猜错会把真矿判成「不刷」，Codex 2026-10-27 补审）。同一次读数只算一次"""
    from .. import navigate as n, mining_area
    now = time.time()
    t, g, info = _pos.current
    if not g or now - t > AREA_MAX_AGE:
        return None
    info = info or {}
    key = (tuple(g), info.get("location"), info.get("zone"), info.get("solar_id"),
           mining_area.rocks_stamp())          # 位置或地名、区域、星系编号、石头表变了才重算
    if _AREA["key"] == key:
        return _AREA["v"]
    v = None
    info = info or {}
    try:
        sysname, sure = n.system_info(g, zone=info.get("zone") or "", location=info.get("location") or "",
                                      solar_id=info.get("solar_id") or "")
        here = n.locate(g, when=info.get("t"), local=info.get("local"), zone=info.get("zone"),
                        local_ok=info.get("local_ok"))
        body = here.get("body")
        ground = bool(here.get("inside") and here.get("height_m", 1e12) < 50_000
                      and (n.load()["bodies"].get(body) or {}).get("sys") == sysname)
        if sure or ground:
            v = mining_area.area(g, sysname, body=body, ground=ground,
                                 location=info.get("location") or "", zone=info.get("zone") or "")
    except Exception:
        v = None
    _AREA.update(key=key, v=v)
    return v


# ---------------------------------------------------------------- 热键与冲突检测
def _hotkey_values(cfg):
    """→ [(键, 名字, 设置名)]，按生效顺序；没设的键是空字符串"""
    return [(str(cfg.get(n, d) or "").strip().upper(), lab, n) for n, d, lab in HOTKEYS]     # 设成空 = 不绑（不回到默认键）


def hotkey_conflicts(cfg=None):
    """热键撞了（settings.json 手改的、旧版本留下的）：只有排在前面的生效，要明确告诉玩家哪个失效"""
    if cfg is None:
        try:
            from .. import settings
            cfg = settings.load()
        except Exception:
            cfg = {}
    out, seen = [], {}
    for key, lab, name in _hotkey_values(cfg):
        if not key:
            continue
        if key in seen:
            tail = "，或在聊天框输入 /showlocation" if name == "fix_key" else ""
            out.append(f"{key} 同时用于「{seen[key]}」和「{lab}」，按下只执行「{seen[key]}」：需在设置页更换「{lab}」的按键{tail}")
        else:
            seen[key] = lab
    return out


def fix_key_hint():
    """导航面板上的定位提示：热键能用就说按哪个键，被占用了就说自己输 /showlocation"""
    key = settings_key("fix_key", "")
    bad = [w for w in hotkey_conflicts() if "一键定位" in w]
    if bad:
        return key, bad[0]
    return key, (f"一键定位：按 {key}（或输入 /showlocation）" if key else "在聊天框输入 /showlocation 定位")


def settings_key(k, default):
    try:
        from .. import settings
        return settings.load().get(k) or default
    except Exception:
        return default


# ---------------------------------------------------------------- 路标保存与快捷记录
def _wp_log(msg):
    try:
        from .. import paths
        with open(paths.log("nav_log.txt"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%F %T')} 路标 {msg}\n")
    except OSError:
        pass


def _surface_limit(here):
    """离地多高以内算「在星球上」（跟着星球自转记坐标）；再高就当太空，记星系坐标"""
    return max(100_000, here.get("radius_km", 0) * 1000 * 0.25)


def _save_here(name, g, info=None):
    """在 g（/showlocation 给的星系坐标，米）记一个路标：星球上/贴地记星球坐标，太空或高轨道记星系坐标。返回说明。
    只用 /showlocation 的坐标换算，不掺右上角调试信息（也不用从右上角学来的偏差）"""
    from .. import navigate as n
    data = n.load()
    here = n.locate(g, data=data, use_offset=False)
    if here.get("inside") and here.get("height_m", 0) < _surface_limit(here):
        n.add_waypoint(name, here["body"], n.pos(here))
        desc = f"{n.body_label(here['body'])}，海拔 {here['height_m']:,.0f} m"
    else:
        system = n.system_of(g, data, **_pos.hints())
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


def _start_here_watch():
    """点了「用当前位置新建」：盯剪贴板，你自己打 /showlocation 也能接住"""
    if _HERE["thread"] and _HERE["thread"].is_alive():
        return

    def run():
        from ..navigate import read_clipboard
        from ..showloc import wait_new_coords
        old = read_clipboard()
        while _HERE["name"] and time.time() < _HERE["until"]:
            g, clip = wait_new_coords(old, 1.0)
            if g and _HERE["name"]:
                name = _take_here_name()
                if name:
                    _wp_log(f"剪贴板读到 {clip!r}")
                    _saved(name, _save_here(name, g))
                return
        if _HERE["name"]:
            _HERE["name"] = None
            _note_hud("路标", "未获取到 /showlocation 坐标，路标未保存", 6)
            _wp_log("等 /showlocation 超时")

    _HERE["thread"] = threading.Thread(target=run, daemon=True, name="here-watch")
    _HERE["thread"].start()


def mark_here():
    """游戏里按热键（默认 F7）：替你在聊天框输入 /showlocation，读剪贴板里的坐标记成路标。
    点过「用当前位置新建」就用那里填的名字，否则按时间和地点起名"""
    from ..showloc import showlocation
    g, why = showlocation(log=_wp_log)
    if not g:
        _note_hud("路标", f"未保存：{why}", 8)
        _wp_log(f"失败：{why}")
        return {"error": why}
    name = _take_here_name() or time.strftime("路标 %m-%d %H:%M:%S")
    try:
        desc = _save_here(name, g)
    except Exception as e:                        # 路标文件读不到 / 坏了：游戏里也要看得到（二审 2026-10-28）
        _note_hud("路标", f"未保存：{e}", 8)
        _wp_log(f"失败：{e}")
        return {"error": str(e)}
    _saved(name, desc)
    return {"name": name, "where": desc}


# ---------------------------------------------------------------- 原矿记录
def _coord_desc(g):
    """/showlocation 坐标 → 「戴玛，海拔 1,234 m」这种说明（只说明，不记路标）"""
    from .. import navigate as n
    data = n.load()
    here = n.locate(g, data=data, use_offset=False)
    if here.get("inside") and here.get("height_m", 0) < _surface_limit(here):
        return f"{n.body_label(here['body'])}，海拔 {here['height_m']:,.0f} m"
    return n.body_label("@" + n.system_of(g, data, **_pos.hints()))


@api
def ore_record(here=False):
    """记下最近这块矿。here=True（游戏里按热键）：顺便替玩家输 /showlocation，把坐标一起记下；窗口里点的不记坐标"""
    from .. import ore_log
    view = _ORE_LAST.get("view")
    if not view:
        _note_hud("原矿", "暂无扫描结果，先扫描矿石", 5)
        return {"error": "暂无扫描结果，先在游戏中扫描矿石"}
    rec = ore_log.from_view(view)
    where = ""
    if here:
        try:
            from ..showloc import showlocation
            g, why = showlocation(log=_wp_log)
        except Exception as e:
            g, why = None, str(e)
        if g:
            rec["coords"] = [round(v, 1) for v in g]
            try:
                rec["where"] = where = _coord_desc(g)
            except Exception:
                rec["where"] = ""
        else:
            rec["where_err"] = why or "未获取到坐标"
    try:
        rec = ore_log.add(rec)
    except Exception as e:
        _note_hud("原矿", f"未记录：{e}", 8)
        return {"error": str(e)}
    _note_hud("原矿", f"已记录：{rec['rock']}" + (f"｜{where}" if where else "｜未获取到坐标" if here else ""), 5)
    bus.publish("ore_log", {"changed": True})
    return rec


@api
def ore_list():
    from .. import ore_log
    rows = list(reversed(ore_log.load()))
    return {"rows": rows, "rocks": sorted({r.get("rock") or "?" for r in rows})}


@api
def ore_delete(id=""):
    from .. import ore_log
    rec = ore_log.delete(id)
    if not rec:
        return {"error": "此记录已不存在"}
    bus.publish("ore_log", {"changed": True})
    return rec


@api
def ore_restore(rec=None):
    from .. import ore_log
    rec = ore_log.restore(rec)
    bus.publish("ore_log", {"changed": True})
    return rec


@api
def ore_go(id=""):
    """「去这里」：把这条记录的坐标记成路标（同一条只记一次），然后开始导航"""
    from .. import ore_log
    rec = next((r for r in ore_log.load() if r.get("id") == id), None)
    if not rec:
        return {"error": "此记录已不存在"}
    if not rec.get("coords"):
        return {"error": "此记录没有坐标"}
    name = rec.get("waypoint")
    rows = {w["name"]: w for w in waypoints()}
    if not name or name not in rows:
        name = f"原矿 {rec.get('rock') or ''} {(rec.get('at') or '')[5:16]}".strip()
        _save_here(name, tuple(rec["coords"]))
        ore_log.update(id, waypoint=name)
        bus.publish("waypoints", {"changed": True})
        rows = {w["name"]: w for w in waypoints()}
    w = rows.get(name)
    if not w:
        return {"error": "路标保存失败，详情见导航页"}
    r = nav_start(w["key"])
    if r.get("error"):
        return r
    return {"ok": True, "name": name}


# ---------------------------------------------------------------- 小行星带（Aaron Halo）导航与一键定位
@api
def halo_options():
    """小行星带页要的选项：10 条带、出发点、量子引擎、上次选的引擎、悬浮窗上正挂着的方案"""
    from .. import halo
    return {"bands": [halo.band_row(r) for r in halo.BANDS],
            "points": [{"key": k, "label": halo.point_zh(k)} for k in halo.points()],
            "qds": [{"name": f"{a} ({b})", "speed": v} for a, b, v in halo.QDS],
            "qd": settings_key("halo_qd", "Atlas (S1)"), "plan": _HALO["plan"]}


@api
def halo_routes(frm="ARC-L1", band=5, qd=""):
    """从 frm 出发、能在第 band 带断开的所有目标"""
    from .. import halo, settings
    try:
        row = halo.band(band)
    except (TypeError, ValueError):
        return {"error": "带号需为 1–10"}
    pts = halo.points()
    if frm not in pts:
        return {"error": f"未找到出发点 {frm}"}
    if qd:
        settings.update(halo_qd=qd)
    speed = halo.qd_speed(qd or settings_key("halo_qd", "Atlas (S1)"))
    return {"from": frm, "band": halo.band_row(row), "speed": speed, "rows": halo.routes(frm, band, speed, pts)}


@api
def halo_pin(frm="", to="", band=5, qd=""):
    """把这条路线挂到悬浮窗：游戏里看着 HUD 剩余距离断开；断开后按一键定位键（或自己输 /showlocation）核对在不在带里"""
    from .. import halo
    from .. import navigate as n
    try:
        r = halo.route(frm, to, band, halo.qd_speed(qd or settings_key("halo_qd", "Atlas (S1)")))
    except (TypeError, ValueError):
        r = None
    if not r:
        return {"error": "此航线不穿过该带"}
    r["text"] = halo.plan_text(r) + "\n退出量子后自动核对是否在带内"
    ev = threading.Event()
    with _HALO["lock"]:
        _HALO["ev"].set()                         # 旧方案的剪贴板监听停掉
        _HALO["sess"] += 1
        sess = _HALO["sess"]
        _HALO.update(plan=r, last=None, ev=ev)
        try:
            _HALO["seen"] = n.read_clipboard()     # 挂上之前剪贴板里的旧坐标不算
        except Exception:
            _HALO["seen"] = None
        _hud().set("小行星带", r["text"])
    threading.Thread(target=_halo_watch, args=(sess, ev), daemon=True, name="halo").start()
    _wp_log(f"小行星带方案：{frm} → {to} 第{band}带，剩 {r['dropout']} Gm 断开")
    return r


@api
def halo_unpin():
    with _HALO["lock"]:
        _HALO["ev"].set()
        _HALO["sess"] += 1
        _HALO.update(plan=None, last=None)
        _hud().clear("小行星带")
    return {"ok": True}


def _halo_watch(sess, ev):
    """挂着方案时：读右上角的实时坐标自动核对（每秒一次）；读不到时玩家自己在聊天框输 /showlocation 也能核对
    （/showlocation 只在必要时用，2026-10-27 用户定；太空导航进行中时剪贴板归导航管）"""
    from .. import navigate as n
    seen_live, live_at, prev, arr = None, 0.0, None, _game_events.arrived_at
    while not ev.is_set():
        try:
            if _game_events.arrived_at != arr:           # 游戏日志说量子到了：马上核对，不用等测速（2026-10-27）
                arr, prev, live_at = _game_events.arrived_at, None, 0.0
            t, g_live, _ = _pos.current          # 每次读到都更新（停着不动也有新的一份），latest 只在坐标变了才换（Codex 2026-10-27）
            if g_live and t != seen_live and time.time() - t < 3 and not _off("halo_auto"):
                seen_live = t
                fast = prev and t > prev[0] and math.dist(g_live, prev[1]) / (t - prev[0]) > QT_SPEED
                prev = (t, g_live)
                if not fast and time.time() - live_at >= 1.0:       # 量子途中（每秒几万公里）不核对，等断开
                    live_at = time.time()
                    halo_check(g_live, None, sess)
            clip = n.read_clipboard()
            g = n.parse_clip(clip)
            if g and clip != _HALO["seen"] and not (_nav.target and _nav.space_mode):
                halo_check(g, clip, sess)
        except Exception:
            pass
        ev.wait(0.3)


def halo_check(g, clip=None, sess=None):
    """拿到 /showlocation 坐标：离恒星多远、在不在要去的那条带里。
    F9 和剪贴板监听可能拿到同一份坐标：查重、发布在同一把锁里；方案已取下或换了就丢掉"""
    from .. import halo
    with _HALO["lock"]:
        p = _HALO["plan"]
        if not p or (sess is not None and sess != _HALO["sess"]):
            return None
        if clip is not None and clip == _HALO["seen"] and _HALO["last"]:
            return _HALO["last"]
        if clip is not None:
            _HALO["seen"] = clip
        w = halo.where(g)
        w["text"] = halo.where_text(w, p["band"])
        _HALO["last"] = w
        _hud().set("小行星带", p["text"] + "\n" + w["text"])      # 退出距离、安全区间一直留着（Codex 2026-10-27：自动核对不能把它盖掉）
        bus.publish("halo", w)
    _wp_log(f"小行星带核对：{w['text']}")
    return w


def fix_here():
    """游戏里按一键定位热键（默认 F9）：导航去太空路标时，替你输 /showlocation 更新距离和偏离角；
    挂着小行星带方案时，核对现在在不在那条带里"""
    from .. import navigate as n
    from ..showloc import showlocation
    if (not _nav.target or not _nav.space_mode) and _HALO["plan"]:
        sess = _HALO["sess"]                     # 等坐标期间方案取下或换了，这次结果就作废
        g, clip = showlocation(log=_wp_log)
        with _HALO["lock"]:
            plan = _HALO["plan"] if _HALO["sess"] == sess else None
            if not g and plan:
                _hud().set("小行星带", plan["text"] + f"\n本次定位失败：{clip}")
        if not g:
            return {"error": clip}
        return halo_check(g, clip, sess) or {"error": "小行星带方案已移除或更换，本次定位无效"}
    if not _nav.target or not _nav.space_mode:
        _hud().set("导航", "一键定位仅用于手动定位（可在导航页切换）")
        threading.Timer(5, lambda: _hud().clear("导航") if not _nav.target else None).start()
        return {"error": "当前未导航到太空路标"}
    sess = _nav.session                          # 等坐标期间导航结束或换了目标，这次结果就作废
    g, clip = showlocation(log=_wp_log)
    if not g:
        if _nav.session == sess and _nav.target:
            _hud().set("导航", f"→ {n.label(_nav.target)}\n这次没定位成功：{clip}")
        return {"error": clip}
    return _nav.add_fix(g, clip, session=sess) or {"error": "导航已结束或目标已更换，本次定位无效"}


__all__ = [
    # 状态与常量
    "_places",
    "POS_FRESH",
    "_WHERE",
    "_AREA",
    "AREA_MAX_AGE",
    "HERE_WAIT",
    "_HERE",
    "HOTKEYS",
    "_HALO",
    "QT_SPEED",
    "LIVE_STALE",
    "DI_HELP",
    # 核心函数
    "_place_row",
    "nav_search",
    "nav_near",
    "nav_site",
    "nav_plan",
    "nav_start",
    "nav_mode",
    "sig_name",
    "sig_names",
    "nav_stop",
    "nav_refresh",
    "waypoints",
    "waypoint_add",
    "waypoint_preview",
    "waypoint_from_text",
    "_where_now",
    "_area_now",
    "_hotkey_values",
    "hotkey_conflicts",
    "fix_key_hint",
    "settings_key",
    "_wp_log",
    "_save_here",
    "_take_here_name",
    "_saved",
    "_start_here_watch",
    "mark_here",
    "_coord_desc",
    "ore_record",
    "ore_list",
    "ore_delete",
    "ore_restore",
    "ore_go",
    "halo_options",
    "halo_routes",
    "halo_pin",
    "halo_unpin",
    "_halo_watch",
    "halo_check",
    "fix_here",
    "_surface_limit",
    "waypoint_delete",
]
