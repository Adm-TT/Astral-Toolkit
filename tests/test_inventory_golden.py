"""库存金样测试（新库存重写 PR0）：锁住现在库存页、流水、盘点确认、目标完成扣料的输出。

只用临时库存和临时目标文件，不读本机库存。跑一串固定操作，把每一步之后 stock() / stock_ledger() 里
和库存账有关的字段（去掉时间、批次号这类每次不同的值，以及只跟显示名字有关的文字）和
tests/golden/inventory_legacy.json 比，一个字都不能变。新库存一步步替换旧代码时，这份输出就是基准。

金样只证明「行为没变」，不证明「行为对」。要更新基准（确实有意改了行为）：
    set AT_GOLDEN_UPDATE=1 && python -X utf8 -m tests.run_all
然后在提交说明里写清改了哪几处、为什么。
"""

import json
import os
import re
from pathlib import Path
from typing import Any

from astral_toolkit.app import bus
from astral_toolkit.crafting import goal_list, goals, stockplaces
from astral_toolkit.tasks import (
    count as count_task,
    goals as goals_task,
    stock as stock_task,
    trade as trade_task,
)
from astral_toolkit.trade.console import Trade
from astral_toolkit.trade.models import Item
from tests import count_helpers
from tests.bootstrap_helpers import bind_for_test

GOLDEN = Path(__file__).resolve().parent / "golden" / "inventory_legacy.json"

GADGET = "Golden Test Gadget"  # 游戏数据里没有的物品：按「个」记
ORE = "Titanium"  # 矿物：按 SCU 记（存 uSCU）
PLACE_A = "金样测试仓甲"  # 不在地点表里的自定义地点，不随地点数据变
PLACE_B = "金样测试仓乙"
M = 1_000_000

ROW_FIELDS = (
    "en",
    "kind",
    "quality",
    "q",
    "location",
    "place",
    "bin",
    "place_state",
    "qty",
    "unit",
    "id",
    "qkey",
    "ukey",
    "raw",
    "goal_qty",
    "reserved",
    "avail",
    "value",
)
HISTORY_FIELDS = ("mode", "undone", "type", "note", "reason", "source", "places")


class _Ids:
    """批次号每次不同：按第一次出现的先后换成 B1、B2……"""

    def __init__(self):
        self.seen: dict[str, str] = {}

    def __call__(self, batch: str) -> str:
        return self.seen.setdefault(batch, f"B{len(self.seen) + 1}")


