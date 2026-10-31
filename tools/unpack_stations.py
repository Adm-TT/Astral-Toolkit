"""空间站里的导航点（2026-10-27，老大要「在主城或空间站里导航去最近的终端和商店」）：
从解开的物件容器里找出每个空间站（休息站 rs_ext_*、尼克斯的人民服务空间站 rs_asmbl_*）里的取船终端、商品交易终端、
货运电梯、诊所、商店……算出坐标，和城里的点一起写进 data/city_places.json（unpack_city.py 的 main 会调用这里）。
  坐标系：绕星球轨道的站（*-leo）跟着星球转，用星球局部坐标（千米，和城里的点一样）；
          拉格朗日点、跳跃点的站不跟星球转，用星系坐标（千米）+ space=True。
做法：斯坦顿：先建「子容器 → 父容器」的反查表，从站一层层往上找到星球容器或星系根容器，把每层的 pos / rot 合起来。
      派罗、尼克斯（2026-10-30）：站挂在拉格朗日点 / 星球 / 小行星带段的容器里，这些在星系文件里是一层套一层的 Child，
      反查表只知道「在哪个文件」、不知道套在哪一层，算出来差几百万公里；改成从星系文件往下一层层走（和 unpack_starmap 一样）。
只发整理出的坐标和名字，不发游戏文件。"""

import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import unpack_city as U  # noqa: E402

ROOT = U.ROOT
SYS_ROOT = {"stantonsystem": "Stanton", "pyrosystem": "Pyro", "nyxsystem": "Nyx"}
TOP = re.compile(
    r"^rs_ext_[a-z0-9_\-]+$|^rs_asmbl_[a-z0-9_\-]+$"
)  # rs_asmbl_*：尼克斯的人民服务空间站（外壳 rs_ext_glaciem_01 套在里面）
JP = {
    "stan-pyro_jp1": "stantonpyro",
    "stan-terra_jp1": "stantonterra",
    "stan-magnus_jp1": "stantonmagnus",
    "pyro-stan_jp1": "pyrostanton",
    "pyro-nyx_jp": "pyronyx",
    "nyx-pyro_jp1": "nyxpyro",
    "nyx-castra_jp1": "nyxcastra",
}

# 站里的东西：(实体名正则, 导航分类, 英文名)。英文名用游戏英文包里的叫法
ENTS = [
    (r"^ShipSelectorKiosk", "取船", "Fleet Manager Terminal"),
    (r"CommodityKiosk", "交易", "Commodity Terminal"),
    (r"FreightElevatorKiosk", "货梯", "Freight Elevator"),
    (r"HospitalCheckIn", "医院", "Clinic Check-In"),
    (r"^Counter_Admin_2m_refineryadmin", "精炼", "Refinery"),
    (r"^Counter_Admin", "行政", "Admin Counter"),
    (r"^ShopKiosk_Rentals", "租船", "Rentals"),
    (r"FineTerminal", "罚款", "Fine Terminal"),
]
# 店（容器名 → 店名）：店名对 data/shops.json（UEX 商店表）里的店名，分类按店里卖什么定
SHOPS = [
    (r"^rstop_pharmacy", "Pharmacy"),
    (r"^util_armor_gen", "Armor"),
    (r"^util_shpweap_gen", "Ship Weapons"),
    (r"^lt_a_livefireweapons", "Live Fire Weapons"),
    (r"^lt_a_platinumbay", "Platinum Bay"),
    (r"^lt_a_casabaoutlet", "Casaba Outlet"),
    (r"^util_clth_gen", "Clothing Shop"),
    (r"^util_a_refinery_admin", "Refinery Shop"),
    (r"^cargo_office", "Cargo Center Supplies"),
    (r"^util_fdcrt_gnrc_sml_htdg", "Hot Dogs"),
    (r"^util_fdcrt_gnrc_sml_pza", "Pizza"),
    (r"^util_fdcrt_gnrc_sml_jce", "Juice Bar"),
    (r"^util_fdcrt_gnrc_sml_brt", "Burrito Bar"),
    (r"^util_fdcrt_gnrc_sml_ndle", "Noodle Bar"),
    (r"^util_ellroys", "Ellroy's"),
    (r"^util_bar_generic", "Bar"),
    # 派罗的破旧站（_rund）、尼克斯的人民服务空间站（2026-10-30）：只收和斯坦顿同一类、容器名看得出是什么的
    (r"^rstop_bar_\d+_rund$", "Bar"),
    (r"^rstop_shipweapongeneric_\d+_rund$", "Ship Weapons"),
    (r"^rstop_noodle_\d+_rund$", "Noodle Bar"),
    (r"^levski_pharmacy$", "Pharmacy"),
]
SELF_ZH = {
    "Hot Dogs": "热狗摊",
    "Pizza": "披萨摊",
    "Burrito Bar": "卷饼吧",
    "Juice Bar": "果汁吧",
    "Noodle Bar": "面条吧",
}  # 汉化组没翻，自译进对照表（AGENTS.md）
SHOP_ZH_KEY = {
    "Pharmacy": "shop_name_pharmacy",
    "Clothing Shop": "shop_name_clothing",
    "Ship Weapons": "shop_name_shipweapons",
    "Bar": "interiormap_common_shop_bar",
}
MERGE_M = 15
DONE_SYS = {"Stanton", "Pyro", "Nyx"}


