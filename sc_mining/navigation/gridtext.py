"""右上角调试信息的「字模识别」（2026-10-26，实时位置用）：不走文字识别引擎，几毫秒认完

游戏的调试字（r_DisplayInfo 2）有几个固定特点，全靠它们：
- 等宽、右对齐：主字号字距 = 5.62 × 屏幕高度 ÷ 1080（1440p 7.49、1600p 8.33，两台机器的截图拟合出来一样）；
  「Current player location」那几行用小一号的字（0.88 倍）。哪一行是哪种字号，看格子边界落在空白列上的是哪种
  → 不用找字在哪，按格子切，每格和字模比对；格子之间不会串
- 亮字 + 右下角 1 像素黑影 → 「textness = 亮度 − 右下角像素亮度」，白墙上的字也抠得出来
- 字形永远不变（只随分辨率缩放）→ 字模按屏幕高度存一份（userdata/glyphs/<高度>.npz），下次直接用

字模哪来（2026-10-27 起）：游戏的调试字体是引擎自带的 VeraMono（Data.p4k 里的 Engine\\Fonts\\VeraMono.ttf，
即 Bitstream Vera Sans Mono）。AT 带着它的开源同款 DejaVu Sans Mono（英文、数字字形一样），第一次看到右上角时
自己试出字号和位置（几秒），直接画出全部字模——不用文字识别引擎校准、不用学截图；在 1440、1600 和游戏里的实拍上
坐标一个数字不错。字体对不上时（以后游戏换字体）才退回老办法：用文字识别认几帧，每行文字对到格子上学。
认不出的格子写「?」；数字中间的格子只在数字、小数点里挑（6 不会认成 S、再被当成 5）。
"""
import json
import re
import time
from pathlib import Path

import numpy as np

from ..core.paths import USER

ADV_1080 = 5.62              # 1080p 下主字号的字距（像素）
SMALL = 0.88                 # 小字号 / 主字号
PITCH_1080 = 9.45            # 1080p 下的行距
INK = 50                     # textness 高于这个算有墨
BRIGHT = 130                 # 真正的字至少有一个像素这么亮（小字号抗锯齿后只有 150 左右）；白墙边缘这种杂讯最多 110
MIN_SAMPLES = 2              # 一个字至少见过几次才算学会
REQUIRED = set("0123456789.:kmZoneRtPsSlary")       # 主字号必需：数字、单位、Zone / Root / Pos / SolarSystem
MIN_SCORE = 0.6              # 和最像的字模相关低于这个：不硬猜，写 ?（坐标里的 ? 当空格，解析不出就退回识别引擎）
VERIFY_TIMES = 2             # 和识别引擎读出的坐标对上几次才算校准好（只学齐字不算）
# 只从这几种行学字（2026-10-26 实测：识别引擎会认错字，比如 Vulkan 认成 vutkan，什么行都学会把字模带坏）：
# 坐标行格式固定、认错了对不上格式；地点行（小字号）只用来找到那一行，内容另外用识别引擎认
TRUST_POS = re.compile(r"^Zone:[A-Za-z0-9_\-]+Pos:(?:-?\d+\.\d+k?m){3}$")
TRUST_CAM = re.compile(r"^CamDir:(?:-?\d+){3}FOV:\d+Focal:\d+\.\d+FStop:\d+\.\d+$")
TRUST_LOC = re.compile(r"^Currentplayerlocation:\S+")
GLYPH_DIR = USER / "glyphs"
FONT_FILE = Path(__file__).resolve().parent.parent / "fonts" / "DejaVuSansMono.ttf"
FONT_CHARS = [chr(c) for c in range(33, 127)]          # 可打印的英文字符全画
CAP_HEIGHT = 0.729                                      # 大写字母高 / 字号（Vera Sans Mono）
FONT_RETRY = 15.0                                       # 画字模没成功（没在游戏里、没开调试信息）：过多久再试
DIGITS = set("0123456789.")
DASH_MIN = 0.3               # 负号最低相关（游戏的负号和字体的不太一样，要求放低，但完全不像就不算）
MAX_SAMPLES = 40             # 每个字最多留几张学字样本（finalize 只用最后 40 张；多的删掉，免得内存一直涨）
GRID_FAILS = 3               # 字模读不出、识别引擎读得出，连续几次就当字模失效，重画
SCALES = ("main", "small")


