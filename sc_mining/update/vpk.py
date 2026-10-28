"""Velopack 在线更新和回滚（2026-10-27，老大定：换 Velopack，只下载改过的部分）

- 只在 Velopack 安装版里用（paths.VELOPACK）；Python 版、老的 Inno 安装版照旧走 update_check / upgrade
- 更新源：自己的香港服务器 https://dl.astral-trade.com/velopack/（releases.win.json + 完整包 / 增量包）
- 升级：查到新版本 → 下载（有增量包就只下改动）→ 等 AT 退出后换程序文件 → 自动重新打开
- 回滚：同一个地址的「prev」频道只放上一个版本（tools/build_velopack.py 发布时生成），允许降级，装回上一版
- 设置和记录在 %LOCALAPPDATA%\\AT_userdata，升级、回滚都不动
"""
from ..core import paths
from .update_check import OWN

import os
_dev = (not paths.FROZEN) or os.environ.get("AT_DEV") == "1"       # 发布版不认环境变量里的更新源（2026-10-28 整体审查）；作者测试时设 AT_DEV=1
FEED = (os.environ.get("AT_VPK_FEED") if _dev else None) or f"https://{OWN}/velopack"     # AT_VPK_FEED：沙盒测试时指到本地文件夹
CHANNEL = "win"
DOWNLOAD_MS = 60 * 60 * 1000          # 下载最多 60 分钟（网断了不会一直卡在「正在下载」；完整包 141 MB，慢网也够）
PREV = "prev"


def installed():
    return paths.VELOPACK


def _mgr(rollback=False, timeout_ms=0):
    """timeout_ms：整个请求（连上 + 传完）最多多久；查版本给 8 秒，下载不限（大文件）"""
    import velopack
    opts = velopack.UpdateOptions(bool(rollback), 10, PREV if rollback else CHANNEL)
    # 超时只对网址有用；本地文件夹（沙盒测试）直接给路径，HttpSource 不认本地路径（2026-10-27 沙盒发现回滚列表是空的）
    src = velopack.HttpSource(FEED, velopack.HttpOptions([], timeout_ms)) if timeout_ms and FEED.startswith("http") else FEED
    return velopack.UpdateManager(src, opts)

def _version_of(info):
    """UpdateInfo → 版本号字符串"""
    rel = getattr(info, "TargetFullRelease", None)
    return str(getattr(rel, "Version", "") or "")


def check(rollback=False):
    """有可装的版本就返回 (UpdateInfo, 版本号)，没有返回 (None, "")。连不上服务器抛异常"""
    m = _mgr(rollback, 8000)
    info = m.check_for_updates()
    if not info:
        return None, ""
    return info, _version_of(info)


def install(rollback=False, progress=print):
    """下载并安排安装：下载完后让 Update.exe 等 AT 退出再换文件、重新打开 AT。返回版本号；调用方随后要让 AT 退出。
    rollback=True：装回上一个版本"""
    info = _mgr(rollback, 8000).check_for_updates()
    if not info:
        raise ValueError("没有可回滚的上一个版本" if rollback else "未找到新版本")
    m = _mgr(rollback, DOWNLOAD_MS)
    v = _version_of(info)
    from .upgrade import ver, current
    if rollback and ver(v) >= current():
        raise ValueError(f"服务器上的上一个版本是 {v}，不比现在的旧，不用回滚")
    if not rollback and ver(v) <= current():
        raise ValueError("已经是最新版本")
    shown = {"p": -1}

    def cb(p):
        p = int(p)
        if p // 5 != shown["p"] // 5:
            shown["p"] = p
            progress(f"已下载 {p}%")
    progress(f"正在下载 AT {v}（AT 服务器）…")
    try:
        m.download_updates(info, cb)
    except TypeError:                                  # 老版本的接口没有进度回调
        m.download_updates(info)
    progress("下载完成，校验通过")
    m.wait_exit_then_apply_updates(info.TargetFullRelease, False, True, [])
    return v
