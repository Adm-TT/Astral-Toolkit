"""助手窗口和后台：网页服务、任务日志、热键、首次运行、单实例、反馈、更新、免责声明、性能（从 test_tools.py 拆出，CL-C3）"""

from astral_toolkit.update import shops
from astral_toolkit.update import loot


def test_app_task_log_routing():
    import queue as _q
    import sys
    from astral_toolkit.app import bus, task_runner

    old = sys.stdout
    task_runner.install_router()
    q = bus.subscribe()
    try:
        task_runner.run_task(
            "t1", lambda: print("你好\n第二行") or 7, title="测试"
        ).join(3)
        got = []
        while True:
            try:
                got.append(q.get_nowait())
            except _q.Empty:
                break
        lines = [
            m["data"]["line"]
            for m in got
            if m["kind"] == "log" and m["data"]["task"] == "t1"
        ]
        assert lines == ["你好", "第二行"]
        assert any(
            m["kind"] == "task"
            and m["data"].get("state") == "done"
            and m["data"]["result"] == 7
            for m in got
        )
    finally:
        bus.unsubscribe(q)
        sys.stdout = old


def test_app_server_roundtrip():
    import json as _j
    import threading as _t
    import urllib.request as _u
    from http.server import ThreadingHTTPServer
    from astral_toolkit.app.server import Handler, TOKEN

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    _t.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        html = _u.urlopen(base + "/").read().decode("utf-8")
        assert "AT 星际公民助手" in html and "app.js" in html
        assert b"PAGES" in _u.urlopen(base + "/app.js").read()
        # 用出厂配装也破得开的石头（一个 Arbor MH2 最多 14,500 kg），不依赖这台电脑上存的配装
        body = _j.dumps({"mass": 8000, "resistance": 0, "instability": 1}).encode()
        req = _u.Request(
            base + "/api/manual_scan",
            data=body,
            headers={"Content-Type": "application/json", "X-Token": TOKEN},
        )
        r = _j.loads(_u.urlopen(req).read())
        assert r["ok"] and r["data"][0]["breakable"]
        for headers in (
            {},
            {"X-Token": "guess"},
            {"X-Token": TOKEN, "Origin": "https://evil.example"},
        ):
            try:  # 没口令、口令错、别的网站发来的：都拒绝
                _u.urlopen(
                    _u.Request(base + "/api/manual_scan", data=body, headers=headers)
                )
                assert False, headers
            except Exception as e:
                assert "403" in str(e), e
        try:
            _u.urlopen(base + "/api/events")
            assert False
        except Exception as e:
            assert "403" in str(e)
        req = _u.Request(base + "/api/nope", data=b"{}", headers={"X-Token": TOKEN})
        try:
            _u.urlopen(req)
            assert False
        except Exception as e:
            assert "404" in str(e)
        try:
            _u.urlopen(base + "/../settings.py")
            assert False
        except Exception as e:
            assert "404" in str(e)
    finally:
        srv.shutdown()


def test_first_run_agreement(monkeypatch, tmp_path):
    from astral_toolkit.bootstrap import status_sources
    from astral_toolkit.core import settings
    from astral_toolkit.tasks import system as t_sys
    from tests.bootstrap_helpers import app_for_test

    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    started = []
    with app_for_test() as app:
        sources = status_sources(app)

        def start():
            started.append("bg")
            return True

        assert settings.load()["agreed"] is False
        assert "error" in t_sys.agree(
            sources, start, text="本软件是免费的"
        )  # 差一个字都不行
        assert settings.load()["agreed"] is False and not started
        t_sys.agree(sources, start, text=" 本软件是免费软件 ")
        assert settings.load()["agreed"] is True and started == ["bg"]


