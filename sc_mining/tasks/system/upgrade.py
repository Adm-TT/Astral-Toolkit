"""在线更新检测、后台轮询、安装包流式接收与版本回滚"""

import base64
import re
import shutil
import time
import uuid
from pathlib import Path

from ...app import bus
from .about import _version

_found = {"at": 0.0, "rows": []}
_online = {"info": None, "told": ""}
VPK_PREV = "vpk:prev"
FROZEN_UPGRADE_MSG = "安装版在「设置与更新」点击「检查更新」在线升级，或到发布页下载新的安装程序（AT_Setup_版本号.exe）直接安装（设置和记录会保留）"


def _upgrade_found():
    """下载/桌面/微信/QQ 里有没有更新的 AT 安装包（10 分钟找一次，找一次不到 0.1 秒）"""
    if time.time() - _found["at"] > 600:
        try:
            from ...update.upgrade import find_packages

            _found["rows"] = find_packages()
        except Exception:
            _found["rows"] = []
        _found["at"] = time.time()
    if _found["rows"]:
        return _found["rows"][0]
    info = _online.get("info")
    if info:  # 网上有新版本、电脑里还没有安装包
        return {
            "version": info["version"],
            "where": "网上",
            "at": info.get("date", ""),
            "online": True,
        }
    return None


def _online_info(force=False):
    """网上有没有新版本（只在后台线程里调：最多等几秒）"""
    from ...core import settings
    from ...update import update_check

    if not update_check.enabled():
        _online["info"] = None
        return None
    if not settings.load().get("update_online", True):
        _online["info"] = (
            None  # 不提示新版本；远程关功能清单照常每小时查（控制台指令第 2 批选 A）
        )
        try:
            update_check.refresh_kill()
        except Exception:
            pass
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


def _online_loop():
    time.sleep(20)  # 刚启动先让识别、窗口起来
    while True:
        _online_info()
        time.sleep(1800)  # 检查本身 6 小时才真的联网一次（update_check.EVERY）


def _online_public(info):
    return (
        {k: info[k] for k in ("version", "date", "notes", "size", "source")}
        if info
        else None
    )


def upgrade_check(online=False):
    """online=True：顺便到网上查一次（设置页「检查更新」；最多等 5 秒×2）"""
    from ...update import update_check, vpk
    from ...update.upgrade import find_packages, rollback_options

    if (
        vpk.installed()
    ):  # Velopack 安装版：不找本地安装包；回滚 = 从 AT 服务器装回上一个版本
        _found.update(at=time.time(), rows=[])
        from ...update.upgrade import (
            current_key,
            vkey,
        )  # 算上 beta 后缀比（S5 审查 2026-10-31）

        if online:
            src, fail = "", False
            try:
                _, pv, src = vpk.check(rollback=True)
            except Exception:
                pv = ""
            try:
                _, nv, src = vpk.check()
            except (
                Exception
            ):  # 香港和国内镜像都连不上：不能说「已是最新」（审查 2026-10-29）
                nv, fail = "", True
            _online.update(prev=pv, vpk_new=nv, vpk_src=src, vpk_fail=fail)
        pv = _online.get("prev") or ""
        older = (
            [
                {
                    "version": pv,
                    "where": _online.get("vpk_src") or "AT 服务器",
                    "at": "",
                    "path": VPK_PREV,
                    "action": "回滚到",
                    "stable": False,
                }
            ]
            if pv and vkey(pv) < current_key()
            else []
        )
    else:
        _found.update(at=time.time(), rows=find_packages())
        try:
            older = rollback_options()
        except Exception:
            older = []
    info = _online_info(force=True) if online else _online.get("info")
    err = update_check.last_error() if online and not info else ""
    pub = _online_public(info)
    if (
        vpk.installed()
    ):  # 有没有新版本以 Velopack 更新源为准；大小不显示（增量下载，实际很小）
        from ...update.upgrade import current_key, vkey

        nv = _online.get("vpk_new") or ""
        hint = ""
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
            "found": _found["rows"],
            "older": older,
            "online": pub,
            "online_enabled": update_check.enabled(),
            "online_error": err,
            "online_hint": hint,
        }
    return {
        "current": _version(),
        "found": _found["rows"],
        "older": older,
        "online": pub,
        "online_enabled": update_check.enabled(),
        "online_error": err,
    }


def _task_print():
    """给 Velopack 的进度回调用：它在 Velopack 自己的线程里调，那个线程不属于升级任务，print 进不了窗口"""
    tid = bus.current_task()

    def out(line):
        if tid and bus.current_task() != tid:
            bus.adopt_task(tid)
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
    path = update_check.download(info)
    _found["at"] = 0.0
    from ...core.paths import FROZEN

    if FROZEN:  # 独立安装版：运行新的安装程序，AT 先退出，装完自动重新打开
        update_check.launch_installer(path)
        print(
            f"✅ 已下载 AT {info['version']}，AT 将关闭并自动安装，完成后自动重新打开（约半分钟）"
        )
        time.sleep(1.5)
        from ...app.server import QUIT

        QUIT.set()
        return {"from": _version(), "to": info["version"]}
    return _upgrade_task(str(path))


