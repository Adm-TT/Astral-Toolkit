"""读屏开发工作台：本机服务。只听 127.0.0.1，只读样本目录里的图，只写区域文件和报告目录。

接口（界面用，全是 JSON，除了图片和静态文件）：
  GET  /                         界面
  GET  /static/<文件>            界面的脚本、样式、画框组件
  GET  /api/features             [{key, name, regions}]
  GET  /api/samples              [{id, root, rel, w, h}]   id = 样本根序号/相对路径
  GET  /api/image?id=            原图
  GET  /api/regions              区域文件 {version, regions}
  PUT  /api/regions              {version, regions} → {version}；版本对不上 409，格式不对 400
  POST /api/try                  {feature, id, point:[x,y]|null} → 结果
  POST /api/batch                {feature, ids?} → {job}
  GET  /api/batch/<job>          {total, done, errors, finished, cancelled, report}
  GET  /reports/<文件>           批量查报告（只限报告目录）
  DELETE /api/batch/<job>        取消（跑完手上这张就停，跑完的照样出报告）
"""

from __future__ import annotations

import json
import mimetypes
import threading
import uuid
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, unquote, urlparse

from PIL import Image

from astral_toolkit.core import screen_regions

from . import features, report

STATIC = Path(__file__).resolve().parent / "static"
EXT = {".png", ".jpg", ".jpeg"}
THUMB_W = report.THUMB_W