def test_single_instance_lock_file(monkeypatch, tmp_path):
    """只开一个：第一个拿到锁，第二个拿不到；第一个放开后又能拿到（用临时文件夹，电脑上开着 AT 也不影响）"""
    import subprocess, sys  # noqa: E401
    from astral_toolkit.core import paths
    from astral_toolkit.app import server as S

    monkeypatch.setattr(paths, "USER", tmp_path)
    first = S._try_lock()
    assert first is not None
    try:  # 另一个进程（模拟第二个 AT）拿不到
        code = (
            "from pathlib import Path; from astral_toolkit.core import paths; paths.USER = Path(%r); "
            "from astral_toolkit.app import server as S; print(S._try_lock() is None)"
            % str(tmp_path)
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(S.Path(__file__).resolve().parents[1]),
        )
        assert out.stdout.strip().endswith("True"), out.stderr
    finally:
        first.close()
    again = S._try_lock()
    assert again is not None
    again.close()


def test_mask_overlay_blacks_out_hud():
    from PIL import Image
    from astral_toolkit.core.capture import mask_overlay

    img = Image.new("RGB", (100, 100), (255, 255, 255))
    mask_overlay(img, 50, 50, rect=(60, 60, 80, 70))  # 截图从屏幕 (50,50) 开始
    assert img.getpixel((15, 15)) == (0, 0, 0) and img.getpixel((5, 5)) == (
        255,
        255,
        255,
    )
    assert img.getpixel((35, 15)) == (255, 255, 255)


def test_perf_log_line_format():
    from astral_toolkit.core import perfmon

    m = perfmon.Monitor()
    m.prev = {"AT": (10.0, 200.0, 300.0), "窗口(Edge)": (5.0, 150.0, 120.0)}
    perfmon._take_ocr()
    perfmon.note_ocr(0.25)
    line = m.line(
        0, {"AT": (10.6, 210.0, 320.0), "窗口(Edge)": (5.06, 150.0, 120.0)}, 60.0
    )
    assert (
        "AT CPU" in line
        and "内存 210MB（提交 320MB）" in line
        and "窗口(Edge)" in line
        and "识别" in line
    )


def test_blas_threads_limited():
    """numpy 的数学库只开 1 个线程（不然 32 线程的电脑一加载就预留 740MB 内存）"""
    import os
    import astral_toolkit  # noqa: F401

    assert os.environ.get("OPENBLAS_NUM_THREADS") == "1"


def test_update_log_reaches_window(monkeypatch):
    """更新数据时几个源并行下载：各线程的输出都要进窗口的更新记录"""
    import sys
    from astral_toolkit.app import bus, task_runner
    import astral_toolkit.run as run
    from astral_toolkit.update import localization, uex
    from astral_toolkit.crafting import build_crafting
    from astral_toolkit.navigation import navigate

    logs = []
    monkeypatch.setattr(bus, "publish", lambda kind, msg: logs.append((kind, msg)))
    for m, n in (
        (localization, "update"),
        (uex, "refresh"),
        (build_crafting, "update"),
        (navigate, "update"),
        (shops, "update"),
        (loot, "update"),
    ):
        monkeypatch.setattr(m, n, lambda name=m.__name__: print(f"{name} ok"))
    from astral_toolkit.update import data_pack
    import astral_toolkit.gamedata as G

    monkeypatch.setattr(
        data_pack, "update", lambda progress=print: None
    )  # 不联网：当作数据包下不到，走各数据网站
    monkeypatch.setattr(
        G, "rebuild", lambda: None
    )  # 收尾 clear_caches 会补建游戏数据库：不碰真实 data/
    old = sys.stdout
    task_runner.install_router()
    try:
        task_runner.run_task("update", run.update, title="更新数据").join()
    finally:
        sys.stdout = old
    lines = [m["line"] for k, m in logs if k == "log"]
    assert sum("ok" in l for l in lines) == 6 and lines[-1] == "全部更新完成"  # noqa: E741


