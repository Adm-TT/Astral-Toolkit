"""右上角调试信息「认字模」（gridtext，2026-10-26）：
等宽字按网格切格、每格和字模比对，几毫秒认完一帧，位置才做得到实时。
两张真实截图：2560×1440 新巴贝奇医院（亮墙背景）、2560×1600 尼克斯基格小行星带采矿基地（黑背景）"""

import time

import numpy as np
import pytest
from PIL import Image

from sc_mining.core.paths import SAMPLES

ROWS_1440 = {
    7: "Zone: ObjectContainer-Ground_Lobby Pos: -4.61m 74.93m 11.71m",
    20: "Zone: OOC_Stanton_4_Microtech Pos: 520.9152km 419.2893km 744.0843km",
    33: "Zone: SolarSystem_862949775749 Pos: 22462326.4853km 37186368.6338km 744.0843km",
    46: "Zone: Root Pos: 22462326.4853km 37186368.6338km 744.0843km",
    197: "Current player location : Hospital Stanton4 NewBabbage (LZ : Stanton4 NewBabbage)",
    210: "Planet:OOC_Stanton_4_Microtech (Load Complete)",
    224: "CamPos Planet Zone: 520915.218755 419289.333861 744084.256923",
}
ROWS_1600 = {
    7: "CamDir: 52 27 -176 FOV: 64 Focal: 3.00 FStop: 64.0",
    21: "Zone: AEGS_Reclaimer_Teach_902805276679 Pos: -3.86m 54.85m -4.83m",
    36: "Zone: keeger_segment_mission_genrl_001_009 Pos: 93.0795km 64.7646km -42.6401km",
    50: "Zone: SolarSystem_862685702877 Pos: -4634409.3882km -47775658.1227km -42.6401km",
    65: "Zone: Root Pos: -4634409.3882km -47775658.1227km -42.6401km",
    290: "Current player location : AsteroidCluster_MiningBase_Nyx_Keeger",
}


def _sample(name):
    p = SAMPLES / name
    if not p.exists():
        pytest.skip(f"没有样本 {name}")
    return np.asarray(Image.open(p).convert("RGB"))


def _fresh(monkeypatch, tmp_path):
    from sc_mining.navigation import gridtext as G

    monkeypatch.setattr(G, "GLYPH_DIR", tmp_path / "glyphs")  # 不碰用户自己的字模
    G._state.update(glyphs=None, h=None, tried_load=False, font_at=0.0)
    return G


def _learn(G, arr, rows, h, skip=None, times=3):
    ocr = [(t, top + 6) for top, t in rows.items() if top != skip]
    for _ in range(times):
        r = G.feed(arr, ocr, h)
    return r


@pytest.mark.parametrize(
    "name,rows,h",
    [
        ("displayinfo_tr_1440.png", ROWS_1440, 1440),
        ("displayinfo_tr_1600.png", ROWS_1600, 1600),
    ],
)
def test_grid_fits_monospace(monkeypatch, tmp_path, name, rows, h):
    """网格：行距、字距按分辨率缩放（1080p 字距 5.62 像素），格子边界明显比别处干净；小字号单独拟合"""
    G = _fresh(monkeypatch, tmp_path)
    arr = _sample(name)
    tm = G.textness(arr)
    g = G.Grid(h, tm)
    assert g.ok
    adv, _ = g.adv["main"]
    assert abs(adv - G.ADV_1080 * h / 1080) < 0.1
    assert abs(g.adv["small"][0] - adv * G.SMALL) < 0.15
    assert abs(g.pitch - G.PITCH_1080 * h / 1080) < 0.6
    tops = G.row_tops(tm)
    assert all(any(abs(t - top) <= 1 for t in tops) for top in rows)
    loc_top = next(top for top, t in rows.items() if "player" in t)
    assert g.scale_of(tm, loc_top) == "small" and g.scale_of(tm, min(rows)) == "main"


