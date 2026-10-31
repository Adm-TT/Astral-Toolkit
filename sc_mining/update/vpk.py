"""Velopack 在线更新和回滚（2026-10-27，老大定：换 Velopack，只下载改过的部分）

- 只在 Velopack 安装版里用（paths.VELOPACK）；Python 版、老的 Inno 安装版照旧走 update_check / upgrade
- 更新源：自己的香港服务器 https://dl.astral-trade.com/velopack/（releases.win.json + 完整包 / 增量包）；
  连不上（出错 / 超时）再用国内镜像（腾讯云 COS，路径一样，2026-10-29：国内连不上香港）
- 升级：查到新版本 → 下载（有增量包就只下改动）→ 等 AT 退出后换程序文件 → 自动重新打开
- 回滚：同一个地址的「prev」频道只放上一个版本（tools/build_velopack.py 发布时生成），允许降级，装回上一版
- 设置和记录在 %LOCALAPPDATA%\\AT_userdata，升级、回滚都不动
"""

from ..core import paths
from .update_check import OWN, OWN_NAME, COS, COS_NAME

import os

_dev = (not paths.FROZEN) or os.environ.get(
    "AT_DEV"
) == "1"  # 发布版不认环境变量里的更新源（2026-10-28 整体审查）；作者测试时设 AT_DEV=1
_env = (
    os.environ.get("AT_VPK_FEED") if _dev else None
)  # AT_VPK_FEED：沙盒测试时指到本地文件夹
FEEDS = (
    [(_env, "测试源")]
    if _env
    else [(f"https://{OWN}/velopack", OWN_NAME), (f"https://{COS}/velopack", COS_NAME)]
)
FEED = FEEDS[0][0]
CHANNEL = "win"
DOWNLOAD_MS = (
    60 * 60 * 1000
)  # 下载最多 60 分钟（网断了不会一直卡在「正在下载」；完整包 141 MB，慢网也够）
PREV = "prev"


def installed():
    return paths.VELOPACK


def _channels(rollback):
    """要问哪些频道：回滚只问 prev；装的是测试版（x.y.z-beta.N）时 beta 和 win 都问、取更新的那个
    （发布脚本把测试版打进 beta 频道；只问 win 的话测试版玩家收不到下一个测试版，2026-10-31 合并后审查）"""
    if rollback:
        return [PREV]
    from . import upgrade

    return ["beta", CHANNEL] if "-" in str(upgrade.VERSION) else [CHANNEL]


def _mgr(rollback=False, timeout_ms=0, feed=None, channel=None):
    """timeout_ms：整个请求（连上 + 传完）最多多久；查版本给 8 秒，下载不限（大文件）。feed：更新源地址（默认第一个）。
    channel：频道（默认 win，回滚是 prev）"""
    import velopack

    feed = feed or FEED
    opts = velopack.UpdateOptions(
        bool(rollback), 10, channel or (PREV if rollback else CHANNEL)
    )
    # 超时只对网址有用；本地文件夹（沙盒测试）直接给路径，HttpSource 不认本地路径（2026-10-27 沙盒发现回滚列表是空的）
    src = (
        velopack.HttpSource(feed, velopack.HttpOptions([], timeout_ms))
        if timeout_ms and feed.startswith("http")
        else feed
    )
    return velopack.UpdateManager(src, opts)


def _version_of(info):
    """UpdateInfo → 版本号字符串"""
    rel = getattr(info, "TargetFullRelease", None)
    return str(getattr(rel, "Version", "") or "")


_last = {"feed": None}  # 上一次答上来的源：下次先问它（国内不用每次先等香港超时）


def _ask(feed, rollback, timeout_ms=8000):
    """在一个源上把要问的频道都问一遍 → (版本最新的 UpdateInfo 或 None, 它的频道)；所有频道都出错才抛错"""
    from .upgrade import vkey

    best, best_ch, err, ok = None, None, None, False
    for ch in _channels(rollback):
        try:
            info = _mgr(rollback, timeout_ms, feed, ch).check_for_updates()
            ok = True
        except Exception as e:  # 这个频道没有（比如还没发过测试版）或连不上：问下一个
            err = e
            continue
        if info and (best is None or vkey(_version_of(info)) > vkey(_version_of(best))):
            best, best_ch = info, ch
    if not ok:
        raise err if err else RuntimeError("更新源没有回答")
    return best, best_ch


def _check_at(rollback):
    """按顺序问更新源（上次答上来的 → 香港 → 国内镜像），第一个答得上的 → (UpdateInfo 或 None, 源地址, 源名字, 频道)；都连不上抛 RuntimeError"""
    err = None
    for feed, name in sorted(FEEDS, key=lambda f: f[0] != _last["feed"]):
        try:
            info, ch = _ask(feed, rollback)
            _last["feed"] = feed
            return info, feed, name, ch
        except Exception as e:  # 连不上 / 超时：换下一个
            err = e
    raise RuntimeError(f"{'和'.join(n for _, n in FEEDS)}都无法连接：{err}") from err


def check(rollback=False):
    """有可装的版本就返回 (UpdateInfo, 版本号, 源名字)，没有返回 (None, "", 源名字)。都连不上抛 RuntimeError"""
    info, _, name, _ = _check_at(rollback)
    if not info:
        return None, "", name
    return info, _version_of(info), name


def install(rollback=False, progress=print):
    """下载并安排安装：下载完后让 Update.exe 等 AT 退出再换文件、重新打开 AT。返回版本号；调用方随后要让 AT 退出。
    rollback=True：装回上一个版本"""
    info, feed, name, ch = _check_at(rollback)
    if not info:
        raise ValueError("没有可回滚的上一个版本" if rollback else "未找到新版本")
    v = _version_of(info)
    from .upgrade import vkey, current_key  # 算上 beta 后缀比（1.1.2-beta.1 < 1.1.2）

    if rollback and vkey(v) >= current_key():
        raise ValueError(f"服务器上的上一个版本是 {v}，不比现在的旧，不用回滚")
    if not rollback and vkey(v) <= current_key():
        raise ValueError("已经是最新版本")
    shown = {"p": -1}

    def cb(p):
        p = int(p)
        if p // 5 != shown["p"] // 5:
            shown["p"] = p
            progress(f"已下载 {p}%")

    rest = [f for f in FEEDS if f[0] != feed]
    last_err = None
    for k, (fd, nm) in enumerate([(feed, name)] + rest):
        if k:  # 上一个源下载失败：换下一个源重新问一遍、再下载
            try:
                info, ch = _ask(fd, rollback)
            except Exception as e:
                last_err = e
                continue
            if not info or _version_of(info) != v:
                continue
        m = _mgr(rollback, DOWNLOAD_MS, fd, ch)
        progress(f"正在下载 AT {v}（{nm}）…")
        try:
            try:
                m.download_updates(info, cb)
            except TypeError:  # 老版本的接口没有进度回调
                m.download_updates(info)
            break
        except Exception as e:
            if k == len(rest):
                raise
            last_err = e
            progress(f"{nm} 下载失败：{e}")
    else:  # 后面的源都问不到同一个版本
        raise RuntimeError(f"更新源都下载不了，稍后再试（{last_err}）")
    progress("下载完成，校验通过")
    m.wait_exit_then_apply_updates(info.TargetFullRelease, False, True, [])
    return v
