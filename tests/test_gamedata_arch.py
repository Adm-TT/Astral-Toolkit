"""架构约束的最小自动检查（架构稿 v1.1 §11.3 / §13.4，2026-11-02）

1. 导入方向：gamedata/_*.py 不导入 tasks / app（含函数体内的 import）——数据层不能反向依赖界面和任务实现。
2. 导入器复用的纯规则（assign_keys、各 _fold、_norm 等）在「查询 / 建库入口被换成调用即报错」的条件下仍能处理固定输入：
   规则本身不触发 ensure / rebuild / snapshot。
3. 同步 ensure() 失败也要能从公开的 gamedata.last_error() 查到（架构稿 v1.1 §13.2 抓到的缺口）。"""

import ast
from pathlib import Path

from tests.test_gamedata_b1 import _setup

_ROOT = Path(__file__).resolve().parent.parent / "astral_toolkit"
_FORBIDDEN = ("astral_toolkit.tasks", "astral_toolkit.app")


def _imports_in(path: Path):
    """模块里所有 import（含函数体内、try 块里的），还原成绝对模块名"""
    pkg = ".".join(path.relative_to(_ROOT.parent).with_suffix("").parts[:-1])
    return _imports_in_source(path.read_text(encoding="utf-8"), pkg)


def _imports_in_source(source: str, pkg: str):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg.split(".")
                base = base[: len(base) - node.level + 1]
                mod = ".".join(base + ([node.module] if node.module else []))
            else:
                mod = node.module or ""
            yield mod
            for a in node.names:
                yield f"{mod}.{a.name}"


def test_gamedata_core_does_not_import_tasks_or_app():
    bad = []
    for p in sorted((_ROOT / "gamedata").glob("_*.py")):
        for mod in _imports_in(p):
            if mod.startswith(_FORBIDDEN):
                bad.append(f"{p.name}: {mod}")
    assert bad == [], bad


def test_gamedata_topics_do_not_import_tasks_or_app():
    """topic 模块（items / shops / …）也不能反向依赖；允许它们 import crafting / navigation / trade 里的纯规则"""
    bad = []
    for p in sorted((_ROOT / "gamedata").glob("[a-z]*.py")):
        for mod in _imports_in(p):
            if mod.startswith(_FORBIDDEN):
                bad.append(f"{p.name}: {mod}")
    assert bad == [], bad


def test_reused_rules_are_pure(monkeypatch):
    """导入器复用的规则在查询 / 建库入口全部「调用即报错」时照常算：规则不查库、不建库、不开快照"""
    import astral_toolkit.gamedata as G
    from astral_toolkit.gamedata import _build, _db, _ready

    def boom(*a, **k):
        raise AssertionError("纯规则不该触发查询 / 建库")

    for mod, names in (
        (_ready, ("ensure", "use")),
        (_build, ("rebuild_if_needed", "build")),
        (_db, ("snapshot", "current_version")),
        (G, ("ensure", "snapshot", "rebuild", "version")),
    ):
        for n in names:
            monkeypatch.setattr(mod, n, boom)

    from astral_toolkit.contracts.blueprints import assign_keys
    from astral_toolkit.contracts.textkeys import (
        blueprint_norm,
        blueprint_search_norm,
        en_key,
        fold_en as _fold_en,
        junk_en as _junk,
        norm_zh as _norm_zh,
        zh_key,
    )
    from astral_toolkit.crafting.loot import _fold as loot_fold
    from astral_toolkit.crafting.wikelo import _fold as wikelo_fold
    from astral_toolkit.navigation.names import _norm
    from astral_toolkit.navigation.starmap import fix_points
    from astral_toolkit.navigation.transit import _city_rows

    bps = [{"n": "X"}, {"n": "X"}, {"n": "Y"}]
    keys, index, total = assign_keys(bps)
    assert [keys[id(b)] for b in bps] == ["X#1", "X#2", "Y"] and total["X"] == 2
    assert (
        blueprint_norm("Main Power-Plant") == "mainpowerplant"
        and blueprint_search_norm("Main Power") == "mainpower"
    )
    assert (
        en_key("Lawson Mining Laser")
        == loot_fold("Lawson Mining Laser")
        == wikelo_fold("Lawson Mining Laser")
        == "iawsonminingiaser"
    )
    assert zh_key("医疗 笔") and _norm("Everus Harbor") == "everusharbor"
    assert (
        _fold_en("'Arrow' I Missile") == "arrowimissile"
        and _norm_zh("医疗笔")
        and _junk("HD", set()) is True
    )
    data = {
        "points": [
            {"n": "A", "i": "RR_ARC_L1", "sys": "Stanton", "x": 1, "y": 2, "z": 3}
        ]
    }
    fix_points(data, None)
    assert data["points"][0]["n"] == "A"
    assert isinstance(_city_rows({}), list)


def test_sync_ensure_failure_visible_in_last_error(monkeypatch, tmp_path):
    """同步 ensure() 建库失败：公开 last_error() 能查到；之后成功就绪会清掉（架构稿 v1.1 §13.2）"""
    import astral_toolkit.gamedata as G
    from astral_toolkit.core import paths
    from tests.minipytest import raises

    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(paths, "DATA", tmp_path / "empty")  # 没有 shops.json：建不出
    assert G.last_error() is None
    with raises(G.GamedataError):
        G.ensure()
    err = G.last_error()
    assert err is not None and "就绪失败" in err
    monkeypatch.setattr(
        paths, "DATA", tmp_path
    )  # 换回有源的目录（另一个库目录，退避按目录记）
    G.ensure()
    assert G.last_error() is None
