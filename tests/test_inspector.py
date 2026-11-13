"""物品视觉识别组件 (Item Inspector) 独立测试"""

import unittest
from unittest.mock import patch, MagicMock  # noqa: F401

from astral_toolkit.ocr import OcrToken


class MockImage:
    def __init__(self, width=1000, height=1000):
        self.size = (width, height)
        self.width = width
        self.height = height

    def crop(self, box):
        w = box[2] - box[0]
        h = box[3] - box[1]
        return MockImage(w, h)


class TestItemInspector(unittest.TestCase):
    def test_import_and_helpers(self):
        from astral_toolkit.trade.inspector import (
            HOVER_REGIONS,  # noqa: F401
            get_hover_regions,
            parse_qlabel,
            parse_count,
            tooltip_quality,
            tooltip_row,
            _is_mineral,
        )

        # 测试区域切分
        regions = get_hover_regions((800, 500), 1000)
        self.assertEqual(regions[0][4], "50-70%")

        # 测试角标与数字解析
        self.assertEqual(parse_qlabel("575Q"), 575)
        self.assertEqual(parse_qlabel("0Q"), 0)
        self.assertEqual(parse_qlabel("9070"), 907)  # Q 认错成 0
        self.assertEqual(parse_count("200x"), 200)
        self.assertEqual(parse_count("5X"), 5)
        self.assertIsNone(parse_count("200/200"))

        # 测试品质与矿物行
        tok_q = OcrToken(text="品质：650", confidence=0.99, box=(100, 50, 80, 20))
        self.assertEqual(tooltip_quality([tok_q]), 650)

        tok_row_zh = OcrToken(
            text="塔兰导电石", confidence=0.99, box=(100, 50, 100, 20)
        )
        tok_row_q = OcrToken(text="925", confidence=0.99, box=(210, 50, 40, 20))
        tok_row_amt = OcrToken(text="0.495 SCU", confidence=0.99, box=(260, 50, 80, 20))
        q, amt = tooltip_row([tok_row_zh, tok_row_q, tok_row_amt])
        self.assertEqual(q, 925)
        self.assertEqual(amt, 0.495)

        # 测试矿物判定
        self.assertTrue(_is_mineral("塔兰导电石", "Taranite"))
        self.assertFalse(_is_mineral("能量突击步枪", "P4-AR Rifle"))

    @patch("astral_toolkit.trade.inspector._read_tooltip")
    def test_inspect_item_miss(self, mock_read):
        from astral_toolkit.trade.inspector import inspect_item

        mock_read.return_value = ([], None, "整屏")
        res = inspect_item(MockImage(), (500, 500))
        self.assertIsNone(res)

    @patch("astral_toolkit.trade.inspector._read_tooltip")
    def test_inspect_item_mineral(self, mock_read):
        from astral_toolkit.trade.inspector import inspect_item

        toks = [
            OcrToken(text="塔兰导电石", confidence=0.99, box=(100, 50, 100, 20)),
            OcrToken(text="925", confidence=0.99, box=(210, 50, 40, 20)),
            OcrToken(text="0.495 SCU", confidence=0.99, box=(260, 50, 80, 20)),
        ]
        mock_read.return_value = (toks, ("塔兰导电石", "Taranite"), "30-50%")
        res = inspect_item(MockImage(), (200, 500))
        self.assertIsNotNone(res)
        self.assertEqual(res["zh"], "塔兰导电石")
        self.assertEqual(res["en"], "Taranite")
        self.assertEqual(res["quality"], 925)
        self.assertEqual(res["qty"], 0.495)
        self.assertEqual(res["unit"], "SCU")
        self.assertEqual(res["where"], "30-50%")

    @patch("astral_toolkit.trade.inspector.cell_labels")
    @patch("astral_toolkit.trade.inspector._read_tooltip")
    def test_inspect_item_normal_with_cell(self, mock_read, mock_cell):
        from astral_toolkit.trade.inspector import inspect_item

        toks = [
            OcrToken(text="医疗笔", confidence=0.99, box=(100, 50, 80, 20)),
        ]
        mock_read.return_value = (toks, ("医疗笔", "MedPen"), "整屏")
        mock_cell.return_value = (None, 5)  # 5 个
        res = inspect_item(MockImage(), (500, 500))
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res["zh"], "医疗笔")
        # 有汉化包时纠正成 MedPens；本机没数据包时 canonical 对不上，英文仍是 OCR 的 MedPen
        self.assertIn(res["en"], ("MedPen", "MedPens"))
        self.assertEqual(res["quality"], 0)  # 普通物品无品质默认为 0
        self.assertEqual(res["qty"], 5)
        self.assertEqual(res["unit"], "个")

    @patch(
        "astral_toolkit.tasks.count._ocr", return_value=[]
    )  # 盘点自己认 count.tooltip（11-09）：假图不认字
    @patch("astral_toolkit.trade.inspector.inspect_item")
    def test_count_read_item(self, mock_inspect, _mock_ocr):
        from astral_toolkit.tasks.count import _read_item

        mock_inspect.return_value = {
            "zh": "测试物品",
            "en": "Test Item",
            "quality": 500,
            "qty": 2,
            "unit": "个",
            "sure": True,
            "craft": None,
        }
        res = _read_item(MockImage(), (100, 100))
        self.assertEqual(res["zh"], "测试物品")
        self.assertEqual(res["quality"], 500)
        self.assertEqual(res["qty"], 2)

    def test_tooltip_title_and_anchor(self):
        from astral_toolkit.trade.inspector import (
            tooltip_pick,
            tooltip_name,
            plausible_name,
            _is_anchor,
        )

        # 测试锚点行识别
        self.assertTrue(_is_anchor("体积：13000 uSCU"))
        self.assertTrue(_is_anchor("Manufacturer: Aegis"))
        self.assertTrue(_is_anchor("物品类型：武器"))
        self.assertFalse(_is_anchor("容量：1.00SCU"))
        self.assertFalse(_is_anchor("剩余容量：100%"))

        # 测试名称合法性校验
        self.assertTrue(plausible_name("能量突击步枪", "P4-AR Rifle"))
        self.assertFalse(plausible_name("OUTPOST", "OUTPOST"))  # 地点大写
        self.assertFalse(plausible_name("短", "A"))  # 字数不足
        self.assertFalse(plausible_name("聊天：你好", "Hello: World"))  # 含冒号

        # 测试说明框标题与中英对提取
        T = lambda text, x, y: OcrToken(  # noqa: E731
            text=text, confidence=0.9, box=(x, y, max(20, len(text) * 9), 18)
        )  # noqa: E731
        toks = [
            T("实准枪口补偿器2", 900, 300),
            T("VeraCompensator2", 900, 324),
            T("体积：20uSCU", 900, 348),
        ]
        name, sure = tooltip_pick(toks, (960, 540))
        self.assertEqual(name, ("实准枪口补偿器2", "VeraCompensator2"))
        self.assertTrue(sure)
        self.assertEqual(
            tooltip_name(toks, (960, 540)), ("实准枪口补偿器2", "VeraCompensator2")
        )

        # 聊天和非说明框杂字应被排除
        chat = [
            T("[全局]RevtheWanderer:", 40, 700),
            T("thewayifigureditoutwasgoingoutsie", 40, 724),
        ]
        self.assertIsNone(tooltip_pick(chat, (960, 540))[0])

    def test_fold_deduplication(self):
        # matching._fold 在 names._fold_en 的基础上再把 l 统一成 i：OCR 常把罗马数字 II 认成 ll，
        # 比较 OCR 认出的名字和市场名字时要当成一样（1.1.1 的行为）；所以和 _fold_en 不再完全相同
        from astral_toolkit.trade.matching import _fold as matching_fold
        from astral_toolkit.trade.names import _fold_en

        self.assertEqual(
            matching_fold("P4-AR Rifle (Custom)"),
            _fold_en("P4-AR Rifle (Custom)").replace("l", "i"),
        )
        self.assertEqual(matching_fold("Omnisky II"), "omniskyii")
        self.assertEqual(matching_fold("Omnisky ll"), matching_fold("Omnisky II"))
        self.assertEqual(_fold_en("Omnisky ll"), "omniskyll")  # names._fold_en 本身不变


