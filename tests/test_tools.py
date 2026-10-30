"""交易界面、物品在哪买 / 限定版同款 / 最近买点 / 掉落 / 维科洛兑换"""
from tests import patch_services
from datetime import datetime, timezone
from decimal import Decimal as D
from sc_mining.trade import console as C
from sc_mining.trade.models import Item, PriceKey, PriceStats, ProviderResult, ImportRow, OcrToken
import time
from sc_mining import shops, wikelo
import json, time
from sc_mining import shops, position, loot, acquire, navigate


# ======================================================================
# 交易界面（查价、入库、F8 悬停识别）
# ======================================================================

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


class Uex:
    source = 'uex'
    def lookup(self, q):
        return [Item('uex:4741', 'Carinite')] if q in ('Carinite',) else []
    def fetch(self, item, qg, op, now):
        return ProviderResult('uex', 'ok', (PriceStats(PriceKey('uex', item.id, qg, 'UEC', 'scu', '4.3', op), D(5000), D(4200), 3, now, D(4800)),), items=(item,))


class Scm:
    source = 'scm'
    def lookup(self, q):
        return [Item('scm:43475', 'Carinite')] if q in ('科力晶', 'Carinite') else []
    def fetch(self, item, qg, op, now):
        return ProviderResult('scm', 'empty', message='没有挂牌')


def feed(monkeypatch, answers):
    it = iter(answers)
    monkeypatch.setattr(C, '_input', lambda prompt='': next(it))


def test_price_flow_chinese(tmp_path, monkeypatch):
    t = C.Trade(tmp_path, [Uex(), Scm()])
    feed(monkeypatch, ['1', '650', ''])
    C.price_flow(t, '科力晶')
    items, _ = t.lookup('科力晶')
    assert {i.id for i in items} == {'uex:4741', 'scm:43475'}
    item = t.catalog.get('uex:4741')
    lines = t.price_lines(item, t.prices(item, 'q3'))
    assert any('均价 5,000' in l and '最低 4,200' in l for l in lines)


def test_manual_import_and_undo(tmp_path, monkeypatch):
    t = C.Trade(tmp_path, [Uex(), Scm()])
    feed(monkeypatch, ['Carinite', '1', '12', '650', '', 'Area18 仓库', 'y'])
    C.manual_import(t)
    stock = t.inventory.list_stock()
    assert stock[0].quantity == 12 and stock[0].key.quality == 'exact:650' and stock[0].key.location == 'Area18 仓库'
    assert any('12' in l for l in t.stock_lines())
    feed(monkeypatch, ['1'])
    C.history_flow(t)
    assert not t.inventory.list_stock()


def test_review_requires_fix(tmp_path, monkeypatch):
    t = C.Trade(tmp_path, [Uex(), Scm()])
    t.catalog.upsert([Item('uex:4741', 'Carinite')])
    rows = [ImportRow('科力晶', 'uex:4741', None, 'exact:650')]
    feed(monkeypatch, ['', '改 1', '', '5', '', ''])         # 缺数量不让过 → 改成 5 → 确认
    out = C.review_rows(t, rows)
    assert out[0].quantity == 5 and out[0].confirmed


def test_quality_parse():
    assert C._quality('650') == 'exact:650' and C._quality('q6') == 'q6' and C._quality('') is None
    assert C._group('exact:650') == 'q3' and C._group('unknown') == 'q0'


def test_tooltip_name_from_hover_box():
    # 按用户截图里的说明框排版（2K）：名字两行，下面是「体积」
    toks = [OcrToken('极限抬升-II“棱脊”牵引光束', 95, (615, 287, 160, 16)),
            OcrToken('MaxLift-II "Keelback" Tractor', 95, (615, 305, 158, 16)),
            OcrToken('体积：16862 uSCU', 95, (615, 322, 95, 16)),
            OcrToken('制造商：灰猫工业 (Greycat Industrial)', 95, (615, 358, 200, 16)),
            OcrToken('60/60', 95, (106, 818, 40, 16))]
    assert C.tooltip_name(toks) == ('极限抬升-II“棱脊”牵引光束', 'MaxLift-II "Keelback" Tractor')
    assert C.tooltip_name([OcrToken('60/60', 95, (106, 818, 40, 16))]) is None


def test_match_tooltip_prefers_truncated_english(tmp_path):
    class U:
        source = 'uex'
        def lookup(self, q):
            return [Item('uex:9', 'MaxLift-II "Keelback" Tractor Beam'), Item('uex:8', 'MaxLift Tractor Beam')] if 'MaxLift' in q else []
        def fetch(self, *a): return ProviderResult('uex', 'empty')
    t = C.Trade(tmp_path, [U()])
    item, _ = C.match_tooltip(t, '极限抬升-II“棱脊”牵引光束', 'MaxLift-II "Keelback" Tractor')
    assert item.id == 'uex:9'


def test_tooltip_real_ocr_output():
    # 用户截图实际识别结果（含聊天窗口、库存面板的干扰文字，II 被认成 ll、空格丢了）
    T = lambda text, x, y: OcrToken(text, 90, (x, y, max(20, len(text) * 9), 18))
    toks = [T('个人/全部', 310, 135), T('容量：', 340, 182), T('0/59K', 455, 186), T('移动所有', 214, 182),
            T('直接输入物品名就能查价，中文、英文都行', 822, 103),
            T('极限抬升-II“棱脊”牵引光束', 615, 287), T('MaxLift-ll"Keelback"Tractor', 615, 305),
            T('体积：16862uSCU', 615, 322), T('回复', 796, 298)]
    assert C.tooltip_name(toks, (690, 450)) == ('极限抬升-II“棱脊”牵引光束', 'MaxLift-ll"Keelback"Tractor')


def test_match_tolerates_ocr_noise(tmp_path):
    class U:
        source = 'uex'
        def lookup(self, q):
            return [Item('uex:9', 'MaxLift-II "Keelback" Tractor Beam'), Item('uex:8', 'MaxLift Tractor Beam')] if q.startswith('MaxLift') else []
        def fetch(self, *a): return ProviderResult('uex', 'empty')
    t = C.Trade(tmp_path, [U()])
    item, _ = C.match_tooltip(t, '极限抬升-II“棱脊”牵引光束', 'MaxLift-ll"Keelback"Tractor')
    assert item.id == 'uex:9'


def test_tooltip_skips_description_lines():
    # 实测：飞行服说明框（描述句子 + 墙上的英文标语 STAND CLEAR 不能当成名字）
    T = lambda text, x, y: OcrToken(text, 90, (x, y, max(20, len(text) * 9), 18))
    toks = [T('太阳-I飞行服飞行员', 800, 100), T('Sol-IllFlightSuitAviator', 800, 120), T('体积：23000uSCU', 800, 140),
            T('物品类型：飞行服', 800, 175), T('设计，同时融入了现代的舒适性。', 800, 600),
            T('这款飞行员版主体采用黄绿色搭配浅绿色的装饰。', 800, 630), T('STAND CLEAR', 805, 650)]
    assert C.tooltip_name(toks, (820, 640)) == ('太阳-I飞行服飞行员', 'Sol-IllFlightSuitAviator')


def test_unrelated_search_results_dropped(tmp_path):
    junk = [Item(f'scm:{n}', name) for n, name in enumerate(['A03 "Scorched" Sniper Rifle', 'Abrade Scraper Module', 'Council Scrip'])]
    class S:
        source = 'scm'
        def lookup(self, q):
            return junk + ([Item('scm:99', 'CQ7 Rifle')] if q in ('CQ7 Rifle', 'CQ7') else [])
        def fetch(self, *a): return ProviderResult('scm', 'empty')
    t = C.Trade(tmp_path, [S()])
    item, cands = C.match_tooltip(t, 'CQ7步枪', 'CQ7Rifle')
    assert item.id == 'scm:99' and all('Scrip' not in c.name for c in cands)
    class N(S):
        def lookup(self, q): return junk
    item, cands = C.match_tooltip(C.Trade(tmp_path / 'x', [N()]), 'CQ7步枪', 'CQ7Rifle')
    assert item is None and cands == []


# ======================================================================
# 物品在哪买、维科洛
# ======================================================================

def fake_shops(monkeypatch):
    data = {"fmt": shops.FMT, "fetched": time.time(), "items": {"1600": ["SureGrip S1 Tractor Beam", "Tractor Beams"],
                                              "1700": ["MaxLift Tractor Beam", "Tractor Beams"]},
            "rows": [[1600, "Refinery Shop - ARC-L4", "Stanton · ArcCorp · ARC-L4 Faint Glen Station", 4600, 0, "4.10"],
                     [1600, "Cousin Crow's - Orison", "Stanton · Crusader · Orison", 4500, 0, "4.10"],
                     [1700, "Shubin - Lorville", "Stanton · Hurston · Lorville", 0, 1200, "4.10"]]}
    monkeypatch.setattr(shops, "_data", data)


def test_finder_cheapest_first(monkeypatch):
    fake_shops(monkeypatch)
    assert shops.find("SureGrip S1")[0][0] == 1600
    buy, sell = shops.where(1600)
    assert buy[0][0] == 4500 and "Orison" in buy[0][2] and not sell
    text = shops.where_text(1700)
    assert "没有这件东西的商店售卖记录" in text and "1,200" in text
    assert "Orison" in shops.where_by_name("SureGrip S1 Tractor Beam")


def test_wikelo_data_and_lookup():
    rows = wikelo.load()
    assert len(rows) > 50
    hits = wikelo.uses("Carinite (Pure)")
    assert hits and all(any(r["n"] == "Carinite (Pure)" for r in c["req"]) for c, _, _ in hits)
    assert wikelo.uses("", "纯净科力晶")
    asg = wikelo.search("Asgard")
    assert asg and "Wikelo Favor" in [r["n"] for r in asg[0]["req"]]
    text = wikelo.describe(asg[0], lambda n: "可买：某店" if n == "ASD Secure Drive" else "")
    assert "× 50 个" in text and "可买：某店" in text


def test_console_commands(monkeypatch):
    fake_shops(monkeypatch)
    out = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: out.append(" ".join(map(str, a))))
    monkeypatch.setattr(C, "_input", lambda prompt="": "1")
    C.finder_flow("SureGrip S1")
    assert any("4,500" in l for l in out)
    out.clear()
    C.wikelo_flow("Asgard")                     # 船名中文与否看玩家装的汉化包（有的包船名不翻译），这里用英文名
    assert any("Asgard" in l or "阿斯加德" in l for l in out) and any("Wikelo Favor" in l or "维科洛" in l for l in out)


# ======================================================================
# 限定版同款、最近买点、掉落
# ======================================================================

POINTS = [dict(n="ArcCorp", i="Stanton3", sys="Stanton", t="Planet", x=18587664740, y=-22151916920, z=0),
          dict(n="ARC L4", i="Stanton3_L4", sys="Stanton", t="Lagrange Point", x=28478354915, y=5021502482, z=8076),
          dict(n="Crusader", i="Stanton2", sys="Stanton", t="Planet", x=-18962176000, y=-2664960000, z=0),
          dict(n="Microtech", i="Stanton4", sys="Stanton", t="Planet", x=22462085252, y=37185744964, z=0),
          dict(n="Pyro1", i="Pyro1", sys="Pyro", t="Planet", x=-7920920853, y=-2386976476, z=0)]


def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(navigate, "_data", {"bodies": {}, "pois": [], "points": POINTS})
    data = {"fmt": shops.FMT, "fetched": time.time(),
            "items": {"1700": ["MaxLift Tractor Beam", "Tractor Beams"], "1701": ["MaxLift Tractor Beam Battery", "Attachments"],
                      "1800": ['MaxLift-II "Keelback" Tractor Beam', "Tractor Beams"]},
            "rows": [[1700, "Shop ARC-L4", "Stanton · ArcCorp · ARC-L4", 18000, 9000, "4.10",
                      ["Stanton", "ArcCorp", "ArcCorp Lagrange Point 4", "", "ARC-L4 Faint Glen Station", ""]],
                     [1700, "Shop Orison", "Stanton · Crusader · Orison", 17000, 0, "4.10", ["Stanton", "Crusader", "", "", "", "Orison"]],
                     [1700, "Shop NB", "Stanton · microTech · New Babbage", 19000, 0, "4.10", ["Stanton", "microTech", "", "", "", "New Babbage"]],
                     [1701, "Shop NB", "x", 300, 0, "4.10", ["Stanton", "microTech", "", "", "", ""]]]}
    monkeypatch.setattr(shops, "_data", data)


