"""库存第 6 条：别名、对账交错与未知地点；只使用临时库存和注入的会话依赖。"""

import threading
from pathlib import Path
from typing import Any

from tests import minipytest as pytest

from astral_toolkit import bootstrap
from astral_toolkit.app import bus
from astral_toolkit.crafting import goals, stockplaces
from astral_toolkit.tasks import count as count_task, stock as stock_task
from astral_toolkit.trade.models import StockKey, StockLine
from tests import count_helpers
from tests.bootstrap_helpers import bind_for_test
from tests.test_goals import _setup, _trade


def _context(monkeypatch, tmp_path, lines=()):
    _setup(monkeypatch, tmp_path)
    t = _trade(tmp_path, lines)
    monkeypatch.setattr(stock_task, "trade", lambda: t)
    monkeypatch.setattr(count_task, "trade", lambda: t)
    monkeypatch.setattr(stockplaces, "current_place", lambda: None)
    return t


def _item(en, qty=2, quality=None, unit="个"):
    return dict(en=en, zh="", quality=quality, unit=unit, qty=qty, cells=1)


@pytest.mark.parametrize("conflict", [True, False])
def test_submit_preserves_new_review_after_interleaved_finish(
    monkeypatch, tmp_path, conflict
):
    """旧对账正在提交时，另一轮盘点收尾；成功或版本冲突都不能把新面板清掉。"""
    t = _context(monkeypatch, tmp_path, [("eye", "unknown", "A", 5)])
    count = count_helpers.count()
    count.review = count_task._count_review("A", {1: _item("Yormandi Eye")})
    entered, finished = threading.Event(), threading.Event()
    apply_count = t.inventory.apply_count
    errors, messages, result = [], [], []
    monkeypatch.setattr(bus, "publish", lambda *args: messages.append(args))

    def blocked(*args, **kw):
        entered.set()
        if not finished.wait(5):
            raise RuntimeError("等待新对账超时")
        return apply_count(*args, **kw)

    monkeypatch.setattr(t.inventory, "apply_count", blocked)

    def confirm():
        try:
            result.append(count_task.count_apply())
        except Exception as exc:
            errors.append(exc)

    with bind_for_test(count_task, count):
        th = threading.Thread(target=confirm)
        th.start()
        try:
            assert entered.wait(5)
            if conflict:
                t.inventory.commit(
                    t.inventory.prepare(
                        [StockLine(StockKey("eye", "unknown", "A"), 1)], "add"
                    ),
                    allow_duplicate=True,
                )
            new_review = count_task._count_review("A", {1: _item("Yormandi Eye", 4)})
            count.review = new_review
        finally:
            finished.set()
            th.join(5)
        assert not th.is_alive() and not errors
        if conflict:
            assert "重新盘点" in result[0]["error"]
        else:
            assert "error" not in result[0]
        assert count.review == new_review
        assert messages[-1] == ("count", {"running": False, "review": new_review})
        assert t.inventory.list_stock()[0].quantity == (6 if conflict else 2)


def test_alias_names_merge_by_matched_stock_keys(monkeypatch, tmp_path):
    t = _context(monkeypatch, tmp_path, [("eye", "unknown", "A", 5)])
    monkeypatch.setattr(
        goals,
        "resolve_all",
        lambda t, en, zh: ["eye", "unused"] if en == "Alias" else ["eye"],
    )
    review = count_task._count_review("A", {1: _item("Alias"), 2: _item("Official", 4)})
    assert len(review["rows"]) == 1
    r = review["rows"][0]
    assert (r["book"], r["game"], r["delta"], r["cells"]) == (5, 6, 1, 2)
    assert r["keys"] == [["eye", "unknown", "A", "unit"]]
    assert review["missing"] == []
    count = count_helpers.count()
    count.review = review
    monkeypatch.setattr(bus, "publish", lambda *args: None)
    with bind_for_test(count_task, count):
        assert "error" not in count_task.count_apply()
    assert t.inventory.list_stock()[0].quantity == 6


