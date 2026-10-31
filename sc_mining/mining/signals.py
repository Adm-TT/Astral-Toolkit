"""雷达信号：信号值 → 矿种 + 块数，以及在整个画面里找信号标记

- 合法信号值只有"单块信号 × 块数（1–10）"这几百个固定值，OCR 读错一位数字时吸附到最接近的合法值
- 画面里的信号标记是「暖色图钉 + 浅色数字」（如 "📍 4,285"）：MOLE 炮塔里是橙色图钉 + 淡绿字，勘探者驾驶舱里是黄色图钉 + 白字。
  先找浅色数字块，左边紧挨暖色图钉才拿去 OCR
"""
import re

import numpy as np

from .data import SIGNATURES, RARITY, MAX_CLUSTER

# 数字之间的形近误认（OCR 小字常见）：越小越像
_DIGIT_CONFUSION = {frozenset("38"), frozenset("56"), frozenset("17"), frozenset("08"),
                    frozenset("69"), frozenset("35"), frozenset("49"), frozenset("06")}


def all_signatures():
    """{信号值: [(矿物, 块数)]}"""
    out = {}
    for mineral, base in SIGNATURES.items():
        for n in range(1, MAX_CLUSTER + 1):
            out.setdefault(base * n, []).append((mineral, n))
    return out


def match_signature(value: int, tolerance: int = 0):
    """返回所有可能的 (矿物, 块数, 稀有度)，按块数从少到多排。个别值会撞车，全部返回"""
    hits = []
    for mineral, base in SIGNATURES.items():
        for n in range(1, MAX_CLUSTER + 1):
            if abs(base * n - value) <= tolerance:
                hits.append((mineral, n, RARITY[mineral]))
    hits.sort(key=lambda h: h[1])
    return hits


SNAP_MAX_REL = 0.03     # 形近修正最多改动 3%：再远就不是「读错一位」能解释的（2026-10-31 审查：3,360 被改成火神石 ×2 = 8,360 还标精确）


def snap(text: str):
    """OCR 读到的信号文字 → (合法信号值, 是否修正过)；认不出返回 (None, False)。
    先看原值是否合法；不合法就在同位数、只差一位数字的合法值里找，形近数字优先"""
    digits = "".join(c for c in str(text) if c.isdigit())
    if not digits:
        return None, False
    valid = all_signatures()
    v = int(digits)
    if v in valid:
        return v, False
    best, best_cost = None, None
    for cand in valid:
        c = str(cand)
        if len(c) != len(digits):
            continue
        if abs(cand - v) > v * SNAP_MAX_REL:   # 改一位改出很远的值（3,360 → 8,360）不算修正，交给「最接近 + 可信度」
            continue
        diffs = [(a, b) for a, b in zip(digits, c) if a != b]
        if len(diffs) != 1:
            continue
        a, b = diffs[0]
        cost = 0 if frozenset((a, b)) in _DIGIT_CONFUSION else 1
        if best_cost is None or cost < best_cost:
            best, best_cost = cand, cost
        elif cost == best_cost:
            best = None if best != cand else best   # 两个同样好的候选：不猜
    return (best, True) if best else (None, False)


def describe(value, where=None) -> str:
    v, fixed = resolve(value)
    if v is None:
        return f"{value}：没有匹配的矿物信号"
    if not match_signature(v):
        return f"{v}：" + " / ".join(t for t, _, _ in guesses(v, where))
    parts = [f"{m} ×{n}（{r}）" for m, n, r in match_signature(v)]
    note = f"（OCR 读成 {value}，已修正）" if fixed else ""
    return f"{v}{note}：" + " / ".join(parts)


# ---------------------------------------------------------------- 画面里找信号


def _components(mask, min_h, max_h):
    import cv2
    n, _, st, _ = cv2.connectedComponentsWithStats(mask.astype("uint8"), connectivity=8)
    return [(int(x), int(y), int(x + w), int(y + h)) for x, y, w, h, area in st[1:]
            if min_h <= h <= max_h and area >= 0.1 * w * h]


