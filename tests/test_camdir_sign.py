"""CamDir 正负号（Astra 二轮研究 2026-11-03）：游戏把三个角度右对齐，正数前面本来就是空白。
以前按「双空格接数字 = 丢了负号」整行作废，正数一出现镜头方向就没了、导航记号跟着消失。
现在按像素判：数字前一格是干净空白 → 正数；格子里还有没认出来的负号残迹 → 这一行不要。"""

import numpy as np
from PIL import Image

from astral_toolkit.core.paths import SAMPLES
from tests.minipytest import Skip

CASES = [
    ("displayinfo_tr_1600.png", 1600, (52, 27, -176)),
    ("displayinfo_live_pyro.png", 1440, (45, -63, 114)),
    ("displayinfo_live_nb1.png", 1440, (-30, -30, -136)),
    ("displayinfo_live_nb2.png", 1440, (-40, -31, -139)),
]


def _sample(name):
    p = SAMPLES / name
    if not p.exists():
        raise Skip(f"没有样本 {name}")
    return np.asarray(Image.open(p).convert("RGB"))


def _font_glyphs(monkeypatch, tmp_path):
    from astral_toolkit.navigation import gridtext as G

    monkeypatch.setattr(G, "GLYPH_DIR", tmp_path / "glyphs")  # 不碰用户自己的字模
    G._state.update(
        glyphs=None, h=None, tried_load=True, font_at=0.0
    )  # 只用字体画的字模
    return G


def _rows(G, arr, h) -> list[tuple[int, str]]:
    rows = G.read_rows(arr, h)
    assert rows
    return [(int(r[0]), str(r[1])) for r in rows]


def _camdir(G, arr, h) -> tuple[str, tuple[float, ...] | None]:
    from astral_toolkit.navigation import displayinfo as D

    rows = _rows(G, arr, h)
    cam = [t for _, t in rows if t.startswith("CamDir:")]
    assert cam, [t for _, t in rows][:3]
    return cam[0], D.parse([D.grid_text(cam[0])])["camdir"]


def _cam_top(G, arr, h) -> int:
    return next(t for t, txt in _rows(G, arr, h) if txt.startswith("CamDir:"))


def _cell_lefts(G, gl, tm, top, text):
    gr = gl.g
    sc = gr.scale_of(tm, top)
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
    return lefts, adv, gr.lh


def test_real_camdir_signs(monkeypatch, tmp_path):
    """四张真实截图：正数（前面两格空白）、负数都读对，不再把正数当成丢了负号"""
    for name, h, want in CASES:
        G = _font_glyphs(monkeypatch, tmp_path)
        raw, cam = _camdir(G, _sample(name), h)
        assert cam == tuple(float(v) for v in want), (name, raw)


def test_faint_minus_rejected(monkeypatch, tmp_path):
    """-176 的负号只剩两个像素（字模判成空白）：这一行不要，不能读成 +176"""
    G = _font_glyphs(monkeypatch, tmp_path)
    clean = _sample("displayinfo_tr_1600.png")
    raw, cam = _camdir(G, clean, 1600)
    assert cam == (52.0, 27.0, -176.0), raw
    gl = G._state["glyphs"]
    tm = G.textness(clean)
    top = _cam_top(G, clean, 1600)
    text = gl.read_row(tm, top)[0]
    lefts, adv, lh = _cell_lefts(G, gl, tm, top, text)
    i = text.index("-")
    x0, x1 = lefts[i] + 1, lefts[i] + int(adv)
    faint = clean.copy()
    box = faint[top : top + lh, x0:x1]
    ys, xs = np.nonzero(tm[top : top + lh, x0:x1] > G.INK)
    keep = set(list(zip(ys.tolist(), xs.tolist()))[:2])  # 只留两个像素：墨量 < 3
    for y, x in zip(ys.tolist(), xs.tolist()):
        if (y, x) not in keep:
            box[y, x] = 0
    raw_f, cam_f = _camdir(G, faint, 1600)
    assert "-176" not in raw_f and cam_f is None, raw_f


