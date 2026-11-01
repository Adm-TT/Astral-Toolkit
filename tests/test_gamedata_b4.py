"""游戏数据层批 4：loot 查询主题，以及掉落查询（crafting/loot.py 的 find / _wiki_classes / mine_info / detail 取版本）改走数据层

全部用 tmp_path 当 data/ 根（monkeypatch paths.DATA 和 loot 的 INDEX / CACHE_DIR / DETAILS），不读真实 data/、不联网、不写 userdata/。"""

from tests.test_gamedata import _MIN_SOURCES, _write_min_sources
from tests.test_gamedata_b1 import _setup


def _loot_src(rows, **extra):
    """loot_index.json 的覆盖：rows 是 [uuid, en, cls, rarity, n, zh]"""
    return {"loot_index.json": {"version": "4.10.2LIVE", "rows": rows, **extra}}


# ---------------------------------------------------------------- Task 1：gamedata.loot 查询主题


def test_loot_rows_order_and_fold(monkeypatch, tmp_path):
    from sc_mining.crafting.loot import _fold
    from sc_mining.gamedata import loot as T

    _setup(
        monkeypatch,
        tmp_path,
        **_loot_src(
            [
                ["u9", "Lawson Laser", "Laser_Lawson_01", "rare", 2, "劳森 激光"],
                ["u1", "Medpen", "medpen_01", "", 0, ""],
            ]
        ),
    )
    rows = T.rows()
    assert [r.uuid for r in rows] == ["u9", "u1"]  # 源顺序，不是 uuid 顺序
    r = rows[0]
    assert (r.en, r.zh, r.rarity, r.n) == ("Lawson Laser", "劳森 激光", "rare", 2)
    assert r.norm_en == _fold("Lawson Laser") and r.norm_zh == _fold("劳森 激光")
    assert r.cls_lower == "laser_lawson_01" and r.source_order == 0


def test_loot_rows_cached_per_version(monkeypatch, tmp_path):
    import sc_mining.gamedata as G
    from sc_mining.gamedata import loot as T

    _setup(monkeypatch, tmp_path)
    a = T.rows()
    assert T.rows() is a  # 同一版本只建一次
    rows = _MIN_SOURCES["loot_index.json"]["rows"] + [
        ["u3", "New Thing", "new_01", "", 1, "新东西"]
    ]
    _write_min_sources(tmp_path, **_loot_src(rows))
    G.rebuild()
    b = T.rows()
    assert b is not a and [r.uuid for r in b][-1] == "u3"


def test_loot_exact_ignores_empty_keys(monkeypatch, tmp_path):
    from sc_mining.crafting.loot import _fold
    from sc_mining.gamedata import loot as T

    _setup(
        monkeypatch,
        tmp_path,
        **_loot_src(
            [
                ["u1", "Medpen", "medpen_01", "", 3, "医疗笔"],
                ["u2", "", "blank_01", "", 1, ""],  # 英文、中文都是空：空键不能命中它
                ["u3", "Medpen", "medpen_ai_exclusive", "", 1, ""],
            ]
        ),
    )
    assert T.exact("", "") == ()
    assert [r.uuid for r in T.exact(_fold("Medpen"), "")] == ["u1", "u3"]
    assert [r.uuid for r in T.exact("", _fold("医疗笔"))] == ["u1"]
    assert [r.uuid for r in T.exact("zzz", _fold("医疗笔"))] == ["u1"]  # 英文或中文


def test_loot_by_cls_prefix_underscore_is_literal(monkeypatch, tmp_path):
    from sc_mining.gamedata import loot as T

    _setup(
        monkeypatch,
        tmp_path,
        **_loot_src(
            [
                ["u1", "A", "A_B_01", "", 1, ""],
                ["u2", "B", "AxB_01", "", 1, ""],  # LIKE 'a_b%' 会把它也算进来
                ["u3", "C", "a_b", "", 1, ""],
                ["u4", "D", "b_a_b", "", 1, ""],
                ["u5", "E", "a%b", "", 1, ""],
            ]
        ),
    )
    assert [r.uuid for r in T.by_cls_prefix("a_b")] == ["u1", "u3"]
    assert [r.uuid for r in T.by_cls_prefix("a%")] == ["u5"]
    assert T.by_cls_prefix("zzz") == ()


