"""游戏数据层批 6：名字对照（trade/names、trade/gamekey）改走 gamedata 的测试

矩阵 docs/superpowers/specs/2026-11-02-gd-b6-callsites.md 每条规则一个测试；“旧实现”（_legacy_*）是迁移前的函数体原样
抄进来、只把读文件换成读 tmp_path，只在测试里存在，用来和新实现逐条比。不读真实 data/、不碰 userdata。"""

import json

from tests.test_gamedata import _MIN_SOURCES, _write_min_sources
from tests.test_gamedata_b1 import _setup

# 在 _MIN_SOURCES 上覆盖：边界样本（矩阵 §1 R1-R9、§3 G1-G8）
_B6_SOURCES = {
    "shops.json": {
        **_MIN_SOURCES["shops.json"],
        "items": {
            **_MIN_SOURCES["shops.json"]["items"],
            "300": ["Tin", "Commodity"],  # 锡 → Tin 短，但商店有：不算假英文名（R4）
        },
    },
    "loot_index.json": {
        "version": "4.10.2LIVE",
        "rows": [
            ["u1", "Medpen", "medpen_01", "common", 3, "医疗笔"],
            # 中英填反：英文位折叠成空串 → known 里混进 ""（R5）
            ["u2", "夹克 - 名称", "jacket_01", "rare", 1, "DYL Jacket"],
            [
                "u3",
                "Lawson Alt",
                "KLEIN_S0_B",
                "common",
                1,
                "",
            ],  # 大写类名：按小写对（G4）
            [
                "u4",
                "Medpen Dup",
                "MEDPEN_01",
                "common",
                1,
                "",
            ],  # 同类名第二行：首个胜出（G4）
        ],
    },
    "zh_names.json": {
        "视差步枪": "HD",  # 假英文名（R3）
        "锡": "Tin",
        "制空": "Omnisky-3 S1",  # 型号码（R3）
        "医疗笔": "Medpen",
        "医疗 笔": "Old Medpen Name",  # 规范化后与上一条同键（R9 / Review Focus 2）
        "护甲": "护甲套",  # 英文位纯中文：known 里有 "" 时保留（R5）
        "劳森": "LAWSON mining laser",  # 拼写与商店不同（R9）
    },
    "zh_only_names.json": {
        "医疗笔": "Medpen Other",  # 被 zh_names 盖住（R7）
        "章": "Badge",  # 中文太短（R6）
        "荣誉勋章": "Medal Of Honor",
    },
    "name_aliases.json": {
        "Medi Pen": "Medpen",
        "Medi-Pen": "Lawson Mining Laser",  # 与上一条同折叠：后写覆盖（G5）
        "Venture Arms": "Lawson Mining Laser",  # 旧写法本身是现有物品：物品目录不登记，gamekey 照收（G5）
    },
    "wiki_items.json": {
        "items": [
            {"n": "Medpen", "t": "Consumable", "s": 1, "cls": "medpen_01", "d": ""},
            {"n": "MEDPEN", "t": "Consumable", "s": 1, "cls": "medpen_dup", "d": ""},
            {"n": "Some Paint", "t": "Paints", "s": None, "cls": "paint_01", "d": ""},
            {
                "n": "Lawson Mining Laser",
                "t": "Mining",
                "s": 1,
                "cls": "Laser_S0",
                "d": "",
            },
            # 大写 I：gamekey._fold 下与 Laser 不同键（G1）；类名掉落里没有，alt[1] 有（G8）
            {
                "n": "Lawson Mining Iaser",
                "t": "Mining",
                "s": 1,
                "cls": "klein_s0",
                "alt": ["nope_x", "klein_s0_b", "medpen_01"],
                "d": "",
            },
            {"n": "No Class Thing", "t": "Misc", "s": 1, "d": ""},  # 没有类名（G7）
        ]
    },
}


def _b6(monkeypatch, tmp_path, **override):
    return _setup(monkeypatch, tmp_path, **{**_B6_SOURCES, **override})


