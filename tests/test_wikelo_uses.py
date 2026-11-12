"""维科洛用途（IQ-C1）：汉化包里对得上的全名不放宽成包含（极地 Polar ≠ Polaris 点数），矿石 / 原矿后缀也不放宽（原矿和精炼分开，
2026-11-08）；OCR 截断的半截名字照旧放宽。"""

from astral_toolkit.crafting import wikelo
from astral_toolkit.gamedata import wikelo as gd_wikelo
from astral_toolkit.trade import names

_POLARIS = {
    "id": "polaris",
    "rz": "Polaris 维科洛版",
    "req": [{"n": "Polaris Bit", "z": "Polaris 点数", "q": 15, "u": "个"}],
}
_STRATA = {
    "id": "strata",
    "rz": "岩层护甲",
    "req": [{"n": "Strata Arms", "z": "岩层 臂甲", "q": 1, "u": "个"}],
}
_ORE = {
    "id": "ore",
    "rz": "Ursa Medivac 维科洛版",
    "req": [{"n": "Jaclium (Ore)", "z": "杰金矿石", "q": 20, "u": "个"}],
}
_FULL = {"Polar", "Strata Arms Amber", "Jaclium", "Polaris Bit"}
_FULL_ZH = {"极地", "岩层 臂甲 琥珀", "杰金", "Polaris 点数"}


def _setup(monkeypatch, exact=()):
    """库里按名字相等找到的（exact）、全部兑换、汉化包全名表都换成替身。"""
    monkeypatch.setattr(gd_wikelo, "requiring", lambda fe, fz: list(exact))
    monkeypatch.setattr(wikelo, "load", lambda: [_POLARIS, _STRATA, _ORE])
    monkeypatch.setattr(
        names,
        "canonical_exact",
        lambda zh="", en="": (zh, en) if en in _FULL or zh in _FULL_ZH else None,
    )


def test_full_name_is_not_loosened_to_contains(monkeypatch):
    """极地冷却器不配「Polaris 点数」，岩层臂甲琥珀不配「岩层 臂甲」（11-06 老大截图）。"""
    _setup(monkeypatch)
    assert wikelo.uses("Polar", "极地") == []
    assert wikelo.uses("Strata Arms Amber", "岩层 臂甲 琥珀") == []


def test_full_name_does_not_match_the_ore(monkeypatch):
    """全名只认一样的：精炼的「杰金」不对维科洛要的「杰金矿石」（原矿和精炼分开，老大 2026-11-08 定）；原矿名一样就对上。"""
    _setup(monkeypatch)
    assert wikelo.uses("Jaclium", "杰金") == []
    assert wikelo.uses("", "杰金") == []
    _setup(monkeypatch, exact=[(_ORE, _ORE["req"][0])])
    assert wikelo.uses("Jaclium (Ore)", "杰金矿石") == [(_ORE, 20, "个")]


def test_truncated_name_is_still_loosened(monkeypatch):
    """OCR 截断的半截名字（汉化包里对不上）照旧放宽成包含。"""
    _setup(monkeypatch)
    assert wikelo.uses("Polaris Bi", "") == [(_POLARIS, 15, "个")]


def test_equal_name_found_first(monkeypatch):
    """名字相等的照旧最先用，不走放宽。"""
    _setup(monkeypatch, exact=[(_POLARIS, _POLARIS["req"][0])])
    assert wikelo.uses("Polaris Bit", "Polaris 点数") == [(_POLARIS, 15, "个")]
