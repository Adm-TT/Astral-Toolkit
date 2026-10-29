"""读屏主程序（Windows，本地离线）

python -m sc_mining.screen            实时读屏，扫描结果一变就输出推荐
python -m sc_mining.screen 截图.png   用截图测试识别效果

读取区域按屏幕比例定位，1080p / 1440p / 4K 都适用；区域故意取得比面板大，
面板位置有点偏移也没关系，真正定位靠标签文字（见 parse.py）。
"""
import re
import sys
import time

# 搜索区域：(左, 上, 右, 下)，按屏幕宽高的比例。驾驶位和炮塔位的面板位置不同，
# 所以取一大块，再按文字聚类自动找出"扫描结果"和"货舱"两个面板。
# 右边一直到屏幕边上（1.6.42）：16:10 屏幕（2560×1600）上鼹鼠炮塔的面板挤到了屏幕最右边，
# 以前只找到 92% 宽，质量、抗性、不稳定性的数字正好在外面，只读到标签（2026-10-23 用户反馈）
SEARCH = (0.55, 0.33, 1.0, 0.80)
REGIONS = {"hud": SEARCH}
SEG_TARGET_PX = 16  # 切块识别时把字放大到约这么高（实测 2K 下 7px 字放大到 14px 效果最好）
INTERVAL = 1.0     # 读屏间隔（秒）：1 秒一帧，少占资源，同一块石头两帧读稳就出结果
VOTE_FRAMES = 5    # 同一块石头取最近几帧投票

_engine = None


def _ocr():
    """兼容两种 RapidOCR 包：rapidocr_onnxruntime（旧）和 rapidocr（新，支持 Python 3.13）。
    统一返回 [(四点框, 文字, 置信度)]"""
    global _engine
    if _engine is None:
        from ..core.perf import rapidocr
        eng = rapidocr()
        if eng.kind.startswith("rapidocr_onnxruntime"):
            _engine = lambda arr: eng(arr)[0] or []
        else:
            def run(arr):
                r = eng(arr)
                if r.boxes is None:
                    return []
                return list(zip(r.boxes.tolist(), r.txts, r.scores))
            _engine = run
    return _engine


_rec = None


def _recognize():
    """只做文字识别（不做检测），输入一小块单行文字图，返回 (文字, 置信度)"""
    global _rec
    if _rec is None:
        from ..core.perf import rapidocr
        eng = rapidocr()
        if eng.kind.startswith("rapidocr_onnxruntime"):
            def run(arr):
                res, _ = eng(arr, use_det=False, use_cls=False, use_rec=True)
                return (res[0][0], float(res[0][1])) if res else ("", 0.0)
        else:
            def run(arr):
                r = eng(arr, use_det=False, use_cls=False, use_rec=True)
                return (r.txts[0], float(r.scores[0])) if r.txts else ("", 0.0)
        _rec = run
    return _rec


WHITE_TEXT = True   # 勘探者驾驶舱的扫描面板是白字（MOLE 炮塔是橙/绿字），两种都要认