def textness(rgb):
    """RGB 数组 → 每个像素「像字的程度」0..255（全程 uint8 运算，871×352 的块约 1 毫秒）"""
    import cv2
    a = np.asarray(rgb)
    if a.ndim == 3:
        r, g, b = a[..., 0], a[..., 1], a[..., 2]
        lum = np.maximum(np.maximum(r, g), b)
        colorful = cv2.absdiff(r, g) > 70                 # 彩色的（黄字、HUD）不要
    else:
        lum, colorful = a, None
    t = np.zeros_like(lum)
    t[:-1, :-1] = cv2.subtract(lum[:-1, :-1], lum[1:, 1:])      # 亮度 − 右下角像素亮度，负数截成 0
    if colorful is not None:
        t[colorful] = 0
    return t


def row_tops(tm, min_cols=8):
    """每一行字的顶边 y"""
    rows = (tm > 90).sum(1)
    tops, inb = [], False
    for y, v in enumerate(rows):
        if v > min_cols and not inb:
            s, inb = y, True
        elif v <= min_cols and inb:
            inb = False
            if y - s >= 5:
                tops.append(s)
    return tops


def _row_score(cols, xr, adv, off):
    """格子边界落在的那些列的平均墨量：越小说明这一行越像这个字距"""
    xs = np.nonzero(cols > 0)[0]
    if not len(xs):
        return None
    b = np.round(np.arange(xr + off, xs.min() - adv, -adv)).astype(int)
    b = b[(b >= 0) & (b < len(cols))]
    return float(cols[b].sum() / max(len(b), 1))


def _fit(tm, bands, xr, adv0):
    """在 adv0 附近微调字距和相位。返回 (adv, off, 最好的平均墨量, 所有相位的中位数)"""
    best, scores = None, []
    col_cache = [tm[t:b].astype(np.float32).sum(0) for t, b in bands]
    for adv in np.arange(adv0 - 0.15, adv0 + 0.16, 0.01):
        for off in np.arange(0, adv, 0.2):
            vals = [v for v in (_row_score(c, xr, adv, off) for c in col_cache) if v is not None]
            if not vals:
                continue
            sc = float(np.mean(vals))
            scores.append(sc)
            if best is None or sc < best[0]:
                best = (sc, adv, off)
    if best is None:
        return adv0, 0.0, 0.0, 0.0
    return best[1], best[2], best[0], float(np.median(scores))


def right_edge(tm, default):
    """文字的右边界（右对齐的那条线）：最右边那根至少有 2 个亮像素的列。每一帧都重新找，窗口挪了也不怕"""
    cols = np.nonzero((tm >= BRIGHT).sum(0) >= 2)[0]
    return int(cols.max()) if len(cols) else default


class Grid:
    """一种分辨率的网格：行高、右边界、两种字号各自的字距和相位"""

    def __init__(self, screen_h, tm=None, params=None):
        self.h = int(screen_h)
        if params:
            self.pitch, self.lh, self.xr = params["pitch"], params["lh"], params["xr"]
            self.adv = {k: tuple(v) for k, v in params["adv"].items()}
            self.ok = True
        else:
            tops = row_tops(tm)
            self.pitch = float(np.median(np.diff(tops[:8]))) if len(tops) > 3 else PITCH_1080 * screen_h / 1080
            self.lh = int(round(self.pitch)) - 1
            self.xr = right_edge(tm, tm.shape[1] - 1)
            bands = [(t, t + self.lh) for t in tops]
            # 字距起点试两个：按屏幕高度缩放的，和 1440 起步的——1440 以下调试字不再变小
            # （1080p 实测字距 7.5、行距 13，和 1440 一样；只按高度缩到 5.6 会判成「不是等宽字」，快路起不来，玩家反馈 2026-10-30）
            best = None
            for a0 in sorted({ADV_1080 * screen_h / 1080, ADV_1080 * max(screen_h, 1440) / 1080}):
                fit = _fit(tm, bands[:6], self.xr, a0) if bands else (a0, 0.0, 0.0, 0.0)
                ratio = fit[2] / fit[3] if fit[3] else float("inf")
                if best is None or ratio < best[0]:
                    best = (ratio, a0, fit)
            _, a0, (adv, off, edge, rnd) = best
            self.ok = bool(bands) and edge < rnd * 0.4            # 格子边界明显比别处干净：真的是等宽字
            # 小字号：挑出按主字号对不上的行再拟合
            small_rows = [b for b in bands if (_row_score(tm[b[0]:b[1]].astype(np.float32).sum(0), self.xr, adv, off) or 0) > rnd * 0.5]
            adv_s, off_s, _, _ = _fit(tm, small_rows, self.xr, a0 * SMALL) if small_rows else (a0 * SMALL, 0.0, 0.0, 0.0)
            self.adv = {"main": (float(adv), float(off)), "small": (float(adv_s), float(off_s))}

    def params(self):
        return {"pitch": float(self.pitch), "lh": int(self.lh), "xr": int(self.xr), "adv": self.adv}

    def scale_of(self, tm, top):
        cols = tm[top:top + self.lh].astype(np.float32).sum(0)
        best = None
        for name, (adv, off) in self.adv.items():
            sc = _row_score(cols, self.xr, adv, off)
            if sc is not None and (best is None or sc < best[0]):
                best = (sc, name)
        return best[1] if best else "main"

    def cells(self, tm, top, scale):
        """一行切格（从左到右）：返回 (格数, lh, cw) 的 float32 数组；没字返回 None"""
        adv, off = self.adv[scale]
        cw = int(np.ceil(adv)) + 1
        strip = tm[top:top + self.lh]
        if strip.shape[0] < self.lh:                 # 最底下一行被截掉半截：补空白，格子大小才和字模一样
            strip = np.vstack([strip, np.zeros((self.lh - strip.shape[0], strip.shape[1]), strip.dtype)])
        colsum = strip.sum(0, dtype=np.int32)
        xs = np.nonzero((strip > INK).any(0))[0]
        if not len(xs):
            return None
        # 每一行再微调一下相位（±1 像素）：格子边界尽量落在空白列上，认字准很多
        off = min(np.arange(off - 1.0, off + 1.01, 0.25), key=lambda o: _row_score(colsum, self.xr, adv, o))
        right = self.xr + off
        n_cells = int(np.ceil((right - xs.min()) / adv))
        lefts = np.round(right - (np.arange(n_cells, 0, -1)) * adv).astype(int)        # 从左到右每格的左边界
        idx = lefts[:, None] + np.arange(cw)[None, :]                                    # (格数, cw) 列号
        ok = (idx >= 0) & (idx < strip.shape[1])
        cells = strip[:, np.clip(idx, 0, strip.shape[1] - 1)].astype(np.float32)        # (lh, 格数, cw)
        cells = np.transpose(cells, (1, 0, 2)) * ok[:, None, :]
        return np.ascontiguousarray(cells)