def test_inspect_item_raw_and_canon(monkeypatch):
    """返回里带纠正前的名字 raw 和汉化包标准名 canon；没对上时 canon 为 None"""
    from astral_toolkit.trade import inspector, names

    toks = [OcrToken("医疗芼", 90, (100, 50, 80, 20))]
    monkeypatch.setattr(
        inspector,
        "_read_tooltip",
        lambda img, cur: (toks, ("医疗芼", "MedPenn"), "30-50%"),
    )
    monkeypatch.setattr(inspector, "cell_labels", lambda *a, **k: (None, 1))
    monkeypatch.setattr(names, "canonical", lambda zh, en: ("医疗笔", "MedPen"))
    res = inspector.inspect_item(MockImage(), (200, 500))
    assert (
        res["raw"] == ("医疗芼", "MedPenn")
        and res["canon"] == ("医疗笔", "MedPen")
        and res["sure"]
    )
    assert (res["zh"], res["en"]) == ("医疗笔", "MedPen")
    monkeypatch.setattr(names, "canonical", lambda zh, en: None)
    res = inspector.inspect_item(MockImage(), (200, 500))
    assert (
        res["raw"] == ("医疗芼", "MedPenn") and res["canon"] is None and not res["sure"]
    )


def test_hover_sends_raw_and_canon_to_train_data(monkeypatch):
    """F8 收错题：传给 train_data.from_tooltip 的是「认成了什么」和「应该是什么」两组名字"""
    import types
    from astral_toolkit import bootstrap
    from astral_toolkit.tasks import hover as Hv
    from astral_toolkit.system import train_data

    toks = [OcrToken("医疗芼", 90, (100, 50, 80, 20))]
    res = {
        "zh": "医疗笔",
        "en": "MedPen",
        "quality": 0,
        "qty": 1,
        "unit": "个",
        "sure": True,
        "craft": None,
        "tokens": toks,
        "where": "30-50%",
        "raw": ("医疗芼", "MedPenn"),
        "canon": ("医疗笔", "MedPen"),
    }
    started = []

    class FakeThread:
        def __init__(self, target=None, args=(), kwargs=None, **_):
            self.target, self.args = target, args

        def start(self):
            started.append((self.target, self.args))

    monkeypatch.setattr(Hv, "WIN", False)

    def _inspect(img, cur, **kw):
        cb = kw.get("on_identified")
        if cb and res.get("sure"):
            cb(
                {
                    "zh": res["zh"],
                    "en": res["en"],
                    "sure": True,
                    "raw": res["raw"],
                    "canon": res["canon"],
                    "where": res["where"],
                }
            )
        return dict(res)

    monkeypatch.setattr(Hv, "inspect_item", _inspect)
    monkeypatch.setattr(Hv, "item_info", lambda *a, **k: {})
    monkeypatch.setattr(Hv, "_item_hud", lambda *a, **k: None)
    monkeypatch.setattr(Hv, "_hover_lines", lambda *a, **k: [])
    monkeypatch.setattr(
        Hv,
        "bus",
        types.SimpleNamespace(
            publish=lambda *a, **k: None,
            runtime_log=lambda *a, **k: None,
            update_preview=lambda *a, **k: None,
        ),
    )
    monkeypatch.setattr(Hv.threading, "Thread", FakeThread)
    img = MockImage()
    assert Hv.hover_once(bootstrap._hover_links(), img)["ok"]
    sent = [a for t, a in started if t is train_data.from_tooltip]
    assert sent == [(img, toks, ("医疗芼", "MedPenn"), ("医疗笔", "MedPen"))]
    res.update(canon=None, sure=False)  # 汉化包里没对上：不收
    started.clear()
    Hv.hover_once(bootstrap._hover_links(), img)
    assert not [a for t, a in started if t is train_data.from_tooltip]


