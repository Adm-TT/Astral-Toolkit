"""城里导航的目的地（2026-10-27，先做新巴贝奇）：从解开的城市物件容器里找空港、取船终端、交易终端、商店、医院、地铁站台……
算出它们在星球上的坐标（星球自转坐标，千米，和星图、右上角调试信息同一个坐标系），写 data/city_places.json。
  .venv\\Scripts\\python.exe -X utf8 tools\\unpack_city.py E:\\Game3\\unpack\\city_x E:\\Game3\\unpack\\oc_x
要先用 StarBreaker 取出、解开城市的 socpak（unpack_all.py 里的 _unzip）。只发整理出的坐标和名字，不发游戏文件。
做法：容器 xml 里子容器的 pos / rot（四元数 w,x,y,z）一层层合起来；容器里的小物件（终端、柜台）位置在 .soc 的字符串表里：
「名字、半径、x,y,z」挨着写"""
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHILD = re.compile(r'<Child [^>]*?name="([^"]+)"[^>]*?entityName="([^"]*)"[^>]*?pos="([^"]+)" rot="([^"]+)"')
ENT = re.compile(rb"([A-Za-z][A-Za-z0-9_\-\.]{3,120})[\x00-\x1f]{1,8}(\d+(?:\.\d+)?)[\x00-\x1f]{1,8}"
                 rb"(-?\d+(?:\.\d+)?(?:e-?\d+)?,-?\d+(?:\.\d+)?(?:e-?\d+)?,-?\d+(?:\.\d+)?(?:e-?\d+)?)[\x00-\x1f]")

CITIES = {   # 城市 → (挂在哪个星球的容器里, 城市总容器, 星图里的星球名, 地点中文名)
    "NewBabbage": ("stanton4", "newbab_all", "Microtech", "新巴贝奇"),
    "Lorville": ("stanton1", "lorville", "Hurston", "罗威尔"),          # 2026-10-27 老大：四个主城都做
    "Area18": ("stanton3", "a18_city", "ArcCorp", "18区"),
    "Orison": ("stanton2", "orison_all", "Crusader", "奥里森"),
    "Levski": ("delamar", "levski", "Delamar", "列夫斯基"),
}

