"""在线更新：读版本说明、安装程序下载、版本号比较（不联网：换掉 _open）"""

import hashlib
import io
import json
import threading
from pathlib import Path


class _Resp(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


def _setup(monkeypatch, tmp_path, pages):
    from astral_toolkit.update import update_check as C

    monkeypatch.setattr(C, "GITHUB", "at/at")
    monkeypatch.setattr(C, "UPDATES", tmp_path / "updates")
    monkeypatch.setattr(
        C, "_state", {"at": 0.0, "info": None, "error": "", "lock": threading.Lock()}
    )
    calls = []

    def fake_open(url, timeout):
        calls.append(url)
        v = pages.get(url)
        if isinstance(v, Exception) or v is None:
            raise v or OSError("连不上")
        return _Resp(v)

    monkeypatch.setattr(C, "_open", fake_open)
    return C, calls


def _installer_manifest(exe, version="9.0.0", sha=None):
    data = exe.read_bytes()
    return {
        "version": version,
        "notes": ["新功能"],
        "installer": {
            "file": exe.name,
            "size": len(data),
            "sha256": sha or hashlib.sha256(data).hexdigest(),
            "urls": [
                "https://dl.astral-trade.com/releases/v9.0.0/" + exe.name,
                "https://github.com/at/at/releases/download/v9.0.0/" + exe.name,
            ],
        },
    }


def test_offline_returns_none(monkeypatch, tmp_path):
    C, _ = _setup(monkeypatch, tmp_path, {})
    assert C.check(force=True) is None and C.last_error()


def test_parse_installer_and_source_retired(tmp_path):
    from astral_toolkit.update import update_check as C

    exe = tmp_path / "AT_Setup_9.0.0.exe"
    exe.write_bytes(b"MZ setup")
    m = _installer_manifest(exe)
    vp = C.parse(json.dumps(m), velopack=True)
    assert vp["version"] == "9.0.0" and vp["urls"] == []
    fz = C.parse(json.dumps(m), frozen=True, velopack=False)
    assert fz["file"] == exe.name and fz["installer"]
    try:
        C.parse(json.dumps(m), frozen=False, velopack=False)
        assert False
    except C.NoPackage:
        pass
    for bad in (
        {**m, "installer": {**m["installer"], "file": "virus.exe"}},
        {**m, "installer": {**m["installer"], "urls": ["http://evil.com/a.exe"]}},
        {**m, "installer": {**m["installer"], "sha256": "123"}},
        {"version": "x.y"},
    ):
        try:
            C.parse(json.dumps(bad), frozen=True, velopack=False)
            assert False, bad
        except ValueError:
            pass


def test_download_checks_sha_and_uses_mirror(monkeypatch, tmp_path):

    exe = tmp_path / "AT_Setup_9.0.0.exe"
    exe.write_bytes(b"MZ setup")
    data = exe.read_bytes()
    m = _installer_manifest(exe)
    updates = tmp_path / "updates"
    updates.mkdir()
    old_zip = updates / "Dubhe_1.0.zip"
    old_zip.write_bytes(b"old")
    C, _ = _setup(
        monkeypatch,
        tmp_path,
        {
            m["installer"]["urls"][0]: data[:-2] + b"xx",
            m["installer"]["urls"][1]: data,
        },
    )
    out = C.download(
        C.parse(json.dumps(m), frozen=True, velopack=False),
        progress=lambda *_: None,
    )
    assert out.read_bytes() == data and old_zip.exists()
    assert not list((tmp_path / "updates").glob("*.part"))
    bad = _installer_manifest(exe, sha="0" * 64)
    C, _ = _setup(monkeypatch, tmp_path, {u: data for u in bad["installer"]["urls"]})
    out.unlink()
    try:
        C.download(
            C.parse(json.dumps(bad), frozen=True, velopack=False),
            progress=lambda *_: None,
        )
        assert False
    except ValueError as e:
        assert "下载失败" in str(e)
    assert not list((tmp_path / "updates").glob("AT_Setup_*"))


def test_make_manifest_with_installer(monkeypatch, tmp_path):
    from astral_toolkit.update import update_check as C

    exe = tmp_path / "AT_Setup_9.0.0.exe"
    exe.write_bytes(b"MZ setup")
    _setup(monkeypatch, tmp_path, {})
    m = C.make_manifest(notes=["x"], installer=exe)
    assert m["installer"]["file"] == exe.name and m["installer"]["size"] == 8
    assert m["installer"]["urls"][:3] == [
        "https://dl.astral-trade.com/releases/v9.0.0/AT_Setup_9.0.0.exe",
        "https://at-dl-1323647399.cos.ap-guangzhou.myqcloud.com/releases/v9.0.0/AT_Setup_9.0.0.exe",
        "https://github.com/at/at/releases/download/v9.0.0/AT_Setup_9.0.0.exe",
    ]
    assert m["kill_rev"] == C.LEGACY_KILL_REV
    assert m["disabled"] == C.LEGACY_DISABLED
    assert not {"file", "size", "sha256", "urls"} & set(m)
    assert C.parse(json.dumps(m), frozen=True, velopack=False)["version"] == "9.0.0"
    wrong = tmp_path / "AT_Setup_8.0.0.exe"
    wrong.write_bytes(b"MZ")
    try:
        C.make_manifest(notes=[], version="9.0.0", installer=wrong)
        assert False
    except ValueError:
        pass


def test_manifest_version_only():
    from astral_toolkit.update import update_check as C

    m = C.make_manifest(notes=["新功能"], version="9.0.0")
    assert m["version"] == "9.0.0" and m["notes"] == ["新功能"]
    assert m["kill_rev"] == C.LEGACY_KILL_REV
    assert m["disabled"] == C.LEGACY_DISABLED
    assert not {"file", "size", "sha256", "urls", "installer"} & set(m)
    vp = C.parse(json.dumps(m), velopack=True)
    assert vp["version"] == "9.0.0" and vp["notes"] == ["新功能"] and vp["urls"] == []
    for frozen in (True, False):
        try:
            C.parse(json.dumps(m), frozen=frozen, velopack=False)
            assert False
        except C.NoPackage:
            pass
    for bad in ("", "x.y", "0.0.0"):
        try:
            C.make_manifest(notes=[], version=bad)
            assert False
        except ValueError:
            pass


def test_make_manifest_tool_installer_only(monkeypatch, tmp_path):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    import make_manifest as T

    exe = tmp_path / "AT_Setup_9.0.0.exe"
    exe.write_bytes(b"MZ setup")
    _setup(monkeypatch, tmp_path, {})
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)
    assert T.main(["--installer", str(exe), "新功能"]) == 0
    m = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert m["version"] == "9.0.0" and "file" not in m and m["notes"] == ["新功能"]
    assert m["kill_rev"] == 1793426539
    assert T.main(["--fresh", "x"]) == 1
    assert T.main(["Dubhe_9.0.0.zip", "x"]) == 1
    assert T.main(["--version"]) == 1