def _inks(cells):
    """每格的墨量（两边各留 2 列：邻格的字会漏进来一点）。既没有亮像素、也没有一横的格子是杂讯，算 0
    （下划线 _ 是半透明的细横线，只有 100 左右亮；亮墙上的杂讯最多也 100 上下，但不成横）"""
    mid = cells[:, :, 2:-2]
    real = (mid.max(axis=(1, 2)) >= BRIGHT) | ((mid > 70).sum(2) >= 4).any(1)
    return (mid > INK).sum(axis=(1, 2)) * real


def _cell_ink(cell):
    return int(_inks(cell[None])[0])


def _corr(a, b):
    a = a.reshape(-1) - a.mean()
    b = b.reshape(-1) - b.mean()
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-6))


def _shifted(T):
    K = T.shape[0]
    out = []
    for dx in (-1, 0, 1):
        t = np.zeros_like(T)
        if dx < 0:
            t[:, :, :dx] = T[:, :, -dx:]
        elif dx > 0:
            t[:, :, dx:] = T[:, :, :-dx]
        else:
            t = T.copy()
        out.append(t)
    M = np.concatenate(out).reshape(3 * K, -1)
    M = M - M.mean(1, keepdims=True)
    return M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-6)


# ---------------------------------------------------------------- 用字体画字模（2026-10-27）

_HIRES = {}


def _hires(em, ch, ss=8):
    """一个字在某个字号下的高清图（ss 倍）：只画一次，不同位置、相位都从它上面截，不用重画。
    → (图, 大写字母顶边在图里的 y, 字的原点 x)"""
    key = (round(float(em), 3), ch, ss)
    hit = _HIRES.get(key)
    if hit is None:
        from PIL import Image, ImageDraw, ImageFont
        if len(_HIRES) > 4000:
            _HIRES.clear()
        fkey = ("font", round(float(em), 3), ss)
        if fkey not in _HIRES:
            _HIRES[fkey] = ImageFont.truetype(str(FONT_FILE), size=em * ss)
        font = _HIRES[fkey]
        asc, _ = font.getmetrics()
        pad = int(3 * ss)
        W, H = int(1.2 * em * ss) + 2 * pad, int(1.6 * em * ss) + 2 * pad
        im = Image.new("L", (W, H), 0)
        ImageDraw.Draw(im).text((pad, pad), ch, fill=255, font=font)
        hit = _HIRES[key] = (np.asarray(im, np.float32) / 255.0, pad + asc - CAP_HEIGHT * em * ss, pad)
    return hit