def test_alias_names_keep_distinct_matches_quality_and_units(monkeypatch, tmp_path):
    _context(
        monkeypatch,
        tmp_path,
        [
            ("eye", "unknown", "A", 5),
            ("vp", "unknown", "A", 7),
            ("eye", "exact:5", "A", 3),
            ("eye", "unknown", "A", 1000000, "uSCU"),
        ],
    )
    ids = {"one": ["eye", "unused"], "two": ["vp"], "quality": ["eye"], "scu": ["eye"]}
    monkeypatch.setattr(goals, "resolve_all", lambda t, en, zh: ids[en])
    rv = count_task._count_review(
        "A",
        {
            1: _item("one"),
            2: _item("two", 4),
            3: _item("quality", 1, quality=5),
            4: _item("scu", 2, unit="SCU"),
        },
    )
    assert len(rv["rows"]) == 4
    assert [r["book"] for r in rv["rows"]] == [5, 7, 3, 1]
    assert len({tuple(k) for r in rv["rows"] for k in r["keys"]}) == 4


def test_partial_stock_overlap_refuses_without_writing(monkeypatch, tmp_path):
    t = _context(
        monkeypatch, tmp_path, [("eye", "unknown", "A", 5), ("vp", "unknown", "A", 7)]
    )
    monkeypatch.setattr(
        goals,
        "resolve_all",
        lambda t, en, zh: ["eye"] if en == "one" else ["eye", "vp"],
    )
    count = count_helpers.count()
    count.review = count_task._count_review("A", {1: _item("one"), 2: _item("two", 4)})
    before = t.inventory.revision()
    with bind_for_test(count_task, count):
        assert "两次" in count_task.count_apply()["error"]
    assert t.inventory.revision() == before


def test_empty_book_different_unresolved_names_do_not_merge(monkeypatch, tmp_path):
    _context(monkeypatch, tmp_path)
    rv = count_task._count_review(
        "A", {1: _item("missing-one"), 2: _item("missing-two")}
    )
    assert len(rv["rows"]) == 2
    assert all(not r["keys"] and r["game"] == 2 for r in rv["rows"])


def test_bootstrap_unknown_does_not_read_last_stock_location(monkeypatch):
    from astral_toolkit.tasks import trade

    monkeypatch.setattr(stockplaces, "current_place", lambda: None)

    def forbidden():
        raise AssertionError("未知地点不应读取上次入库地点")

    monkeypatch.setattr(trade, "trade", forbidden)
    assert bootstrap._count_links({}).place_now() == ""


def test_unknown_manual_place_validation_and_start(monkeypatch, tmp_path):
    _context(monkeypatch, tmp_path)
    starts = []

    class Loop:
        def running(self):
            return False

        def start(self, payload):
            starts.append(payload)
            return 1

    notes = []
    links = bootstrap._count_links({})
    from dataclasses import replace

    links = replace(links, note=lambda *a: notes.append(a), refuse=lambda: None)
    count = count_helpers.count(links=links, _loop_factory=lambda *a, **kw: Loop())
    with bind_for_test(count_task, count):
        r = count_task.count_toggle()
        assert r["need_place"] and "选择" in r["error"]
        assert starts == [] and "选择" in notes[-1][1]
        invalid: list[Any] = ["123", "x" * 31, "A｜B", "   ", [], {}]
        for bad in invalid:
            r = count_task.count_toggle(place=bad)
            assert "error" in r and not starts
        assert count_task.count_toggle(place="New Babbage") == {
            "running": True,
            "place": "新巴贝奇",
        }
        assert starts == ["新巴贝奇"]