def test_craft_override_for_count(monkeypatch):
    """F6 盘点（craft_override=True）：加成和蓝图完全对上就用倒推的品质和各槽品质；F8 默认格子上读到品质就不倒推"""
    from astral_toolkit.trade import inspector
    from astral_toolkit.crafting import crafting

    toks = [OcrToken("能量突击步枪", 90, (100, 50, 80, 20))]
    slots = [{"slot": "Frame", "q": 700}]
    monkeypatch.setattr(
        inspector,
        "_read_tooltip",
        lambda img, cur: (toks, ("能量突击步枪", "P4-AR Rifle"), "30-50%"),
    )
    monkeypatch.setattr(inspector, "cell_labels", lambda *a, **k: (500, 1))
    monkeypatch.setattr(crafting, "parse_mods", lambda t: ["mod"])
    monkeypatch.setattr(crafting, "for_item", lambda en, zh: "bp")
    monkeypatch.setattr(
        crafting,
        "solve_slots",
        lambda bp, mods: {"exact": True, "avg": 700, "slots": slots},
    )
    f8 = inspector.inspect_item(MockImage(), (200, 500))
    assert f8["quality"] == 500 and f8["craft"] is None
    f6 = inspector.inspect_item(MockImage(), (200, 500), craft_override=True)
    assert f6["quality"] == 700 and f6["craft"] == slots
    monkeypatch.setattr(
        crafting,
        "solve_slots",
        lambda bp, mods: {"exact": False, "avg": 600, "slots": slots},
    )
    f6 = inspector.inspect_item(MockImage(), (200, 500), craft_override=True)
    assert f6["quality"] == 500 and f6["craft"] is None  # 对不上蓝图：格子上的品质照用