def test_export_logs(monkeypatch, tmp_path):
    """导出日志：日志 + 设置 + 系统说明打包到桌面；窗口文件夹（浏览器数据）不打进去"""
    import zipfile
    from astral_toolkit.core import paths
    from astral_toolkit.tasks import hover as t_hover, system as t_sys

    user = tmp_path / "userdata"
    (user / "logs").mkdir(parents=True)
    (user / "logs" / "app_log.txt").write_text(
        "启动\n→ C:\\Users\\SomeUser\\AppData\\Local\\AT\\data\\prices.json\n",
        encoding="utf-8",
    )
    (user / "logs" / "nav_log.txt").write_text("导航", encoding="utf-8")
    (user / "logs" / "runrec_2099-01-01.log").write_text(
        "2099-01-01 00:00:00.000 [INFO] [SYSTEM] 本机服务已启动\n", encoding="utf-8"
    )
    (user / "logs" / "runlog_2099-01-01.log").write_text(
        "00:00:00 [INFO] [HOVER] F8 价格与数据同步完成\n", encoding="utf-8"
    )
    (user / "logs" / "debug_2099-01-01.log").write_text(
        "00:00:00 [DEBUG] [识别] 识别路径开始\n", encoding="utf-8"
    )
    (user / "settings.json").write_text("{}", encoding="utf-8")
    (user / "window").mkdir()
    (user / "window" / "Cookies").write_text("隐私", encoding="utf-8")
    monkeypatch.setattr(paths, "USER", user)
    monkeypatch.setattr(paths, "LOGS", user / "logs")
    _v = False
    for _m in (t_hover, t_sys):
        monkeypatch.setattr(_m, "WIN", _v)
    monkeypatch.setattr(t_sys, "_desktop", lambda: tmp_path)
    r = t_sys.export_logs()
    names = zipfile.ZipFile(r["path"]).namelist()
    assert {
        "logs/app_log.txt",
        "logs/nav_log.txt",
        "logs/runrec_2099-01-01.log",
        "logs/runlog_2099-01-01.log",
        "logs/debug_2099-01-01.log",
        "settings.json",
        "系统信息.txt",
    } <= set(names)
    log = zipfile.ZipFile(r["path"]).read("logs/app_log.txt").decode("utf-8")
    assert (
        "启动" in log and "SomeUser" not in log
    )  # 导出时抹掉 Windows 用户名（调试模式复查）
    assert not any("window" in n or "Cookies" in n for n in names)
    info = zipfile.ZipFile(r["path"]).read("系统信息.txt").decode("utf-8")
    assert "AT 版本" in info and "Python" in info


def test_hotkey_conflicts(monkeypatch):
    """物品识别热键不能设成记路标 / 一键定位的键；已有冲突要明确说哪个失效"""
    from astral_toolkit import bootstrap
    from astral_toolkit.core import settings
    from astral_toolkit.tasks import system as t_sys
    from astral_toolkit.app import bus

    store = {
        **settings.DEFAULTS,
        "mark_key": "F7",
        "fix_key": "F9",
    }  # 1.0.5 起这两个默认不绑，这里是玩家自己绑了
    monkeypatch.setattr(settings, "load", lambda: dict(store))
    monkeypatch.setattr(
        settings, "update", lambda **kw: (store.update(kw), dict(store))[1]
    )
    monkeypatch.setattr(bus, "publish", lambda *a, **k: None)

    from tests.bootstrap_helpers import app_for_test

    # RT-B7：set_settings 会推一次状态：用这个 app 的状态源
    with app_for_test() as app:
        sources = bootstrap.status_sources(app)
        assert (
            "一键定位" in t_sys.set_settings(sources, trade_capture_key="F9")["error"]
        )
        assert (
            "记录路标" in t_sys.set_settings(sources, trade_capture_key="f7")["error"]
        )
        assert store["trade_capture_key"] == "F8"
        assert (
            t_sys.set_settings(sources, trade_capture_key="f11")["trade_capture_key"]
            == "F11"
        )  # F5 采矿助手、F6 盘点也占着（1.6.57）
        assert "盘点" in t_sys.set_settings(sources, trade_capture_key="F6")["error"]
        assert t_sys.hotkey_conflicts(store) == []
        w = t_sys.hotkey_conflicts({**store, "trade_capture_key": "F9"})
        assert len(w) == 1 and "一键定位" in w[0] and "/showlocation" in w[0]
        assert (
            "记录路标"
            in t_sys.hotkey_conflicts({**store, "trade_capture_key": "F7"})[0]
        )