class Lab(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, roots: list[Path], port: int, report_dir: Path | None):
        super().__init__(("127.0.0.1", port), Handler)
        self.roots = [Path(r).resolve() for r in roots]
        self.report_dir = (
            Path(report_dir)
            if report_dir
            else (self.roots[0] / "工作台报告" if self.roots else Path("工作台报告"))
        )
        self.jobs: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()

    # ---------------------------------------------------------------- 样本
    def samples(self) -> list[dict[str, Any]]:
        out = []
        for i, root in enumerate(self.roots):
            if not root.is_dir():
                continue
            for p in sorted(root.rglob("*")):
                if (
                    p.suffix.lower() not in EXT
                    or not p.is_file()
                    or self.report_dir in p.parents
                ):
                    continue
                try:
                    with Image.open(p) as im:  # 只读文件头，不整张解码
                        w, h = im.size
                except OSError:
                    continue
                rel = p.relative_to(root).as_posix()
                out.append(
                    {"id": f"{i}/{rel}", "root": str(root), "rel": rel, "w": w, "h": h}
                )
        return out

    def resolve(self, sid: str) -> Path | None:
        """样本 id → 文件；不在样本根里面（.. 、绝对路径、根序号不对）返回 None"""
        idx, _sep, rel = (sid or "").partition("/")
        if not idx.isdigit() or int(idx) >= len(self.roots) or not rel:
            return None
        root = self.roots[int(idx)]
        p = (root / rel).resolve()
        if not p.is_relative_to(root) or p.suffix.lower() not in EXT:
            return None
        return p

    # ---------------------------------------------------------------- 批量查
    def start_batch(self, feature: str, ids: list[str]) -> str:
        job = uuid.uuid4().hex[:12]
        st = {
            "total": len(ids),
            "done": 0,
            "errors": 0,
            "finished": False,
            "cancelled": False,
            "report": "",
        }
        stop = threading.Event()
        with self.lock:
            self.jobs[job] = {"state": st, "stop": stop}
        threading.Thread(
            target=self._batch, args=(feature, ids, st, stop), daemon=True
        ).start()
        return job

    def _batch(
        self, feature: str, ids: list[str], st: dict[str, Any], stop: threading.Event
    ) -> None:
        rows = []
        for sid in ids:
            if stop.is_set():
                st["cancelled"] = True
                break
            path = self.resolve(sid)
            try:
                if path is None:
                    raise FileNotFoundError(sid)
                with Image.open(path) as im:
                    img = im.convert("RGB")
                r = features.run(feature, img, None, batch=True)
                small = img.resize(
                    (THUMB_W, max(1, img.size[1] * THUMB_W // img.size[0]))
                )
                rows.append((sid, img.size, r, small))  # 只留缩略图，几百张也不占内存
            except Exception as e:  # 打不开的图记一笔，接着跑
                rows.append(
                    (
                        sid,
                        (1, 1),
                        features.Result(error=f"{type(e).__name__}: {e}"),
                        Image.new("RGB", (1, 1)),
                    )
                )
            if rows[-1][2].error:
                st["errors"] += 1
            st["done"] += 1
        try:
            st["report"] = str(report.write(feature, rows, self.report_dir))
        finally:
            st["finished"] = True


class Handler(BaseHTTPRequestHandler):
    @property
    def lab(self) -> Lab:
        return cast(Lab, self.server)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - 不往控制台刷每个请求
        pass

    # ---------------------------------------------------------------- 回复
    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: Any) -> None:
        self._send(
            status,
            json.dumps(data, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _err(self, status: int, msg: str) -> None:
        self._json(status, {"error": msg})

    def _body(self) -> Any:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"null") if n else None

    # ---------------------------------------------------------------- GET
    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        path = unquote(url.path)
        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path.startswith("/static/"):
            return self._static(path[len("/static/") :])
        if path == "/api/features":
            return self._json(
                200,
                [
                    {"key": f.key, "name": f.name, "regions": f.regions}
                    for f in features.FEATURES.values()
                ],
            )
        if path == "/api/samples":
            return self._json(200, self.lab.samples())
        if path == "/api/image":
            p = self.lab.resolve((parse_qs(url.query).get("id") or [""])[0])
            if p is None:
                return self._err(403, "不在样本目录里")
            if not p.is_file():
                return self._err(404, "没有这张图")
            return self._send(
                200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "image/png"
            )
        if path == "/api/regions":
            return self._json(200, screen_regions.load())
        if path.startswith("/reports/"):
            return self._file(self.lab.report_dir, path[len("/reports/") :])
        if path.startswith("/api/batch/"):
            job = self.lab.jobs.get(path.rsplit("/", 1)[1])
            return (
                self._json(200, job["state"]) if job else self._err(404, "没有这个任务")
            )
        return self._err(404, "没有这个地址")

    def _static(self, rel: str) -> None:
        self._file(STATIC, rel)

    def _file(self, base: Path, rel: str) -> None:
        """base 目录里的文件（不许跑出 base）"""
        p = (base / rel).resolve()
        if not p.is_relative_to(base.resolve()) or not p.is_file():
            return self._err(404, "没有这个文件")
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, p.read_bytes(), ctype)

    # ---------------------------------------------------------------- PUT / POST / DELETE
    def do_PUT(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/regions":
            return self._err(404, "没有这个地址")
        try:
            body = self._body() or {}
            regions = body.get("regions")
            if not isinstance(regions, dict):
                raise ValueError("regions 要是 {键: [条目, …]}")
            version = screen_regions.save(regions, int(body.get("version", -1)))
        except screen_regions.StaleRegions:
            return self._err(409, "区域文件已被改过，刷新后再存")
        except (ValueError, TypeError, AttributeError) as e:
            return self._err(400, f"区域格式不对：{e}")
        self._json(200, {"version": version})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self._body() or {}
        except ValueError:
            return self._err(400, "不是 JSON")
        feature = body.get("feature")
        if feature not in features.FEATURES:
            return self._err(400, "没有这个功能")
        if path == "/api/try":
            p = self.lab.resolve(body.get("id", ""))
            if p is None:
                return self._err(403, "不在样本目录里")
            if not p.is_file():
                return self._err(404, "没有这张图")
            point = body.get("point")
            try:
                if point is not None and len(point) != 2:
                    raise ValueError(point)
                pt = (int(point[0]), int(point[1])) if point is not None else None
            except (TypeError, ValueError, IndexError):
                return self._err(400, f"点的位置不对：{point!r}")
            with Image.open(p) as im:
                img = im.convert("RGB")
            return self._json(200, asdict(features.run(feature, img, pt, batch=False)))
        if path == "/api/batch":
            ids = body.get("ids") or [s["id"] for s in self.lab.samples()]
            return self._json(200, {"job": self.lab.start_batch(feature, list(ids))})
        return self._err(404, "没有这个地址")

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        job = (
            self.lab.jobs.get(path.rsplit("/", 1)[1])
            if path.startswith("/api/batch/")
            else None
        )
        if not job:
            return self._err(404, "没有这个任务")
        job["stop"].set()
        self._json(200, {"ok": True})


def make_server(
    roots: list[Path], port: int = 0, report_dir: Path | None = None
) -> Lab:
    """起服务（还没开始接请求，调 serve_forever 才接）；只绑定本机"""
    return Lab(roots, port, report_dir)
