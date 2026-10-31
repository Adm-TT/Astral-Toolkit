"""在线更新（2026-10-25）：启动时到网上读一个很小的版本说明（latest.json），有新版本就提示；玩家点「下载并升级」才下载。

- 先试自己的香港服务器 dl.astral-trade.com（2026-10-27），再试国内镜像（腾讯云 COS 广州，2026-10-29：国内连不上香港），再试 Gitee、GitHub；每个地址最多等 5 秒，都不通就当没有新版本，不报错（能离线就离线）
- 下载完核对文件大小和 SHA-256，对不上就删掉、不装；装的时候走 upgrade.apply（先备份，失败可回滚）
- 下载的安装包放 userdata/updates（只留最新的一个），一键升级也能找到它
- 版本说明由 tools/make_manifest.py 在发版本时生成

latest.json 的格式：
{"version": "1.7.1", "date": "2026-11-01", "notes": ["更新内容一", "…"],
 "file": "Dubhe_1.7.1.zip", "size": 12345678, "sha256": "…64 位…",
 "urls": ["https://gitee.com/…/Dubhe_1.7.1.zip", "https://github.com/…/Dubhe_1.7.1.zip"],
 "installer": {"file": "AT_Setup_1.7.1.exe", "size": …, "sha256": "…", "urls": […]}}
Python 版用上面的 Dubhe_*.zip；独立安装版（AT.exe，1.7.0 起）只看 installer：下载安装程序，退出 AT 后静默安装，装完自动重新打开。
旧的 Python 版不认识 installer 这一项，会直接忽略，所以两种版本共用一份 latest.json
"""

import hashlib
import json
import re
import threading
import time
from pathlib import Path

from ..core import paths
from ..core.paths import USER

# 仓库地址（「用户名/仓库名」，2026-10-25 用户建的公开仓库）；空着就不检查在线更新
GITEE = (
    "Adm_TT/Astral-Toolkit"  # https://gitee.com/Adm_TT/Astral-Toolkit（master 分支）
)
GITHUB = (
    "Adm-TT/Astral-Toolkit"  # https://github.com/Adm-TT/Astral-Toolkit（main 分支）
)
OWN = "dl.astral-trade.com"  # 自己的香港服务器（2026-10-27）：latest.json、data.json 放根目录，文件放 releases/<标签>/
OWN_NAME = "AT 服务器"
COS = "at-dl-1323647399.cos.ap-guangzhou.myqcloud.com"  # 国内镜像（腾讯云 COS 广州，2026-10-29）：路径和香港服务器一样
COS_NAME = "国内镜像"
TIMEOUT = 5
EVERY = 6 * 3600  # 一直开着时，每 6 小时再查一次
HOSTS = (
    OWN,
    COS,
    "gitee.com",
    "github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "foruda.gitee.com",
)
UPDATES = USER / "updates"
NAME = re.compile(r"^Dubhe_\d+\.\d+\.\d+\.zip$", re.I)
SETUP = re.compile(r"^AT_Setup_\d+\.\d+\.\d+\.exe$", re.I)
SETUP_MAX = 300 * 2**20  # 安装程序（Gitee 单个附件上限 100 MB，这里放宽留余地）

_state = {"at": 0.0, "info": None, "error": "", "lock": threading.Lock()}


def release_urls(tag, name):
    """发行版里一个文件的下载地址：自己的服务器、国内镜像、Gitee、GitHub（按这个顺序试）"""
    out = []
    if OWN:
        out.append(f"https://{OWN}/releases/{tag}/{name}")
    if COS:
        out.append(f"https://{COS}/releases/{tag}/{name}")
    if GITEE:
        out.append(f"https://gitee.com/{GITEE}/releases/download/{tag}/{name}")
    if GITHUB:
        out.append(f"https://github.com/{GITHUB}/releases/download/{tag}/{name}")
    return out


def where(url):
    """下载地址是哪个网站（给玩家看）"""
    m = re.match(r"^https://([^/:]+)/", url or "")
    host = m.group(1).lower() if m else ""
    return (
        OWN_NAME
        if OWN and host == OWN
        else COS_NAME
        if COS and host == COS
        else "Gitee"
        if "gitee" in host
        else "GitHub"
        if "github" in host
        else "网上"
    )


