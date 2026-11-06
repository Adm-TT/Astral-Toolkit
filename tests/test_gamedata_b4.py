"""游戏数据层批 4：loot 查询主题，以及掉落查询（crafting/loot.py 的 find / _wiki_classes / mine_info / detail 取版本）改走数据层

全部用 tmp_path 当 data/ 根（monkeypatch paths.DATA 和 loot 的 INDEX / CACHE_DIR / DETAILS），不读真实 data/、不联网、不写 userdata/。"""

from tests.test_gamedata import _MIN_SOURCES, _write_min_sources
from tests.test_gamedata_b1 import _setup


def _loot_src(rows, **extra):
    """loot_index.json 的覆盖：rows 是 [uuid, en, cls, rarity, n, zh]"""
    return {"loot_index.json": {"version": "4.10.2LIVE", "rows": rows, **extra}}


# ---------------------------------------------------------------- Task 1：gamedata.loot 查询主题


def test_loot_rows_order_and_fold(monkeypatch, tmp_path):
    from astral_toolkit.tasks.catalog_queries.loot import _fold
    from astral_toolkit.gamedata import loot as T

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
    import astral_toolkit.gamedata as G
    from astral_toolkit.gamedata import loot as T

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
    from astral_toolkit.tasks.catalog_queries.loot import _fold
    from astral_toolkit.gamedata import loot as T

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
    from astral_toolkit.gamedata import loot as T

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
    from astral_toolkit.tasks.catalog_queries.loot import _fold
    from astral_toolkit.gamedata import loot as T

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
    import astral_toolkit.gamedata as G
    from astral_toolkit.gamedata import loot as T

    _setup(monkeypatch, tmp_path)
    assert T.index_meta() == {"version": "4.10.2LIVE"}
    _write_min_sources(tmp_path, **{"loot_index.json": {"rows": []}})
    G.rebuild()
    assert T.index_meta() == {}  # 有文件、没有 version 键
    (tmp_path / "loot_index.json").unlink()
    G.rebuild()
    assert T.index_meta() is None  # 没有掉落索引


def test_loot_topic_uses_outer_snapshot(monkeypatch, tmp_path):
    import astral_toolkit.gamedata as G
    from astral_toolkit.tasks.catalog_queries.loot import _fold
    from astral_toolkit.gamedata import loot as T

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

    from astral_toolkit.catalog.loot import VARIANT as _VARIANT
    from astral_toolkit.tasks.catalog_queries.loot import _fold

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
    from astral_toolkit.tasks.catalog_queries import loot

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
    from astral_toolkit.tasks.catalog_queries import loot

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
    import astral_toolkit.gamedata as G
    from astral_toolkit.tasks.catalog_queries import loot

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
    import astral_toolkit.gamedata as G
    from astral_toolkit.core import paths
    from astral_toolkit.tasks.catalog_queries import loot

    _find_setup(monkeypatch, tmp_path)
    (tmp_path / "loot_index.json").unlink()
    G.rebuild()
    assert loot.find("Citadel Core") == [] and loot.find("Gadget") == []
    monkeypatch.setattr(
        paths, "DATA", tmp_path / "empty"
    )  # 没有 shops.json：库建不出来
    assert loot.find("Citadel Core", "要塞 胸甲") == []  # 不往外抛


def test_find_does_not_read_json(monkeypatch, tmp_path):
    from astral_toolkit.tasks.catalog_queries import loot
    from astral_toolkit.update import loot as loot_index
    from astral_toolkit.tasks.catalog_queries import search as itemsearch

    def boom(*a, **kw):
        raise AssertionError("查询路径不该再读 JSON")

    _find_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(loot_index, "load_index", boom)
    assert not hasattr(
        itemsearch, "wiki_items"
    )  # 读 JSON 的那份收口 2 删了；类名走 gamedata.names.wiki_classes
    assert [h[0] for h in loot.find("Citadel Core")] == [
        "c4",
        "c3",
    ]  # wiki 类名照样用上
    assert loot.find("Zeus Helmet") == []
    assert loot._wiki_classes("Citadel Core") == {"core_01_c", "core_01"}


def test_wiki_classes_swallows_db_errors(monkeypatch, tmp_path):
    from astral_toolkit.core import paths
    from astral_toolkit.tasks.catalog_queries import loot

    _find_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(paths, "DATA", tmp_path / "empty")
    assert loot._wiki_classes("Citadel Core") == set()  # 旧代码出错返回空集，不抛