def test_make_manifest_tool_version_only(monkeypatch, tmp_path):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    import make_manifest as T  # pyright: ignore[reportMissingImports]

    _setup(monkeypatch, tmp_path, {})
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)
    out = tmp_path / "out"
    assert T.main(["--version", "9.0.0", "--out", str(out), "新功能"]) == 0
    m = json.loads((out / "latest.json").read_text(encoding="utf-8"))
    assert m["version"] == "9.0.0" and m["notes"] == ["新功能"]
    assert not {"file", "installer", "urls"} & set(m)
    assert m["disabled"] == json.loads(
        json.dumps(
            [
                {
                    "feature": "feedback",
                    "versions": "<=1.1.1",
                    "why": "请升级到 1.1.2（已删除全部模拟按键）",
                },
                {
                    "feature": "train",
                    "versions": "<=1.1.1",
                    "why": "请升级到 1.1.2（已删除全部模拟按键）",
                },
                {
                    "feature": "nav_marker",
                    "versions": "<=1.1.1",
                    "why": "请升级到 1.1.2（已删除全部模拟按键）",
                },
                {
                    "feature": "radar",
                    "versions": "<=1.1.1",
                    "why": "请升级到 1.1.2（已删除全部模拟按键）",
                },
                {
                    "feature": "scan",
                    "versions": "<=1.1.1",
                    "why": "请升级到 1.1.2（已删除全部模拟按键）",
                },
                {
                    "feature": "item",
                    "versions": "<=1.1.1",
                    "why": "请升级到 1.1.2（已删除全部模拟按键）",
                },
                {
                    "feature": "halo_auto",
                    "versions": "<=1.1.1",
                    "why": "请升级到 1.1.2（已删除全部模拟按键）",
                },
                {
                    "feature": "game_events",
                    "versions": "<=1.1.1",
                    "why": "请升级到 1.1.2（已删除全部模拟按键）",
                },
            ]
        )
    )