@pytest.mark.parametrize(
    "name,rows,h",
    [
        ("displayinfo_tr_1440.png", ROWS_1440, 1440),
        ("displayinfo_tr_1600.png", ROWS_1600, 1600),
    ],
)
def test_learn_from_ocr_then_read_every_row(monkeypatch, tmp_path, name, rows, h):
    """用识别引擎认出来的几行文字学字模（亮背景上也要学得会），学完整块每一行都认对；字模存到文件、再读回来一样能认"""
    G = _fresh(monkeypatch, tmp_path)
    arr = _sample(name)
    n, ok = _learn(G, arr, rows, h)
    assert ok and G.ready(h) and not G.status()["missing"]
    got = {top: text for top, text, _, _ in G.read_rows(arr, h)}
    for top, text in rows.items():
        if not G.trusted(text) or "player" in text:
            continue  # 只学格式固定的行；地点行另用识别引擎认
        read = got[min(got, key=lambda t: abs(t - top))]
        exp, have = text.replace(" ", ""), read.replace(" ", "")
        assert len(exp) == len(have), (top, read)
        roles = G._roles(text)
        for a, b, role in zip(
            exp, have, roles
        ):  # 格式固定的字（数字、Zone、Pos、km…）一个不能错
            if role == "fixed":
                assert a == b, (top, read)
        # 区域名：只学和学过的字对得上的，一帧样本少时允许个别字母认不出，但大部分要对（O/0 这类易混字算对）
        nm = [(a, b) for a, b, role in zip(exp, have, roles) if role == "name"]
        if nm:
            assert sum(G.fold(a) == G.fold(b) for a, b in nm) >= 0.7 * len(nm), (
                top,
                read,
            )
    assert (tmp_path / "glyphs" / f"{h}_v2.npz").exists()
    G._state.update(glyphs=None, h=None, tried_load=False)
    assert G.ready(h)  # 从文件读回来
    zr = [top for top, t in rows.items() if t.startswith("Zone")]
    got2 = {top: text for top, text, _, _ in G.read_rows(arr, h, only=[zr[-1], zr[0]])}
    assert len(got2) == 2 and got2[max(got2)].split() == rows[zr[-1]].split()


def test_reads_unseen_coordinates(monkeypatch, tmp_path):
    """没学过的那一行（Root 坐标）也认得出：数字、小数点、负号、km 一个不错"""
    G = _fresh(monkeypatch, tmp_path)
    arr = _sample("displayinfo_tr_1600.png")
    _learn(G, arr, ROWS_1600, 1600, skip=65)
    g = G._state["glyphs"]
    text, conf, scale = g.read_row(G.textness(arr), 65)
    assert scale == "main" and text.split() == ROWS_1600[65].split() and conf > 0.6


def test_bright_wall_noise_is_not_ink(monkeypatch, tmp_path):
    """亮墙上的杂讯（textness 最多 110 上下、零零星星）不算字；下划线（半透明细横线，只有 100 左右亮）算字"""
    G = _fresh(monkeypatch, tmp_path)
    arr = _sample("displayinfo_tr_1440.png")
    tm = G.textness(arr)
    g = G.Grid(1440, tm)
    cells = g.cells(tm, 20, "main")
    ink = G._inks(cells) >= 3
    assert int(ink.sum()) == len(ROWS_1440[20].replace(" ", ""))
    assert not G._inks(cells[:10]).any()  # 行首左边的空白


def test_wrong_ocr_text_is_not_learned(monkeypatch, tmp_path):
    """识别引擎认错了字数对不上的行不学；全学错时自检不过、不存文件"""
    G = _fresh(monkeypatch, tmp_path)
    arr = _sample("displayinfo_tr_1600.png")
    wrong = {top: "Zone: xx Pos: 1km 2km 3km" for top in ROWS_1600}
    n, ok = _learn(G, arr, wrong, 1600)
    assert not ok and not (tmp_path / "glyphs" / "1600_v2.npz").exists()


