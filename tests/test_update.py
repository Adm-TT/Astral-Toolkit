"""在线更新：读版本说明、核对下载的安装包（不联网：换掉 _open）"""

import hashlib
import io
import json
import threading

from tests.test_upgrade import _pkg


class _Resp(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


def _setup(monkeypatch, tmp_path, pages):
    from sc_mining.update import update_check as C

    monkeypatch.setattr(C, "GITEE", "at/at")
    monkeypatch.setattr(C, "GITHUB", "at/at")
    monkeypatch.setattr(C, "UPDATES", tmp_path / "updates")
    monkeypatch.setattr(
        C, "_state", {"at": 0.0, "info": None, "error": "", "lock": threading.Lock()}
    )
    monkeypatch.setattr(
        C, "KILL_FILE", tmp_path / "killswitch.json"
    )  # 不碰真实的关功能记录（Codex 2026-10-27）
    monkeypatch.setattr(C, "_kill", {"list": None, "at": 0.0})
    calls = []

    def fake_open(url, timeout):
        calls.append(url)
        v = pages.get(url)
        if isinstance(v, Exception) or v is None:
            raise v or OSError("连不上")
        return _Resp(v)

    monkeypatch.setattr(C, "_open", fake_open)
    return C, calls


def _manifest(zip_path, version="9.0.0", sha=None):
    data = zip_path.read_bytes()
    return {
        "version": version,
        "file": zip_path.name,
        "size": len(data),
        "notes": ["新功能"],
        "sha256": sha or hashlib.sha256(data).hexdigest(),
        "urls": [
            "https://gitee.com/at/at/releases/download/v9.0.0/" + zip_path.name,
            "https://github.com/at/at/releases/download/v9.0.0/" + zip_path.name,
        ],
    }


def test_falls_back_to_github_and_ignores_older(monkeypatch, tmp_path):
    z = _pkg(tmp_path / "Dubhe_9.0.0.zip", "9.0.0", {})
    m = _manifest(z)
    C, calls = _setup(
        monkeypatch,
        tmp_path,
        {
            "https://raw.githubusercontent.com/at/at/main/latest.json": json.dumps(
                m
            ).encode()
        },
    )
    info = C.check(force=True)
    assert info and info["version"] == "9.0.0" and info["source"] == "GitHub"
    assert {c.split("/")[2] for c in calls} == {
        "dl.astral-trade.com",
        "at-dl-1323647399.cos.ap-guangzhou.myqcloud.com",
        "gitee.com",
        "raw.githubusercontent.com",
    }  # 四处一起问
    old = dict(m, version="0.0.1")
    C, _ = _setup(
        monkeypatch,
        tmp_path,
        {"https://gitee.com/at/at/raw/master/latest.json": json.dumps(old).encode()},
    )
    assert C.check(force=True) is None  # 比现在旧：不提示


def test_offline_returns_none(monkeypatch, tmp_path):
    C, _ = _setup(monkeypatch, tmp_path, {})
    assert C.check(force=True) is None and C.last_error()


def test_parse_rejects_bad_manifest():
    from sc_mining.update import update_check as C

    good = {
        "version": "1.7.1",
        "file": "Dubhe_1.7.1.zip",
        "sha256": "a" * 64,
        "urls": ["https://gitee.com/x/y/z.zip"],
    }
    assert C.parse(json.dumps(good))["version"] == "1.7.1"
    for bad in (
        {**good, "sha256": "123"},
        {**good, "file": "virus.exe"},
        {**good, "urls": ["http://evil.com/a.zip"]},
        {**good, "version": "abc"},
    ):
        try:
            C.parse(json.dumps(bad))
            assert False, bad
        except ValueError:
            pass


def test_download_checks_sha_and_uses_mirror(monkeypatch, tmp_path):
    z = _pkg(tmp_path / "Dubhe_9.0.0.zip", "9.0.0", {})
    data = z.read_bytes()
    m = _manifest(z)
    C, _ = _setup(
        monkeypatch, tmp_path, {m["urls"][0]: data[:-5] + b"xxxxx", m["urls"][1]: data}
    )  # Gitee 的坏了
    out = C.download(C.parse(json.dumps(m)), progress=lambda *_: None)
    assert out.read_bytes() == data and not list((tmp_path / "updates").glob("*.part"))
    bad = _manifest(z, sha="0" * 64)
    C, _ = _setup(monkeypatch, tmp_path, {u: data for u in bad["urls"]})
    (tmp_path / "updates" / z.name).unlink()
    try:
        C.download(C.parse(json.dumps(bad)), progress=lambda *_: None)
        assert False
    except ValueError as e:
        assert "下载失败" in str(e)
    assert not list((tmp_path / "updates").glob("Dubhe_*"))  # 校验不符的不留


def test_disabled_without_repo(monkeypatch):
    from sc_mining.update import update_check as C

    monkeypatch.setattr(C, "GITEE", "")
    monkeypatch.setattr(C, "GITHUB", "")
    monkeypatch.setattr(C, "OWN", "")
    monkeypatch.setattr(C, "COS", "")
    assert not C.enabled() and C.check(force=True) is None


def test_installer_entry_only_for_standalone(tmp_path):
    """1.7.0 起 latest.json 多一项 installer：Python 版照旧用 Dubhe_*.zip，独立安装版只认 AT_Setup_*.exe"""
    from sc_mining.update import update_check as C

    m = {
        "version": "1.7.1",
        "file": "Dubhe_1.7.1.zip",
        "sha256": "a" * 64,
        "urls": ["https://gitee.com/x/y/Dubhe_1.7.1.zip"],
        "installer": {
            "file": "AT_Setup_1.7.1.exe",
            "sha256": "b" * 64,
            "size": 9,
            "urls": ["https://github.com/x/y/AT_Setup_1.7.1.exe"],
        },
    }
    py = C.parse(json.dumps(m), frozen=False)
    assert py["file"] == "Dubhe_1.7.1.zip" and not py["installer"]
    fz = C.parse(json.dumps(m), frozen=True)
    assert (
        fz["file"] == "AT_Setup_1.7.1.exe"
        and fz["sha256"] == "b" * 64
        and fz["installer"]
    )
    for bad in (
        {k: v for k, v in m.items() if k != "installer"},
        {**m, "installer": {**m["installer"], "file": "virus.exe"}},
    ):
        try:
            C.parse(json.dumps(bad), frozen=True)
            assert False, bad
        except ValueError:
            pass


def test_make_manifest_with_installer(monkeypatch, tmp_path):
    z = _pkg(tmp_path / "Dubhe_9.0.0.zip", "9.0.0", {})
    exe = tmp_path / "AT_Setup_9.0.0.exe"
    exe.write_bytes(b"MZ setup")
    C, _ = _setup(monkeypatch, tmp_path, {})
    m = C.make_manifest(z, ["x"], installer=exe)
    assert m["installer"]["file"] == exe.name and m["installer"]["size"] == 8
    assert m["installer"]["urls"][:3] == [
        "https://dl.astral-trade.com/releases/v9.0.0/AT_Setup_9.0.0.exe",
        "https://at-dl-1323647399.cos.ap-guangzhou.myqcloud.com/releases/v9.0.0/AT_Setup_9.0.0.exe",
        "https://gitee.com/at/at/releases/download/v9.0.0/AT_Setup_9.0.0.exe",
    ]
    assert (
        C.where(m["installer"]["urls"][0]) == "AT 服务器"
        and C.where("https://evil.com/dl.astral-trade.com/x") == "网上"
    )
    assert C.where(m["installer"]["urls"][1]) == "国内镜像"
    assert [n for n, _ in C.manifest_urls()][:2] == ["AT 服务器", "国内镜像"]
    assert C.parse(json.dumps(m), frozen=True)["version"] == "9.0.0"
    wrong = tmp_path / "AT_Setup_8.0.0.exe"
    wrong.write_bytes(b"MZ")
    try:
        C.make_manifest(z, installer=wrong)
        assert False
    except ValueError:
        pass


def test_manifest_installer_only(monkeypatch, tmp_path):
    """压缩包版停止维护：只给安装程序也能生成 latest.json；顶层不写 file（不会出现新版本号配旧压缩包），
    源码版读到当作没有新版本、不报错，安装版照常认 installer"""
    exe = tmp_path / "AT_Setup_9.0.0.exe"
    exe.write_bytes(b"MZ setup")
    C, _ = _setup(monkeypatch, tmp_path, {})
    online = {
        "version": "1.1.1",
        "file": "Dubhe_1.1.1.zip",
        "sha256": "a" * 64,
        "size": 1,
        "urls": ["https://gitee.com/at/at/releases/download/v1.1.1/Dubhe_1.1.1.zip"],
        "kill_rev": 5,
        "disabled": [],
    }
    m = C.make_manifest(None, ["x"], installer=exe, keep=online)
    assert (
        m["version"] == "9.0.0"
        and m["kill_rev"] == 5
        and m["installer"]["file"] == exe.name
    )
    assert not {"file", "size", "sha256", "urls"} & set(m)
    assert C.parse(json.dumps(m), frozen=True)["file"] == "AT_Setup_9.0.0.exe"
    try:
        C.parse(json.dumps(m), frozen=False)
        assert False
    except C.NoPackage:
        pass
    for bad in ((None, None), (None, tmp_path / "setup.exe")):
        try:
            C.make_manifest(bad[0], installer=bad[1])
            assert False, bad
        except ValueError:
            pass
    C, _ = _setup(
        monkeypatch,
        tmp_path,
        {"https://gitee.com/at/at/raw/master/latest.json": json.dumps(m).encode()},
    )
    monkeypatch.setattr(C.paths, "FROZEN", False)
    assert (
        C.check(force=True) is None and C.last_error() == ""
    )  # 源码版：没有新版本，不是「连不上」
    C, _ = _setup(
        monkeypatch,
        tmp_path,
        {"https://gitee.com/at/at/raw/master/latest.json": json.dumps(m).encode()},
    )
    monkeypatch.setattr(C.paths, "FROZEN", True)
    assert C.check(force=True)["file"] == "AT_Setup_9.0.0.exe"  # 安装版照常提示


def test_make_manifest_tool_installer_only(monkeypatch, tmp_path):
    """tools/make_manifest.py 只给 --installer：latest.json 生成在安装程序旁边"""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    import make_manifest as T

    exe = tmp_path / "AT_Setup_9.0.0.exe"
    exe.write_bytes(b"MZ setup")
    C, _ = _setup(monkeypatch, tmp_path, {})
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)
    assert T.main(["--installer", str(exe), "--fresh", "新功能"]) == 0
    m = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert m["version"] == "9.0.0" and "file" not in m and m["notes"] == ["新功能"]
    assert T.main(["--fresh", "只有说明"]) == 1