def rec_of(stem):
    s = stem.lower()
    for pat, fmt in (
        (r"rs_ext_(hur|cru|arc|mic)-l(\d)", "rr_{0}_l{1}"),
        (r"rs_ext_(hur|cru|arc|mic)-leo1", "rr_{0}_leo"),
        (r"rs_ext_pyro(\d)_l(\d)", "rr_p{0}_l{1}"),
        (r"rs_ext_pyro(\d)_leo", "rr_p{0}_leo"),
    ):
        m = re.fullmatch(pat, s)
        if m:
            return fmt.format(*m.groups())
    m = re.fullmatch(r"rs_ext_(.+)", s)
    return "rr_jp_" + JP[m[1]] if m and m[1] in JP else ""


def reverse_index(idx):
    """子容器 → [(父容器, pos, rot)]"""
    rev = {}
    for k, f in idx.items():
        for name, _ent, p, r in U.CHILD.findall(
            f.read_text(encoding="utf-8", errors="ignore")
        ):
            s = Path(name.replace("\\", "/")).stem.lower()
            item = (
                k,
                tuple(float(v) for v in p.split(",")),
                tuple(float(v) for v in r.split(",")),
            )
            if item not in rev.setdefault(s, []):
                rev[s].append(item)
    return rev


def bodies_of(rev, bodies):
    """星系根容器下面的星球容器 → 星图里的星球名（按位置对，差 5 km 内）"""
    out = {}
    for child, parents in rev.items():
        for parent, p, _q in parents:
            if parent in SYS_ROOT:
                best = min(
                    (
                        (math.dist(p, (b["x"], b["y"], b["z"])), n)
                        for n, b in bodies.items()
                        if b.get("sys") == SYS_ROOT[parent]
                    ),
                    default=None,
                )
                if best and best[0] < 5000:
                    out[child] = best[1]
    return out


def resolve(stem, rev, body_of):
    """站容器 → ("body", 星球名, 位置, 朝向) 或 ("sys", 星系名, 位置, 朝向)；位置是米。找不到 / 有好几个父容器返回 None"""
    P, Q, cur = (0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), stem
    for _ in range(10):
        if cur in body_of:
            return "body", body_of[cur], P, Q
        ps = rev.get(cur) or []
        if len(ps) != 1:
            return None
        parent, pp, pq = ps[0]
        P = tuple(a + b for a, b in zip(pp, U.rot(pq, P)))
        Q = U.qmul(pq, Q)
        if parent in SYS_ROOT:
            return "sys", SYS_ROOT[parent], P, Q
        cur = parent
    return None


def system_frames(idx):
    """派罗、尼克斯：从星系文件往下一层层走（内嵌的 Child 都走；外部容器只钻星系文件直接引用的那一层，和 unpack_starmap 一样）
    → {容器名: [(星系坐标 米, 星系朝向, 外面最近的轨道容器 (星系坐标, 星系朝向) 或 None)]}"""
    import xml.etree.ElementTree as ET

    out = {}

    def walk(el, P, Q, ooc, depth, root):
        for ch in el.findall("./ChildObjectContainers/Child"):
            p = tuple(float(v) for v in (ch.get("pos") or "0,0,0").split(","))
            q = tuple(float(v) for v in (ch.get("rot") or "1,0,0,0").split(","))
            g = tuple(a + b for a, b in zip(P, U.rot(Q, p)))
            gq = U.qmul(Q, q)
            stem = Path((ch.get("name") or "").replace("\\", "/")).stem.lower()
            out.setdefault(stem, []).append((g, gq, ooc))
            FRAME_SYS.setdefault(stem, root)
            nooc = (g, gq) if ch.get("class") == "OrbitingObjectContainer" else ooc
            if ch.findall("./ChildObjectContainers/Child"):
                walk(ch, g, gq, nooc, depth, root)
            elif depth == 0 and stem in idx:
                try:
                    walk(ET.parse(idx[stem]).getroot(), g, gq, nooc, 1, root)
                except ET.ParseError:
                    pass

    for root in ("pyrosystem", "nyxsystem"):
        if root in idx:
            walk(
                ET.parse(idx[root]).getroot(),
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0, 0.0),
                None,
                0,
                root,
            )
    return out


