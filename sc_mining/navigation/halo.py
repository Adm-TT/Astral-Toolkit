"""Aaron Halo 小行星带导航（照 SCMiner 的 Aaron Halo Flight Computer 做）

做法：小行星带是绕斯坦顿恒星的一圈圈环带（离恒星 19.67–21.30 Gm）。从一个拉格朗日点 / 星球
量子跳向另一个，航线会穿过某一条带；算出穿过点到目标还剩多远，玩家盯着 HUD 上「到目标的剩余距离」，
到这个数就按 U 断开量子，就停在这条带里了。

数据：带的范围、厚度、密度、矿种、量子引擎速度都抄自 scminer.rocks（2026-10-23）。
坐标：斯坦顿星系坐标原点就是恒星（用 ARC-L1→CRU-L4 第 5 带核对：算出 14.29 Gm，SCMiner 显示 14.3 Gm）。
安全窗口：航线在带「核心」（中心 85% 厚度）里走的长度。这样算出的 5 条路线和 SCMiner 的 margin 相差 3% 以内
（SCMiner 没公开公式，这个比例是对着它的数反推的）。反应时间 = 安全窗口 ÷ 量子引擎速度。
"""
import math

# 带号, 内径 Gm, 外径 Gm, 厚度 Mm, 相对密度 %, 主要矿物, 评级
BANDS = [
    (1, 19.67, 19.71, 42, 1, ("Titanium", "Tungsten", "Beryl", "Diamond"), "普通"),
    (2, 19.82, 19.91, 99, 24, ("Titanium", "Tungsten", "Beryl", "Diamond"), "普通"),
    (3, 19.91, 20.00, 81, 35, ("Titanium", "Tungsten", "Beryl", "Diamond"), "普通"),
    (4, 20.07, 20.18, 108, 23, ("Titanium", "Tungsten", "Beryl", "Diamond"), "普通"),
    (5, 20.23, 20.41, 177, 100, ("Quantainium", "Bexalite", "Gold", "Taranite"), "★ 最密热点"),
    (6, 20.41, 20.54, 133, 33, ("Titanium", "Tungsten", "Beryl", "Diamond"), "普通"),
    (7, 20.54, 20.88, 341, 36, ("Quantainium", "Agricium", "Laranite", "Hephaestanite"), "★ 高价矿带"),
    (8, 20.88, 21.05, 165, 26, ("Titanium", "Tungsten", "Beryl", "Diamond"), "普通"),
    (9, 21.05, 21.13, 86, 25, ("Titanium", "Tungsten", "Beryl", "Diamond"), "普通"),
    (10, 21.13, 21.30, 166, 33, ("Titanium", "Tungsten", "Beryl", "Diamond"), "普通"),
]
# 量子引擎：名字, 尺寸, 速度 Mm/s（SCMiner 的选项）
QDS = [("Atlas", "S1", 103), ("Hemera", "S2", 95), ("Beacon", "S1", 90), ("Expedition", "S1", 86),
       ("Voyage", "S2", 79), ("Odyssey", "S3", 74)]
CORE = 0.85          # 安全窗口只算带中心 85% 的厚度
WIDE_MM = 250        # 安全窗口超过这么多算「宽」，好断
PLANETS = ("Hurston", "Crusader", "ArcCorp", "microTech")
STAR_GM = 1.0        # 航线离恒星中心这么近，游戏里量子跳多半会被恒星挡住（SCMiner 没过滤这种，我们标出来）


def band(b):
    for row in BANDS:
        if row[0] == int(b):
            return row
    raise ValueError(f"没有第 {b} 带（仅 1–10）")


def band_row(row):
    from ..core.i18n import mineral_zh
    b, lo, hi, thick, dens, ores, rate = row
    return {"band": b, "lo": lo, "hi": hi, "thick": thick, "density": dens, "rating": rate,
            "ores": [mineral_zh(o) or o for o in ores], "ores_en": list(ores)}


def qd_speed(qd):
    for name, size, v in QDS:
        if str(qd).lower() in (name.lower(), f"{name} ({size})".lower()):
            return v
    try:
        return float(qd)
    except (TypeError, ValueError):
        return QDS[0][2]


def points(data=None):
    """可以出发 / 跳过去的点：斯坦顿的拉格朗日点（ARC-L1 这种叫法）和四颗行星，坐标 Gm"""
    from . import navigate as n
    data = data or n.load()
    out = {}
    for p in data.get("points", []):
        if p.get("sys") == "Stanton" and p.get("t") == "Lagrange Point":
            out[p["n"].replace(" ", "-")] = (p["x"] / 1e9, p["y"] / 1e9, p["z"] / 1e9)
    bodies = data.get("bodies", {})
    for name in PLANETS:
        b = next((v for k, v in bodies.items() if k.lower() == name.lower()), None)
        if b:
            out[name] = (b["x"] / 1e9, b["y"] / 1e9, b["z"] / 1e9)
    return out


def point_zh(name):
    from .navigate import BODY_ZH
    zh = next((v for k, v in BODY_ZH.items() if k.lower() == name.lower()), None)
    return f"{zh}（{name}）" if zh else name


