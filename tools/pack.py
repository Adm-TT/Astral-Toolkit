# 打包「天枢」安装包 → dist\Dubhe_<版本>.zip（不含个人数据、Python 环境、测试、tools）。用法：.venv\Scripts\python.exe -X utf8 tools\pack.py
import sys, io, traceback, contextlib, zipfile, time, os  # noqa: E401, F401
from pathlib import Path

root = Path(__file__).resolve().parent.parent  # tools\ 的上一级就是项目根目录
sys.path.insert(0, str(root))
out = io.StringIO()
with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
    try:
        lost = [f for f in ("LICENSE", "免责声明.txt") if not (root / f).exists()]
        if lost:  # 先查：缺了就别删上一版的包（复审 2026-10-28）
            raise SystemExit(
                "缺少 " + "、".join(lost) + "，不能打包（AGPL 要求随程序附上许可证）"
            )
        from sc_mining.app.build_exe import build

        build()  # 用最新代码重新生成 Dubhe.exe
        dist = root / "dist"
        dist.mkdir(exist_ok=True)
        from sc_mining.core.version import VERSION

        name = f"Dubhe_{VERSION}"
        zpath = dist / f"{name}.zip"
        sys.path.insert(0, str(root / "tools"))
        from collect_licenses import build as collect_licenses

        n_lic, missing_lic = (
            collect_licenses()
        )  # 第三方许可.txt：从 .venv 收集开源组件的许可证原文（2026-10-26）
        print(
            "第三方许可：",
            n_lic,
            "个组件",
            ("，缺原文：" + "、".join(missing_lic)) if missing_lic else "",
        )
        if not (root / "第三方许可.txt").exists():
            raise SystemExit("缺少 第三方许可.txt，不能打包")
        for old in list(dist.glob("天枢_*.zip")) + list(dist.glob("Dubhe_*.zip")):
            old.unlink()
        top_files = [
            "Dubhe.exe",
            "首次安装.bat",
            "免责声明.txt",
            "使用说明.txt",
            "requirements.txt",
            "第三方许可.txt",
            "LICENSE",
        ]
        skip_dirs = {"__pycache__"}
        skip_data = {
            "scmdb",
            "loc",
            "unpack",
        }  # unpack：作者自己解包出的蓝图 / 任务原文件（2026-10-28），只在作者电脑上用                        # 原始大文件，更新数据时会自动下载
        n, size = 0, 0
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for f in top_files:
                p = root / f
                if p.exists():
                    z.write(p, f"{name}/{f}")
                    n += 1  # noqa: E702
                else:
                    print("缺少", f)
            readme = (root / "README.md").read_text(encoding="utf-8")
            readme = "\n".join(l for l in readme.splitlines() if "_claude_run" not in l)  # noqa: E741
            z.writestr(f"{name}/README.md", readme)
            n += 1  # noqa: E702
            for base in ("sc_mining", "data"):
                for dirpath, dirs, files in os.walk(root / base):
                    rel = Path(dirpath).relative_to(root)
                    dirs[:] = [
                        d
                        for d in dirs
                        if d not in skip_dirs
                        and not (
                            base == "data" and rel == Path("data") and d in skip_data
                        )
                    ]
                    for f in files:
                        if f.endswith((".pyc",)) or (
                            base == "data"
                            and rel == Path("data")
                            and f in ("loot_details.zip",)
                        ):
                            continue  # 掉落明细整包和数据包版本从 Gitee 数据包下载，安装包里不带
                        p = Path(dirpath) / f
                        z.write(p, f"{name}/{p.relative_to(root).as_posix()}")
                        n += 1
                        size += p.stat().st_size  # noqa: E702
        print(
            "zip:",
            zpath,
            n,
            "个文件，压缩后",
            round(zpath.stat().st_size / 1e6, 1),
            "MB",
        )
        # 检查：解压到临时目录，能导入、关键文件都在
        import tempfile, subprocess  # noqa: E401

        tmp = Path(tempfile.mkdtemp())
        with zipfile.ZipFile(zpath) as z:
            z.extractall(tmp)
            names = z.namelist()
        print(
            "含 userdata:",
            any("/userdata/" in x for x in names),
            " 含 .venv:",
            any("/.venv/" in x for x in names),
            " 含 tests:",
            any("/tests/" in x for x in names),
            " 含 _claude:",
            any("_claude" in x for x in names),
        )
        app = tmp / name
        r = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sc_mining.app.server, sc_mining.app.api.router, sc_mining.run; "
                "from sc_mining.core import settings; print('agreed', settings.load()['agreed'])",
            ],
            cwd=app,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        print("解压后导入:", r.returncode, r.stdout.strip(), r.stderr.strip()[-500:])
        for must in (
            "Dubhe.exe",
            "首次安装.bat",
            "免责声明.txt",
            "使用说明.txt",
            "第三方许可.txt",
            "LICENSE",
            "sc_mining/app/web/index.html",
            "data/shops.json",
            "data/crafting.json",
            "data/ship_signatures.json",
            "data/wikelo.json",
            "data/zh_names.json",
        ):
            print(" ", must, (app / must).exists())
    except Exception:
        traceback.print_exc()
    print("DONE")
print(out.getvalue())