def candidates(img):
    """返回疑似信号数字的框 [(x0, y0, x1, y1)]（整屏坐标）"""
    import cv2
    from .screen import deflood
    R, G, B = cv2.split(np.ascontiguousarray(np.asarray(img)))          # uint8；差值用 cv2.subtract（负数截成 0）
    lo, hi = cv2.min(cv2.min(R, G), B), cv2.max(cv2.max(R, G), B)
    H = img.height
    k = max(15, int(H * 0.03) | 1)
    # 信号数字：不同船的 HUD 颜色不一样——MOLE 炮塔是淡绿色字 + 橙色图钉，勘探者驾驶舱是白色字 + 黄色图钉
    # 背景本身就是亮白（浓雾、雪地天空，2026-10-23 Calliope 实测雾是 (210,222,232)）时只要比周围更亮的（deflood）
    # 淡绿字 G 比 R 高一截；雾里信号框是淡黄色 (228,225,195)，G 和 R 差不多，不算
    green = deflood((G > 140) & (cv2.subtract(G, B) > 20) & (cv2.subtract(G, R) > 8), G, k, 15)
    # 白字按最暗的通道和周围比：白字三个通道都高，雾偏蓝、信号框偏黄，最暗的通道都低一截
    white = deflood((R > 185) & (G > 185) & (B > 170) & (cv2.subtract(hi, lo) < 45), lo, k, 10)
    # 雾里信号框的边框比雾亮，也会被当成字：上边框把图钉和数字连成一块，长横线先去掉
    white = _no_hlines(white, max(20, int(H * 0.025)))
    text = green | white
    # 图钉：MOLE/勘探者是暖色（橙或黄），Perseus 等大船的 HUD 是白色图钉 + 白字（在半透明的蓝灰小框里）
    rb = cv2.subtract(R, B)
    orange = deflood((R > 170) & (G > 80) & (G < 230) & (B < 130) & (rb > 80), rb, k, 20)
    pin_mask = orange | white
    # 选中的信号是「橙色底框 + 黄色图钉 + 白字」（2026-10-23 玩家反馈，阿伯丁黄沙大气里的 12,675 没认出来）：
    # 整块橙底都算进了 orange，图钉形状看不出来。另取「比周围明显更黄更亮」的像素当图钉
    tagpin = (R > 200) & (G > 160) & (B < 140) & (cv2.subtract(G, cv2.blur(G, (k, k))) > 30)
    gap = max(3, round(H * 0.004))
    words = cv2.dilate(text.astype("uint8"), np.ones((3, gap), np.uint8))
    out = []
    W = img.width
    for x0, y0, x1, y1 in _components(words, H * 0.0045, H * 0.02):   # 大船 HUD 的信号字更小（1440p 下约 8px 高）
        if x0 > W * 0.62 and y1 < H * 0.30:     # 右上角是调试信息（r_DisplayInfo，1440p 下一直写到约 0.27 屏高），不会有信号
            continue
        h = y1 - y0
        if 1.5 <= (x1 - x0) / h <= 6 and (_pin_left(pin_mask, x0, y0, y1) or _pin_left(tagpin, x0, y0, y1)):   # 左边有一个图钉
            out.append((x0, y0, x1, y1))
        elif x1 - x0 <= 15 * h:
            part = _split(lo, pin_mask, (x0, y0, x1, y1), gap)
            if part:
                out.append(part)
    return out