def test_displayinfo_fast_path_and_fallback(monkeypatch, tmp_path):
    """displayinfo.read：用字体画出字模后几毫秒认完（fast=True，坐标、地点都对）；字体不能用、又没学过时走识别引擎（fast=False）"""
    from sc_mining.navigation import displayinfo as D

    G = _fresh(monkeypatch, tmp_path)
    full = (
        Image.open(SAMPLES / "displayinfo.png").convert("RGB")
        if (SAMPLES / "displayinfo.png").exists()
        else None
    )
    if full is None:
        pytest.skip("没有样本 displayinfo.png")
    D._grid_layout.update(tops=None, at=0.0)
    D._layout.update(at=0.0, boxes=None)
    calls = []
    monkeypatch.setattr(
        "sc_mining.ocr.recognize", lambda img, **k: calls.append("full") or []
    )
    loc_text = "Current player location : Hospital Stanton4 NewBabbage (LZ : Stanton4 NewBabbage)"
    zone_text = "Zone: OOC_Stanton_4_Microtech Pos: 520.9152km 419.2893km 744.0843km"
    answers = iter([loc_text, zone_text])  # 先认地点那一行，再认区域名那一行
    monkeypatch.setattr(
        "sc_mining.ocr.read_line",
        lambda img: calls.append("line") or (next(answers), 0.9),
    )
    D._loc.update(hash=None, text="", at=0.0, top=None)
    D._zones.update(map={}, at=0.0)
    font = G.FONT_FILE
    monkeypatch.setattr(G, "FONT_FILE", tmp_path / "没有这个字体.ttf")
    info = D.read(full)
    assert not info["fast"] and calls == [
        "full"
    ]  # 没有字体、也没学过：识别引擎（这里被换掉了）
    monkeypatch.setattr(G, "FONT_FILE", font)
    G._state["font_at"] = 0.0
    calls.clear()
    info = D.read(full)  # 有字体：当场画字模，第一帧就是快速路径，不用校准
    assert info["fast"] and calls == [
        "line",
        "line",
    ]  # 只有地点、区域名这两行交给识别引擎（变了才认）
    assert (
        G.status()["source"] == "font"
        and (tmp_path / "glyphs" / "1440_v2.npz").exists()
    )
    assert info["zone"] == "OOC Stanton 4 Microtech"
    assert all(
        abs(a - b) < 1
        for a, b in zip(info["global"], (22462326.4853e3, 37186368.6338e3, 744.0843e3))
    )
    from sc_mining.navigation import navigate as n

    assert info["solar_id"] == "862949775749"
    if n.CACHE.exists() and n.load().get(
        "bodies"
    ):  # 没有星图就不读（load 会去联网下载、写 data\）
        assert n.zone_body(info["zone"]) == n.zone_body(
            "OOC_Stanton_4_Microtech"
        )  # 区域名个别字母认成易混字也能对上星球
    assert all(
        abs(a - b) < 1e-3 for a, b in zip(info["local"], (520.9152, 419.2893, 744.0843))
    )
    assert info["camdir"] is None  # 这张截图没开 CamDir 那行
    assert "NewBabbage" in info["location"] and "Hospital" in info["location"]
    assert D._grid_layout["tops"] and len(D._grid_layout["tops"]) >= 4
    info2 = D.read(full)  # 第二次只认记下的那几行
    assert (
        info2["fast"]
        and info2["global"] == info["global"]
        and calls == ["line", "line"]
    )  # 地点、区域名都没变：不再认
    assert "NewBabbage" in info2["location"]