# 容器 → (类别, 英文名)。类别：空港 / 交易 / 商店 / 医院 / 地铁 / 公寓 / 其他
CONTAINERS = [
    (r"^newbab_sp_int$", "空港", "Spaceport"),
    (r"^lorville_sp_int$", "空港", "Teasa Spaceport"),
    (r"^a18_sp_int$", "空港", "Riker Memorial Spaceport"),
    (r"^orison_sp_int$", "空港", "August Dunlow Spaceport"),
    (r"^lorville_atc_office$", "空港", "Spaceport ATC"),
    (r"^lorville_hosp_int$", "医院", "Maria Pure of Heart Hospital"),
    (r"^a18_hospital_int$", "医院", "Area18 Hospital"),
    (r"^orison_hospital_int$", "医院", "Orison General Hospital"),
    (r"^levski_hosp_lobby$", "医院", "Mercy Hospital"),
    (r"^(mpoh_pharmacy|area_18_pharmacy|pharmacy_orison|levski_pharmacy)$", "医院", "Pharmacy"),
    (r"^health_insurance_mpoh$", "医院", "Health Insurance"),
    (r"^astroarmada_area18_int$", "买船", "Astro Armada"),
    (r"^crusader_showroom_int$", "买船", "Crusader Showroom"),
    (r"^teachsshipshop$", "买船", "Teach's Ship Shop"),
    (r"^(tdd_area18_int|tdd_orison)$", "交易", "Trade & Development Division"),
    (r"^(admin_med_base_a_loreville|admin_small_orison_a)$", "交易", "Admin Office"),
    (r"^atc_newbab", "空港", "Spaceport ATC"),
    (r"^tdd_newbab", "交易", "Trade & Development Division"),
    (r"^admin_newbab", "交易", "Admin Office"),
    (r"^omegapro_newbab", "商店", "Omega Pro"),
    (r"^centermass", "商店", "CenterMass"),
    (r"^microtech_factoryline", "商店", "microTech Factory Line"),
    (r"^aparelli", "商店", "Aparelli"),
    (r"^wallys_newbab", "商店", "Wally's Bar"),
    (r"^whammers", "商店", "Whammer's"),
    (r"^kel_to_constore", "商店", "Kel-To"),
    (r"^newbab_pharmacy", "医院", "Pharmacy"),
    (r"^health_insurance_newbab", "医院", "Health Insurance"),
    (r"^newbab_hosp$", "医院", "Hospital"),
    (r"^tran_plat_newbab_(\w+?)_line", "地铁", "Metro {0} Line"),
    (r"^tran_plat_lorville_(perim_line_[ab]|sp_line|com_line|cen_line)_([a-z]+\d?)(?:_\d+)?$", "地铁", "Lorville Metro {0} {1}"),
    (r"^newbab_hab_tower_lobby_int$", "公寓", "Hab Tower Lobby"),
    (r"^security_newbab", "其他", "Security Checkpoint"),
    (r"^refin_levski", "精炼", "Refinery"),
]
# 容器里的小物件 → (类别, 英文名[, 只认哪个容器里的])；同一种挨得近（20 米内）的合成一个点
ENTITIES = [
    (r"^VehicleShoppingPedestal", "买船", "New Deal", r"^lorville_sp_int$"),      # 罗威尔的全新交易在空港楼里，没有单独的容器
    (r"^ShipSelectorKiosk", "空港", "Fleet Manager Terminal"),
    (r"FreightElevatorKiosk", "货梯", "Freight Elevator"),
    (r"FineTerminal$|FineTerminal_", "罚款", "Fine Terminal"),
    (r"^ShopKiosk_Rentals", "租船", "Rentals"),
    (r"CommodityKiosk_kiosk_tdd", "交易", "Commodity Terminal"),
    (r"^Counter_Admin", "交易", "Admin Counter", r"admin"),        # 商店里的柜台也叫 Counter_Admin_*（卡莎巴…），只认行政中心里的
    (r"HospitalCheckIn", "医院", "Hospital Check-In"),
    (r"^Console_Standing_Angled_console_info", "其他", "Info Console"),
    (r"ShoppingKiosk", "商店", "Shopping Kiosk"),
    (r"^TagPoint_FTUE_", "引导", "{name}"),
]
MERGE_M = 20
# 房间类的目的地（店、柜台所在的房间）：房间原点可能在墙里（2026-10-27 实测「健康保险」指到墙上），
# 改指向房间里离原点最近的能交互的东西：柜台、终端、登记台
SNAP = (r"Counter_Reception|counter_welcome|Counter_Admin|HospitalCheckIn|CommodityKiosk|ShoppingKiosk|ShipSelectorKiosk|Console_Standing|Terminal"
        r"|^ShopKiosk|VehicleShoppingPedestal|Counter_Shop")              # 买船：店里的购买终端 / 展台
SNAP_M = 80
# 容器名 → 所在区域，用汉化组的区域名（global_zh.ini 的 Stanton4_NewBab_*）
AREAS = {
    "NewBabbage": [
        ("sp_surface_entrance", "NBIS 航站楼 · 地面出入口"), ("surfaceentrance", "地面出入口"), ("newbab_sp", "NBIS 航站楼"),
        ("atc_newbab", "NBIS 航站楼"), ("hab_tower", "志远大厦"), ("promenade", "市民广场"), ("commons", "市民广场"),
        ("tran_plat_elev", "地铁站"), ("tran_plat", "地铁站"), ("admin_newbab", "市民广场"),
        ("health_insurance", "布伦特沃斯医护中心"), ("pharmacy", "布伦特沃斯医护中心"), ("hosp", "布伦特沃斯医护中心"),
        ("tdd_newbab", "市民广场"), ("security_newbab", "NBIS 航站楼")],
    "Lorville": [("lorville_sp", "蒂莎空港"), ("lorville_atc", "蒂莎空港"), ("lorville_hosp", "玛利亚纯洁之心医院"),
                 ("mpoh", "玛利亚纯洁之心医院"), ("tran_plat", "地铁站")],
    "Area18": [("a18_sp", "里克纪念空港"), ("a18_hospital", "帝国医疗服务医疗站"), ("area_18_pharmacy", "帝国医疗服务医疗站")],
    "Orison": [("orison_sp", "奥古斯特·顿洛 空港"), ("orison_hospital", "奥里森综合医院"), ("pharmacy_orison", "奥里森综合医院")],
    "Levski": [("levski_hosp", "仁慈医院"), ("levski_pharmacy", "仁慈医院")],
}
# 地铁站台：哪条线、哪个站（分段路线用，2026-10-27）。新巴贝奇是一条环线（微科地铁环线），罗威尔几条线在地铁中心换乘
LINE_ZH = {"loop": ("MetroLoop", "微科地铁环线", "汉化组"), "perim_line_a": ("Perimeter Line A", "外环 A 线", "自译"),
           "perim_line_b": ("Perimeter Line B", "外环 B 线", "自译"), "sp_line": ("Spaceport Line", "空港线", "自译"),
           "com_line": ("Commerce Line", "商业线", "自译"), "cen_line": ("Central Line", "中央线", "自译")}