def resolve_tree(stem, frames, bodies):
    """派罗、尼克斯的站 → 和 resolve() 一样的 (坐标系, 星球名 / 星系名, 位置 米, 朝向)；在星系文件里找不到 / 挂了好几处 → None。
    挂在星球的轨道容器下（绕星球的站）：星球局部坐标（不含星球容器的朝向，同 resolve）；不自转的星球照 unpack_city 乘上容器朝向。
    其余（拉格朗日点、跳跃点、小行星带）：星系坐标"""
    fs = frames.get(stem) or []
    if len(fs) != 1:
        return None
    g, q, ooc = fs[0]
    sysname = SYS_ROOT.get(FRAME_SYS.get(stem, ""), "")
    if ooc:
        og, oq = ooc
        hit = min(
            (
                (math.dist(og, (b["x"], b["y"], b["z"])), n)
                for n, b in bodies.items()
                if b.get("sys") == sysname
            ),
            default=None,
        )
        if hit and hit[0] < 5000:
            off = tuple(a - b for a, b in zip(g, og))
            if bodies[hit[1]].get("rot") == 0:
                return "body", hit[1], off, q
            inv = (oq[0], -oq[1], -oq[2], -oq[3])
            return "body", hit[1], U.rot(inv, off), U.qmul(inv, q)
    return "sys", sysname, g, q


FRAME_SYS = {}  # 容器名 → 它在哪个星系根文件下面（system_frames 填）


def frame_of(top, rev, body_of, bodies, frames):
    """站容器 → (坐标系, 星球名 / 星系名, 位置 米, 朝向) 或 None。斯坦顿照旧用反查表；派罗、尼克斯按星系文件一层层算
    （unpack_lifts 也用这个，两边的站坐标系必须一样）"""
    r = resolve(top, rev, body_of)
    sysname = (
        (r[1] if r[0] == "sys" else (bodies.get(r[1]) or {}).get("sys", ""))
        if r
        else ""
    )
    if sysname == "Stanton":
        return r
    r2 = resolve_tree(top, frames, bodies)
    if r and r2 and math.dist(r[2], r2[2]) > 1:
        print(
            f"  {top}：两种算法差 {math.dist(r[2], r2[2]):,.0f} m，用星系文件逐层算的"
        )
    return r2


def shop_zh(en):
    L = U.loc()
    key = SHOP_ZH_KEY.get(en) or "shop_name_" + re.sub(r"[^a-z]", "", en.lower())
    z = (L["zh"].get(key) or "").strip()
    if z and re.search(r"[\u4e00-\u9fff]", z):
        return z, "汉化组"
    return (SELF_ZH[en], "自译") if en in SELF_ZH else (en, "英文")