def test_system_from_solar_id_and_zone(monkeypatch, tmp_path):
    """星系判断：地点里的星系名 > SolarSystem 编号（学过的）> 区域名对上的地点 > 最近的星球（只猜，不记）。
    尼克斯基格小行星带的坐标按「最近星球」会猜错，右上角线索能救回来；学到的编号存到临时目录"""
    from sc_mining.navigation import navigate as n

    if (
        not n.CACHE.exists()
    ):  # 先判断再 load：load 在没有数据时会联网下载（S2 审查 2026-10-31）
        pytest.skip("没有星图数据")
    data = n.load()
    if not data.get("points"):
        pytest.skip("没有星图数据")
    monkeypatch.setattr(n, "USER", tmp_path)
    n._solar_ids.clear()
    nyx = next(p for p in data["points"] if p["sys"] == "Nyx")
    g = (nyx["x"], nyx["y"], nyx["z"])
    assert (
        n.system_of(g, data, location="AsteroidCluster_MiningBase_Nyx_Keeger") == "Nyx"
    )
    assert (
        n.system_of(
            g,
            data,
            zone="keeger_segment_mission_genrl_001_009",
            solar_id="862685702877",
        )
        == "Nyx"
    )
    assert (
        n.system_of((0, 0, 0), data, solar_id="862685702877") == "Nyx"
    )  # 学过的编号直接用
    assert (tmp_path / "solar_ids_v2.json").exists()
    assert n.system_info(
        (0, 0, 0), data, location="Stanton4_x", solar_id="862685702877"
    ) == ("Stanton", True)  # 明写的星系名为准
    assert n._solar_map()["862685702877"] == "Stanton"
    assert n.system_of((0, 0, 0), data, zone="OOC_Stanton_4_Microtech") == "Stanton"
    n._solar_ids.clear()


def test_nyx_location_label():
    from sc_mining.navigation import navigate as n

    if not n.CACHE.exists():  # display_label 里会 load 星图：没有就跳过，不联网
        pytest.skip("没有星图数据")
    from sc_mining.navigation.position import display_label as d

    assert d("AsteroidCluster_MiningBase_Nyx_Keeger") == "采矿基地（基格小行星带）"
    assert d("Hospital Stanton4 NewBabbage (LZ : Stanton4 NewBabbage)") == "新巴贝奇"


def test_only_trusted_rows_and_two_checks(monkeypatch, tmp_path):
    """2026-10-26 实测：识别引擎认错的行（Vulkan→vutkan）学进字模会把字模带坏。
    只学格式固定的行；字学齐了还要和识别引擎读的坐标对上两次才算能用（以前学齐就当能用，结果一直认不出又退回老引擎）"""
    G = _fresh(monkeypatch, tmp_path)
    arr = _sample("displayinfo_tr_1440.png")
    assert G.trusted("Zone: Root Pos: 22462326.4853km 37186368.6338km 744.0843km")
    assert G.trusted("Zone:Root Pos:-0.00m0.05m1.74m")  # 识别引擎常把空格吞掉，照样算
    assert not G.trusted("Graphics Renderer : vutkan(DLsS-66%)")
    assert not G.trusted("Zone: Root Pos: 2246232б.4853km 37186368.6338km 744.0843km")
    ocr = [(t, top + 6) for top, t in ROWS_1440.items()] + [
        ("Graphics Renderer : vutkan", 59 + 6)
    ]
    G.feed(arr, ocr, 1440)
    assert (
        G.status()["missing"] and not G.status()["ready"]
    )  # 一帧里只出现一次的字（Root 的 R）还不算学会
    G.feed(arr, ocr, 1440)
    st = G.status()
    assert (
        not st["missing"] and st["verified"] == 1 and not st["ready"]
    )  # 学齐了、只对上一次：还不能用
    assert "v" not in G._state["glyphs"].keys["main"]  # 认错的那行没学
    assert not (tmp_path / "glyphs" / "1440_v2.npz").exists()
    G.feed(arr, ocr, 1440)
    assert G.status()["ready"] and (tmp_path / "glyphs" / "1440_v2.npz").exists()


LIVE_PYRO = {
    20: "Zone: ARGO_MOLE_901556328045 Pos: 6.14m 25.20m 16.07m",
    33: "Zone: pyro5d Pos: -391.7098km 15.6168km 18.5458km",
    46: "Zone: SolarSystem_862775775663 Pos: -3946045.0466km -42879795.3054km 18.5458km",
    59: "Zone: Root Pos: -3946045.0466km -42879795.3054km 18.5458km",
}