def test_clear_caches_still_safe(monkeypatch, tmp_path):
    from astral_toolkit.tasks.catalog_queries import loot
    from astral_toolkit.update import data_pack, uex

    _find_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(
        uex, "apply_live", lambda *a, **kw: None
    )  # 不碰真实 mining.data
    assert loot.find("Combat Knife")
    data_pack.clear_caches()
    assert not hasattr(loot, "_folded")  # 收口 2 删了这个只被 clear_caches 写的壳
    assert [h[0] for h in loot.find("Combat Knife")] == ["k2"]


# ---------------------------------------------------------------- Task 3：detail 的版本、mine_info


def _detail_env(monkeypatch, tmp_path):
    """明细相关路径都换到 tmp_path；整包 from_zip、下载 get_json 换成记录器（不联网、不读真实整包）"""
    from astral_toolkit.infrastructure.persistence import loot_details
    from astral_toolkit.infrastructure.providers import loot_site
    from astral_toolkit.tasks.catalog_queries import loot
    from astral_toolkit.update import loot as loot_index

    rec = {"zip": [], "get": []}
    monkeypatch.setattr(loot_details, "DETAILS", tmp_path / "loot_details.zip")
    monkeypatch.setattr(loot_details, "CACHE_DIR", tmp_path / "loot")
    monkeypatch.setattr(loot_index, "INDEX", tmp_path / "loot_index.json")
    monkeypatch.setattr(loot_index, "_index", None)
    monkeypatch.setattr(loot, "_failed", {})
    monkeypatch.setattr(
        loot_details, "from_zip", lambda u, v: rec["zip"].append((u, v)) or None
    )

    def get(url, timeout=60):
        rec["get"].append(url)
        return {"url": url}

    monkeypatch.setattr(loot_site, "get_json", get)
    return rec


def test_detail_version_from_meta_matches_legacy(monkeypatch, tmp_path):
    import json

    import astral_toolkit.gamedata as G
    from astral_toolkit.infrastructure.providers import loot_site
    from astral_toolkit.tasks.catalog_queries import loot
    from tests.minipytest import raises

    _setup(monkeypatch, tmp_path)
    rec = _detail_env(monkeypatch, tmp_path)

    def legacy_version():
        f = tmp_path / "loot_index.json"
        idx = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        return (idx or {}).get("version", "4.10.2LIVE")

    cases = [
        _MIN_SOURCES["loot_index.json"],  # 有版本
        {"rows": []},  # 有索引、没有 version 键
        {"version": "4.11.0PTU", "rows": []},
        None,  # 没有索引
    ]
    for i, src in enumerate(cases):
        if src is None:
            (tmp_path / "loot_index.json").unlink()
        else:
            _write_min_sources(tmp_path, **{"loot_index.json": src})
        G.rebuild()
        u = f"u{i}"
        want = legacy_version()
        assert loot.detail(u, online=True) == {
            "url": f"{loot_site.BASE}{want}/q/{u}.json"
        }
        assert rec["zip"][-1] == (u, want)
        assert (tmp_path / "loot" / f"{want}_{u}.json").exists()
        assert loot.detail(u, online=False) == {
            "url": f"{loot_site.BASE}{want}/q/{u}.json"
        }  # 读缓存
    _write_min_sources(tmp_path, **{"loot_index.json": {"version": 4.1, "rows": []}})
    G.rebuild()
    with raises(ValueError):  # 版本不是字符串：和以前一样拒绝（原值类型照存）
        loot.detail("u9", online=False)


def test_detail_online_write_not_in_updating(monkeypatch, tmp_path):
    from astral_toolkit.tasks.catalog_queries import loot
    from tests.test_gamedata_b1 import _count_updating

    _setup(monkeypatch, tmp_path)
    _detail_env(monkeypatch, tmp_path)
    state = _count_updating(monkeypatch)
    assert loot.detail("u1", online=True)
    assert state["n"] == 0
    assert state["writes"] == [(tmp_path / "loot" / "4.10.2LIVE_u1.json", False)]


def test_detail_does_not_read_index_json(monkeypatch, tmp_path):
    from astral_toolkit.tasks.catalog_queries import loot
    from astral_toolkit.update import loot as loot_index

    def boom(*a, **kw):
        raise AssertionError("detail 不该再读 loot_index.json")

    _setup(monkeypatch, tmp_path)
    rec = _detail_env(monkeypatch, tmp_path)
    monkeypatch.setattr(loot_index, "load_index", boom)
    assert loot.detail("u1", online=True)
    assert rec["zip"] == [("u1", "4.10.2LIVE")]


