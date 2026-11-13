"""debug_mode 下 F8/F6 识别区域调试落盘。

见 docs/superpowers/specs/2026-11-04-debug-region-shots.md：
每次识别（成败）异步写入 userdata/shots/debug/{hover|count}/… 的 crop、标注整屏、meta.json。
默认关；写失败只打日志，不拖垮识别。
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

KEEP = 5  # hover / count 各留最近几次触发
_SYNC = False  # 测试可改 True，避免异步等文件

_tls = threading.local()


def _debug_on() -> bool:
    try:
        from ..core import settings

        return bool(settings.load().get("debug_mode"))
    except Exception:
        return False


def _stamp() -> str:
    now = time.time()
    return (
        time.strftime("%Y%m%d_%H%M%S", time.localtime(now))
        + f"_{int(now * 1000) % 1000:03d}"
    )


def safe_label(label: str) -> str:
    """文件名用：去掉 % 等，只留安全字符。"""
    s = (label or "unknown").replace("%", "")
    s = re.sub(r"[^\w\-@.]+", "_", s, flags=re.UNICODE)
    return (s or "unknown")[:80]


@dataclass
class RegionRec:
    label: str
    stage: str
    box: Tuple[int, int, int, int]
    used: bool = False
    crop: Any = None  # PIL Image | None
    kind: str = ""  # extras 用：cell / body 等


@dataclass
class Session:
    attempts: List[RegionRec] = field(default_factory=list)
    extras: List[RegionRec] = field(default_factory=list)
    stop_reason: str = ""

    def add_attempt(
        self,
        label: str,
        stage: str,
        box: Sequence[int],
        crop: Any = None,
        *,
        used: bool = False,
    ) -> None:
        self.attempts.append(
            RegionRec(
                label=label,
                stage=stage or "",
                box=(int(box[0]), int(box[1]), int(box[2]), int(box[3])),
                used=used,
                crop=crop.copy()
                if crop is not None and hasattr(crop, "copy")
                else crop,
            )
        )

    def add_extra(
        self,
        label: str,
        stage: str,
        box: Sequence[int],
        crop: Any = None,
        *,
        kind: str = "",
        used: bool = False,
    ) -> None:
        self.extras.append(
            RegionRec(
                label=label,
                stage=stage or "",
                box=(int(box[0]), int(box[1]), int(box[2]), int(box[3])),
                used=used,
                crop=crop.copy()
                if crop is not None and hasattr(crop, "copy")
                else crop,
                kind=kind or label,
            )
        )


def begin_if_debug() -> Optional[Session]:
    """识别入口：调试开着就开新会话（覆盖线程上未 flush 的旧会话）。"""
    if not _debug_on():
        _tls.session = None
        return None
    sess = Session()
    _tls.session = sess
    return sess


def current() -> Optional[Session]:
    return getattr(_tls, "session", None)


def bind_count_run(stamp: Optional[str] = None) -> str:
    """F6 盘点线程开始时绑定；返回本次 run 时间戳目录名。"""
    s = stamp or _stamp()
    _tls.count_stamp = s
    _tls.count_cell = 0
    return s


def unbind_count_run() -> None:
    _tls.count_stamp = None
    _tls.count_cell = 0


def _count_bound() -> Optional[str]:
    return getattr(_tls, "count_stamp", None)


def _next_cell() -> int:
    n = int(getattr(_tls, "count_cell", 0) or 0)
    _tls.count_cell = n + 1
    return n


def _prune(root: Path, keep: int = KEEP) -> None:
    if not root.is_dir():
        return
    dirs = [p for p in root.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.name)
    for old in dirs[:-keep] if keep > 0 else dirs:
        try:
            for f in sorted(old.rglob("*"), reverse=True):
                if f.is_file():
                    f.unlink(missing_ok=True)
                elif f.is_dir():
                    f.rmdir()
            old.rmdir()
        except Exception:
            pass


def inventory_guides(img: Any, cursor: Optional[Tuple[int, int]]) -> List[RegionRec]:
    """物品栏 ROI 示意框（左右仓、命中侧、角标、说明框），供调试图叠画。失败返回空。"""
    try:
        from . import inventory_panel
        from .cell_grid import cell_box
    except Exception:
        return []
    W, H = img.size
    size = (W, H)
    out: List[RegionRec] = []

    def add(label: str, box: Sequence[int], *, kind: str, used: bool = False) -> None:
        if box[2] - box[0] < 2 or box[3] - box[1] < 2:
            return
        out.append(
            RegionRec(
                label=label,
                stage="inventory",
                box=(int(box[0]), int(box[1]), int(box[2]), int(box[3])),
                used=used,
                kind=kind,
            )
        )

    try:
        from ..core import screen_regions

        lg = screen_regions.px("inventory.left.grid", inventory_panel.LEFT_GRID, size)
        rg = screen_regions.px_first(
            ("inventory.right.grid", "count.grid"),
            inventory_panel.RIGHT_GRID,
            size,
        )
        add("inventory.left.grid", lg, kind="guide")
        add("inventory.right.grid", rg, kind="guide")
        tip = screen_regions.px_first(
            ("inventory.tooltip", "count.tooltip"),
            inventory_panel.TOOLTIP,
            size,
        )
        add("inventory.tooltip", tip, kind="guide")
    except Exception:
        pass

    panel = None
    if cursor is not None:
        try:
            panel = inventory_panel.resolve(cursor, size)
        except Exception:
            panel = None
    if panel is not None:
        add(f"panel.{panel.side}.grid", panel.grid, kind="panel", used=True)
        if panel.scrollbar is not None:
            add(f"panel.{panel.side}.scrollbar", panel.scrollbar, kind="panel")
        if panel.page is not None:
            add(f"panel.{panel.side}.page", panel.page, kind="panel")

    if cursor is not None:
        try:
            cell = cell_box(img, (int(cursor[0]), int(cursor[1])))
        except Exception:
            cell = None
        if cell is not None:
            add("cell_box", cell, kind="cell", used=True)
            try:
                q = inventory_panel.map_cell_roi(
                    cell, inventory_panel.cell_badge_frac("quality"), size
                )
                n = inventory_panel.map_cell_roi(
                    cell, inventory_panel.cell_badge_frac("stack"), size
                )
                add("cell.quality", q, kind="badge")
                add("cell.stack", n, kind="badge")
            except Exception:
                pass
    return out


def _draw_overlay(
    img: Any,
    attempts: List[RegionRec],
    extras: List[RegionRec],
    guides: Optional[List[RegionRec]] = None,
) -> Any:
    from PIL import ImageDraw, ImageFont

    rgb = img.convert("RGB")
    half = rgb.resize((max(1, rgb.width // 2), max(1, rgb.height // 2)))
    draw = ImageDraw.Draw(half)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    def _box(b: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        return (b[0] // 2, b[1] // 2, b[2] // 2, b[3] // 2)

    def _tag(
        bb: Tuple[int, int, int, int], text: str, color: Tuple[int, int, int]
    ) -> None:
        if font is not None:
            draw.text((bb[0] + 2, max(0, bb[1] - 10)), text, fill=color, font=font)
        else:
            draw.text((bb[0] + 2, max(0, bb[1] - 10)), text, fill=color)

    # 先画 inventory 示意（底层），再画 OCR 尝试框
    for g in guides or []:
        kind = g.kind or ""
        if kind == "panel":
            color = (255, 200, 40)  # 黄：光标命中的仓
        elif kind == "badge":
            color = (255, 80, 80) if "quality" in g.label else (40, 220, 100)
        elif kind == "cell":
            color = (255, 255, 255)
        else:
            color = (200, 140, 40)  # 橙：左右仓/说明框参考
        bb = _box(g.box)
        draw.rectangle(bb, outline=color, width=2)
        _tag(bb, g.label, color)

    for a in attempts:
        color = (0, 200, 0) if a.used else (140, 140, 140)
        bb = _box(a.box)
        draw.rectangle(bb, outline=color, width=2)
        tag = a.label
        if font is not None:
            draw.text((bb[0] + 2, bb[1] + 2), tag, fill=color, font=font)
        else:
            draw.text((bb[0] + 2, bb[1] + 2), tag, fill=color)
    for e in extras:
        color = (80, 160, 255)
        bb = _box(e.box)
        draw.rectangle(bb, outline=color, width=2)
        _tag(bb, e.kind or e.label, color)
    return half


def _write_dump(
    *,
    task: str,
    out_dir: Path,
    img: Any,
    cursor: Optional[Tuple[int, int]],
    ok: bool,
    where: str,
    stop_reason: str,
    name: Any,
    note: str,
    attempts: List[RegionRec],
    extras: List[RegionRec],
    guides: Optional[List[RegionRec]] = None,
) -> None:
    from ..core import paths

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        for i, a in enumerate(attempts):
            if a.crop is None:
                continue
            fn = out_dir / f"attempt_{i:02d}_{safe_label(a.label)}.png"
            try:
                a.crop.save(fn)
            except Exception:
                pass
        for i, e in enumerate(extras):
            if e.crop is None:
                continue
            kind = safe_label(e.kind or e.label)
            fn = out_dir / f"extra_{i:02d}_{kind}.png"
            try:
                e.crop.save(fn)
            except Exception:
                pass
        guides = list(guides or [])
        try:
            overlay = _draw_overlay(img, attempts, extras, guides)
            overlay.save(out_dir / "final_overlay.jpg", quality=80)
        except Exception:
            pass
        W, H = img.size
        meta = {
            "task": task,
            "ok": bool(ok),
            "where": where or "",
            "stop_reason": stop_reason or "",
            "screen": [int(W), int(H)],
            "cursor": [int(cursor[0]), int(cursor[1])] if cursor else None,
            "attempts": [
                {
                    "label": a.label,
                    "stage": a.stage,
                    "box": list(a.box),
                    "used": bool(a.used),
                }
                for a in attempts
            ],
            "extras": [
                {
                    "label": e.label,
                    "stage": e.stage,
                    "box": list(e.box),
                    "used": bool(e.used),
                    "kind": e.kind,
                }
                for e in extras
            ],
            "inventory": [
                {
                    "label": g.label,
                    "box": list(g.box),
                    "kind": g.kind,
                    "used": bool(g.used),
                }
                for g in guides
            ],
        }
        if name is not None:
            meta["name"] = list(name) if isinstance(name, (tuple, list)) else name
        if note:
            meta["note"] = note
        (out_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        root = paths.shots("debug") / task
        _prune(root, KEEP)
    except Exception as e:
        from ..core import day_logs

        day_logs.write("debug", f"[WARN] [识别] 调试截图写入失败：{e!r}")


def flush(
    img: Any,
    cursor: Optional[Tuple[int, int]],
    *,
    ok: bool,
    where: str = "",
    stop_reason: str = "",
    name: Any = None,
    note: str = "",
) -> Optional[Path]:
    """把当前线程会话落盘并清空；非调试或无会话则空操作。返回将写入的目录（异步时目录可能尚未写完）。"""
    sess: Optional[Session] = getattr(_tls, "session", None)
    _tls.session = None
    if sess is None or img is None:
        return None
    if stop_reason:
        sess.stop_reason = stop_reason
    elif not sess.stop_reason and where:
        sess.stop_reason = where
    # 标 used
    if where:
        for a in sess.attempts:
            a.used = a.label == where
        if where == "整屏" and not any(a.label == "整屏" for a in sess.attempts):
            W, H = img.size
            full_crop = None
            try:
                full_crop = img.copy()
            except Exception:
                pass
            sess.add_attempt("整屏", "full", (0, 0, W, H), full_crop, used=True)

    count_stamp = _count_bound()
    if count_stamp:
        task = "count"
        cell = _next_cell()
        from ..core import paths

        out_dir = paths.shots("debug") / "count" / count_stamp / f"cell_{cell:02d}"
    else:
        task = "hover"
        from ..core import paths

        out_dir = paths.shots("debug") / "hover" / _stamp()

    # 主线程先拷整图，避免识别线程继续改图
    try:
        img_copy = img.copy()
    except Exception:
        img_copy = img
    attempts = list(sess.attempts)
    extras = list(sess.extras)
    reason = sess.stop_reason
    try:
        guides = inventory_guides(img_copy, cursor)
    except Exception:
        guides = []

    def _run() -> None:
        _write_dump(
            task=task,
            out_dir=out_dir,
            img=img_copy,
            cursor=cursor,
            ok=ok,
            where=where or "",
            stop_reason=reason,
            name=name,
            note=note,
            attempts=attempts,
            extras=extras,
            guides=guides,
        )

    if _SYNC:
        _run()
    else:
        threading.Thread(target=_run, daemon=True, name="debug-shots").start()
    return out_dir