def font_templates(em, dy, lh, cw, chars=FONT_CHARS, phases=(0.0, 0.25, 0.5, 0.75), ss=8):
    """用字体画字模：{字: [lh×cw 的 textness 图, ...]}。em = 字号（像素），dy = 大写字母顶边相对行顶边的位置，
    phases = 字在格子里往右挪的小数像素（字距不是整数，同一个字落在不同相位上抗锯齿不一样）。
    画法和游戏一样：白字 + 右下角 1 像素黑影，再算 textness"""
    out = {}
    for ch in chars:
        hi, cap_top, pad = _hires(em, ch, ss)
        y0 = int(round(cap_top - dy * ss))                        # 格子第 0 行在高清图里的 y
        hi = np.pad(hi, ((max(0, -y0), max(0, y0 + lh * ss - hi.shape[0])), (0, max(0, cw * ss + pad - hi.shape[1]))))
        y0 = max(0, y0)
        lst = []
        for ph in phases:
            x0 = int(round(pad - ph * ss))
            a = hi[y0:y0 + lh * ss, x0:x0 + cw * ss].reshape(lh, ss, cw, ss).mean(axis=(1, 3))
            sh = np.zeros_like(a)
            sh[:-1, :-1] = a[1:, 1:]
            lst.append(np.clip(a - sh, 0, 1) * 255.0)
        out[ch] = lst
    return out


FIT_CHARS = {"main": "0123456789.-:kmZonePsRtSlary", "small": "Curentplayeoci:"}


def _fit_score(cells_n, em, dy, lh, cw, chars):
    """这组字号和位置画出的字模，和画面上这些格子有多吻合：每格取最像的字的相关，再平均"""
    T = font_templates(em, dy, lh, cw, chars)
    M = np.stack([t for lst in T.values() for t in lst])
    Mn = _shifted(M)
    S = (cells_n @ Mn.T).max(1)
    return float(S.mean())


def fit_font(tm, grid, scale):
    """不用识别引擎，直接从画面试出字号和位置：先粗后细两轮网格搜索（约 1 秒）。返回 (字号, dy, 吻合度) 或 None"""
    adv, _ = grid.adv[scale]
    cw = int(np.ceil(adv)) + 1
    cells = []
    for top in row_tops(tm)[:24]:
        if grid.scale_of(tm, top) != scale:
            continue
        c = grid.cells(tm, top, scale)
        if c is None:
            continue
        ink = _inks(c)
        cells += list(c[(ink >= 8)])
        if len(cells) >= 160:
            break
    if len(cells) < 20:
        return None
    X = np.stack(cells[:160]).reshape(min(len(cells), 160), -1)
    X = X - X.mean(1, keepdims=True)
    X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-6)
    chars = FIT_CHARS[scale]
    best = None
    for em in np.arange(adv / 0.76, adv / 0.54, 0.25):          # 字距 ÷ 字号 在 0.54～0.76 之间（Vera 自身是 0.60）
        for dy in np.arange(-2.0, 1.51, 0.5):
            sc = _fit_score(X, em, dy, grid.lh, cw, chars)
            if best is None or sc > best[0]:
                best = (sc, em, dy)
    _, em0, dy0 = best
    for em in np.arange(em0 - 0.25, em0 + 0.26, 0.05):
        for dy in np.arange(dy0 - 0.5, dy0 + 0.51, 0.125):
            sc = _fit_score(X, em, dy, grid.lh, cw, chars)
            if sc > best[0]:
                best = (sc, em, dy)
    return float(best[1]), float(best[2]), float(best[0])


_FOLD = str.maketrans({"0": "o", "O": "o", "1": "l", "I": "l", "i": "l", "|": "l", "5": "s", "S": "s", "8": "b", "B": "b",
                       "2": "z", "Z": "z"})


def fold(text):
    """易混字归成一类（O/0、l/1/I/i、S/5、B/8、Z/2，大小写不分）：这个字体里它们几乎一样，识别引擎也常认错。
    比对区域名、地名时两边都先 fold"""
    return (text or "").translate(_FOLD).lower()


def _roles(text):
    """每个非空格字是格式固定的（fixed）还是区域名里的（name）。坐标行里 Zone: 和 Pos: 之间是区域名，
    但 Root、SolarSystem_<数字> 是固定的；其他行全算固定（只会传进来格式对得上的行）"""
    out = []
    m = re.match(r"^(\s*Zone:\s*)(.*?)(\s*Pos:.*)$", text)
    if not m:
        return ["fixed"] * len(text.replace(" ", ""))
    head, name, tail = m.groups()
    fixed_name = bool(re.fullmatch(r"Root|SolarSystem_\d+", name.strip()))
    for part, role in ((head, "fixed"), (name, "fixed" if fixed_name else "name"), (tail, "fixed")):
        out += [role] * len(part.replace(" ", ""))
    return out


