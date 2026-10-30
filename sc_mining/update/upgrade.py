"""一键升级：找到下载好的新版安装包（Dubhe_x.y.z.zip），覆盖程序文件，重启

以前升级要：退出 AT → 解压 → 选「替换所有文件」→ 再打开，太麻烦。现在：
- 自动在「下载」「桌面」、微信和 QQ 收到的文件里找比现在新的 Dubhe_*.zip
- 也可以在窗口里手动选一个安装包
- 只换程序文件；你的设置、路标、配置、目标（userdata）和 Python 环境（.venv）都不动
- 新版本加了新组件（requirements.txt 变了）会先装好再重启
- 升级前自动把当前版本备份到 userdata/backups（只留上一个版本）；新版本出问题可以一键回滚
- 测试通过的版本可以「存为稳定版」放到 userdata/stable，永远不自动删
"""
import os
import re
import shutil
import time
import zipfile
from pathlib import Path

from ..core.paths import ROOT, USER
from ..core.version import VERSION

NAME = re.compile(r"^Dubhe_(\d+)\.(\d+)\.(\d+)\.zip$", re.I)
KEEP = ("userdata/", ".venv/", "tools/", "dist/", "tests/")       # 这些不动
MAX_BYTES = 80 * 2 ** 20
STAMP = USER / "upgraded.json"
BACKUPS = USER / "backups"          # 升级前自动备份的旧版本
STABLE = USER / "stable"            # 手动标记的稳定版
KEEP_BACKUPS = 1                    # 只留上一个版本（用户 2026-10-23）
TOP_FILES = ("Dubhe.exe", "首次安装.bat", "免责声明.txt", "使用说明.txt", "第三方许可.txt", "LICENSE", "requirements.txt", "README.md")
SKIP_DATA = {"scmdb", "loc", "unpack"}        # 原始大文件，更新数据时会重新下载
SKIP_DATA_FILES = {"loot_details.zip"}   # 掉落明细整包（约 25 MB，数据包里下载；升级不动它，备份也不带）
PROGRAM_EXT = (".py", ".js", ".css", ".html")   # 这些算程序文件：装完必须和安装包一字不差（老大审查 2026-10-28 第 3 条）
REQUIRED = ("sc_mining/__init__.py", "sc_mining/run.py",
            "sc_mining/app/server.py")      # 少一个 AT 就起不来：装包前后都要有（2026-10-30 重构阶段 4 删了 app/services.py，从这里去掉）


def _is_program(rel):
    return rel.rsplit("/", 1)[-1].rsplit(".", 1)[-1].lower() in tuple(e[1:] for e in PROGRAM_EXT)