def test_count_read_item_uses_craft_override(monkeypatch):
    from astral_toolkit.trade import inspector
    from astral_toolkit.tasks.count import _read_item

    from astral_toolkit.tasks import count

    seen = {}
    monkeypatch.setattr(
        count, "_ocr", lambda *a: ["字"]
    )  # 盘点自己认 count.tooltip（11-09）
    monkeypatch.setattr(inspector, "tooltip_pick", lambda *a: (None, False))
    monkeypatch.setattr(
        inspector, "inspect_item", lambda img, cur, **kw: seen.update(kw) or {"zh": "x"}
    )
    _read_item(MockImage(), (1, 1))
    assert seen["craft_override"] is True
    assert seen["tokens"] == ["字"] and seen["where"] == "盘点说明框"
    assert seen["body_box"] == count._tooltip_boxes((1000, 1000))[0]


def test_stage_regions_order_and_boxes():
    """高度阶段 × 宽度条带的裁切顺序、像素框、native 标记（纯函数，不认图）"""
    from astral_toolkit.trade.inspector import (
        BODY_Y0,
        BODY_Y1,
        HEIGHT_STAGES,
        TITLE_Y0,
        TITLE_Y1,
        get_stage_regions,
        region_box,
    )

    assert TITLE_Y0 == 0.24 and TITLE_Y1 == 0.30  # 2026-11-13 收紧标题带
    assert BODY_Y0 == 0.24 and BODY_Y1 == 0.70
    assert [s[2] for s in HEIGHT_STAGES] == ["title", "body"]
    assert [(s[0], s[1]) for s in HEIGHT_STAGES] == [(0.24, 0.30), (0.24, 0.70)]
    assert [s[3] for s in HEIGHT_STAGES] == [True, False]  # 只有标题带按原尺寸认

    regions = [(0.30, 0.0, 0.50, 1.0, "30-50%"), (0.30, 0.0, 0.70, 1.0, "30-70%")]
    got = get_stage_regions(regions, 1000, 1000)
    assert [label for _box, label, _stage, _native in got] == [
        "30-50%@title",
        "30-70%@title",
        "30-50%@body",
        "30-70%@body",
    ]
    assert [box for box, *_ in got] == [
        (300, 240, 500, 300),
        (300, 240, 700, 300),
        (300, 240, 500, 700),
        (300, 240, 700, 700),
    ]
    assert [native for *_, native in got] == [True, True, False, False]

    assert region_box("50-70%@body", 1000, 1000) == (500, 240, 700, 700)
    assert region_box("整屏", 1000, 1000) == (0, 0, 1000, 1000)
    assert region_box("30-50%", 1000, 1000) == (300, 0, 500, 1000)  # 旧标签按全高
    assert region_box("30-50%@nope", 1000, 1000) is None
    assert region_box(None, 1000, 1000) is None


def _tiny_names(monkeypatch):
    """汉化包名字表换成一小组：canonical / canonical_exact 都只用它（不受本机数据包影响）"""
    from astral_toolkit.trade import names

    t = {"实准枪口补偿器2": "VeraCompensator2"}
    zh_map = {names._norm_zh(zh): (zh, en) for zh, en in t.items()}
    en_map = {names._fold_en(en): (zh, en) for zh, en in t.items()}
    monkeypatch.setattr(names, "table", lambda: t)
    monkeypatch.setattr(names, "_index", lambda: (zh_map, en_map))
    monkeypatch.setattr(names, "_from_items", lambda en, strict=False: None)
    return names