@pytest.mark.parametrize(
    "action, jump",
    [("rename", False), ("delete", False), ("rename", True), ("delete", True)],
)
def test_bin_aliases_read_and_edit_atomically(monkeypatch, tmp_path, action, jump):
    alias, label, second = "New Babbage", "新巴贝奇", "newbabbage"
    if jump:
        alias, second = "斯坦顿 - 派罗 跳跃点", "Stanton-Pyro Jump Point"
        p = stockplaces.match(alias)
        assert p is not None
        label = p["label"]
    t = _context(
        monkeypatch,
        tmp_path,
        [
            ("eye", "unknown", alias + "｜待卖", 2),
            ("eye", "unknown", label + "｜待卖", 3),
            ("eye", "unknown", second + "｜待卖", 4),
            ("vp", "unknown", label, 1),
        ],
    )
    raw_bins = {
        alias: {
            "bins": [
                {"name": "待卖", "desc": "旧描述"},
                {"name": "旧空仓", "desc": "保留"},
            ],
            "default": "待卖",
        },
        label: {"bins": [{"name": "待卖", "desc": "正式描述"}], "default": "待卖"},
        second: {"bins": [{"name": "新空仓", "desc": "也保留"}], "default": "新空仓"},
    }
    t.db.set("stock_bins", raw_bins)
    before = t.inventory.list_stock()
    before_revision = t.inventory.revision()
    d: Any = stock_task.stock()
    assert len(d["tree"][0]["places"]) == 1
    assert set(d["bins"]) == {label}
    assert d["bins"][label]["default"] == "待卖"
    assert {b["name"]: b["desc"] for b in d["bins"][label]["bins"]} == {
        "待卖": "正式描述",
        "旧空仓": "保留",
        "新空仓": "也保留",
    }
    assert stock_task._place_for(label) == label + "｜待卖"
    assert t.db.get("stock_bins") == raw_bins
    assert (
        t.inventory.list_stock() == before and t.inventory.revision() == before_revision
    )
    if action == "rename":
        d = stock_task.stock_bin_save(
            place=second, old="待卖", name="出售", default=True
        )
        assert "error" not in d
        target = label + "｜出售"
        assert d["bins"][label]["default"] == "出售"
    else:
        d = stock_task.stock_bin_delete(place=second, name="待卖")
        assert "error" not in d and d["moved"] == 3
        target = label
        assert d["bins"][label]["default"] == ""
    assert (
        sum(r["raw"] for r in d["rows"] if r["id"] == "eye" and r["location"] == target)
        == 9
    )
    assert all(b["name"] != "待卖" for b in d["bins"][label]["bins"])
    assert t.inventory.revision() == before_revision + 1
    assert t.inventory.history()[0]["source"] == ""  # 玩家改的仓位，记录来源不写成 AT
    t.inventory.undo(d["history"][0]["batch"])
    assert t.inventory.list_stock() == before


def test_legacy_bin_default_and_unrelated_place_remain(monkeypatch, tmp_path):
    t = _context(monkeypatch, tmp_path)
    original = {
        "New Babbage": {
            "bins": [{"name": "旧空仓", "desc": "描述"}],
            "default": "旧空仓",
        },
        "MOLE": {"bins": [{"name": "别动", "desc": "独立"}], "default": "别动"},
    }
    t.db.set("stock_bins", original)
    assert stock_task._place_for("新巴贝奇") == "新巴贝奇｜旧空仓"
    assert stock_task.stock_places()["bins"]["MOLE"] == original["MOLE"]
    assert t.db.get("stock_bins") == original


