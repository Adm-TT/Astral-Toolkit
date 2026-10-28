"""从游戏右上角的调试信息（控制台 r_DisplayInfo 2）直接读位置

右上角这几行是我们要的（游戏每帧都在刷新）：
  Zone: OOC_Stanton_4_Microtech Pos: 520.9152km 410.2893km 744.0843km     ← 星球自转坐标（和星图同一坐标系）
  Zone: SolarSystem_862949775749 Pos: 22462326.4853km 37186368.6338km 744.0843km   ← 星系坐标
  Zone: Root Pos: 22462326.4853km 37186368.6338km 744.0843km              ← 同上，用来核对
  Current player location : Hospital Stanton4 NewBabbage (L2 : Stanton4 NewBabbage)
做法：截右上角一块，放大后 OCR，按行找这些字段；星系坐标两行（SolarSystem 和 Root）读到一样才算数，
防止 OCR 认错一位数字。拿到的星系坐标交给 navigate.locate() 算方位。
"""
import re
import time

REGION = (0.66, 0.0, 1.0, 0.22)          # 右上角：左、上、右、下（占屏幕比例）；只截用得到的几行，识别快一半
UPSCALE = 2

_NUM = r"(-?\d[\d,]*\.?\d*)"
POS = re.compile(rf"Zone:\s*(?P<zone>.+?)\s*Pos:\s*{_NUM}\s*(?P<u1>km|m)\s*{_NUM}\s*(?P<u2>km|m)\s*{_NUM}\s*(?P<u3>km|m)", re.I)
LOC = re.compile(r"Current\s*player\s*location\s*:?\s*(?P<loc>.+)$", re.I)
CAMPOS = re.compile(rf"P\W*[lI1|]\W*an\W*[e3]t\W*Zone\s*:?\s*{_NUM}\s+{_NUM}\s+{_NUM}", re.I)   # CamPos Planet Zone（米）
CAMDIR = re.compile(r"c[a@]m\s*d[il1]r\s*:?(?P<rest>.*)$", re.I)   # 镜头朝向：俯仰 横滚 偏航（度，星系坐标系）
PLANET = re.compile(r"(?<![A-Za-z])Planet\s*:\s*(?P<p>.+?)\s*(?:\(.*)?$", re.I)     # 前面可能带着几个杂字


_SWAP = str.maketrans({"s": "5", "S": "5", "o": "0", "O": "0", "l": "1", "I": "1", "|": "1"})


def _fix_numbers(line):
    """数字部分（Pos: 后面、CamPos Planet Zone: 后面）OCR 常把 5 认成 s、0 认成 o、1 认成 l：
    只在挨着数字的地方换回来（km、m 这些单位不动）"""
    m = re.search(r"(Pos\s*:|Zone\s*:|CamDir\s*:)(?!.*(?:Pos\s*:|Zone\s*:))", line, re.I)
    if not m:
        return line
    head, tail = line[:m.end()], line[m.end():]
    tail = re.sub(r"(?<=[\d.])[sSoOlI|]|[sSoOlI|](?=[\d.])|(?<=[-+\s])[lIO|](?=[\d.lIO|])", lambda x: x.group(0).translate(_SWAP), tail)
    return head + tail


def _like(zl, word):
    """区域名开头像不像 SolarSystem / Root：允许认错一两个字母（字模把 SolarSystem 读成 SolarSyscem，2026-10-27 实拍）。
    认错了也不怕：两行坐标必须一模一样才采用"""
    from difflib import SequenceMatcher
    head = re.sub(r"[^a-z]", "", zl)[:len(word)]
    if head == word:
        return True
    # 首字母要对、长度要够，再看相似度（「oo6_Stabton」不能被当成 Root）
    return (len(head) == len(word) and head[0] == word[0] and head[-1] == word[-1]
            and SequenceMatcher(None, head, word).ratio() >= (0.8 if len(word) > 6 else 0.75))


def _num(s):
    return float(s.replace(",", ""))