def test_canonical_title_english_fuzzy_unique(monkeypatch):
    """F8 标题带停不停（canonical_title）：英文≥0.9 且唯一算高把握；中文弱模糊不算；英文太糊不算；
    canonical_exact 不做模糊（配物品、盘点用，11-12 合 PR #18 后收窄）"""
    names = _tiny_names(monkeypatch)
    t = {
        "实准枪口补偿器2": "VeraCompensator2",
        "高精度瞄准镜": "PrecisionScopeAdvanced",
    }
    zh_map = {names._norm_zh(zh): (zh, en) for zh, en in t.items()}
    en_map = {names._fold_en(en): (zh, en) for zh, en in t.items()}
    monkeypatch.setattr(names, "_index", lambda: (zh_map, en_map))
    assert names.canonical_exact("实准枪口补偿器2") == (
        "实准枪口补偿器2",
        "VeraCompensator2",
    )  # 中文规整精确
    # 英文 OCR 错两个字母、末尾没有尺寸：标题带可停，但 canonical_exact 不算
    assert names.canonical_title("", "PrecisionScopeAdvancad") == (
        "高精度瞄准镜",
        "PrecisionScopeAdvanced",
    )
    assert names.canonical_exact("", "PrecisionScopeAdvancad") is None
    # 丢了末尾的尺寸「2」：差的正是尺寸，标题带也不停（接着放大认）
    assert names.canonical_title("实准枪口补偿器", "VeraCompensato") is None
    # 中文弱模糊（缺「2」）且英文太糊：不算高把握
    assert names.canonical_title("实准枪口补偿器", "VeraCompens") is None
    assert names.canonical("实准枪口补偿器") == (
        "实准枪口补偿器2",
        "VeraCompensator2",
    )  # 完整 canonical 的中文模糊档照旧能用（放大后再纠正）
    assert names.canonical_exact("実准", "VeraCompensator2") == (
        "实准枪口补偿器2",
        "VeraCompensator2",
    )  # 中文认错、英文精确兜
    assert names.canonical_exact("塔兰导电石", "Taranite") == (
        "塔兰导电石",
        "Taranite",
    )  # 矿物精确
    assert names.canonical_exact() is None and names.canonical_title() is None


def test_canonical_title_keeps_roman_size(monkeypatch):
    """只差罗马数字的两件（Ignite I / II）：Ignite Il（l 当 I 是 II）不能模糊成 Ignite I；
    末尾罗马数字一样才走模糊档（老大 11-09：尺寸是关键数据，不许认错）"""
    names = _tiny_names(monkeypatch)
    t = {"点火I": "Ignite I", "点火II": "Ignite II", "抑制器III": "Suppressor III"}
    zh_map = {names._norm_zh(zh): (zh, en) for zh, en in t.items()}
    en_map = {names._fold_en(en): (zh, en) for zh, en in t.items()}
    monkeypatch.setattr(names, "_index", lambda: (zh_map, en_map))
    assert names._size_tail("Ignite Il") == ("r", "II")
    assert names._size_tail("VeraCompensator2") == ("d", "2")
    assert names._size_tail("Ignite") is None
    for ocr in ("Ignit I", "Ignitr II", "Igmite Il"):
        hit = names.canonical_title("", ocr)
        assert hit is None or names._size_tail(hit[1]) == names._size_tail(ocr), ocr
    assert names.canonical_title("", "Supressor III") == ("抑制器III", "Suppressor III")
    assert names.canonical_title("", "Supressor II") is None


def test_js500_english_code_is_en_name():
    """短型号英文（JS-500 / CQ7 / TS-2）也算英文名行；S1 太短不当名"""
    from astral_toolkit.trade import inspector

    assert inspector._is_en_name("JS-500")
    assert inspector._is_en_name("CQ7")
    assert inspector._is_en_name("TS-2")
    assert inspector._is_en_name("MedPen")
    assert not inspector._is_en_name("体积")
    assert not inspector._is_en_name("S1")  # 太短，不当物品名


def test_tooltip_pick_keeps_js500_english(monkeypatch):
    """无汉化中文名的型号：中文类别行 + JS-500 要能抽成英文名；只有 JS-500 也能成名"""
    from astral_toolkit.trade import inspector

    zh = OcrToken("发电机", 90, (100, 40, 80, 16))
    en = OcrToken("JS-500", 90, (100, 58, 80, 16))
    name, sure = inspector.tooltip_pick([zh, en], cursor=(100, 50))
    assert name == ("发电机", "JS-500")
    assert sure is False

    name_only, sure_only = inspector.tooltip_pick([en], cursor=(100, 50))
    assert name_only == ("", "JS-500")
    assert sure_only is False

    vol = OcrToken("体积", 90, (100, 100, 80, 16))
    name_a, sure_a = inspector.tooltip_pick([zh, en, vol], cursor=(100, 50))
    assert name_a == ("发电机", "JS-500")
    assert sure_a is True


