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
    from sc_mining.gamedata import names as gn

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
    from sc_mining.gamedata import names as gn

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
    from sc_mining.gamedata import names as gn

    _b6(monkeypatch, tmp_path)
    assert gn.alias_pairs() == (
        ("Medi Pen", "Medpen"),
        ("Medi-Pen", "Lawson Mining Laser"),
        ("Venture Arms", "Lawson Mining Laser"),  # item_names 里被拒的那条也在
    )


def test_class_uuids_source_order(monkeypatch, tmp_path):
    from sc_mining.gamedata import names as gn

    _b6(monkeypatch, tmp_path)
    assert gn.class_uuids() == (
        ("medpen_01", "u1"),
        ("jacket_01", "u2"),
        ("KLEIN_S0_B", "u3"),
        ("MEDPEN_01", "u4"),
    )


def test_names_topic_shares_outer_snapshot(monkeypatch, tmp_path):
    import sc_mining.gamedata as G
    from sc_mining.gamedata import names as gn

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
    import sc_mining.gamedata as G
    from sc_mining.gamedata import names as gn

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