def deflood(mask, score, k, d, frac=0.5):
    """背景本身就是「字的颜色」的地方（雾、雪地、沙地、亮天空）：mask 会整片都是 True，字和背景连成一大块。
    这种地方（周围 k×k 里一半以上都是 True）只留比周围明显更突出（score 高出 d）的像素；其他地方不动。
    2026-10-23 Calliope 浓雾实测：雾是 (210,222,232) 的亮灰，HUD 白字只比雾亮 20~40，以前整片雾都当成字"""
    import numpy as np
    import cv2
    h, w = mask.shape
    sw, sh = max(1, w // 4), max(1, h // 4)
    small = cv2.resize(mask.astype(np.float32), (sw, sh), interpolation=cv2.INTER_AREA)
    ks = max(3, (k // 4) | 1)
    flood = cv2.blur(small, (ks, ks)) > frac
    if not flood.any():
        return mask
    flood = cv2.resize(flood.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST).astype(bool)
    sc = np.asarray(score, dtype=np.float32)
    bg = cv2.blur(sc, (k, k))
    return mask & (~flood | (sc - bg > d))


def _text_mask(a, thr=40):
    """HUD 文字像素：橙色/淡绿色字（MOLE 炮塔），或者亮白字（勘探者驾驶舱）。
    小行星是暗的蓝灰色，会被排除；背景本身很亮（雪地、雾）或很暖（沙地）的地方，只要比周围更突出的字"""
    import numpy as np
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    k = max(15, (min(a.shape[0], a.shape[1]) // 12) | 1)
    # 1.6.71：字的笔画很细，只要「比周围细细一条更亮 / 更暖」的像素（顶帽变换）。雪地边上、座舱立柱旁边那一大片亮雪
    # 以前会和左边一列标签连成一大块被扔掉（Golem / MOLE 雪地样本），顶帽之后只剩笔画
    se = max(5, int(round(a.shape[0] * 0.0103)) | 1)
    warmth = np.maximum(R - B, (G - B) * 2.5) * (np.maximum(R, G) / 255)
    warm = deflood(warmth > thr, warmth, k, thr / 2) & (_tophat(warmth, se) > thr / 2)
    if not WHITE_TEXT:
        return warm
    hi = np.maximum(np.maximum(R, G), B)
    lo = np.minimum(np.minimum(R, G), B)
    # 亮白字。雪地、冰原（2026-10-23 Wala）、浓雾（同日 Calliope）上背景也是亮白：那里只要比周围亮一截的
    white = (lo > 165) & (hi - lo < 60) & (_tophat(lo, se) > 12)
    return warm | white


def _tophat(x, se):
    import numpy as np
    import cv2
    return cv2.morphologyEx(np.asarray(x, dtype=np.float32), cv2.MORPH_TOPHAT,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (se, se)))


def _runs(profile, min_val, min_gap):
    out, start = [], None
    for i, v in enumerate(profile > min_val):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append([start, i])
            start = None
    if start is not None:
        out.append([start, len(profile)])
    merged = []
    for r in out:
        if merged and r[0] - merged[-1][1] < min_gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return merged


def segment(crop, screen_h=None):
    """按文字颜色找出一个个词块（连通域），过滤掉 HUD 的弧线、进度条等大图形。返回 [(x0,y0,x1,y1)]"""
    import numpy as np
    import cv2
    screen_h = screen_h or crop.height
    m = _text_mask(np.asarray(crop).astype(float)).astype("uint8")
    # 1.6.71：长直线（采矿激光的引导线斜穿过面板、面板上的分隔线）先擦掉，不然会把好几行字连成一块被扔掉（沙漠样本）
    lines = cv2.HoughLinesP(m * 255, 1, np.pi / 180, threshold=60, minLineLength=int(screen_h * 0.06), maxLineGap=4)
    if lines is not None:
        for x0, y0, x1, y1 in lines.reshape(-1, 4):
            cv2.line(m, (int(x0), int(y0)), (int(x1), int(y1)), 0, 3)
    # 横向膨胀把一个词里的字连起来，纵向少量膨胀把汉字的上下笔画连起来
    gap = max(3, round(screen_h * 0.0035))
    md = cv2.dilate(m, np.ones((3, gap), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(md, connectivity=8)
    hmin, hmax = screen_h * 0.004, screen_h * 0.022
    boxes = []
    for i, (x, y, w, h, area) in enumerate(stats[1:], 1):
        if hmin <= h <= hmax and w >= 3 and area >= 0.15 * w * h:
            boxes.append((int(x), int(y), int(x + w), int(y + h)))
        elif hmax < h <= 10 * hmax and w >= 3:          # 几行字被竖线、边框连成了一块：按行切开
            sub = m[y:y + h, x:x + w] * (lab[y:y + h, x:x + w] == i)
            boxes += _split_rows(sub, x, y, hmin, hmax)
    return sorted(boxes, key=lambda b: (b[1], b[0]))


def _split_rows(sub, x0, y0, hmin, hmax):
    """一块太高的连通域按横向投影的空隙切成一行一行（每行再按有笔画的列定左右）"""
    import numpy as np
    prof = sub.sum(axis=1).astype(float)
    if prof.max() <= 0:
        return []
    out = []
    for a, b in _runs(prof, 0.12 * prof.max(), 2):
        if not hmin <= b - a <= hmax:
            continue
        cols = np.nonzero(sub[a:b].sum(axis=0) > 0)[0]
        if len(cols):
            out.append((int(x0 + cols[0]), int(y0 + a), int(x0 + cols[-1] + 1), int(y0 + b)))
    return out


def read_region_seg(img, region, upscale=None, pad=3, variants=("raw", "inv")):
    """切块 + 逐块识别（比整块检测稳定得多）。返回 [(文字, (x, y), 字高)]"""
    import numpy as np
    from PIL import Image
    W, H = img.size
    l, t, r, b = region
    crop = img.crop((int(l * W), int(t * H), int(r * W), int(b * H)))
    rec = _recognize()
    out = []
    for x0, y0, x1, y1 in segment(crop, H):
        up = upscale or max(1, round(SEG_TARGET_PX / max(1, y1 - y0)))
        piece = crop.crop((max(0, x0 - pad), max(0, y0 - pad),
                           min(crop.width, x1 + pad), min(crop.height, y1 + pad)))
        piece = piece.resize((piece.width * up, piece.height * up), Image.LANCZOS)
        best = ("", 0.0)
        vs = list(variants)
        if np.median(np.asarray(piece)) > 170 and "stretch" not in vs:
            vs.append("stretch")          # 亮背景（雪地）上的白字：把比背景亮的部分拉开对比度，转成白底黑字
        for v in vs:
            arr = np.asarray(piece)
            if v == "stretch":
                g = arr.max(axis=2).astype(float)
                lo_, hi_ = np.percentile(g, 50), np.percentile(g, 99.5)
                g = np.clip((g - lo_) / max(1.0, hi_ - lo_) * 255, 0, 255)
                arr = np.stack([255 - g] * 3, axis=2).astype("uint8")
            elif v == "inv":
                g = arr.max(axis=2).astype(float)
                g = np.clip(g / max(1, np.percentile(g, 99)) * 255, 0, 255)
                arr = np.stack([255 - g] * 3, axis=2).astype("uint8")
            txt, sc = rec(np.ascontiguousarray(arr))
            if sc > best[1]:
                best = (txt, sc)
            if sc >= LAZY_SCORE and txt.strip():
                break                     # 1.6.71：原图就认得很有把握，不用再换底色认一遍（省一半时间）
        if best[0].strip():
            out.append((best[0], ((x0 + x1) / 2, (y0 + y1) / 2), y1 - y0, (x0, y0, x1, y1)))
    return out


LAZY_SCORE = 0.93


def read_box(img, box, up=2):
    """1.6.71：已知面板大概在哪（box，整屏坐标）：整块交给 OCR 的「检测 + 识别」读。
    亮背景（雪地、雾、沙地）上切块容易切不出字，检测模型照样找得到；整块一次读完也比逐块认快（约 0.2–0.4 秒）。
    先认原图；读不全再认拉开对比度的反色图、只留笔画的顶帽图，几次读到的拼起来（各项取先读到的，成分取加起来接近 100% 的那次）。
    返回 (文字行, 扫描结果, 文字块)"""
    import numpy as np
    from PIL import Image
    from .parse import rows, parse_scan
    x0, y0, x1, y1 = box
    crop = img.crop(box)
    c = crop.resize((crop.width * up, crop.height * up), Image.LANCZOS)
    reads = []
    for mode in ("raw", "inv", "tophat"):
        arr = _variant(np.asarray(c), mode, up)
        items = _left_trim(_det_items(_ocr()(np.ascontiguousarray(arr)), up, x0, y0))
        lines = _det_rows(items)
        s = parse_scan(lines)
        reads.append((lines, s, items))
        for r in reads:                       # 先读的优先；缺品质的行用别的预处理读到的同一行（百分比一样）补上
            _fill_quality(r[1], [o[1] for o in reads if o is not r])
            if r[1].valid:
                return r
        merged = _merge([r[1] for r in reads])
        if merged.valid:
            return reads[0][0], merged, reads[0][2]
    return reads[0]


def _det_rows(items):
    """检测结果分行。驾驶位转头看时面板是斜的（右边一列比左边高 / 低半行以上），框本身却是正的，
    所以试一组斜率，把中心 y 按 y - k·x 摆正：取「成行的多、两行挤成一行（同一列上下两个字在一行里）的少」的那个。
    同一行：摆正后中心 y 相差不到半个字高（按字高的中位数）"""
    if not items:
        return []
    hs = sorted(i[2] for i in items)
    tol = 0.55 * hs[len(hs) // 2]

    def group(k):
        its = sorted(items, key=lambda i: i[1][1] - k * i[1][0])
        groups = [[its[0]]]
        for it in its[1:]:
            last = groups[-1][-1]
            if abs((it[1][1] - k * it[1][0]) - (last[1][1] - k * last[1][0])) <= tol:
                groups[-1].append(it)
            else:
                groups.append([it])
        return groups

    def score(groups):
        sc = 0
        for g in groups:
            if len(g) >= 2:
                sc += 1
            for a_ in range(len(g)):                         # 同一列上下两个字被并进一行：扣分
                for b_ in range(a_ + 1, len(g)):
                    A, B = g[a_][3], g[b_][3]
                    if min(A[2], B[2]) - max(A[0], B[0]) > 0.3 * min(A[2] - A[0], B[2] - B[0]):
                        sc -= 2
        return sc

    from .parse import parse_scan, _tiers

    def lines_of(groups):
        return [" ".join(t[0] for t in sorted(g, key=lambda t: t[1][0])) for g in groups]

    def meaning(lines):
        """按这个斜率分行后读得通的程度：成分行的品质正好是这种矿的一档（行没错位）最要紧"""
        sc = parse_scan(lines)
        ok = sum(1 for n, _, q in sc.composition if n and q and q in (_tiers(n) or ()))
        return 3 * ok + 2 * sc.valid

    cands = {}
    for k in range(-20, 21):
        g = group(k / 100)
        cands[k] = (score(g), g)
    top = sorted(cands, key=lambda k: (cands[k][0], -abs(k)), reverse=True)[:8]   # 结构上像样的几个斜率里，挑读得通的
    best = max(top, key=lambda k: (meaning(lines_of(cands[k][1])), cands[k][0], -abs(k)))
    return lines_of(cands[best][1])


def _variant(arr, mode, up):
    import numpy as np
    if mode == "raw":
        return arr
    a = arr.astype(np.float32)
    if mode == "inv":
        g = a.max(axis=2)
        lo_, hi_ = np.percentile(g, 50), np.percentile(g, 99.5)
        g = np.clip((g - lo_) / max(1.0, hi_ - lo_) * 255, 0, 255)
        return np.stack([255 - g] * 3, axis=2).astype("uint8")
    R, G, B = a[..., 0], a[..., 1], a[..., 2]                  # 顶帽：只留比周围亮 / 暖的细笔画，转成白底黑字
    se = 7 * up // 2 * 2 + 1
    lo = np.minimum(np.minimum(R, G), B)
    warm = np.maximum(R - B, (G - B) * 2.5)
    th = np.maximum(_tophat(lo, se), _tophat(warm, se) * 0.8)
    th = np.clip(th / max(1.0, np.percentile(th, 99.5)) * 255, 0, 255)
    return np.stack([255 - th] * 3, axis=2).astype("uint8")


def _left_trim(items):
    """面板的标签和成分百分比都从同一列开始：整个落在这一列左边的字（勘探者驾驶舱的「光强度」读数）不是面板上的，
    混进来会把成分行拼坏（「光强度 30.79% 原矿 298」）"""
    import statistics
    col = [i for i in items if _LABEL.search(i[0]) or _PCT.search(i[0])]
    if len(col) < 3:
        return items
    hh = statistics.median(i[2] for i in col)
    left = statistics.median(i[3][0] for i in col)
    return [i for i in items if i[3][2] > left + 0.5 * hh]


def _fill_quality(s, others):
    """有一行的品质没读到（「52.57% 铁原矿」后面的 325 没检测出来）：别的预处理读到的同一行（百分比一样）有品质、而且说法一致，就补上"""
    if not any(q is None for n, _, q in s.composition if n and n != "Inert Materials"):
        return
    got = {}
    for o in others:
        for n, p, q in o.composition:
            if q is not None:
                got.setdefault(round(p, 2), set()).add(q)
    s.composition = [(n, p, q if q is not None or not n or n == "Inert Materials" or len(got.get(round(p, 2), ())) != 1
                      else next(iter(got[round(p, 2)]))) for n, p, q in s.composition]


def _merge(scans):
    """同一帧换几种预处理读到的结果拼起来：每一项取最先读到的；成分取加起来接近 100% 的那次（都不是就取最长的）"""
    from .parse import Scan
    out = Scan()
    for f in ("rock", "mass", "resistance", "instability", "total_scu", "difficulty"):
        vals = [getattr(s, f) for s in scans]
        # 原图读到的直接用；换了预处理才读到的，要两种预处理读得一样才算（宁可这帧不出，也不拼一个错的数）
        v = vals[0] if vals[0] is not None else next((x for x in vals[1:] if x is not None and vals[1:].count(x) >= 2), None)
        setattr(out, f, v)
    good = [s.composition for s in scans if s.composition and abs(sum(p for _, p, _ in s.composition) - 100) <= 2]
    out.composition = good[0] if good else max((s.composition for s in scans), key=len, default=[])
    from .parse import _fix_by_tiers
    out.composition = _fix_by_tiers(out.composition, out.rock)     # 和单次读一样，按品质档位补矿名
    return out


def _det_items(res, up, ox, oy):
    """OCR 检测结果 → [(文字, 中心, 字高, 框)]，整屏坐标。驾驶位转头看时面板是斜的（每行右边比左边低一截），
    按检测框上沿的斜率把中心的 y 摆正，同一行的字才分得到一起"""
    import statistics
    raw = []
    for quad, text, conf in res:
        xs = [p[0] / up for p in quad]
        ys = [p[1] / up for p in quad]
        w = max(xs) - min(xs)
        slope = (quad[1][1] - quad[0][1]) / max(1e-6, quad[1][0] - quad[0][0])
        raw.append((text, sum(xs) / 4, sum(ys) / 4, max(ys) - min(ys), w, slope,
                    (min(xs) + ox, min(ys) + oy, max(xs) + ox, max(ys) + oy)))
    wide = [r[5] for r in raw if r[4] > 3 * max(1.0, r[3])]
    k = statistics.median(wide) if len(wide) >= 3 else 0.0
    if abs(k) < 0.02:
        k = 0.0
    out = []
    for text, cx, cy, h, w, _s, b in raw:
        h_true = h - abs(k) * w if k else h
        out.append((text, (cx + ox, cy + oy - k * cx), max(1.0, h_true), b))
    return out


def clusters(items):
    """把文字块按距离聚成面板：横向间隔 < 9 个字高、纵向间隔 < 3 个字高算同一面板"""
    import statistics
    if not items:
        return []
    h = statistics.median(it[2] for it in items) or 10
    n = len(items)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        ax0, ay0, ax1, ay1 = items[i][3]
        for j in range(i + 1, n):
            bx0, by0, bx1, by1 = items[j][3]
            dx = max(0, max(ax0, bx0) - min(ax1, bx1))
            dy = max(0, max(ay0, by0) - min(ay1, by1))
            if dx < 9 * h and dy < 3 * h:
                parent[find(i)] = find(j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(items[i])
    return list(groups.values())


def grab():
    """整屏截图；悬浮窗盖住的那块涂黑，不会读到悬浮窗自己的字"""
    from ..core.perf import grab_screen
    img = grab_screen()
    try:
        from ..app import bus
        bus.update_preview(img, source="live")
    except Exception:
        pass
    return img


def find_panels(img):
    """返回 (扫描面板的文字行, 货舱面板的文字行)。
    驾驶位的扫描面板中间有一大段空白，会被分成上下两个聚类（数值一块、成分一块），这里再拼回去"""
    import re
    import statistics
    from .parse import rows
    LAST_PANEL.clear()
    items = read_region_seg(img, SEARCH)
    if not items:
        return [], []
    h = statistics.median(it[2] for it in items) or 10
    def describe(g):
        text = " ".join(rows(g))
        box = (min(i[3][0] for i in g), min(i[3][1] for i in g),
               max(i[3][2] for i in g), max(i[3][3] for i in g))
        labs = [i[3][0] for i in g if re.search(r"扫描|质量|抗性|稳定|定性|组成", i[0])]
        return dict(
            items=g, text=text, box=box, left=min(labs) if labs else box[0],    # 标签那一列的左边（不算左边挨着的速度表）
            bag=(bool(re.search(r"\d[.,]\d+\s*/\s*\S*\d", text)) or "货舱" in text) and "SC" in text.upper(),
            comp=len(re.findall(r"\d{1,3}[.,]\d{2}\s*%?", text)) + 2 * ("组成" in text or "SCU" in text.upper()),
            top=sum(k in text for k in ("质", "抗", "稳定", "扫描")))
    info = [describe(g) for g in clusters(items)]
    bag = next((c for c in info if c["bag"]), None)
    if bag is not None and bag["top"] >= 2 and bag["comp"] >= 2:
        # 1.6.71：扫描面板和下面的货舱连成了一个聚类（Golem 太空样本，五种成分的面板一直拉到货舱）：
        # 「货舱」那一行及以下归货舱，上面的还是扫描面板
        ys = [i[3][1] for i in bag["items"] if re.search(r"货舱|\d\s*/\s*\d", i[0])]
        if ys:
            cut = min(ys) - 0.5 * h
            upper = [i for i in bag["items"] if i[3][3] <= cut]
            lower = [i for i in bag["items"] if i[3][3] > cut]
            info.remove(bag)
            if upper:
                info.append(describe(upper))
            bag = describe(lower) if lower else None
            if bag:
                info.append(bag)
    rest = [c for c in info if c is not bag]
    comp = max(rest, key=lambda c: c["comp"] + c["top"], default=None)
    if comp is None:
        return [], rows(bag["items"]) if bag else []
    chosen = comp["items"]
    if comp["top"] < 2:      # 上半部分（质量/抗性/不稳定性）在另一个聚类里，找左边对齐、紧挨在上面的那块
        # 按标签列对齐（下半截常把左边的速度表「0.00 SCU/S」也聚进来，整块的左边就不准了）
        cands = [c for c in rest if c is not comp and c["top"] >= 2
                 and abs(c["left"] - comp["left"]) < 4 * h
                 and 0 <= comp["box"][1] - c["box"][3] < 15 * h]
        if cands:
            chosen = max(cands, key=lambda c: c["top"])["items"] + chosen
    chosen = _panel_only(chosen, h)
    _note_panel(img, chosen)
    return rows(chosen), rows(bag["items"]) if bag else []


LAST_PANEL = {}       # 最近一帧认到的扫描面板在屏幕上的位置：{box, cut（顶着屏幕右边）, h（字高）}


def _note_panel(img, items):
    """记下面板在哪：读不全时用来判断原因（被屏幕右边挡住、字有色差重影）"""
    import statistics
    if not items:
        return
    W, H = img.size
    ox, oy = int(SEARCH[0] * W), int(SEARCH[1] * H)
    x0 = ox + min(i[3][0] for i in items)
    y0 = oy + min(i[3][1] for i in items)
    x1 = ox + max(i[3][2] for i in items)
    y1 = oy + max(i[3][3] for i in items)
    LAST_PANEL.update(box=(x0, y0, x1, y1), cut=x1 >= W - max(4, round(W * 0.004)),
                      h=statistics.median(i[2] for i in items))


def chroma_shift(img, box, r=2):
    """这块画面里红、蓝通道相对绿色错开几个像素（游戏开着「色差」时字边上有红蓝重影，小字就认不准）。
    2026-10-23 用户反馈：1080p 勘探者驾驶舱，红、蓝各错开 1 像素，「贝沙电气石原矿」认成「贝莎电气有#」"""
    import numpy as np
    a = np.asarray(img.crop(box).convert("RGB")).astype(np.float32)
    h, w = a.shape[:2]
    if h < 2 * r + 8 or w < 2 * r + 8:
        return 0
    G = a[r:h - r, r:w - r, 1]
    G = G - G.mean()
    ng = float(np.sqrt((G * G).sum())) or 1.0
    worst = 0
    for ch in (0, 2):
        best = (-2.0, 0)
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                X = a[r + dy:h - r + dy, r + dx:w - r + dx, ch]
                X = X - X.mean()
                c = float((X * G).sum()) / ((float(np.sqrt((X * X).sum())) or 1.0) * ng)
                if c > best[0]:
                    best = (c, max(abs(dx), abs(dy)))
        worst = max(worst, best[1])
    return worst


def miss_reason(img):
    """面板在、却读不全时，看看是什么原因（给玩家的提示）：cut 被屏幕右边挡住 / ca 字有色差重影；看不出来返回 None"""
    if not LAST_PANEL:
        return None
    if LAST_PANEL.get("cut"):
        return "cut"
    try:
        if chroma_shift(img, LAST_PANEL["box"]) >= 1:
            return "ca"
    except Exception:
        pass
    return None


def _panel_only(items, h):
    """去掉面板左边挨着的别的 HUD 读数（勘探者驾驶舱里 "质量" 左边就是速度/距离表的 "0.0"、"28.2"）：
    面板的字都从标签那一列开始，整个落在标签列左边的块不要"""
    import re
    labels = [i for i in items if re.search(r"扫描|质量|抗性|稳定|组成", i[0])]
    if not labels:
        return items
    left = min(i[3][0] for i in labels)
    return [i for i in items if i[3][2] > left + 0.5 * h]


LAST_RAW = {"t": 0.0, "scan": [], "bag": []}      # 最近一帧 OCR 出来的原文（问题反馈时一起打包）


PANEL_CACHE = {"win": None, "t": 0.0, "size": None}
CACHE_SECONDS = 30      # 上一次读全的面板位置记这么久：下一帧先只读那一块（约 0.3 秒），读不全再整片找


def _panel_items(items):
    """检测结果里属于扫描面板 / 货舱的字（标签、百分比、SCU、数字），用来定面板的框"""
    import re
    return [i for i in items if re.search(r"扫描|结果|质量|抗性|稳定|定性|组成|货舱|\d[.,]\d{2}|SCU|\d{3,}|%", i[0])]


def _window(img, box, h, below=10):
    """面板框往外扩一圈，作为下一次只读这一块的范围（下面多留一截把货舱带上）"""
    W, H = img.size
    x0, y0, x1, y1 = box
    h = h or H * 0.009
    return (max(int(SEARCH[0] * W), int(x0 - 3 * h)), max(int(SEARCH[1] * H), int(y0 - 3 * h)),
            min(W, int(x1 + 3 * h)), min(int(SEARCH[3] * H), int(y1 + below * h)))


def _guess_window(img):
    """整片找没读全、但找到了面板的一部分（LAST_PANEL）：按面板大约 20 字宽、30 字高往外扩"""
    W, H = img.size
    x0, y0, x1, y1 = LAST_PANEL["box"]
    h = LAST_PANEL.get("h") or H * 0.009
    return (max(int(SEARCH[0] * W), int(x0 - 3 * h)), max(int(SEARCH[1] * H), int(y0 - 14 * h)),
            min(W, int(max(x1, x0 + 20 * h) + 3 * h)), min(int(SEARCH[3] * H), int(y1 + 14 * h)))


LOCATE_UP = 1.5     # 整片找面板时放大多少：1.5 倍时驾驶位的小字（地表、远一点的面板）也找得到，约 0.45 秒
_LABEL = re.compile(r"扫描|结果|质量|抗性|稳定|定性|组成|货舱")
_PCT = re.compile(r"\d[.,]\d{2}\s*%")


def _locate(img, up=1.0):
    """整片搜索区过一遍检测 + 识别（不放大，约 0.3 秒）。返回 (面板读取范围或 None, 画面里像不像有面板)。
    面板的标签（扫描结果 / 质量 / 抗性 / 组成 / 货舱）和成分百分比都从同一列开始：先找出这一列，
    读取范围只取这一列往右约 25 个字宽，免得把左边别的 HUD 读数（「能量传输抗性 0.00」）混进来"""
    import numpy as np
    import statistics
    from PIL import Image
    W, H = img.size
    l, t, r, b = SEARCH
    ox, oy, bottom_lim = int(l * W), int(t * H), int(b * H)
    crop = img.crop((ox, oy, int(r * W), bottom_lim))
    if up != 1:
        crop = crop.resize((int(crop.width * up), int(crop.height * up)), Image.LANCZOS)
    items = _det_items(_ocr()(np.ascontiguousarray(np.asarray(crop))), up, ox, oy)
    labels = [i for i in items if _LABEL.search(i[0])]
    pct = [i for i in items if _PCT.search(i[0])]
    scu = [i for i in items if "SCU" in i[0].upper() and not _LABEL.search(i[0])]
    seen = bool(labels or pct or scu)
    cand = labels + pct
    if len(cand) + len(scu) < 2 or not cand:
        return None, seen
    h = statistics.median(i[2] for i in cand + scu) or H * 0.009
    xs = [i[3][0] for i in cand]
    L = max(xs, key=lambda x: sum(abs(x - y) < 3 * h for y in xs))
    col = sorted([i for i in cand if abs(i[3][0] - L) < 3 * h] +
                 [i for i in scu if L < i[3][0] < L + 26 * h], key=lambda i: i[3][1])
    # 同一块面板上下挨着（间隔不到 10 个字高）；取字最多的那一段
    runs, cur = [], [col[0]]
    for a, b2 in zip(col, col[1:]):
        if b2[3][1] - a[3][3] < 10 * h:
            cur.append(b2)
        else:
            runs.append(cur)
            cur = [b2]
    runs.append(cur)
    g = max(runs, key=len)
    if len(g) < 2:
        return None, seen
    title = [i for i in g if "扫描" in i[0] or "结果" in i[0]]
    cargo = [i for i in g if "货舱" in i[0] or re.search(r"\d[.,]\d{2}\s*/", i[0])]
    y0 = min(i[3][1] for i in g)
    y1 = max(i[3][3] for i in g)
    top = min(i[3][1] for i in title) - 2 * h if title else y0 - 12 * h
    bot = max(i[3][3] for i in cargo) + 2 * h if cargo else y1 + 14 * h
    win = (max(ox, int(L - 3 * h)), max(oy, int(top)), min(W, int(L + 25 * h)), min(bottom_lim, int(bot)))
    return win, seen


def _split_bag(lines):
    """整块读出来的行 → (扫描面板的行, 货舱的行)：从「货舱 / 0.00/96.00 SCU」那行起算货舱"""
    import re
    for i, ln in enumerate(lines):
        if "货舱" in ln or re.search(r"\d[.,]\d{2}\s*/\s*\d", ln):
            return lines[:i], lines[i:]
    return lines, []


def _use_det(img, r, cache=True):
    """整块读的结果记下来：面板位置（LAST_PANEL、下一帧的读取范围；没读全的 cache=False，只记位置）"""
    import statistics
    import time as _t
    lines, scan, items = r
    pi = _panel_items(items) or items
    col = [i for i in items if _LABEL.search(i[0]) or _PCT.search(i[0])]
    if col:                                   # 只算标签那一列往右的字（左边别的 HUD 读数不算进面板的框）
        hh = statistics.median(i[2] for i in col)
        left = statistics.median(i[3][0] for i in col) - 3 * hh
        pi = [i for i in pi if i[3][0] >= left] or pi
    W, H = img.size
    box = (min(i[3][0] for i in pi), min(i[3][1] for i in pi), max(i[3][2] for i in pi), max(i[3][3] for i in pi))
    h = statistics.median(i[2] for i in pi)
    LAST_PANEL.update(box=tuple(int(v) for v in box), cut=box[2] >= W - max(4, round(W * 0.004)), h=h)
    if cache:
        PANEL_CACHE.update(win=_window(img, box, h), t=_t.time(), size=img.size)
    return _split_bag(lines)


def _wider(img, win):
    """整块读没读全时再试一次的范围：往上、往右多放一些（面板右半边的品质、上面的标题被切在外面的时候）"""
    W, H = img.size
    x0, y0, x1, y1 = win
    w, h = x1 - x0, y1 - y0
    return (max(int(SEARCH[0] * W), int(x0 - 0.1 * w)), max(int(SEARCH[1] * H), int(y0 - 0.25 * h)),
            min(W, int(x1 + 0.8 * w)), min(int(SEARCH[3] * H), int(y1 + 0.05 * h)))


LAST_PATH = {"path": None}    # 这一帧是哪条路读出来的（调试 / 打分用）


def analyse(img):
    """读一帧：先只读上次面板所在的那一块（1.6.71，快）；没有或读不全就整片找；整片找也没读全、
    但找到了面板的一部分（雪地、雾里常见），再把那一块交给整块检测读一遍"""
    import time as _t
    from .parse import parse_scan, parse_bag
    scan_lines = bag_lines = None
    det_scan = None
    LAST_PATH["path"] = "none"
    c = PANEL_CACHE
    if c["win"] and c["size"] == img.size and _t.time() - c["t"] < CACHE_SECONDS:
        r = read_box(img, c["win"])
        if r and r[1].valid:
            LAST_PANEL.clear()
            scan_lines, bag_lines = _use_det(img, r)
            det_scan = r[1]
            LAST_PATH["path"] = "cache"
        else:
            c["win"] = None
    if scan_lines is None:
        # 1.6.71：先用 OCR 的检测模型把整片搜索区过一遍（约 0.3 秒），按「扫描结果 / 质量 / 组成 / SCU」这些字定出面板，
        # 再把面板那一块放大读；找不到这些字、也没有成分百分比，就当画面里没有面板（不再逐块认，省时间）
        # （2026-10-26 试过「先按原尺寸找、有迹象才放大找」：140 张样本打分 4 张退步、整体反而慢 18%，已撤回）
        win, seen = _locate(img, LOCATE_UP)
        if win:
            r = read_box(img, win)
            if not (r and r[1].valid):
                # 没读全：放大范围再读一次就停。以前接着走老的逐块认（约 1 秒）和猜范围再读（约 3 秒），
                # 识别样本 90 张里老路一张都没读出来，读不出的帧却要等 7 秒左右（1.6.71）
                r2 = read_box(img, _wider(img, win))
                if r2 and r2[1].valid:
                    r = r2
                    LAST_PATH["path"] = "wide"
            else:
                LAST_PATH["path"] = "locate"
            LAST_PANEL.clear()
            if r and r[1].valid:
                scan_lines, bag_lines = _use_det(img, r)
                det_scan = r[1]
            elif r and r[2]:
                # 面板在、读不全：照样记下面板位置（被屏幕右边挡住的提示、只读质量抗性的破碎方案要用）
                scan_lines, bag_lines = _use_det(img, r, cache=False)
            else:
                scan_lines, bag_lines = [], []
        elif not seen:
            LAST_PANEL.clear()
            scan_lines, bag_lines = [], []
    if scan_lines is None:
        scan_lines, bag_lines = find_panels(img)
        s = parse_scan(scan_lines)
        LAST_PATH["path"] = "seg" if s.valid else "none"
        if s.valid and LAST_PANEL.get("box"):
            PANEL_CACHE.update(win=_window(img, LAST_PANEL["box"], LAST_PANEL.get("h")), t=_t.time(), size=img.size)
        elif LAST_PANEL.get("box") and (scan_lines or bag_lines):
            r = read_box(img, _guess_window(img))
            if r and r[1].valid:
                scan_lines, bag_lines = _use_det(img, r)
                det_scan = r[1]
                LAST_PATH["path"] = "guess"
    if scan_lines or bag_lines:
        LAST_RAW.update(t=_t.time(), scan=list(scan_lines), bag=list(bag_lines))
    try:                                    # 矿袋容量按现在选的船（MOLE 96、勘探者和魔像 32）
        from .laser import current_ship
        from .data import SHIPS
        cap = float(SHIPS[current_ship()]["bag"])
    except Exception:
        cap = 96.0
    return det_scan or parse_scan(scan_lines), parse_bag(bag_lines, cap)


def panel_seen(scan, raw=None):
    """画面里真有扫描面板吗：读全了，或者至少一行「质量：12431」这种「标签 + 数字」，或者至少两行带矿名的成分。
    只读到零散数字不算：勘探者驾驶舱右边的高度表、气压（0.40、76m、0.646MPa）会被拼成「质量 0.7、抗性 76」；
    只有字没有数字也不算：屏幕上别的窗口（聊天、文档）里的「扫描」「稳定性测试」（2026-10-23 自动留图里看到的）。
    以前这两种都会被当成面板开着：信号识别整段暂停、画面不动也不停地识别"""
    import re
    if scan.valid:
        return True
    labeled = any(re.search(r"(质量|抗性|稳定性|定性)[:：]?\d", x.replace(" ", "")) for x in (raw or ()))
    named = sum(1 for n, *_ in scan.composition if n)
    return labeled or named >= 2


def report(scan, bag):
    """控制台打印完整结果；返回给悬浮窗用的简短文字"""
    from ..core.i18n import mineral_zh
    from .laser import recommend
    from .data import best_price
    print("\n" + "=" * 60)
    rock = mineral_zh(scan.main_mineral) if scan.main_mineral else "?"
    diff = f"｜游戏评级：{scan.difficulty}" if scan.difficulty else ""
    print(f"{rock}｜质量 {scan.mass:,.0f} kg｜抗性 {scan.resistance:g}%｜不稳定性 {scan.instability:g}{diff}")
    hud = [f"{rock}｜{scan.mass:,.0f} kg｜抗性 {scan.resistance:g}%｜不稳定 {scan.instability:g}"]
    from .refinery import refined_plan
    from ..core.i18n import method_zh, station_zh
    minerals = {k: v for k, v in scan.minerals_scu().items() if k not in ("Inert Materials", "?")}
    if minerals:
        print("  成分：" + "，".join(f"{mineral_zh(k)} {v:.2f} SCU" for k, v in minerals.items()))
        for n_, (method, station, value, rscu, fee, hours) in enumerate(refined_plan(minerals)):
            if n_ == 0:
                hud.append(f"精炼后值 {value:,.0f} aUEC（建议：{method_zh(method)}，{station_zh(station)}精炼）")
            print(f"  精炼后净值 ≈ {value:,.0f} aUEC｜{method_zh(method)} @ {station_zh(station)}"
                  f"｜得 {rscu:.2f} SCU，精炼费 {fee:,.0f}，约 {hours:.1f} 小时")
        sells = "，".join(f"{mineral_zh(k)}→{best_price(k)[1] or '无收购'}" for k in minerals)
        print(f"  卖到：{sells}")
        try:
            from ..crafting.crafting import quality_hints
            for h in quality_hints(scan.composition):
                print("  制造：" + h)
        except Exception as e:        # 制造数据缺失不影响读屏
            print(f"  （制造提示出错：{e}）")
    plans = recommend(scan.mass, scan.resistance, scan.instability)
    for i, p in enumerate(plans, 1):
        print(f"  {i}. {p.summary()}")
    if plans:
        hud.insert(1, plans[0].short())
    contents, used, cap = bag
    bag_text = ""
    if used is not None:
        print(f"矿袋 {used:g}/{cap:g} SCU：" + "，".join(f"{mineral_zh(k)} {v:g}" for k, v in contents.items()))
        bag_text = f"{used:g}/{cap:g} SCU\n" + "，".join(f"{mineral_zh(k)} {v:g}" for k, v in contents.items())
    return "\n".join(hud), bag_text


def main():
    if len(sys.argv) > 1:
        from PIL import Image
        from .parse import rows
        img = Image.open(sys.argv[1]).convert("RGB")
        print(f"截图尺寸 {img.size}")
        scan_lines, bag_lines = find_panels(img)
        print("--- 扫描面板 ---")
        for line in scan_lines:
            print("  " + line)
        print("--- 货舱面板 ---")
        for line in bag_lines:
            print("  " + line)
        scan, bag = analyse(img)
        print("--- 解析结果 ---")
        print(scan, bag, sep="\n")
        print("自检：" + ("通过" if scan.valid else f"不通过（成分合计 {sum(p for _, p, _ in scan.composition):.2f}%）"))
        if scan.complete:
            report(scan, bag)
        return
    live()


def _same_rock(a, b):
    """是不是同一块石头：质量差 1% 以内，抗性也对得上（只看质量的话，两块差不多重的石头会混进同一个投票队列）"""
    if not (a.mass and b.mass and abs(a.mass - b.mass) / b.mass < 0.01):
        return False
    if a.resistance is not None and b.resistance is not None and abs(a.resistance - b.resistance) > 2:
        return False
    return True


def live():
    """实时读屏。同一块石头连续多帧投票，结果稳定了才输出一次；识别记录写进 userdata/logs/live_log.txt，
    每块新石头的画面存进 userdata/shots/live/，方便之后排查"""
    import collections
    from pathlib import Path
    from ..core import paths
    root = paths.ROOT
    shots = paths.shots("live")
    log = open(paths.log("live_log.txt"), "a", encoding="utf-8")
    recent = collections.deque(maxlen=VOTE_FRAMES)
    from ..app.overlay import hud
    ov = hud()
    print("读屏中… 在采矿模式下扫描石头即可。按 Ctrl+C 退出")
    if ov.ok:
        print("结果也会显示在右上角悬浮窗（游戏要用无边框窗口模式；按住可拖动，双击暂时隐藏）")
    try:
        _live_loop(root, shots, log, recent, ov)
    finally:
        for k in ("信号", "扫描", "矿袋"):
            ov.clear(k)


def _live_loop(root, shots, log, recent, ov):
    last_key = None
    sig_prev, sig_shown = None, None
    while True:
        img = grab()
        # 雷达信号：连续两帧看到同一组信号才输出，变了再输出
        try:
            from .signals import find_signatures, describe_all
            sigs = frozenset(v for v, *_ in find_signatures(img))
            if sigs and sigs == sig_prev and sigs != sig_shown:
                sig_shown = sigs
                print("\n" + "-" * 60)
                lines = describe_all(find_signatures(img))
                for line in lines:
                    print("  " + line)
                ov.set("信号", "\n".join(l.split("｜精炼后")[0].replace("信号 ", "") for l in lines[:4]))
                log.write(f"{time.strftime('%F %T')} SIG {sorted(sigs)}\n")
                log.flush()
            sig_prev = sigs
        except Exception as e:
            print(f"（信号识别出错：{e}）")
        scan, bag = analyse(img)
        if not scan.valid:
            ov.sleep(INTERVAL)
            continue
        enqueue_rock(recent, scan, bag)
        if len(recent) < 2:
            ov.sleep(INTERVAL)
            continue
        best, stable = vote([r[0] for r in recent])
        key = (round(best.mass), best.resistance, best.instability)
        if stable and key != last_key:
            last_key = key
            stamp = time.strftime("%H%M%S")
            text, bag_text = report(best, recent[-1][1])
            ov.set("扫描", text)
            if bag_text:
                ov.set("矿袋", bag_text)
            log.write(f"{time.strftime('%F %T')} {best} {recent[-1][1]}\n")
            log.flush()
            try:
                img.save(shots / f"{stamp}.png")
                old = sorted(shots.glob("*.png"))[:-20]   # 只留最近 20 张
                for f in old:
                    f.unlink()
            except OSError:
                pass
        ov.sleep(INTERVAL)




def _mode(vals):
    """出现次数最多的值（忽略 None）。返回 (值, 次数)"""
    import collections
    c = collections.Counter(v for v in vals if v is not None)
    return c.most_common(1)[0] if c else (None, 0)


def _pick(vals):
    """一簇读数的代表值：簇里出现最多的那个实际读数，并列时取离中位数最近的（再并列取小的）。
    不取平均：抗性两帧 20 / 21 平均成 20.5、百分比 45.22 / 45.27 平均成 45.245，面板上根本没有这个数（1.6.43）"""
    import collections
    vals = sorted(vals)
    mid = len(vals) // 2
    med = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
    c = collections.Counter(vals)
    return min(c, key=lambda x: (-c[x], abs(x - med), x))


def _consensus(vals, rel=None, abs_=None):
    """数值字段的多帧投票。同一块石头的真值不变，帧间差异全是 OCR 抖动，所以把相差
    不超过容差的读数聚成一簇，取最大簇的代表值（_pick：簇里实际读到过的数）——对个别离群帧免疫（质量少认一位
    数字差 10 倍以上，自成一簇被丢掉）。容差两种：rel=相对比例（质量、总 SCU），
    abs_=绝对值（抗性、不稳定性）。返回 (代表值, 簇大小)；没有读数返回 (None, 0)。
    2026-10-24 改进：以前要求逐位完全一致，末位抖一抖（质量 12431 / 12437）就永远
    投不出稳定结果（采矿助手一直不出结果，日志记 MISS 读不稳）"""
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None, 0
    best, best_n = [], 0
    for v in vals:
        if rel is not None:
            group = [x for x in vals if abs(x - v) <= max(rel * abs(v), 1e-9)]
        else:
            group = [x for x in vals if abs(x - v) <= abs_]
        if len(group) > best_n:
            best, best_n = group, len(group)
    return _pick(best), best_n


def _row_consensus(cands):
    """同一成分行在多帧里的读数投票。矿名和百分比必须同帧出现（不能跨帧拼合出一个
    其实没出现过的组合，Codex 复审 2026-10-23）；百分比按 ±0.35 聚类，容忍末位数字
    抖动（23.42 / 23.47 / 23.44 是同一行，23.42 / 28.42 不是）。
    返回 (矿名, 百分比代表值（_pick：实际读到过的数）, 品质, 簇大小)；没有读数返回 (None, None, None, 0)"""
    pool = [c for c in cands if c[1] is not None]
    best = (None, None, None, 0)
    for name, pct, _q in pool:
        group = [c for c in pool if c[0] == name and abs(c[1] - pct) <= 0.35]
        if len(group) > best[3]:
            best = (name, _pick([c[1] for c in group]), _mode(c[2] for c in group)[0], len(group))
    return best


def vote(scans):
    """每个字段多帧投票；成分逐行投票。返回 (结果, 是否稳定)
    稳定 = 质量、抗性、不稳定性、总 SCU 和每一行成分（矿名 + 百分比）都至少两帧读数
    一致（数值字段按容差聚类取中位数，见 _consensus），投票结果本身也要通过自检
    （成分合计约 100%）——成分没读稳就不出结果"""
    from .parse import Scan

    out = Scan()
    stable = True
    out.rock = _mode(s.rock for s in scans)[0]
    out.difficulty = _mode(s.difficulty for s in scans)[0]
    out.mass, n_mass = _consensus((s.mass for s in scans), rel=0.008)
    out.resistance, n_res = _consensus((s.resistance for s in scans), abs_=1.2)
    out.instability, n_ins = _consensus((s.instability for s in scans), abs_=0.3)
    out.total_scu, n_scu = _consensus((s.total_scu for s in scans), rel=0.01)
    if min(n_mass, n_res, n_ins, n_scu) < 2:
        stable = False
    lengths = _mode(len(s.composition) for s in scans)[0]
    rows_ = [s.composition for s in scans if len(s.composition) == lengths]
    out.composition = []
    for i in range(lengths or 0):
        name, pct, quality, n = _row_consensus([r[i] for r in rows_])
        if n < 2:
            stable = False
        out.composition.append((name, pct, quality))
    if not out.valid:
        stable = False
    return out, stable


def vote_partial(scans):
    """面板被屏幕挡住（总 SCU、品质读不到）时的投票：质量、抗性、不稳定性都要至少两帧
    一致（容差聚类）才算稳定；成分逐行投票，读不稳就不要成分（破碎方案只用前三个数）。
    返回 (结果, 是否稳定)"""
    from .parse import Scan

    out = Scan()
    stable = True
    out.rock = _mode(s.rock for s in scans)[0]
    out.difficulty = _mode(s.difficulty for s in scans)[0]
    out.mass, n_mass = _consensus((s.mass for s in scans), rel=0.008)
    out.resistance, n_res = _consensus((s.resistance for s in scans), abs_=1.2)
    out.instability, n_ins = _consensus((s.instability for s in scans), abs_=0.3)
    if min(n_mass, n_res, n_ins) < 2:
        stable = False
    lengths = _mode(len(s.composition) for s in scans)[0]
    rows_ = [s.composition for s in scans if len(s.composition) == lengths]
    comp = []
    for i in range(lengths or 0):
        name, pct, quality, n = _row_consensus([r[i] for r in rows_])
        if n < 2:
            comp = []
            break
        comp.append((name, pct, quality))
    out.composition = comp
    if not out.complete or (out.mass or 0) < 500 or not 0 <= (out.resistance or 0) <= 100:
        stable = False
    return out, stable


def _rock_consensus(scans):
    """质量/抗性/不稳定性的容差共识：三样都至少两帧聚成一簇才可信。返回 Scan 或 None"""
    from .parse import Scan
    mass, n1 = _consensus((s.mass for s in scans), rel=0.008)
    res, n2 = _consensus((s.resistance for s in scans), abs_=1.2)
    ins, n3 = _consensus((s.instability for s in scans), abs_=0.3)
    if min(n1, n2, n3) < 2:
        return None
    return Scan(mass=mass, resistance=res, instability=ins)


_reject = {}          # id(队列) → (队列的弱引用, 最近一帧和队列共识对不上的扫描)（在观察是不是换了石头）


def _pending(queue):
    """这条队列记下的可疑帧。按 id 存、再用弱引用核对是不是同一条队列：采矿助手停了再开，新队列可能分到
    旧队列的 id，不核对就会读到上一次留下的可疑帧，换石头早一帧判定（1.6.44）"""
    ent = _reject.get(id(queue))
    return ent[1] if ent and ent[0]() is queue else None


def _set_pending(queue, scan):
    import weakref
    for k in [k for k, (ref, _s) in _reject.items() if ref() is None]:
        del _reject[k]                        # 顺手清掉已经不在了的队列
    _reject[id(queue)] = (weakref.ref(queue), scan)


def enqueue_rock(queue, scan, bag=None):
    """把新帧放进投票队列（队列元素是 (scan, bag) 元组）。返回 True 表示换了石头、队列已清空。
    和上一帧对不上时不急着清队列：先和队列共识（≥3 帧的质量/抗性/不稳定性容差共识）比对——
    和共识一致说明上一帧是离群误读，弹掉它，保住积累的好帧；和共识不一致说明这一帧可疑，先记下
    丢掉（误读帧不占投票位）；连续两帧可疑且互相同一块石头，才是真换了石头，清空重计。
    以前一帧认错就清空队列，之后 4 帧白攒，结果迟迟出不来"""
    key = id(queue)
    cleared = False
    if not queue or _same_rock(scan, queue[-1][0]):
        _reject.pop(key, None)
        queue.append((scan, bag))
        return False
    ref = _rock_consensus([x[0] for x in queue]) if len(queue) >= 3 else None
    if ref is not None:
        if _same_rock(scan, ref):
            queue.pop()                       # 上一帧是离群误读，弹掉
            _reject.pop(key, None)
        else:
            prev = _pending(queue)
            if prev is not None and _same_rock(scan, prev):
                queue.clear()                 # 连续两帧一致的新石头：确认换石头
                _reject.pop(key, None)
                cleared = True
            else:
                _set_pending(queue, scan)     # 先观察一帧
                return False
    else:                                     # 队列太薄投不出共识：维持老行为，清空重来
        _reject.pop(key, None)
        queue.clear()
        cleared = True
    queue.append((scan, bag))
    return cleared


if __name__ == "__main__":
    main()
