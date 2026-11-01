"""游戏数据层批 3：制造蓝图 / 维科洛兑换 / 物品属性 / 打印点 / 出厂配件改走数据层（gamedata.crafting / wikelo / itemstats）

全部用 tmp_path 当 data/ 根（monkeypatch paths.DATA），不读真实 data/、不写 userdata/。最小源复用 test_gamedata_craft 的 _CRAFT_SOURCES。"""

import copy
import json

from tests.test_gamedata import _write_min_sources
from tests.test_gamedata_craft import _BP, _CRAFT_SOURCES


def _setup(monkeypatch, tmp_path, **override):
    """tmp_path 当 data/ 根、写最小源 + 制造源；就绪标记、后台线程记录换成新的（每个测试一个新库目录）"""
    import sc_mining.gamedata as G
    from sc_mining.core import paths
    from sc_mining.gamedata import _ready

    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(_ready, "_state", {"done": None, "failed": None})
    monkeypatch.setattr(G, "_state", {"last_error": None, "warm_thread": None})
    _write_min_sources(tmp_path, **{**copy.deepcopy(_CRAFT_SOURCES), **override})
    return tmp_path


def _rewrite(tmp_path, name, obj):
    """换一个源文件并重建（模拟更新数据）"""
    from sc_mining.gamedata._build import rebuild_if_needed

    (tmp_path / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    rebuild_if_needed()


# ---------------------------------------------------------------- Task 1：data() / blueprints() / 编号


def test_blueprints_dict_shape_equals_json(monkeypatch, tmp_path):
    """还原出的蓝图 dict 与源逐字相等（含重名两份、u 空、无槽）"""
    from sc_mining.crafting import crafting

    _setup(monkeypatch, tmp_path)
    src = _CRAFT_SOURCES["crafting.json"]["blueprints"]
    got = crafting.blueprints()
    assert got == src
    assert crafting.data() == {"blueprints": src}


def test_blueprints_same_objects_within_version(monkeypatch, tmp_path):
    """同一版本内两次取到的是同一批对象（bp_key 靠 id(bp)）；换了版本就是新对象、新内容"""
    from sc_mining.crafting import crafting

    _setup(monkeypatch, tmp_path)
    a, b = crafting.blueprints(), crafting.blueprints()
    assert a is b and all(x is y for x, y in zip(a, b))
    assert crafting.data() is crafting.data()
    new = copy.deepcopy(_CRAFT_SOURCES["crafting.json"])
    new["blueprints"][2]["z"] = "医疗笔 改"
    _rewrite(tmp_path, "crafting.json", new)
    c = crafting.blueprints()
    assert c is not a and c[2]["z"] == "医疗笔 改"
    assert crafting.bp_key(c[1]) == "Main Powerplant#2"


def test_blueprints_kept_when_other_source_changes(monkeypatch, tmp_path):
    """别的源文件更新（这里换 wikelo.json）换了库版本，蓝图还是同一批对象：长期拿着旧对象的地方编号照样对"""
    from sc_mining.crafting import crafting, wikelo

    _setup(monkeypatch, tmp_path)
    a = crafting.blueprints()
    before = [c["id"] for c in wikelo.load()]
    _rewrite(tmp_path, "wikelo.json", copy.deepcopy(_WIKELO))
    assert [c["id"] for c in wikelo.load()] != before  # 库确实重建了
    assert crafting.blueprints() is a
    assert crafting.bp_key(a[1]) == "Main Powerplant#2"


def test_catalog_built_once_when_threads_race(monkeypatch, tmp_path):
    """两个以上线程同时第一次取：只建一份，大家拿到同一批对象"""
    import threading
    import time

    from sc_mining.gamedata import crafting as gc

    _setup(monkeypatch, tmp_path)
    gc.catalog()  # 先把库建好
    gc._clear()
    real, calls = gc._load, []

    def slow(s):
        calls.append(1)
        time.sleep(0.05)
        return real(s)

    monkeypatch.setattr(gc, "_load", slow)
    bar, got = threading.Barrier(4), []

    def run():
        bar.wait()
        got.append(gc.catalog())

    ts = [threading.Thread(target=run) for _ in range(4)]
    for x in ts:
        x.start()
    for x in ts:
        x.join()
    assert len(calls) == 1 and len(got) == 4
    assert all(g is got[0] for g in got)


def test_blueprint_dicts_are_plain_mutable_like_json(monkeypatch, tmp_path):
    """slots / 选项 / 改装 / src 是 list 不是 tuple，d 是 bool，和 json.loads 出来的一样"""
    from sc_mining.crafting import crafting

    _setup(monkeypatch, tmp_path)
    bp = crafting.blueprints()[0]
    assert type(bp) is dict and type(bp["slots"]) is list
    assert type(bp["slots"][0]) is list and type(bp["slots"][0][1][0]) is list
    assert type(bp["slots"][0][2][0]) is list and type(bp["src"][0]) is list
    assert bp["d"] is False and type(bp["sec"]) is int
    assert type(bp["slots"][0][1][1][2]) is int  # 物品数量 2 还是 int（不是 2.0）


def test_keys_rule_unchanged(monkeypatch, tmp_path):
    """编号：名字唯一 → 名字；重名 → 名字#序号；旧编号（只有名字）取第一份；variant_note 照旧"""
    from sc_mining.crafting import crafting

    _setup(monkeypatch, tmp_path)
    bps = crafting.blueprints()
    assert [crafting.bp_key(b) for b in bps] == [
        "Main Powerplant#1",
        "Main Powerplant#2",
        "Medpen",
    ]
    assert crafting.by_key("Main Powerplant#2") is bps[1]
    assert crafting.by_key("Main Powerplant") is bps[0]  # 旧目标只存了名字
    assert crafting.by_key("Medpen") is bps[2]
    assert crafting.by_key("Main Powerplant#3") is None and crafting.by_key("x") is None
    assert crafting.variant_note(bps[1]) == "配方 2/2 · 0 分钟"
    assert crafting.variant_note(bps[2]) == ""
    assert crafting.bp_key({"n": "别的"}) == "别的"  # 不是这一版的对象：退回名字


def test_data_empty_when_no_blueprints(monkeypatch, tmp_path):
    """库里没有蓝图 / 库不可用：{"blueprints": []}，同一个原因只记一次警告"""
    import sc_mining.gamedata as G
    from sc_mining.crafting import crafting

    _setup(monkeypatch, tmp_path, **{"crafting.json": {"version": "x"}})
    assert crafting.data() == {"blueprints": []} and crafting.blueprints() == []
    assert crafting.by_key("Medpen") is None and crafting.search("med") == []

    def boom(snap=None):
        raise G.GamedataUnavailable("坏了")

    monkeypatch.setattr(G.crafting, "catalog", boom)
    warned = []
    monkeypatch.setattr(crafting, "_WARNED", set())
    import logging

    log = logging.getLogger(crafting.__name__)
    monkeypatch.setattr(log, "warning", lambda *a: warned.append(a))
    assert crafting.data() == {"blueprints": []}
    assert crafting.data() == {"blueprints": []}
    assert crafting.bp_key({"n": "Medpen"}) == "Medpen"
    assert len(warned) == 1


# ---------------------------------------------------------------- Task 2：for_item / search / by_key / uses / mat_summary

_MORE_BPS = [
    {
        **_BP,
        "n": "Tin Can",
        "z": "锡罐",
        "u": "u-3",
        "slots": [
            ["A", [["r", "Tin", 0.5, 600], ["r", "Iron", 1, 0]], []],
            ["B", [["r", "Tin", 2, 900]], []],
        ],
    },
    {
        **_BP,
        "n": "Pen",
        "z": "",
        "u": "u-4",
        "slots": [["A", [["i", "Tin", 1, 0]], []]],  # 物品 Tin 不算矿
    },
    {**_BP, "n": "Main Power", "z": "主发电", "u": "u-5"},
    {
        **_BP,
        "n": "main-powerplant",
        "z": "主 发电机",
        "u": "u-6",
    },  # 折叠后和 Main Powerplant 撞
]


def _rich(monkeypatch, tmp_path):
    src = copy.deepcopy(_CRAFT_SOURCES["crafting.json"])
    src["blueprints"] += copy.deepcopy(_MORE_BPS)
    _setup(monkeypatch, tmp_path, **{"crafting.json": src})
    return src["blueprints"]


def _legacy_for_item(bps, name_en="", name_zh=""):
    """迁移前的 crafting.for_item（照抄，比对用）"""
    import re

    def fold(s):
        return re.sub(r"[\W_]+", "", (s or "").lower())

    en, zh = fold(name_en), fold(name_zh)
    return next((b for b in bps if en and fold(b["n"]) == en), None) or next(
        (b for b in bps if zh and b["z"] and fold(b["z"]) == zh), None
    )


def _legacy_search(bps, query, limit=20):
    q = query.strip().lower().replace(" ", "")
    if not q:
        return []
    exact, part = [], []
    for bp in bps:
        names = [
            bp["n"].lower().replace(" ", ""),
            (bp["z"] or "").lower().replace(" ", ""),
        ]
        if q in names:
            exact.append(bp)
        elif any(q in n for n in names if n):
            part.append(bp)
    part.sort(key=lambda b: (len(b["n"]), b["n"]))
    return (exact + part)[:limit]


def _legacy_uses(bps, mineral):
    return [
        (bp, qty, minq)
        for bp in bps
        for slot, opts, mods in bp["slots"]
        for kind_, name, qty, minq in opts
        if kind_ == "r" and name == mineral
    ]


def _pos(bps, got):
    """把结果里的蓝图换成在源列表里的下标（库里还原的对象和源不是同一个，按位置比）"""
    return [bps.index(b) for b in got]


def test_for_item_fold_rule(monkeypatch, tmp_path):
    from sc_mining.crafting import crafting

    src = _rich(monkeypatch, tmp_path)
    bps = crafting.blueprints()
    cases = [
        ("Main Powerplant", ""),
        ("MAIN-powerplant!", ""),  # 去符号、不分大小写；撞名取第一份
        ("", "主发电机"),
        ("", "主 发电机"),
        ("", "主发电机 B"),
        ("Medpen", "主发电机"),  # 英文优先
        ("xx", "锡罐"),
        ("", ""),
        ("Pen", ""),
        ("", "不存在"),
    ]
    for en, zh in cases:
        want = _legacy_for_item(src, en, zh)
        got = crafting.for_item(en, zh)
        assert (want is None and got is None) or bps.index(got) == src.index(want), (
            en,
            zh,
        )
    assert crafting.for_item("Medpen") is bps[2]


def test_search_exact_before_partial_sorted(monkeypatch, tmp_path):
    from sc_mining.crafting import crafting

    src = _rich(monkeypatch, tmp_path)
    bps = crafting.blueprints()
    for q in [
        "main",
        "Main Powerplant",
        "主发电机",
        "主发电",
        "pen",
        " PEN ",
        "n",
        "锡",
        "",
        "  ",
        "xyz",
    ]:
        assert _pos(bps, crafting.search(q)) == _pos(src, _legacy_search(src, q)), q
    assert _pos(bps, crafting.search("n", limit=3)) == _pos(
        src, _legacy_search(src, "n", 3)
    )
    hits = crafting.search("主发电机")
    assert hits[0] is bps[0] and hits[0]["z"] == "主发电机"  # 完全匹配在前


def test_by_key_legacy_name_only(monkeypatch, tmp_path):
    from sc_mining.crafting import crafting

    _rich(monkeypatch, tmp_path)
    bps = crafting.blueprints()
    assert crafting.by_key("Main Powerplant") is bps[0]
    assert crafting.by_key("Main Powerplant#2") is bps[1]
    assert crafting.by_key("Tin Can") is bps[3] and crafting.by_key("Tin Can#1") is None


def test_mat_summary_gates_are_ints(monkeypatch, tmp_path):
    from sc_mining.crafting import crafting

    _rich(monkeypatch, tmp_path)
    m = crafting.mat_summary("Tin", 700)
    assert m == {"count": 5, "ok": 4, "gated": 4, "gates": [2, 600, 900], "gated_ok": 3}
    assert all(type(g) is int for g in m["gates"])
    assert crafting.mat_summary("Tin")["ok"] is None
    assert crafting.mat_summary("不存在") == {
        "count": 0,
        "ok": None,
        "gated": 0,
        "gates": [],
        "gated_ok": None,
    }


def test_uses_matches_legacy_on_sample(monkeypatch, tmp_path):
    from sc_mining.crafting import crafting

    src = _rich(monkeypatch, tmp_path)
    bps = crafting.blueprints()
    for m in ["Tin", "Iron", "Hephaestanite", "Medpen", "不存在"]:
        got = crafting.uses(m)
        want = _legacy_uses(src, m)
        assert [(bps.index(b), q, mq) for b, q, mq in got] == [
            (src.index(b), q, mq) for b, q, mq in want
        ], m
        assert [type(q) for _b, q, _m in got] == [type(q) for _b, q, _m in want]
    assert all(
        b is bps[i] for b, i in zip((x[0] for x in crafting.uses("Tin")), (0, 1, 3, 3))
    )
    assert "锡" in crafting.uses_report("Tin") and crafting.uses_report(
        "Medpen"
    ).endswith("没有蓝图用到它。")


def test_queries_empty_when_db_unavailable(monkeypatch, tmp_path):
    """库不可用：for_item → None，search / uses → []，mat_summary 计 0（照批 1 shops 的做法，不往外抛）"""
    import sc_mining.gamedata as G
    from sc_mining.crafting import crafting

    _setup(monkeypatch, tmp_path)

    def boom(*a, **k):
        raise G.GamedataUnavailable("坏了")

    for name in ("catalog", "for_item", "containing", "using_material"):
        monkeypatch.setattr(G.crafting, name, boom)
    monkeypatch.setattr(crafting, "_WARNED", {"游戏数据库不可用：坏了"})
    assert crafting.for_item("Medpen") is None
    assert crafting.search("med") == [] and crafting.uses("Tin") == []
    assert crafting.mat_summary("Tin")["count"] == 0
    assert crafting.by_key("Medpen") is None


# ---------------------------------------------------------------- Task 3：维科洛兑换 / 打印点

_WIKELO = {
    "version": "w2",
    "contracts": [
        {
            "id": "C1",
            "type": "收集",
            "t": "非常饥饿",
            "te": "Very Hungry",
            "rz": "随机衣服",
            "rewards": ["Hat Blue", "Hat Red"],
            "req": [
                {"n": "Lawson Mining Laser", "z": "激光", "q": 2, "u": "个"},
                {"n": "Tin", "z": "", "q": 1.5, "u": "SCU"},
                {
                    "n": "Yormandi Eye",
                    "z": "约曼迪之眼\\",
                    "q": 4,
                    "u": "个",
                },  # 汉化包里末尾带反斜杠
            ],
            "systems": ["Stanton", "Pyro"],
        },
        {
            "id": "C0",
            "type": "载具",
            "t": "要北极星？",
            "te": "Want Polaris?",
            "rz": "",
            "rewards": ["Polaris"],
            "req": [
                {"n": "Medpen", "z": "医疗笔", "q": 10, "u": "个"},
                {"n": "Lawson Mining Laser Mk2", "z": "激光二型", "q": 1, "u": "个"},
            ],
            "systems": [],
        },
    ],
}


def _wk(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, **{"wikelo.json": copy.deepcopy(_WIKELO)})
    src = copy.deepcopy(_WIKELO["contracts"])
    for c in src:  # 原 wikelo.load() 的清理
        for r in c["req"]:
            r["z"] = (r.get("z") or "").rstrip("\\ ").strip()
    return src


def _legacy_wk_uses(cs, name_en="", name_zh=""):
    """迁移前的 wikelo.uses（照抄，比对用；_fold / _same 用模块里的，没改）"""
    from sc_mining.crafting.wikelo import _fold, _same

    hits = []
    for c in cs:
        for r in c["req"]:
            if (name_en and _fold(r["n"]) == _fold(name_en)) or (
                name_zh and r["z"] and _fold(r["z"]) == _fold(name_zh)
            ):
                hits.append((c, r["q"], r["u"]))
    if not hits:
        for c in cs:
            for r in c["req"]:
                if (name_en and _same(r["n"], name_en)) or (
                    name_zh and r["z"] and _same(r["z"], name_zh)
                ):
                    hits.append((c, r["q"], r["u"]))
    return hits


def test_wikelo_load_shape(monkeypatch, tmp_path):
    """load() 与源同形（按源顺序，req 的 z 去掉末尾反斜杠），同一版本内是同一个列表"""
    from sc_mining.crafting import wikelo

    src = _wk(monkeypatch, tmp_path)
    got = wikelo.load()
    assert got == src and got is wikelo.load()
    assert [c["id"] for c in got] == ["C1", "C0"]
    assert got[0]["req"][2]["z"] == "约曼迪之眼" and got[0]["systems"] == [
        "Stanton",
        "Pyro",
    ]
    assert type(got[0]["rewards"]) is list and type(got[0]["req"][0]) is dict


def test_wikelo_uses_prefix_rule_preserved(monkeypatch, tmp_path):
    """先按折叠名相等找；一条都没有才放宽成包含（≥4 个字符），和旧实现逐条一致"""
    from sc_mining.crafting import wikelo

    src = _wk(monkeypatch, tmp_path)
    cases = [
        ("Lawson Mining Laser", ""),  # 相等命中一条，不放宽（Mk2 不算）
        ("lawson-mining-laser!", ""),
        ("Lawson Mining", ""),  # 截断：放宽后两条都中
        ("", "约曼迪之眼"),
        ("", "约曼迪"),  # 中文截断
        ("Tin", ""),
        ("", ""),
        ("Laws", ""),
        ("Law", ""),  # 不到 4 个字符不放宽
        ("medpen", "激光"),
        ("xyz", "不存在"),
    ]
    for en, zh in cases:
        got = [(c["id"], q, u) for c, q, u in wikelo.uses(en, zh)]
        want = [(c["id"], q, u) for c, q, u in _legacy_wk_uses(src, en, zh)]
        assert got == want, (en, zh, got, want)
    cs = wikelo.load()
    assert wikelo.uses("Medpen")[0][0] is cs[1]  # 返回的是 load() 里那份对象
    assert wikelo.uses_text("Medpen") == "维科洛兑换要用：要北极星？（10）"


def test_wikelo_search(monkeypatch, tmp_path):
    from sc_mining.crafting import wikelo

    _wk(monkeypatch, tmp_path)
    assert wikelo.search("") is wikelo.load()
    assert [c["id"] for c in wikelo.search("polaris")] == ["C0"]
    assert [c["id"] for c in wikelo.search("激光")] == ["C1", "C0"]
    assert [c["id"] for c in wikelo.search("hat red")] == ["C1"]
    assert wikelo.search("不存在") == []


def test_print_spots(monkeypatch, tmp_path):
    """按名字找打印地点：不分大小写、去首尾空格；没有 → []"""
    from sc_mining.crafting import wikelo

    _setup(monkeypatch, tmp_path)
    assert wikelo.print_spots("Comp-Board") == ["死局空间站", "另一处"]
    assert wikelo.print_spots("  comp-board ") == ["死局空间站", "另一处"]
    assert wikelo.print_spots("不存在") == [] and wikelo.print_spots(None) == []
    assert wikelo.source_note("Comp-Board") == "打印：死局空间站；另一处"


def test_wikelo_empty_when_db_unavailable(monkeypatch, tmp_path):
    import sc_mining.gamedata as G
    from sc_mining.crafting import wikelo

    _wk(monkeypatch, tmp_path)

    def boom(*a, **k):
        raise G.GamedataUnavailable("坏了")

    for name in ("contracts", "requiring", "print_places"):
        monkeypatch.setattr(G.wikelo, name, boom)
    assert wikelo.load() == [] and wikelo.uses("Medpen") == []
    assert wikelo.search("x") == [] and wikelo.print_spots("Comp-Board") == []


# ---------------------------------------------------------------- Task 4：物品属性 / 出厂配件

_STATS = {
    "version": "s2",
    "source": "x",
    "fetched": "2026",
    "items": {
        "uuid-a": {
            "n": "ADP Core",
            "size": 1,
            "grade": "A",
            "cls": "Civilian",
            "type": "Char_Armor_Torso",
            "sub": "Heavy",
            "mass": 7.0,
            "ver": "4.10",
            "mfr": "CDS",
            "cn": "cds_core",
            "s": {
                "temperature_resistance": {"min": -75.0, "max": 105.0},
                "durability": {"health": 55},
                "suit_armor": {
                    "damage_resistance": {
                        "physical": {"multiplier": 0.8},
                        "energy": {"multiplier": 0.9},
                    }
                },
            },
        },
        "uuid-b": {
            "n": "Cooler",
            "size": 2,
            "grade": "C",
            "cls": "Military",
            "type": "Cooler",
            "sub": "",
            "mass": 120.5,
            "ver": "4.10",
            "mfr": "ACOM",
            "cn": "cool",
            "s": {},
        },
    },
}


def test_itemstats_item_shapes(monkeypatch, tmp_path):
    """item(uuid) 与源同形（s 里 {min,max} / 数值 / 嵌套都原样）；base_value / tags 照旧"""
    from sc_mining.crafting import itemstats

    _setup(monkeypatch, tmp_path, **{"item_stats.json": copy.deepcopy(_STATS)})
    a = itemstats.item("uuid-a")
    assert a is not None
    assert (
        a == _STATS["items"]["uuid-a"] and type(a["s"]["durability"]["health"]) is int
    )
    assert itemstats.item("uuid-b") == _STATS["items"]["uuid-b"]
    assert itemstats.base_value("uuid-a", "armor_temperaturemin") == (-75.0, " ºC")
    assert itemstats.base_value("uuid-a", "health_maxhealth") == (55, "")
    assert itemstats.base_value("uuid-a", "armor_damagemitigation") == (0.85, "")
    assert itemstats.base_value("uuid-b", "health_maxhealth") == (None, "")
    assert itemstats.tags("uuid-b") == {
        "size": 2,
        "grade": "C",
        "cls": "Military",
        "mfr": "ACOM",
        "type": "Cooler",
    }


def test_itemstats_none_for_unknown(monkeypatch, tmp_path):
    from sc_mining.crafting import itemstats

    _setup(monkeypatch, tmp_path, **{"item_stats.json": copy.deepcopy(_STATS)})
    for u in ("", None, "不存在"):
        assert itemstats.item(u) is None and itemstats.tags(u) == {}
        assert itemstats.base_value(u, "health_maxhealth") == (None, "")


def test_itemstats_version(monkeypatch, tmp_path):
    import sc_mining.gamedata as G
    from sc_mining.crafting import itemstats

    _setup(monkeypatch, tmp_path, **{"item_stats.json": copy.deepcopy(_STATS)})
    assert itemstats.version() == "s2"
    _rewrite(tmp_path, "item_stats.json", {"items": {}})  # 没有 version 键
    assert itemstats.version() == "" and itemstats.item("uuid-a") is None

    def boom(*a, **k):
        raise G.GamedataUnavailable("坏了")

    monkeypatch.setattr(G.itemstats, "item", boom)
    monkeypatch.setattr(G.itemstats, "version", boom)
    assert itemstats.item("uuid-a") is None and itemstats.version() == ""


def test_ships_with(monkeypatch, tmp_path):
    """部件名折叠（小写、只留字母数字）后对上；返回新列表；没有 → []"""
    import sc_mining.gamedata as G
    from sc_mining.crafting import acquire

    _setup(monkeypatch, tmp_path)
    want = ["剜度 死镰", "埃斯佩里亚 刀锋"]
    assert acquire.ships_with("'Arrow' I Missile") == want
    assert acquire.ships_with("ARROW I missile") == want
    a = acquire.ships_with("arrowimissile")
    a.append("x")
    assert acquire.ships_with("arrowimissile") == want  # 调用方改了返回值不影响下次
    assert acquire.ships_with("不存在") == [] and acquire.ships_with(None) == []

    def boom(*a, **k):
        raise G.GamedataUnavailable("坏了")

    monkeypatch.setattr(G.itemstats, "ships_with", boom)
    assert acquire.ships_with("'Arrow' I Missile") == []


# ---------------------------------------------------------------- Task 5：重建 crafting.json / wikelo.json 的更新边界


def _spy_updating(monkeypatch, log):
    """包一层 gamedata.updating：记下每次进入时本线程是不是已经拿着 BUILD_LOCK（拿着就是锁顺序反了）"""
    import sc_mining.gamedata as G
    from sc_mining.crafting.build_crafting import BUILD_LOCK

    real = G.updating

    from contextlib import contextmanager

    @contextmanager
    def spy():
        log.append(("updating", BUILD_LOCK._is_owned()))
        with real():
            yield

    monkeypatch.setattr(G, "updating", spy)


def _count_rebuilds(monkeypatch):
    from sc_mining.gamedata import _build

    n = [0]
    real = _build.rebuild_if_needed

    def counted(*a, **k):
        n[0] += 1
        return real(*a, **k)

    monkeypatch.setattr(_build, "rebuild_if_needed", counted)
    return n


def test_build_crafting_runs_inside_updating(monkeypatch, tmp_path):
    """写 crafting.json 在 updating 里（BUILD_LOCK 在内），出口重建库：新蓝图马上查得到"""
    from sc_mining.crafting import build_crafting, crafting

    _setup(monkeypatch, tmp_path)
    assert crafting.by_key("Medpen") is not None
    log = []
    _spy_updating(monkeypatch, log)
    new = copy.deepcopy(_CRAFT_SOURCES["crafting.json"])
    new["blueprints"][2]["n"] = "Medpen Mk2"
    build_crafting._write(tmp_path / "crafting.json", new)
    assert log == [("updating", False)]
    assert (
        crafting.by_key("Medpen") is None and crafting.by_key("Medpen Mk2") is not None
    )
    assert not list(tmp_path.glob(".crafting.*.tmp"))


def test_wikelo_build_runs_inside_updating(monkeypatch, tmp_path):
    from sc_mining.crafting import wikelo

    _setup(monkeypatch, tmp_path)
    log = []
    _spy_updating(monkeypatch, log)
    wikelo._write(tmp_path / "wikelo.json", copy.deepcopy(_WIKELO))
    assert log == [("updating", False)]
    assert [c["id"] for c in wikelo.load()] == ["C1", "C0"]


def test_update_rebuilds_once_and_checks_outside_write_lock(monkeypatch, tmp_path):
    """update()：比版本 / 下载只在 BUILD_LOCK 里、不进 updating；两份文件重建套一层 updating，库只重建一次"""
    import sc_mining.gamedata as G
    from sc_mining.crafting import build_crafting, crafting, wikelo
    from sc_mining.gamedata import _lock

    _setup(monkeypatch, tmp_path)
    crafting.blueprints()  # 先建好库
    seen = {}

    def fake_update():
        seen["write_lock_depth"] = _lock._depth
        seen["build_lock"] = build_crafting.BUILD_LOCK._is_owned()
        return (
            "bp.json",
            "merged.json",
            "names.ini",
            tmp_path / "crafting.json",
            "已更新",
        )

    new_bp = copy.deepcopy(_CRAFT_SOURCES["crafting.json"])
    new_bp["blueprints"][2]["n"] = "Medpen Mk2"
    monkeypatch.setattr(build_crafting, "_update", fake_update)
    monkeypatch.setattr(
        build_crafting,
        "build",
        lambda bp, m, n, out: build_crafting._write(out, new_bp),
    )

    def fake_wikelo_build(merged, names):
        wikelo._write(tmp_path / "wikelo.json", copy.deepcopy(_WIKELO))
        return 2

    monkeypatch.setattr(wikelo, "build", fake_wikelo_build)
    log = []
    _spy_updating(monkeypatch, log)
    n = _count_rebuilds(monkeypatch)
    out = []
    monkeypatch.setattr(
        "builtins.print", lambda *a, **k: out.append(" ".join(map(str, a)))
    )
    build_crafting.update()
    assert seen == {"write_lock_depth": 0, "build_lock": True}
    assert [x for x, _ in log] == ["updating"] * 3 and not any(held for _, held in log)
    assert n[0] == 1 and G.last_error() is None
    assert out == ["维科洛兑换：2 个", "已更新"]
    assert crafting.by_key("Medpen Mk2") is not None and wikelo.load()[1]["id"] == "C0"


def test_rebuild_still_rebuilds_db_when_wikelo_fails(monkeypatch, tmp_path):
    """维科洛那份写失败：crafting.json 已经换了，库照样重建一次（新蓝图查得到），错再往外抛、不打印完成提示"""
    from sc_mining.crafting import build_crafting, crafting, wikelo

    _setup(monkeypatch, tmp_path)
    crafting.blueprints()
    new_bp = copy.deepcopy(_CRAFT_SOURCES["crafting.json"])
    new_bp["blueprints"][2]["n"] = "Medpen Mk2"
    monkeypatch.setattr(
        build_crafting,
        "build",
        lambda bp, m, n, out: build_crafting._write(out, new_bp),
    )

    def bad(merged, names):
        raise PermissionError("占用")

    monkeypatch.setattr(wikelo, "build", bad)
    out = []
    monkeypatch.setattr(
        "builtins.print", lambda *a, **k: out.append(" ".join(map(str, a)))
    )
    n = _count_rebuilds(monkeypatch)
    try:
        build_crafting._rebuild(
            "bp.json", "merged.json", "names.ini", tmp_path / "crafting.json", "已更新"
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("维科洛的错应该抛出来")
    assert n[0] == 1 and out == []
    assert crafting.by_key("Medpen Mk2") is not None
