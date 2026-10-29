"""系统、更新与诊断服务任务模块（Task: System & Maintenance）

从 app/services.py 中解耦出来，专职处理：
1. 软件运行状态监控、热键冲突检测与全局设置修改；
2. 在线更新检查、下载升级、稳定版备份与回滚（含 Velopack 与绿色版）；
3. 历史版本数据迁移与旧版进程协同；
4. 运行日志导出、系统配置清单打包；
5. 一键问题反馈记录与截图打包上报；
6. 悬浮窗位移、驾驶舱 HUD 状态探查；
7. 关于信息、数据来源索引、第三方开源许可证展示与免责声明确认。
"""
import base64
import json
import platform
import re
import shutil
import sys
import threading
import time
import uuid
import webbrowser
import zipfile
from pathlib import Path

from ..app import bus

WIN = sys.platform == "win32"
API = {}


def api(fn):
    """标记为暴露给前端的 API 函数（名字就是接口路径 /api/<fn_name>）"""
    API[fn.__name__] = fn
    return fn


# ---------------------------------------------------------------- 依赖转发辅助
def _services():
    from ..app import services
    return services


def _hud():
    try:
        from ..app.overlay import hud
        return hud()
    except Exception:
        srv = _services()
        return srv._hud() if hasattr(srv, "_hud") else None


def _note_hud(section, text, secs=6):
    """悬浮窗上一条短提示，secs 秒后自己收起"""
    h = _hud()
    if h is None:
        return
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


# ---------------------------------------------------------------- 热键定义与冲突检测
# 游戏里的热键：(设置名, 默认键, 名字)。撞键时排在前面的生效
HOTKEYS = [("trade_capture_key", "F8", "物品识别"), ("mark_key", "", "记录路标"), ("fix_key", "", "一键定位"),
           ("report_key", "F10", "问题反馈"), ("live_key", "F5", "采矿助手开关"), ("count_key", "F6", "盘点"),
           ("ore_key", "", "原矿记录")]


def _hotkey_values(cfg):
    """→ [(键, 名字, 设置名)]，按生效顺序；没设的键是空字符串"""
    return [(str(cfg.get(n, d) or "").strip().upper(), lab, n) for n, d, lab in HOTKEYS]


def hotkey_conflicts(cfg=None):
    """热键撞了（settings.json 手改的、旧版本留下的）：只有排在前面的生效，要明确告诉玩家哪个失效"""
    if cfg is None:
        try:
            from ..core import settings
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


