"""交易界面：查价、F8 悬停识别、物品说明框、市场价（从 test_tools.py 拆出，CL-C3）"""

from datetime import datetime
from datetime import timezone
from decimal import Decimal as D
from astral_toolkit.trade import console as C
from astral_toolkit.trade import inspector as trade_inspector
from astral_toolkit.trade import market_text as trade_market_text
from astral_toolkit.trade import matching as trade_matching
from astral_toolkit.trade.models import Item
from astral_toolkit.trade.models import PriceKey
from astral_toolkit.trade.models import PriceStats
from astral_toolkit.trade.models import ProviderResult
from astral_toolkit.ocr import OcrToken
import time


class Uex:
    source = "uex"

    def lookup(self, q):
        return [Item("uex:4741", "Carinite")] if q in ("Carinite",) else []

    def fetch(self, item, qg, op, now):
        return ProviderResult(
            "uex",
            "ok",
            (
                PriceStats(
                    PriceKey("uex", item.id, qg, "UEC", "scu", "4.3", op),
                    D(5000),
                    D(4200),
                    3,
                    now,
                    D(4800),
                ),
            ),
            items=(item,),
        )


class Scm:
    source = "scm"

    def lookup(self, q):
        return [Item("scm:43475", "Carinite")] if q in ("科力晶", "Carinite") else []

    def fetch(self, item, qg, op, now):
        return ProviderResult("scm", "empty", message="没有挂牌")


class _FakeClient:
    """不联网的假 HTTP：按网址路径返回 JSON，记下请求了哪些"""

    def __init__(self, handler, delay=0.0):
        self.handler, self.delay, self.calls = handler, delay, []

    def get(self, url, params=None, headers=None, timeout=15):
        import json, time  # noqa: E401, F811
        from astral_toolkit.trade.providers.http import _Response

        self.calls.append((url, dict(params or {})))
        time.sleep(self.delay)
        return _Response(200, {}, json.dumps(self.handler(url, params or {})))

    def close(self):
        pass


def test_trade_lookup_chinese(tmp_path):
    """查价（窗口、F8 都走 Trade.lookup）：中文名两家都查得到（原来夹在命令行查价那条测试里，F 段 B3 拆出来）"""
    t = C.Trade(tmp_path, [Uex(), Scm()])
    items, _ = t.lookup("科力晶")
    assert {i.id for i in items} == {"uex:4741", "scm:43475"}


def test_quality_parse():
    assert (
        C._quality("650") == "exact:650"
        and C._quality("q6") == "q6"
        and C._quality("") is None
    )
    assert (
        trade_market_text._group("exact:650") == "q3"
        and trade_market_text._group("unknown") == "q0"
    )


def test_tooltip_name_from_hover_box():
    # 按用户截图里的说明框排版（2K）：名字两行，下面是「体积」
    toks = [
        OcrToken("极限抬升-II“棱脊”牵引光束", 95, (615, 287, 160, 16)),
        OcrToken('MaxLift-II "Keelback" Tractor', 95, (615, 305, 158, 16)),
        OcrToken("体积：16862 uSCU", 95, (615, 322, 95, 16)),
        OcrToken("制造商：灰猫工业 (Greycat Industrial)", 95, (615, 358, 200, 16)),
        OcrToken("60/60", 95, (106, 818, 40, 16)),
    ]
    assert trade_inspector.tooltip_name(toks) == (
        "极限抬升-II“棱脊”牵引光束",
        'MaxLift-II "Keelback" Tractor',
    )
    assert (
        trade_inspector.tooltip_name([OcrToken("60/60", 95, (106, 818, 40, 16))])
        is None
    )


def test_match_tooltip_prefers_truncated_english(tmp_path):
    class U:
        source = "uex"

        def lookup(self, q):
            return (
                [
                    Item("uex:9", 'MaxLift-II "Keelback" Tractor Beam'),
                    Item("uex:8", "MaxLift Tractor Beam"),
                ]
                if "MaxLift" in q
                else []
            )

        def fetch(self, *a):
            return ProviderResult("uex", "empty")

    t = C.Trade(tmp_path, [U()])
    item, _ = trade_matching.match_tooltip(
        t, "极限抬升-II“棱脊”牵引光束", 'MaxLift-II "Keelback" Tractor'
    )
    assert item.id == "uex:9"