def _pin_left(pin_mask, x0, y0, y1):
    h = y1 - y0
    lx0 = max(0, int(x0 - 2.5 * h))
    pin = pin_mask[max(0, y0 - h // 2): y1 + h // 2, lx0: max(lx0, x0 - 2)]
    return pin.sum() >= 0.8 * h and _has_pin(pin, h)


def _split(lo, pin_mask, box, gap):
    """亮背景（雾、雪）里数字和别的东西连成了一块：雾里信号框的边框、框上的竖条纹、图钉都比雾亮（2026-10-23 Calliope）。
    这块里只取最亮的那些像素（白字最亮，条纹和边框暗一截），按空白列切成一个个字，
    从左往右找「左边紧挨图钉、至少 3 个字、中间有一个贴底的逗号」的那一段"""
    x0, y0, x1, y1 = box
    reg = lo[y0:y1, x0:x1]
    if reg.size == 0 or np.median(reg) < 150:          # 暗背景走不到这里（边框看不见，原来的办法就够）
        return None
    sub = reg >= np.percentile(reg, 97) - 16
    cols = sub.any(axis=0)
    segs, start = [], None
    for i, c in enumerate(list(cols) + [False]):
        if c and start is None:
            start = i
        elif not c and start is not None:
            rows = np.nonzero(sub[:, start:i].any(axis=1))[0]
            segs.append((start, i, int(rows[0]), int(rows[-1]) + 1))
            start = None
    if len(segs) < 4:
        return None
    hs = sorted(r1 - r0 for _s, _e, r0, r1 in segs)
    med = hs[len(hs) // 2]
    keep = [g for g in segs if not (g[1] - g[0] <= 3 and g[3] - g[2] >= 1.25 * med)]     # 边框：细、比字高
    for i in range(1, len(keep) - 2):
        part = keep[i:]
        top, bot = min(g[2] for g in part), max(g[3] for g in part)
        if not any(g[2] >= top + 0.45 * (bot - top) for g in part[1:-1]):      # 没有逗号：不像信号值
            continue
        sx0, sx1 = x0 + part[0][0] - gap // 2, x0 + part[-1][1] + gap // 2
        sy0, sy1 = y0 + top - 1, y0 + bot + 1
        h = sy1 - sy0
        if h >= 6 and 1.5 <= (sx1 - sx0) / h <= 6 and _pin_left(pin_mask, sx0, sy0, sy1):
            return sx0, sy0, sx1, sy1
    return None


def _no_hlines(mask, length):
    """去掉比 length 还长的横线（允许中间断开几个像素）：框线、HUD 分隔线；数字和汉字的横笔都没这么长"""
    import cv2
    m = mask.astype(np.uint8)
    closed = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((1, 5), np.uint8))
    lines = cv2.morphologyEx(closed, cv2.MORPH_OPEN, np.ones((1, length), np.uint8))
    return mask & ~lines.astype(bool)


def _has_pin(win, h):
    """窗口里有没有一个图钉形状的小块：大约和数字一样高或高一点、比较窄、不是一长串字的一部分"""
    import cv2
    n, _, st, _ = cv2.connectedComponentsWithStats(win.astype("uint8"), connectivity=8)
    for x, y, w, bh, area in st[1:]:
        if 0.7 * h <= bh <= 2.4 * h and 0.3 * h <= w <= 1.6 * h and area >= 0.6 * h and x + w >= win.shape[1] - 1.8 * h:
            return True
    return False


def _variants(arr):
    """先认原图；背景很亮（雾、雪）时字和背景只差几十，再认一次拉开对比度的白底黑字"""
    yield arr
    g = arr.max(axis=2).astype(float)
    if np.median(g) > 150:
        lo_, hi_ = np.percentile(g, 50), np.percentile(g, 99.5)
        g = np.clip((g - lo_) / max(1.0, hi_ - lo_) * 255, 0, 255)
        yield np.stack([255 - g] * 3, axis=2).astype("uint8")


_SEEN = {}                 # 标签画面 → 认出的 (信号值, 修正过, 原文) 或 None（不是信号）；最多记 SEEN_MAX 块
SEEN_MAX = 256


def _crop_key(piece):
    """一小块画面的指纹：缩到 32 像素宽、灰度后的字节（同一块标签画面不变，指纹就一样）"""
    import hashlib
    small = piece.convert("L").resize((32, max(4, round(32 * piece.height / max(1, piece.width)))))
    return hashlib.blake2b(small.tobytes(), digest_size=12).digest()


def _remember(key, val):
    if key is None:
        return
    if len(_SEEN) >= SEEN_MAX:
        _SEEN.pop(next(iter(_SEEN)))
    _SEEN[key] = val


def find_signatures(img, rec=None):
    """返回 [(信号值, 是否修正过, OCR原文, 框)]"""
    from PIL import Image
    cache = rec is None                      # 测试里传进来的假识别不进缓存
    if rec is None:
        from .screen import _recognize
        rec = _recognize()
    out = []
    for x0, y0, x1, y1 in candidates(img):
        h = y1 - y0
        pad = max(2, h // 4)
        piece = img.crop((x0 - pad, y0 - pad, x1 + pad, y1 + pad))
        # 指纹连左边 5 个字宽一起算：同样的数字、左边多了一截（余额这种长数字）就不是同一块，要重新判断（Codex 2026-10-27）
        key = _crop_key(img.crop((max(0, x0 - 5 * h), y0 - pad, x1 + pad, y1 + pad))) if cache else None
        if cache and key in _SEEN:           # 这块标签画面和刚才一模一样：直接用上次的结果（含「不是信号」），不再认一遍（老大审查 2026-10-28：None 以前当没命中）
            hit = _SEEN[key]
            if hit:
                out.append((*hit, (x0, y0, x1, y1)))
            continue
        up = max(1, round(24 / h))
        piece = piece.resize((piece.width * up, piece.height * up), Image.LANCZOS)
        text, t = "", ""
        for arr in _variants(np.asarray(piece)):
            text, score = rec(np.ascontiguousarray(arr))
            t = text.replace(" ", "").replace("，", ",")
            # 信号数字带千分位逗号且是整数（如 4,285 / 12,680）；成分百分比、距离等格式不符，直接排除
            if re.fullmatch(r"\d{1,3}[,.]\d{3}", t):
                break
        else:
            _remember(key, None)
            continue
        if _longer_number(img, (x0, y0, x1, y1), rec):
            _remember(key, None)
            continue
        value, fixed = resolve(t)
        if value is None:                   # 0,000 这种：不是信号。别把 None 放进结果（下游排序、匹配会抛错，整帧信号都发不出去）
            _remember(key, None)
            continue
        _remember(key, (value, fixed, text))
        out.append((value, fixed, text, (x0, y0, x1, y1)))
    W, H = img.size
    l, tp, r, b = (int(v * s) for v, s in zip(CENTER_TAG, (W, H, W, H)))
    if CENTER_TAG and not any(l <= bx[0] and bx[2] <= r and tp <= bx[1] and bx[3] <= b for *_x, bx in out):
        out += _center_tag(img, (l, tp, r, b))
    return out


# 选中的信号挂在屏幕上方正中（航向刻度上面）的小标签里。亮天空、云层、雪地上这个半透明的小标签颜色淡，按颜色找不出来
# （2026-10-25 用户样本：MOLE 驾驶位云层里 8,000 / 42,000 / 54,000 全没认出）：这一小块直接交给 OCR 的检测 + 识别再找一遍
CENTER_TAG = (0.42, 0.30, 0.58, 0.47)


def _center_tag(img, box, up=2):
    from PIL import Image
    from .screen import _ocr
    crop = img.crop(box)
    crop = crop.resize((crop.width * up, crop.height * up), Image.LANCZOS)
    nums = []
    for quad, text, conf in _ocr()(np.ascontiguousarray(np.asarray(crop))):
        t = text.replace(" ", "").replace("，", ",").lstrip("0Q@")
        if not re.fullmatch(r"\d{1,3}[,.]\d{3}", t):
            continue
        xs = [p[0] / up + box[0] for p in quad]
        ys = [p[1] / up + box[1] for p in quad]
        nums.append((t, text, (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))))
    out = []
    for t, text, b in nums:
        # 同一行并排好几个数字的不是采矿信号：选中目标时屏幕中上方那行「3,349 | 16,500 | 1,184」是目标的三种特征信号
        # （2026-10-22 珀尔修斯截图被认成托瑞特金属）。采矿信号的标签一行只有一个数
        h = b[3] - b[1]
        if any(o is not b and abs((o[1] + o[3]) / 2 - (b[1] + b[3]) / 2) <= h for _, _, o in nums):
            continue
        value, fixed = resolve(t)
        if value:
            out.append((value, fixed, text, b))
    return out


_BIG = re.compile(r"\d{1,3}(?:[,.]\d{3}){2,}")


def _longer_number(img, box, rec):
    """这串数字其实是一个更长数字的后半截（星图左下角的余额 58,847,832 被读成信号 7,832，2026-10-24 玩家反馈）：
    往左多截几个字宽再认一次，认出来是带两组以上千分位的大数（信号不会上百万；只认逗号分组，图钉被认成数字也不会误杀）就不算信号"""
    from PIL import Image
    x0, y0, x1, y1 = box
    h = y1 - y0
    pad = max(2, h // 4)
    piece = img.crop((max(0, x0 - 5 * h), y0 - pad, x1 + pad, y1 + pad))
    up = max(1, round(24 / h))
    piece = piece.resize((piece.width * up, piece.height * up), Image.LANCZOS)
    for arr in _variants(np.asarray(piece)):
        text, _ = rec(np.ascontiguousarray(arr))
        if _BIG.search(text.replace(" ", "").replace("，", ",")):
            return True
    return False


# 飞船矿以外的信号：每个点的固定信号值 × 个数。地面的数值以 SCMiner 矿物目录为准（gems.py，2026-10-25 核对）：
#   4,000：熵瞬晶 Feynmaline、冰碛棉 Glacosite、冰蓝珀 Beradom（只能 ROC 车挖）
#   3,000：哈丹水晶 Hadanite、紫钠水晶 Aphorite、暗橄榄石 Dolivine（ROC 车或手采）。
#          矿洞里手采的加纳石、杰金、Sadaryx、烁迪银也是 3,000，不写进说明（用户 2026-10-25）
# 太空里 3,000 的倍数是可打捞残骸（用户 2026-10-23 提供）
# 最后一项是一个集群最多几个：手采矿、车矿最多十来个，按 15 算；残骸一般 3 到 8 块、也有十块以上的，按 15 算（用户 2026-10-25）
GROUND_MAX = 15
# 2,000：可采集物（植物、菌菇等，harvestable_base_*，2026-10-27 解包核对；老大实测 10,000 = 5 个可采集物）
GROUND_SOURCES = (("ROC 车矿", 4000, "熵瞬晶 / 冰碛棉 / 冰蓝珀", GROUND_MAX),
                  ("车矿或手采", 3000, "哈丹水晶 / 紫钠水晶 / 暗橄榄石", GROUND_MAX),
                  ("可采集物", 2000, "植物、菌菇等", GROUND_MAX))
SALVAGE_MAX = 15
SPACE_SOURCES = (("可打捞残骸", 3000, "", SALVAGE_MAX),)
OTHER_SOURCES = tuple((n, b, mx) for n, b, _, mx in GROUND_SOURCES + SPACE_SOURCES)
MANY = 2             # 地面上比一簇还大的整千信号：最多按两簇叠加来估（再大就写「未知」）


def resolve(text):
    """OCR 文字 → (信号值, 是否按形近数字修正过)。
    原值是飞船矿或其他来源的合法值就照用；否则先试只差一位的形近修正；都不行就照原值（由 guesses 给最接近的）"""
    digits = "".join(c for c in str(text) if c.isdigit())
    if not digits:
        return None, False
    v = int(digits)
    if v == 0:                               # 读到 0,000：不是信号
        return None, False
    if v in all_signatures() or any(v % base == 0 and 1 <= v // base <= mx for _, base, mx in OTHER_SOURCES):
        return v, False
    if v > max(all_signatures()) * 1.1:      # 比最大的飞船矿信号还大得多：不要改一位数硬凑成飞船矿
        return v, False
    fixed, did = snap(digits)
    return (fixed, True) if fixed else (v, False)


def _local_table(area):
    """当地会刷的石头：{矿: 百分比}。优先用解包的石头表（按石头种类，和雷达信号一一对应），没有才用 SCMiner 的矿物表；
    不知道在哪 → None（不过滤）"""
    if not area:
        return None
    return area["rocks"] if area.get("rocks") is not None else area.get("minerals")


def cluster_weight(mineral, n):
    """这种石头一团 n 块有多常见（解包的成团规则：普通 4～6 块、罕见 3～5、稀有 2～4、史诗 40% 成团 2～3、传说 25% 成 2 块）。
    刚刷出来的块数最常见；挖掉几块后剩得少也常见（打个折）；比一团最多还多的很少（几团挨在一起）。没有解包数据 → 1（不影响排序）"""
    from .mining_area import rocks_table
    t = rocks_table()
    tier = ((t.get("ores") or {}).get(mineral) or {}).get("tier")
    rule = (t.get("tiers") or {}).get(tier)
    if not rule:
        return 1.0
    pc = (rule.get("p_cluster") or 0) / 100
    sizes = rule.get("sizes") or []
    tot = sum(p for p, _, _ in sizes) or 1
    start = {1: 1 - pc}                                   # 刚刷出来时是几块的概率
    for p, lo, hi in sizes:
        for k in range(lo, hi + 1):
            start[k] = start.get(k, 0) + pc * p / tot / (hi - lo + 1)
    most = max(start)
    if n > most:
        return 0.02
    return start.get(n, 0) + 0.25 * sum(v for k, v in start.items() if k > n)


def _local_note(mineral, local):
    pct = (local or {}).get(mineral)
    return f"｜此地 {pct:g}%" if pct else ""


# ---------------------------------------------------------------- 自己记的信号、两种混在一团（2026-10-27）

def _mine_file():
    from ..core.paths import USER
    return USER / "my_signatures.json"


_MINE = {"stamp": -1, "t": {}}


def my_signatures():
    """玩家自己给信号起的名字 {"12345": "名字"}（userdata/my_signatures.json，升级不动）"""
    from ..core.paths import cached_json
    t = cached_json(_mine_file(), default={})
    return t if isinstance(t, dict) else {}


def set_my_signature(value, name):
    """记下 / 改名；名字为空 = 删掉"""
    import json
    t = dict(my_signatures())
    name = (name or "").strip()[:40]
    if name:
        t[str(int(value))] = name
    else:
        t.pop(str(int(value)), None)
    p = _mine_file()
    from ..core.paths import write_json
    write_json(p, t, indent=1)
    return t


MIX_MAX = 2          # 混合最多列几种可能


def mixed(value, local):
    """两种当地会刷的石头挨在一团、信号加在一起正好等于 value：[(说明, 0, False)]，按当地概率 × 成团常见程度排。
    只在知道当地刷什么时试（不知道的话组合太多，什么数都凑得出来）"""
    from ..core.i18n import mineral_zh
    if not local:
        return []
    ores = sorted(m for m in local if m in SIGNATURES)
    found = []
    for i, a in enumerate(ores):
        for b in ores[i + 1:]:
            for n in range(1, MAX_CLUSTER + 1):
                rest = value - SIGNATURES[a] * n
                if rest <= 0:
                    break
                if rest % SIGNATURES[b] == 0 and 1 <= rest // SIGNATURES[b] <= MAX_CLUSTER:
                    m = rest // SIGNATURES[b]
                    w = local[a] * local[b] * cluster_weight(a, n) * cluster_weight(b, m)
                    found.append((w, f"可能两种混在一团：{mineral_zh(a)} ×{n} + {mineral_zh(b)} ×{m}"
                                     f"｜此地 {local[a]:g}% / {local[b]:g}%"))
    found.sort(key=lambda x: -x[0])
    return [(t, 0, False) for _, t in found[:MIX_MAX]]


def guesses(value, where=None, area=None):
    """_guesses 的结果，再加上：玩家自己记过这个信号 → 排第一；对不上单一种矿时，试两种混在一团（加起来正好相等才算）"""
    out = _guesses(value, where, area)
    if not any(exact for *_, exact in out):
        mix = mixed(value, _local_table(area))
        if mix:
            out = mix + [g for g in out if g[0] != "未知"]
    mine = my_signatures().get(str(value))
    if mine:
        out = [(f"{mine}（自己记的）", 0, True)] + out
    return out


def _guesses(value, where=None, area=None):
    """信号值最可能是什么：[(说明, 价格或 0, 是否精确)]，最可能的排前面。
    where：玩家在 "ground"（星球表面）还是 "space"（太空），None = 不知道（两边的可能都列出来）
    1. 正好是飞船矿「单块 × 块数」→ 精确（地面、太空都有飞船矿）
    2. 正好是地面矿 / 手采矿（在地面）或可打捞残骸（在太空）的整数倍 → 精确
    3. 都不是 → 给最接近的飞船矿（标「最接近，仅供参考」）
    area：玩家所在的产矿区（mining_area.area 的结果），None = 不知道（不过滤）。知道的话（2026-10-27 用户要求）：
    只报当地会刷的矿，按当地概率排、标「此地 18%」；数值正好是当地不刷的矿 → 改报当地最接近的；
    不刷船挖矿的空旷太空 → 不报船挖矿"""
    from .data import best_price
    from ..core.i18n import mineral_zh
    local = _local_table(area)
    out, skipped = [], []
    hits = match_signature(value)
    if local is not None:
        skipped = [(m, n) for m, n, _ in hits if m not in local]
        hits = sorted((h for h in hits if h[0] in local), key=lambda h: -local[h[0]] * cluster_weight(h[0], h[1]))
    for mineral, n, rarity in hits:
        out.append((f"{mineral_zh(mineral)} ×{n}｜{rarity}{_local_note(mineral, local)}", best_price(mineral)[0], True))
    sources = (GROUND_SOURCES if where != "space" else ()) + (SPACE_SOURCES if where != "ground" else ())
    for src in sources:
        name, base, what, mx = src
        if value % base == 0 and 1 <= value // base <= mx:
            head = "" if where else ("地面：" if src in GROUND_SOURCES else "太空：")
            out.append((f"{head}{name} ×{value // base}" + (f"（{what}）" if what else ""), 0, True))
    if out:
        return out
    # 地面上整千、又比一簇地面矿最大的还大（2026-10-23 Calliope 浓雾实测 80,000、54,000）：
    # 一簇车矿 / 手采矿最多十来个，这么大多半是同一方向几处信号加在一起。只能估个大概有几处，都是飞船挖不了的地面小矿
    if where != "space" and value % 1000 == 0 and value > GROUND_MAX * 3000:
        lo_n, hi_n = -(-value // 4000), value // 3000
        if hi_n <= GROUND_MAX * MANY:
            return [(f"地面小矿叠在一起（ROC 车矿 4,000 / 车矿或手采 3,000 一处），约 {lo_n}~{hi_n} 处", 0, False)]
    # 都对不上：按 SCMiner 的做法取最接近的飞船矿（可信度 = 1 − 差值 / 那个合法值，scminer.rocks 查 12200 →
    # 火神石 ×3 = 12,540，可信度 97.3%，2026-10-23 核对过）；地面/太空的其他来源接近的话列在后面
    allowed = SIGNATURES if local is None else {m: b for m, b in SIGNATURES.items() if m in local}
    ship = min(((abs(base * n - value), base * n, m, n) for m, base in allowed.items()
                for n in range(1, MAX_CLUSTER + 1)), default=None)
    if ship is None:                         # 不刷船挖矿的地方：只剩残骸 / 地面小矿这些解释
        if local is not None and not local:
            extra = f"（读数像{mineral_zh(skipped[0][0])} ×{skipped[0][1]}）" if skipped else ""
            return [(f"{area.get('zh') or '此处不刷船挖矿'}，多半是残骸或其他信号{extra}", 0, False)]
        return []
    diff, target, m, n = ship
    why = ""
    if skipped:                              # 数值正好是当地不刷的矿：多半读错了一位
        sm, sn = skipped[0]
        why = f"（读数是{mineral_zh(sm)} ×{sn}，此地不刷）"
    cands = [(max(0.0, 1 - diff / target), f"{mineral_zh(m)} ×{n}（{target:,}）｜{RARITY[m]}{_local_note(m, local)}{why}")]
    for src in sources:
        name, base, what, mx = src
        k = max(1, min(mx, round(value / base)))
        head = "" if where else ("地面：" if src in GROUND_SOURCES else "太空：")
        cands.append((1 - abs(base * k - value) / (base * k),
                      f"{head}{name} ×{k}" + (f"（{what}）" if what else "")))
    # SCMiner 为准：飞船矿可信度够（≥90%）就排第一；地面矿/残骸要很接近（≥97%）才列，按可信度排
    ship_c, others = cands[0], sorted(cands[1:], key=lambda c: -c[0])
    good = ([ship_c] if ship_c[0] >= 0.9 else []) + [c for c in others if c[0] >= 0.97]
    if not good:
        good = [c for c in others if c[0] >= 0.9][:1]
    if not good:
        return [("未知", 0, False)]          # 实在对不上：浮窗就写「未知」（用户 2026-10-23）
    # 没正好对上的最多写 99.9%（铝 ×7 = 29,995 对 30,000 是 99.98%，四舍五入成 100.0% 像是完全对上）
    return [(("最接近 " if i == 0 else "或 ") + f"{t}（可信度 {min(c, 0.999):.1%}）", 0, False) for i, (c, t) in enumerate(good[:3])]


def describe_all(found, where=None, area=None):
    """把找到的信号整理成几行中文说明，按矿的价值从高到低排；对不上信号表的给最可能的解释。
    where：玩家在 "ground" / "space" / None（不知道）；area：所在产矿区（只报当地会刷的矿），None = 不过滤"""
    groups, seen = [], set()
    for value, fixed, raw, _ in found:
        if value in seen:
            continue
        seen.add(value)
        note = f"（读成 {raw}，改过一位，可能有误）" if fixed else ""
        lines = []
        for text, price, exact in guesses(value, where, area):
            tail = f"｜精炼后 {price:,}/SCU" if price else ""
            # 读数是按形近数字改过的：不算准确，排到后面（2026-10-27）
            lines.append((price if exact and not fixed else -1, f"信号 {value:,}{note} → {text}{tail}"))
        if lines:
            groups.append((max(p for p, _ in lines), [t for _, t in lines]))
    # 几个信号之间按价值排；同一个信号的几种可能保持 guesses 的顺序（当地概率 × 一团几块，Codex 2026-10-27 二审）
    return [t for _, ts in sorted(groups, key=lambda g: g[0], reverse=True) for t in ts]