def _roots(A, D, r):
    """航线 A + t·D 离恒星正好 r 的 t（0~1 之间）"""
    qa = sum(x * x for x in D)
    qb = 2 * sum(A[i] * D[i] for i in range(3))
    qc = sum(x * x for x in A) - r * r
    disc = qb * qb - 4 * qa * qc
    if qa == 0 or disc < 0:
        return []
    s = math.sqrt(disc)
    return [t for t in ((-qb - s) / (2 * qa), (-qb + s) / (2 * qa)) if 0 <= t <= 1]


def _inside(A, D, t0, lo, hi):
    """t0 附近航线在 lo~hi 这一圈里的那一段 [t1, t2]"""
    cuts = sorted({0.0, 1.0, *_roots(A, D, lo), *_roots(A, D, hi)})
    r = lambda t: math.sqrt(sum((A[i] + t * D[i]) ** 2 for i in range(3)))
    for a, b in zip(cuts, cuts[1:]):
        if a <= t0 <= b and lo <= r((a + b) / 2) <= hi:
            return a, b
    return t0, t0


def route(frm, to, b, speed=103, pts=None):
    """从 frm 量子跳向 to，在第 b 带断开：到 to 还剩多少（Gm）时断、安全窗口多长。航线不穿过这条带就 None"""
    pts = pts or points()
    if frm not in pts or to not in pts or frm == to:
        return None
    _, lo, hi, *_ = band(b)
    A, B = pts[frm], pts[to]
    D = [B[i] - A[i] for i in range(3)]
    L = math.sqrt(sum(x * x for x in D))
    mid = (lo + hi) / 2
    ts = _roots(A, D, mid)
    if not ts:
        return None
    t = min(ts)                                   # 先碰到的那一次
    half = (hi - lo) / 2
    c1, c2 = _inside(A, D, t, mid - half * CORE, mid + half * CORE)
    f1, f2 = _inside(A, D, t, lo, hi)
    margin = (c2 - c1) * L * 1000                 # Mm
    if margin <= 0:
        return None
    out_r = math.sqrt(sum(x * x for x in A))
    tc = max(0.0, min(1.0, -sum(A[i] * D[i] for i in range(3)) / (L * L)))
    star = math.sqrt(sum((A[i] + tc * D[i]) ** 2 for i in range(3)))    # 航线离恒星最近多少 Gm
    return {"from": frm, "to": to, "band": int(b), "to_zh": point_zh(to), "from_zh": point_zh(frm),
            "dropout": round((1 - t) * L, 3),                     # Gm：HUD 到目标剩这么多时断开
            "early": round((1 - c1) * L, 3),       # 安全窗口：HUD 剩这么多时进核心
            "late": round((1 - c2) * L, 3),        # 剩这么多时就出核心了
            "margin": round(margin), "chord": round((f2 - f1) * L * 1000),
            "wide": margin >= WIDE_MM, "window": round(margin / speed, 1),
            "flight": round(t * L * 1000 / speed), "total": round(L, 3),
            "inward": out_r > mid, "star": round(star, 2), "blocked": star < STAR_GM}


def routes(frm, b, speed=103, pts=None):
    """从 frm 出发、航线穿过第 b 带的所有目标，安全窗口宽的排前面"""
    pts = pts or points()
    rows = [r for to in pts if (r := route(frm, to, b, speed, pts))]
    return sorted(rows, key=lambda r: -r["margin"])


def gm(v):
    return f"{v:.2f} Gm（{v * 1000:,.0f} Mm）"


def plan_text(r):
    """悬浮窗上显示的步骤"""
    return (f"小行星带 第{r['band']}带：从 {r['from_zh']} 量子跳向 {r['to_zh']}\n"
            f"HUD 到 {r['to_zh']} 剩 {r['dropout']:.1f} Gm 左右按 U 断开\n"
            f"剩 {r['early']:.1f}–{r['late']:.1f} Gm 之间断开都在带里")


def where(g):
    """/showlocation 坐标（米）→ 离恒星多远、在第几带"""
    r = math.sqrt(sum(float(v) ** 2 for v in g)) / 1e9       # 不四舍五入：判带、算方向都用原值，只在文字里格式化
    for row in BANDS:
        if row[1] <= r <= row[2]:
            return {"r": r, "band": row[0], "off": 0.0}
    near = min(BANDS, key=lambda row: min(abs(r - row[1]), abs(r - row[2])))
    off = (near[1] - r) if r < near[1] else (near[2] - r)     # 正数：要往外飞
    return {"r": r, "band": None, "near": near[0], "off": off * 1000}


def where_text(w, want=None):
    r = f"离恒星 {w['r']:.3f} Gm"
    if want:
        row = band(want)
        if row[1] <= w["r"] <= row[2]:
            return f"✅ {r}：在第{want}带里"
        off = ((row[1] - w["r"]) if w["r"] < row[1] else (row[2] - w["r"])) * 1000
    elif w["band"]:
        return f"✅ {r}：在第{w['band']}带里"
    else:
        off = w["off"]
    if abs(off) > 3000:
        return f"❌ {r}：离小行星带太远（带在离恒星 19.67–21.30 Gm）"
    way = "往外（背对恒星）" if off > 0 else "往里（朝恒星）"
    now = f"在第{w['band']}带" if w["band"] else "在带外"
    goal = f"第{want}带" if want else f"最近的第{w['near']}带"
    far = f"{abs(off):,.0f} Mm" if abs(off) >= 1 else f"{abs(off) * 1000:,.0f} km"
    return f"⚠️ {r}：{now}，离{goal}还要{way}飞约 {far}"
