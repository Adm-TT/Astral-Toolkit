"""空间站里的导航点（2026-10-27，老大要「在主城或空间站里导航去最近的终端和商店」）：
从解开的物件容器里找出每个空间站（休息站 rs_ext_*、派罗的轨道站 station_ext_p*_leo）里的取船终端、商品交易终端、
货运电梯、诊所、商店……算出坐标，和城里的点一起写进 data/city_places.json（unpack_city.py 的 main 会调用这里）。
  坐标系：绕星球轨道的站（*-leo）跟着星球转，用星球局部坐标（千米，和城里的点一样）；
          拉格朗日点、跳跃点的站不跟星球转，用星系坐标（千米）+ space=True。
做法：先建「子容器 → 父容器」的反查表，从站一层层往上找到星球容器或星系根容器，把每层的 pos / rot 合起来。
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
TOP = re.compile(r"^rs_ext_[a-z0-9_\-]+$")
JP = {"stan-pyro_jp1": "stantonpyro", "stan-terra_jp1": "stantonterra", "stan-magnus_jp1": "stantonmagnus",
      "pyro-stan_jp1": "pyrostanton", "pyro-nyx_jp": "pyronyx", "nyx-pyro_jp1": "nyxpyro", "nyx-castra_jp1": "nyxcastra"}

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
    (r"^rstop_pharmacy", "Pharmacy"), (r"^util_armor_gen", "Armor"), (r"^util_shpweap_gen", "Ship Weapons"),
    (r"^lt_a_livefireweapons", "Live Fire Weapons"), (r"^lt_a_platinumbay", "Platinum Bay"), (r"^lt_a_casabaoutlet", "Casaba Outlet"),
    (r"^util_clth_gen", "Clothing Shop"), (r"^util_a_refinery_admin", "Refinery Shop"), (r"^cargo_office", "Cargo Center Supplies"),
    (r"^util_fdcrt_gnrc_sml_htdg", "Hot Dogs"), (r"^util_fdcrt_gnrc_sml_pza", "Pizza"), (r"^util_fdcrt_gnrc_sml_jce", "Juice Bar"),
    (r"^util_fdcrt_gnrc_sml_brt", "Burrito Bar"), (r"^util_fdcrt_gnrc_sml_ndle", "Noodle Bar"), (r"^util_ellroys", "Ellroy's"),
    (r"^util_bar_generic", "Bar"),
]
SELF_ZH = {"Hot Dogs": "热狗摊", "Pizza": "披萨摊", "Burrito Bar": "卷饼吧", "Juice Bar": "果汁吧", "Noodle Bar": "面条吧"}   # 汉化组没翻，自译进对照表（AGENTS.md）
SHOP_ZH_KEY = {"Pharmacy": "shop_name_pharmacy", "Clothing Shop": "shop_name_clothing", "Ship Weapons": "shop_name_shipweapons",
               "Bar": "interiormap_common_shop_bar"}
MERGE_M = 15
DONE_SYS = {"Stanton"}


def rec_of(stem):
    s = stem.lower()
    for pat, fmt in ((r"rs_ext_(hur|cru|arc|mic)-l(\d)", "rr_{0}_l{1}"), (r"rs_ext_(hur|cru|arc|mic)-leo1", "rr_{0}_leo"),
                     (r"rs_ext_pyro(\d)_l(\d)", "rr_p{0}_l{1}"), (r"rs_ext_pyro(\d)_leo", "rr_p{0}_leo")):
        m = re.fullmatch(pat, s)
        if m:
            return fmt.format(*m.groups())
    m = re.fullmatch(r"rs_ext_(.+)", s)
    return "rr_jp_" + JP[m[1]] if m and m[1] in JP else ""


def reverse_index(idx):
    """子容器 → [(父容器, pos, rot)]"""
    rev = {}
    for k, f in idx.items():
        for name, _ent, p, r in U.CHILD.findall(f.read_text(encoding="utf-8", errors="ignore")):
            s = Path(name.replace("\\", "/")).stem.lower()
            item = (k, tuple(float(v) for v in p.split(",")), tuple(float(v) for v in r.split(",")))
            if item not in rev.setdefault(s, []):
                rev[s].append(item)
    return rev


def bodies_of(rev, bodies):
    """星系根容器下面的星球容器 → 星图里的星球名（按位置对，差 5 km 内）"""
    out = {}
    for child, parents in rev.items():
        for parent, p, _q in parents:
            if parent in SYS_ROOT:
                best = min(((math.dist(p, (b["x"], b["y"], b["z"])), n) for n, b in bodies.items()
                            if b.get("sys") == SYS_ROOT[parent]), default=None)
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


def shop_zh(en):
    L = U.loc()
    key = SHOP_ZH_KEY.get(en) or "shop_name_" + re.sub(r"[^a-z]", "", en.lower())
    z = (L["zh"].get(key) or "").strip()
    if z and re.search(r"[\u4e00-\u9fff]", z):
        return z, "汉化组"
    return (SELF_ZH[en], "自译") if en in SELF_ZH else (en, "英文")


def build(idx, bodies, brand_kinds, names):
    rev = reverse_index(idx)
    body_of = bodies_of(rev, bodies)
    out = []
    for top in sorted(k for k in idx if TOP.match(k)):
        rec = rec_of(top)
        site = names.get(rec)
        if not site and rec:                       # 星图记录里没有设施的站：名字直接查汉化包 / 英文包
            L = U.loc()
            en_n, zh_n = L["en"].get(rec, ""), L["zh"].get(rec, "")
            if en_n and not en_n.startswith("@"):
                site = (en_n, re.sub(r"\s*[(（][^()（）]*[)）]\s*$", "", zh_n).strip())
        if not site:
            print(f"⚠ {top}：认不出是哪个站，跳过")
            continue
        r = resolve(top, rev, body_of)
        if not r:
            print(f"⚠ {top}（{site[0]}）：找不到它挂在哪，跳过")
            continue
        frame, where, P, Q = r
        sysname = where if frame == "sys" else (bodies.get(where) or {}).get("sys", "")
        if sysname not in DONE_SYS:
            # 派罗、尼克斯：星系文件里的星球位置和星图（starmap.space）对不上、站内容器也没解全，先不做（2026-10-27）
            print(f"  {site[1] or site[0]}：{sysname} 先不做")
            continue
        up = U.rot(Q, (0.0, 0.0, 1.0))
        nodes = [(top, top, P, Q, ())] + U.walk(idx, top, P, Q)
        pts = []

        def add(kind, en, zh, src, g, zsrc):
            near = next((p for p in pts if p["en"] == en and math.dist(p["m"], g) <= MERGE_M), None)
            if near:
                return
            pts.append({"kind": kind, "en": en, "zh": zh, "zh_src": zsrc, "src": src, "m": g})

        for stem, _ent, gp, gq, _anc in nodes:
            base_stem = re.sub(r"_\d+$", "", stem)
            shop = next((en for pat, en in SHOPS if re.search(pat, base_stem)), None)
            ents = U.soc_entities(idx, stem)
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
                pts.append({"kind": "商店", "kinds": kinds, "en": shop, "zh": zh, "zh_src": zs, "src": stem, "m": g})
            for name, lp in ents:
                for pat, kind, en in ENTS:
                    if re.search(pat, name):
                        g = tuple(a + b for a, b in zip(gp, U.rot(gq, lp)))
                        zh, zs = U.ZH.get(en, (en, "英文"))
                        add(kind, en, zh, f"{stem}/{re.sub(r'[-_]?\\d+$', '', name)}", g, zs)
                        break
        for p in pts:
            g = p.pop("m")
            kinds = p.pop("kinds", None)
            if kinds is None:
                kinds = [p["kind"]]
            row = {"city": rec, "site_en": site[0], "site_zh": site[1], "cat": p["kind"], "kinds": kinds,
                   "en": p["en"], "zh": p["zh"], "zh_src": p["zh_src"], "area": "", "src": p["src"],
                   "x": round(g[0] / 1000, 6), "y": round(g[1] / 1000, 6), "z": round(g[2] / 1000, 6),
                   "up": [round(v, 5) for v in up]}
            if frame == "body":
                row["body"] = where
            else:
                row.update(body="", sys=where, space=True)
            out.append(row)
        print(f"  {site[1] or site[0]}（{frame}:{where}）{len(pts)} 个点")
    return out


def station_names():
    """rr_* 记录名 → (英文, 中文)：data/place_amenities.json（tools/unpack_amenities.py 从星图记录生成）"""
    try:
        rows = json.loads((ROOT / "data" / "place_amenities.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for r in rows:
        zh = re.sub(r"\s*[(（][^()（）]*[)）]\s*$", "", r.get("zh") or "").strip()
        out[(r.get("rec") or "").lower()] = (r.get("en") or "", zh)
    return out
