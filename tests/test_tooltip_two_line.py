"""F8 认汉化包两行名（RD-B1）：船零件「中文English」一行 + 「[标签]」一行；坐标是老大 11-06 截图的 OCR 实数。"""

from astral_toolkit.ocr import OcrToken
from astral_toolkit.trade import inspector as I


def test_title_band_two_line_name():
    """标题带：中英一行加下一行标签，认出极地冷却器。"""
    toks = [
        OcrToken("极地Polar", 95, (1370, 371, 69, 18)),
        OcrToken("[冷却S1军用B]", 95, (1370, 393, 107, 19)),
        OcrToken("体积：84000uSCU", 95, (1370, 415, 121, 19)),
        OcrToken("制造商：圣盾动力（AegisDynamics）", 95, (1369, 458, 240, 21)),
        OcrToken("物品类型：冷却器", 95, (1370, 482, 120, 19)),
        OcrToken("尺寸：1", 95, (1370, 504, 57, 14)),
    ]
    assert I.tooltip_pick(toks, (2121, 968)) == (("极地", "Polar"), True)


def test_body_band_two_line_name_with_broken_grade():
    """说明框带：刚毅发电机，拆开的等级行也不能顶替名字。"""
    toks = [
        OcrToken("刚毅Fortitude", 95, (1370, 371, 96, 18)),
        OcrToken("[发电S1工业C]", 95, (1370, 393, 108, 19)),
        OcrToken("体积：84000uSCU", 95, (1368, 415, 123, 18)),
        OcrToken("制造商：朱诺星际工厂（JunoStarwerk）", 95, (1370, 459, 262, 19)),
        OcrToken("物品类型：发电机", 95, (1370, 481, 120, 20)),
        OcrToken("尺寸：1", 95, (1369, 503, 58, 24)),
        OcrToken("等级：", 95, (1370, 526, 48, 20)),
        OcrToken("C", 95, (1414, 531, 9, 11)),
        OcrToken("类别：工业", 95, (1369, 548, 78, 21)),
    ]
    assert I.tooltip_pick(toks, (2395, 945)) == (("刚毅", "Fortitude"), True)


def test_missing_title_rejects_tag_and_c():
    """名字那行没认到：不许返回标签或 C。"""
    toks = [
        OcrToken("[发电S1工业C]", 95, (1370, 393, 108, 19)),
        OcrToken("体积：84000uSCU", 95, (1368, 415, 123, 18)),
        OcrToken("制造商：朱诺星际工厂（JunoStarwerk）", 95, (1370, 459, 262, 19)),
        OcrToken("物品类型：发电机", 95, (1370, 481, 120, 20)),
        OcrToken("尺寸：1", 95, (1369, 503, 58, 24)),
        OcrToken("等级：", 95, (1370, 526, 48, 20)),
        OcrToken("C", 95, (1414, 531, 9, 11)),
        OcrToken("类别：工业", 95, (1369, 548, 78, 21)),
    ]
    assert I.tooltip_pick(toks, (2395, 945)) == (None, False)


def test_bilingual_line_without_tag_unchanged():
    """中英一行、下面没有标签：照旧走原来的路。"""
    toks = [
        OcrToken("塔兰导电石Taranite", 95, (100, 100, 150, 20)),
        OcrToken("体积：13000 uSCU", 95, (100, 124, 120, 20)),
    ]
    assert I.tooltip_pick(toks, (300, 300)) == (("塔兰导电石Taranite", ""), True)


def test_missile_three_line_unchanged():
    """三行中 / 英 / 标签的导弹：仍按原来的中英行对识别。"""
    toks = [
        OcrToken("VT-T10 “真理” 鱼雷", 95, (100, 100, 160, 20)),
        OcrToken('VT-T10 "Veritas" Torpedo', 95, (100, 124, 200, 20)),
        OcrToken("[S10 红外线IR 270m/s 总伤750,000]", 95, (100, 148, 260, 20)),
        OcrToken("体积：2400000 uSCU", 95, (100, 172, 150, 20)),
        OcrToken("制造商：贝尔", 95, (100, 196, 120, 20)),
        OcrToken("物品类型：鱼雷", 95, (100, 220, 120, 20)),
        OcrToken("尺寸：10", 95, (100, 244, 60, 20)),
    ]
    assert I.tooltip_pick(toks, (300, 300)) == (
        ("VT-T10 “真理” 鱼雷", 'VT-T10 "Veritas" Torpedo'),
        True,
    )


def test_is_tag():
    """标签行：整行一对方括号且带中文才算。"""
    yes = [
        "[冷却 S1 民用 D]",
        "[冷却S1民用D]",
        "【雷达 S2 军用 B】",
        "[缓解脑震荡]",
        "[S10 红外线IR 270m/s 总伤750,000]",
    ]
    no = [
        "[全局]某人：你好",
        "[红外]灾星 XII-IR",
        "冷却S1民用D",
        "[]",
        "[100,0|100.0|100.0]",
        "[全局]",
        "【本地】",
        "",
    ]
    assert all(I._is_tag(t) for t in yes)
    assert not any(I._is_tag(t) for t in no)


def test_tag_too_far_does_not_use_two_line_path():
    """标签离名字太远：不按新格式认名字。"""
    toks = [
        OcrToken("极地Polar", 95, (1370, 371, 69, 18)),
        OcrToken("[冷却S1军用B]", 95, (1370, 431, 107, 19)),
        OcrToken("体积：84000uSCU", 95, (1370, 415, 121, 19)),
        OcrToken("制造商：圣盾动力（AegisDynamics）", 95, (1369, 458, 240, 21)),
        OcrToken("物品类型：冷却器", 95, (1370, 482, 120, 19)),
        OcrToken("尺寸：1", 95, (1370, 504, 57, 14)),
    ]
    assert I.tooltip_pick(toks, (2121, 968))[0] != ("极地", "Polar")


def test_missing_title_rejects_tag_inside_window():
    """名字那行没认到、标签落在「尺寸」往上 6 个行高里：也不许把标签当名字。"""
    toks = [
        OcrToken("[冷却S1军用B]", 95, (1370, 393, 107, 19)),
        OcrToken("体积：84000uSCU", 95, (1370, 415, 121, 19)),
        OcrToken("制造商：圣盾动力（AegisDynamics）", 95, (1369, 458, 240, 21)),
        OcrToken("物品类型：冷却器", 95, (1370, 482, 120, 19)),
        OcrToken("尺寸：1", 95, (1370, 504, 57, 20)),
        OcrToken("等级：B", 95, (1370, 526, 50, 20)),
        OcrToken("分类：军用", 95, (1370, 548, 76, 21)),
    ]
    assert I.tooltip_pick(toks, (2121, 968)) == (None, False)


def test_two_line_path_keeps_name_filters():
    """中英一行加标签的新路照样过滤「物品类型：…」这种属性行。"""
    toks = [
        OcrToken("物品类型：冷却器Cooler", 95, (100, 100, 150, 20)),
        OcrToken("[冷却S1军用B]", 95, (100, 124, 100, 20)),
        OcrToken("体积：84000uSCU", 95, (100, 148, 120, 20)),
    ]
    assert I.tooltip_pick(toks, (300, 300)) == (None, False)
