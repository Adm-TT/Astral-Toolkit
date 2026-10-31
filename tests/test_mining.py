import pytest
"""挖矿核心、读屏解析、精炼、制造、导航、游戏辅助"""
from sc_mining.mining.signals import match_signature  # noqa: E402
from sc_mining.mining.laser import recommend, evaluate, loadout, verdict, HeadSetup  # noqa: E402, F401
from sc_mining.mining.refinery import best_stations  # noqa: E402
from sc_mining.mining import data  # noqa: E402

AUTHOR = HeadSetup("helix_ii", ["rieger_c3", "rieger_c3", "focus_iii"])   # 作者那套 MOLE 的第一个矿头


def _author_mole(monkeypatch, tmp_path):
    """测试用作者的两人 MOLE 配装（不读电脑上真实的设置）"""
    from sc_mining.core import settings
    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    settings.update(mining_ship="mole", mining_loadouts={"mole": data.AUTHOR_MOLE})


def test_signature_examples():
    # 社区工具里的实测例子
    assert ("Quantainium", 3, "传说") in match_signature(9510)
    assert ("Quartz", 4, "普通") in match_signature(16840)
    assert ("Aluminum", 4, "普通") in match_signature(17140)
    assert match_signature(12345) == []


def test_break_formula_single_head():
    helix = AUTHOR
    # Helix II + C3×2 + Focus III：4930 × 1.25 × 1.25 × 0.95
    assert round(helix.max_power()) == round(4930 * 1.25 * 1.25 * 0.95)
    p = evaluate([helix], None, mass=10000, resistance_pct=0, instability=10, k=0.2)
    assert p.threshold == 2000
    assert p.breakable
    # 同一块石头在各模型下都给出对照
    assert evaluate([helix], None, 10000, 0, 10).k == 0.2   # 默认就是用户公式


def test_matches_scminer_breakability_matrix():
    # SCMiner「Can I Crack It?」全矿头表：5000 kg、0% 抗性、无模组
    expected = {"helix_ii": 274, "hofstede_s2": 226, "arbor_mh2": 161, "lancet_mh2": 242}
    for key, pct in expected.items():
        p = evaluate([HeadSetup(key, [])], None, mass=5000, resistance_pct=0, instability=0,
                     k=data.BREAK_MODELS["scminer"])
        assert p.threshold == 1800
        assert round(p.ratio * 100) == pct, key
    assert verdict(2.17) == "单人可破" and verdict(1.0) == "需要贴工具" and verdict(0.5) == "需要多人"


def test_resistance_reduces_power():
    helix = AUTHOR
    easy = evaluate([helix], None, 20000, 0, 10)
    hard = evaluate([helix], None, 20000, 60, 10)
    assert hard.ratio < easy.ratio


def test_big_rock_needs_two_heads_or_gadget(monkeypatch, tmp_path):
    _author_mole(monkeypatch, tmp_path)
    best = recommend(mass=35000, resistance_pct=30, instability=20)[0]
    assert best.breakable
    assert len(best.heads) == 2 or best.gadget is not None


def test_refinery_picks_quartz_station():
    top = best_stations({"Quartz": 20}, system="Stanton")[0]
    assert top[0] in ("ARC-L1", "Nyx Gateway (Stanton)")


def test_all_signatures_have_rarity():
    assert set(data.SIGNATURES) == set(data.RARITY)


def test_loadout_uses_arbor_and_methods():
    assert [k for k, _ in data.DEFAULT_LOADOUTS["mole"]["heads"]] == ["arbor_mh2"] * 3     # MOLE 出厂配装
    assert data.DEFAULT_METHODS == ["Dinyx Solventation", "Ferron Exchange"]


def test_sell_only_main_cities():
    allowed = set(data.SELL_TERMINALS.values())
    for cities in data.CITY_PRICES.values():
        assert set(cities) <= allowed
    # 2026-10-28 起矿价会被 data/prices.json（更新数据下的 UEX 矿价）覆盖，不再比写死的数：按表算最高价核对
    for m in ("Quantainium", "Riccite"):
        price, city = data.best_price(m)
        assert (price, city) == max(((v, c) for c, v in data.CITY_PRICES[m].items()), key=lambda x: x[0]) and city in allowed
        assert price > 0
    assert data.CITY_PRICES["Quantainium"]["Orison"] > 0 and data.CITY_PRICES["Riccite"]["Levski"] > 0


def test_i18n_minerals():
    from sc_mining.core.i18n import mineral_en, mineral_zh
    assert mineral_en("量子矿物") == "Quantainium"
    assert mineral_en("量子矿物原矿") == "Quantainium"
    assert mineral_en("砬兰石") == "Laranite"
    assert mineral_en("塔兰导电") == "Taranite"   # OCR 少一个字也能认
    assert mineral_en("压缩冰") == "Ice"
    assert mineral_zh("Gold") == "金"
    for en in data.SIGNATURES:
        assert mineral_zh(en) != en, en


def test_calibration_from_observations(monkeypatch, tmp_path):
    import tempfile
    from pathlib import Path
    from sc_mining.mining import laser as calibrate
    from sc_mining.mining.laser import active_model
    _author_mole(monkeypatch, tmp_path)             # 按作者的 MOLE 配装（Helix II 带满模组），不读电脑上真实的设置
    old = calibrate.LOG
    calibrate.LOG = Path(tempfile.mkdtemp()) / "obs.csv"
    try:
        assert active_model() == ("user", 0.2)
        # Helix II 满配输出 ≈7318 W（0% 抗性）
        calibrate.record(20000, 0, "helix_ii", None, 1.0, True)    # 满功率破开 → K ≤ 0.366
        calibrate.record(25000, 0, "helix_ii", None, 1.0, False)   # 满功率没破 → K > 0.293
        calibrate.record(15000, 0, "helix_ii", None, 0.8, True)    # 80% 破开 → K ≤ 0.390
        k = calibrate.calibrated_k(0.2)
        assert 0.293 < k < 0.366                     # 能算出拟合值供核对
        assert active_model() == ("user", 0.2)       # 但不会自动改公式
    finally:
        calibrate.LOG = old


def test_user_formula_example():
    # 用户给的公式：矿头功率 × 模组功率 × (1 − 抗性) × 5
    # 螺旋2 4080 W + 里格-C3 ×3 → 4080 × 1.25³ × 5 = 39843；20% 抗性 → ×0.8 = 31875
    from sc_mining.mining import laser  # noqa: F401
    h = HeadSetup("helix_ii", ["rieger_c3"] * 3)
    orig = dict(data.HEADS["helix_ii"])
    data.HEADS["helix_ii"].update(pmax=4080, res=0)   # 例子里没算矿头自带的抗性修正
    try:
        p0 = evaluate([h], None, 10000, 0, 0, k=0.2)
        p20 = evaluate([h], None, 10000, 20, 0, k=0.2)
        assert round(p0.max_mass) == 39844 and int(p0.max_mass) == 39843
        assert round(p20.max_mass) == 31875
    finally:
        data.HEADS["helix_ii"].clear(); data.HEADS["helix_ii"].update(orig)  # noqa: E702


def _items(spec):
    # spec: [(文字, x, y)]，模拟 OCR 输出，字高 30
    return [(t, (x, y), 30) for t, x, y in spec]


def test_parse_scan_from_screenshot():
    # 来自用户 2560×1440 截图（MOLE 驾驶位）的扫描面板，故意带了 OCR 常见毛病
    from sc_mining.mining.parse import rows, parse_scan
    lines = rows(_items([
        ("扫描结果", 60, 10),
        ("量子矿物原矿", 80, 70),
        ("质量：", 40, 130), ("43066", 400, 132),
        ("抗性:", 40, 190), ("69%", 400, 188),
        ("不稳定性：", 60, 250), ("407.87", 400, 251),
        ("组成", 40, 400), ("28.45 SCU", 500, 402),
        ("9.32%", 40, 520), ("量子矿物原矿", 280, 521), ("974", 560, 519),
        ("39.28%", 40, 560), ("量子矿物原", 280, 561), ("344", 560, 559),
        ("7.95%", 40, 600), ("绿柱石原矿", 280, 600), ("547", 560, 601),
        ("43,42%", 40, 640), ("惰性物质", 280, 641), ("0", 560, 640),
    ]))
    s = parse_scan(lines)
    assert s.rock == "Quantainium"
    assert (s.mass, s.resistance, s.instability, s.total_scu) == (43066, 69, 407.87, 28.45)
    assert s.composition == [("Quantainium", 9.32, 974), ("Quantainium", 39.28, 344),
                             ("Beryl", 7.95, 547), ("Inert Materials", 43.42, 0)]
    scu = s.minerals_scu()
    assert round(scu["Quantainium"], 2) == 13.83 and round(scu["Beryl"], 2) == 2.26


def test_parse_bag():
    from sc_mining.mining.parse import rows, parse_bag
    lines = rows(_items([("货舱", 40, 10), ("0.30 / 96.00 SCU", 500, 12),
                         ("惰性物质", 40, 120), ("0.30 SCU", 500, 121)]))
    bag, used, cap = parse_bag(lines)
    assert (used, cap) == (0.30, 96.0) and bag == {"Inert Materials": 0.30}


def test_real_ocr_output_from_user_pc():
    # 用户电脑上 RapidOCR 对 2K 截图的真实识别结果（含形近字误认）
    from sc_mining.mining.parse import parse_scan, parse_bag
    scan = parse_scan(["扫装结家", "J", "量子物展", "质量 43056", "特作： 69%", "不微定性 407.87",
                       "A 心 一 ·", "人数消 组成 28.45 SCU", "9.32% 量子矿物联矿 974",
                       "39.28% 姐子矿物医矿 344", "7.95% 绿桂石速 647", "43,4296 情经特质 。"])
    assert scan.rock == "Quantainium" and scan.resistance == 69 and scan.instability == 407.87
    assert [(n, p) for n, p, _ in scan.composition] == [
        ("Quantainium", 9.32), ("Quantainium", 39.28), ("Beryl", 7.95), ("Inert Materials", 43.42)]
    assert parse_bag(["就能 0.30/%.00 SCU", "一", "情性物费 口 0.305CU", "247"]) == \
        ({"Inert Materials": 0.3}, 0.3, 96.0)