def test_mask_own_window_too():
    """盖在游戏上的 AT 主窗口也涂黑（窗口里的实时栏有信号值 / 质量，会被当成游戏里的字）"""
    from PIL import Image
    from astral_toolkit.core.capture import mask_overlay, own_window_rects

    img = Image.new("RGB", (200, 100), (255, 255, 255))
    mask_overlay(img, 0, 0, rect=(10, 10, 20, 20), own=[(100, 50, 150, 90)])
    assert img.getpixel((15, 15)) == (0, 0, 0) and img.getpixel((120, 60)) == (0, 0, 0)
    assert img.getpixel((60, 60)) == (255, 255, 255)
    assert isinstance(own_window_rects(), list)  # 非 Windows 返回空列表，不报错


def test_bootstrap_wires_overlay_for_masking(monkeypatch):
    """截图涂黑用的悬浮窗句柄和「显示着没有」由装配（bootstrap.bind_all）接给 core/capture（core 不 import 界面，CL-C5）；
    每次读悬浮窗模块当时的值；没接当没有悬浮窗"""
    from astral_toolkit import bootstrap
    from astral_toolkit.app import overlay
    from astral_toolkit.core import capture, run_records

    monkeypatch.setattr(capture, "_overlay_state", None)  # 测完还原
    monkeypatch.setattr(run_records, "_ui_sink", None)
    assert capture._overlay() == (None, False) and capture.overlay_rect() is None
    bootstrap._bind_core_to_ui()
    monkeypatch.setattr(overlay, "HWND", 12345)
    monkeypatch.setattr(overlay, "SHOWN", True)
    assert capture._overlay() == (12345, True)
    monkeypatch.setattr(overlay, "SHOWN", False)
    assert capture._overlay() == (12345, False)


