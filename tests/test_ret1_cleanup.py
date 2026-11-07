"""RET-1 退役清理：远程关、压缩包版、旧文件不清理、Velopack 回滚收窄"""

import os
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_no_off_calls_left():
    for sub in ("runtime", "app/inputs", "tasks"):
        for p in (ROOT / "astral_toolkit" / sub).rglob("*.py"):
            text = p.read_text(encoding="utf-8")
            assert "_off(" not in text, p


def test_update_check_remote_kill_gone():
    from astral_toolkit.update import update_check as C

    for name in ("disabled", "refresh_kill", "KILL_FILE", "FEATURES"):
        assert not hasattr(C, name), name


def test_no_update_upgrade_import():
    bad = "update." + "upgrade"
    files = list((ROOT / "astral_toolkit").rglob("*.py")) + list(
        (ROOT / "tools").rglob("*.py")
    )
    for p in files:
        assert bad not in p.read_text(encoding="utf-8"), p


def test_feedback_and_train_enabled_only_settings(monkeypatch):
    from astral_toolkit.core import settings
    from astral_toolkit.system import feedback_up, train_data

    old = os.environ.pop("AT_FEEDBACK_OFF", None)
    try:
        monkeypatch.setattr(settings, "load", lambda: {"feedback_upload": True})
        assert feedback_up.enabled()
        monkeypatch.setattr(settings, "load", lambda: {"feedback_upload": False})
        assert not feedback_up.enabled()

        monkeypatch.setattr(settings, "load", lambda: {"feedback_upload": True})
        os.environ["AT_FEEDBACK_OFF"] = "1"
        assert not feedback_up.enabled()

        os.environ.pop("AT_FEEDBACK_OFF", None)
        monkeypatch.setattr(settings, "load", lambda: {"train_upload": True})
        assert train_data.enabled()
        monkeypatch.setattr(settings, "load", lambda: {"train_upload": False})
        assert not train_data.enabled()
    finally:
        if old is None:
            os.environ.pop("AT_FEEDBACK_OFF", None)
        else:
            os.environ["AT_FEEDBACK_OFF"] = old


def test_upgrade_check_velopack_only_prev(monkeypatch):
    from astral_toolkit.tasks.system import upgrade as U
    from astral_toolkit.update import version, vpk

    monkeypatch.setattr(vpk, "installed", lambda: True)
    monkeypatch.setattr(version, "VERSION", "2.0.0")
    monkeypatch.setattr(
        vpk,
        "check",
        lambda rollback=False: (None, "1.0.0" if rollback else "", "测试源"),
    )
    monkeypatch.setattr(U, "_online_info", lambda force=False: None)
    monkeypatch.setattr(U, "_online", {})
    r = U.upgrade_check(online=True)
    assert "found" not in r
    assert [x["path"] for x in r["older"]] == [U.VPK_PREV]


def test_upgrade_rollback_rejects_zip_path():
    from astral_toolkit.tasks.system import upgrade as U

    assert U.upgrade_rollback(path="x.zip") == {"error": "只能回滚到安装版的上一版本"}


def test_upgrade_online_uses_vpk_install(monkeypatch):
    from astral_toolkit.app import server
    from astral_toolkit.tasks.system import upgrade as U
    from astral_toolkit.update import vpk

    class Q:
        def set(self):
            return None

    called = []
    monkeypatch.setattr(vpk, "installed", lambda: True)
    monkeypatch.setattr(
        vpk, "install", lambda progress=None: called.append(True) or "9.0.0"
    )
    monkeypatch.setattr(U.time, "sleep", lambda *_: None)
    monkeypatch.setattr(server, "QUIT", Q())
    r = U._online_task()
    assert called and r["to"] == "9.0.0"


def test_old_files_not_cleaned(monkeypatch, tmp_path):
    import importlib

    from astral_toolkit.core import paths
    from astral_toolkit.tasks.system import upgrade as U
    from astral_toolkit.tasks.system.common import StatusSources

    S = importlib.import_module("astral_toolkit.tasks.system.status")

    user = tmp_path / "userdata"
    (user / "upgrade" / "旧目录").mkdir(parents=True)
    (user / "updates").mkdir(parents=True)
    kill = user / "killswitch.json"
    kill.write_text("{}", encoding="utf-8")
    oldzip = user / "updates" / "Dubhe_1.0.zip"
    oldzip.write_bytes(b"old")

    monkeypatch.setattr(paths, "USER", user)
    from astral_toolkit.update import update_check as C

    monkeypatch.setattr(C, "UPDATES", user / "updates")
    monkeypatch.setattr(C, "enabled", lambda: False)
    monkeypatch.setattr(U, "_online", {})

    sources = StatusSources(
        live_running=lambda: False,
        live_paused=lambda: False,
        nav_target_label=lambda: "",
        nav_space_mode=lambda: False,
        pos_reader_active=lambda: False,
        pos_label=lambda: (0.0, None),
        pos_system=lambda: (0.0, ""),
        game_events_last=lambda: {},
        results=types.SimpleNamespace(get=lambda slot: None),
    )
    monkeypatch.setattr(S, "_gridtext_status", lambda: {})
    monkeypatch.setattr(S, "WIN", False)

    assert C.check(force=True) is None
    U.upgrade_check()
    S.status(sources)
    assert kill.exists()
    assert (user / "upgrade" / "旧目录").is_dir()
    assert oldzip.exists()
