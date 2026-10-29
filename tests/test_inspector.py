"""物品视觉识别组件 (Item Inspector) 独立测试"""
import unittest
from unittest.mock import patch, MagicMock

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
            HOVER_REGIONS,
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

        tok_row_zh = OcrToken(text="塔兰导电石", confidence=0.99, box=(100, 50, 100, 20))
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
        self.assertEqual(res["en"], "MedPen")
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


if __name__ == "__main__":
    unittest.main()