def _digit_context(out, sc_of, SK, keys):
    """数字中间的格子只在数字、小数点里挑：「37186368.6338km」里的 6 不能认成 S（以前会再被当成 5，坐标悄悄错一位）。
    按空格、下划线、冒号把一行切成小段，去掉末尾的 km / m，剩下的大部分（≥60%）是数字就算数字段；
    段首那一格还可以是负号（游戏的负号和字体的不太一样，常认成 + ~ 之类，不能把它改成数字）"""
    dig = [k for k, c in enumerate(keys) if c in DIGITS]
    dash = [k for k, c in enumerate(keys) if c == "-"]
    if not dig:
        return
    seg = []
    for i in range(len(out) + 1):
        if i == len(out) or out[i] in " _:":
            core = seg[:]
            if len(core) > 1 and out[core[-1]] == "m":            # 单位 m / km
                core = core[:-1]
                if len(core) > 1 and out[core[-1]] == "k":
                    core = core[:-1]
            body = core[1:] if core and out[core[0]] not in DIGITS else core
            if len(body) >= 2 and sum(out[j] in DIGITS for j in body) >= 0.6 * len(body):
                for n, j in enumerate(core):
                    if out[j] in DIGITS:
                        continue
                    cand = dig + dash if n == 0 else dig
                    if n == 0 and dash:                            # 段首：像负号就是负号（游戏的负号只是一小横）
                        k = max(cand, key=lambda kk: SK[j, kk])
                        k = dash[0] if _is_dash(SK, j, dash[0], dig) else k
                    else:
                        k = max(cand, key=lambda kk: SK[j, kk])
                    sc = float(SK[j, k])
                    if sc < (DASH_MIN if keys[k] == "-" else MIN_SCORE):
                        out[j], sc_of[j] = "?", sc                # 挑出来的数字也不像：不硬猜（Codex 2026-10-27 补审）
                    else:
                        out[j], sc_of[j] = keys[k], sc
            seg = []
        else:
            seg.append(i)


def _is_dash(SK, j, kd, dig):
    """段首这一格是负号还是数字：负号那张字模比所有数字都像，或者数字里最像的也不太像（< 0.7）"""
    bd = max(SK[j, k] for k in dig)
    return SK[j, kd] >= bd or bd < 0.7


