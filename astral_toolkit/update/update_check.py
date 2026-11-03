"""在线更新（2026-10-25）：启动时到网上读一个很小的版本说明（latest.json），有新版本就提示；玩家点「下载并升级」才下载。

- 先试自己的香港服务器 dl.astral-trade.com，再试国内镜像，再试 GitHub；每个地址最多等 5 秒，都不通就当没有新版本，不报错
- Velopack 安装版只看版本号、日期、更新说明，下载走 Velopack 更新源
- 独立安装版（桥接安装程序）只认 installer：下载 AT_Setup_*.exe，退出 AT 后静默安装，装完自动重新打开；1.1.4 发版后单独删
- 版本说明由 tools/make_manifest.py 在发版本时生成；清单里冻结的 kill_rev / disabled 只给 ≤1.1.1 老客户端看，本代码不读，永不再改

latest.json 的格式：
{"version": "1.7.1", "date": "2026-11-01", "notes": ["更新内容一", "…"],
 "kill_rev": 1793426539, "disabled": [...],
 "installer": {"file": "AT_Setup_1.7.1.exe", "size": …, "sha256": "…", "urls": […]}}
Python 源码压缩包版已退役，不再读顶层 Dubhe_*.zip / file。
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
    "github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
)
UPDATES = USER / "updates"
SETUP = re.compile(r"^AT_Setup_\d+\.\d+\.\d+\.exe$", re.I)
SETUP_MAX = 300 * 2**20  # 安装程序大小上限（防止下到异常大的文件）

_state = {"at": 0.0, "info": None, "error": "", "lock": threading.Lock()}


def release_urls(tag, name):
    """发行版里一个文件的下载地址：自己的服务器、国内镜像、GitHub（按这个顺序试）"""
    out = []
    if OWN:
        out.append(f"https://{OWN}/releases/{tag}/{name}")
    if COS:
        out.append(f"https://{COS}/releases/{tag}/{name}")
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
    """这份版本说明里没有这种版本能用的包：当作没有新版本，不算出错"""


def parse(raw, frozen=None, velopack=None):
    """读版本说明；格式不对抛 ValueError。
    velopack：下载走 Velopack 更新源，这里只取版本号、日期、更新说明，清单带不带安装包都行。
    frozen（独立安装版）：只认 installer。源码压缩包版已退役：不认顶层 file / Dubhe_*.zip，直接当作没有新版本。"""
    from .version import ver

    frozen = paths.FROZEN if frozen is None else frozen
    velopack = paths.VELOPACK if velopack is None else velopack
    d = json.loads(raw)
    v = str(d.get("version") or "")
    if ver(v) == (0, 0, 0):
        raise ValueError("版本号格式错误")
    head = {
        "version": ".".join(map(str, ver(v))),
        "date": str(d.get("date") or ""),
        "notes": [str(x) for x in (d.get("notes") or []) if str(x).strip()][:8],
    }
    if velopack:
        return {**head, "file": "", "size": None, "sha256": "", "urls": []}
    if not frozen:
        raise NoPackage("源码压缩包版已退役，不在线更新")
    pkg = d.get("installer")
    if not isinstance(pkg, dict) or "file" not in pkg:
        raise NoPackage("这个版本没有安装程序，不在线更新")
    name, sha = str(pkg.get("file") or ""), str(pkg.get("sha256") or "").lower()
    if not SETUP.match(name) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("安装包信息不完整")
    urls = [u for u in pkg.get("urls") or [] if isinstance(u, str) and _host_ok(u)]
    if not urls:
        raise ValueError("没有可用的下载地址")
    size = int(pkg.get("size") or 0)
    return {
        **head,
        "file": name,
        "size": size,
        "sha256": sha,
        "urls": urls,
        "installer": True,
    }


def _fetch_all(sources, timeout, limit=64 * 1024):
    """几处同时读（2026-10-27：自己服务器、国内镜像、GitHub 一起问，不用一个个等超时）。
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
    """到网上读版本说明。几处都问，取版本最新的一份。
    返回 (info, 哪里读到的)；都读不到返回 (None, 原因)。"""
    from .version import ver

    errs, best, nopkg = [], None, (0, 0, 0)
    for where, raw in _fetch_all(manifest_urls(), timeout):
        if isinstance(raw, Exception):
            errs.append(f"{where}：{raw}")
            continue
        v = (0, 0, 0)
        try:
            d = json.loads(raw)
            v = ver(str(d.get("version") or "")) if isinstance(d, dict) else (0, 0, 0)
        except Exception:
            pass
        try:
            info = parse(raw)
            info["source"] = where
            if best is None or ver(info["version"]) > ver(best["version"]):
                best = info
        except NoPackage:
            nopkg = max(nopkg, v)
        except Exception as e:
            errs.append(f"{where}：{e}")
    # 最新的那份清单对这种版本没有包（比如源码版、而新清单只写版本号）：就是没有新版本，
    # 不能退回去用别处更旧清单里的旧包（审查 2026-11-03）
    if best and ver(best["version"]) >= nopkg:
        return best, best["source"]
    if best or nopkg != (
        0,
        0,
        0,
    ):  # 读到了，只是没有这种版本的包：没有新版本，不是连不上
        return None, ""
    return None, "；".join(errs) or "未设置更新地址"