def manifest_urls():
    out = []
    if OWN:
        out.append((OWN_NAME, f"https://{OWN}/latest.json"))
    if COS:
        out.append((COS_NAME, f"https://{COS}/latest.json"))
    if GITEE:
        out.append(("Gitee", f"https://gitee.com/{GITEE}/raw/master/latest.json"))
    if GITHUB:
        out.append(
            ("GitHub", f"https://raw.githubusercontent.com/{GITHUB}/main/latest.json")
        )
    return out


def enabled():
    return bool(manifest_urls())


def _host_ok(url):
    m = re.match(r"^https://([^/:]+)/", url or "")
    return bool(m) and m.group(1).lower() in HOSTS


def _open(url, timeout):
    """打开网址（测试里换掉）。只认 https 和上面几个网站"""
    import urllib.request

    if not _host_ok(url):
        raise ValueError("下载地址不在允许范围内")
    req = urllib.request.Request(url, headers={"User-Agent": "AT-update"})
    return urllib.request.urlopen(req, timeout=timeout)


class NoPackage(ValueError):
    """这份版本说明里没有这种版本能用的包（压缩包版停止维护后只发安装版）：当作没有新版本，不算出错"""


def parse(raw, frozen=None):
    """读版本说明；格式不对抛 ValueError。frozen：独立安装版（默认看现在是不是），只认 installer 那一项。
    源码版读到只有安装程序、顶层没有 file 的版本说明：抛 NoPackage（没有新版本，不报错）"""
    from .upgrade import ver

    frozen = paths.FROZEN if frozen is None else frozen
    d = json.loads(raw)
    v = str(d.get("version") or "")
    if ver(v) == (0, 0, 0):
        raise ValueError("版本号格式错误")
    if not frozen and "file" not in d and isinstance(d.get("installer"), dict):
        raise NoPackage("这个版本只发安装版，源码版不再在线更新")
    pkg, pattern = (d.get("installer"), SETUP) if frozen else (d, NAME)
    if not isinstance(pkg, dict):
        raise ValueError("这个版本没有独立安装程序")
    name, sha = str(pkg.get("file") or ""), str(pkg.get("sha256") or "").lower()
    if not pattern.match(name) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("安装包信息不完整")
    urls = [u for u in pkg.get("urls") or [] if isinstance(u, str) and _host_ok(u)]
    if not urls:
        raise ValueError("没有可用的下载地址")
    size = int(pkg.get("size") or 0)
    notes = [str(x) for x in (d.get("notes") or []) if str(x).strip()][:8]
    return {
        "version": ".".join(map(str, ver(v))),
        "date": str(d.get("date") or ""),
        "notes": notes,
        "file": name,
        "size": size,
        "sha256": sha,
        "urls": urls,
        "installer": bool(frozen),
    }


# ---------------------------------------------------------------- 远程关功能（2026-10-27，借鉴精英危险 EDMC 的 killswitch）
# latest.json 里加（改了 disabled 要把 kill_rev 改大，比如写当前时间戳；几处清单取 kill_rev 最大的那份）：
#   "kill_rev": 1793000000, "disabled": [{"feature": "nav_marker", "versions": "<=1.0.4", "why": "记号位置不对，修好前先关掉"}]
# feature：nav_marker 导航记号 / radar 雷达信号 / scan 扫描面板 / item F8 物品识别 / halo_auto 小行星带自动核对 /
#          game_events 读游戏日志事件；versions：空或 * = 所有版本，「1.0.4」只这一版，「<=1.0.4」「>=1.0.2」「1.0.2-1.0.4」
# 游戏一更新某个读屏坏了、会给玩家报错的数时，不用发新版就能先关掉。读到的存在 userdata/killswitch.json，离线启动也照样关
FEATURES = {
    "feedback": "问题反馈自动发送",
    "train": "帮助改进识别",
    "nav_marker": "导航记号",
    "radar": "雷达信号识别",
    "scan": "扫描面板识别",
    "item": "物品识别",
    "halo_auto": "小行星带自动核对",
    "game_events": "读游戏日志事件",
}
KILL_FILE = USER / "killswitch.json"
KILL_EVERY = 3600  # 一小时再读一次（版本检查本身 6 小时）
_kill = {
    "list": None,
    "at": 0.0,
    "key": None,
}  # key = (kill_rev, 版本)：比已经用上的旧的清单不改（Codex 2026-10-27）