def _old_install(d, version="1.6.72", settings=None, waypoints=None):
    (d / "sc_mining").mkdir(parents=True)
    (d / "userdata").mkdir()
    (d / "Dubhe.exe").write_bytes(b"MZ")
    (d / "sc_mining" / "version.py").write_text(
        f'VERSION = "{version}"\n', encoding="utf-8"
    )
    (d / "userdata" / "settings.json").write_text(
        json.dumps(settings or {"agreed": True, "mark_key": "F4"}), encoding="utf-8"
    )
    if waypoints is not None:
        (d / "userdata" / "waypoints.json").write_text(
            json.dumps(waypoints, ensure_ascii=False), encoding="utf-8-sig"
        )  # 带 BOM 也要认
    return d


def test_legacy_find_and_import(monkeypatch, tmp_path):
    """1.0.1：安装版找旧版天枢、导入设置和路标（免责声明那项不带过来、AT 原来的文件先备份）"""
    from sc_mining.update import legacy
    from sc_mining.core import paths

    me = tmp_path / "AT"
    (me / "userdata").mkdir(parents=True)
    monkeypatch.setattr(paths, "ROOT", me)
    monkeypatch.setattr(paths, "USER", me / "userdata")
    old = _old_install(
        tmp_path / "Downloads" / "Dubhe_1.6.36" / "Dubhe_1.6.36",
        waypoints=[{"n": "空间站"}],
    )
    _old_install(
        tmp_path / "Downloads" / "deep" / "a" / "b" / "c" / "Dubhe"
    )  # 太深，不找
    rows = legacy.find(roots=[(tmp_path / "Downloads", 3)])
    assert (
        [r["path"] for r in rows] == [str(old)]
        and rows[0]["version"] == "1.6.72"
        and rows[0]["waypoints"] == 1
    )
    (me / "userdata" / "settings.json").write_text(
        json.dumps({"agreed": False, "mark_key": "F7"}), encoding="utf-8"
    )
    done = legacy.import_from(old)
    assert "settings.json" in done and "waypoints.json" in done
    cfg = json.loads((me / "userdata" / "settings.json").read_text(encoding="utf-8"))
    assert (
        cfg["mark_key"] == "F4" and cfg["agreed"] is False
    )  # 免责声明要在 AT 里重新同意
    assert json.loads(
        (me / "userdata" / "waypoints.json").read_text(encoding="utf-8")
    ) == [{"n": "空间站"}]
    bak = list((me / "userdata").glob("import_backup_*/settings.json"))
    assert bak and json.loads(bak[0].read_text(encoding="utf-8"))["mark_key"] == "F7"
    assert (
        json.loads((old / "userdata" / "settings.json").read_text(encoding="utf-8"))[
            "mark_key"
        ]
        == "F4"
    )  # 旧版不动
    try:
        legacy.import_from(tmp_path)
        assert False
    except ValueError:
        pass
    assert legacy.running(rows) == []  # 旧版没开着