STOP_ZH = {"gate1": ("City Gates 01", "城市大门 01"), "gate2": ("City Gates 02", "城市大门 02"), "gate3": ("City Gates 03", "城市大门 03"),
           "gate4": ("City Gates 04", "城市大门 04"), "gate5": ("City Gates 05", "城市大门 05"), "gate6": ("City Gates 06", "城市大门 06"),
           "mc": ("Metro Center", "地铁中心"), "sp": ("Teasa Spaceport", "蒂莎空港"), "lvsdn": ("Leavsden Station", "列维斯登站")}
# 新巴贝奇环线的站（汉化组：ui_interactor_ST4_Transit_*、area_map_pu_newbab_*）；以前自译成「空港线」「广场线」，其实是站名
NB_STOP_ZH = {"sp": ("Spaceport", "主要空港"), "expo": ("Tobin Expo", "托宾中心"), "commons": ("Commons", "市民广场"),
              "ag": ("Aspire Grand", "志远大厦")}


def metro_info(stem):
    """站台容器名 → (线, 站)；不是站台返回 None"""
    m = re.match(r"^tran_plat_newbab_(\w+?)_line", stem, re.I)
    if m:
        return "loop", m[1].lower()
    m = re.match(r"^tran_plat_lorville_(perim_line_[ab]|sp_line|com_line|cen_line)_([a-z]+\d?)(?:_\d+)?$", stem, re.I)
    if m:
        return m[1].lower(), m[2].lower()
    return None


SKIP_CATS = {"引导"}           # 游戏自己的新手引导点（TagPoint_FTUE_*）：先不当目的地，留着以后做路线用

