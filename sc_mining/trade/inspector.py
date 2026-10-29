"""物品视觉识别组件 (Item Inspector)

专职负责游戏内鼠标悬停时物品格与说明框（Tooltip）的视觉特征提取与结构化解析：
1. 鼠标横向位置自适应分级识别区域划分 (get_hover_regions)；
2. 物品说明框 OCR 与名称提取 (_read_tooltip)；
3. 品质提取 (tooltip_quality, tooltip_row, cell_labels, parse_qlabel)；
4. 数量与 SCU 容积解析 (parse_count, tooltip_row)；
5. 蓝图制造品各槽位品质逆向反推；
6. 结构化汇总接口 (inspect_item)，供 F8 物品查询与 F6 仓库盘点共同复用。
"""
import re
from typing import Any, Dict, List, Optional, Tuple

# 物品说明框识别区域配置：按鼠标横向位置自适应分级识别
# 纵向覆盖 0.0 ~ 1.0 全高
HOVER_REGIONS: Dict[str, Tuple[float, float, float, float]] = {
    "30-50%": (0.30, 0.0, 0.50, 1.0),
    "50-70%": (0.50, 0.0, 0.70, 1.0),
    "30-70%": (0.30, 0.0, 0.70, 1.0),
    "中间": (0.30, 0.0, 0.70, 1.0),
    "整屏": (0.0, 0.0, 1.0, 1.0),
}
HOVER_REGION = HOVER_REGIONS["中间"]

_AMOUNT = re.compile(r"^(\d+(?:[.,]\d+)?)\s*[S5]\s*C\s*U$", re.I)


def get_hover_regions(cursor: Optional[Tuple[int, int]], width: int) -> List[Tuple[float, float, float, float, str]]:
    """根据鼠标横向位置返回识别区域列表：[(left, top, right, bottom, name), ...]
    识别都是按照从左向右，从上到下不考虑（全高 0%~100%）。
    - 鼠标在 0-30%: 首选 30%-50%，失败备选 30%-70%
    - 鼠标在 30%-50%: 首选 50%-70%，失败备选 30%-70%
    - 鼠标在 50%-70%: 首选 30%-50%，失败备选 30%-70%
    - 鼠标在 70%-100%: 首选 50%-70%，失败备选 30%-70%
    - 鼠标异常(None或越界): 首选中间 30%-70%
    """
    if cursor is None or cursor[0] is None or not width or width <= 0:
        l, t, r, b = HOVER_REGIONS["中间"]
        return [(l, t, r, b, "中间")]
    rx = cursor[0] / width
    if rx < 0.0 or rx > 1.0:
        l, t, r, b = HOVER_REGIONS["中间"]
        return [(l, t, r, b, "中间")]

    mid_l, mid_t, mid_r, mid_b = HOVER_REGIONS["30-70%"]
    fallback_region = (mid_l, mid_t, mid_r, mid_b, "30-70%")

    if rx < 0.30:
        l, t, r, b = HOVER_REGIONS["30-50%"]
        return [(l, t, r, b, "30-50%"), fallback_region]
    elif rx < 0.50:
        l, t, r, b = HOVER_REGIONS["50-70%"]
        return [(l, t, r, b, "50-70%"), fallback_region]
    elif rx < 0.70:
        l, t, r, b = HOVER_REGIONS["30-50%"]
        return [(l, t, r, b, "30-50%"), fallback_region]
    else:
        l, t, r, b = HOVER_REGIONS["50-70%"]
        return [(l, t, r, b, "50-70%"), fallback_region]


