"""用 Windows 自带的 C# 编译器（.NET Framework 4，每台 Windows 10/11 都有）生成「Dubhe.exe」

不用下载任何东西。exe 只是个启动器：用 pythonw 启动助手，所以不会出现黑色命令行窗口。
python -m sc_mining.app.build_exe
"""

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
EXE_NAME = "Dubhe.exe"


def find_csc():
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    for fw in ("Framework64", "Framework"):
        c = windir / "Microsoft.NET" / fw / "v4.0.30319" / "csc.exe"
        if c.exists():
            return c
    return None


def build(out_dir=ROOT):
    csc = find_csc()
    if not csc:
        raise RuntimeError(
            "这台电脑上没找到 Windows 自带的 C# 编译器（.NET Framework 4）"
        )
    tmp = Path(out_dir) / "_launcher_build.exe"
    cmd = [
        str(csc),
        "/nologo",
        "/target:winexe",
        "/optimize+",
        "/codepage:65001",
        f"/win32icon:{HERE / 'icon.ico'}",
        "/r:System.Windows.Forms.dll",
        f"/out:{tmp}",
        str(HERE / "launcher.cs"),
    ]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="mbcs" if sys.platform == "win32" else "utf-8",
        errors="replace",
        creationflags=0x08000000 if sys.platform == "win32" else 0,
    )
    if r.returncode != 0 or not tmp.exists():
        raise RuntimeError("编译失败：" + (r.stdout + r.stderr).strip())
    final = Path(out_dir) / EXE_NAME
    if final.exists():
        final.unlink()
    tmp.rename(final)
    for old_name in ("星际公民助手.exe", "天枢.exe"):  # 改名前生成的旧启动器
        old = Path(out_dir) / old_name
        if old.exists():
            try:
                old.unlink()
            except OSError:
                pass
    return final


if __name__ == "__main__":
    print(build())
