"""读屏开发工作台（tools/readlab）：统一接口、本机服务、批量报告。假图，不读真截图、不碰真实设置"""

from pathlib import Path

from PIL import Image

from astral_toolkit.core import screen_regions
from tests.test_cell_grid import _inventory
from tools.readlab import features

KEYS = ("count", "hover", "mining", "radar", "nav")


def test_every_feature_returns_a_result_on_a_blank_image():
    img = Image.new("RGB", (2560, 1440))
    for key in KEYS:
        for batch in (False, True):
            r = features.run(key, img, (1280, 720), batch=batch)
            assert isinstance(r, features.Result) and r.ms >= 0, key
            assert r.error == "", (key, r.error)
            assert r.lines, key  # 认不出也要说一句


def test_errors_are_captured(monkeypatch):
    from astral_toolkit.mining import screen

    monkeypatch.setattr(screen, "analyse", lambda img: 1 / 0)
    r = features.run("mining", Image.new("RGB", (2560, 1440)), None, batch=True)
    assert "ZeroDivisionError" in r.error
    assert features.run(
        "没这个功能", Image.new("RGB", (100, 100)), None, batch=True
    ).error


def test_count_marks_the_cell_box():
    r = features.run("count", _inventory(), (2240, 700), batch=False)
    assert any(s.color == "hit" and abs(s.box[0] - 2171) <= 4 for s in r.shapes), (
        r.shapes
    )
    gap = features.run("count", _inventory(), (2019, 700), batch=False)
    assert any("缝" in line for line in gap.lines)


def test_shapes_use_known_colors():
    for key in KEYS:
        r = features.run(key, _inventory(), (2240, 700), batch=False)
        assert all(s.color in features.COLORS for s in r.shapes), key


def test_regions_listed_exist():
    keys = set(screen_regions.load()["regions"])
    for f in features.FEATURES.values():
        assert f.regions and set(f.regions) <= keys, f.key