def _read_tooltip(img, cursor):
    """→ (文字, (中文名, 英文名) 或 None, 认的范围)
    识别机制：
    1. 按照从左向右，从上到下不考虑（全高 0%~100%）。
    2. 先确定鼠标位置，按 0~30%、30%~50%、50%~70%、70%~100% 匹配首选区域。
    3. 首选区域未成功识别，再尝试 30%~70% 中间区域。
    4. 均未命中时，使用全屏兜底。
    5. 鼠标位置异常则直接尝试中间 30%~70%，失败后再全屏兜底。
    """
    from . import console as C
    from .ocr import recognize
    W, H = img.size
    regions = get_hover_regions(cursor, W)
    best_candidate = None

    for l, t, r, b, label in regions:
        box = (int(W * l), int(H * t), int(W * r), int(H * b))
        tokens = recognize(img.crop(box), urgent=True, offset=box[:2])
        name, sure = C.tooltip_pick(tokens, cursor, img)
        if name and sure:
            return tokens, name, label
        if name and C.plausible_name(*name) and not best_candidate:
            best_candidate = (tokens, name, label)

    # 都不行的时候全屏兜底
    full = recognize(img, urgent=True)
    name_full, sure_full = C.tooltip_pick(full, cursor, img)
    if name_full and sure_full:
        return full, name_full, "整屏"
    if best_candidate:
        return best_candidate
    if name_full and C.plausible_name(*name_full):
        return full, name_full, "整屏"
    return full, None, "整屏"


def tooltip_quality(tokens):
    """说明框里的品质：「品质：650」「品质 650」「Quality: 650」「Q650」→ 650；没有返回 None"""
    for t in sorted(tokens or [], key=lambda k: (k.box[1], k.box[0])):
        m = re.search(r"(?:品质|品貭|晶质|Quality)\s*[:：]?\s*(\d{1,4})", t.text, re.I) or re.fullmatch(r"\s*Q\s*(\d{3,4})\s*", t.text)
        if m and 0 <= int(m.group(1)) <= 1000:
            return int(m.group(1))
    return None


def tooltip_row(tokens):
    """说明框里的内容行「塔兰导电石Taranite｜925｜0.495 SCU」→ (品质, 数量 SCU)；没有返回 (None, None)。
    品质是数量左边、同一行最近的那个 0–1000 的整数；
    「容量：1.00SCU」是箱子能装多少，不算"""
    toks = list(tokens or [])
    for a in sorted(toks, key=lambda k: (k.box[1], k.box[0])):
        t = a.text.replace(" ", "")
        if "容量" in t or "体积" in t:
            continue
        m = _AMOUNT.match(t)
        if not m:
            continue
        amount = float(m.group(1).replace(",", "."))
        h = max(a.box[3], 10)
        mid = a.box[1] + a.box[3] / 2
        same = [k for k in toks if k is not a and abs(k.box[1] + k.box[3] / 2 - mid) < 0.6 * h and k.box[0] < a.box[0]]
        q = None
        for k in sorted(same, key=lambda k: -k.box[0]):          # 数量左边最近的整数
            mq = re.fullmatch(r"\d{1,4}", k.text.strip()) or re.search(r"\s(\d{1,4})$", k.text.strip())
            if mq and 0 <= int(mq.group(mq.lastindex or 0)) <= 1000:
                q = int(mq.group(mq.lastindex or 0))
                break
        return q, amount
    return None, None


def parse_qlabel(text):
    """物品格子左上角的品质标签 → 品质；不是品质标签返回 None。
    游戏里写成「575Q」「0Q」。OCR 常把 Q 认成 0（907Q → 9070）、把 0 认成 Q（0Q → QQ），
    品质最多 1000，四位数末尾是 0 就是 Q 认错了"""
    t = (text or "").replace(" ", "").upper()
    if t in ("QQ", "OQ", "0Q", "00", "0O"):
        return 0
    m = re.fullmatch(r"(\d{1,4})[QO]", t)
    if m:
        return int(m.group(1)) if int(m.group(1)) <= 1000 else None
    m = re.fullmatch(r"\d{1,5}", t)
    if not m:
        return None
    if len(t) >= 4 and t.endswith("0") and t != "1000":
        v = int(t[:-1])                                   # Q 认成了 0
        return v if v <= 1000 else None
    return int(t) if int(t) <= 1000 else None


def parse_count(text):
    """格子右上角的堆叠数量「200x」→ 200；「200/200」（当前量 / 上限）不是数量"""
    m = re.fullmatch(r"(\d{1,5})[xX×]", (text or "").replace(" ", ""))
    return int(m.group(1)) if m else None