# 中文名：(中文, 来源)。来源「汉化组」= global_zh.ini 里有（Maps_Amenities_*、物品名里的店名、提示里的「登记处」）；
# 「自译」= 汉化组没有，写进 翻译对照\自译对照_词表.csv 给老大改；品牌名汉化组没翻的保持英文
ZH = {
    "Spaceport": ("空港", "自译"),
    "Spaceport ATC": ("空港调度台", "自译"),
    "Fleet Manager Terminal": ("舰队管理器终端", "汉化组"),          # 汉化组 tut03_part02_hint01_toasop_title（以前叫 ASOP 终端）
    "Trade & Development Division": ("TDD 贸易发展部", "自译"),
    "Commodity Terminal": ("商品交易终端", "自译"),
    "Freight Elevator": ("货运电梯", "汉化组"),                      # area_name_freightelevator
    "Fine Terminal": ("罚款终端", "自译"),
    "Refinery": ("精炼厂", "汉化组"),                                 # ui_interactor_generic_refinery
    "Rentals": ("租赁柜台", "自译"),
    "Clinic Check-In": ("诊所登记处", "自译"),
    "Admin Office": ("行政中心", "自译"),
    "Admin Counter": ("行政中心柜台", "自译"),
    "Omega Pro": ("Omega Pro", "英文"),
    "CenterMass": ("CenterMass", "英文"),
    "microTech Factory Line": ("microTech Factory Line", "英文"),
    "Aparelli": ("Aparelli", "英文"),
    "Wally's Bar": ("沃利酒吧", "汉化组"),
    "Whammer's": ("重锤汉堡", "汉化组"),
    "Kel-To": ("凯尔托", "汉化组"),
    "Pharmacy": ("药店", "汉化组"),           # 汉化组 shop_name_pharmacy（2026-10-27 以前自译「药房」）
    "Health Insurance": ("健康保险", "自译"),
    "Hospital": ("布伦特沃斯医护中心", "汉化组"),
    "Hospital Check-In": ("医院登记处", "汉化组"),
    "Metro Ag Line": ("地铁站台（AG 线）", "自译"),
    "Metro Commons Line": ("地铁站台（广场线）", "自译"),
    "Metro Sp Line": ("地铁站台（空港线）", "自译"),
    "Metro Expo Line": ("地铁站台（展览线）", "自译"),
    "Hab Tower Lobby": ("公寓楼大堂", "自译"),
    "Security Checkpoint": ("安检", "自译"),
    "Info Console": ("问讯台", "自译"),
    "Shopping Kiosk": ("购物终端", "自译"),
    "Teasa Spaceport": ("蒂莎空港", "汉化组"),
    "Riker Memorial Spaceport": ("里克纪念空港", "汉化组"),
    "August Dunlow Spaceport": ("奥古斯特·顿洛 空港", "汉化组"),
    "Maria Pure of Heart Hospital": ("玛利亚纯洁之心医院", "汉化组"),
    "Area18 Hospital": ("帝国医疗服务医疗站", "汉化组"),
    "Orison General Hospital": ("奥里森综合医院", "汉化组"),
    "Mercy Hospital": ("仁慈医院", "汉化组"),
    "New Deal": ("全新交易", "汉化组"),
    "Astro Armada": ("天文舰队", "汉化组"),
    "Crusader Showroom": ("十字军展厅", "汉化组"),
    "Teach's Ship Shop": ("蒂奇的飞船店", "汉化组"),
}


def qmul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2)


def rot(q, v):
    w, x, y, z = q
    return qmul(qmul(q, (0, *v)), (w, -x, -y, -z))[1:]


def index(dirs):
    idx = {}
    for root in dirs:
        for d in Path(root).iterdir():
            if d.is_dir():
                for f in d.glob("*.xml"):
                    if not f.name.endswith("_editor.xml"):
                        idx[f.stem.lower()] = f
    return idx


PARENTS = {}                  # 容器名 → 外面那层容器名（找区域用：店在哪个大区里）


def walk(idx, stem, pos, q, depth=0, out=None, anc=()):
    """→ [(容器名, 实体名, 位置, 四元数, 上层容器链)]，位置和朝向都是相对最上面那层"""
    out = [] if out is None else out
    anc = anc + (stem.lower(),)
    f = idx.get(stem.lower())
    if not f or depth > 8:
        return out
    for name, ent, p, r in CHILD.findall(f.read_text(encoding="utf-8", errors="ignore")):
        s = Path(name.replace("\\", "/")).stem
        lp = tuple(float(v) for v in p.split(","))
        lq = tuple(float(v) for v in r.split(","))
        gp = tuple(a + b for a, b in zip(pos, rot(q, lp)))
        gq = qmul(q, lq)
        out.append((s, ent, gp, gq, anc))
        PARENTS.setdefault(s.lower(), stem.lower())
        walk(idx, s, gp, gq, depth + 1, out, anc)
    return out


def soc_entities(idx, stem):
    f = idx.get(stem.lower())
    if not f:
        return []
    soc = f.with_suffix(".soc")
    if not soc.exists():
        return []
    out = []
    for m in ENT.finditer(soc.read_bytes()):
        try:
            out.append((m.group(1).decode(), tuple(float(v) for v in m.group(3).decode().split(","))))
        except ValueError:
            pass
    return out


_LOC = {}


def loc():
    """汉化包和英文包（店名 shop_name_*、罗威尔的门 ATC_Lorville_GateNN）"""
    if not _LOC:
        sys.path.insert(0, str(ROOT))
        from sc_mining.localization import read_ini
        for lang, f in (("zh", ROOT / "data" / "loc" / "global_zh.ini"),
                        ("en", Path(r"E:\Game3\unpack\p4k_out\Data\Localization\english\global.ini"))):
            try:
                _LOC[lang] = {k.lower(): v.split("\\n")[0].strip() for k, v in read_ini(f).items()}
            except OSError:
                _LOC[lang] = {}
    return _LOC


