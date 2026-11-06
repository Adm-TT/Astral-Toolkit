"""在线更新检测、后台轮询与版本回滚（Velopack；旧 Inno 桥接升级保留到 1.1.4）"""

import threading
import time

from ...app import bus, task_runner
from .about import _version

_online = {"info": None, "told": ""}
VPK_PREV = "vpk:prev"


def _online_info(force=False):
    """网上有没有新版本（只在后台线程里调：最多等几秒）"""
    from ...core import settings
    from ...update import update_check

    if not update_check.enabled():
        _online["info"] = None
        return None
    if not settings.load().get("update_online", True):
        _online["info"] = None  # 不提示新版本，也不额外联网
        return None
    try:
        info = update_check.check(force=force)
    except Exception:
        info = None
    _online["info"] = info
    if info and _online["told"] != info["version"]:
        _online["told"] = info["version"]
        bus.publish(
            "update", {"version": info["version"], "notes": info.get("notes", [])}
        )
    return info


def _online_loop(stop_ev=None):
    if stop_ev is None:
        stop_ev = threading.Event()
    if stop_ev.wait(20):  # 刚启动先让识别、窗口起来
        return
    while not stop_ev.is_set():
        _online_info()
        if stop_ev.wait(1800):
            # 检查本身 6 小时才真的联网一次（update_check.EVERY）
            break


def _online_public(info):
    return (
        {k: info[k] for k in ("version", "date", "notes", "size", "source")}
        if info
        else None
    )


def upgrade_check(online=False):
    """online=True：顺便到网上查一次（设置页「检查更新」）。
    Velopack 安装版只给 prev 回滚行；其他安装版不找本地包，只显示在线说明。"""
    from ...update import update_check, vpk
    from ...update.version import current_key, vkey

    pub = None
    older = []
    hint = ""
    err = ""
    if vpk.installed():
        if online:
            src, fail = "", False
            try:
                _, pv, src = vpk.check(rollback=True)
            except Exception:
                pv = ""
            try:
                _, nv, src = vpk.check()
            except Exception:  # 香港和国内镜像都连不上：不能说「已是最新」
                nv, fail = "", True
            _online.update(prev=pv, vpk_new=nv, vpk_src=src, vpk_fail=fail)
        pv = _online.get("prev") or ""
        if pv and vkey(pv) < current_key():
            older = [
                {
                    "version": pv,
                    "where": _online.get("vpk_src") or "AT 服务器",
                    "at": "",
                    "path": VPK_PREV,
                    "action": "回滚到",
                    "stable": False,
                }
            ]
        info = _online_info(force=True) if online else _online.get("info")
        pub = _online_public(info)
        nv = _online.get("vpk_new") or ""
        if nv and vkey(nv) > current_key():
            same = pub and pub["version"] == nv
            pub = {
                "version": nv,
                "date": pub["date"] if same else "",
                "notes": pub["notes"] if same else [],
                "size": None,
                "source": _online.get("vpk_src") or "AT 服务器",
            }
            err = ""
        else:
            if _online.get("vpk_fail"):
                err = "无法连接更新服务器"
                if pub and vkey(pub["version"]) > current_key():
                    hint = f"无法连接更新服务器。网上已有 AT {pub['version']}，可在下载页手动下载"
            pub = None
        return {
            "current": _version(),
            "older": older,
            "online": pub,
            "online_enabled": update_check.enabled(),
            "online_error": err,
            "online_hint": hint,
        }
    info = _online_info(force=True) if online else _online.get("info")
    err = update_check.last_error() if online and not info else ""
    return {
        "current": _version(),
        "older": [],
        "online": _online_public(info),
        "online_enabled": update_check.enabled(),
        "online_error": err,
    }


def _task_print():
    """给 Velopack 的进度回调用：它在 Velopack 自己的线程里调，那个线程不属于升级任务，print 进不了窗口"""
    tid = task_runner.current_task()

    def out(line):
        if tid and task_runner.current_task() != tid:
            task_runner.adopt_task(tid)
        print(line)

    return out


def _vpk_rollback_task():
    from ...update import vpk

    v = vpk.install(rollback=True, progress=_task_print())
    print(f"✅ 已下载 AT {v}，AT 将关闭并自动安装，完成后自动重新打开")
    time.sleep(1.5)
    from ...app.server import QUIT

    QUIT.set()
    return {"from": _version(), "to": v}


def _online_task():
    from ...update import update_check, vpk

    if (
        vpk.installed()
    ):  # Velopack 安装版：只下改过的部分，AT 退出后换文件、自动重新打开
        v = vpk.install(progress=_task_print())
        print(f"✅ 已下载 AT {v}，AT 将关闭并自动安装，完成后自动重新打开")
        time.sleep(1.5)
        from ...app.server import QUIT

        QUIT.set()
        return {"from": _version(), "to": v}
    info = _online.get("info") or update_check.check(force=True)
    if not info:
        raise ValueError("未找到新版本")
    from ...core.paths import FROZEN

    if not FROZEN:
        raise ValueError("源码包在线升级已退役，请使用安装版")
    path = update_check.download(info)
    update_check.launch_installer(path)
    print(
        f"✅ 已下载 AT {info['version']}，AT 将关闭并自动安装，完成后自动重新打开（约半分钟）"
    )
    time.sleep(1.5)
    from ...app.server import QUIT

    QUIT.set()
    return {"from": _version(), "to": info["version"]}


def upgrade_online():
    """「下载并升级」：下载网上的新版本，核对后照常升级（先备份，能回滚）。
    Velopack 安装版直接问更新源有没有新版本（latest.json 读不到也能升）"""
    from ...update import vpk

    if not _online.get("info") and not vpk.installed():
        return {"error": "未找到新版本，点击「检查更新」后重试"}
    if task_runner.run_task_once("upgrade", _online_task, title="升级 AT") is None:
        return {"error": "正在升级，稍候"}
    return {"started": True}


def upgrade_rollback(path=""):
    """回滚到旧版本：只接受 Velopack 的 VPK_PREV。"""
    from ...update import vpk

    if path != VPK_PREV:
        return {"error": "只能回滚到安装版的上一版本"}
    if not vpk.installed():
        return {"error": "只有安装版能这样回滚"}
    if (
        task_runner.run_task_once("upgrade", _vpk_rollback_task, title="回滚 AT")
        is None
    ):
        return {"error": "正在升级，稍候"}
    return {"started": True}