def _in_range(spec, v):
    from .upgrade import ver

    spec = str(spec or "").strip()
    if spec in ("", "*"):
        return True
    m = re.fullmatch(r"(\d+\.\d+\.\d+)\s*-\s*(\d+\.\d+\.\d+)", spec)
    if m:
        return ver(m.group(1)) <= v <= ver(m.group(2))
    m = re.fullmatch(r"(<=|>=|<|>|=)?\s*(\d+\.\d+\.\d+)", spec)
    if not m:
        return False  # 写错了：不关（宁可不关，也不误关）
    op, x = m.group(1) or "=", ver(m.group(2))
    return {"<=": v <= x, ">=": v >= x, "<": v < x, ">": v > x, "=": v == x}[op]


def _load_kill():
    """userdata/killswitch.json → _kill（旧格式只存了列表：当成最旧的）"""
    if _kill["list"] is not None:
        return
    try:
        d = json.loads(KILL_FILE.read_text(encoding="utf-8"))
    except Exception:
        d = []
    if isinstance(d, dict):
        try:
            key = (
                _rev(d.get("rev")),
                tuple(int(x) for x in d.get("ver") or (0, 0, 0))[:3],
            )
        except (TypeError, ValueError):
            key = (0, (0, 0, 0))
        _kill.update(
            list=d.get("list") if isinstance(d.get("list"), list) else [], key=key
        )
    else:
        _kill.update(list=d if isinstance(d, list) else [], key=(0, (0, 0, 0)))


def _set_kill(raw_list, key=(0, (0, 0, 0))):
    """用上这份关功能列表；key 比已经用上的小（旧镜像）就不改，返回 False"""
    _load_kill()
    if _kill.get("key") is not None and key < _kill["key"]:
        return False
    rows = []
    for r in raw_list if isinstance(raw_list, list) else []:
        if isinstance(r, dict) and r.get("feature") in FEATURES:
            rows.append(
                {
                    "feature": r["feature"],
                    "versions": str(r.get("versions") or ""),
                    "why": str(r.get("why") or "")[:80],
                }
            )
    _kill.update(list=rows, key=key)
    try:
        # 先写临时文件再换名：写到一半被结束会留下半个文件，读不出来就当没关、离线时被关的功能又开了（S5 审查 2026-10-31）
        paths.write_json(KILL_FILE, {"rev": key[0], "ver": list(key[1]), "list": rows})
    except OSError:
        pass
    return True


def disabled(feature):
    """这个功能被远程关了没有：关了返回原因（没写原因就是「暂时关闭」），没关返回 None"""
    from .upgrade import current

    _load_kill()
    v = current()
    for r in _kill["list"] or []:
        if r.get("feature") == feature and _in_range(r.get("versions"), v):
            return r.get("why") or "暂时关闭"
    return None


def _fetch_all(sources, timeout, limit=64 * 1024):
    """几处同时读（2026-10-27：自己服务器、Gitee、GitHub 一起问，不用一个个等超时）。
    返回 [(哪里, 读到的字节 或 出错的异常)]，顺序和 sources 一样"""
    from concurrent.futures import ThreadPoolExecutor, wait

    def one(url):
        with _open(url, timeout) as r:
            return r.read(limit)

    if not sources:
        return []
    ex = ThreadPoolExecutor(max_workers=len(sources))
    futs = [(w, ex.submit(one, u)) for w, u in sources]
    wait([f for _, f in futs], timeout=timeout * 2 + 1)
    ex.shutdown(wait=False)  # 卡住的那个不等它
    out = []
    for w, f in futs:
        if not f.done():
            out.append((w, TimeoutError("超时")))
            continue
        try:
            out.append((w, f.result()))
        except Exception as e:
            out.append((w, e))
    return out


def _rev(v):
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return 0


