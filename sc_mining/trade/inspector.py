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
import time
from typing import Any, Dict, List, Optional, Tuple

from .names import canonical, has_chinese

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


# ---------------------------------------------------------------- 说明框启发式与标题提取
# 行首可能多认出一个字母（「A附件：瞄具…」，2026-10-20 日志里没认出的那次）
_ANCHOR = re.compile(r"^[A-Za-z0-9]?(体积|Volume|制造商|Manufacturer|物品类型|Item Type|类别|尺寸|附件|伤害|弹匣)")
_VOLUME = re.compile(r"[:：]\s*[\d,.]+\s*[uμ]?S[CG]U\b", re.I)     # 「体积：13000 uSCU」：OCR 漏了「积」也认得出


def _is_anchor(text: str) -> bool:
    """说明框里名字下面那几行（体积、制造商、物品类型…）。「容量：1.00SCU」「剩余容量：100%」在说明框最底下，
    不算（2026-10-27 勋章：按它往上找，把说明文字最后一行「越。」当成了名字）"""
    t = (text or "").replace(" ", "")
    if t.startswith(("容量", "剩余容量", "Capacity")):
        return False
    return bool(_ANCHOR.match(t) or _VOLUME.search(t))


_SENTENCE = re.compile(r"[，。；！？、,.;!?]\s*\S")
_LETTERS = re.compile(r"[A-Za-z]{3,}")
_STAT = re.compile(r"[:：]\s*[-+]?\d|\d\s*%")              # 「属性：数值」行（NDR:20、剩余容量：100%）
# 不是物品名的屏幕文字：聊天（[全局]某人：…、[本地]…）、调试信息（Zone: … Pos:）、「名字：」结尾的发言人
_NOT_ITEM = re.compile(
    r"^\s*\d{1,2}\s*[:：、]\s*\S|^\s*\d{1,2}\.\s+\S|^\s*[\[【(（]\s*(全局|本地|队伍|小队|组织|私聊|好友|系统|派对|Global|Local|Party|Org|Private|Whisper)|"
    r"Zone\s*[:：]|Pos\s*[:：]|[:：]\s*$",
    re.I,
)


def _ink(img, box):
    """一行字有多亮：框里亮的像素（字）比一般像素（底）亮多少。两个说明框叠在一起时，
    正在淡出的旧框、后面那层的框字是暗的（老大 2026-10-27：叠在一起只认高亮的那个）"""
    if img is None:
        return None
    x, y, w, h = box
    try:
        hist = img.crop((max(0, x), max(0, y), x + max(w, 1), y + max(h, 1))).convert("L").histogram()
    except Exception:
        return None
    n = sum(hist)
    if not n:
        return None

    def pct(p):
        c = 0
        for v, k in enumerate(hist):
            c += k
            if c >= n * p:
                return v
        return 255
    return pct(0.92) - pct(0.5)


def _bright_only(items, img, box_of, keep=0.6):
    """去掉字明显暗的候选（比最亮的暗 40% 以上）；量不出亮度就原样返回"""
    if img is None or len(items) < 2:
        return items
    inks = [_ink(img, box_of(it)) for it in items]
    if any(v is None for v in inks):
        return items
    top = max(inks)
    if top <= 0:
        return items
    return [it for it, v in zip(items, inks) if v >= top * keep]


def tooltip_name(tokens, cursor=None):
    """从物品悬停说明框里取名字。说明框第一行是中文名、紧接着一行英文名（游戏汉化包的固定格式），
    找这样的「中文行 + 英文行」，有多处时取离鼠标最近的；找不到再退回按「体积/制造商」那行往上找。
    返回 (中文名, 英文名)，认不出返回 None"""
    return tooltip_pick(tokens, cursor)[0]


def plausible_name(zh, en):
    """没把握的名字（下面没认到「体积」这类行）像不像物品名：中文至少 3 个字、英文至少两个词、
    不是全大写（地点标记 OUTPOST、BAYAR…）、不带冒号。样本里的真物品都过，聊天 / 系统界面的碎字都不过"""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", zh or ""))
    words = re.findall(r"[A-Za-z][A-Za-z0-9'\-]*", en or "")
    letters = "".join(words)
    return (
        3 <= cjk and len(zh) <= 20 and len(words) >= 2 and ":" not in (en or "") and "：" not in (zh or "")
        and not letters.isupper()
    )


