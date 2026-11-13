"""独立目录包（PyInstaller onedir，2026-10-26 验证阶段）：玩家不用装 Python，解压后双击 AT.exe

用构建环境里的 Python 运行（不是项目的 .venv）：
  E:\\Game3\\AT_build\\venv\\Scripts\\python.exe -X utf8 tools\\build_standalone.py
输出 E:\\Game3\\AT_build\\dist\\AT\\（AT.exe + _internal + data + 免责声明等），并打印体积统计。
暂不做单文件封装、不做增量更新（用户 2026-10-26 定）
安装程序由 tools/build_velopack.py 出（老的 Inno 安装版 2026-10-31 停发，--installer 已删）
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = Path(
    os.environ.get("AT_BUILD_DIR", ROOT.parent / "AT_build")
)  # 和项目放在同一层（2026-10-27 起 E:\\Game3）
DIST = BUILD / "dist"
OUT = DIST / "AT"
sys.path.insert(0, str(ROOT))
from astral_toolkit.core.paths import BUILD_DIR  # noqa: E402

# 以后 BUILD_DIR 改名时，旧目录名也要留在这个排除表里，否则游戏数据原文件会被打进安装包
SKIP_DATA_DIRS = {
    "scmdb",
    "loc",
    "release",
    BUILD_DIR,
}  # BUILD_DIR：构建输入目录（2026-10-28），只在作者电脑上用                         # 原始大文件，更新数据时会自动下载（和 tools/pack.py 一致）
SKIP_DATA_FILES = {
    "loot_details.zip"
}  # 掉落明细整包从数据包下载；data_pack.json 要带上（不然「开始更新」会拿网上更旧的包盖掉，2026-10-28）
# 安装包必须自带的数据（自检 selftest.data_files 查的这些 + 数据包版本记录：没带记录「更新数据」会拿网上更旧的包盖掉）
DATA_MUST = (
    "shops.json",
    "crafting.json",
    "starmap.json",
    "loot_index.json",
    "zh_names.json",
    "wikelo.json",
    "prices.json",
    "data_pack.json",
)
TOP_FILES = ("免责声明.txt", "使用说明.txt", "第三方许可.txt", "LICENSE")
SHELL_SRC = (
    ROOT / "tools" / "shell" / "ATShell"
)  # AT 窗口外壳（WinUI 3 + WebView2，2026-10-27）
SHELL_OUT = BUILD / "shell_out"
NUGET = BUILD / "nuget"  # NuGet 缓存放 E 盘，不放 C 盘
ISCC = (
    BUILD / "tools" / "InnoSetup6" / "ISCC.exe"
)  # Inno Setup 6.7.3（2026-10-26 装在构建目录里）；只剩 build_velopack 编桥接安装程序用
# 用不上的大文件：OpenCV 的视频解码（29 MB，AT 不读视频）、Pillow 的 AVIF 图片支持（7 MB）。删掉后自检、样本识别照常
UNUSED = ("_internal/cv2/opencv_videoio_ffmpeg*.dll", "_internal/PIL/_avif*.pyd")
BUILD_ONLY = {
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "altgraph",
    "pefile",
    "pywin32-ctypes",
    "setuptools",
    "wheel",
    "pip",
}


def _size(p):
    return sum(f.stat().st_size for f in Path(p).rglob("*") if f.is_file())


def _ensure_ppocrv6_tiny_models():
    """打包前把 PP-OCRv6 识别模型（ocr.runtime.MODEL_TYPE 那一档）下进 rapidocr/models，再靠 --collect-data rapidocr 打进安装包。"""
    from astral_toolkit.ocr import runtime as OR

    try:
        OR.ensure_models()
    except Exception as e:
        raise SystemExit(f"❌ 打包需要的 OCR 模型没下好：{e}") from e
    print(f"OCR 模型就绪：{OR.OCR_VERSION}/{OR.MODEL_TYPE}")


def _version_file():
    """AT.exe 的文件说明写成 AstralToolkit：任务管理器里显示的就是它（老大 2026-11-09 定）"""
    from astral_toolkit.core.version import VERSION

    nums = [int(x) for x in VERSION.split("-")[0].split(".")[:3]]
    v = tuple(nums + [0] * (4 - len(nums)))
    p = BUILD / "version_info.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004,
    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('080404b0', [
      StringStruct('CompanyName', 'Adm_TT'),
      StringStruct('FileDescription', 'AstralToolkit'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', 'AT'),
      StringStruct('OriginalFilename', 'AT.exe'),
      StringStruct('ProductName', 'AstralToolkit'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
""",
        encoding="utf-8",
    )
    return p