class Glyphs:
    """字模（两种字号各一套）：每个字一张平均图；认的时候每格和全部字模做归一化相关，左右各挪 1 像素取最好的"""

    def __init__(self, grid):
        self.g = grid
        self.samples = {s: {} for s in SCALES}
        self.keys = {s: [] for s in SCALES}
        self.T = {s: None for s in SCALES}          # 字模图 (M, lh, cw)
        self.owner = {s: None for s in SCALES}      # 每张字模是 keys 里第几个字
        self.Tn = {s: None for s in SCALES}
        self.verified = 0                            # 自检通过了几次（存下来的字模读回来算通过）
        self.font = {}                               # 用字体画的：{字号: (字号像素, dy, 吻合度)}
        self.starts = {s: None for s in SCALES}      # 每个字的第一张字模在 T 里的位置（字模按字排好）

    # ---- 学 ----
    def learn(self, tm, top, text, part="fixed"):
        """text：这一行的文字（空格数不用准）。有墨的格子按顺序对应去掉空格后的字；个数对不上就不学。返回学了几个字。
        part="fixed"：只学格式固定的字（Zone、Pos、数字、km、Root、SolarSystem…）；
        part="name"：只学区域名里的字，而且要和已经学会的同一个字很像才收——识别引擎常把 O 认成 0、o 认成 0，
        区域名又没有固定格式，不检查就会把字模带坏（2026-10-27 实测：学多了 Pos 读成 P0s）"""
        scale = self.g.scale_of(tm, top)
        imgs = self.g.cells(tm, top, scale)
        chars = [c for c in text if c != " "]
        if imgs is None or not chars:
            return 0
        ink = _inks(imgs) >= 3
        if int(ink.sum()) != len(chars):
            return 0
        roles = _roles(text)
        bag = self.samples[scale]
        n = 0
        for ch, im, role in zip(chars, imgs[ink], roles):
            if role != part:
                continue
            if part == "name" and not self._looks_like(scale, im, ch):
                continue
            lst = bag.setdefault(ch, [])
            lst.append(im.copy())                       # 复制一份：切片会连带留住整块大图
            del lst[:-MAX_SAMPLES]
            n += 1
        if part == "fixed":
            for im in imgs[~ink][:2]:
                lst = bag.setdefault(" ", [])
                lst.append(im.copy())
                del lst[:-MAX_SAMPLES]
        return n

    def _looks_like(self, scale, im, ch):
        """区域名里的字收不收：学过这个字 → 要和它很像、而且不比别的字更像；没学过 → 不能像任何学过的字"""
        Tn, keys, owner = self.Tn[scale], self.keys[scale], self.owner[scale]
        if Tn is None:
            return False
        x = im.reshape(-1) - im.mean()
        x = x / (np.linalg.norm(x) + 1e-6)
        S = (Tn @ x).reshape(3, len(owner)).max(0)
        best = {}
        for k, v in zip(owner, S):
            best[keys[k]] = max(best.get(keys[k], -1.0), float(v))
        best.pop(" ", None)
        other = max((v for c, v in best.items() if c != ch), default=0.0)
        if ch in best:
            return best[ch] >= 0.85 and best[ch] >= other
        near = max(((v, c) for c, v in best.items()), default=(0.0, ""))
        return not (near[0] >= 0.8 and fold(near[1]) == fold(ch))      # 新字长得像学过的「易混字」（O 像 0）：不收



    def finalize(self):
        """同一个字按「渲染相位」分成几个字模：字距不是整数像素，同一个字落在不同相位上抗锯齿长得不一样
        （1440p 两种、1600p 三种），一张平均图糊在一起认不准。相关 ≥ 0.85 的并成一组取平均，最多 4 组"""
        for s in SCALES:
            bag = self.samples[s]
            keys = sorted(c for c, v in bag.items() if len(v) >= MIN_SAMPLES or c == " ")
            self.keys[s] = keys
            if not keys:
                continue
            T, owner = [], []
            for ki, c in enumerate(keys):
                groups = []                                   # [(平均图, 个数)]
                for im in bag[c][-40:]:
                    best, bi = -1.0, -1
                    for gi, (m, n) in enumerate(groups):
                        r = _corr(im, m)
                        if r > best:
                            best, bi = r, gi
                    if bi >= 0 and (best >= 0.85 or len(groups) >= 4):
                        m, n = groups[bi]
                        groups[bi] = ((m * n + im) / (n + 1), n + 1)
                    else:
                        groups.append((im.copy(), 1))
                big = [g for g in groups if g[1] >= 2] or groups
                for m, n in big:
                    T.append(m); owner.append(ki)  # noqa: E702
            self.T[s] = np.stack(T)
            self.owner[s] = np.array(owner)
            self.starts[s] = np.searchsorted(self.owner[s], np.arange(len(keys)))
            self.Tn[s] = _shifted(self.T[s])
        return self.keys

    @classmethod
    def from_font(cls, grid, tm):
        """用字体画全部字模（两种字号各自试出字号和位置）。主字号对不上返回 None"""
        try:
            return cls._from_font(grid, tm)
        finally:
            # 高清大图只在画字模时用：画完就放掉（字模已经在 g 里、也存了文件）。
            # 以前一直留着，1440p 约一百多 MB、4K 三百多 MB 常驻（S2 审查 2026-10-31）
            _HIRES.clear()

    @classmethod
    def _from_font(cls, grid, tm):
        g = cls(grid)
        for s in SCALES:
            fit = fit_font(tm, grid, s)
            if fit is None:
                if s == "main":
                    return None
                em, dy, sc = g.font["main"][0] * SMALL, g.font["main"][1] * SMALL, 0.0
            else:
                em, dy, sc = fit
            if s == "main" and sc < 0.8:
                return None
            g.font[s] = (em, dy, sc)
            adv, _ = grid.adv[s]
            for ch, lst in font_templates(em, dy, grid.lh, int(np.ceil(adv)) + 1).items():
                for t in lst:
                    g.samples[s].setdefault(ch, []).extend([t, t])
        g.finalize()
        return g

    def complete(self):
        return REQUIRED <= set(self.keys["main"])

    def ready(self):
        """能用了：字学齐了，而且和识别引擎读的坐标对上过 VERIFY_TIMES 次"""
        return self.complete() and self.verified >= VERIFY_TIMES

    # ---- 认 ----
    def read_row(self, tm, top):
        """一行 → (文字, 最低可信度, 字号)。认不出的格子（相关 < 0.5 或这种字号还没学）写 '?'"""
        scale = self.g.scale_of(tm, top)
        imgs = self.g.cells(tm, top, scale)
        if imgs is None:
            return "", 0.0, scale
        Tn, keys, owner = self.Tn[scale], self.keys[scale], self.owner[scale]
        ink = _inks(imgs)
        if Tn is None:
            return "".join("?" if v >= 3 else " " for v in ink).strip(), 0.0, scale
        X = imgs.reshape(len(imgs), -1)
        Xn = X - X.mean(1, keepdims=True)
        Xn = Xn / (np.linalg.norm(Xn, axis=1, keepdims=True) + 1e-6)
        S = (Xn @ Tn.T).reshape(len(imgs), 3, len(owner)).max(1)      # 三个位移取最好 → (格数, 字模数)
        SK = np.maximum.reduceat(S, self.starts[scale], axis=1)      # 每个字取它几张字模里最像的 → (格数, 字数)
        best = SK.argmax(1)
        out, sc_of = [], []
        for i in range(len(imgs)):
            if ink[i] < 3:
                out.append(" "); sc_of.append(1.0)  # noqa: E702
                continue
            sc = float(SK[i, best[i]])
            ch = keys[best[i]]
            if sc < MIN_SCORE:
                if ink[i] < 6:                      # 几个像素的墨、又谁都不像：邻格漏进来的，当空格
                    out.append(" "); sc_of.append(1.0)  # noqa: E702
                    continue
                ch, sc = "?", 0.0
            out.append(ch); sc_of.append(sc)  # noqa: E702
        _digit_context(out, sc_of, SK, keys)
        low = min([v for v, c in zip(sc_of, out) if c != " "] or [1.0])
        return "".join(out).strip(), low, scale

    def read(self, tm, only=None):
        """整块 → [(顶边 y, 文字, 可信度, 字号)]，从上到下。only：只认这几个顶边 y 附近的行（每帧只认要用的四五行，快一倍多）"""
        tops = row_tops(tm)
        if only:
            want = []
            for y in only:
                t = min(tops, key=lambda v: abs(v - y)) if tops else None
                if t is not None and abs(t - y) <= 3 and t not in want:
                    want.append(t)
            tops = sorted(want)
        return [(t, *self.read_row(tm, t)) for t in tops]

    # ---- 存取 ----
    def save(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"grid": json.dumps(self.g.params()), "h": self.g.h, "font": json.dumps(self.font)}
        for s in SCALES:
            if self.T[s] is not None:
                data[f"T_{s}"] = self.T[s]
                data[f"owner_{s}"] = self.owner[s]
                data[f"keys_{s}"] = np.array(self.keys[s])
        np.savez_compressed(path, **data)

    @classmethod
    def load(cls, path):
        z = np.load(path, allow_pickle=False)
        grid = Grid(int(z["h"]), params=json.loads(str(z["grid"])))
        g = cls(grid)
        for s in SCALES:
            if f"T_{s}" in z:
                keys = [str(k) for k in z[f"keys_{s}"]]
                T = z[f"T_{s}"].astype(np.float32)
                for t, ki in zip(T, z[f"owner_{s}"]):
                    g.samples[s].setdefault(keys[int(ki)], []).extend([t, t])   # 每张字模当两个样本，做以后继续学的底子
        g.finalize()
        g.verified = VERIFY_TIMES                    # 只有自检通过才会存文件
        if "font" in z:
            g.font = {k: tuple(v) for k, v in json.loads(str(z["font"])).items()}
        return g