def test_beta_sees_same_number_live(monkeypatch, tmp_path):
    from astral_toolkit.update import version

    page = {
        "https://raw.githubusercontent.com/at/at/main/latest.json": json.dumps(
            {"version": "9.0.0", "notes": []}
        ).encode()
    }
    C, _ = _setup(monkeypatch, tmp_path, page)
    monkeypatch.setattr(C.paths, "VELOPACK", True)
    monkeypatch.setattr(C.paths, "FROZEN", False)
    monkeypatch.setattr(version, "current", lambda: (9, 0, 0))
    monkeypatch.setattr(C, "_is_beta", lambda: True)
    assert C.check(force=True)["version"] == "9.0.0"
    monkeypatch.setattr(C, "_is_beta", lambda: False)
    assert C.check(force=True) is None


def test_data_pack_takes_newest_source(monkeypatch, tmp_path):
    import io
    from astral_toolkit.update import data_pack as P
    from astral_toolkit.update import update_check as U

    base = {
        "file": "AT_data_2026.10.27-0100.zip",
        "sha256": "a" * 64,
        "urls": ["https://github.com/x/y/AT_data_2026.10.27-0100.zip"],
    }
    pages = {
        "https://dl.astral-trade.com/data.json": json.dumps(
            dict(base, version="2026.10.26-0100")
        ).encode(),
        "https://raw.githubusercontent.com/at/at/main/data.json": json.dumps(
            dict(base, version="2026.10.27-0100")
        ).encode(),
    }
    monkeypatch.setattr(U, "GITHUB", "at/at")

    def fake(url, timeout):
        if url not in pages:
            raise OSError("连不上")
        return io.BytesIO(pages[url])

    monkeypatch.setattr(U, "_open", fake)
    info, err = P.fetch()
    assert info["version"] == "2026.10.27-0100" and info["source"] == "GitHub"


def test_publish_hk_checks_manifest(tmp_path):
    import sys
    from pathlib import Path

    tools = Path(__file__).resolve().parent.parent / "tools"
    if not (tools / "publish_hk.py").exists():
        from tests.minipytest import skip

        skip("没有 tools/publish_hk.py")
    sys.path.insert(0, str(tools))
    import publish_hk as H

    lj = tmp_path / "latest.json"
    good = {
        "version": "1.0.5",
        "file": "Dubhe_1.0.5.zip",
        "sha256": "a" * 64,
        "urls": ["https://dl.astral-trade.com/releases/v1.0.5/Dubhe_1.0.5.zip"],
        "installer": {
            "file": "AT_Setup_1.0.5.exe",
            "sha256": "b" * 64,
            "urls": ["https://dl.astral-trade.com/releases/v1.0.5/AT_Setup_1.0.5.exe"],
        },
    }
    only_setup = {"version": "1.0.5", "installer": good["installer"]}
    assert [e[0] for e in H.entries(lj, only_setup)] == ["AT_Setup_1.0.5.exe"]
    bad = [
        {},
        good,  # 源码压缩包版已退役（RET-1）：清单里再带压缩包就不发
        {k: v for k, v in good.items() if k != "installer"},
        dict(
            only_setup,
            installer=dict(
                good["installer"],
                urls=["https://dl.astral-trade.com/releases/x;rm/AT_Setup_1.0.5.exe"],
            ),
        ),
        dict(good, urls=["https://dl.astral-trade.com/releases/v1.0.5/$(id).zip"]),
        dict(
            good, urls=["https://dl.astral-trade.com/releases/v1.0.5/Dubhe_1.0.4.zip"]
        ),
        dict(good, urls=["https://dl.astral-trade.com/releases/x;rm/Dubhe_1.0.5.zip"]),
    ]
    for m in bad:
        try:
            H.entries(lj, m)
        except (SystemExit, ValueError):
            continue
        raise AssertionError(m)