def test_real_ocr_turret_view():
    # 用户电脑上炮塔位截图的真实识别结果
    from sc_mining.mining.parse import parse_scan, parse_bag
    s = parse_scan(["扫描结果", "J", "钨矿石", "质量： 44336", "抗性： 4% ", "不稳定性： 17.32",
                    "（地狱IMPOSSIBLE）", "组成 23.68 SCU", "e8888080028888814181108888888888",
                    "6.55% 兰石原矿 510", "12.95% 钨矿石 662", "49.41% 钨矿石 363", "31.07% 情性物质 。"])
    assert (s.rock, s.mass, s.resistance, s.instability, s.total_scu, s.difficulty) == \
        ("Tungsten", 44336, 4, 17.32, 23.68, "地狱")
    assert [(n, p) for n, p, _ in s.composition] == [
        ("Laranite", 6.55), ("Tungsten", 12.95), ("Tungsten", 49.41), ("Inert Materials", 31.07)]
    assert parse_bag(["胱酸0301950 0.30/96.00SCU J", "怕性物费 口 0 1.305CU"]) == ({}, 0.3, 96.0)


def test_refining_matches_scminer_simulator():
    # SCMiner 精炼模拟器：32 SCU 量子矿，Dinyx/Ferron 产出 14.4 SCU（45%），精炼费 2,560 / 3,200
    from sc_mining.mining.refinery import refined_scu, refine_fee
    bag = {"Quantainium": 32}
    for method, fee in (("Dinyx Solventation", 2560), ("Ferron Exchange", 3200)):
        assert round(refined_scu(bag, "MIC-L1", method)["Quantainium"], 2) == 14.4   # MIC-L1 无量子加成
        assert refine_fee(bag, method) == fee


def test_signature_snap_and_scminer_values():
    from sc_mining.mining.signals import snap
    assert data.SIGNATURES["Agricium"] == 3885          # SCMiner 值（grimhex 是 3895）
    assert snap("9510") == (9510, False)
    assert snap("9570") == (9510, True)                  # 一位读错，吸附回量子 ×3
    assert snap("98510") == (None, False)
    assert snap("6285") == (None, False) and snap("7185") == (None, False)   # 改一位能凑成 4,285 / 3,185，但差太远：不改（交给最接近）


def test_where_to_mine():
    from sc_mining.mining.locations import where, LOCATIONS, _match_zh
    assert len(LOCATIONS) == 51
    top = where("Tungsten")[0]
    assert top[0] == 29
    assert {loc["name"] for _, loc in where("Lindinium")} == {"Glaciem Ring", "Keeger Belt"}
    assert _match_zh("量子") == "Quantainium" and _match_zh("塔兰") == "Taranite"
    for loc in LOCATIONS:                       # 地点里的矿名都在矿物表里
        assert set(loc["minerals"]) <= set(data.SIGNATURES), loc["name"]


def test_crafting_dataset_and_links():
    from sc_mining.crafting import crafting as C
    bps = C.blueprints()
    assert len(bps) == 1618
    helix = C.search("螺旋 II")[0]
    assert helix["n"] == "Helix II Mining Laser"
    mats = {o[1] for s in helix["slots"] for o in s[1]}
    assert {"Iron", "Copper", "Sadaryx"} <= mats
    # 能量格的品质分段：<400 −1，400–899 0，≥900 +1
    defiant = C.search("Defiant")[0]
    segs = C.group_mods(defiant["slots"][1][2])["Power Pips"]
    assert [C.curve_value(segs, q) for q in (100, 500, 950)] == [-1, 0, 1]
    hints = C.quality_hints([("Laranite", 6.55, 510)])
    assert "≥700/≥900" in hints[0]
    # 所有蓝图里的矿名都在矿物表里（物品类材料除外）
    for bp in bps:
        for s in bp["slots"]:
            for kind, name, *_ in s[1]:
                if kind == "r":
                    assert name in data.SIGNATURES, name


def test_menu_has_all_features():
    from sc_mining.run import MENU
    titles = " ".join(t for _, t, _ in MENU)
    for word in ("实时读屏", "找矿点", "制造", "更新数据", "导航", "交易"):
        assert word in titles


def _nav_data():
    from sc_mining.navigation import navigate as n
    oc = [{"System": "Stanton", "ObjectContainer": "Daymar", "Type": "Planet", "XCoord": "-18930539540",
           "YCoord": "-2610158765", "ZCoord": "0", "RotationSpeedX": "2.48000002",
           "RotationAdjustmentX": "117.48224842", "BodyRadius": "295000", "OrbitalMarkerRadius": "432850",
           "GRIDRadius": "590000"}]
    pois = [dict(Planet="Daymar", PoiName=a, Type=t, XCoord=x, YCoord=y, ZCoord=z, QTMarker=q)
            for a, t, x, y, z, q in [
                ("Sand Cave #003", "Cave", -135.06, -105.57, 240.68, 0),
                ("Brio's Breaker Yard", "Scrapyard", -176.97, -160.95, 173.85, 1),
                ("Security Post Thaquray", "Underground Facility", -6.98, -89.66, 281.36, 0)]]
    return n, n.compact(oc, pois)


def test_nav_matches_starmap():
    from datetime import datetime, timezone
    n, d = _nav_data()
    cave, brio = d["pois"][0], d["pois"][1]
    lat, lon, _ = n.latlon(n.pos(cave))
    assert abs(lat - 54.5393) < 0.01 and abs(lon - 38.0128) < 0.01        # starmap 的经纬度字段
    # starmap 提示："Brio's Breaker Yard @ 96km for 352°"
    assert round(n.bearing(n.pos(brio), n.pos(cave))) == 352
    assert 95 < n.surface_km(n.pos(brio), n.pos(cave), 295) < 98
    # 和 starmap 网页 JS 同输入同时刻的输出一致
    b = d["bodies"]["Daymar"]
    w = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    x, y, z = n.to_local(b, (-18930539540 + 200000, -2610158765 - 100000, 150000), w)
    assert abs(x - 211.92354) < 1e-3 and abs(y - 71.33312) < 1e-3 and z == 150
    # 剪贴板 → 定位 → 导航
    g = n.to_global(b, n.pos(brio), w)
    here = n.locate(g, w, d)
    assert here["body"] == "Daymar" and here["inside"]
    assert "352°" in n.nav_text(here, cave, d)
    assert n.poi_zh("Security Post Thaquray") == "塔库赖安保站"


def test_waypoints_and_latlon(tmp=None):
    import tempfile
    from pathlib import Path
    n, d = _nav_data()
    loc = n.from_latlon(54.5397, 38.0131, 295, 488)
    lat, lon, r = n.latlon(loc)
    assert abs(lat - 54.5397) < 1e-6 and abs(lon - 38.0131) < 1e-6 and abs(r - 295.488) < 1e-6
    assert n.direct_km(loc, n.pos(d["pois"][0])) < 0.1        # 就是 Sand Cave #003
    old = n.WAYPOINTS
    n.WAYPOINTS = Path(tempfile.mkdtemp()) / "waypoints.json"
    try:
        n.add_waypoint("集合点", "Daymar", loc)
        hits, _ = n.search("集合点", d)
        assert hits and hits[0]["t"] == "Waypoint" and n.label(hits[0]) == "集合点"
        assert n.delete_waypoint("集合点") and not n.waypoints()
    finally:
        n.WAYPOINTS = old
    assert n._find_body("戴玛尔", d) == "Daymar" and n._find_body("daymar", d) == "Daymar"


def test_overlay_is_optional():
    from sc_mining.app import overlay
    h = overlay.Hud()
    h.set("扫描", "金｜8,000 kg\nHelix II｜功率 60%")      # 没有屏幕/tkinter 时不报错
    h.clear("扫描")
    h.sleep(0.01)


