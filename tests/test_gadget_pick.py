"""带了哪些手持工具（老大 11-04：要能选携带的手持工具）：破碎方案只在带了的里挑，全不带就只给不贴的方案"""

import dataclasses


def test_recommend_only_uses_carried_gadgets():
    from astral_toolkit.mining import laser
    from astral_toolkit.mining.data import GADGETS

    base = laser.loadout_facts()
    # 一块需要贴工具才破得开的重石头：全带时会推荐贴工具
    mass, res, instab = 60000, 45, 20
    every = laser.recommend(
        mass,
        res,
        instab,
        top=999,
        loadout=dataclasses.replace(base, gadgets=tuple(GADGETS)),
    )
    assert {p.gadget for p in every} == {None, *GADGETS}
    none = laser.recommend(
        mass, res, instab, top=999, loadout=dataclasses.replace(base, gadgets=())
    )
    assert none and all(p.gadget is None for p in none)
    only = laser.recommend(
        mass,
        res,
        instab,
        top=999,
        loadout=dataclasses.replace(base, gadgets=("sabir",)),
    )
    assert {p.gadget for p in only} == {None, "sabir"}


def test_carried_gadgets_setting(monkeypatch):
    from astral_toolkit.core import settings
    from astral_toolkit.mining import laser
    from astral_toolkit.mining.data import GADGETS

    cur = {}
    monkeypatch.setattr(settings, "load", lambda: dict(cur))
    assert laser.carried_gadgets() == tuple(GADGETS)  # 没设过：全带（和以前一样）
    cur["mining_gadgets"] = ["optimax", "sabir", "没有这种"]
    assert laser.carried_gadgets() == ("sabir", "optimax")  # 按表里的顺序，认不出的不要
    cur["mining_gadgets"] = []
    assert laser.carried_gadgets() == ()
    assert laser.loadout_facts().gadgets == ()


def test_set_mining_gadgets_saves_and_summary(monkeypatch):
    from types import SimpleNamespace

    from astral_toolkit.core import settings
    from astral_toolkit.tasks import mining as t

    cur = {}
    monkeypatch.setattr(settings, "load", lambda: dict(cur))
    monkeypatch.setattr(settings, "update", lambda **kw: cur.update(kw))
    changed = []
    monkeypatch.setattr(
        t,
        "_engines",
        lambda: SimpleNamespace(
            live=SimpleNamespace(config_changed=lambda: changed.append(1))
        ),
    )
    g = t.set_mining_gadgets(keys=["optimax", "sabir"])
    assert cur["mining_gadgets"] == ["sabir", "optimax"] and changed
    on = {x["key"] for x in g["gadgets"] if x["on"]}
    assert on == {"sabir", "optimax"}
    assert all(x["name"] and x["desc"] for x in g["gadgets"])
    ship = next(s for s in g["ships"] if s["key"] == g["ship"])
    assert ship["summary"]["gadget"] and ship["summary"]["mass_gadget"]
    g = t.set_mining_gadgets(keys=[])
    ship = next(s for s in g["ships"] if s["key"] == g["ship"])
    assert ship["summary"]["gadget"] == "" and ship["summary"]["mass_gadget"] is None
    for bad in ("sabir", ["没有这种"]):
        try:
            t.set_mining_gadgets(keys=bad)
        except ValueError:
            continue
        raise AssertionError(bad)