def test_tooltip_real_ocr_output():
    # 用户截图实际识别结果（含聊天窗口、库存面板的干扰文字，II 被认成 ll、空格丢了）
    T = lambda text, x, y: OcrToken(text, 90, (x, y, max(20, len(text) * 9), 18))  # noqa: E731
    toks = [
        T("个人/全部", 310, 135),
        T("容量：", 340, 182),
        T("0/59K", 455, 186),
        T("移动所有", 214, 182),
        T("直接输入物品名就能查价，中文、英文都行", 822, 103),
        T("极限抬升-II“棱脊”牵引光束", 615, 287),
        T('MaxLift-ll"Keelback"Tractor', 615, 305),
        T("体积：16862uSCU", 615, 322),
        T("回复", 796, 298),
    ]
    assert trade_inspector.tooltip_name(toks, (690, 450)) == (
        "极限抬升-II“棱脊”牵引光束",
        'MaxLift-ll"Keelback"Tractor',
    )


def test_match_tolerates_ocr_noise(tmp_path):
    class U:
        source = "uex"

        def lookup(self, q):
            return (
                [
                    Item("uex:9", 'MaxLift-II "Keelback" Tractor Beam'),
                    Item("uex:8", "MaxLift Tractor Beam"),
                ]
                if q.startswith("MaxLift")
                else []
            )

        def fetch(self, *a):
            return ProviderResult("uex", "empty")

    t = C.Trade(tmp_path, [U()])
    item, _ = trade_matching.match_tooltip(
        t, "极限抬升-II“棱脊”牵引光束", 'MaxLift-ll"Keelback"Tractor'
    )
    assert item.id == "uex:9"


def test_tooltip_skips_description_lines():
    # 实测：飞行服说明框（描述句子 + 墙上的英文标语 STAND CLEAR 不能当成名字）
    T = lambda text, x, y: OcrToken(text, 90, (x, y, max(20, len(text) * 9), 18))  # noqa: E731
    toks = [
        T("太阳-I飞行服飞行员", 800, 100),
        T("Sol-IllFlightSuitAviator", 800, 120),
        T("体积：23000uSCU", 800, 140),
        T("物品类型：飞行服", 800, 175),
        T("设计，同时融入了现代的舒适性。", 800, 600),
        T("这款飞行员版主体采用黄绿色搭配浅绿色的装饰。", 800, 630),
        T("STAND CLEAR", 805, 650),
    ]
    assert trade_inspector.tooltip_name(toks, (820, 640)) == (
        "太阳-I飞行服飞行员",
        "Sol-IllFlightSuitAviator",
    )


def test_unrelated_search_results_dropped(tmp_path):
    junk = [
        Item(f"scm:{n}", name)
        for n, name in enumerate(
            ['A03 "Scorched" Sniper Rifle', "Abrade Scraper Module", "Council Scrip"]
        )
    ]

    class S:
        source = "scm"

        def lookup(self, q):
            return junk + (
                [Item("scm:99", "CQ7 Rifle")] if q in ("CQ7 Rifle", "CQ7") else []
            )

        def fetch(self, *a):
            return ProviderResult("scm", "empty")

    t = C.Trade(tmp_path, [S()])
    item, cands = trade_matching.match_tooltip(t, "CQ7步枪", "CQ7Rifle")
    assert item.id == "scm:99" and all("Scrip" not in c.name for c in cands)

    class N(S):
        def lookup(self, q):
            return junk

    item, cands = trade_matching.match_tooltip(
        C.Trade(tmp_path / "x", [N()]), "CQ7步枪", "CQ7Rifle"
    )
    assert item is None and cands == []


