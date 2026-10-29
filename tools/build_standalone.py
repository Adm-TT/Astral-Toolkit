"""独立目录包（PyInstaller onedir，2026-10-26 验证阶段）：玩家不用装 Python，解压后双击 AT.exe

用构建环境里的 Python 运行（不是项目的 .venv）：
  E:\\Game3\\AT_build\\venv\\Scripts\\python.exe -X utf8 tools\\build_standalone.py
输出 E:\\Game3\\AT_build\\dist\\AT\\（AT.exe + _internal + data + 免责声明等），并打印体积统计。
暂不做单文件封装、不做增量更新（用户 2026-10-26 定）
加 --installer：再用 Inno Setup 编出安装程序 AT_Setup_<版本>.exe（放在 dist\\，tools\\AT_setup.iss）
"""
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = Path(os.environ.get("AT_BUILD_DIR", ROOT.parent / "AT_build"))     # 和项目放在同一层（2026-10-27 起 E:\\Game3）
DIST = BUILD / "dist"
OUT = DIST / "AT"
SKIP_DATA_DIRS = {"scmdb", "loc", "unpack"}        # unpack：作者自己解包出的蓝图 / 任务原文件（2026-10-28），只在作者电脑上用                         # 原始大文件，更新数据时会自动下载（和 tools/pack.py 一致）
SKIP_DATA_FILES = {"loot_details.zip"}  # 掉落明细整包从 Gitee 下载；data_pack.json 要带上（不然「开始更新」会拿网上更旧的包盖掉，2026-10-28）
TOP_FILES = ("免责声明.txt", "使用说明.txt", "第三方许可.txt", "LICENSE")
SHELL_SRC = ROOT / "tools" / "shell" / "ATShell"                   # AT 窗口外壳（WinUI 3 + WebView2，2026-10-27）
SHELL_OUT = BUILD / "shell_out"
NUGET = BUILD / "nuget"                                            # NuGet 缓存放 E 盘，不放 C 盘
ISCC = BUILD / "tools" / "InnoSetup6" / "ISCC.exe"                # Inno Setup 6.7.3（2026-10-26 装在构建目录里）
# 用不上的大文件：OpenCV 的视频解码（29 MB，AT 不读视频）、Pillow 的 AVIF 图片支持（7 MB）。删掉后自检、样本识别照常
UNUSED = ("_internal/cv2/opencv_videoio_ffmpeg*.dll", "_internal/PIL/_avif*.pyd")
BUILD_ONLY = {"pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "pywin32-ctypes", "setuptools", "wheel", "pip"}


def _size(p):
    return sum(f.stat().st_size for f in Path(p).rglob("*") if f.is_file())


def main():
    t0 = time.time()
    sys.path.insert(0, str(ROOT / "tools"))
    import collect_licenses
    collect_licenses.SKIP = set(collect_licenses.SKIP) | BUILD_ONLY      # 只列随 AT 分发的组件
    n, missing = collect_licenses.build()
    print(f"第三方许可：{n} 个组件" + (f"，缺原文：{'、'.join(missing)}" if missing else ""))
    lost = [f for f in TOP_FILES if not (ROOT / f).exists()]
    if lost:                                       # PyInstaller 跑之前就查（复审 2026-10-28）
        raise SystemExit(f"缺少 {'、'.join(lost)}，不能打包（AGPL 要求随程序附上许可证）")

    import PyInstaller.__main__
    os.environ["PYTHONPATH"] = str(ROOT)          # PyInstaller 在单独的进程里找包，要让它也找得到 sc_mining
    # sc_mining 自带的数据文件（网页界面、汉化对照、图标、字体……）和全部模块：逐个列出，不依赖 PyInstaller 自己去找
    #（第一次构建时 --collect-data sc_mining 报「not a package」，数据文件全漏了，2026-10-26）
    pkg = ROOT / "sc_mining"
    extra = []
    for f in sorted(pkg.rglob("*")):
        if not f.is_file() or "__pycache__" in f.parts:
            continue
        rel = f.relative_to(ROOT)
        if f.suffix == ".py":
            mod = ".".join(rel.with_suffix("").parts)
            if not mod.endswith("__init__"):
                extra += ["--hidden-import", mod]
        elif f.suffix not in (".pyc", ".pyo"):
            extra += ["--add-data", f"{f}{os.pathsep}{rel.parent.as_posix()}"]
    args = ["--noconfirm", "--clean", "--onedir", "--windowed", "--name", "AT",
            "--icon", str(ROOT / "sc_mining" / "app" / "icon.ico"),
            "--distpath", str(DIST), "--workpath", str(BUILD / "work"), "--specpath", str(BUILD),
            "--paths", str(ROOT),
            *extra,
            "--collect-data", "rapidocr_onnxruntime", "--collect-binaries", "onnxruntime",
            "--hidden-import", "velopack",               # Velopack 安装、升级、卸载时的入口（frozen_main._velopack）
            "--exclude-module", "tests",
            str(ROOT / "sc_mining" / "frozen_main.py")]
    print("PyInstaller", " ".join(args[:6]), "…")
    PyInstaller.__main__.run(args)

    for pat in UNUSED:
        for f in OUT.glob(pat):
            f.unlink()
    # 输出里不能带 userdata（之前在本机试运行留下的设置、日志、Edge 窗口缓存，2026-10-26 沙盒验收时发现）
    if (OUT / "userdata").exists():
        shutil.rmtree(OUT / "userdata")
    # 程序旁边的文件：数据、免责声明、第三方许可、自检截图
    data_out = OUT / "data"
    if data_out.exists():
        shutil.rmtree(data_out)
    for p in (ROOT / "data").rglob("*"):
        rel = p.relative_to(ROOT / "data")
        if not p.is_file() or rel.parts[0] in SKIP_DATA_DIRS or (len(rel.parts) == 1 and rel.name in SKIP_DATA_FILES):
            continue
        (data_out / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, data_out / rel)
    for f in TOP_FILES:
        shutil.copy2(ROOT / f, OUT / f)
    (OUT / "selftest").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "tests" / "samples" / "scan1.png", OUT / "selftest" / "scan1.png")

    build_shell()

    total, internal, data = _size(OUT), _size(OUT / "_internal"), _size(data_out)
    must = ["sc_mining/sc_glossary.json", "sc_mining/names_zh.json", "sc_mining/app/web/index.html", "sc_mining/app/web/app.js",
            "sc_mining/app/icon.ico", "sc_mining/app/web/fonts/D-DIN.ttf"]
    lost = [m for m in must if not (OUT / "_internal" / m).exists()]
    if lost:
        raise SystemExit("❌ 打包缺文件：" + "、".join(lost))
    print(f"\n✅ 输出：{OUT}")
    print(f"总大小 {total / 2 ** 20:,.1f} MB（程序和组件 {internal / 2 ** 20:,.1f} MB，数据 {data / 2 ** 20:,.1f} MB），"
          f"{sum(1 for f in OUT.rglob('*') if f.is_file())} 个文件，用时 {time.time() - t0:,.0f} 秒")
    big = {}
    for f in (OUT / "_internal").rglob("*"):
        if f.is_file():
            top = f.relative_to(OUT / "_internal").parts[0]
            big[top] = big.get(top, 0) + f.stat().st_size
    print("最大的组件：" + "，".join(f"{k} {v / 2 ** 20:,.1f} MB" for k, v in sorted(big.items(), key=lambda x: -x[1])[:10]))
    if "--installer" in sys.argv:
        installer()


