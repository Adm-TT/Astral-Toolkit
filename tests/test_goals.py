"""目标：库存联动维科洛兑换 / 制造，算还差多少"""

from sc_mining.trade.console import Trade
from sc_mining.trade.models import Item, StockKey, StockLine


def _trade(tmp_path, stock):
    t = Trade(tmp_path / "db", providers=[])
    t.catalog.upsert(
        [
            Item("tit", "Titanium"),
            Item("ric", "Riccite"),
            Item("eye", "Yormandi Eye"),
            Item("vp", "Vanduul Plating"),
            Item("vm", "Vanduul Metal"),
        ]
    )
    lines = [
        StockLine(StockKey(i, q, loc, *u), n) for i, q, loc, n, *u in stock
    ]  # 第 5 项是单位（不写就是「个」）
    if lines:
        t.inventory.commit(t.inventory.prepare(lines, "add"), allow_duplicate=True)
    return t


def _setup(monkeypatch, tmp_path):
    from sc_mining.crafting import goals

    monkeypatch.setattr(goals, "FILE", tmp_path / "goals.json")
    return goals


def test_wikelo_goal_shortfall(monkeypatch, tmp_path):
    G = _setup(monkeypatch, tmp_path)
    t = _trade(
        tmp_path, [("vp", "unknown", "Area18", 1), ("vm", "unknown", "Lorville", 5)]
    )
    G.add("wikelo", "TheCollector_BigBooma")  # 剜度装甲板 2、剜度金属 2、爆破筒发射器 1
    g = G.plan(t)["goals"][0]
    rows = {r["en"]: r for r in g["rows"]}
    assert (
        rows["Vanduul Plating"]["have"] == 1 and rows["Vanduul Plating"]["short"] == 1
    )
    assert rows["Vanduul Metal"]["short"] == 0 and rows["Vanduul Metal"]["have"] == 2
    assert not g["done"] and 0 < g["progress"] < 1
    # 次数改成 3：数量都 ×3
    G.update(g["id"], times=3)
    rows = {r["en"]: r for r in G.plan(t)["goals"][0]["rows"]}
    assert rows["Vanduul Metal"]["need"] == 6 and rows["Vanduul Metal"]["short"] == 1


def test_quality_gate_and_priority(monkeypatch, tmp_path):
    """制造有品质门槛：品质不够的不算；两个目标抢同一种料时，先满足排前面的；品质未知单独提示"""
    G = _setup(monkeypatch, tmp_path)
    # 超材料测试 #146：钛 2 SCU（≥900）、Riccite 2 SCU（≥800）、Yormandi Eye 4 个
    M = 1_000_000  # 矿按 uSCU 记；按「个」记的钛（D）单位对不上，不算
    t = _trade(
        tmp_path,
        [
            ("tit", "exact:950", "A", 3 * M, "uSCU"),
            ("tit", "exact:700", "B", 10 * M, "uSCU"),
            ("tit", "unknown", "C", 5 * M, "uSCU"),
            ("tit", "exact:950", "D", 5),
            ("ric", "exact:850", "A", 2 * M, "uSCU"),
            ("eye", "unknown", "A", 4),
        ],
    )
    G.add("craft", "Metamaterial Test #146", 2)  # 要 钛 4、Riccite 4、眼 8
    p = G.plan(t)
    rows = {r["en"]: r for r in p["goals"][0]["rows"]}
    assert (
        rows["Titanium"]["have"] == 3 and rows["Titanium"]["short"] == 1
    )  # 700 品质的不算
    assert rows["Titanium"]["unknown"] == 5  # 品质未知的提示出来
    assert (
        rows["Titanium"]["other_unit"] == "5 个" and rows["Riccite"]["other_unit"] == ""
    )  # 单位对不上的不算，但要提示
    import pytest

    with pytest.raises(ValueError):  # 品质填错被拒：不留下空的本地物品
        G.stock_line(t, "Zzqx Test Thing", "测试物", 1, "个", "abc", "Area18")
    assert t.catalog.get("local:Zzqx Test Thing") is None
    for bad in ("inf", "nan", float("inf"), float("nan")):  # 数量 inf / nan 被拒
        with pytest.raises(ValueError, match="数量不对"):
            G.stock_line(t, "Titanium", "", bad, "SCU", "", "Area18")
    assert rows["Riccite"]["short"] == 2 and rows["Yormandi Eye"]["short"] == 4
    short = {x["en"]: x["short"] for x in p["shortfall"]}
    assert short == {"Titanium": 1, "Riccite": 2, "Yormandi Eye": 4}
    # 再加一个同样的目标（次数并进去变 3）；新开第二个目标抢料：排后面的拿不到前面拿走的
    G.add("craft", "Metamaterial Test #146")
    assert len(G.load()) == 1 and G.load()[0]["times"] == 3
    G.add("wikelo", "TheCollector_BigBooma")
    gid = G.load()[1]["id"]
    G.update(gid, move=-1)  # 挪到第一位
    assert G.load()[0]["kind"] == "wikelo"
    G.update(gid, remove=True)
    assert len(G.load()) == 1


