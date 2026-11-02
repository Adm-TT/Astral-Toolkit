"""算法函数吃值（运行结构 RT-B2）：给了快照就不读全局表和设置，不给和以前一样"""

from contextlib import contextmanager
from typing import Any

from sc_mining import gamedata
from sc_mining.mining import data, laser, refinery
from sc_mining.mining.analysis import analyze
from sc_mining.mining.parse import Scan
from sc_mining.tasks import goals, mining

BAG = {"Gold": 10.0}


def test_refined_functions_default_matches_explicit_snapshot():
    prices = {m: data.best_price(m) for m in data.CITY_PRICES}
    table = dict(data.REFINERIES)
    assert refinery.refined_plan(BAG) == refinery.refined_plan(
        BAG, prices=prices, refineries=table
    )
    station = next(iter(table))
    assert refinery.refined_scu(BAG, station) == refinery.refined_scu(
        BAG, station, None, table
    )


def test_refined_plan_uses_given_values():
    table = {"站 A": ("Stanton", {}), "站 B": ("Stanton", {"Gold": 50})}
    plan = refinery.refined_plan(BAG, prices={"Gold": (1000, "城")}, refineries=table)
    assert {row[1] for row in plan} == {"站 B"}
    no_price = refinery.refined_plan(BAG, prices={}, refineries=table)
    assert all(row[2] <= 0 for row in no_price)  # 快照里没有的矿算不收，不去读全局价


def test_recommend_with_facts_does_not_read_settings(monkeypatch):
    facts = laser.loadout_facts()
    want = laser.recommend(9000, 30, 10)

    def boom():
        raise AssertionError("给了配装就不该读设置")

    monkeypatch.setattr(laser, "ship_loadout", lambda ship=None: boom())
    monkeypatch.setattr(laser, "active_model", boom)
    got = laser.recommend(9000, 30, 10, loadout=facts)
    assert [(p.names, p.gadget, p.ratio) for p in got] == [
        (p.names, p.gadget, p.ratio) for p in want
    ]


def test_recommend_crew_limits_heads():
    setups = tuple(laser.HeadSetup(k, []) for k in ("helix_ii", "klein_s2"))
    facts = laser.LoadoutFacts(setups, 1, "default", 0.2)
    plans = laser.recommend(1000, 10, 5, top=999, loadout=facts)
    assert plans and all(len(p.heads) == 1 for p in plans)


def _gold_scan(**over):
    kw: dict[str, Any] = dict(
        rock="Gold",
        mass=9000,
        resistance=35,
        instability=6,
        total_scu=10.0,
        composition=[("Gold", 50.0, 500), ("Tungsten", 50.0, 300)],
    )
    kw.update(over)
    return Scan(**kw)


def _target(en):
    return {"en": en, "zh": "", "short": 1, "unit": "SCU", "minq": 1, "goals": ["蓝图"]}


def test_collect_inputs_queries_in_one_snapshot(monkeypatch):
    calls, state = [], {"in": 0, "opened": 0}

    @contextmanager
    def snap():
        state["in"] += 1
        state["opened"] += 1
        try:
            yield
        finally:
            state["in"] -= 1

    def seen(name, value):
        def f(*a):
            calls.append((name, state["in"]))
            return value

        return f

    monkeypatch.setattr(gamedata, "snapshot", snap)
    monkeypatch.setattr(mining, "_quality_hints", seen("hints", ["提示"]))
    monkeypatch.setattr(mining, "_mat_summary", seen("mats", {"count": 1}))
    monkeypatch.setattr(mining, "_goal_for", seen("goal", None))
    ins = mining.collect_inputs(_gold_scan())
    assert state["opened"] == 1 and calls and all(depth == 1 for _, depth in calls)
    assert ins.craft_hints == ("提示",) and ins.goals_complete
    assert [nm for nm, _ in ins.craft_mats] == ["Gold", "Tungsten"]


def test_collect_inputs_without_database_still_queries_goals(monkeypatch):
    @contextmanager
    def snap():
        raise gamedata.GamedataUnavailable("没库")
        yield

    monkeypatch.setattr(gamedata, "snapshot", snap)
    monkeypatch.setattr(mining, "_quality_hints", lambda c: [])
    monkeypatch.setattr(mining, "_mat_summary", lambda *a: {"count": 0})
    monkeypatch.setattr(mining, "_goal_for", lambda *n: _target(n[0]))
    ins = mining.collect_inputs(_gold_scan())
    assert [nm for nm, _ in ins.goal_targets] == ["Gold", "Tungsten"]
    assert ins.goals_complete


def test_collect_inputs_goal_error_keeps_earlier_ones(monkeypatch):
    def goal_for(*names):
        if names[0] == "Tungsten":
            raise RuntimeError("读不到")
        return _target(names[0])

    monkeypatch.setattr(mining, "_quality_hints", lambda c: ["提示"])
    monkeypatch.setattr(mining, "_mat_summary", lambda *a: {"count": 0})
    monkeypatch.setattr(mining, "_goal_for", goal_for)
    ins = mining.collect_inputs(_gold_scan())
    assert ins.craft_hints == ("提示",)
    assert [nm for nm, _ in ins.goal_targets] == ["Gold"] and not ins.goals_complete


def test_collect_inputs_no_minerals_queries_nothing(monkeypatch):
    def boom(*a):
        raise AssertionError("没有算钱的矿不该查")

    monkeypatch.setattr(mining, "_quality_hints", boom)
    monkeypatch.setattr(mining, "_goal_for", boom)
    ins = mining.collect_inputs(_gold_scan(total_scu=None))
    assert ins.craft_hints == () and ins.goal_targets == ()


def test_goal_targets_do_not_share_cache_objects(monkeypatch):
    target = _target("Gold")
    monkeypatch.setattr(goals, "goal_short", lambda force=False: {"gold": target})
    ins = mining.collect_inputs(_gold_scan())
    got = dict(ins.goal_targets)["Gold"]
    assert got["en"] == "Gold" and got["goals"] == ("蓝图",)
    target["goals"].append("改")  # 目标缓存之后变了，这一轮不受影响
    assert got["goals"] == ("蓝图",)


def test_analyze_reads_snapshot_not_later_changes(monkeypatch):
    """取好输入之后全局表和设置变了，这一轮不受影响"""
    scan = _gold_scan()
    bag = ({}, None, None)
    monkeypatch.setattr(goals, "goal_short", lambda force=False: {})
    want = analyze(scan, bag, mining.collect_inputs(scan))
    ins = mining.collect_inputs(scan)
    monkeypatch.setattr(data, "CITY_PRICES", {})
    monkeypatch.setattr(laser, "ship_loadout", lambda ship=None: 1 / 0)
    monkeypatch.setattr(laser, "active_model", lambda: 1 / 0)
    saved = dict(data.REFINERIES)
    try:
        for k in saved:
            data.REFINERIES[k] = ("星系", {"Gold": 90})
        got = analyze(scan, bag, ins)
    finally:
        data.REFINERIES.update(saved)
    assert got.refine == want.refine and got.sell == want.sell
    assert got.plans == want.plans