def check(force=False):
    """有没有比现在新的在线版本：有就返回 info，没有或没联网返回 None。6 小时内不重复查（force 除外）"""
    from .version import ver, current

    if not enabled():
        return None
    st = _state
    with st["lock"]:
        if force or time.time() - st["at"] > EVERY:
            info, err = fetch()
            st.update(at=time.time(), info=info, error="" if info else err)
        info = st["info"]
    if not info:
        return None
    new, cur = ver(info["version"]), current()
    # 本机装的是 beta（如 1.1.2-beta.1）：同号的 live（1.1.2）也算新版本（2026-10-30 版本分 beta / live）
    return info if new > cur or (new == cur and _is_beta()) else None


def _is_beta():
    from ..core.version import VERSION

    return "-" in VERSION


def last_error():
    return _state["error"]


def download(info, progress=print):
    """下载安装程序到 userdata/updates，核对大小和 SHA-256。返回文件路径；失败抛 ValueError"""
    if not SETUP.match(info["file"]):
        raise ValueError("只支持下载安装程序")
    limit = SETUP_MAX
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
            for old in UPDATES.glob("AT_Setup_*.exe"):  # 只留这一个
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


# 只给 ≤1.1.1 老客户端看；客户端代码不读，永不再改。
LEGACY_KILL_REV = 1793426539
LEGACY_DISABLED = [
    {
        "feature": "feedback",
        "versions": "<=1.1.1",
        "why": "请升级到 1.1.2（已删除全部模拟按键）",
    },
    {
        "feature": "train",
        "versions": "<=1.1.1",
        "why": "请升级到 1.1.2（已删除全部模拟按键）",
    },
    {
        "feature": "nav_marker",
        "versions": "<=1.1.1",
        "why": "请升级到 1.1.2（已删除全部模拟按键）",
    },
    {
        "feature": "radar",
        "versions": "<=1.1.1",
        "why": "请升级到 1.1.2（已删除全部模拟按键）",
    },
    {
        "feature": "scan",
        "versions": "<=1.1.1",
        "why": "请升级到 1.1.2（已删除全部模拟按键）",
    },
    {
        "feature": "item",
        "versions": "<=1.1.1",
        "why": "请升级到 1.1.2（已删除全部模拟按键）",
    },
    {
        "feature": "halo_auto",
        "versions": "<=1.1.1",
        "why": "请升级到 1.1.2（已删除全部模拟按键）",
    },
    {
        "feature": "game_events",
        "versions": "<=1.1.1",
        "why": "请升级到 1.1.2（已删除全部模拟按键）",
    },
]


def make_manifest(notes=(), date="", installer=None, version=None):
    """发版本时用：生成 latest.json 的内容（tools/make_manifest.py 调这个）。
    installer：同一版本的独立安装程序 AT_Setup_x.y.z.exe（可选）。
    version：只发 Velopack 版时用；installer 和 version 都不给就报错。
    顶层不再写 file / size / sha256 / urls；kill_rev / disabled 写冻结常量，只给老客户端看。"""
    from .version import ver

    want = None
    if version:
        want = ver(str(version))
        if want == (0, 0, 0):
            raise ValueError("版本号格式错误，应为 x.y.z")
    if installer:
        ip = Path(installer)
        mt = re.match(r"^AT_Setup_(\d+\.\d+\.\d+)\.exe$", ip.name, re.I)
        if not mt:
            raise ValueError("安装程序文件名应为 AT_Setup_x.y.z.exe")
        v = ver(mt.group(1))
    elif want:
        v = want
    else:
        raise ValueError("安装程序、版本号至少要给一个")
    if want and want != v:
        raise ValueError(
            f"--version {'.'.join(map(str, want))} 和安装程序的版本 {'.'.join(map(str, v))} 不一致"
        )
    ver_s = ".".join(map(str, v))
    tag = f"v{ver_s}"
    m = {
        "version": ver_s,
        "date": date or time.strftime("%Y-%m-%d"),
        "notes": list(notes),
        "kill_rev": LEGACY_KILL_REV,
        "disabled": [dict(r) for r in LEGACY_DISABLED],
    }
    if installer:
        ip = Path(installer)
        if ip.name != f"AT_Setup_{ver_s}.exe":
            raise ValueError(f"安装程序文件名应为 AT_Setup_{ver_s}.exe")
        m["installer"] = _entry(ip, tag)
    return m
