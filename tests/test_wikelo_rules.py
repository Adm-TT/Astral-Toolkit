"""维科洛纯规则（CR-B3）：不读库、不读文件；旧名字还从 crafting.wikelo 拿。"""

from astral_toolkit.crafting import wikelo, wikelo_rules
from astral_toolkit.gamedata import wikelo as gd_wikelo
from astral_toolkit.trade import names

_ORE = {
    "id": "ore",
    "type": "收集",
    "t": "杰金样本",
    "te": "Jaclium Sample",
    "rz": "杰金奖励",
    "rewards": [],
    "req": [{"n": "Jaclium (Ore)", "z": "杰金矿石", "q": 20, "u": "个"}],
    "systems": [],
}
_RECOMB = {
    "id": "recomb",
    "type": "装备/物品",
    "t": "重组样本兑换",
    "te": "Recombination Exchange",
    "rz": "",
    "rewards": ["重组奖励"],
    "req": [{"n": "RCMBNT-XTL", "z": "重组样本", "q": 5, "u": "个"}],
    "systems": [],
}
_PLAIN = {
    "id": "plain",
    "type": "载具",
    "t": "极地巡逻车",
    "te": "Polaris Rover",
    "rz": "极地涂装 巡逻车",
    "rewards": [],
    "req": [{"n": "Polaris Bit", "z": "Polaris 点数", "q": 15, "u": "个"}],
    "systems": ["Pyro"],
}
_ROWS = [_ORE, _RECOMB, _PLAIN]
_RCMBNT_NOTE = (
    "玛瑙设施（Onyx Facility）任务里在终端合成：催化剂 XTL/PWL/RGL 配反应物，"
    "做出的样本送到设施货梯"
)


def test_rewarding_matches_rz_rewards_and_zh():
    """F8「可通过维科洛兑换获得」：奖励 rz / rewards 对英文名、中文名都对得上，按原顺序"""
    a = dict(_PLAIN, id="a")
    b = dict(_RECOMB, id="b")
    c = dict(_ORE, id="c")
    rows = [a, b, c]
    assert wikelo_rules.rewarding(rows, "极地涂装 巡逻车", "") == [a]
    assert wikelo_rules.rewarding(rows, "Recombination Reward", "") == []
    assert wikelo_rules.rewarding(rows, "xx", "重组奖励") == [b]
    assert wikelo_rules.rewarding(rows, "Jaclium Reward", "杰金奖励") == [c]
    assert wikelo_rules.rewarding(rows, "xx", "") == []


def test_rewarding_uses_same_containment_rule():
    """rewarding 用 _same 的规则：不足 4 个字的包含不算、够 4 个字的包含算"""
    c = {"t": "甲", "rz": "ABCDEF", "rewards": []}
    assert wikelo_rules.rewarding([c], "ABC", "") == []
    assert wikelo_rules.rewarding([c], "ABCD", "") == [c]


def test_wikelo_rules_are_pure(monkeypatch):
    """外部取数入口全换成抛错，纯规则照常算。"""

    def boom(*a, **k):
        raise AssertionError("纯规则不该查库 / 读汉化包")

    for name in ("contracts", "requiring", "print_places"):
        monkeypatch.setattr(gd_wikelo, name, boom)
    monkeypatch.setattr(names, "canonical_exact", boom)

    req = _ORE["req"][0]
    assert wikelo_rules.note_for("RCMBNT-XTL") == ("重组样本", _RCMBNT_NOTE)
    assert wikelo_rules.req_label(req) == "杰金矿石（Jaclium (Ore)）"
    assert wikelo_rules.uses(
        "Jaclium (Ore)", "杰金矿石", [(_ORE, req)], boom, boom
    ) == [(_ORE, 20, "个")]
    assert wikelo_rules.search(lambda: _ROWS, "") == _ROWS
    assert wikelo_rules.search(lambda: _ROWS, "杰金") == [_ORE]
    assert wikelo_rules.source_note("RCMBNT-XTL", boom) == _RCMBNT_NOTE
    assert wikelo_rules.describe(_ORE) == (
        "【杰金样本】收集｜换：杰金奖励\n  · 杰金矿石（Jaclium (Ore)） × 20 个"
    )


