"""读屏区域文件（core/screen_regions）：按屏幕比例存、挑最接近的比例、坏了用默认值、存时防覆盖"""

import json

from astral_toolkit.core import screen_regions as sr
from tests.minipytest import raises

D = (0.1, 0.2, 0.3, 0.4)
A = (0.5, 0.1, 0.9, 0.6)
B = (0.6, 0.2, 0.8, 0.7)


def _use(tmp_path, monkeypatch, data=None, raw=None):
    p = tmp_path / "r.json"
    monkeypatch.setattr(sr, "PATH", p)
    if raw is not None:
        p.write_text(raw, encoding="utf-8")
    elif data is not None:
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def test_frac_falls_back_to_default_when_missing_or_broken(tmp_path, monkeypatch):
    p = _use(tmp_path, monkeypatch)
    assert sr.frac("x.y", D) == D  # 没文件
    p.write_text("{坏的", encoding="utf-8")
    assert sr.frac("x.y", D) == D  # 坏文件
    p.write_text(
        '{"version":1,"regions":{"x.y":[{"aspect":"16:9"}]}}', encoding="utf-8"
    )
    assert sr.frac("x.y", D) == D  # 缺 box
    p.write_text(
        '{"version":1,"regions":{"x.y":[{"aspect":"16:9","box":[0.5,0.5,0.2,0.9]}]}}',
        encoding="utf-8",
    )
    assert sr.frac("x.y", D) == D  # 左 ≥ 右：不认
    p.write_text('{"version":1,"regions":[]}', encoding="utf-8")
    assert sr.frac("x.y", D) == D  # regions 不是表


def test_frac_picks_nearest_aspect(tmp_path, monkeypatch):
    _use(
        tmp_path,
        monkeypatch,
        {
            "version": 1,
            "regions": {
                "x.y": [
                    {"aspect": "16:9", "box": list(A), "kind": "read"},
                    {"aspect": "21:9", "box": list(B), "kind": "read"},
                ]
            },
        },
    )
    assert sr.frac("x.y", D, (2560, 1440)) == A
    assert sr.frac("x.y", D, (3440, 1440)) == B
    assert sr.frac("x.y", D, (1920, 1200)) == A  # 16:10 离 16:9 更近
    assert sr.frac("x.y", D) == A  # 没给尺寸取第一条
    assert sr.px("x.y", (0, 0, 1, 1), (2560, 1440)) == (
        int(2560 * A[0]),
        int(1440 * A[1]),
        int(2560 * A[2]),
        int(1440 * A[3]),
    )


def test_aspect_names():
    assert sr.aspect_of((2560, 1440)) == "16:9"
    assert sr.aspect_of((1920, 1200)) == "16:10"
    assert sr.aspect_of((3440, 1440)) == "21:9"
    assert sr.aspect_of((1280, 720)) == "16:9"
    assert sr.aspect_of((1280, 1024)) == "5:4"


def test_save_rejects_stale_version(tmp_path, monkeypatch):
    p = _use(tmp_path, monkeypatch)
    v = sr.load()["version"]
    first = {
        "x.y": [{"aspect": "16:9", "box": list(A), "kind": "read", "note": "第一次"}]
    }
    v2 = sr.save(first, v)
    assert v2 == v + 1
    with raises(sr.StaleRegions):
        sr.save(
            {"x.y": [{"aspect": "16:9", "box": list(B), "kind": "read", "note": ""}]}, v
        )
    assert (
        json.loads(p.read_text(encoding="utf-8"))["regions"]["x.y"][0]["note"]
        == "第一次"
    )
    assert sr.frac("x.y", D) == A  # 存后重新读到新值


def test_save_validates_boxes(tmp_path, monkeypatch):
    p = _use(tmp_path, monkeypatch, {"version": 3, "regions": {}})
    before = p.read_text(encoding="utf-8")
    bad = [
        [{"aspect": "16:9", "box": [0.1, 0.2, 1.3, 0.4], "kind": "read"}],  # 超出 0~1
        [{"aspect": "16:9", "box": [0.5, 0.2, 0.3, 0.4], "kind": "read"}],  # 左 ≥ 右
        [{"aspect": "16:9", "box": [0.1, 0.5, 0.3, 0.4], "kind": "read"}],  # 上 ≥ 下
        [
            {"aspect": "16:9", "box": [0.1, 0.2, 0.3, 0.4], "kind": "别的"}
        ],  # kind 不认识
        [
            {"aspect": "宽", "box": [0.1, 0.2, 0.3, 0.4], "kind": "read"}
        ],  # aspect 写法不对
    ]
    for entries in bad:
        with raises(ValueError):
            sr.save({"x.y": entries}, 3)
    assert p.read_text(encoding="utf-8") == before