def _read(data_dir, name):
    return json.loads((data_dir / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- Task 1：gamedata.names 原样有序行


def test_zh_pairs_order_and_src(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import names as gn

    _b6(monkeypatch, tmp_path)
    got = [(p.zh, p.en, p.src) for p in gn.zh_pairs()]
    assert got == [
        ("锡", "Tin", "zh_names"),
        ("医疗笔", "Medpen", "zh_names"),
        ("医疗 笔", "Old Medpen Name", "zh_names"),
        ("护甲", "护甲套", "zh_names"),
        ("劳森", "LAWSON mining laser", "zh_names"),
        ("荣誉勋章", "Medal Of Honor", "zh_only"),
    ]
    assert [p.source_order for p in gn.zh_pairs()] == list(range(6))


def test_wiki_classes_keep_noise_raw_case_and_alt_order(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import names as gn

    _b6(monkeypatch, tmp_path)
    got = [(w.n, w.cls, w.alt) for w in gn.wiki_classes()]
    assert got == [
        ("Medpen", "medpen_01", ()),
        ("MEDPEN", "medpen_dup", ()),
        ("Some Paint", "paint_01", ()),  # 涂装（物品目录当噪声丢掉）照留
        ("Lawson Mining Laser", "Laser_S0", ()),  # 类名原大小写
        ("Lawson Mining Iaser", "klein_s0", ("nope_x", "klein_s0_b", "medpen_01")),
        ("No Class Thing", "", ()),
    ]


def test_alias_pairs_unfiltered_in_source_order(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import names as gn

    _b6(monkeypatch, tmp_path)
    assert gn.alias_pairs() == (
        ("Medi Pen", "Medpen"),
        ("Medi-Pen", "Lawson Mining Laser"),
        ("Venture Arms", "Lawson Mining Laser"),  # item_names 里被拒的那条也在
    )


def test_class_uuids_source_order(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import names as gn

    _b6(monkeypatch, tmp_path)
    assert gn.class_uuids() == (
        ("medpen_01", "u1"),
        ("jacket_01", "u2"),
        ("KLEIN_S0_B", "u3"),
        ("MEDPEN_01", "u4"),
    )


def test_names_topic_shares_outer_snapshot(monkeypatch, tmp_path):
    import astral_toolkit.gamedata as G
    from astral_toolkit.gamedata import names as gn

    _b6(monkeypatch, tmp_path)
    G.ensure()
    with G.snapshot() as s:
        before = gn.zh_pairs(s)
        _write_min_sources(
            tmp_path, **{**_B6_SOURCES, "zh_names.json": {"医疗笔": "Medpen"}}
        )
        G.rebuild()  # 中途发布新代
        assert gn.zh_pairs(s) == before  # 传进来的快照还是旧代
        assert gn.zh_pairs() == before  # 不传也复用外层快照
        assert len(gn.wiki_classes()) == 6
    assert [(p.zh, p.en) for p in gn.zh_pairs()] == [
        ("医疗笔", "Medpen"),
        ("荣誉勋章", "Medal Of Honor"),
    ]


def test_names_topic_cached_per_version(monkeypatch, tmp_path):
    import astral_toolkit.gamedata as G
    from astral_toolkit.gamedata import names as gn

    _b6(monkeypatch, tmp_path)
    a, w, al, u = gn.zh_pairs(), gn.wiki_classes(), gn.alias_pairs(), gn.class_uuids()
    assert gn.zh_pairs() is a and gn.wiki_classes() is w
    assert gn.alias_pairs() is al and gn.class_uuids() is u
    _write_min_sources(
        tmp_path, **{**_B6_SOURCES, "name_aliases.json": {"Old": "Medpen"}}
    )
    G.rebuild()
    assert gn.alias_pairs() == (("Old", "Medpen"),)
    assert gn.zh_pairs() is not a  # 版本变了：整份换新
    assert gn.zh_pairs() == a  # 内容没变


# ---------------------------------------------------------------- Task 2：trade/names.table / _index


def _legacy_table(d):
    """迁移前 trade/names.table() + _known_names() 的函数体原样，只把读文件 / shops.load / loot.load_index 换成读 d 下的 JSON"""
    from astral_toolkit.trade.names import _fold_en, _junk, _norm_zh

    try:
        raw = _read(d, "zh_names.json")
    except (OSError, ValueError):
        return {}
    known = set()
    try:
        known |= {
            _fold_en(v[0]) for v in _read(d, "shops.json").get("items", {}).values()
        }
    except Exception:
        pass
    try:
        known |= {
            _fold_en(r[1])
            for r in (_read(d, "loot_index.json") or {}).get("rows") or []
        }
    except Exception:
        pass
    out = {zh: en for zh, en in raw.items() if not _junk(en, known)}
    try:
        for zh, en in _read(d, "zh_only_names.json").items():
            if not _junk(en, known) and len(_norm_zh(zh)) >= 3:
                out.setdefault(zh, en)
    except (OSError, ValueError):
        pass
    return out


def _legacy_index(t):
    """迁移前 trade/names._index() 的函数体原样（setdefault：首个胜出）"""
    from astral_toolkit.trade.names import _fold_en, _norm_zh

    zh_map, en_map = {}, {}
    for zh, en in t.items():
        zh_map.setdefault(_norm_zh(zh), (zh, en))
        en_map.setdefault(_fold_en(en), (zh, en))
    return zh_map, en_map


def _on_legacy(monkeypatch, d, fn):
    """把 table / _index 换成旧实现在 d 上的结果，再跑 fn()——比较“同样的派生函数”在新旧数据上的输出"""
    from astral_toolkit.trade import names

    t = _legacy_table(d)
    idx = _legacy_index(t)
    monkeypatch.setattr(names, "table", lambda: t)
    monkeypatch.setattr(names, "_index", lambda: idx)
    return fn()


def test_table_equals_legacy_on_edge_sample(monkeypatch, tmp_path):
    from astral_toolkit.trade import names

    _b6(monkeypatch, tmp_path)
    got = list(names.table().items())
    assert got == list(_legacy_table(tmp_path).items())
    assert got == [
        ("锡", "Tin"),
        ("医疗笔", "Medpen"),
        ("医疗 笔", "Old Medpen Name"),
        ("护甲", "护甲套"),
        ("劳森", "LAWSON mining laser"),
        ("荣誉勋章", "Medal Of Honor"),
    ]


def test_table_empty_when_zh_names_missing_even_with_zh_only(monkeypatch, tmp_path):
    from astral_toolkit.trade import names

    _b6(monkeypatch, tmp_path)
    (tmp_path / "zh_names.json").unlink()
    assert names.table() == {} == _legacy_table(tmp_path)  # R1：不看 zh_only_names


def test_table_zh_only_broken_keeps_zh_names(monkeypatch, tmp_path):
    from astral_toolkit.trade import names

    _b6(monkeypatch, tmp_path)
    (tmp_path / "zh_only_names.json").write_text("{坏了", encoding="utf-8")
    t = names.table()
    assert list(t.items()) == list(_legacy_table(tmp_path).items())  # R2
    assert "荣誉勋章" not in t and t["医疗笔"] == "Medpen"


def test_table_drops_code_like_english(monkeypatch, tmp_path):
    from astral_toolkit.trade import names

    _b6(monkeypatch, tmp_path)
    assert "视差步枪" not in names.table() and "制空" not in names.table()  # R3


def test_table_keeps_short_name_known_in_shop(monkeypatch, tmp_path):
    from astral_toolkit.trade import names

    _b6(monkeypatch, tmp_path)
    assert names.table()["锡"] == "Tin"  # R4


def test_table_known_includes_raw_loot_en_quirk(monkeypatch, tmp_path):
    from astral_toolkit.trade import names

    _b6(monkeypatch, tmp_path)
    assert names.table()["护甲"] == "护甲套"  # R5：掉落英文位是中文 → known 里有 ""
    rows = [r for r in _B6_SOURCES["loot_index.json"]["rows"] if r[0] != "u2"]
    _write_min_sources(
        tmp_path,
        **{**_B6_SOURCES, "loot_index.json": {"version": "x", "rows": rows}},
    )
    import astral_toolkit.gamedata as G

    G.rebuild()
    assert "护甲" not in names.table()
    assert list(names.table().items()) == list(_legacy_table(tmp_path).items())


def test_table_zh_only_needs_three_chars(monkeypatch, tmp_path):
    from astral_toolkit.trade import names

    _b6(monkeypatch, tmp_path)
    assert (
        "章" not in names.table() and names.table()["荣誉勋章"] == "Medal Of Honor"
    )  # R6


def test_table_zh_names_wins_over_zh_only(monkeypatch, tmp_path):
    from astral_toolkit.trade import names

    _b6(monkeypatch, tmp_path)
    assert names.table()["医疗笔"] == "Medpen"  # R7：zh_only 的 Medpen Other 不覆盖


def test_to_english_returns_source_spelling_not_item_en(monkeypatch, tmp_path):
    from astral_toolkit.trade import names

    _b6(monkeypatch, tmp_path)
    assert names.to_english("劳森") == [
        "LAWSON mining laser"
    ]  # R9：不是商店的 Lawson Mining Laser
    assert names.to_english("医疗 笔") == ["Old Medpen Name"]
    assert names.to_english("护甲") == ["护甲套"]  # 物品目录里没有这条（D2），这里照有


def test_to_english_exact_last_wins_index_first_wins(monkeypatch, tmp_path):
    from astral_toolkit.trade import names

    _b6(monkeypatch, tmp_path)
    new = (names.to_english("医疗笔"), names.canonical("医疗笔", ""))
    assert new == (
        ["Old Medpen Name"],
        ("医疗笔", "Medpen"),
    )  # 精确：后写覆盖；_index：首个胜出
    old = _on_legacy(
        monkeypatch,
        tmp_path,
        lambda: (names.to_english("医疗笔"), names.canonical("医疗笔", "")),
    )
    assert new == old


def test_to_english_fuzzy_order_and_limit(monkeypatch, tmp_path):
    from astral_toolkit.trade import names

    _b6(monkeypatch, tmp_path)
    qs = [
        ("医疗", 8),
        ("医疗笔护甲", 8),
        ("勋章", 8),
        ("劳", 8),
        ("医疗笔护甲劳森", 2),
        ("abc", 8),
    ]

    def run():
        return [names.to_english(q, limit=n) for q, n in qs]

    new = run()
    assert new == _on_legacy(monkeypatch, tmp_path, run)
    assert new[4] == ["Old Medpen Name", "护甲套"]


def test_canonical_and_zh_for_unchanged(monkeypatch, tmp_path):
    from astral_toolkit.trade import names

    _b6(monkeypatch, tmp_path)
    cs = [
        ("医疗 笔", ""),
        ("", "Medpen"),
        ("", "MEDPEN!"),
        ("", "Old Medpen Nam"),
        ("劳森", ""),
        ("", "Lawson Mining Laser"),
        ("荣誉勋", ""),
        ("荣誉勋章Medal Of Honor", ""),
        ("护甲", ""),
        ("锡", "Tin"),
        ("不存在的东西", ""),
    ]
    zs = ["Medpen", "Old Medpen Name", "LAWSON MINING LASER", "Tin", "x"]

    def run():
        return [names.canonical(z, e) for z, e in cs], [names.zh_for(e) for e in zs]

    new = run()
    assert new == _on_legacy(monkeypatch, tmp_path, run)
    assert new[1][:2] == ["医疗笔", "医疗 笔"]


def test_suggest_tie_order_follows_table(monkeypatch, tmp_path):
    from astral_toolkit.trade import names

    _b6(monkeypatch, tmp_path)
    qs = ["医疗", "医疗笔", "med", "lawson", "荣誉"]

    def run():
        return [names.suggest(q) for q in qs]

    new = run()
    assert new == _on_legacy(monkeypatch, tmp_path, run)
    assert new[1][:2] == [("医疗笔", "Medpen"), ("医疗 笔", "Old Medpen Name")]


def test_table_refreshes_after_rebuild_without_cache_clear(monkeypatch, tmp_path):
    import astral_toolkit.gamedata as G
    from astral_toolkit.trade import names
    from astral_toolkit.update import data_pack, uex

    _b6(monkeypatch, tmp_path)
    t1, i1 = names.table(), names._index()
    assert names.table() is t1 and names._index() is i1  # 同一版本同一个对象
    _write_min_sources(
        tmp_path,
        **{**_B6_SOURCES, "zh_names.json": {"医疗笔": "Medpen", "新名字": "New Name"}},
    )
    G.rebuild()  # 没调任何 cache_clear
    assert names.table() is not t1 and names.table()["新名字"] == "New Name"
    assert names._index() is not i1
    assert names.canonical("新名字", "") == ("新名字", "New Name")
    assert names.zh_for("New Name") == "新名字"
    # 收口 2 删了 cache_clear 壳：缓存只跟版本走，谁也不用按名字清
    assert not hasattr(names.table, "cache_clear") and not hasattr(
        names._index, "cache_clear"
    )
    monkeypatch.setattr(uex, "apply_live", lambda *a, **k: None)
    data_pack.clear_caches()
    assert names.table()["新名字"] == "New Name"


def test_names_empty_when_db_unavailable(monkeypatch, tmp_path):
    from astral_toolkit.core import paths
    from astral_toolkit.trade import names

    _b6(monkeypatch, tmp_path)
    monkeypatch.setattr(
        paths, "DATA", tmp_path / "empty"
    )  # 没有 shops.json：库建不出来
    assert names.table() == {}  # R11：不往外抛
    assert names.to_english("医疗笔") == [] and names.suggest("医疗") == []
    assert names.canonical("医疗笔", "") is None and names.zh_for("Medpen") is None
    paths.DATA = tmp_path  # 换回有数据的目录：立刻正常（失败没被缓存）
    assert names.table()["医疗笔"] == "Medpen"
    assert names.to_english("医疗笔") == ["Old Medpen Name"]


def test_names_does_not_read_json_or_call_loaders(monkeypatch, tmp_path):
    import astral_toolkit.gamedata as G
    from astral_toolkit.crafting import loot, shops
    from astral_toolkit.trade import names

    def boom(*a, **k):
        raise AssertionError("不该再读旧数据")

    _b6(monkeypatch, tmp_path)
    G.ensure()
    for p in tmp_path.glob("*.json"):
        p.unlink()  # data/ 只剩 gamedata/
    monkeypatch.setattr(shops, "load", boom)
    monkeypatch.setattr(loot, "load_index", boom)
    assert names.table()["医疗笔"] == "Medpen"
    assert names.canonical("", "Medpen") == ("医疗笔", "Medpen")


# ---------------------------------------------------------------- Task 3：trade/gamekey


def _legacy_gamekey_index(d):
    """迁移前 trade/gamekey._index() 的函数体原样，wiki_items() 换成直接读 d/wiki_items.json"""
    from astral_toolkit.trade.gamekey import _fold

    rows = (_read(d, "wiki_items.json") or {}).get("items") or []
    by_name = {}
    for w in rows:
        by_name.setdefault(_fold(w.get("n")), w)
    uuid = {}
    try:
        for u, en, cls, *_ in _read(d, "loot_index.json").get("rows") or []:
            uuid.setdefault((cls or "").lower(), u)
    except (OSError, ValueError):
        pass
    alias = {}
    try:
        for old, new in (_read(d, "name_aliases.json") or {}).items():
            alias[_fold(old)] = new
    except (OSError, ValueError):
        pass
    return {"by_name": by_name, "uuid": uuid, "alias": alias}


def _legacy_resolve(idx, name_en):
    """迁移前 trade/gamekey.resolve() 的函数体原样"""
    from astral_toolkit.trade.gamekey import _fold

    k = _fold(name_en)
    if not k:
        return None
    w = idx["by_name"].get(k) or idx["by_name"].get(_fold(idx["alias"].get(k, "")))
    if not w or not w.get("cls"):
        return None
    cls = w["cls"].lower()
    u = idx["uuid"].get(cls) or next(
        (
            idx["uuid"][a.lower()]
            for a in w.get("alt") or []
            if a.lower() in idx["uuid"]
        ),
        "",
    )
    return cls, u


_GK_QUERIES = [
    "Medpen",
    "MEDPEN",
    "Lawson Mining Laser",
    "Lawson Mining Iaser",
    "Some Paint",
    "Medi Pen",
    "Venture Arms",
    "No Class Thing",
    "",
    "zzz",
]


def test_gamekey_resolve_equals_legacy_on_sample(monkeypatch, tmp_path):
    from astral_toolkit.trade import gamekey

    _b6(monkeypatch, tmp_path)
    idx = _legacy_gamekey_index(tmp_path)
    got = [gamekey.resolve(q) for q in _GK_QUERIES]
    assert got == [_legacy_resolve(idx, q) for q in _GK_QUERIES]
    assert got[:5] == [
        ("medpen_01", "u1"),  # 同折叠名首个 wiki 行；同类名首个掉落行（G2、G4）
        ("medpen_01", "u1"),
        ("laser_s0", ""),
        ("klein_s0", "u3"),
        ("paint_01", ""),  # 涂装：物品目录丢掉的噪声行照样能解析（G3）
    ]
    assert got[7:] == [None, None, None]  # 没类名（G7）、空、对不上


def test_gamekey_fold_does_not_merge_l_and_i(monkeypatch, tmp_path):
    from astral_toolkit.trade import gamekey

    _b6(monkeypatch, tmp_path)
    assert gamekey.resolve("Lawson Mining Laser") == ("laser_s0", "")  # G1：不做 l→i
    assert gamekey.resolve("Lawson Mining Iaser") == ("klein_s0", "u3")


def test_gamekey_alias_last_wins_and_unfiltered(monkeypatch, tmp_path):
    from astral_toolkit.trade import gamekey

    _b6(monkeypatch, tmp_path)
    assert gamekey.resolve("Medi Pen") == ("laser_s0", "")  # G5：同折叠旧写法后写覆盖
    assert gamekey.resolve("Venture Arms") == (
        "laser_s0",
        "",
    )  # 旧写法本身是商店物品也照收


def test_gamekey_alt_class_fallback_in_order(monkeypatch, tmp_path):
    from astral_toolkit.trade import gamekey

    _b6(monkeypatch, tmp_path)
    # klein_s0 掉落里没有 → alt 按顺序：nope_x 没有、klein_s0_b（掉落里是大写）有 → u3，不看后面的 medpen_01（G8）
    assert gamekey.resolve("Lawson Mining Iaser") == ("klein_s0", "u3")


def test_gamekey_none_when_db_unavailable(monkeypatch, tmp_path):
    from astral_toolkit.core import paths
    from astral_toolkit.trade import gamekey

    _b6(monkeypatch, tmp_path)
    monkeypatch.setattr(paths, "DATA", tmp_path / "empty")
    assert gamekey.resolve("Medpen") is None  # G9：不往外抛
    paths.DATA = tmp_path
    assert gamekey.resolve("Medpen") == ("medpen_01", "u1")  # 失败没被缓存


def test_gamekey_refreshes_after_alias_change(monkeypatch, tmp_path):
    import astral_toolkit.gamedata as G
    from astral_toolkit.trade import gamekey

    _b6(monkeypatch, tmp_path)
    assert gamekey.resolve("Zed Pen") is None
    (tmp_path / "name_aliases.json").write_text(  # 只改这一份，wiki_items.json 不动
        json.dumps({"Zed Pen": "Medpen"}), encoding="utf-8"
    )
    G.rebuild()  # 只改了旧写法：以前的索引只认 wiki_items 那份 list，不会刷新（G10，允许差异）
    assert gamekey.resolve("Zed Pen") == ("medpen_01", "u1")
    assert gamekey.resolve("Medi Pen") is None


# ---------------------------------------------------------------- Task 4：调用方冒烟（调用方代码不改）


def _catalog(tmp_path):
    from astral_toolkit.trade.catalog import Catalog
    from astral_toolkit.trade.storage import Database

    return Catalog(Database(tmp_path / "inv" / "trade.db"))


def test_catalog_search_uses_to_english(monkeypatch, tmp_path):
    from astral_toolkit.trade.models import Item

    _b6(monkeypatch, tmp_path)
    cat = _catalog(tmp_path)
    cat.upsert([Item("uex:1", "Old Medpen Name", None), Item("uex:2", "Tin", None)])
    assert [i.id for i in cat.search("医疗笔")] == [
        "uex:1"
    ]  # 中文 → 汉化包英文原文 → 库存物品
    assert [i.id for i in cat.search("锡")] == ["uex:2"]


def test_catalog_fill_keys_resolves(monkeypatch, tmp_path):
    from astral_toolkit.trade.models import Item

    _b6(monkeypatch, tmp_path)
    cat = _catalog(tmp_path)
    cat.upsert(
        [
            Item("uex:1", "Medpen", None),
            Item("uex:2", "Lawson Mining Iaser", None),
            Item("uex:3", "Nothing Here", None),
        ]
    )  # upsert 里会调 fill_keys
    assert cat.game_key("uex:1") == ("medpen_01", "u1")
    assert cat.game_key("uex:2") == ("klein_s0", "u3")
    assert cat.game_key("uex:3") is None
    assert cat.fill_keys() == 0  # 已经填过的不再填


def test_parser_and_market_service_import_ok(monkeypatch, tmp_path):
    import astral_toolkit.trade.market_service  # noqa: F401
    import astral_toolkit.trade.parser  # noqa: F401
    from astral_toolkit.trade import names

    _b6(monkeypatch, tmp_path)
    a = names.to_english("医疗")[:3]
    assert (
        a and names.to_english("医疗")[:3] == a
    )  # market_service 连调两次，结果要一致


def test_trade_names_module_has_no_toplevel_gamedata_import():
    """建库时 gamedata/_import → trade.names：trade/names.py、trade/gamekey.py 顶层 import gamedata 会循环"""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "astral_toolkit" / "trade"
    for name in ("names.py", "gamekey.py"):
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                mods = [node.module or ""] + [a.name for a in node.names]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            else:
                continue
            assert not any("gamedata" in m for m in mods), (name, mods)


def test_tasks_catalog_zh_of_refreshes_with_table(monkeypatch, tmp_path):
    import astral_toolkit.gamedata as G
    from astral_toolkit.tasks import catalog as C

    _b6(monkeypatch, tmp_path)
    assert C._zh_of("Medpen") == "医疗笔"
    assert C._zh_of("LAWSON MINING LASER") == "劳森"
    _write_min_sources(
        tmp_path, **{**_B6_SOURCES, "zh_names.json": {"新医疗笔": "Medpen"}}
    )
    G.rebuild()  # 更新数据后：以前反查表挂在函数属性上永不失效（矩阵 §9 第 4 条）
    assert C._zh_of("Medpen") == "新医疗笔"
    assert C._zh_of("LAWSON MINING LASER") == ""
