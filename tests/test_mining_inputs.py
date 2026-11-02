"""算法函数吃值（运行结构 RT-B2）：给了快照就不读全局表和设置，不给和以前一样"""

from sc_mining.mining import data, laser, refinery

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