def test_live_frames_learn_in_pyro_read_in_new_babbage(monkeypatch, tmp_path):
    """2026-10-27 用户实测的三帧（2560×1440，游戏里）：派罗 5d 那帧学（识别引擎把 ARGO_MOLE 认成 ARG0_M0LE 也不能把字模带坏），
    跳到新巴贝奇医院后的两帧直接认：坐标一个数字都不能错，Pos、Root 不能认成 P0s、Ro0t（以前学多了会这样，又退回识别引擎）"""
    from sc_mining.navigation.displayinfo import parse

    G = _fresh(monkeypatch, tmp_path)
    arr = _sample("displayinfo_live_pyro.png")
    ocr = [
        (t.replace("ARGO_MOLE", "ARG0_M0LE"), top + 6) for top, t in LIVE_PYRO.items()
    ]
    for _ in range(3):
        G.feed(arr, ocr, 1440)
    assert G.ready(1440)
    g = G._state["glyphs"]
    expect = {
        "displayinfo_live_nb1.png": (22462749.9938, 37185671.7264, 744.1104, 520.9095),
        "displayinfo_live_nb2.png": (22462751.0304, 37185681.5621, 744.0872, 520.9220),
    }
    for name, (x, y, z, lx) in expect.items():
        frame = _sample(name)
        tm = G.textness(frame)
        g.g.xr = G.right_edge(tm, g.g.xr)
        rows = g.read(tm, only=[20, 33, 46, 59])
        texts = [t for _, t, _, _ in rows]
        assert all("P0s" not in t and "Ro0t" not in t for t in texts), texts
        info = parse([t.replace("?", " ") for t in texts])
        assert info["global"] and all(
            abs(a - b * 1000) < 0.5 for a, b in zip(info["global"], (x, y, z))
        ), texts
        assert info["local"] and abs(info["local"][0] - lx) < 1e-6


def test_bottom_row_cut_in_half_does_not_crash(monkeypatch, tmp_path):
    """最底下一行被截掉半截（截图区域的下边缘）：以前格子比字模小，直接报错，这一帧位置就丢了"""
    G = _fresh(monkeypatch, tmp_path)
    arr = _sample("displayinfo_tr_1440.png")
    _learn(G, arr, ROWS_1440, 1440)
    cut = arr[: 224 + 5]  # CamPos 那一行只留 5 行像素
    rows = G.read_rows(cut, 1440)
    assert rows and any("Zone: Root" in t for _, t, _, _ in rows)


def test_fold_lookalikes():
    from sc_mining.navigation.gridtext import fold

    assert fold("00C_Stanton_4_M1crotech") == fold("OOC_Stanton_4_Microtech")
    assert fold("Pyro5d") == fold("pyrosd") and fold("ARG0") == "argo"


FONT_CASES = [
    ("displayinfo_tr_1440.png", 1440, (22462326.4853, 37186368.6338, 744.0843)),
    ("displayinfo_tr_1600.png", 1600, (-4634409.3882, -47775658.1227, -42.6401)),
    ("displayinfo_live_pyro.png", 1440, (-3946045.0466, -42879795.3054, 18.5458)),
    ("displayinfo_live_nb1.png", 1440, (22462749.9938, 37185671.7264, 744.1104)),
    ("displayinfo_live_nb2.png", 1440, (22462751.0304, 37185681.5621, 744.0872)),
]


@pytest.mark.parametrize("name,h,xyz", FONT_CASES)
def test_font_glyphs_read_coordinates_without_learning(
    monkeypatch, tmp_path, name, h, xyz
):
    """2026-10-27：游戏调试字是 Vera Sans Mono（Data.p4k 里 Engine\\Fonts\\VeraMono.ttf），AT 带开源同款 DejaVu Sans Mono。
    不学任何截图、不用识别引擎，自己试出字号画字模：两种分辨率、三张游戏实拍的坐标一个数字都不能错（含负号）"""
    from sc_mining.navigation.displayinfo import parse

    G = _fresh(monkeypatch, tmp_path)
    arr = _sample(name)
    rows = G.read_rows(arr, h)
    assert rows is not None and G.status()["source"] == "font"
    info = parse([t.replace("?", " ") for _, t, _, _ in rows])
    assert info["global"] and all(
        abs(a - b * 1000) < 0.5 for a, b in zip(info["global"], xyz)
    ), [t for _, t, _, _ in rows][:8]
    assert (tmp_path / "glyphs" / f"{h}_v2.npz").exists()
    G._state.update(
        glyphs=None, h=None, tried_load=False
    )  # 存下来的字模读回来，结果一样
    rows2 = G.read_rows(arr, h)
    assert (
        parse([t.replace("?", " ") for _, t, _, _ in rows2])["global"] == info["global"]
    )