def test_uses_equal_hit_does_not_load_or_check_full_name():
    calls = []

    def load():
        calls.append("load")
        return _ROWS

    def is_full():
        calls.append("is_full")
        return True

    req = _ORE["req"][0]
    got = wikelo_rules.uses("Jaclium (Ore)", "杰金矿石", [(_ORE, req)], load, is_full)
    assert got == [(_ORE, 20, "个")]
    assert calls == []


def test_full_name_does_not_loosen():
    """全名只认一样的：不放宽成包含（极地 ≠ Polaris），矿石 / 原矿后缀也不放宽——精炼的杰金交不了要杰金矿石的兑换
    （老大 2026-11-08 定原矿、精炼分开）；全名不用再翻全部兑换"""
    calls = []

    def load():
        calls.append("load")
        return _ROWS

    def is_full():
        calls.append("is_full")
        return True

    assert wikelo_rules.uses("Polar", "极地", [], load, is_full) == []
    assert wikelo_rules.uses("Jaclium", "杰金", [], load, is_full) == []
    assert calls == ["is_full", "is_full"]


def test_truncated_name_is_loosened_when_not_full():
    assert wikelo_rules._same("abc", "abcdef") is False
    assert wikelo_rules._same("abcd", "abcdef") is True

    calls = []

    def load():
        calls.append("load")
        return _ROWS

    def is_full():
        calls.append("is_full")
        return False

    got = wikelo_rules.uses("Polaris Bi", "", [], load, is_full)
    assert got == [(_PLAIN, 15, "个")]
    assert calls == ["is_full", "load"]


def test_source_note_notes_does_not_call_print_spots():
    def print_spots(_name):
        raise AssertionError("命中 NOTES 不该查打印地点")

    assert wikelo_rules.source_note("RCMBNT-XTL", print_spots) == _RCMBNT_NOTE


def test_source_note_uses_print_spots():
    seen = []

    def print_spots(name):
        seen.append(name)
        return ["地点 A", "", "地点 B"]

    assert wikelo_rules.source_note("某个物品", print_spots) == "打印：地点 A；地点 B"
    assert seen == ["某个物品"]
    assert (
        wikelo_rules.source_note("DCHS-99", lambda _name: [])
        == "派罗争夺区（Contested Zone）内打印"
    )


def test_uses_passes_chinese_name(monkeypatch):
    """wikelo.uses(英文名, 中文名) 把中文名也传下去：只靠中文名对上的兑换也要列出来
    （原来经 uses_text 测，CL-C4 删了 uses_text）"""

    def requiring(norm_en, norm_zh, snap=None):
        return [(_ORE, _ORE["req"][0])] if norm_zh == "杰金矿石" else []

    monkeypatch.setattr(gd_wikelo, "requiring", requiring)
    monkeypatch.setattr(names, "canonical_exact", lambda zh, en: None)
    monkeypatch.setattr(wikelo, "load", lambda: _ROWS)
    assert [(c["t"], q, u) for c, q, u in wikelo.uses("", "杰金矿石")] == [
        ("杰金样本", 20, "个")
    ]


def test_req_label_only_pairs_real_chinese_names():
    """BF-2：汉化包没译的（中文名那栏还是英文、或者「[…]」属性行）只写英文，不写两遍"""
    assert (
        wikelo_rules.req_label({"n": "Wikelo Favor", "z": "维科洛人情"})
        == "维科洛人情（Wikelo Favor）"
    )
    assert wikelo_rules.req_label({"n": "Argo ATLS", "z": "Argo ATLS"}) == "Argo ATLS"
    assert wikelo_rules.req_label({"n": "Some Part", "z": "[S1 Part]"}) == "Some Part"
    assert wikelo_rules.req_label({"n": "Some Part", "z": ""}) == "Some Part"
    assert wikelo_rules.req_label({"n": "Some Part", "z": None}) == "Some Part"