def parse(lines, need_both=False):
    """OCR 出来的文字行 → dict(global=(x,y,z) 米 或 None, local=(x,y,z) 千米 或 None, zone, location, planet,
    local_ok)。local_ok：星球局部坐标和「CamPos Planet Zone」那行（同一个位置，单位米）对得上 = True，
    对不上 = False（有一行认错了），没有那行 = None。
    inner_zone：第一行 Zone 的名字（最里层，三个数可能都是 m，比如空间站里的「Hangar SmallFront RestStop 906008046493」），
    只要名字、坐标不用（空间站里认在哪个区域 / 在不在电梯里，2026-10-28）"""
    out = {"global": None, "local": None, "zone": "", "location": "", "planet": "", "campos": None, "local_ok": None,
           "camdir": None, "fov": None, "solar_id": "", "inner_zone": ""}
    sys_pos, root_pos = None, None
    for raw in lines:
        line = _fix_numbers(raw.replace("：", ":").replace("_", " ").strip())
        m = POS.search(line)
        units = [m.group(u).lower() for u in ("u1", "u2", "u3")] if m else []
        if m and not out["inner_zone"]:
            out["inner_zone"] = m.group("zone").strip()
        if "km" in units:                       # 三个数各带单位（小的显示成 m），按各自单位换成千米；三个都是 m 的是飞船 / 室内局部坐标，不收
            zone = m.group("zone").strip()
            try:
                raw3 = [_num(m.group(i)) for i in (2, 4, 6)]
                if any(u == "m" and abs(v) >= 1e5 for v, u in zip(raw3, units)):
                    continue                        # 游戏写成 m 的最大也就一两千米：几十万「米」是 km 的 k 被认丢了
                xyz = tuple(v * (1 if u == "km" else 0.001) for v, u in zip(raw3, units))
            except ValueError:
                continue
            zl = zone.lower().replace(" ", "").replace("5", "s").replace("0", "o")     # OCR 常把 S 认成 5、O 认成 0
            if _like(zl, "solarsystem"):
                sys_pos = xyz
                m2 = re.search(r"(\d{6,})", zone)
                out["solar_id"] = m2.group(1) if m2 else ""              # 每个星系一个固定编号：学会了就能直接定星系
            elif _like(zl, "root"):
                root_pos = xyz
            elif out["local"] is None:
                out["local"], out["zone"] = xyz, zone
            continue
        m = CAMDIR.search(line)
        if m and out["camdir"] is None:
            parts = re.split(r"f[o0]v", m.group("rest"), flags=re.I)
            rest = parts[0]
            if len(parts) > 1:                      # 视角大小（度）：在屏幕上画导航记号要用（2026-10-27）
                fv = re.match(r"\W*(\d+(?:[.,]\d+)?)", parts[1])
                if fv and 20 <= float(fv.group(1).replace(",", ".")) <= 160:
                    out["fov"] = float(fv.group(1).replace(",", "."))
            nums = re.findall(r"[-+]?\d+(?:[.,]\d+)?", rest)
            if len(nums) >= 3:
                v = tuple(float(x.replace(",", ".")) for x in nums[:3])
                if all(-360 <= a <= 360 for a in v):        # 超出范围就是认错了数字
                    out["camdir"] = v
            continue
        m = CAMPOS.search(line)
        if m and out["campos"] is None:
            try:
                out["campos"] = tuple(_num(m.group(i)) for i in (1, 2, 3))
            except ValueError:
                pass
            continue
        m = LOC.search(line)
        if m:
            out["location"] = m.group("loc").strip()
            continue
        m = PLANET.search(line)
        if m and not out["planet"]:
            out["planet"] = m.group("p").strip()
    # 两行星系坐标一致才采用。need_both=False（识别引擎那条老路）只有一行时也收，但要求数值像样；
    # 字模这条路必须两行都完整读出来而且一致（Codex 2026-10-27 补审：只看一行，读错的数字会直接进导航）
    cand = None
    if sys_pos and root_pos:
        if all(abs(a - b) < 0.01 for a, b in zip(sys_pos, root_pos)):
            cand = sys_pos
    elif (sys_pos or root_pos) and not need_both:
        cand = sys_pos or root_pos
    if cand and max(abs(v) for v in cand) > 1000:          # 星系坐标至少上千公里
        out["global"] = tuple(v * 1000 for v in cand)
    if out["local"] and out["campos"]:
        import math
        out["local_ok"] = math.dist(out["local"], tuple(v / 1000 for v in out["campos"])) < 0.05
    return out