def tooltip_pick(tokens, cursor=None, img=None):
    """同 tooltip_name，另外返回「有没有把握」：名字下面紧跟着「体积/物品类型…」这种说明框才有的行，就是有把握。
    img：截图（和 tokens 同一坐标）；给了就只认字亮的那个说明框（两个框叠在一起时）"""
    toks = sorted(tokens or [], key=lambda k: (k.box[1], k.box[0]))
    pairs = []
    for e in toks:
        if has_chinese(e.text) or not _LETTERS.search(e.text):
            continue
        h = max(e.box[3], 12)
        above = [
            z for z in toks if has_chinese(z.text) and 0.4 * h < e.box[1] - z.box[1] < 2.6 * h
            and abs(z.box[0] - e.box[0]) < 2.5 * h
        ]
        if not above:
            continue
        z = max(above, key=lambda k: k.box[1])
        names = [z]
        while True:                                   # 中文名太长会折成两行
            more = [
                k for k in toks if has_chinese(k.text) and 0.4 * h < names[0].box[1] - k.box[1] < 1.8 * h
                and abs(k.box[0] - z.box[0]) < 2.5 * h and not _ANCHOR.match(k.text.replace(" ", ""))
            ]
            if not more or len(names) >= 2:
                break
            names.insert(0, max(more, key=lambda k: k.box[1]))
        zh = "".join(k.text for k in names).strip()
        en = e.text.strip()
        # 名字不是句子：描述文字带逗号句号、而且很长；也不是「属性：数值」（剩余容量：100%、NDR:20）
        if (
            _ANCHOR.match(zh.replace(" ", "")) or _SENTENCE.search(zh) or len(zh) > 30 or len(en) > 60
            or _SENTENCE.search(en.rstrip(".")) or _STAT.search(zh) or _STAT.search(en)
            or _NOT_ITEM.search(zh) or _NOT_ITEM.search(en)
        ):
            continue
        cx, cy = cursor if cursor else (e.box[0], e.box[1])
        dist = ((e.box[0] - cx) ** 2 + (e.box[1] - cy) ** 2) ** 0.5
        # 英文名下面紧跟「体积/物品类型/附件…」的，几乎肯定是说明框标题
        below = [k for k in toks if 0.4 * h < k.box[1] - e.box[1] < 2.6 * h and abs(k.box[0] - e.box[0]) < 2.5 * h]
        anch_boxes = tuple(tuple(k.box) for k in below if _is_anchor(k.text))
        anchored = bool(anch_boxes)
        if anchored:
            dist -= 10000
        pairs.append((dist, zh, en, anchored, tuple(e.box), anch_boxes))
    anch = [p for p in pairs if p[3]]
    if anch:                                          # 有说明框标题：只在说明框之间比亮度（彩色标题别被白色 HUD 字比下去，二审）
        pairs = _bright_only(anch, img, lambda p: p[4]) + [p for p in pairs if not p[3]]
    else:
        pairs = _bright_only(pairs, img, lambda p: p[4])
    best = min(pairs) if pairs else None
    if best and best[3]:
        _, zh, en, anchored, _box, ab = best
        if img is not None:
            # 这个说明框的「体积」行比别的说明框的暗：它是后面那层，亮的那个只认出了中文名（二审 2026-10-27）
            bright = {tuple(k.box) for k in _bright_only([k for k in toks if _is_anchor(k.text)], img, lambda k: k.box)}
            if ab and not any(b in bright for b in ab):
                hit = _anchor_name(toks, cursor, img)
                # 还要确认找到的名字那行确实比这个标题亮：只有一个说明框、别处（库存表头）有更亮的「类别」行时不换（复审 2026-10-27）
                tok = next((k for k in toks if hit and k.text.strip() and k.text.strip() in (hit[0] or "")), None)
                mine, theirs = _ink(img, _box), (_ink(img, tok.box) if tok is not None else None)
                if hit and hit[0] != zh and mine is not None and theirs and mine < theirs * 0.6:
                    return hit, True
        return (zh, en), anchored
    # 没有「名字下面紧跟体积」的中英对：说明框可能只有中文名（矿石、食物…），先按「体积」那行往上找；
    # 找不到再用没把握的中英对（以前直接用中英对：杰金矿石的说明框下面列着「1: 焦焰 RYT…/Pyro RYT…」被当成名字，2026-10-24）
    hit = _anchor_name(toks, cursor, img)
    if hit:
        return hit, True
    if best:
        _, zh, en, anchored, _box, _ab = best
        return (zh, en), anchored
    return None, False