def test_import_inno_userdata(monkeypatch, tmp_path):
    import os
    import time
    from astral_toolkit.core import paths

    old, new = tmp_path / "Programs" / "AT" / "userdata", tmp_path / "AT_userdata"
    (old / "logs").mkdir(parents=True)
    (old / "window").mkdir()
    (old / "settings.json").write_text('{"a": 1}', encoding="utf-8")
    (old / "waypoints.json").write_text("old", encoding="utf-8")
    (old / "window_url.txt").write_text("http://x", encoding="utf-8")
    (old / "instance.lock").write_text("", encoding="utf-8")
    (old / "window" / "cache.bin").write_text("x", encoding="utf-8")
    (old / "logs" / "app_log.txt").write_text("log", encoding="utf-8")
    new.mkdir()
    (new / "waypoints.json").write_text("new", encoding="utf-8")
    t = time.time()
    os.utime(old / "waypoints.json", (t - 100, t - 100))
    monkeypatch.setattr(paths, "VELOPACK", True)
    monkeypatch.setattr(paths, "INNO_USER", old)
    monkeypatch.setattr(paths, "USER", new)
    monkeypatch.setattr(paths, "MIGRATED", new / ".migrated_from_inno")
    assert paths.import_inno() == 2
    assert (new / "settings.json").exists() and (new / "logs" / "app_log.txt").exists()
    assert (new / "waypoints.json").read_text(encoding="utf-8") == "new"
    assert not (new / "window_url.txt").exists()
    assert not (new / "instance.lock").exists()
    assert not (new / "window").exists()
    assert (new / ".migrated_from_inno").exists()
    (old / "settings.json").write_text('{"a": 2}', encoding="utf-8")
    assert paths.import_inno() == 0
    monkeypatch.setattr(paths, "VELOPACK", False)
    assert paths.import_inno() == 0


def test_vkey_beta_older_than_live():
    from astral_toolkit.update.version import vkey

    assert vkey("1.1.2-beta.1") < vkey("1.1.2")
    assert vkey("1.1.2-beta.1") < vkey("1.1.2-beta.2") < vkey("1.1.2-beta.10")
    assert vkey("1.1.1") < vkey("1.1.2-beta.1") < vkey("1.1.2")
    assert vkey("1.1.2") == vkey("1.1.2")
    assert vkey("") < vkey("0.0.1")


def _fake_velopack(versions):
    import types

    class Mgr:
        def __init__(self, src, opts):
            self.channel = opts[2]

        def check_for_updates(self):
            v = versions.get(self.channel)
            return (
                types.SimpleNamespace(
                    TargetFullRelease=types.SimpleNamespace(Version=v)
                )
                if v
                else None
            )

        def download_updates(self, info, cb=None):
            pass

        def wait_exit_then_apply_updates(self, *a):
            pass

    return types.SimpleNamespace(
        UpdateOptions=lambda *a: a,
        HttpOptions=lambda *a: a,
        HttpSource=lambda feed, o: feed,
        UpdateManager=Mgr,
    )


def test_vpk_falls_back_to_cos(monkeypatch):
    import sys
    import types
    from astral_toolkit.update import version, vpk

    calls = []

    class Mgr:
        def __init__(self, src, opts):
            self.src = src

        def check_for_updates(self):
            calls.append(("check", self.src))
            if "dl.astral-trade.com" in self.src:
                raise OSError("timed out")
            return types.SimpleNamespace(
                TargetFullRelease=types.SimpleNamespace(Version="99.0.0")
            )

        def download_updates(self, info, cb=None):
            calls.append(("download", self.src))

        def wait_exit_then_apply_updates(self, *a):
            calls.append(("apply", self.src))

    fake = types.SimpleNamespace(
        UpdateOptions=lambda *a: a,
        HttpOptions=lambda *a: a,
        HttpSource=lambda feed, o: feed,
        UpdateManager=Mgr,
    )
    old = sys.modules.get("velopack")
    sys.modules["velopack"] = fake
    monkeypatch.setattr(
        vpk,
        "FEEDS",
        [
            ("https://dl.astral-trade.com/velopack", "AT 服务器"),
            (
                "https://at-dl-1323647399.cos.ap-guangzhou.myqcloud.com/velopack",
                "国内镜像",
            ),
        ],
    )
    monkeypatch.setattr(version, "VERSION", "1.0.0")
    try:
        vpk._last["feed"] = None
        assert vpk.check()[1:] == ("99.0.0", "国内镜像")
        n_hk = sum(1 for k, s in calls if k == "check" and "astral-trade" in s)
        vpk.check()
        assert sum(1 for k, s in calls if k == "check" and "astral-trade" in s) == n_hk
        msgs = []
        assert vpk.install(progress=msgs.append) == "99.0.0"
        vpk._last["feed"] = None
        Mgr.check_for_updates = lambda self: (_ for _ in ()).throw(OSError("timed out"))
        try:
            vpk.check()
            raise AssertionError("应该报错")
        except RuntimeError as e:
            assert "AT 服务器和国内镜像都无法连接" in str(e)
    finally:
        vpk._last["feed"] = None
        if old is None:
            sys.modules.pop("velopack", None)
        else:
            sys.modules["velopack"] = old
    assert all("myqcloud" in s for k, s in calls if k in ("download", "apply")) and any(
        "国内镜像" in x for x in msgs
    )