def fetch(timeout=TIMEOUT):
    """到网上读版本说明。几处都问，取版本最新的一份（Codex 2026-10-27：一处的清单旧了不能挡住别处的新版本）。
    返回 (info, 哪里读到的)；都读不到返回 (None, 原因)。
    顺便更新远程关功能的列表：取 kill_rev 最大（同样大取版本新）的那份清单里的 disabled"""
    from .upgrade import ver

    errs, best, kill, nopkg = [], None, None, False
    for where, raw in _fetch_all(manifest_urls(), timeout):
        if isinstance(raw, Exception):
            errs.append(f"{where}：{raw}")
            continue
        try:  # 是像样的版本说明才算关功能列表；错误页面、格式不对就不用（Codex 2026-10-27）
            d = json.loads(raw)
            v = ver(str(d.get("version") or "")) if isinstance(d, dict) else (0, 0, 0)
            if v != (0, 0, 0) and isinstance(d.get("disabled", []), list):
                key = (_rev(d.get("kill_rev")), v)
                if kill is None or key > kill[0]:
                    kill = (key, d.get("disabled", []))
        except Exception:
            pass
        try:
            info = parse(raw)
            info["source"] = where
            if best is None or ver(info["version"]) > ver(best["version"]):
                best = info
        except NoPackage:
            nopkg = True
        except Exception as e:
            errs.append(f"{where}：{e}")
    if kill is not None:
        _set_kill(kill[1], kill[0])
        _kill["at"] = time.time()
    if best:
        return best, best["source"]
    if nopkg:  # 读到了，只是没有这种版本的包：没有新版本，不是连不上
        return None, ""
    return None, "；".join(errs) or "未设置更新地址"


def check(force=False):
    """有没有比现在新的在线版本：有就返回 info，没有或没联网返回 None。6 小时内不重复查（force 除外）"""
    from .upgrade import ver, current

    if not enabled():
        return None
    st = _state
    with st["lock"]:
        if (
            force
            or time.time() - st["at"] > EVERY
            or time.time() - _kill["at"] > KILL_EVERY
        ):
            info, err = fetch()
            st.update(at=time.time(), info=info, error="" if info else err)
        info = st["info"]
    if not info:
        return None
    new, cur = ver(info["version"]), current()
    # 本机装的是 beta（如 1.1.2-beta.1）：同号的 live（1.1.2）也算新版本（2026-10-30 版本分 beta / live）
    return info if new > cur or (new == cur and _is_beta()) else None


def refresh_kill():
    """只更新远程关功能清单，不管新版本：玩家关了「启动时检查更新」也照常查（控制台指令第 2 批选 A，2026-10-31：
    远程关是游戏更新后防止给出错误识别结果的兜底）。一小时最多联网一次；读不到就继续用本地存的清单"""
    if not enabled():
        return
    with _state["lock"]:
        if time.time() - _kill["at"] > KILL_EVERY:
            fetch()


def _is_beta():
    from ..core.version import VERSION

    return "-" in VERSION


def last_error():
    return _state["error"]


def download(info, progress=print):
    """下载安装包到 userdata/updates，核对大小和 SHA-256。返回文件路径；失败抛 ValueError"""
    from .upgrade import MAX_BYTES

    limit = SETUP_MAX if SETUP.match(info["file"]) else MAX_BYTES
    UPDATES.mkdir(parents=True, exist_ok=True)
    dest = UPDATES / info["file"]
    if dest.exists() and _sha256(dest) == info["sha256"]:
        progress(f"安装包已下载：{info['file']}")
        return dest
    part = dest.with_suffix(".part")
    errs = []
    for url in info["urls"]:
        try:
            progress(f"正在下载 AT {info['version']}（{_where(url)}）…")
            h, n, shown = hashlib.sha256(), 0, 0
            with _open(url, 15) as r, open(part, "wb") as f:
                total = int(r.headers.get("Content-Length") or info.get("size") or 0)
                while True:
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    n += len(chunk)
                    if n > limit:
                        raise ValueError("文件大小异常")
                    h.update(chunk)
                    f.write(chunk)
                    if total and n * 20 // total > shown:
                        shown = n * 20 // total
                        progress(
                            f"已下载 {shown * 5}%（{n / 2**20:.1f} / {total / 2**20:.1f} MB）"
                        )
            if info.get("size") and n != info["size"]:
                raise ValueError("文件大小不符，下载不完整")
            if h.hexdigest() != info["sha256"]:
                raise ValueError("文件校验不符，可能下载损坏")
            part.replace(dest)
            for old in [
                *UPDATES.glob("Dubhe_*.zip"),
                *UPDATES.glob("AT_Setup_*.exe"),
            ]:  # 只留这一个
                if old != dest:
                    old.unlink(missing_ok=True)
            progress("下载完成，校验通过")
            return dest
        except Exception as e:
            errs.append(f"{_where(url)}：{e}")
            progress(f"{_where(url)} 下载失败：{e}")
        finally:
            if part.exists():
                part.unlink(missing_ok=True)
    raise ValueError(
        "下载失败。" + "；".join(errs) + "。检查网络后重试，或到发布页手动下载"
    )


