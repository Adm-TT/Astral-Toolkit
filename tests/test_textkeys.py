"""名字折叠规则（IQ-B1）：旧名字还指向 contracts.textkeys 的同一个函数，规则和迁移前一致。"""

import re
import unicodedata

from astral_toolkit.contracts import textkeys
from astral_toolkit.crafting import itemsearch, loot, shops, wikelo
from astral_toolkit.trade import gamekey, names

_INPUTS = (
    None,
    "",
    "Lawson Mining Laser",
    "LAWSON",
    "Ⅱ",
    "Ｍｅｄ Ｐｅｎ",
    "Citadel-SE",
    "医疗笔（血红扎）",
    "医疗笔(血红扎)",
    "l I 1 |",
    "Hofstede–S2",
    "Ｌ",
    "İstanbul",
    "😀 Cap",
    "  中 文　",
    "医疗　笔",
    "x_y-z.w",
    "ǅ",
    "Ⅻ-3",
    "Ａｒｅａ１８",
    "\u00a0Nbsp",
)


def _old_fold_en(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _old_fold_en_loose(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower().replace("l", "i"))


def _old_fold_mixed_loose(s):
    return re.sub(r"[^a-z0-9一-鿿]", "", (s or "").lower().replace("l", "i"))


def _old_zh_key(s):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", s or "").lower())


def _old_en_key(s):
    return _old_fold_en_loose(unicodedata.normalize("NFKC", s or ""))


def _old_norm_zh(text):
    return (
        (text or "")
        .replace("(", "（")
        .replace(")", "）")
        .replace(" ", "")
        .replace("　", "")
        .strip()
    )


def test_old_names_share_textkeys_objects():
    assert loot._fold is textkeys.fold_mixed_loose
    assert wikelo._fold is textkeys.fold_mixed_loose
    assert shops._fold is textkeys.fold_en_loose
    assert names._fold_en is textkeys.fold_en
    assert gamekey._fold is textkeys.fold_en
    assert names._norm_zh is textkeys.norm_zh
    assert itemsearch.zh_key is textkeys.zh_key
    assert itemsearch.en_key is textkeys.en_key


def test_rules_match_before_migration():
    for value in _INPUTS:
        label = repr(value)
        assert textkeys.fold_en(value) == _old_fold_en(value), label
        assert textkeys.fold_en_loose(value) == _old_fold_en_loose(value), label
        assert textkeys.fold_mixed_loose(value) == _old_fold_mixed_loose(value), label
        assert textkeys.zh_key(value) == _old_zh_key(value), label
        assert textkeys.en_key(value) == _old_en_key(value), label
        assert textkeys.norm_zh(value) == _old_norm_zh(value), label


def test_rule_examples():
    assert textkeys.fold_en("Lawson-II") == "lawsonii"
    assert textkeys.fold_en_loose("Lawson-II") == "iawsonii"
    assert textkeys.fold_mixed_loose("劳森 Lawson") == "劳森iawson"
    assert textkeys.zh_key("Ｍｅｄ Ｐｅｎ（血红扎）") == "medpen血红扎"
    assert textkeys.en_key("Ｌａｗｓｏｎ") == "iawson"
    assert textkeys.norm_zh(" 医疗笔(血红扎) ") == "医疗笔（血红扎）"
