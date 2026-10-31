"""游戏上方的悬浮窗（所有功能共用）

各功能往自己的分区写字：hud().set("扫描", "第一行是标题\\n下面是内容")，悬浮窗把各分区叠起来显示，
同样的内容也会实时出现在助手窗口右侧。一闪而过的提示用 hud().note("…", 秒)：白色胶囊，同时只有一条。
- 游戏要用「无边框窗口」模式才看得到悬浮窗（全屏模式下会被游戏盖住）
- 鼠标穿透、永远不抢焦点：鼠标飘过去或点到它，操作都直接给游戏
- 要换位置：AT「设置与更新」里打开「移动悬浮窗」，拖好再关上（位置会记住）
- 悬浮窗在自己的线程里运行，任何线程都可以调用 set()

1.6.61 起照 DESIGN.md 第 8 节自己画：先用 PIL 画成一张带透明度的图，再整张贴到窗口上（UpdateLayeredWindow）。
这样只有底板半透明、字不透明（以前整个窗口 92% 透明，字也跟着淡）；字号按屏幕高度算（1080p 正文 18px、2K 24px），
数字和英文用 D-DIN，数字等宽。1.6.63（审查意见）：读数变了直接换、位置不动，不再模糊；只有新出现的分区淡入。
"""

import json
import queue
import re
import sys
import threading
import time
from pathlib import Path

ENABLED = True  # 不想要悬浮窗就改成 False
from ..core.paths import USER  # noqa: E402

POS_FILE = USER / "overlay_pos.json"
LABEL = {
    "扫描": "采矿助手",
    "导航": "导航",
}  # 分区显示名（2026-10-25 用户改的页名；内部仍叫扫描 / 导航）
EN = {
    "辅助": "ASSIST",
    "信号": "SIGNAL",
    "扫描": "SCAN",
    "矿袋": "BAG",
    "导航": "NAV",
    "小行星带": "BELT",
    "物品": "ITEM",
    "交易": "TRADE",
    "路标": "MARK",
    "反馈": "REPORT",
    "盘点": "COUNT",
    "采矿助手": "SCAN",
}
ORDER = [
    "辅助",
    "信号",
    "扫描",
    "矿袋",
    "导航",
    "小行星带",
    "物品",
    "交易",
    "盘点",
    "路标",
    "反馈",
]  # 分区显示顺序，没列出的排最后

# ---- 尺寸（1080p 下的像素，按屏幕高度等比放大；玩家还能在设置里缩小到 hud_scale 倍：0.5 / 0.75 / 1）
BASE_W = 400  # 悬浮窗宽
BODY_PX = 18  # 正文：XAG 101，PC 1080p 至少 18px
TITLE_PX = 21
LABEL_PX = 12
NOTE_PX = 17
STAT_PX = 26  # 关键读数的数字
STAT_L = 15  # 关键读数的小标签
HEAD_PX = 20  # 分组标题（矿物组成、开采建议）
ROW_PX = 20  # 每种矿
SUB_PX = 18  # 各品质
GAIN_PX = 26  # 精炼产量、净值的数字
MINOR_PX = 17
FOOT_PX = 14
LINE_C = (255, 255, 255, 46)  # 分隔线
HI_C = (142, 197, 255, 255)  # 高品质那份（蓝，DESIGN.md 的「好」）
PAD_X, PAD_T, PAD_B, GAP = 16, 12, 14, 8
RADIUS = 8
MARGIN = 2  # 留一点边，圆角和阴影不被切

# ---- 颜色（DESIGN.md 第 1、8 节）：只有底板半透明，字不透明
PLATE = (0, 0, 0)
PLATE_ALPHA = 0.72  # 设置 hud_plate 可以改
EDGE = (255, 255, 255, 31)
TITLE_C = (255, 255, 255, 255)
BODY_C = (230, 230, 238, 255)
LABEL_C = (196, 196, 204, 255)
MINOR_C = (180, 180, 190, 255)  # 次要详情：灰一档，在雪地上也有 4.5:1
NOTE_BG = (240, 240, 250, 255)
NOTE_C = (0, 0, 0, 255)
# 2026-10-27 老大：保留现有（默认）、再加两套。设置 hud_theme 选
PALETTES = {
    "默认": dict(
        PLATE=(0, 0, 0),
        EDGE=(255, 255, 255, 31),
        TITLE_C=(255, 255, 255, 255),
        BODY_C=(230, 230, 238, 255),
        LABEL_C=(196, 196, 204, 255),
        MINOR_C=(180, 180, 190, 255),
        LINE_C=(255, 255, 255, 46),
        HI_C=(142, 197, 255, 255),
        NOTE_BG=(240, 240, 250, 255),
        NOTE_C=(0, 0, 0, 255),
    ),
    "蓝金": dict(
        PLATE=(16, 30, 60),
        EDGE=(198, 171, 108, 70),
        TITLE_C=(233, 237, 245, 255),
        BODY_C=(214, 221, 234, 255),
        LABEL_C=(198, 171, 108, 255),
        MINOR_C=(170, 181, 201, 255),
        LINE_C=(198, 171, 108, 64),
        HI_C=(222, 196, 132, 255),
        NOTE_BG=(198, 171, 108, 255),
        NOTE_C=(21, 40, 81, 255),
    ),
    "浅色": dict(
        PLATE=(242, 242, 247),
        EDGE=(0, 0, 0, 36),
        TITLE_C=(0, 0, 0, 255),
        BODY_C=(28, 28, 30, 255),
        LABEL_C=(95, 95, 102, 255),
        MINOR_C=(80, 80, 88, 255),
        LINE_C=(0, 0, 0, 40),
        HI_C=(23, 84, 150, 255),
        NOTE_BG=(23, 37, 56, 255),
        NOTE_C=(255, 255, 255, 255),
        PLATE_MIN=0.9,
    ),
}
for _p in PALETTES.values():
    _p.setdefault("PLATE_MIN", 0.0)  # 浅底板太透明会透出游戏 HUD，至少 90% 不透明
PLATE_MIN = 0.0


