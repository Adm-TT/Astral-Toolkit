"""游戏上方的悬浮窗（所有功能共用）

各功能往自己的分区写字：hud().set("扫描", "第一行是标题\\n下面是内容")，悬浮窗把各分区叠起来显示，
同样的内容也会实时出现在助手窗口右侧。一闪而过的提示用 hud().note("…", 秒)：白色胶囊，同时只有一条。
- 游戏要用「无边框窗口」模式才看得到悬浮窗（全屏模式下会被游戏盖住）
- 文案窗鼠标穿透、永远不抢焦点：点到它操作直接给游戏
- 外框锁在游戏客户区中上带（宽 30%–70%、高顶部 0%–20%）；内容超出可滑动，默认钉底
- 功能往悬浮窗写字时显示文案窗与左上角手柄；之后 10 秒内无写字、无手柄操作则自动隐藏（内容仍留着，下次再写会再显示）
- 左上角独立小手柄窗：长按拖动改位置（写入 overlay_pos.json）；在手柄上滚轮滑动内容
- 导航菱形 / 瞄准环仍是另两扇独立窗口
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
BASE_W = 400  # 单列卡片参考宽（横排时单卡不超过此宽×scale）
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

# 文案视口相对游戏客户区（2026-11-08）
BAND_X0, BAND_X1 = 0.30, 0.70
BAND_Y0, BAND_Y1 = 0.0, 0.20
GRIP_HOLD_MS = 300
GRIP_BASE_PX = 28  # 手柄边长（再乘 hud 字号 scale）
IDLE_HIDE_SECS = 10.0  # 显示后多久无操作则自动隐藏


def band_size(area_w: int, area_h: int) -> tuple[int, int]:
    """客户区 → 文案视口像素宽高"""
    w = max(1, int(round(area_w * (BAND_X1 - BAND_X0))))
    h = max(1, int(round(area_h * (BAND_Y1 - BAND_Y0))))
    return w, h


def band_origin(area: dict) -> tuple[int, int]:
    """客户区字典 → 视口左上角屏幕坐标"""
    return (
        int(area["left"] + area["width"] * BAND_X0),
        int(area["top"] + area["height"] * BAND_Y0),
    )


def clamp_scroll_from_bottom(scroll: float, content_h: int, view_h: int) -> float:
    """距底部的滚动偏移：0 = 钉底；上限 = 内容比视口多出的高度"""
    max_up = max(0, int(content_h) - int(view_h))
    return max(0.0, min(float(scroll), float(max_up)))

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
# 2026-10-27 负责人：保留现有（默认）、再加两套。设置 hud_theme 选
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


def layout(sections, scale, rich=None, content_width=None):
    """分区 → 要画的块：[{key, label, lines: [(种类, 文字, 右边文字)]}]。
    种类：t 标题、s 关键读数（几格）、b 正文、k 左名右值、m 次要（灰）、g 组间留白。
    content_width：单卡正文可用宽（不含左右 padding）；默认按 BASE_W。"""
    width = (
        content_width
        if content_width is not None
        else (BASE_W - 2 * PAD_X) * scale
    )
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


def _line_heights(scale):
    s = scale
    return {
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


def paint(
    sections,
    note="",
    scale=1.0,
    plate=PLATE_ALPHA,
    fresh=None,
    now=None,
    rich=None,
    viewport_w=None,
    viewport_h=None,
    scroll_from_bottom=0.0,
):
    """画出文案视口。viewport 固定；正文可更高，按 scroll_from_bottom 裁进视口（0=钉底）。
    note 固定画在视口底部。返回 (图, 还在动画吗, 正文内容高)。"""
    from PIL import Image, ImageDraw, ImageFilter

    s = scale
    vw = int(viewport_w or (BASE_W * s + 2 * MARGIN))
    vh = int(viewport_h or max(1, int(vw * 0.5)))
    card_inner = min((BASE_W - 2 * PAD_X) * s, max(40.0, vw - 2 * MARGIN - 2 * PAD_X * s))
    blocks = layout(sections, s, rich, content_width=card_inner)
    note = clean(note)
    lh = _line_heights(s)
    heights = []
    for b in blocks:
        bh = (
            PAD_T * s
            + LABEL_PX * s * 1.6
            + sum(lh[t] for t, _, _ in b["lines"])
            + PAD_B * s
        )
        heights.append(int(bh))
    card_w = int(card_inner + 2 * PAD_X * s)
    # 横排：卡片从左到右，一行放不下换行
    places = []  # (b, bh, x, y)
    x = MARGIN
    y = MARGIN
    row_h = 0
    for b, bh in zip(blocks, heights):
        if x > MARGIN and x + card_w > vw - MARGIN:
            x = MARGIN
            y += row_h + int(GAP * s)
            row_h = 0
        places.append((b, bh, x, y))
        x += card_w + int(GAP * s)
        row_h = max(row_h, bh)
    content_h = (
        int(y + row_h + MARGIN)
        if places
        else MARGIN
    )
    content_h = max(1, content_h)
    body = Image.new("RGBA", (vw, content_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(body)
    now = time.time() if now is None else now
    fresh = fresh or {}
    busy = False
    plate_a = int(255 * plate_alpha(plate))
    for b, bh, x0, y0 in places:
        x1 = x0 + card_w - 1
        d.rounded_rectangle(
            (x0, y0, x1, y0 + bh),
            radius=RADIUS * s,
            fill=PLATE + (plate_a,),
            outline=EDGE,
            width=max(1, int(s)),
        )
        ly = y0 + PAD_T * s + LABEL_PX * s * 1.05
        draw_text(d, x0 + PAD_X * s, ly, b["label"], LABEL_PX * s, LABEL_C)
        cy = y0 + PAD_T * s + LABEL_PX * s * 1.6
        for i, (t, left, right) in enumerate(b["lines"]):
            px = (TITLE_PX if t == "t" else BODY_PX) * s
            base = cy + px * (1.08 if t == "t" else 1.12)
            started = fresh.get((b["key"], i))
            p = 1.0 if started is None else (now - started) * 1000 / FADE_MS
            target = d
            layer = None
            if 0 <= p < 1:
                busy = True
                layer = Image.new("RGBA", body.size, (0, 0, 0, 0))
                target = ImageDraw.Draw(layer)
            elif p < 0:
                busy = True
                cy += lh[t]
                continue
            L, R = x0 + PAD_X * s, x1 - PAD_X * s
            if t in ("s", "G"):
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
            elif t == "d":
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
                if right:
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
            elif t == "c":
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
            elif t == "q":
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
            elif t == "a":
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
                body.alpha_composite(part, (box[0], box[1]))
            cy += lh[t]

    scroll = clamp_scroll_from_bottom(scroll_from_bottom, content_h, vh)
    # 钉底：src_y 使内容下端对齐视口下端，再往上滚 scroll
    src_y = max(0, content_h - vh - int(scroll))
    img = Image.new("RGBA", (vw, vh), (0, 0, 0, 0))
    crop = body.crop((0, src_y, vw, min(content_h, src_y + vh)))
    img.alpha_composite(crop, (0, 0))
    if note:
        note_lines = wrap(note, NOTE_PX * s, max(40.0, vw - 40 * s))
        nw = max(text_width(l, NOTE_PX * s) for l in note_lines) + 40 * s  # noqa: E741
        nh = len(note_lines) * NOTE_PX * s * 1.45 + 20 * s
        nd = ImageDraw.Draw(img)
        nx = vw - MARGIN - nw
        ny = vh - MARGIN - nh
        nd.rounded_rectangle(
            (nx, ny, vw - MARGIN - 1, ny + nh),
            radius=min(nh / 2, 32 * s),
            fill=NOTE_BG,
        )
        by = ny + 10 * s + NOTE_PX * s * 1.08
        for l in note_lines:  # noqa: E741
            draw_text(nd, nx + 20 * s, by, l, NOTE_PX * s, NOTE_C)
            by += NOTE_PX * s * 1.45
    return img, busy, content_h


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
        self.sections = {}
        self.rich = {}
        self.note_text = ""
        self._note_seq = 0
        self._q = queue.Queue()
        self._ready = threading.Event()
        self._blocks, self._fresh = [], {}
        self._cfg, self._cfg_at = (1.0, PLATE_ALPHA), 0.0
        self._fps = 5  # 导航帧数：记号显示着时悬浮窗按它加快（跟设置走，两秒读一次；设置页改了收到 restyle 马上重读）
        self.scroll_from_bottom = 0.0  # 距内容底部的偏移；0 = 钉底
        self._content_h = 1
        self._view_h = 1
        self._grip = None  # (tk_win, hwnd)
        self._grip_press_at = 0.0
        self._grip_dragging = False
        self._off = (0, 0)
        self._visible = False  # 屏幕上是否正在显示文案窗/手柄
        self._last_op_at = 0.0  # 最近一次写字或手柄操作
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
        self._on_content_change(activity=True)
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
        self._on_content_change(activity=True)
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
                # 提示到期不算「操作」：若已空闲隐藏就别因为清 note 再弹出来
                self._on_content_change(activity=False)
                if self.ok:
                    self._q.put("render")

        t = threading.Timer(secs, gone)
        t.daemon = True
        t.start()

    def hide(self):
        if self.ok:
            self._q.put("hide")

    def _on_content_change(self, *, activity: bool):
        """activity=True：写字/开功能 → 显示并刷新空闲计时；全部清空 → 立刻隐藏。
        activity=False：仅同步「空了就藏」（如 note 到期），不主动重新显示。"""
        if not self._has_text():
            self._visible = False
            return
        if activity:
            self._visible = True
            self._last_op_at = time.time()

    def _bump_op(self):
        """手柄拖动 / 滚轮：算作用户操作，延长显示"""
        if not self._has_text():
            return
        self._visible = True
        self._last_op_at = time.time()

    def restyle(self):
        if self.ok:
            self._q.put("restyle")

    def sleep(self, seconds):
        time.sleep(seconds)

    def scroll_by(self, delta: float):
        """正文相对视口滚动（正数往上看更早内容）。任何线程可调；手柄滚轮走队列。"""
        if self.ok:
            self._q.put(("scroll", float(delta)))

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
            )  # 和主窗口「AT 星际公民助手」区分开（找主窗口时按标题找）
            self.root.overrideredirect(True)
            self.root.attributes("-topmost", True)
            self.root.configure(bg="black")
            x, y = self._load_pos()
            self.root.geometry(f"1x1+{x}+{y}")
            self.root.update()
            self._remember_hwnd()
            self._apply_style()
            from PIL import Image

            if not HWND or not _ulw(HWND, Image.new("RGBA", (1, 1), (0, 0, 0, 0))):
                raise RuntimeError("UpdateLayeredWindow")
            self.ok = True
            try:
                self._mk_window()
            except Exception:
                pass
            try:
                self._grip_window()
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
                self._fps = settings.nav_fps(c.get("nav_fps"))
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
        mk = False
        try:
            while True:
                cmd = self._q.get_nowait()
                if cmd == "render":
                    dirty = True
                elif cmd == "hide":
                    self._visible = False
                    self._push(None)
                    self._grip_sync()
                elif cmd == "marker":
                    mk = True
                elif cmd == "restyle":
                    self._cfg_at = 0.0
                    dirty = True
                    if getattr(self, "_mk", None):
                        mk = True
                elif isinstance(cmd, tuple) and cmd and cmd[0] == "scroll":
                    self._bump_op()
                    self.scroll_from_bottom = clamp_scroll_from_bottom(
                        self.scroll_from_bottom + cmd[1],
                        self._content_h,
                        self._view_h,
                    )
                    dirty = True
        except queue.Empty:
            pass
        # 显示中且超时无操作 → 自动隐藏（分区文字仍保留，下次写字再出）
        if (
            self._visible
            and self._has_text()
            and self._last_op_at
            and time.time() - self._last_op_at >= IDLE_HIDE_SECS
        ):
            self._visible = False
            dirty = True
        if mk:
            self._marker_render()
        busy = False
        try:
            if dirty or self._fresh:
                busy = self._render(changed=dirty)
        except Exception as e:
            self._fresh = {}
            sig = f"{type(e).__name__}: {e}"
            if sig != getattr(self, "_last_err", None):
                self._last_err = sig
                import traceback

                traceback.print_exc()
        self.root.after(self._next_ms(busy), self._tick)

    def _next_ms(self, busy):
        """下一圈隔多久（毫秒）：平时 100、有动画 30；导航记号显示着时按导航帧数加快，读数间隔的一半（5 帧时还是 100）"""
        ms = 30 if busy else 100
        if getattr(self, "mk_data", None):
            self._settings()
            ms = min(ms, max(1, int(500 / max(1, self._fps))))
        return ms

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

    def _viewport_px(self):
        """当前文案视口宽高（游戏客户区中上带；找不到游戏则按屏高估算）"""
        try:
            from ..core.capture import game_area, game_size

            a = game_area()
            if game_size() is not None:
                return band_size(a["width"], a["height"])
            return band_size(a["width"], a["height"])
        except Exception:
            try:
                import ctypes

                sw = ctypes.windll.user32.GetSystemMetrics(0)
                sh = ctypes.windll.user32.GetSystemMetrics(1)
            except Exception:
                sw, sh = 1920, 1080
            return band_size(sw, sh)

    def _render(self, changed=True):
        scale = self._scale()
        sections = dict(self.sections)
        vw, vh = self._viewport_px()
        self._view_h = vh
        card_inner = min(
            (BASE_W - 2 * PAD_X) * scale, max(40.0, vw - 2 * MARGIN - 2 * PAD_X * scale)
        )
        if changed:
            blocks = layout(sections, scale, dict(self.rich), content_width=card_inner)
            self._fresh = diff_fresh(self._blocks, blocks, time.time(), self._fresh)
            self._blocks = blocks
        img, busy, content_h = paint(
            sections,
            self.note_text,
            scale,
            self._settings()[1],
            self._fresh,
            rich=dict(self.rich),
            viewport_w=vw,
            viewport_h=vh,
            scroll_from_bottom=self.scroll_from_bottom,
        )
        self._content_h = content_h
        self.scroll_from_bottom = clamp_scroll_from_bottom(
            self.scroll_from_bottom, content_h, vh
        )
        if not busy:
            self._fresh = {}
        # 无文案，或已空闲隐藏：屏幕上不画（分区数据可仍在）
        if not self._visible or not self._has_text():
            self._push(None)
            self._grip_sync()
            return False
        self._push(img)
        self._grip_sync()
        return busy

    def _push(self, img):
        global SHOWN
        from PIL import Image

        SHOWN = img is not None
        try:
            if img is not None:
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
                from ..core.capture import game_area

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
        """文案窗：鼠标穿透 + 永不激活 + 不在任务栏/Alt+Tab；拖动只走左上角手柄窗"""
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
                | WS_EX_TRANSPARENT
            )
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
                from ..core.capture import game_area, game_size

                a = game_area()
                if game_size() is not None:
                    return band_origin(a)
            except Exception:
                pass
            try:
                import ctypes

                sw = ctypes.windll.user32.GetSystemMetrics(0)
                sh = ctypes.windll.user32.GetSystemMetrics(1)
            except Exception:
                sw, sh = 1920, 1080
            return band_origin(
                {"left": 0, "top": 0, "width": sw, "height": sh}
            )

    def _save_pos(self):
        try:
            x, y = self._rect()
            from ..core.paths import write_json

            write_json(POS_FILE, {"x": x, "y": y})
        except Exception:
            pass

    def _has_text(self) -> bool:
        """内存里是否还有分区文案或短提示（与屏幕上是否可见无关）"""
        return bool(self.sections or self.note_text)

    def _drawn(self) -> bool:
        """此刻是否该画在屏幕上：有文案且处于显示期（未空闲隐藏）"""
        return self._visible and self._has_text()

    def _grip_px(self):
        return max(20, int(round(GRIP_BASE_PX * self._scale())))

    def _grip_image(self, size):
        """六点握把图标"""
        from PIL import Image, ImageDraw

        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        pad = max(2, size // 10)
        d.rounded_rectangle(
            (0, 0, size - 1, size - 1),
            radius=max(3, size // 6),
            fill=PLATE + (int(255 * plate_alpha(self._settings()[1])),),
            outline=EDGE,
            width=1,
        )
        r = max(1, size // 14)
        gap = (size - 2 * pad) / 4
        for i in range(3):
            for j in range(2):
                cx = pad + gap + i * gap
                cy = pad + gap * (0.8 + j * 1.4)
                d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=LABEL_C)
        return img

    def _grip_window(self):
        """左上角手柄：不穿透，可长按拖主窗、滚轮滑正文。无文案时保持隐藏。"""
        if self._grip is not None:
            return self._grip
        import ctypes

        u32 = ctypes.windll.user32
        get = getattr(u32, "GetWindowLongPtrW", u32.GetWindowLongW)
        put = getattr(u32, "SetWindowLongPtrW", u32.SetWindowLongW)
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
        )
        ex = ex & ~WS_EX_TRANSPARENT
        put(h, GWL_EXSTYLE, ex)
        w.bind("<ButtonPress-1>", self._grip_press)
        w.bind("<B1-Motion>", self._grip_drag)
        w.bind("<ButtonRelease-1>", self._grip_release)
        w.bind("<MouseWheel>", self._grip_wheel)
        self._grip = (w, h)
        self._grip_sync()
        return self._grip

    def _grip_sync(self):
        """有文案才画手柄；空闲时 1×1 全透明，不挡屏幕。"""
        if not self._grip or not HWND:
            return
        try:
            import ctypes
            from PIL import Image

            _, h = self._grip
            if not self._drawn():
                ctypes.windll.user32.SetWindowPos(
                    ctypes.c_void_p(h),
                    None,
                    0,
                    0,
                    1,
                    1,
                    SWP_NOACTIVATE,
                )
                _ulw(h, Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
                return
            sz = self._grip_px()
            x, y = self._rect()
            img = self._grip_image(sz)
            if img.size != (sz, sz):
                img = img.resize((sz, sz), Image.Resampling.LANCZOS)
            ctypes.windll.user32.SetWindowPos(
                ctypes.c_void_p(h),
                ctypes.c_void_p(-1),
                int(x),
                int(y),
                int(sz),
                int(sz),
                SWP_NOACTIVATE,
            )
            _ulw(h, img)
        except Exception:
            pass

    def _grip_press(self, e):
        if not self._drawn():
            return
        self._bump_op()
        self._grip_press_at = time.time()
        self._grip_dragging = False
        x, y = self._rect()
        self._off = (e.x_root - x, e.y_root - y)

    def _grip_drag(self, e):
        if not self._drawn():
            return
        if not self._grip_dragging:
            if (time.time() - self._grip_press_at) * 1000 < GRIP_HOLD_MS:
                return
            self._grip_dragging = True
            self._bump_op()
        try:
            import ctypes

            nx = e.x_root - self._off[0]
            ny = e.y_root - self._off[1]
            ctypes.windll.user32.SetWindowPos(
                ctypes.c_void_p(HWND),
                None,
                int(nx),
                int(ny),
                0,
                0,
                SWP_NOSIZE | SWP_NOACTIVATE,
            )
            self._grip_sync()
        except Exception:
            pass

    def _grip_release(self, e):
        if self._grip_dragging:
            self._save_pos()
            self._bump_op()
        self._grip_dragging = False
        self._grip_press_at = 0.0

    def _grip_wheel(self, e):
        if not self._drawn():
            return
        self._bump_op()
        # Windows：delta 为正向上滚 → 看更早内容（增大距底偏移）
        step = max(24, self._view_h // 8)
        delta = step if getattr(e, "delta", 0) > 0 else -step
        self.scroll_from_bottom = clamp_scroll_from_bottom(
            self.scroll_from_bottom + delta, self._content_h, self._view_h
        )
        if self.ok:
            self._q.put("render")

    def _remember_hwnd(self):
        """记下悬浮窗的窗口句柄：AT 自己截图读屏时把悬浮窗那块涂黑（capture.mask_overlay），就不会读到悬浮窗上的字。
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