# ---------------------------------------------------------------- 校准（从文字识别的结果里学）和对外接口

NEEDED_LINE = re.compile(r"Zone|player\s*location|CamDir|FPS|Planet", re.I)
_state = {"glyphs": None, "h": None, "tried_load": False, "font_at": 0.0, "fails": 0}


GLYPH_VERSION = 2            # 2026-10-27 起用字体画字模：旧版（1.0.2 测试版）学出来的文件可能被带坏，不再读


def _path(h):
    return GLYPH_DIR / f"{int(h)}_v{GLYPH_VERSION}.npz"


def _for(h, create_tm=None):
    if _state["h"] != h:
        _state.update(h=h, glyphs=None, tried_load=False)
    if _state["glyphs"] is None and not _state["tried_load"]:
        _state["tried_load"] = True
        try:
            if _path(h).exists():
                _state["glyphs"] = Glyphs.load(_path(h))
        except Exception:
            _state["glyphs"] = None
    if _state["glyphs"] is None and create_tm is not None:
        grid = Grid(h, create_tm)
        if grid.ok:
            _state["glyphs"] = Glyphs(grid)
    return _state["glyphs"]


def ready(h):
    g = _for(h)
    return bool(g and g.ready())


def note(ok):
    """读完一次告诉这里字模好不好用：字模读不出、识别引擎却读得出，连续 GRID_FAILS 次就扔掉这套字模马上重画
    （改了游戏缩放 / 分辨率后旧字模会一直失效，以前不会重画，只会每 0.2 秒退回识别引擎占 CPU，Codex 2026-10-27 补审）"""
    if ok:
        _state["fails"] = 0
        return
    _state["fails"] += 1
    if _state["fails"] >= GRID_FAILS:
        _state.update(glyphs=None, tried_load=True, font_at=0.0, fails=0)       # 不再读旧文件，下一帧就用字体重画