def shop_of(stem):
    """容器名 → 汉化包里的店名 (英文, 中文)：tammanyandsons_lorville_int → Tammany and Sons / 坦姆尼父子"""
    L = loc()
    flat = re.sub(r"[^a-z]", "", stem.lower())
    best = None
    for k, en in L["en"].items():
        if k.startswith("shop_name_"):
            key = re.sub(r"[^a-z]", "", k[10:])
            if len(key) >= 4 and key in flat and L["zh"].get(k) and (best is None or len(key) > len(best[0])):
                best = (key, en, L["zh"][k])
    return best[1:] if best else None


def gate_of(anc):
    """罗威尔的门：上层容器里有 gate_0N_int → 「罗威尔 N 号门」（汉化组 ATC_Lorville_Gate0N）"""
    for a in reversed(anc or ()):
        m = re.fullmatch(r"gate_0?(\d)_int", a)
        if m:
            return loc()["zh"].get(f"atc_lorville_gate0{m[1]}", "")
    return ""


def area_of(stem, city="NewBabbage"):
    """自己的容器名先找，找不到往外一层层找（店 → 所在的广场 / 大楼）"""
    s, seen = stem.lower(), set()
    while s and s not in seen:
        seen.add(s)
        hit = next((zh_a for key, zh_a in AREAS.get(city, []) if key in s), "")
        if hit:
            return hit
        s = PARENTS.get(s, "")
    return ""


def snap(idx, stem, gp, gq):
    """房间原点 → 房间里离原点最近的柜台 / 终端（SNAP_M 米内）；没有就还是原点"""
    best = None
    for name, lp in soc_entities(idx, stem):
        if re.search(SNAP, name, re.I):
            g = tuple(a + b for a, b in zip(gp, rot(gq, lp)))
            d = math.dist(g, gp)
            if d <= SNAP_M and (best is None or d < best[0]):
                best = (d, g)
    return best[1] if best else gp