def main():
    t0 = time.time()
    sys.path.insert(0, str(ROOT / "tools"))
    import collect_licenses

    collect_licenses.SKIP = (
        set(collect_licenses.SKIP) | BUILD_ONLY
    )  # 只列随 AT 分发的组件
    n, missing = collect_licenses.build()
    print(
        f"第三方许可：{n} 个组件"
        + (f"，缺原文：{'、'.join(missing)}" if missing else "")
    )
    lost = [f for f in TOP_FILES if not (ROOT / f).exists()]
    if lost:  # PyInstaller 跑之前就查（复审 2026-10-28）
        raise SystemExit(
            f"缺少 {'、'.join(lost)}，不能打包（AGPL 要求随程序附上许可证）"
        )

    import PyInstaller.__main__

    os.environ["PYTHONPATH"] = str(
        ROOT
    )  # PyInstaller 在单独的进程里找包，要让它也找得到 astral_toolkit
    _ensure_ppocrv6_tiny_models()  # wheel 默认只带 small；换别的档要事先下好再 --collect-data，玩家断网也能认字
    # astral_toolkit 自带的数据文件（网页界面、汉化对照、图标、字体……）和全部模块：逐个列出，不依赖 PyInstaller 自己去找
    # （第一次构建时 --collect-data astral_toolkit 报「not a package」，数据文件全漏了，2026-10-26）
    pkg = ROOT / "astral_toolkit"
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
    args = [
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        "AT",
        "--icon",
        str(ROOT / "astral_toolkit" / "app" / "icon.ico"),
        "--version-file",
        str(_version_file()),
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD / "work"),
        "--specpath",
        str(BUILD),
        "--paths",
        str(ROOT),
        *extra,
        "--collect-data",
        "rapidocr",
        "--collect-binaries",
        "onnxruntime",
        "--hidden-import",
        "velopack",  # Velopack 安装、升级、卸载时的入口（frozen_main._velopack）
        "--exclude-module",
        "tests",
        str(ROOT / "astral_toolkit" / "frozen_main.py"),
    ]
    print("PyInstaller", " ".join(args[:6]), "…")
    PyInstaller.__main__.run(args)

    for pat in UNUSED:
        for f in OUT.glob(pat):
            f.unlink()
    # 输出里不能带 userdata（之前在本机试运行留下的设置、日志、Edge 窗口缓存，2026-10-26 沙盒验收时发现）
    if (OUT / "userdata").exists():
        shutil.rmtree(OUT / "userdata")
    # 程序旁边的文件：数据、免责声明、第三方许可、自检截图
    lost = [f for f in DATA_MUST if not (ROOT / "data" / f).is_file()]
    if lost:  # 没有 data/ 会静默打出不带数据的安装包（玩家装完一片空）
        raise SystemExit(
            f"❌ 项目 data\\ 里缺 {'、'.join(lost)}，不能打包（先跑 astral_toolkit.run update 或 make_data_pack 准备数据）"
        )
    data_out = OUT / "data"
    if data_out.exists():
        shutil.rmtree(data_out)
    for p in (ROOT / "data").rglob("*"):
        rel = p.relative_to(ROOT / "data")
        if (
            not p.is_file()
            or rel.parts[0] in SKIP_DATA_DIRS
            or (len(rel.parts) == 1 and rel.name in SKIP_DATA_FILES)
        ):
            continue
        (data_out / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, data_out / rel)
    # 对玩家可见清单（老大 2026-11-13）：安装包带的是 data/release/ 下那份；没有清单或没有地点总表不打包，不能把全量地点发出去
    vis = ROOT / "data" / "release" / "place_visibility.json"
    if not vis.is_file() or not (ROOT / "data" / "places.json").is_file():
        raise SystemExit(
            f"❌ 缺地点总表（data\\places.json）或对玩家可见清单（{vis}），不能打包"
        )
    shutil.copy2(vis, data_out / "place_visibility.json")
    for f in TOP_FILES:
        shutil.copy2(ROOT / f, OUT / f)
    (OUT / "selftest").mkdir(exist_ok=True)
    shutil.copy2(
        ROOT / "tests" / "samples" / "scan1.png", OUT / "selftest" / "scan1.png"
    )

    build_shell()

    total, internal, data = _size(OUT), _size(OUT / "_internal"), _size(data_out)
    must = [
        "astral_toolkit/sc_glossary.json",
        "astral_toolkit/names_zh.json",
        "astral_toolkit/app/web/index.html",
        "astral_toolkit/app/web/app.js",
        "astral_toolkit/app/icon.ico",
        "astral_toolkit/app/web/fonts/D-DIN.ttf",
    ]
    lost = [m for m in must if not (OUT / "_internal" / m).exists()]
    lost += [f"data/{f}" for f in DATA_MUST if not (data_out / f).is_file()]
    if lost:
        raise SystemExit("❌ 打包缺文件：" + "、".join(lost))
    print(f"\n✅ 输出：{OUT}")
    print(
        f"总大小 {total / 2**20:,.1f} MB（程序和组件 {internal / 2**20:,.1f} MB，数据 {data / 2**20:,.1f} MB），"
        f"{sum(1 for f in OUT.rglob('*') if f.is_file())} 个文件，用时 {time.time() - t0:,.0f} 秒"
    )
    big = {}
    for f in (OUT / "_internal").rglob("*"):
        if f.is_file():
            top = f.relative_to(OUT / "_internal").parts[0]
            big[top] = big.get(top, 0) + f.stat().st_size
    print(
        "最大的组件："
        + "，".join(
            f"{k} {v / 2**20:,.1f} MB"
            for k, v in sorted(big.items(), key=lambda x: -x[1])[:10]
        )
    )