def test_overlay_paint_rules():
    """1.6.61 悬浮窗自己画（DESIGN.md 第 8 节）：底板半透明、字不透明；两列的行数字靠右；表情去掉；
    读数变了直接换（1.6.63）、只有新分区淡入；2K 屏正文 24px；临时提示单独一条、顶掉旧的"""
    from sc_mining.app import overlay as O
    secs = {"盘点": "盘点｜新巴贝奇\n铁 Q800 ×3  2.900 SCU\n塔兰导电石 Q925 ×1  0.495 SCU", "路标": "📍 已记下：矿点"}
    s = 1440 / 1080
    blocks = O.layout(secs, s)
    count = next(b for b in blocks if b["key"] == "盘点")
    assert count["lines"][1] == ("b", "铁 Q800 ×3", "2.900 SCU") and count["label"] == "COUNT · 盘点"
    assert next(b for b in blocks if b["key"] == "路标")["lines"][0][1] == "已记下：矿点"
    assert round(O.BODY_PX * s) == 24
    img, busy = O.paint(secs, note="盘点结束｜数量一致", scale=s)
    assert not busy and img.mode == "RGBA" and img.width == round(O.BASE_W * s) + 2 * O.MARGIN
    alphas = img.getchannel("A")
    assert min(alphas.getdata()) == 0 and max(alphas.getdata()) == 255          # 底板外透明、字和提示不透明
    plate = img.getpixel((img.width // 2, img.height - O.MARGIN - 3))
    assert 150 < plate[3] < 200                                                  # 底板 72%
    new = dict(secs, 盘点="盘点｜新巴贝奇\n铁 Q800 ×4  3.200 SCU\n塔兰导电石 Q925 ×1  0.495 SCU")
    assert O.diff_fresh(blocks, O.layout(new, s), 100.0, {}) == {}
    more = dict(new, 扫描="金｜8,000 kg\nHelix II｜功率 60%")
    fresh = O.diff_fresh(blocks, O.layout(more, s), 100.0, {})
    assert {k for k, _ in fresh} == {"扫描"}
    _, busy = O.paint(more, scale=s, fresh=fresh, now=100.05)
    assert busy
    h = O.Hud()
    h.note("一"); h.note("二")  # noqa: E702
    assert h.note_text == "二"
    # 1.6.64：采矿助手按层次排（矿名 → 关键读数 → 怎么碎 → 收益 → 次要），数字和单位不拆开
    assert all("SCU" not in ln or "18.35 SCU" in ln for ln in O.wrap("精炼后 18.35 SCU，值 412,000 aUEC（建议：德尼克斯熔解法）", 24, 150))
    assert "412,000 aUEC（建议：德尼克" in O.wrap("精炼后 18.35 SCU，值 412,000 aUEC（建议：德尼克斯熔解法）", 24, 300)
    rich = {"title": "塔兰导电石", "stats": [["质量", "5,561", "kg"], ["抗性", "12", "%"], ["不稳定性", "3.1", ""]],
            "comp": [{"name": "塔兰导电石", "pct": "55%", "subs": [{"q": "925", "pct": "30%", "hi": True}, {"q": "600", "pct": "25%"}]},
                     {"name": "惰性物质", "pct": "27%", "inert": True, "subs": []}],
            "advice": {"heads": "Helix II ×2", "power": "建议功率 60%"},
            "gain": [["预计精炼产量", "18.35", "SCU"], ["价格", "412,000", "aUEC"]], "minor": ["德尼克斯熔解法 · 微 L5"], "foot": "精炼结果为估算"}
    kinds = [l[0] for l in O.layout({"扫描": "x"}, s, {"扫描": rich})[0]["lines"]]     # 1.6.65：照用户样图的层次  # noqa: E741
    assert kinds == ["t", "s", "d", "h", "c", "q", "q", "c", "d", "h", "a", "d", "G", "m", "f"]
    one = {"title": "铜", "comp": [{"name": "铜", "pct": "18%", "subs": [{"q": "450", "pct": "18%"}]}]}       # 1.6.66：只有一种品质的合成一行
    assert [l[0] for l in O.layout({"扫描": "x"}, s, {"扫描": one})[0]["lines"]] == ["t", "d", "h", "c"]  # noqa: E741
    img, _ = O.paint({"扫描": "x"}, scale=s, rich={"扫描": rich})
    assert img.height > 200
    # 1.6.69：采矿助手和别的分区同时显示时不能报错（开采建议那行曾覆盖底板透明度，悬浮窗整个停掉）
    img, _ = O.paint({"扫描": "x", "导航": "去 ARC-L1｜12.3 km"}, scale=s, rich={"扫描": rich})
    assert 150 < img.getpixel((img.width // 2, img.height - O.MARGIN - 3))[3] < 200


def test_nearby_and_feed():
    from datetime import datetime, timezone
    from sc_mining.system import showloc  # noqa: F401
    n, d = _nav_data()
    b = d["bodies"]["Daymar"]
    w = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    cave = d["pois"][0]
    here = n.locate(n.to_global(b, (cave["x"] + 0.3, cave["y"], cave["z"]), w), w, d)
    km, p = n.nearby(here, d)
    assert p["n"] == "Sand Cave #003" and km < 0.5
    assert "附近" in n.here_text(here, d) and " m）" in n.near_text(here, d)


def test_settings_roundtrip():
    import tempfile
    from pathlib import Path
    from sc_mining.core import settings
    old = settings.FILE
    settings.FILE = Path(tempfile.mkdtemp()) / "settings.json"
    try:
        c = settings.load()                        # 防挂机 2026-10-30、自动跑（控制台第 4 批）删掉；autorun 键由 S5 的测试管
        assert c["admin"] is None and "anti_afk" not in c and "autorun" not in c
        settings.update(admin=True)
        c = settings.load()
        assert c["admin"] is True and "anti_afk" not in c
    finally:
        settings.FILE = old


def test_gamelog_vehicle_channel():
    """读游戏日志判断在不在驾驶位（自动跑按控制台第 4 批删了，日志判断还在用）"""
    from sc_mining.system.gamelog import GameLog
    g = GameLog()
    g.line('<2026-10-20T07:36:58.726Z> [Notice] <SHUDEvent_OnNotification> Added notification "你已加入 频道 \'Aegis Idris-P : NeuromancerTT\'。')
    assert not g.aboard and g.channel.startswith("Aegis Idris")                  # 在伊德里斯里走动：不算在开
    seat = ("<y> [Notice] <Failed to get starmap route data!> [ItemNavigation][CL][27808] | NOT AUTH | "
            "AEGS_Idris_P_891312926245[891312926245]|CSCItemNavigation::GetStarmapRouteSegmentData|No ")
    g.line(seat)
    assert g.aboard and g.vehicle == "AEGS_Idris_P"                              # 坐上驾驶位
    g.line('<z> [Notice] <SHUDEvent_OnNotification> Added notification "你退出了 频道 \'Aegis Idris-P : NeuromancerTT\'。')
    assert not g.aboard                                                          # 坐着退出频道：清掉
    g.line(seat)
    assert g.aboard
    g.line('<z> [CSessionManager::OnClientSpawned] Spawned!')
    assert not g.aboard and g.channel is None                                    # 坐着重生：清掉


def test_real_screenshot_scan():
    """原来菜单里的「截图测试」：用你电脑上截的 MOLE 扫描截图跑一遍完整识别（没装 OCR 就跳过）"""
    import pytest
    from sc_mining.core import paths
    img = paths.SAMPLES / "scan1.png"
    if not img.exists():
        pytest.skip("没有测试截图")
    try:
        from sc_mining.mining.screen import _recognize
        _recognize()
    except Exception:
        pytest.skip("没装 OCR")
    from PIL import Image
    from sc_mining.mining import screen
    scan, bag = screen.analyse(Image.open(img).convert("RGB"))
    assert scan.composition and scan.mass and abs(scan.mass - 43066) / 43066 < 0.02


def test_autorun_seat_from_real_log():
    """你 2026-10-20 的日志：上船只加入一次频道、一直不退；离开驾驶位靠 ClearDriver，坐回去靠导航模块的日志"""
    from sc_mining.system.gamelog import GameLog
    g = GameLog()
    g.line('<2026-10-20T06:39:22.010Z> [Notice] <SHUDEvent_OnNotification> Added notification "你已加入 频道 \'Anvil C8R Pisces Rescue : NeuromancerTT\'。')
    assert not g.aboard                                                       # 只是登船
    g.line("<2026-10-20T06:40:07.596Z> [Notice] <Vehicle Control Flow> CVehicleMovementBase::ClearDriver: Local client node "
           "[721472803216] releasing control token for 'ANVL_C8R_Pisces_892158680463' [892158680463] [Team_CGP4][Vehicle]")
    assert not g.aboard                                                       # 下了驾驶位：可以自动跑
    g.line("<2026-10-20T06:43:18.562Z> [Notice] <Local Route Guard - Server Rerouted> [CL][27808] | NULL ENTITY|"
           "CSCItemNavigation::PostInitialize::<lambda_1>::operator ()|FinalStop=-1 [Team_CGP4][QuantumTravel]")
    assert not g.aboard                                                       # 没有载具名的导航日志不算
    g.line("<2026-10-20T06:42:24.793Z> [Notice] <Failed to get starmap route data!> [ItemNavigation][CL][27808] | NOT AUTH | "
           "ANVL_C8R_Pisces_892158680463[892158680463]|CSCItemNavigation::GetStarmapRouteSegmentData|No ")
    assert g.aboard and g.vehicle == "ANVL_C8R_Pisces"                         # 坐回驾驶位：不触发
    g.line("<2026-10-20T07:00:39.033Z> [Notice] <Vehicle Control Flow> CVehicleMovementBase::ClearDriver: Local client node "
           "[721472803216] releasing control token for 'ANVL_C8R_Pisces_892158680463' [892158680463] [Team_CGP4][Vehicle]")
    assert not g.aboard


def test_autorun_state_after_replaying_real_log():
    from pathlib import Path
    import pytest
    from sc_mining.system.gamelog import GameLog
    log = Path("/mnt/user-data/uploads/LIVE/Game.log")
    if not log.exists():
        pytest.skip("没有日志样本")
    g = GameLog(log)
    g.poll()                                                                  # 真实日志能完整读完、不出错
    assert isinstance(g.aboard, bool)


def test_ship_loadouts(tmp_path, monkeypatch):
    """勘探者 / 魔像 / MOLE 配装：默认值、自定义保存、非法配装被纠正、矿袋容量跟着船走"""
    from sc_mining.core import settings
    from sc_mining.mining import laser
    from sc_mining.mining.data import SHIPS
    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    # 还没选船：没选过（窗口会先问），临时按出厂 MOLE 算
    assert laser.chosen_ship() is None
    assert [h.key for h in laser.loadout()] == ["arbor_mh2"] * 3 and laser.max_active_heads() == 1
    # 作者自己的两人 MOLE
    settings.update(mining_ship="mole", mining_loadouts={"mole": data.AUTHOR_MOLE})
    assert [h.key for h in laser.loadout()] == ["helix_ii", "hofstede_s2", "arbor_mh2"]
    assert laser.max_active_heads() == 2
    # 勘探者：只能装 S1，换成 Helix I + 两个 Rieger-C3
    settings.update(mining_ship="prospector",
                    mining_loadouts={"prospector": {"heads": [["helix_i", ["rieger_c3", "rieger_c3"]]]}})
    lo = laser.loadout()
    assert [h.key for h in lo] == ["helix_i"] and lo[0].max_power() == 3900 * 1.25 * 1.25
    assert laser.max_active_heads() == 1
    plans = laser.recommend(5000, 20, 10)
    assert plans and all(len(p.heads) == 1 for p in plans)
    # 勘探者装 S2 矿头 → 纠正回默认的 Arbor MH1
    assert laser.clean_loadout("prospector", {"heads": [["helix_ii", []]]})["heads"][0][0] == "arbor_mh1"
    # 魔像：矿头锁死 Pitman，模组最多 2 个
    lo = laser.clean_loadout("golem", {"heads": [["helix_i", ["rieger_c3"] * 3]], "crew": 3})
    assert lo == {"heads": [["pitman", ["rieger_c3", "rieger_c3"]]], "crew": 1}
    assert SHIPS["prospector"]["bag"] == 32 and SHIPS["mole"]["bag"] == 96


def test_module_resistance_counts():
    """带抗性修正的模组（Overrun -24.8%）要算进有效抗性"""
    from sc_mining.mining.laser import HeadSetup, evaluate
    plain = evaluate([HeadSetup("helix_i", [])], None, 5000, 40, 10)
    over = evaluate([HeadSetup("helix_i", ["overrun"])], None, 5000, 40, 10)
    assert over.eff_resistance[0] < plain.eff_resistance[0]


def test_signal_markers_both_hud_styles():
    """雷达信号：MOLE 炮塔是橙色图钉 + 淡绿字，勘探者驾驶舱是黄色图钉 + 白字，Perseus 是白色图钉 + 更小的白字，都要认出来（2026-10-23 实测）"""
    import pytest
    from sc_mining.core import paths
    from sc_mining.mining import signals
    shots = {"sig1.png": 4285, "sig_prospector.png": 7080, "sig_perseus.png": 39000}
    if not all((paths.SAMPLES / f).exists() for f in shots):
        pytest.skip("没有测试截图")
    try:
        from sc_mining.mining.screen import _recognize
        _recognize()
    except Exception:
        pytest.skip("没装 OCR")
    from PIL import Image
    for f, value in shots.items():
        found = signals.find_signatures(Image.open(paths.SAMPLES / f).convert("RGB"))
        assert value in [v for v, *_ in found], (f, found)
    # 右上角调试信息里的数字不算候选（省时间，也不会误认）
    img = Image.open(paths.SAMPLES / "sig_prospector.png").convert("RGB")
    assert not [b for b in signals.candidates(img) if b[0] > img.width * 0.66 and b[3] < img.height * 0.22]


def test_scan_panel_prospector_white_text():
    """勘探者驾驶舱的扫描面板是白字，左边紧挨着速度表的 "0.0 / 28.2"；货舱的斜杠常认不出（2026-10-23 实测）"""
    import pytest
    from sc_mining.core import paths
    if not (paths.SAMPLES / "scan_prospector.jpg").exists():
        pytest.skip("没有测试截图")
    try:
        from sc_mining.mining.screen import _recognize
        _recognize()
    except Exception:
        pytest.skip("没装 OCR")
    from PIL import Image
    from sc_mining.mining import screen
    from sc_mining.mining.parse import parse_scan, parse_bag
    scan_lines, bag_lines = screen.find_panels(Image.open(paths.SAMPLES / "scan_prospector.jpg").convert("RGB"))
    s = parse_scan(scan_lines)
    assert (s.mass, s.resistance, s.instability, s.total_scu) == (7076, 0, 6.36, 9.42), s
    assert [p for _, p, _ in s.composition] == [8.37, 7.73, 40.71, 43.16] and s.valid, s
    assert parse_bag(bag_lines, 32)[1:] == (6.49, 60.0)


def test_signal_values_outside_table_give_best_guess():
    """信号表外的值不丢掉，给最可能的解释（用户 2026-10-23：不合法就返回可能性最大的）"""
    from sc_mining.mining.signals import resolve, describe, describe_all
    assert resolve("21,500") == (21500, False) and "冰 ×5" in describe_all([(21500, False, "21,500", None)])[0]
    assert resolve("57,000") == (57000, False)          # 正好是手采矿 3000 × 19，不要硬改成别的飞船矿
    assert "可打捞残骸 ×19" not in describe(57000) and "车矿或手采 ×19" not in describe(57000)   # 手采/车矿、残骸一处最多按 15 块算
    # 按玩家在哪分开：地面的 3,000 倍数是手采矿，太空里是残骸；4,000 倍数在地面是车矿
    assert describe(6000, "space") == "6000：可打捞残骸 ×2" and describe(57000, "space") == "57000：未知"
    # 地面上比一簇还大的整千（2026-10-23 Calliope 实测 80,000、54,000）：几处地面小矿叠在一起，只估个数范围
    assert "约 15~19 处" in describe(57000, "ground") and "残骸" not in describe(57000, "ground")
    assert "约 20~26 处" in describe(80000, "ground") and "约 14~18 处" in describe(54000, "ground")
    assert describe(80000, "space") == "80000：未知"
    assert "车矿或手采 ×15（哈丹水晶 / 紫钠水晶 / 暗橄榄石）" in describe(45000, "ground")
    assert "冰碛棉" in describe(12000, "ground") and "冰碛棉" not in describe(12000, "space")
    assert "托瑞特金属" in describe_all([(39000, False, "39,000", None)], "space")[0]   # 飞船矿排最前
    assert describe(122000, "ground") == "122000：未知"
    assert describe_all([(122000, False, "122,000", None)], "ground") == ["信号 122,000 → 未知"]
    # 和 scminer.rocks 一致：12200 → 火神石 ×3（12,540），可信度 97.3%，排第一
    first = describe_all([(12200, False, "12,200", None)], "space")[0]
    assert "火神石 ×3" in first and "97.3%" in first
    assert resolve("9,570") == (9510, True)             # 形近一位修正仍然优先于「最接近」
    assert resolve("3,360") == (3370, True) and resolve("0,000") == (None, False)
    assert "最接近" in describe(12345)


def test_copper_tin_names_not_gold():
    """勘探者面板上的小字「铜矿石」「锡矿石」常认成 钥/網/确 和 锯/继，不能落到「金」"""
    from sc_mining.core.i18n import mineral_en
    for t in ("钥矿石", "網矿石", "确矿石", "销矿石", "铜矿石"):
        assert mineral_en(t) == "Copper", t
    for t in ("锯矿石", "继矿石", "锡矿石"):
        assert mineral_en(t) == "Tin", t
    assert mineral_en("金矿石") == "Gold" and mineral_en("矿石") is None


def test_scan_panel_prospector_png():
    """勘探者驾驶舱 2560×1440 原图：石头标题、成分矿名都要对（2026-10-23 实测）"""
    import pytest
    from sc_mining.core import paths
    if not (paths.SAMPLES / "scan_prospector2.png").exists():
        pytest.skip("没有测试截图")
    try:
        from sc_mining.mining.screen import _recognize
        _recognize()
    except Exception:
        pytest.skip("没装 OCR")
    from PIL import Image
    from sc_mining.mining import screen
    s, bag = screen.analyse(Image.open(paths.SAMPLES / "scan_prospector2.png").convert("RGB"))
    assert s.rock == "Copper" and (s.mass, s.resistance, s.instability, s.total_scu) == (7076, 0, 6.36, 9.42), s
    assert [n for n, _, _ in s.composition] == ["Tin", "Copper", "Copper", "Inert Materials"], s
    assert s.valid


def test_snow_ground_panels_and_signals():
    """2026-10-23 Wala 雪地实测：亮白背景上的白字扫描面板要认出来（以前整片雪地都算成字，面板认不出、
    采矿助手只出过一次结果）；地面的信号图钉照常认"""
    import pytest
    from pathlib import Path
    from sc_mining.mining import screen, signals
    d = Path(__file__).parent / "ingame"
    if not (d / "g1523_09.png").exists():
        pytest.skip("没有雪地截图")
    try:
        screen._recognize()
    except Exception:
        pytest.skip("没装 OCR")
    from PIL import Image
    for f, mass in (("g1523_08.png", 7714), ("g1523_09.png", None)):
        scan, _ = screen.analyse(Image.open(d / f).convert("RGB"))
        assert scan.rock == "Laranite" and scan.valid, (f, scan)
        assert scan.total_scu and len(scan.composition) == 4
        if mass:
            assert scan.mass == mass
    for f, v in (("g1523_05.png", 7080), ("g1523_07.png", 33000), ("g1523_03.png", 45000), ("g1523_01.png", 25440)):
        assert v in [x[0] for x in signals.find_signatures(Image.open(d / f).convert("RGB"))], f


def test_fog_signal_boxes_found():
    """2026-10-23 Calliope 浓雾：雾是 (210,222,232) 的亮灰，信号框（淡黄底、图钉、白字 80,000 / 54,000）以前整片被当成字，
    一个信号都认不出。现在只要比周围亮一截的字，框线、条纹不算（不用 OCR 也能测）"""
    import pytest
    from pathlib import Path
    from PIL import Image
    from sc_mining.mining import signals
    d = Path(__file__).parent / "ingame"
    if not (d / "calliope_fog_80000.png").exists():
        pytest.skip("没有浓雾截图")
    for f, digits in (("calliope_fog_80000.png", (1277, 535, 1310, 546)), ("calliope_fog_54000.png", (1277, 527, 1307, 539))):
        boxes = signals.candidates(Image.open(d / f).convert("RGB"))
        cx, cy = (digits[0] + digits[2]) / 2, (digits[1] + digits[3]) / 2
        hit = [b for b in boxes if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]]
        assert hit, (f, boxes)
        x0, y0, x1, y1 = hit[0]
        assert x0 >= digits[0] - 8 and x1 <= digits[2] + 10, (f, hit)        # 框里只有数字，不带图钉和边框


def test_fog_signals_read():
    import pytest
    from pathlib import Path
    from PIL import Image
    from sc_mining.mining import screen, signals
    d = Path(__file__).parent / "ingame"
    if not (d / "calliope_fog_80000.png").exists():
        pytest.skip("没有浓雾截图")
    try:
        screen._recognize()
    except Exception:
        pytest.skip("没装 OCR")
    for f, v in (("calliope_fog_80000.png", 80000), ("calliope_fog_54000.png", 54000)):
        assert v in [x[0] for x in signals.find_signatures(Image.open(d / f).convert("RGB"))], f


def test_cockpit_hud_numbers_are_not_a_scan_panel():
    """勘探者驾驶舱右边的高度表、气压被拼成「质量 0.7、抗性 76」：不算面板（以前因此信号识别整段暂停）；
    真面板哪怕只读到下半截（组成 + 成分行）也算"""
    from sc_mining.mining.parse import parse_scan
    from sc_mining.mining.screen import panel_seen
    junk = ["？", "0.40", "0.7未知 中 十 ? 一。 0 .3 7.7 G", "#", "0.34", "地表雷达商度76m", "外部大气压力0.646MPa", "加力"]
    s = parse_scan(junk)
    assert s.mass is not None and not panel_seen(s, junk)          # 解析出了「质量」，但不是面板
    half = ["组成 39.72SCU", "2.38% 原础 510", "4.19% 火神石原矿 572", "44.96% 火神石腺矿 330", "43.78% 销性物质 。"]
    assert panel_seen(parse_scan(half), half)
    top = ["扫描结果", "质量： 12431"]
    assert panel_seen(parse_scan(top), top)
    # 屏幕上别的窗口里的字（2026-10-23 自动留图：Claude 窗口里「快速稳定性测试…扫描面板…」）：只有字没有数字，不算
    chat = ["快速稳定性测试跑完了， ， 没发现问题： 用时 4分钟， 0 报", "。 挑了 36 张有代表性的截图： 以前认出过信号、 扫描",
            "面板、 物品、 坐标的各挑一些, 加几张什么都没有"]
    assert not panel_seen(parse_scan(chat), chat)


def test_deflood_keeps_text_on_bright_background():
    """亮背景（雾 / 雪）上的白字：整片背景都会被当成「白色」，deflood 之后只剩字；暗背景上的字不受影响"""
    import numpy as np
    from sc_mining.mining.screen import deflood
    a = np.full((120, 200), 212, np.uint8)            # 雾
    a[50:62, 40:42] = a[50:62, 60:62] = 248           # 两笔竖画（字）
    a[56, 40:62] = 248
    mask = a > 200
    out = deflood(mask, a, 31, 12)
    assert out[55, 41] and out[56, 50] and not out[10, 10] and out.sum() == ((a > 240).sum())
    dark = np.full((120, 200), 40, np.uint8)
    dark[50:62, 40:42] = 248
    assert (deflood(dark > 200, dark, 31, 12) == (dark > 200)).all()


def test_fog_half_panel_read():
    """扫描面板上半截在雾里、下半截在地上（整块搜索区里雾不到三成）：以前雾整片当成字，质量/抗性那几行全丢，采矿助手失败。
    用 Calliope 实拍的面板，把上半截背景换成实测的雾色来测"""
    import pytest
    import sys
    from pathlib import Path
    from PIL import Image
    from sc_mining.mining import screen
    d = Path(__file__).parent / "ingame"
    if not (d / "calliope_161036.png").exists():
        pytest.skip("没有 Calliope 采矿助手截图")
    try:
        screen._recognize()
    except Exception:
        pytest.skip("没装 OCR")
    sys.path.insert(0, str(Path(__file__).parent))
    from fogsim import fog_panel
    img = Image.open(d / "calliope_161036.png").convert("RGB")
    for im in (img, fog_panel(img, (1560, 560, 2100, 775))):
        scan, _ = screen.analyse(im)
        assert (scan.mass, scan.resistance, scan.instability, scan.total_scu) == (12431, 0, 221.75, 39.72), scan
        assert scan.rock == "Hephaestanite" and scan.valid and len(scan.composition) == 5, scan


def test_parse_low_contrast_panel_lines():
    """雪地上 OCR 常见的错：「组成 7,835CU」（S 认成 5、小数点成逗号）、砬→位/脑/敬、钨→韩；
    几个矿名一样像时按石头本身的矿算"""
    from sc_mining.mining.parse import parse_scan
    s = parse_scan(["扫描结  一", "兰石原", "质量： 7714", "抗性： 37%", "不稳定性： 22.17", "组成 7,835CU",
                    "8.25% 敬兰石取矿 698", "30.79 脑兰石原矿 298", "9.80% 韩石 530", "51.14%% 情性物间 0"])
    assert s.rock == "Laranite" and s.total_scu == 7.83 and s.valid
    assert [n for n, *_ in s.composition] == ["Laranite", "Laranite", "Tungsten", "Inert Materials"]
    s = parse_scan(["砂兰石原旷", "质量： 8764", "抗性： 47%", "不膀定性： 30.05", "组成 6.32SCU",
                    "5.74% 位就石原矿 858", "59.74% 拉兰石眼矿 298", "24.58% 情性物局 。"])
    assert s.composition[0][0] == "Laranite"


def test_parse_total_scu_and_unlabeled_mass():
    """总 SCU 的小数点被切块拆开（「组成 (7. .84 SCU)」）要拼回 7.84，以前读成 84、精炼量多算 10 倍；
    小数点整个丢了（「84 SCU」）不采信。质量标签没认出时，「13,586」「13,596」都不能当成一行成分
    （2026-10-24 外部补丁；13,596 那种带 96 的是 1.6.43 补上的）"""
    from sc_mining.mining.parse import parse_scan
    head = ["钨矿石", "质量: 13,586", "抗性: 23%", "不稳定性: 12.45"]
    tail = ["45.20% 钨矿石 662", "54.80% 惰性物质 0"]
    s = parse_scan(head + ["组成 (7. .84 SCU)"] + tail)
    assert s.total_scu == 7.84 and s.valid
    s = parse_scan(head + ["组成 (84 SCU)"] + tail)
    assert s.total_scu is None and not s.valid
    assert parse_scan(head + ["组成 7,835CU"] + tail).total_scu == 7.83
    for mass in ("13,586", "13,596"):
        s = parse_scan(["钨矿石", mass, "抗性: 69%", "不稳定性: 12.45", "组成 (7.84 SCU)"] + tail)
        assert s.mass == float(mass.replace(",", "")) and s.valid and len(s.composition) == 2, (mass, s)
    # 总 SCU 读不到（面板被挡住）时，百分号认成 96 的成分行照样认
    s = parse_scan(head + ["组成", "45.2096 钨矿石 662", "54.8096 惰性物质 0"])
    assert [(n, p) for n, p, _ in s.composition] == [("Tungsten", 45.2), ("Inert Materials", 54.8)]


def test_parse_stray_numbers_in_composition_ignored():
    """「组成」那行之后读不懂的行照旧跳过：成分区多出来的单独数字（品质「662」、行尾的「1」，玩家日志里见过）
    不能拿去补不稳定性、把读不全的帧变成「有效」，也不能把质量改掉（1.6.43）"""
    from sc_mining.mining.parse import parse_scan
    s = parse_scan(["钨矿石", "质量: 13,586", "抗性: 23%", "组成 (7.84 SCU)", "45.20% 钨矿石", "662", "54.80% 惰性物质 0"])
    assert s.instability is None and not s.valid
    s = parse_scan(["钨矿石", "质量: 13,586", "抗性: 23%", "不稳定性:", "组成 (7.84 SCU)",
                    "45.20% 钨矿石 662", "54.80% 惰性物质 0", "1"])
    assert s.instability is None and not s.valid
    s = parse_scan(["钨矿石", "质量: 13,586", "抗性: 23%", "不稳定性: 12.45", "组成 (7.84 SCU)",
                    "45.20% 钨矿石 662", "惰性物质 0"])
    assert s.mass == 13586 and not s.valid


def test_crafted_head_quality(tmp_path, monkeypatch):
    """自造矿头（1.6.41）：发射器（萨达瑞晶）+ 汇流排（铜）的品质决定激光功率，破碎方案按自造的功率算。
    两个槽的加成相加（1.6.47 起；数据里没有合并规则，游戏制造终端、SCM、Crafter 三处都是相加：947 + 958 → +36.20%）"""
    from sc_mining.core import settings
    from sc_mining.mining import laser, quality
    from sc_mining.tasks import mining as t_mining
    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    # 档位按各自材料：萨达瑞晶、铜各有 7 档 + 1000 完美（starcitizen.tools 品质表）
    assert [q for _, q in quality.tiers("Sadaryx")] == [258, 510, 688, 797, 865, 940, 971, 1000]
    assert [q for _, q in quality.tiers("Copper")] == [359, 593, 652, 742, 855, 917, 958, 1000]
    assert quality.tier_of("Tungsten", 662) == ("D", 3, 7) and quality.tier_of("Tungsten", 600) is None
    assert quality.tier_of("Laranite (Ore)", 858) == ("B", 5, 7) and quality.tiers("没有这种矿") == []
    assert {s["slot"]: s["mat"] for s in laser.craft_slots("helix_ii")} == {"Emitter": "Sadaryx", "Bus Bars": "Copper"}
    assert all(laser.head_blueprint(k) for k in laser.HEADS)          # 船用矿头都有蓝图（包括魔像的 Pitman）
    shop = laser.HeadSetup("helix_ii", [])
    std = laser.HeadSetup("helix_ii", [], {"Emitter": 500, "Bus Bars": 500})
    top = laser.HeadSetup("helix_ii", [], {"Emitter": 971, "Bus Bars": 958})
    e = laser.HeadSetup("helix_ii", [], {"Emitter": 510, "Bus Bars": 593})
    assert shop.max_power() == std.max_power() == 4930                # 品质 500 = 和商店买的一样
    assert abs(top.max_power() - 4930 * (1 + 0.1884 + 0.1832)) < 0.01
    assert abs(top.min_power() / top.max_power() - shop.min_power() / shop.max_power()) < 1e-9
    assert abs(e.power_mult() - 1.0412) < 1e-4                       # 510 → +0.40%，593 → +3.72%，相加 +4.12%
    assert abs(laser.HeadSetup("helix_ii", [], {"Emitter": 947, "Bus Bars": 958}).power_mult() - 1.3620) < 1e-4   # SCM / Crafter 的例子
    assert top.label == "螺旋 Helix II（自造 +37%）" and shop.label == "螺旋 Helix II"
    # 配装：自造的品质存下来，超范围的纠正，没填的按 500；没有自造矿头的配装不多出这一项（老配装照旧）
    lo = laser.clean_loadout("prospector", {"heads": [["helix_i", []]], "craft": [{"Emitter": "971", "Bus Bars": 5000}]})
    assert lo["craft"] == [{"Emitter": 971, "Bus Bars": 1000}]
    assert "craft" not in laser.clean_loadout("prospector", {"heads": [["helix_i", []]], "craft": [None]})
    assert laser.clean_loadout("prospector", {"heads": [["helix_i", []]], "craft": [{}]})["craft"] == [{"Emitter": 500, "Bus Bars": 500}]
    # 自造的功率更高 → 满功率能破更重的；方案、悬浮窗里标出「自造 +X%」
    t_mining.set_mining_gear("prospector", {"heads": [["helix_i", []]], "crew": 1})
    plain = laser.evaluate(laser.loadout(), None, 9000, 30, 10)
    g = t_mining.set_mining_gear("prospector", {"heads": [["helix_i", []]], "crew": 1, "craft": [{"Emitter": 971, "Bus Bars": 958}]})
    made = laser.evaluate(laser.loadout(), None, 9000, 30, 10)
    assert abs(made.max_mass / plain.max_mass - (1 + 0.1884 + 0.1832)) < 1e-6
    assert "自造 +37%" in laser.recommend(9000, 30, 10)[0].short()
    assert "自造 +37%" in t_mining.manual_scan(9000, 30, 10)[0]["heads"]
    for bad in ((0, 30, 10), ("", 30, 10), (9000, 130, 10), (9000, 30, -1)):   # 空的 / 0 质量以前返回 Infinity，前端只报「连不上」
        with pytest.raises(ValueError):
            t_mining.manual_scan(*bad)
    ship = next(s for s in g["ships"] if s["key"] == "prospector")
    assert ship["power"][0] == {"base": 3900, "now": round(3900 * 1.3716), "pct": 37.2, "craft": True}
    assert not ship["is_default"] and ship["loadout"]["craft"] == [{"Emitter": 971, "Bus Bars": 958}]
    head = next(h for h in g["heads"] if h["key"] == "helix_i")
    assert [x["slot"] for x in head["craft"]] == ["Emitter", "Bus Bars"] and head["craft"][0]["tiers"][0] == ["商店标准", 500]
    assert head["craft"][1]["tiers"][-1] == ["完美", 1000] and head["craft"][1]["mat_zh"] == "铜"
    # 换回商店买的：功率回到原样
    t_mining.set_mining_gear("prospector", {"heads": [["helix_i", []]], "crew": 1, "craft": [None]})
    assert laser.loadout()[0].max_power() == 3900


def test_laser_power_naming_on_craft_page():
    """制造页：采矿激光的「冲击力」其实是激光功率，另外给出发射器 + 汇流排的合计（相加，1.6.47）"""
    from sc_mining.crafting import crafting as C
    bp = next(b for b in C.blueprints() if b["n"] == "Helix II Mining Laser")
    text = C.describe(bp, with_locations=False)
    assert "冲击力" not in text and "激光功率 ×0.80→×1.20" in text and "激光功率合计" in text and "×1.40" in text and "相加" in text
    eff = C.effect(bp, {1: 971, 2: 958})
    assert [p["name"] for x in eff for p in x["props"]] == ["激光功率", "激光功率"] and eff[0]["material"] == "萨达瑞晶"
    assert C.laser_total(bp, {1: 971, 2: 958})["text"].startswith("激光功率合计 +37.2%")
    assert C.laser_total(bp, {1: 971})["mult"] is None
    from sc_mining.tasks import goals as t_goals                               # 目标页「品质影响」：点「计算」也带合计
    r = t_goals.craft_effect("Helix II Mining Laser", {"1": "971", "2": "958"})
    assert r["total"]["text"].startswith("激光功率合计 +37.2%") and len(r["slots"]) == 2
    # 武器的冲击力照旧叫冲击力，也没有合计
    gun = next(b for b in C.blueprints() if b["t"] == "weapons" and any(m[0] == "Impact Force" for _, _, mods in b["slots"] for m in mods))
    assert "冲击力" in C.describe(gun, with_locations=False) and C.laser_total(gun) is None


def test_panel_cut_and_chroma_shift():
    """读不全的原因（1.6.42）：面板顶着屏幕右边（16:10 屏幕）、字有色差重影（1080p 开着「色差」）"""
    import numpy as np
    from PIL import Image
    from sc_mining.mining import screen
    img = Image.new("RGB", (2560, 1600))
    ox, oy = int(screen.SEARCH[0] * 2560), int(screen.SEARCH[1] * 1600)  # noqa: F841
    it = lambda x0, x1: ("质量： 745", ((x0 + x1) / 2, 10), 14, (x0 - ox, 100, x1 - ox, 114))  # noqa: E731
    screen._note_panel(img, [it(2200, 2300), it(2480, 2558)])
    assert screen.LAST_PANEL["cut"] and screen.LAST_PANEL["box"][2] == 2558
    screen._note_panel(img, [it(1600, 1700), it(1750, 1820)])
    assert not screen.LAST_PANEL["cut"]
    # 色差：红、蓝各错开 1 像素
    rng = np.random.default_rng(1)
    g = (rng.random((120, 160)) > 0.7).astype(np.uint8) * 220
    g = np.kron(g, np.ones((1, 1), np.uint8))
    aligned = Image.fromarray(np.stack([g, g, g], axis=2))
    shifted = Image.fromarray(np.stack([np.roll(g, 1, axis=1), g, np.roll(g, -1, axis=0)], axis=2))
    assert screen.chroma_shift(aligned, (0, 0, 160, 120)) == 0
    assert screen.chroma_shift(shifted, (0, 0, 160, 120)) == 1
    screen.LAST_PANEL.clear()
    screen.LAST_PANEL.update(box=(0, 0, 160, 120), cut=False, h=8)
    assert screen.miss_reason(shifted) == "ca" and screen.miss_reason(aligned) is None
    screen.LAST_PANEL.clear()
    assert screen.miss_reason(shifted) is None


def test_vote_partial_needs_two_frames():
    from sc_mining.mining import screen
    from sc_mining.mining.parse import Scan
    a = Scan(mass=745, resistance=20, instability=8.2, composition=[("Ouratite", 2.79, None), ("Inert Materials", 97.21, None)])
    b = Scan(mass=745, resistance=20, instability=8.2, composition=[("Ouratite", 2.79, None), ("Inert Materials", 97.21, None)])
    z = Scan(mass=0.0, resistance=0, instability=0.0)
    best, ok = screen.vote_partial([a, b])
    assert ok and best.mass == 745 and len(best.composition) == 2
    assert not screen.vote_partial([a])[1]
    assert not screen.vote_partial([z, z])[1]                                 # 还没扫的石头（0.00）不算


def test_craft_stats_and_detail_structure(monkeypatch, tmp_path):
    """制造页改版（1.6.47）：属性统计（基础 → 强化 → 变化，几个槽影响同一属性时相加）、标题标签（尺寸 / 等级 / 类别）、
    结构化的材料槽位、去哪挖、蓝图来源带掉率。成品基础值来自 data/item_stats.json（star-citizen.wiki 解包数据，按 uuid 对上）"""
    import json
    from sc_mining.crafting import crafting as C, itemstats
    from sc_mining.core import paths
    from sc_mining.tasks import goals as t_goals
    bp = next(b for b in C.blueprints() if b["n"] == "Helix II Mining Laser")
    st = C.stats(bp, {1: 947, 2: 958})
    lp = next(p for p in st["props"] if p["name"] == "激光功率")
    assert abs(lp["delta"] - 0.362) < 1e-6 and lp["text"] == "+36.20%" and [s["slot"] for s in lp["slots"]] == ["发射器", "汇流排"]
    assert st["missing"] == ["框架"] and next(p for p in st["props"] if p["name"] == "结构强度")["delta"] == 0
    assert abs(lp["best"] - 0.4) < 1e-9 and abs(lp["worst"] + 0.4) < 1e-9
    # 有成品基础值时：强化属性 = 基础 × (1 + 相加的百分比)；能量格这种加法属性直接加
    fake = {"version": "4.10.2-test", "items": {bp["u"]: {"n": bp["n"], "size": 2, "grade": "A", "cls": None, "type": "WeaponMining",
            "s": {"durability": {"health": 8000}, "mining_laser": {"laser_power": {"min": 1232.5, "max": 4930}}}}}}
    f = tmp_path / "item_stats.json"
    f.write_text(json.dumps(fake), encoding="utf-8")
    monkeypatch.setattr(paths, "data", lambda name: f if name == "item_stats.json" else paths.DATA / name)
    itemstats.data.cache_clear()
    try:
        st = C.stats(bp, {0: 501, 1: 947, 2: 958})
        by = {p["name"]: p for p in st["props"]}
        assert by["结构强度"]["base"] == 8000 and abs(by["结构强度"]["now"] - 8003.2) < 0.01     # SCM 截图：8000 → 8003.20
        assert by["激光功率"]["base"] == 4930 and abs(by["激光功率"]["now"] - 4930 * 1.362) < 0.01
        h = C.header(bp)
        assert h["tags"] == ["S2", "A 级"] and h["kind"] == "采矿激光器" and h["stats_version"] == "4.10.2-test"
        d = t_goals.craft_detail("Helix II Mining Laser")
        assert d["head"]["tags"] == ["S2", "A 级"] and [s["slot"] for s in d["slots"]] == ["框架", "发射器", "汇流排"]
        assert d["slots"][1]["mats"][0] == {"kind": "i", "en": "Sadaryx", "zh": "萨达瑞晶", "qty": 13, "unit": "个", "minq": 1}
        assert d["slots"][2]["curves"][0]["name"] == "激光功率" and d["mine"][0]["zh"] == "铁" and d["sources"][0]["chance"] == 1
        r = t_goals.craft_stats("Helix II Mining Laser", {"1": "947", "2": "958"})
        assert r["stats"]["props"][1]["now"] and len(r["slots"]) == 2
        assert C.header(next(b for b in C.blueprints() if b["t"] == "armour"))["tags"][:1] in ([], ["S0"], ["S1"], ["S2"], ["S3"])
    finally:
        itemstats.data.cache_clear()
    # 真数据：Helix II 的成品基础值（star-citizen.wiki 解包）和 SCM 一致；解包里没有的属性（后坐力）只有变化、没有绝对值
    assert C.stats(bp, {1: 1000, 2: 1000})["props"][1]["base"] == 4930
    gun = next(b for b in C.blueprints() if any(m[0] == "Recoil Kick" for _, _, mods in b["slots"] for m in mods))
    assert next(p for p in C.stats(gun, {})["props"] if p["name"] == "后坐力")["now"] is None
    # 加法属性（能量格）：各槽相加
    pw = next(b for b in C.blueprints() if any(m[0] == "Power Pips" for _, _, mods in b["slots"] for m in mods))
    pp = next(p for p in C.stats(pw, {i: 1000 for i in range(len(pw["slots"]))})["props"] if p["name"] == "能量格")
    assert pp["add"] and pp["text"].startswith("+") and pp["delta"] == pp["best"]


def test_gear_labels_bilingual():
    """矿头、模组、手持工具统一「中文 English」（2026-10-26 用户定）：中文取汉化包、去掉型号；汉化包里没有中文的只写英文"""
    from sc_mining.core.i18n import gear_label
    from sc_mining.mining.data import HEADS, MODULES, GADGETS
    assert gear_label("Hofstede-S2") == "霍夫斯泰德 Hofstede-S2"
    assert gear_label("Helix II") == "螺旋 Helix II" and gear_label("Arbor MH2") == "刀轴 Arbor MH2"
    assert gear_label("Rieger-C3") == "里格 Rieger-C3" and gear_label("Sabir") == "萨比尔 Sabir" and gear_label("Pitman") == "石工 Pitman"
    assert gear_label("XTR-L") == "XTR-L"
    for d in (HEADS, MODULES, GADGETS):                  # 每件都有名字，没有「型采矿激光器」「模组」后缀
        for v in d.values():
            lab = gear_label(v["name"])
            assert lab.endswith(v["name"]) and "采矿激光器" not in lab and "模组" not in lab


def test_gear_view_has_cards_and_summary(monkeypatch, tmp_path):
    """配置区：每个矿头装上模组后的读数、汇总（总功率、可破碎质量）、预设；改配置后汇总跟着变"""
    from sc_mining.core import settings
    from sc_mining.tasks import mining as t_mining
    from sc_mining.mining.data import AUTHOR_MOLE
    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    g = t_mining.set_mining_gear(ship="mole")
    mole = next(x for x in g["ships"] if x["key"] == "mole")
    assert mole["is_default"] and len(mole["cards"]) == 3 and {p["key"] for p in mole["presets"]} == {"factory", "author"}
    base = mole["summary"]
    g = t_mining.set_mining_gear(ship="mole", loadout=AUTHOR_MOLE)
    mole = next(x for x in g["ships"] if x["key"] == "mole")
    c0 = mole["cards"][0]
    assert c0["power"] == 7318 and c0["stats"]["power"] == 48 and c0["stats"]["res"] == -30   # Helix II + Rieger-C3 ×2 + Focus III
    assert mole["summary"]["crew"] == 2 and mole["summary"]["power"] > base["power"] and mole["summary"]["mass"] > base["mass"]
    assert mole["summary"]["mass_gadget"] > mole["summary"]["mass"] and mole["summary"]["gadget"] == "萨比尔 Sabir"
    assert all(m["group"] != "其他" for m in g["modules"]) and g["heads"][0]["name"] == "螺旋 Helix II"


def test_mining_area_from_position():
    """2026-10-27 用户反馈：尼克斯太空扫到贝沙电气石。按实时位置判断产矿区（SCMiner 地点矿表）：
    尼克斯两条环带按离恒星的距离判断（基格 48.0 Gm、冰川环带 15.0 Gm）；派罗星团；星球地表；远离这些的太空不刷船挖矿"""
    from sc_mining.mining import mining_area as M
    keeger = M.area((-4634409388.2, -47775658122.7, -42640.1), "Nyx")       # 用户在基格带采矿基地的实测坐标
    assert keeger["name"] == "Keeger Belt" and keeger["minerals"]["Bexalite"] == 18
    assert M.area((15.0e9, 0, 1e6), "Nyx")["name"] == "Glaciem Ring"
    assert M.area((30e9, 0, 0), "Nyx")["minerals"] == {}                    # 尼克斯的空旷太空
    # 派罗「小行星群 FSN-704」用的是深空小行星表（2026-10-27 解物件容器）；阿克罗团单独一张表
    assert M.area((0, 0, 0), "Pyro", location="AsteroidCluster_Pyro_RegionC_FSN-704")["name"] in ("Deep Space Asteroids", "Akiro Cluster")
    assert M.area((1, 2, 3), "Pyro", body="Fairo", ground=True)["name"] == "Pyro V-d (Fairo)"
    assert M.area((1, 2, 3), "Pyro", body="Pyro4", ground=True)["name"] == "Pyro IV"
    assert M.area((1, 2, 3), "Nyx", body="Delamar", ground=True) is None    # 没有矿表的星球：不过滤
    assert M.area((1e9, 2e9, 3e9), "Stanton") is None or M.area((1e9, 2e9, 3e9), "Stanton")["minerals"]


def test_signatures_only_ores_that_spawn_here():
    """只报当地会刷的矿：基格带 7200 是贝沙电气石 ×2（此地 18%）；HUR-L1 不刷贝沙电气石 → 报当地最接近的并说明；
    空旷太空不报船挖矿；不知道在哪就和以前一样"""
    from sc_mining.mining import mining_area as M, signals as S
    keeger = M.area((-4634409388.2, -47775658122.7, -42640.1), "Nyx")
    hl1 = M._result(M._table("HUR-L1"))
    empty = M.area((30e9, 0, 0), "Nyx")
    assert S.guesses(7200)[0][0].startswith("贝沙电气石 ×2")
    assert "此地 18%" in S.guesses(7200, "space", keeger)[0][0]
    t = S.guesses(7200, "space", hl1)[0][0]
    assert "贝沙电气石 ×2，此地不刷" in t and t.startswith("最接近")
    t = S.guesses(7200, "space", empty)[0][0]
    assert t.startswith("此处不刷船挖矿") and "贝沙电气石" in t
    assert S.guesses(6000, "space", empty)[0][0] == "可打捞残骸 ×2"
    lines = S.describe_all([(7200, False, "7200", None)], "space", hl1)
    assert lines and "此地不刷" in lines[0]


def test_radar_uses_unpacked_rock_types():
    """2026-10-27 解包：雷达信号按「石头种类」给。SCMiner 的矿物表把石头里夹带的少量矿也算进去了：
    基格带按 SCMiner 有金 18%，但游戏里基格带根本不刷金石（金只夹在贝沙电气石石头里）→ 金 ×2（7,170）不能报成金"""
    from sc_mining.mining import mining_area as M, signals as S
    if not M.rocks_table():
        pytest.skip("没有 data/mining_rocks.json")
    keeger = M.area((-4634409388.2, -47775658122.7, -42640.1), "Nyx")
    assert set(keeger["rocks"]) == {"Torite", "Ice", "Aluminum", "Bexalite", "Lindinium", "Savrilium"}
    assert "Gold" in keeger["minerals"] and "Gold" not in keeger["rocks"]
    assert "金" not in S.guesses(7170, "space", keeger)[0][0].split("（")[0] or "此地不刷" in S.guesses(7170, "space", keeger)[0][0]
    # 一团几块：稀有矿刚刷出来 2 块最常见，挖掉一块剩 1 块也常见，6 块几乎不可能
    assert S.cluster_weight("Bexalite", 2) > S.cluster_weight("Bexalite", 1) > S.cluster_weight("Bexalite", 6)
    assert S.cluster_weight("Quantainium", 1) > S.cluster_weight("Quantainium", 2)       # 传说矿多半单块
    assert M.rocks_table()["ores"]["Bexalite"]["sig"] == 3600


def test_review_102_area_never_guesses(monkeypatch):
    """Codex 2026-10-27 补审：只靠坐标猜的星系不能拿来排除矿种（亚伦光环会被猜成尼克斯 → 报「不刷」）；
    派罗星图缺地点列表 = 不知道，不是「不刷」"""
    from sc_mining.navigation import navigate as n
    from sc_mining.mining import mining_area as M
    data = n.load()
    if not data.get("points"):
        pytest.skip("没有星图数据")
    import math
    g = (20.3e9 * math.cos(math.radians(30)), 20.3e9 * math.sin(math.radians(30)), 0)
    sysname, sure = n.system_info(g, data)
    assert sure is False
    assert n.system_info(g, data, zone="keeger_segment_x")[1] is True
    pyro = next(p for p in data["points"] if p["sys"] == "Pyro" and p["t"] == "AsteroidBelt")
    assert M.area((pyro["x"], pyro["y"], pyro["z"]), "Pyro")["name"] in ("Deep Space Asteroids", "Akiro Cluster")
    monkeypatch.setattr(n, "load", lambda: {**data, "points": []})
    monkeypatch.setattr(M, "_spots_raw", lambda: [])
    assert M.area((pyro["x"], pyro["y"], pyro["z"]), "Pyro") is None


def test_review_102_place_names_without_ini(monkeypatch, tmp_path):
    """新装还没下汉化包：派罗地名用随包的地点代号表，不显示 PYR3"""
    import json
    from sc_mining.navigation import position as P
    from sc_mining.update import localization as L
    (tmp_path / "place_codes_zh.json").write_text(json.dumps({"rr_p3": "轨道讣闻站 (Orbituary)"}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(L, "DATA", tmp_path)
    monkeypatch.setattr(L, "read_ini", lambda *a: (_ for _ in ()).throw(FileNotFoundError()))
    P.reset_names()
    try:
        assert P.ini_name("RR_P3") == "轨道讣闻站"
    finally:
        P.reset_names()                 # 测完清掉缓存，下次按真的汉化包重新读


def test_review_104_rocks_reload_and_order(monkeypatch, tmp_path):
    """Codex 二审：①更新数据换了石头表不用重启就生效；②同一个信号的几种可能保持「当地概率 × 一团几块」的顺序，不被矿价打乱"""
    import json
    from sc_mining.mining import mining_area as M, signals as S
    from sc_mining.core import paths
    monkeypatch.setattr(paths, "DATA", tmp_path)
    M._ROCKS.clear()
    assert M.rocks_table() == {}
    (tmp_path / "mining_rocks.json").write_text(json.dumps({"areas": {"X": {"Iron": 100}}}), encoding="utf-8")
    assert M.rocks_table()["areas"]["X"] == {"Iron": 100}
    M._ROCKS.clear()
    keeger = {"name": "Keeger Belt", "zh": "基格", "minerals": {}, "rocks": {"Bexalite": 18.0, "Savrilium": 2.0}}
    order = [t for t, _, _ in S.guesses(28800, "space", keeger)]
    lines = S.describe_all([(28800, False, "28800", None)], "space", keeger)
    assert [l.split(" → ")[1].split("｜精炼后")[0] for l in lines] == order  # noqa: E741



def test_unpacked_mining_spots_and_pyro_areas():
    """2026-10-27 解物件容器：派罗 15 个小行星群、86 个远矿站能量子、刷深空小行星（以前当成阿克罗团）；
    派罗拉格朗日点有子云（派1/派2 暖带 01、派3 暖带 02、派5 冷带 01、派6 冷带 02）；导航「挖矿点」能按矿搜"""
    from sc_mining.navigation import navigate as n
    from sc_mining.mining import mining_area as M
    sp = n.mining_spots()
    if not sp or not M.rocks_table().get("areas", {}).get("Deep Space Asteroids"):
        pytest.skip("没有 data/mining_spots.json / mining_rocks.json")
    fsn = next(p for p in sp if p["n"].endswith("FSN-704"))
    assert fsn["zh"] == "小行星群 FSN-704" and fsn["space"] and fsn["qt"] == 1
    g = (fsn["x"] * 1000, fsn["y"] * 1000, fsn["z"] * 1000)
    a = M.area(g, "Pyro")
    assert a["name"] == "Deep Space Asteroids" and "Torite" in a["rocks"] and "Bexalite" not in a["rocks"]
    assert sum(1 for p in sp if p["n"].startswith("RMB-")) >= 80
    l4 = next(q for q in n.load()["points"] if q.get("i") == "P5_L4")
    a = M.area((l4["x"] + 1e6, l4["y"], l4["z"]), "Pyro")
    assert a["name"] == "PYR5-L4" and set(a["rocks"]) == {"Titanium", "Ice", "Silicon", "Borase"}
    hits, total = n.search("贝沙电气石")
    assert total and all("Bexalite" in (h.get("rocks") or {}) for h in hits if h.get("t") == "Mining Spot")


def test_review_104_final(monkeypatch, tmp_path):
    """1.0.4 发版前 Codex 二审：派罗 L 点缺石头表时不能判成「不刷」；只认正式服数据；星图改正文件坏了不崩"""
    from sc_mining.navigation import navigate as n
    from sc_mining.mining import mining_area as M
    from sc_mining.crafting.build_crafting import pick_live, latest_live, live_version
    # 1. 缺表 → None（不过滤），不是「此处不刷船挖矿」
    try:
        l4 = next(q for q in n.load()["points"] if q.get("i") == "P5_L4")
    except Exception:
        l4 = None
    if l4:
        monkeypatch.setattr(M, "rocks_table", lambda: {"areas": {}})
        monkeypatch.setattr(M, "_spots_raw", lambda: [])
        assert M.area((l4["x"] + 1e6, l4["y"], l4["z"]), "Pyro") is None
    # 2. 只认 LIVE
    assert pick_live(["4.10.3-ptu.1", "4.10.2-live.5", "4.10.1-live.9"]) == "4.10.2-live.5"
    assert pick_live(["4.10.3-ptu.1"]) is None and pick_live([]) is None
    fs = [tmp_path / f"merged-{v}.json" for v in ("4.10.3-ptu.1", "4.9.0-live.99", "4.10.2-live.5")]
    assert latest_live(fs).name == "merged-4.10.2-live.5.json" and latest_live(fs[:1]) is None
    assert live_version(fs[2]) == "4.10.2-live.5"
    # 4. 改正文件结构不对：跳过坏条目，不崩
    monkeypatch.setattr(n, "DATA", tmp_path)
    pts = {"points": [{"n": "A", "x": 1, "y": 2, "z": 3}, {"n": "B", "x": 1, "y": 2, "z": 3}]}
    for bad in ("[]", '{"A": 123}', '{"A": ["bad", 0, 0], "B": [7, 8, 9]}', "{坏"):
        (tmp_path / "starmap_fixes.json").write_text(bad, encoding="utf-8")
        d = {"points": [dict(p) for p in pts["points"]]}
        n._apply_fixes(d)
        assert (d["points"][0]["x"], d["points"][0]["y"]) == (1, 2)
    assert d["points"][1]["x"] == 1                       # 最后一个是坏 JSON，整份不用
    (tmp_path / "starmap_fixes.json").write_text('{"A": ["bad", 0, 0], "B": [7, 8, 9]}', encoding="utf-8")
    n._apply_fixes(d)
    assert (d["points"][1]["x"], d["points"][1]["z"]) == (7.0, 9.0)


def test_signal_mixed_named_and_fixed(monkeypatch, tmp_path):
    """2026-10-27 借鉴别的识别工具：两种石头混在一团（加起来正好相等才算）、玩家自己给信号起名、
    按形近数字改过的读数不算准确"""
    from sc_mining.mining import signals as S
    from sc_mining.mining.data import SIGNATURES
    a, b = sorted(SIGNATURES, key=lambda m: SIGNATURES[m])[:2]
    singles = set(S.all_signatures())
    v = next(SIGNATURES[a] * n + SIGNATURES[b] * m for n in range(1, 6) for m in range(1, 6)
             if SIGNATURES[a] * n + SIGNATURES[b] * m not in singles)
    local = {a: 40.0, b: 30.0}
    mix = S.mixed(v, local)
    assert mix and "混在一团" in mix[0][0] and not mix[0][2]
    assert S.mixed(v, None) == [] and S.mixed(v, {}) == []
    area = {"name": "X", "zh": "某地", "rocks": local}
    g = S.guesses(v, "space", area)
    assert "混在一团" in g[0][0]
    # 自己记的名字排第一
    monkeypatch.setattr(S, "_mine_file", lambda: tmp_path / "my_signatures.json")
    S._MINE.update(stamp=-1, t={})
    S.set_my_signature(v, "  我的怪信号  ")
    assert S.guesses(v, "space", area)[0] == ("我的怪信号（自己记的）", 0, True)
    S.set_my_signature(v, "")
    assert "自己记的" not in S.guesses(v, "space", area)[0][0]
    # 改过一位的读数：说明里写清楚，不按价格排到前面
    real = SIGNATURES[a] * 2
    lines = S.describe_all([(real, True, "x", (0, 0, 1, 1))], "space", None)
    assert lines and "可能有误" in lines[0]


def test_fill_name_exact_tier_before_one_edit():
    """2026-10-27 录制：火神石面板第一行矿名没认出「4.77% 510」（游戏写的是原硅 510）。510 只有硅有这一档，
    要补成硅 510；以前先试「差一个字」，补成了石头里已有的石英、品质改成 710，几帧之间硅 / 石英来回跳"""
    from sc_mining.mining.parse import _fix_by_tiers
    comp = [(None, 4.77, 510), ("Hephaestanite", 3.31, 572), ("Hephaestanite", 53.11, 330), ("Quartz", 2.11, 522),
            ("Inert Materials", 36.68, 0)]
    assert _fix_by_tiers(comp, "Hephaestanite")[0] == ("Silicon", 4.77, 510)