def test_legacy_skips_self(monkeypatch, tmp_path):
    from sc_mining.update import legacy
    from sc_mining.core import paths

    me = _old_install(tmp_path / "Documents" / "sc_mining")
    monkeypatch.setattr(paths, "ROOT", me)
    assert legacy.find(roots=[(tmp_path / "Documents", 3)]) == []


def test_killswitch(monkeypatch, tmp_path):
    """远程关功能（2026-10-27，借鉴 EDMC）：latest.json 的 disabled 按版本范围关掉指定功能；写错的不关；存到本地离线也照样关"""
    import json
    from sc_mining.update import update_check as U, upgrade

    monkeypatch.setattr(U, "KILL_FILE", tmp_path / "killswitch.json")
    monkeypatch.setattr(U, "_kill", {"list": None, "at": 0.0})
    monkeypatch.setattr(upgrade, "VERSION", "1.0.4")
    v = upgrade.ver("1.0.4")
    assert (
        U._in_range("", v)
        and U._in_range("*", v)
        and U._in_range("1.0.4", v)
        and not U._in_range("1.0.3", v)
    )
    assert (
        U._in_range("<=1.0.4", v)
        and not U._in_range("<1.0.4", v)
        and U._in_range(">=1.0.2", v)
    )
    assert (
        U._in_range("1.0.2-1.0.4", v)
        and not U._in_range("1.0.5-1.0.9", v)
        and not U._in_range("胡写", v)
    )
    U._set_kill(
        [
            {"feature": "nav_marker", "versions": "<=1.0.4", "why": "记号位置不对"},
            {"feature": "radar", "versions": "1.0.3"},
            {"feature": "不认识的", "versions": "*"},
            "坏的",
        ]
    )
    assert (
        U.disabled("nav_marker") == "记号位置不对"
        and U.disabled("radar") is None
        and U.disabled("item") is None
    )
    assert (
        len(
            json.loads((tmp_path / "killswitch.json").read_text(encoding="utf-8"))[
                "list"
            ]
        )
        == 2
    )
    U._kill.update(list=None)  # 重开 AT：从本地文件读回来
    assert U.disabled("nav_marker") == "记号位置不对"
    U._set_kill([])
    assert U.disabled("nav_marker") is None
    # 拿到的不是版本说明（错误页面）：保留原来关掉的功能（Codex 2026-10-27）
    import io

    U._set_kill([{"feature": "radar", "versions": "*"}])
    monkeypatch.setattr(
        U, "manifest_urls", lambda: [("Gitee", "https://gitee.com/x/latest.json")]
    )
    monkeypatch.setattr(
        U, "_open", lambda url, timeout: io.BytesIO(b'{"message": "not found"}')
    )
    assert U.fetch()[0] is None and U.disabled("radar")