def test_vpk_beta_gets_same_number_live(monkeypatch):
    import sys
    from astral_toolkit.update import version, vpk
    from astral_toolkit.tasks import system as t_sys

    versions = {"win": "1.1.2", "beta": None, "prev": None}
    monkeypatch.setattr(vpk, "FEEDS", [("https://example.invalid/velopack", "测试源")])
    monkeypatch.setattr(vpk, "_last", {"feed": None})
    monkeypatch.setattr(vpk, "installed", lambda: True)
    monkeypatch.setattr(t_sys, "_online_info", lambda force=False: None)
    monkeypatch.setattr(t_sys, "_online", {})
    monkeypatch.setattr(version, "VERSION", "1.1.2-beta.1")
    old = sys.modules.get("velopack")
    sys.modules["velopack"] = _fake_velopack(versions)
    try:
        assert vpk.install(progress=lambda *a: None) == "1.1.2"
        assert t_sys.upgrade_check(online=True)["online"]["version"] == "1.1.2"
        versions.update(win=None, beta="1.1.2-beta.1")
        try:
            vpk.install(progress=lambda *a: None)
            raise AssertionError("应该报已经是最新")
        except ValueError as e:
            assert "最新" in str(e)
        assert t_sys.upgrade_check(online=True)["online"] is None
        versions.update(win="1.1.1", beta="1.1.2-beta.2")
        assert vpk.install(progress=lambda *a: None) == "1.1.2-beta.2"
        assert vpk._missing(RuntimeError("HTTP 404 Not Found"))
        assert not vpk._missing(TimeoutError("timed out"))
        monkeypatch.setattr(version, "VERSION", "1.1.2")
        versions.update(win=None, beta="1.1.3-beta.1")
        try:
            vpk.install(progress=lambda *a: None)
            raise AssertionError("正式版不该收到测试版")
        except ValueError as e:
            assert "未找到" in str(e) or "最新" in str(e)
        monkeypatch.setattr(version, "VERSION", "1.1.2")
        versions.update(win=None, prev="1.1.2-beta.3")
        assert vpk.install(rollback=True, progress=lambda *a: None) == "1.1.2-beta.3"
        assert [r["version"] for r in t_sys.upgrade_check(online=True)["older"]] == [
            "1.1.2-beta.3"
        ]
    finally:
        if old is None:
            sys.modules.pop("velopack", None)
        else:
            sys.modules["velopack"] = old


def test_game_source_marker():
    from astral_toolkit.core import paths

    assert paths.from_game({"source": paths.SRC_GAME}) and not paths.from_game(None)
    assert paths.from_game({"source": paths.SRC_GAME_OLD})
    assert not paths.from_game({"source": "scmdb.net"})


def test_crafting_update_without_build_input_stays_offline(monkeypatch, tmp_path):
    """本机没有构建输入（玩家的电脑）：制造数据不重建、不联网（2026-11-13 起不再去 scmdb 下），数据包带来的那份原样留着；
    以前从 scmdb 下到 data/scmdb 的旧文件也不再拿来重建（换汉化时）"""
    from astral_toolkit.core import net, paths
    from astral_toolkit.crafting import build_crafting
    from astral_toolkit.update import localization

    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(localization, "DATA", tmp_path)
    sent = []
    monkeypatch.setattr(net, "read", lambda *a, **k: sent.append(a) or b"[]")
    built = []
    monkeypatch.setattr(build_crafting, "build", lambda *a, **k: built.append(a))
    out = tmp_path / "crafting.json"
    out.write_text('{"version": "pack"}', encoding="utf-8")
    old = tmp_path / "scmdb"
    old.mkdir()
    (old / "crafting_blueprints-4.10.2-live.1.json").write_text("{}", encoding="utf-8")
    (old / "merged-4.10.2-live.1.json").write_text("{}", encoding="utf-8")
    for gone in ("SCMDB", "_fetch", "pick_live"):
        assert not hasattr(build_crafting, gone), gone
    build_crafting.update()
    localization._rebuild_crafting(tmp_path / "names.json", lambda *_: None)
    assert sent == [] and built == []
    assert out.read_text(encoding="utf-8") == '{"version": "pack"}'


