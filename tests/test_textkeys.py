"""名字比较键（contracts/textkeys）：几组固定输入的结果锁死；改任何一条都要升 gamedata/_schema.IMPORTER_VERSION"""

from astral_toolkit.contracts import textkeys

_TABLE = (
    (None, "", "", "", "", "", ""),
    ("", "", "", "", "", "", ""),
    (
        "Lawson Mining Laser",
        "lawsonmininglaser",
        "iawsonminingiaser",
        "iawsonminingiaser",
        "lawsonmininglaser",
        "iawsonminingiaser",
        "LawsonMiningLaser",
    ),
    ("LAWSON", "lawson", "iawson", "iawson", "lawson", "iawson", "LAWSON"),
    ("\u2161", "", "", "", "ii", "ii", "\u2161"),
    (
        "\uff2d\uff45\uff44 \uff30\uff45\uff4e",
        "",
        "",
        "",
        "medpen",
        "medpen",
        "\uff2d\uff45\uff44\uff30\uff45\uff4e",
    ),
    (
        "Citadel-SE",
        "citadelse",
        "citadeise",
        "citadeise",
        "citadelse",
        "citadeise",
        "Citadel-SE",
    ),
    (
        "\u533b\u7597\u7b14\uff08\u8840\u7ea2\u624e\uff09",
        "",
        "",
        "\u533b\u7597\u7b14\u8840\u7ea2\u624e",
        "\u533b\u7597\u7b14\u8840\u7ea2\u624e",
        "",
        "\u533b\u7597\u7b14\uff08\u8840\u7ea2\u624e\uff09",
    ),
    (
        "\u533b\u7597\u7b14(\u8840\u7ea2\u624e)",
        "",
        "",
        "\u533b\u7597\u7b14\u8840\u7ea2\u624e",
        "\u533b\u7597\u7b14\u8840\u7ea2\u624e",
        "",
        "\u533b\u7597\u7b14\uff08\u8840\u7ea2\u624e\uff09",
    ),
    ("l I 1 |", "li1", "ii1", "ii1", "li1", "ii1", "lI1|"),
    (
        "Hofstede\u2013S2",
        "hofstedes2",
        "hofstedes2",
        "hofstedes2",
        "hofstedes2",
        "hofstedes2",
        "Hofstede\u2013S2",
    ),
    ("\uff2c", "", "", "", "l", "i", "\uff2c"),
    (
        "\u0130stanbul",
        "istanbul",
        "istanbui",
        "istanbui",
        "istanbul",
        "istanbui",
        "\u0130stanbul",
    ),
    ("\U0001f600 Cap", "cap", "cap", "cap", "cap", "cap", "\U0001f600Cap"),
    (
        "  \u4e2d \u6587\u3000",
        "",
        "",
        "\u4e2d\u6587",
        "\u4e2d\u6587",
        "",
        "\u4e2d\u6587",
    ),
    (
        "\u533b\u7597\u3000\u7b14",
        "",
        "",
        "\u533b\u7597\u7b14",
        "\u533b\u7597\u7b14",
        "",
        "\u533b\u7597\u7b14",
    ),
    ("x_y-z.w", "xyzw", "xyzw", "xyzw", "xyzw", "xyzw", "x_y-z.w"),
    ("\u01c5", "", "", "", "d\u017e", "d", "\u01c5"),
    ("\u216b-3", "3", "3", "3", "xii3", "xii3", "\u216b-3"),
    (
        "\uff21\uff52\uff45\uff41\uff11\uff18",
        "",
        "",
        "",
        "area18",
        "area18",
        "\uff21\uff52\uff45\uff41\uff11\uff18",
    ),
    ("\xa0Nbsp", "nbsp", "nbsp", "nbsp", "nbsp", "nbsp", "Nbsp"),
)


def test_rules_table():
    for (
        value,
        fold_en,
        fold_en_loose,
        fold_mixed_loose,
        zh_key,
        en_key,
        norm_zh,
    ) in _TABLE:
        label = repr(value)
        assert textkeys.fold_en(value) == fold_en, label
        assert textkeys.fold_en_loose(value) == fold_en_loose, label
        assert textkeys.fold_mixed_loose(value) == fold_mixed_loose, label
        assert textkeys.zh_key(value) == zh_key, label
        assert textkeys.en_key(value) == en_key, label
        assert textkeys.norm_zh(value) == norm_zh, label