def test_feedback_report_bundle(monkeypatch, tmp_path):
    """一键问题反馈（F10 / 「报告问题」）：整屏截图 + 最近采矿助手截图 + OCR 原文 + 当时显示的结果 + 日志尾巴
    存成 userdata\\feedback\\<时间>_<类型>（文件夹 + zip）；导出把所有 zip 再打包到桌面；清空"""
    import json, zipfile  # noqa: E401, F811
    from PIL import Image
    from astral_toolkit import bootstrap
    from astral_toolkit.core import paths
    from astral_toolkit.mining import screen
    from astral_toolkit.tasks import (
        hover as t_hover,
        navigation as t_nav,
        system as t_sys,
    )
    from astral_toolkit.app import hud_state
    from tests.bootstrap_helpers import app_for_test

    monkeypatch.setattr(paths, "USER", tmp_path, raising=False)
    monkeypatch.setattr(paths, "LOGS", tmp_path / "logs", raising=False)
    monkeypatch.setattr(paths, "SHOTS", tmp_path / "shots", raising=False)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "live_log.txt").write_text(
        "\n".join(f"line {i}" for i in range(300)), encoding="utf-8"
    )  # noqa: E702
    import time as _time

    (tmp_path / "logs" / f"runrec_{_time.strftime('%Y-%m-%d')}.log").write_text(
        "2026-11-01 12:00:00.000 [INFO] [HOVER] 触发 F8 物品识别\n", encoding="utf-8"
    )
    (tmp_path / "shots" / "live").mkdir(parents=True)
    for i in range(7):
        Image.new("RGB", (8, 8)).save(tmp_path / "shots" / "live" / f"{i}.png")
    monkeypatch.setattr(t_sys, "_desktop", lambda: tmp_path / "desk")
    (tmp_path / "desk").mkdir()
    _v = lambda: type(  # noqa: E731
        "H",
        (),
        {"sections": {"信号": "x"}, "set": lambda *a: None, "clear": lambda *a: None},
    )()  # noqa: E731
    for _m in (t_nav, t_sys, hud_state):
        monkeypatch.setattr(_m, "_hud", _v)
    import threading

    monkeypatch.setattr(
        threading,
        "Timer",
        lambda *a, **k: type("T", (), {"start": lambda self: None})(),
    )  # 悬浮窗短提示 6 秒后自己收起：别在补丁还原后建真悬浮窗
    _v = False
    for _m in (t_hover, t_sys):
        monkeypatch.setattr(_m, "WIN", _v)
    screen.LAST_RAW.update(t=1.0, scan=["扫描结果", "质量： 123"], bag=[])
    from astral_toolkit.runtime.results import MINING_SIGNALS, ResultStore

    results = ResultStore()
    with app_for_test(results=results) as app:
        sources = bootstrap.status_sources(app)
        assert results.accept(
            MINING_SIGNALS, {"view": {}, "values": [44336]}, 1, 0, 1, 0.0, 0.0
        )
        r = t_sys.feedback_report(
            sources,
            kind="signal",
            note="屏幕是 33,000",
            img=Image.new("RGB", (64, 32)),
        )
        d = tmp_path / "feedback"
        assert (
            r["count"] == 1 and (d / r["dir"].split("\\")[-1].split("/")[-1]).is_dir()
        )
        folder = next(p for p in d.iterdir() if p.is_dir())
        names = {p.name for p in folder.iterdir()}
        assert (
            "屏幕.png" in names
            and "情况.json" in names
            and "说明.txt" in names
            and "live_log.txt" in names
        )
        assert any(n.startswith("runrec_") and n.endswith(".log") for n in names)
        assert "runrec_" in (folder / "说明.txt").read_text(encoding="utf-8")
        assert (
            sum(n.startswith("live_") and n.endswith(".png") for n in names) == 5
        )  # 最近 5 帧
        info = json.loads((folder / "情况.json").read_text(encoding="utf-8"))
        assert (
            info["note"] == "屏幕是 33,000"
            and info["kind"] == "signal"
            and info["shown_signal"]["values"] == [44336]
        )
        assert info["ocr_scan_lines"] == ["扫描结果", "质量： 123"]
        assert (
            len((folder / "live_log.txt").read_text(encoding="utf-8").splitlines())
            == 150
        )
        with zipfile.ZipFile(folder.with_suffix(".zip")) as z:
            assert any(n.endswith("屏幕.png") for n in z.namelist())
        t_sys.feedback_report(sources, kind="坏类型", img=Image.new("RGB", (8, 8)))
        rows = t_sys.feedback_list()
        assert len(rows) == 2 and rows[0]["name"].endswith(
            "_auto"
        )  # 不认识的类型按 auto
        e = t_sys.feedback_export()
        assert (
            e["files"] == 2
            and (tmp_path / "desk" / e["path"].split("\\")[-1].split("/")[-1]).exists()
        )
        assert t_sys.feedback_clear()["removed"] >= 4 and t_sys.feedback_list() == []
        assert "error" in t_sys.feedback_export()
        # 热键冲突：反馈键撞了别的键要提示
        assert any(
            "问题反馈" in w
            for w in t_sys.hotkey_conflicts({"trade_capture_key": "F10"})
        )
        from astral_toolkit.core import settings
        from astral_toolkit.app import bus

        store = dict(settings.DEFAULTS)  # 不读写真实设置
        monkeypatch.setattr(settings, "load", lambda: dict(store))
        monkeypatch.setattr(
            settings, "update", lambda **kw: (store.update(kw), dict(store))[1]
        )
        monkeypatch.setattr(bus, "publish", lambda *a, **k: None)
        r = t_sys.set_settings(sources, trade_capture_key="F10")
        assert "问题反馈" in r.get("error", ""), r
        assert store["trade_capture_key"] == "F8"  # 冲突时不保存