def test_build_input_rows(monkeypatch, tmp_path):
    from astral_toolkit.core import paths
    from astral_toolkit.crafting import build_crafting

    monkeypatch.setattr(paths, "DATA", tmp_path)
    assert build_crafting.source_rows() is None
    d = tmp_path / paths.BUILD_DIR
    d.mkdir()
    bp = d / "crafting_blueprints-4.10.2-live.12913470.json"
    bp.write_text("{}", encoding="utf-8")
    assert build_crafting.source_rows() is None
    (d / "merged-4.10.2-live.12913470.json").write_text("{}", encoding="utf-8")
    got = build_crafting.source_rows()
    assert got and got[0] == bp and got[2] == "4.10.2-live.12913470"


def test_make_data_pack_keeps_game_starmap(monkeypatch, tmp_path):
    """本机星图是游戏数据版：发数据包前的更新不会碰它（不下星图、不调合并脚本），也不用再设构建目录的环境变量"""
    import runpy
    import subprocess
    from pathlib import Path

    from astral_toolkit import run
    from astral_toolkit.core import paths
    from astral_toolkit.update import data_pack
    from tests.minipytest import raises

    M = runpy.run_path(
        str(Path(__file__).resolve().parent.parent / "tools" / "make_data_pack.py")
    )

    monkeypatch.setattr(paths, "DATA", tmp_path)
    star = tmp_path / "starmap.json"
    text = json.dumps({"source": paths.SRC_GAME})
    star.write_text(text, encoding="utf-8")
    calls = []
    monkeypatch.setattr(run, "update", lambda **kw: calls.append(kw) or {"results": []})
    monkeypatch.setenv("AT_SRC_DIR", "")
    monkeypatch.setenv("AT_DATA_TOOLS", "")
    spawned = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: spawned.append(a))

    class Stop(Exception):
        pass

    def stop(*a, **kw):
        raise Stop

    monkeypatch.setattr(data_pack, "make", stop)
    with raises(Stop):
        M["main"](["--no-loot"])
    assert calls == [{"direct": True}] and spawned == []
    assert star.read_text(encoding="utf-8") == text


def test_falls_back_to_github_and_ignores_older(monkeypatch, tmp_path):
    from astral_toolkit.update import version

    exe = tmp_path / "AT_Setup_9.0.0.exe"
    exe.write_bytes(b"MZ setup")
    m = _installer_manifest(exe)
    C, calls = _setup(
        monkeypatch,
        tmp_path,
        {
            "https://raw.githubusercontent.com/at/at/main/latest.json": json.dumps(
                m
            ).encode()
        },
    )
    monkeypatch.setattr(C.paths, "FROZEN", True)
    monkeypatch.setattr(C.paths, "VELOPACK", False)
    monkeypatch.setattr(version, "current", lambda: (1, 0, 0))
    info = C.check(force=True)
    assert info and info["version"] == "9.0.0" and info["source"] == "GitHub"
    assert {c.split("/")[2] for c in calls} == {
        "dl.astral-trade.com",
        "at-dl-1323647399.cos.ap-guangzhou.myqcloud.com",
        "raw.githubusercontent.com",
    }
    old = dict(m, version="0.0.1")
    C, _ = _setup(
        monkeypatch,
        tmp_path,
        {
            "https://raw.githubusercontent.com/at/at/main/latest.json": json.dumps(
                old
            ).encode()
        },
    )
    monkeypatch.setattr(C.paths, "FROZEN", True)
    monkeypatch.setattr(C.paths, "VELOPACK", False)
    monkeypatch.setattr(version, "current", lambda: (1, 0, 0))
    assert C.check(force=True) is None


def test_own_server_stale_does_not_hide_newer(monkeypatch, tmp_path):
    from astral_toolkit.update import version

    exe = tmp_path / "AT_Setup_9.0.0.exe"
    exe.write_bytes(b"MZ setup")
    new = _installer_manifest(exe)
    old = dict(new, version="0.0.1")
    C, _ = _setup(
        monkeypatch,
        tmp_path,
        {
            "https://dl.astral-trade.com/latest.json": json.dumps(old).encode(),
            "https://raw.githubusercontent.com/at/at/main/latest.json": json.dumps(
                new
            ).encode(),
        },
    )
    monkeypatch.setattr(C.paths, "FROZEN", True)
    monkeypatch.setattr(C.paths, "VELOPACK", False)
    monkeypatch.setattr(version, "current", lambda: (1, 0, 0))
    info = C.check(force=True)
    assert info and info["version"] == "9.0.0" and info["source"] == "GitHub"


