"""旧版天枢（压缩包版 Dubhe）→ 安装版 AT 的过渡（1.0.1，2026-10-26 用户要求）

老玩家装了 AT 安装版后，电脑上还留着解压的旧版天枢：
- 旧版的设置、路标、目标不会自己过来 → 第一次打开 AT 时找旧版，问要不要导入（只复制，旧版那边不动）
- 旧版和 AT 同时开着，热键互相抢 → AT 发现旧版在运行，提示并可以一键关掉旧版（调它自己的退出接口）

只在常见位置找（下载、桌面、文档、用户目录、各盘根目录），往下最多 3 层，限时 3 秒。
认旧版的标志：文件夹里有 Dubhe.exe、sc_mining\\version.py、userdata\\settings.json
"""
import json
import os
import re
import shutil
import string
import time
from pathlib import Path

from ..core import paths

# 要导入的东西：设置（同意免责声明那一项不带）、路标、目标、原矿记录、悬浮窗位置、地点记录、问题反馈
FILES = ("settings.json", "waypoints.json", "goals.json", "ore_log.json", "observations.csv", "overlay_pos.json",
         "location_ids.json", "last_position.json", "showloc_method.txt", "showlocation_method.txt")
DIRS = ("feedback",)
KEEP_NEW = ("agreed",)          # 这些设置保留 AT 自己的（免责声明要在新版里重新同意）
SKIP_DIRS = {"windows", "program files", "program files (x86)", "programdata", "$recycle.bin", "appdata",
             "system volume information", "node_modules", ".venv", "_internal", "steam", "steamapps"}


def _roots():
    home = Path.home()
    out = [(home / "Downloads", 3), (home / "Desktop", 3), (home / "Documents", 3), (home, 1)]
    if os.name == "nt":
        for d in string.ascii_uppercase:
            p = Path(f"{d}:\\")
            if d != "C" and p.exists():
                out.append((p, 2))
    return out


def _is_old(d):
    has_ver = (d / "sc_mining" / "core" / "version.py").is_file() or (d / "sc_mining" / "version.py").is_file()
    return (d / "Dubhe.exe").is_file() and has_ver and (d / "userdata" / "settings.json").is_file()


def _version(d):
    for f in (d / "sc_mining" / "core" / "version.py", d / "sc_mining" / "version.py"):
        if f.is_file():
            try:
                m = re.search(r'VERSION\s*=\s*"([^"]+)"', f.read_text(encoding="utf-8"))
                return m.group(1) if m else ""
            except OSError:
                return ""
    return ""


def _count(p):
    try:
        v = json.loads(p.read_text(encoding="utf-8-sig"))
        return len(v) if isinstance(v, (list, dict)) else 0
    except Exception:
        return 0


def find(limit_s=3.0, roots=None):
    """找电脑上的旧版天枢。返回 [{path, version, waypoints, goals, used}]，最近用过的排前面"""
    me = paths.ROOT.resolve()
    end = time.time() + limit_s
    seen, out = set(), []

    def walk(d, depth):
        if time.time() > end or d in seen:
            return
        seen.add(d)
        if _is_old(d):
            if d.resolve() != me:
                out.append(d)
            return
        if depth <= 0:
            return
        try:
            subs = [e for e in os.scandir(d) if e.is_dir(follow_symlinks=False)]
        except OSError:
            return
        for e in subs:
            if e.name.lower() not in SKIP_DIRS and not e.name.startswith("."):
                walk(Path(e.path), depth - 1)

    for root, depth in (roots if roots is not None else _roots()):
        if root.exists():
            walk(root, depth)
    rows = []
    for d in out:
        u = d / "userdata"
        used = max((p.stat().st_mtime for p in u.iterdir() if p.is_file()), default=0)
        rows.append({"path": str(d), "version": _version(d), "waypoints": _count(u / "waypoints.json"),
                     "goals": _count(u / "goals.json"), "used": time.strftime("%Y-%m-%d %H:%M", time.localtime(used)),
                     "_t": used})
    rows.sort(key=lambda r: r["_t"], reverse=True)
    for r in rows:
        r.pop("_t")
    return rows


def import_from(path):
    """把旧版的设置和记录复制到 AT。先把 AT 现有的同名文件备份到 userdata\\import_backup_<时间>。返回导入了哪些"""
    src = Path(path) / "userdata"
    if not _is_old(Path(path)):
        raise ValueError("这个文件夹不是旧版天枢")
    dst = paths.USER
    dst.mkdir(parents=True, exist_ok=True)
    bak = dst / f"import_backup_{time.strftime('%Y%m%d_%H%M%S')}"
    done = []
    for name in FILES:
        s = src / name
        if not s.is_file():
            continue
        d = dst / name
        if d.exists():
            bak.mkdir(exist_ok=True)
            shutil.copy2(d, bak / name)
        if name == "settings.json":
            from ..core import settings
            old = json.loads(s.read_text(encoding="utf-8-sig"))      # 手改过的文件可能带 BOM（记事本另存）
            with settings._LOCK:                                      # AT 开着，别的线程也在改设置：读-改-写连着做，写原子的（S5 审查 2026-10-31）
                try:
                    cur = json.loads(d.read_text(encoding="utf-8-sig")) if d.exists() else {}
                except Exception:
                    cur = {}
                for k in KEEP_NEW:
                    if k in cur:
                        old[k] = cur[k]
                    else:
                        old.pop(k, None)
                paths.write_json(d, old, indent=1)
        elif s.suffix in (".json", ".txt", ".csv"):
            d.write_text(s.read_text(encoding="utf-8-sig"), encoding="utf-8")   # 去掉 BOM，AT 按 UTF-8 读
        else:
            shutil.copy2(s, d)
        done.append(name)
    for name in DIRS:
        s = src / name
        if s.is_dir():
            shutil.copytree(s, dst / name, dirs_exist_ok=True)
            done.append(name)
    return done


def window_url(path):
    """旧版正在运行时它写的窗口地址（不一定还活着）"""
    try:
        return (Path(path) / "userdata" / "window_url.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _call(url, name, timeout=2.0):
    import urllib.request
    m = re.match(r"^(http://127\.0\.0\.1:\d+)/.*[#?&]t=([\w-]+)", url or "")
    if not m:
        raise ValueError("地址不对")
    req = urllib.request.Request(f"{m.group(1)}/api/{name}", data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json", "X-Token": m.group(2)})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8"))


def running(rows):
    """哪些旧版正开着：它的本机接口能应答就算开着"""
    out = []
    for r in rows:
        try:
            if _call(window_url(r["path"]), "status").get("ok"):
                out.append(r)
        except Exception:
            pass
    return out


def quit_old(path):
    """请正在运行的旧版自己退出（和再双击一次旧版时用的是同一个接口）"""
    _call(window_url(path), "quit")
    return True