def test_disclaimer_and_about_have_required_notices():
    """免责声明和关于页（2026-10-26）：CIG 要求的非官方声明和权利人、版权、EULA 自动化风险、要求注明的数据来源"""
    from astral_toolkit.core import paths
    from astral_toolkit.tasks import system as t_sys

    h = (paths.CODE / "app" / "web" / "disclaimer.html").read_text(encoding="utf-8")
    for must in (
        "not affiliated with the Cloud Imperium group of companies",
        "Cloud Imperium Rights LLC",
        "Cloud Imperium Rights Limited",
        "© 2026 Adm_TT",
        "自动化软件",
        "api.star-citizen.wiki",
        "CC BY-SA 4.0",
        "第三方许可.txt",
    ):
        assert must in h, must
    info = t_sys.about_info()
    names = {x["name"] for x in info["sources"]}
    assert {
        "SCMiner",
        "UEX",
        "Star Citizen Wiki API",
        "Star Citizen Wiki",
        "星际公民掉落查询",
        "SC汉化盒子",
    } <= names
    assert all(x["url"].startswith("https://") for x in info["sources"])
    assert "text" in t_sys.third_party_licenses()


def test_feedback_upload_pack_send_retry(tmp_path, monkeypatch):
    """问题反馈自动发送（2026-10-27）：截图转 JPG 打包、发成写 .sent、服务器拒收不再重试、启动只补发 .pending 的"""
    import io
    import zipfile
    from PIL import Image
    from astral_toolkit.system import feedback_up as F
    from astral_toolkit.core import paths, settings

    monkeypatch.setattr(paths, "USER", tmp_path)
    monkeypatch.setattr(settings, "load", lambda: {"feedback_upload": True})
    monkeypatch.setenv("AT_FEEDBACK_OFF", "")  # 网络已换成假的（下面 fake）
    fb = tmp_path / "feedback"

    def make(name):
        d = fb / name
        d.mkdir(parents=True)
        Image.new("RGB", (640, 360), (20, 40, 60)).save(d / "屏幕.png")
        (d / "说明.txt").write_text("x", encoding="utf-8")
        (d / "evil.exe").write_bytes(b"MZ")
        return d

    d = make("20261027_171313_auto")
    names = zipfile.ZipFile(io.BytesIO(F.pack(d))).namelist()
    assert sorted(names) == [
        "20261027_171313_auto/屏幕.jpg",
        "20261027_171313_auto/说明.txt",
    ]
    sent = []

    class R:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=0):
        sent.append(req.headers)
        return R()

    monkeypatch.setattr(F.urllib.request, "urlopen", fake)
    F.mark_pending(d)
    assert F.send(d, "auto") == (True, "已发送", False)
    assert (d / ".sent").exists() and not (d / ".pending").exists()
    assert F.send(d, "auto")[0] and len(sent) == 1  # 发过的不重复发
    assert len(F.install_id()) == 12 and F.install_id() == F.install_id()

    old = make("20261020_100000_scan")  # 没有 .pending 的旧反馈不补发
    new = make("20261027_180000_signal")
    F.mark_pending(new)
    assert (
        F.retry_pending(fb) == 1
        and (new / ".sent").exists()
        and not (old / ".sent").exists()
    )

    bad = make("20261027_190000_item")
    F.mark_pending(bad)

    def reject(req, timeout=0):
        raise F.urllib.error.HTTPError(F.URL, 413, "too big", {}, None)

    monkeypatch.setattr(F.urllib.request, "urlopen", reject)
    ok, why, again = F.send(bad, "item")
    assert not ok and "413" in why and not again and not (bad / ".pending").exists()

    def down(req, timeout=0):
        raise OSError("down")

    monkeypatch.setattr(F.urllib.request, "urlopen", down)
    later = make("20261027_200000_auto")
    F.mark_pending(later)
    ok, why, again = F.send(later, "auto")
    assert not ok and again and (later / ".pending").exists()  # 连不上：留着下次发

    monkeypatch.setattr(settings, "load", lambda: {"feedback_upload": False})
    assert not F.enabled()
    monkeypatch.setattr(F.urllib.request, "urlopen", fake)
    n = len(sent)
    assert (
        F.send(later, "auto")[1] == "自动发送已关闭" and len(sent) == n
    )  # 关掉后排队的也不发
    assert F.retry_pending(fb) == 0 and len(sent) == n