def _javascript(program):
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("本机无 Node")
    assert node is not None
    result = subprocess.run(
        [node, "-e", program],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _frontend():
    return (Path(__file__).parents[1] / "astral_toolkit/app/web/app.js").read_text(
        encoding="utf-8"
    )


def test_frontend_real_api_count_picker_cancel_confirm_and_other_error():
    """只注入 fetch，经过真实api业务错误处理，不用假的api掩盖need_place异常。"""
    source = _frontend()
    api = source[source.index("const WRITE_API") : source.index("\nfunction toast")]
    start = source.index("async function countToggle()")
    toggle = source[start : source.index("\nPAGES.stock", start)]
    result = _javascript(
        """
const TOKEN = 'test', calls = [], messages = [];
let chosen = null, picks = 0, failed = false;
const state = {count: {running: false}};
const toast = message => messages.push(message);
const countDraw = () => {};
const pickPlace = async () => { picks++; return chosen; };
const fetch = async (url, request) => {
  const args = JSON.parse(request.body);
  calls.push([url, args]);
  const data = failed ? {error: '写库失败'} : args.place ? {running: true, place: args.place} : {error: '未知地点', need_place: true};
  return {json: async () => ({ok: true, data})};
};
"""
        + api
        + toggle
        + """
(async () => {
  await countToggle();
  if (picks !== 1 || calls.length !== 1 || state.count.running) throw Error('取消选择错误');
  chosen = '新巴贝奇';
  await countToggle();
  if (picks !== 2 || calls.length !== 3 || calls[2][1].place !== chosen || !state.count.running) throw Error('手选未启动');
  failed = true;
  await countToggle();
  if (picks !== 2 || calls.length !== 4 || messages.at(-1) !== '写库失败') throw Error('普通错误被误当成选地点');
  console.log(JSON.stringify({picks, calls: calls.length}));
})();
"""
    )
    assert result == {"picks": 2, "calls": 4}


@pytest.mark.parametrize("action", ["apply", "cancel"])
def test_frontend_old_response_preserves_new_sse_review(action):
    source = _frontend()
    draw = source[
        source.index("function countDraw()") : source.index("\nfunction stockInDialog")
    ]
    program = (
        """
const old = {place:'old', rows:[], missing:[]}, fresh = {place:'new', rows:[], missing:[]};
const state = {count:{running:false, review:old}};
const nodes = {'#st-count':{}, '#st-review':{querySelectorAll:()=>[]}, '#cr-ok':{}, '#cr-no':{}};
const $ = selector => nodes[selector], esc = String, qtyText = String, stockShow = () => {}, toast = () => {};
let release;
const api = () => new Promise(resolve => {release = () => resolve({});});
"""
        + draw
        + """
(async () => {
  countDraw();
  const done = nodes[ACTION].onclick();
  state.count = {...state.count, running: true, review: fresh};
  release();
  await done;
  if (state.count.review !== fresh || !state.count.running) throw Error('旧响应覆盖新SSE');
  console.log(JSON.stringify({place:state.count.review.place}));
})();
"""
    )
    result = _javascript(
        program.replace("ACTION", "'#cr-ok'" if action == "apply" else "'#cr-no'")
    )
    assert result == {"place": "new"}


def test_real_catalog_english_name_wins_over_shared_label(monkeypatch, tmp_path):
    """英文名明确对上正式物品时按英文名认：汉化名撞到别的物品，不把它的库存配过去，也不整笔拒绝（审查 2026-11-08）"""
    t = _context(monkeypatch, tmp_path, [("eye", "unknown", "A", 5)])
    t.catalog.add_alias("eye", "shared-label")
    items = {
        1: {**_item("Yormandi Eye", 2), "zh": "shared-label"},
        2: {**_item("Vanduul Plating", 4), "zh": "shared-label"},
    }
    assert goals.resolve_all(t, "Yormandi Eye", "shared-label") == ["eye"]
    assert set(goals.resolve_all(t, "Vanduul Plating", "shared-label")) == {"eye", "vp"}
    rv = count_task._count_review("A", items)
    assert [(r["en"], r["book"], r["game"]) for r in rv["rows"]] == [
        ("Yormandi Eye", 5, 2),
        ("Vanduul Plating", 0, 4),
    ]
    assert "conflicts" not in rv
    count = count_helpers.count()
    count.review = rv
    monkeypatch.setattr(bus, "publish", lambda *args: None)
    with bind_for_test(count_task, count):
        assert "error" not in count_task.count_apply()
    got = {line.key.item_id: line.quantity for line in t.inventory.list_stock()}
    assert got == {"eye": 2, "vp": 4}


@pytest.mark.parametrize(
    "vid, name",
    [
        ("rare", "Yormandi Eye (Rare)"),  # F8 当时模糊配到的那条
        ("local:Yormandi Eyes", "Yormandi Eyes"),  # 旧英文名的本地副本
        (
            "local:Old Eye Name",
            "Old Eye Name",
        ),  # 改名改得多的本地副本：本地副本照旧都算
    ],
)
def test_variant_entry_with_same_label_counts_once(monkeypatch, tmp_path, vid, name):
    """同一件东西的库存记在另一条目录名下（F8 当时模糊配到的那条、旧英文名的本地副本），和英文名那条挂着同一个中文名：
    盘点按英文名认时也配上它，确认后不变成两份；撞名、名字不像的别的物品照样不配（审查 2026-11-08）"""
    from astral_toolkit.trade.matching import names_alike
    from astral_toolkit.trade.models import Item

    assert names_alike(name, "Yormandi Eye") != (vid == "local:Old Eye Name")
    assert not names_alike("Vanduul Plating", "Yormandi Eye")
    t = _context(monkeypatch, tmp_path)
    t.catalog.upsert([Item(vid, name)])
    for iid in ("eye", vid, "vp"):  # 英文名那条、变体、撞名的别的物品都挂着同一个中文名
        t.catalog.add_alias(iid, "约曼迪之眼")
    t.inventory.commit(
        t.inventory.prepare(
            [
                StockLine(StockKey(vid, "unknown", "A"), 5),
                StockLine(StockKey("vp", "unknown", "A"), 7),
            ],
            "add",
        ),
        allow_duplicate=True,
    )
    rv = count_task._count_review(
        "A", {1: {**_item("Yormandi Eye", 5), "zh": "约曼迪之眼"}}
    )
    assert [(r["book"], r["game"], r["delta"]) for r in rv["rows"]] == [(5, 5, 0)]
    assert [m["key"][0] for m in rv["missing"]] == ["vp"]
    count = count_helpers.count()
    count.review = rv
    monkeypatch.setattr(bus, "publish", lambda *args: None)
    with bind_for_test(count_task, count):
        assert "error" not in count_task.count_apply()
    got = {line.key.item_id: line.quantity for line in t.inventory.list_stock()}
    assert got == {vid: 5, "vp": 7}


def test_same_item_two_english_names_merge_at_new_place(monkeypatch, tmp_path):
    """账上还没有这件东西的地点：同一物品的两个英文名也合成一行，确认时不报「出现了两次」（审查 2026-11-08）"""
    from astral_toolkit.trade.models import Item

    t = _context(monkeypatch, tmp_path)
    t.catalog.add_alias("eye", "Eye Alias")
    t.catalog.upsert([Item("local:Eye Alias", "Eye Alias")])
    rv = count_task._count_review(
        "A", {1: _item("Yormandi Eye", 2), 2: _item("Eye Alias", 4)}
    )
    assert len(rv["rows"]) == 1
    assert rv["rows"][0]["game"] == 6 and not rv["rows"][0]["keys"]
    count = count_helpers.count()
    count.review = rv
    monkeypatch.setattr(bus, "publish", lambda *args: None)
    with bind_for_test(count_task, count):
        assert "error" not in count_task.count_apply()
    got = [(line.key.item_id, line.quantity) for line in t.inventory.list_stock()]
    assert got == [("eye", 6)]


def test_place_pick_while_running_keeps_count(monkeypatch, tmp_path):
    """选地点框还开着时游戏里已经按 F6 开始了：再选地点不把刚开始的盘点停掉；不带地点照旧是停（审查 2026-11-08）"""
    _context(monkeypatch, tmp_path)
    count = count_helpers.count()
    stops = []
    monkeypatch.setattr(count, "running", lambda: True)
    monkeypatch.setattr(count, "stop", lambda: stops.append(1) or {"running": False})
    with bind_for_test(count_task, count):
        r = count_task.count_toggle(place="New Babbage")
        assert r["running"] is True and not stops
        assert count_task.count_toggle() == {"running": False} and stops == [1]


def test_legacy_bin_default_and_desc_fill_official_blanks(monkeypatch, tmp_path):
    """正式名的默认仓位、同名仓位描述是空的：用旧名设过的，不让自动建的空设置盖掉（审查 2026-11-08）"""
    t = _context(monkeypatch, tmp_path)
    t.db.set(
        "stock_bins",
        {
            "New Babbage": {
                "bins": [{"name": "待卖", "desc": "旧描述"}],
                "default": "待卖",
            },
            "新巴贝奇": {"bins": [{"name": "待卖", "desc": ""}], "default": ""},
        },
    )
    b = stock_task.stock_places()["bins"]["新巴贝奇"]
    assert b["default"] == "待卖"
    assert b["bins"] == [{"name": "待卖", "desc": "旧描述"}]


def test_real_catalog_same_item_alias_merges_despite_extra_local_candidate(
    monkeypatch, tmp_path
):
    from astral_toolkit.trade.models import Item

    t = _context(monkeypatch, tmp_path, [("eye", "unknown", "A", 5)])
    t.catalog.add_alias("eye", "Eye Alias")
    t.catalog.upsert([Item("local:Eye Alias", "Eye Alias")])
    assert goals.resolve_all(t, "Eye Alias") == ["eye", "local:Eye Alias"]
    rv = count_task._count_review(
        "A", {1: _item("Yormandi Eye", 2), 2: _item("Eye Alias", 4)}
    )
    assert len(rv["rows"]) == 1 and rv["rows"][0]["game"] == 6
    count = count_helpers.count()
    count.review = rv
    with bind_for_test(count_task, count):
        assert "error" not in count_task.count_apply()
    assert t.inventory.list_stock()[0].quantity == 6


@pytest.mark.parametrize("action", ["rename", "delete"])
def test_bin_settings_failure_rolls_back_stock_and_settings(
    monkeypatch, tmp_path, action
):
    t = _context(
        monkeypatch,
        tmp_path,
        [
            ("eye", "unknown", "New Babbage｜旧仓", 2),
            ("eye", "unknown", "新巴贝奇｜旧仓", 3),
        ],
    )
    meta = {
        "New Babbage": {"bins": [{"name": "旧仓", "desc": "保留"}], "default": "旧仓"}
    }
    t.db.set("stock_bins", meta)
    before, revision, history = (
        t.inventory.list_stock(),
        t.inventory.revision(),
        t.inventory.history(),
    )
    original = t.db.set

    def failed_set(key, value):
        if key == "stock_bins":
            # 故障发生在SQL已经成功之后；外层必须把这次设置和前面的库存流水一起回滚。
            original(key, value)
            raise OSError("模拟写设置失败")
        original(key, value)

    monkeypatch.setattr(t.db, "set", failed_set)
    with pytest.raises(OSError, match="模拟写设置失败"):
        if action == "rename":
            stock_task.stock_bin_save(
                place="新巴贝奇", old="旧仓", name="新仓", default=True
            )
        else:
            stock_task.stock_bin_delete(place="新巴贝奇", name="旧仓")
    assert t.inventory.list_stock() == before
    assert t.inventory.revision() == revision and t.inventory.history() == history
    assert t.db.get("stock_bins") == meta


@pytest.mark.parametrize("conflict", [True, False])
def test_publish_snapshot_cannot_overtake_new_worker_finish(
    monkeypatch, tmp_path, conflict
):
    """旧提交在bus入队前阻塞；新worker的真实finish输出与命令状态发布共用原子边界。"""
    from types import SimpleNamespace
    from astral_toolkit.runtime.session import StopInfo
    from astral_toolkit.runtime.workers.count import _CountCtx

    t = _context(monkeypatch, tmp_path, [("eye", "unknown", "A", 5)])
    count = count_helpers.count()
    count.review = count_task._count_review("A", {1: _item("Yormandi Eye", 2)})
    if conflict:
        t.inventory.commit(
            t.inventory.prepare([StockLine(StockKey("eye", "unknown", "A"), 1)], "add"),
            allow_duplicate=True,
        )
    old_entered, release, fresh_entered, fresh_done = [
        threading.Event() for _ in range(4)
    ]
    events, errors = [], []

    def publish(kind, data):
        if threading.current_thread().name == "old-apply":
            old_entered.set()
            if not release.wait(5):
                raise RuntimeError("未释放旧提交")
        if kind == "count":
            events.append(data)

    monkeypatch.setattr(bus, "publish", publish)
    # 只把输出终端换成记录器；会话锁、共享状态和 worker.finish 返回的输出均沿用真实实现。
    monkeypatch.setattr(
        count.loop._output,
        "apply",
        lambda op: publish(op[1], op[2]) if op[0] == "bus" else None,
    )
    fresh = count_task._count_review("A", {1: _item("Yormandi Eye", 4)})
    monkeypatch.setattr(count._worker._an, "review", lambda *a: fresh)
    session = SimpleNamespace(payload="A")
    ctx = _CountCtx(items={1: _item("Yormandi Eye", 4)})
    finish_ops = count._worker.finish(session, ctx, StopInfo("user"))

    def confirm():
        try:
            count_task.count_apply()
        except Exception as exc:
            errors.append(exc)

    def finish():
        fresh_entered.set()
        deferred = []
        # 生产_finish_thread正是以该锁应用finish输出；不伪造review setter / publish两次调用。
        with count.loop._lock:
            count.loop._apply_locked(finish_ops, deferred)
        count.loop._run_ops(deferred)
        fresh_done.set()

    with bind_for_test(count_task, count):
        old = threading.Thread(target=confirm, name="old-apply")
        new = threading.Thread(target=finish)
        old.start()
        try:
            assert old_entered.wait(5)
            new.start()
            assert fresh_entered.wait(5)
            # 旧命令尚在入队边界内时，新finish必须等待；红测会看到它已先完成。
            assert not fresh_done.wait(0.2)
        finally:
            release.set()
            old.join(5)
            if new.ident is not None:
                new.join(5)
        assert not old.is_alive() and not new.is_alive() and not errors
    assert count.review == fresh
    assert events[-1]["review"] == fresh


def test_real_catalog_local_stock_alias_merges_with_official_name(
    monkeypatch, tmp_path
):
    """旧英文别名只映射本地副本；两种名字命中同一批正式与本地库存，应只计算一次账面。"""
    from astral_toolkit.trade.models import Item

    t = _context(monkeypatch, tmp_path, [("eye", "unknown", "A", 5)])
    t.catalog.upsert(
        [
            Item("local:Yormandi Eye", "Yormandi Eye"),
            Item("local:Eye Alias", "Eye Alias"),
        ]
    )
    t.catalog.add_alias("eye", "共享名称")
    t.catalog.add_alias("local:Yormandi Eye", "共享名称")
    t.catalog.add_alias("local:Yormandi Eye", "Eye Alias")
    t.inventory.commit(
        t.inventory.prepare(
            [StockLine(StockKey("local:Yormandi Eye", "unknown", "A"), 3)], "add"
        ),
        allow_duplicate=True,
    )
    items = {
        1: {**_item("Yormandi Eye", 2), "zh": "共享名称"},
        2: {**_item("Eye Alias", 4), "zh": "共享名称"},
    }
    assert set(goals.resolve_all(t, "Yormandi Eye", "共享名称")) == {
        "eye",
        "local:Yormandi Eye",
    }
    assert set(goals.resolve_all(t, "Eye Alias", "共享名称")) == {
        "eye",
        "local:Yormandi Eye",
        "local:Eye Alias",
    }
    before, revision = t.inventory.list_stock(), t.inventory.revision()
    rv = count_task._count_review("A", items)
    assert len(rv["rows"]) == 1 and "conflicts" not in rv
    row = rv["rows"][0]
    assert (row["book"], row["game"], row["delta"], row["cells"]) == (8, 6, -2, 2)
    assert {key[0] for key in row["keys"]} == {"eye", "local:Yormandi Eye"}
    count = count_helpers.count()
    count.review = rv
    with bind_for_test(count_task, count):
        assert "error" not in count_task.count_apply()
    assert sum(line.quantity for line in t.inventory.list_stock()) == 6
    assert t.inventory.revision() == revision + 1
    t.inventory.undo(t.inventory.history()[0]["batch_id"])
    assert t.inventory.list_stock() == before