def test_own_server_stale_does_not_hide_newer(monkeypatch, tmp_path):
    """Codex 2026-10-27：自己服务器上的清单旧了，Gitee 上有新版本，要用新的；关功能列表取 kill_rev 最大的那份"""
    z = _pkg(tmp_path / "Dubhe_9.0.0.zip", "9.0.0", {})
    new = dict(_manifest(z), kill_rev=5, disabled=[{"feature": "radar", "why": "新"}])
    old = dict(
        new,
        version="0.0.1",
        kill_rev=9,
        disabled=[{"feature": "scan", "why": "旧但关功能更新"}],
    )
    C, calls = _setup(
        monkeypatch,
        tmp_path,
        {
            "https://dl.astral-trade.com/latest.json": json.dumps(old).encode(),
            "https://gitee.com/at/at/raw/master/latest.json": json.dumps(new).encode(),
        },
    )
    info = C.check(force=True)
    assert info and info["version"] == "9.0.0" and info["source"] == "Gitee"
    assert C.disabled("scan") and not C.disabled("radar")


def test_beta_sees_same_number_live(monkeypatch, tmp_path):
    """本机是 beta（1.1.2-beta.1）时，同号的 live（1.1.2）也提示更新；live 装的不提示同号（2026-10-30）"""
    from sc_mining.update import upgrade

    z = _pkg(tmp_path / "Dubhe_9.0.0.zip", "9.0.0", {})
    C, calls = _setup(
        monkeypatch,
        tmp_path,
        {
            "https://gitee.com/at/at/raw/master/latest.json": json.dumps(
                _manifest(z)
            ).encode()
        },
    )
    monkeypatch.setattr(upgrade, "current", lambda: (9, 0, 0))
    monkeypatch.setattr(C, "_is_beta", lambda: True)
    assert C.check(force=True)["version"] == "9.0.0"
    monkeypatch.setattr(C, "_is_beta", lambda: False)
    assert C.check(force=True) is None