def test_shop_point_and_nearest(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    assert shops.shop_point(["Stanton", "ArcCorp", "ArcCorp Lagrange Point 4", "", "ARC-L4", ""])["n"] == "ARC L4"
    assert shops.shop_point(["Stanton", "Crusader", "", "", "", "Orison"])["n"] == "Crusader"
    here = dict(POINTS[3], label="NB", age=0)                                   # 在微科星
    near = shops.nearest(1700, here, 3)
    assert near[0][2] == "Shop NB" and near[0][0] == 0


def test_log_location(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    log = tmp_path / "Game.log"
    log.write_text("<2026-10-20T05:00:00.000Z> [Notice] <RequestLocationInventory> Player[X] requested inventory for Location[RR_ARC_L4] [Team]\n"
                   "<2026-10-20T05:10:00.000Z> [Notice] <Calculate Route> ...|Projected Start Location is 微科星 (microTech) for route to destination LOC_X\n",
                   encoding="utf-8")
    t, label, p = position.from_log(log)
    assert p["n"] == "ARC L4"                      # 只认「打开库存」的地点，量子路线的出发点不算
    assert position.from_code("Stanton4_NewBabbage")["n"] == "Microtech"
    assert position.from_code("RR_ARC_L4")["n"] == "ARC L4"


def test_limited_variant_recommends_base(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(position, "current", lambda: dict(POINTS[2], label="在 十字军 开过库存", age=0))
    monkeypatch.setattr(loot, "text", lambda en="", zh="", top=5: "  掉落（测试）：\n    ASD：1.06%")
    out = acquire.text('MaxLift-II "Keelback" Tractor Beam', "", 1800)
    assert "商店买不到" in out and "MaxLift Tractor Beam（3 处有卖）" in out and "Battery" not in out
    assert out.index("Shop Orison") < out.index("Shop NB")                       # 在十字军，奥里森最近
    assert "掉落" in out
    out2 = acquire.text("MaxLift Tractor Beam", "", 1700)                        # 能买 + 也有掉落：两个都显示
    assert "商店有卖（共 3 处）" in out2 and "掉落" in out2 and "卖给商店最高：9,000" in out2


def test_loot_summary():
    d = {"regions": [{"id": "asddelving", "name": "ASD", "best": 0.0106, "containers": [{"name": "Lootable_Container_Large", "openp": 0.0106}]},
                     {"id": "caves", "name": "洞穴", "best": 0.0000067, "containers": [{"name": "Lootable_Generated_Container_06_dirty", "loc": "阿伯丁洞穴·中等", "openp": 6.7e-6}]}]}
    rows = loot.summary(d)
    assert rows[0][0] == "ASD" and "Large" in rows[0][2] and "阿伯丁洞穴" in rows[1][2]


def test_nearest_distinct_places_and_loot_grouping(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    shops._data["rows"].append([1700, "Shop NB 2", "Stanton · microTech · New Babbage", 18500, 0, "4.10",
                                ["Stanton", "microTech", "", "", "", "New Babbage"]])
    near = shops.nearest(1700, dict(POINTS[3], label="", age=0), 3)
    assert len({r[3] for r in near}) == 3 and near[0][2] == "Shop NB 2"          # 同一地点只留最便宜的
    d = {"regions": [{"name": n, "best": 0.0106, "containers": [{"name": "Lootable_Container_Large", "openp": 0.0106}]}
                     for n in ("ASD", "QV", "Hathor")] + [{"name": "SoO", "best": 0.1364, "containers": []}]}
    monkeypatch.setattr(loot, "find", lambda en, zh: [("u", "X", "某物", 1)])
    monkeypatch.setattr(loot, "detail", lambda u, online=True: d)
    t = loot.text("X")
    assert "13.64%｜SoO" in t and "1.06%｜Large 箱｜ASD、QV、Hathor" in t and t.count("1.06%") == 1


# ======================================================================
# 助手窗口（app）
# ======================================================================

def test_app_scan_view_and_manual():
    from sc_mining.parse import parse_scan
    from sc_mining.app import services
    s = parse_scan(["扫描结果", "钨矿石", "质量： 44336", "抗性： 4% ", "不稳定性： 17.32", "组成 23.68 SCU",
                    "6.55% 兰石原矿 510", "12.95% 钨矿石 662", "49.41% 钨矿石 363", "31.07% 情性物质 。"])
    v = services.scan_view(s, ({"Inert Materials": 0.3}, 0.3, 96.0))
    assert v["rock"] and v["plans"] and v["refine"] and v["bag"]["cap"] == 96.0
    assert "kg" in v["hud"] and v["plans"][0]["heads"]
    mats = {m["en"]: m for m in v["craft_mats"]}                       # 「可制造 N 份蓝图」按钮的数据
    if mats:
        assert mats["Tungsten"]["q"] == 662 and mats["Tungsten"]["count"] > 0      # 同种矿取最高品质
        assert all(m["count"] > 0 and m["ok"] is not None for m in mats.values())
        assert [m["en"] for m in v["minerals"]] and all("en" in m for m in v["minerals"])
    assert services.manual_scan(mass=20000, resistance=10, instability=5)


def test_app_task_log_routing():
    import queue as _q
    from sc_mining.app import bus
    bus.install_router()
    q = bus.subscribe()
    try:
        bus.run_task("t1", lambda: print("你好\n第二行") or 7, title="测试").join(3)
        got = []
        while True:
            try:
                got.append(q.get_nowait())
            except _q.Empty:
                break
        lines = [m["data"]["line"] for m in got if m["kind"] == "log" and m["data"]["task"] == "t1"]
        assert lines == ["你好", "第二行"]
        assert any(m["kind"] == "task" and m["data"].get("state") == "done" and m["data"]["result"] == 7 for m in got)
    finally:
        bus.unsubscribe(q)


def test_app_server_roundtrip():
    import json as _j
    import threading as _t
    import urllib.request as _u
    from http.server import ThreadingHTTPServer
    from sc_mining.app.server import Handler, TOKEN
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    _t.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        html = _u.urlopen(base + "/").read().decode("utf-8")
        assert "AT 星际公民助手" in html and "app.js" in html
        assert b"PAGES" in _u.urlopen(base + "/app.js").read()
        # 用出厂配装也破得开的石头（一个 Arbor MH2 最多 14,500 kg），不依赖这台电脑上存的配装
        body = _j.dumps({"mass": 8000, "resistance": 0, "instability": 1}).encode()
        req = _u.Request(base + "/api/manual_scan", data=body, headers={"Content-Type": "application/json", "X-Token": TOKEN})
        r = _j.loads(_u.urlopen(req).read())
        assert r["ok"] and r["data"][0]["breakable"]
        for headers in ({}, {"X-Token": "guess"}, {"X-Token": TOKEN, "Origin": "https://evil.example"}):
            try:                                            # 没口令、口令错、别的网站发来的：都拒绝
                _u.urlopen(_u.Request(base + "/api/manual_scan", data=body, headers=headers))
                assert False, headers
            except Exception as e:
                assert "403" in str(e), e
        try:
            _u.urlopen(base + "/api/events")
            assert False
        except Exception as e:
            assert "403" in str(e)
        req = _u.Request(base + "/api/nope", data=b"{}", headers={"X-Token": TOKEN})
        try:
            _u.urlopen(req)
            assert False
        except Exception as e:
            assert "404" in str(e)
        try:
            _u.urlopen(base + "/../settings.py")
            assert False
        except Exception as e:
            assert "404" in str(e)
    finally:
        srv.shutdown()


def test_displayinfo_parse():
    """游戏右上角 r_DisplayInfo 的文字（取自你 2026-10-20 新巴贝奇医院的截图）"""
    from sc_mining.displayinfo import parse
    lines = ["Zone: ObjectContainer-Ground Lobby Pos: -4.61m 74.93m 11.71m",
             "Zone: OOC_Stanton_4_Microtech Pos: 520.9152km 410.2893km 744.0843km",
             "Zone: SolarSystem_862949775749 Pos: 22462326.4853km 37186368.6338km 744.0843km",
             "Zone: Root Pos: 22462326.4853km 37186368.6338km 744.0843km",
             "Current player location : Hospital Stanton4 NewBabbage (L2 : Stanton4 NewBabbage)",
             "Planet: OOC_Stanton_4_Microtech (Load Complete)"]
    d = parse(lines)
    assert all(abs(a - b) < 0.01 for a, b in zip(d["global"], (22462326485.3, 37186368633.8, 744084.3)))
    assert d["local"] == (520.9152, 410.2893, 744.0843) and "Microtech" in d["zone"]
    assert d["location"].startswith("Hospital Stanton4 NewBabbage") and "Microtech" in d["planet"]
    bad = list(lines)
    bad[3] = "Zone: Root Pos: 22462326.4853km 37186868.6338km 744.0843km"      # OCR 认错一位：两行对不上就不用
    assert parse(bad)["global"] is None
    assert parse(["纯音乐，请欣赏"])["global"] is None


def test_displayinfo_feeds_locate(monkeypatch):
    from sc_mining import navigate
    from sc_mining.displayinfo import parse
    if not navigate.CACHE.exists():
        import pytest
        pytest.skip("没有星图数据")
    g = parse(["Zone: SolarSystem_1 Pos: 22462326.4853km 37186368.6338km 744.0843km"])["global"]
    monkeypatch.setattr(navigate, "_remember", lambda *a, **k: None)
    here = navigate.locate(g)
    assert here["body"] == "microTech" or "icro" in here["body"]


def test_displayinfo_local_beats_rotation_math():
    from sc_mining import navigate
    if not navigate.CACHE.exists():
        import pytest
        pytest.skip("没有星图数据")
    assert navigate.zone_body("OOC Stanton 4 Microtech") == "Microtech"
    assert navigate.zone_body("OOC Stanton 2b Daymar") == "Daymar"
    navigate_remember = navigate._remember
    navigate._remember = lambda *a, **k: None
    navigate._offsets.clear()
    g = (22462326485.3, 37186368633.8, 744084.3)
    try:
        ref = navigate.locate(g)
        assert ref["src"] == "推算"
        near = (ref["x"] + 0.1, ref["y"] - 0.1, ref["z"])
        h = navigate.locate(g, local=near, zone="OOC Stanton 4 Microtech")
        assert (h["x"], h["y"]) == near[:2] and h["src"] == "游戏"            # 游戏给的、和推算接近：用游戏的
        h = navigate.locate(g, local=(520.9, 310.2, 744.1), zone="OOC Stanton 4 Microtech")
        # OCR 认错一位、差太远：不用；用「推算 + 刚才记下的偏差」，位置和上一次一样，不会跳回推算的
        assert abs(h["x"] - near[0]) < 0.01 and abs(h["y"] - near[1]) < 0.01 and h["src"] == "推算+偏差"
        h = navigate.locate(g, local=near, zone="OOC Stanton 4 Microtech", local_ok=False)     # 和 CamPos 对不上
        assert h["src"] == "推算+偏差"
        assert abs(ref["height_m"] - 396) < 20                                # 游戏显示 Altitude 396 m
    finally:
        navigate._remember = navigate_remember
        navigate._offsets.clear()


def test_log_place_is_specific(monkeypatch):
    """顶部「位置」要显示具体地点（新巴贝奇），不是星球（微科星）"""
    from sc_mining import position
    monkeypatch.setattr(position, "_places_zh", lambda: {"newbabbage": "新巴贝奇", "arcl1wideforeststation": "弧 L1 广袤森林站",
                                                         "checkmate": "死局空间站"})
    monkeypatch.setattr(position, "_station_at", lambda i: "Checkmate Station" if i == "P2_L4" else "")
    position.place_name.cache_clear()
    assert position.place_name("Stanton4_NewBabbage") == "新巴贝奇"
    assert position.place_name("RR_ARC_L1") == "弧 L1 广袤森林站"
    assert position.place_name("RR_P2_L4") == "死局空间站"
    assert position.place_name("Stanton1_SomeNewPlace") == "Some New Place"
    position.place_name.cache_clear()


def test_displayinfo_real_ocr_lines():
    """你电脑上 RapidOCR 读你截图右上角的真实结果（S 认成 5、O 认成 0）"""
    from sc_mining.displayinfo import parse
    d = parse(["Zone:0bjectcontainer-Ground_Lobby Pos:-4.6lm 74.93m 11.71m",
               "Zone: 00c_Stanton_4_Microtech Pos: 520.9152km 419.2893km 744.0843km",
               "Zone: 5olarSystem_862949775749 Pos: 22462326.4853km 37186368.6338km 744.0843km",
               "Currentplayer location :HospitalStanton4 NewBabbage(LZ:Stanton4 NewBabbage)",
               "Planet:ooc_Stanton_4_Microtech(Load Complete)"])
    assert d["global"] and abs(d["global"][0] - 22462326485.3) < 1
    assert d["local"] == (520.9152, 419.2893, 744.0843) and "NewBabbage" in d["location"]


def test_first_run_agreement(monkeypatch, tmp_path):
    from sc_mining import settings, helpers
    from sc_mining.app import services
    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    started = []
    monkeypatch.setattr(helpers, "start", lambda: started.append("helpers"))
    patch_services(monkeypatch, "start_background", lambda: started.append("bg"))
    assert settings.load()["agreed"] is False
    assert "error" in services.agree("本软件是免费的")                    # 差一个字都不行
    assert settings.load()["agreed"] is False and not started
    services.agree(" 本软件是免费软件 ")
    assert settings.load()["agreed"] is True and started == ["helpers", "bg"]


def test_live_scan_updates_when_read_gets_more_complete(monkeypatch, tmp_path):
    """画面不动时：第一次读到的成分不全，后面读全了也要更新（不能停在不完整的结果上）"""
    import threading, time as _t
    from PIL import Image
    from sc_mining import screen, signals, paths
    monkeypatch.setattr(paths, "log", lambda name: tmp_path / name)        # 别往电脑上真实的扫描记录里写
    monkeypatch.setattr(paths, "shots", lambda name: tmp_path)
    from sc_mining.parse import Scan
    from sc_mining.app import services, bus
    img = Image.new("RGB", (320, 180), (20, 20, 20))
    part = Scan(rock="Tungsten", mass=44336, resistance=4, instability=17.32, total_scu=23.68,
                composition=[("Tungsten", 12.95, 662), ("Tungsten", 49.41, 363), ("Inert Materials", 37.64, 0)])
    full = Scan(rock="Tungsten", mass=44336, resistance=4, instability=17.32, total_scu=23.68,
                composition=[("Laranite", 6.55, 510), ("Tungsten", 12.95, 662), ("Tungsten", 49.41, 363),
                             ("Inert Materials", 31.07, 0)])
    seq = [part, part, full, full, full, full, full, full]
    calls = []

    def analyse(_):
        calls.append(1)
        return (seq[min(len(calls) - 1, len(seq) - 1)], ({}, None, None))
    monkeypatch.setattr(screen, "grab", lambda: img)
    monkeypatch.setattr(screen, "analyse", analyse)
    monkeypatch.setattr(screen, "INTERVAL", 0.01)
    monkeypatch.setattr(signals, "find_signatures", lambda im: [])
    patch_services(monkeypatch, "_game_front", lambda: None)            # 不看真电脑上哪个窗口在最前面
    q = bus.subscribe()
    live = services._Live()
    try:
        live.stop_ev = threading.Event()
        th = threading.Thread(target=live._run, daemon=True)
        th.start()
        _t.sleep(1.0)
        live.stop_ev.set()
        th.join(2)
        scans = []
        while not q.empty():
            m = q.get_nowait()
            if m["kind"] == "scan":
                scans.append(m["data"])
        assert scans, "没有出结果"
        assert len(scans[-1]["minerals"]) == 2, scans[-1]["minerals"]       # 最后显示的是读全的（钨 + 兰石）
        assert len(calls) < 40                                              # 画面不动、结果已完整：不再一直识别
    finally:
        bus.unsubscribe(q)


def test_tooltip_name_food_without_english_name():
    """食物说明框只有中文名，下面是「NDR:20 免疫下降」「剩余容量：100%」这类属性行，不能当名字（实测 肉串）"""
    from sc_mining.trade import console as C
    from sc_mining.trade.ocr import OcrToken
    T = lambda text, x, y: OcrToken(text, 90, (x, y, max(20, len(text) * 9), 18))
    toks = [T('Zone:P2_L4Pos:-11023.9564km', 1960, 22), T('Current player location :RR P2 L4 CLINIC(LZ:R P24)', 2160, 200),
            T('肉串', 864, 374), T('NDR:20免疫下降', 864, 398), T('体积：0uSCU', 864, 422), T('剩余容量：100%', 864, 444),
            T('NDR:20', 864, 488), T('效果：免疫下降', 864, 512), T('一根烤串，上面有着大块大块的肯定是肉的东西。', 864, 558),
            T('60/60', 140, 1056)]
    assert C.tooltip_name(toks, (900, 500)) == ('肉串', '')


def test_display_label_lagrange_station():
    from sc_mining.position import display_label as d
    assert d('RR P2 L4 CLINIC(LZ:R P24)') == '死局空间站'
    assert d('RR P2 L4(LZ:RR P24)') == '死局空间站'
    assert d('RR_HUR_L2') == '赫 L2 坚贞梦想站'
    assert d('Hospital Stanton4 NewBabbage (L2 : Stanton4 NewBabbage)') == '新巴贝奇'


def test_status_keeps_displayinfo_place_when_reader_goes_stale():
    """切屏后右上角暂时读不到，位置还显示死局空间站，不跳回别的；游戏日志里有更新的地点才换。
    2026-10-26 起不导航也一直读右上角（实时位置）：右上角读到的比日志新就用右上角的"""
    import time
    from sc_mining.app import services as S
    import sc_mining.position as P
    old = P.current, P.from_log, S._pos.label, S._nav.target
    try:
        S._nav.target = {"n": "测试目标"}
        S._pos.reader.ok_at = 0                       # 读取器已经不算「开着」
        S._pos.label = (time.time() - 20, "死局空间站")
        P.current = lambda *a, **k: {"label": "玛格达 附近", "age": 1.0, "sys": "Pyro"}
        P.from_log = lambda *a, **k: (time.time() - 3600, "死局空间站", {})
        assert S.status()["position"]["label"] == "死局空间站"
        P.current = lambda *a, **k: {"label": "鼠巢空间站", "age": 2.0, "sys": "Pyro"}   # 后来在别处开了库存
        P.from_log = lambda *a, **k: (time.time() - 2, "鼠巢空间站", {})
        assert S.status()["position"]["label"] == "鼠巢空间站"
        S._nav.target = None                          # 不导航也一样：右上角刚读到的比日志新，用右上角的
        S._pos.label = (time.time(), "死局空间站")
        assert S.status()["position"]["label"] == "死局空间站"
    finally:
        P.current, P.from_log, S._pos.label, S._nav.target = old


def test_single_instance_lock_file(monkeypatch, tmp_path):
    """只开一个：第一个拿到锁，第二个拿不到；第一个放开后又能拿到（用临时文件夹，电脑上开着天枢也不影响）"""
    import subprocess, sys
    from sc_mining import paths
    from sc_mining.app import server as S
    monkeypatch.setattr(paths, "USER", tmp_path)
    first = S._try_lock()
    assert first is not None
    try:   # 另一个进程（模拟第二个天枢）拿不到
        code = ("from pathlib import Path; from sc_mining import paths; paths.USER = Path(%r); "
                "from sc_mining.app import server as S; print(S._try_lock() is None)" % str(tmp_path))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(S.Path(__file__).resolve().parents[1]))
        assert out.stdout.strip().endswith("True"), out.stderr
    finally:
        first.close()
    again = S._try_lock()
    assert again is not None
    again.close()


def test_log_location_found_far_back_and_updates(monkeypatch, tmp_path):
    """「打开库存」在很早以前（几十 MB 之前）也能找到；之后日志新增了新的「打开库存」就换成新的"""
    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(position, "CHUNK", 1000)        # 用小块模拟大文件
    monkeypatch.setattr(position, "_save_ids", lambda: None)
    position._log_cache.clear()
    log = tmp_path / "Game.log"
    inv = "<2026-10-20T05:00:00.000Z> [Notice] <RequestLocationInventory> Player[X] requested inventory for Location[{}] [Team]\n"
    log.write_text(inv.format("RR_ARC_L4") + "<2026-10-20T05:01:00.000Z> noise line padding padding\n" * 500, encoding="utf-8")
    assert position.from_log(log)[2]["n"] == "ARC L4"
    with open(log, "a", encoding="utf-8") as f:
        f.write(inv.format("Stanton4_NewBabbage"))
    assert position.from_log(log)[2]["n"] == "Microtech"


def test_mask_overlay_blacks_out_hud():
    from PIL import Image
    from sc_mining.perf import mask_overlay
    img = Image.new("RGB", (100, 100), (255, 255, 255))
    mask_overlay(img, 50, 50, rect=(60, 60, 80, 70))         # 截图从屏幕 (50,50) 开始
    assert img.getpixel((15, 15)) == (0, 0, 0) and img.getpixel((5, 5)) == (255, 255, 255)
    assert img.getpixel((35, 15)) == (255, 255, 255)


def test_hud_prices_fall_back_when_no_minimum():
    """UEX 常常没有最低价：用均价，再没有用 7 天均价，并标明是哪种价"""
    from decimal import Decimal as D
    from types import SimpleNamespace as N
    from sc_mining.trade.console import hud_prices
    st = lambda src, mn, mean, wk: N(key=N(source=src), minimum=mn, mean=mean, week_mean=wk)
    r = lambda src, *s: N(source=src, stats=s)
    assert hud_prices([r("uex", st("uex", None, D(15000), None)), r("scm", st("scm", D(9500), D(11000), None))]) \
        == "UEX 均价 15,000；SCM 最低 9,500"
    assert hud_prices([r("uex", st("uex", None, None, D(14000)))]) == "UEX 7天均价 14,000"
    assert hud_prices([r("uex"), r("scm")]).startswith("暂无报价")


def test_log_location_learns_ids_and_follows_moves(monkeypatch, tmp_path):
    """开个人库存学到「编号 ↔ 地点」；之后开本地库存/走动时日志只给编号，认识的编号也能更新位置；
    不认识的编号（比如进了飞船）保持原地点；半行写入不会丢"""
    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(position, "_save_ids", lambda: None)
    position._log_cache.clear()
    position._log_cache["ids"] = {}
    log = tmp_path / "Game.log"
    L = lambda t, body: f"<2026-10-20T05:{t}.000Z> [Notice] {body} [Team_CoreGameplayFeatures][Inventory]\n"
    log.write_text(
        L("00:00", "<RequestLocationInventory> Player[X] requested inventory for Location[Stanton4_NewBabbage]")
        + L("00:01", "<Query Inventory> Request[1] Inventory[7:Location:111] ")
        + L("01:00", "<RequestLocationInventory> Player[X] requested inventory for Location[RR_ARC_L4]")
        + L("01:01", "<Query Inventory> Request[2] Inventory[7:Location:222]"), encoding="utf-8")
    assert position.from_log(log)[2]["n"] == "ARC L4"
    assert position._ids() == {"111": "Stanton4_NewBabbage", "222": "RR_ARC_L4"}
    with open(log, "a", encoding="utf-8") as f:                 # 进飞船：不认识的编号，保持原地点
        f.write(L("02:00", "<Update Inventory Location> Player [X] is changing location. Landing [222] -> [222]. Location [222] -> [999]. Pending [0]"))
    assert position.from_log(log)[2]["n"] == "ARC L4"
    line = L("03:00", "<Update Inventory Location> Player [X] is changing location. Landing [0] -> [111]. Location [0] -> [111]. Pending [0]")
    with open(log, "a", encoding="utf-8") as f:                 # 游戏只写了半行
        f.write(line[:40])
    position.from_log(log)
    with open(log, "a", encoding="utf-8") as f:
        f.write(line[40:])
    assert position.from_log(log)[2]["n"] == "Microtech"       # 回到认识的地点：更新


def test_hud_market_min_max_mean_and_hide_empty():
    from decimal import Decimal as D
    from types import SimpleNamespace as N
    from sc_mining.trade.console import hud_market
    key = N(source="uex")
    st = lambda mn, mean, wk=None: N(key=key, minimum=mn, mean=mean, week_mean=wk)
    q = lambda p: N(key=key, price=D(p))
    r = lambda stats, quotes=(): N(source="uex", stats=stats, quotes=quotes)
    assert hud_market([r([st(None, D(12000))], [q(9500), q(20000)])]) == "UEX 已知最低 9,500｜最高 20,000｜均价 12,000"
    assert hud_market([r([st(D(9000), None, D(11000))])]) == "UEX 最低 9,000｜7天均价 11,000"
    assert hud_market([r([st(None, None)]), N(source="scm", stats=(), quotes=())]) == ""     # 没数据：不显示


def test_hover_overlay_updates_before_network(monkeypatch):
    """F8：名字和本机数据先上悬浮窗，联网的（市场匹配、查价、掉落）在后台；后台慢也不耽误悬浮窗"""
    import threading, time
    from PIL import Image
    from sc_mining.app import services as S
    from sc_mining.trade import console as C
    from sc_mining.trade.ocr import OcrToken
    T = lambda text, x, y: OcrToken(text, 90, (x, y, max(20, len(text) * 9), 18))
    toks = [T('CQ7步枪', 1368, 367), T('CQ7Rifle', 1368, 391), T('体积：13000uSCU', 1368, 414)]
    calls = []
    monkeypatch.setattr("sc_mining.trade.ocr.recognize", lambda img, urgent=False, offset=(0, 0): calls.append((img.size, urgent)) or toks)
    gate = threading.Event()
    monkeypatch.setattr(C, "match_tooltip", lambda *a, **k: (gate.wait(5), (None, []))[1])   # 联网很慢
    monkeypatch.setattr(C, "_hover_log", lambda *a, **k: None)
    monkeypatch.setattr(C, "_cursor_on_image", lambda img: (1280, 720))   # 不看真鼠标在哪
    shown = []

    class Hud:
        def set(self, sec, text):
            shown.append((time.time(), text))
    patch_services(monkeypatch, "_hud", lambda: Hud())
    t0 = time.time()
    r = S.hover_once(Image.new("RGB", (2560, 1440)))
    assert r["ok"] and shown[-1][1].startswith(("CQ7步枪", "CQ7 步枪"))      # 名字按汉化包纠正成标准写法（1.6.37）
    assert shown[-1][0] - t0 < 2.0                           # 没等联网
    assert calls[0] == ((512, 1440), True)                  # 鼠标在 50%：先认左边 30%~50% 整高一条，插队识别（NGU 2026-10-30 改的分区）
    gate.set()


def test_match_tooltip_uses_local_catalog_without_network(tmp_path):
    from sc_mining.trade import console as C
    from sc_mining.trade.models import Item

    class Boom:
        source = "uex"
        def lookup(self, q):
            raise AssertionError("不该联网")
        def fetch(self, *a):
            raise AssertionError("不该联网")
    t = C.Trade(tmp_path / "x", [Boom()])
    t.catalog.upsert([Item("u1", "CQ7 Rifle", None)])
    item, _ = C.match_tooltip(t, "CQ7步枪", "CQ7Rifle")
    assert item.id == "u1"
    t.catalog.add_alias("u1", "CQ7步枪")
    item, _ = C.match_tooltip(t, "CQ7步枪", "乱码")                # 认过的中文名：直接对上
    assert item.id == "u1"


class _FakeClient:
    """不联网的假 HTTP：按网址路径返回 JSON，记下请求了哪些"""
    def __init__(self, handler, delay=0.0):
        self.handler, self.delay, self.calls = handler, delay, []

    def get(self, url, params=None, headers=None, timeout=15):
        import json, time
        from sc_mining.trade.providers.http import _Response
        self.calls.append((url, dict(params or {})))
        time.sleep(self.delay)
        return _Response(200, {}, json.dumps(self.handler(url, params or {})))

    def close(self):
        pass


def test_scm_orders_downloaded_once_and_pages_in_parallel():
    import time
    from datetime import datetime, timezone
    from sc_mining.trade.models import Item
    from sc_mining.trade.providers.http import HttpTransport
    from sc_mining.trade.providers.scm import ScmProvider

    def handler(url, params):
        if "orders/page" in url:
            return {"code": 0, "data": {"total": 450, "list": []}}
        return {"code": 0, "data": []}
    client = _FakeClient(handler, delay=0.2)
    p = ScmProvider(HttpTransport(client=client, sleep=lambda _: None))
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    t = time.time()
    p.fetch(Item("scm:1", "A"), "q0", "sell", now)
    first = time.time() - t
    pages = [c for c in client.calls if "orders/page" in c[0]]
    assert len(pages) == 5 and first < 0.2 * 5            # 5 页：第 1 页后其余 4 页一起下
    p.fetch(Item("scm:2", "B"), "q0", "sell", now)           # 换个物品：挂单列表直接用上次的
    assert len([c for c in client.calls if "orders/page" in c[0]]) == 5


def test_market_sources_are_queried_at_the_same_time(tmp_path):
    import time
    from datetime import datetime, timezone
    from sc_mining.trade.market_service import MarketService
    from sc_mining.trade.models import Item, ProviderResult
    from sc_mining.trade.storage import Database

    class Slow:
        def __init__(self, source):
            self.source = source
        def fetch(self, *a):
            time.sleep(0.4)
            return ProviderResult(self.source, "empty")
    s = MarketService(Database(tmp_path / "m.db"), [Slow("uex"), Slow("scm")])
    t = time.time()
    r = s.refresh(Item("a", "A"), "q0", "sell", datetime(2026, 10, 20, tzinfo=timezone.utc))
    assert [x.source for x in r] == ["uex", "scm"]
    assert time.time() - t < 0.7                              # 两个各 0.4 秒，同时查


def test_tooltip_anchor_tolerates_missing_char():
    from sc_mining.trade import console as C
    from sc_mining.trade.ocr import OcrToken
    T = lambda text, x, y: OcrToken(text, 90, (x, y, max(20, len(text) * 9), 18))
    toks = [T('CQ7步枪', 1368, 367), T('CQ7Rifle', 1368, 391), T('体：13000uSCU', 1368, 414),
            T('1网灵领童第卖枪', 1368, 900), T("Artington-Warchpoint' Rille", 1368, 924)]
    name, sure = C.tooltip_pick(toks, (1400, 950))           # 鼠标离下面的对比列表更近，也要选说明框标题
    assert name == ('CQ7步枪', 'CQ7Rifle') and sure


def test_displayinfo_reads_only_needed_lines_after_first_time(monkeypatch):
    """右上角：第一次整块认、记下要用的几行在哪；之后只认这几行；认出来对不上就重新整块认"""
    from PIL import Image
    from sc_mining import displayinfo as D
    from sc_mining.trade.ocr import OcrToken
    D._layout.update(at=0.0, boxes=None)
    T = lambda text, x, y: OcrToken(text, 90, (x, y, len(text) * 9, 20))
    lines = ["Zone: SolarSystem_862949775749 Pos: 22462326.4853km 37186368.6338km 744.0843km",
             "Zone: Root Pos: 22462326.4853km 37186368.6338km 744.0843km",
             "Current player location : Hospital Stanton4 NewBabbage (LZ: Stanton4 NewBabbage)"]
    full_calls, line_calls = [], []
    toks = [T("纯音乐，请欣赏", 10, 60)] + [T(t, 1740 - len(t) * 9, 20 + 40 * i) for i, t in enumerate(lines)]
    monkeypatch.setattr("sc_mining.trade.ocr.recognize", lambda img, **k: full_calls.append(img.size) or toks)
    answers = iter(lines + lines + ["乱码"] * 3)
    monkeypatch.setattr("sc_mining.trade.ocr.read_line", lambda img: line_calls.append(img.size) or (next(answers), 0.9))
    img = Image.new("RGB", (2560, 1440))
    assert D.read(img)["global"] and len(full_calls) == 1 and not line_calls
    assert len(D._layout["boxes"]) == 3
    # 和 Root 同一行左边的「纯音乐」不算进 Root 那行
    assert all(b[0] > 100 for b in D._layout["boxes"])
    for _ in range(2):
        info = D.read(img)
        assert info["global"] and "NewBabbage" in info["location"]
    assert len(full_calls) == 1 and len(line_calls) == 6       # 后两次只认了那 3 行
    D.read(img)                                               # 认出来对不上：马上重新整块认
    assert len(full_calls) == 2
    D._layout.update(at=0.0, boxes=None)


def test_perf_log_line_format():
    from sc_mining import perfmon
    m = perfmon.Monitor()
    m.prev = {"天枢": (10.0, 200.0, 300.0), "窗口(Edge)": (5.0, 150.0, 120.0)}
    perfmon._take_ocr()
    perfmon.note_ocr(0.25)
    line = m.line(0, {"天枢": (10.6, 210.0, 320.0), "窗口(Edge)": (5.06, 150.0, 120.0)}, 60.0)
    assert "天枢 CPU" in line and "内存 210MB（提交 320MB）" in line and "窗口(Edge)" in line and "识别" in line
    assert perfmon._tree(1, {1: [2, 3], 3: [4]}) == {1, 2, 3, 4}


def test_displayinfo_local_cross_checked_with_campos():
    """星球局部坐标和 CamPos Planet Zone（同一个位置，单位米）两行对得上才算可靠"""
    from sc_mining.displayinfo import parse
    base = ["Zone: OOC_Stanton_4_Microtech Pos: 520.9152km 419.2893km 744.0843km",
            "Zone: SolarSystem_862949775749 Pos: 22462326.4853km 37186368.6338km 744.0843km",
            "Zone: Root Pos: 22462326.4853km 37186368.6338km 744.0843km"]
    ok = parse(base + ["CamP0s P1anet Zone: 520915.218755 419289.333861 744084.256923"])
    assert ok["local_ok"] is True and ok["campos"][0] == 520915.218755
    bad = parse(base + ["CamPos Planet Zone: 520915.218755 449289.333861 744084.256923"])   # 认错一位
    assert bad["local_ok"] is False
    assert parse(base)["local_ok"] is None
    # 实测：快速读取时 5 被认成 s（52091s），数字里的 s/o/l 换回来
    fixed = parse(base + [" CamP06 Planet Zone: 52091s.218755 419289.333861 744084.256923"])
    assert fixed["local_ok"] is True


def test_nav_bearing_is_steady_when_standing_still():
    """站着不动：右上角那行有时认不出，位置也不在「游戏给的」和「推算的」之间来回跳，显示的方位不变"""
    from sc_mining import navigate as n
    from sc_mining.app import services as S
    if not n.CACHE.exists():
        import pytest
        pytest.skip("没有星图数据")
    n._remember_orig, n._remember = n._remember, (lambda *a, **k: None)
    n._offsets.clear()
    try:
        g = (22462326485.3, 37186368633.8, 744084.3)
        ref = n.locate(g, when=1792500000.0)
        game = (ref["x"] + 0.8, ref["y"] - 0.6, ref["z"])                  # 推算和游戏差将近 1 km
        target = {"b": ref["body"], "x": game[0] + 2.0, "y": game[1] + 1.2, "z": game[2], "n": "目标"}
        steady = S._Steady()
        shown = set()
        for i in range(12):
            local = None if i % 3 == 2 else game                           # 每 3 次有 1 次没认出那一行
            h = n.locate(g, when=1792500000.0, local=local, zone="OOC Stanton 4 Microtech", local_ok=True if local else None)
            shown.add(n.deg_text(S._nav_view(h, target, n.load(), steady)["bearing"]))
        assert len(shown) == 1
    finally:
        n._remember = n._remember_orig
        n._offsets.clear()


def test_bearing_text_and_deadband():
    from sc_mining import navigate as n
    from sc_mining.app import services as S
    assert n.deg_text(359.6) == "000" and n.deg_text(5.2) == "005"
    st = S._Steady()
    assert st(10.0) == 10.0 and st(11.5) == 10.0 and st(358.9) == 358.9 and st(0.5) == 358.9 and st(1.2) == 1.2


def test_anti_afk_removed(monkeypatch, tmp_path):
    """2026-10-30 老大定删掉防挂机：老设置文件里开着防挂机，读出来也没有这几项；只开防挂机不再启动辅助进程"""
    import json
    from sc_mining import settings, helpers
    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    settings.FILE.write_text(json.dumps({"agreed": True, "keys_v5": True, "anti_afk": True, "afk_seconds": 500, "afk_v3": True}), encoding="utf-8")
    c = settings.load()
    assert not any(k in c for k in ("anti_afk", "afk_seconds", "afk_v3", "afk_v4"))
    assert "anti_afk" not in json.loads(settings.FILE.read_text(encoding="utf-8"))   # 文件里也清掉了（回滚 1.1.0 不会自动开）
    assert not hasattr(helpers, "AntiAfk")
    monkeypatch.setattr(helpers.S, "WIN", True)
    monkeypatch.setattr(helpers, "stop_helpers", lambda: None)
    assert helpers.start() is False                       # 自动跑没开：不起辅助进程


def test_nav_uses_display_info_waypoints_use_showlocation():
    """导航实时方位只读右上角调试信息（不往游戏里打字）；自定义路标只用 /showlocation（2026-10-23 用户要求）"""
    import inspect
    from sc_mining.app import services
    run = inspect.getsource(services._Nav._run)
    assert "showlocation(" not in run and "showloc import" not in run        # 实时导航：读右上角，不往游戏里打字（读不到时只接玩家自己输的 /showlocation）
    src = inspect.getsource(services.mark_here) + inspect.getsource(services._save_here)
    assert "showlocation" in src and "_pos.reader" not in src and "use_offset=False" in src


def test_mix_plan_matches_guide_example():
    """攻略图里的例子：S1 绿柱石 0.14 SCU，860 的低料 + 967 的高料，按 902 混 → 低 0.085 + 高 0.055，高料占 39%"""
    from sc_mining import crafting as c
    r = c.mix_plan(0.14, 900, [(860, 1), (967, 1)])
    assert r["ok"] and r["goal"] == 902
    assert [(p["q"], p["use"]) for p in r["plan"]] == [(860, 0.085), (967, 0.055)]
    assert r["avg"] >= 902 and round(r["high"] / 0.14, 2) == 0.39
    # 到不了、料不够、合箱
    assert not c.mix_plan(0.14, 980, [(860, 1), (967, 1)])["ok"]
    assert "材料不足" in c.mix_plan(2, 900, [(860, 1)])["msg"]
    m = c.mix_plan(0, 0, [(860, 1.0), (967, 0.2), (860, 0.5)])
    assert m["ok"] and abs(m["avg"] - (860 * 1.5 + 967 * 0.2) / 1.7) < 1e-9 and len(m["plan"]) == 2


def test_mix_targets_from_blueprint():
    from sc_mining import crafting as c
    bp = next((b for b in c.blueprints() if b["n"] == "QuadraCell"), None)
    if bp is None:
        import pytest
        pytest.skip("没有制造数据")
    beryl = next(m for m in c.mix_targets(bp) if m["material"] == "Beryl")
    assert beryl["scu"] == 0.14 and beryl["steps"][-1]["q"] == 900


def test_blas_threads_limited():
    """numpy 的数学库只开 1 个线程（不然 32 线程的电脑一加载就预留 740MB 内存）"""
    import os
    import sc_mining  # noqa: F401
    assert os.environ.get("OPENBLAS_NUM_THREADS") == "1"


def test_ship_signature_match():
    """截面对得上：短剑正对时的截面应该把短剑排第一；离谱的数对不上任何船"""
    from sc_mining import shipsig
    rows = shipsig.match(1956)
    assert rows and "Gladius" in rows[0]["name"]
    assert shipsig.match(10) == []
    # 电磁远超上限的排除掉
    assert all(r["em_max"] * shipsig.SLACK >= 10 ** 6 for r in shipsig.match(1956, em=10 ** 6))


def test_update_log_reaches_window(monkeypatch):
    """更新数据时几个源并行下载：各线程的输出都要进窗口的更新记录"""
    import sys
    from sc_mining.app import bus
    import sc_mining.run as run
    from sc_mining import localization, uex, build_crafting, navigate, shops, loot
    logs = []
    monkeypatch.setattr(bus, "publish", lambda kind, msg: logs.append((kind, msg)))
    for m, n in ((localization, "update"), (uex, "refresh"), (build_crafting, "update"),
                 (navigate, "update"), (shops, "update"), (loot, "update")):
        monkeypatch.setattr(m, n, lambda name=m.__name__: print(f"{name} ok"))
    from sc_mining import data_pack
    monkeypatch.setattr(data_pack, "update", lambda progress=print: None)   # 不联网：当作数据包下不到，走各数据网站
    old = sys.stdout
    bus.install_router()
    try:
        bus.run_task("update", run.update, title="更新数据").join()
    finally:
        sys.stdout = old
    lines = [m["line"] for k, m in logs if k == "log"]
    assert sum("ok" in l for l in lines) == 6 and lines[-1] == "全部更新完成"


def test_space_waypoint(monkeypatch, tmp_path):
    """太空里用当前位置新建路标：记星系坐标；导航给直线距离、先跳到哪、对准哪个标记"""
    import time, math
    from sc_mining import navigate as n
    from sc_mining.app import services as S
    data = n.load()
    if not data.get("points"):
        pytest.skip("没有星图数据")
    monkeypatch.setattr(n, "WAYPOINTS", tmp_path / "wp.json")
    # 尼克斯星系里一个拉格朗日点旁边 20 km 的太空（不在任何星球附近）
    lp = next(p for p in data["points"] if p["sys"] == "Nyx" and p["t"] in ("Lagrange Point", "Jumppoint"))
    g = (lp["x"] + 20_000, lp["y"], lp["z"])                       # 米
    assert n.system_of(g, data) == "Nyx"
    # 窗口里点「用当前位置新建」：只认 /showlocation 的坐标——等剪贴板出现新坐标，不在星球上 → 太空路标
    clip = {"t": "随便什么"}
    monkeypatch.setattr(n, "read_clipboard", lambda: clip["t"])
    patch_services(monkeypatch, "_hud", lambda: type("H", (), {"set": lambda *a: None, "clear": lambda *a: None})())
    monkeypatch.setattr(__import__("sc_mining.paths", fromlist=["log"]), "log", lambda name: tmp_path / name)   # 真的写记录（写到临时目录），以前把记录函数换掉，没发现它和导航记录重名、一调用就报错
    r = S.waypoint_add(name="气体云矿点", here=True)
    assert r["pending"] and "/showlocation" in r["message"]
    time.sleep(0.3)
    clip["t"] = f"Coordinates: x:{g[0]} y:{g[1]} z:{g[2]}"
    for _ in range(40):
        if any(w["n"] == "气体云矿点" for w in n.waypoints()):
            break
        time.sleep(0.1)
    rows = S.waypoints()
    w = next(r for r in rows if r["name"] == "气体云矿点")
    assert w["space"] and w["system"] == "Nyx"
    # 搜得到，路线给最近的参照点
    hits, _ = n.search("气体云矿点")
    p = hits[0]
    assert n.is_space(p)
    plan = S.nav_plan(S._place_row(p)["key"])
    assert plan["space"] and plan["routes"][0]["direct"] < 25
    # 就在原地：到了
    assert n.space_guide(g, p, data)["arrived"]
    # 从参照点另一侧 300 km 飞过来：直线距离对、对准参照点（目标就在它旁边）夹角很小
    far = (lp["x"] - 300_000, lp["y"], lp["z"])
    s = n.space_guide(far, p, data)
    assert abs(s["direct"] - 320) < 0.5 and s["aim"]["angle"] < 5
    # 在别的星系：提示先跳过去
    other = next(b for b in data["bodies"].values() if b["sys"] != "Nyx")
    assert not n.space_guide((other["x"], other["y"], other["z"]), p, data)["same_system"]
    S._HERE["name"] = None


def test_camdir_steering():
    """右上角 CamDir（俯仰 横滚 偏航）→ 机头要怎么转。用 2026-10-23 微科星轨道的真实截图核对过约定：
    CamDir 23 9 -142、Root Pos (22461632.7352, 37186362.6645, 799.5096) km，画面里地平线在中心略下方"""
    import math
    from sc_mining.displayinfo import parse
    from sc_mining import navigate as n
    assert parse(["CamDir: 23 9 -142 FOV: 70 Focal: 3.00"])["camdir"] == (23, 9, -142)
    assert parse(["CamD1r 12 -1 72 F0V: 60"])["camdir"] == (12, -1, 72)      # OCR 认错的字母也行
    assert parse(["CamDir: 23 9 -1420 FOV: 70"])["camdir"] is None           # 超出范围 = 认错数字
    # 基本方向：镜头不转时朝 +y
    assert n.steer_text(n.steer((0, 0, 0), (0, 0, 0), (0, 1000, 0))).startswith("✅")
    s = n.steer((0, 0, 0), (0, 0, 0), (1000, 1000, 0))
    assert round(s["turn"]) == 45 and abs(s["pitch"]) < 1 and "右转 45°" in n.steer_text(s)
    s = n.steer((0, 0, 0), (0, 0, 0), (0, 1000, -1000))
    assert round(s["pitch"]) == -45 and "低头 45°" in n.steer_text(s)
    assert "掉头" in n.steer_text(n.steer((0, 0, 0), (0, 0, 0), (-10, -1000, 0)))
    # 真实截图：微科星的地平线应该在机头下方约 3°（画面中心略下方）
    data = n.load()
    if "Microtech" not in data.get("bodies", {}):
        pytest.skip("没有星图数据")
    b = data["bodies"]["Microtech"]
    g = (22461632.7352e3, 37186362.6645e3, 799.5096e3)
    s = n.steer(g, (23, 9, -142), (b["x"], b["y"], b["z"]))
    limb = math.degrees(math.asin(b["r"] / math.dist(g, (b["x"], b["y"], b["z"]))))
    assert -8 < s["pitch"] + limb < 2


def test_mark_here_hotkey(monkeypatch, tmp_path):
    """游戏里按 F7：替你打 /showlocation，用剪贴板里的坐标记路标（太空里记星系坐标）；不读右上角"""
    from sc_mining import navigate as n, showloc
    from sc_mining.app import services as S
    data = n.load()
    if not data.get("points"):
        pytest.skip("没有星图数据")
    monkeypatch.setattr(n, "WAYPOINTS", tmp_path / "wp.json")
    lp = next(p for p in data["points"] if p["sys"] == "Stanton" and p["t"] == "Lagrange Point")
    g = (lp["x"] + 5_000, lp["y"], lp["z"])
    monkeypatch.setattr(showloc, "showlocation", lambda log=None: (g, "Coordinates: ..."))
    monkeypatch.setattr(S._pos.reader, "poll", lambda force=False: (_ for _ in ()).throw(AssertionError("不该读右上角")))
    monkeypatch.setattr(__import__("sc_mining.paths", fromlist=["log"]), "log", lambda name: tmp_path / name)   # 真的写记录（写到临时目录），以前把记录函数换掉，没发现它和导航记录重名、一调用就报错
    shown = {}
    class H:
        def set(self, k, v, *rich): shown[k] = v
        def clear(self, k): shown.pop(k, None)
    patch_services(monkeypatch, "_hud", lambda: H())
    monkeypatch.setattr(S.threading, "Timer", lambda *a, **k: type("T", (), {"start": lambda self: None})())
    out = S.mark_here()
    assert "error" not in out and "斯坦顿星系" in out["where"] and "已保存" in shown["路标"]
    assert "已记下" in (tmp_path / "nav_log.txt").read_text(encoding="utf-8")       # 记录真的写进去了
    wp = n.waypoints()[-1]
    assert n.is_space(wp) and wp["n"] == out["name"]
    # 点过「用当前位置新建」再按 F7：用那里填的名字
    S._HERE.update(name="我的矿点", until=__import__("time").time() + 30)
    assert S.mark_here()["name"] == "我的矿点" and S._HERE["name"] is None
    # 没读到坐标：悬浮窗说原因，不记
    monkeypatch.setattr(showloc, "showlocation", lambda log=None: (None, "游戏窗口不在最前面"))
    assert "error" in S.mark_here() and "不在最前面" in shown["路标"]


def test_parse_showlocation_clip():
    from sc_mining.navigate import parse_clip
    assert parse_clip("Coordinates: x:-18930539540.1 y:-2610158765.2 z:295000.3") == (-18930539540.1, -2610158765.2, 295000.3)
    assert parse_clip("hello") is None and parse_clip("") is None


def test_camdir_sign_filter():
    """CamDir 漏了负号（-142 认成 142）：这次不用；转过 ±180° 是真的转了，照用"""
    from sc_mining.app.services import _CamFilter
    f = _CamFilter()
    assert f.check((23, 9, -142)) == (23, 9, -142)
    assert f.check((23, 9, 142)) is None
    assert f.check((24, 9, -140)) == (24, 9, -140)
    f = _CamFilter()
    assert f.check((0, 0, 178)) and f.check((0, 0, -178)) == (0, 0, -178)


def test_export_logs(monkeypatch, tmp_path):
    """导出日志：日志 + 设置 + 系统说明打包到桌面；窗口文件夹（浏览器数据）不打进去"""
    import zipfile
    from sc_mining import paths
    from sc_mining.app import services as S
    user = tmp_path / "userdata"
    (user / "logs").mkdir(parents=True)
    (user / "logs" / "app_log.txt").write_text("启动", encoding="utf-8")
    (user / "logs" / "nav_log.txt").write_text("导航", encoding="utf-8")
    (user / "settings.json").write_text("{}", encoding="utf-8")
    (user / "window").mkdir()
    (user / "window" / "Cookies").write_text("隐私", encoding="utf-8")
    monkeypatch.setattr(paths, "USER", user)
    monkeypatch.setattr(paths, "LOGS", user / "logs")
    patch_services(monkeypatch, "WIN", False)
    patch_services(monkeypatch, "_desktop", lambda: tmp_path)
    r = S.export_logs()
    names = zipfile.ZipFile(r["path"]).namelist()
    assert {"logs/app_log.txt", "logs/nav_log.txt", "settings.json", "系统信息.txt"} <= set(names)
    assert not any("window" in n or "Cookies" in n for n in names)
    info = zipfile.ZipFile(r["path"]).read("系统信息.txt").decode("utf-8")
    assert "AT 版本" in info and "Python" in info


def test_live_scan_resumes_after_restart(monkeypatch, tmp_path):
    """原矿扫描开着时天枢重启 / 升级：重启后自动接着扫（以前重启后就关了，信号识别也跟着没了）"""
    from sc_mining import settings
    from sc_mining.app import services as S
    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    settings.update(agreed=True)
    started = []
    monkeypatch.setattr(S._live, "start", lambda: started.append(1))
    monkeypatch.setattr(S._live, "stop", lambda: None)
    for name in ("_hover", "_pos", "_logwatch"):
        monkeypatch.setattr(getattr(S, name), "start", lambda: None)
    patch_services(monkeypatch, "_online_loop", lambda: None)          # 测试里不联网检查更新
    S.live_start()
    assert settings.load()["live_on"]
    started.clear()
    S.start_background()                     # 模拟重启
    assert started == [1]
    S.live_stop()
    started.clear()
    S.start_background()
    assert not started and not settings.load()["live_on"]



def test_where_now_ground_or_space(monkeypatch):
    """信号表外的值要知道玩家在地面还是太空：小行星带 → 太空；贴着星球 → 地面；高空 → 太空"""
    import time
    from sc_mining.app import services as sv
    from sc_mining import navigate
    patch_services(monkeypatch, "_WHERE", {"t": 0.0, "v": None, "tried": 0.0})
    monkeypatch.setattr(sv._pos, "latest", (time.time(), (1.0, 2.0, 3.0), {"location": "AsteroidCluster MiningBase Stanton2"}))
    assert sv._where_now() == "space"
    patch_services(monkeypatch, "_WHERE", {"t": 0.0, "v": None, "tried": 0.0})
    monkeypatch.setattr(sv._pos, "latest", (time.time(), (1.0, 2.0, 3.0), {"location": "Planet Clio"}))
    monkeypatch.setattr(navigate, "locate", lambda *a, **k: {"inside": True, "height_m": 2700})
    assert sv._where_now() == "ground"
    patch_services(monkeypatch, "_WHERE", {"t": 0.0, "v": None, "tried": 0.0})
    monkeypatch.setattr(navigate, "locate", lambda *a, **k: {"inside": True, "height_m": 400_000})
    assert sv._where_now() == "space"


def test_wikelo_detail_sticky_and_names_clean():
    """维科洛兑换：右边详情跟着页面滚动；汉化名末尾的反斜杠去掉"""
    from sc_mining import paths
    css = (paths.CODE / "app" / "web" / "style.css").read_text(encoding="utf-8")
    js = (paths.CODE / "app" / "web" / "app.js").read_text(encoding="utf-8")
    assert ".split > .sticky { position: sticky" in css and 'id="wout" class="sticky"' in js
    from sc_mining import wikelo
    wikelo.load.cache_clear()
    for c in wikelo.load():
        for r in c["req"]:
            assert not r["z"].endswith("\\"), r


def test_wikelo_materials_all_have_source(monkeypatch):
    """每样维科洛材料都要有「去哪弄」：商店 / 挖矿 / 特殊说明 / 开箱掉落（用户 2026-10-23：不知道就查，补齐为止）"""
    import pytest
    from sc_mining import wikelo, loot
    from sc_mining.trade.console import material_source
    wikelo.load.cache_clear()
    cs = wikelo.load()
    if not cs or not loot.load_index(False):
        pytest.skip("没有维科洛 / 掉落数据")
    names = {r["n"] for c in cs for r in c["req"]}
    missing = [n for n in sorted(names) if not material_source(n)]
    assert not missing, missing


def test_craft_blueprint_dictionary():
    """制造页的蓝图字典：按类别 / 子类 / 部位 / 厂商筛选、分页，筛选项带数量"""
    import pytest
    from sc_mining import crafting
    if not crafting.blueprints():
        pytest.skip("没有制造数据")
    from sc_mining.app.services import craft_browse, craft_detail
    r = craft_browse()
    assert r["total"] == len(crafting.blueprints()) and len(r["rows"]) == 60
    assert sum(c["count"] for c in r["cats"]) == r["total"] and any(c["label"] == "护甲" for c in r["cats"])
    a = craft_browse(cat="fpsgear/armour")
    assert any(p["key"] == "头盔" for p in a["parts"]) and any(x["label"] == "战斗" for x in a["subs"])
    h = craft_browse(cat="fpsgear/armour", part="头盔")
    assert h["total"] == next(p["count"] for p in a["parts"] if p["key"] == "头盔")
    assert all("头盔" in x["tags"] for x in h["rows"])
    more = craft_browse(cat="fpsgear/armour", offset=60)
    assert more["rows"] and more["rows"][0]["key"] != a["rows"][0]["key"]
    s2 = craft_browse(cat="vehiclegear/powerplant", sub="size2")
    assert s2["total"] and all("S2" in x["tags"].split(" · ") for x in s2["rows"])
    # 点一份能看详情
    assert "text" in craft_detail(h["rows"][0]["key"])


def test_craft_same_name_blueprints_distinct():
    """同名两份配方（比如 Main Powerplant）：列表编号不同，点开看到各自的材料（Codex 二审 2026-10-23 发现的 bug）"""
    import pytest
    from collections import Counter
    from sc_mining import crafting
    from sc_mining.app.services import craft_browse, craft_detail
    dup = next((n for n, c in Counter(b["n"] for b in crafting.blueprints()).items() if c > 1), None)
    if not dup:
        pytest.skip("数据里没有同名蓝图")
    rows = [r for r in craft_browse(q=dup)["rows"] if r["key"].startswith(dup)]
    keys = [r["key"] for r in rows]
    assert len(set(keys)) == len(keys) >= 2 and all("配方" in r["tags"] for r in rows)
    texts = [craft_detail(k)["text"] for k in keys]
    assert len(set(texts)) == len(texts)
    assert [craft_detail(k)["key"] for k in keys] == keys
    # 以前存的目标只有名字：取同名第一份，不报错
    assert crafting.by_key(dup) is crafting.by_key(keys[0])


def _live_run(monkeypatch, tmp_path, frames, seconds=0.8, stale=None, static=False, ev=None, sig=None, front=None,
              grabs=None):
    """跑一小段实时读屏：frames = 每次 analyse 依次返回的 Scan（None = 画面里没有面板），返回推送的消息和悬浮窗操作。
    front：游戏在不在最前面（默认判断不了 = 照常认，不看真电脑的前台窗口）；grabs：记下每次截图的时间"""
    import threading, time as _t
    from PIL import Image
    from sc_mining import screen, signals, paths
    from sc_mining.parse import Scan
    from sc_mining.app import services, bus
    monkeypatch.setattr(paths, "log", lambda name: tmp_path / name)
    monkeypatch.setattr(paths, "shots", lambda name: tmp_path)
    n = {"i": 0}
    imgs = [Image.new("RGB", (320, 180), (20 + 40 * (k % 5), 20, 20)) for k in range(60)]   # 每帧画面都明显不同：不省电跳过

    def grab():
        if grabs is not None:
            grabs.append(_t.time())
        return imgs[0] if static else imgs[n["i"] % len(imgs)]

    def analyse(_):
        s = frames[min(n["i"], len(frames) - 1)]
        n["i"] += 1
        return (s or Scan(), ({}, None, None))
    hud = []
    patch_services(monkeypatch, "_hud", lambda: type("H", (), {"set": lambda self, k, v, *rich: hud.append(("set", k)),
                                                                   "clear": lambda self, k: hud.append(("clear", k))})())
    monkeypatch.setattr(screen, "grab", grab)
    monkeypatch.setattr(screen, "analyse", analyse)
    monkeypatch.setattr(screen, "INTERVAL", 0.01)
    monkeypatch.setattr(signals, "find_signatures", sig or (lambda im: []))
    patch_services(monkeypatch, "_game_front", front or (lambda: None))
    live = services._Live()
    if stale is not None:
        monkeypatch.setattr(live, "STALE_SECONDS", stale)
    q = bus.subscribe()
    while not q.empty():                              # 总线会补发之前保存的最后一条结果：先丢掉，只看这次跑出来的
        q.get_nowait()
    ev = ev or threading.Event()
    try:
        th = threading.Thread(target=live._run, args=(ev,), daemon=True)
        th.start()
        _t.sleep(seconds)
        ev.set()
        th.join(2)
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        return msgs, hud
    finally:
        bus.unsubscribe(q)


def _rock(mass, res, instab, scu, comp):
    from sc_mining.parse import Scan
    return Scan(rock=None, mass=mass, resistance=res, instability=instab, total_scu=scu, composition=comp)


def test_vote_needs_stable_composition_and_same_rock_checks_resistance():
    """成分没读稳（两帧百分比对不上）不算稳定；质量差不多但抗性不同的是两块石头（Codex 审查建议 2026-10-23）"""
    from sc_mining import screen
    a = _rock(10000, 20, 5.0, 10.0, [("Copper", 40.0, 500), ("Inert Materials", 60.0, 0)])
    b = _rock(10000, 20, 5.0, 10.0, [("Copper", 45.0, 500), ("Inert Materials", 55.0, 0)])
    assert screen.vote([a, a])[1] and not screen.vote([a, b])[1]
    c = _rock(10000, 20, 5.0, 11.0, a.composition)                  # 总 SCU 也要读稳
    assert not screen.vote([a, c])[1]
    assert screen._same_rock(a, a) and not screen._same_rock(a, _rock(10050, 45, 5.0, 10.0, a.composition))


def test_live_rebuilds_queue_and_expires_old_result(monkeypatch, tmp_path):
    """目标丢了（连续几帧没面板）投票队列重建，不把下一块石头混进来；面板消失太久，悬浮窗清掉、窗口标过期
    （画面静止、省电跳过识别时也要过期）"""
    a = _rock(10000, 20, 5.0, 10.0, [("Copper", 40.0, 500), ("Inert Materials", 60.0, 0)])
    msgs, hud = _live_run(monkeypatch, tmp_path, [a, a, a] + [None] * 200, seconds=0.8, stale=0.2)
    scans = [m["data"] for m in msgs if m["kind"] == "scan"]
    assert scans and not scans[0].get("stale") and scans[-1].get("stale")      # 先出结果，后来同一条结果带「已过期」再发
    assert ("clear", "扫描") in hud and ("clear", "矿袋") in hud
    from sc_mining.app import bus
    q = bus.subscribe()                                                           # 窗口刷新/重连：补发的也是过期的那条
    try:
        replay = [m["data"] for m in iter(lambda: q.get_nowait() if not q.empty() else None, None) if m["kind"] == "scan"]
        assert replay and replay[-1].get("stale")
    finally:
        bus.unsubscribe(q)


def test_live_republishes_corrected_total_scu(monkeypatch, tmp_path):
    """同一块石头，总 SCU 一开始读错、后来读对：要重新发布（以前只看质量/抗性/不稳定性，修正后的数推不出去）"""
    comp = [("Copper", 40.0, 500), ("Inert Materials", 60.0, 0)]
    wrong, right = _rock(10000, 20, 5.0, 16.0, comp), _rock(10000, 20, 5.0, 10.0, comp)
    msgs, _ = _live_run(monkeypatch, tmp_path, [wrong, wrong] + [right] * 50, seconds=0.6)
    scans = [m["data"] for m in msgs if m["kind"] == "scan"]
    assert len(scans) >= 2 and abs(sum(x["scu"] for x in scans[-1]["minerals"]) - 4.0) < 0.01


def test_live_session_isolation(monkeypatch, tmp_path):
    """快速停了又开：旧会话的停止开关已经按下，就算线程还没退出也不会再干活（日志写到临时目录）"""
    import threading
    from sc_mining import paths
    from sc_mining.app import services
    monkeypatch.setattr(paths, "log", lambda name: tmp_path / name)
    monkeypatch.setattr(paths, "shots", lambda name: tmp_path)
    live = services._Live()
    old = threading.Event()
    old.set()
    live.stop_ev = threading.Event()                  # 新会话的开关（没按下）
    errors = []
    t = threading.Thread(target=live._run, args=(old,), daemon=True)
    hook = threading.excepthook
    threading.excepthook = lambda a: errors.append(a.exc_value)
    try:
        t.start()
        t.join(2)
    finally:
        threading.excepthook = hook
    assert not t.is_alive() and not errors            # 旧会话看自己的开关，立刻正常退出


def test_live_stop_during_compute_publishes_nothing(monkeypatch, tmp_path):
    """算破碎方案的时候用户按了停止：算完不能再把旧结果推到窗口和悬浮窗（Codex 复审 2026-10-23）"""
    import threading
    from sc_mining.app import services
    real = services.scan_view
    ev = threading.Event()

    def slow_view(scan, bag):
        ev.set()                                      # 模拟：算到一半用户点了停止
        return real(scan, bag)
    patch_services(monkeypatch, "scan_view", slow_view)
    a = _rock(10000, 20, 5.0, 10.0, [("Copper", 40.0, 500), ("Inert Materials", 60.0, 0)])
    msgs, hud = _live_run(monkeypatch, tmp_path, [a] * 50, seconds=0.5, ev=ev)
    assert not [m for m in msgs if m["kind"] == "scan"] and ("set", "扫描") not in hud


def test_live_saves_frames_when_panel_unreadable(monkeypatch, tmp_path):
    """看得到扫描面板却一直读不全 / 读不稳：自动留一张图、日志记一行 MISS（2026-10-23 用户说「部分矿物扫描失败」，当时没有图可查）"""
    import time as _t
    half = _rock(None, None, None, 10.0, [("Copper", 40.0, 500), ("Inert Materials", 60.0, 0)])   # 上半截（质量那几行）没读到
    msgs, _ = _live_run(monkeypatch, tmp_path, [half] * 200, seconds=0.6)
    _t.sleep(0.3)                                                                # 存图在后台线程
    log = (tmp_path / "live_log.txt").read_text(encoding="utf-8")
    assert "MISS 读不全" in log and list(tmp_path.glob("*.png"))
    assert log.count("MISS") == 1                                                # 30 秒内只留一张
    assert not [m for m in msgs if m["kind"] == "scan"]


def test_live_saves_frame_when_votes_never_agree(monkeypatch, tmp_path):
    import time as _t
    a = _rock(10000, 20, 5.0, 10.0, [("Copper", 40.0, 500), ("Inert Materials", 60.0, 0)])
    b = _rock(10000, 20, 5.0, 10.0, [("Copper", 45.0, 500), ("Inert Materials", 55.0, 0)])
    c = _rock(10000, 20, 5.0, 10.0, [("Copper", 30.0, 500), ("Inert Materials", 70.0, 0)])
    d = _rock(10000, 20, 5.0, 10.0, [("Copper", 35.0, 500), ("Inert Materials", 65.0, 0)])
    e = _rock(10000, 20, 5.0, 10.0, [("Copper", 25.0, 500), ("Inert Materials", 75.0, 0)])
    msgs, _ = _live_run(monkeypatch, tmp_path, [a, b, c, d, e, a, b, c, d, e] + [None] * 200, seconds=0.6)
    _t.sleep(0.3)
    log = (tmp_path / "live_log.txt").read_text(encoding="utf-8")
    assert "MISS 读不稳" in log or [m for m in msgs if m["kind"] == "scan"], log


def test_live_pauses_when_game_not_in_front(monkeypatch, tmp_path):
    """游戏不在最前面（切到聊天、浏览器）：不截图、不认面板和信号，窗口显示已暂停；回到游戏马上接着认，
    暂停的这段不算面板消失（结果不过期、悬浮窗不清）（2026-10-23 用户同意：聊天窗口里的字被当成面板、数字被当成信号）"""
    import time as _t
    a = _rock(10000, 20, 5.0, 10.0, [("Copper", 40.0, 500), ("Inert Materials", 60.0, 0)])
    st = {"t0": None}

    def front():
        now = _t.time()
        st["t0"] = st["t0"] or now
        return not (0.4 <= now - st["t0"] < 1.4)                    # 0.4~1.4 秒切到了别的窗口
    grabs = []
    msgs, hud = _live_run(monkeypatch, tmp_path, [a] * 5000, seconds=2.0, stale=0.3, front=front, grabs=grabs)
    t0 = st["t0"]
    assert grabs and not [g for g in grabs if 0.55 < g - t0 < 1.3]  # 暂停时一张都不截、不认
    assert [g for g in grabs if g - t0 > 1.45]                      # 回到游戏接着认
    live = [m["data"] for m in msgs if m["kind"] == "live"]
    assert {"running": True, "paused": True} in live and live[-1] == {"running": True, "paused": False}, live
    scans = [m["data"] for m in msgs if m["kind"] == "scan"]
    assert scans and not any(x.get("stale") for x in scans) and ("clear", "扫描") not in hud
    log = (tmp_path / "live_log.txt").read_text(encoding="utf-8")
    assert "PAUSE 游戏不在最前面" in log and "RESUME 回到游戏" in log


def test_game_front_unknown_does_not_pause(monkeypatch):
    """判断不了游戏在不在最前面（不是 Windows、这一刻没有前台窗口、出错）返回 None：采矿助手照常认，不能因此停掉"""
    from sc_mining import showloc
    if not showloc.WIN:
        assert showloc.game_front() is None
        return
    fake = type("U32", (), {})()
    fake.GetForegroundWindow = lambda: 0
    monkeypatch.setattr(showloc, "_u32", fake)
    monkeypatch.setattr(showloc, "_fg_cache", {"hwnd": None, "ok": False})
    assert showloc.game_front() is None and showloc.game_foreground() is False
    fake.GetForegroundWindow = lambda: 1234
    monkeypatch.setattr(showloc, "_is_game_window", lambda h: False)
    monkeypatch.setattr(showloc, "_exe_of", lambda h: "claude.exe")
    assert showloc.game_front() is False
    monkeypatch.setattr(showloc, "_fg_cache", {"hwnd": None, "ok": False})
    monkeypatch.setattr(showloc, "_exe_of", lambda h: "starcitizen.exe")
    assert showloc.game_front() is True

    def boom(h):
        raise OSError("读不到")
    monkeypatch.setattr(showloc, "_fg_cache", {"hwnd": None, "ok": False})
    monkeypatch.setattr(showloc, "_is_game_window", boom)
    assert showloc.game_front() is None


def test_vote_name_and_percent_voted_together():
    """矿名和百分比要一起投票：Copper 40,40 / Copper 60 / Gold 60,60 不能拼出只出现过一次的「Copper 60%」"""
    from sc_mining import screen
    rows = [("Copper", 40.0), ("Copper", 40.0), ("Copper", 60.0), ("Gold", 60.0), ("Gold", 60.0)]
    frames = [_rock(10000, 20, 5.0, 10.0, [(n, p, 500), ("Inert Materials", 100 - p, 0)]) for n, p in rows]
    best, stable = screen.vote(frames)
    assert best.composition[0][:2] in (("Copper", 40.0), ("Gold", 60.0)) and best.composition[0][:2] != ("Copper", 60.0)


def test_vote_tolerates_last_digit_jitter_with_real_readings():
    """末位抖动（质量 12431 / 12437、抗性 20 / 21、百分比 45.22 / 45.27）也要投出结果（2026-10-24 外部补丁）；
    结果只用实际读到过的数，不取平均——抗性 20.5%、百分比 45.245 面板上没有（1.6.43）"""
    from sc_mining import screen

    def comp(p):
        return [("Copper", p, 600), ("Inert Materials", round(100 - p, 2), 0)]
    frames = [_rock(12431, 20, 5.0, 7.84, comp(45.22)), _rock(12437, 21, 5.0, 7.84, comp(45.27))]
    best, stable = screen.vote(frames)
    assert stable and best.mass in (12431, 12437) and best.resistance in (20, 21), best
    assert best.composition[0][1] in (45.22, 45.27) and best.composition[1][1] in (54.78, 54.73), best
    best, stable = screen.vote(frames + [_rock(12434, 20, 5.0, 7.84, comp(45.24))])
    assert stable and best.resistance == 20 and best.mass == 12434 and best.composition[0][1] == 45.24, best
    best, stable = screen.vote_partial(frames)
    assert stable and best.mass in (12431, 12437) and best.resistance in (20, 21), best


def test_enqueue_rock_keeps_votes_on_one_bad_frame():
    """投票队列（2026-10-24 外部补丁）：读稳以后中间认错一帧（质量少认一位）不清空，那一帧不进队列；
    真换了石头要连续两帧一致才清空重计（新石头因此晚出 1 帧）"""
    import collections
    from sc_mining import screen
    screen._reject.clear()
    comp = [("Copper", 40.0, 500), ("Inert Materials", 60.0, 0)]
    A, X, B = _rock(10000, 20, 5.0, 10.0, comp), _rock(1000, 20, 5.0, 10.0, comp), _rock(20850, 35, 5.0, 10.0, comp)
    q = collections.deque(maxlen=screen.VOTE_FRAMES)
    assert [screen.enqueue_rock(q, s) for s in (A, A, A)] == [False] * 3
    assert screen.enqueue_rock(q, X) is False and len(q) == 3                  # 认错的一帧先记下，不进队列
    assert screen.enqueue_rock(q, A) is False and len(q) == 4                  # 下一帧又是 A：照常累积
    assert screen.vote([x[0] for x in q])[1]
    assert screen.enqueue_rock(q, B) is False and len(q) == 4                  # 新石头第一帧：先观察
    assert screen.enqueue_rock(q, B) is True and [x[0] for x in q] == [B]      # 连续两帧一致：换石头
    screen._reject.clear()


def test_space_fix_navigation(monkeypatch, tmp_path):
    """太空路标一键定位：两次 /showlocation 之间直线飞 → 距离、近了多少、偏离角、多久到；不读右上角（2026-10-23 用户定的方案）"""
    import time as _t
    from sc_mining import navigate as n, paths
    from sc_mining.app import services as S, bus
    data = n.load()
    if not data.get("points"):
        pytest.skip("没有星图数据")
    monkeypatch.setattr(paths, "log", lambda name: tmp_path / name)
    from sc_mining import settings
    monkeypatch.setattr(settings, "load", lambda: {**settings.DEFAULTS, "nav_mode": "space", "fix_key": "F9"})   # 玩家自己选了「手动定位」、绑了 F9
    lp = next(p for p in data["points"] if p["sys"] == "Stanton" and p["t"] == "Lagrange Point")
    target = {"n": "太空矿点", "b": "@Stanton", "t": "Waypoint", "sys": "Stanton", "space": True, "qt": 0,
              "x": lp["x"] / 1000 + 50, "y": lp["y"] / 1000, "z": lp["z"] / 1000}
    g0 = (lp["x"] + 10_000, lp["y"] + 5_000, lp["z"])
    g1 = (lp["x"] + 20_000, lp["y"] + 5_000, lp["z"])
    f = n.fix_guide([(0, g0), (10, g1)], target, data)
    assert abs(f["direct"] - 30.41) < 0.05 and f["delta"] < -9 and f["deviation"] < 10 and 25 < f["eta"] < 35
    text = n.fix_text(f, "F9")
    assert "近了" in text and "✅ 偏离" in text and "秒到" in text
    assert "再按 F9" in n.fix_text(n.fix_guide([(0, g1)], target, data), "F9")          # 只有一次：提示再飞一段
    back = n.fix_text(n.fix_guide([(0, g1), (5, g0)], target, data), "F9")
    assert "远了" in back and "❌" in back and "反方向" in back
    # 导航中：剪贴板出现新的 /showlocation 坐标就更新（自己在聊天框输也行），悬浮窗显示结果
    clip = {"t": "旧东西"}
    monkeypatch.setattr(n, "read_clipboard", lambda: clip["t"])
    hud = {}
    patch_services(monkeypatch, "_hud", lambda: type("H", (), {"set": lambda self, k, v, *rich: hud.__setitem__(k, v),
                                                          "clear": lambda self, k: hud.pop(k, None)})())
    q = bus.subscribe()
    try:
        S._nav.start(target)
        _t.sleep(0.5)
        assert "F9" in hud.get("导航", "")
        clip["t"] = f"Coordinates: x:{g0[0]} y:{g0[1]} z:{g0[2]}"
        _t.sleep(0.8)
        clip["t"] = f"Coordinates: x:{g1[0]} y:{g1[1]} z:{g1[2]}"
        _t.sleep(0.8)
        assert "偏离" in hud["导航"] and "近了" in hud["导航"] and len(S._nav.fixes) == 2
    finally:
        S._nav.stop()
        bus.unsubscribe(q)
    # 没在导航太空路标时按 F9：提示，不打字
    assert "error" in S.fix_here()



def test_space_fix_dedupe_and_session(monkeypatch, tmp_path):
    """Codex 审查 1.6.23：剪贴板监听和 F9 拿到同一份坐标只算一次；导航结束 / 换目标后，旧的定位结果不再发出来"""
    import time as _t
    from sc_mining import navigate as n, paths, settings
    from sc_mining.app import services as S, bus
    data = n.load()
    if not data.get("points"):
        pytest.skip("没有星图数据")
    monkeypatch.setattr(paths, "log", lambda name: tmp_path / name)
    monkeypatch.setattr(settings, "load", lambda: {**settings.DEFAULTS, "nav_mode": "space"})     # 手动定位
    monkeypatch.setattr(n, "read_clipboard", lambda: "")
    patch_services(monkeypatch, "_hud", lambda: type("H", (), {"set": lambda *a: None, "clear": lambda *a: None})())
    lp = next(p for p in data["points"] if p["sys"] == "Stanton" and p["t"] == "Lagrange Point")
    target = {"n": "太空矿点", "b": "@Stanton", "t": "Waypoint", "sys": "Stanton", "space": True, "qt": 0,
              "x": lp["x"] / 1000 + 50, "y": lp["y"] / 1000, "z": lp["z"] / 1000}
    g0 = (lp["x"] + 10_000, lp["y"] + 5_000, lp["z"])
    g1 = (lp["x"] + 20_000, lp["y"] + 5_000, lp["z"])
    c0 = f"Coordinates: x:{g0[0]} y:{g0[1]} z:{g0[2]}"
    c1 = f"Coordinates: x:{g1[0]} y:{g1[1]} z:{g1[2]}"
    q = bus.subscribe()
    try:
        S._nav.start(target)
        sess = S._nav.session
        S._nav.add_fix(g0, c0, session=sess)
        _t.sleep(0.05)                                        # 两次定位要隔开时间才算得出多久到（Windows 时钟粒度粗，连着调用可能同一时刻）
        v = S._nav.add_fix(g1, c1, session=sess)              # 剪贴板监听先收到
        assert v["deviation"] is not None and v["eta"]
        again = S._nav.add_fix(g1, c1, session=sess)          # F9 返回同一份坐标
        assert len(S._nav.fixes) == 2 and again["deviation"] == v["deviation"] and again["eta"] == v["eta"]
        assert S._nav.add_fix(g1, None, session=sess)["delta"] == v["delta"]   # 坐标一样也不重复记
        S._nav.start(target)                                  # 换导航：旧会话的结果作废
        assert S._nav.add_fix(g0, "别的" + c0, session=sess) is None and S._nav.fixes == []
        sess2 = S._nav.session
        S._nav.stop()
        while True:                                           # 清掉之前的消息
            try:
                q.get_nowait()
            except Exception:
                break
        assert S._nav.add_fix(g1, "再别的" + c1, session=sess2) is None
        assert S._nav.add_fix(g1, "再别的" + c1) is None          # 没在导航
        left = []
        while True:
            try:
                left.append(q.get_nowait())
            except Exception:
                break
        assert not any(isinstance(m, dict) and (m.get("data") or {}).get("active") for m in left)
    finally:
        S._nav.stop()
        bus.unsubscribe(q)


def test_hotkey_conflicts(monkeypatch):
    """物品识别热键不能设成记路标 / 一键定位的键；已有冲突要明确说哪个失效"""
    from sc_mining import settings
    from sc_mining.app import services as S
    store = {**settings.DEFAULTS, "mark_key": "F7", "fix_key": "F9"}      # 1.0.5 起这两个默认不绑，这里是玩家自己绑了
    monkeypatch.setattr(settings, "load", lambda: dict(store))
    monkeypatch.setattr(settings, "update", lambda **kw: (store.update(kw), dict(store))[1])
    monkeypatch.setattr(S.bus, "publish", lambda *a, **k: None)
    from sc_mining import helpers
    monkeypatch.setattr(helpers, "start", lambda: None)
    assert "一键定位" in S.set_settings(trade_capture_key="F9")["error"]
    assert "记录路标" in S.set_settings(trade_capture_key="f7")["error"]
    assert store["trade_capture_key"] == "F8"
    assert S.set_settings(trade_capture_key="f11")["trade_capture_key"] == "F11"        # F5 采矿助手、F6 盘点也占着（1.6.57）
    assert "盘点" in S.set_settings(trade_capture_key="F6")["error"]
    assert S.hotkey_conflicts(store) == []
    w = S.hotkey_conflicts({**store, "trade_capture_key": "F9"})
    assert len(w) == 1 and "一键定位" in w[0] and "/showlocation" in w[0]
    assert "记录路标" in S.hotkey_conflicts({**store, "trade_capture_key": "F7"})[0]


def test_nav_mode_switch(monkeypatch, tmp_path):
    """导航页的开关：星球上的路标可以切到太空导航（一键定位），太空路标只能用太空导航；正在导航就按新方式重新开始"""
    import json, time as _t
    from sc_mining import navigate as n, settings, paths
    from sc_mining.app import services as S
    data = n.load()
    if not data.get("bodies"):
        pytest.skip("没有星图数据")
    monkeypatch.setattr(paths, "log", lambda name: tmp_path / name)
    monkeypatch.setattr(n, "read_clipboard", lambda: "")
    store = {}
    monkeypatch.setattr(settings, "load", lambda: {**settings.DEFAULTS, **store} if hasattr(settings, "DEFAULTS") else dict(store))
    monkeypatch.setattr(settings, "update", lambda **kw: store.update(kw))
    patch_services(monkeypatch, "_hud", lambda: type("H", (), {"set": lambda *a: None, "clear": lambda *a: None})())
    ground = {"n": "地面点", "b": "Daymar", "t": "Waypoint", "sys": "Stanton", "qt": 0, "x": 100.0, "y": 50.0, "z": 0.0}
    space = {"n": "太空点", "b": "@Stanton", "t": "Waypoint", "sys": "Stanton", "space": True, "qt": 0, "x": 1.0, "y": 2.0, "z": 3.0}
    try:
        assert S._nav.use_space(ground) is False and S._nav.use_space(space) is False   # 2026-10-27：太空路标默认也实时读右上角
        S._nav.start(ground)
        assert S._nav.space_mode is False
        r = S.nav_mode("space")
        assert r["space"] is True and S._nav.space_mode and S._nav.target is ground
        S.nav_mode("ground")
        assert S._nav.space_mode is False
        S._nav.start(space)
        S.nav_mode("ground")
        assert S._nav.space_mode is False                # 太空路标也能用实时定位
        assert "error" in S.nav_mode("别的")
    finally:
        S._nav.stop()
    # 星球上的路标用一键定位：在星球自转坐标里算（目标跟着星球转，不能当成星系里的固定点）
    b = data["bodies"]["Daymar"]
    t0 = 1_800_000_000.0
    tgt_g = n.target_global(ground, data, t0 + 10)
    near = tuple(v + 1000 for v in tgt_g)                   # 离目标约 1.7 km
    f = n.fix_guide([(t0 + 10, near)], ground, data)
    assert f["same_system"] and 1.5 < f["direct"] < 2.0


def test_halo_routes_match_scminer():
    """小行星带导航：对照 SCMiner 的 Aaron Halo Flight Computer（ARC-L1 出发，第 5 带）
    SCMiner：CRU-L3 12.7 Gm/389 Mm、CRU-L4 14.3/345、Hurston 13.5/192、Crusader 33.2/177、CRU-L5 39.5/151"""
    from sc_mining import halo
    pts = halo.points()
    if "ARC-L1" not in pts:
        pytest.skip("没有星图数据")
    want = {"CRU-L3": (12.7, 389), "CRU-L4": (14.3, 345), "Hurston": (13.5, 192), "Crusader": (33.2, 177), "CRU-L5": (39.5, 151)}
    rows = {r["to"]: r for r in halo.routes("ARC-L1", 5, 103, pts)}
    for to, (gm, mm) in want.items():
        r = rows[to]
        assert abs(r["dropout"] - gm) < 0.06, (to, r["dropout"])
        assert abs(r["margin"] - mm) / mm < 0.05, (to, r["margin"])
        assert r["late"] < r["dropout"] < r["early"]
    assert abs(rows["CRU-L4"]["window"] - 3.3) < 0.2                 # 345 Mm ÷ 103 Mm/s
    assert rows["CRU-L4"]["wide"] and not rows["Hurston"]["wide"]
    assert rows["CRU-L5"]["blocked"] and not rows["CRU-L4"]["blocked"]   # 穿过恒星的标出来
    ms = [r["margin"] for r in halo.routes("ARC-L1", 5, 103, pts)]
    assert ms == sorted(ms, reverse=True)
    assert "microTech" in pts and halo.route("ARC-L1", "ARC-L1", 5, 103, pts) is None
    t = halo.plan_text(rows["CRU-L4"])
    assert "14.3 Gm" in t and "按 U" in t and "14.5–14.1 Gm" in t and "秒" not in t      # 挖矿用：0.1 Gm、不讲反应秒数
    try:
        halo.band(11)
        assert False
    except ValueError:
        pass
    # 断开后核对：离恒星多远、在不在带里、往哪飞
    assert halo.where((20.3e9, 0, 0))["band"] == 5
    assert halo.where_text(halo.where((20.3e9, 0, 0)), 5).startswith("✅")
    t = halo.where_text(halo.where((20.0e9, 0, 0)), 5)
    assert "第3带" in t and "往外" in t and "230" in t
    assert "往里" in halo.where_text(halo.where((21.6e9, 0, 0)), 5)
    assert halo.where_text(halo.where((10e9, 0, 0)), 5).startswith("❌")
    assert halo.qd_speed("Atlas (S1)") == 103 and halo.qd_speed("odyssey") == 74


def test_halo_services(monkeypatch, tmp_path):
    """小行星带页的接口：选项、路线、挂到悬浮窗；挂着方案时按 F9 或自己输 /showlocation 核对在不在带里（Codex 复审 1.6.24 补的情形）"""
    import time as _t
    from sc_mining import halo, paths, settings, showloc
    from sc_mining import navigate as n
    from sc_mining.app import services as S
    if "ARC-L1" not in halo.points():
        pytest.skip("没有星图数据")
    monkeypatch.setattr(paths, "log", lambda name: tmp_path / name)
    store = dict(settings.DEFAULTS)
    monkeypatch.setattr(settings, "load", lambda: dict(store))
    monkeypatch.setattr(settings, "update", lambda **kw: (store.update(kw), dict(store))[1])
    clip = {"t": "Coordinates: x:20300000000 y:0 z:0"}             # 挂上之前就在剪贴板里的旧坐标：不算
    monkeypatch.setattr(n, "read_clipboard", lambda: clip["t"])
    hud = {}
    patch_services(monkeypatch, "_hud", lambda: type("H", (), {"set": lambda self, k, v, *rich: hud.__setitem__(k, v),
                                                          "clear": lambda self, k: hud.pop(k, None)})())
    o = S.halo_options()
    assert len(o["bands"]) == 10 and o["bands"][4]["ores"][0] == "量子矿物" and o["qd"] == "Atlas (S1)"
    assert any(p["key"] == "ARC-L1" for p in o["points"])
    r = S.halo_routes(frm="ARC-L1", band=5, qd="Odyssey (S3)")
    assert store["halo_qd"] == "Odyssey (S3)" and r["speed"] == 74 and r["rows"]
    assert "error" in S.halo_routes(frm="ARC-L1", band=0) and "error" in S.halo_routes(frm="没有", band=5)
    assert "error" in S.halo_pin(frm="ARC-L1", to="ARC-L1", band=5)
    S._nav.target = None
    try:
        p = S.halo_pin(frm="ARC-L1", to="CRU-L4", band=5)
        assert "14.3 Gm" in hud["小行星带"] and "自动核对" in hud["小行星带"] and S._HALO["plan"] is p
        _t.sleep(0.5)
        assert "✅" not in hud["小行星带"]                              # 旧坐标没被当成新定位
        # 自己在聊天框输 /showlocation：剪贴板出现新坐标就核对
        clip["t"] = "Coordinates: x:20000000000 y:0 z:0"
        _t.sleep(0.8)
        assert "第3带" in hud["小行星带"] and "往外" in hud["小行星带"]
        # F9：拿到的还是这一份坐标（监听已经处理过）→ 不重复算，结果一样
        monkeypatch.setattr(showloc, "showlocation", lambda log=None: ((20.0e9, 0.0, 0.0), clip["t"]))
        assert S.fix_here()["band"] == 3
        monkeypatch.setattr(showloc, "showlocation", lambda log=None: ((20.3e9, 0.0, 0.0), "Coordinates: x:20300000001 y:0 z:0"))
        assert S.fix_here()["band"] == 5 and "✅" in hud["小行星带"]
        monkeypatch.setattr(showloc, "showlocation", lambda log=None: (None, "游戏没在前台"))
        assert "error" in S.fix_here() and "定位失败" in hud["小行星带"]
        # F9 等坐标期间方案被取下：结果作废，不报错
        def slow(log=None):
            S.halo_unpin()
            return None, "超时"
        monkeypatch.setattr(showloc, "showlocation", slow)
        assert S.fix_here() == {"error": "超时"}
        S.halo_pin(frm="ARC-L1", to="CRU-L4", band=5)
        def swap(log=None):
            S.halo_pin(frm="ARC-L1", to="CRU-L3", band=5)
            return (20.3e9, 0.0, 0.0), "Coordinates: x:20300000002 y:0 z:0"
        monkeypatch.setattr(showloc, "showlocation", swap)
        assert "error" in S.fix_here()                                 # 换了方案：旧的这次不算
    finally:
        S.halo_unpin()
    assert "小行星带" not in hud and S._HALO["plan"] is None
    clip["t"] = "Coordinates: x:20100000000 y:0 z:0"
    _t.sleep(0.5)
    assert "小行星带" not in hud                                       # 取下后监听停了
    assert "error" in S.fix_here()                                     # 什么都没挂：只提示，不打字


def test_halo_where_edges():
    """判带用没四舍五入的半径：离内边界还差 400 km 不能说已经在带里"""
    from sc_mining import halo
    w = halo.where((20.2296e9, 0, 0))
    assert w["band"] is None and halo.where_text(w, 5).startswith("⚠️") and "km" in halo.where_text(w, 5)
    w = halo.where((20.4104e9, 0, 0))
    assert w["band"] == 6 and halo.where_text(w, 5).startswith("⚠️") and "往里" in halo.where_text(w, 5)
    assert halo.where_text(halo.where((20.2300001e9, 0, 0)), 5).startswith("✅")


def test_names_follow_game_localization(tmp_path, monkeypatch):
    """中文名以游戏里装的汉化为准（2026-10-23 用户要求）：尺寸写 S1/S2，类别照「物品类型」，
    舰船部件按类名取名字（同名不同物品不再张冠李戴），双语包才拿来用"""
    from sc_mining import crafting, localization, build_crafting as B
    assert crafting.SUB_ZH["size3"] == "S3" and crafting.GEAR_ZH[("vehiclegear", "quantumdrive")] == "量子驱动器"
    assert crafting.GEAR_ZH[("vehiclegear", "shield")] == "护盾生成器" and crafting.SUB_ZH["tachyon"] == "快子"
    assert crafting.SUB_ZH["undersuit"] == "基底服" and crafting.SUB_ZH["distortion"] == "畸变"
    ini = {"item_name_qdrv_arcc_s02_torrent": "激流Torrent\\n[量子 S2 民用 C]",
           "item_name_cool_jspn_s00_cryostarsl": "低温之星SL CryoStarSL\\n[冷却 S0 民用 B]",
           "item_name_radr_chco_s00_broadspecgo": "泛用规格-Go BroadSpec-Go\\n[雷达 S0 工业 B]",
           "item_nameshld_s02_kozane_scitem": "6MA “科赞Kozane”\\n[护盾 S2 军用 B]",
           "item_nametbeam_s01": "绝对牵引 TH1 牵引光束\\nSureGrip TH1 Tractor Beam",
           "item_namemodel_only": "VK-00\\n[量子 S1 军用 A]"}
    assert B.class_zh(ini, "BP_CRAFT_QDRV_ARCC_S02_Torrent", "Torrent") == "激流"
    assert B.class_zh(ini, "BP_CRAFT_COOL_JSPN_S00_CryoStarSL_SCItem", "Cryo-Star SL") == "低温之星SL"
    assert B.class_zh(ini, "BP_CRAFT_RADR_CHCO_S00_BroadSpecGo", "BroadSpec-Go") == "泛用规格-Go"
    assert B.class_zh(ini, "BP_CRAFT_SHLD_S02_Kozane_SCItem", "6MA 'Kozane'") == "6MA “科赞”"
    assert B.class_zh(ini, "BP_CRAFT_TBEAM_S01", "SureGrip S1 Tractor Beam") == "绝对牵引 TH1 牵引光束"
    assert B.class_zh(ini, "BP_CRAFT_MODEL_ONLY", "VK-00") == "" and B.class_zh(ini, "BP_CRAFT_NOPE", "x") is None
    # 游戏汉化：只认双语包
    live = tmp_path / "LIVE"
    loc = live / "data" / "Localization" / "chinese_(simplified)"
    loc.mkdir(parents=True)
    (loc / "global.ini").write_text("\n".join(f"item_NameX{i}=激流{i}Torrent{i}\\n[量子]" for i in range(80)), encoding="utf-8")
    from sc_mining import settings
    monkeypatch.setattr(settings, "load", lambda: {"game_log": str(live / "Game.log")})
    assert localization.game_ini() == loc / "global.ini"
    assert localization.names_source() == loc / "global.ini" and localization.names_tag(loc / "global.ini").startswith("game:")
    (loc / "global.ini").write_text("\n".join(f"item_NameX{i}=纯中文名字{i}" for i in range(80)), encoding="utf-8")
    assert localization._bilingual(loc / "global.ini") is False


def test_item_search_finds_everything():
    """物品查询搜索（1.6.41）：商店、掉落、汉化包一起搜，每件东西用完整的中文名、英文名都搜得到；
    视差步枪 → 视差 能量突击步枪（基础款在前，2026-10-23 用户报搜不到）；汉化包简称带出来的假英文名（视差步枪 → HD）不再有；
    商店和掉落数据里都没有的也搜得到，点开写明「商店和掉落数据里都没有」，能造的带上蓝图"""
    from sc_mining import itemsearch as I, crafting
    from sc_mining.trade import names
    from sc_mining.app import services as S
    rows = I._build()["rows"]
    if len(rows) < 1000:
        pytest.skip("没有商店 / 掉落数据")
    miss_en = [e["en"] for e in rows if not any(I.en_key(x["en"]) == e["ek"] for x in I.find(e["en"], 30))]
    miss_zh = [(k, e["en"]) for e in rows for k in e["zks"] if not any(I.en_key(x["en"]) == e["ek"] for x in I.find(k, 30))]
    assert not miss_en and not miss_zh, (len(miss_en), miss_en[:5], len(miss_zh), miss_zh[:5])
    assert "HD" not in names.table().values() and "S1" not in names.table().values()
    if I.lookup("Parallax Energy Assault Rifle"):
        r = S.item_search("视差步枪")
        assert r[0]["name"] == "Parallax Energy Assault Rifle" and all('"' in x["name"] for x in r[1:6])   # 后面是涂装版
        assert S.item_search("parallax rifle")[0]["name"] == "Parallax Energy Assault Rifle"
        assert S.item_search("视差")[0]["name"] == "Parallax Energy Assault Rifle"
    if I.lookup("Steel"):                  # 只在掉落数据里、名字又很常见：以前商店搜到 5 个以上就不看掉落，搜不到
        assert S.item_search("Steel")[0]["name"] == "Steel"
    # 完全一样的排第一（同一个中文名有两三件东西的，排在最前面那几个里）
    for e in rows[:: max(1, len(rows) // 300)]:
        assert I.en_key(I.find(e["en"], 1)[0]["en"]) == e["ek"], e["en"]
        if e["zh"]:
            assert e["ek"] in [I.en_key(x["en"]) for x in I.find(e["zh"], 3)], e["zh"]
    # 商店和掉落数据里都没有的（任务奖励、活动、涂装……）：搜得到，点开写明
    loc = [e for e in rows if not e["has_data"] and e["loc"]]            # 1.6.48 起另有只在 wiki 清单里的（没有中文名）
    assert loc and all(e["zh"] for e in loc)
    e = loc[len(loc) // 2]
    hit = next(x for x in S.item_search(e["zh"]) if I.en_key(x["name"]) == e["ek"])
    assert hit["src"] == "loc" and hit["id"] is None
    d = S.item_info(name=hit["name"], zh=hit["zh"], exact=True)
    assert d["nowhere"] and d["loot"] is None and not d["buyable"] and d["name"] == hit["name"]
    made = next((x for x in loc if crafting.for_item(x["en"], x["zh"])), None)
    if made:
        d = S.item_info(name=made["en"], zh=made["zh"], exact=True)
        assert d["nowhere"] and d["craft"]["key"] and d["craft"]["name"]
    # 有数据的：不算「都没有」；顶上搜索框也是这一套
    shop = next(x for x in rows if x["shop"] is not None)
    assert not S.item_info(name=shop["en"], exact=True, loot=False)["nowhere"]
    assert S.search(q=shop["en"])["items"][0]["name"] == shop["en"]


def test_mineral_in_item_search_with_nav():
    """矿物并进物品页搜索：去哪挖的每个地点带导航方式——Aaron Halo 进小行星带导航（挑这种矿最多的带），
    星球 / 卫星去导航页搜它，拉格朗日点矿区和没有地点数据的小行星带只给提示（2026-10-23 用户要求拆掉找矿点页）"""
    from sc_mining.app import services as S
    from sc_mining.locations import where
    if not where("Taranite"):
        pytest.skip("没有矿点数据")
    t = S.mineral_info(name="Taranite")
    kinds = {r["name"]: r["nav"] for r in t["rows"]}
    assert len(t["rows"]) == min(30, t["total"])
    assert kinds["Clio"]["kind"] == "search" and kinds["Clio"]["q"] == "Clio"
    assert kinds["ARC-L1"]["kind"] == "hint" and "ARC-L1" in kinds["ARC-L1"]["hint"]
    if "Pyro II (Monox)" in kinds:
        assert kinds["Pyro II (Monox)"]["q"] == "Monox"
    halo = S._mine_nav({"name": "Aaron Halo", "kind": "Belt"}, "Quantainium")
    assert halo["kind"] == "halo" and halo["band"] == 5                  # 量子矿：第5带密度最高
    assert S._mine_nav({"name": "Aaron Halo", "kind": "Belt"}, "Agricium")["band"] == 7
    assert S._mine_nav({"name": "Keeger Belt", "kind": "Belt"}, "Gold")["kind"] == "hint"
    assert S.mineral_search(q="塔兰")[0]["en"] == "Taranite"


def test_ground_gems_searchable_with_locations():
    """SCMiner 的 ROC 车矿、手采矿也能在百货集搜到：类型、信号、地点（2026-10-25 用户要求）；Hathor 矿洞写「校准站矿洞」、不能导航"""
    from sc_mining.app import services as S
    assert S.mineral_search(q="杰金")[0]["en"] == "Jaclium"            # 中文名一字不差先认，不模糊成「愈金」
    f = S.mineral_info(name="Feynmaline")
    assert f["gem"]["kind"] == "车矿" and f["gem"]["rs"] == 4000 and f["rows"][0]["pct"] == 100
    j = S.mineral_info(name="Jaclium")
    assert j["rows"][0]["place"] == "校准站矿洞" and j["rows"][0]["nav"]["kind"] == "none"
    assert S.mineral_info(name="Taranite")["gem"] is None


def test_craft_filter_by_mineral_and_item_hud_expires(monkeypatch):
    """扫描 / 矿物页「可制造 N 份蓝图」→ 制造页按这种矿筛选，带品质门槛的标出够不够；
    悬浮窗「物品」结果过一段时间自动收起（2026-10-23 用户：一直挂着不消失）"""
    import time as _t
    from sc_mining import crafting
    from sc_mining.app import services as S
    if not crafting.blueprints():
        pytest.skip("没有制造数据")
    gated = next((m for m in ("Titanium", "Riccite", "Agricium", "Quantainium", "Laranite", "Tungsten")
                  if crafting.mat_summary(m)["gated"]), None)
    for mat in ("Agricium", gated):
        if not mat:
            continue
        s = crafting.mat_summary(mat, 500)
        r = S.craft_browse(mat=mat, mq=500)
        assert r["total"] == s["count"] > 0 and r["mat"]["en"] == mat and r["mat"]["count"] == s["count"]
        zh = crafting.material_zh(mat)
        assert all(zh in x["need"] for x in r["rows"])
        assert sum(1 for x in r["rows"] if "ok" in x) <= s["gated"]
        assert S.craft_browse(mat=mat, cat=r["cats"][0]["key"])["total"] == r["cats"][0]["count"]
    if gated:
        lo, hi = crafting.mat_summary(gated, 1), crafting.mat_summary(gated, 1000)
        assert lo["ok"] <= hi["ok"] == hi["count"]
    assert "craft_count" in S.mineral_info(name="Agricium") and S.mineral_info(name="Agricium")["craft_count"] > 0
    assert "mat" not in S.craft_browse()
    # 物品悬浮窗定时收起；中途又写了新内容就按新内容重新计时
    hud = {}
    patch_services(monkeypatch, "_hud", lambda: type("H", (), {"set": lambda self, k, v, *rich: hud.__setitem__(k, v),
                                                          "clear": lambda self, k: hud.pop(k, None)})())
    S._item_hud("A", 0.2)
    _t.sleep(0.4)
    assert "物品" not in hud
    S._item_hud("B", 0.2)
    _t.sleep(0.1)
    S._item_hud("C", 0.5)
    _t.sleep(0.25)
    assert hud.get("物品") == "C"                  # B 的计时器到了，但已经换成 C，不收
    _t.sleep(0.4)
    assert "物品" not in hud


def test_hover_ignores_chat_hud_and_markers(monkeypatch):
    """F8 物品识别：全局聊天「[全局]某人：…」、飞船 HUD、地点标记不能当成物品（2026-10-23 用户日志）；
    整屏找的时候必须名字下面紧跟「体积/制造商/物品类型…」才算说明框"""
    from PIL import Image
    from sc_mining.trade import console as C
    from sc_mining.trade import ocr
    from sc_mining.trade.ocr import OcrToken
    from sc_mining.app import services as S
    T = lambda text, x, y: OcrToken(text, 90, (x, y, max(20, len(text) * 9), 18))
    chat = [T("[全局]RevtheWanderer:", 40, 700), T("thewayifigureditoutwasgoingoutsie", 40, 724),
            T("[全局]Omnicidal-Kitten：", 40, 760), T("LAMP ON", 40, 784)]
    marker = [T("拉亚利-坎特韦尔研究站", 900, 300), T("OUTPOST", 900, 324)]
    hud = [T("Zone: RSI_Perseus Pos:", 1500, 40), T("Zone: SolarSystem Pos: 22477025km", 1500, 64)]
    assert C.tooltip_pick(chat, (960, 540))[0] is None
    assert C.tooltip_pick(chat + hud, (960, 540))[0] is None
    name, sure = C.tooltip_pick(marker, (960, 540))
    assert not sure                                            # 地点标记：下面没有「体积」之类，不算说明框
    item = [T("实准枪口补偿器2", 900, 300), T("VeraCompensator2", 900, 324), T("体积：20uSCU", 900, 348)]
    assert C.tooltip_pick(chat + item, (960, 540)) == (("实准枪口补偿器2", "VeraCompensator2"), True)
    # 新识别机制：按鼠标横向分级（首选局部 -> 备选局部 30~70% -> 全屏兜底）
    calls = []
    def fake(img, urgent=False, offset=(0, 0)):
        calls.append(offset)
        return [] if len(calls) <= 2 else chat + marker + hud
    monkeypatch.setattr(ocr, "recognize", fake)
    img = Image.new("RGB", (1920, 1080))
    toks, name, where = S._read_tooltip(img, (100, 540))
    assert name is None and where == "整屏" and len(calls) == 3
    calls.clear()
    monkeypatch.setattr(ocr, "recognize", lambda img, urgent=False, offset=(0, 0): [] if not calls.append(1) and len(calls) <= 2 else chat + item)
    toks, name, where = S._read_tooltip(img, (100, 540))
    assert name == ("实准枪口补偿器2", "VeraCompensator2") and where == "整屏"
    # 鼠标在中间（50%~70%）：两轮局部未找到时进入整屏兜底
    calls.clear()
    monkeypatch.setattr(ocr, "recognize", lambda img, urgent=False, offset=(0, 0): [] if not calls.append(1) and len(calls) <= 2 else chat + item)
    toks, name, where = S._read_tooltip(img, (960, 540))
    assert name == ("实准枪口补偿器2", "VeraCompensator2") and where == "整屏" and len(calls) == 3


def test_live_signals_pause_while_scan_panel_open(monkeypatch, tmp_path):
    """对着石头看扫描面板时不认信号（面板上的质量 13,586 会被当成信号，2026-10-23 用户反馈）；
    面板一出现悬浮窗的信号就收起，面板关了再继续认"""
    from sc_mining.parse import Scan
    a = Scan(rock="Iron", mass=13586.0, resistance=0.0, instability=10.23, total_scu=17.46,
             composition=[("Iron", 10.98, 710), ("Inert Materials", 89.02, None)])
    calls = []

    def sig(img):
        calls.append(1)
        return [(13586, False, "13,586", (0, 0, 10, 10))]
    from sc_mining.app import services as S
    patch_services(monkeypatch, "_where_now", lambda: None)           # 不去读真屏幕右上角（Windows 上会很慢）
    patch_services(monkeypatch, "goal_short", lambda force=False: {})   # 不读真的目标 / 库存
    frames = [None] * 6 + [a] * 60
    msgs, hud = _live_run(monkeypatch, tmp_path, frames, seconds=1.0, sig=sig)
    assert len(calls) <= 6                                  # 面板出现后不再调用信号识别
    assert ("set", "信号") in hud and ("clear", "信号") in hud
    assert hud.index(("clear", "信号")) > hud.index(("set", "信号"))


def test_goal_shortage_marked_everywhere(monkeypatch):
    """目标还缺的材料：扫描结果、悬浮窗、信号、物品页、矿物页都标出来；精炼后的量给 SCU 和 uSCU（2026-10-23 用户要求）"""
    from sc_mining.parse import parse_scan
    from sc_mining.app import services as S
    from sc_mining import goals as G
    gold = {"en": "Gold", "zh": "金", "short": 2.0, "unit": "SCU", "minq": 800, "goals": ["某蓝图"], "item": None}
    tung = {"en": "Tungsten", "zh": "钨", "short": 0.5, "unit": "SCU", "minq": 1, "goals": ["某蓝图"], "item": None}
    monkeypatch.setattr(G, "load", lambda: [{"id": "x"}])
    monkeypatch.setattr(G, "plan", lambda t=None, goals=None: {"goals": [], "shortfall": [gold, tung]})
    patch_services(monkeypatch, "trade", lambda: None)
    S._SHORT["t"] = 0.0
    assert S._gkey("Gold (Ore)") == S._gkey("gold") and S._gkey("钨矿石") == S._gkey("钨")
    assert S._goal_for("钨矿石")["en"] == "Tungsten" and S._goal_for("Iron") is None
    s = parse_scan(["扫描结果", "钨矿石", "质量： 44336", "抗性： 4% ", "不稳定性： 17.32", "组成 23.68 SCU",
                    "6.55% 兰石原矿 510", "12.95% 钨矿石 662", "49.41% 钨矿石 363", "31.07% 情性物质 。"])
    v = S.scan_view(s, ({"Inert Materials": 0.3}, 0.3, 96.0))
    assert [g["en"] for g in v["goal"]] == ["Tungsten"] and v["goal"][0]["ok"]
    assert "🎯 目标缺少 钨 0.5 SCU" in v["hud"]
    assert "aUEC" in v["hud"] and "净值" not in v["hud"]                 # 用户：净值就是 aUEC，写价格
    assert "精炼后" in v["hud"] and "uSCU" in v["hud"] and v["refine"][0]["amount"] and v["refine"][0]["yield"]
    r = v["hud_rich"]                                        # 1.6.65 悬浮窗按样图：矿物组成按矿合并，各品质从高到低，高品质那份标出来
    assert [c["name"] for c in r["comp"]] == ["钨", "砬兰石", "惰性物质"] and r["comp"][0]["pct"] == "62.36%"
    assert [(q["q"], q["pct"], q["hi"]) for q in r["comp"][0]["subs"]] == [("662", "12.95%", True), ("363", "49.41%", False)]
    assert r["gain"][1][2] == "aUEC" and r["advice"]["heads"]
    assert S.scu_text(0.42) == "420,000 uSCU（0.420 SCU）" and S.scu_text(3.5).startswith("3.50 SCU（3,500,000 uSCU）")
    assert "当前 650 未达标" in S._goal_text(gold, 650) and "当前 900 已达标" in S._goal_text(gold, 900)
    lines = S._mark_goal_lines(["信号 13,600 → 林登金 ×4", "信号 8,000 → 金 ×2", "信号 4,000 → 钨 ×1"])
    assert lines[0].startswith("信号") and lines[1].startswith("🎯") and lines[2].startswith("🎯")
    assert S.mineral_info(name="Gold")["goal"].startswith("🎯 目标缺少 金 2 SCU")
    assert S._hover_lines({"name": "Tungsten"}, "Tungsten", "钨")[0].startswith("🎯")
    S._SHORT["t"] = 0.0


def test_hover_unsure_names_and_anchor_lines():
    """2026-10-23 全量样本测试发现：中间没把握时会把碎字（「力 mnoc」）、地点标记、系统界面当物品；
    靠「体积」往上找名字时会把「制造商：灰猫工业」当名字"""
    from sc_mining.trade import console as C
    from sc_mining.trade.ocr import OcrToken
    T = lambda text, x, y: OcrToken(text, 90, (x, y, max(20, len(text) * 9), 18))
    assert C.plausible_name("受辐射的瓦拉卡蛋", "IradiatedValakkar Egg")
    for zh, en in [("力", "mnoc"), ("加力", "mnoo"), ("拉正利-收特书尔研究站", "BAYARCANTWELLBESE"), ("未知", "2Lokgr"),
                   ("北极星需要外部货梯或者超大机库才能卸货", "Rabbit (id:Fiendmcy)"), ("天之神", "·Roberts")]:
        assert not C.plausible_name(zh, en), (zh, en)
    toks = [T("制造商：灰猫工业（GreycatIndustrial)", 900, 280), T("体积：16862uSCU", 900, 304)]
    name, sure = C.tooltip_pick(toks, (960, 540))
    assert not name or "制造商" not in name[0]
    toks = [T("必事A20", 900, 256), T("制造商：必事", 900, 280), T("体积：600uSCU", 900, 304)]
    assert C.tooltip_pick(toks, (960, 540))[0][0] == "必事A20"


def test_mask_own_window_too():
    """盖在游戏上的天枢主窗口也涂黑（窗口里的实时栏有信号值 / 质量，会被当成游戏里的字）"""
    from PIL import Image
    from sc_mining.perf import mask_overlay, own_window_rects
    img = Image.new("RGB", (200, 100), (255, 255, 255))
    mask_overlay(img, 0, 0, rect=(10, 10, 20, 20), own=[(100, 50, 150, 90)])
    assert img.getpixel((15, 15)) == (0, 0, 0) and img.getpixel((120, 60)) == (0, 0, 0)
    assert img.getpixel((60, 60)) == (255, 255, 255)
    assert isinstance(own_window_rects(), list)                 # 非 Windows 返回空列表，不报错


def test_waypoint_from_pasted_showlocation(monkeypatch, tmp_path):
    """路标页粘贴 /showlocation 的输出：先预览认出星球 / 经纬度，再起名保存（2026-10-23 用户要求，取代填经纬度）"""
    from sc_mining import navigate as n, paths
    from sc_mining.app import services as S
    data = n.load()
    if not data.get("bodies"):
        pytest.skip("没有星图数据")
    monkeypatch.setattr(paths, "log", lambda name: tmp_path / name)
    monkeypatch.setattr(n, "WAYPOINTS", tmp_path / "wp.json", raising=False)
    saved = []
    monkeypatch.setattr(n, "add_waypoint", lambda name, body, local: saved.append(("ground", name, body)))
    monkeypatch.setattr(n, "add_space_waypoint", lambda name, system, g: saved.append(("space", name, system)))
    patch_services(monkeypatch, "waypoints", lambda: [])
    patch_services(monkeypatch, "_hud", lambda: type("H", (), {"set": lambda *a: None, "clear": lambda *a: None})())
    b = data["bodies"]["Daymar"]
    g = n.target_global({"b": "Daymar", "x": 10.0, "y": 20.0, "z": 0.5, "t": "Waypoint"}, data, 1_800_000_000.0) if hasattr(n, "target_global") else None
    assert "error" in S.waypoint_preview(text="随便一句话")
    assert "error" in S.waypoint_from_text(name="x", text="没有坐标")
    assert "error" in S.waypoint_from_text(name="", text="Coordinates: x:1 y:2 z:3")
    lp = next(p for p in data["points"] if p["sys"] == "Stanton" and p["t"] == "Lagrange Point")
    txt = f"Coordinates: x:{lp['x'] + 5000} y:{lp['y']} z:{lp['z']}"
    pv = S.waypoint_preview(text=txt)
    assert pv["ok"] and pv["space"] and "Stanton" in pv["body"]
    r = S.waypoint_from_text(name="太空点", text=txt)
    assert saved[-1] == ("space", "太空点", "Stanton") and "太空" in r["desc"]
    if g:
        txt = f"Coordinates: x:{g[0]} y:{g[1]} z:{g[2]}"
        pv = S.waypoint_preview(text=txt)
        assert pv["ok"] and not pv["space"] and pv["body"] == "Daymar" and "戴玛尔" in pv["desc"]
        S.waypoint_from_text(name="地面点", text=txt)
        assert saved[-1] == ("ground", "地面点", "Daymar")


def test_feedback_report_bundle(monkeypatch, tmp_path):
    """一键问题反馈（F10 / 「报告问题」）：整屏截图 + 最近采矿助手截图 + OCR 原文 + 当时显示的结果 + 日志尾巴
    存成 userdata\\feedback\\<时间>_<类型>（文件夹 + zip）；导出把所有 zip 再打包到桌面；清空"""
    import json, zipfile
    from PIL import Image
    from sc_mining import paths, screen
    from sc_mining.app import services as S
    monkeypatch.setattr(paths, "USER", tmp_path, raising=False)
    monkeypatch.setattr(paths, "LOGS", tmp_path / "logs", raising=False)
    monkeypatch.setattr(paths, "SHOTS", tmp_path / "shots", raising=False)
    (tmp_path / "logs").mkdir(); (tmp_path / "logs" / "live_log.txt").write_text("\n".join(f"line {i}" for i in range(300)), encoding="utf-8")
    (tmp_path / "shots" / "live").mkdir(parents=True)
    for i in range(7):
        Image.new("RGB", (8, 8)).save(tmp_path / "shots" / "live" / f"{i}.png")
    patch_services(monkeypatch, "_desktop", lambda: tmp_path / "desk")
    (tmp_path / "desk").mkdir()
    patch_services(monkeypatch, "_hud", lambda: type("H", (), {"sections": {"信号": "x"}, "set": lambda *a: None, "clear": lambda *a: None})())
    patch_services(monkeypatch, "WIN", False)
    screen.LAST_RAW.update(t=1.0, scan=["扫描结果", "质量： 123"], bag=[])
    S._FB_LAST["sig"] = {"values": [44336]}
    r = S.feedback_report(kind="signal", note="屏幕是 33,000", img=Image.new("RGB", (64, 32)))
    d = tmp_path / "feedback"
    assert r["count"] == 1 and (d / r["dir"].split("\\")[-1].split("/")[-1]).is_dir() or d.exists()
    folder = next(p for p in d.iterdir() if p.is_dir())
    names = {p.name for p in folder.iterdir()}
    assert "屏幕.png" in names and "情况.json" in names and "说明.txt" in names and "live_log.txt" in names
    assert sum(n.startswith("live_") and n.endswith(".png") for n in names) == 5        # 最近 5 帧
    info = json.loads((folder / "情况.json").read_text(encoding="utf-8"))
    assert info["note"] == "屏幕是 33,000" and info["kind"] == "signal" and info["shown_signal"]["values"] == [44336]
    assert info["ocr_scan_lines"] == ["扫描结果", "质量： 123"]
    assert len((folder / "live_log.txt").read_text(encoding="utf-8").splitlines()) == 150
    with zipfile.ZipFile(folder.with_suffix(".zip")) as z:
        assert any(n.endswith("屏幕.png") for n in z.namelist())
    S.feedback_report(kind="坏类型", img=Image.new("RGB", (8, 8)))
    rows = S.feedback_list()
    assert len(rows) == 2 and rows[0]["name"].endswith("_auto")                     # 不认识的类型按 auto
    e = S.feedback_export()
    assert e["files"] == 2 and (tmp_path / "desk" / e["path"].split("\\")[-1].split("/")[-1]).exists()
    assert S.feedback_clear()["removed"] >= 4 and S.feedback_list() == []
    assert "error" in S.feedback_export()
    # 热键冲突：反馈键撞了别的键要提示
    assert any("问题反馈" in w for w in S.hotkey_conflicts({"trade_capture_key": "F10"}))
    assert "问题反馈" in S.set_settings.__wrapped__(trade_capture_key="F10")["error"] if hasattr(S.set_settings, "__wrapped__") else True


def test_scan_view_lots_by_quality(monkeypatch):
    """成分表（1.6.42）：石头里每一份（矿 × 品质、惰性物质）一行；同一种矿两种品质标高 / 低；品质写第几档；
    精炼按份算（精炼保留品质，不同品质精炼完还是分开的）；目标按每一份判断品质门槛；悬浮窗写惰性占比和高品质那份"""
    from sc_mining.parse import parse_scan
    from sc_mining.app import services as S
    from sc_mining import goals as G
    tung = {"en": "Tungsten", "zh": "钨", "short": 0.5, "unit": "SCU", "minq": 600, "goals": ["某蓝图"], "item": None}
    monkeypatch.setattr(G, "load", lambda: [{"id": "x"}])
    monkeypatch.setattr(G, "plan", lambda t=None, goals=None: {"goals": [], "shortfall": [tung]})
    patch_services(monkeypatch, "trade", lambda: None)
    S._SHORT["t"] = 0.0
    s = parse_scan(["扫描结果", "钨矿石", "质量： 44336", "抗性： 4% ", "不稳定性： 17.32", "组成 23.68 SCU",
                    "6.55% 兰石原矿 510", "12.95% 钨矿石 662", "49.41% 钨矿石 363", "31.07% 情性物质 。"])
    v = S.scan_view(s, ({}, None, None))
    lots = v["lots"]
    assert [(r["zh"], r["q"], r["rank"]) for r in lots] == [("砬兰石", 510, ""), ("钨", 662, "高品质"), ("钨", 363, "低品质"), ("惰性物质", None, "")]
    assert [r["tier"] for r in lots] == ["E 档", "D 档", "F 档（最低）", ""]
    assert abs(lots[1]["scu"] - 23.68 * 0.1295) < 1e-3 and abs(lots[3]["scu"] - 23.68 * 0.3107) < 1e-3
    assert lots[3]["inert"] and lots[3]["refined_text"] == "无精炼产出，仅占用矿袋"
    # 每份精炼后的量加起来 = 第一种精炼方式的总量
    assert abs(sum(r["refined"] or 0 for r in lots) - v["refine"][0]["scu"]) < 1e-6
    assert [(x["zh"], x["q"]) for x in v["refine"][0]["lots"]] == [("砬兰石", 510), ("钨", 662), ("钨", 363)]
    assert v["lots_plan"] and v["total_scu"] == 23.68 and not v["cut"]
    assert "惰性 31%｜钨 品质 662：3.07 SCU" in v["hud"]
    g = v["goal"][0]
    assert g["ok"] and "品质 662：已达标（精炼后 1.50 SCU），品质 363：未达标" in g["text"] and "品质 ≥600" in g["text"]
    # 只有一种品质时照旧：「当前 650 不够」
    assert "当前 650 未达标" in S._goal_text(dict(tung, minq=800), 650)
    S._SHORT["t"] = 0.0


def test_scan_view_when_panel_cut_off():
    """面板被屏幕右边挡住（16:10 屏幕上鼹鼠炮塔，2026-10-23 用户反馈）：只有质量、抗性、不稳定性和成分占比，
    照样给破碎方案，写明品质和总 SCU 看不到、调大 FOV视野"""
    from sc_mining.parse import Scan
    from sc_mining.app import services as S
    c = Scan(rock="Ouratite", mass=745, resistance=20, instability=8.2, total_scu=None, difficulty="简单",
             composition=[("Ouratite", 2.79, None), ("Ouratite", 5.04, None), ("Agricium", 14.52, None), ("Inert Materials", 77.64, None)])
    v = S.scan_view(c, ({}, None, None), cut=True)
    assert v["cut"] and "FOV视野" in v["note"] and v["plans"] and not v["refine"] and not v["minerals"]
    assert "面板被遮挡：仅计算破碎方案" in v["hud"] and "惰性 78%" in v["hud"]
    assert [r["scu"] for r in v["lots"]] == [None] * 4 and [r["pct"] for r in v["lots"]] == [2.79, 5.04, 14.52, 77.64]


def test_live_cut_panel_gives_breaking_plan(monkeypatch, tmp_path):
    """面板顶着屏幕右边、品质和总 SCU 读不到：两帧一致就出「只有破碎方案」的结果，不当成读不全（不留图）"""
    import time as _t
    from sc_mining import screen
    from sc_mining.parse import Scan
    c = Scan(rock="Ouratite", mass=745, resistance=20, instability=8.2, total_scu=None,
             composition=[("Ouratite", 2.79, None), ("Agricium", 14.52, None), ("Inert Materials", 82.69, None)])
    monkeypatch.setattr(screen, "LAST_PANEL", {"cut": True, "box": (2200, 600, 2560, 1000), "h": 14})
    msgs, hud = _live_run(monkeypatch, tmp_path, [c] * 40, seconds=0.5)
    scans = [m["data"] for m in msgs if m["kind"] == "scan"]
    assert scans and scans[-1]["cut"] and scans[-1]["mass"] == 745 and scans[-1]["plans"]
    assert ("set", "扫描") in hud
    _t.sleep(0.2)
    log = (tmp_path / "live_log.txt").read_text(encoding="utf-8")
    assert "PART" in log and "MISS" not in log and not list(tmp_path.glob("*.png"))
    # 没顶着屏幕边的面板读不全：不出这种结果
    monkeypatch.setattr(screen, "LAST_PANEL", {"cut": False, "box": (1500, 600, 1800, 1000), "h": 8})
    msgs, _ = _live_run(monkeypatch, tmp_path, [c] * 40, seconds=0.4)
    assert not [m for m in msgs if m["kind"] == "scan"]


def test_live_miss_hint_reason(monkeypatch, tmp_path):
    """读不全时告诉玩家原因：面板被屏幕右边挡住 → 调大 FOV视野；面板不见了提示收起"""
    from sc_mining import screen
    from sc_mining.parse import Scan
    half = Scan(rock="Ouratite", mass=None, resistance=None, instability=None, total_scu=None,
                composition=[("Ouratite", 2.79, None), ("Inert Materials", 97.21, None)])
    monkeypatch.setattr(screen, "LAST_PANEL", {"cut": True, "box": (2200, 600, 2560, 1000), "h": 14})
    msgs, hud = _live_run(monkeypatch, tmp_path, [half] * 30 + [None] * 200, seconds=1.0, stale=0.3)
    hints = [m["data"] for m in msgs if m["kind"] == "scan_hint"]
    assert hints and hints[0]["why"] == "cut" and "FOV视野" in hints[0]["text"]
    assert hints[-1]["text"] == "" and ("clear", "扫描") in hud                 # 面板不见了：收起
    assert "HINT cut" in (tmp_path / "live_log.txt").read_text(encoding="utf-8")


def test_item_search_wiki_gap_fill_and_tail_name_keys():
    """物品查询查漏补缺（1.6.48，用户对照 starcitizen.tools 发现搜不到的）：
    ①汉化包里 item_Cargo_…_Name / item_Mining_…_Name / item_fuelpod_…_Name 这种结尾是 Name 的键也读（矿石吊舱、采矿模组、打捞头），
      采矿模组的英文补上 Module，燃料舱第二行的属性串不当中文名；
    ②英文 wiki（游戏解包）的物品清单只补别处都没有的英文名（标 wiki），中文名只信汉化包；涂装、飞船内部通用件不补；
    ③只有掉落数据的物品也带上 wiki 的类型 / 尺寸当分类"""
    from sc_mining.localization import zh2en_items
    from sc_mining import itemsearch as I
    from sc_mining.app import services as S
    t = zh2en_items({"item_Cargo_ShipMining_Pod_Golem_BTGL_Name": "Golem MC-4 矿石吊舱\\nGOLEM MC-4 Ore Pod ",
                     "item_Mining_Modules_Active_GRIN_Charge_BTGL_Name": "净采 模组Clearcut\\n[+15%功率|+30%绿区速度]",
                     "item_fuelpod_MISC_Standard_Name": "CR-60\\n[调节1.16 | 血量22800 | 20 SCU]",
                     "item_fuelpod_GRIN_BigAndFast_Name": "巨灵Gargant\\n[调节1.3 | 血量11550 | 12.4 SCU]",
                     "item_scraper_GRIN_Standard_Name": "研磨 刮削模块\\nAbrade Scraper Module", "item_Name_x_Desc": "说明"})
    assert t == {"Golem MC-4 矿石吊舱": "GOLEM MC-4 Ore Pod", "净采 模组": "Clearcut Module", "巨灵": "Gargant", "研磨 刮削模块": "Abrade Scraper Module"}
    assert len(I.wiki_items()) > 7000
    hit = S.item_search("Hartmoore Inverter")[0]
    # 2026-10-27 起汉化包只写中文名的物品也有英文名（data/zh_only_names.json）：带中文名、来源是汉化包
    assert hit["name"] == "Hartmoore Inverter Code" and hit["src"] == "loc" and hit["zh"] == "哈特莫尔转换器密码" \
        and hit["category"] == "钥匙卡"            # 2026-10-27 老大定：芯片卡（DCHS 计算板、密钥）归钥匙卡一类
    assert S.item_search("Biological Samples")[0]["zh"] == "生物样本" and S.item_search("生物样本")[0]["name"] == "Biological Samples"
    assert not [r for r in S.item_search("300 Series Amber") if r["src"] == "wiki"]          # 涂装只有汉化包 / 掉落来源，不从 wiki 补
    assert not any(r["name"] == "Remote Turret" and r["src"] == "wiki" for r in S.item_search("Remote Turret"))
    assert any(r["category"].startswith("炮塔") for r in S.item_search("Remote Turret"))         # 掉落物品带上 wiki 的类型
    names = {r["en"] for r in I._build()["rows"]}
    assert "mount_gimbal_mining_golem" not in names                                              # 内部占位名不收


def test_item_desc_and_alias_from_wiki(monkeypatch, tmp_path):
    """物品描述和英文名对齐（1.6.49）：①描述来自 wiki 的游戏官方中文说明（data/wiki_items.json 的 d），物品页显示；
    ②汉化包的英文名按游戏内部类名（item_Name_<类名>）对到 wiki 正名，写错 / 过时的（Bulldog → Badger、Monolith Arms → Monolith Armor Arms）
      记进 name_aliases.json，搜旧写法也能找到正名；③wiki 清单带类名 cls"""
    from sc_mining import localization as L, itemsearch as I, paths
    from sc_mining.app import services as S
    d = S.item_info(name="Helix II Mining Laser", exact=True)
    assert "采矿激光" in d["desc"] and "铝热" in d["desc"]
    t = L.zh2en_items({"item_Name_kap_combat_heavy_arms_01_01_01": "巨石 臂甲\\nMonolith Arms", "item_NameX_Y": "甲\\nFoo Bar"},
                      {"kap_combat_heavy_arms_01_01_01": "Monolith Armor Arms", "x_y": "Foo Bar"})
    assert t == {"巨石 臂甲": "Monolith Armor Arms", "甲": "Foo Bar"} and L.ALIASES == {"Monolith Arms": "Monolith Armor Arms"}
    cls = L.wiki_class_names()
    assert cls.get("mining_laser_thcn_helix_s2") == "Helix II Mining Laser" and len(cls) > 10000
    # 别名文件：搜旧写法找到正名，物品页标「也叫」
    f = tmp_path / "name_aliases.json"
    f.write_text('{"Helix 2 Old Name": "Helix II Mining Laser"}', encoding="utf-8")
    real = paths.DATA
    monkeypatch.setattr(I, "_cache", {"key": None, "index": None})
    monkeypatch.setattr(paths, "DATA", tmp_path)
    import shutil
    for n in ("zh_names.json", "wiki_items.json", "shops.json", "loot_index.json"):
        if (real / n).exists() and not (tmp_path / n).exists():
            shutil.copyfile(real / n, tmp_path / n)              # Windows 建符号链接要特权，直接复制
    try:
        hit = S.item_search("Helix 2 Old Name")
        assert hit and hit[0]["name"] == "Helix II Mining Laser"
        assert "Helix 2 Old Name" in S.item_info(name="Helix II Mining Laser", exact=True)["aka"]
    finally:
        monkeypatch.setattr(I, "_cache", {"key": None, "index": None})


def test_ore_log_record_and_hotkeys(monkeypatch, tmp_path):
    """1.6.70 原矿记录：记最近一块矿（窗口里点的不带坐标）、删除能撤销；所有热键都能改，原矿记录键能清掉"""
    from sc_mining import ore_log, settings, helpers
    from sc_mining.app import services as S
    monkeypatch.setattr(ore_log, "FILE", tmp_path / "ore_log.json")
    monkeypatch.setattr(S.bus, "publish", lambda *a, **k: None)
    patch_services(monkeypatch, "_note_hud", lambda *a, **k: None)
    patch_services(monkeypatch, "_ORE_LAST", {"view": None})
    assert "error" in S.ore_record()
    S._ORE_LAST["view"] = {"rock": "塔兰导电石", "mass": 38775, "resistance": 55, "instability": 323.46, "total_scu": 36.9, "at": "16:02:06",
                           "lots": [{"zh": "塔兰导电石", "en": "Taranite", "pct": 11.55, "q": 718, "scu": 4.26, "inert": False},
                                    {"zh": "惰性物质", "en": "Inert Materials", "pct": 30.92, "q": None, "scu": 11.41, "inert": True}],
                           "refine": [{"method": "德尼克斯熔解法", "station": "列夫斯基", "value": 344786, "scu": 12.39}]}
    rec = S.ore_record()
    assert rec["value"] == 344786 and rec["lots"][0]["pct"] == 11.55 and "coords" not in rec
    assert S.ore_list()["rows"][0]["id"] == rec["id"]
    gone = S.ore_delete(id=rec["id"])
    assert S.ore_list()["rows"] == []
    S.ore_restore(rec=gone)
    assert [r["id"] for r in S.ore_list()["rows"]] == [rec["id"]]
    assert "没有坐标" in S.ore_go(id=rec["id"])["error"]
    store = dict(settings.DEFAULTS)
    monkeypatch.setattr(settings, "load", lambda: dict(store))
    monkeypatch.setattr(settings, "update", lambda **kw: (store.update(kw), dict(store))[1])
    monkeypatch.setattr(helpers, "start", lambda: None)
    assert S.set_settings(live_key="f4")["live_key"] == "F4"
    assert "盘点" in S.set_settings(ore_key="F6")["error"]
    assert S.set_settings(ore_key="F11")["ore_key"] == "F11" and S.set_settings(ore_key="")["ore_key"] == ""
    assert "F1–F12" in S.set_settings(mark_key="Q")["error"]
    w = S.hotkey_conflicts({**store, "mark_key": "F7", "ore_key": "F7"})
    assert len(w) == 1 and "原矿记录" in w[0] and "记录路标" in w[0]


def test_gear_change_marks_live_for_recalc(monkeypatch, tmp_path):
    """改配装后，采矿助手正在显示的石头要按新配装重算：set_mining_gear 给 _live 打记号"""
    from sc_mining import settings
    from sc_mining.app import services as S
    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    before = S._live.gear_rev
    S.set_mining_gear(ship="mole", loadout={"heads": [["helix_ii", []]] * 3, "crew": 2})
    assert S._live.gear_rev == before + 1


def test_item_names_and_categories_unified():
    """物品名「中文 English」（2026-10-26）：采矿装备的中文不带型号、中文也搜得到；蓝图同样写法；商店分类用游戏里的中文"""
    from sc_mining.i18n import gear_zh_of_item, shop_cat_zh
    from sc_mining.crafting import display_name
    assert gear_zh_of_item("Hofstede-S2 Mining Laser") == "霍夫斯泰德" and gear_zh_of_item("Rieger-C3 Module") == "里格"
    assert gear_zh_of_item("Sabir") == "萨比尔" and gear_zh_of_item("FLTR-L Module") == "" and gear_zh_of_item("Antium Core") == ""
    assert shop_cat_zh("Mining Laser Heads") == "采矿激光器" and shop_cat_zh("Arms") == "臂甲" and shop_cat_zh("没见过的") == "没见过的"
    assert display_name({"n": "Hofstede-S2 Mining Laser", "z": "霍夫斯泰德-S2 型采矿激光器"}) == "霍夫斯泰德 Hofstede-S2 Mining Laser"
    assert display_name({"n": "Karna Rifle", "z": "卡纳 步枪"}) == "卡纳 步枪 Karna Rifle" and display_name({"n": "X", "z": ""}) == "X"
    from sc_mining.app import services as S
    rows = S.item_search("霍夫斯泰德")
    assert any(r["name"] == "Hofstede-S2 Mining Laser" and r["zh"] == "霍夫斯泰德" and r["category"] == "采矿激光器" for r in rows)


def test_disclaimer_and_about_have_required_notices():
    """免责声明和关于页（2026-10-26）：CIG 要求的非官方声明和权利人、版权、EULA 自动化风险、要求注明的数据来源"""
    from sc_mining import paths
    from sc_mining.app import services as S
    h = (paths.CODE / "app" / "web" / "disclaimer.html").read_text(encoding="utf-8")
    for must in ("not affiliated with the Cloud Imperium group of companies", "Cloud Imperium Rights LLC", "Cloud Imperium Rights Limited",
                 "© 2026 Adm_TT", "未经授权的自动化软件", "api.star-citizen.wiki", "CC BY-SA 4.0", "第三方许可.txt"):
        assert must in h, must
    info = S.about_info()
    names = {x["name"] for x in info["sources"]}
    assert {"SCMiner", "UEX", "Star Citizen Wiki API", "Star Citizen Wiki", "星际公民掉落查询", "SC汉化盒子"} <= names
    assert all(x["url"].startswith("https://") for x in info["sources"])
    assert "text" in S.third_party_licenses()


def test_pyro_place_names_from_localization():
    """2026-10-27 用户反馈：派罗很多空间站、星球显示成 PYR4-L1 这种代号。汉化包里都有正式名：
    有站的点用站名（RR_P1_L2 → 焰联-远程站-1-2），空点用点本身的叫法（派1 PYR1 L1）；星球、跳跃点也一样"""
    from sc_mining import position as P, navigate as n
    if not P.ini_name("RR_P2_L4"):
        pytest.skip("没有汉化包")
    assert P.place_name("RR_P2_L4") == "死局空间站"
    assert P.place_name("RR_P1_L2") == "焰联-远程站-1-2"
    assert P.place_name("RR_P3") == "轨道讣闻站" and P.place_name("RR_P6") == "废墟空间站"
    assert P.place_name("RR_P1_L1") == "派1 PYR1 L1"
    assert P.display_label("RR_P3_Clinic") == "轨道讣闻站"
    data = n.load()
    if data.get("points"):
        labels = [n.label(p) for p in data["points"] if p["sys"] in ("Pyro", "Stanton") and p["t"] != "AsteroidBelt"]
        assert all("（" in x for x in labels), [x for x in labels if "（" not in x]
        assert P.display_label("Pyro5d") == "法伊罗"


def test_poi_rule_names():
    """洞穴、前哨这类社区起的名字（汉化包里没有）按规则翻，编号原样保留"""
    from sc_mining.navigate import rule_zh
    assert rule_zh("Rock Cave #12, Fauna") == "岩石洞穴 #12（有动物）"
    assert rule_zh("Sand Cave #015 / Derelict Outpost #023") == "沙地洞穴 #015 / 废弃前哨站 #023"
    assert rule_zh("RL_Pyro3_col_m_drlct_otpst_occ_001") == "废弃前哨站（有人）001"
    assert rule_zh("Caterpillar Derelict 03 S1") == "毛虫残骸 03 S1"
    assert rule_zh("HDRSO-Bersch") == ""


def test_showlocation_keys_freed(monkeypatch, tmp_path):
    """2026-10-27 用户定：/showlocation 只在必要时用，「记录路标」「一键定位」默认不绑；老玩家存着的也清一次（之后自己绑的不再动）"""
    import json
    from sc_mining import settings
    from sc_mining.app import services as S
    f = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "FILE", f)
    assert settings.DEFAULTS["mark_key"] == "" and settings.DEFAULTS["fix_key"] == ""
    f.write_text(json.dumps({"agreed": True, "mark_key": "F7", "fix_key": "F9", "nav_mode": "space", "afk_v3": True, "afk_v4": True}), encoding="utf-8")
    cfg = settings.load()
    assert cfg["mark_key"] == "" and cfg["fix_key"] == "" and cfg["nav_mode"] == "auto" and cfg["keys_v5"]
    settings.update(fix_key="F11")
    assert settings.load()["fix_key"] == "F11"                       # 清过一次，后来自己绑的不动
    vals = {n: k for k, _, n in S._hotkey_values({**settings.DEFAULTS})}
    assert vals["mark_key"] == "" and vals["fix_key"] == "" and vals["trade_capture_key"] == "F8"
    monkeypatch.setattr(settings, "load", lambda: dict(settings.DEFAULTS))
    assert S.fix_key_hint() == ("", "在聊天框输入 /showlocation 定位")


def test_nav_marker_projection():
    """导航记号（2026-10-27）：目标投到屏幕上的位置；画面外贴边画箭头；不盖右上角调试信息；记号和瞄准环能画出来"""
    import math
    from sc_mining import navigate as n, overlay as o
    from sc_mining.displayinfo import parse, REGION
    assert parse(["CamDir: 23 9 -142 FOV: 78 Focal: 0.10"])["fov"] == 78
    assert parse(["CamDir: 23 9 -142 FOV: 999"])["fov"] is None
    W, H, cam = 2560, 1440, (0, 0, 0)                     # 镜头不转：朝 +y、头顶 +z
    p = n.project((0, 0, 0), cam, 78, (0, 1000, 0), W, H)
    assert p["on"] and abs(p["x"] - W / 2) < 0.5 and abs(p["y"] - H / 2) < 0.5 and p["off"] < 0.01
    p = n.project((0, 0, 0), cam, 78, (100, 1000, 0), W, H)
    assert p["on"] and p["x"] > W / 2 and abs(p["y"] - H / 2) < 0.5             # 右边
    up = math.tan(math.radians(39)) * 1000                                      # 正好在上边缘（上下视角 78°）
    p = n.project((0, 0, 0), cam, 78, (0, 1000, up * 0.999), W, H)
    assert p["on"] and p["y"] < 2
    p = n.project((0, 0, 0), cam, 78, (1000, 10, 0), W, H)
    assert not p["on"] and not p["behind"] and abs(p["angle"]) < 1                # 画面右边外面：箭头朝右
    x, y = o.edge_point(p["angle"], W, H, 70)
    assert abs(x - (W - 70)) < 1 and abs(y - H / 2) < 1
    p = n.project((0, 0, 0), cam, 78, (0, -1000, 0), W, H)
    assert p["behind"] and not p["on"] and abs(p["off"] - 180) < 0.1
    assert n.dist_text(512) == "512 m" and n.dist_text(12_345) == "12.3 km" and n.dist_text(3.2e9) == "3.2 Gm"
    # 不盖右上角那块
    x, y = o.avoid_box(W * 0.8, 10, 100, 60, W, H, REGION)
    assert y >= REGION[3] * H
    img, (ax, ay) = o.marker_image({"on": True, "label": "12.3 km"})
    assert img.width > 40 and 0 < ax < img.width
    img, _ = o.marker_image({"on": False, "angle": 135, "label": "1,234 km"})
    assert img.getbbox()
    assert o.ring_image({"off": 30, "angle": 45}).getbbox() and o.ring_image({"off": 170, "angle": -90, "behind": True}).getbbox()


def test_game_events_from_log(tmp_path):
    """游戏日志事件（2026-10-27，按老大 4.10.2 的真实日志行）：选量子目标、量子到达、管辖区、禁火区、监管区域、重生；
    只读打开以后新写的部分；游戏重开（日志变小）从头读"""
    from sc_mining.gamelog import GameEvents, EventTail
    L = ['<2026-10-24T10:46:36.173Z> [Notice] <Player Selected Quantum Target - Local> [ItemNavigation][CL][40004] | NOT AUTH | '
         'CRUS_Spirit_A1_899163362014[899163362014]|CSCItemNavigation::OnPlayerSelectedQuantumTarget|Player has selected point '
         'ab_collector_gas_Stanton4 as their destination, routing locally [Team_CGP4][QuantumTravel]',
         '<2026-10-24T10:47:40.133Z> [Notice] <Quantum Drive Arrived - Arrived at Final Destination> [ItemNavigation][CL][40004] | '
         'NOT AUTH | CRUS_Spirit_A1_899163362014[899163362014]|CSCItemNavigation::OnQuantumDriveArrived|Quantum Drive has arrived '
         'at final destination [Team_CGP4][QuantumTravel]',
         '<2026-10-26T14:53:31.492Z> [Notice] <SHUDEvent_OnNotification> Added notification "正在进入禁火区 - 禁止一切战斗行为: " [1] to queue.',
         '<2026-10-26T14:53:32.492Z> [Notice] <SHUDEvent_OnNotification> Added notification "已进入 微科公司 管辖区: " [1] to queue.',
         '<2026-10-26T14:53:33.492Z> [Notice] <SHUDEvent_OnNotification> Added notification "已离开监管区域: " [1] to queue.',
         '<2026-10-26T14:53:34.000Z> [Notice] <SHUDEvent_OnNotification> Added notification "合约共享：RSI 探索月" [1] to queue.',
         '<2026-10-26T14:55:00.000Z> [CSessionManager::OnClientSpawned] Spawned!']
    g = GameEvents()
    kinds = [e[1:] for line in L for e in g.feed(line)]
    assert kinds == [("qt_target", "ab_collector_gas_Stanton4"), ("qt_arrived", True), ("armistice", True),
                     ("jurisdiction", "微科公司"), ("monitored", False), ("spawn", True)]
    assert g.last["jurisdiction"][1] == "微科公司"
    log = tmp_path / "Game.log"
    log.write_text(L[0] + "\n", encoding="utf-8")
    tail = EventTail(log)
    assert tail.poll() == []                                   # 打开前的旧事件不算
    with open(log, "a", encoding="utf-8") as f:
        f.write(L[1] + "\n" + L[3][:40])                       # 半行：等写完
    assert [e[1] for e in tail.poll()] == ["qt_arrived"]
    with open(log, "a", encoding="utf-8") as f:
        f.write(L[3][40:] + "\n")
    assert [e[1] for e in tail.poll()] == ["jurisdiction"]
    log.write_text(L[1] + "\n", encoding="utf-8")              # 游戏重开：新日志更短
    assert [e[1] for e in tail.poll()] == ["qt_arrived"]


def test_city_nav(monkeypatch, tmp_path):
    """城内导航：读 city_places.json（坏行跳过、改了文件重读），按米显示、8 米内到达、上下楼层提示"""
    import json
    import os
    from sc_mining import navigate as n
    from sc_mining.app import services as S
    rows = [{"city": "NewBabbage", "body": "Microtech", "cat": "交易", "en": "TDD", "zh": "交易中心", "area": "广场",
             "x": 520.900, "y": 419.200, "z": 744.100},
            {"city": "NewBabbage", "body": "Microtech", "en": "坏的", "x": "abc", "y": 0, "z": 0},
            {"en": "缺字段"}]
    f = tmp_path / "city_places.json"
    f.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(n, "DATA", tmp_path)
    n._city.clear()
    ps = n.city_places()
    assert len(ps) == 1 and n.is_city(ps[0]) and ps[0]["city_zh"] == "新巴贝奇" and ps[0]["b"] == "Microtech"
    assert not n.is_city({"t": "Outpost"}) and not n.is_city(None)
    rows[0]["zh"] = "改过"
    f.write_text(json.dumps(rows[:1], ensure_ascii=False), encoding="utf-8")
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    assert n.city_places()[0]["zh"] == "改过"

    t = ps[0]
    r = math_r = (t["x"] ** 2 + t["y"] ** 2 + t["z"] ** 2) ** 0.5
    k = 1 - 0.012 / r                                             # 同一方向往下 12 米
    h = (t["x"] ** 2 + t["y"] ** 2) ** 0.5
    tx, ty = t["y"] / h, -t["x"] / h                              # 水平方向（和地心方向垂直）
    here = dict(body="Microtech", inside=True, x=t["x"] * k + 0.05 * tx, y=t["y"] * k + 0.05 * ty, z=t["z"] * k,
                lat=0.0, lon=0.0, height_m=0.0, radius_km=math_r)
    d, up = n.city_metrics(here, t)
    assert 45 < d < 60 and 10 < up < 14
    txt = n.city_text(here, t)
    assert " m" in txt and "上方" in txt and "km" not in txt
    assert n._short(here, t).startswith("朝 ")
    near = dict(here, x=t["x"] + 0.003 * tx, y=t["y"] + 0.003 * ty, z=t["z"])
    assert n.city_text(near, t).startswith("✅ 到了")
    flat = dict(here, x=t["x"] + 0.03 * tx, y=t["y"] + 0.03 * ty, z=t["z"])
    assert "楼" not in n.city_text(flat, t)
    assert n._short(dict(here, body="Hurston"), t).startswith("先量子跳到")

    monkeypatch.setattr(n, "here_text", lambda h, data: "")
    v = S._nav_view(here, t, {})
    assert v["city"] and not v["arrived"] and 45 < v["direct_m"] < 60 and v["updown"] > 10
    assert S._nav_view(near, t, {})["arrived"]
    n._city.clear()


def test_city_nav_review(monkeypatch, tmp_path):
    """Codex 二审城内导航的 5 个问题：同名地点串号、记号没校准、手动定位到达标准、坏数据、详情页叫人量子跳"""
    import json
    from datetime import datetime, timezone
    from sc_mining import navigate as n
    from sc_mining.app import services as S
    base = {"city": "NewBabbage", "body": "Microtech", "cat": "空港", "en": "ASOP", "zh": "ASOP 终端", "area": "空港"}
    rows = [dict(base, src="a", x=520.9, y=419.2, z=744.1), dict(base, src="b", x=520.95, y=419.2, z=744.1),
            dict(base, src="c", en=None, x=1, y=1, z=1), dict(base, src="d", cat=None, x=1, y=1, z=1),
            dict(base, src="e", x="NaN", y=1, z=1), "坏", None]
    (tmp_path / "city_places.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(n, "DATA", tmp_path)
    n._city.clear()
    ps = n.city_places()
    assert [p["id"] for p in ps] == ["a", "b", "d"] and ps[2]["cat"] == ""
    assert ps[0]["zh"] == "ASOP 终端" and ps[1]["zh"] == "ASOP 终端 2"
    k0, k1 = S._place_row(ps[0])["key"], S._place_row(ps[1])["key"]
    assert k0 != k1 and S._places[k1] is ps[1]

    t = ps[0]                                                       # 手动定位：100 米不算到，按米显示
    b = {"r": 1_000_000.0, "sys": "Stanton"}
    monkeypatch.setattr(n, "system_of", lambda g, data: "Stanton")
    monkeypatch.setattr(n, "to_local", lambda body, g, when: tuple(v / 1000 for v in g))
    data = {"bodies": {"Microtech": b}}
    g = (t["x"] * 1000 + 100.0, t["y"] * 1000, t["z"] * 1000)
    f = n.fix_guide([(1.0, g)], t, data)
    assert f["city"] and not f["arrived"] and 99 < f["direct"] * 1000 < 101
    txt = n.fix_text(f)
    assert "100 m" in txt and "km" not in txt
    g2 = (t["x"] * 1000 + 3.0, t["y"] * 1000, t["z"] * 1000)
    assert n.fix_guide([(1.0, g2)], t, data)["arrived"]

    monkeypatch.setattr(n, "to_global", lambda body, p, when: tuple(v * 1000 for v in p))
    here = dict(body="Microtech", x=t["x"] + 0.010, y=t["y"], z=t["z"])    # 游戏局部坐标：离目标 10 米
    g_game = (here["x"] * 1000 + 500.0, here["y"] * 1000, here["z"] * 1000)  # 星系坐标和推算差 500 米
    tg = n.target_global(t, data, 1.0, (g_game, here, 1.0))
    import math
    assert abs(math.dist(g_game, tg) - 10.0) < 0.01
    assert abs(math.dist(g_game, n.target_global(t, data, 1.0)) - 510.0) < 0.01

    monkeypatch.setattr(n, "load", lambda: data)
    monkeypatch.setattr(n, "latlon", lambda p: (0.0, 0.0, 1000.0))
    plan = S.nav_plan(k1)
    assert plan["city"] and plan["routes"] == [] and plan["area"] == "空港"
    n._city.clear()


def test_city_arrive_hysteresis_and_near():
    """2026-10-27 实测：到了在 7–9 米来回跳 → 进 8 米算到、出 15 米才算离开；15 米内不给转向角度"""
    from sc_mining import navigate as n
    assert n.city_arrived(7.5) and not n.city_arrived(9)
    assert n.city_arrived(12, before=True) and not n.city_arrived(16, before=True)
    t = {"b": "Microtech", "t": "City", "x": 520.9, "y": 419.2, "z": 744.1}
    h = (t["x"] ** 2 + t["y"] ** 2) ** 0.5
    tx, ty = t["y"] / h, -t["x"] / h
    here = dict(body="Microtech", inside=True, x=t["x"] + 0.012 * tx, y=t["y"] + 0.012 * ty, z=t["z"])
    assert n.city_text(here, t).startswith("就在附近 12 m")
    assert n.city_text(here, t, arrived=True).startswith("✅ 到了")
    far = dict(here, x=t["x"] + 0.05 * tx, y=t["y"] + 0.05 * ty)
    assert n.city_text(far, t).startswith("朝 ")


def test_feedback_upload_pack_send_retry(tmp_path, monkeypatch):
    """问题反馈自动发送（2026-10-27）：截图转 JPG 打包、发成写 .sent、服务器拒收不再重试、启动只补发 .pending 的"""
    import io
    import zipfile
    from PIL import Image
    from sc_mining import feedback_up as F, paths, settings
    monkeypatch.setattr(paths, "USER", tmp_path)
    monkeypatch.setattr(settings, "load", lambda: {"feedback_upload": True})
    monkeypatch.setenv("AT_FEEDBACK_OFF", "")                       # 网络已换成假的（下面 fake）
    fb = tmp_path / "feedback"

    def make(name):
        d = fb / name
        d.mkdir(parents=True)
        Image.new("RGB", (640, 360), (20, 40, 60)).save(d / "屏幕.png")
        (d / "说明.txt").write_text("x", encoding="utf-8")
        (d / "evil.exe").write_bytes(b"MZ")
        return d

    d = make("20261027_171313_auto")
    names = zipfile.ZipFile(io.BytesIO(F.pack(d))).namelist()
    assert sorted(names) == ["20261027_171313_auto/屏幕.jpg", "20261027_171313_auto/说明.txt"]
    sent = []

    class R:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=0):
        sent.append(req.headers)
        return R()
    monkeypatch.setattr(F.urllib.request, "urlopen", fake)
    F.mark_pending(d)
    assert F.send(d, "auto") == (True, "已发送", False)
    assert (d / ".sent").exists() and not (d / ".pending").exists()
    assert F.send(d, "auto")[0] and len(sent) == 1                     # 发过的不重复发
    assert len(F.install_id()) == 12 and F.install_id() == F.install_id()

    old = make("20261020_100000_scan")                                 # 没有 .pending 的旧反馈不补发
    new = make("20261027_180000_signal")
    F.mark_pending(new)
    assert F.retry_pending(fb) == 1 and (new / ".sent").exists() and not (old / ".sent").exists()

    bad = make("20261027_190000_item")
    F.mark_pending(bad)

    def reject(req, timeout=0):
        raise F.urllib.error.HTTPError(F.URL, 413, "too big", {}, None)
    monkeypatch.setattr(F.urllib.request, "urlopen", reject)
    ok, why, again = F.send(bad, "item")
    assert not ok and "413" in why and not again and not (bad / ".pending").exists()

    def down(req, timeout=0):
        raise OSError("down")
    monkeypatch.setattr(F.urllib.request, "urlopen", down)
    later = make("20261027_200000_auto")
    F.mark_pending(later)
    ok, why, again = F.send(later, "auto")
    assert not ok and again and (later / ".pending").exists()          # 连不上：留着下次发

    monkeypatch.setattr(settings, "load", lambda: {"feedback_upload": False})
    assert not F.enabled()
    monkeypatch.setattr(F.urllib.request, "urlopen", fake)
    n = len(sent)
    assert F.send(later, "auto")[1] == "自动发送已关闭" and len(sent) == n   # 关掉后排队的也不发
    assert F.retry_pending(fb) == 0 and len(sent) == n


def test_signal_harvestable_2000():
    """地面 2,000 的倍数是可采集物（植物、菌菇等）：老大 2026-10-27 实测 10,000 = 5 个"""
    from sc_mining import signals
    lines = signals.describe_all([(10000, False, "10000", None)], where="ground")
    assert lines == ["信号 10,000 → 可采集物 ×5（植物、菌菇等）"]


def test_displayinfo_yields_to_mining(monkeypatch):
    """采矿助手看着面板时，读位置字模认不出也不退回识别引擎（2026-10-27 录制：抢引擎让悬浮窗晚 10–18 秒）；
    强制读（判断地面/太空）照常用识别引擎"""
    from sc_mining import displayinfo as D, gridtext
    calls = []
    monkeypatch.setattr(gridtext, "ready", lambda h: True)
    monkeypatch.setattr(D, "_grid_read", lambda piece, h: None)
    monkeypatch.setattr(D, "_full_read", lambda piece, h: calls.append(1) or {**D.parse([]), "global": (1e7, 1e7, 1e7)})
    import sc_mining.perf as P
    from PIL import Image
    monkeypatch.setattr(P, "grab_region", lambda r: Image.new("RGB", (400, 300)))
    monkeypatch.setattr(P, "game_area", lambda: {"height": 1440})
    monkeypatch.setattr(D, "_YIELD", {"until": 0.0})
    D.yield_ocr(6)
    info = D.read()
    assert info.get("yielded") and not info["global"] and not calls
    r = D.Reader(every=1.0)
    monkeypatch.setattr("sc_mining.showloc.game_foreground", lambda: True)
    assert r.poll() is None and not calls and r.misses == 0                    # 让路不算没读到
    r.poll(force=True)
    assert calls == [1] and r.info and r.info["global"]                        # 强制读不让
    monkeypatch.setattr(D, "_YIELD", {"until": 0.0})
    assert not D.read().get("yielded")



def test_nav_nearest(monkeypatch, tmp_path):
    """导航「医院 / 空港 / 买船」找最近的（2026-10-27）：城里只找本城（取船终端 / 登记处优先），城外按星图里的站算距离；
    位置不知道只列出来；汉化名自带的英文不重复"""
    import json
    import time
    from sc_mining import navigate as n
    from sc_mining.app import services as S
    data = n.load()
    city = [{"city": "NewBabbage", "body": "Microtech", "cat": "医院", "en": "Hospital Check-In", "zh": "登记处",
             "src": "nb/checkin", "x": 520.900, "y": 419.200, "z": 744.100},
            {"city": "NewBabbage", "body": "Microtech", "cat": "医院", "en": "Pharmacy", "zh": "药店",
             "src": "nb/pharm", "x": 520.950, "y": 419.250, "z": 744.000},
            {"city": "Lorville", "body": "Hurston", "cat": "医院", "en": "Hospital Check-In", "zh": "登记处",
             "src": "lv/checkin", "x": -328.989, "y": -752.435, "z": 572.12}]
    amen = [{"en": "ARC-L1 Wide Forest Station", "zh": "弧 L1 广袤森林站", "kinds": ["医院", "空港"], "ref": {"point": "ARC L1"}},
            {"en": "Nowhere", "kinds": ["医院"], "ref": {"point": "不存在的点"}}, "坏行"]
    (tmp_path / "city_places.json").write_text(json.dumps(city, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "place_amenities.json").write_text(json.dumps(amen, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(n, "DATA", tmp_path)
    n._city.clear()
    n._amen.clear()
    now = time.time()
    arc = next(p for p in data["points"] if p["n"] == "ARC L1")
    g = (arc["x"] + 5000, arc["y"], arc["z"])
    hits = n.nearest("医院", g, "Stanton", now, data)
    assert hits[0][1]["n"] == "ARC-L1 Wide Forest Station" and 4000 < hits[0][0] < 6000
    assert n.label(hits[0][1]) == "弧 L1 广袤森林站（ARC-L1 Wide Forest Station）"
    assert {q["n"] for _, q in hits} == {"ARC-L1 Wide Forest Station", "Hospital Check-In"}      # 城里只要登记处，药店不列
    nb = next(q for q in n.city_places() if q["city"] == "NewBabbage" and q["cat"] == "医院" and q["n"] == "Hospital Check-In")
    g2 = n.target_global(nb, data, now)
    here = n.locate(g2, when=now)
    hits = n.nearest("医院", g2, "Stanton", now, data, here)
    assert [q["city"] for _, q in hits] == ["NewBabbage"] and hits[0][0] < 50          # 在城里：只找本城
    assert all(d is None for d, _ in n.nearest("医院", None, "", None, data))          # 不知道位置：只列出来
    assert n.label({"n": "Checkmate", "zh": "死局空间站 (Checkmate)", "t": "Orbital Station"}) == "死局空间站（Checkmate）"
    assert "error" in S.nav_near("加油")
    n._city.clear()
    n._amen.clear()


def test_city_route(monkeypatch, tmp_path):
    """城里分段路线（2026-10-27）：远了走到站台 → 坐地铁（同线直达 / 在共同的站换乘一次）→ 出站；近了直接走；
    只有一个站的线不算；当前步骤标 →"""
    import json
    from sc_mining import navigate as n

    def pt(x, y, z):
        return {"x": x, "y": y, "z": z}
    city = [dict(city="Lorville", body="Hurston", cat="地铁", en="A gate1", zh="地铁站台 · 城市大门 01（外环 A 线）", line="perim_line_a", stop="gate1", src="a1", **pt(-317.0, -756.5, 573.5)),
            dict(city="Lorville", body="Hurston", cat="地铁", en="A mc", zh="地铁站台 · 地铁中心（外环 A 线）", line="perim_line_a", stop="mc", src="amc", **pt(-328.9, -758.8, 564.0)),
            dict(city="Lorville", body="Hurston", cat="地铁", en="SP mc", zh="地铁站台 · 地铁中心（空港线）", line="sp_line", stop="mc", src="smc", **pt(-328.9, -758.85, 564.03)),
            dict(city="Lorville", body="Hurston", cat="地铁", en="SP sp", zh="地铁站台 · 蒂莎空港（空港线）", line="sp_line", stop="sp", src="ssp", **pt(-326.9, -758.6, 565.6)),
            dict(city="Lorville", body="Hurston", cat="地铁", en="CEN only", zh="地铁站台 · 列维斯登站（中央线）", line="cen_line", stop="lvsdn", src="c1", **pt(-329.0, -758.6, 564.2)),
            dict(city="Lorville", body="Hurston", cat="买船", en="New Deal", zh="全新交易", src="nd", **pt(-326.95, -758.65, 565.55)),
            dict(city="Lorville", body="Hurston", cat="空港", en="Gate1 ASOP", zh="1 号门取船", src="g1", **pt(-317.02, -756.52, 573.52))]
    (tmp_path / "city_places.json").write_text(json.dumps(city, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(n, "DATA", tmp_path)
    n._city.clear()
    ps = {q["n"]: q for q in n.city_places()}
    assert set(n._metro_lines("Lorville")) == {"perim_line_a", "sp_line"}           # 中央线只有一个站：不算

    def here_at(q, dx=0.0):
        return dict(body="Hurston", inside=True, x=q["x"] + dx, y=q["y"], z=q["z"], radius_km=1000.0, lat=0, lon=0, height_m=0)
    route = n.city_route(here_at(ps["Gate1 ASOP"]), ps["New Deal"])
    assert [a for a, *_ in route] == ["walk", "ride", "transfer", "ride"]
    assert route[1][1]["stop"] == "mc" and route[2][2] == "sp_line" and route[3][1]["stop"] == "sp"
    goal, steps = n.city_leg(here_at(ps["A gate1"]), ps["New Deal"])                 # 站在站台上：当前步骤是上车，指向下一站
    assert goal is ps["A mc"] and steps[1].startswith("→ 2. 坐 外环 A 线（Perimeter Line A） 到 地铁中心") and "换乘 空港线（Spaceport Line）" in steps[2]
    plan = {}                                                                         # 导航时：路线定下来按段走（二审 2026-10-27）
    far0 = here_at(ps["Gate1 ASOP"], dx=0.05)
    assert n.city_leg(far0, ps["New Deal"], plan)[0] is ps["A gate1"] and plan["i"] == 0
    route0 = plan["route"]
    assert n.city_leg(here_at(ps["A gate1"]), ps["New Deal"], plan)[0] is ps["A mc"] and plan["i"] == 1
    goal, steps = n.city_leg(here_at(ps["A gate1"], dx=0.01), ps["New Deal"], plan)  # 车开出去一点：还在这一段，不跳回第一步
    assert plan["route"] is route0 and plan["i"] == 1 and steps[1].startswith("→ 2.")
    assert n.city_leg(here_at(ps["A mc"]), ps["New Deal"], plan)[0] is ps["SP mc"] and plan["i"] == 2   # 到地铁中心：换乘
    assert n.city_leg(here_at(ps["SP mc"]), ps["New Deal"], plan)[0] is ps["SP sp"] and plan["i"] == 3  # 上了空港线
    goal, steps = n.city_leg(here_at(ps["SP sp"]), ps["New Deal"], plan)              # 坐到终点站：出站步行
    assert goal is ps["New Deal"] and steps[-1].startswith("→ 5. 出站步行到")
    assert "5. 出站步行到 全新交易" in steps[-1]
    far = here_at(ps["Gate1 ASOP"], dx=0.05)                                         # 离站台 50 米：当前步骤是走到站台
    assert n.city_leg(far, ps["New Deal"])[1][0].startswith("→ 1. 步行到")
    assert n.city_route(here_at(ps["SP sp"]), ps["New Deal"]) is None                  # 就在旁边：直接走
    assert n.city_leg(here_at(ps["SP sp"]), ps["New Deal"]) == (ps["New Deal"], [])
    n._city.clear()



def test_site_menu(monkeypatch, tmp_path):
    """主城 / 空间站里的分类菜单（2026-10-27）：拉格朗日点的站用星系坐标；离站 6 km 内算在站里，只列这个站的；
    按站自己的「上」分楼层；同一个站里重名才加编号；名字双语"""
    import json
    from sc_mining import navigate as n
    base = dict(city="rr_hur_l1", site_en="HUR-L1 Green Glade Station", site_zh="赫 L1 绿色林地站", body="", sys="Stanton",
                space=True, up=[0, 0, 1], area="")
    rows = [dict(base, cat="取船", kinds=["取船"], en="Fleet Manager Terminal", zh="舰队管理器终端", src="a", x=1000.0, y=0.0, z=0.0),
            dict(base, cat="商店", kinds=["吃喝"], en="Bar", zh="酒吧", src="b", x=1000.05, y=0.0, z=0.02),
            dict(base, cat="商店", kinds=["吃喝"], en="Bar", zh="酒吧", src="c", x=1000.2, y=0.0, z=0.0),
            dict(base, city="rr_hur_l2", cat="商店", kinds=["吃喝"], en="Bar", zh="酒吧", src="d", x=5000.0, y=0.0, z=0.0)]
    (tmp_path / "city_places.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(n, "DATA", tmp_path)
    n._city.clear()
    data = {"bodies": {}, "pois": [], "points": []}
    ps = n.city_places()
    assert [q["zh"] for q in ps] == ["舰队管理器终端", "酒吧", "酒吧 2", "酒吧"]          # 别的站的同名不加编号
    assert ps[0]["b"] == "@Stanton" and ps[0]["space"] and n.label(ps[1]) == "酒吧（Bar）"
    g = (1000_000.0, 0.0, 0.0)
    s = n.site_at(g, None, None, data)
    assert s["site"] == "rr_hur_l1" and s["kinds"] == ["取船", "吃喝"]
    assert n.site_at((1010_000.0, 0.0, 0.0), None, None, data) is None                   # 离站 10 km：不在站里
    near = n.site_nearest("rr_hur_l1", "吃喝", g, None, data)
    assert [q["id"] for _, q in near] == ["b", "c"] and round(near[0][0]) == 54
    assert "上方 20 米" in n.station_text(g, near[0][1], data)
    assert n.station_text(g, ps[0], data).startswith("✅ 到了")
    n._city.clear()

def test_train_data(monkeypatch, tmp_path):
    """帮助改进识别（2026-10-27）：被汉化包纠正的名字那一行存成「小截图 + 正确答案」；认对的只抽一部分；
    开关关了不存；每天有上限；跑测试时不发"""
    import json
    from PIL import Image
    from sc_mining import train_data as T, settings, paths
    from sc_mining.trade.models import OcrToken
    monkeypatch.setattr(paths, "USER", tmp_path)
    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    monkeypatch.setattr(T, "maybe_send", lambda force=False: None)
    img = Image.new("RGB", (400, 200), "black")
    toks = [OcrToken("塔维因战争服役微记（完好）", 90.0, (20, 30, 240, 22)), OcrToken("体积：173uSCU", 90.0, (20, 56, 100, 18))]
    T.from_tooltip(img, toks, ("塔维因战争服役微记（完好）", ""), ("塔维因战争服役徽记（完好）", "Tevarin War Service Marker (Pristine)"))
    js = sorted((tmp_path / "train").glob("*.json"))
    assert len(js) == 1
    rec = json.loads(js[0].read_text(encoding="utf-8"))
    assert rec["truth"] == "塔维因战争服役徽记（完好）" and rec["ocr"] == "塔维因战争服役微记（完好）"
    with Image.open(tmp_path / "train" / rec["img"]) as im:
        assert im.size == (248, 30)                       # 那一行四周各多 4 像素
    monkeypatch.setattr(T.random, "random", lambda: 0.99)  # 认对的：抽不中就不存
    assert not T.add_line(img, (20, 56, 100, 18), "体积", "体积")
    assert not T.add_line(img, (20, 56, 100, 400), "很高", "很髙")   # 不像一行字
    settings.update(train_upload=False)
    assert not T.add_line(img, (20, 56, 100, 18), "关了", "关子")
    settings.update(train_upload=True)
    monkeypatch.setattr(T, "DAY_MAX", 1)
    assert not T.add_line(img, (20, 56, 100, 18), "今天满了", "今天满子")
    # 一包不超过服务器的 60 个文件；服务器拒收（4xx）当天不再发（二审 2026-10-27）
    import io as _io
    import zipfile
    import urllib.error
    monkeypatch.setattr(T, "DAY_MAX", 1000)
    for k in range(T.BATCH + 5):
        assert T.add_line(img, (20, 56, 100, 18), f"第{k}条", f"弟{k}条")
    monkeypatch.setattr(T, "enabled", lambda: True)
    got = {}

    def fake_open(req, timeout=None):
        got["body"] = req.data
        raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, None)
    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    T._send_batch()
    with zipfile.ZipFile(_io.BytesIO(got["body"])) as z:
        names = z.namelist()
    assert 0 < len(names) <= 60 and all(n.startswith("train/") and n.count("/") == 1 for n in names)
    assert T._refused_today()
    T.clear()                                             # 关掉开关：本地攒着的删掉
    assert not list((tmp_path / "train").glob("*.png")) and not list((tmp_path / "train").glob("*.json"))


def test_rotation_phase_calibration(tmp_path, monkeypatch):
    """右上角同时给了星系坐标和星球坐标 → 反推自转相位：算回来和原值一样；连续两次一致才写文件；写了以后 rotation_deg 用校准值"""
    import math
    from datetime import datetime, timezone
    from sc_mining import navigate as n
    monkeypatch.setattr(n, "CALIB", tmp_path / "rotation_calib.json")
    n._calib.update(stamp=None, data={}, pending={})
    n._offsets.clear()
    d = n.load()
    b, name = d["bodies"]["Microtech"], "Microtech"
    when = datetime(2026, 10, 28, 1, 0, tzinfo=timezone.utc)
    p = (68.364, 64.276, -996.49)                                   # 新巴贝奇附近（星球坐标，千米）
    a = (360 - n.rotation_deg(b, when)) / n.R2D
    c, s = math.cos(-a), math.sin(-a)
    lx, ly = p[0] * 1000, p[1] * 1000
    g = (b["x"] + lx * c - ly * s, b["y"] + lx * s + ly * c, b["z"] + p[2] * 1000)
    assert abs(n.phase_from(b, g, p, when) - b["adj"]) < 1e-6
    assert n.phase_from(b, g, (p[0], p[1], p[2] + 5), when) is None  # 高度对不上：不信
    # 假装游戏里的相位比表里多 1°：第一次只记着，第二次一致才采用
    shifted = (360 - (n.rotation_deg(b, when) + 1.0)) / n.R2D
    c2, s2 = math.cos(-shifted), math.sin(-shifted)
    g2 = (b["x"] + lx * c2 - ly * s2, b["y"] + lx * s2 + ly * c2, b["z"] + p[2] * 1000)
    assert not n._calibrate(name, b, g2, p, when) and not n.CALIB.exists()   # 第一次只记着
    assert n._calibrate(name, b, g2, p, when) is True and n.CALIB.exists()
    assert abs(n._ang_diff(n.rotation_deg(b, when), (n.rotation_deg({**b, "name": ""}, when) + 1.0) % 360)) < 1e-4   # 文件里存 5 位小数
    assert math.dist(n.to_local(b, g2, when), p) < 0.01             # 校准后推算的位置和游戏给的一致
    n._calib.update(stamp=None, data={}, pending={})