def test_tooltip_name_food_without_english_name():
    """食物说明框只有中文名，下面是「NDR:20 免疫下降」「剩余容量：100%」这类属性行，不能当名字（实测 肉串）"""
    from astral_toolkit.ocr import OcrToken

    T = lambda text, x, y: OcrToken(text, 90, (x, y, max(20, len(text) * 9), 18))  # noqa: E731
    toks = [
        T("Zone:P2_L4Pos:-11023.9564km", 1960, 22),
        T("Current player location :RR P2 L4 CLINIC(LZ:R P24)", 2160, 200),
        T("肉串", 864, 374),
        T("NDR:20免疫下降", 864, 398),
        T("体积：0uSCU", 864, 422),
        T("剩余容量：100%", 864, 444),
        T("NDR:20", 864, 488),
        T("效果：免疫下降", 864, 512),
        T("一根烤串，上面有着大块大块的肯定是肉的东西。", 864, 558),
        T("60/60", 140, 1056),
    ]
    assert trade_inspector.tooltip_name(toks, (900, 500)) == ("肉串", "")


def test_hud_market_min_max_mean_and_hide_empty():
    from decimal import Decimal as D
    from types import SimpleNamespace as N
    from astral_toolkit.trade.market_text import hud_market

    key = N(source="uex")
    st = lambda mn, mean, wk=None: N(key=key, minimum=mn, mean=mean, week_mean=wk)  # noqa: E731
    q = lambda p: N(key=key, price=D(p))  # noqa: E731
    r = lambda stats, quotes=(): N(source="uex", stats=stats, quotes=quotes)  # noqa: E731
    assert (
        hud_market([r([st(None, D(12000))], [q(9500), q(20000)])])
        == "UEX 已知最低 9,500｜最高 20,000｜均价 12,000"
    )
    assert (
        hud_market([r([st(D(9000), None, D(11000))])])
        == "UEX 最低 9,000｜7天均价 11,000"
    )
    assert (
        hud_market([r([st(None, None)]), N(source="scm", stats=(), quotes=())]) == ""
    )  # 没数据：不显示


def test_hover_overlay_updates_before_network(monkeypatch, tmp_path):
    """F8：名字和本机数据先上悬浮窗，联网的（市场匹配、查价、掉落）在后台；后台慢也不耽误悬浮窗"""
    import threading  # noqa: E401
    from PIL import Image
    from astral_toolkit import bootstrap
    from astral_toolkit.tasks import (
        hover as t_hover,
        navigation as t_nav,
        system as t_sys,
    )
    from astral_toolkit.app import hud_state
    from astral_toolkit.tasks import trade as t_trade
    from astral_toolkit.trade import console as C
    from astral_toolkit.ocr import OcrToken

    T = lambda text, x, y: OcrToken(text, 90, (x, y, max(20, len(text) * 9), 18))  # noqa: E731
    toks = [
        T("CQ7步枪", 1368, 367),
        T("CQ7Rifle", 1368, 391),
        T("体积：13000uSCU", 1368, 414),
    ]
    calls = []
    monkeypatch.setattr(
        "astral_toolkit.ocr.recognize",
        lambda img, urgent=False, offset=(0, 0), native=False: (
            calls.append((img.size, urgent)) or toks
        ),
    )
    gate = threading.Event()
    monkeypatch.setattr(
        trade_matching, "match_tooltip", lambda *a, **k: (gate.wait(5), (None, []))[1]
    )  # 联网很慢
    monkeypatch.setattr(trade_inspector, "_hover_log", lambda *a, **k: None)
    monkeypatch.setattr(
        trade_inspector, "_cursor_on_image", lambda img: (1280, 720)
    )  # 不看真鼠标在哪
    monkeypatch.setattr(
        t_trade, "trade", lambda: C.Trade(tmp_path, [])
    )  # 后台线程不开真实库存库、没有联网的价格源
    # 照生产接法：市场会话、报价、掉落走 tasks/catalog
    monkeypatch.setattr(
        "astral_toolkit.tasks.catalog_queries.loot.info", lambda *a, **k: {}
    )  # 掉落查询也不联网
    shown = []

    class Hud:
        def set(self, sec, text):
            shown.append((time.time(), text))

    _v = lambda: Hud()  # noqa: E731
    for _m in (t_nav, t_sys, hud_state):
        monkeypatch.setattr(_m, "_hud", _v)
    t0 = time.time()
    try:
        r = t_hover.hover_once(bootstrap._hover_links(), Image.new("RGB", (2560, 1440)))
        assert r["ok"] and shown[-1][1].startswith(
            ("CQ7步枪", "CQ7 步枪")
        )  # 名字按汉化包纠正成标准写法（1.6.37）
        assert shown[-1][0] - t0 < 2.0  # 没等联网
        # 鼠标在 50%：先认左边 30%~50% 的标题带（屏高 24%~36%、native=True），插队识别
        assert calls[0] == ((512, 173), True)
    finally:
        gate.set()
        for th in threading.enumerate():  # 后台线程在补丁还原前跑完
            if th.name == "hover-more":
                th.join(5)