def _rows(view: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [{k: r.get(k) for k in ROW_FIELDS} for r in view.get("rows", [])]
    return sorted(rows, key=lambda r: json.dumps(r, ensure_ascii=False, sort_keys=True))


def _history(items: list[dict[str, Any]], ids: _Ids) -> list[dict[str, Any]]:
    out = []
    for h in items:
        d = {k: h.get(k) for k in HISTORY_FIELDS}
        d["batch"] = ids(h["batch"])
        mode = d.get("mode") or ""
        if mode.startswith("undo:"):  # 撤销记的是被撤那笔的批次号
            d["mode"] = "undo:" + ids(mode[5:])
        d["lines"] = len(h.get("items") or [])
        out.append(d)
    return out


def _snap(label: str, ids: _Ids) -> dict[str, Any]:
    view = stock_task.stock()
    assert "error" not in view, (label, view)
    ledger = stock_task.stock_ledger(size=100)
    return {
        "step": label,
        "rows": _rows(view),
        "tree": [
            {
                "label": p["label"],
                "state": p["state"],
                "count": p["count"],
                "bins": [b["name"] for b in p.get("bins", [])],
            }
            for g in view.get("tree", [])
            for p in g.get("places", [])
        ],
        "custom": view.get("custom"),
        "unmatched": view.get("unmatched"),
        "history": _history(view.get("history", []), ids),
        "ledger_total": ledger["total"],
        "ledger": _history(ledger["rows"], ids),
    }


def _row(en: str, place: str) -> dict[str, Any]:
    return next(
        r for r in stock_task.stock()["rows"] if r["en"] == en and r["place"] == place
    )


def _ok(out: dict[str, Any]) -> dict[str, Any]:
    assert "error" not in out, out
    return out


def _setup(monkeypatch, tmp_path) -> Trade:
    monkeypatch.setattr(goal_list, "FILE", tmp_path / "goals.json")
    t = Trade(tmp_path / "db", providers=[])
    t.catalog.upsert([Item("gad", GADGET), Item("tit", ORE)])
    for m in (stock_task, count_task, goals_task, trade_task):
        monkeypatch.setattr(m, "trade", lambda: t)
    monkeypatch.setattr(stockplaces, "current_place", lambda: None)
    monkeypatch.setattr(bus, "publish", lambda *a, **k: None)
    # 目标的用料固定写死，不读蓝图数据：做一次要 1 个测试物品
    req = [
        {
            "slot": "",
            "alts": [{"en": GADGET, "zh": "", "qty": 1, "unit": "个", "minq": 0}],
        }
    ]
    monkeypatch.setattr(
        goals,
        "requirements",
        lambda g: [
            {
                "slot": r["slot"],
                "alts": [dict(a, qty=a["qty"] * g.get("times", 1)) for a in r["alts"]],
            }
            for r in req
        ],
    )
    goal_list.save(
        [
            {
                "id": "g1",
                "kind": "craft",
                "ref": "Golden",
                "times": 2,
                "title": "金样目标",
                "at": 0,
            }
        ]
    )
    return t


def _scenario(monkeypatch, tmp_path) -> list[dict[str, Any]]:
    _setup(monkeypatch, tmp_path)
    ids = _Ids()
    snaps = []

    def step(label):
        snaps.append(_snap(label, ids))

    _ok(stock_task.stock_place_add(name=PLACE_A))
    _ok(stock_task.stock_add(id="gad", qty=3, quality="", location=PLACE_A))
    step("入库 测试物品 3 个 @甲")
    # 接口收到的是 JSON 小数，stock_add 的签名只写了 int
    ore: dict[str, Any] = dict(id="tit", qty=2.5, quality="950", location=PLACE_A)
    _ok(stock_task.stock_add(**ore))
    step("入库 钛 2.5 SCU 品质 950 @甲")
    _ok(stock_task.stock_add(id="gad", qty=2, quality="", location=PLACE_B))
    step("入库 测试物品 2 个 @乙")

    r = _row(GADGET, PLACE_A)
    _ok(
        stock_task.stock_out(
            id=r["id"],
            qkey=r["qkey"],
            location=r["location"],
            ukey=r["ukey"],
            qty="1",
            reason="卖了",
            note="金样",
        )
    )
    step("出库 测试物品 1 个 @甲")

    r = _row(GADGET, PLACE_B)
    _ok(
        stock_task.stock_set_qty(
            id=r["id"], qkey=r["qkey"], location=r["location"], ukey=r["ukey"], qty="5"
        )
    )
    step("改数量 测试物品 @乙 → 5")

    r = _row(ORE, PLACE_A)
    _ok(
        stock_task.stock_move(
            id=r["id"],
            qkey=r["qkey"],
            location=r["location"],
            ukey=r["ukey"],
            qty="1",
            to=PLACE_B,
        )
    )
    step("移库 钛 1 SCU 甲 → 乙")

    r = _row(GADGET, PLACE_A)
    _ok(
        stock_task.stock_set_quality(
            id=r["id"],
            qkey=r["qkey"],
            location=r["location"],
            ukey=r["ukey"],
            quality="600",
        )
    )
    step("改品质 测试物品 @甲 → 600")

    last = stock_task.stock()["history"][0]["batch"]
    _ok(stock_task.stock_undo(batch=last))
    step("撤销上一笔（改品质）")

    r = _row(ORE, PLACE_B)
    _ok(
        stock_task.stock_reserve(
            id=r["id"], qkey=r["qkey"], location=r["location"], ukey=r["ukey"], on=True
        )
    )
    step("钛 @乙 标「不给目标用」")

    # 盘点甲：测试物品认出 4 个（账上 2），钛没看到（不在这次范围里，不动）
    review = count_task._count_review(
        PLACE_A, {1: dict(en=GADGET, zh="", quality=None, unit="个", qty=4, cells=1)}
    )
    count = count_helpers.count()
    count.review = review
    with bind_for_test(count_task, count):
        _ok(count_task.count_apply())
    step("盘点确认 @甲：测试物品 2 → 4")

    _ok(goals_task.goal_finish(id="g1"))
    step("目标完成一次：扣测试物品 1 个")

    last = stock_task.stock()["history"][0]["batch"]
    _ok(stock_task.stock_undo(batch=last))
    step("撤销目标扣料")
    return snaps


def test_inventory_legacy_golden(monkeypatch, tmp_path):
    snaps = _scenario(monkeypatch, tmp_path)
    text = json.dumps(snaps, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if os.environ.get("AT_GOLDEN_UPDATE") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(text, encoding="utf-8", newline="\n")
    want = GOLDEN.read_text(encoding="utf-8")
    if text != want:
        got_steps = [s["step"] for s in snaps]
        bad = next(
            (
                s["step"]
                for s, w in zip(snaps, json.loads(want))
                if json.dumps(s, sort_keys=True) != json.dumps(w, sort_keys=True)
            ),
            "步数不同",
        )
        raise AssertionError(
            f"库存金样变了，第一处不同在「{bad}」（共 {len(got_steps)} 步）"
        )


def test_golden_has_no_volatile_values():
    """基准文件里不能有时间戳和真批次号（否则每次跑都会不一样）"""
    text = GOLDEN.read_text(encoding="utf-8")
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:", text)
    assert not re.search(r"\b[0-9a-f]{32}\b", text)