def test_erased_minus_caught_by_cam_filter(monkeypatch, tmp_path):
    """负号整个抹掉（和正数一模一样）：像素上分不出来，读成 63。-63 → 63 差 126°：
    导航里的镜头防误读（单独一帧变号不信）要拦下这一帧"""
    from astral_toolkit.app.engines.nav import _CamFilter

    G = _font_glyphs(monkeypatch, tmp_path)
    pyro = _sample("displayinfo_live_pyro.png")
    raw_p, cam_p = _camdir(G, pyro, 1440)
    assert cam_p == (45.0, -63.0, 114.0), raw_p
    gl = G._state["glyphs"]
    tm = G.textness(pyro)
    top = _cam_top(G, pyro, 1440)
    text = gl.read_row(tm, top)[0]
    lefts, adv, lh = _cell_lefts(G, gl, tm, top, text)
    i = text.index("-")
    gone = pyro.copy()
    gone[top : top + lh, lefts[i] + 1 : lefts[i] + int(adv)] = 0
    raw_g, cam_g = _camdir(G, gone, 1440)
    assert cam_g == (45.0, 63.0, 114.0), raw_g
    f = _CamFilter()
    assert f.check(cam_p, fast=True) == cam_p
    assert f.check(cam_g, fast=True) is None


def test_faint_signs_only_touches_camdir_sign_slots():
    """只改 CamDir: 到 FOV 之间、数字前一格、而且格子里有残迹的空白；干净空白、别的行不动"""
    from astral_toolkit.navigation.gridtext import SIGN_FAINT, _faint_signs
    from astral_toolkit.navigation.displayinfo import parse, grid_text

    text = "CamDir:  52  27 -176 FOV: 64"
    imgs = np.zeros((len(text), 12, 8), np.float32)
    out = list(text)
    _faint_signs(out, imgs)
    assert "".join(out) == text  # 干净空白：正数照读
    j = text.index("27") - 1
    imgs[j, 6, 3] = SIGN_FAINT  # 27 前一格有残迹
    k = text.index("64") - 1
    imgs[k, 6, 3] = 255  # FOV 后面的不管
    out = list(text)
    _faint_signs(out, imgs)
    got = "".join(out)
    assert got == text[:j] + "?" + text[j + 1 :]
    assert parse([grid_text(got)])["camdir"] is None
    pos = "Pos: 93.0795km 64.7646km"
    out = list(pos)
    _faint_signs(out, np.full((len(pos), 12, 8), 255, np.float32))
    assert "".join(out) == pos  # 别的行不归它管


def test_faint_signs_cell_geometry():
    """负号残迹偏到格子左边列也要查到；右边 2 列（后面数字漏进来的墨）、字高上下的杂讯不算（DeepSeek 审查 2026-11-03）"""
    from astral_toolkit.navigation.gridtext import SIGN_FAINT, _faint_signs

    text = "CamDir:  45 -63  114 FOV: 58"
    j = text.index("45") - 1

    def run(y, x, v=255):
        imgs = np.zeros((len(text), 13, 9), np.float32)
        imgs[j, y, x] = v
        out = list(text)
        _faint_signs(out, imgs)
        return out[j]

    assert run(5, 0) == "?"  # 偏到最左列
    assert run(6, 4) == "?"  # 正中
    assert run(5, 4, SIGN_FAINT - 1) == " "  # 阈值以下：干净空白
    assert run(5, 8) == " " and run(5, 7) == " "  # 右边 2 列：后面数字漏进来的
    assert run(0, 4) == " " and run(12, 4) == " "  # 字高最上 / 最下：不是负号的位置


def test_lone_zero_read_as_letter_o():
    """角度正好是 0：字模把单独的 0 认成字母 O（老大 11-03 诊断原文），CamDir 里当 0；别处的 O 不动"""
    from astral_toolkit.navigation.displayinfo import grid_text, parse

    raw = "CamDir: -125   O   39 FOV: 78 Focal: 3.00 FStop: 64.0"
    assert parse([grid_text(raw)])["camdir"] == (-125.0, 0.0, 39.0)
    assert parse([grid_text("CamDir:  o -12  140 FOV: 78")])["camdir"] == (
        0.0,
        -12.0,
        140.0,
    )
    assert (
        grid_text("Zone: OOC_Stanton_2 Pos: 1.0km") == "Zone: OOC_Stanton_2 Pos: 1.0km"
    )