def build_shell():
    """编外壳 ATShell.exe（dotnet publish，自带 .NET 和界面组件、裁掉用不上的代码），放进 AT\\shell\\"""
    env = dict(
        os.environ,
        NUGET_PACKAGES=str(NUGET),
        DOTNET_CLI_TELEMETRY_OPTOUT="1",
        DOTNET_NOLOGO="1",
    )
    if SHELL_OUT.exists():
        shutil.rmtree(SHELL_OUT)
    r = subprocess.run(
        [
            "dotnet",
            "publish",
            str(SHELL_SRC / "ATShell.csproj"),
            "-c",
            "Release",
            "-p:Platform=x64",
            "-o",
            str(SHELL_OUT),
        ],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode or not (SHELL_OUT / "ATShell.exe").exists():
        raise SystemExit("❌ 外壳没编出来：\n" + r.stdout[-3000:] + r.stderr[-2000:])
    dest = OUT / "shell"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(SHELL_OUT, dest)
    lic = OUT / "第三方许可.txt"
    note = (
        "\n\n==== AT 窗口外壳（shell\\ATShell.exe）用到的组件 ====\n"
        ".NET 运行库（MIT，© .NET Foundation and Contributors）\n"
        "Windows App SDK / WinUI 3（MIT，© Microsoft Corporation）\n"
        "Microsoft Edge WebView2（运行库为 Windows 组件；WebView2 SDK 按其许可随附，© Microsoft Corporation）\n"
    )
    if lic.exists():
        lic.write_text(lic.read_text(encoding="utf-8") + note, encoding="utf-8")
    print(f"外壳：{_size(dest) / 2**20:,.1f} MB")


if __name__ == "__main__":
    main()