def test_match_tooltip_uses_local_catalog_without_network(tmp_path):
    from astral_toolkit.trade import console as C
    from astral_toolkit.trade.models import Item

    class Boom:
        source = "uex"

        def lookup(self, q):
            raise AssertionError("不该联网")

        def fetch(self, *a):
            raise AssertionError("不该联网")

    t = C.Trade(tmp_path / "x", [Boom()])
    t.catalog.upsert([Item("u1", "CQ7 Rifle", None)])
    item, _ = trade_matching.match_tooltip(t, "CQ7步枪", "CQ7Rifle")
    assert item.id == "u1"
    t.catalog.add_alias("u1", "CQ7步枪")
    item, _ = trade_matching.match_tooltip(
        t, "CQ7步枪", "乱码"
    )  # 认过的中文名：直接对上
    assert item.id == "u1"


def test_scm_orders_downloaded_once_and_pages_in_parallel():
    from astral_toolkit.trade.models import Item
    from astral_toolkit.trade.providers.http import HttpTransport
    from astral_toolkit.trade.providers.scm import ScmProvider

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
    assert len(pages) == 5 and first < 0.2 * 5  # 5 页：第 1 页后其余 4 页一起下
    p.fetch(Item("scm:2", "B"), "q0", "sell", now)  # 换个物品：挂单列表直接用上次的
    assert len([c for c in client.calls if "orders/page" in c[0]]) == 5


def test_market_sources_are_queried_at_the_same_time(tmp_path):
    from astral_toolkit.trade.market_service import MarketService
    from astral_toolkit.trade.models import Item, ProviderResult
    from astral_toolkit.trade.storage import Database

    class Slow:
        def __init__(self, source):
            self.source = source

        def fetch(self, *a):
            time.sleep(0.4)
            return ProviderResult(self.source, "empty")

    s = MarketService(Database(tmp_path / "m.db"), [Slow("uex"), Slow("scm")])
    t = time.time()
    r = s.refresh(
        Item("a", "A"), "q0", "sell", datetime(2026, 10, 20, tzinfo=timezone.utc)
    )
    assert [x.source for x in r] == ["uex", "scm"]
    assert time.time() - t < 0.7  # 两个各 0.4 秒，同时查


def test_tooltip_anchor_tolerates_missing_char():
    from astral_toolkit.ocr import OcrToken

    T = lambda text, x, y: OcrToken(text, 90, (x, y, max(20, len(text) * 9), 18))  # noqa: E731
    toks = [
        T("CQ7步枪", 1368, 367),
        T("CQ7Rifle", 1368, 391),
        T("体：13000uSCU", 1368, 414),
        T("1网灵领童第卖枪", 1368, 900),
        T("Artington-Warchpoint' Rille", 1368, 924),
    ]
    name, sure = trade_inspector.tooltip_pick(
        toks, (1400, 950)
    )  # 鼠标离下面的对比列表更近，也要选说明框标题
    assert name == ("CQ7步枪", "CQ7Rifle") and sure