def plate_alpha(plate):
    """底板不透明度。浅色配色至少 90%：「浅 / 标准 / 深」三档映射成 90% / 约 95% / 100%，不然三档一样（二审 2026-10-27）"""
    p = max(0.3, min(1.0, float(plate)))
    if PLATE_MIN:
        p = PLATE_MIN + (min(0.85, max(0.6, p)) - 0.6) / 0.25 * (1.0 - PLATE_MIN)
    return p


_palette = "默认"


def use_palette(name):
    """换悬浮窗配色（只改底板和字的颜色，导航记号还是金色）"""
    global _palette
    name = name if name in PALETTES else "默认"
    if name != _palette:
        globals().update(PALETTES[name])
        _palette = name


FADE_MS, STAGGER_MS, BLUR_PX = (
    160,
    0,
    0,
)  # 新出现的分区：160ms 淡入（不模糊）；已有分区里的读数变了直接换

_hud = None
_hud_lock = threading.Lock()

HWND = None  # 悬浮窗的窗口句柄（读屏时涂黑这块）
SHOWN = False  # 现在有没有显示内容（没内容时窗口还在，只是全透明）

# Windows 扩展样式
GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x00080000, 0x00000020
WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, WS_EX_TOPMOST = 0x00000080, 0x08000000, 0x00000008
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x1, 0x2, 0x10, 0x20

# 悬浮窗不放表情符号（DESIGN.md：一行一件事，不靠图标），画出来也只是方框
_EMOJI = re.compile("[\U0001f000-\U0001faff\u2600-\u27bf\ufe0f\u200d\u2b50\u2b55]")
_DIN_CHARS = set(
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz .,:;%+-/()'#&!?[]_=<>*"
)
_COLS = re.compile(r"\s{2,}|\t")


def clean(text):
    return _EMOJI.sub("", text or "").strip()