def test_wiki_classes_includes_alt_and_drops_empty(monkeypatch, tmp_path):
    from sc_mining.crafting.loot import _fold
    from sc_mining.gamedata import loot as T

    _setup(
        monkeypatch,
        tmp_path,
        **{
            "wiki_items.json": {
                "items": [
                    {
                        "n": "Citadel Core",
                        "cls": "Core_01",
                        "alt": ["Core_01_AI_Exclusive", ""],
                    },
                    {
                        "n": "Citadei Core",
                        "cls": "",
                        "alt": ["Core_02"],
                    },  # l→i 折叠后同名
                    {"n": "Other", "cls": "other_01"},
                ]
            }
        },
    )
    assert T.wiki_classes(_fold("Citadel Core")) == frozenset(
        {"core_01", "core_01_ai_exclusive", "core_02"}
    )
    assert T.wiki_classes(_fold("Nothing")) == frozenset()


def test_index_meta_three_states(monkeypatch, tmp_path):
    import sc_mining.gamedata as G
    from sc_mining.gamedata import loot as T

    _setup(monkeypatch, tmp_path)
    assert T.index_meta() == {"version": "4.10.2LIVE"}
    _write_min_sources(tmp_path, **{"loot_index.json": {"rows": []}})
    G.rebuild()
    assert T.index_meta() == {}  # 有文件、没有 version 键
    (tmp_path / "loot_index.json").unlink()
    G.rebuild()
    assert T.index_meta() is None  # 没有掉落索引


def test_loot_topic_uses_outer_snapshot(monkeypatch, tmp_path):
    import sc_mining.gamedata as G
    from sc_mining.crafting.loot import _fold
    from sc_mining.gamedata import loot as T

    _setup(monkeypatch, tmp_path)
    G.ensure()
    with G.snapshot() as s:
        before = len(T.rows(s))
        rows = _MIN_SOURCES["loot_index.json"]["rows"] + [
            ["u3", "New Thing", "new_01", "", 1, "新东西"]
        ]
        _write_min_sources(tmp_path, **_loot_src(rows))
        G.rebuild()  # 中途发布新代
        assert len(T.rows(s)) == before  # 传进来的快照还是旧代
        assert len(T.rows()) == before  # 不传也复用外层快照（嵌套）
        assert T.exact(_fold("New Thing"), "") == ()
        assert T.by_cls_prefix("new_") == ()
    assert len(T.rows()) == before + 1  # 出了快照读到新代
    assert [r.uuid for r in T.exact(_fold("New Thing"), "")] == ["u3"]


# ---------------------------------------------------------------- Task 2：find 与 _wiki_classes 改走数据层

# 最小源：同名多实体（wiki 类名含 alt / 变体 / 普通，n 有并列）、l/I 混写、中文 ≥3 子串、英文 5 / 6 字符边界、
# wiki 里有但掉落没有完全同名、部分匹配超过 5 个
_FIND_ROWS = [
    ["c1", "Citadel Core", "Core_01_AI_Exclusive", "common", 5, "要塞 胸甲"],
    ["c2", "Citadel Core", "core_01_b", "common", 7, "要塞 胸甲"],
    ["c3", "Citadel Core", "Core_01", "rare", 5, "要塞 胸甲"],
    ["c4", "Citadel Core", "core_01_c", "common", 7, "要塞 胸甲"],
    ["k1", "Combat Knife", "knife_01_gungame", "common", 3, "战术匕首"],
    ["k2", "Combat Knife", "knife_01_b", "common", 3, "战术匕首"],
    ["t1", "Twin Thing", "twin_01", "", 2, ""],
    ["t2", "Twin Thing", "twin_02", "", 4, ""],
    ["t3", "Twin Thing", "twin_03", "", 4, ""],
    ["g1", "Ghost Box", "box_ai_exclusive", "", 1, ""],
    ["g2", "Ghost Box", "box_gungame", "", 2, ""],
    ["l1", "Lawson Laser", "laser_01", "rare", 2, "劳森 激光器"],
    ["p1", "Zeus Helmet Echo", "zeus_echo", "rare", 1, "宙斯 探索头盔 回声"],
    ["p2", "Zeus Helmet Echo Dark", "zeus_echo_dark", "rare", 1, "宙斯 探索头盔 暗"],
    ["p3", "Zeus Helmet Test", "zeus_x_debug", "rare", 1, "宙斯 探索头盔 测试"],
    ["m1", "Medpen", "medpen_01", "common", 3, "医疗笔"],
    ["a1", "Abcde", "abcde_01", "", 1, ""],
    ["a2", "Abcdefg Long", "abcdefg_01", "", 1, ""],
    *[
        [f"q{i}", f"Gadget Mk {i}", f"gadget_0{i}", "", 1, f"小装置 {i} 型"]
        for i in range(1, 7)
    ],
]
_FIND_WIKI = {
    "items": [
        {"n": "Citadel Core", "cls": "core_01_c", "alt": ["Core_01", ""]},
        {"n": "Zeus Helmet", "cls": "zeus_base"},  # wiki 有、掉落里没有完全同名
        {"n": "Medpen", "cls": "medpen_01", "t": "Consumable"},
    ]
}
_FIND_INPUTS = [
    ("Citadel Core", ""),
    ("", "要塞 胸甲"),
    ("Citadel Core", "不对的中文"),
    ("Combat Knife", ""),
    ("Twin Thing", ""),
    ("Ghost Box", ""),
    ("Iawson Iaser", ""),
    ("LAWSON-laser", ""),
    ("Zeus Helmet", ""),
    ("Zeus H", ""),
    ("eus Helmet", ""),
    ("Zeus", ""),
    ("", "探索头盔"),
    ("", "头盔"),
    ("Abcde", ""),
    ("Abcdef", ""),
    ("bcdef", ""),
    ("Gadget", ""),
    ("adget", ""),
    ("", "小装置"),
    ("", ""),
    ("%", ""),
    ("_", "%"),
    ("Nothing", "无"),
    ("Medpen", "医疗笔"),
    ("", "医疗笔"),
    ("medpen", "不对"),
]