def test_digit_context_keeps_6_and_minus():
    """数字段里只在数字、小数点里挑；段首像负号就是负号（游戏的负号和字体的不太一样）"""
    from sc_mining.navigation.gridtext import _digit_context

    keys = list("0123456789.-Sm k")
    K = len(keys)

    def sk(*best):
        m = np.full((len(best), K), 0.3)
        for i, (c, alt) in enumerate(best):
            m[i, keys.index(c)] = 0.9
            if alt:
                m[i, keys.index(alt)] = 0.8
        return m

    # 「-6.5km」：负号那格最像 S（字体的负号对不上），6 那格也最像 S
    out = list("SS.5km")
    SK = sk(("S", None), ("S", "6"), (".", None), ("5", None), ("k", None), ("m", None))
    SK[0, keys.index("-")] = 0.5
    _digit_context(out, [0.9] * 6, SK, keys)
    assert "".join(out)[1:] == "6.5km" and out[0] in "-0123456789"
    out = list("Pos")  # 不是数字段：不动
    _digit_context(out, [0.9] * 3, np.full((3, K), 0.3), keys)
    assert "".join(out) == "Pos"


def test_font_file_and_license_present():
    from sc_mining.navigation.gridtext import FONT_FILE

    assert FONT_FILE.exists() and FONT_FILE.stat().st_size > 100_000
    lic = FONT_FILE.parent / "LICENSE-DejaVu.txt"
    assert lic.exists() and "Bitstream" in lic.read_text(encoding="utf-8")


def test_review_102_position_guards(monkeypatch, tmp_path):
    """Codex 2026-10-27 补审：①字模这条路两行坐标都要读出来且一致；②数字旁认不出的格子让坐标作废，不删成少一位；
    ③挑出来的数字也不像就写 ?；④字模失效（识别引擎读得出、字模读不出）连续 3 次就扔掉重画；⑤学字样本有上限"""
    from sc_mining.navigation import displayinfo as D, gridtext as G

    sol = (
        "Zone: SolarSystem_862949775749 Pos: 22462326.4853km 37186368.6338km 744.0843km"
    )
    root = "Zone: Root Pos: 22462326.4853km 37186368.6338km 744.0843km"
    assert D.parse([sol], need_both=True)["global"] is None
    assert D.parse([sol])["global"] is not None  # 识别引擎那条老路照旧
    assert D.parse([sol, root], need_both=True)["global"] is not None
    assert (
        D.parse([sol.replace("SolarSystem", "SolarSyscem"), root], need_both=True)[
            "global"
        ]
        is not None
    )  # 字母认错一个也认得出是哪行
    bad = "Zone: Root Pos: ?2462326.4853km 37186368.6338km 744.0843km"
    assert (
        D.parse(
            [D.grid_text(sol.replace("22462326", "?2462326")), D.grid_text(bad)],
            need_both=True,
        )["global"]
        is None
    )
    assert (
        D.parse([D.grid_text(sol.replace("6.4853", "?.4853")), root], need_both=True)[
            "global"
        ]
        is None
    )
    assert D.grid_text("Zone:?Root Pos: 1.0km") == "Zone: Root Pos: 1.0km"
    keys = list("0123456789.-Sm k")
    SK = np.full((4, len(keys)), 0.1)
    SK[0, keys.index("1")] = SK[1, keys.index("2")] = SK[3, keys.index("4")] = 0.9
    out = list("12?4")
    G._digit_context(out, [0.9, 0.9, 0.1, 0.9], SK, keys)
    assert "".join(out) == "12?4"
    saved = dict(G._state)
    G._state.update(glyphs=object(), fails=0, tried_load=False, font_at=0.0)
    for _ in range(G.GRID_FAILS - 1):
        G.note(False)
    G.note(True)
    G.note(False)
    assert G._state["glyphs"] is not None
    for _ in range(G.GRID_FAILS):
        G.note(False)
    try:
        assert G._state["glyphs"] is None and G._state["font_at"] == 0.0
    finally:
        G._state.clear()
        G._state.update(saved)