def crop(img):
    from PIL import Image
    w, h = img.size
    l, t, r, b = REGION
    piece = img.crop((int(w * l), int(h * t), int(w * r), int(h * b)))
    return piece.resize((piece.width * UPSCALE, piece.height * UPSCALE), Image.LANCZOS)


def lines_of(img):
    """右上角 OCR → 按从上到下排好的文字行"""
    return _lines(crop(img))


def _rows(toks):
    toks = sorted(toks, key=lambda t: (t.box[1], t.box[0]))
    rows = []
    for t in toks:                                      # 同一行的几段拼起来
        if rows and abs(rows[-1][0] - t.box[1]) < max(6, t.box[3] * 0.5):
            rows[-1][1].append(t)
        else:
            rows.append([t.box[1], [t]])
    return [sorted(ts, key=lambda t: t.box[0]) for _, ts in rows]


def _lines(piece):
    from .trade.ocr import recognize
    return [" ".join(t.text for t in ts) for ts in _rows(recognize(piece, native=True))]


# ---------------------------------------------------------------- 快速读取
# 右上角有二三十行调试信息，我们只要其中四五行（Zone…Pos、Current player location）。
# 第一次整块认一遍，记下这几行在哪；之后每次只认这几行（不再找字的位置），快 5~10 倍。
# 认出来的对不上（行的位置变了）就重新整块认一遍。
NEED = re.compile(r"Zone|player\s*location|Planet", re.I)      # CamDir 那行另外单独放大认（_camdir_band）
LAYOUT_TTL = 180.0         # 3 分钟重新整块认一次；中间哪次对不上会马上重认
_layout = {"at": 0.0, "boxes": None}


def _need_boxes(rows, scale):
    """要用的那几行在原尺寸截图里的位置 [(左, 上, 右, 下)]：从认出关键字的那一段开始，
    连上它右边紧挨着的几段（同一行左边别的东西不要，比如屏幕上恰好同一高度的其他文字）"""
    boxes = []
    for ts in rows:
        for i, t in enumerate(ts):
            if not NEED.search(t.text):
                continue
            x0, y0 = t.box[0], t.box[1]
            x1, y1 = t.box[0] + t.box[2], t.box[1] + t.box[3]
            for u in ts[i + 1:]:
                if u.box[0] - x1 > max(40, t.box[3] * 4):
                    break
                x1, y1 = max(x1, u.box[0] + u.box[2]), max(y1, u.box[1] + u.box[3])
                y0 = min(y0, u.box[1])
            boxes.append(tuple(int(v / scale) for v in (x0, y0, x1, y1)))
            break
    return boxes


CAM_UPSCALE = 3      # CamDir 那行字小、数字挨得近（「23 9 -142」容易认成「239·142」）：单独放大 3 倍再认


_cam_fov = {"v": None}      # 最近一次读到的视角大小（度）


def last_fov():
    return _cam_fov["v"]


def _camdir_band(piece, box):
    """CamDir 那一行单独放大再认，返回 (俯仰, 横滚, 偏航) 或 None"""
    from PIL import Image
    from .trade.ocr import read_line
    x0, y0, x1, y1 = box
    w = x1 - x0
    band = piece.crop((max(0, int(x0 - w * 0.08 - 6)), max(0, y0 - 3),
                       min(piece.width, int(x1 + w * 0.04 + 6)), min(piece.height, y1 + 3)))
    band = band.resize((band.width * CAM_UPSCALE, band.height * CAM_UPSCALE), Image.LANCZOS)
    r = parse([read_line(band)[0]])
    _cam_fov["v"] = r["fov"] or _cam_fov["v"]          # FOV 和 CamDir 在同一行，顺便记下
    return r["camdir"]


