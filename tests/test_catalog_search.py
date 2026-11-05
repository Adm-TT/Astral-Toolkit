"""catalog.search 的纯规则测试（甲：IQ-B2）。"""

from types import SimpleNamespace

from astral_toolkit.catalog import search
from astral_toolkit.contracts import textkeys
from astral_toolkit.crafting import itemsearch


def _item(en, item_id, zh, *, zlen=None, variant=False, loot=False, loc=False):
    return SimpleNamespace(
        en=en,
        item_id=item_id,
        zh=zh,
        cat="",
        has_loot=loot,
        loc=loc,
        wiki=False,
        wtype="",
        wsize=None,
        desc="",
        zlen=len(zh) if zlen is None else zlen,
        variant=variant,
    )


def _index_for_find():
    items = [
        _item("B Base", "bbase", "基础步枪"),
        _item("E Variant", "evariant", "基础步枪", variant=True),
        _item("AA NoData", "aanodata", "基础步枪", loc=True),
        _item("Z Short", "zshort", "短步枪"),
        _item("C Long", "clong", "很长步枪"),
    ]
    zks = {it.item_id: (it.zh,) for it in items}
    shops = {
        "bbase": "11",
        "evariant": "12",
        "zshort": "13",
        "clong": "14",
    }
    return search.index_from(items, zks, {}, shops)


def test_small_text_helpers():
    assert search.has_cjk("视差") is True
    assert search.has_cjk("Parallax") is False
    assert search.variant('Parallax "Hurston"', "") is True
    assert search.variant("", "视差“限定”") is True
    assert search.variant("Parallax", "视差") is False
    assert search.trigrams("abcd") == {"abc", "bcd"}
    assert search.subseq("步枪", "基础步枪") is True
    assert search.wiki_noise({"en": "Turret"}) is True
    assert search.wiki_noise({"en": "Rifle", "wtype": "weapons"}) is False


def test_rank_zh_exact_ending_contiguous_and_subsequence():
    key = "视差能量突击步枪"
    assert search.rank_zh("视差步枪", ["视差步枪"]) == 0
    assert search.rank_zh("视差步枪", [key]) == 1
    assert search.rank_zh("视差", [key]) == 2
    assert search.rank_zh("能量突击", [key]) == 3
    assert search.rank_zh("视能步", [key]) == 4
    assert search.rank_zh("不存在", [key]) is None


def test_rank_en_exact_start_contains_and_all_words():
    name = "parallax energy assault rifle"
    assert (
        search.rank_en("parallax rifle", ["parallax", "rifle"], "parallax rifle") == 0
    )
    assert search.rank_en("energy rifle", ["energy", "rifle"], name) == 1
    assert search.rank_en("parallax", ["parallax"], name) == 2
    assert search.rank_en("energy assault", ["energy", "assault"], name) == 3
    assert search.rank_en("rifle parallax", ["rifle", "parallax"], name) == 4
    assert search.rank_en("mining", ["mining"], name) is None


def test_empty_index_shape():
    assert search.empty_index() == {
        "rows": [],
        "by_char": {},
        "by_tri": {},
        "by_en": {},
    }


def test_find_sorts_by_rank_base_data_size_and_limit():
    index = _index_for_find()
    names = [r["en"] for r in search.find(index, "步枪")]
    # 短的在前（Z Short 英文名最靠后也排第一）；没数据的在有数据的后面（AA NoData 英文名最靠前也排后面）
    assert names == ["Z Short", "B Base", "C Long", "AA NoData", "E Variant"]
    assert [r["en"] for r in search.find(index, "步枪", limit=2)] == [
        "Z Short",
        "B Base",
    ]


def test_find_english_exact_uses_trigram_index():
    index = _index_for_find()
    assert search.find(index, "B Base")[0]["en"] == "B Base"


def test_index_includes_aka_for_lookup_and_search():
    items = [_item("Primary", "primary", "主武器")]
    names = {
        "primary": [
            ("zh_loot", "主武器掉落", None),
            ("aka", "Old Primary", None),
        ]
    }
    index = search.index_from(items, {"primary": ("主武器",)}, names, {})
    assert index["rows"][0]["zh_loot"] == "主武器掉落"
    assert index["rows"][0]["aka"] == ["Old Primary"]
    assert search.lookup(index, "Old Primary")["en"] == "Primary"
    assert search.find(index, "Old Primary")[0]["en"] == "Primary"


def test_lookup_uses_en_key():
    index = _index_for_find()
    assert search.lookup(index, " Z-SHORT ")["en"] == "Z Short"
    assert search.lookup(index, "none") is None


def test_old_private_names_are_same_catalog_functions():
    assert itemsearch._has_cjk is search.has_cjk
    assert itemsearch._variant is search.variant
    assert itemsearch._trigrams is search.trigrams
    assert itemsearch._wiki_noise is search.wiki_noise
    assert itemsearch._subseq is search.subseq
    assert itemsearch._rank_zh is search.rank_zh
    assert itemsearch._rank_en is search.rank_en
    assert itemsearch._empty_index is search.empty_index
    assert itemsearch.en_key is textkeys.en_key
    assert itemsearch.zh_key is textkeys.zh_key