def cell_labels(img, cursor, tokens=None, size=None):
    """鼠标指着的那个物品格子：左上角的品质（575Q）和右上角的数量（200x）。没有返回 None。
    只认鼠标上方一个格子高度以内的标签；同一排里品质取鼠标左边最近的、数量取鼠标右边最近的。
    size：格子大小 (宽, 高)，默认按整屏比例估（1440p 下约 150×140）"""
    W, H = img.size
    cw, ch = size or (int(W * 0.065), int(H * 0.11))
    cx, cy = cursor
    if tokens is None:
        from .ocr import recognize
        box = (max(0, cx - cw), max(0, cy - ch), min(W, cx + cw), min(H, cy + ch // 6))
        # native=True 避免小裁剪图被 RapidOCR 强行放大至 736px，提速 2~3 倍
        tokens = recognize(img.crop(box), urgent=True, offset=box[:2], native=True)
    best_q = best_n = None
    for t in tokens:
        x, y, w, h = t.box
        if not cy - ch < y < cy:
            continue
        q = parse_qlabel(t.text)
        if q is not None and cx - cw < x <= cx + 4 and (best_q is None or (y, x) > best_q[:2]):
            best_q = (y, x, q)
        n = parse_count(t.text)
        if n is not None and cx - 4 <= x + w < cx + cw and (best_n is None or (y, -x) > best_n[:2]):
            best_n = (y, -x, n)
    return (best_q[2] if best_q else None), (best_n[2] if best_n else None)


def _is_mineral(zh, en):
    try:
        from ..mining.data import SIGNATURES
        from ..core.i18n import mineral_en
        return (en or "").strip().lower() in {k.lower() for k in SIGNATURES} or bool(zh and mineral_en(zh))
    except Exception:
        return False


def inspect_item(img, cursor: Tuple[int, int], tokens=None, where=None) -> Optional[Dict[str, Any]]:
    """识别鼠标悬停的物品格与说明框，返回结构化字典或 None：
    {
        "zh": 中文名,
        "en": 英文名,
        "quality": 品质 (int | None),
        "qty": 数量 (float | int),
        "unit": 单位 ("SCU" | "个"),
        "sure": bool (是否通过标准对照表纠正),
        "craft": list | None (蓝图材料槽反推详情),
        "tokens": tokens,
        "where": 识别区域标签 ("30-50%" / "50-70%" / "整屏" 等)
    }
    """
    from .names import canonical
    W, H = img.size
    cx, cy = cursor

    if tokens is None or where is None:
        tokens, name, where = _read_tooltip(img, (cx, cy))
    else:
        from . import console as C
        name, _sure = C.tooltip_pick(tokens, (cx, cy), img)

    if not name:
        return None

    zh, en = name
    canon = canonical(zh, en)
    if canon:
        zh, en = canon

    mineral = _is_mineral(zh, en)
    row_q, row_amt = tooltip_row(tokens)
    if row_q is None:
        row_q = tooltip_quality(tokens)

    cell_q, cell_n = None, None
    if not mineral:
        can_reuse = False
        if where == "整屏":
            can_reuse = True
        elif where in HOVER_REGIONS:
            cw, ch = int(W * 0.065), int(H * 0.11)
            l, t, r, b = HOVER_REGIONS[where]
            box_hover = (int(W * l), int(H * t), int(W * r), int(H * b))
            if cx - cw >= box_hover[0] and cy - ch >= box_hover[1] and cx + cw <= box_hover[2] and cy + ch // 6 <= box_hover[3]:
                can_reuse = True
        try:
            cell_q, cell_n = cell_labels(img, (cx, cy), tokens=tokens if can_reuse else None)
        except Exception:
            cell_q, cell_n = None, None

    quality = row_q if row_q is not None else cell_q if cell_q is not None else (None if mineral else 0)
    qty, unit = (row_amt, "SCU") if mineral else ((cell_n or 1), "个")

    craft = None
    if not mineral and row_q is None and cell_q is None:
        # 制造出来的装备无显式品质数字，根据蓝图修饰词倒推各材料槽品质
        try:
            from ..crafting.crafting import parse_mods, solve_slots, for_item
            mods = parse_mods(tokens)
            res = solve_slots(for_item(en, zh), mods) if mods else None
            if res and res["exact"]:
                quality, craft = res["avg"], res["slots"]
            elif res:
                quality = None
        except Exception:
            craft = None

    return {
        "zh": zh,
        "en": en,
        "quality": quality,
        "qty": qty,
        "unit": unit,
        "sure": bool(canon),
        "craft": craft,
        "tokens": tokens,
        "where": where,
    }