def _cam_box(rows, scale):
    """CamDir 那一行在原尺寸截图里的位置"""
    for ts in rows:
        for i, t in enumerate(ts):
            if re.search(r"c[a@]m\s*d[il1]r", t.text, re.I):
                x0, y0 = t.box[0], t.box[1]
                x1 = max(u.box[0] + u.box[2] for u in ts[i:])
                y1 = max(u.box[1] + u.box[3] for u in ts[i:])
                return tuple(int(v / scale) for v in (x0, y0, x1, y1))
    return None


def _full_read(piece, screen_h=None):
    """整块认（找字 + 认字），顺便记下要用的几行的位置；认出来的文字喂给字模校准（gridtext）"""
    from PIL import Image
    from .trade.ocr import recognize
    up = piece.resize((piece.width * UPSCALE, piece.height * UPSCALE), Image.LANCZOS)
    rows = _rows(recognize(up, native=True))
    texts = [" ".join(t.text for t in ts) for ts in rows]
    info = parse(texts, need_both=True)          # 实时位置：两行星系坐标都要读出来而且一致（Codex 2026-10-27 复审）
    boxes = _need_boxes(rows, UPSCALE) if info["global"] else None
    cam = _cam_box(rows, UPSCALE)
    _layout.update(at=time.time(), boxes=boxes, cam=cam)
    if cam:
        info["camdir"] = _camdir_band(piece, cam)
    if screen_h and info["global"]:
        try:
            from . import gridtext
            import numpy as np
            ocr_rows = [(text, (min(t.box[1] for t in ts) + max(t.box[1] + t.box[3] for t in ts)) / 2 / UPSCALE)
                        for text, ts in zip(texts, rows)]
            arr = np.asarray(piece.convert("RGB"))
            gridtext.feed(arr, ocr_rows, screen_h)
            loc_y = next((y for text, y in ocr_rows if LOC.search(text)), None)
            if loc_y is not None:                                   # 记下地点那一行的顶边，字模路径要用
                tops = gridtext.row_tops(gridtext.textness(arr))
                if tops:
                    t = min(tops, key=lambda v: abs(v + 6 * screen_h / 1080 - loc_y))
                    _loc["top"] = t if abs(t + 6 * screen_h / 1080 - loc_y) < 10 * screen_h / 1080 else None
        except Exception:
            pass
    return info


# ---------------------------------------------------------------- 字模快速路径（gridtext，2026-10-26）
# 字模认整块只要几毫秒；「Current player location」那行是小字号、字母多，字模没学全时用识别引擎只认那一行，
# 而且只在那一行的画面变了才认（地点几分钟才变一次）
_loc = {"hash": None, "text": "", "at": 0.0, "top": None}
_grid_layout = {"tops": None, "at": 0.0}        # 要用的那几行的顶边 y：每帧只认这几行；30 秒或认不出坐标时重新整块认
LOC_LOOSE = re.compile(r"pl[a-z?]{2,4}r\s*l[a-z?]{3,8}\s*:", re.I)
NEED_ROW = re.compile(r"Zone|CamDir|player|locat|Planet", re.I)


_NUM_Q = re.compile(r"\?(?=[\d.,])|(?<=[\d.,\-])\?")


def grid_text(t):
    """字模认出的一行 → 给 parse 的文字：数字旁边认不出的格子（?）写成 #，让这个坐标解析失败（以前当空格删掉，
    「?2462326.4853km」会变成少一位的坐标，Codex 2026-10-27 补审）；别处的 ? 多半是邻格漏进来的墨，当空格"""
    return _NUM_Q.sub("#", t).replace("?", " ")