def _find_setup(monkeypatch, tmp_path):
    return _setup(
        monkeypatch,
        tmp_path,
        **_loot_src(_FIND_ROWS),
        **{"wiki_items.json": _FIND_WIKI},
    )


def _legacy_find(tmp_path, name_en="", name_zh=""):
    """迁移前 crafting/loot.py 的 find + _folded_rows + _wiki_classes（行号 L92-159），只在测试里存在：直接读最小源的 JSON"""
    import json

    from sc_mining.crafting.loot import _VARIANT, _fold

    f = tmp_path / "loot_index.json"
    idx = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    if not idx:
        return []
    wf = tmp_path / "wiki_items.json"
    wiki = (
        (json.loads(wf.read_text(encoding="utf-8")).get("items") or [])
        if wf.exists()
        else []
    )

    def wiki_classes(name):
        try:
            k = _fold(name)
            out = set()
            for w in wiki:
                if _fold(w.get("n")) == k:
                    out.add((w.get("cls") or "").lower())
                    out.update(c.lower() for c in w.get("alt") or [])
            return out - {""}
        except Exception:
            return set()

    rows = [
        (u, en, zh, rar, _fold(en), _fold(zh), (cls or "").lower(), n or 0)
        for u, en, cls, rar, n, zh in idx["rows"]
    ]
    ke, kz = _fold(name_en), _fold(name_zh)
    exact, part = [], []
    for u, en, zh, rar, fe, fz, cls, n in rows:
        if (ke and fe == ke) or (kz and fz == kz):
            exact.append((u, en, zh, rar, cls, n))
        elif (
            (ke and len(ke) >= 6 and fe.startswith(ke))
            or (ke and len(ke) >= 5 and ke in fe)
            or (kz and len(kz) >= 3 and kz in fz)
        ):
            part.append((u, en, zh, rar, cls, n))
    if exact:
        good = wiki_classes(name_en or (exact[0][1] if not name_en else ""))
        pick = (
            [h for h in exact if h[4] in good]
            or [h for h in exact if not _VARIANT.search(h[4])]
            or exact
        )
        pick.sort(key=lambda h: -h[5])
        return [h[:4] for h in pick]
    if name_en and wiki_classes(name_en):
        return []
    part = [h for h in part if not _VARIANT.search(h[4])]
    return [h[:4] for h in part[:5]]


def test_find_equals_legacy_on_sample(monkeypatch, tmp_path):
    from sc_mining.crafting import loot

    _find_setup(monkeypatch, tmp_path)
    nonempty = 0
    for en, zh in _FIND_INPUTS:
        got, want = loot.find(en, zh), _legacy_find(tmp_path, en, zh)
        assert got == want, (en, zh, got, want)
        nonempty += bool(want)
    assert nonempty >= 12  # 样例真的走到了精确 / 部分 / 截断这些分支