# ---------------------------------------------------------------- 状态与系统信息
@api
def status():
    from ..core import settings
    from ..system import helpers
    from ..system import showloc
    from ..mining.data import GAME_VERSION
    cfg = settings.load()
    srv = _services()

    live_running = srv._live.running() if hasattr(srv, "_live") else False
    live_paused = bool(live_running and srv._live.paused) if hasattr(srv, "_live") else False
    nav_label = srv._nav.target_label() if hasattr(srv, "_nav") else ""
    nav_space = srv._nav.space_mode if hasattr(srv, "_nav") else False
    pos_reader_active = srv._pos.reader.active if hasattr(srv, "_pos") else False
    game_events_dict = {k: v for k, (_, v) in list(srv._game_events.last.items())} if hasattr(srv, "_game_events") else {}

    out = {"settings": cfg, "game_version": GAME_VERSION, "win": WIN,
           "admin": showloc.is_admin() if WIN else True,
           "game_elevated": bool(WIN and showloc.game_elevated()),
           "helpers": helpers.status_line(),
           "live": live_running, "live_paused": live_paused,
           "nav": nav_label, "nav_space": nav_space, "hover_key": cfg.get("trade_capture_key") or "F8",
           "hotkey_warn": hotkey_conflicts(cfg),
           "position": None, "data": _data_versions(), "displayinfo": pos_reader_active,
           "version": _version(), "new_version": _upgrade_found(), "game_size": None,
           "game_events": game_events_dict,
           "frozen": __import__("sc_mining.core.paths", fromlist=["FROZEN"]).FROZEN,
           "vpk": __import__("sc_mining.core.paths", fromlist=["VELOPACK"]).VELOPACK}
    if WIN:
        from ..core.perf import game_size
        out["game_size"] = game_size()                          # 游戏画面多大：低于 1080 高时页面上提醒识别会不准
    try:
        from ..navigation.position import current
        here = current()
        if here:
            out["position"] = {"label": here["label"], "minutes": int(here["age"] // 60), "sys": here["sys"]}
            from ..crafting.stockplaces import match
            p = match(here["label"], here["sys"])               # 库存入库默认放这里（地点列表里的叫法）
            out["place"] = {"label": p["label"], "path": p["path"], "minutes": int(here["age"] // 60)} if p else None
    except Exception:
        pass
    # 右上角读到的具体地点：记住最后一次读到的，切屏、某一次没认出来都不换（以前会在「附近」和站名之间来回闪）。
    # 只有游戏日志里有更新的地点（比如到别的站开了库存）才换掉它
    if hasattr(srv, "_pos"):
        lab_t, lab = srv._pos.label
        if lab and time.time() - lab_t < 3 * 3600:
            log_t = 0.0
            try:
                from ..navigation.position import from_log
                hit = from_log()
                log_t = hit[0] if hit else 0.0
            except Exception:
                pass
            if lab_t >= log_t:
                sys_t, sysname = srv._pos.system
                out["position"] = {"label": lab, "minutes": int((time.time() - lab_t) // 60),
                                   "sys": sysname or (out["position"] or {}).get("sys", ""),
                                   "live": pos_reader_active and time.time() - lab_t < 15}
    if out["position"] is not None:
        out["position"].setdefault("live", False)
    out["gridtext"] = _gridtext_status()
    return out


def _gridtext_status():
    try:
        from ..navigation import gridtext
        return gridtext.status()
    except Exception:
        return {}


def _version():
    from ..core.version import VERSION
    return VERSION


def _data_versions():
    from ..core import paths
    out = {}
    try:
        out["loc"] = (paths.DATA / "loc" / "version.txt").read_text(encoding="utf-8").strip()
    except Exception:
        out["loc"] = ""
    for key, name in (("shops", "shops.json"), ("starmap", "starmap.json")):
        p = paths.DATA / name
        out[key] = time.strftime("%Y-%m-%d", time.localtime(p.stat().st_mtime)) if p.exists() else ""
    try:
        from ..crafting.loot import load_index
        idx = load_index(False)
        out["loot"] = (idx or {}).get("version", "")
    except Exception:
        out["loot"] = ""
    from ..update.data_pack import local_version
    out["pack"] = local_version()                    # 数据包版本（2026-10-26 起数据从 Gitee 的数据包更新）
    return out


def _desktop():
    """桌面文件夹（桌面被 OneDrive 搬走的也能找到）"""
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
    from ..core import paths
    lines = [f"AT 版本：{_version()}", f"导出时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"Windows：{platform.platform()}", f"Python：{sys.version.split()[0]}"]
    try:
        import ctypes
        u32 = ctypes.windll.user32
        lines.append(f"屏幕：{u32.GetSystemMetrics(0)} × {u32.GetSystemMetrics(1)}（缩放后）")
    except Exception:
        pass
    try:
        from ..system import showloc
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
        from ..core.perf import ocr_device
        lines.append(f"文字识别用：{ocr_device()}")
    except Exception:
        pass
    lines.append("数据：" + json.dumps(_data_versions(), ensure_ascii=False))
    lines.append(f"安装位置里有中文：{'是' if any(ord(c) > 127 for c in str(paths.ROOT)) else '否'}")
    return "\n".join(lines) + "\n"


@api
def export_logs():
    """「导出日志」：运行日志 + 设置 + 一页系统说明打成一个压缩包，放到桌面，并在文件夹里选中它"""
    from ..core import paths
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


# ---------------------------------------------------------------- 在线升级与版本回滚
_found = {"at": 0.0, "rows": []}
_online = {"info": None, "told": ""}
VPK_PREV = "vpk:prev"
FROZEN_UPGRADE_MSG = "安装版在「设置与更新」点击「检查更新」在线升级，或到发布页下载新的安装程序（AT_Setup_版本号.exe）直接安装（设置和记录会保留）"


def _upgrade_found():
    """下载/桌面/微信/QQ 里有没有更新的 AT 安装包（10 分钟找一次，找一次不到 0.1 秒）"""
    if time.time() - _found["at"] > 600:
        try:
            from ..update.upgrade import find_packages
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


def _online_info(force=False):
    """网上有没有新版本（只在后台线程里调：最多等几秒）"""
    from ..core import settings
    from ..update import update_check
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
    from ..update.upgrade import find_packages, rollback_options
    from ..update import update_check
    from ..update import vpk
    if vpk.installed():                       # Velopack 安装版：不找本地安装包；回滚 = 从 AT 服务器装回上一个版本
        _found.update(at=time.time(), rows=[])
        from ..update.upgrade import ver, current
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
        from ..update.upgrade import ver, current
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


def _task_print():
    """给 Velopack 的进度回调用：它在 Velopack 自己的线程里调，那个线程不属于升级任务，print 进不了窗口"""
    tid = bus.current_task()

    def out(line):
        if tid and bus.current_task() != tid:
            bus.adopt_task(tid)
        print(line)
    return out


def _vpk_rollback_task():
    from ..update import vpk
    v = vpk.install(rollback=True, progress=_task_print())
    print(f"✅ 已下载 AT {v}，AT 将关闭并自动安装，完成后自动重新打开")
    time.sleep(1.5)
    from ..app.server import QUIT
    QUIT.set()
    return {"from": _version(), "to": v}


def _online_task():
    from ..update import update_check
    from ..update import vpk
    if vpk.installed():                          # Velopack 安装版：只下改过的部分，AT 退出后换文件、自动重新打开
        v = vpk.install(progress=_task_print())
        print(f"✅ 已下载 AT {v}，AT 将关闭并自动安装，完成后自动重新打开")
        time.sleep(1.5)
        from ..app.server import QUIT
        QUIT.set()
        return {"from": _version(), "to": v}
    info = _online.get("info") or update_check.check(force=True)
    if not info:
        raise ValueError("未找到新版本")
    path = update_check.download(info)
    _found["at"] = 0.0
    from ..core.paths import FROZEN
    if FROZEN:                                   # 独立安装版：运行新的安装程序，AT 先退出，装完自动重新打开
        update_check.launch_installer(path)
        print(f"✅ 已下载 AT {info['version']}，AT 将关闭并自动安装，完成后自动重新打开（约半分钟）")
        time.sleep(1.5)
        from ..app.server import QUIT
        QUIT.set()
        return {"from": _version(), "to": info["version"]}
    return _upgrade_task(str(path))


@api
def upgrade_online():
    """「下载并升级」：下载网上的新版本，核对后照常升级（先备份，能回滚）。
    Velopack 安装版直接问更新源有没有新版本（latest.json 读不到也能升）"""
    from ..update import vpk
    if not _online.get("info") and not vpk.installed():
        return {"error": "未找到新版本，点击「检查更新」后重试"}
    if bus.run_task_once("upgrade", _online_task, title="升级 AT") is None:
        return {"error": "正在升级，稍候"}
    return {"started": True}


@api
def upgrade_rollback(path=""):
    """回滚到旧版本（稳定版 / 自动备份 / 旧安装包）：和升级同一套流程，装之前也会先备份现在的版本。
    Velopack 安装版：path = VPK_PREV，从 AT 服务器装回上一个版本"""
    from ..update import vpk
    if path == VPK_PREV:
        if not vpk.installed():
            return {"error": "只有安装版能这样回滚"}
        if bus.run_task_once("upgrade", _vpk_rollback_task, title="回滚 AT") is None:
            return {"error": "正在升级，稍候"}
        return {"started": True}
    return upgrade_apply(path)


@api
def upgrade_mark_stable():
    from ..update.upgrade import mark_stable
    try:
        p = mark_stable()
    except Exception as e:
        return {"error": f"保存稳定版失败：{e}"}
    return {"path": str(p), "version": _version()}


def _drop_upload(path):
    """手动上传的包（userdata/upgrade/<随机名>/…）装完就删；别处的包（下载文件夹、备份）不动"""
    from ..core import paths
    try:
        p = Path(path).resolve()
        d = (paths.USER / "upgrade").resolve()
        if p.parent.parent == d:
            shutil.rmtree(p.parent, ignore_errors=True)
    except Exception:
        pass


def _upgrade_task(path):
    from ..update import upgrade
    try:
        r = upgrade.apply(path)
    except ValueError as e:
        print(f"❌ {e}")
        raise
    finally:
        _drop_upload(path)
    print(f"✅ 已{'升级' if upgrade.ver(r['to']) >= upgrade.ver(r['from']) else '回滚'}到 {r['to']}，马上重启 AT…")
    time.sleep(1.5)
    from ..app.server import _relaunch
    _relaunch()
    return r


@api
def upgrade_apply(path=""):
    from ..core.paths import FROZEN
    if FROZEN:                              # 独立打包版：程序在 _internal 里，按旧方式覆盖源码会出错
        return {"error": FROZEN_UPGRADE_MSG}
    from ..update.upgrade import check
    try:
        check(path)
    except ValueError as e:
        return {"error": str(e)}
    if bus.run_task_once("upgrade", _upgrade_task, path, title="升级 AT") is None:
        return {"error": "正在升级，稍候"}
    return {"started": True}


def _sweep_uploads(d):
    """清掉以前上传剩下的随机文件夹。只清 1 小时前的：正在收的、刚交给升级任务的那份不碰（任务用完自己删）"""
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


def upgrade_receive(name, write):
    """接收窗口里手动选的安装包（新旧上传接口共用）：
    每次写到 userdata/upgrade/<随机名>/Dubhe_x.y.z.zip（独立文件，两次上传互不覆盖，升级任务读的时候也不会被下一次上传改掉），
    write(f) 负责把内容写进打开的文件（抛异常=没收完），收完先校验再交给升级任务；没启动成功就把这份删掉。
    升级任务用完（成功或失败）会删掉这个随机文件夹（_upgrade_task）。"""
    from ..core import paths
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


@api
def upgrade_upload(name="", data=""):
    """旧接口（base64 整包进内存）：1.0.4 起网页改走 /api/upgrade_upload_raw 流式上传，这里只留给老窗口"""
    try:
        raw = base64.b64decode(data)
    except Exception:
        return {"error": "无法读取此文件"}
    return upgrade_receive(name, lambda f: f.write(raw))


@api
def upgraded():
    """刚升级完重启后：窗口弹一句「已升级到 x」"""
    from ..update.upgrade import just_upgraded, adopt_previous
    d = just_upgraded() or {}
    if d.get("from"):
        try:
            adopt_previous(d["from"])          # 旧版本自己不会备份（1.6.18 及以前）：找到它的安装包就收进备份
        except Exception:
            pass
        from ..update.upgrade import ver
        d["rollback"] = ver(d["to"]) < ver(d["from"])
    return d


# ---------------------------------------------------------------- 旧版天枢过渡
_legacy = {"rows": None}


@api
def legacy_scan():
    """安装版：电脑上的旧版天枢（压缩包版），以及哪些正开着。ask=True 表示还没问过要不要导入"""
    from ..update import legacy
    from ..core import settings
    from ..core.paths import FROZEN
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
    from ..update import legacy
    from ..core import settings
    if path not in [r["path"] for r in (_legacy["rows"] or [])]:
        return {"error": "未找到这个旧版"}
    try:
        done = legacy.import_from(path)
    except Exception as e:
        return {"error": f"导入失败：{e}"}
    settings.update(legacy_checked=True)

    def later():
        time.sleep(1.5)
        from ..app.server import _relaunch
        _relaunch()
    threading.Thread(target=later, daemon=True).start()
    return {"done": done}


@api
def legacy_skip():
    from ..core import settings
    settings.update(legacy_checked=True)
    return {"ok": True}


@api
def legacy_quit(path=""):
    """关掉正在运行的旧版天枢（请它自己退出）"""
    from ..update import legacy
    if path not in [r["path"] for r in (_legacy["rows"] or [])]:
        return {"error": "未找到这个旧版"}
    try:
        legacy.quit_old(path)
    except Exception:
        return {"error": "旧版未响应：在屏幕右下角托盘右键旧版天枢图标，选「退出」"}
    return {"ok": True}


# ---------------------------------------------------------------- 问题反馈与诊断
_FB_LAST = {"sig": None, "scan": None}      # 最近一次推送的信号 / 扫描结果（反馈时写进去对照）
_ORE_LAST = {"view": None}                  # 最近一次出的采矿助手结果（原矿记录记的就是它）


def _fb_dir():
    from ..core import paths
    d = paths.USER / "feedback"
    d.mkdir(parents=True, exist_ok=True)
    return d


@api
def feedback_report(kind="auto", note="", img=None):
    """一键反馈：现在的整屏截图 + 最近几帧采矿助手截图 + OCR 原文 + 当时显示的结果 + 日志尾巴，打成一个文件夹和 zip
    放在 userdata\\feedback\\。kind：scan（矿物认错）/ signal（信号不对）/ item（F8 认错）/ auto"""
    from ..core import paths
    from ..mining import screen
    from ..mining.screen import grab
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

    srv = _services()
    last_hover = getattr(srv, "_last_hover", {})
    live_running = srv._live.running() if hasattr(srv, "_live") else False
    live_paused = getattr(srv._live, "paused", False) if hasattr(srv, "_live") else False
    where_now = srv._WHERE.get("v") if hasattr(srv, "_WHERE") else None
    nav_label = srv._nav.target_label() if hasattr(srv, "_nav") else ""
    nav_space = srv._nav.space_mode if hasattr(srv, "_nav") else False

    fb_sig = getattr(srv, "_FB_LAST", {}).get("sig") if hasattr(srv, "_FB_LAST") else _FB_LAST["sig"]
    fb_scan = getattr(srv, "_FB_LAST", {}).get("scan") if hasattr(srv, "_FB_LAST") else _FB_LAST["scan"]

    info = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "version": _version(), "kind": kind, "note": note or "",
            "screen": [img.width, img.height] if img else None,
            "ocr_scan_lines": screen.LAST_RAW.get("scan"), "ocr_bag_lines": screen.LAST_RAW.get("bag"),
            "ocr_age_s": round(time.time() - screen.LAST_RAW.get("t", 0)) if screen.LAST_RAW.get("t") else None,
            "shown_signal": fb_sig, "shown_scan": fb_scan,
            "hover": {k: v for k, v in last_hover.items() if k != "img"},
            "hud": dict(getattr(_hud(), "sections", {}) or {}), "live": live_running, "live_paused": live_paused,
            "where_now": where_now, "nav": nav_label, "nav_space": nav_space}
    try:
        from ..core import settings
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
    from ..system import feedback_up
    upload = feedback_up.enabled()
    hm = f"{stamp[-6:-4]}:{stamp[-4:-2]}:{stamp[-2:]}"
    try:
        _note_hud("反馈", f"📝 已保存问题反馈（{hm}）\n" + ("正在发送给作者…" if upload else "可在设置页「问题反馈」导出"), 6)
    except Exception:
        pass
    if upload:                                   # 存好就自动发给作者（后台，不卡游戏）
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
            note = json.loads((d / "情况.json").read_text(encoding="utf-8")).get("note", "")
        except Exception:
            pass
        rows.append({"name": z.stem, "kb": round(z.stat().st_size / 1024), "note": note, "sent": (d / ".sent").exists(),
                     "at": time.strftime("%m-%d %H:%M", time.localtime(z.stat().st_mtime))})
    return rows


@api
def feedback_export():
    """把所有反馈 zip 再打成一个包放到桌面，并在文件夹里选中"""
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
    n = 0
    for f in list(_fb_dir().iterdir()):
        try:
            shutil.rmtree(f) if f.is_dir() else f.unlink()
            n += 1
        except OSError:
            pass
    return {"removed": n}


# ---------------------------------------------------------------- 辅助、悬浮窗与设置修改
@api
def cockpit_check():
    """辅助进程双击 W 时问：现在画面中间有没有飞行 HUD（用主程序的识别引擎，辅助进程不用自己加载一份）"""
    from ..system import cockpit
    try:
        flying, hits = cockpit.flight_hud()
    except Exception as e:
        return {"flying": False, "error": str(e)}
    return {"flying": bool(flying), "hits": hits[:4]}


@api
def overlay_move(on=False):
    """「移动悬浮窗」：打开时悬浮窗能拖动（不穿透），关上恢复鼠标穿透"""
    h = _hud()
    if h and hasattr(h, "set_movable"):
        h.set_movable(bool(on))
    return {"on": bool(on)}


@api
def set_settings(**kw):
    from ..core import settings
    from ..system import helpers
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
    clear_train = kw.get("train_upload") is False          # 关掉「帮助改进识别」：先存「关」，再删本地攒着没发的
    if "hud_scale" in kw:
        kw["hud_scale"] = min(1.0, max(0.5, float(kw["hud_scale"])))
    if "hud_plate" in kw:
        kw["hud_plate"] = min(1.0, max(0.3, float(kw["hud_plate"])))
    if "hud_theme" in kw and kw["hud_theme"] not in ("默认", "蓝金", "浅色"):
        kw["hud_theme"] = "默认"
    cur = None
    for name, default, label in HOTKEYS:                # 所有热键都能在设置页改
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
            from ..system import train_data
            train_data.clear()
        except Exception:
            pass
    if any(k in kw for k in ("hud_theme", "hud_plate", "hud_scale")):
        try:
            h = _hud()
            if h and hasattr(h, "restyle"):
                h.restyle()
        except Exception:
            pass
    if any(k in kw for k in ("anti_afk", "afk_seconds", "autorun", "autorun_sprint", "admin")):
        helpers.start()                                   # 只有辅助相关的项变了才重启辅助进程
    bus.publish("status", status())
    return cfg


@api
def update_data():
    from ..run import update
    if bus.run_task_once("update", update, title="更新数据") is None:   # 已经在更新：不再起第二份
        return {"started": False, "running": True}
    return {"started": True}


# ---------------------------------------------------------------- 关于、许可与用户协议
REFERRAL_URL = "https://www.robertsspaceindustries.com/enlist?referral=STAR-4CNY-K3YT"

# 数据来源：(名称, 网址, 提供什么)
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
    webbrowser.open(DATA_SOURCES[int(i)][1])
    return {"ok": True}


@api
def third_party_licenses():
    """开源组件许可证原文（安装目录的「第三方许可.txt」，打包时由 tools/collect_licenses.py 生成）"""
    from ..core import paths
    p = paths.ROOT / "第三方许可.txt"
    try:
        return {"text": p.read_text(encoding="utf-8-sig")}
    except OSError:
        return {"text": "", "error": "未找到「第三方许可.txt」（开发目录里没有，打包时生成）"}


@api
def open_referral():
    """用系统默认浏览器打开作者的星际公民邀请注册页（只能打开这一个固定网址）"""
    webbrowser.open(REFERRAL_URL)
    return {"ok": True}


AGREE_TEXT = "本软件是免费软件"


@api
def agree(text=""):
    """第一次打开：必须一字不差地输入「本软件是免费软件」才能用"""
    from ..core import settings
    if (text or "").strip() != AGREE_TEXT:
        return {"error": f"需完整输入：{AGREE_TEXT}"}
    settings.update(agreed=True)
    from ..system import helpers
    helpers.start()
    start_background()
    return status()


def start_background():
    """窗口打开时：后台监听与轮询初始化"""
    try:
        srv = _services()
        if hasattr(srv, "start_background"):
            srv.start_background()
            return
    except Exception:
        pass
    from ..core import settings
    if not settings.load().get("agreed"):
        return
    if not _online.get("loop"):
        _online["loop"] = True
        threading.Thread(target=_online_loop, daemon=True, name="update").start()
    if not _online.get("fb_retry"):
        _online["fb_retry"] = True
        from ..system import feedback_up
        threading.Thread(target=lambda: feedback_up.retry_pending(_fb_dir()), daemon=True, name="feedback-retry").start()


@api
def show():
    """又双击了一次 Dubhe.exe：后台开着的 AT 把窗口打开"""
    from ..app.server import show_window
    show_window()
    return {"ok": True}


@api
def quit():
    """又双击了一次 Dubhe.exe：旧的这个退出，让新的接手"""
    from ..app.server import QUIT
    QUIT.set()
    return {"ok": True}


__all__ = [
    "status",
    "upgrade_check",
    "upgrade_online",
    "upgrade_rollback",
    "upgrade_mark_stable",
    "upgrade_apply",
    "upgrade_receive",
    "upgrade_upload",
    "upgraded",
    "legacy_scan",
    "legacy_import",
    "legacy_skip",
    "legacy_quit",
    "export_logs",
    "feedback_report",
    "feedback_list",
    "feedback_export",
    "feedback_clear",
    "cockpit_check",
    "overlay_move",
    "set_settings",
    "update_data",
    "about_info",
    "open_source_site",
    "third_party_licenses",
    "open_referral",
    "agree",
    "show",
    "quit",
    "start_background",
    "hotkey_conflicts",
    "API",
    "HOTKEYS",
    "DATA_SOURCES",
    "VPK_PREV",
]