def test_detail_default_version_when_db_unavailable(monkeypatch, tmp_path):
    from astral_toolkit.core import paths
    from astral_toolkit.tasks.catalog_queries import loot

    _setup(monkeypatch, tmp_path)
    rec = _detail_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        paths, "DATA", tmp_path / "empty"
    )  # 库建不出来：当没有索引，用默认版本
    assert loot.detail("u1", online=True)
    assert rec["zip"] == [("u1", "4.10.2LIVE")]


_ROCKS = [
    ["r1", "Carinite", "MineableRock_FPS_Carinite_01", "", 1, "科力晶"],
    [
        "r2",
        "Carinite (Pure)",
        "mineablerock_fps_carinite_pure_01",
        "",
        1,
        "科力晶（纯）",
    ],
    [
        "r3",
        "Fake",
        "mineablerockXfpsXcarinite",
        "",
        1,
        "",
    ],  # 下划线换成别的字符：LIKE 会误中
    ["r4", "Carinite", "harvestable_mineral_1h_carinite", "rare", 17, "科力晶"],
]


def _fake_details(monkeypatch):
    from astral_toolkit.tasks.catalog_queries import loot

    seen = []

    def detail(u, online=True):
        seen.append(u)
        return {"regions": [{"name": f"区域-{u}", "best": 0.25, "containers": []}]}

    monkeypatch.setattr(loot, "detail", detail)
    return seen


def _mine(key, online):
    """mine_info 的结果，断言不是 None（类型检查要知道下面能取下标）"""
    from typing import Any

    from astral_toolkit.tasks.catalog_queries import loot

    d = loot.mine_info(key, online=online)
    assert d is not None
    out: dict[str, Any] = d
    return out


def test_mine_info_cls_prefix_literal_and_skips_pure(monkeypatch, tmp_path):

    _setup(monkeypatch, tmp_path, **_loot_src(_ROCKS))
    _detail_env(monkeypatch, tmp_path)
    seen = _fake_details(monkeypatch)
    d = _mine("carinite", online=False)
    assert seen == ["r1"] and d["groups"] == [
        {"p": 0.25, "box": "", "regions": ["区域-r1"]}
    ]
    assert d["name"] == "科力晶" and d["mine"] is True and d["more"] == 0
    seen.clear()
    d = _mine("carinitepure", online=False)
    assert seen == ["r2"] and d["groups"][0]["regions"] == ["区域-r2"]
    seen.clear()
    assert _mine("janalite", online=False)["groups"] == [] and seen == []


def test_mine_info_online_downloads_when_no_index(monkeypatch, tmp_path):
    import json

    import astral_toolkit.gamedata as G
    from astral_toolkit.tasks.catalog_queries import loot
    from astral_toolkit.update import loot as loot_index

    _setup(monkeypatch, tmp_path, **_loot_src(_ROCKS))
    (tmp_path / "loot_index.json").unlink()
    G.rebuild()
    _detail_env(monkeypatch, tmp_path)
    _fake_details(monkeypatch)
    calls = []

    def update(version=None, progress=print):
        calls.append(1)
        data = {"version": "4.10.2LIVE", "rows": _ROCKS}
        with G.updating():
            (tmp_path / "loot_index.json").write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
        loot_index._index = data
        return data

    monkeypatch.setattr(loot_index, "update", update)
    assert loot.mine_info("carinite", online=False) is None and calls == []
    d = _mine("carinite", online=True)
    assert calls == [1] and d["groups"][0]["regions"] == ["区域-r1"]


def test_mine_info_none_when_download_fails(monkeypatch, tmp_path):
    import astral_toolkit.gamedata as G
    from astral_toolkit.tasks.catalog_queries import loot
    from astral_toolkit.update import loot as loot_index

    _setup(monkeypatch, tmp_path)
    (tmp_path / "loot_index.json").unlink()
    G.rebuild()
    _detail_env(monkeypatch, tmp_path)

    def update(version=None, progress=print):
        raise OSError("断网")

    monkeypatch.setattr(loot_index, "update", update)
    assert loot.mine_info("carinite", online=True) is None