def verify(path, top):
    """装完对账：安装包里每个程序文件，AT 文件夹里都得有、CRC 都得一样。返回没对上的 [相对路径]（空 = 完整）"""
    import zlib
    bad = []
    with zipfile.ZipFile(path) as z:
        wanted = {}
        for info in z.infolist():                 # 同名条目出现两次：以最后一个为准（装的时候也是后写的覆盖前面的）
            rel = info.filename[len(top) + 1:]
            if not rel or info.is_dir() or rel.startswith(KEEP) or not _is_program(rel):
                continue
            wanted[rel] = info
        for rel, info in wanted.items():
            dest = ROOT / rel
            try:
                crc = 0
                with open(dest, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        crc = zlib.crc32(chunk, crc)
                if crc != info.CRC:
                    bad.append(rel)
            except OSError:
                bad.append(rel)
    return bad


def ver(text):
    m = re.match(r"^\s*(\d+)\.(\d+)\.(\d+)", str(text or ""))
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def current():
    return ver(VERSION)


def _search_dirs():
    """可能放着下载好的安装包的地方：（文件夹, 中文名, 往下找几层）"""
    home = Path.home()
    out = [(USER / "updates", "在线下载", 0),           # 在线更新下载的（update_check.py）
           (home / "Downloads", "下载", 1), (home / "Desktop", "桌面", 1), (ROOT.parent, "AT 所在的文件夹", 0)]
    docs = home / "Documents"
    out += [(p / "FileStorage" / "File", "微信收到的文件", 2) for p in docs.glob("WeChat Files/*")]
    out += [(p, "微信收到的文件", 3) for p in docs.glob("xwechat_files/*")]
    out += [(p / "FileRecv", "QQ 收到的文件", 1) for p in docs.glob("Tencent Files/*")]
    return out


def _walk(folder, depth):
    try:
        for p in folder.iterdir():
            if p.is_file() and NAME.match(p.name):
                yield p
            elif p.is_dir() and depth > 0:
                yield from _walk(p, depth - 1)
    except OSError:
        return


def find_packages():
    """比现在新的安装包，最新的排前面：[{path, version, where, at}]。独立安装版不用 Dubhe_*.zip，不找"""
    from ..core.paths import FROZEN
    if FROZEN:
        return []
    seen, out = set(), []
    for folder, where, depth in _search_dirs():
        if not folder.exists():
            continue
        for p in _walk(folder, depth):
            v = ver(NAME.match(p.name).group(1) + "." + NAME.match(p.name).group(2) + "." + NAME.match(p.name).group(3))
            if v <= current() or p in seen:
                continue
            seen.add(p)
            out.append({"path": str(p), "version": ".".join(map(str, v)), "where": where,
                        "at": time.strftime("%m-%d %H:%M", time.localtime(p.stat().st_mtime))})
    out.sort(key=lambda x: (ver(x["version"]), x["at"]), reverse=True)
    return out


def check(path):
    """检查安装包：是 AT 的包、没有危险路径、读出版本号。返回 (顶层文件夹名, 版本)，不对就抛 ValueError"""
    path = Path(path)
    if not path.exists() or path.stat().st_size > MAX_BYTES:
        raise ValueError("未找到此安装包，或文件大小异常")
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ValueError("此文件不是完整的压缩包（可能未下载完成）")
    with z:
        names = z.namelist()
        tops = {n.split("/", 1)[0] for n in names if n.strip("/")}
        if len(tops) != 1:
            raise ValueError("压缩包结构异常，不是 AT 安装包")
        top = tops.pop()
        for n in names:
            if n.startswith("/") or ".." in n.split("/") or ":" in n:
                raise ValueError("压缩包含可疑的文件路径，已停止安装")
        ver_candidates = (f"{top}/sc_mining/core/version.py", f"{top}/sc_mining/version.py")
        ver_file = next((f for f in ver_candidates if f in names), None)
        if not ver_file:
            raise ValueError("压缩包中缺少版本文件（sc_mining/core/version.py），不是完整的 AT 安装包")
        miss = [r for r in REQUIRED if f"{top}/{r}" not in names]
        if miss:
            raise ValueError(f"压缩包中缺少 AT 程序文件（{'、'.join(miss)}），不是完整的 AT 安装包")
        if z.testzip() is not None:
            raise ValueError("压缩包已损坏（可能未下载完成），需重新下载")
        v = (0, 0, 0)
        m = re.search(r'VERSION\s*=\s*"([^"]+)"', z.read(ver_file).decode("utf-8", "replace"))
        v = ver(m.group(1)) if m else v
        if v == (0, 0, 0):
            v = ver(NAME.match(path.name).group(0)[6:] if NAME.match(path.name) else "")
        return top, v


def apply(path, progress=print):
    """装上这个安装包（覆盖程序文件，升级、回滚都用它）。返回 {"from", "to", "deps"}；deps=True 表示装了新组件
    先把要装的包复制一份再装：回滚到最早那份自动备份时，备份清理会删掉它（Codex 复审 2026-10-23）"""
    import tempfile
    top, v = check(path)
    progress(f"安装包没问题：AT {'.'.join(map(str, v))}（现在是 {VERSION}）")
    work = Path(tempfile.mkdtemp(prefix="dubhe_install_"))
    try:
        src = work / Path(path).name
        shutil.copy2(path, src)
        try:
            same = BACKUPS / f"Dubhe_{VERSION}.zip"
            if v == current() and same.exists() and Path(path).resolve() != same.resolve():
                check(same)                        # 重新安装同版本：已有一份好备份就别再打包覆盖它（现在的目录可能是坏的，十二审 2026-10-28）
                b = same
            elif v == current() and Path(path).resolve() == same.resolve():
                b = src                            # 装的就是那份备份：用临时副本当回退包，别覆盖它
            else:
                b = backup_current()
                check(b)                           # 备份本身也要是能装回来的完整包
        except Exception as e:
            raise ValueError(f"备份现在的版本没成功（{e}），为了能回滚，这次没有改动任何程序文件。"
                             f"检查一下磁盘空间，或者把 AT 文件夹的只读属性去掉再试")
        progress(f"已备份现在的版本（{VERSION}），出问题可以在设置里回滚：{b.name}")
        try:
            return _install(src, top, v, progress)
        except Exception as e:                     # 装到一半出错：马上把备份装回去，别留下一半新一半旧（十审 2026-10-28）
            progress(f"升级失败（{e}），正在装回原来的版本…")
            try:
                btop, bv = check(b)
                _install(b, btop, bv, progress, restoring=True)
                progress("已装回原来的版本")
            except Exception as e2:
                raise ValueError(f"升级失败（{e}），装回原版本也失败（{e2}）：在设置页回滚列表里点「重新安装 {VERSION}」")
            raise ValueError(f"升级失败，已装回原来的版本：{e}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _install(path, top, v, progress, restoring=False):
    old_req = (ROOT / "requirements.txt").read_text(encoding="utf-8") if (ROOT / "requirements.txt").exists() else ""
    new_files = set()
    skipped = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            rel = info.filename[len(top) + 1:]
            if not rel or info.is_dir() or rel.startswith(KEEP):
                continue
            new_files.add(rel)
            dest = ROOT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".new")
            with z.open(info) as src, open(tmp, "wb") as out:
                shutil.copyfileobj(src, out)
            try:
                for i in range(6):                # 被别的线程读着时换名会失败：稍等再试（和 data_pack 一样，十审 2026-10-28）
                    try:
                        os.replace(tmp, dest)     # 一次换上，换到一半出错也不会留下半个文件
                        break
                    except PermissionError:
                        if i == 5:
                            raise
                        time.sleep(0.05)
            except OSError:                       # 正在用的文件（比如 Dubhe.exe 正开着）：跳过，下次再换
                skipped.append(rel)
                try:
                    tmp.unlink()
                except OSError:
                    pass
    progress(f"已更新 {len(new_files) - len(skipped)} 个程序文件" + (f"（{len(skipped)} 个正在用，跳过：{'、'.join(skipped[:3])}）" if skipped else ""))
    bad = verify(path, top)                       # 逐个对账（CRC）：程序文件没换上、换错了都算没装成，装回备份时也一样（老大审查 2026-10-28 第 3 条）
    if bad:                                       # 数据 json 换不上留旧的无害，verify 只看程序文件
        what = "装回" if restoring else "升级"
        raise RuntimeError(f"{len(bad)} 个程序文件没换上（{'、'.join(bad[:5])}{'…' if len(bad) > 5 else ''}），{what}未完成")
    if "data/data_pack.json" not in new_files:      # 包里的数据没带版本标记（旧包）：本地标记和刚装上的数据对不上，删掉，下次更新重新下（二十一审）
        try:
            (ROOT / "data" / "data_pack.json").unlink(missing_ok=True)
        except OSError:
            pass
    # 旧版本有、新版本删掉的程序文件：删掉，免得旧代码捣乱（只动 sc_mining 里的程序文件）
    removed = 0
    for p in (ROOT / "sc_mining").rglob("*"):
        rel = p.relative_to(ROOT).as_posix()
        if p.is_file() and "__pycache__" not in rel and p.suffix in (".py", ".js", ".css", ".html") and rel not in new_files:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    if removed:
        progress(f"删掉了 {removed} 个新版本不再用的旧文件")
    # 清掉编译缓存：新旧文件大小一样、又在同一秒里写的话，Python 可能还用旧的缓存（回滚演练时真碰到过）
    for d in (ROOT / "sc_mining").rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)
    deps = (ROOT / "requirements.txt").exists() and (ROOT / "requirements.txt").read_text(encoding="utf-8") != old_req
    if deps and not restoring:                    # 装回备份时不跑 pip：旧环境本来就能跑（十一审 2026-10-28）
        progress("新版本需要新的组件，正在安装（会自动选最快的下载源）…")
        from ..run import _pip, _has_directml, use_directml
        had_dml = _has_directml()                 # 原来装的是显卡版识别组件：-r 装依赖时可能把 CPU 版 onnxruntime 装回来盖掉它
        if _pip("-r", str(ROOT / "requirements.txt")) is False:
            raise RuntimeError("新版本需要的组件没装上，升级未完成")
        if had_dml:
            use_directml()                        # 装不上显卡版也不算升级失败：留着 CPU 版照样能识别
    if not restoring:                             # 装回备份不算「已升级」，别让窗口弹「已升级到 x」
        try:
            import json
            STAMP.write_text(json.dumps({"from": VERSION, "to": ".".join(map(str, v)), "at": time.time()}), encoding="utf-8")
        except OSError:
            pass
    return {"from": VERSION, "to": ".".join(map(str, v)), "deps": deps}


