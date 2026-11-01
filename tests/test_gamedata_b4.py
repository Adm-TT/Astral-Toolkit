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