def upgrade_online():
    """「下载并升级」：下载网上的新版本，核对后照常升级（先备份，能回滚）。
    Velopack 安装版直接问更新源有没有新版本（latest.json 读不到也能升）"""
    from ...update import vpk

    if not _online.get("info") and not vpk.installed():
        return {"error": "未找到新版本，点击「检查更新」后重试"}
    if bus.run_task_once("upgrade", _online_task, title="升级 AT") is None:
        return {"error": "正在升级，稍候"}
    return {"started": True}


def upgrade_rollback(path=""):
    """回滚到旧版本（稳定版 / 自动备份 / 旧安装包）：和升级同一套流程，装之前也会先备份现在的版本。
    Velopack 安装版：path = VPK_PREV，从 AT 服务器装回上一个版本"""
    from ...update import vpk

    if path == VPK_PREV:
        if not vpk.installed():
            return {"error": "只有安装版能这样回滚"}
        if bus.run_task_once("upgrade", _vpk_rollback_task, title="回滚 AT") is None:
            return {"error": "正在升级，稍候"}
        return {"started": True}
    return upgrade_apply(path)


def upgrade_mark_stable():
    from ...update.upgrade import mark_stable

    try:
        p = mark_stable()
    except Exception as e:
        return {"error": f"保存稳定版失败：{e}"}
    return {"path": str(p), "version": _version()}


def _drop_upload(path):
    """手动上传的包（userdata/upgrade/<随机名>/…）装完就删；别处的包（下载文件夹、备份）不动"""
    from ...core import paths

    try:
        p = Path(path).resolve()
        d = (paths.USER / "upgrade").resolve()
        if p.parent.parent == d:
            shutil.rmtree(p.parent, ignore_errors=True)
    except Exception:
        pass


def _upgrade_task(path):
    from ...update import upgrade

    try:
        r = upgrade.apply(path)
    except ValueError as e:
        print(f"❌ {e}")
        raise
    finally:
        _drop_upload(path)
    print(
        f"✅ 已{'升级' if upgrade.ver(r['to']) >= upgrade.ver(r['from']) else '回滚'}到 {r['to']}，马上重启 AT…"
    )
    time.sleep(1.5)
    from ...app.server import _relaunch

    _relaunch()
    return r


def upgrade_apply(path=""):
    from ...core.paths import FROZEN

    if FROZEN:  # 独立打包版：程序在 _internal 里，按旧方式覆盖源码会出错
        return {"error": FROZEN_UPGRADE_MSG}
    from ...update.upgrade import check

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
                p.unlink()  # 1.0.4 以前直接放在 upgrade/ 下的旧包
        except OSError:
            pass


def upgrade_receive(name, write):
    """接收窗口里手动选的安装包（新旧上传接口共用）：
    每次写到 userdata/upgrade/<随机名>/Dubhe_x.y.z.zip（独立文件，两次上传互不覆盖，升级任务读的时候也不会被下一次上传改掉），
    write(f) 负责把内容写进打开的文件（抛异常=没收完），收完先校验再交给升级任务；没启动成功就把这份删掉。
    升级任务用完（成功或失败）会删掉这个随机文件夹（_upgrade_task）。"""
    from ...core import paths

    if not re.match(r"^Dubhe_\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?\.zip$", name or "", re.I):
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
    target = sub / name  # 文件名照旧保留版本号（check 用它兜底）
    try:
        with open(target, "wb") as f:
            write(f)
    except Exception as e:
        shutil.rmtree(sub, ignore_errors=True)  # 半个文件不留
        return {"error": f"保存安装包失败：{e}"}
    try:
        r = upgrade_apply(str(target))
    except Exception:  # 包坏到检查时直接抛（zlib.error 之类）：也别留着
        shutil.rmtree(sub, ignore_errors=True)
        raise
    if not isinstance(r, dict) or r.get(
        "error"
    ):  # 没装（安装版 / 包不对 / 已在升级）：别留着
        shutil.rmtree(sub, ignore_errors=True)
    return r


def upgrade_upload(name="", data=""):
    """旧接口（base64 整包进内存）：1.0.4 起网页改走 /api/upgrade_upload_raw 流式上传，这里只留给老窗口"""
    try:
        raw = base64.b64decode(data)
    except Exception:
        return {"error": "无法读取此文件"}
    return upgrade_receive(name, lambda f: f.write(raw))


def upgraded():
    """刚升级完重启后：窗口弹一句「已升级到 x」"""
    from ...update.upgrade import adopt_previous, just_upgraded

    d = just_upgraded() or {}
    if d.get("from"):
        try:
            adopt_previous(
                d["from"]
            )  # 旧版本自己不会备份（1.6.18 及以前）：找到它的安装包就收进备份
        except Exception:
            pass
        from ...update.upgrade import ver

        d["rollback"] = ver(d["to"]) < ver(d["from"])
    return d