def backup_current(dest_dir=None):
    """把现在正在用的这个版本打成和安装包一样的压缩包（Dubhe_<版本>.zip），升级前调用，出问题能装回来"""
    dest_dir = Path(dest_dir or BACKUPS)
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = f"Dubhe_{VERSION}"
    out = dest_dir / f"{name}.zip"
    tmp = out.with_name(out.name + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in TOP_FILES:
            p = ROOT / f
            if p.exists():
                z.write(p, f"{name}/{f}")
        for base in ("sc_mining", "data"):
            for dirpath, dirs, files in os.walk(ROOT / base):
                rel = Path(dirpath).relative_to(ROOT)
                dirs[:] = [d for d in dirs if d != "__pycache__" and not (rel == Path("data") and d in SKIP_DATA)]
                for f in files:
                    if not f.endswith(".pyc") and not (rel == Path("data") and f in SKIP_DATA_FILES):
                        p = Path(dirpath) / f
                        z.write(p, f"{name}/{p.relative_to(ROOT).as_posix()}")
    os.replace(tmp, out)
    if dest_dir == BACKUPS:                           # 自动备份只留最近几个
        olds = sorted(BACKUPS.glob("Dubhe_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in olds[KEEP_BACKUPS:]:
            try:
                p.unlink()
            except OSError:
                pass
    return out


def mark_stable():
    """把现在这个版本存成稳定版（userdata/stable，不会被自动删）"""
    return backup_current(STABLE)


def rollback_options():
    """能回滚到的版本：稳定版、自动备份、下载/桌面等地方比现在旧的安装包。最新的排前面（独立安装版没有）"""
    from ..core.paths import FROZEN
    if FROZEN:
        return []
    rows, seen = [], set()

    def add(p, where):
        m = NAME.match(p.name)
        if not m or p.resolve() in seen:
            return
        v = ver(".".join(m.groups()))
        if v == current() and where not in ("稳定版", "升级前自动备份"):     # 升级失败后要能「重新安装」自动备份（十一审 2026-10-28）
            return
        rel = "回滚到" if v < current() else ("重新安装" if v == current() else "升级到")
        seen.add(p.resolve())
        rows.append({"path": str(p), "version": ".".join(map(str, v)), "where": where, "stable": where == "稳定版", "action": rel,
                     "at": time.strftime("%m-%d %H:%M", time.localtime(p.stat().st_mtime))})
    for p in STABLE.glob("Dubhe_*.zip") if STABLE.exists() else []:
        add(p, "稳定版")
    for p in BACKUPS.glob("Dubhe_*.zip") if BACKUPS.exists() else []:
        add(p, "升级前自动备份")
    older = []
    for folder, where, depth in _search_dirs():
        if folder.exists():
            older += [(p, where) for p in _walk(folder, depth) if ver(".".join(NAME.match(p.name).groups())) < current()]
    older.sort(key=lambda x: ver(".".join(NAME.match(x[0].name).groups())), reverse=True)
    for p, where in older[:3]:
        add(p, where)
    rows.sort(key=lambda r: (not r["stable"], tuple(-x for x in ver(r["version"]))))
    return rows


def adopt_previous(version):
    """刚从 version 升级上来、但备份里没有它（旧版本的升级不会备份）：在下载/桌面等地方找到它的安装包就复制进备份"""
    BACKUPS.mkdir(parents=True, exist_ok=True)
    if (BACKUPS / f"Dubhe_{version}.zip").exists() or (STABLE / f"Dubhe_{version}.zip").exists():
        return None
    for folder, where, depth in _search_dirs():
        if folder.exists():
            for p in _walk(folder, depth):
                if ver(".".join(NAME.match(p.name).groups())) == ver(version):
                    try:
                        check(p)
                    except ValueError:
                        continue
                    dest = BACKUPS / f"Dubhe_{version}.zip"
                    shutil.copy2(p, dest)
                    return dest
    return None


def just_upgraded():
    """刚升级完（重启后第一次问）：返回 {"from","to"}，只返回一次"""
    try:
        import json
        d = json.loads(STAMP.read_text(encoding="utf-8"))
        STAMP.unlink()
        return d if time.time() - d.get("at", 0) < 600 else None
    except Exception:
        return None