def _grid_read(piece, screen_h):
    """字模路径：→ parse() 的结果，或 None（字模没准备好 / 没读到坐标）"""
    from . import gridtext
    import numpy as np
    arr = np.asarray(piece.convert("RGB"))
    only = _grid_layout["tops"] if time.time() - _grid_layout["at"] < 30 else None
    rows = gridtext.read_rows(arr, screen_h, only=only)
    if rows is None:
        return None
    info = parse([grid_text(t) for _, t, _, _ in rows], need_both=True)
    if not info["global"] and only:                                  # 只认那几行没读到：整块重认一次
        _grid_layout.update(tops=None, at=0.0)
        rows = gridtext.read_rows(arr, screen_h)
        if rows is None:
            return None
        info = parse([grid_text(t) for _, t, _, _ in rows], need_both=True)
    if not info["global"]:
        return None
    if not only:
        need = [top for top, t, _, _ in rows if NEED_ROW.search(t) or LOC_LOOSE.search(t)]
        if _loc.get("top") is not None and _loc["top"] not in need:
            need.append(_loc["top"])
        _grid_layout.update(tops=sorted(need), at=time.time())
    # 地点那一行：字模只用来找到这一行（地名字母多、大小写像，字模认不稳），内容用识别引擎认——只在这一行画面变了才认。
    # 字模找不到时，用上次整块识别时记下的位置
    loc_row = next((r for r in rows if r[3] == "small" and (LOC.search(r[1]) or LOC_LOOSE.search(r[1]))), None)
    top = loc_row[0] if loc_row else _loc.get("top")
    if top is not None:
        info["location"] = _ocr_location(piece, arr, top, screen_h, key=loc_row[1] if loc_row else None)
    if info.get("zone"):
        info["zone"] = _zone_name(piece, rows, info["zone"], screen_h)
    info["fast"] = True
    return info


_zones = {"map": {}, "at": 0.0}


def _zone_name(piece, rows, zone, screen_h):
    """局部坐标那一行的区域名（导航靠它认是哪颗星球）：字模在新地方还没学全时会读歪（Microtech → M1orotetn）。
    区域名一变（换地方才变），识别引擎认一次那一行，按字模读到的样子记住，同样的样子以后直接用；认到的那一行顺便喂给字模学"""
    m = _zones["map"]
    if zone in m:
        return m[zone]
    if time.time() - _zones["at"] < 2.0 or getattr(_TL, "skip_ocr", False):
        return zone
    row = next((r for r in rows if POS.search(_fix_numbers(r[1].replace("?", " ").replace("_", " ")))
                and zone in _fix_numbers(r[1].replace("?", " ").replace("_", " "))), None)
    if not row:
        return zone
    _zones["at"] = time.time()
    try:
        from PIL import Image
        import numpy as np
        from . import gridtext
        from .trade.ocr import read_line
        top = row[0]
        lh = gridtext._for(screen_h).g.lh
        y0, y1 = max(0, top - 3), min(piece.height, top + lh + 3)
        arr = np.asarray(piece.convert("RGB"))
        cols = (gridtext.textness(arr[y0:y1]) > 50).sum(0)
        xs = [x for x, v in enumerate(cols) if v]
        img = piece.crop((max(0, (xs[0] if xs else 0) - 4), y0, piece.width, y1))
        text = read_line(img.resize((img.width * UPSCALE, img.height * UPSCALE), Image.LANCZOS))[0]
        got = parse([text])
        if got["local"] and got["zone"]:
            if len(m) > 200:
                m.clear()
            m[zone] = got["zone"]
            gridtext.feed(arr, [(text, top + lh / 2)], screen_h)
            return got["zone"]
    except Exception:
        pass
    return zone


def _known_place(loc):
    """地点认出来是不是已知的地方（能翻成中文名）"""
    try:
        from .position import display_label
        raw = re.sub(r"\s*\(.*$", "", loc).strip()
        lab = display_label(loc)
        return bool(lab) and lab != raw
    except Exception:
        return False