def test_set_settings_tells_when_not_saved(monkeypatch, tmp_path):
    """设置文件暂时读不到（被杀毒、同步软件占着）或写不进去：这次改动没存上，设置页要告诉玩家再点一次，
    不能装作存好了（以前只在控制台打一行；待做原第 468 行）；读写正常照旧存上"""
    from astral_toolkit import bootstrap
    from astral_toolkit.app import bus
    from astral_toolkit.core import paths, settings
    from astral_toolkit.tasks import system as t_sys
    from tests.bootstrap_helpers import app_for_test

    monkeypatch.setattr(bus, "publish", lambda *a, **k: None)
    with app_for_test() as app:
        sources = bootstrap.status_sources(app)
        locked = tmp_path / "locked.json"
        locked.mkdir()  # 读这个「文件」报 OSError：和被别的程序占着一样
        monkeypatch.setattr(settings, "FILE", locked)
        r = t_sys.set_settings(sources, theme="light")
        assert "没存上" in r["error"] and "再点一次" in r["error"]
        ok = tmp_path / "ok.json"
        monkeypatch.setattr(settings, "FILE", ok)

        def busy(*a, **k):
            raise PermissionError("被别的程序占着")

        real = paths.write_json
        monkeypatch.setattr(paths, "write_json", busy)
        r = t_sys.set_settings(sources, theme="light")
        assert "写不进去" in r["error"] and "没存上" in r["error"]
        monkeypatch.setattr(paths, "write_json", real)
        r = t_sys.set_settings(sources, theme="light")
        assert r.get("theme") == "light" and settings.load()["theme"] == "light"


def test_set_hotkey_unread_settings_says_not_saved(monkeypatch, tmp_path):
    """改热键先读设置查撞键：设置文件暂时读不到时拿到的只是默认值，按默认值查会误报「F8 已用于物品识别」，
    要直接说这次没存上、再点一次（s1 复查）；读得到时按真实设置查"""
    import json

    from astral_toolkit import bootstrap
    from astral_toolkit.app import bus
    from astral_toolkit.core import settings
    from astral_toolkit.tasks import system as t_sys
    from tests.bootstrap_helpers import app_for_test

    monkeypatch.setattr(bus, "publish", lambda *a, **k: None)
    with app_for_test() as app:
        sources = bootstrap.status_sources(app)
        locked = tmp_path / "locked.json"
        locked.mkdir()  # 读这个「文件」报 OSError：和被别的程序占着一样
        monkeypatch.setattr(settings, "FILE", locked)
        r = t_sys.set_settings(sources, live_key="F8")  # 默认值里 F8 是物品识别
        assert "没存上" in r["error"] and "已用于" not in r["error"]
        ok = tmp_path / "ok.json"
        ok.write_text(json.dumps({"trade_capture_key": "F11"}), encoding="utf-8")
        monkeypatch.setattr(settings, "FILE", ok)
        r = t_sys.set_settings(sources, live_key="F8")  # 物品识别早改成 F11：F8 空着
        assert r.get("live_key") == "F8" and settings.load()["live_key"] == "F8"