def test_mine_info_empty_rows_does_not_download(monkeypatch, tmp_path):
    from astral_toolkit.update import loot as loot_index

    _setup(monkeypatch, tmp_path, **_loot_src([]))
    _detail_env(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(loot_index, "update", lambda *a, **kw: calls.append(1))
    d = _mine("carinite", online=True)
    assert calls == [] and d["groups"] == [] and d["more"] == 0


def test_mine_info_none_when_db_unavailable(monkeypatch, tmp_path):
    from astral_toolkit.core import paths
    from astral_toolkit.tasks.catalog_queries import loot
    from astral_toolkit.update import loot as loot_index

    _setup(monkeypatch, tmp_path, **_loot_src(_ROCKS))
    _detail_env(monkeypatch, tmp_path)
    monkeypatch.setattr(paths, "DATA", tmp_path / "empty")
    calls = []
    monkeypatch.setattr(loot_index, "update", lambda *a, **kw: calls.append("update"))
    monkeypatch.setattr(
        loot_index, "load_index", lambda *a, **kw: calls.append("load_index")
    )  # 连读本地索引也不该走到（不然 _detail_env 指的那份文件在，这条会空过）
    assert loot.mine_info("carinite", online=False) is None
    assert loot.mine_info("carinite", online=True) is None
    assert (
        calls == []
    )  # 库不可用 ≠ 没有索引：查询路径不联网、不读 JSON（收口 2，待做 ⑮）


# ---------------------------------------------------------------- Task 4：输出不变与更新流程保持


def _details_zip(path, version, details):
    import json
    import zipfile

    with zipfile.ZipFile(path, "w") as z:
        z.writestr("version.txt", version)
        for u, d in details.items():
            z.writestr(f"{u}.json", json.dumps(d, ensure_ascii=False))
    return path


_DETAILS = {
    # 8 个地区概率、箱子一样（合成一行，regions 有 8 个），再加 6 个更低的（top=5 截掉 → more 大于 0）
    "c4": {
        "raw": "Item.core_01_c",
        "regions": [
            {
                "name": f"地区{i}",
                "best": 0.0106,
                "containers": [
                    {
                        "name": "Lootable_Container_Large",
                        "loc": "前哨站",
                        "openp": 0.0106,
                    }
                ],
            }
            for i in range(8)
        ]
        + [
            {
                "name": f"低{i}",
                "best": 0.001 * (i + 1),
                "containers": [{"name": f"Box_{i}", "p": 0.001}],
            }
            for i in range(6)
        ],
    },
    # 「容器」就是物品自己：直接刷在场景里
    "k2": {
        "raw": "Item.Knife_01_B",
        "regions": [
            {
                "name": "洞穴",
                "best": 0.3,
                "containers": [
                    {"name": "Knife_01_B · 架子", "loc": "奖励室", "openp": 0.3}
                ],
            },
            {"name": "空地", "best": 0.05, "containers": []},
        ],
    },
}


def test_info_equal_legacy_on_sample(monkeypatch, tmp_path):
    """loot.info 离线、在线两种调法，新的找物品和旧的（legacy）结果一样；顺带钉住分组（多于 6 类地点、
    还有概率更低的、刷在场景里）和明细本机没有时离线挂起、在线断网报错
    （原来还比 loot.text 的整段文字，CL-C4 删了 text，改成看 info 本身）"""
    import json

    from astral_toolkit.catalog.loot import PLACED
    from astral_toolkit.infrastructure.persistence import loot_details
    from astral_toolkit.infrastructure.providers import loot_site
    from astral_toolkit.tasks.catalog_queries import loot

    _find_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(
        loot_details,
        "DETAILS",
        _details_zip(tmp_path / "loot_details.zip", "4.10.2LIVE", _DETAILS),
    )
    monkeypatch.setattr(loot_details, "CACHE_DIR", tmp_path / "loot")
    monkeypatch.setattr(
        loot_details, "_zip", {"z": None, "mtime": None, "version": None}
    )

    def no_net(*a, **kw):
        raise OSError("断网")

    monkeypatch.setattr(loot_site, "get_json", no_net)
    inputs = [
        ("Citadel Core", ""),
        ("Combat Knife", ""),
        ("Twin Thing", ""),
        ("Gadget", ""),
        ("Nothing", "无"),
    ]

    def run():
        out = []
        for en, zh in inputs:
            monkeypatch.setattr(loot, "_failed", {})
            out.append(loot.info(en, zh, online=False))
            monkeypatch.setattr(loot, "_failed", {})
            out.append(loot.info(en, zh))
        return out

    new = run()
    legacy_version = json.loads(
        (tmp_path / "loot_index.json").read_text(encoding="utf-8")
    )
    monkeypatch.setattr(
        loot, "find", lambda en="", zh="": _legacy_find(tmp_path, en, zh)
    )
    monkeypatch.setattr(
        loot, "_index_meta", lambda: {"version": legacy_version["version"]}
    )
    old = run()
    loot_details.close_bundle()
    assert new == old
    found = [d for d in new if d and "groups" in d]
    groups = [g for d in found for g in d["groups"]]
    assert any(len(g["regions"]) == 8 for g in groups)  # 多于 6 类地点
    assert any(d.get("more", 0) > 0 for d in found)  # 还有概率更低的地点
    assert any(PLACED in (g["box"] or "") for g in groups)  # 刷在场景里
    # 明细本机没有：离线挂起、在线断网报错
    assert new[4] == {"pending": True} and "暂时取不到" in new[5]["error"]
    assert new[8] is None and new[9] is None


def test_loot_update_still_inside_updating(monkeypatch, tmp_path):
    from astral_toolkit.infrastructure.providers import loot_site
    from astral_toolkit.update import loot as loot_index
    from tests.test_gamedata_b1 import _count_updating

    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(loot_index, "INDEX", tmp_path / "loot_index.json")
    monkeypatch.setattr(loot_index, "_index", None)
    monkeypatch.setattr(loot_site, "latest_version", lambda: "4.10.3LIVE")
    monkeypatch.setattr(
        loot_site,
        "get_json",
        lambda url, timeout=60: (
            {"version": "4.10.3LIVE"} if url.endswith("manifest.json") else []
        ),
    )
    state = _count_updating(monkeypatch)
    data = loot_index.update(progress=None)
    assert state["n"] == 1 and state["writes"] == [(tmp_path / "loot_index.json", True)]
    assert data == {"version": "4.10.3LIVE", "rows": []} and loot_index._index is data


def test_load_index_still_available_for_batch6(monkeypatch, tmp_path):
    from astral_toolkit.update import loot as loot_index

    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(loot_index, "INDEX", tmp_path / "loot_index.json")
    monkeypatch.setattr(loot_index, "_index", None)
    assert loot_index.load_index(False) == _MIN_SOURCES["loot_index.json"]


# ---------------------------------------------------------------- 目录迁移 Q3a 补测：改坏检查第一次没抓到的（老代码也没人测）


def test_detail_rejects_bad_uuid_before_touching_files(monkeypatch, tmp_path):
    """编号要拼进缓存路径和网址：不是字母数字、横线的（..\\ 之类、空的、太长的、不是字符串的）先拒，
    不碰整包、不建缓存目录、不联网"""
    from astral_toolkit.tasks.catalog_queries import loot
    from tests.minipytest import raises

    _setup(monkeypatch, tmp_path)
    rec = _detail_env(monkeypatch, tmp_path)
    for bad in ("../x", "a/b", "a\\b", "x.json", "", "x" * 65, 7, None):
        with raises(ValueError):
            loot.detail(bad, online=True)
    assert rec == {"zip": [], "get": []}
    assert not (tmp_path / "loot").exists()


def test_detail_backs_off_ten_minutes_after_failure(monkeypatch, tmp_path):
    """同一件联网失败后 10 分钟内不再试，直接报网络不通（断网时别每次都等超时）；别的物品照常试；过了 10 分钟再试"""
    from astral_toolkit.infrastructure.providers import loot_site
    from astral_toolkit.tasks.catalog_queries import loot

    _setup(monkeypatch, tmp_path)
    _detail_env(monkeypatch, tmp_path)
    calls = []

    def down(url, timeout=60):
        calls.append(url)
        raise OSError("断网")

    def err(u):
        try:
            loot.detail(u, online=True)
        except OSError as e:
            return str(e)
        raise AssertionError("断网却没报错")

    monkeypatch.setattr(loot_site, "get_json", down)
    assert err("u1") == "断网" and len(calls) == 1
    assert err("u1") == "网络不通，稍后再试" and len(calls) == 1  # 10 分钟内：不再联网
    assert err("u2") == "断网" and len(calls) == 2  # 别的物品照常试
    loot._failed["u1"] -= 601  # 过了 10 分钟
    assert err("u1") == "断网" and len(calls) == 3


def test_detail_drops_half_written_cache_file(monkeypatch, tmp_path):
    """单件缓存是半个文件（旧版直接写、写到一半被结束）：删掉当没有——离线照样挂起，联网现取再写好"""
    from astral_toolkit.tasks.catalog_queries import loot

    _setup(monkeypatch, tmp_path)
    rec = _detail_env(monkeypatch, tmp_path)
    f = tmp_path / "loot" / "4.10.2LIVE_u1.json"
    f.parent.mkdir(parents=True)
    f.write_text('{"half": ', encoding="utf-8")
    try:
        loot.detail("u1", online=False)
    except loot.Pending:
        pass
    else:
        raise AssertionError("半个缓存文件不该当成有")
    assert not f.exists()  # 坏文件删了，不会一直卡在它上面
    assert loot.detail("u1", online=True) == {"url": rec["get"][-1]} and f.exists()


def test_close_bundle_closes_the_open_bundle(monkeypatch, tmp_path):
    """换整包前关掉正在读的那个（Windows 上打开着的文件不能替换）：真的关上，下次读再重新打开"""
    from astral_toolkit.infrastructure.persistence import loot_details

    z = _details_zip(tmp_path / "loot_details.zip", "4.10.2LIVE", {"u1": {"a": 1}})
    monkeypatch.setattr(loot_details, "DETAILS", z)
    monkeypatch.setattr(
        loot_details, "_zip", {"z": None, "mtime": None, "version": None}
    )
    assert loot_details.from_zip("u1", "4.10.2LIVE") == {"a": 1}
    opened = loot_details._zip["z"]
    assert opened is not None and opened.fp is not None
    loot_details.close_bundle()
    assert opened.fp is None
    assert loot_details._zip == {"z": None, "mtime": None, "version": None}
    assert loot_details.from_zip("u1", "4.10.2LIVE") == {"a": 1}  # 重新打开
    loot_details.close_bundle()


def test_loot_update_version_order(monkeypatch, tmp_path):
    """更新掉落索引取版本的先后：站点最新 → 本机索引里的 → 4.10.2LIVE；清单里没写版本就用取到的这个"""
    import json

    from astral_toolkit.infrastructure.providers import loot_site
    from astral_toolkit.update import loot as loot_index
    from tests.test_gamedata_b1 import _count_updating

    _setup(monkeypatch, tmp_path)
    index = tmp_path / "loot_index.json"
    monkeypatch.setattr(loot_index, "INDEX", index)
    _count_updating(monkeypatch)  # 写文件换成记录：本机索引一直是下面写的这份
    urls = []

    def get(url, timeout=60):
        urls.append(url)
        return {} if url.endswith("manifest.json") else []

    def version(latest):
        monkeypatch.setattr(loot_site, "latest_version", lambda: latest)
        monkeypatch.setattr(loot_index, "_index", None)
        urls.clear()
        got = loot_index.update(progress=None)["version"]
        assert urls == [
            f"{loot_site.BASE}{got}/manifest.json",
            f"{loot_site.BASE}{got}/search.json",
        ], urls
        return got

    monkeypatch.setattr(loot_site, "get_json", get)
    index.write_text(
        json.dumps({"version": "4.10.9LIVE", "rows": []}), encoding="utf-8"
    )
    assert version("4.11.0LIVE") == "4.11.0LIVE"  # 站点最新优先
    assert version(None) == "4.10.9LIVE"  # 站点取不到：本机索引里的
    index.unlink()
    assert version(None) == "4.10.2LIVE"  # 都没有：默认


def test_instance_ore_names():
    """副本专属矿：英文名（带不带 (Ore)、大小写、纯的）和汉化包里的中文名（有没有空格）都认得；别的矿、普通物品不算"""
    from astral_toolkit.catalog.loot import instance_ore

    assert instance_ore("Carinite") == instance_ore("carinite (Ore)") == "carinite"
    assert instance_ore("Carinite (Pure)") == "carinitepure"
    assert instance_ore("", "杰金") == "jaclium"
    assert (
        instance_ore("", "科力晶（纯）")
        == instance_ore("", "纯净科力晶")
        == "carinitepure"
    )
    assert instance_ore("", "烁迪银 矿石") == "saldynium"
    assert instance_ore("Quantanium", "量子矿") is None and instance_ore() is None


def test_mine_info_english_names(monkeypatch, tmp_path):
    """副本专属矿开采点的英文名：纯科力晶是 Carinite (Pure)，其余首字母大写"""
    _setup(monkeypatch, tmp_path, **_loot_src(_ROCKS))
    _detail_env(monkeypatch, tmp_path)
    _fake_details(monkeypatch)
    pure = _mine("carinitepure", online=False)
    assert pure["en"] == "Carinite (Pure)" and pure["name"] == "科力晶（纯）"
    assert _mine("carinite", online=False)["en"] == "Carinite"
    assert _mine("janalite", online=False)["en"] == "Janalite"