def test_missing_goal_and_bad_input(monkeypatch, tmp_path):
    import pytest

    G = _setup(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        G.add("craft", "没有这个蓝图")
    with pytest.raises(ValueError):
        G.add("trade", "x")
    t = _trade(tmp_path, [])
    G.save(
        [
            {
                "id": "x",
                "kind": "craft",
                "ref": "早就删掉的蓝图",
                "times": 1,
                "title": "旧目标",
            }
        ]
    )
    assert G.plan(t)["goals"][0]["missing"]


def test_shared_stock_goes_by_priority(monkeypatch, tmp_path):
    """两个兑换都要剜度金属：库存只有 6 个，排前面的先拿；调换顺序后反过来"""
    G = _setup(monkeypatch, tmp_path)
    t = _trade(tmp_path, [("vm", "unknown", "Area18", 6)])
    G.add("wikelo", "TheCollector_BigBooma")  # 要 2
    G.add("wikelo", "TheCollector_GMNI_LMG")  # 要 5
    vm = lambda g: next(r for r in g["rows"] if r["en"] == "Vanduul Metal")  # noqa: E731
    a, b = G.plan(t)["goals"]
    assert vm(a)["have"] == 2 and vm(b)["have"] == 4 and vm(b)["short"] == 1
    G.update(G.load()[1]["id"], move=-1)  # LMG 挪到前面
    b, a = G.plan(t)["goals"]
    assert vm(b)["have"] == 5 and vm(a)["have"] == 1 and vm(a)["short"] == 1
    total = {x["en"]: x["short"] for x in G.plan(t)["shortfall"]}
    assert total["Vanduul Metal"] == 1


def test_add_stock_from_goal_page(monkeypatch, tmp_path):
    """交易库里没有的材料：目标页入库时自动建本地物品；矿按 uSCU 记，小数能正确累计"""
    G = _setup(monkeypatch, tmp_path)
    t = Trade(tmp_path / "db", providers=[])  # 空的交易库：钛、Riccite 都没有
    G.add(
        "craft", "Metamaterial Test #146"
    )  # 钛 2 SCU ≥900、Riccite 2 SCU ≥800、眼 4 个
    G.add_stock(t, "Titanium", "钛", "1.25", "SCU", "950", "ARC-L1")
    G.add_stock(t, "Titanium", "钛", 0.75, "SCU", "910", "ARC-L1")
    G.add_stock(t, "Riccite", "愈金", 5, "SCU", "700", "Area18")  # 品质不够
    G.add_stock(t, "Yormandi Eye", "约曼迪之眼", 4, "个", "", "Area18")
    rows = {r["en"]: r for r in G.plan(t)["goals"][0]["rows"]}
    assert rows["Titanium"]["have"] == 2 and rows["Titanium"]["short"] == 0
    assert rows["Riccite"]["have"] == 0 and rows["Riccite"]["short"] == 2
    assert rows["Yormandi Eye"]["short"] == 0
    assert t.catalog.get("local:Titanium") and rows["Titanium"]["local"]
    import pytest

    with pytest.raises(ValueError):
        G.add_stock(
            t, "Yormandi Eye", "", 1.5, "个", "", "Area18"
        )  # 按个记的不能有小数
    with pytest.raises(ValueError):
        G.add_stock(
            t, "Titanium", "", 0.0000001, "SCU", "", "Area18"
        )  # 不到 1 uSCU（1.6.37 起按 uSCU 记）


def test_goal_quality_effect_and_stock_quality(monkeypatch, tmp_path):
    """目标：带入分到的库存平均品质，算成品属性；库存页手动入库、改品质（能撤销）"""
    from sc_mining.crafting import crafting as CR
    from sc_mining.tasks import (
        count as t_count,
        goals as t_goals,
        hover as t_hover,
        stock as t_stock,
        trade as t_trade,
    )

    G = _setup(monkeypatch, tmp_path)
    t = Trade(tmp_path / "db", providers=[])
    _v = lambda: t  # noqa: E731
    for _m in (t_count, t_goals, t_hover, t_stock, t_trade):
        monkeypatch.setattr(_m, "trade", _v)
    bp = next(
        b
        for b in CR.blueprints()
        if any(m for _s, _o, m in b["slots"])
        and any(k == "r" for _s, o, _m in b["slots"] for k, *_ in o)
    )
    idx = next(
        i
        for i, (_s, o, m) in enumerate(bp["slots"])
        if m and any(k == "r" for k, *_ in o)
    )
    mineral = next(n for k, n, *_ in bp["slots"][idx][1] if k == "r")
    lo, hi = CR.effect(bp, {idx: 0})[0], CR.effect(bp, {str(idx): 1000})[0]
    assert lo["props"] and all(0 <= p["pos"] <= 1 for p in lo["props"])
    assert all(p["pos"] == 1 for p in hi["props"]) or any(
        p["next_gate"] is None for p in hi["props"]
    )
    assert CR.effect(bp, {}) == [] and CR.effect(bp, {idx: "abc"}) == []
    assert (
        t_goals.craft_effect(key=bp["n"], qualities={str(idx): 500})["slots"][0]["q"]
        == 500
    )
    # 库存：手动入库两批不同品质 → 目标用加权平均品质
    t_stock.stock_add_named(
        name=mineral, qty="30", unit="SCU", quality="1000", location="A"
    )
    r = t_stock.stock_add_named(
        name=mineral, qty="10", unit="SCU", quality="", location="A"
    )
    assert "added" in r and any(x["qkey"] == "unknown" for x in r["rows"])
    G.add("craft", bp["n"])
    goal = next(g for g in t_goals.goals()["goals"] if g["kind"] == "craft")
    sq = next(x for x in goal["slots_q"] if x["idx"] == idx)
    assert sq["q"] in (None, 1000) and sq["has_mods"]  # 未知品质那批不算平均
    if sq["q"] == 1000:
        assert goal["effect"] and goal["effect"][0]["q"] == 1000
    # 改品质：未知 → 600，数量挪过去，可以撤销
    row = next(x for x in t_stock.stock()["rows"] if x["qkey"] == "unknown")
    out = t_stock.stock_set_quality(
        id=row["id"], qkey="unknown", location="A", ukey=row["ukey"], quality="600"
    )
    assert not any(x["qkey"] == "unknown" for x in out["rows"]) and any(
        x["qkey"] == "exact:600" for x in out["rows"]
    )
    assert "error" in t_stock.stock_set_quality(
        id=row["id"], qkey="unknown", location="A", ukey=row["ukey"], quality="600"
    )
    t_stock.stock_undo(batch=out["history"][0]["batch"])
    assert any(x["qkey"] == "unknown" for x in t_stock.stock()["rows"])
    assert "error" in t_stock.stock_add_named(name="", qty="1")


def test_tooltip_quality():
    from types import SimpleNamespace as N
    from sc_mining.tasks.hover import tooltip_quality

    tk = lambda s, y=0: N(text=s, box=(0, y, 10, y + 5))  # noqa: E731
    assert tooltip_quality([tk("钛"), tk("品质：650", 10)]) == 650
    assert (
        tooltip_quality([tk("Quality 812")]) == 812
        and tooltip_quality([tk("Q700")]) == 700
    )
    assert (
        tooltip_quality([tk("品质 4000")]) is None
        and tooltip_quality([tk("价格 650")]) is None
    )


def test_units_uscu_and_migration(monkeypatch, tmp_path):
    """入库单位 个 / SCU / uSCU：SCU 和 uSCU 都按 uSCU 存（0.495 SCU 不再被存成 0.50，2026-10-23 用户）；
    以前按 0.01 SCU 记的旧库存换算成 uSCU，历史记录一起换算，撤销照常"""
    from sc_mining.tasks import (
        count as t_count,
        goals as t_goals,
        hover as t_hover,
        stock as t_stock,
        trade as t_trade,
    )

    G = _setup(monkeypatch, tmp_path)
    t = Trade(tmp_path / "db", providers=[])
    _v = lambda: t  # noqa: E731
    for _m in (t_count, t_goals, t_hover, t_stock, t_trade):
        monkeypatch.setattr(_m, "trade", _v)
    G.add_stock(t, "Taranite", "塔兰导电石", "0.495", "SCU", "925", "新巴贝奇")
    G.add_stock(t, "Taranite", "塔兰导电石", "5000", "uSCU", "925", "新巴贝奇")
    G.add_stock(t, "CryoPod", "冷冻舱", 35, "个", "0", "新巴贝奇")
    rows = {r["id"]: r for r in t_stock.stock()["rows"]}
    tar = next(r for i, r in rows.items() if "Taranite" in i)
    assert (tar["qty"], tar["unit"], tar["raw"], tar["ukey"]) == (
        0.5,
        "SCU",
        500000,
        "uSCU",
    )
    assert next(r for i, r in rows.items() if "CryoPod" in i)["unit"] == "个"
    import pytest

    with pytest.raises(ValueError):
        G.add_stock(t, "Taranite", "", "1.5", "uSCU", "", "A")  # uSCU 要整数
    # 目标：要 0.5 SCU，有 0.495 SCU 不够（以前 0.01 精度会存成 0.50，以为够了）
    t2 = Trade(tmp_path / "db2", providers=[])
    G.add_stock(t2, "Titanium", "钛", "0.495", "SCU", "950", "A")
    lots = G.stock_lots(t2)
    assert abs(sum(l[3] for ls in lots.values() for l in ls) - 0.495) < 1e-9  # noqa: E741
    # 旧的 cSCU 记录：换算 ×10000，换算前备份数据库，旧批次还能撤销
    t3 = Trade(tmp_path / "db3", providers=[])
    t3.catalog.upsert([Item("local:Iron", "Iron")])
    old = t3.inventory.prepare(
        [StockLine(StockKey("local:Iron", "exact:710", "A", "cSCU"), 43)], "add"
    )
    batch = t3.inventory.commit(old, allow_duplicate=True)
    backup = tmp_path / "bak.db"
    assert t3.inventory.migrate_cscu(backup=backup) == 2 and backup.exists()
    line = t3.inventory.list_stock()[0]
    assert (line.key.unit, line.quantity) == ("uSCU", 430000)
    assert t3.inventory.migrate_cscu() == 0  # 只换算一次
    t3.inventory.undo(batch)
    assert not t3.inventory.list_stock()


def test_stock_suggest_and_named_add(monkeypatch, tmp_path):
    """手动入库联想：打几个字就出矿物和物品（带单位）；点选后按选中的入库"""
    from sc_mining.tasks import (
        count as t_count,
        goals as t_goals,
        hover as t_hover,
        stock as t_stock,
        trade as t_trade,
    )
    from sc_mining.trade import names

    _setup(monkeypatch, tmp_path)
    t = Trade(tmp_path / "db", providers=[])
    _v = lambda: t  # noqa: E731
    for _m in (t_count, t_goals, t_hover, t_stock, t_trade):
        monkeypatch.setattr(_m, "trade", _v)
    monkeypatch.setattr(
        names,
        "table",
        lambda: {
            "冷冻舱（剜度）": "CryoPod (Vanduul)",
            "冷冻舱": "CryoPod",
            "钛": "Titanium",
        },
    )
    names._index.cache_clear()
    try:
        rows = t_stock.stock_suggest(q="冷冻")
        assert {
            "zh": "冷冻舱（剜度）",
            "en": "CryoPod (Vanduul)",
            "kind": "物品",
            "unit": "个",
        } in rows
        ore = t_stock.stock_suggest(q="taran")[0]
        assert (
            ore["en"] == "Taranite" and ore["kind"] == "矿物" and ore["unit"] == "SCU"
        )
        r = t_stock.stock_add_named(
            name="冷冻舱（剜度）",
            en="CryoPod (Vanduul)",
            zh="冷冻舱（剜度）",
            kind="物品",
            qty="35",
            unit="个",
            quality="0",
            location="新巴贝奇",
        )
        assert "added" in r and any(
            x["qty"] == 35 and x["unit"] == "个" for x in r["rows"]
        )
        r = t_stock.stock_add_named(
            name="冷冻舱（刻度）", qty="2", unit="", quality="", location="A"
        )  # 没点选、名字认错：按汉化包纠正
        assert "冷冻舱（剜度）" in r["added"]
        assert "error" in t_stock.stock_add_named(
            name="钛", qty="1", unit="桶", location="A"
        )
    finally:
        names._index.cache_clear()


def test_stock_places_list_and_match():
    """库存地点列表（1.6.39）：游戏里能存东西的地方，中文名和「星系 / 星球 / 站点」路径；以前手打的位置能对上的自动认"""
    import pytest
    from sc_mining.crafting import stockplaces as SP

    ps = SP.places()
    labels = [p["label"] for p in ps]
    assert len(ps) >= 20 and len(set(labels)) == len(
        labels
    )  # 同名的（派罗星门）后面加星系，不会重复
    nb = SP.by_label("新巴贝奇")
    assert nb and nb["path"] == "斯坦顿 / 微科星 / 新巴贝奇" and nb["kind"] == "城市"
    assert SP.by_label("炽天使空间站")["path"] == "斯坦顿 / 十字军 / 炽天使空间站"
    assert (
        SP.match("New Babbage")["label"]
        == SP.match("newbabbage")["label"]
        == "新巴贝奇"
    )
    assert (
        SP.match("Area18")["label"] == "18区"
        and SP.match("Grim HEX")["label"] == "六角湾"
    )
    assert SP.match("ARC-L1")["label"].startswith("弧 L1")
    assert SP.match("38") is None and SP.match("") is None
    if (
        len([p for p in ps if p["zh"] == "派罗星门"]) > 1
    ):  # 斯坦顿、尼克斯两边都有派罗星门：分不清就不猜
        assert (
            SP.match("派罗星门") is None
            and SP.match("派罗星门", "Nyx")["label"] == "派罗星门（尼克斯）"
        )
    assert SP.check_name("  MOLE   货舱 ") == "MOLE 货舱"
    for bad in ("38", "", "1,000", "a｜b", "x" * 31):
        with pytest.raises(ValueError):
            SP.check_name(bad)


def test_stock_out_set_move_and_places(monkeypatch, tmp_path):
    """库存 1.6.39：地点从列表选（New Babbage → 新巴贝奇）、出库 / 改数量 / 移库 / 改品质都单独记一笔带备注、能撤销；
    以前手打的位置：能对上的启动时自动归位（先备份），对不上的放「未归类」，可以整组归到某个地点或留成自己的地点"""
    from sc_mining.tasks import (
        count as t_count,
        goals as t_goals,
        hover as t_hover,
        stock as t_stock,
        trade as t_trade,
    )
    from sc_mining.trade.storage import EXPECTED_SCHEMA

    _setup(monkeypatch, tmp_path)
    t = Trade(tmp_path / "db", providers=[])
    _v = lambda: t  # noqa: E731
    for _m in (t_count, t_goals, t_hover, t_stock, t_trade):
        monkeypatch.setattr(_m, "trade", _v)
    monkeypatch.setattr("sc_mining.crafting.stockplaces.current_place", lambda: None)
    # 以前手打的位置（直接写进库存，不经过地点列表）
    t.catalog.upsert([Item("ber", "Beryl"), Item("crp", "CryoPod")])
    old = [
        StockLine(StockKey("ber", "exact:547", "Area18", "uSCU"), 1_495_000),
        StockLine(StockKey("crp", "exact:0", "38", "unit"), 35),
        StockLine(StockKey("crp", "exact:0", "MOLE 货舱", "unit"), 2),
    ]
    t.inventory.commit(t.inventory.prepare(old, "add"), allow_duplicate=True)
    t = Trade(tmp_path / "db", providers=[])  # 升级后第一次打开：能对上的自动归位
    _v = lambda: t  # noqa: E731
    for _m in (t_count, t_goals, t_hover, t_stock, t_trade):
        monkeypatch.setattr(_m, "trade", _v)
    assert list((tmp_path / "db").glob("inventory_地点归位前备份_*.db"))
    d = t_stock.stock()
    assert [(g["sys"], [p["label"] for p in g["places"]]) for g in d["tree"]] == [
        ("斯坦顿", ["18区"])
    ]
    assert {g["label"] for g in d["unmatched"]} == {"38", "MOLE 货舱"} and not d[
        "custom"
    ]
    assert (
        d["history"][0]["type"] == "移库" and "Area18 → 18区" in d["history"][0]["note"]
    )
    # 入库：英文地点名 → 列表里的中文名；带备注、从哪录的
    r = t_stock.stock_add_named(
        name="钛",
        en="Titanium",
        zh="钛",
        kind="矿物",
        qty="2.5",
        unit="SCU",
        quality="800",
        location="New Babbage",
        note="第一次挖钛",
    )
    tit = next(x for x in r["rows"] if x["en"] == "Titanium")
    assert (
        tit["place"] == tit["location"] == "新巴贝奇"
        and tit["kind"] == "矿物"
        and tit["q"] == 800
    )
    h = r["history"][0]
    assert (h["type"], h["note"], h["source"]) == ("入库", "第一次挖钛", "库存页")
    assert "error" in t_stock.stock_add_named(
        name="钛",
        en="Titanium",
        zh="钛",
        kind="矿物",
        qty="1",
        unit="SCU",
        location="38",
    )
    key = dict(
        id=tit["id"], qkey=tit["qkey"], location=tit["location"], ukey=tit["ukey"]
    )
    # 出库：不能比库存多；记原因和备注
    assert "库存不够" in t_stock.stock_out(**key, qty="3", reason="卖出")["error"]
    r = t_stock.stock_out(**key, qty="0.5", reason="卖出", note="卖给 TDD")
    assert next(x for x in r["rows"] if x["en"] == "Titanium")["qty"] == 2.0
    assert (
        r["history"][0]["type"],
        r["history"][0]["reason"],
        r["history"][0]["note"],
    ) == ("出库", "卖出", "卖给 TDD")
    # 改数量：直接改成实际数；改成 0 这一行就没了，撤销回来
    r = t_stock.stock_set_qty(**key, qty="0")
    assert (
        not any(x["en"] == "Titanium" for x in r["rows"])
        and r["history"][0]["type"] == "改数量"
    )
    assert t_stock.stock_set_qty(**key, qty="0")["error"] == "数量没变"
    r = t_stock.stock_undo(batch=r["history"][0]["batch"])
    assert next(x for x in r["rows"] if x["en"] == "Titanium")["qty"] == 2.0
    # 移库：搬一部分到炽天使空间站（英文名也认）；记录写「从 → 到」
    r = t_stock.stock_move(**key, qty="0.5", to="Seraphim Station", note="拉去卖")
    assert r["moved_to"] == "炽天使空间站"
    assert {(x["place"], x["qty"]) for x in r["rows"] if x["en"] == "Titanium"} == {
        ("新巴贝奇", 1.5),
        ("炽天使空间站", 0.5),
    }
    assert (
        "新巴贝奇 → 炽天使空间站" in r["history"][0]["items"][0]
        and r["history"][0]["type"] == "移库"
    )
    move = r["history"][0]["batch"]
    sk = next(x for x in r["rows"] if x["place"] == "炽天使空间站")
    t_stock.stock_out(
        id=sk["id"],
        qkey=sk["qkey"],
        location=sk["location"],
        ukey=sk["ukey"],
        qty="0.5",
        reason="卖出",
    )
    assert (
        "无法撤销" in t_stock.stock_undo(batch=move)["error"]
    )  # 搬过去的已经卖了：撤销说人话
    # 改品质：记成「改品质」，写旧 → 新
    r = t_stock.stock_set_quality(**key, quality="850", note="重新看了一眼")
    assert (
        r["history"][0]["type"] == "改品质"
        and "品质 800 → 品质 850" in r["history"][0]["items"][0]
    )
    # 未归类：「38」整组归到新巴贝奇；「MOLE 货舱」留成自己的地点
    r = t_stock.stock_relocate(location="38", to="新巴贝奇")
    assert r["relocated"] == 1 and {g["label"] for g in r["unmatched"]} == {"MOLE 货舱"}
    r = t_stock.stock_keep_custom(location="MOLE 货舱")
    assert not r["unmatched"] and [g["label"] for g in r["custom"]] == ["MOLE 货舱"]
    assert t_stock.stock_place_add(name="38")["error"] == "地点名称不能只含数字"
    assert t_stock.stock_place_add(name="new babbage")["label"] == "新巴贝奇"
    assert (
        t_stock.stock_place_add(name="Caterpillar 货舱")["custom"]
        and "Caterpillar 货舱" in t_stock.stock_places()["custom"]
    )
    # 1.6.38 以前的改品质记成 adjust（一减一加）：记录里也显示成「改品质」
    cr = next(
        x
        for x in t_stock.stock()["rows"]
        if x["id"] == "crp" and x["place"] == "新巴贝奇"
    )
    with t.db.connection() as c:
        t.inventory._write(
            c,
            [
                (StockKey("crp", cr["qkey"], cr["location"], "unit"), -cr["raw"]),
                (StockKey("crp", "exact:300", cr["location"], "unit"), cr["raw"]),
            ],
            "adjust",
        )
    h = t_stock.stock()["history"][0]
    assert h["type"] == "改品质" and "品质 0 → 品质 300" in h["items"][0]
    # 1.6.58：库存表带工作区（个人）
    assert "workspace_id" in str(EXPECTED_SCHEMA["stocks"])


V1_SCHEMA = """
CREATE TABLE items (id TEXT PRIMARY KEY, name TEXT NOT NULL, uuid TEXT);
CREATE TABLE aliases (item_id TEXT REFERENCES items(id), alias TEXT NOT NULL, PRIMARY KEY(item_id,alias));
CREATE TABLE source_ids (source TEXT, external_id TEXT, item_id TEXT REFERENCES items(id), PRIMARY KEY(source,external_id));
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE stocks (item_id TEXT NOT NULL REFERENCES items(id), quality TEXT NOT NULL, location TEXT NOT NULL, unit TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>=0), PRIMARY KEY(item_id,quality,location,unit));
CREATE TABLE batches (id TEXT PRIMARY KEY, at TEXT NOT NULL, mode TEXT NOT NULL, image_hash TEXT, undone INTEGER NOT NULL DEFAULT 0);
CREATE TABLE movements (id INTEGER PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(id), item_id TEXT NOT NULL, quality TEXT NOT NULL, location TEXT NOT NULL, unit TEXT NOT NULL, delta INTEGER NOT NULL, before_qty INTEGER NOT NULL, after_qty INTEGER NOT NULL);
CREATE TABLE snapshots (key TEXT NOT NULL, hour TEXT NOT NULL, at TEXT NOT NULL, mean TEXT NOT NULL, minimum TEXT, PRIMARY KEY(key,hour));
CREATE TABLE provider_cache (cache_key TEXT PRIMARY KEY, at TEXT NOT NULL, next_at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE batch_notes (batch_id TEXT PRIMARY KEY, note TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '');
"""


def test_stock_v1_import_leaves_old_file(tmp_path):
    """1.6.58：新库存文件第一次打开时，把旧 inventory.db 的物品、库存、记录（带备注）导进来；旧文件一个字节都不动；不重复导"""
    import hashlib, sqlite3  # noqa: E401

    d = tmp_path / "db"
    d.mkdir()
    old = d / "inventory.db"
    with sqlite3.connect(old) as c:
        c.executescript(V1_SCHEMA)
        c.execute("INSERT INTO items VALUES ('ber','Beryl',NULL)")
        c.execute(
            "INSERT INTO stocks VALUES ('ber','exact:547','新巴贝奇','uSCU',1495000)"
        )
        c.execute(
            "INSERT INTO batches VALUES ('b1','2026-10-20T00:00:00+00:00','add',NULL,0)"
        )
        c.execute(
            "INSERT INTO movements VALUES (1,'b1','ber','exact:547','新巴贝奇','uSCU',1495000,0,1495000)"
        )
        c.execute("INSERT INTO batch_notes VALUES ('b1','第一次挖','','库存页')")
        c.execute("INSERT INTO settings VALUES ('last_location','\"新巴贝奇\"')")
    before = hashlib.sha256(old.read_bytes()).hexdigest()
    t = Trade(d, providers=[])
    assert (d / "dubhe_inventory.db").exists()
    lines = t.inventory.list_stock()
    assert [(l.key.item_id, l.key.location, l.quantity) for l in lines] == [
        ("ber", "新巴贝奇", 1495000)
    ]  # noqa: E741
    h = t.inventory.history()
    assert (
        h[0]["note"] == "第一次挖"
        and h[0]["source"] == "库存页"
        and t.db.get("last_location") == "新巴贝奇"
    )
    assert hashlib.sha256(old.read_bytes()).hexdigest() == before
    t.inventory.undo("b1")  # 导过来的记录照样能撤销
    t2 = Trade(d, providers=[])  # 再开一次：不重复导
    assert t2.inventory.list_stock() == []


def test_stock_undo_blocked_by_later_ops_and_op_id(tmp_path):
    """1.6.58：同一行库存在这笔之后还有没撤销的操作，就不能单独撤销这笔；先撤后面的再撤前面的可以。
    同一个操作编号再来一次（连点、重发）只记一次"""
    import pytest

    t = Trade(tmp_path / "db", providers=[])
    t.catalog.upsert([Item("ber", "Beryl")])
    k = StockKey("ber", "exact:547", "新巴贝奇", "uSCU")
    first = t.inventory.commit(t.inventory.prepare([StockLine(k, 10)], "add"))
    sold = t.inventory.out(k, 4, reason="卖出")
    with pytest.raises(ValueError, match="无法撤销"):
        t.inventory.undo(first)
    t.inventory.undo(sold)
    t.inventory.undo(first)
    assert t.inventory.list_stock() == []
    with t.db.connection() as c:
        a = t.inventory._write(c, [(k, 3)], "add", op_id="click-1")
        b = t.inventory._write(c, [(k, 3)], "add", op_id="click-1")
    assert a == b and t.inventory.list_stock()[0].quantity == 3


def test_stock_page_uses_place_picker():
    """库存页、物品页、目标页入库都从地点列表选（不再手打「放在哪」）；库存页有出库 / 改数量 / 移库 / 改品质"""
    from sc_mining.core import paths

    js = (paths.CODE / "app" / "web" / "app.js").read_text(encoding="utf-8")
    assert 'id="s-loc"' not in js and "gf-loc" not in js and 'id="sa-loc"' not in js
    assert js.count("placeBtnHTML(") >= 4 and "stock_places" in js
    for name in (
        "stock_out",
        "stock_set_qty",
        "stock_move",
        "stock_relocate",
        "stock_keep_custom",
        "stock_place_add",
    ):
        assert f'"{name}"' in js


def test_stock_bins_reserve_ledger_and_values(monkeypatch, tmp_path):
    """库存 1.6.40：仓位（建 / 默认 / 改名 / 删除，东西跟着走）、「不给目标用」、目标占用、仓储流水筛选分页、估值"""
    from sc_mining.tasks import (
        count as t_count,
        goals as t_goals,
        hover as t_hover,
        stock as t_stock,
        trade as t_trade,
    )

    G = _setup(monkeypatch, tmp_path)
    t = Trade(tmp_path / "db", providers=[])
    _v = lambda: t  # noqa: E731
    for _m in (t_count, t_goals, t_hover, t_stock, t_trade):
        monkeypatch.setattr(_m, "trade", _v)
    monkeypatch.setattr("sc_mining.crafting.stockplaces.current_place", lambda: None)
    add = lambda **k: t_stock.stock_add_named(
        **{
            "name": "钛",
            "en": "Titanium",
            "zh": "钛",
            "kind": "矿物",
            "unit": "SCU",
            "quality": "950",
            **k,
        }
    )  # noqa: E731
    # 仓位：建在 New Babbage → 记在新巴贝奇下面；不能重名、不能叫总仓
    r = t_stock.stock_bin_save(place="New Babbage", name="待卖", desc="拉去卖的")
    assert r["bin"] == "新巴贝奇｜待卖" and r["bins"]["新巴贝奇"]["bins"] == [
        {"name": "待卖", "desc": "拉去卖的"}
    ]
    assert "已有" in t_stock.stock_bin_save(place="新巴贝奇", name="待卖")["error"]
    assert "总仓" in t_stock.stock_bin_save(place="新巴贝奇", name="总仓")["error"]
    add(qty="2", location="新巴贝奇", bin="待卖")
    add(qty="1", location="新巴贝奇", bin="总仓")
    d = t_stock.stock()
    nb = d["tree"][0]["places"][0]
    assert nb["label"] == "新巴贝奇" and [
        (b["name"], b["count"]) for b in nb["bins"]
    ] == [("总仓", 1), ("待卖", 1)]
    assert {(x["bin"], x["qty"]) for x in d["rows"]} == {("总仓", 1.0), ("待卖", 2.0)}
    # 默认仓位：不指定仓位入库就放进去；指定「总仓」照样放总仓
    t_stock.stock_bin_save(
        place="新巴贝奇", name="待卖", desc="拉去卖的", default=True, old="待卖"
    )
    assert (
        t_stock._place_for("新巴贝奇") == "新巴贝奇｜待卖"
        and t_stock._place_for("新巴贝奇", "总仓") == "新巴贝奇"
    )
    # 改名：东西跟着走、默认跟着改、记一笔能撤销
    r = t_stock.stock_bin_save(place="新巴贝奇", name="卖的", default=True, old="待卖")
    assert {x["bin"] for x in r["rows"]} == {"总仓", "卖的"} and r["bins"]["新巴贝奇"][
        "default"
    ] == "卖的"
    assert r["history"][0]["type"] == "移库" and "仓位改名" in r["history"][0]["note"]
    # 目标占用 / 不给目标用
    G.add(
        "craft",
        next(
            b
            for b in __import__(
                "sc_mining.crafting.crafting", fromlist=["x"]
            ).blueprints()
            if any(n == "Titanium" for _s, opts, _m in b["slots"] for _k, n, *_ in opts)
        )["n"],
    )
    d = t_stock.stock()
    used = sum(x["goal_qty"] for x in d["rows"])
    assert used > 0 and all(x["goal_titles"] for x in d["rows"] if x["goal_qty"])
    sell = next(x for x in d["rows"] if x["bin"] == "卖的")
    d = t_stock.stock_reserve(
        id=sell["id"],
        qkey=sell["qkey"],
        location=sell["location"],
        ukey=sell["ukey"],
        on=True,
    )
    sell = next(x for x in d["rows"] if x["bin"] == "卖的")
    assert sell["reserved"] and sell["goal_qty"] == 0
    assert G.stock_lots(t) and all(
        l[2] != sell["location"] for ls in G.stock_lots(t).values() for l in ls
    )  # noqa: E741
    d = t_stock.stock_reserve(
        id=sell["id"],
        qkey=sell["qkey"],
        location=sell["location"],
        ukey=sell["ukey"],
        on=False,
    )
    assert not next(x for x in d["rows"] if x["bin"] == "卖的")["reserved"]
    # 删仓位：东西放回总仓
    r = t_stock.stock_bin_delete(place="新巴贝奇", name="卖的")
    assert r["moved"] == 1 and {x["bin"] for x in r["rows"]} == {"总仓"}
    assert not (r["bins"].get("新巴贝奇") or {}).get("bins")
    assert next(x for x in r["rows"])["qty"] == 3.0
    # 仓储流水：类型、地点、搜索、日期、分页
    for i in range(6):
        add(qty="0.1", location="Area18", note=f"第 {i} 次")
    L = t_stock.stock_ledger(size=5)
    assert (
        L["total"] >= 10
        and L["pages"] >= 2
        and len(L["rows"]) == 5
        and "18区" in L["places"]
    )
    assert (
        t_stock.stock_ledger(size=5, page=99)["page"] == L["pages"]
    )  # 超过最后一页就停在最后一页
    assert {x["type"] for x in t_stock.stock_ledger(type="入库", size=50)["rows"]} == {
        "入库"
    }
    assert all(
        "18区" in x["places"]
        for x in t_stock.stock_ledger(place="18区", size=50)["rows"]
    )
    assert t_stock.stock_ledger(q="第 3 次")["total"] == 1
    assert t_stock.stock_ledger(start="2000-01-01", end="2000-12-31")["total"] == 0
    # 估值：按缓存里最便宜的出售挂牌（品质档、单位对得上才算），品质未知的不算
    from decimal import Decimal

    tit = next(x for x in t_stock.stock()["rows"] if x["place"] == "新巴贝奇")
    monkeypatch.setattr(
        t_stock,
        "_price_index",
        lambda _t: {(tit["id"], "q7", "SCU"): (Decimal(1000), "uex")},
    )
    d = t_stock.stock()
    tit = next(x for x in d["rows"] if x["place"] == "新巴贝奇")
    assert tit["value"] == 3000 and d["value_total"] >= 3000 and d["priced"] >= 1
    assert (
        t_stock._row_value(
            {("x", "q3", "unit"): (Decimal(5), "scm")}, "x", "exact:650", "unit", 4
        )
        == 20
    )
    assert (
        t_stock._row_value(
            {("x", "q3", "unit"): (Decimal(5), "scm")}, "x", "unknown", "unit", 4
        )
        is None
    )
    assert (
        t_stock._row_value(
            {("x", "q3", "unit"): (Decimal(5), "scm")}, "x", "exact:650", "uSCU", 4
        )
        is None
    )  # 单位对不上不猜


def test_goal_finish_deducts_stock(monkeypatch, tmp_path):
    """目标「做完了」：从库存扣掉做一次用掉的材料（一笔出库，原因「用于制造」，能撤销），次数 -1，最后一次做完删掉目标；
    材料不够不让扣；标了「不给目标用」的不拿"""
    from sc_mining.tasks import (
        count as t_count,
        goals as t_goals,
        hover as t_hover,
        stock as t_stock,
        trade as t_trade,
    )
    from sc_mining.crafting import crafting as CR

    G = _setup(monkeypatch, tmp_path)
    t = Trade(tmp_path / "db", providers=[])
    _v = lambda: t  # noqa: E731
    for _m in (t_count, t_goals, t_hover, t_stock, t_trade):
        monkeypatch.setattr(_m, "trade", _v)
    bp = next(
        b
        for b in CR.blueprints()
        if (G.requirements({"kind": "craft", "ref": b["n"], "times": 1}) or [None])
        and all(
            r["alts"][0]["unit"] == "SCU"
            for r in G.requirements({"kind": "craft", "ref": b["n"], "times": 1})
        )
    )
    reqs = G.requirements({"kind": "craft", "ref": bp["n"], "times": 1})
    G.add("craft", bp["n"], times=2)
    gid = G.load()[0]["id"]
    assert t_goals.goal_finish_preview(id=gid)["short"]  # 还没材料
    assert "不足" in t_goals.goal_finish(id=gid)["error"]
    for r in reqs:
        a = r["alts"][0]
        G.add_stock(
            t, a["en"], a["zh"], round(a["qty"] * 2, 6), "SCU", 1000, "新巴贝奇"
        )
    p = t_goals.goal_finish_preview(id=gid)
    assert not p["short"] and len(p["takes"]) == len(reqs) and p["times"] == 2
    before = {x["en"]: x["qty"] for x in t_stock.stock()["rows"]}
    r = t_goals.goal_finish(id=gid)
    assert r["finished"]["left"] == 1 and G.load()[0]["times"] == 1
    after = {x["en"]: x["qty"] for x in t_stock.stock()["rows"]}
    for q in reqs:
        a = q["alts"][0]
        assert abs((before[a["en"]] - after.get(a["en"], 0)) - a["qty"]) < 1e-6
    h = t_stock.stock()["history"][0]
    assert (h["type"], h["reason"], h["source"]) == ("出库", "用于制造", "目标") and h[
        "note"
    ].startswith("制造：")
    t_stock.stock_undo(batch=h["batch"])  # 撤销：材料回来
    assert {x["en"]: x["qty"] for x in t_stock.stock()["rows"]} == before
    t_goals.goal_finish(id=gid)
    t_goals.goal_finish(id=gid)  # 最后一次：目标删掉
    assert not G.load()


def test_crafted_item_qualities_from_bonus(monkeypatch, tmp_path):
    """1.6.67：制造出来的东西说明框里只有加成行（用户 2026-10-25 F10 那把视差「血红」，OCR 原文）→ 按蓝图和固定品质档倒推
    钨 858、金 916、科力晶 959（一分不差），记平均 911，详情各槽；入库手填各槽也一样；老库存文件没有新表照样能打开"""
    from types import SimpleNamespace as N
    from sc_mining.crafting import crafting as C
    from sc_mining.tasks import (
        count as t_count,
        goals as t_goals,
        hover as t_hover,
        stock as t_stock,
        trade as t_trade,
    )

    toks = [
        N(text=t, box=b)
        for t, b in [
            ["视差“血红”能量突击步枪", [1371, 369, 184, 20]],
            ["射速：200rpm-光束", [1370, 595, 144, 18]],
            ["冲击力：", [1369, 848, 53, 21]],
            ["+17.50 %", [1470, 850, 67, 18]],
            ["后坐力冲击：", [1370, 874, 80, 20]],
            ["-28.64 %", [1471, 876, 62, 18]],
            ["后坐力平滑度：+28.64%", [1372, 902, 163, 17]],
            ["后坐力操控：", [1372, 929, 77, 16]],
            ["+28.64%", [1467, 927, 68, 20]],
            ["1.00SCU", [1399, 953, 61, 18]],
        ]
    ]
    mods = C.parse_mods(toks)
    assert [m[0] for m in mods] == [
        "冲击力",
        "后坐力冲击",
        "后坐力平滑度",
        "后坐力操控",
    ]  # 「射速：200rpm」不算
    bp = C.for_item('Parallax "Sanguine" Energy Assault Rifle', "")
    r = C.solve_slots(bp, mods)
    assert (
        [x["q"] for x in r["slots"]] == [858, 916, 959]
        and r["avg"] == 911
        and r["exact"]
    )
    G = _setup(monkeypatch, tmp_path)  # noqa: F841
    t = Trade(tmp_path / "db", providers=[])
    _v = lambda: t  # noqa: E731
    for _m in (t_count, t_goals, t_hover, t_stock, t_trade):
        monkeypatch.setattr(_m, "trade", _v)
    out = t_stock.stock_add_named(
        name="视差 “血红” 能量突击步枪",
        en='Parallax "Sanguine" Energy Assault Rifle',
        zh="视差 “血红” 能量突击步枪",
        qty=1,
        unit="个",
        location="新巴贝奇",
        craft=[dict(x) for x in r["slots"]],
    )
    row = next(x for x in out["rows"] if x["en"].startswith("Parallax"))
    assert row["q"] == 911 and row["craft"] == "框架 858 · 线缆 916 · 功率调节器 959"
    assert [
        x["slot"]
        for x in t_stock.craft_slots_for(en='Parallax "Sanguine" Energy Assault Rifle')
    ] == ["框架", "线缆", "功率调节器"]
    import sqlite3

    with sqlite3.connect(tmp_path / "db" / "dubhe_inventory.db") as c:
        c.execute("DROP TABLE craft_details")
    Trade(
        tmp_path / "db", providers=[]
    )  # 1.6.58–1.6.66 建的文件：缺表补上，不报「表结构不符」


# ---------------------------------------------------------------- 2026-10-30 重构阶段 2：导航、目标的接口走自己的 Controller
_NAV_API = [
    "nav_search",
    "nav_near",
    "nav_site",
    "nav_plan",
    "nav_start",
    "nav_mode",
    "sig_name",
    "sig_names",
    "nav_stop",
    "nav_refresh",
    "waypoints",
    "waypoint_add",
    "waypoint_preview",
    "waypoint_from_text",
    "waypoint_delete",
    "ore_record",
    "ore_list",
    "ore_delete",
    "ore_restore",
    "ore_go",
    "halo_options",
    "halo_routes",
    "halo_pin",
    "halo_unpin",
]
_GOALS_API = [
    "goal_finish_preview",
    "goal_finish",
    "wikelo_search",
    "wikelo_detail",
    "goals",
    "goal_add",
    "goal_update",
    "goal_stock_add",
    "craft_effect",
    "goal_prices",
    "craft_search",
    "craft_browse",
    "craft_detail",
    "craft_stats",
    "craft_mix",
]


def test_nav_goals_controller_routes():
    """导航、目标的每个接口名都由 app/api/navigation.py、app/api/goals.py 接，名单和 Controller 的 ROUTES 一个不多一个不少"""
    from sc_mining.app.api import router, navigation as CN, goals as CG

    router.reset()
    r = router.routes()
    for name in _NAV_API:
        assert r[name].__module__ == "sc_mining.app.api.navigation", name
    for name in _GOALS_API:
        assert r[name].__module__ == "sc_mining.app.api.goals", name
    assert sorted(CN.ROUTES) == sorted(_NAV_API) and sorted(CG.ROUTES) == sorted(
        _GOALS_API
    )


def test_nav_goals_tasks_no_services():
    """tasks/navigation.py、tasks/goals.py 不再反过来引用 app.services"""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "sc_mining" / "tasks"
    for f in ("navigation.py", "goals.py"):
        text = (root / f).read_text(encoding="utf-8")
        for bad in ("app import services", "_services()", "@api"):
            assert bad not in text, (f, bad)


def test_nav_goals_router_roundtrip(monkeypatch, tmp_path):
    """只读接口 waypoints：走 router 和直接调 tasks 结果一样（路标文件用临时的）"""
    import json
    from sc_mining.app.api import router
    from sc_mining.navigation import navigate as n
    from sc_mining.tasks import navigation as TN

    monkeypatch.setattr(n, "WAYPOINTS", tmp_path / "wp.json")
    n.add_space_waypoint("测试点", "Stanton", (1.0e9, 2.0e9, 3.0e9))
    router.reset()
    got = router.call("waypoints", {})
    assert got["ok"], got
    want = json.loads(json.dumps(TN.waypoints(), ensure_ascii=False, default=str))
    assert got["data"] == want and any(w["name"] == "测试点" for w in want)