def test_find_exact_prefers_wiki_class_then_non_variant_then_n_desc(
    monkeypatch, tmp_path
):
    from sc_mining.crafting import loot

    _find_setup(monkeypatch, tmp_path)
    ids = lambda hits: [h[0] for h in hits]  # noqa: E731
    # wiki 类名（含 alt 的 Core_01）优先；同 n 保持源顺序（稳定排序）
    assert ids(loot.find("Citadel Core")) == ["c4", "c3"]
    # 只给中文：用排序前源顺序第一个的英文名去查 wiki 类名
    assert ids(loot.find("", "要塞 胸甲")) == ["c4", "c3"]
    assert ids(loot.find("Combat Knife")) == ["k2"]  # 没有 wiki：去掉变体
    assert ids(loot.find("Twin Thing")) == ["t2", "t3", "t1"]  # n 降序、并列按源顺序
    assert ids(loot.find("Ghost Box")) == ["g2", "g1"]  # 全是变体：退回全部
    assert loot.find("Zeus Helmet") == []  # wiki 有这件、掉落只有开头像的：不拿别的顶
    assert ids(loot.find("Gadget")) == ["q1", "q2", "q3", "q4", "q5"]  # 部分匹配取前 5
    assert loot.find("Medpen")[0] == ("m1", "Medpen", "医疗笔", "common")  # 返回形状


def test_find_refreshes_after_rebuild_without_clear_caches(monkeypatch, tmp_path):
    import sc_mining.gamedata as G
    from sc_mining.crafting import loot

    _find_setup(monkeypatch, tmp_path)
    assert loot.find("Brand New Thing") == []
    _write_min_sources(
        tmp_path,
        **_loot_src(_FIND_ROWS + [["n1", "Brand New Thing", "new_01", "", 1, "全新"]]),
        **{"wiki_items.json": _FIND_WIKI},
    )
    G.rebuild()  # 不调 data_pack.clear_caches
    assert [h[0] for h in loot.find("Brand New Thing")] == ["n1"]
    assert [h[0] for h in loot.find("Brand Ne")] == ["n1"]  # 部分匹配走的整表缓存也换了


def test_find_empty_when_no_index_or_db_unavailable(monkeypatch, tmp_path):
    import sc_mining.gamedata as G
    from sc_mining.core import paths
    from sc_mining.crafting import loot

    _find_setup(monkeypatch, tmp_path)
    (tmp_path / "loot_index.json").unlink()
    G.rebuild()
    assert loot.find("Citadel Core") == [] and loot.find("Gadget") == []
    monkeypatch.setattr(
        paths, "DATA", tmp_path / "empty"
    )  # 没有 shops.json：库建不出来
    assert loot.find("Citadel Core", "要塞 胸甲") == []  # 不往外抛


def test_find_does_not_read_json(monkeypatch, tmp_path):
    from sc_mining.crafting import itemsearch, loot

    def boom(*a, **kw):
        raise AssertionError("查询路径不该再读 JSON")

    _find_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(loot, "load_index", boom)
    monkeypatch.setattr(itemsearch, "wiki_items", boom)
    assert [h[0] for h in loot.find("Citadel Core")] == [
        "c4",
        "c3",
    ]  # wiki 类名照样用上
    assert loot.find("Zeus Helmet") == []
    assert loot._wiki_classes("Citadel Core") == {"core_01_c", "core_01"}


def test_wiki_classes_swallows_db_errors(monkeypatch, tmp_path):
    from sc_mining.core import paths
    from sc_mining.crafting import loot

    _find_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(paths, "DATA", tmp_path / "empty")
    assert loot._wiki_classes("Citadel Core") == set()  # 旧代码出错返回空集，不抛


def test_clear_caches_still_safe(monkeypatch, tmp_path):
    from sc_mining.crafting import loot
    from sc_mining.update import data_pack, uex

    _find_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(
        uex, "apply_live", lambda *a, **kw: None
    )  # 不碰真实 mining.data
    assert loot.find("Combat Knife")
    data_pack.clear_caches()
    assert isinstance(loot._folded, dict)
    assert [h[0] for h in loot.find("Combat Knife")] == ["k2"]