def build(dirs, only=None):
    idx = index(dirs)
    places = []
    for city, (planet_stem, top, body, city_zh) in CITIES.items():
        if only and city != only:
            continue
        if planet_stem not in idx:
            print(f"⚠ 找不到 {planet_stem} 的星球容器，{city} 跳过")
            continue
        t = idx[planet_stem].read_text(encoding="utf-8", errors="ignore")
        m = re.search(r'<Child [^>]*?name="[^"]*/' + top + r'\.socpak"[^>]*?pos="([^"]+)" rot="([^"]+)"', t, re.I)
        if not m:
            print(f"⚠ {planet_stem} 里找不到 {top}，{city} 跳过")
            continue
        P = tuple(float(v) for v in m.group(1).split(","))
        Q = tuple(float(v) for v in m.group(2).split(","))
        nodes = [(top, top, P, Q, ())] + walk(idx, top, P, Q)
        seen = {}
        for stem, ent, gp, gq, anc in nodes:
            for pat, cat, en in CONTAINERS:
                mm = re.search(pat, stem, re.I)
                if mm:
                    en2 = en.format(*(g.capitalize() for g in mm.groups()))
                    key = (cat, en2)
                    if key not in seen:       # 同名容器只要第一个（城市里同一家店只有一个；有多个的按实体合并）
                        seen[key] = True
                        places.append({"city": city, "body": body, "cat": cat, "en": en2, "src": stem, "m": snap(idx, stem, gp, gq),
                                       "_anc": anc})
                    break
            for name, lp in soc_entities(idx, stem):
                base = re.sub(r"[-_]\d{2,}$", "", name)
                for pat, cat, en, *only_in in ENTITIES:
                    if only_in and not re.search(only_in[0], stem, re.I):
                        continue
                    if re.search(pat, base):
                        g = tuple(a + b for a, b in zip(gp, rot(gq, lp)))
                        label = en.format(name=re.sub(r"^TagPoint_FTUE_", "", base).replace("_", " "))
                        near = next((p for p in places if p["en"] == label and p["city"] == city and
                                     math.dist(p["m"], g) <= MERGE_M), None)
                        if near:
                            near.setdefault("_pts", [near["m"]]).append(g)
                            k = len(near["_pts"])
                            near["m"] = tuple(sum(v[i] for v in near["_pts"]) / k for i in range(3))
                        else:
                            places.append({"city": city, "body": body, "cat": cat, "en": label, "src": f"{stem}/{base}", "m": g,
                                           "_anc": anc})
                        break
    out = []
    for p in places:
        if p["cat"] in SKIP_CATS:
            continue
        p.pop("_pts", None)
        x, y, z = (round(v / 1000, 5) for v in p.pop("m"))           # 米 → 千米（星图的单位）
        zh, src = ZH.get(p["en"], (p["en"], "英文"))
        if p["en"] == "Shopping Kiosk":                               # 购物终端：前面带上是哪家店的
            shop = next((q for q in places if q["cat"] == "商店" and q["src"] == p["src"].split("/")[0]), None)
            named = None if shop else shop_of(p["src"].split("/")[0])     # 没列在 CONTAINERS 里的店：按汉化包的店名表认
            if shop:
                zh = f"{ZH.get(shop['en'], (shop['en'],))[0].split('（')[0]} 购物终端"
                p["en"] = f"{shop['en']} Shopping Kiosk"
            elif named:
                zh, src = f"{named[1]} 购物终端", "汉化组"
                p["en"] = f"{named[0]} Shopping Kiosk"
        anc = p.pop("_anc", ())
        area = gate_of(anc) or area_of(p["src"].split("/")[0], p["city"])
        mi = metro_info(p["src"]) if p["cat"] == "地铁" else None
        if mi:
            p["line"], p["stop"] = mi
            le, lz, lsrc = LINE_ZH.get(mi[0], (mi[0], mi[0], "英文"))
            stops = NB_STOP_ZH if p["city"] == "NewBabbage" else STOP_ZH
            if mi[1] in stops:
                se, sz = stops[mi[1]]
                p["en"], zh, src = f"Metro {le} - {se}", f"地铁站台 · {sz}（{lz}）", lsrc
        if zh == "购物终端" and area:                                 # 认不出是哪家店：至少写上在哪个区
            zh = f"购物终端 · {area}"
        out.append({**p, "zh": zh, "zh_src": src, "area": area, "x": x, "y": y, "z": z})
    from collections import Counter
    dup = Counter((q["city"], q["zh"]) for q in out)
    for q in out:                                  # 同一个城里重名的加上区域：「ASOP 终端（取船）· 空港」
        if dup[(q["city"], q["zh"])] > 1 and q["area"]:
            q["zh"] = f"{q['zh']} · {q['area']}"
    return out


# 导航分类（2026-10-27：在主城 / 空间站里点一下去最近的）。店按 data/shops.json（UEX）里卖的东西分
KIND_ORDER = ["取船", "交易", "货梯", "医院", "武器", "护甲", "服装", "部件", "吃喝", "精炼", "行政", "罚款", "租船", "买船", "地铁"]
CAT_KINDS = {"交易": ["交易"], "医院": ["医院"], "买船": ["买船"], "地铁": ["地铁"], "货梯": ["货梯"], "罚款": ["罚款"],
             "精炼": ["精炼"], "租船": ["租船"], "行政": ["行政"]}
GROUP = {"武器": {"Guns", "Personal Weapons", "Attachments", "Gadgets", "Throwables", "Grenades"},
         "护甲": {"Arms", "Legs", "Torso", "Helmets", "Undersuits", "Backpacks"},
         "服装": {"Jackets", "Footwear", "Legwear", "Shirts", "Hats", "Gloves", "Eyewear"},
         "吃喝": {"Foods", "Drinks"},
         "部件": {"Radar", "Coolers", "Missiles", "Quantum Drives", "Power Plants", "Shield Generators", "Missile Racks", "Turrets",
                "Bomb Racks", "External Fuel Tanks", "Tractor Beams", "Flight Blade", "Module", "Mining Modules", "Mining Laser Heads",
                "Scraper Beams", "Jump Modules", "Docking Collars"}}