def _ocr_location(piece, arr, top, screen_h, key=None):
    """识别引擎只认地点那一行（字没变就用上次的）。key：字模认出的这一行（认不全也没关系，只用来判断变没变）；
    没有就看这一行的字的像素（2026-10-27 实测：直接比像素，背后游戏画面一动就算变，平均 2 秒认一次，太勤）"""
    from . import gridtext
    lh = gridtext._for(screen_h).g.lh
    y0, y1 = max(0, top - 3), min(piece.height, top + lh + 3)
    band = arr[y0:y1]
    h = hash(key) if key else hash((gridtext.textness(band) > 120).tobytes())
    if h == _loc["hash"]:
        return _loc["text"]
    if getattr(_TL, "skip_ocr", False) and time.time() - _loc["at"] < 15.0:
        return _loc["text"]     # 给采矿助手让路：地点这一行最多 15 秒认一次（飞到别的矿区，产矿区不会一直停在旧的，独立审查 2026-10-27）
    if time.time() - _loc["at"] < 2.0:
        return _loc["text"]
    _loc["at"] = time.time()
    try:
        from PIL import Image
        from .trade.ocr import read_line
        cols = (gridtext.textness(band) > 50).sum(0)
        xs = [x for x, v in enumerate(cols) if v]
        x0 = max(0, (xs[0] if xs else 0) - 4)
        img = piece.crop((x0, y0, piece.width, y1))
        img = img.resize((img.width * UPSCALE, img.height * UPSCALE), Image.LANCZOS)
        text = read_line(img)[0]
        m = LOC.search(text.replace("：", ":"))
        loc = m.group("loc").strip() if m else ""
        if not loc:                                  # 这次没认出来：保留上次的地点，过 2 秒再认（以前会把地点冲成空的）
            return _loc["text"]
        gridtext.feed(arr, [(text, top + lh / 2)], screen_h)              # 顺便学这一行的小字（只用来找这一行）
        if loc != _loc["text"] and loc != _loc.get("cand") and not _known_place(loc) and _loc["text"]:
            _loc["cand"] = loc                       # 和上次不一样、又对不上已知地点：多半是认错了字母，再认一次一样才换
            return _loc["text"]
        _loc.update(hash=h, text=loc, cand=None)
        return loc
    except Exception:
        return _loc["text"]


def _fast_read(piece, boxes):
    """只认记下的那几行：每行左边多留一点（数字变长时字往左长），按原尺寸认"""
    from .trade.ocr import read_line
    lines = []
    for x0, y0, x1, y1 in boxes:
        w = x1 - x0
        band = piece.crop((max(0, int(x0 - w * 0.08 - 6)), max(0, y0 - 3),
                           min(piece.width, int(x1 + w * 0.04 + 6)), min(piece.height, y1 + 3)))
        lines.append(read_line(band)[0])
    info = parse(lines, need_both=True)
    cam = _layout.get("cam")
    info["camdir"] = _camdir_band(piece, cam) if cam else None
    return info


# 采矿助手看着扫描面板 / 雷达信号时，读位置给它让路：只用字模（几毫秒），字模认不出也不退回识别引擎（一次几百毫秒，
# 和采矿助手抢同一个识别引擎）。2026-10-27 录制：导航开着时读位置每分钟占识别引擎 15–30 秒，悬浮窗因此晚 10–18 秒
_YIELD = {"until": 0.0, "calib_at": 0.0}
YIELD_RETRY = 5.0               # 让路时字模认不出：隔这么久再试
YIELD_CALIB = 20.0              # 让路时字模还没学会：隔这么久放行一次识别引擎（不然整段采矿字模都学不会，独立审查 2026-10-27）
import threading as _threading
_TL = _threading.local()        # 本次读取要不要跳过识别引擎（地点行 / 区域名那两处也看它）


def yield_ocr(seconds=6.0):
    """采矿助手调用：接下来 seconds 秒读位置不用识别引擎"""
    _YIELD["until"] = max(_YIELD["until"], time.time() + seconds)


def yielding():
    return time.time() < _YIELD["until"]