def test_vpk_check_fail_not_up_to_date(monkeypatch):
    from astral_toolkit.tasks.system import upgrade as U
    from astral_toolkit.update import version, vpk

    def boom(rollback=False):
        raise RuntimeError("AT 服务器和国内镜像都无法连接：timed out")

    monkeypatch.setattr(vpk, "installed", lambda: True)
    monkeypatch.setattr(vpk, "check", boom)
    monkeypatch.setattr(version, "VERSION", "1.0.0")
    monkeypatch.setattr(U, "_online", {})
    monkeypatch.setattr(
        U,
        "_online_info",
        lambda force=False: {
            "version": "99.0.0",
            "date": "",
            "notes": [],
            "size": 1,
            "source": "GitHub",
        },
    )
    r = U.upgrade_check(online=True)
    assert r["online"] is None
    assert r["online_error"] == "无法连接更新服务器"
    assert "AT 99.0.0" in r["online_hint"]
    monkeypatch.setattr(vpk, "check", lambda rollback=False: (None, "", "国内镜像"))
    monkeypatch.setattr(U, "_online", {})
    r = U.upgrade_check(online=True)
    assert r["online"] is None and r["online_error"] == "" and r["online_hint"] == ""


def test_installer_entry_only_for_standalone(tmp_path):
    from astral_toolkit.update import update_check as C

    exe = tmp_path / "AT_Setup_9.0.0.exe"
    exe.write_bytes(b"MZ setup")
    m = _installer_manifest(exe)
    fz = C.parse(json.dumps(m), frozen=True, velopack=False)
    assert fz["file"] == exe.name and fz["installer"]
    vp = C.parse(json.dumps(m), frozen=False, velopack=True)
    assert vp["version"] == "9.0.0" and vp["urls"] == []
    try:
        C.parse(json.dumps(m), frozen=False, velopack=False)
        assert False
    except C.NoPackage:
        pass
    for bad in (
        {k: v for k, v in m.items() if k != "installer"},
        {**m, "installer": {**m["installer"], "file": "virus.exe"}},
    ):
        try:
            C.parse(json.dumps(bad), frozen=True, velopack=False)
            assert False, bad
        except ValueError:
            pass


def test_parse_rejects_bad_manifest(tmp_path):
    from astral_toolkit.update import update_check as C

    exe = tmp_path / "AT_Setup_9.0.0.exe"
    exe.write_bytes(b"MZ setup")
    good = _installer_manifest(exe)
    assert C.parse(json.dumps(good), frozen=True, velopack=False)["version"] == "9.0.0"
    for bad in (
        {**good, "installer": {**good["installer"], "sha256": "123"}},
        {**good, "installer": {**good["installer"], "file": "virus.exe"}},
        {
            **good,
            "installer": {
                **good["installer"],
                "urls": ["http://evil.com/a.exe"],
            },
        },
        {**good, "version": "abc"},
    ):
        try:
            C.parse(json.dumps(bad), frozen=True, velopack=False)
            assert False, bad
        except ValueError:
            pass


def test_manifest_installer_only(monkeypatch, tmp_path):
    from astral_toolkit.update import update_check as C
    from astral_toolkit.update import version

    exe = tmp_path / "AT_Setup_9.0.0.exe"
    exe.write_bytes(b"MZ setup")
    m = C.make_manifest(notes=["x"], installer=exe)
    assert m["version"] == "9.0.0" and m["installer"]["file"] == exe.name
    assert m["kill_rev"] == C.LEGACY_KILL_REV
    assert m["disabled"] == C.LEGACY_DISABLED
    assert not {"file", "size", "sha256", "urls"} & set(m)
    assert C.parse(json.dumps(m), frozen=True, velopack=False)["file"] == exe.name
    try:
        C.parse(json.dumps(m), frozen=False, velopack=False)
        assert False
    except C.NoPackage:
        pass
    C, _ = _setup(
        monkeypatch,
        tmp_path,
        {
            "https://raw.githubusercontent.com/at/at/main/latest.json": json.dumps(
                m
            ).encode()
        },
    )
    monkeypatch.setattr(C.paths, "FROZEN", False)
    monkeypatch.setattr(C.paths, "VELOPACK", False)
    monkeypatch.setattr(version, "current", lambda: (1, 0, 0))
    assert C.check(force=True) is None and C.last_error() == ""
    C, _ = _setup(
        monkeypatch,
        tmp_path,
        {
            "https://raw.githubusercontent.com/at/at/main/latest.json": json.dumps(
                m
            ).encode()
        },
    )
    monkeypatch.setattr(C.paths, "FROZEN", True)
    monkeypatch.setattr(C.paths, "VELOPACK", False)
    monkeypatch.setattr(version, "current", lambda: (1, 0, 0))
    info = C.check(force=True)
    assert info and info["file"] == exe.name


