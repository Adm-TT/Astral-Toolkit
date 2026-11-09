"""起读屏开发工作台：.venv\\Scripts\\python.exe -X utf8 -m tools.readlab [--samples 目录 ...] [--port 端口]

不给 --samples 时只用老大挑过的样本：E:\\Claude公主的书\\项目资料\\测试数据（11-09 老大：不要把 Windows 截图文件夹
这些私人截图混进来）；要看别的目录用 --samples 指定。起好后自动打开浏览器；Ctrl+C 停。
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
    """默认样本根：只用挑过的测试数据（有才用）"""
    return [r for r in DEFAULT_ROOTS if r.is_dir()]


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