def test_strong_canonical_hits_item_catalog_english(monkeypatch):
    """汉化包没有中文名时：物品目录英文精确也算标题带「库精确」"""
    from astral_toolkit.trade import inspector, names

    _tiny_names(monkeypatch)  # 汉化包里没有 JS-500
    monkeypatch.setattr(
        names,
        "_from_items",
        lambda en, strict=False: (
            ("", "JS-500") if (en or "").strip().upper() == "JS-500" else None
        ),
    )

    assert inspector._strong_canonical(("", "JS-500")) == ("", "JS-500")
    assert inspector._strong_canonical(("发电机", "JS-500")) == ("", "JS-500")
    assert inspector._strong_canonical(("", "NOT-A-ITEM")) is None


def test_title_band_stops_on_item_catalog_english(monkeypatch):
    """标题带认出 JS-500 且物品目录精确命中：停在 @title，不放大到整屏"""
    from astral_toolkit import ocr
    from astral_toolkit.trade import inspector, names

    _tiny_names(monkeypatch)
    monkeypatch.setattr(
        names,
        "_from_items",
        lambda en, strict=False: (
            ("", "JS-500") if (en or "").strip().upper() == "JS-500" else None
        ),
    )

    calls = []

    def fake_recognize(img, urgent=False, offset=(0, 0), native=False):
        calls.append((offset, native, img.size))
        # 标题带相对裁切坐标；offset 会加回整图
        return [
            OcrToken("JS-500", 90, (offset[0] + 20, offset[1] + 20, 80, 16)),
        ]

    monkeypatch.setattr(ocr, "recognize", fake_recognize)
    img = MockImage(2560, 1440)
    # 鼠标在右侧：首选 70-100% 条带
    tokens, name, where = inspector._read_tooltip(img, (2000, 400), whole_screen=True)
    assert name == ("", "JS-500")
    assert where.endswith("@title")
    assert len(calls) == 1  # 标题带一次就停，不进说明框带 / 全高 / 整屏


def test_cell_labels_reuse_respects_height_stage(monkeypatch):
    """角标复用看区域标签的高度阶段：body 圈住就复用；标题窄带圈不住就重新认"""
    from astral_toolkit.trade import inspector

    toks = [OcrToken(text="医疗笔", confidence=0.99, box=(390, 470, 80, 20))]
    seen = []
    monkeypatch.setattr(
        inspector,
        "cell_labels",
        lambda img, cur, tokens=None: seen.append(tokens) or (None, 1),
    )
    monkeypatch.setattr(inspector, "_tooltip_body_tokens", lambda *a, **k: None)
    monkeypatch.setattr(
        inspector,
        "_read_tooltip",
        lambda img, cur: (toks, ("医疗笔", "MedPen"), "30-50%@body"),
    )
    inspector.inspect_item(MockImage(), (400, 500))
    assert seen == [toks]  # 说明框带 24%~70% 把 (400,500) 圈住了：复用

    seen.clear()
    monkeypatch.setattr(
        inspector,
        "_read_tooltip",
        lambda img, cur: (toks, ("医疗笔", "MedPen"), "30-50%@title"),
    )
    inspector.inspect_item(MockImage(), (400, 500))
    assert seen == [None]  # 标题带只有 24%~36%，不含鼠标那格：重新认一块小图

    seen.clear()
    inspector.inspect_item(MockImage(), (400, 200))
    assert seen == [None]  # (400,200) 在标题带停下且 body 补扫被关掉：角标另裁


def test_crafted_item_keeps_bonus_lines_after_title_hit(monkeypatch):
    """标题带停下的制造品：加成行在说明框正文（标题带外），按同一宽度条带补认一次，倒推品质不丢"""
    from astral_toolkit import ocr
    from astral_toolkit.trade import inspector
    from astral_toolkit.crafting import crafting

    title = [
        OcrToken("能量突击步枪", 90, (350, 40, 100, 18)),
        OcrToken("P4-AR Rifle", 90, (350, 64, 100, 18)),
    ]
    body = title + [
        OcrToken("体积：20uSCU", 90, (350, 120, 100, 18)),
        OcrToken("武器伤害 +5%", 90, (350, 600, 100, 18)),
    ]
    crops = []
    monkeypatch.setattr(
        ocr,
        "recognize",
        lambda img, urgent=False, offset=(0, 0), native=False: (
            crops.append((offset, img.size)) or body
        ),
    )
    monkeypatch.setattr(
        inspector,
        "_read_tooltip",
        lambda img, cur: (title, ("能量突击步枪", "P4-AR Rifle"), "30-50%@title"),
    )
    monkeypatch.setattr(inspector, "cell_labels", lambda *a, **k: (None, 1))
    slots = [{"slot": "Frame", "q": 700}]
    monkeypatch.setattr(
        crafting,
        "parse_mods",
        lambda toks: ["mod"] if any("+" in t.text for t in toks) else [],
    )
    monkeypatch.setattr(crafting, "for_item", lambda en, zh: "bp")
    monkeypatch.setattr(
        crafting,
        "solve_slots",
        lambda bp, mods: {"exact": True, "avg": 700, "slots": slots},
    )
    res = inspector.inspect_item(MockImage(), (400, 500))
    assert res is not None
    assert res["quality"] == 700 and res["craft"] == slots
    # 只补认说明框带那一条（同一宽度条带 30%~50%，屏高 24%~70%），不是旧的全高竖条
    assert crops == [((300, 240), (200, 460))]
    assert res["tokens"] is body  # 日志 / 收错题用补认到的那份（字更全）