def build(idx, bodies, brand_kinds, names, points=()):
    rev = reverse_index(idx)
    body_of = bodies_of(rev, bodies)
    frames = system_frames(idx)
    point_name = {(p.get("i") or "").lower(): p["n"] for p in points if p.get("i")}
    out, later = (
        [],
        [],
    )  # 斯坦顿的站排前面、顺序照旧：导航的点编号（同名 src 后面加 +）不变
    for top in sorted(k for k in idx if TOP.match(k)):
        if (rev.get(top) or []) and all(
            re.match(r"rs_asmbl_", par) for par, _p, _q in rev[top]
        ):
            continue  # 人民服务空间站的外壳：跟着它所在的 rs_asmbl_* 一起算
        rec = rec_of(top)
        site = names.get(rec)
        if not site and rec:  # 星图记录里没有设施的站：名字直接查汉化包 / 英文包
            L = U.loc()
            en_n, zh_n = L["en"].get(rec, ""), L["zh"].get(rec, "")
            if en_n and not en_n.startswith("@"):
                site = (en_n, re.sub(r"\s*[(（][^()（）]*[)）]\s*$", "", zh_n).strip())
        if (
            not site and top in point_name
        ):  # 没有 rr_ 记录的（人民服务空间站）：星图点的名字 + 汉化名
            from sc_mining.navigation.navigate import poi_zh

            site = (
                point_name[top],
                re.sub(
                    r"\s*[(（][^()（）]*[)）]\s*$", "", poi_zh(point_name[top])
                ).strip(),
            )
        if not site:
            print(f"⚠ {top}：认不出是哪个站，跳过")
            continue
        r = frame_of(top, rev, body_of, bodies, frames)
        if not r:
            print(f"⚠ {top}（{site[0]}）：找不到它挂在哪，跳过")
            continue
        frame, where, P, Q = r
        sysname = where if frame == "sys" else (bodies.get(where) or {}).get("sys", "")
        if sysname not in DONE_SYS:
            print(f"  {site[1] or site[0]}：{sysname} 先不做")
            continue
        up = U.rot(Q, (0.0, 0.0, 1.0))
        nodes = [(top, top, P, Q, ())] + U.walk(idx, top, P, Q)
        pts = []

        def add(kind, en, zh, src, g, zsrc):
            near = next(
                (p for p in pts if p["en"] == en and math.dist(p["m"], g) <= MERGE_M),
                None,
            )
            if near:
                return
            pts.append(
                {"kind": kind, "en": en, "zh": zh, "zh_src": zsrc, "src": src, "m": g}
            )

        for stem, _ent, gp, gq, _anc in nodes:
            base_stem = re.sub(r"_\d+$", "", stem)
            shop = next((en for pat, en in SHOPS if re.search(pat, base_stem)), None)
            ents = U.soc_entities(idx, stem)
            if shop and any(
                p["en"] == shop
                and math.dist(p["m"], U.snap(idx, stem, gp, gq)) <= MERGE_M
                for p in pts
            ):
                shop = None  # 同一家店的底座 + 装饰层（rstop_pharmacy_rundown / _1_occu）：只算一个
            if shop:
                kinds = brand_kinds.get(re.sub(r"[^a-z]", "", shop.lower())) or []
                if shop == "Pharmacy":
                    kinds = ["医院"]
                g = U.snap(idx, stem, gp, gq)
                zh, zs = shop_zh(shop)
                if shop == "Refinery Shop":
                    zh, zs = "精炼站商店", "自译"
                elif shop == "Cargo Center Supplies":
                    zh, zs = "货运中心补给", "自译"
                pts.append(
                    {
                        "kind": "商店",
                        "kinds": kinds,
                        "en": shop,
                        "zh": zh,
                        "zh_src": zs,
                        "src": stem,
                        "m": g,
                    }
                )
            for name, lp in ents:
                for pat, kind, en in ENTS:
                    if re.search(pat, name):
                        g = tuple(a + b for a, b in zip(gp, U.rot(gq, lp)))
                        zh, zs = U.ZH.get(en, (en, "英文"))
                        add(
                            kind,
                            en,
                            zh,
                            f"{stem}/{re.sub(r'[-_]?\\d+$', '', name)}",
                            g,
                            zs,
                        )
                        break
        for p in pts:
            g = p.pop("m")
            kinds = p.pop("kinds", None)
            if kinds is None:
                kinds = [p["kind"]]
            row = {
                "city": rec or top,
                "site_en": site[0],
                "site_zh": site[1],
                "cat": p["kind"],
                "kinds": kinds,
                "en": p["en"],
                "zh": p["zh"],
                "zh_src": p["zh_src"],
                "area": "",
                "src": p["src"],
                "x": round(g[0] / 1000, 6),
                "y": round(g[1] / 1000, 6),
                "z": round(g[2] / 1000, 6),
                "up": [round(v, 5) for v in up],
            }
            if frame == "body":
                row["body"] = where
            else:
                row.update(body="", sys=where, space=True)
            (out if sysname == "Stanton" else later).append(row)
        print(f"  {site[1] or site[0]}（{frame}:{where}）{len(pts)} 个点")
    return out + later


def station_names():
    """rr_* 记录名 → (英文, 中文)：data/place_amenities.json（tools/unpack_amenities.py 从星图记录生成）"""
    try:
        rows = json.loads(
            (ROOT / "data" / "place_amenities.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return {}
    out = {}
    for r in rows:
        zh = re.sub(r"\s*[(（][^()（）]*[)）]\s*$", "", r.get("zh") or "").strip()
        out[(r.get("rec") or "").lower()] = (r.get("en") or "", zh)
    return out
