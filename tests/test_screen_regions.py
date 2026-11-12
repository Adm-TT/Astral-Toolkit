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


def test_cell_coord_space_allows_out_of_range(tmp_path, monkeypatch):
    """coord_space=cell 时 box 可越出 [0,1]（角标贴角）"""
    _use(
        tmp_path,
        monkeypatch,
        {
            "version": 1,
            "regions": {
                "inventory.cell.quality": [
                    {
                        "aspect": "16:9",
                        "box": [-0.1, -0.12, 0.48, 0.28],
                        "kind": "read",
                        "coord_space": "cell",
                    }
                ]
            },
        },
    )
    assert sr.frac("inventory.cell.quality", D) == (-0.1, -0.12, 0.48, 0.28)
    # 无 cell 标记仍拒绝越界
    with raises(ValueError):
        sr.save(
            {
                "bad": [
                    {
                        "aspect": "16:9",
                        "box": [-0.1, 0.0, 0.5, 0.5],
                        "kind": "read",
                    }
                ]
            },
            1,
        )


# 读屏开发工作台第 2 步：原来写死在代码里的区域原样搬进区域文件（老大 11-09；值逐位不变）
SHIPPED = {
    "hover.band_30_50": (0.30, 0.0, 0.50, 1.0),
    "hover.band_50_70": (0.50, 0.0, 0.70, 1.0),
    "hover.band_30_70": (0.30, 0.0, 0.70, 1.0),
    "hover.title_rows": (0.0, 0.24, 1.0, 0.3),
    "hover.body_rows": (0.0, 0.24, 1.0, 0.70),
    "mining.search": (0.55, 0.33, 1.0, 0.80),
    "mining.center_tag": (0.42, 0.30, 0.58, 0.47),
    "nav.displayinfo": (0.66, 0.0, 1.0, 0.22),
}


def test_shipped_regions_equal_code_defaults():
    from astral_toolkit.mining import screen, signals
    from astral_toolkit.navigation import displayinfo
    from astral_toolkit.trade import inspector

    data = json.loads(sr.PATH.read_text(encoding="utf-8"))
    regions = data["regions"]
    assert set(SHIPPED) <= set(
        regions
    )  # 盘点等新区域（count.*）是后来画的，不在这张表里
    for key, box in SHIPPED.items():
        (entry,) = regions[key]
        assert tuple(entry["box"]) == box, key
        assert entry["aspect"] == "16:9" and entry["kind"] == "read" and entry["note"]
    # 默认比例只在 inventory_panel；inspector 别名同源（区域文件缺了就用它们）
    from astral_toolkit.trade import inventory_panel as inv

    assert inv.HOVER_BANDS["30-50%"] == SHIPPED["hover.band_30_50"]
    assert inv.HOVER_BANDS["50-70%"] == SHIPPED["hover.band_50_70"]
    assert inv.HOVER_BANDS["30-70%"] == SHIPPED["hover.band_30_70"]
    assert inv.HOVER_BANDS["中间"] == SHIPPED["hover.band_30_70"]
    assert inv.TITLE_ROWS == (0.24, 0.30) and inv.BODY_ROWS == (0.24, 0.70)
    assert inspector.HOVER_REGIONS is inv.HOVER_BANDS
    assert (inspector.TITLE_Y0, inspector.TITLE_Y1) == inv.TITLE_ROWS
    assert (inspector.BODY_Y0, inspector.BODY_Y1) == inv.BODY_ROWS
    assert screen.SEARCH == SHIPPED["mining.search"]
    assert signals.CENTER_TAG == SHIPPED["mining.center_tag"]
    assert displayinfo.REGION == SHIPPED["nav.displayinfo"]


