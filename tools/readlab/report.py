"""读屏开发工作台：批量查的报告。一个 HTML + 同名文件夹（每张图一张带框的缩略图），只在本机，不引外部资源。"""

from __future__ import annotations

import html
import statistics
import time
from pathlib import Path
from typing import Any

from PIL import ImageDraw

from astral_toolkit.core import screen_regions

from .features import Result

THUMB_W = 960
INK = {
    "read": (64, 160, 255),
    "exclude": (255, 160, 0),
    "hit": (40, 200, 90),
    "miss": (230, 60, 60),
}


def _thumb(img: Any, r: Result, path: Path) -> None:
    im = img.convert("RGB").copy()
    d = ImageDraw.Draw(im)
    lw = max(2, im.size[1] // 400)
    for s in r.shapes:
        d.rectangle(s.box, outline=INK.get(s.color, (255, 255, 255)), width=lw)
    k = THUMB_W / im.size[0]
    im.resize((THUMB_W, max(1, int(im.size[1] * k)))).save(path, quality=82)


def write(
    feature: str, rows: list[tuple[str, tuple[int, int], Result, Any]], out_dir: Path
) -> Path:
    """rows：(图名, 原图尺寸, 结果, 图)。返回 HTML 的路径"""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    page = out_dir / f"{feature}_{stamp}.html"
    pics = out_dir / f"{feature}_{stamp}"
    pics.mkdir(exist_ok=True)
    ms = [r.ms for _n, _s, r, _i in rows]
    errors = sum(1 for _n, _s, r, _i in rows if r.error)
    aspects: dict[str, int] = {}
    body = []
    for i, (name, size, r, img) in enumerate(rows):
        pic = f"{i:04d}.jpg"
        _thumb(img, r, pics / pic)
        a = screen_regions.aspect_of(size)
        aspects[a] = aspects.get(a, 0) + 1
        lines = "<br>".join(html.escape(x) for x in r.lines)
        err = f'<div class="err">{html.escape(r.error)}</div>' if r.error else ""
        body.append(
            f'<tr><td><img src="{pics.name}/{pic}" loading="lazy"></td>'
            f"<td><b>{html.escape(name)}</b><br>{size[0]}×{size[1]}（{a}）｜{r.ms} 毫秒"
            f"<p>{lines}</p>{err}</td></tr>"
        )
    summary = (
        f"共 {len(rows)} 张｜出错 {errors} 张｜耗时中位 {statistics.median(ms) if ms else 0:.0f} 毫秒、"
        f"最慢 {max(ms, default=0)} 毫秒｜屏幕比例 "
        + "、".join(f"{k} {v} 张" for k, v in sorted(aspects.items()))
    )
    page.write_text(
        "<!doctype html><meta charset=utf-8><title>读屏批量查</title><style>"
        "body{font:14px/1.6 'Segoe UI Variable','Microsoft YaHei UI',sans-serif;margin:16px;background:#111;color:#ddd}"
        "img{width:480px;border:1px solid #333}td{vertical-align:top;padding:6px;border-bottom:1px solid #222}"
        ".err{color:#f66;white-space:pre-wrap}</style>"
        f"<h1>{html.escape(feature)} 批量查 {stamp}</h1><p class=sum>{html.escape(summary)}</p>"
        f"<table>{''.join(body)}</table>",
        encoding="utf-8",
    )
    return page