def test_newest_manifest_without_package_blocks_older_package(monkeypatch, tmp_path):
    """对桥接安装版仍成立：新清单 9.0.0 没有 installer，不能退回旧清单里的 5.0.0 安装程序。"""
    from astral_toolkit.update import version

    exe = tmp_path / "AT_Setup_5.0.0.exe"
    exe.write_bytes(b"MZ setup")
    older = _installer_manifest(exe, version="5.0.0")
    pages = {
        "https://dl.astral-trade.com/latest.json": json.dumps(
            {"version": "9.0.0", "notes": ["新功能"]}
        ).encode(),
        "https://raw.githubusercontent.com/at/at/main/latest.json": json.dumps(
            older
        ).encode(),
    }
    C, calls = _setup(monkeypatch, tmp_path, pages)
    monkeypatch.setattr(C.paths, "FROZEN", True)
    monkeypatch.setattr(C.paths, "VELOPACK", False)
    monkeypatch.setattr(version, "current", lambda: (1, 0, 0))
    assert C.check(force=True) is None and C.last_error() == ""
    assert calls and all(u.endswith("/latest.json") for u in calls)
    C, _ = _setup(monkeypatch, tmp_path, pages)
    monkeypatch.setattr(C.paths, "FROZEN", False)
    monkeypatch.setattr(C.paths, "VELOPACK", True)
    monkeypatch.setattr(version, "current", lambda: (1, 0, 0))
    info = C.check(force=True)
    assert info and info["version"] == "9.0.0" and info["source"] == "AT 服务器"


def test_make_manifest_version_must_match_package(tmp_path):
    from astral_toolkit.update import update_check as C

    exe = tmp_path / "AT_Setup_9.0.0.exe"
    exe.write_bytes(b"MZ setup")
    assert C.make_manifest(installer=exe, version="9.0.0")["version"] == "9.0.0"
    try:
        C.make_manifest(installer=exe, version="9.0.1")
        raise AssertionError("版本不一致应报错")
    except ValueError as e:
        assert "不一致" in str(e)


def test_zip_in_downloads_not_scanned(monkeypatch, tmp_path):
    import types
    import importlib

    from astral_toolkit.core import paths
    from astral_toolkit.tasks.system import upgrade as U
    from astral_toolkit.tasks.system.common import StatusSources

    S = importlib.import_module("astral_toolkit.tasks.system.status")
    from astral_toolkit.update import vpk

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "Dubhe_9.9.9.zip").write_bytes(b"PK")
    root = tmp_path / "AT"
    root.mkdir()
    user = tmp_path / "userdata"
    user.mkdir()
    monkeypatch.setattr(paths, "ROOT", root)
    monkeypatch.setattr(paths, "USER", user)
    monkeypatch.setattr(paths, "FROZEN", True)
    monkeypatch.setattr(paths, "VELOPACK", False)
    monkeypatch.setattr(vpk, "installed", lambda: False)
    monkeypatch.setattr(U, "_online", {})
    r = U.upgrade_check()
    assert "found" not in r and "new_version" not in r
    assert "Dubhe_9.9.9.zip" not in json.dumps(r, ensure_ascii=False)

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
    st = S.status(sources)
    assert "new_version" not in st
    assert "Dubhe_9.9.9.zip" not in json.dumps(st, ensure_ascii=False, default=str)


def test_retired_routes_absent():
    from astral_toolkit.app.api import router

    router.reset()
    routes = router.routes()
    retired = (
        "upgrade_apply",
        "upgrade_upload",
        "upgrade_upload_raw",
        "legacy_scan",
        "legacy_import",
        "legacy_skip",
        "legacy_quit",
    )
    for name in retired:
        assert name not in routes, name
        try:
            got = router.call(name, {})
        except Exception:
            continue
        assert not (isinstance(got, dict) and got.get("ok")), (name, got)


def test_source_import_without_legacy():
    import astral_toolkit.app.server  # noqa: F401
    from astral_toolkit import selftest

    assert "update.legacy" not in selftest.MODULES