def test_hover_ignores_chat_hud_and_markers(monkeypatch):
    """F8 物品识别：全局聊天「[全局]某人：…」、飞船 HUD、地点标记不能当成物品（2026-10-23 用户日志）；
    整屏找的时候必须名字下面紧跟「体积/制造商/物品类型…」才算说明框"""
    from PIL import Image
    from astral_toolkit import ocr
    from astral_toolkit.ocr import OcrToken
    from astral_toolkit.tasks import hover as t_hover

    T = lambda text, x, y: OcrToken(text, 90, (x, y, max(20, len(text) * 9), 18))  # noqa: E731
    chat = [
        T("[全局]RevtheWanderer:", 40, 700),
        T("thewayifigureditoutwasgoingoutsie", 40, 724),
        T("[全局]Omnicidal-Kitten：", 40, 760),
        T("LAMP ON", 40, 784),
    ]
    marker = [T("拉亚利-坎特韦尔研究站", 900, 300), T("OUTPOST", 900, 324)]
    hud = [
        T("Zone: RSI_Perseus Pos:", 1500, 40),
        T("Zone: SolarSystem Pos: 22477025km", 1500, 64),
    ]
    assert trade_inspector.tooltip_pick(chat, (960, 540))[0] is None
    assert trade_inspector.tooltip_pick(chat + hud, (960, 540))[0] is None
    name, sure = trade_inspector.tooltip_pick(marker, (960, 540))
    assert not sure  # 地点标记：下面没有「体积」之类，不算说明框
    item = [
        T("实准枪口补偿器2", 900, 300),
        T("VeraCompensator2", 900, 324),
        T("体积：20uSCU", 900, 348),
    ]
    assert trade_inspector.tooltip_pick(chat + item, (960, 540)) == (
        ("实准枪口补偿器2", "VeraCompensator2"),
        True,
    )
    # 新识别机制：标题带 24%~36% → 说明框带 24%~70% × 宽度条带；不再全高/整屏
    STAGE_CROPS = 4  # 2 个高度阶段 × 2 个宽度条带
    calls = []

    def fake(img, urgent=False, offset=(0, 0), native=False):
        calls.append(offset)
        return chat + marker + hud

    monkeypatch.setattr(ocr, "recognize", fake)
    img = Image.new("RGB", (1920, 1080))
    toks, name, where = t_hover._read_tooltip(img, (100, 540))
    assert name is None and len(calls) == STAGE_CROPS
    assert "整屏" not in str(where)
    calls.clear()
    # 标题带两个条带没认到，说明框带看到完整说明框（英文下面紧跟体积）就停
    monkeypatch.setattr(
        ocr,
        "recognize",
        lambda img, urgent=False, offset=(0, 0), native=False: (
            [] if not calls.append(1) and len(calls) <= 2 else chat + item
        ),
    )
    toks, name, where = t_hover._read_tooltip(img, (100, 540))
    assert name == ("实准枪口补偿器2", "VeraCompensator2") and where == "30-50%@body"
    # 鼠标在中间：级联跑完仍无名字，也不整屏
    calls.clear()

    def fake_nothing(img, urgent=False, offset=(0, 0), native=False):
        calls.append(offset)
        return []

    monkeypatch.setattr(ocr, "recognize", fake_nothing)
    toks, name, where = t_hover._read_tooltip(img, (960, 540))
    assert name is None and len(calls) == STAGE_CROPS


def test_hover_unsure_names_and_anchor_lines():
    """2026-10-23 全量样本测试发现：中间没把握时会把碎字（「力 mnoc」）、地点标记、系统界面当物品；
    靠「体积」往上找名字时会把「制造商：灰猫工业」当名字"""
    from astral_toolkit.ocr import OcrToken

    T = lambda text, x, y: OcrToken(text, 90, (x, y, max(20, len(text) * 9), 18))  # noqa: E731
    assert trade_inspector.plausible_name("受辐射的瓦拉卡蛋", "IradiatedValakkar Egg")
    for zh, en in [
        ("力", "mnoc"),
        ("加力", "mnoo"),
        ("拉正利-收特书尔研究站", "BAYARCANTWELLBESE"),
        ("未知", "2Lokgr"),
        ("北极星需要外部货梯或者超大机库才能卸货", "Rabbit (id:Fiendmcy)"),
        ("天之神", "·Roberts"),
    ]:
        assert not trade_inspector.plausible_name(zh, en), (zh, en)
    toks = [
        T("制造商：灰猫工业（GreycatIndustrial)", 900, 280),
        T("体积：16862uSCU", 900, 304),
    ]
    name, sure = trade_inspector.tooltip_pick(toks, (960, 540))
    assert not name or "制造商" not in name[0]
    toks = [
        T("必事A20", 900, 256),
        T("制造商：必事", 900, 280),
        T("体积：600uSCU", 900, 304),
    ]
    assert trade_inspector.tooltip_pick(toks, (960, 540))[0][0] == "必事A20"