def test_data_pack_takes_newest_source(monkeypatch, tmp_path):
    import io
    from sc_mining.update import data_pack as P
    from sc_mining.update import update_check as U

    base = {
        "file": "AT_data_2026.10.27-0100.zip",
        "sha256": "a" * 64,
        "urls": ["https://gitee.com/x/y/AT_data_2026.10.27-0100.zip"],
    }
    pages = {
        "https://dl.astral-trade.com/data.json": json.dumps(
            dict(base, version="2026.10.26-0100")
        ).encode(),
        "https://gitee.com/at/at/raw/master/data.json": json.dumps(
            dict(base, version="2026.10.27-0100")
        ).encode(),
    }
    monkeypatch.setattr(U, "GITEE", "at/at")
    monkeypatch.setattr(U, "GITHUB", "")

    def fake(url, timeout):
        if url not in pages:
            raise OSError("连不上")
        return io.BytesIO(pages[url])

    monkeypatch.setattr(U, "_open", fake)
    info, err = P.fetch()
    assert info["version"] == "2026.10.27-0100" and info["source"] == "Gitee"


def test_publish_hk_checks_manifest(tmp_path):
    """发布脚本：空清单、地址里带命令、文件名和地址不一致都要停（不碰服务器）"""
    import sys
    from pathlib import Path

    tools = Path(__file__).resolve().parent.parent / "tools"
    if not (tools / "publish_hk.py").exists():  # 开源版不带服务器发布工具
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
    assert [e[0] for e in H.entries(lj, good)] == [
        "Dubhe_1.0.5.zip",
        "AT_Setup_1.0.5.exe",
    ]
    only_setup = {
        "version": "1.0.5",
        "installer": good["installer"],
    }  # 压缩包版停了：清单只给安装程序也合法（控制台第 1 批）
    assert [e[0] for e in H.entries(lj, only_setup)] == ["AT_Setup_1.0.5.exe"]
    bad = [
        {},
        {k: v for k, v in good.items() if k != "installer"},
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


def test_vpk_falls_back_to_cos(monkeypatch):
    """Velopack：香港连不上（出错 / 超时）就用国内镜像查版本、下载（2026-10-29）；用假的 velopack，不联网"""
    import sys
    import types
    from sc_mining.update import vpk, upgrade

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
    monkeypatch.setattr(upgrade, "current", lambda: (1, 0, 0))
    try:
        vpk._last["feed"] = None
        assert vpk.check()[1:] == ("99.0.0", "国内镜像")
        n_hk = sum(1 for k, s in calls if k == "check" and "astral-trade" in s)
        vpk.check()  # 下次先问上次答上来的国内镜像，不再等香港
        assert sum(1 for k, s in calls if k == "check" and "astral-trade" in s) == n_hk
        msgs = []
        assert vpk.install(progress=msgs.append) == "99.0.0"
        vpk._last["feed"] = None
        Mgr.check_for_updates = lambda self: (_ for _ in ()).throw(
            OSError("timed out")
        )  # 两个都连不上：中文报错
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


def test_vpk_check_fail_not_up_to_date(monkeypatch):
    """Velopack 版：香港和国内镜像都连不上时「检查更新」不说「已是最新」；latest.json 有新版本就提示手动下载（审查 2026-10-29）"""
    from sc_mining.update import vpk
    from sc_mining.tasks import system as t_sys

    def boom(rollback=False):
        raise RuntimeError("AT 服务器和国内镜像都无法连接：timed out")

    monkeypatch.setattr(vpk, "installed", lambda: True)
    monkeypatch.setattr(vpk, "check", boom)
    monkeypatch.setattr(
        t_sys,
        "_online_info",
        lambda force=False: {
            "version": "99.0.0",
            "date": "",
            "notes": [],
            "size": 1,
            "source": "Gitee",
        },
    )
    r = t_sys.upgrade_check(online=True)
    assert (
        r["online"] is None
        and r["online_error"] == "无法连接更新服务器"
        and "AT 99.0.0" in r["online_hint"]
    )
    monkeypatch.setattr(
        vpk, "check", lambda rollback=False: (None, "", "国内镜像")
    )  # 连得上、没有新版本：照常
    r = t_sys.upgrade_check(online=True)
    assert r["online"] is None and r["online_error"] == "" and r["online_hint"] == ""
    t_sys._online.pop("vpk_fail", None)


def test_killswitch_old_mirror_cannot_undo(monkeypatch, tmp_path):
    """Codex 2026-10-27：第一次读到 kill_rev=200 关了雷达；第二次只有旧镜像（kill_rev=100、没关）能连上，雷达照样关着；
    重开 AT 从本地文件读回来也一样。发新版的 make_manifest 带上网上的 disabled 和 kill_rev"""
    z = _pkg(tmp_path / "Dubhe_9.0.0.zip", "9.0.0", {})
    m = _manifest(z)
    new = dict(m, kill_rev=200, disabled=[{"feature": "radar", "why": "坏了"}])
    old = dict(m, kill_rev=100, disabled=[])
    C, _ = _setup(
        monkeypatch,
        tmp_path,
        {"https://dl.astral-trade.com/latest.json": json.dumps(new).encode()},
    )
    C.check(force=True)
    assert C.disabled("radar")
    C, _ = _setup(
        monkeypatch,
        tmp_path,
        {"https://gitee.com/at/at/raw/master/latest.json": json.dumps(old).encode()},
    )
    C.check(force=True)
    assert C.disabled("radar")
    newer = dict(m, kill_rev=300, disabled=[])
    C, _ = _setup(
        monkeypatch,
        tmp_path,
        {"https://gitee.com/at/at/raw/master/latest.json": json.dumps(newer).encode()},
    )
    C.check(force=True)
    assert not C.disabled("radar")
    mm = C.make_manifest(z, keep=new)
    assert mm["kill_rev"] == 200 and mm["disabled"] == new["disabled"]
    assert "disabled" not in C.make_manifest(z)
    try:
        C.make_manifest(z, keep=dict(new, disabled={"feature": "radar"}))
        raise AssertionError("disabled 写成对象要报错")
    except ValueError:
        pass


def test_import_inno_userdata(monkeypatch, tmp_path):
    """Velopack 版第一次启动：老 Inno 版的设置和记录搬过来（窗口缓存、窗口地址、锁不搬；新位置更新的文件不盖）；搬完写标记，不再搬"""
    import os
    import time
    from sc_mining.core import paths

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
    assert (
        not (new / "window_url.txt").exists()
        and not (new / "instance.lock").exists()
        and not (new / "window").exists()
    )
    assert (new / ".migrated_from_inno").exists()
    (old / "settings.json").write_text('{"a": 2}', encoding="utf-8")
    assert paths.import_inno() == 0
    monkeypatch.setattr(paths, "VELOPACK", False)
    assert paths.import_inno() == 0


def test_vkey_beta_older_than_live():
    """版本比较按 semver：x.y.z-beta.N 比同号 x.y.z 旧；beta.2 比 beta.1 新，beta.10 比 beta.9 新（S5 审查 2026-10-31）"""
    from sc_mining.update.upgrade import vkey

    assert vkey("1.1.2-beta.1") < vkey("1.1.2")
    assert vkey("1.1.2-beta.1") < vkey("1.1.2-beta.2") < vkey("1.1.2-beta.10")
    assert vkey("1.1.1") < vkey("1.1.2-beta.1") < vkey("1.1.2")
    assert vkey("1.1.2") == vkey("1.1.2")
    assert vkey("") < vkey("0.0.1")


def _fake_velopack(versions):
    """假的 velopack：versions = {"win": 新版本号, "prev": 上一个版本号}（频道 → 版本，None 表示没有）"""
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


def test_vpk_beta_gets_same_number_live(monkeypatch):
    """Velopack 版装着 1.1.2-beta.1：服务器上的 1.1.2 正式版能升级、界面也提示；同号 beta 不算新；
    装着 1.1.2 时上一个版本 1.1.2-beta.3 能回滚（S5 审查 2026-10-31：以前比版本丢掉 beta 后缀，测试玩家收不到同号正式版）"""
    import sys
    from sc_mining.update import upgrade, vpk
    from sc_mining.tasks import system as t_sys

    versions = {"win": "1.1.2", "prev": None}
    monkeypatch.setattr(vpk, "FEEDS", [("https://example.invalid/velopack", "测试源")])
    monkeypatch.setattr(vpk, "_last", {"feed": None})
    monkeypatch.setattr(vpk, "installed", lambda: True)
    monkeypatch.setattr(t_sys, "_online_info", lambda force=False: None)
    monkeypatch.setattr(t_sys, "_online", {})
    monkeypatch.setattr(upgrade, "VERSION", "1.1.2-beta.1")
    old = sys.modules.get("velopack")
    sys.modules["velopack"] = _fake_velopack(versions)
    try:
        assert vpk.install(progress=lambda *a: None) == "1.1.2"
        assert t_sys.upgrade_check(online=True)["online"]["version"] == "1.1.2"
        versions["win"] = "1.1.2-beta.1"  # 同号同 beta：不是新版本
        try:
            vpk.install(progress=lambda *a: None)
            raise AssertionError("应该报已经是最新")
        except ValueError as e:
            assert "最新" in str(e)
        assert t_sys.upgrade_check(online=True)["online"] is None
        monkeypatch.setattr(upgrade, "VERSION", "1.1.2")  # 正式版回滚到同号 beta
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


def test_killswitch_refreshes_when_update_check_off(monkeypatch):
    """玩家关了「启动时检查更新」：不提示新版本，但远程关功能清单照常每小时查一次
    （控制台指令第 2 批选 A，2026-10-31：远程关是游戏更新后防止给出错误识别结果的兜底）"""
    import time as _t
    from sc_mining.core import settings
    from sc_mining.tasks import system as t_sys
    from sc_mining.update import update_check as U

    calls = []

    def fake_fetch(timeout=None):
        calls.append(1)
        U._kill["at"] = _t.time()  # 真的 fetch 读到清单时也会记下时间
        return {"version": "99.0.0"}, "测试源"

    monkeypatch.setattr(U, "fetch", fake_fetch)
    monkeypatch.setattr(U, "enabled", lambda: True)
    monkeypatch.setattr(U, "_kill", {"list": [], "at": 0.0, "key": None})
    monkeypatch.setattr(
        U, "_state", {"at": 0.0, "info": None, "error": "", "lock": threading.Lock()}
    )
    monkeypatch.setattr(
        settings, "load", lambda: {**settings.DEFAULTS, "update_online": False}
    )
    monkeypatch.setattr(t_sys, "_online", {"info": None, "told": ""})
    assert t_sys._online_info() is None and calls == [1]  # 查了清单，但不提示新版本
    assert t_sys._online_info() is None and calls == [1]  # 一小时内不再联网
    U._kill["at"] = 0.0
    t_sys._online_info()
    assert calls == [1, 1]
