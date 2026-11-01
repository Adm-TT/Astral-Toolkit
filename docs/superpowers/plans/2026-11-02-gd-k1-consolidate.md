# 游戏数据层 收口 1（GD-K1：批 1 合并后、批 2–6 开工前）

| 日期 | 变更 | 原因 |
|---|---|---|
| 2026-11-02 | 初稿 | 批 1 控制台复审留下的重复实现 / 过渡代码，在四个批次并行开工前先收掉，免得各会话再造一遍 |
| 2026-11-02 | 审查后：蓝图 / 维科洛重建挪到 updating() 之外（它们不是库的源，且会在写锁里联网）；转换在锁外先算；二级索引按对象身份当键（`VersionCache(identity=True)`）；None 版本照旧缓存；测试文件清单补 `tests/test_gamedata.py`、`tests/test_tools.py`（换缓存对象那两行）；`VersionCache` 不从包导出，各处直接 `from ._cache import` | 新上下文审查 8 条 |

**Goal:** 把批 1 留下的「等别的批次再删」的过渡代码和「各写一份」的重复实现，在批 2–6 开工前收掉；顺手修一个与数据来源判断有关的旧 bug。对外行为不变。

**Architecture:** 新增 `gamedata/_cache.py::VersionCache`（按库内容版本缓存一份值，换代重算，只留当前版本），`gamedata/items.py`、`gamedata/shops.py`、`crafting/stockplaces.py`、`crafting/itemsearch.py` 四处手写缓存改用它。`localization.rebuild()` 和 `loot.update()` 的写源文件套进 `gamedata.updating()`（锁里只写文件；蓝图 / 维科洛重建不是库的源，留在边界外只拿 BUILD_LOCK），于是 `itemsearch._on_data_changed` 钩子没有存在理由，删。`run._is_game_source` / `make_data_pack` 按函数的 `__module__` 判断"星图是不是游戏数据版"，而 `navigate.update` 实际是 `starmap.update`（`__module__` 是 starmap），保护从没生效——改成两个模块名都认。

**Tech Stack:** Python 3.12 标准库；`tests/minipytest`。

## Global Constraints

- 基线 `1.1.4-beta.1-database`（03ae3f0 起）。分支 `chore/gd-k1-consolidate`，worktree `AT_wt\gd-k1`。
- 只改：`sc_mining/gamedata/_cache.py`（新）、`gamedata/items.py`、`gamedata/shops.py`、`gamedata/__init__.py`（导出）、`crafting/stockplaces.py`、`crafting/itemsearch.py`、`update/localization.py`、`crafting/loot.py`、`run.py`、`tools/make_data_pack.py`、`tests/test_gamedata_b1.py`（改钩子相关用例）、`tests/test_gamedata.py`、`tests/test_tools.py`（换缓存对象的几行）、`tests/test_gd_k1.py`（新）、`tests/run_all.py`。**不动** `navigation/*`（B2 的）、`data_pack.py`（B6 的）。
- 行为不变：`tools/gamedata_baseline.py` 迁移前后 `results` 逐字一致。
- 每 Task 一提交；新上下文审查一轮；全量 + ruff + basedpyright；合入基线后批 2–6 开工说明里写明「缓存用 `VersionCache`，别自己写」。

## Tasks

### Task 1: `VersionCache`
- [ ] 测试：`test_version_cache_rebuilds_on_new_version`、`test_version_cache_keeps_only_current`、`test_version_cache_clear`、`test_version_cache_get_for_explicit_key`（stockplaces 那种不开快照、按 `version()` 返回值当键的用法；键为 None 时不缓存）。
- [ ] 实现 `gamedata/_cache.py`；四处替换；`tests/test_gamedata_b1.py` 里 `monkeypatch.setattr(IS, "_cache", {...})` 改成 `VersionCache()`。基线逐字一致。

### Task 2: 写源文件进更新边界，删钩子
- [ ] 测试：`test_localization_rebuild_runs_inside_updating`（write_json 四次都在边界内，且 BUILD_LOCK 段也在内；边界只进一次）、`test_loot_update_runs_inside_updating`、`test_itemsearch_sees_new_aliases_after_rebuild_via_updating`（代替原 `test_clear_caches_rebuilds_for_writers_outside_updating`：现在靠 updating 出口重建，不靠钩子）。
- [ ] 实现；删 `itemsearch._on_data_changed` 和 `CACHE_HOOKS` 登记；`data_pack.CACHE_HOOKS` 机制保留（goals / navigation 还在用）。

### Task 3: 数据来源判断的模块名
- [ ] 测试：`test_is_game_source_recognizes_starmap_update`（`navigate.update` 指向 starmap，`starmap.json` 是游戏数据版 → True；网站版 → False）；`make_data_pack` 的 web_ok 两个名字都传。
- [ ] 实现：`run._is_game_source` 的映射表加 `sc_mining.navigation.starmap`；`make_data_pack` web_ok 元组加同名。

### Task 4: 验证与交付
- [ ] 全量、ruff、basedpyright（全项目，还原 baseline）、行为基线比对；新上下文审查；合入基线、推送；更新批 2–6 开工说明。
