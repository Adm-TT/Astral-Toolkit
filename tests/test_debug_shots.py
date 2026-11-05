"""debug_mode 识别区域调试落盘（docs/superpowers/specs/2026-11-04-debug-region-shots.md）"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image


def test_safe_label_strips_percent():
    from astral_toolkit.trade.debug_shots import safe_label

    assert safe_label("30-50%@title") == "30-50@title"
    assert safe_label("整屏") == "整屏"


def test_flush_off_writes_nothing(monkeypatch, tmp_path):
    from astral_toolkit.core import paths, settings
    from astral_toolkit.trade import debug_shots

    monkeypatch.setattr(paths, "SHOTS", tmp_path / "shots")
    monkeypatch.setattr(settings, "load", lambda: {"debug_mode": False})
    monkeypatch.setattr(debug_shots, "_SYNC", True)
    debug_shots.begin_if_debug()
    out = debug_shots.flush(Image.new("RGB", (40, 30), "black"), (10, 10), ok=False)
    assert out is None
    assert not (tmp_path / "shots" / "debug").exists() or not any(
        (tmp_path / "shots" / "debug").rglob("*")
    )


def test_hover_dump_writes_attempts_overlay_meta(monkeypatch, tmp_path):
    from astral_toolkit.core import paths, settings
    from astral_toolkit.trade import debug_shots

    monkeypatch.setattr(paths, "SHOTS", tmp_path / "shots")
    monkeypatch.setattr(settings, "load", lambda: {"debug_mode": True})
    monkeypatch.setattr(debug_shots, "_SYNC", True)
    debug_shots.unbind_count_run()

    sess = debug_shots.begin_if_debug()
    assert sess is not None
    img = Image.new("RGB", (100, 80), (20, 20, 20))
    crop = img.crop((10, 20, 50, 40))
    sess.add_attempt("30-50%@title", "title", (10, 20, 50, 40), crop)
    sess.add_attempt(
        "30-50%@body", "body", (10, 20, 50, 60), img.crop((10, 20, 50, 60))
    )
    sess.stop_reason = "库精确"

    out = debug_shots.flush(
        img,
        (40, 30),
        ok=True,
        where="30-50%@title",
        name=("塔兰导电石", "Taranite"),
        note="unit",
    )
    assert out is not None
    assert out.is_dir()
    assert (out / "meta.json").is_file()
    assert (out / "final_overlay.jpg").is_file()
    attempts = sorted(out.glob("attempt_*.png"))
    assert len(attempts) == 2
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert meta["task"] == "hover"
    assert meta["ok"] is True
    assert meta["where"] == "30-50%@title"
    assert meta["stop_reason"] == "库精确"
    assert meta["screen"] == [100, 80]
    assert meta["cursor"] == [40, 30]
    assert len(meta["attempts"]) == 2
    assert meta["attempts"][0]["used"] is True
    assert meta["attempts"][1]["used"] is False
    assert meta["name"] == ["塔兰导电石", "Taranite"]


def test_count_run_cells_share_stamp(monkeypatch, tmp_path):
    from astral_toolkit.core import paths, settings
    from astral_toolkit.trade import debug_shots

    monkeypatch.setattr(paths, "SHOTS", tmp_path / "shots")
    monkeypatch.setattr(settings, "load", lambda: {"debug_mode": True})
    monkeypatch.setattr(debug_shots, "_SYNC", True)

    stamp = debug_shots.bind_count_run("20261104_120000_001")
    assert stamp == "20261104_120000_001"
    img = Image.new("RGB", (64, 64), "navy")
    for i in range(2):
        sess = debug_shots.begin_if_debug()
        assert sess is not None
        sess.add_attempt(
            "30-50%@title", "title", (0, 0, 20, 20), img.crop((0, 0, 20, 20))
        )
        debug_shots.flush(img, (8, 8), ok=i == 0, where="30-50%@title")
    debug_shots.unbind_count_run()

    root = tmp_path / "shots" / "debug" / "count" / stamp
    assert (root / "cell_00" / "meta.json").is_file()
    assert (root / "cell_01" / "meta.json").is_file()
    m0 = json.loads((root / "cell_00" / "meta.json").read_text(encoding="utf-8"))
    m1 = json.loads((root / "cell_01" / "meta.json").read_text(encoding="utf-8"))
    assert m0["task"] == "count" and m0["ok"] is True
    assert m1["ok"] is False


def test_prune_keeps_five(monkeypatch, tmp_path):
    from astral_toolkit.core import paths, settings
    from astral_toolkit.trade import debug_shots

    monkeypatch.setattr(paths, "SHOTS", tmp_path / "shots")
    monkeypatch.setattr(settings, "load", lambda: {"debug_mode": True})
    monkeypatch.setattr(debug_shots, "_SYNC", True)
    debug_shots.unbind_count_run()

    hover = tmp_path / "shots" / "debug" / "hover"
    hover.mkdir(parents=True)
    for i in range(5):
        d = hover / f"20261104_10000{i}_000"
        d.mkdir()
        (d / "meta.json").write_text("{}", encoding="utf-8")

    sess = debug_shots.begin_if_debug()
    assert sess is not None
    img = Image.new("RGB", (32, 32), "gray")
    sess.add_attempt("整屏", "full", (0, 0, 32, 32), img)
    debug_shots.flush(img, None, ok=False, where="整屏", stop_reason="未识别")

    dirs = sorted(p.name for p in hover.iterdir() if p.is_dir())
    assert len(dirs) == 5


def test_inspect_item_dumps_when_debug(monkeypatch, tmp_path):
    """开 debug_mode 时 inspect_item 结束会落 hover dump（含 attempt）。"""
    from astral_toolkit import ocr
    from astral_toolkit.core import paths, settings
    from astral_toolkit.ocr import OcrToken
    from astral_toolkit.trade import debug_shots, inspector

    monkeypatch.setattr(paths, "SHOTS", tmp_path / "shots")
    monkeypatch.setattr(settings, "load", lambda: {"debug_mode": True})
    monkeypatch.setattr(debug_shots, "_SYNC", True)
    debug_shots.unbind_count_run()

    monkeypatch.setattr(
        inspector,
        "get_hover_regions",
        lambda cursor, width: [(0.3, 0.0, 0.5, 1.0, "30-50%")],
    )
    monkeypatch.setattr(
        inspector,
        "get_stage_regions",
        lambda regions, W, H: [
            ((0, 0, 40, 20), "30-50%@title", "title", True),
        ],
    )
    tok_zh = OcrToken(text="塔兰导电石", confidence=99, box=(10, 10, 80, 16))
    tok_en = OcrToken(text="Taranite", confidence=99, box=(10, 30, 80, 16))
    monkeypatch.setattr(ocr, "recognize", lambda *a, **k: [tok_zh, tok_en])
    monkeypatch.setattr(
        inspector, "tooltip_pick", lambda *a, **k: (("塔兰导电石", "Taranite"), True)
    )
    monkeypatch.setattr(
        inspector, "_strong_canonical", lambda name: ("塔兰导电石", "Taranite")
    )
    monkeypatch.setattr(inspector, "_is_mineral", lambda *a, **k: True)

    img = Image.new("RGB", (200, 200), (30, 30, 30))
    res = inspector.inspect_item(img, (80, 100))
    assert res is not None
    hover_root = tmp_path / "shots" / "debug" / "hover"
    runs = [p for p in hover_root.iterdir() if p.is_dir()]
    assert len(runs) == 1
    meta = json.loads((runs[0] / "meta.json").read_text(encoding="utf-8"))
    assert meta["ok"] is True
    assert meta["where"] == "30-50%@title"
    assert meta["stop_reason"] == "库精确"
    assert Path(runs[0] / "attempt_00_30-50@title.png").is_file()
