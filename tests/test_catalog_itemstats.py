"""catalog/itemstats：成品属性的取值规则（dev 拆分②从 crafting/itemstats 搬来）。纯函数，吃一件成品的字典"""

from astral_toolkit.catalog import itemstats as S

ARMOR = {
    "size": 2,
    "grade": None,
    "cls": "x",
    "mfr": "M",
    "type": "Char_Armor_Torso",
    "sub": "Heavy",
    "s": {
        "durability": {"health": 55},
        "suit_armor": {
            "damage_resistance": {
                "a": {"multiplier": 0.8},
                "b": {"multiplier": 0.9},
                "impact": 1,
            }
        },
        "temperature_resistance": {"min": -75.0, "max": True},
    },
}


def test_base_value_of():
    assert S.base_value_of(ARMOR, "health_maxhealth") == (55, "")
    assert S.base_value_of(ARMOR, "armor_damagemitigation") == (0.85, "")
    assert S.base_value_of(ARMOR, "armor_temperaturemin") == (-75.0, " ºC")
    assert S.base_value_of(ARMOR, "armor_temperaturemax") == (
        None,
        " ºC",
    )  # True 不当数
    assert S.base_value_of(ARMOR, "unknown_key") == (None, "")
    assert S.base_value_of(None, "health_maxhealth") == (None, "")


def test_tags_of():
    assert S.tags_of(ARMOR) == {
        "size": 2,
        "grade": None,
        "cls": "x",
        "mfr": "M",
        "type": "Char_Armor_Torso",
        "sub": "Heavy",
        "cn": None,
    }
    assert S.tags_of(None) == {} and S.tags_of({}) == {}
