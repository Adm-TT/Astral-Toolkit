"""物品视觉识别组件 (Item Inspector) 独立测试"""

import unittest
from unittest.mock import patch, MagicMock  # noqa: F401

from sc_mining.trade.models import OcrToken


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
        from sc_mining.trade.inspector import (
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

    @patch("sc_mining.trade.inspector._read_tooltip")
    def test_inspect_item_miss(self, mock_read):
        from sc_mining.trade.inspector import inspect_item

        mock_read.return_value = ([], None, "整屏")
        res = inspect_item(MockImage(), (500, 500))
        self.assertIsNone(res)

    @patch("sc_mining.trade.inspector._read_tooltip")
    def test_inspect_item_mineral(self, mock_read):
        from sc_mining.trade.inspector import inspect_item

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

    @patch("sc_mining.trade.inspector.cell_labels")
    @patch("sc_mining.trade.inspector._read_tooltip")
    def test_inspect_item_normal_with_cell(self, mock_read, mock_cell):
        from sc_mining.trade.inspector import inspect_item

        toks = [
            OcrToken(text="医疗笔", confidence=0.99, box=(100, 50, 80, 20)),
        ]
        mock_read.return_value = (toks, ("医疗笔", "MedPen"), "整屏")
        mock_cell.return_value = (None, 5)  # 5 个
        res = inspect_item(MockImage(), (500, 500))
        self.assertIsNotNone(res)
        self.assertEqual(res["zh"], "医疗笔")
        # 汉化包里这件商品写作「医疗笔MedPens」（items_commodities_medPens），纠正后英文名是 MedPens
        self.assertEqual(res["en"], "MedPens")
        self.assertEqual(res["quality"], 0)  # 普通物品无品质默认为 0
        self.assertEqual(res["qty"], 5)
        self.assertEqual(res["unit"], "个")

    @patch("sc_mining.trade.inspector.inspect_item")
    def test_count_read_item(self, mock_inspect):
        from sc_mining.tasks.count import _read_item

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
        from sc_mining.trade.inspector import (
            tooltip_pick,
            tooltip_name,
            plausible_name,
            _is_anchor,
        )
        from sc_mining.trade.console import tooltip_pick as console_tooltip_pick

        # 确保向后兼容重导出一致
        self.assertIs(tooltip_pick, console_tooltip_pick)

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
        # console._fold 在 names._fold_en 的基础上再把 l 统一成 i：OCR 常把罗马数字 II 认成 ll，
        # 比较 OCR 认出的名字和市场名字时要当成一样（1.1.1 的行为）；所以和 _fold_en 不再完全相同
        from sc_mining.trade.console import _fold as console_fold
        from sc_mining.trade.names import _fold_en

        self.assertEqual(
            console_fold("P4-AR Rifle (Custom)"),
            _fold_en("P4-AR Rifle (Custom)").replace("l", "i"),
        )
        self.assertEqual(console_fold("Omnisky II"), "omniskyii")
        self.assertEqual(console_fold("Omnisky ll"), console_fold("Omnisky II"))
        self.assertEqual(_fold_en("Omnisky ll"), "omniskyll")  # names._fold_en 本身不变


def test_inspect_item_raw_and_canon(monkeypatch):
    """返回里带纠正前的名字 raw 和汉化包标准名 canon；没对上时 canon 为 None"""
    from sc_mining.trade import inspector, names

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
    from sc_mining.tasks import hover as Hv
    from sc_mining.system import train_data

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
    monkeypatch.setattr(Hv, "_off", lambda k: None)
    monkeypatch.setattr(Hv, "inspect_item", lambda img, cur: dict(res))
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
    assert Hv.hover_once(img)["ok"]
    sent = [a for t, a in started if t is train_data.from_tooltip]
    assert sent == [(img, toks, ("医疗芼", "MedPenn"), ("医疗笔", "MedPen"))]
    res.update(canon=None, sure=False)  # 汉化包里没对上：不收
    started.clear()
    Hv.hover_once(img)
    assert not [a for t, a in started if t is train_data.from_tooltip]


def test_craft_override_for_count(monkeypatch):
    """F6 盘点（craft_override=True）：加成和蓝图完全对上就用倒推的品质和各槽品质；F8 默认格子上读到品质就不倒推"""
    from sc_mining.trade import inspector
    from sc_mining.crafting import crafting

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
    from sc_mining.trade import inspector
    from sc_mining.tasks.count import _read_item

    seen = {}
    monkeypatch.setattr(
        inspector, "inspect_item", lambda img, cur, **kw: seen.update(kw) or {"zh": "x"}
    )
    _read_item(MockImage(), (1, 1))
    assert seen == {"craft_override": True}


if __name__ == "__main__":
    unittest.main()