def test_review_102_reader_poll_is_serialized(monkeypatch):
    """两个线程同时读位置：一次只读一个，旧帧不会盖掉新帧"""
    import threading
    from sc_mining.navigation import displayinfo as D

    calls = {"n": 0, "max": 0, "now": 0}
    lock = threading.Lock()

    def fake_read(**kw):
        with lock:
            calls["now"] += 1
            calls["max"] = max(calls["max"], calls["now"])
        time.sleep(0.05)
        with lock:
            calls["now"] -= 1
            calls["n"] += 1
            n = calls["n"]
        return {"global": (n * 1e7, 0, 0), "fast": True, "t": time.time()}

    from sc_mining.system import showloc

    monkeypatch.setattr(D, "read", fake_read)
    monkeypatch.setattr(showloc, "game_foreground", lambda: True)  # 测试时游戏不在前台
    r = D.Reader(every=0)
    ts = [threading.Thread(target=r.poll, kwargs={"force": True}) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert calls["max"] == 1 and calls["n"] == 4
    assert r.snapshot()[1]["global"][0] == 4e7


def test_lost_minus_sign_rejected(monkeypatch, tmp_path):
    """字模把负号当空格丢掉（1080p 实拍见过），两行一起丢时两行照样一致：Pos 后双空格接数字就作废这一帧（2026-10-30）"""
    from sc_mining.navigation import displayinfo as D

    sol = "Zone: SolarSystem_862685702877 Pos: -4634409.3882km -47775658.1227km -42.6401km"
    root = "Zone: Root Pos: -4634409.3882km -47775658.1227km -42.6401km"
    assert (
        D.parse([D.grid_text(sol), D.grid_text(root)], need_both=True)["global"]
        is not None
    )
    gone = [s.replace(" -", "  ") for s in (sol, root)]
    assert D.parse([D.grid_text(s) for s in gone], need_both=True)["global"] is None
    assert D.grid_text("Zone:?Root Pos: 1.0km") == "Zone: Root Pos: 1.0km"
    # 图像层：把样本两行坐标里的负号抹掉，字模读出来也不能给出（正号的）坐标
    G = _fresh(monkeypatch, tmp_path)
    clean = _sample("displayinfo_tr_1600.png")
    G._state.update(tried_load=True)
    assert G.read_rows(clean, 1600)
    gl = G._state["glyphs"]
    gr = gl.g
    tm = G.textness(clean)
    arr = clean.copy()
    for top in (50, 65):
        text, _, sc = gl.read_row(tm, top)
        adv, off = gr.adv[sc]
        strip = tm[top : top + gr.lh]
        colsum = strip.sum(0, dtype=np.int32)
        xs = np.nonzero((strip > G.INK).any(0))[0]
        off = min(
            np.arange(off - 1.0, off + 1.01, 0.25),
            key=lambda o: G._row_score(colsum, gr.xr, adv, o),
        )
        right = gr.xr + off
        n = int(np.ceil((right - xs.min()) / adv))
        lefts = np.round(right - np.arange(n, 0, -1) * adv).astype(int)
        assert len(lefts) == len(text)
        p = text.index("Pos:")
        for i, ch in enumerate(text):
            if ch == "-" and i > p:
                arr[top : top + gr.lh, lefts[i] + 1 : lefts[i] + int(adv)] = 0
    texts = [D.grid_text(t) for _, t, _, _ in G.read_rows(arr, 1600)]
    assert D.parse(texts, need_both=True)["global"] is None


def test_dot_after_unit_may_be_lost_minus():
    """「km.21」可能是认丢的负号：两行都这样（或只有一行）就不采用；另一行干净、数值一致才采用（S2 审查 2026-10-31）"""
    from sc_mining.navigation.displayinfo import parse

    sys_dot = "Zone: SolarSystem 862685702877 Pos: 744.0843km 1000.5km.42.6401km"
    root_dot = "Zone: Root Pos: 744.0843km 1000.5km.42.6401km"
    assert parse([sys_dot, root_dot])["global"] is None
    assert parse([root_dot])["global"] is None
    clean = "Zone: SolarSystem 862685702877 Pos: 744.0843km 1000.5km 42.6401km"
    d = parse([clean, root_dot], need_both=True)
    assert d["global"] and abs(d["global"][2] - 42640.1) < 0.5
    signed = (
        "Zone: Root Pos: 744.0843km 1000.5km.-42.6401km"  # 点后面带着负号：符号没丢
    )
    assert parse([signed])["global"][2] < 0


def test_camdir_broken_row_rejected():
    """CamDir 那行残缺（认不出的格子、丢了负号、数多了少了）整行不要（S2 审查 2026-10-31）"""
    from sc_mining.navigation.displayinfo import parse, grid_text

    assert parse(["CamDir: 52 27 -176 FOV: 64"])["camdir"] == (52, 27, -176)
    assert parse(["CamDir: 5# 27 -176 FOV: 64"])["camdir"] is None
    assert (
        parse([grid_text("CamDir: 52  27 -176 FOV: 64")])["camdir"] is None
    )  # 27 前面丢了负号
    assert parse([grid_text("CamDir:  52 27 -176 FOV: 64")])["camdir"] is None
    assert parse(["CamDir: 52 27 -176 3 FOV: 64"])["camdir"] is None
    assert parse(["CamDir: 52 27 -176 FQV: 64 Focal: 3.00 FStop: 64.0"])["camdir"] == (
        52,
        27,
        -176,
    )  # FOV 认岔（复审 2026-10-31）
    assert parse(["CamDir: 52 27 -176 F OV: 64"])["camdir"] == (52, 27, -176)
    for bad in (
        "52 27 -1B6",
        "52 27 -1g2",
        "52 27 1Z4",
        "5Z 27 -176",
    ):  # 数字认成字母：整行不要（第 3 轮复审）
        assert parse([f"CamDir: {bad} FOV: 64"])["camdir"] is None


def test_cam_filter_recovers_from_real_mirror_turn():
    """被拒的读数连着几帧都一样就收下，不会永久卡在旧值上（S2 审查 2026-10-31）"""
    from sc_mining.app.engines.nav import _CamFilter

    f = _CamFilter()
    assert f.check((30, 0, 90), fast=True) == (30, 0, 90)
    assert f.check((-30, 0, 90), fast=True) is None  # 单独一帧像漏了负号：不信
    assert f.check((-30, 0, 90), fast=True) is None
    assert f.check((-30, 0, 90), fast=True) == (
        -30,
        0,
        90,
    )  # 字模连着三帧都这样：真转过去了
    assert f.check((-31, 0, 91), fast=True) == (-31, 0, 91)
    f = _CamFilter()  # 识别引擎的帧：错得一样也不放行（复审 2026-10-31）
    assert f.check((30, 0, 90)) == (30, 0, 90)
    assert all(f.check((-30, 0, 90)) is None for _ in range(5))


def test_font_hires_cache_released_after_build():
    """画字模用的高清大图画完就放掉，不常驻内存（S2 审查 2026-10-31）"""
    from sc_mining.navigation import gridtext as G

    if not G.FONT_FILE.exists():
        pytest.skip("没有字体文件")
    G._hires(20.0, "A")
    assert G._HIRES
    try:
        G.Glyphs.from_font(object(), None)  # 参数不对会抛错：抛错也要放掉
    except Exception:
        pass
    assert not G._HIRES