def test_no_extra_scan_when_no_blueprint_or_bonus_in_tokens(monkeypatch):
    """标题带停下且无品质会补扫 body；已有品质字样 / 非标题带停下则不再补扫"""
    from astral_toolkit import ocr
    from astral_toolkit.trade import inspector
    from astral_toolkit.crafting import crafting

    title = [
        OcrToken("能量突击步枪", 90, (350, 40, 100, 18)),
        OcrToken("P4-AR Rifle", 90, (350, 64, 100, 18)),
    ]
    calls = []
    monkeypatch.setattr(ocr, "recognize", lambda *a, **k: calls.append(1) or title)
    monkeypatch.setattr(
        inspector,
        "_read_tooltip",
        lambda img, cur: (title, ("能量突击步枪", "P4-AR Rifle"), "30-50%@title"),
    )
    monkeypatch.setattr(inspector, "cell_labels", lambda *a, **k: (None, 1))
    monkeypatch.setattr(crafting, "parse_mods", lambda toks: [])
    monkeypatch.setattr(
        crafting, "for_item", lambda en, zh: None
    )  # 没有蓝图：不是制造品
    res = inspector.inspect_item(MockImage(), (400, 500))
    assert res is not None
    # 标题带无品质 → 补扫 body 一次找品质；body 也没有则默认 0
    assert calls == [1] and res["quality"] == 0 and res["craft"] is None

    # 标题带已有品质字样：不补扫
    calls.clear()
    title_q = title + [OcrToken("品质：650", 90, (350, 88, 80, 16))]
    monkeypatch.setattr(
        inspector,
        "_read_tooltip",
        lambda img, cur: (title_q, ("能量突击步枪", "P4-AR Rifle"), "30-50%@title"),
    )
    slots = [{"slot": "Frame", "q": 700}]
    monkeypatch.setattr(crafting, "parse_mods", lambda toks: ["mod"])
    monkeypatch.setattr(crafting, "for_item", lambda en, zh: "bp")
    monkeypatch.setattr(
        crafting,
        "solve_slots",
        lambda bp, mods: {"exact": True, "avg": 700, "slots": slots},
    )
    res = inspector.inspect_item(MockImage(), (400, 500), craft_override=True)
    assert res is not None
    assert calls == [] and res["quality"] == 700 and res["craft"] == slots

    # 不是标题带停下的：说明框已认过，绝不能再补认
    monkeypatch.setattr(crafting, "parse_mods", lambda toks: [])
    for where in ("30-50%@body", "30-50%@full", "整屏", "30-50%", None):
        monkeypatch.setattr(
            inspector,
            "_read_tooltip",
            lambda img, cur, w=where: (title, ("能量突击步枪", "P4-AR Rifle"), w),
        )
        res = inspector.inspect_item(MockImage(), (400, 500), craft_override=True)
        assert res is not None and calls == [], where
        assert res["tokens"] is title, where  # 没用补认的那份，还是原来识别到的


