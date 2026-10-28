"""窗口调用的功能接口：每个函数收 JSON 参数、返回 JSON。耗时的放后台线程，结果用 bus 推给窗口

和命令行版本用同一套数据和算法（shops / loot / acquire / navigate / locations / crafting / wikelo / trade），
只是不再 input() 一步步问，改成窗口里点选。
"""
import math
import re
from pathlib import Path
import sys
import threading
import time

from . import bus

WIN = sys.platform == "win32"
API = {}


def api(fn):
    API[fn.__name__] = fn
    return fn


def _hud():
    from ..overlay import hud
    return hud()


_ITEM_SEQ = [0]
ITEM_HUD_SECONDS = 60     # F8 物品结果在悬浮窗上留多久（2026-10-23 用户：一直挂着不消失）


_OFF_TOLD = set()


def _off(feature):
    """这个功能有没有被远程关掉（latest.json 的 disabled，update_check.disabled）：关了返回原因，第一次碰到时在悬浮窗提示一次"""
    try:
        from .. import update_check
        why = update_check.disabled(feature)
    except Exception:
        return None
    if why and feature not in _OFF_TOLD:
        _OFF_TOLD.add(feature)
        try:
            _note_hud("AT", f"{update_check.FEATURES.get(feature, feature)}暂时关闭：{why}", 8)
        except Exception:
            pass
    return why


def _note_hud(section, text, secs=6):
    """悬浮窗上一条短提示，secs 秒后自己收起（1.6.61：白色胶囊，同时只有一条，新的顶掉旧的）"""
    h = _hud()
    if hasattr(h, "note"):
        h.note(text, secs)
        return
    h.set(section, text)

    def gone():
        if getattr(_hud(), "sections", {}).get(section) == text:
            _hud().clear(section)
    t = threading.Timer(secs, gone)
    t.daemon = True
    t.start()


ITEM_AWAY_PX = 160         # 鼠标离开按 F8 时的位置这么远（1080p 像素，按屏幕高度放大）就收起物品结果
ITEM_AWAY_AFTER = 1.5      # 至少先显示这么久（秒）
_ITEM_MODE = {"pinned": False, "origin": None, "shown_at": 0.0}


def _cursor():
    try:
        import ctypes
        from ctypes import wintypes
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y
    except Exception:
        return None


def _key_down(vk):
    try:
        import ctypes
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
    except Exception:
        return False


def item_key_pressed():
    """按下物品识别键那一刻：记下鼠标在哪、是不是按着 Shift（Shift+F8 = 钉住，一直挂着，再按 F8 换掉）。
    借鉴流放之路的 Awakened PoE Trade（MIT）：鼠标移开自动收起、按住 Ctrl 不收、另一个键弹出固定的（2026-10-27）"""
    _ITEM_MODE.update(pinned=_key_down(0x10), origin=_cursor(), shown_at=time.time())


def _item_hud(text, secs=ITEM_HUD_SECONDS):
    """悬浮窗「物品」分区：鼠标从物品上移开就收起（按住 Ctrl 不收）；钉住的（Shift+F8）一直挂着；
    最多 secs 秒。期间内容更新了（比如市场价补上）就按新内容重新计时"""
    _ITEM_SEQ[0] += 1
    my = _ITEM_SEQ[0]
    _hud().set("物品", text)
    _ITEM_MODE["shown_at"] = time.time()      # 每次显示（识别中、结果、补上价格）都重新给够阅读时间（Codex 2026-10-27）
    if _ITEM_MODE["pinned"]:
        return

    def watch():
        import ctypes
        try:
            h = ctypes.windll.user32.GetSystemMetrics(1) or 1080
        except Exception:
            h = 1080
        away = ITEM_AWAY_PX * max(1.0, h / 1080)
        end = time.time() + secs
        while _ITEM_SEQ[0] == my and time.time() < end:
            time.sleep(0.1)
            o, c = _ITEM_MODE["origin"], _cursor()
            if (o and c and time.time() - _ITEM_MODE["shown_at"] >= ITEM_AWAY_AFTER and not _key_down(0x11)
                    and math.dist(o, c) > away):
                break
            if _key_down(0x11):                 # 按住 Ctrl：不收，也不算时间
                end = max(end, time.time() + 1)
        if _ITEM_SEQ[0] == my:                 # 之后又写过（再按 F8、价格补上）就不归这次管
            _hud().clear("物品")
    threading.Thread(target=watch, daemon=True, name="item-hud").start()


# ================================================================ 状态 / 设置