def test_readers_follow_the_region_file(tmp_path, monkeypatch):
    """在区域文件里改了，读屏代码就按新的取；文件里没有就用原来的值"""
    from PIL import Image

    from astral_toolkit.mining import screen
    from astral_toolkit.navigation import displayinfo
    from astral_toolkit.trade import inspector

    W, H = 2560, 1440
    regs = inspector.get_hover_regions(
        (int(W * 0.8), H // 2), W
    )  # 鼠标在右边：先找 50-70% 带
    before = inspector.get_stage_regions(regs, W, H)
    assert before[0][0] == (int(W * 0.5), int(H * 0.24), int(W * 0.7), int(H * 0.30))

    entry = lambda box: [{"aspect": "16:9", "box": box, "kind": "read", "note": "测试"}]  # noqa: E731
    _use(
        tmp_path,
        monkeypatch,
        {
            "version": 1,
            "regions": {
                "hover.band_50_70": entry([0.52, 0.0, 0.66, 1.0]),
                "hover.title_rows": entry([0.0, 0.25, 1.0, 0.33]),
                "mining.search": entry([0.6, 0.3, 0.9, 0.7]),
                "nav.displayinfo": entry([0.7, 0.0, 1.0, 0.2]),
            },
        },
    )
    after = inspector.get_stage_regions(regs, W, H)
    assert after[0][0] == (int(W * 0.52), int(H * 0.25), int(W * 0.66), int(H * 0.33))
    assert inspector.region_box("50-70%@title", W, H) == after[0][0]
    assert inspector.region_box("30-70%@body", W, H) == (
        int(W * 0.3),
        int(H * 0.24),
        int(W * 0.7),
        int(H * 0.7),
    )
    img = Image.new("RGB", (W, H))
    assert screen._search(img) == (0.6, 0.3, 0.9, 0.7)
    piece = displayinfo.crop(img)
    assert piece.size == (int(W * 1.0) - int(W * 0.7), int(H * 0.2)) or piece.size == (
        (int(W * 1.0) - int(W * 0.7)) * displayinfo.UPSCALE,
        int(H * 0.2) * displayinfo.UPSCALE,
    )


def test_frac_survives_hand_broken_files(tmp_path, monkeypatch):
    """区域文件被手改坏：读屏照常，用默认值，不抛（审查 11-09）"""
    p = _use(tmp_path, monkeypatch)
    for regions in (
        {"x.y": 1},
        {"x.y": [{"aspect": 16, "box": list(A)}]},
        {"x.y": [{"aspect": ["16", "9"], "box": list(A)}]},
        {
            "x.y": [{"aspect": "16:9", "box": [0.5, 0.0, 0.5001, 1.0]}]
        },  # 窄到裁出 0 像素
        {"x.y": [{"aspect": "16:9", "box": "0,0,1,1"}]},
    ):
        p.write_text(json.dumps({"version": 1, "regions": regions}), encoding="utf-8")
        assert sr.frac("x.y", D, (2560, 1440)) == D, regions


def test_frac_ignores_exclude_and_far_aspects(tmp_path, monkeypatch):
    _use(
        tmp_path,
        monkeypatch,
        {
            "version": 1,
            "regions": {
                "ex.y": [{"aspect": "16:9", "box": list(A), "kind": "exclude"}],
                "wide.y": [{"aspect": "21:9", "box": list(B), "kind": "read"}],
            },
        },
    )
    assert sr.frac("ex.y", D, (2560, 1440)) == D  # 排除区不当要认的区域用
    assert sr.frac("wide.y", D, (2560, 1440)) == D  # 只有 21:9 的：16:9 不借，用默认值
    assert sr.frac("wide.y", D, (3440, 1440)) == B


def test_read_failure_is_not_cached(tmp_path, monkeypatch):
    p = _use(
        tmp_path,
        monkeypatch,
        {
            "version": 1,
            "regions": {"x.y": [{"aspect": "16:9", "box": list(A), "kind": "read"}]},
        },
    )
    real = type(p).read_text
    calls = []

    def flaky(self, *a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError("被占用")
        return real(self, *a, **k)

    monkeypatch.setattr(type(p), "read_text", flaky)
    assert sr.frac("x.y", D) == D  # 这次读不到
    assert sr.frac("x.y", D) == A  # 下次照常读到，不是一直用默认值
