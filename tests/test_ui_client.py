"""UI-K1：前端 store / 连接层与后端真实序列的一致性测试。"""

import importlib
import json
import queue
import shutil
import subprocess
from pathlib import Path
from typing import Any

from tests.minipytest import Skip

ROOT = Path(__file__).resolve().parents[1]


def _find_node() -> Path | None:
    try:
        module = importlib.import_module("nodejs_wheel")
    except Exception:
        module = None
    if module is not None:
        base = Path(str(getattr(module, "__file__", ""))).resolve().parent
        for rel in ("node.exe", "bin/node.exe", "bin/node", "node"):
            candidate = base / rel
            if candidate.is_file():
                return candidate
    found = shutil.which("node")
    return Path(found) if found else None


def _require_node() -> Path:
    node = _find_node()
    if node is None:
        raise Skip("找不到 node，跳过前端测试")
    return node


def _run_node(node: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(node), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


def _assert_ok(proc: subprocess.CompletedProcess[str]) -> None:
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
    assert proc.returncode == 0, "node 返回码非 0"


def _reset(monkeypatch: Any) -> Any:
    from astral_toolkit.app import http_server, ui_stream

    ui_stream.reset_for_tests()
    monkeypatch.setattr(ui_stream, "read_switches", lambda: {})
    ui_stream._QUEUE_MAX = 2000
    ui_stream.ENDED_MAX = 256
    http_server.UI_HEARTBEAT_INTERVAL = 5.0
    return ui_stream


def _subscribe(ui: Any) -> tuple[dict[str, Any], Any]:
    hello, q = ui.subscribe(maxsize=1000)
    assert q is not None
    return hello, q


def _drain(q: Any) -> list[dict[str, Any]]:
    messages = []
    while True:
        try:
            messages.append(q.get_nowait())
        except queue.Empty:
            break
    return messages


def _run_replay(node: Path, tmp_path: Any, steps: list[dict[str, Any]]) -> Any:
    path = tmp_path / "ui_fixture.json"
    path.write_text(json.dumps(steps, ensure_ascii=False), encoding="utf-8")
    proc = _run_node(node, ["tests/js/replay.mjs", str(path)])
    _assert_ok(proc)
    return json.loads(proc.stdout)


def test_ui_client_node_suite() -> None:
    node = _require_node()
    files = sorted(str(f) for f in (ROOT / "tests" / "js").glob("*.test.mjs"))
    proc = _run_node(node, ["--test", *files])
    _assert_ok(proc)


def test_ui_client_replay_normal_lifecycle(monkeypatch: Any, tmp_path: Any) -> None:
    node = _require_node()
    ui = _reset(monkeypatch)
    hello, q = _subscribe(ui)
    snap0 = ui.snapshot(hello["conn"])

    ui.publish_ui(
        "ui.activity",
        {
            "activity": {
                "activity_id": "mining:1",
                "kind": "mining",
                "state": "running",
                "title": "挖矿",
            }
        },
    )
    ui.publish_ui(
        "ui.activity",
        {
            "activity": {
                "activity_id": "mining:1",
                "kind": "mining",
                "state": "running",
                "title": "挖矿更新",
            }
        },
    )
    end_seq = ui.publish_ui(
        "ui.activity_end",
        {"activity_id": "mining:1", "end_reason": "done"},
    )
    messages = _drain(q)

    steps = [
        {"method": "onHello", "msg": hello},
        {"method": "onSnapshot", "snap": snap0},
    ]
    steps.extend({"method": "onMessage", "msg": item} for item in messages)
    view = _run_replay(node, tmp_path, steps)

    assert view["phase"] == "live"
    assert view["watermark"] == end_seq
    assert view["activities"] == []
    assert view["ended"] == ["mining:1"]
    assert len(view["lastEnds"]) == 1
    assert view["lastEnds"][0]["activity_id"] == "mining:1"
    assert view["lastEnds"][0]["end_reason"] == "done"

    end_msg = next(item for item in messages if item["kind"] == "ui.activity_end")
    assert view["lastEnds"][0]["summary_notice_id"] == end_msg["summary_notice_id"]
    assert any(
        item["notice_id"] == end_msg["summary_notice_id"] for item in view["notices"]
    )
    ui.unsubscribe(q)


def test_ui_client_replay_rejects_late_snapshot(
    monkeypatch: Any, tmp_path: Any
) -> None:
    node = _require_node()
    ui = _reset(monkeypatch)
    hello, q = _subscribe(ui)
    snap0 = ui.snapshot(hello["conn"])

    ui.publish_ui(
        "ui.activity",
        {
            "activity": {
                "activity_id": "update:1",
                "kind": "update",
                "state": "running",
                "title": "更新",
            }
        },
    )
    first = _drain(q)

    last_seq = ui.publish_ui(
        "ui.notice",
        {
            "notice": {
                "notice_id": "late:notice",
                "level": "info",
                "dismissed": False,
            }
        },
    )
    second = _drain(q)

    steps = [
        {"method": "onHello", "msg": hello},
        {"method": "onSnapshot", "snap": snap0},
    ]
    steps.extend({"method": "onMessage", "msg": item} for item in first)
    steps.append({"method": "onSnapshot", "snap": snap0})
    steps.extend({"method": "onMessage", "msg": item} for item in second)
    view = _run_replay(node, tmp_path, steps)

    assert view["phase"] == "live"
    assert view["watermark"] == last_seq
    assert [item["activity_id"] for item in view["activities"]] == ["update:1"]
    assert [item["notice_id"] for item in view["notices"]] == ["late:notice"]
    ui.unsubscribe(q)


def test_ui_client_replay_fills_gap_from_snapshot(
    monkeypatch: Any, tmp_path: Any
) -> None:
    node = _require_node()
    ui = _reset(monkeypatch)
    hello, q = _subscribe(ui)
    snap0 = ui.snapshot(hello["conn"])

    ui.publish_ui(
        "ui.activity",
        {
            "activity": {
                "activity_id": "mining:1",
                "kind": "mining",
                "state": "running",
                "title": "采矿 1",
            }
        },
    )
    _drain(q)
    snap1 = ui.snapshot(hello["conn"])
    assert snap1["ui_seq"] == 1

    ui.publish_ui(
        "ui.activity",
        {
            "activity": {
                "activity_id": "mining:2",
                "kind": "mining",
                "state": "running",
                "title": "采矿 2",
            }
        },
    )
    last_seq = ui.publish_ui(
        "ui.notice",
        {
            "notice": {
                "notice_id": "gap:notice",
                "level": "info",
                "dismissed": False,
            }
        },
    )
    messages = _drain(q)
    msg_b = next(item for item in messages if item["kind"] == "ui.activity")
    msg_c = next(item for item in messages if item["kind"] == "ui.notice")

    steps = [
        {"method": "onHello", "msg": hello},
        {"method": "onSnapshot", "snap": snap0},
        {"method": "onMessage", "msg": msg_c},
        {"method": "onMessage", "msg": msg_b},
        {"method": "onSnapshot", "snap": snap1},
    ]
    view = _run_replay(node, tmp_path, steps)

    assert view["phase"] == "live"
    assert view["watermark"] == last_seq
    assert [item["activity_id"] for item in view["activities"]] == [
        "mining:1",
        "mining:2",
    ]
    assert [item["notice_id"] for item in view["notices"]] == ["gap:notice"]
    ui.unsubscribe(q)


def test_ui_client_replay_instance_change_clears(
    monkeypatch: Any, tmp_path: Any
) -> None:
    node = _require_node()
    ui = _reset(monkeypatch)
    hello, q = _subscribe(ui)
    snap0 = ui.snapshot(hello["conn"])

    ui.publish_ui(
        "ui.activity",
        {
            "activity": {
                "activity_id": "old:1",
                "kind": "update",
                "state": "running",
                "title": "旧实例",
            }
        },
    )
    ui.publish_ui(
        "ui.activity_end",
        {"activity_id": "old:1", "end_reason": "done"},
    )
    messages = _drain(q)

    steps = [
        {"method": "onHello", "msg": hello},
        {"method": "onSnapshot", "snap": snap0},
    ]
    steps.extend({"method": "onMessage", "msg": item} for item in messages)

    ui.reset_for_tests()
    second = "ui-instance-second"
    monkeypatch.setattr(ui, "INSTANCE_ID", second)
    monkeypatch.setattr(ui, "instance_id", second)
    hello2, q2 = _subscribe(ui)
    snap2 = ui.snapshot(hello2["conn"])
    assert hello2["instance_id"] == second
    assert snap2["ended"] == []

    steps.append({"method": "onHello", "msg": hello2})
    steps.append({"method": "onSnapshot", "snap": snap2})
    view = _run_replay(node, tmp_path, steps)

    assert view["phase"] == "live"
    assert view["instanceId"] == second
    assert view["watermark"] == snap2["ui_seq"]
    assert view["activities"] == []
    assert view["tiles"] == []
    assert view["notices"] == []
    assert view["ended"] == []
    assert view["lastEnds"] == []
    ui.unsubscribe(q2)