def build_shell():
    """编外壳 ATShell.exe（dotnet publish，自带 .NET 和界面组件、裁掉用不上的代码），放进 AT\\shell\\"""
    env = dict(os.environ, NUGET_PACKAGES=str(NUGET), DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1")
    if SHELL_OUT.exists():
        shutil.rmtree(SHELL_OUT)
    r = subprocess.run(["dotnet", "publish", str(SHELL_SRC / "ATShell.csproj"), "-c", "Release", "-p:Platform=x64",
                        "-o", str(SHELL_OUT)], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode or not (SHELL_OUT / "ATShell.exe").exists():
        raise SystemExit("❌ 外壳没编出来：\n" + r.stdout[-3000:] + r.stderr[-2000:])
    dest = OUT / "shell"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(SHELL_OUT, dest)
    lic = OUT / "第三方许可.txt"
    note = ("\n\n==== AT 窗口外壳（shell\\ATShell.exe）用到的组件 ====\n"
            ".NET 运行库（MIT，© .NET Foundation and Contributors）\n"
            "Windows App SDK / WinUI 3（MIT，© Microsoft Corporation）\n"
            "Microsoft Edge WebView2（运行库为 Windows 组件；WebView2 SDK 按其许可随附，© Microsoft Corporation）\n")
    if lic.exists():
        lic.write_text(lic.read_text(encoding="utf-8") + note, encoding="utf-8")
    print(f"外壳：{_size(dest) / 2 ** 20:,.1f} MB")


def installer():
    """Inno Setup 编安装程序。Gitee 发行版单个附件上限 100 MB，超了直接报错"""
    version = re.search(r'VERSION = "([^"]+)"', (ROOT / "sc_mining" / "core" / "version.py").read_text(encoding="utf-8")).group(1)
    out_dir = ROOT / "dist"
    out_dir.mkdir(exist_ok=True)
    if not ISCC.exists():
        raise SystemExit(f"❌ 没找到 Inno Setup：{ISCC}")
    t0 = time.time()
    subprocess.run([str(ISCC), "/Q", f"/DMyVersion={version}", f"/DSrcDir={OUT}", f"/DOutDir={out_dir}",
                    str(ROOT / "tools" / "AT_setup.iss")], check=True)
    exe = out_dir / f"AT_Setup_{version}.exe"
    size = exe.stat().st_size
    print(f"✅ 安装程序：{exe}（{size / 2 ** 20:,.1f} MB，用时 {time.time() - t0:,.0f} 秒）")
    if size >= 100 * 2 ** 20:
        raise SystemExit("❌ 超过 Gitee 单个附件上限 100 MB，传不上去")


if __name__ == "__main__":
    main()