def launch_installer(path):
    """独立安装版升级：等 AT 退出（约 3 秒）后静默运行安装程序；装完安装程序会自动重新打开 AT。
    安装日志写到 userdata/logs/install.log。返回后调用方要马上让 AT 退出（文件被占用会装不上）"""
    import subprocess

    path = Path(path)
    if not SETUP.match(path.name) or not path.exists():
        raise ValueError("安装程序不存在")
    log = USER / "logs" / "install.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = (
        f'cmd /c "ping -n 4 127.0.0.1 >nul & "{path}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART '
        f'/CLOSEAPPLICATIONS /LOG="{log}""'
    )
    flags = (
        0x00000008 | 0x00000200 | 0x08000000
    )  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    subprocess.Popen(cmd, creationflags=flags, close_fds=True)


def _where(url):
    return where(url)


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _entry(p, tag):
    urls = release_urls(tag, p.name)
    return {
        "file": p.name,
        "size": p.stat().st_size,
        "sha256": _sha256(p),
        "urls": urls,
    }


def make_manifest(zip_path, notes=(), date="", installer=None, keep=None):
    """发版本时用：按安装包生成 latest.json 的内容（tools/make_manifest.py 调这个）。
    zip_path：Dubhe_x.y.z.zip；压缩包版停止维护后可以给 None，只发安装程序：这时顶层不写 file / size / sha256 / urls，
    版本号取安装程序文件名，源码版读到会当作没有新版本（不会出现版本是新号、file 却指向旧压缩包）。
    installer：同一版本的独立安装程序 AT_Setup_x.y.z.exe（有压缩包时可选，没压缩包时必须给）。
    keep：网上现在的 latest.json——远程关功能的 kill_rev 和 disabled 原样带上（Codex 2026-10-27：发新版不能把旧版的禁用清掉）"""
    from .upgrade import check as check_pkg, ver

    if zip_path:
        p = Path(zip_path)
        _, v = check_pkg(p)
    elif installer:
        mt = re.match(r"^AT_Setup_(\d+\.\d+\.\d+)\.exe$", Path(installer).name, re.I)
        if not mt:
            raise ValueError("安装程序文件名应为 AT_Setup_x.y.z.exe")
        v = ver(mt.group(1))
    else:
        raise ValueError("压缩包和安装程序至少要给一个")
    ver_s = ".".join(map(str, v))
    tag = f"v{ver_s}"
    m = {
        "version": ver_s,
        "date": date or time.strftime("%Y-%m-%d"),
        "notes": list(notes),
        **(_entry(p, tag) if zip_path else {}),
    }
    if isinstance(keep, dict):
        if "disabled" in keep and not isinstance(keep["disabled"], list):
            raise ValueError(
                "网上 latest.json 的 disabled 不是列表（写成 [ {...} ]），先改好再生成"
            )
        if "kill_rev" in keep:
            m["kill_rev"] = _rev(keep.get("kill_rev"))
        if isinstance(keep.get("disabled"), list):
            m["disabled"] = keep["disabled"]
    if installer:
        ip = Path(installer)
        if not SETUP.match(ip.name) or ip.name != f"AT_Setup_{ver_s}.exe":
            raise ValueError(f"安装程序文件名应为 AT_Setup_{ver_s}.exe")
        m["installer"] = _entry(ip, tag)
    return m