def test_debug_mode_logs_read_tooltip_path(monkeypatch):
    """调试模式开着：_read_tooltip 每档裁切与停因记进调试日志文件（logs/debug_日期.log）；关着不记。
    细节只进文件、不进窗口运行日志（2026-11-08 老大定）"""
    from astral_toolkit import ocr
    from astral_toolkit.app import bus
    from astral_toolkit.core import day_logs, settings
    from astral_toolkit.trade import inspector

    lines = []
    shown = []
    monkeypatch.setattr(
        bus,
        "runtime_log",
        lambda line, tag="SYS", level="INFO": shown.append(str(line)),
    )
    monkeypatch.setattr(
        day_logs, "write", lambda kind, line: lines.append(f"{kind}|{line}")
    )
    monkeypatch.setattr(
        inspector,
        "get_hover_regions",
        lambda cursor, width: [(0.3, 0.0, 0.5, 1.0, "30-50%")],
    )
    monkeypatch.setattr(
        inspector,
        "get_stage_regions",
        lambda regions, W, H: [
            ((0, 0, 100, 50), "30-50%@title", "title", True),
        ],
    )
    tok_zh = OcrToken(text="塔兰导电石", confidence=99, box=(10, 10, 80, 16))
    tok_en = OcrToken(text="Taranite", confidence=99, box=(10, 30, 80, 16))
    monkeypatch.setattr(ocr, "recognize", lambda *a, **k: [tok_zh, tok_en])
    monkeypatch.setattr(
        inspector, "tooltip_pick", lambda *a, **k: (("塔兰导电石", "Taranite"), True)
    )
    monkeypatch.setattr(
        inspector, "_strong_canonical", lambda name: ("塔兰导电石", "Taranite")
    )

    monkeypatch.setattr(settings, "load", lambda: {"debug_mode": False})
    inspector._read_tooltip(MockImage(1000, 1000), (400, 500))
    inspector._dbg("关着时直接调也不记")
    assert lines == [] and shown == []

    lines.clear()
    monkeypatch.setattr(settings, "load", lambda: {"debug_mode": True})
    toks, name, where = inspector._read_tooltip(MockImage(1000, 1000), (400, 500))
    assert name == ("塔兰导电石", "Taranite") and where == "30-50%@title"
    assert lines and all(x.startswith("debug|") for x in lines)
    blob = "\n".join(lines)
    assert "识别路径开始" in blob
    assert "30-50%@title" in blob
    assert "停·库精确" in blob
    assert shown == []  # 细节只进文件，不进窗口运行日志


def test_debug_mode_default_off():
    from astral_toolkit.core import settings

    assert settings.DEFAULTS.get("debug_mode") is False


def test_on_identified_fires_before_quality_ocr(monkeypatch):
    """sure 后、body/角标之前回调；未 sure 不回调。"""
    from astral_toolkit.trade import inspector
    from astral_toolkit.trade import names

    order = []
    monkeypatch.setattr(
        inspector,
        "_read_tooltip",
        lambda *a, **k: (
            [OcrToken("医疗笔", 90, (100, 50, 80, 20))],
            ("医疗笔", "MedPen"),
            "30-50%@title",
        ),
    )
    monkeypatch.setattr(names, "canonical", lambda zh, en: ("医疗笔", "MedPen"))
    monkeypatch.setattr(inspector, "_is_mineral", lambda *a, **k: False)
    monkeypatch.setattr(
        inspector,
        "_tooltip_body_tokens",
        lambda *a, **k: order.append("body") or [],
    )
    monkeypatch.setattr(
        inspector,
        "cell_labels",
        lambda *a, **k: order.append("cell") or (500, 2),
    )

    def on_id(p):
        order.append(("id", p["zh"], p["en"]))

    res = inspector.inspect_item(MockImage(), (200, 500), on_identified=on_id)
    assert res is not None
    assert res["quality"] == 500 and res["qty"] == 2
    assert order[0] == ("id", "医疗笔", "MedPen")
    assert "body" in order and "cell" in order
    assert order.index(("id", "医疗笔", "MedPen")) < order.index("body")
    assert order.index(("id", "医疗笔", "MedPen")) < order.index("cell")

    order.clear()
    monkeypatch.setattr(names, "canonical", lambda zh, en: None)
    res = inspector.inspect_item(MockImage(), (200, 500), on_identified=on_id)
    assert res is not None and not res["sure"]
    assert not any(x[0] == "id" for x in order if isinstance(x, tuple))


def test_should_abort_stops_inspect(monkeypatch):
    """should_abort 为真时 inspect_item 返回 None，不跑角标。"""
    from astral_toolkit.trade import inspector
    from astral_toolkit.trade import names

    monkeypatch.setattr(
        inspector,
        "_read_tooltip",
        lambda *a, **k: (
            [OcrToken("医疗笔", 90, (100, 50, 80, 20))],
            ("医疗笔", "MedPen"),
            "30-50%@title",
        ),
    )
    monkeypatch.setattr(names, "canonical", lambda zh, en: ("医疗笔", "MedPen"))
    cells = []
    monkeypatch.setattr(
        inspector, "cell_labels", lambda *a, **k: cells.append(1) or (0, 1)
    )
    assert (
        inspector.inspect_item(MockImage(), (200, 500), should_abort=lambda: True)
        is None
    )
    assert cells == []


if __name__ == "__main__":
    unittest.main()