def test_rule_examples():
    assert textkeys.fold_en("Lawson-II") == "lawsonii"
    assert textkeys.fold_en_loose("Lawson-II") == "iawsonii"
    assert textkeys.fold_mixed_loose("劳森 Lawson") == "劳森iawson"
    assert textkeys.zh_key("Ｍｅｄ Ｐｅｎ（血红扎）") == "medpen血红扎"
    assert textkeys.en_key("Ｌａｗｓｏｎ") == "iawson"
    assert textkeys.norm_zh(" 医疗笔(血红扎) ") == "医疗笔（血红扎）"


def test_junk_en_examples():
    known = {textkeys.fold_en("Tin")}
    assert (
        textkeys.junk_en("HD", known)
        and textkeys.junk_en("S1", known)
        and textkeys.junk_en("XII-IR", known)
    )
    assert textkeys.junk_en("Arbor S00", known) and textkeys.junk_en("1 SCU", known)
    assert not textkeys.junk_en("Tin", known) and not textkeys.junk_en(
        "Guardian Undersuit", known
    )


# 制造蓝图的两套键（CR-B1 从 crafting.crafting 逐字搬进 contracts）：下面的值是搬之前那两个函数算的
_BP_TABLE = (
    (None, "", ""),
    ("", "", ""),
    ("Lawson Mining Laser", "lawsonmininglaser", "lawsonmininglaser"),
    ("LAWSON", "lawson", "lawson"),
    ("\u2161", "\u2171", "\u2171"),
    (
        "\uff2d\uff45\uff44 \uff30\uff45\uff4e",
        "\uff4d\uff45\uff44\uff50\uff45\uff4e",
        "\uff4d\uff45\uff44\uff50\uff45\uff4e",
    ),
    ("Citadel-SE", "citadelse", "citadel-se"),
    (
        "\u533b\u7597\u7b14\uff08\u8840\u7ea2\u624e\uff09",
        "\u533b\u7597\u7b14\u8840\u7ea2\u624e",
        "\u533b\u7597\u7b14\uff08\u8840\u7ea2\u624e\uff09",
    ),
    (
        "\u533b\u7597\u7b14(\u8840\u7ea2\u624e)",
        "\u533b\u7597\u7b14\u8840\u7ea2\u624e",
        "\u533b\u7597\u7b14(\u8840\u7ea2\u624e)",
    ),
    ("l I 1 |", "li1", "li1|"),
    ("Hofstede\u2013S2", "hofstedes2", "hofstede\u2013s2"),
    ("\uff2c", "\uff4c", "\uff4c"),
    ("\u0130stanbul", "istanbul", "i\u0307stanbul"),
    ("\U0001f600 Cap", "cap", "\U0001f600cap"),
    ("  \u4e2d \u6587\u3000", "\u4e2d\u6587", "\u4e2d\u6587\u3000"),
    ("\u533b\u7597\u3000\u7b14", "\u533b\u7597\u7b14", "\u533b\u7597\u3000\u7b14"),
    ("x_y-z.w", "xyzw", "x_y-z.w"),
    ("\u01c5", "\u01c6", "\u01c6"),
    ("\u216b-3", "\u217b3", "\u217b-3"),
    (
        "\uff21\uff52\uff45\uff41\uff11\uff18",
        "\uff41\uff52\uff45\uff41\uff11\uff18",
        "\uff41\uff52\uff45\uff41\uff11\uff18",
    ),
    ("\xa0Nbsp", "nbsp", "\xa0nbsp"),
    ("Main Power-Plant", "mainpowerplant", "mainpower-plant"),
    (
        "\u4e3b\u53d1\u7535\u673a B",
        "\u4e3b\u53d1\u7535\u673ab",
        "\u4e3b\u53d1\u7535\u673ab",
    ),
    ("Main  Powerplant_MK2", "mainpowerplantmk2", "mainpowerplant_mk2"),
)


def test_blueprint_rules_table():
    for value, norm, search in _BP_TABLE:
        label = repr(value)
        assert textkeys.blueprint_norm(value) == norm, label
        assert textkeys.blueprint_search_norm(value) == search, label