def read(img=None, allow_yield=True):
    """→ parse() 的结果，另外 t = 截图的时间（星球在转：算位置要用截图那一刻，不能用认完字的时刻）、
    fast = 这次是字模认的（几毫秒）还是识别引擎认的、yielded = 给采矿助手让路，这次没用识别引擎（没读到）"""
    shot_at = time.time()
    if img is None:                                  # 只截右上角这一块
        from .perf import grab_region, game_area
        screen_h = game_area()["height"]
        piece = grab_region(REGION)
    else:
        w, h = img.size
        screen_h = h
        l, t, r, b = REGION
        piece = img.crop((int(w * l), int(h * t), int(w * r), int(h * b)))
    info = None
    from . import gridtext
    was_ready = False
    try:
        was_ready = gridtext.ready(screen_h)
    except Exception:
        pass
    skip = allow_yield and img is None and yielding()      # 只管实时截屏（传了截图的是测试 / 别处在认）
    if skip and not was_ready and time.time() - _YIELD["calib_at"] >= YIELD_CALIB:
        _YIELD["calib_at"] = time.time()
        skip = False
    _TL.skip_ocr = skip
    try:
        info = _grid_read(piece, screen_h)
    except Exception:
        info = None
    finally:
        _TL.skip_ocr = False
    if info is None and skip:
        info = parse([])
        info.update(fast=False, yielded=True, t=shot_at)
        return info
    if info is None:
        boxes = _layout["boxes"]
        if boxes and time.time() - _layout["at"] < LAYOUT_TTL:
            info = _fast_read(piece, boxes)
        if not info or not info["global"]:
            info = _full_read(piece, screen_h)
        info["fast"] = False
        if was_ready and info.get("global"):
            gridtext.note(False)          # 字模读不出、识别引擎却读得出：字模可能失效了（改了缩放 / 分辨率），连续几次就重画
    elif was_ready:
        gridtext.note(True)
    info["t"] = shot_at
    return info


class Reader:
    """导航/位置用：定时读右上角，有新坐标就返回；读不到（没开 r_DisplayInfo）就慢慢试。
    后台位置线程和采矿扫描线程都会调 poll：整个读取加锁，同一时间只读一次，旧帧不会盖掉新帧（Codex 2026-10-27 补审）"""

    def __init__(self, every=1.0):
        import threading
        self.every = every
        self.next_at = 0.0
        self.misses = 0
        self.ok_at = 0.0
        self.yielded_at = 0.0           # 最后一次给采矿助手让路（没读）的时间
        self.last = None
        self.info = None
        self._lock = threading.Lock()

    @property
    def active(self):
        """最近读到过（两次读取间隔再多留一点）：说明右上角调试信息开着。给采矿助手让路的这段不算没开
        （以前一直采矿会误报「没开 r_DisplayInfo」，独立审查 2026-10-27）——前提是以前读到过"""
        now = time.time()
        if now - self.ok_at < max(8.0, self.every * 2 + 5):
            return True
        return self.ok_at > 0 and now - self.yielded_at < YIELD_RETRY + 3

    def snapshot(self):
        """(最后读到的时间, 那次的全部信息)：同一次读取的，不会一半新一半旧"""
        with self._lock:
            return self.ok_at, self.info

    def poll(self, force=False):
        with self._lock:
            now = time.time()
            if not force and now < self.next_at:
                return None
            try:
                from .showloc import game_foreground, WIN
                if WIN and not game_foreground():
                    self.next_at = now + 1.0
                    return None
                info = read(allow_yield=not force)       # 强制读（采矿助手要判断地面/太空）不让路
            except Exception:
                info = None
            done = time.time()                  # 下次从读完算起：识别引擎一次要几百毫秒，从开始算会读完马上又读
            if info and info.get("yielded"):    # 给采矿助手让路：不算没读到，过一会再试
                self.yielded_at = done
                self.next_at = done + YIELD_RETRY
                return None
            # 不是字模读的（识别引擎，几百毫秒一次）：成功、失败都至少隔 2 秒，不按 0.2 秒狂读
            gap = self.every if (info and info.get("fast")) else max(self.every, 2.0)
            if info and info["global"]:
                self.misses = 0
                self.ok_at = done
                self.info = info
                self.next_at = done + gap
                g = info["global"]
                if self.last is None or max(abs(a - b) for a, b in zip(g, self.last)) > 1.0:
                    self.last = g
                    return g
                return None
            self.misses += 1
            self.next_at = done + (gap if self.misses < 3 else max(gap, min(60.0, self.every * self.misses)))
            return None
