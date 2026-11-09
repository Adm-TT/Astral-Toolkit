"""起读屏开发工作台：.venv\\Scripts\\python.exe -X utf8 -m tools.readlab [--samples 目录 ...] [--port 端口]

不给 --samples 时用这些样本根（有的才用）：E:\\Claude公主的书\\项目资料\\测试数据、tests\\samples，
以及 tools\\sample_sweep.py 里登记的截图来源。起好后自动打开浏览器；Ctrl+C 停。
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DEFAULT_ROOTS = [Path(r"E:\Claude公主的书\项目资料\测试数据")]


def default_roots() -> list[Path]:
    roots = list(DEFAULT_ROOTS)
    try:
        from tools import sample_sweep

        roots += [d for _label, d in sample_sweep.SOURCES]
    except Exception:  # sample_sweep 改了结构也不影响开工作台
        roots.append(ROOT / "tests" / "samples")
    seen, out = set(), []
    for r in roots:
        key = str(r.resolve()).lower() if r.exists() else None
        if key and key not in seen and r.is_dir():
            seen.add(key)
            out.append(r)
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="python -m tools.readlab", description="读屏开发工作台（只在本机）"
    )
    ap.add_argument("--samples", nargs="*", type=Path, help="样本目录（可以给多个）")
    ap.add_argument("--port", type=int, default=0, help="端口（默认随便挑一个空的）")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args(argv)

    from tools.readlab.server import make_server

    roots = args.samples or default_roots()
    httpd = make_server(roots, args.port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"读屏开发工作台：{url}", flush=True)
    for i, r in enumerate(httpd.roots):
        print(f"  样本根 {i}：{r}", flush=True)
    print(f"  报告放在：{httpd.report_dir}", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