CITY_EN = {"NewBabbage": "New Babbage", "Lorville": "Lorville", "Area18": "Area 18", "Orison": "Orison", "Levski": "Levski"}


def _brand(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def brand_kinds():
    """店名 → 导航分类（这家店卖的东西里占 25% 以上的类）；药店（主要卖药）→ 医院"""
    try:
        d = json.loads((ROOT / "data" / "shops.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    cat_of = {c: g for g, cs in GROUP.items() for c in cs}
    from collections import Counter
    cnt = {}
    for r in d.get("rows") or []:
        try:
            b = _brand(str(r[1]).split(" - ")[0])
            c = (d["items"].get(str(r[0])) or ["", ""])[1]
        except (IndexError, KeyError, TypeError):
            continue
        cnt.setdefault(b, Counter())[cat_of.get(c, "药" if c == "Consumables" else "")] += 1
    out = {}
    for b, c in cnt.items():
        tot = sum(c.values())
        if c["药"] / tot >= 0.5:
            out[b] = ["医院"]
            continue
        out[b] = [g for g, v in c.most_common() if g in GROUP and v / tot >= 0.25]
    return out


def add_kinds(places, bk):
    """城里的点加上导航分类、所在地（中英文）"""
    for p in places:
        cat, en = p.get("cat"), p.get("en") or ""
        if en == "Fleet Manager Terminal":
            kinds = ["取船"]
        elif en in ("Admin Office", "Admin Counter"):
            kinds = ["行政"]
        elif cat == "商店":
            kinds = bk.get(_brand(re.sub(r" Shopping Kiosk$", "", en))) or []
            if en in ("Pharmacy",) or en.startswith("Pharmacy"):
                kinds = ["医院"]
        else:
            kinds = CAT_KINDS.get(cat, [])
        p["kinds"] = [k for k in KIND_ORDER if k in kinds]
        if "site_en" not in p:
            p["site_en"] = CITY_EN.get(p.get("city"), p.get("city", ""))
            p["site_zh"] = CITIES.get(p.get("city"), ("", "", "", ""))[3]
    return places


def main():
    dirs = sys.argv[1:] or [d for d in (r"E:\Game3\unpack\city_x", r"E:\Game3\unpack\oc_x", r"E:\Game3\unpack\loc_x",
                                        r"E:\Game3\unpack\stn_x") if Path(d).exists()]
    bk = brand_kinds()
    places = add_kinds(build(dirs), bk)
    try:                                           # 空间站里的点（tools/unpack_stations.py）
        import unpack_stations as S
        sys.path.insert(0, str(ROOT))
        from sc_mining import navigate as N
        st = S.build(index(dirs), N.load()["bodies"], bk, S.station_names())
        for p in st:
            p["kinds"] = [k for k in KIND_ORDER if k in p["kinds"]]
        print(f"空间站里的点 {len(st)} 个")
        places += st
    except Exception as e:                         # 站没解出来不影响城里的
        import traceback
        traceback.print_exc()
        print(f"⚠ 空间站没做成：{e}")
    dst = ROOT / "data" / "city_places.json"
    dst.write_text(json.dumps(places, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    print(f"✅ 城里目的地 {len(places)} 个 → {dst}：{dict(Counter((p['city'], p['cat']) for p in places))}")
    for p in places:
        print(f"  {p['cat']}  {p['zh']:<28} {p['en']:<40} {p['src']}")
    # 自译的词写进对照表（已经有的不重复写），老大在「改成」列改
    csv = ROOT / "翻译对照" / "自译对照_词表.csv"
    if csv.exists():
        import csv as _csv
        rows = list(_csv.reader(csv.open(encoding="utf-8-sig")))
        have = {r[0] for r in rows[1:] if r}
        new = sorted({(p["en"], p["zh"]) for p in places if p["zh_src"] == "自译" and p["en"] not in have})
        if new:
            with csv.open("a", encoding="utf-8", newline="") as f:          # 追加不能再写 BOM
                w = _csv.writer(f)
                for en, zh in new:
                    w.writerow([en, zh, "自译（城里导航）", 1, ""])
            print(f"自译对照_词表.csv 加了 {len(new)} 个词")


if __name__ == "__main__":
    main()