def _anchor_name(toks, cursor=None, img=None):
    """按「体积 / 制造商…」那行往上找名字：取最上面一行、不带「：数值」的。返回 (中文名, 英文名) 或 None"""
    anchors = _bright_only([k for k in toks if _is_anchor(k.text)], img, lambda k: k.box)
    if not anchors:
        return None
    # 没有英文名的说明框（食物、饮料等只有中文名）：按「体积」那行往上找，取最上面一行、不带「：数值」的
    if cursor:
        cx, cy = cursor
        anchors.sort(key=lambda k: ((k.box[0] - cx) ** 2 + (k.box[1] - cy) ** 2))
    a = anchors[0] if cursor else min(anchors, key=lambda k: k.box[1])
    h = max(a.box[3], 12)
    above = [
        k for k in toks if a.box[1] - h * 6 < k.box[1] < a.box[1] - h * 0.4 and abs(k.box[0] - a.box[0]) < h * 3
        and not _STAT.search(k.text) and not _SENTENCE.search(k.text)
        and not _is_anchor(k.text) and not re.search(r"[:：]", k.text)     # 「制造商：灰猫工业」不是名字
        and not re.search(r"[。！？，,；]\s*$", k.text)                  # 「越。」：说明文字的最后一截
    ]
    if not above:
        return None
    top = min(k.box[1] for k in above)
    first = [k for k in above if k.box[1] - top < h * 0.6]          # 最上面那一行就是名字
    zh = "".join(k.text for k in first if has_chinese(k.text)).strip()
    nxt = [k for k in above if h * 0.6 <= k.box[1] - top < h * 2.2 and not has_chinese(k.text) and _LETTERS.search(k.text)]
    en = nxt[0].text.strip() if nxt else " ".join(k.text for k in first if not has_chinese(k.text)).strip()
    return (zh, en) if (zh or en) else None


def _cursor_on_image(img):
    """鼠标位置换算成截图像素坐标（截图是游戏画面，见 perf.game_area，1.6.46）"""
    from ..core.perf import cursor_on_image
    return cursor_on_image(img)


def _hover_log(crop, tokens, name, note=""):
    """每次 F8 的截图和识别结果存一份（只留最近 20 张），方便排查认错的情况。note：各步骤耗时"""
    try:
        from ..core import paths
        d = paths.shots("hover")
        stamp = time.strftime("%H%M%S")
        crop.convert("RGB").resize((crop.width // 2, crop.height // 2)).save(d / f"{stamp}.jpg", quality=80)
        with open(paths.log("trade_log.txt"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%F %T')} 名字={name} {note} 文字={[k.text for k in tokens][:40]}\n")
        for old in sorted(d.glob("*.*"))[:-20]:
            old.unlink()
    except Exception:
        pass


def _read_tooltip(img, cursor):
    """→ (文字, (中文名, 英文名) 或 None, 认的范围)
    识别机制：
    1. 按照从左向右，从上到下不考虑（全高 0%~100%）。
    2. 先确定鼠标位置，按 0~30%、30%~50%、50%~70%、70%~100% 匹配首选区域。
    3. 首选区域未成功识别，再尝试 30%~70% 中间区域。
    4. 均未命中时，使用全屏兜底。
    5. 鼠标位置异常则直接尝试中间 30%~70%，失败后再全屏兜底。
    """
    from .ocr import recognize
    W, H = img.size
    regions = get_hover_regions(cursor, W)
    best_candidate = None

    for l, t, r, b, label in regions:
        box = (int(W * l), int(H * t), int(W * r), int(H * b))
        tokens = recognize(img.crop(box), urgent=True, offset=box[:2])
        name, sure = tooltip_pick(tokens, cursor, img)
        if name and sure:
            return tokens, name, label
        if name and plausible_name(*name) and not best_candidate:
            best_candidate = (tokens, name, label)

    # 都不行的时候全屏兜底
    full = recognize(img, urgent=True)
    name_full, sure_full = tooltip_pick(full, cursor, img)
    if name_full and sure_full:
        return full, name_full, "整屏"
    if best_candidate:
        return best_candidate
    if name_full and plausible_name(*name_full):
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
        name, _sure = tooltip_pick(tokens, (cx, cy), img)

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