# ================================================================ 字体
_FONT_CACHE = {}
_WEB_FONTS = Path(__file__).resolve().parent / "web" / "fonts"
_CJK = {  # 中文：微软雅黑；没有的话（测试机）用系统里的 Noto
    False: [
        r"C:\Windows\Fonts\msyh.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ],
    True: [
        r"C:\Windows\Fonts\msyhbd.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ],
}


def _font(kind, px, bold=False):
    """kind：din（数字英文）/ cjk（中文和其他）"""
    key = (kind, int(px), bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    from PIL import ImageFont

    paths = (
        [str(_WEB_FONTS / ("D-DIN-Bold.ttf" if bold else "D-DIN.ttf"))]
        if kind == "din"
        else []
    )
    paths += _CJK[bold] + _CJK[False]
    f = None
    for p in paths:
        try:
            f = ImageFont.truetype(p, int(px))
            break
        except Exception:
            continue
    if f is None:
        f = ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f


def _runs(text):
    """按字分成「D-DIN 能画的」和「中文字体画的」几段"""
    out = []
    for ch in text:
        k = "din" if ch in _DIN_CHARS else "cjk"
        if out and out[-1][0] == k:
            out[-1][1] += ch
        else:
            out.append([k, ch])
    return out


def text_width(text, px, bold=False):
    return sum(_font(k, px, bold).getlength(s) for k, s in _runs(text))


def draw_text(draw, x, baseline, text, px, fill, bold=False):
    for k, s in _runs(text):
        f = _font(k, px, bold)
        draw.text((x, baseline), s, font=f, fill=fill, anchor="ls")
        x += f.getlength(s)
    return x


# 不能从中间断开的一段：数字连同单位（18.35 SCU、412,000 aUEC、12%）、英文单词
_ATOM = re.compile(
    r"[+\-−]?\d[\d,.]*(?:\s?(?:uSCU|SCU|aUEC|kg|km|Gm|m|%|°|×\d+))?|×\d+|[A-Za-z][A-Za-z0-9'\-]*|\s+|.",
    re.S,
)


def wrap(text, px, width, bold=False):
    """按实际宽度折行：中文按字断，数字和单位、英文单词整体换行（审查意见：数字与单位不能拆开）"""
    lines, cur = [], ""
    for atom in _ATOM.findall(text):
        if not cur and atom.isspace():
            continue
        if text_width(cur + atom, px, bold) <= width or not cur:
            cur += atom
            continue
        lines.append(cur.rstrip())
        cur = "" if atom.isspace() else atom
    if cur.strip():
        lines.append(cur.rstrip())
    return lines or [""]


# ================================================================ 画图（纯函数：测试和预览也用它）
def _rich_lines(rich, scale, width):
    """采矿助手（1.6.65 照用户给的样图）：矿名 → 三格读数 → 矿物组成（每种矿、下面各品质、占整石）→ 开采建议 → 精炼产量和净值 → 次要。
    主次靠字号、位置和分隔线"""
    lines = [
        ("t", s, "")
        for s in wrap(clean(rich.get("title") or ""), TITLE_PX * scale, width, True)
    ]
    stats = [[clean(str(x)) for x in c] for c in rich.get("stats") or []]
    if stats:
        lines.append(("s", stats, ""))
    comp = rich.get("comp") or []
    if comp:
        # 1.6.66（用户）：比例一律写明占整块矿石；只有一种品质的矿合成一行「铜 · 品质 450 · 18%」；不画折叠箭头（点不了）
        lines += [("d", "", ""), ("h", "矿物组成", "占整块矿石")]
        for c in comp:
            subs = c.get("subs") or []
            if len(subs) == 1:
                lines.append(("c", dict(c, one=subs[0]), ""))
                continue
            lines.append(("c", c, ""))
            for j, q in enumerate(subs):
                lines.append(("q", dict(q, last=j == len(subs) - 1), ""))
    adv = rich.get("advice")
    if adv:
        lines += [("d", "", ""), ("h", "开采建议", "")]
        heads, power = clean(adv.get("heads") or ""), clean(adv.get("power") or "")
        if (
            text_width(heads, 21 * scale) + 32 * scale + text_width(power, 19 * scale)
            <= width
        ):
            lines.append(("a", {"heads": heads, "power": power}, ""))
        else:  # 1.6.70：矿头名太长放不下，建议功率换到下一行（以前叠在一起）
            lines += [("a", {"heads": l}, "") for l in wrap(heads, 21 * scale, width)]  # noqa: E741
            if power:
                lines.append(("a", {"heads": power, "sub": True}, ""))
    gain = rich.get("gain") or []
    if gain:
        lines += [("d", "", ""), ("G", gain, "")]
    minor = [clean(x) for x in rich.get("minor") or [] if clean(x)]
    for m in minor:
        lines += [("m", s, "") for s in wrap(m, MINOR_PX * scale, width)]
    if rich.get("foot"):
        lines.append(("f", clean(rich["foot"]), ""))
    return lines


def layout(sections, scale, rich=None):
    """分区 → 要画的块：[{key, label, lines: [(种类, 文字, 右边文字)]}]。
    种类：t 标题、s 关键读数（几格）、b 正文、k 左名右值、m 次要（灰）、g 组间留白"""
    width = (BASE_W - 2 * PAD_X) * scale
    rich = rich or {}
    blocks = []
    for k in sorted(
        sections, key=lambda k: ORDER.index(k) if k in ORDER else len(ORDER)
    ):
        text = clean(sections[k])
        if not text:
            continue
        name = LABEL.get(k, k)
        label = f"{EN.get(k, '')} · {name}" if EN.get(k) else name
        if rich.get(k):
            blocks.append(
                {"key": k, "label": label, "lines": _rich_lines(rich[k], scale, width)}
            )
            continue
        title, *rest = text.split("\n")
        lines = [("t", s, "") for s in wrap(title, TITLE_PX * scale, width, True)]
        for raw in "\n".join(rest).split("\n") if rest else []:
            raw = raw.rstrip()
            if not raw:
                continue
            parts = [p for p in _COLS.split(raw.strip()) if p]
            if len(parts) >= 2 and text_width(raw, BODY_PX * scale) <= width:
                lines.append(("b", parts[0], "  ".join(parts[1:])))
            else:
                lines += [("b", s, "") for s in wrap(raw, BODY_PX * scale, width)]
        blocks.append(
            {
                "key": k,
                "label": f"{EN.get(k, '')} · {name}" if EN.get(k) else name,
                "lines": lines,
            }
        )
    return blocks


def paint(
    sections,
    note="",
    movable=False,
    scale=1.0,
    plate=PLATE_ALPHA,
    fresh=None,
    now=None,
    rich=None,
):
    """画出整个悬浮窗。fresh = {(分区, 行号): 开始淡入的时间}，正在淡入的行画成半模糊。返回 (图, 还在动画吗)"""
    from PIL import Image, ImageDraw, ImageFilter

    s = scale
    W = int(round(BASE_W * s)) + 2 * MARGIN
    blocks = layout(sections, s, rich)
    note = clean(note)
    if movable and not blocks and not note:
        blocks = [
            {
                "key": "_move",
                "label": "MOVE · 移动",
                "lines": [
                    ("t", "拖动此处调整位置", ""),
                    ("b", "调整完成后在 AT 中关闭「移动悬浮窗」", ""),
                ],
            }
        ]
    lh = {
        "t": TITLE_PX * s * 1.3,
        "b": BODY_PX * s * 1.5,
        "k": BODY_PX * s * 1.5,
        "m": MINOR_PX * s * 1.5,
        "s": (STAT_L * 1.5 + STAT_PX * 1.2) * s,
        "g": 4 * s,
        "d": 14 * s,
        "h": HEAD_PX * s * 1.4,
        "hr": STAT_L * s * 1.7,
        "c": ROW_PX * s * 1.55,
        "q": SUB_PX * s * 1.45,
        "a": 21 * s * 1.45,
        "G": (STAT_L * 1.55 + GAIN_PX * 1.2) * s + 4 * s,
        "f": FOOT_PX * s * 1.5,
    }
    # 先算高度
    h = MARGIN
    note_lines = wrap(note, NOTE_PX * s, (BASE_W - 40) * s) if note else []
    if note:
        h += int(len(note_lines) * NOTE_PX * s * 1.45 + 20 * s) + int(GAP * s)
    heights = []
    for b in blocks:
        bh = (
            PAD_T * s
            + LABEL_PX * s * 1.6
            + sum(lh[t] for t, _, _ in b["lines"])
            + PAD_B * s
        )
        heights.append(int(bh))
        h += int(bh) + int(GAP * s)
    h = max(1, int(h + MARGIN - (GAP * s if (blocks or note) else 0)))
    img = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    now = time.time() if now is None else now
    fresh = fresh or {}
    busy = False
    y = MARGIN
    x0, x1 = MARGIN, W - MARGIN - 1
    if note:  # 一闪而过的提示：白色胶囊，贴右
        nw = max(text_width(l, NOTE_PX * s) for l in note_lines) + 40 * s  # noqa: E741
        nh = len(note_lines) * NOTE_PX * s * 1.45 + 20 * s
        nx = x1 - nw
        d.rounded_rectangle(
            (nx, y, x1, y + nh), radius=min(nh / 2, 32 * s), fill=NOTE_BG
        )
        by = y + 10 * s + NOTE_PX * s * 1.08
        for l in note_lines:  # noqa: E741
            draw_text(d, nx + 20 * s, by, l, NOTE_PX * s, NOTE_C)
            by += NOTE_PX * s * 1.45
        y += int(nh) + int(GAP * s)
    plate_a = int(255 * plate_alpha(plate))
    for b, bh in zip(blocks, heights):
        d.rounded_rectangle(
            (x0, y, x1, y + bh),
            radius=RADIUS * s,
            fill=PLATE + (plate_a,),
            outline=EDGE,
            width=max(1, int(s)),
        )
        ly = y + PAD_T * s + LABEL_PX * s * 1.05
        draw_text(d, x0 + PAD_X * s, ly, b["label"], LABEL_PX * s, LABEL_C)
        cy = y + PAD_T * s + LABEL_PX * s * 1.6
        for i, (t, left, right) in enumerate(b["lines"]):
            px = (TITLE_PX if t == "t" else BODY_PX) * s
            base = cy + px * (1.08 if t == "t" else 1.12)
            started = fresh.get((b["key"], i))
            p = 1.0 if started is None else (now - started) * 1000 / FADE_MS
            target = d
            layer = None
            if 0 <= p < 1:  # 淡入中：先画到单独一层，模糊 + 降透明度再贴上
                busy = True
                layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
                target = ImageDraw.Draw(layer)
            elif p < 0:
                busy = True
                cy += lh[t]
                continue
            L, R = x0 + PAD_X * s, x1 - PAD_X * s
            if t in ("s", "G"):  # 几格：小标签在上、大数字在下，格子之间竖线
                cells = left
                cw = (R - L) / max(1, len(cells))
                vpx = STAT_PX if t == "s" else GAIN_PX
                for j, cell in enumerate(cells):
                    name, val, unit = (list(cell) + ["", "", ""])[:3]
                    cx = L + j * cw + (14 * s if j else 0)
                    if j:
                        target.line(
                            (L + j * cw, cy + 2 * s, L + j * cw, cy + lh[t] - 6 * s),
                            fill=LINE_C,
                            width=max(1, int(s)),
                        )
                    draw_text(
                        target, cx, cy + STAT_L * s * 1.05, name, STAT_L * s, LABEL_C
                    )
                    vy = cy + (STAT_L * 1.55 + vpx * 1.0) * s
                    vx = draw_text(target, cx, vy, val, vpx * s, TITLE_C, bold=True)
                    if unit:
                        draw_text(target, vx + 4 * s, vy, unit, vpx * s * 0.68, BODY_C)
            elif t == "d":  # 分隔线
                target.line(
                    (L, cy + lh[t] / 2, R, cy + lh[t] / 2),
                    fill=LINE_C,
                    width=max(1, int(s)),
                )
            elif t == "h":
                draw_text(
                    target,
                    L,
                    cy + HEAD_PX * s * 1.05,
                    left,
                    HEAD_PX * s,
                    TITLE_C,
                    bold=True,
                )
                if right:  # 右边写比例的口径（占整块矿石）
                    draw_text(
                        target,
                        R - text_width(right, STAT_L * s),
                        cy + HEAD_PX * s * 1.05,
                        right,
                        STAT_L * s,
                        LABEL_C,
                    )
            elif t == "hr":
                draw_text(target, L, cy + STAT_L * s * 1.1, left, STAT_L * s, LABEL_C)
                draw_text(
                    target,
                    R - text_width(right, STAT_L * s),
                    cy + STAT_L * s * 1.1,
                    right,
                    STAT_L * s,
                    LABEL_C,
                )
                target.line(
                    (L, cy + lh[t] - 3 * s, R, cy + lh[t] - 3 * s),
                    fill=LINE_C,
                    width=max(1, int(s)),
                )
            elif (
                t == "c"
            ):  # 一种矿：名字 …… 占整块矿石；只有一种品质的合成一行；惰性物质不写品质
                c = left
                base_c = cy + ROW_PX * s * 1.1
                x = draw_text(
                    target,
                    L,
                    base_c,
                    c["name"],
                    ROW_PX * s,
                    BODY_C if c.get("inert") else TITLE_C,
                    bold=not c.get("inert"),
                )
                one = c.get("one")
                if one:
                    x = draw_text(target, x, base_c, " · 品质 ", SUB_PX * s, BODY_C)
                    draw_text(
                        target,
                        x,
                        base_c,
                        one["q"],
                        SUB_PX * s,
                        HI_C if one.get("hi") else BODY_C,
                    )
                pct = c["pct"]
                draw_text(
                    target,
                    R - text_width(pct, ROW_PX * s, True),
                    base_c,
                    pct,
                    ROW_PX * s,
                    TITLE_C,
                    bold=True,
                )
            elif t == "q":  # 各品质：树线 + 品质 925 …… 30%
                q = left
                lx = L + 6 * s
                mid = cy + lh[t] * 0.48
                target.line(
                    (lx, cy - 2 * s, lx, mid if q.get("last") else cy + lh[t]),
                    fill=LINE_C,
                    width=max(1, int(s)),
                )
                target.line(
                    (lx, mid, lx + 12 * s, mid), fill=LINE_C, width=max(1, int(s))
                )
                bq = cy + SUB_PX * s * 1.08
                x = draw_text(target, L + 24 * s, bq, "品质 ", SUB_PX * s, BODY_C)
                draw_text(
                    target, x, bq, q["q"], SUB_PX * s, HI_C if q.get("hi") else BODY_C
                )
                draw_text(
                    target,
                    R - text_width(q["pct"], SUB_PX * s),
                    bq,
                    q["pct"],
                    SUB_PX * s,
                    BODY_C,
                )
            elif t == "a":  # 开采建议：矿头组合 | 建议功率
                adv = left
                ba = cy + 21 * s * 1.05
                pw = text_width(adv.get("power", ""), 19 * s)
                draw_text(
                    target,
                    L,
                    ba,
                    adv.get("heads", ""),
                    (19 if adv.get("sub") else 21) * s,
                    BODY_C if adv.get("sub") else TITLE_C,
                )
                if adv.get("power"):
                    target.line(
                        (
                            R - pw - 16 * s,
                            cy + 4 * s,
                            R - pw - 16 * s,
                            cy + lh[t] - 8 * s,
                        ),
                        fill=LINE_C,
                        width=max(1, int(s)),
                    )
                    draw_text(target, R - pw, ba, adv["power"], 19 * s, BODY_C)
            elif t == "f":
                draw_text(target, L, cy + FOOT_PX * s * 1.1, left, FOOT_PX * s, MINOR_C)
            elif t == "m":
                draw_text(
                    target, L, cy + MINOR_PX * s * 1.1, left, MINOR_PX * s, MINOR_C
                )
            elif t != "g":
                fill = (
                    TITLE_C
                    if t == "t"
                    else MINOR_C
                    if t == "m"
                    else LABEL_C
                    if t == "k"
                    else BODY_C
                )
                draw_text(target, x0 + PAD_X * s, base, left, px, fill, bold=(t == "t"))
                if right:
                    rw = text_width(right, px)
                    draw_text(
                        target,
                        x1 - PAD_X * s - rw,
                        base,
                        right,
                        px,
                        TITLE_C if t == "k" else fill,
                    )
            if layer is not None:
                box = (int(x0), int(cy - 2), int(x1), int(cy + lh[t] + 4))
                part = layer.crop(box)
                if BLUR_PX:
                    part = part.filter(
                        ImageFilter.GaussianBlur(BLUR_PX * s * (1 - p) / 2)
                    )
                al = part.getchannel("A").point(lambda v, k=p: int(v * k))
                part.putalpha(al)
                img.alpha_composite(part, (box[0], box[1]))
            cy += lh[t]
        y += bh + int(GAP * s)
    return img, busy


def diff_fresh(old_blocks, new_blocks, start, fresh):
    """新出现的分区：整块记下开始淡入的时间；已经在的分区读数变了直接换（玩家正盯着看的数不能糊一下）"""
    had = {b["key"] for b in old_blocks}
    keep = {}
    for b in new_blocks:
        for i, _ in enumerate(b["lines"]):
            k = (b["key"], i)
            if b["key"] not in had:
                keep[k] = start + i * STAGGER_MS / 1000
            elif k in fresh:
                keep[k] = fresh[k]
    return keep


# ================================================================ 导航记号（2026-10-27）：画在游戏画面上的目标位置 + 瞄准环
# 借鉴：游戏里的航点记号（画面外贴边画箭头）、精英危险 EDISON 的转向箭头、坎巴拉的导航球（太空里没有参考系，靠「点在环里哪边」）
MK_C = (213, 164, 90, 255)  # 琥珀金（DESIGN.md 品牌强调色）
MK_EDGE = (0, 0, 0, 200)  # 记号外面一圈黑边：雪地、亮星云上也看得清
MK_PX = 16  # 距离数字
MK_SIZE = 14  # 菱形半径
EDGE_MARGIN = 70  # 箭头离屏幕边多远
RING_R = 46  # 瞄准环半径


def _pill(draw, cx, top, text, px, plate):
    w = text_width(text, px, True) + px
    h = px * 1.5
    draw.rounded_rectangle(
        (cx - w / 2, top, cx + w / 2, top + h),
        radius=h / 2,
        fill=PLATE + (int(255 * plate_alpha(plate)),),
    )
    draw_text(
        draw,
        cx - text_width(text, px, True) / 2,
        top + h * 0.72,
        text,
        px,
        TITLE_C,
        bold=True,
    )
    return w, h


def marker_image(m, scale=1.0, plate=PLATE_ALPHA):
    """m：navigate.project 的结果加 label（距离字）。→ (图, 记号中心在图里的位置)：在画面里画菱形，画面外画指向目标的箭头"""
    from PIL import Image, ImageDraw

    s, px = MK_SIZE * scale, round(MK_PX * scale)
    W, H = (
        int(s * 2 + max(px * 7, text_width(m["label"], px, True) + px * 2)),
        int(s * 2 + px * 3 + 8),
    )
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = W / 2, s + 4
    if m.get("on"):
        pts = [(cx, cy - s), (cx + s, cy), (cx, cy + s), (cx - s, cy)]
        d.polygon(pts, outline=MK_EDGE, width=round(5 * scale))
        d.polygon(pts, outline=MK_C, width=round(3 * scale))
        d.ellipse(
            (cx - 2 * scale, cy - 2 * scale, cx + 2 * scale, cy + 2 * scale), fill=MK_C
        )
    else:
        import math

        a = math.radians(m.get("angle", 0))
        ux, uy = math.cos(a), -math.sin(a)  # 屏幕上的方向（y 向下）
        tip = (cx + ux * s, cy + uy * s)
        back = (cx - ux * s * 0.6, cy - uy * s * 0.6)
        side = (-uy * s * 0.8, ux * s * 0.8)
        pts = [
            tip,
            (back[0] + side[0], back[1] + side[1]),
            (back[0] - side[0], back[1] - side[1]),
        ]
        d.polygon(pts, fill=MK_C, outline=MK_EDGE, width=round(2 * scale))
    _pill(d, cx, cy + s + 4 * scale, m["label"], px, plate)
    return img, (cx, cy)


def ring_image(m, scale=1.0, plate=PLATE_ALPHA):
    """瞄准环：中心 = 正在看的方向；金点 = 目标在哪边，离中心越远偏得越多（外圈 = 偏 90°）；在身后画空心点贴外圈。
    下面一行字：对准了 / 偏几度 / 在身后"""
    import math
    from PIL import Image, ImageDraw

    R, px = RING_R * scale, round(15 * scale)
    W = int(R * 2 + 24 * scale)
    W2 = int(max(W, text_width("在身后：掉头", px, True) + px * 2))
    H = int(W + px * 1.5 + 4)
    img = Image.new("RGBA", (W2, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = W2 / 2, W / 2
    d.ellipse(
        (
            cx - R - 6 * scale,
            cy - R - 6 * scale,
            cx + R + 6 * scale,
            cy + R + 6 * scale,
        ),
        fill=(0, 0, 0, int(255 * plate)),
    )
    d.ellipse(
        (cx - R, cy - R, cx + R, cy + R),
        outline=(255, 255, 255, 120),
        width=max(1, round(2 * scale)),
    )
    d.ellipse(
        (cx - R / 3, cy - R / 3, cx + R / 3, cy + R / 3),
        outline=(255, 255, 255, 60),
        width=1,
    )
    d.line(
        (cx - 6 * scale, cy, cx + 6 * scale, cy),
        fill=(255, 255, 255, 200),
        width=max(1, round(2 * scale)),
    )
    d.line(
        (cx, cy - 6 * scale, cx, cy + 6 * scale),
        fill=(255, 255, 255, 200),
        width=max(1, round(2 * scale)),
    )
    off = m.get("off", 0)
    a = math.radians(m.get("angle", 0))
    rr = R * min(off, 90) / 90
    dx, dy = cx + math.cos(a) * rr, cy - math.sin(a) * rr
    k = 7 * scale
    if m.get("behind"):
        d.ellipse(
            (dx - k, dy - k, dx + k, dy + k),
            outline=MK_C,
            width=max(2, round(3 * scale)),
        )
        text = "在身后：掉头"
    else:
        d.ellipse(
            (dx - k, dy - k, dx + k, dy + k),
            fill=MK_C,
            outline=MK_EDGE,
            width=max(1, round(2 * scale)),
        )
        text = "对准了" if off < 3 else f"偏 {off:.0f}°"
    _pill(d, cx, W + 2, text, px, plate)
    return img


def edge_point(angle, w, h, margin):
    """画面外的目标：从画面中心朝 angle 方向走，停在离边 margin 的地方"""
    import math

    a = math.radians(angle)
    ux, uy = math.cos(a), -math.sin(a)
    tx = (w / 2 - margin) / abs(ux) if abs(ux) > 1e-9 else float("inf")
    ty = (h / 2 - margin) / abs(uy) if abs(uy) > 1e-9 else float("inf")
    k = min(tx, ty)
    return w / 2 + ux * k, h / 2 + uy * k


def avoid_box(x, y, w, h, area_w, area_h, box):
    """记号不能盖住右上角调试信息那块（读屏时会把自己的窗口涂黑，盖上就读不到位置了）：碰到就挪到它下面"""
    l, t, r, b = box[0] * area_w, box[1] * area_h, box[2] * area_w, box[3] * area_h  # noqa: E741
    if x < r and x + w > l and y < b and y + h > t:
        y = b + 4
    return x, y


# ================================================================ 贴到窗口上（Windows）
def _ulw(hwnd, img):
    """整张图（带透明度）贴到分层窗口上；位置不变"""
    import ctypes
    from ctypes import wintypes
    from PIL import Image, ImageChops

    u32, g32 = ctypes.windll.user32, ctypes.windll.gdi32
    vp = ctypes.c_void_p
    u32.GetDC.restype = vp
    u32.GetDC.argtypes = [vp]  # noqa: E702
    u32.ReleaseDC.argtypes = [vp, vp]
    g32.CreateCompatibleDC.restype = vp
    g32.CreateCompatibleDC.argtypes = [vp]  # noqa: E702
    g32.CreateDIBSection.restype = vp
    g32.SelectObject.restype = vp
    g32.SelectObject.argtypes = [vp, vp]  # noqa: E702
    g32.DeleteObject.argtypes = [vp]
    g32.DeleteDC.argtypes = [vp]  # noqa: E702

    class BMIH(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BLEND(ctypes.Structure):
        _fields_ = [
            ("op", ctypes.c_ubyte),
            ("flags", ctypes.c_ubyte),
            ("alpha", ctypes.c_ubyte),
            ("fmt", ctypes.c_ubyte),
        ]

    g32.CreateDIBSection.argtypes = [
        vp,
        ctypes.POINTER(BMIH),
        wintypes.UINT,
        ctypes.POINTER(vp),
        vp,
        wintypes.DWORD,
    ]
    u32.UpdateLayeredWindow.argtypes = [
        vp,
        vp,
        ctypes.POINTER(wintypes.POINT),
        ctypes.POINTER(wintypes.SIZE),
        vp,
        ctypes.POINTER(wintypes.POINT),
        wintypes.DWORD,
        ctypes.POINTER(BLEND),
        wintypes.DWORD,
    ]
    w, h = img.size
    r, g, b, a = img.split()  # 分层窗口要「预乘透明度」的 BGRA
    data = Image.merge(
        "RGBA",
        (
            ImageChops.multiply(b, a),
            ImageChops.multiply(g, a),
            ImageChops.multiply(r, a),
            a,
        ),
    ).tobytes()
    screen = u32.GetDC(None)
    mem = g32.CreateCompatibleDC(screen)
    bmi = BMIH(ctypes.sizeof(BMIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = vp()
    bmp = g32.CreateDIBSection(mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    ok = False
    try:
        if bmp and bits:
            ctypes.memmove(bits, data, len(data))
            old = g32.SelectObject(mem, bmp)
            size, src = wintypes.SIZE(w, h), wintypes.POINT(0, 0)
            ok = bool(
                u32.UpdateLayeredWindow(
                    hwnd,
                    screen,
                    None,
                    ctypes.byref(size),
                    mem,
                    ctypes.byref(src),
                    0,
                    ctypes.byref(BLEND(0, 0, 255, 1)),
                    2,
                )
            )
            g32.SelectObject(mem, old)
    finally:
        if bmp:
            g32.DeleteObject(bmp)
        g32.DeleteDC(mem)
        u32.ReleaseDC(None, screen)
    return ok


class Hud:
    def __init__(self):
        self.ok = False
        self.movable = False
        self.sections = {}
        self.rich = {}
        self.note_text = ""
        self._note_seq = 0
        self._q = queue.Queue()
        self._ready = threading.Event()
        self._blocks, self._fresh = [], {}
        self._cfg, self._cfg_at = (1.0, PLATE_ALPHA), 0.0
        if ENABLED and sys.platform == "win32":
            threading.Thread(target=self._thread, daemon=True, name="overlay").start()
            self._ready.wait(5)

    # ---------------------------------------------------------------- 对外接口（任何线程）
    def set(self, section, text, rich=None):
        """更新一个分区；text 为空就删掉这个分区。rich：有层次的内容（采矿助手），悬浮窗按它排，窗口右侧还用 text"""
        text = text or ""
        if self.sections.get(section, "") == text and self.rich.get(section) == rich:
            return
        if text:
            self.sections[section] = text
            if rich:
                self.rich[section] = rich
            else:
                self.rich.pop(section, None)
        else:
            self.sections.pop(section, None)
            self.rich.pop(section, None)
        try:
            from ..app import bus

            bus.publish("hud", {"section": section, "text": text})
        except Exception:
            pass
        if self.ok:
            self._q.put("render")

    def marker(self, data):
        """导航记号：data = {"area": (左, 上, 宽, 高) 游戏画面的屏幕像素, "proj": navigate.project 的结果, "label": 距离字}；
        None = 收起来。任何线程都能调"""
        self.mk_data = data
        if self.ok:
            self._q.put("marker")

    def clear(self, section):
        self.set(section, "")

    def note(self, text, secs=6):
        """一闪而过的提示（白色胶囊）：同时只有一条，新的顶掉旧的；secs 秒后自己消失"""
        self._note_seq += 1
        my = self._note_seq
        self.note_text = text or ""
        try:
            from ..app import bus

            bus.publish("hud", {"section": "提示", "text": self.note_text})
        except Exception:
            pass
        if self.ok:
            self._q.put("render")

        def gone():
            if self._note_seq == my:
                self.note_text = ""
                try:
                    from ..app import bus

                    bus.publish("hud", {"section": "提示", "text": ""})
                except Exception:
                    pass
                if self.ok:
                    self._q.put("render")

        t = threading.Timer(secs, gone)
        t.daemon = True
        t.start()

    def hide(self):
        if self.ok:
            self._q.put("hide")

    def restyle(self):
        if self.ok:
            self._q.put("restyle")

    def pump(self):
        """兼容旧代码：悬浮窗现在自己刷新，这里什么都不用做"""

    def sleep(self, seconds):
        time.sleep(seconds)

    def set_movable(self, on):
        if self.ok:
            self._q.put("move_on" if on else "move_off")

    # ---------------------------------------------------------------- 悬浮窗线程
    def _thread(self):
        try:
            import ctypes

            try:  # 这个线程按物理像素算（2K、4K 屏不被系统放大糊掉）
                ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
            except Exception:
                pass
            import tkinter as tk

            self.tk = tk
            self.root = tk.Tk()
            self.root.title(
                "AT 悬浮窗"
            )  # 和主窗口「天枢 Dubhe」区分开（找主窗口时按标题找）
            self.root.overrideredirect(True)
            self.root.attributes("-topmost", True)
            self.root.configure(bg="black")
            x, y = self._load_pos()
            self.root.geometry(f"1x1+{x}+{y}")
            self.root.bind(
                "<ButtonPress-1>", self._press
            )  # 只有「移动悬浮窗」打开时才收得到鼠标
            self.root.bind("<B1-Motion>", self._drag)
            self.root.bind("<ButtonRelease-1>", lambda e: self._save_pos())
            self.root.update()
            self._remember_hwnd()
            self.movable = False
            self._apply_style()
            from PIL import Image

            if not HWND or not _ulw(HWND, Image.new("RGBA", (1, 1), (0, 0, 0, 0))):
                raise RuntimeError("UpdateLayeredWindow")
            self.ok = True
            try:  # 导航记号的两个小窗口启动时就建好：Tk 第一次显示新窗口可能激活它，
                self._mk_window()  # 以前第一次出记号时（正在游戏里）才建，可能抢一次焦点（S2 审查 2026-10-31）
            except Exception:
                pass
        except Exception:
            self.ok = False
            self._ready.set()
            return
        self._ready.set()
        self.root.after(100, self._tick)
        try:
            self.root.mainloop()
        except Exception:
            self.ok = False

    def _settings(self):
        if time.time() - self._cfg_at > 2:
            self._cfg_at = time.time()
            try:
                from ..core import settings

                c = settings.load()
                self._cfg = (
                    max(0.5, min(1.0, float(c.get("hud_scale", 1.0)))),
                    max(0.3, min(1.0, float(c.get("hud_plate", PLATE_ALPHA)))),
                )
                use_palette(c.get("hud_theme") or "默认")
            except Exception:
                pass
        return self._cfg

    def _scale(self):
        try:
            import ctypes

            h = ctypes.windll.user32.GetSystemMetrics(1)
        except Exception:
            h = 1080
        return max(0.75, h / 1080) * self._settings()[0]

    def _tick(self):
        dirty = False
        try:
            while True:
                cmd = self._q.get_nowait()
                if cmd == "render":
                    dirty = True
                elif cmd == "hide":
                    self._push(None)
                elif cmd == "marker":
                    self._marker_render()
                elif (
                    cmd == "restyle"
                ):  # 设置页换了配色 / 底板 / 大小：马上按新设置重画（二审 2026-10-27）
                    self._cfg_at = 0.0
                    dirty = True
                    if getattr(
                        self, "_mk", None
                    ):  # 正在显示导航记号才重画（没有就别建窗口）
                        self._marker_render()
                elif cmd in ("move_on", "move_off"):
                    self.movable = cmd == "move_on"
                    self._apply_style()
                    dirty = True
        except queue.Empty:
            pass
        busy = False
        try:
            if dirty or self._fresh:
                busy = self._render(changed=dirty)
        except Exception as e:  # 某一帧画错了：记一次日志、跳过这帧，悬浮窗照常继续刷新
            self._fresh = {}
            sig = f"{type(e).__name__}: {e}"
            if sig != getattr(self, "_last_err", None):
                self._last_err = sig
                import traceback

                traceback.print_exc()
        self.root.after(30 if busy else 100, self._tick)

    def _mk_window(self):
        """导航记号用的两个小窗口（记号、瞄准环）：和悬浮窗一样点不中、不抢焦点、不进任务栏"""
        if getattr(self, "_mk", None):
            return self._mk
        import ctypes

        u32 = ctypes.windll.user32
        get = getattr(u32, "GetWindowLongPtrW", u32.GetWindowLongW)
        put = getattr(u32, "SetWindowLongPtrW", u32.SetWindowLongW)
        hwnds = []
        for _ in range(2):
            w = self.tk.Toplevel(self.root)
            w.overrideredirect(True)
            w.attributes("-topmost", True)
            w.geometry("1x1+0+0")
            w.update()
            h = u32.GetAncestor(w.winfo_id(), 2)
            ex = (
                get(h, GWL_EXSTYLE)
                | WS_EX_LAYERED
                | WS_EX_TOOLWINDOW
                | WS_EX_NOACTIVATE
                | WS_EX_TOPMOST
                | WS_EX_TRANSPARENT
            )
            put(h, GWL_EXSTYLE, ex)
            hwnds.append((w, h))
        self._mk = hwnds
        return hwnds

    def _mk_put(self, h, img, x, y):
        import ctypes
        from PIL import Image

        if img is None:
            _ulw(h, Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
            return
        ctypes.windll.user32.SetWindowPos(
            ctypes.c_void_p(h),
            ctypes.c_void_p(-1),
            int(x),
            int(y),
            0,
            0,
            SWP_NOSIZE | SWP_NOACTIVATE,
        )
        _ulw(h, img)

    def _marker_render(self):
        try:
            (_, h1), (_, h2) = self._mk_window()
        except Exception:
            return
        data = getattr(self, "mk_data", None)
        if not data:
            self._mk_put(h1, None, 0, 0)
            self._mk_put(h2, None, 0, 0)
            return
        try:
            from ..navigation.displayinfo import REGION

            left, top, w, h = data["area"]
            m = dict(data["proj"], label=data["label"])
            scale = max(0.75, h / 1080) * self._settings()[0]
            plate = self._settings()[1]
            img, (ax, ay) = marker_image(m, scale, plate)
            if m.get("on"):
                px, py = m["x"], m["y"]
            else:
                px, py = edge_point(m.get("angle", 0), w, h, EDGE_MARGIN * scale)
            x, y = px - ax, py - ay
            x, y = avoid_box(x, y, img.width, img.height, w, h, REGION)
            self._mk_put(h1, img, left + x, top + y)
            ring = ring_image(m, scale, plate)
            self._mk_put(h2, ring, left + w / 2 - ring.width / 2, top + h * 0.72)
        except Exception:
            self._mk_put(h1, None, 0, 0)
            self._mk_put(h2, None, 0, 0)

    def _render(self, changed=True):
        scale = self._scale()
        sections = dict(self.sections)
        if changed:
            blocks = layout(sections, scale, dict(self.rich))
            self._fresh = diff_fresh(self._blocks, blocks, time.time(), self._fresh)
            self._blocks = blocks
        img, busy = paint(
            sections,
            self.note_text,
            self.movable,
            scale,
            self._settings()[1],
            self._fresh,
            rich=dict(self.rich),
        )
        if not busy:
            self._fresh = {}
        empty = not (sections or self.note_text or self.movable)
        self._push(None if empty else img)
        return busy

    def _push(self, img):
        global SHOWN
        from PIL import Image

        SHOWN = img is not None
        try:
            if img is not None and not self.movable:
                self._avoid_di(img)
            _ulw(
                HWND,
                img if img is not None else Image.new("RGBA", (1, 1), (0, 0, 0, 0)),
            )
            if img is not None:
                self._topmost()
        except Exception:
            pass

    def _avoid_di(self, img):
        """悬浮窗不能盖住游戏右上角的调试信息那块：AT 读屏时会把悬浮窗那块涂黑，盖上就读不到位置
        （2026-10-28 用户反馈「读不到位置」，F10 截图里右上角整块是黑的）。盖到了就挪到它下面，和导航记号一样"""
        try:
            import ctypes
            from ..navigation.displayinfo import REGION

            try:
                from ..core.perf import game_area

                a = game_area()
                left, top, w, h = a["left"], a["top"], a["width"], a["height"]
            except Exception:
                left, top = 0, 0
                w, h = (
                    ctypes.windll.user32.GetSystemMetrics(0),
                    ctypes.windll.user32.GetSystemMetrics(1),
                )
            x, y = self._rect()
            nx, ny = avoid_box(x - left, y - top, img.width, img.height, w, h, REGION)
            if (nx, ny) != (x - left, y - top):
                ctypes.windll.user32.SetWindowPos(
                    ctypes.c_void_p(HWND),
                    None,
                    int(left + nx),
                    int(top + ny),
                    0,
                    0,
                    SWP_NOSIZE | SWP_NOACTIVATE,
                )
        except Exception:
            pass

    def _topmost(self):
        """放到最上层，但不激活（不抢游戏的焦点）"""
        try:
            import ctypes

            if HWND:
                ctypes.windll.user32.SetWindowPos(
                    ctypes.c_void_p(HWND),
                    ctypes.c_void_p(-1),
                    0,
                    0,
                    0,
                    0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
                )
        except Exception:
            pass

    def _apply_style(self):
        """鼠标穿透 + 永不激活 + 不在任务栏/Alt+Tab 里出现；「移动悬浮窗」打开时去掉穿透，才拖得动"""
        try:
            import ctypes

            if not HWND:
                return
            u32 = ctypes.windll.user32
            get = getattr(u32, "GetWindowLongPtrW", u32.GetWindowLongW)
            put = getattr(u32, "SetWindowLongPtrW", u32.SetWindowLongW)
            ex = (
                get(HWND, GWL_EXSTYLE)
                | WS_EX_LAYERED
                | WS_EX_TOOLWINDOW
                | WS_EX_NOACTIVATE
                | WS_EX_TOPMOST
            )
            ex = ex & ~WS_EX_TRANSPARENT if self.movable else ex | WS_EX_TRANSPARENT
            put(HWND, GWL_EXSTYLE, ex)
            u32.SetWindowPos(
                HWND,
                -1,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )
        except Exception:
            pass

    # ---- 位置（拖动用 SetWindowPos 只挪位置：用 Tk 的 geometry 会把窗口大小改回 Tk 自己记的大小）
    def _rect(self):
        import ctypes
        from ctypes import wintypes

        r = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(ctypes.c_void_p(HWND), ctypes.byref(r))
        return r.left, r.top

    def _load_pos(self):
        try:
            p = json.loads(POS_FILE.read_text(encoding="utf-8"))
            return int(p["x"]), int(p["y"])
        except Exception:
            try:
                import ctypes

                sw = ctypes.windll.user32.GetSystemMetrics(0)
                sh = ctypes.windll.user32.GetSystemMetrics(1)
            except Exception:
                sw, sh = self.root.winfo_screenwidth(), 1080
            s = max(0.75, sh / 1080)
            return int(sw - BASE_W * s - 48 * s), int(32 * s)

    def _save_pos(self):
        try:
            x, y = self._rect()
            from ..core.paths import write_json

            write_json(POS_FILE, {"x": x, "y": y})
        except Exception:
            pass

    def _press(self, e):
        x, y = self._rect()
        self._off = (e.x_root - x, e.y_root - y)

    def _drag(self, e):
        try:
            import ctypes

            ctypes.windll.user32.SetWindowPos(
                ctypes.c_void_p(HWND),
                None,
                e.x_root - self._off[0],
                e.y_root - self._off[1],
                0,
                0,
                SWP_NOSIZE | SWP_NOACTIVATE,
            )
        except Exception:
            pass

    def _remember_hwnd(self):
        """记下悬浮窗的窗口句柄：AT 自己截图读屏时把悬浮窗那块涂黑（perf.mask_overlay），就不会读到悬浮窗上的字。
        以前用的是「截屏时隐藏这个窗口」，但英伟达录屏会把它当成受保护内容、直接停止录制，所以不用了"""
        global HWND
        try:
            import ctypes

            HWND = ctypes.windll.user32.GetAncestor(self.root.winfo_id(), 2)  # GA_ROOT
        except Exception:
            HWND = None


def hud():
    global _hud
    with _hud_lock:
        if _hud is None:
            _hud = Hud()
    return _hud