def test_non_16_9_images_still_work():
    for size in ((1280, 800), (3440, 1440), (1280, 720)):
        r = features.run(
            "hover", Image.new("RGB", size), (size[0] // 2, size[1] // 2), batch=False
        )
        assert r.error == "", (size, r.error)


def test_report_lists_every_row_and_errors(tmp_path):
    from tools.readlab import report

    img = Image.new("RGB", (2560, 1440))
    ok = features.Result(
        shapes=[features.Shape((10, 10, 200, 200), "框", "hit")],
        lines=["认出 <甲>"],
        ms=12,
    )
    bad = features.Result(error="ZeroDivisionError: x", ms=3)
    rows = [
        ("a.png", (2560, 1440), ok, img),
        ("b.png", (3440, 1440), bad, img),
        ("c.png", (2560, 1440), ok, img),
    ]
    page = report.write("count", rows, tmp_path)
    text = page.read_text(encoding="utf-8")
    assert text.count("<img") == 3
    assert "出错 1 张" in text and "21:9 1 张" in text and "16:9 2 张" in text
    assert "&lt;甲&gt;" in text  # 内容转义
    pics = page.with_suffix("")
    assert len(list(pics.glob("*.jpg"))) == 3


# ---------------------------------------------------------------- 本机服务
import json as _json  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from urllib.parse import quote  # noqa: E402


class _Srv:
    def __init__(self, tmp_path, monkeypatch, n=1):
        from tools.readlab import server

        root = tmp_path / "样本"
        (root / "盘点").mkdir(parents=True)
        _inventory().save(root / "盘点" / "inv.png")
        for i in range(n - 1):
            Image.new("RGB", (2560, 1440)).save(root / f"b{i}.png")
        (tmp_path / "secret.png").write_bytes(b"x")
        monkeypatch.setattr(screen_regions, "PATH", tmp_path / "regions.json")
        self.httpd = server.make_server([root], 0, report_dir=tmp_path / "报告")
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def call(self, method, path, body=None):
        data = None if body is None else _json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return r.status, (
                    _json.loads(raw)
                    if r.headers.get_content_type() == "application/json"
                    else raw
                )
        except urllib.error.HTTPError as e:
            raw = e.read()
            return e.code, (_json.loads(raw) if raw[:1] == b"{" else raw)

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_server_lists_samples_and_serves_images(tmp_path, monkeypatch):
    s = _Srv(tmp_path, monkeypatch)
    try:
        st, samples = s.call("GET", "/api/samples")
        assert st == 200 and [x["id"] for x in samples] == ["0/盘点/inv.png"]
        assert (samples[0]["w"], samples[0]["h"]) == (2560, 1440)
        st, raw = s.call("GET", "/api/image?id=" + quote("0/盘点/inv.png"))
        assert st == 200 and raw[:4] == b"\x89PNG"
        st, feats = s.call("GET", "/api/features")
        assert {f["key"] for f in feats} == {"count", "hover", "mining", "radar", "nav"}
        st, page = s.call("GET", "/")
        assert st == 200
    finally:
        s.close()


def test_image_outside_roots_is_forbidden(tmp_path, monkeypatch):
    s = _Srv(tmp_path, monkeypatch)
    try:
        for bad in (
            "0/../secret.png",
            "0/" + str(tmp_path / "secret.png"),
            "9/x.png",
            "x",
            "0/盘点/没有.png",
        ):
            assert s.call("GET", "/api/image?id=" + quote(bad))[0] in (403, 404), bad
        assert s.call("GET", "/api/image?id=" + quote("0/../secret.png"))[0] == 403
        assert s.call("GET", "/static/../server.py")[0] in (403, 404)
    finally:
        s.close()


def test_regions_put_conflict_and_validation(tmp_path, monkeypatch):
    s = _Srv(tmp_path, monkeypatch)
    try:
        v = s.call("GET", "/api/regions")[1]["version"]
        good = {
            "x.y": [
                {
                    "aspect": "16:9",
                    "box": [0.1, 0.1, 0.5, 0.5],
                    "kind": "read",
                    "note": "",
                }
            ]
        }
        st, r = s.call("PUT", "/api/regions", {"version": v, "regions": good})
        assert st == 200 and r["version"] == v + 1
        st, r = s.call("PUT", "/api/regions", {"version": v, "regions": good})
        assert st == 409 and "刷新" in r["error"]
        bad = {"x.y": [{"aspect": "16:9", "box": [0.5, 0.1, 0.1, 0.5], "kind": "read"}]}
        assert (
            s.call("PUT", "/api/regions", {"version": v + 1, "regions": bad})[0] == 400
        )
    finally:
        s.close()


def test_try_returns_result(tmp_path, monkeypatch):
    s = _Srv(tmp_path, monkeypatch)
    try:
        st, r = s.call(
            "POST",
            "/api/try",
            {"feature": "count", "id": "0/盘点/inv.png", "point": [2240, 700]},
        )
        assert (
            st == 200
            and r["error"] == ""
            and any(x["color"] == "hit" for x in r["shapes"])
        )
        assert (
            s.call(
                "POST",
                "/api/try",
                {"feature": "count", "id": "0/../secret.png", "point": None},
            )[0]
            == 403
        )
    finally:
        s.close()


def test_batch_progress_report_and_cancel(tmp_path, monkeypatch):
    def slow(feature, img, point, batch):
        time.sleep(0.3)
        return features.Result(lines=["好"])

    monkeypatch.setattr(features, "run", slow)
    s = _Srv(tmp_path, monkeypatch, n=5)
    try:
        job = s.call("POST", "/api/batch", {"feature": "mining"})[1]["job"]
        for _ in range(100):
            st = s.call("GET", f"/api/batch/{job}")[1]
            if st["done"] >= 1:
                break
            time.sleep(0.05)
        s.call("DELETE", f"/api/batch/{job}")
        for _ in range(100):
            st = s.call("GET", f"/api/batch/{job}")[1]
            if st["finished"]:
                break
            time.sleep(0.05)
        assert (
            st["finished"] and st["total"] == 5 and st["done"] < 5 and st["cancelled"]
        )
        assert st["report"] and Path(st["report"]).exists()  # 取消了也把跑完的出报告
        job2 = s.call(
            "POST", "/api/batch", {"feature": "mining", "ids": ["0/盘点/inv.png"]}
        )[1]["job"]
        for _ in range(100):
            st = s.call("GET", f"/api/batch/{job2}")[1]
            if st["finished"]:
                break
            time.sleep(0.05)
        assert st["total"] == 1 and st["done"] == 1 and st["errors"] == 0
    finally:
        s.close()


def test_binds_localhost_only(tmp_path):
    from tools.readlab import server

    httpd = server.make_server([tmp_path], 0)
    try:
        assert httpd.server_address[0] == "127.0.0.1"
    finally:
        httpd.server_close()