def trusted(text):
    """这一行的识别结果能不能拿来学字"""
    t = re.sub(r"\s+", "", text or "")
    return bool(TRUST_POS.match(t) or TRUST_CAM.match(t) or TRUST_LOC.match(t))


def feed(piece_rgb, ocr_rows, screen_h):
    """一次整块文字识别的结果喂进来学：ocr_rows = [(文字, 这一行在 piece 里的中心 y)]。返回 (主字号学会的字数, 是否可用)。
    只学格式对得上的行（trusted）；学完用字模把坐标行重读一遍，和识别引擎读的坐标一样才算通过一次自检"""
    tm = textness(piece_rgb)
    g = _for(screen_h, create_tm=tm)
    if g is None:
        return 0, False
    g.g.xr = right_edge(tm, g.g.xr)
    tops = row_tops(tm)
    if not tops:
        return len(g.keys["main"]), g.ready()
    good = []
    for text, yc in ocr_rows:
        text = (text or "").strip()
        if not text or not trusted(text):
            continue
        top = min(tops, key=lambda t: abs(t + g.g.lh / 2 - yc))
        if abs(top + g.g.lh / 2 - yc) > g.g.lh:
            continue
        g.learn(tm, top, text, "fixed")
        good.append((text, top))
    g.finalize()
    for text, top in good:                          # 第二遍：区域名里的字，和学会的字对照着收
        g.learn(tm, top, text, "name")
    g.finalize()
    if g.complete() and _verify(g, tm, good):
        g.verified += 1
        if g.ready():
            try:
                g.save(_path(screen_h))
            except Exception:
                pass
    return len(g.keys["main"]), g.ready()


def _verify(g, tm, rows):
    """自检：字模把坐标行重读一遍，解析出来的星系坐标、星球局部坐标都要和识别引擎的一样"""
    from .displayinfo import parse
    pos = [(t, top) for t, top in rows if TRUST_POS.match(re.sub(r"\s+", "", t))]
    if len(pos) < 2:
        return False
    exp = parse([t for t, _ in pos])
    from .displayinfo import grid_text
    got = parse([grid_text(g.read_row(tm, top)[0]) for _, top in pos])
    if not exp["global"] or got["global"] != exp["global"]:
        return False
    return got["local"] == exp["local"]


def _try_font(h, tm):
    """还没有能用的字模：用字体画一套（试字号约 1～3 秒，每种分辨率只做一次，存到 userdata\\glyphs）。
    自检：画出的字模要把 SolarSystem、Root 两行坐标都认出来而且一致，才启用"""
    if time.time() - _state["font_at"] < FONT_RETRY or not FONT_FILE.exists():
        return None
    _state["font_at"] = time.time()
    try:
        grid = Grid(h, tm)
        if not grid.ok:
            return None
        g = Glyphs.from_font(grid, tm)
        if g is None or not _self_check(g, tm):
            return None
    except Exception:
        return None
    g.verified = VERIFY_TIMES
    _state["glyphs"] = g
    try:
        g.save(_path(h))
    except Exception:
        pass
    return g


def _self_check(g, tm):
    from .displayinfo import parse
    from .displayinfo import grid_text
    texts = [grid_text(t) for _, t, _, _ in g.read(tm)]
    return parse(texts, need_both=True)["global"] is not None          # 两行都完整读出来、而且一致


def read_rows(piece_rgb, screen_h, only=None):
    """字模认整块 → [(顶边 y, 文字, 可信度, 字号)]；字模没准备好（而且用字体也画不出）返回 None。only：只认这几行（顶边 y）"""
    tm = textness(piece_rgb)
    g = _for(screen_h)
    if g is None or not g.ready():
        g = _try_font(screen_h, tm)
        if g is None:
            return None
        only = None
    g.g.xr = right_edge(tm, g.g.xr)
    return g.read(tm, only=only)


def status():
    g = _state["glyphs"]
    return {"h": _state["h"], "ready": bool(g and g.ready()), "verified": g.verified if g else 0,
            "source": ("font" if g.font else "learned") if g else "",
            "glyphs": {s: len(g.keys[s]) for s in SCALES} if g else {},
            "missing": sorted(REQUIRED - set(g.keys["main"])) if g else sorted(REQUIRED)}