@api
def status():
    from .. import settings, helpers, showloc
    from ..data import GAME_VERSION
    cfg = settings.load()
    out = {"settings": cfg, "game_version": GAME_VERSION, "win": WIN,
           "admin": showloc.is_admin() if WIN else True,
           "game_elevated": bool(WIN and showloc.game_elevated()),
           "helpers": helpers.status_line(),
           "live": _live.running(), "live_paused": _live.running() and _live.paused,
           "nav": _nav.target_label(), "nav_space": _nav.space_mode, "hover_key": cfg.get("trade_capture_key") or "F8",
           "hotkey_warn": hotkey_conflicts(cfg),
           "position": None, "data": _data_versions(), "displayinfo": _pos.reader.active,
           "version": _version(), "new_version": _upgrade_found(), "game_size": None,
           "game_events": {k: v for k, (_, v) in list(_game_events.last.items())},
           "frozen": __import__("sc_mining.paths", fromlist=["FROZEN"]).FROZEN,
            "vpk": __import__("sc_mining.paths", fromlist=["VELOPACK"]).VELOPACK}
    if WIN:
        from ..perf import game_size
        out["game_size"] = game_size()                          # 游戏画面多大：低于 1080 高时页面上提醒识别会不准
    try:
        from ..position import current
        here = current()
        if here:
            out["position"] = {"label": here["label"], "minutes": int(here["age"] // 60), "sys": here["sys"]}
            from ..stockplaces import match
            p = match(here["label"], here["sys"])               # 库存入库默认放这里（地点列表里的叫法）
            out["place"] = {"label": p["label"], "path": p["path"], "minutes": int(here["age"] // 60)} if p else None
    except Exception:
        pass
    # 右上角读到的具体地点：记住最后一次读到的，切屏、某一次没认出来都不换（以前会在「附近」和站名之间来回闪）。
    # 只有游戏日志里有更新的地点（比如到别的站开了库存）才换掉它
    lab_t, lab = _pos.label
    if lab and time.time() - lab_t < 3 * 3600:
        log_t = 0.0
        try:
            from ..position import from_log
            hit = from_log()
            log_t = hit[0] if hit else 0.0
        except Exception:
            pass
        if lab_t >= log_t:
            sys_t, sysname = _pos.system
            out["position"] = {"label": lab, "minutes": int((time.time() - lab_t) // 60),
                               "sys": sysname or (out["position"] or {}).get("sys", ""),
                               "live": _pos.reader.active and time.time() - lab_t < 15}
    if out["position"] is not None:
        out["position"].setdefault("live", False)
    out["gridtext"] = _gridtext_status()
    return out


def _gridtext_status():
    try:
        from .. import gridtext
        return gridtext.status()
    except Exception:
        return {}


def _version():
    from ..version import VERSION
    return VERSION


_found = {"at": 0.0, "rows": []}


def _upgrade_found():
    """下载/桌面/微信/QQ 里有没有更新的 AT 安装包（10 分钟找一次，找一次不到 0.1 秒）"""
    if time.time() - _found["at"] > 600:
        try:
            from ..upgrade import find_packages
            _found["rows"] = find_packages()
        except Exception:
            _found["rows"] = []
        _found["at"] = time.time()
    if _found["rows"]:
        return _found["rows"][0]
    info = _online.get("info")
    if info:                                     # 网上有新版本、电脑里还没有安装包
        return {"version": info["version"], "where": "网上", "at": info.get("date", ""), "online": True}
    return None


_online = {"info": None, "told": ""}


def _online_info(force=False):
    """网上有没有新版本（只在后台线程里调：最多等几秒）"""
    from .. import settings, update_check
    if not settings.load().get("update_online", True) or not update_check.enabled():
        _online["info"] = None
        return None
    try:
        info = update_check.check(force=force)
    except Exception:
        info = None
    _online["info"] = info
    if info and _online["told"] != info["version"]:
        _online["told"] = info["version"]
        bus.publish("update", {"version": info["version"], "notes": info.get("notes", [])})
    return info


def _online_loop():
    time.sleep(20)                               # 刚启动先让识别、窗口起来
    while True:
        _online_info()
        time.sleep(1800)                         # 检查本身 6 小时才真的联网一次（update_check.EVERY）


def _online_public(info):
    return {k: info[k] for k in ("version", "date", "notes", "size", "source")} if info else None


@api
def upgrade_check(online=False):
    """online=True：顺便到网上查一次（设置页「检查更新」；最多等 5 秒×2）"""
    from ..upgrade import find_packages, rollback_options
    from .. import update_check, vpk
    if vpk.installed():                       # Velopack 安装版：不找本地安装包；回滚 = 从 AT 服务器装回上一个版本
        _found.update(at=time.time(), rows=[])
        from ..upgrade import ver, current
        if online:
            try:
                _, pv = vpk.check(rollback=True)
            except Exception:
                pv = ""
            try:
                _, nv = vpk.check()
            except Exception:
                nv = ""
            _online.update(prev=pv, vpk_new=nv)
        pv = _online.get("prev") or ""
        older = [{"version": pv, "where": "AT 服务器", "at": "", "path": VPK_PREV, "action": "回滚到", "stable": False}] \
            if pv and ver(pv) < current() else []
    else:
        _found.update(at=time.time(), rows=find_packages())
        try:
            older = rollback_options()
        except Exception:
            older = []
    info = _online_info(force=True) if online else _online.get("info")
    err = update_check.last_error() if online and not info else ""
    pub = _online_public(info)
    if vpk.installed():                       # 有没有新版本以 Velopack 更新源为准；大小不显示（增量下载，实际很小）
        from ..upgrade import ver, current
        nv = _online.get("vpk_new") or ""
        if nv and ver(nv) > current():
            same = pub and pub["version"] == nv
            pub = {"version": nv, "date": pub["date"] if same else "", "notes": pub["notes"] if same else [],
                   "size": None, "source": "AT 服务器"}
            err = ""
        else:
            pub = None
    return {"current": _version(), "found": _found["rows"], "older": older, "online": pub,
            "online_enabled": update_check.enabled(), "online_error": err}


def _online_task():
    from .. import update_check
    from .. import vpk
    if vpk.installed():                          # Velopack 安装版：只下改过的部分，AT 退出后换文件、自动重新打开
        v = vpk.install(progress=_task_print())
        print(f"✅ 已下载 AT {v}，AT 将关闭并自动安装，完成后自动重新打开")
        time.sleep(1.5)
        from .server import QUIT
        QUIT.set()
        return {"from": _version(), "to": v}
    info = _online.get("info") or update_check.check(force=True)
    if not info:
        raise ValueError("未找到新版本")
    path = update_check.download(info)
    _found["at"] = 0.0
    from ..paths import FROZEN
    if FROZEN:                                   # 独立安装版：运行新的安装程序，AT 先退出，装完自动重新打开
        update_check.launch_installer(path)
        print(f"✅ 已下载 AT {info['version']}，AT 将关闭并自动安装，完成后自动重新打开（约半分钟）")
        time.sleep(1.5)
        from .server import QUIT
        QUIT.set()
        return {"from": _version(), "to": info["version"]}
    return _upgrade_task(str(path))


@api
def upgrade_online():
    """「下载并升级」：下载网上的新版本，核对后照常升级（先备份，能回滚）。
    Velopack 安装版直接问更新源有没有新版本（latest.json 读不到也能升）"""
    from .. import vpk
    if not _online.get("info") and not vpk.installed():
        return {"error": "未找到新版本，点击「检查更新」后重试"}
    if bus.run_task_once("upgrade", _online_task, title="升级 AT") is None:
        return {"error": "正在升级，稍候"}
    return {"started": True}


@api
def upgrade_rollback(path=""):
    """回滚到旧版本（稳定版 / 自动备份 / 旧安装包）：和升级同一套流程，装之前也会先备份现在的版本。
    Velopack 安装版：path = VPK_PREV，从 AT 服务器装回上一个版本"""
    from .. import vpk
    if path == VPK_PREV:
        if not vpk.installed():
            return {"error": "只有安装版能这样回滚"}
        if bus.run_task_once("upgrade", _vpk_rollback_task, title="回滚 AT") is None:
            return {"error": "正在升级，稍候"}
        return {"started": True}
    return upgrade_apply(path)


VPK_PREV = "vpk:prev"


def _task_print():
    """给 Velopack 的进度回调用：它在 Velopack 自己的线程里调，那个线程不属于升级任务，print 进不了窗口（复审 2026-10-27）"""
    tid = bus.current_task()

    def out(line):
        if tid and bus.current_task() != tid:
            bus.adopt_task(tid)
        print(line)
    return out


def _vpk_rollback_task():
    from .. import vpk
    v = vpk.install(rollback=True, progress=_task_print())
    print(f"✅ 已下载 AT {v}，AT 将关闭并自动安装，完成后自动重新打开")
    time.sleep(1.5)
    from .server import QUIT
    QUIT.set()
    return {"from": _version(), "to": v}


@api
def upgrade_mark_stable():
    from ..upgrade import mark_stable
    try:
        p = mark_stable()
    except Exception as e:
        return {"error": f"保存稳定版失败：{e}"}
    return {"path": str(p), "version": _version()}


def _upgrade_task(path):
    from .. import upgrade
    try:
        r = upgrade.apply(path)
    except ValueError as e:
        print(f"❌ {e}")
        raise
    finally:
        _drop_upload(path)
    print(f"✅ 已{'升级' if upgrade.ver(r['to']) >= upgrade.ver(r['from']) else '回滚'}到 {r['to']}，马上重启 AT…")
    time.sleep(1.5)
    from .server import _relaunch
    _relaunch()
    return r


def _drop_upload(path):
    """手动上传的包（userdata/upgrade/<随机名>/…）装完就删；别处的包（下载文件夹、备份）不动"""
    import shutil
    from .. import paths
    try:
        p = Path(path).resolve()
        d = (paths.USER / "upgrade").resolve()
        if p.parent.parent == d:
            shutil.rmtree(p.parent, ignore_errors=True)
    except Exception:
        pass


# ---- 旧版天枢过渡（1.0.1）：导入旧版的设置和记录、关掉同时开着的旧版 ----
_legacy = {"rows": None}


@api
def legacy_scan():
    """安装版：电脑上的旧版天枢（压缩包版），以及哪些正开着。ask=True 表示还没问过要不要导入"""
    from .. import legacy, settings
    from ..paths import FROZEN
    if not FROZEN:
        return {"found": [], "running": [], "ask": False}
    if _legacy["rows"] is None:
        try:
            _legacy["rows"] = legacy.find()
        except Exception:
            _legacy["rows"] = []
    rows = _legacy["rows"]
    try:
        run = legacy.running(rows)
    except Exception:
        run = []
    return {"found": rows, "running": run, "ask": bool(rows) and not settings.load().get("legacy_checked")}


@api
def legacy_import(path=""):
    """把旧版的设置、路标、目标等复制过来，然后重新打开 AT（热键、悬浮窗按新设置重新挂）"""
    from .. import legacy, settings
    if path not in [r["path"] for r in (_legacy["rows"] or [])]:
        return {"error": "未找到这个旧版"}
    try:
        done = legacy.import_from(path)
    except Exception as e:
        return {"error": f"导入失败：{e}"}
    settings.update(legacy_checked=True)

    def later():
        time.sleep(1.5)
        from .server import _relaunch
        _relaunch()
    threading.Thread(target=later, daemon=True).start()
    return {"done": done}


@api
def legacy_skip():
    from .. import settings
    settings.update(legacy_checked=True)
    return {"ok": True}


@api
def legacy_quit(path=""):
    """关掉正在运行的旧版天枢（请它自己退出）"""
    from .. import legacy
    if path not in [r["path"] for r in (_legacy["rows"] or [])]:
        return {"error": "未找到这个旧版"}
    try:
        legacy.quit_old(path)
    except Exception:
        return {"error": "旧版未响应：在屏幕右下角托盘右键旧版天枢图标，选「退出」"}
    return {"ok": True}


FROZEN_UPGRADE_MSG = "安装版在「设置与更新」点击「检查更新」在线升级，或到发布页下载新的安装程序（AT_Setup_版本号.exe）直接安装（设置和记录会保留）"


@api
def upgrade_apply(path=""):
    from ..paths import FROZEN
    if FROZEN:                              # 独立打包版（2026-10-26 验证阶段）：程序在 _internal 里，按旧方式覆盖源码会出错
        return {"error": FROZEN_UPGRADE_MSG}
    from ..upgrade import check
    try:
        check(path)
    except ValueError as e:
        return {"error": str(e)}
    if bus.run_task_once("upgrade", _upgrade_task, path, title="升级 AT") is None:
        return {"error": "正在升级，稍候"}
    return {"started": True}


def upgrade_receive(name, write):
    """接收窗口里手动选的安装包（新旧上传接口共用）：
    每次写到 userdata/upgrade/<随机名>/Dubhe_x.y.z.zip（独立文件，两次上传互不覆盖，升级任务读的时候也不会被下一次上传改掉），
    write(f) 负责把内容写进打开的文件（抛异常=没收完），收完先校验再交给升级任务；没启动成功就把这份删掉。
    升级任务用完（成功或失败）会删掉这个随机文件夹（_upgrade_task）。"""
    import shutil
    import uuid
    from .. import paths
    if not re.match(r"^Dubhe_\d+\.\d+\.\d+\.zip$", name or "", re.I):
        return {"error": "需要 AT 安装包（Dubhe_版本号.zip）"}
    if bus.task_running("upgrade"):
        return {"error": "正在升级，稍候"}
    d = paths.USER / "upgrade"
    try:
        d.mkdir(parents=True, exist_ok=True)
        _sweep_uploads(d)
        sub = d / uuid.uuid4().hex
        sub.mkdir()
    except OSError as e:
        return {"error": f"保存安装包失败：{e}"}
    target = sub / name                                # 文件名照旧保留版本号（check 用它兜底）
    try:
        with open(target, "wb") as f:
            write(f)
    except Exception as e:
        shutil.rmtree(sub, ignore_errors=True)         # 半个文件不留
        return {"error": f"保存安装包失败：{e}"}
    try:
        r = upgrade_apply(str(target))
    except Exception:                                  # 包坏到检查时直接抛（zlib.error 之类）：也别留着
        shutil.rmtree(sub, ignore_errors=True)
        raise
    if not isinstance(r, dict) or r.get("error"):      # 没装（安装版 / 包不对 / 已在升级）：别留着
        shutil.rmtree(sub, ignore_errors=True)
    return r


def _sweep_uploads(d):
    """清掉以前上传剩下的随机文件夹。只清 1 小时前的：正在收的、刚交给升级任务的那份不碰（任务用完自己删）"""
    import shutil
    cutoff = time.time() - 3600
    for p in d.iterdir():
        try:
            if p.stat().st_mtime > cutoff:
                continue
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink()                             # 1.0.4 以前直接放在 upgrade/ 下的旧包
        except OSError:
            pass


@api
def upgrade_upload(name="", data=""):
    """旧接口（base64 整包进内存）：1.0.4 起网页改走 /api/upgrade_upload_raw 流式上传，这里只留给老窗口"""
    import base64
    try:
        raw = base64.b64decode(data)
    except Exception:
        return {"error": "无法读取此文件"}
    return upgrade_receive(name, lambda f: f.write(raw))


@api
def upgraded():
    """刚升级完重启后：窗口弹一句「已升级到 x」"""
    from ..upgrade import just_upgraded, adopt_previous
    d = just_upgraded() or {}
    if d.get("from"):
        try:
            adopt_previous(d["from"])          # 旧版本自己不会备份（1.6.18 及以前）：找到它的安装包就收进备份
        except Exception:
            pass
        from ..upgrade import ver
        d["rollback"] = ver(d["to"]) < ver(d["from"])
    return d


def _data_versions():
    from .. import paths
    import json
    out = {}
    try:
        out["loc"] = (paths.DATA / "loc" / "version.txt").read_text(encoding="utf-8").strip()
    except Exception:
        out["loc"] = ""
    for key, name in (("shops", "shops.json"), ("starmap", "starmap.json")):
        p = paths.DATA / name
        out[key] = time.strftime("%Y-%m-%d", time.localtime(p.stat().st_mtime)) if p.exists() else ""
    try:
        from ..loot import load_index
        idx = load_index(False)
        out["loot"] = (idx or {}).get("version", "")
    except Exception:
        out["loot"] = ""
    from ..data_pack import local_version
    out["pack"] = local_version()                    # 数据包版本（2026-10-26 起数据从 Gitee 的数据包更新）
    return out


def _desktop():
    """桌面文件夹（桌面被 OneDrive 搬走的也能找到）"""
    from pathlib import Path
    if WIN:
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:
                return Path(buf.value)
        except Exception:
            pass
    p = Path.home() / "Desktop"
    return p if p.exists() else Path.home()


def _system_info():
    """导出日志时附带的一页说明：版本、系统、屏幕、数据版本（不含任何个人数据）"""
    import json
    import platform
    from .. import paths
    lines = [f"AT 版本：{_version()}", f"导出时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"Windows：{platform.platform()}", f"Python：{sys.version.split()[0]}"]
    try:
        import ctypes
        u32 = ctypes.windll.user32
        lines.append(f"屏幕：{u32.GetSystemMetrics(0)} × {u32.GetSystemMetrics(1)}（缩放后）")
    except Exception:
        pass
    try:
        from .. import showloc
        lines.append(f"AT 管理员身份：{'是' if showloc.is_admin() else '否'}；游戏管理员身份：{'是' if showloc.game_elevated() else '否/未运行'}")
    except Exception:
        pass
    try:
        from importlib.metadata import version as v

        def ver(n):
            try:
                return f"{n} {v(n)}"
            except Exception:
                return ""
        # onnxruntime 的显卡版包名是 onnxruntime-directml：哪个装了写哪个
        names = ("rapidocr_onnxruntime", "onnxruntime", "onnxruntime-directml", "numpy", "pillow", "mss")
        lines.append("组件：" + "，".join(x for x in map(ver, names) if x))
        from ..perf import ocr_device
        lines.append(f"文字识别用：{ocr_device()}")
    except Exception:
        pass
    lines.append("数据：" + json.dumps(_data_versions(), ensure_ascii=False))
    lines.append(f"安装位置里有中文：{'是' if any(ord(c) > 127 for c in str(paths.ROOT)) else '否'}")
    return "\n".join(lines) + "\n"


@api
def export_logs():
    """「导出日志」：运行日志 + 设置 + 一页系统说明打成一个压缩包，放到桌面，并在文件夹里选中它"""
    import zipfile
    from .. import paths
    out = _desktop() / time.strftime("AT日志_%Y%m%d_%H%M%S.zip")      # 精确到秒，不会盖掉同一分钟导出的另一份
    files = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(paths.LOGS.glob("*.txt*")) if paths.LOGS.exists() else []:     # 含轮换下来的 .txt.old
            z.write(p, f"logs/{p.name}")
            files += 1
        for name in ("settings.json", "goals.json"):
            p = paths.USER / name
            if p.exists():
                z.write(p, name)
                files += 1
        z.writestr("系统信息.txt", _system_info())
    if WIN:
        try:
            import subprocess
            subprocess.Popen(["explorer", "/select,", str(out)])
        except Exception:
            pass
    return {"path": str(out), "files": files, "kb": round(out.stat().st_size / 1024)}


# ================================================================ 问题反馈：识别不到 / 认错了，一键把当时的截图和数据存下来

_FB_LAST = {"sig": None, "scan": None}      # 最近一次推送的信号 / 扫描结果（反馈时写进去对照）
_ORE_LAST = {"view": None}                  # 最近一次出的采矿助手结果（原矿记录记的就是它）


def _fb_dir():
    from .. import paths
    d = paths.USER / "feedback"
    d.mkdir(parents=True, exist_ok=True)
    return d


@api
def feedback_report(kind="auto", note="", img=None):
    """一键反馈：现在的整屏截图 + 最近几帧采矿助手截图 + OCR 原文 + 当时显示的结果 + 日志尾巴，打成一个文件夹和 zip
    放在 userdata\feedback\。kind：scan（矿物认错）/ signal（信号不对）/ item（F8 认错）/ auto"""
    import json
    import shutil
    import zipfile
    from .. import paths, screen
    from ..screen import grab
    stamp = time.strftime("%Y%m%d_%H%M%S")
    kind = kind if kind in ("scan", "signal", "item", "auto") else "auto"
    d = _fb_dir() / f"{stamp}_{kind}"
    d.mkdir(parents=True, exist_ok=True)
    try:
        img = img or grab()
        img.save(d / "屏幕.png")
    except Exception as e:
        (d / "截图失败.txt").write_text(str(e), encoding="utf-8")
    # 最近几帧采矿助手截图和 F8 截图（本来就只留最近 20 张）
    for sub, n in (("live", 5), ("hover", 2), ("miss", 3)):        # miss：采矿助手看到面板却没出结果时自动留的图
        src = paths.SHOTS / sub
        if src.exists():
            for f in sorted(src.glob("*.*"), key=lambda f: f.stat().st_mtime)[-n:]:
                try:
                    shutil.copy(f, d / f"{sub}_{f.name}")
                except OSError:
                    pass
    info = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "version": _version(), "kind": kind, "note": note or "",
            "screen": [img.width, img.height] if img else None,
            "ocr_scan_lines": screen.LAST_RAW.get("scan"), "ocr_bag_lines": screen.LAST_RAW.get("bag"),
            "ocr_age_s": round(time.time() - screen.LAST_RAW.get("t", 0)) if screen.LAST_RAW.get("t") else None,
            "shown_signal": _FB_LAST["sig"], "shown_scan": _FB_LAST["scan"],
            "hover": {k: v for k, v in _last_hover.items() if k != "img"},
            "hud": dict(getattr(_hud(), "sections", {}) or {}), "live": _live.running(), "live_paused": _live.paused,
            "where_now": _WHERE.get("v"), "nav": _nav.target_label(), "nav_space": _nav.space_mode}
    try:
        from .. import settings
        cfg = settings.load()
        info["settings"] = {k: cfg.get(k) for k in ("mining_ship", "mining_loadouts", "admin", *(n for n, _, _ in HOTKEYS))}
    except Exception:
        pass
    (d / "情况.json").write_text(json.dumps(info, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for name in ("live_log.txt", "trade_log.txt", "nav_log.txt", "app_log.txt", "crash_log.txt", "crash_log_ocr.txt"):
        p = paths.LOGS / name
        if p.exists():
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[-150:]
                (d / name).write_text("\n".join(lines), encoding="utf-8")
            except OSError:
                pass
    (d / "说明.txt").write_text(
        f"AT 问题反馈 {info['time']}（{kind}）\n{note or '（无备注）'}\n\n"
        "屏幕.png = 按下反馈键时的截图；live_*.png = 采矿助手最近几帧；情况.json = 当时的识别文字和显示结果。\n"
        "自动发送开着时已发给作者；关着时将此文件夹（或同名 zip）发给作者即可。截图中可能有游戏聊天框。", encoding="utf-8")
    zp = d.with_suffix(".zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in d.iterdir():
            z.write(f, f"{d.name}/{f.name}")
    from .. import feedback_up
    upload = feedback_up.enabled()
    hm = f"{stamp[-6:-4]}:{stamp[-4:-2]}:{stamp[-2:]}"
    try:
        _note_hud("反馈", f"📝 已保存问题反馈（{hm}）\n" + ("正在发送给作者…" if upload else "可在设置页「问题反馈」导出"), 6)
    except Exception:
        pass
    if upload:                                   # 2026-10-27：存好就自动发给作者（后台，不卡游戏）
        feedback_up.mark_pending(d)

        def _up():
            ok, why, again = feedback_up.send(d, kind)
            try:
                _note_hud("反馈", f"📝 问题反馈（{hm}）" + ("已发送给作者" if ok else f"未发送：{why}\n"
                          + ("下次启动自动重发" if again else "可在设置页「问题反馈」导出")), 6)
            except Exception:
                pass
            bus.publish("feedback", {"path": str(zp), "kind": kind, "at": info["time"], "sent": ok, "why": why})
        threading.Thread(target=_up, daemon=True, name="feedback-up").start()
    bus.publish("feedback", {"path": str(zp), "kind": kind, "at": info["time"]})
    return {"path": str(zp), "dir": str(d), "kb": round(zp.stat().st_size / 1024), "count": len(list(_fb_dir().glob("*.zip"))),
            "upload": upload}


@api
def feedback_list():
    rows = []
    for z in sorted(_fb_dir().glob("*.zip"), key=lambda f: f.stat().st_mtime, reverse=True)[:30]:
        d = z.with_suffix("")
        note = ""
        try:
            import json
            note = json.loads((d / "情况.json").read_text(encoding="utf-8")).get("note", "")
        except Exception:
            pass
        rows.append({"name": z.stem, "kb": round(z.stat().st_size / 1024), "note": note, "sent": (d / ".sent").exists(),
                     "at": time.strftime("%m-%d %H:%M", time.localtime(z.stat().st_mtime))})
    return rows


@api
def feedback_export():
    """把所有反馈 zip 再打成一个包放到桌面，并在文件夹里选中"""
    import zipfile
    zs = sorted(_fb_dir().glob("*.zip"))
    if not zs:
        return {"error": "暂无反馈记录"}
    out = _desktop() / time.strftime("AT问题反馈_%Y%m%d_%H%M%S.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for f in zs:
            z.write(f, f.name)
    if WIN:
        try:
            import subprocess
            subprocess.Popen(["explorer", "/select,", str(out)])
        except Exception:
            pass
    return {"path": str(out), "files": len(zs), "kb": round(out.stat().st_size / 1024)}


@api
def feedback_clear():
    import shutil
    n = 0
    for f in list(_fb_dir().iterdir()):
        try:
            shutil.rmtree(f) if f.is_dir() else f.unlink()
            n += 1
        except OSError:
            pass
    return {"removed": n}


@api
def cockpit_check():
    """辅助进程双击 W 时问：现在画面中间有没有飞行 HUD（用主程序的识别引擎，辅助进程不用自己加载一份）"""
    from .. import cockpit
    try:
        flying, hits = cockpit.flight_hud()
    except Exception as e:
        return {"flying": False, "error": str(e)}
    return {"flying": bool(flying), "hits": hits[:4]}


@api
def overlay_move(on=False):
    """「移动悬浮窗」：打开时悬浮窗能拖动（不穿透），关上恢复鼠标穿透"""
    _hud().set_movable(bool(on))
    return {"on": bool(on)}


@api
def set_settings(**kw):
    from .. import settings, helpers
    allowed = {"anti_afk", "afk_seconds", "autorun", "autorun_sprint", "admin", "hud_scale", "hud_plate", "hud_theme"} | {k for k, _, _ in HOTKEYS}
    if "stock_mode" in kw and kw["stock_mode"] not in ("simple", "pro"):
        kw.pop("stock_mode")
    allowed.add("stock_mode")
    if "theme" in kw and kw["theme"] not in ("dark", "light"):
        kw.pop("theme")
    allowed.add("theme")
    for k in ("ata", "update_online", "feedback_upload", "train_upload"):
        if k in kw:
            kw[k] = bool(kw[k])
        allowed.add(k)
    clear_train = kw.get("train_upload") is False          # 关掉「帮助改进识别」：先存「关」，再删本地攒着没发的（二审 2026-10-27）
    if "hud_scale" in kw:
        kw["hud_scale"] = min(1.0, max(0.5, float(kw["hud_scale"])))     # 2026-10-26 用户定：50% / 75% / 100%
    if "hud_plate" in kw:
        kw["hud_plate"] = min(1.0, max(0.3, float(kw["hud_plate"])))
    if "hud_theme" in kw and kw["hud_theme"] not in ("默认", "蓝金", "浅色"):
        kw["hud_theme"] = "默认"
    cur = None
    for name, default, label in HOTKEYS:                # 1.6.70：所有热键都能在设置页改（点一下、按一下）
        if name not in kw:
            continue
        k = str(kw[name] or "").strip().upper()
        if not k and not default:                       # 原矿记录这种默认不设的可以清掉
            kw[name] = ""
            continue
        if not re.fullmatch(r"F([1-9]|1[0-2])", k):
            return {"error": "热键仅支持 F1–F12"}
        cur = cur or settings.load()
        taken = {key: lab for key, lab, n in _hotkey_values(cur) if n != name and key}
        if k in taken:
            return {"error": f"{k} 已用于「{taken[k]}」，需更换按键"}
        kw[name] = k
    cfg = settings.update(**{k: v for k, v in kw.items() if k in allowed})
    if clear_train:
        try:
            from .. import train_data
            train_data.clear()
        except Exception:
            pass
    if any(k in kw for k in ("hud_theme", "hud_plate", "hud_scale")):
        try:
            _hud().restyle()
        except Exception:
            pass
    if any(k in kw for k in ("anti_afk", "afk_seconds", "autorun", "autorun_sprint", "admin")):
        helpers.start()                                   # 只有辅助相关的项变了才重启辅助进程（2026-10-28 用户反馈连点开关卡一下）
    bus.publish("status", status())
    return cfg


@api
def update_data():
    from ..run import update
    if bus.run_task_once("update", update, title="更新数据") is None:   # 已经在更新：不再起第二份
        return {"started": False, "running": True}
    return {"started": True}


# ================================================================ 全局搜索

@api
def search(q=""):
    """一个输入框搜所有东西：物品、地点、矿、蓝图、维科洛兑换"""
    q = (q or "").strip()
    out = {"items": [], "places": [], "minerals": [], "blueprints": [], "wikelo": []}
    if not q:
        return out
    try:
        out["minerals"] = mineral_search(q)
    except Exception:
        pass
    try:
        out["items"] = item_search(q)[:8]
    except Exception:
        pass
    try:
        out["places"] = nav_search(q)["rows"][:6]
    except Exception:
        pass
    try:
        out["blueprints"] = craft_search(q)[:6]
    except Exception:
        pass
    try:
        out["wikelo"] = wikelo_search(q)[:5]
    except Exception:
        pass
    return out


# ================================================================ 物品：在哪买 / 同款 / 掉落 / 维科洛

@api
def item_search(q=""):
    """物品查询搜索（1.6.41 起商店、掉落、汉化包一起搜，见 itemsearch.py）。
    src：shop 商店有数据 / loot 只在掉落数据里 / loc 商店和掉落数据里都没有（只有汉化包里有名字）"""
    from .. import itemsearch
    from ..i18n import shop_cat_zh
    return [{"id": r["shop"], "name": r["en"], "zh": r["zh"], "category": shop_cat_zh(r["cat"]) or _wiki_cat(r),
             "src": "shop" if r["shop"] is not None else "loot" if r["loot"] else "wiki" if r.get("wiki") else "loc"}
            for r in itemsearch.find(q, limit=30)]


WIKI_TYPE_ZH = {"WeaponPersonal": "单兵武器", "WeaponGun": "舰炮", "MissileLauncher": "导弹架", "Missile": "导弹", "Turret": "炮塔",
                "Char_Armor_Helmet": "头盔", "Char_Armor_Torso": "胸甲", "Char_Armor_Arms": "臂甲", "Char_Armor_Legs": "腿甲",
                "Char_Armor_Backpack": "背包", "Char_Armor_Undersuit": "基底服", "Char_Clothing_Torso_0": "上衣", "Char_Clothing_Torso_1": "外套",
                "Char_Clothing_Legs": "裤子", "Char_Clothing_Feet": "鞋", "Char_Clothing_Hat": "帽子", "Char_Clothing_Hands": "手套",
                "WeaponAttachment": "附件", "Shield": "护盾生成器", "PowerPlant": "发电机", "Cooler": "冷却器", "QuantumDrive": "量子驱动器",
                "Radar": "雷达", "WeaponMining": "采矿激光器", "MiningModifier": "采矿模组", "Container": "货柜", "TractorBeam": "牵引光束",
                "FuelTank": "燃料箱", "FuelIntake": "燃料进气口", "Thruster": "推进器", "Armor": "舰船装甲", "UtilityTurret": "工具炮塔",
                "RemovableChip": "钥匙卡", "FPS_Consumable": "消耗品", "Food": "食物", "Drink": "饮料", "Commodity": "商品"}


def _wiki_cat(r):
    """只在 wiki 清单里的物品：类型 + 尺寸当分类显示（「导弹架 S5」）"""
    if not r.get("wtype"):
        return ""
    t = WIKI_TYPE_ZH.get(r["wtype"], r["wtype"])
    return f"{t} S{r['wsize']}" if r.get("wsize") not in (None, 0, 1) or (r.get("wsize") == 1 and r["wtype"] in ("WeaponGun", "MissileLauncher", "Shield", "PowerPlant", "Cooler", "QuantumDrive", "Radar", "WeaponMining")) else t


def _zh_of(en):
    try:
        from ..trade.names import table
        rev = getattr(_zh_of, "_rev", None)
        if rev is None:
            rev = _zh_of._rev = {v.lower(): k for k, v in table().items()}
        return rev.get(en.lower(), "")
    except Exception:
        return ""


@api
def item_info(name="", zh="", id=None, loot=True, exact=False):
    """exact=True：从物品查询 / 顶上搜索框的结果点进来的（名字是准的）。
    掉落明细本机没有时不上网等（loot 里给 pending），窗口再调 item_loot 后台取（2026-10-28 用户反馈卡 10 秒）"""
    from .. import acquire
    d = acquire.info(name, zh, id, show_loot=loot, exact=bool(exact), loot_online=False)
    from ..i18n import gear_zh_of_item, shop_cat_zh
    d["zh"] = gear_zh_of_item(d["name"]) or d.get("zh") or _zh_of(d["name"])   # 采矿装备的中文不带型号，和配置区一致
    if d.get("category"):
        d["category"] = shop_cat_zh(d["category"])
    g = _goal_for(d.get("name"), name, zh, d["zh"])
    d["goal"] = _goal_text(g) if g else ""
    return d


@api
def item_loot(name="", zh=""):
    """物品查询里掉落那一块：明细本机没有时窗口在后面单独调这个（会上网，最多等 15 秒，不挡别的）"""
    try:
        from ..loot import info as loot_info
        return {"loot": loot_info(name, zh)}
    except Exception as e:
        return {"loot": {"error": f"掉落数据出错：{e}"}}


@api
def nav_shop(shop="", place=""):
    """物品查询里点一处商店 → 导航过去（2026-10-28 用户定）。先找主城 / 空间站里这家店的点（城里导航），
    没有就导航到这个地点本身（星图）"""
    from .. import navigate as n
    data = n.load()
    brand = re.sub(r"[^a-z]", "", (shop.split(" - ")[0] or "").lower())
    place = (place or "").split(" · ")[-1].strip()      # 商店行的地点是「Stanton · MicroTech · New Babbage」，只要最后一段（2026-10-28 反馈：点了说没这个地点）
    site = re.sub(r"[^a-z0-9]", "", place.lower())
    hit = None
    if site:
        pts = [q for q in n.city_places() if re.sub(r"[^a-z0-9]", "", (q.get("site_en") or "").lower()) == site]
        if brand:
            hit = next((q for q in pts if re.sub(r"[^a-z]", "", q["n"].lower()).startswith(brand)), None)
        if hit is None and pts:                            # 店的点没解出来：去这个地方的取船终端（下了船就在旁边）
            hit = next((q for q in pts if "取船" in (q.get("kinds") or ())), None)
        if hit is None:
            hit = next((q for q in data["pois"] if re.sub(r"[^a-z0-9]", "", q["n"].lower()) == site), None)
        if hit is None:                                    # 派罗的站星图地点表里没有（死局空间站在 PYR2 L4 上）：按设施表找
            for k in n.NEAR_KINDS:
                hit = next((q for q in n.amenity_targets(k, data)
                            if re.sub(r"[^a-z0-9]", "", q["n"].lower()) in (site, re.sub(r"station$", "", site))), None)
                if hit:
                    break
        for q in ([place, re.sub(r"\s+Station$", "", place, flags=re.I)] if hit is None else []):   # 星图里叫 Checkmate，不带 Station
            hits, _ = n.search(q, data, limit=1)
            if hits:
                hit = hits[0]
                break
    if hit is None:
        return {"error": "导航数据里没有这个地点"}
    row = _place_row(hit)
    _nav.start(_places[row["key"]])
    return {"key": row["key"], "label": row["label"]}


# ================================================================ 交易：玩家市场价、库存

_trade = None
_trade_lock = threading.Lock()


def trade():
    global _trade
    with _trade_lock:
        if _trade is None:
            from ..trade.console import Trade
            _trade = Trade()
    return _trade


@api
def market_lookup(q=""):
    t = trade()
    items, err = t.lookup(q)
    return {"err": err or "", "items": [{"id": i.id, "label": t.label(i.id),
                                         "src": i.id.split(":")[0].upper() if ":" in i.id else "UEX"} for i in items[:15]]}


@api
def market_prices(id="", quality="q0", op="sell"):
    out, results = _market_rows(id, quality, op)
    if results is not None:
        from ..trade.console import hud_market
        market = hud_market(results)
        if _last_hover.get("id") == id:                   # F8 认出的物品：接在买点/兑换/制造后面
            _item_hud("\n".join(_last_hover["lines"] + ([market] if market else [])))
        elif market:                                      # 窗口里查的价
            _item_hud(f"{trade().label(id)}\n{market}")
    return out


def _market_rows(id, quality="q0", op="sell"):
    """(窗口用的价格表, 原始结果)；没有这个物品返回 ({error}, None)"""
    from ..trade.console import _group, _money, SOURCE_ZH, STATE_ZH
    t = trade()
    item = t.catalog.get(id)
    if not item:
        return {"error": "未找到此物品"}, None
    results = t.prices(item, _group(quality), op)
    rows = []
    for r in results:
        src = SOURCE_ZH.get(r.source, r.source)
        if not r.stats:
            rows.append({"src": src, "state": STATE_ZH.get(r.state, r.state) or "暂无报价"})
            continue
        for s in r.stats:
            rows.append({"src": src, "quality": s.key.quality_group.upper(), "unit": s.key.unit,
                         "currency": s.key.currency, "mean": _money(s.mean), "min": _money(s.minimum),
                         "count": s.count, "week": _money(s.week_mean) if s.week_mean is not None else "",
                         "state": STATE_ZH.get(r.state, "")})
    return {"label": t.label(id), "rows": rows}, results


def scu_amount(qty, unit):
    """库存里存的整数 → SCU（uSCU 是百万分之一，旧的 cSCU 是百分之一），去掉浮点误差"""
    return round(qty / (1_000_000 if unit == "uSCU" else 100), 6)


MODE_ZH = {"add": "入库", "count": "盘点", "adjust": "改数量", "out": "出库", "set": "改数量", "move": "移库", "quality": "改品质"}
LEDGER_TYPES = ("入库", "出库", "移库", "改数量", "改品质", "盘点", "撤销")


def _qlabel(qkey, short=False):
    if qkey.startswith("exact:"):
        return ("" if short else "品质 ") + qkey[6:]
    return "品质未知" if qkey == "unknown" else qkey.upper()


def _amount_text(raw, ukey, sign=False):
    """库存里存的整数 → 「0.495 SCU」「3 个」（sign：带 +/-）"""
    if ukey in ("uSCU", "cSCU"):
        v = scu_amount(raw, ukey)
        return f"{v:+g} SCU" if sign else f"{v:g} SCU"
    return f"{raw:+d} 个" if sign else f"{raw} 个"


def _stock_kind(zh, en, ukey):
    """库存页筛选用的类别：矿物（能挖的）/ 材料（按 SCU 记的其他东西）/ 物品（按个记的）"""
    if ukey == "unit":
        return "物品"
    return "矿物" if _is_mineral(zh, en) else "材料"


def _place_of(location):
    """库存里记的位置 → (地点叫法, 仓位, 地点信息或 None)：「新巴贝奇｜待卖」→ (新巴贝奇, 待卖, …)；New Babbage → (新巴贝奇, 总仓, …)"""
    from .. import stockplaces as SP
    place, b = SP.split_loc(location)
    p = SP.match(place)
    return (p["label"] if p else place), b, p


def _all_batches(t):
    """全部库存记录（新的在前）：每笔的类型、时间、内容（移库写「从 → 到」，改品质写「旧 → 新」）、备注、涉及的地点和物品"""
    batches = []
    for r in t.inventory.history():
        if not batches or batches[-1]["batch"] != r["batch_id"]:
            mode = r["mode"]
            batches.append({"batch": r["batch_id"], "at": r["at"], "mode": mode, "undone": bool(r["undone"]),
                            "type": "撤销" if mode.startswith("undo:") else MODE_ZH.get(mode, mode),
                            "note": r.get("note") or "", "reason": r.get("reason") or "", "source": r.get("source") or "", "_rows": []})
        batches[-1]["_rows"].append(r)
    labels = {}

    def name(iid):
        if iid not in labels:
            labels[iid] = t.label(iid)
        return labels[iid]
    for b in batches:
        rows, items = b.pop("_rows"), []
        if b["mode"] == "adjust" and len(rows) == 2:              # 1.6.38 以前的改品质也记成 adjust：一减一加、品质不同
            x, y = rows
            if (x["item_id"], x["location"], x["unit"]) == (y["item_id"], y["location"], y["unit"]) \
                    and x["delta"] == -y["delta"] and x["quality"] != y["quality"]:
                b["mode"], b["type"] = "quality", "改品质"
        if b["mode"] in ("move", "quality"):
            # 成对的一减一加：移库按物品+品质+单位配对，改品质按物品+位置+单位配对
            pair = (lambda r: (r["item_id"], r["quality"], r["unit"])) if b["mode"] == "move" else (lambda r: (r["item_id"], r["location"], r["unit"]))
            plus = {pair(r): r for r in rows if r["delta"] > 0}
            for r in rows:
                if r["delta"] >= 0:
                    continue
                to = plus.get(pair(r))
                amt = _amount_text(-r["delta"], r["unit"])
                if b["mode"] == "move":
                    items.append(f"{name(r['item_id'])}（{_qlabel(r['quality'])}）{amt}：{r['location']} → {to['location'] if to else '?'}")
                else:
                    items.append(f"{name(r['item_id'])} {amt}：{_qlabel(r['quality'])} → {_qlabel(to['quality']) if to else '?'}（{r['location']}）")
        if not items:
            items = [f"{name(r['item_id'])}（{_qlabel(r['quality'])}）{_amount_text(r['delta'], r['unit'], True)}｜{r['location']}" for r in rows]
        b["items"] = items
        b["places"] = sorted({_place_of(r["location"])[0] for r in rows})
        b["names"] = " ".join(sorted({name(r["item_id"]) for r in rows}))
    return batches


def _history_view(t, limit=12):
    return [{k: v for k, v in b.items() if k != "names"} for b in _all_batches(t)[:limit]]


def _bins(t):
    """仓位：{地点: {"bins": [{name, desc}], "default": 默认仓位名或空}}（存在交易库的设置里）"""
    d = t.db.get("stock_bins", {}) or {}
    return d if isinstance(d, dict) else {}


def _price_index(t):
    """缓存里的玩家市场挂牌价（不联网）：{(物品, 品质档, 单位): (单价, 来源)}，同一档取最便宜的出售挂牌"""
    from decimal import Decimal
    best = {}
    try:
        stats = t.market.cached_stats()
    except Exception:
        stats = []
    for s in stats:
        if s.key.operation != "sell":
            continue
        v = s.minimum if s.minimum is not None else s.mean
        if v is None or (s.count or 0) <= 0:
            continue
        k = (s.key.item_id, s.key.quality_group, s.key.unit)
        if k not in best or Decimal(v) < best[k][0]:
            best[k] = (Decimal(v), s.key.source)
    return best


def _row_value(prices, item_id, qkey, ukey, raw):
    """这一行按最便宜的出售挂牌值多少 aUEC；品质未知、没报价、单位对不上返回 None"""
    from ..trade.providers.http import quality_group
    if not qkey.startswith("exact:"):
        return None
    group = quality_group(qkey[6:])
    if ukey == "unit":
        hit = prices.get((item_id, group, "unit"))
        return float(hit[0]) * raw if hit else None
    scu = scu_amount(raw, ukey)
    for unit, per in (("SCU", scu), ("cSCU", scu * 100), ("uSCU", scu * 1_000_000)):
        hit = prices.get((item_id, group, unit))
        if hit:
            return float(hit[0]) * per
    return None


@api
def stock():
    """库存页：每一行（地点、仓位、类别、最后变动、目标占用、不给目标用、估值）、左边的地点树（带仓位）、当前位置、最近记录"""
    from .. import stockplaces as SP
    from .. import goals as G
    from ..trade.names import has_chinese
    t = trade()
    custom = list(t.db.get("stock_custom_places", []) or [])
    bins = _bins(t)
    changed = t.inventory.last_changes()
    reserved = G.reserved_keys(t)
    from ..crafting import craft_text
    try:
        crafts = t.inventory.craft_map()
    except Exception:
        crafts = {}
    try:
        alloc = G.plan(t).get("alloc", {})
    except Exception:
        alloc = {}
    prices = _price_index(t)
    rows, groups = [], {}

    def group(label, p):
        if label not in groups:
            state = "known" if p else ("custom" if label in custom else "unmatched")
            groups[label] = {"label": label, "path": p["path"] if p else label, "sys": p["sys_zh"] if p else "",
                             "kind": p["kind"] if p else "其他", "state": state, "count": 0, "value": 0.0, "bins": {}}
        return groups[label]
    for line in t.inventory.list_stock():
        k = line.key
        place, b, p = _place_of(k.location)
        g = group(place, p)
        g["count"] += 1
        g["bins"][b] = g["bins"].get(b, 0) + 1
        item = t.catalog.get(k.item_id)
        en = item.name if item else k.item_id
        label = t.label(k.item_id)
        zh = label.split("（")[0] if label.endswith("）") and "（" in label else (label if has_chinese(label) else "")
        qty, unit = line.quantity, k.unit
        if unit in ("uSCU", "cSCU"):                # 矿和材料按 uSCU（以前 0.01 SCU）记的，显示成 SCU
            qty, unit = scu_amount(qty, unit), "SCU"
        elif unit == "unit":
            unit = "个"
        lk = G.lot_key(k.item_id, k.quality, k.location, k.unit)
        a = alloc.get(lk) or {}
        value = _row_value(prices, k.item_id, k.quality, k.unit, line.quantity)
        if value:
            g["value"] += value
        rows.append({"item": label, "zh": zh, "en": en, "kind": _stock_kind(zh, en, k.unit),
                     "quality": "未知" if k.quality == "unknown" else _qlabel(k.quality),
                     "q": int(k.quality[6:]) if k.quality.startswith("exact:") else None,
                     "location": k.location, "place": place, "bin": b, "place_state": g["state"],
                     "qty": qty, "unit": unit, "id": k.item_id, "qkey": k.quality, "ukey": k.unit, "raw": line.quantity,
                     "changed": changed.get((k.item_id, k.quality, k.location, k.unit), ""),
                     "goal_qty": round(a.get("qty", 0.0), 6), "goal_titles": a.get("goals", []), "reserved": lk in reserved,
                     # 可用 = 在库 − 目标占用（1.6.55；以后再减挂单锁定）。挂单只能卖可用的
                     "avail": round(max(0.0, qty - a.get("qty", 0.0)), 6),
                     "value": round(value) if value else None,
                     "craft": craft_text(crafts.get((k.item_id, k.quality))) if crafts.get((k.item_id, k.quality)) else ""})
    here = SP.current_place()
    if here and not here.get("custom"):              # 当前位置还没东西：也列出来，方便直接入库到这里
        group(here["label"], SP.by_label(here["label"]))
    for place, meta in bins.items():                 # 建好还没放东西的仓位也列出来
        if meta.get("bins"):
            g = group(place, SP.match(place))
            for x in meta["bins"]:
                g["bins"].setdefault(x["name"], 0)
    for g in groups.values():                        # 仓位：总仓在前，其余按名字；带描述、默认
        meta = bins.get(g["label"]) or {}
        desc = {x["name"]: x.get("desc", "") for x in meta.get("bins", [])}
        names = sorted(n for n in g["bins"] if n != SP.MAIN_BIN)
        g["bins"] = ([{"name": SP.MAIN_BIN, "count": g["bins"].get(SP.MAIN_BIN, 0), "desc": "", "default": not meta.get("default")}]
                     + [{"name": n, "count": g["bins"][n], "desc": desc.get(n, ""), "default": meta.get("default") == n} for n in names])
        g["value"] = round(g["value"])
    order = {p["label"]: i for i, p in enumerate(SP.places())}
    known = sorted((g for g in groups.values() if g["state"] == "known"), key=lambda g: order.get(g["label"], 999))
    tree = []
    for g in known:
        if not tree or tree[-1]["sys"] != g["sys"]:
            tree.append({"sys": g["sys"], "places": []})
        tree[-1]["places"].append(g)
    priced = [r for r in rows if r["value"]]
    total = round(sum(r["value"] for r in priced))
    value = [f"参考估值（玩家市场最低出售挂牌价）：≈ {total:,} aUEC｜{len(priced)} 行有报价，{len(rows) - len(priced)} 行无报价"] if priced else []
    return {"rows": rows, "tree": tree,
            "custom": sorted((g for g in groups.values() if g["state"] == "custom"), key=lambda g: g["label"]),
            "unmatched": sorted((g for g in groups.values() if g["state"] == "unmatched"), key=lambda g: g["label"]),
            "here": here, "value": value, "value_total": total, "priced": len(priced), "bins": bins,
            "history": _history_view(t), "last_location": t.db.get("last_location", "")}


def _place_for(location, bin=None):
    """入库 / 移库的目标 → 库存里记的叫法「地点」或「地点｜仓位」。
    地点：列表里的用标准中文名（New Babbage → 新巴贝奇），别的（船、前哨、自己起的名字）检查一下、记进「自己的地点」。
    仓位：bin=None 时用地点的默认仓位；「总仓」或空 = 不分仓位；别的名字没建过就顺手建上"""
    from .. import stockplaces as SP
    place, b = SP.split_loc(location)
    if "｜" in str(location or "") and bin is None:
        bin = b
    p = SP.match(place)
    t = trade()
    if p:
        label = p["label"]
    else:
        label = SP.check_name(place)
        custom = list(t.db.get("stock_custom_places", []) or [])
        if label not in custom:
            t.db.set("stock_custom_places", custom + [label])
    bins = _bins(t)
    if bin is None:
        bin = (bins.get(label) or {}).get("default") or SP.MAIN_BIN
    bin = (bin or "").strip() or SP.MAIN_BIN
    if bin != SP.MAIN_BIN:
        bin = SP.check_bin(bin)
        meta = bins.setdefault(label, {"bins": [], "default": ""})
        if not any(x["name"] == bin for x in meta.setdefault("bins", [])):
            meta["bins"].append({"name": bin, "desc": ""})
            t.db.set("stock_bins", bins)
    return SP.join_loc(label, bin)


def _raw_amount(qty, ukey, allow_zero=False):
    """窗口里填的数量（SCU 或 个）→ 库存里存的整数（uSCU 或 个）"""
    try:
        v = float(str(qty).replace(",", "").strip())
    except ValueError:
        raise ValueError("数量需为数字")
    if ukey == "uSCU":
        n = int(round(v * 1_000_000))
    elif ukey == "cSCU":
        n = int(round(v * 100))
    else:
        if v != int(v):
            raise ValueError("此物品按「个」计数，数量需为整数")
        n = int(v)
    if n < 0 or v < 0:
        raise ValueError("数量不能是负数")
    if n == 0 and not allow_zero:
        raise ValueError("最小 1 uSCU（0.000001 SCU）" if v > 0 else "数量需大于 0")
    return n


@api
def stock_add(id="", qty=1, quality="", location=""):
    _SHORT["t"] = 0.0
    from ..trade.console import _quality
    from ..trade.models import StockKey, StockLine
    t = trade()
    if not t.catalog.get(id):
        return {"error": "未找到此物品"}
    qty = int(qty)
    if qty <= 0 or not location.strip():
        return {"error": "数量需大于 0，地点不能为空"}
    try:
        location = _place_for(location)
    except ValueError as e:
        return {"error": str(e)}
    q = _quality(quality) if quality else "unknown"
    t.db.set("last_location", location)
    preview = t.inventory.prepare([StockLine(StockKey(id, q or "unknown", location), qty)], "add")
    t.inventory.commit(preview, allow_duplicate=True)
    return stock()


@api
def craft_slots_for(en="", zh=""):
    """入库时：制造出来的东西有哪些材料槽要填品质（1.6.67）；不是能制造的返回 []"""
    from ..crafting import for_item, craft_slots
    return craft_slots(for_item(en, zh)) if (en or zh) else []


@api
def stock_add_named(name="", qty=0, unit="", quality="", location="", en="", zh="", kind="", id="", note="", source="", bin=None, craft=None):
    """库存页手动入库：名字（中文或英文；矿物、材料、物品都行）、数量、单位（个 / SCU / uSCU）、品质、位置、备注。
    从联想里点选的会带上 en / zh / kind，直接用，不再猜；矿物默认按 SCU，其他默认按个；交易库里没有的自动建成本地物品。
    位置：地点列表里的用标准中文名，别的记成自己的地点；source：从哪录的（库存页 / F8 / 物品查询）"""
    _SHORT["t"] = 0.0
    from .. import goals as G
    name = (name or "").strip()
    if en:
        u = unit or ("SCU" if kind == "矿物" else "个")
    else:
        if not name:
            return {"error": "需填写物品或矿物名称"}
        ores = mineral_search(q=name)
        if ores and (len(name) >= 2 or ores[0]["zh"] == name):
            en, zh, u = ores[0]["en"], ores[0]["zh"], unit or "SCU"
        else:
            from ..trade.names import canonical
            hit = canonical(name, "")                          # 汉化包里有的：用标准中英文名
            if hit:
                zh, en = hit
            else:
                hits = item_search(q=name)
                exact = [h for h in hits if name.lower() in ((h.get("zh") or "").lower(), h["name"].lower())]
                h = (exact or hits or [None])[0]
                en, zh = (h["name"], h.get("zh") or "") if h else (name, "")
            u = unit or "个"
    if u not in ("个", "SCU", "uSCU"):
        return {"error": "单位仅支持 个、SCU 或 uSCU"}
    try:
        location = _place_for(location, bin)
        craft = [x for x in (craft or []) if str(x.get("q", "")).strip() != ""]
        if craft:                                              # 制造的东西：品质记各槽平均，各槽另外存（1.6.67）
            for x in craft:
                x["q"] = max(0, min(1000, int(float(x["q"]))))
            quality = round(sum(x["q"] for x in craft) / len(craft))
        G.add_stock(trade(), en, zh, qty, u, quality, location, item_id=id or None, note=note, source=source or "库存页", craft=craft)
    except ValueError as e:
        return {"error": str(e)}
    out = stock()
    out["added"] = f"{zh or en} {qty} {u}" + (f"（品质 {quality}）" if str(quality).strip() else "")
    return out


@api
def stock_suggest(q=""):
    """手动入库的名字联想：矿物、交易库里的物品、汉化包里的物品名，中文 / 英文 / 名字的一部分 / 错一两个字都行。
    返回 [{zh, en, kind: 矿物 / 物品, unit}]，最多 12 个"""
    from ..trade.names import suggest, _fold_en
    q = (q or "").strip()
    if not q:
        return []
    out, seen = [], set()

    def add(zh, en, kind):
        k = _fold_en(en)
        if k and k not in seen:
            seen.add(k)
            out.append({"zh": zh or "", "en": en, "kind": kind, "unit": "SCU" if kind == "矿物" else "个"})
    for o in mineral_search(q=q)[:4]:
        add(o["zh"], o["en"], "矿物")
    for zh, en in suggest(q, 12):
        add(zh, en, "物品")
    try:
        t = trade()
        for i in t.catalog.search(q)[:6]:                 # 以前入过库、查过价的（本地物品也在这里）
            lab = t.label(i.id)
            add(lab.split("（")[0] if "（" in lab else "", i.name, "物品")
    except Exception:
        pass
    return out[:12]


@api
def stock_set_quality(id="", qkey="", location="", ukey="", quality="", note=""):
    """改一行库存的品质（比如「未知」改成 650；空着 = 未知）：同一批数量从旧品质挪到新品质，一次记录、能撤销"""
    _SHORT["t"] = 0.0
    from ..trade.console import _quality
    from ..trade.models import StockKey
    t = trade()
    try:
        newq = _quality(str(quality)) if str(quality or "").strip() else "unknown"
        newq = newq or "unknown"
    except ValueError as e:
        return {"error": str(e)}
    if newq == qkey:
        return stock()
    try:
        t.inventory.requality(StockKey(id, qkey, location, ukey), newq, note=note)
    except ValueError as e:
        return {"error": str(e)}
    return stock()


@api
def stock_undo(batch=""):
    _SHORT["t"] = 0.0
    try:
        trade().inventory.undo(batch)
    except ValueError as e:
        msg = str(e)
        if "负数" in msg:
            msg = "无法撤销：此记录之后，相关物品已出库、移库或修改过数量"
        return {"error": msg}
    return stock()


def _row_key(id, qkey, location, ukey):
    from ..trade.models import StockKey
    if not all(str(v or "").strip() for v in (id, qkey, location, ukey)):
        raise ValueError("此行库存已变更，需刷新")
    return StockKey(id, qkey, location, ukey)


@api
def stock_out(id="", qkey="", location="", ukey="", qty="", reason="", note=""):
    """出库：卖了、用掉、交了维科洛……（qty 按这一行显示的单位：SCU 或 个）"""
    _SHORT["t"] = 0.0
    try:
        trade().inventory.out(_row_key(id, qkey, location, ukey), _raw_amount(qty, ukey), reason=reason, note=note, source="库存页")
    except ValueError as e:
        return {"error": str(e)}
    return stock()


@api
def stock_set_qty(id="", qkey="", location="", ukey="", qty="", note=""):
    """改数量：在游戏里数完直接改成实际数（可以改成 0）"""
    _SHORT["t"] = 0.0
    try:
        trade().inventory.set_quantity(_row_key(id, qkey, location, ukey), _raw_amount(qty, ukey, allow_zero=True),
                                       note=note, source="库存页")
    except ValueError as e:
        return {"error": str(e)}
    return stock()


@api
def stock_move(id="", qkey="", location="", ukey="", qty="", to="", note="", bin=None):
    """移库：搬到别的地点（qty 空着 = 整行都搬）"""
    _SHORT["t"] = 0.0
    try:
        key = _row_key(id, qkey, location, ukey)
        dest = _place_for(to, bin)
        n = _raw_amount(qty, ukey) if str(qty or "").strip() else next(
            (l.quantity for l in trade().inventory.list_stock() if l.key == key), 0)
        if not n:
            raise ValueError("此行库存已变更，需刷新")
        trade().inventory.move(key, dest, n, note=note, source="库存页")
    except ValueError as e:
        return {"error": str(e)}
    out = stock()
    out["moved_to"] = dest
    return out


@api
def stock_relocate(location="", to="", bin=None):
    """「未归类」里的一个位置（以前手打的，对不上地点列表）：整个归到选好的地点"""
    _SHORT["t"] = 0.0
    try:
        dest = _place_for(to, bin)
        n = trade().inventory.relocate(location, dest, note=f"归位：{location} → {dest}")
    except ValueError as e:
        return {"error": str(e)}
    out = stock()
    out["relocated"] = n
    return out


@api
def stock_keep_custom(location=""):
    """「未归类」里的位置其实没错（比如船名）：留下来当自己的地点"""
    from .. import stockplaces as SP
    try:
        name = SP.check_name(location)
    except ValueError as e:
        return {"error": str(e)}
    if name != location:
        return {"error": "地点名称含多余的空格或符号，可用「归入地点」更换"}
    t = trade()
    custom = list(t.db.get("stock_custom_places", []) or [])
    if name not in custom:
        t.db.set("stock_custom_places", custom + [name])
    return stock()


@api
def stock_places():
    """选地点用：游戏里所有能存东西的地方（按星系、星球排好）、自己的地点、当前位置"""
    from .. import stockplaces as SP
    t = trade()
    return {"places": [SP.public(p) for p in SP.places()], "custom": list(t.db.get("stock_custom_places", []) or []),
            "here": SP.current_place(), "last": t.db.get("last_location", ""), "bins": _bins(t)}


@api
def stock_place_add(name=""):
    """选地点时自己写的名字：能对上列表的就用列表里的；对不上的检查一下（不能只有数字）记成自己的地点"""
    from .. import stockplaces as SP
    p = SP.match(name)
    if p:
        return SP.public(p)
    try:
        label = _place_for(name)
    except ValueError as e:
        return {"error": str(e)}
    return {"label": label, "zh": label, "en": "", "sys_zh": "", "path": label, "kind": "其他", "custom": True}


@api
def stock_bin_save(place="", name="", desc="", default=False, old=""):
    """新建仓位 / 改仓位（名字、描述、是不是默认）。改名时这个仓位里的东西一起换过去（一笔移库，能撤销）"""
    from .. import stockplaces as SP
    _SHORT["t"] = 0.0
    t = trade()
    try:
        label = SP.split_loc(_place_for(place, SP.MAIN_BIN))[0]
        name = SP.check_bin(name)
        bins = _bins(t)
        meta = bins.setdefault(label, {"bins": [], "default": ""})
        meta.setdefault("bins", [])
        old = (old or "").strip()
        if old and old != name:
            if any(x["name"] == name for x in meta["bins"]):
                raise ValueError(f"{label} 已有名为「{name}」的仓位")
            t.inventory.rename_location(SP.join_loc(label, old), SP.join_loc(label, name), note=f"仓位改名：{old} → {name}")
            meta["bins"] = [x for x in meta["bins"] if x["name"] != old]
            if meta.get("default") == old:
                meta["default"] = name
        elif not old and any(x["name"] == name for x in meta["bins"]):
            raise ValueError(f"{label} 已有名为「{name}」的仓位")
        hit = next((x for x in meta["bins"] if x["name"] == name), None)
        if hit:
            hit["desc"] = str(desc or "").strip()[:100]
        else:
            meta["bins"].append({"name": name, "desc": str(desc or "").strip()[:100]})
        if default:
            meta["default"] = name
        elif meta.get("default") == name:
            meta["default"] = ""
        t.db.set("stock_bins", bins)
    except ValueError as e:
        return {"error": str(e)}
    out = stock()
    out["bin"] = SP.join_loc(label, name)
    return out


@api
def stock_bin_delete(place="", name=""):
    """删仓位：里面的东西放回这个地点的总仓（一笔移库，能撤销）"""
    from .. import stockplaces as SP
    _SHORT["t"] = 0.0
    t = trade()
    bins = _bins(t)
    meta = bins.get(place) or {}
    if not any(x["name"] == name for x in meta.get("bins", [])) and not any(
            l.key.location == SP.join_loc(place, name) for l in t.inventory.list_stock()):
        return {"error": "未找到此仓位"}
    try:
        n = t.inventory.rename_location(SP.join_loc(place, name), place, note=f"删除仓位「{name}」：物品移回总仓")
    except ValueError as e:
        return {"error": str(e)}
    meta["bins"] = [x for x in meta.get("bins", []) if x["name"] != name]
    if meta.get("default") == name:
        meta["default"] = ""
    t.db.set("stock_bins", bins)
    out = stock()
    out["moved"] = n
    return out


@api
def stock_reserve(id="", qkey="", location="", ukey="", on=True):
    """这一行「不给目标用」（比如留着卖的）：目标不算它；再点一次取消"""
    from .. import goals as G
    _SHORT["t"] = 0.0
    t = trade()
    keys = list(t.db.get(G.RESERVED, []) or [])
    k = G.lot_key(id, qkey, location, ukey)
    if on and k not in keys:
        keys.append(k)
    if not on:
        keys = [x for x in keys if x != k]
    t.db.set(G.RESERVED, keys)
    return stock()


@api
def stock_ledger(start="", end="", type="", place="", q="", page=1, size=20):
    """仓储流水：按日期（本地日期，含两头）、类型、地点、物品名筛选，分页。新的在前"""
    from datetime import datetime, date
    t = trade()

    def day(v):
        try:
            return date.fromisoformat(str(v)[:10]) if v else None
        except ValueError:
            return None
    d0, d1 = day(start), day(end)
    q = (q or "").strip().lower()
    out = []
    for b in _all_batches(t):
        try:
            local = datetime.fromisoformat(b["at"]).astimezone().date()
        except ValueError:
            local = None
        if local and ((d0 and local < d0) or (d1 and local > d1)):
            continue
        if type and b["type"] != type:
            continue
        if place and place not in b["places"]:
            continue
        if q and q not in (b["names"] + " " + " ".join(b["items"]) + " " + b["note"]).lower():
            continue
        out.append(b)
    size = max(5, min(100, int(size or 20)))
    pages = max(1, (len(out) + size - 1) // size)
    page = max(1, min(pages, int(page or 1)))
    rows = [{k: v for k, v in b.items() if k != "names"} for b in out[(page - 1) * size: page * size]]
    places = sorted({p for b in _all_batches(t) for p in b["places"]})
    return {"rows": rows, "total": len(out), "page": page, "pages": pages, "size": size, "types": list(LEDGER_TYPES), "places": places}


@api
def stock_prices():
    """库存里有品质的东西去玩家市场（UEX / SCM）查一遍价（同时查，结果缓存 1 小时），查完重算估值"""
    from concurrent.futures import ThreadPoolExecutor
    from ..trade.providers.http import quality_group
    t = trade()
    todo = {}
    for line in t.inventory.list_stock():
        k = line.key
        if k.quality.startswith("exact:"):
            todo[(k.item_id, quality_group(k.quality[6:]))] = True

    def one(key):
        iid, group = key
        item = t.catalog.get(iid)
        if not item or iid.startswith("local:"):
            return 0
        try:
            return sum(1 for r in t.prices(item, group, "sell") if r.stats)
        except Exception:
            return 0
    with ThreadPoolExecutor(4) as ex:
        found = sum(1 for n in ex.map(one, list(todo)) if n)
    out = stock()
    out["checked"], out["found"] = len(todo), found
    return out


@api
def goal_finish_preview(id=""):
    """目标「做完了」之前先看要扣哪些材料（做一次的量）"""
    from .. import goals as G
    try:
        takes, short = G.finish_takes(trade(), id)
    except ValueError as e:
        return {"error": str(e)}
    g = next((x for x in G.load() if x["id"] == id), {})
    return {"title": g.get("title", ""), "times": g.get("times", 1), "short": short,
            "takes": [{"name": x["zh"] or x["en"], "place": x["place"], "quality": x["quality"], "qty": x["qty"], "unit": x["unit"]}
                      for x in (takes or [])]}


@api
def goal_finish(id=""):
    """目标「做完了」：从库存扣掉做一次用掉的材料（库存页的记录里能撤销），次数减一，最后一次做完就删掉这个目标"""
    from .. import goals as G
    _SHORT["t"] = 0.0
    try:
        r = G.finish(trade(), id)
    except ValueError as e:
        return {"error": str(e)}
    out = _goals_view()
    out["finished"] = {"title": r["title"], "left": r["left"], "lines": len(r["taken"])}
    return out


# ================================================================ 维科洛兑换

_wk_cache = {}


@api
def wikelo_search(q=""):
    from .. import wikelo
    rows = wikelo.search(q or "")
    out = []
    for c in rows[:60]:
        key = str(len(_wk_cache))
        _wk_cache[key] = c
        out.append({"key": key, "title": c["t"], "type": c["type"], "reward": c["rz"] or "、".join(c["rewards"][:2])})
    return out


@api
def wikelo_detail(key=""):
    from .. import wikelo
    from ..trade.console import material_source
    c = _wk_cache.get(key)
    if not c:
        return {"error": "未找到此兑换，需重新搜索"}
    reqs = []
    groups = []
    for r in c["req"]:
        k = (r["z"], r["q"], r["u"]) if wikelo.note_for(r["n"]) else (r["n"],)
        if groups and groups[-1][0] == k:
            groups[-1][1].append(r)
        else:
            groups.append((k, [r]))
    for _, rs in groups:
        r = rs[0]
        name = f"{r['z']}（{'、'.join(x['n'] for x in rs)}）" if len(rs) > 1 else wikelo.req_label(r)
        try:
            tip = material_source(r["n"])
        except Exception:
            tip = ""
        reqs.append({"name": name, "q": (f"{r['q']:g} {r['u']}" if r["q"] else "若干") + (" 各" if len(rs) > 1 else ""),
                     "tip": tip, "en": r["n"], "zh": r["z"]})
    return {"id": c["id"], "title": c["t"], "type": c["type"], "reward": c["rz"] or "、".join(c["rewards"][:4]) or c["te"], "req": reqs}


# ================================================================ 目标：库存联动维科洛兑换 / 制造 / 交易

_SHORT = {"t": 0.0, "map": {}}


def _gkey(name):
    """目标材料和矿 / 物品对名字用：忽略大小写、空格和「(Ore)」「(Raw)」「原矿」这类后缀"""
    n = re.sub(r"\s*[\(（](ore|raw|原矿|矿石)[\)）]\s*$", "", (name or "").strip(), flags=re.I)
    n = re.sub(r"(原矿|矿石)$", "", n)
    return re.sub(r"\s+", "", n.lower())


def goal_short(force=False):
    """目标还缺的材料：{名字键: {en, zh, short, unit, minq, goals}}，英文名和中文名都能查。算一次记 30 秒；
    目标或库存一改就清掉重算"""
    now = time.time()
    if not force and now - _SHORT["t"] < 30:
        return _SHORT["map"]
    m = {}
    try:
        from .. import goals as G
        if G.load():
            for t in G.plan(trade())["shortfall"]:
                for k in {_gkey(t["en"]), _gkey(t["zh"])} - {""}:
                    m[k] = t
    except Exception:
        m = {}
    _SHORT.update(t=now, map=m)
    return m


def _goal_for(*names):
    sm = goal_short()
    for n in names:
        if n and _gkey(n) in sm:
            return sm[_gkey(n)]
    return None


def _goal_text(t, q=None, lots=None):
    """「🎯 目标还缺 金 2 SCU（品质 ≥800，这块 650 不够）」。
    lots：扫描结果里这种矿的每一份（1.6.42）：同一种矿有几种品质时逐份写够不够，
    「品质 ≥600：662 那份够（精炼后 1.50 SCU），363 那份不够」"""
    amt = f"{t['short']:g} {t['unit']}" if t.get("unit") else f"{t['short']:g}"
    need_q = f"品质 ≥{t['minq']}" if t.get("minq", 0) > 1 else ""
    known = [r for r in (lots or []) if r.get("q") is not None]
    if need_q and len(known) >= 2:
        parts = []
        for r in sorted(known, key=lambda r: -r["q"]):
            good = r["q"] >= t["minq"]
            v = r.get("refined")
            got = "" if not v else f"（精炼后 {v:.2f} SCU）" if v >= 1 else f"（精炼后 {v * 1e6:,.0f} uSCU）"
            parts.append(f"品质 {r['q']}：" + ("已达标" + got if good else "未达标"))
        need_q += "：" + "，".join(parts)
    elif q is not None and need_q:
        need_q += f"，当前 {q} " + ("已达标" if q >= t["minq"] else "未达标")
    return f"🎯 目标缺少 {t['zh'] or t['en']} {amt}" + (f"（{need_q}）" if need_q else "")


def _mark_goal_lines(lines):
    """信号说明里有目标还缺的矿：行首加 🎯"""
    pats = []
    for t in goal_short().values():
        if t.get("zh"):        # 整词匹配：目标要「金」，不能把「林登金」「艾格瑞金属」也标上
            pats.append(re.compile(f"(?<![\u4e00-\u9fff]){re.escape(t['zh'])}(?![\u4e00-\u9fff])"))
        if t.get("en"):
            pats.append(re.compile(rf"\b{re.escape(t['en'])}\b", re.I))
    return [("🎯 " + l) if any(p.search(l) for p in pats) else l for l in lines]


def crafting_zh(opt):
    """蓝图材料的中文名（手挖的萨达瑞晶、哈丹水晶这些也有中文名，1.6.41 以前显示英文）"""
    from ..crafting import material_zh
    k, name, *_ = opt
    return material_zh(name)


def _goals_view():
    from .. import goals as G
    t = trade()
    p = G.plan(t)
    p["last_location"] = t.db.get("last_location", "")
    for g in p["goals"]:
        for r in g["rows"]:
            if r["short"] > 0:
                r["tip"] = G.where_to_get(r["en"])
    for t in p["shortfall"]:
        t["tip"] = G.where_to_get(t["en"])
    from ..crafting import by_key, effect, slot_zh, laser_total
    for g in p["goals"]:
        if g.get("kind") != "craft" or g.get("missing"):
            continue
        bp = by_key(g["ref"])
        if not bp:
            continue
        # 每个材料槽的品质：先用分给它的库存的加权平均品质（混着做出来就是这个品质）
        qs = {}
        for idx, (slot, opts, mods) in enumerate(bp["slots"]):
            row = next((r for r in g["rows"] if r["slot"] == slot), None)
            qs[idx] = row.get("avg_q") if row else None
        g["slots_q"] = [{"idx": i, "slot": slot_zh(sl), "has_mods": bool(m), "material": "/".join(crafting_zh(o) for o in opts),
                         "q": qs[i], "minq": max([x[3] for x in opts] + [0])} for i, (sl, opts, m) in enumerate(bp["slots"])]
        g["effect"] = effect(bp, {i: q for i, q in qs.items() if q is not None})
        g["effect_total"] = laser_total(bp, {i: q for i, q in qs.items() if q is not None}) if g["effect"] else None
        st = _craft_struct(bp)                       # 1.6.47：目标页和制造页共用槽位卡片 + 属性统计
        for sl in st["slots"]:
            sl["q"] = qs.get(sl["idx"])
        g["craft"] = {"head": st["head"], "slots": st["slots"]}
    return p


@api
def goals():
    return _goals_view()


@api
def goal_add(kind="", ref="", times=1):
    _SHORT["t"] = 0.0
    from .. import goals as G
    try:
        G.add(kind, ref, int(times or 1))
    except ValueError as e:
        return {"error": str(e)}
    return _goals_view()


@api
def goal_update(id="", times=None, move=0, remove=False):
    _SHORT["t"] = 0.0
    from .. import goals as G
    try:
        G.update(id, None if times in (None, "") else int(times), int(move or 0), bool(remove))
    except ValueError as e:
        return {"error": str(e)}
    return _goals_view()


@api
def goal_stock_add(en="", zh="", qty=0, unit="", quality="", location=""):
    _SHORT["t"] = 0.0
    """目标页里直接入库（交易库里没有的材料自动建成本地物品）"""
    from .. import goals as G
    try:
        G.add_stock(trade(), en, zh, qty, unit, quality, _place_for(location), source="目标")
    except ValueError as e:
        return {"error": str(e)}
    return _goals_view()


@api
def craft_effect(key="", qualities=None):
    """蓝图在给定材料品质下，每个槽对成品属性的影响（目标页「品质影响」）。qualities：{槽序号: 品质}"""
    from ..crafting import by_key, effect, laser_total
    bp = _bp_cache.get(key) or by_key(key)
    if not bp:
        return {"error": "未找到此蓝图"}
    slots = effect(bp, qualities or {})
    return {"slots": slots, "total": laser_total(bp, qualities or {}) if slots else None}


@api
def goal_prices():
    """还差的东西在玩家市场（UEX / SCM）上最便宜多少钱，合计大概要花多少（同时查，结果缓存）"""
    from concurrent.futures import ThreadPoolExecutor
    from .. import goals as G
    from ..trade.console import SOURCE_ZH
    t = trade()
    todo = G.plan(t)["shortfall"]

    def one(x):
        try:
            iid = x["item"]
            if not iid:                     # 交易库里还没有：按英文名去玩家市场搜一次，名字完全一样才算
                items, _ = t.market.lookup(x["en"])
                hit = next((i for i in items if i.name.casefold() == x["en"].casefold()), None)
                if not hit:
                    return x, None
                if x["zh"]:
                    t.catalog.add_alias(hit.id, x["zh"])
                iid = hit.id
            return x, G.market_price(t, iid, x["minq"])
        except Exception:
            return x, None

    rows, total, priced = [], 0.0, 0
    with ThreadPoolExecutor(4) as ex:
        for x, best in ex.map(one, todo):
            if best:
                price, src, unit, cur = best
                cost = float(price) * x["short"]
                total += cost
                priced += 1
                rows.append({"en": x["en"], "minq": x["minq"], "unit": x["unit"], "price": float(price), "price_unit": unit,
                             "currency": cur, "src": SOURCE_ZH.get(src, src), "cost": cost})
            else:
                rows.append({"en": x["en"], "minq": x["minq"], "unit": x["unit"], "price": None})
    return {"rows": rows, "total": total, "priced": priced, "unpriced": len(rows) - priced}


# ================================================================ 找矿点 / 制造

@api
def mineral_search(q=""):
    from ..data import SIGNATURES
    from ..gems import GEMS
    from ..i18n import mineral_zh
    from ..locations import _match_zh
    names = list(SIGNATURES) + list(GEMS)              # 地面小矿（车矿、手采）也能搜
    en_names = {k.lower(): k for k in names}
    out = []
    for token in re.split(r"[\s,，、]+", q.strip()):
        if not token:
            continue
        m = (en_names.get(token.lower()) or next((k for k in names if mineral_zh(k) == token), None)   # 中文名一字不差的先认（「杰金」不要模糊成「愈金」）
             or _match_zh(token))
        if not m:
            m = next((k for k in names if token.lower() in k.lower() or token in mineral_zh(k)), None)
        if m and m not in [x["en"] for x in out]:
            out.append({"en": m, "zh": mineral_zh(m)})
    return out


def _mine_nav(loc, mineral):
    """矿点 → 怎么导航过去：Aaron Halo 用小行星带导航（挑这种矿最多的带）；别的星球、卫星、小行星带去导航页搜它"""
    from ..halo import BANDS
    if loc["kind"] in ("Cave", "Interior"):          # 校准站矿洞、Breaker 站内部：没有能量子跳的点
        return {"kind": "none", "hint": "不能直接导航"}
    if loc["name"] == "Aaron Halo":
        bands = sorted((r for r in BANDS if mineral in r[5]), key=lambda r: -r[4])
        return {"kind": "halo", "band": bands[0][0] if bands else 5,
                "hint": f"第{bands[0][0]}带最多" if bands else "此矿物不是任何一条带的主要矿物，选择密度最高的第5带"}
    from ..locations import zh_name
    if re.fullmatch(r"(ARC|CRU|HUR|MIC)-L\d", loc["name"]):
        return {"kind": "hint", "hint": f"在星图中选择 {loc['name']} 量子跳跃，矿物位于该处小行星中"}
    m = re.search(r"\(([^)]+)\)", loc["name"])
    q = m.group(1) if m else loc["name"]
    if loc["kind"] in ("Moon", "Planet") and nav_search(q=q).get("total"):
        return {"kind": "search", "q": q, "hint": "量子跳跃到此星球或卫星，低空飞行扫描；导航页列出其上的地点"}
    return {"kind": "hint", "hint": f"在星图中量子跳跃到 {zh_name(loc)}"}


@api
def mineral_info(name=""):
    from ..data import best_price, REFINERIES, RARITY
    from ..i18n import mineral_zh, station_zh
    from ..locations import where, zh_name, _SYS_ZH, _TYPE_ZH
    rows = []
    for pct, loc in where(name)[:30]:
        others = sorted(((best_price(m)[0], m) for m in loc["minerals"] if m != name), reverse=True)[:3]
        rows.append({"pct": pct, "place": zh_name(loc), "system": _SYS_ZH[loc["system"]], "kind": _TYPE_ZH[loc["kind"]],
                     "also": [mineral_zh(m) for p, m in others if p], "name": loc["name"], "type": loc["kind"],
                     "nav": _mine_nav(loc, name)})
    price, city = best_price(name)
    bonus = sorted(((b.get(name, 0), st) for st, (sys_, b) in REFINERIES.items()), reverse=True)
    uses = ""
    try:
        from ..crafting import uses_report
        uses = uses_report(name)
    except Exception:
        pass
    try:
        from ..crafting import mat_summary
        craft_count = mat_summary(name)["count"]
    except Exception:
        craft_count = 0
    from ..gems import GEMS
    gem = GEMS.get(name)
    if gem:                                   # 地面小矿：不精炼，卖原矿；写类型、信号、终端价、不稳定性、抗性
        gem = {"kind": gem["kind"], "rs": gem["rs"], "price": gem["price"], "inst": gem["inst"], "res": gem["res"]}
    return {"en": name, "zh": mineral_zh(name), "rarity": RARITY.get(name, ""), "price": price, "city": city or "", "gem": gem,
            "craft_count": craft_count, "goal": (lambda g: _goal_text(g) if g else "")(_goal_for(name, mineral_zh(name))),
            "rows": rows, "total": len(where(name)),
            "refine": [{"station": station_zh(st), "bonus": b} for b, st in bonus[:3] if b > 0], "uses": uses}


_bp_cache = {}


@api
def craft_search(q=""):
    from ..crafting import search as s, display_name, name_parts, GEAR_ZH, bp_key, variant_note
    out = []
    for bp in s(q, limit=30):
        key = bp_key(bp)
        _bp_cache[key] = bp
        note = variant_note(bp)
        zh, en = name_parts(bp)
        out.append({"key": key, "name": display_name(bp) + (f"｜{note}" if note else ""), "zh": zh, "en": en, "note": note,
                    "kind": GEAR_ZH.get((bp["g"], bp["t"]), bp["t"] or bp["g"])})
    return out


@api
def craft_browse(cat="", sub="", part="", maker="", q="", unlocked=False, offset=0, mat="", mq=None):
    """蓝图字典：分类筛选 + 分页；mat=只看用到这种矿的（mq=手上矿的品质，标出够不够做）"""
    from ..crafting import browse, display_name, category_zh, part_of, SUB_ZH, bp_key, variant_note, needs, material_zh
    r = browse(cat, sub, part, maker, q, bool(unlocked), int(offset or 0), mat=mat)
    try:
        mq = int(mq) if mq not in (None, "") else None
    except (TypeError, ValueError):
        mq = None
    rows = []
    for bp in r["rows"]:
        key = bp_key(bp)
        _bp_cache[key] = bp
        tags = [t for t in (part_of(bp), SUB_ZH.get(bp["s"] or "", bp["s"] or ""), variant_note(bp)) if t]
        row = {"key": key, "name": display_name(bp), "kind": category_zh(bp), "tags": " · ".join(tags),
               "maker": bp["m"] or "", "unlocked": bool(bp["d"])}
        if mat:
            n = needs(bp, mat)
            minq = max(m for _, m in n)
            row["need"] = f"{material_zh(mat)} {sum(x for x, _ in n):g} SCU" + (f"（品质 ≥{minq}）" if minq > 1 else "")
            if mq is not None and minq > 1:          # 只有带品质门槛的才标够不够
                row["ok"] = mq >= minq
        rows.append(row)
    out = {**r, "rows": rows}
    if mat:
        from ..crafting import mat_summary
        out["mat"] = {"en": mat, "zh": material_zh(mat), "q": mq, **mat_summary(mat, mq)}
    return out


@api
def craft_detail(key=""):
    from ..crafting import describe, by_key, bp_key, variant_note
    bp = _bp_cache.get(key) or by_key(key)
    if not bp:
        hits = craft_search(key)
        bp = _bp_cache.get(hits[0]["key"]) if hits else None
    if not bp:
        return {"error": "未找到此蓝图"}
    from ..crafting import mix_targets
    note = variant_note(bp)
    text = describe(bp)
    if note:                                   # 同名多份配方：标题行后面注明是哪一份
        first, _, rest = text.partition("\n")
        text = f"{first}｜{note}\n{rest}" if rest else f"{first}｜{note}"
    return {"key": bp_key(bp), "text": text, "mix": mix_targets(bp), **_craft_struct(bp, note)}


def _craft_struct(bp, note=""):
    """制造页改版（1.6.47）用的结构化详情：标题标签、材料槽（带品质曲线）、去哪挖、蓝图来源"""
    from ..crafting import header, slot_zh, group_mods, material_zh, curve_text, prop_zh, _clean_title, PROP_KEY, LOWER_BETTER
    from ..data import best_price
    from ..locations import where, zh_name
    h = header(bp)
    h["note"] = note
    slots, minerals = [], []
    for idx, (slot, opts, mods) in enumerate(bp["slots"]):
        mats = [{"kind": k, "en": name, "zh": material_zh(name), "qty": qty, "unit": "SCU" if k == "r" else "个", "minq": minq}
                for k, name, qty, minq in opts]
        gm = group_mods(mods)
        curves = [{"prop": pz, "name": prop_zh(pz, bp), "key": PROP_KEY.get(pz, ""), "add": segs[0][4], "lower": pz in LOWER_BETTER,
                   "segs": [list(x[:4]) for x in segs], "text": curve_text(pz, segs, prop_zh(pz, bp))} for pz, segs in gm.items()]
        slots.append({"idx": idx, "slot": slot_zh(slot), "mats": mats, "minq": max([m["minq"] for m in mats] + [0]), "curves": curves})
        minerals += [name for k, name, *_ in opts if k == "r"]
    mine = []
    for m in dict.fromkeys(minerals):
        rows = where(m)[:2]
        price, city = best_price(m)
        mine.append({"en": m, "zh": material_zh(m), "spots": [{"loc": zh_name(loc), "pct": round(pct)} for pct, loc in rows],
                     "price": price, "city": city or ""})
    src = [{"title": _clean_title(t), "who": w, "kind": k, "systems": sy, "chance": ch} for t, w, k, sy, ch in bp["src"]]
    return {"head": h, "slots": slots, "mine": mine, "sources": src, "nsrc": bp["nsrc"]}


@api
def craft_stats(key="", qualities=None):
    """成品属性统计（制造 / 目标页）：各槽品质 → 每项属性的基础值、强化后、变化（1.6.47）"""
    from ..crafting import by_key, stats, effect
    bp = _bp_cache.get(key) or by_key(key)
    if not bp:
        return {"error": "未找到此蓝图"}
    qs = qualities or {}
    return {"stats": stats(bp, qs), "slots": effect(bp, qs)}


@api
def craft_mix(need=0, target=0, margin=2, boxes=()):
    """混料计算器：boxes = [[品质, SCU], …]"""
    from ..crafting import mix_plan
    try:
        rows = [(float(q), float(s)) for q, s in boxes if str(q).strip() and str(s).strip()]
    except (TypeError, ValueError):
        return {"ok": False, "msg": "品质和数量需为数字"}
    return mix_plan(float(need or 0), float(target or 0), rows, float(margin or 0))


# ================================================================ 导航

_places = {}


def _clear_services_caches():
    """更新数据后清掉接口层的缓存（2026-10-28 审查）"""
    _wk_cache.clear()
    _bp_cache.clear()
    _places.clear()


try:
    from ..data_pack import CACHE_HOOKS as _CACHE_HOOKS
    _CACHE_HOOKS.append(_clear_services_caches)
except Exception:
    pass


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
        import math
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


POS_FRESH = 120          # 「用当前位置」：位置最多是多少秒前读到的

_WHERE = {"t": 0.0, "v": None, "tried": 0.0}


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


_AREA = {"key": None, "v": None}
AREA_MAX_AGE = 10         # 位置超过 10 秒没更新就不判断产矿区（不过滤），刚跳跃、读不到时宁可不过滤


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


HERE_WAIT = 90            # 点「用当前位置新建」后等 /showlocation 坐标多少秒
_HERE = {"name": None, "until": 0.0, "thread": None}


# 游戏里的热键：(设置名, 默认键, 名字)。撞键时排在前面的生效（顺序和以前一样：物品识别 > 记路标 > 一键定位 > 问题反馈 > 采矿助手 > 盘点）
HOTKEYS = [("trade_capture_key", "F8", "物品识别"), ("mark_key", "", "记录路标"), ("fix_key", "", "一键定位"),
           ("report_key", "F10", "问题反馈"), ("live_key", "F5", "采矿助手开关"), ("count_key", "F6", "盘点"),
           ("ore_key", "", "原矿记录")]


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


def _wp_log(msg):
    try:
        from .. import paths
        with open(paths.log("nav_log.txt"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%F %T')} 路标 {msg}\n")
    except OSError:
        pass


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


# ================================================================ 原矿记录（1.6.70）

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
    view = _ORE_LAST["view"]
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


# ================================================================ 小行星带（Aaron Halo）导航

_HALO = {"plan": None, "sess": 0, "seen": None, "last": None, "ev": threading.Event(), "lock": threading.Lock()}


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


def _surface_limit(here):
    """离地多高以内算「在星球上」（跟着星球自转记坐标）；再高就当太空，记星系坐标"""
    return max(100_000, here.get("radius_km", 0) * 1000 * 0.25)


@api
def waypoint_delete(name=""):
    from ..navigate import delete_waypoint
    delete_waypoint(name)
    return waypoints()


QT_SPEED = 50_000          # 米/秒：比这快就是在量子跳跃（普通飞行最快一千多米每秒）
LIVE_STALE = 3.0           # 右上角多少秒没读到才算读不到（这时才用玩家自己输的 /showlocation）

DI_HELP = "未检测到右上角位置信息：在游戏中按 ~ 打开控制台，输入 r_DisplayInfo 2 后回车"


# ---- 引擎类 2026-10-28 剪到 engines/（逻辑没改）；实例仍在下面创建，测试里 S._live / S._Steady 照旧
from .engines.nav import _Steady, _CamFilter, _Nav, _GameEvents
from .engines.live import _Live
from .engines.hover import _Hover
from .engines.count import _Count
from .engines.pos import _Pos, _LogWatch


def _mark_hud(data):
    try:
        _hud().marker(data)
    except Exception:            # 测试里的假悬浮窗没有这个接口
        pass


_MK_CFG = {"on": True, "at": 0.0}


def _marker_on():
    """设置里的 nav_marker（两秒读一次，导航每 0.1 秒问一次）"""
    if time.time() - _MK_CFG["at"] > 2:
        _MK_CFG["at"] = time.time()
        try:
            from .. import settings
            _MK_CFG["on"] = settings.load().get("nav_marker", True) is not False
        except Exception:
            _MK_CFG["on"] = True
    return _MK_CFG["on"]


MARKER_STALE = 4.0         # 右上角多少秒没读到就收起导航记号（城里偶尔几次读不到，1.5 秒就收会一直闪，2026-10-27 实测）


def _marker_tick(target, data, state, shown, ref=None):
    """导航记号（2026-10-27）：每圈先判断该不该显示（还没算出位置、到了、跨星系、1.5 秒没读到、切出游戏、玩家关了、
    采矿助手开着——记号窗口读屏时会被涂黑，会挡住扫描面板和雷达信号），不该显示就收起；
    该显示且右上角有新截图（停着只转镜头也算）就按镜头朝向和视角重算位置。返回这次画的截图时间，收起了返回 None"""
    from .. import navigate as n
    from ..showloc import game_foreground
    t, g, info = _pos.current
    h = state.get("here")
    cam = (info or {}).get("camdir")
    try:
        fg = game_foreground()
    except Exception:
        fg = True
    show = (h is not None and g and cam and time.time() - t < MARKER_STALE and not h.get("arrived") and not h.get("far")
            and fg and not _live.running() and _marker_on() and not _off("nav_marker"))
    if not show:
        if shown is not None:
            _mark_hud(None)
        return None
    if t == shown:
        return shown
    try:
        from ..displayinfo import last_fov
        from ..perf import game_area
        a = game_area()
        fov = info.get("fov") or last_fov() or 70.0
        tg = n.target_global(target, data, info.get("t"), ref)
        pr = n.project(g, cam, fov, tg, a["width"], a["height"], vertical=settings_key("fov_axis", "v") != "h")
        _mark_hud({"area": (a["left"], a["top"], a["width"], a["height"]), "proj": pr, "label": n.dist_text(pr["dist"])})
        return t
    except Exception:
        _mark_hud(None)
        return None


_game_events = _GameEvents()


def _nav_log(here, info, view):
    """导航时每次算出新位置记一行（logs/nav_log.txt），方向不对时用来查是哪一步的问题"""
    try:
        from .. import paths
        p = paths.log("nav_log.txt")
        if p.exists() and p.stat().st_size > 300_000:
            p.write_text("\n".join(p.read_text(encoding="utf-8").splitlines()[-1000:]) + "\n", encoding="utf-8")
        loc = info.get("local")
        line = (f"{time.strftime('%H:%M:%S')} 来源={here.get('src', '?')} 核对={info.get('local_ok')} "
                f"游戏局部={tuple(round(v, 4) for v in loc) if loc else None} "
                f"用的=({here['x']:.4f}, {here['y']:.4f}, {here['z']:.4f}) "
                f"方位={view.get('raw_bearing', 0):.1f}° 显示={view.get('bearing', 0):.0f}° 距离={view.get('surface', 0):.2f}km")
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


_cam_filter = _CamFilter()


def _space_view(g, target, data):
    """导航去太空路标：没有南北，给直线距离、先量子跳到哪、对准哪个标记偏几度"""
    from .. import navigate as n
    s = n.space_guide(g, target, data)
    out = {"space": True, "same_body": False, "inside": False, "text": n.space_text(g, target, data)}
    if not s["same_system"]:
        out["far"] = f"目标位于 {n.SYS_ZH.get(s['target_system'], s['target_system'])}星系，需先跃迁到该星系"
        return out
    out.update(direct=s["direct"], arrived=s["arrived"], aim=s.get("aim"), qt=s.get("qt"))
    return out


def _station_view(g, target, data, when=None, prev=None, info=None):
    """拉格朗日点 / 跳跃点空间站里走路：距离按米、按站自己的朝向分上下；转向靠机头那一行和屏幕记号"""
    from .. import navigate as n
    out = {"space": True, "city": True, "station": True, "inside": True, "same_body": True}
    try:                                                   # 先核对星系：别的星系同一个坐标也可能有东西（二审 2026-10-27）
        system, sure = n.system_info(g, data, **{k: (info or {}).get(k) or "" for k in ("zone", "location", "solar_id")})
    except Exception:
        system, sure = "", False
    if target.get("sys") and system and system != target["sys"]:   # 猜出来的星系不一样也不算到（复审 2026-10-27）
        out["far"] = f"目标位于 {n.SYS_ZH.get(target['sys'], target['sys'])}星系，需先跃迁到该星系"
        return out
    tg = n.target_global(target, data, when)
    d = math.dist(g, tg)
    out.update(direct=d / 1000, direct_m=d)
    if d > 50_000:
        out["far"] = f"先前往{target.get('city_zh') or target.get('site_en') or '空间站'}，到站后按步行指引前往"
        return out
    up = sum((t - a) * u for t, a, u in zip(tg, g, target.get("up") or (0, 0, 0)))
    arrived = n.city_arrived(d, bool(prev and prev.get("station") and prev.get("arrived")))
    out.update(arrived=arrived, close=not arrived and d < n.CITY_NEAR_M, updown=up,
               text=n.station_text(g, target, data, when, arrived))
    return out


def _nav_view(here, target, data, steady=None, prev=None):
    from .. import navigate as n
    out = {"text": n.here_text(here, data), "inside": here["inside"], "body": n.body_label(here["body"]),
           "same_body": here["inside"] and here["body"] == target["b"]}
    if not out["same_body"]:
        out["far"] = (f"先前往{target.get('city_zh') or n.body_label(target['b'])}，到达城市后按步行指引前往" if n.is_city(target)
                      else f"先量子跳跃到 {n.body_label(target['b'])}，再按推荐路线前往")
        return out
    a, t = n.pos(here), n.pos(target)
    out["raw_bearing"] = n.bearing(a, t)
    out["bearing"] = steady(out["raw_bearing"]) if steady else out["raw_bearing"]
    out["compass"] = n.compass(out["bearing"])
    out["surface"] = n.surface_km(a, t, here["radius_km"])
    out["direct"] = n.direct_km(a, t)
    out["height"] = here["height_m"]
    out["target_height"] = n.latlon(t)[2] * 1000 - here["radius_km"] * 1000
    out["lat"], out["lon"] = here["lat"], here["lon"]
    out["arrived"] = out["surface"] < 1
    if n.is_city(target):                         # 城里：几米以内才算到，距离按米、加上下楼层（2026-10-27）
        d, up = n.city_metrics(here, target)
        arrived = n.city_arrived(d, bool(prev and prev.get("city") and prev.get("arrived")))
        out.update(city=True, arrived=arrived, close=not arrived and d < n.CITY_NEAR_M, direct_m=d, updown=up, near=None,
                   station=bool(target.get("up")))      # 绕星球轨道的空间站：不给南北方位
        return out
    near = n.nearby(here, data)
    out["near"] = {"name": n.label(near[1]), "km": near[0]} if near else None
    best = n.approaches(target, data, top=1)
    if best and best[0][1] < out["surface"] * 0.5 and out["surface"] > 30:
        d3q, dsq, brgq, q = best[0]
        out["hint"] = f"距离过远：先量子跳跃到 {n.label(q)}（距目标 {dsq:,.1f} km），再朝 {n.deg_text(brgq)}° 飞行"
    return out


_nav = _Nav()


# ================================================================ 实时读屏

def _game_front():
    """游戏窗口在不在最前面：True / False；判断不了（不是 Windows、读不到前台窗口）返回 None——照常识别"""
    from .. import showloc
    return showloc.game_front()


def scu_text(v):
    """精炼后的量：1 SCU 以上写 SCU，不到 1 SCU 写 uSCU（1 SCU = 1,000,000 uSCU）；两种都给"""
    if v >= 1:
        return f"{v:,.2f} SCU（{v * 1e6:,.0f} uSCU）"
    return f"{v * 1e6:,.0f} uSCU（{v:.3f} SCU）"


def _station_bonus(station, minerals):
    """精炼站对这块石头里的矿的加成：只有一种值钱的矿写「+3%」，几种不一样就写「铁 +3%、金 -2%」，都是 0 返回空"""
    from ..data import REFINERIES, best_price
    from ..i18n import mineral_zh
    bonus = REFINERIES.get(station, ("", {}))[1]
    worth = sorted(minerals, key=lambda m: -(minerals[m] * (best_price(m)[0] or 0)))
    worth = [m for m in worth if (best_price(m)[0] or 0) > 0] or worth
    vals = {m: bonus.get(m, 0) for m in worth}
    if not any(vals.values()):
        return ""
    if len(set(vals.values())) == 1:
        return f"{next(iter(vals.values())):+d}%"
    return "、".join(f"{mineral_zh(m)} {v:+d}%" for m, v in vals.items() if v)


def _lots(scan, plan=None):
    """成分表（1.6.42）：石头里的每一份（矿 × 品质、惰性物质）一行。同一种矿有几种品质时标「高品质 / 低品质」；
    品质写上这种矿的第几档（quality.py，4.8 起每种矿只有 7 档）。plan = (精炼方式, 站点)：按它算这一份精炼后多少。
    精炼保留品质、不同品质精炼完还是分开的两份（expcarry、scopique、The Impound），所以按份算"""
    from collections import defaultdict
    from ..i18n import mineral_zh
    from ..quality import tier_of
    from ..refinery import refined_scu, INERT
    total = scan.total_scu
    groups = defaultdict(list)
    for i, (n, p, q) in enumerate(scan.composition):
        if n and n != INERT:
            groups[n].append(i)
    rank = {}
    for n, idx in groups.items():
        qs = [scan.composition[i][2] for i in idx]
        if len(idx) < 2 or None in qs or len(set(qs)) < 2:
            continue
        order = sorted(idx, key=lambda i: scan.composition[i][2])
        for k, i in enumerate(order):
            rank[i] = "低品质" if k == 0 else "高品质" if k == len(order) - 1 else "中等品质"
    rows = []
    for i, (n, p, q) in enumerate(scan.composition):
        inert = n == INERT
        scu = total * p / 100 if total else None
        row = {"en": n or "", "zh": "惰性物质" if inert else (mineral_zh(n) if n else "?"), "pct": p,
               "scu": round(scu, 4) if scu is not None else None, "q": None if inert else q, "tier": "",
               "rank": rank.get(i, ""), "inert": inert, "refined": None, "refined_text": ""}
        t = tier_of(n, q) if (n and not inert and q is not None) else None
        if t:
            row["tier"] = "完美" if t[0] == "完美" else f"{t[0]} 档" + ("（最低）" if t[1] == 1 else "（最高）" if t[1] == t[2] else "")
        if inert:
            row["refined_text"] = "无精炼产出，仅占用矿袋"
        elif plan and scu is not None and n:
            v = refined_scu({n: scu}, plan[1], plan[0]).get(n, 0.0)
            row["refined"] = round(v, 6)
            row["refined_text"] = scu_text(v)
        rows.append(row)
    return rows


def _lots_hud(lots):
    """悬浮窗一行：「惰性 31%｜钨 662 那份 3.07 SCU」（同一种矿有高低两种品质时写高品质那份）；没什么可说返回空"""
    parts = []
    inert = sum(r["pct"] for r in lots if r["inert"])
    if inert >= 0.5:
        parts.append(f"惰性 {inert:.0f}%")
    for r in lots:
        if r["rank"] == "高品质":
            low = [x["q"] for x in lots if x["en"] == r["en"] and x["rank"] == "低品质"]
            parts.append(f"{r['zh']} 品质 {r['q']}：{r['scu']:.2f} SCU" if r["scu"] is not None
                         else f"{r['zh']} 品质 {r['q']}/{low[0] if low else '?'}")
    return "｜".join(parts)


def scan_view(scan, bag, cut=False):
    """一块石头的读屏结果（窗口用）。cut=True：面板被屏幕右边挡住，品质和总 SCU 读不到，只有破碎方案和成分占比"""
    from ..i18n import mineral_zh, method_zh, station_zh
    from ..laser import recommend
    from ..data import best_price, GADGETS
    from ..refinery import refined_plan
    rock = mineral_zh(scan.main_mineral) if scan.main_mineral else "?"
    out = {"rock": rock, "mass": scan.mass, "resistance": scan.resistance, "instability": scan.instability,
           "difficulty": scan.difficulty or "", "minerals": [], "refine": [], "sell": [], "craft": [], "craft_mats": [], "goal": [], "plans": [],
           "total_scu": scan.total_scu, "lots": [], "lots_plan": "", "cut": bool(cut), "note": "",
           "at": time.strftime("%H:%M:%S")}
    hud = [f"{rock}｜{scan.mass:,.0f} kg｜抗性 {scan.resistance:g}%｜不稳定 {scan.instability:g}"]
    # 1.6.64：悬浮窗按层次排（审查意见）：矿名 → 关键读数 → 怎么碎 → 收益 → 次要详情；文字版 hud 还给窗口右侧用
    # 1.6.65 照用户给的样图：矿名、三格读数、矿物组成（每种矿下面列各品质、占整石）、开采建议、精炼产量和净值、次要
    rich = {"title": rock, "stats": [["质量", f"{scan.mass:,.0f}", "kg"], ["抗性", f"{scan.resistance:g}", "%"],
                                     ["不稳定性", f"{scan.instability:g}", ""]], "comp": [], "advice": None, "gain": [], "minor": [], "foot": ""}
    if cut:
        out["note"] = ("扫描面板右侧被屏幕边缘遮挡，无法识别品质和总 SCU：仅计算破碎方案和成分占比。"
                       "在游戏设置中调大「FOV视野」使面板完整显示后，可计算精炼收益和价格。")
        hud.append("面板被遮挡：仅计算破碎方案")
        rich["minor"].append("面板被遮挡：仅计算破碎方案")
    minerals = {k: v for k, v in scan.minerals_scu().items() if k not in ("Inert Materials", "?")}
    out["minerals"] = [{"name": mineral_zh(k), "en": k, "scu": v} for k, v in minerals.items()]
    first = None
    if minerals:
        for i, (method, station, value, rscu, fee, hours) in enumerate(refined_plan(minerals)):
            bonus = _station_bonus(station, minerals)
            from ..refinery import refined_scu
            per = refined_scu(minerals, station, method)
            out["refine"].append({"method": method_zh(method), "station": station_zh(station), "value": value,
                                  "scu": rscu, "fee": fee, "hours": hours, "bonus": bonus, "amount": scu_text(rscu),
                                  "yield": [{"zh": mineral_zh(k), "amount": scu_text(v)} for k, v in per.items() if v > 0]})
            if i == 0:
                first = (method, station)
                out["lots_plan"] = f"{method_zh(method)}，{station_zh(station)}"
                hud.append(f"精炼后 {scu_text(rscu)}，价值 {value:,.0f} aUEC（建议：{method_zh(method)}，{station_zh(station)}精炼"
                           + (f" {bonus}" if bonus else "") + "）")
                rich["gain"] = [["预计精炼产量", f"{rscu:,.2f}", "SCU"], ["价格", f"{value:,.0f}", "aUEC"]]
                rich["minor"].append(f"{method_zh(method)} · {station_zh(station)}" + (f" {bonus}" if bonus else ""))
                rich["foot"] = "精炼结果为估算"
        out["sell"] = [{"name": mineral_zh(k), "where": best_price(k)[1] or "无收购"} for k in minerals]
    out["lots"] = _lots(scan, first)
    if out["refine"]:          # 精炼后按品质分开写：「钨 662 有 1.50 SCU、钨 363 有 5.74 SCU」
        out["refine"][0]["lots"] = [{"zh": r["zh"], "q": r["q"], "amount": r["refined_text"]}
                                    for r in out["lots"] if not r["inert"] and r["refined"]]
    line = _lots_hud(out["lots"])
    if line:
        hud.append(line)
    groups = {}                                                # 矿物组成：同一种矿合在一起，下面列各品质（高品质那份标蓝）
    for row in out["lots"]:                                    # 占比照游戏里的两位小数写
        key = "惰性物质" if row["inert"] else row["zh"]
        g = groups.setdefault(key, {"name": key, "inert": row["inert"], "pct_n": 0.0, "subs": []})
        g["pct_n"] += row["pct"] or 0
        if not row["inert"]:                                  # 品质没认出来写「未知」，单独一份，不混进别的品质
            g["subs"].append({"q": "未知" if row["q"] is None else str(row["q"]), "pct": f"{row['pct'] or 0:.2f}%",
                              "hi": row["rank"] == "高品质", "n": row["pct"] or 0})
    for g in groups.values():
        g["subs"].sort(key=lambda x: -int(x["q"]) if x["q"].isdigit() else 1)
        g["pct"] = f"{g.pop('pct_n'):.2f}%"                  # 1.6.70（用户）：游戏里读到多少写多少，不四舍五入
        for x in g["subs"]:
            x.pop("n", None)
    rich["comp"] = sorted(groups.values(), key=lambda g: (g["inert"], -float(g["pct"][:-1] or 0)))
    if minerals:
        try:
            from ..crafting import quality_hints
            out["craft"] = list(quality_hints(scan.composition))
            from ..crafting import mat_summary
            best = {}
            for nm, pct, qq in scan.composition:
                if nm and nm not in ("Inert Materials", "?"):
                    best[nm] = max(best.get(nm) or 0, qq or 0) if qq is not None else best.get(nm)
            out["craft_mats"] = [{"en": nm, "zh": mineral_zh(nm), "q": qq, **mat_summary(nm, qq)}
                                 for nm, qq in best.items() if mat_summary(nm)["count"]]
            for nm, qq in best.items():                       # 目标还缺这种矿：窗口和悬浮窗都标出来（有品质门槛的按每一份判断）
                g = _goal_for(nm, mineral_zh(nm))
                if g:
                    lots = [r for r in out["lots"] if r["en"] == nm]
                    ok = any((r["q"] or 0) >= g["minq"] for r in lots) if g["minq"] > 1 else True
                    out["goal"].append({"en": nm, "zh": g["zh"] or mineral_zh(nm), "short": g["short"], "unit": g["unit"],
                                        "minq": g["minq"], "q": qq, "ok": ok, "goals": g["goals"], "text": _goal_text(g, qq, lots)})
            hud += [x["text"] for x in out["goal"][:2]]
            rich["minor"] += [x["text"] for x in out["goal"][:2]]
        except Exception:
            pass
    plans = recommend(scan.mass, scan.resistance, scan.instability)
    for p in plans:
        out["plans"].append({"heads": p.names, "short": p.short(), "summary": p.summary(),
                             "ratio": p.ratio, "breakable": p.breakable, "comfortable": p.comfortable,
                             "throttle": p.throttle if p.breakable else None})
    if plans:
        hud.insert(1, plans[0].short())
        p0 = plans[0]
        from ..laser import gadget_label
        heads = p0.names + (f" + {gadget_label(p0.gadget)}" if p0.gadget else "")
        rich["advice"] = {"heads": heads, "power": f"建议功率 {p0.throttle * 100:.0f}%" if p0.breakable else "满功率也无法破碎"}
    contents, used, cap = bag
    out["bag"] = None
    out["bag_text"] = ""
    if used is not None:
        out["bag"] = {"used": used, "cap": cap, "items": [{"name": mineral_zh(k), "scu": v} for k, v in contents.items()]}
        out["bag_text"] = f"{used:g}/{cap:g} SCU\n" + "，".join(f"{mineral_zh(k)} {v:g}" for k, v in contents.items())
    out["hud"] = "\n".join(hud)
    out["hud_rich"] = rich
    return out


_live = _Live()


@api
def live_start():
    from .. import settings
    _live.start()
    settings.update(live_on=True)          # 记住：重启、升级后自动接着扫
    return {"running": True}


@api
def live_stop():
    from .. import settings
    _live.stop()
    settings.update(live_on=False)
    return {"running": False}


MOD_GROUPS = (("rieger", "提高功率"), ("vaux", "提高提取功率"), ("focus", "扩大绿区"), ("xtr", "扩大绿区"),
              ("torrent", "加快充能"), ("deluge", "降低抗性"), ("overrun", "降低抗性"), ("fltr", "过滤惰性物质"))
STAT_ZH = {"power": "功率", "extract": "提取功率", "res": "抗性", "instab": "不稳定性", "window": "绿区", "rate": "充能",
           "filter": "过滤"}


def _gear_summary(key, lo):
    """一条船当前配置的汇总：同时操作的矿头总功率、满功率能破多重（抗性 30%；使用萨比尔 Sabir 时）。
    和破碎方案同一套公式（laser.evaluate）：在 crew 个矿头的组合里取最强的"""
    from itertools import combinations
    from ..laser import HeadSetup, evaluate, active_model, gadget_label
    craft = lo.get("craft") or [None] * len(lo["heads"])
    setups = [HeadSetup(k, mods, craft[i]) for i, (k, mods) in enumerate(lo["heads"])]
    model, k = active_model()
    n = max(1, min(lo.get("crew") or 1, len(setups)))
    combos = list(combinations(setups, n))
    best = lambda g: max(evaluate(list(c), g, 1.0, 30, 0, k=k, model=model).max_mass for c in combos)
    return {"crew": n, "power": round(max(sum(h.max_power() for h in c) for c in combos)),
            "mass": round(best(None), -1), "mass_gadget": round(best("sabir"), -1), "gadget": gadget_label("sabir")}


def _gear(ship=None):
    """配置区要的东西：几条船、每条船现在的配置（每个矿头加上模组后的读数、汇总）、能选的矿头和模组。
    名字一律「中文 English」（2026-10-26 用户定：霍夫斯泰德 Hofstede-S2）"""
    from ..data import SHIPS, HEADS, MODULES, DEFAULT_LOADOUTS, AUTHOR_MOLE
    from ..laser import ship_loadout, current_ship, clean_loadout, HeadSetup, _mult
    from ..i18n import gear_label

    def fmt(d, keys):
        return "，".join(f"{STAT_ZH[k]} {d[k]:+g}%" for k in keys if d.get(k))

    from ..laser import craft_slots, craft_mult
    from ..quality import tiers

    def power(k, craft):
        """矿头自己的激光功率（不算模组）：商店买的 → 自造的"""
        m = craft_mult(k, craft)
        return {"base": HEADS[k]["pmax"], "now": round(HEADS[k]["pmax"] * m), "pct": round((m - 1) * 100, 1), "craft": bool(craft)}

    def card(k, mods, craft):
        """一个矿头装上模组（和自造）后的读数：功率 W，其余是相对没有修正时的变化 %"""
        h = HeadSetup(k, mods, craft)
        pct = lambda m: round((m - 1) * 100)
        return {"power": round(h.max_power()), "base": HEADS[k]["pmax"],
                "stats": {"power": pct(h.max_power() / HEADS[k]["pmax"]),
                          "res": pct(_mult(HEADS[k]["res"], *h.res_mods())), "instab": pct(h.instab_mult()),
                          "window": pct(h.window_mult()), "rate": pct(h.rate_mult())}}

    ships = []
    for key, spec in SHIPS.items():
        _, lo = ship_loadout(key)
        craft = lo.get("craft") or [None] * len(lo["heads"])
        presets = [{"key": "factory", "name": "出厂配置"}]
        if key == "mole":
            presets.append({"key": "author", "name": "作者推荐（2 人）", "loadout": clean_loadout(key, AUTHOR_MOLE)})
        ships.append({"key": key, "name": spec["name"], "size": spec["size"], "heads": spec["heads"],
                      "crew_max": spec["crew_max"], "fixed": spec.get("fixed"), "loadout": lo,
                      "power": [power(k, craft[i]) for i, (k, _) in enumerate(lo["heads"])],
                      "cards": [card(k, mods, craft[i]) for i, (k, mods) in enumerate(lo["heads"])],
                      "summary": _gear_summary(key, lo), "presets": presets,
                      "is_default": lo == clean_loadout(key, DEFAULT_LOADOUTS[key])})
    heads = [{"key": k, "name": gear_label(h["name"]), "en": h["name"], "size": h["size"], "slots": h["slots"], "ship": h.get("ship"),
              "pmax": h["pmax"], "desc": f"最大功率 {h['pmax']:,.0f} W｜" + (fmt(h, ("res", "instab", "window", "rate")) or "无修正"),
              # 自造时影响激光功率的材料槽，和这种材料的品质档位（选档或者直接填数字）
              "craft": [{"slot": s["slot"], "slot_zh": s["slot_zh"], "mat_zh": s["mat_zh"], "segs": [list(x[:4]) for x in s["segs"]],
                         "tiers": [["商店标准", 500]] + [[n, q] for n, q in tiers(s["mat"])]} for s in craft_slots(k)]}
             for k, h in HEADS.items()]
    mods = [{"key": k, "name": gear_label(m["name"]), "en": m["name"], "desc": fmt(m, ("power", "extract", "res", "instab", "window", "rate", "filter")),
             "group": next((g for p, g in MOD_GROUPS if k.startswith(p)), "其他")}
            for k, m in MODULES.items()]
    from ..laser import chosen_ship
    return {"ship": current_ship(), "chosen": chosen_ship() is not None, "ships": ships, "heads": heads, "modules": mods,
            "groups": list(dict.fromkeys(g for _, g in MOD_GROUPS))}


@api
def mining_gear():
    return _gear()


@api
def set_mining_gear(ship="mole", loadout=None, reset=False):
    """选船 / 保存这条船的配置（reset=True 恢复出厂配置）"""
    from .. import settings
    from ..data import SHIPS
    from ..laser import clean_loadout
    if ship not in SHIPS:
        raise ValueError("未找到此飞船")
    saved = dict(settings.load().get("mining_loadouts") or {})
    if reset:
        saved.pop(ship, None)
    elif loadout is not None:
        saved[ship] = clean_loadout(ship, loadout)
    settings.update(mining_ship=ship, mining_loadouts=saved)
    _live.gear_rev += 1                     # 正在显示的石头按新配置重算（采矿助手最多 5 秒后重新发布）
    return _gear()


@api
def manual_scan(mass=0, resistance=0, instability=0):
    """手动输入扫描数据：只算破碎方案"""
    from ..laser import recommend
    plans = recommend(float(mass), float(resistance), float(instability))
    return [{"heads": p.names, "short": p.short(), "summary": p.summary(),
             "ratio": p.ratio, "breakable": p.breakable, "comfortable": p.comfortable,
             "throttle": p.throttle if p.breakable else None} for p in plans]


# ================================================================ 游戏里 F8：认出鼠标下的物品


# 物品说明框只会出现在屏幕中间这一块（物品栏左右两个固定位置，顶在屏幕约 1/4 高处）。
# 先只认这一块（约 1/3 屏幕，快 2~3 倍）；认不出、或者认出来的不像说明框，再认整屏
HOVER_REGION = (0.26, 0.19, 0.76, 0.96)


def _read_tooltip(img, cursor):
    """→ (文字, (中文名, 英文名) 或 None, 认的范围)"""
    from ..trade import console as C
    from ..trade.ocr import recognize
    W, H = img.size
    l, t, r, b = HOVER_REGION
    box = (int(W * l), int(H * t), int(W * r), int(H * b))
    tokens = recognize(img.crop(box), urgent=True, offset=box[:2])
    name, sure = C.tooltip_pick(tokens, cursor, img)
    if name and sure:
        return tokens, name, "中间"
    # 中间这块连说明框的样子（体积 / 制造商 / 物品类型…）都没有、鼠标也在中间：多半是开着船按了 F8，
    # 不再整屏找（整屏一次 5~16 秒，2026-10-23 两位玩家在驾驶位上按 F8 都等了很久，CPU 也白占）
    inside = cursor is None or (box[0] <= cursor[0] <= box[2] and box[1] <= cursor[1] <= box[3])
    if inside and not any(C._is_anchor(k.text) for k in tokens):
        if name and C.plausible_name(*name):
            return tokens, name, "中间"
        return tokens, None, "中间"
    full = recognize(img, urgent=True)
    name_full, sure_full = C.tooltip_pick(full, cursor, img)
    if name_full and sure_full:                       # 整屏找：必须名字下面紧跟「体积/制造商/物品类型…」才算物品说明框
        return full, name_full, "整屏"                 # （不然会把全局聊天、飞船 HUD、地点标记当成物品，2026-10-23 用户反馈）
    if name and C.plausible_name(*name):              # 中间认到但没把握：像物品名才要（2026-10-23 全量样本测试：碎字、系统界面会被当物品）
        return tokens, name, "中间"
    return full, None, "整屏"


def tooltip_quality(tokens):
    """说明框里的品质：「品质：650」「品质 650」「Quality: 650」「Q650」→ 650；没有返回 None"""
    for t in sorted(tokens or [], key=lambda k: (k.box[1], k.box[0])):
        m = re.search(r"(?:品质|品貭|晶质|Quality)\s*[:：]?\s*(\d{1,4})", t.text, re.I) or re.fullmatch(r"\s*Q\s*(\d{3,4})\s*", t.text)
        if m and 0 <= int(m.group(1)) <= 1000:
            return int(m.group(1))
    return None


_AMOUNT = re.compile(r"^(\d+(?:[.,]\d+)?)\s*[S5]\s*C\s*U$", re.I)


def tooltip_row(tokens):
    """说明框里的内容行「塔兰导电石Taranite｜925｜0.495 SCU」→ (品质, 数量 SCU)；没有返回 (None, None)。
    品质是数量左边、同一行最近的那个 0–1000 的整数（前面没写「品质」两个字，2026-10-23 用户截图）；
    「容量：1.00SCU」是箱子能装多少，不算"""
    toks = list(tokens or [])
    for a in sorted(toks, key=lambda k: (k.box[1], k.box[0])):
        t = a.text.replace(" ", "")
        if "容量" in t or "体积" in t:
            continue
        m = _AMOUNT.match(t)
        if not m:
            continue
        amount = float(m.group(1).replace(",", "."))
        h = max(a.box[3], 10)
        mid = a.box[1] + a.box[3] / 2
        same = [k for k in toks if k is not a and abs(k.box[1] + k.box[3] / 2 - mid) < 0.6 * h and k.box[0] < a.box[0]]
        q = None
        for k in sorted(same, key=lambda k: -k.box[0]):          # 数量左边最近的整数
            mq = re.fullmatch(r"\d{1,4}", k.text.strip()) or re.search(r"\s(\d{1,4})$", k.text.strip())
            if mq and 0 <= int(mq.group(mq.lastindex or 0)) <= 1000:
                q = int(mq.group(mq.lastindex or 0))
                break
        return q, amount
    return None, None


def parse_qlabel(text):
    """物品格子左上角的品质标签 → 品质；不是品质标签返回 None。
    游戏里写成「575Q」「0Q」。OCR 常把 Q 认成 0（907Q → 9070）、把 0 认成 Q（0Q → QQ），
    品质最多 1000，四位数末尾是 0 就是 Q 认错了（2026-10-23 用户截图实测 23 个全对）"""
    t = (text or "").replace(" ", "").upper()
    if t in ("QQ", "OQ", "0Q", "00", "0O"):
        return 0
    m = re.fullmatch(r"(\d{1,4})[QO]", t)
    if m:
        return int(m.group(1)) if int(m.group(1)) <= 1000 else None
    m = re.fullmatch(r"\d{1,5}", t)
    if not m:
        return None
    if len(t) >= 4 and t.endswith("0") and t != "1000":
        v = int(t[:-1])                                   # Q 认成了 0
        return v if v <= 1000 else None
    return int(t) if int(t) <= 1000 else None


def parse_count(text):
    """格子右上角的堆叠数量「200x」→ 200；「200/200」（当前量 / 上限）不是数量"""
    m = re.fullmatch(r"(\d{1,5})[xX×]", (text or "").replace(" ", ""))
    return int(m.group(1)) if m else None


def cell_labels(img, cursor, tokens=None, size=None):
    """鼠标指着的那个物品格子：左上角的品质（575Q）和右上角的数量（200x）。没有返回 None。
    只认鼠标上方一个格子高度以内的标签；同一排里品质取鼠标左边最近的、数量取鼠标右边最近的。
    size：格子大小 (宽, 高)，默认按整屏比例估（1440p 下约 150×140）"""
    W, H = img.size
    cw, ch = size or (int(W * 0.065), int(H * 0.11))
    cx, cy = cursor
    if tokens is None:
        from ..trade.ocr import recognize
        box = (max(0, cx - cw), max(0, cy - ch), min(W, cx + cw), min(H, cy + ch // 6))
        tokens = recognize(img.crop(box), urgent=True, offset=box[:2])
    best_q = best_n = None
    for t in tokens:
        x, y, w, h = t.box
        if not cy - ch < y < cy:
            continue
        q = parse_qlabel(t.text)
        if q is not None and cx - cw < x <= cx + 4 and (best_q is None or (y, x) > best_q[:2]):
            best_q = (y, x, q)
        n = parse_count(t.text)
        if n is not None and cx - 4 <= x + w < cx + cw and (best_n is None or (y, -x) > best_n[:2]):
            best_n = (y, -x, n)
    return (best_q[2] if best_q else None), (best_n[2] if best_n else None)


def _is_mineral(zh, en):
    from ..data import SIGNATURES
    from ..i18n import mineral_en
    return (en or "").strip().lower() in {k.lower() for k in SIGNATURES} or bool(zh and mineral_en(zh))


def qty_text(qty, unit):
    """数量写成玩家看得懂的：0.495 SCU / 200 个 / 495,000 uSCU"""
    if qty is None:
        return ""
    if unit == "SCU":
        return f"{qty:g} SCU"
    if unit == "uSCU":
        return f"{qty:,.0f} uSCU"
    return f"{qty:g} 个"


def hover_once(img=None):
    """F8：认出鼠标指着的物品，马上把名字和本机数据（哪里买、维科洛、制造）显示到悬浮窗；
    要联网的（玩家市场价、掉落）放到后台，查到了再补上。以前要等联网全查完才显示，慢好几秒"""
    from ..screen import grab
    from ..trade import console as C
    why = _off("item")
    if why:
        _item_hud(f"物品识别暂时关闭：{why}", 8)
        return {"error": why}
    t0 = time.time()
    _last_hover.clear()
    _last_hover["at"] = "识别中"                          # 上一次 F8 后台还没查完的价格，不再往悬浮窗上写
    img = img or grab()
    t1 = time.time()
    bus.publish("hover", {"state": "working"})
    _item_hud("识别中…", 30)                          # 按下就有反应
    cx, cy = C._cursor_on_image(img) if WIN else (img.width // 2, img.height // 2)
    tokens, name, where = _read_tooltip(img, (cx, cy))
    t2 = time.time()
    if not name:
        msg = "未找到物品说明框。鼠标停在物品上，等说明框出现后再按"
        bus.publish("hover", {"state": "miss", "msg": msg})
        _item_hud("未识别到物品\n鼠标停在物品上，等说明框出现后再按", 10)
        threading.Thread(target=C._hover_log, args=(img, tokens, None, f"识别({where}) {(t2 - t1) * 1000:.0f}ms"),
                         daemon=True).start()
        return {"miss": True}
    zh, en = name
    from ..trade.names import canonical
    canon = canonical(zh, en)                              # 认错的字按汉化包纠正（冷冻舱（刻度）→ 冷冻舱（剜度））
    if canon:
        zh, en = canon
    at = time.strftime("%H:%M:%S")
    info = item_info(en, zh, loot=False)                   # 只用本机数据，很快
    # 品质：说明框内容行（矿：925｜0.495 SCU）> 格子左上角 575Q > 没写就是 0（矿没读到就空着，让玩家自己填）
    # 数量：矿按说明框里的 SCU，其他按格子右上角的 200x，没有就是 1 个
    row_q, row_amt = tooltip_row(tokens)
    if row_q is None:
        row_q = tooltip_quality(tokens)                    # 「品质：650」这种写了字的
    try:
        cell_q, cell_n = cell_labels(img, (cx, cy))
    except Exception:
        cell_q, cell_n = None, None
    mineral = _is_mineral(zh, en)
    quality = row_q if row_q is not None else cell_q if cell_q is not None else (None if mineral else 0)
    if mineral:
        qty, unit = row_amt, "SCU"
    else:
        qty, unit = (cell_n or 1), "个"
    craft = None
    if not mineral and row_q is None and cell_q is None:   # 制造出来的东西没写品质：按加成行倒推各材料槽（和盘点同一套，老大 2026-10-27 反馈 F8 显示品质 0）
        try:
            from ..crafting import parse_mods, solve_slots, for_item, craft_text
            mods = parse_mods(tokens)
            res = solve_slots(for_item(en, zh), mods) if mods else None
            if res and res["exact"]:                       # 加成对不上蓝图（认错数字 / 蓝图不对）：不当品质（Codex 2026-10-27）
                quality, craft = res["avg"], res["slots"]
            elif res:
                quality = None
        except Exception:
            craft = None
    head = (zh or en) + (f"｜品质 {quality}" if quality is not None else "") + (f"｜{qty_text(qty, unit)}" if qty else "")
    if not canon:                                          # 汉化包里没对上：名字只是照字认的，不硬猜成别的东西
        head += "｜识别结果不确定"
    lines = [head] + ([f"材料品质：{craft_text(craft)}"] if craft else []) + _hover_lines(info, en, zh)
    _last_hover.clear()
    _last_hover.update(at=at, id=None, lines=lines)
    _item_hud("\n".join(lines))                  # 没数据的行不显示；市场价查到了再补上
    t3 = time.time()
    bus.publish("hover", {"state": "ok", "zh": zh, "en": en, "info": info, "market": None, "candidates": [],
                          "pending": True, "at": at, "quality": quality, "qty": qty, "unit": unit,
                          "tier": _tier(quality), "craft": craft})
    note = (f"耗时 截图{(t1 - t0) * 1000:.0f}ms 识别({where}){(t2 - t1) * 1000:.0f}ms "
            f"本机数据{(t3 - t2) * 1000:.0f}ms 共{(t3 - t0) * 1000:.0f}ms｜品质 {quality} 数量 {qty} {unit}"
            + ("" if canon else "｜汉化包里没对上"))
    threading.Thread(target=_hover_more, args=(at, zh, en, info, quality, bool(canon)), daemon=True, name="hover-more").start()
    threading.Thread(target=C._hover_log, args=(img, tokens, name, note), daemon=True).start()
    if canon:                                              # 帮助改进识别：名字那几行 + 汉化包里的正确名字（后台存，不拖慢 F8）
        from .. import train_data
        threading.Thread(target=train_data.from_tooltip, args=(img, tokens, name, canon), daemon=True).start()
    return {"ok": True, "ms": int((t3 - t0) * 1000)}


def _tier(quality):
    """品质 → UEX 玩家市场的品质档 q0–q7（q0 = 品质 0，q1 = 1–499 … q7 = 950–1000）；不知道品质按 q0"""
    from ..trade.providers.http import quality_group
    g = quality_group(quality) if quality is not None else "q0"
    return g if g != "unknown" else "q0"


def _hover_more(at, zh, en, info, quality=None, canon=True):
    """后台：对上玩家市场里的物品、查价、查掉落，查到一样补一样（悬浮窗和窗口都更新）"""
    from ..trade import console as C
    out = {"at": at}
    t = trade()
    try:
        item, items = C.match_tooltip(t, zh, en)
    except Exception:
        item, items = None, []
    if _last_hover.get("at") != at:                       # 已经又按了一次 F8：这次的结果不要了
        return
    if item is not None and zh and C.has_chinese(zh) and canon:      # 只记汉化包里的标准名（认错的字不记，免得库存里显示错名）
        try:
            t.catalog.add_alias(item.id, zh)
        except Exception:
            pass
    out["market"] = {"id": item.id, "label": t.label(item.id)} if item else None
    out["candidates"] = [{"id": i.id, "label": t.label(i.id)} for i in items[:8]] if item is None else []
    # 认出的英文名有错字、本机没对上商店数据时：用市场里的标准英文名再查一次
    if item is not None and info.get("id") is None and C._fold(item.name) != C._fold(en):
        try:
            better = item_info(item.name, zh, loot=False)
            if better.get("id") is not None:
                info = better
                out["info"] = better
                lines = (_last_hover.get("lines") or [zh or en])[:1] + _hover_lines(better, item.name, zh)   # 第一行（名字｜品质｜数量）不动
                _last_hover["lines"] = lines
                _item_hud("\n".join(lines))
        except Exception:
            pass
    if item is not None:
        _last_hover["id"] = item.id
        bus.publish("hover_more", dict(out))
        try:
            tier = _tier(quality)                         # 认出了品质：按那一档查价（925 → q6 900–949）
            prices, results = _market_rows(item.id, tier)
            if _last_hover.get("at") != at:
                return
            from ..trade.console import hud_market
            market = hud_market(results) if results is not None else ""
            if market:
                _item_hud("\n".join(_last_hover["lines"] + [market]))
            out["prices"] = dict(prices, quality=tier, op="sell")
        except Exception as e:
            out["prices"] = {"error": f"价格查询失败：{e}", "quality": _tier(quality), "op": "sell"}
    try:
        from ..loot import info as loot_info
        out["loot"] = loot_info(info.get("name") or en, zh)
    except Exception as e:
        out["loot"] = {"error": f"掉落数据查询失败：{e}"}
    if _last_hover.get("at") == at:
        bus.publish("hover_more", out)


_last_hover = {}


def _hover_lines(info, en, zh):
    """悬浮窗里物品下面的几行：买（商店有才写）、维科洛兑换、制造。没有的不写"""
    lines = []
    g = _goal_for(info.get("name"), en, zh)
    if g:
        lines.append(_goal_text(g))
    buy = _short_buy(info)
    if buy:
        lines.append(f"购买：{buy}")
    ships = info.get("ships") or []
    if ships and not buy:                        # 商店买不到、出厂自带在船上（2026-10-27 解包）
        lines.append(f"随船自带：{'、'.join(ships[:3])}" + (f" 等 {len(ships)} 条船" if len(ships) > 3 else ""))
    if info.get("how"):
        lines.append(f"获取：{info['how']}")
    try:
        from .. import wikelo
        name = info.get("name") or en
        got = [c for c in wikelo.load() if any(wikelo._same(x, name) or (zh and wikelo._same(x, zh)) for x in [c.get("rz", ""), *c.get("rewards", [])])]
        if got:
            lines.append(f"可通过维科洛兑换获得：{got[0]['t']}" + (f" 等 {len(got)} 个" if len(got) > 1 else ""))
        uses = info.get("wikelo") or []
        if uses:
            u = uses[0]
            lines.append(f"可用于维科洛兑换：{u['reward']}" + (f" 等 {len(uses)} 个" if len(uses) > 1 else ""))
    except Exception:
        pass
    try:
        from .. import crafting
        fold = lambda x: re.sub(r"[^a-z0-9一-鿿]", "", (x or "").lower())
        want = {fold(info.get("name")), fold(en), fold(zh)} - {""}
        bps = [b for b in crafting.blueprints() if fold(b["n"]) in want or fold(b["z"]) in want]
        if bps:
            lines.append("可制造：有蓝图（材料见物品查询）")
    except Exception:
        pass
    return lines


def _short_buy(info):
    rows = info.get("buy") or (info["variants"][0]["buy"] if info.get("variants") else [])
    if not rows:
        return ""
    r = rows[0]
    return f"{r['dist'] + '｜' if r['dist'] else ''}{r['price']:,.0f}｜{r['shop']}"


_hover = _Hover()


# ================================================================ 盘点（F6，2026-10-25 用户要求）
# 开着时鼠标停在游戏库存的格子上、说明框一出来就自动记一格（同一格不重复记）；悬浮窗显示本轮小计。
# 再按 F6，或 60 秒没认到物品，自动结束：和账上对一遍，窗口里确认后才改账（游戏里同一种东西常分好几格，按格加总）


def _read_item(img, cursor):
    """鼠标指着的物品：{zh, en, quality, qty, unit, sure}；认不出返回 None（和 F8 用同一套识别）"""
    from ..trade.names import canonical
    tokens, name, _where = _read_tooltip(img, cursor)
    if not name:
        return None
    zh, en = name
    canon = canonical(zh, en)
    if canon:
        zh, en = canon
    row_q, row_amt = tooltip_row(tokens)
    if row_q is None:
        row_q = tooltip_quality(tokens)
    try:
        cell_q, cell_n = cell_labels(img, cursor)
    except Exception:
        cell_q, cell_n = None, None
    mineral = _is_mineral(zh, en)
    quality = row_q if row_q is not None else cell_q if cell_q is not None else (None if mineral else 0)
    qty, unit = (row_amt, "SCU") if mineral else ((cell_n or 1), "个")
    craft = None
    if not mineral:                  # 1.6.67：制造出来的东西没有品质数，只有加成行 → 按蓝图倒推各材料槽的品质，记平均
        try:
            from ..crafting import parse_mods, solve_slots, for_item
            mods = parse_mods(tokens)
            res = solve_slots(for_item(en, zh), mods) if mods else None
            if res and res["exact"]:                       # 加成对不上蓝图：不当品质（Codex 2026-10-27）
                quality, craft = res["avg"], res["slots"]
            elif res and row_q is None and cell_q is None:  # 没直接读到品质、倒推又对不上：品质未知，不记成 0
                quality = None
        except Exception:
            craft = None
    return {"zh": zh, "en": en, "quality": quality, "qty": qty, "unit": unit, "sure": bool(canon), "craft": craft}


def _kl(k):
    return [k.item_id, k.quality, k.location, k.unit]


def _count_review(place, items):
    """本轮盘点 → 和账上对：rows（看到的，账上多少 → 游戏里多少）、missing（账上有、这轮没看到）"""
    from .. import goals as G
    t = trade()
    rev = t.inventory.revision()                       # 先记版本号再读账：读账这会儿别处写了，确认时才查得出来（二审 2026-10-28）
    book = [l for l in t.inventory.list_stock() if _place_of(l.key.location)[0] == place]
    used, rows = set(), []
    # 同一物品 + 品质 + 单位分成了几组（制造品各槽品质不同、两个名字是同一物品）：会配到同一批库存行，先合成一行
    # （各槽品质只留第一组的——库存还不分变体，见待做 #10；复审 2026-10-28）
    merged = {}
    for v in items.values():
        ids = frozenset(G.resolve_all(t, v["en"], v["zh"]))
        qkey = "unknown" if v["quality"] is None else f"exact:{int(v['quality'])}"
        ukey = G.USCU if v["unit"] == "SCU" else "unit"
        k = (ids or (v["en"] or v["zh"]), qkey, ukey)
        if k in merged:
            m = merged[k]
            merged[k] = {**m, "qty": m["qty"] + v["qty"], "cells": m["cells"] + v["cells"]}
        else:
            merged[k] = v
    for (ids, qkey, ukey), v in merged.items():
        ids = ids if isinstance(ids, frozenset) else frozenset()
        lines = [l for l in book if l.key.item_id in ids and l.key.quality == qkey and l.key.unit == ukey]
        have = sum(l.quantity for l in lines)
        game = int(round(v["qty"] * 1_000_000)) if ukey == G.USCU else int(v["qty"])
        used.update(l.key for l in lines)
        show = (lambda n: scu_amount(n, ukey)) if ukey == G.USCU else (lambda n: n)
        rows.append({"zh": v["zh"], "en": v["en"], "quality": v["quality"], "unit": v["unit"], "cells": v["cells"], "craft": v.get("craft"),
                     "book": show(have), "game": show(game), "delta": show(game - have) if game != have else 0,
                     "keys": [_kl(l.key) for l in lines], "raw_game": game})
    missing = []
    for l in book:
        if l.key in used or l.quantity <= 0:
            continue
        item = t.catalog.get(l.key.item_id)
        u = "SCU" if l.key.unit in ("uSCU", "cSCU") else "个"
        missing.append({"item": t.label(l.key.item_id), "en": item.name if item else l.key.item_id,
                        "quality": l.key.quality[6:] if l.key.quality.startswith("exact:") else "",
                        "qty": scu_amount(l.quantity, l.key.unit) if u == "SCU" else l.quantity, "unit": u,
                        "key": _kl(l.key)})
    return {"place": place, "rows": rows, "missing": missing, "at": time.strftime("%H:%M:%S"),
            "revision": rev}                          # 确认时核对：中间改过账就不按这份旧账改（老大审查 2026-10-28 第 8 条）


_count = _Count()


@api
def count_toggle():
    """盘点开关（窗口按钮；游戏里是 F6）"""
    return _count.stop() if _count.running() else _count.start()


@api
def count_state():
    return {"running": _count.running(), "place": _count.place, "review": _count.review}


@api
def count_apply(zero=None):
    """确认对账：看到的按游戏里的数改；zero：账上有、这轮没看到、要清零的行（[[物品, 品质, 位置, 单位], …]）"""
    from .. import goals as G
    from ..trade.models import StockKey
    rv, _count.review = _count.review, None             # 先拿走：连点两下「确认」第二下直接提示没有待确认的
    if not rv:
        return {"error": "没有待确认的盘点"}
    t = trade()
    _SHORT["t"] = 0.0

    def put(key, n):
        if key in targets:                              # 对账时已按库存行合并，到这里还重复说明名字认得不一样：别悄悄覆盖
            raise ValueError("同一物品在盘点里出现了两次（名字不一样），这次没改；取消后在库存页手动改数量")
        targets[key] = n
    # 先把每一行要改成多少算清楚（不写库），再一笔事务写进去：要么全改、要么一行不改（老大审查 2026-10-28 第 8 条）
    targets, crafts = {}, []
    try:
        for r in rv["rows"]:
            if not r["delta"]:
                continue
            keys = [StockKey(*k) for k in r["keys"]]
            if not keys:                                # 账上没有：入库
                key, n = G.stock_line(t, r["en"], r["zh"], r["game"], r["unit"], r["quality"], _place_for(rv["place"]))
                put(key, n)
                if r.get("craft"):
                    crafts.append((key.item_id, key.quality, r["craft"]))
                continue
            if r.get("craft"):
                crafts.append((keys[0].item_id, keys[0].quality, r["craft"]))
            # 好几个仓位都有：多出来的记在第一个仓位；少了的从各仓位依次扣（老大审查 2026-10-28：以前只扣第一个、不够就截成 0，总数对不上）
            qs = [t.inventory._quantity_of(k) for k in keys]
            total, target = sum(qs), r["raw_game"]
            if target >= total:
                put(keys[0], qs[0] + (target - total))
            else:
                need = total - target
                for k, q in zip(keys, qs):
                    take = min(q, need)
                    if take > 0:
                        put(k, q - take)
                        need -= take
                    if need <= 0:
                        break
        want = {tuple(k) for k in (zero or [])}
        for m in rv["missing"]:
            if tuple(m["key"]) in want:
                put(StockKey(*m["key"]), 0)
        t.inventory.apply_count(list(targets.items()), rv.get("revision"), source="盘点")
    except ValueError as e:                             # 一行都没改：库存变过了要重新盘；别的错把这轮对账放回去
        if "重新盘点" not in str(e) and _count.review is None and not _count.running():
            _count.review = rv
        else:
            bus.publish("count", {"running": _count.running(), "review": None})
        return {"error": str(e)}
    except Exception:                                   # 数据库出错之类：对账放回去，窗口里还能再点确认
        if _count.review is None and not _count.running():
            _count.review = rv
        raise
    for iid, q, slots in crafts:                        # 制造品各槽品质：不是库存数，批次写完再记
        try:
            t.inventory.set_craft(iid, q, slots)
        except Exception:
            pass
    _count.review = None
    bus.publish("count", {"running": _count.running(), "review": None})
    return stock()


@api
def count_cancel():
    _count.review = None
    bus.publish("count", {"running": _count.running(), "review": None})
    return {"ok": True}


_pos = _Pos()


@api
def show():
    """又双击了一次 Dubhe.exe：后台开着的 AT 把窗口打开"""
    from .server import show_window
    show_window()
    return {"ok": True}


@api
def quit():
    """又双击了一次 Dubhe.exe：旧的这个退出，让新的接手"""
    from .server import QUIT
    QUIT.set()
    return {"ok": True}


REFERRAL_URL = "https://www.robertsspaceindustries.com/enlist?referral=STAR-4CNY-K3YT"


# 数据来源（关于页、免责声明第 5 条；2026-10-26 按各站条款整理）：(名称, 网址, 提供什么)
DATA_SOURCES = (
    ("SCMiner", "https://scminer.rocks", "矿物、雷达信号、采矿地点、车矿和手采矿"),
    ("UEX", "https://uexcorp.space", "矿价、精炼站加成、商店售卖地点、玩家市场价"),
    ("SC Market", "https://scm.flowcld.com/market", "玩家市场价"),
    ("scmdb.net", "https://scmdb.net", "制造蓝图、维科洛兑换"),
    ("starmap.space", "https://starmap.space", "星图和地点坐标"),
    ("星际公民掉落查询", "https://scl.miao.network", "掉落数据"),
    ("Star Citizen Wiki API", "https://api.star-citizen.wiki", "物品数值、物品清单和说明"),
    ("Star Citizen Wiki", "https://starcitizen.tools", "矿物品质分档（CC BY-SA 4.0 许可，改编使用）"),
    ("erkul.games", "https://www.erkul.games", "舰船信号截面"),
    ("SC汉化盒子", "https://github.com/StarCitizenToolBox/app", "中文名称（及社区汉化项目）"),
)


@api
def about_info():
    """关于页：版权、数据来源"""
    return {"copyright": "© 2026 Adm_TT　AGPL-3.0 开源", "sources": [{"name": n, "url": u, "what": w} for n, u, w in DATA_SOURCES]}


@api
def open_source_site(i=0):
    """关于页点数据来源：用系统默认浏览器打开（只开 DATA_SOURCES 里的网址）"""
    import webbrowser
    webbrowser.open(DATA_SOURCES[int(i)][1])
    return {"ok": True}


@api
def third_party_licenses():
    """开源组件许可证原文（安装目录的「第三方许可.txt」，打包时由 tools/collect_licenses.py 生成）"""
    from .. import paths
    p = paths.ROOT / "第三方许可.txt"
    try:
        return {"text": p.read_text(encoding="utf-8-sig")}
    except OSError:
        return {"text": "", "error": "未找到「第三方许可.txt」（开发目录里没有，打包时生成）"}


@api
def open_referral():
    """用系统默认浏览器打开作者的星际公民邀请注册页（只能打开这一个固定网址）"""
    import webbrowser
    webbrowser.open(REFERRAL_URL)
    return {"ok": True}


AGREE_TEXT = "本软件是免费软件"


@api
def agree(text=""):
    """第一次打开：必须一字不差地输入「本软件是免费软件」才能用"""
    from .. import settings
    if (text or "").strip() != AGREE_TEXT:
        return {"error": f"需完整输入：{AGREE_TEXT}"}
    settings.update(agreed=True)
    from .. import helpers
    helpers.start()
    start_background()
    return status()


_logwatch = _LogWatch()


def start_background():
    """窗口打开时：F8 热键监听、盯游戏日志里的位置、导航时读右上角（第一次打开要先确认免费声明）"""
    from .. import settings
    if not settings.load().get("agreed"):
        return
    _hover.start()
    _pos.start()
    _logwatch.start()
    _game_events.start()
    if not _online.get("loop"):                 # 同意免责声明后也会调一次：只开一个
        _online["loop"] = True
        threading.Thread(target=_online_loop, daemon=True, name="update").start()
        from .. import itemsearch
        itemsearch.warm_up()                     # 搜索索引后台先建好（2026-10-26 优化：第一次搜索从 1–3 秒变 0）
    if not _online.get("fb_retry"):              # 上次没发成的问题反馈：后台补发
        _online["fb_retry"] = True
        from .. import feedback_up
        threading.Thread(target=lambda: feedback_up.retry_pending(_fb_dir()), daemon=True, name="feedback-retry").start()
    if settings.load().get("live_on"):          # 上次关天枢（或重启、升级）时原矿扫描开着：接着扫
        _live.start()
    try:
        from ..perfmon import monitor            # 每分钟记一行资源占用（logs/perf_log.txt）
        monitor.start()
    except Exception:
        pass
