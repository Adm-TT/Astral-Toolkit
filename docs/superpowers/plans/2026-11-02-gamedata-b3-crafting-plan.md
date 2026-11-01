# 游戏数据层 批 3（crafting / wikelo / itemstats）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 制造蓝图、维科洛合同、成品属性、打印点、出厂配件五份数据的读取改走 `sc_mining/gamedata`（schema 4 的 11 张表，公共层先行 PR 已合），删掉直接读 JSON 的代码，对外行为不变。

**Architecture:** 公开函数签名和返回形状不变。`crafting.data()` / `blueprints()` 仍返回同形 dict 列表（bp 是嵌套 dict，从库的 `slots_json / src_json` 还原），按 `gamedata.version()` 缓存一份，保证同版本内 bp 对象身份稳定（`_keys()` 靠 `id(bp)`）；`for_item / by_key / search / uses / mat_summary / needs` 的扫描改成索引查询；`wikelo.load()`、`itemstats.item()` 同理。新增 topic：`gamedata/crafting.py`、`gamedata/wikelo.py`、`gamedata/itemstats.py`。

**Tech Stack:** Python 3.12 标准库；`tests/minipytest`。

**Spec:** 设计文档 v3；矩阵 `docs/superpowers/specs/2026-11-02-gamedata-callsites-b3.md`；地基 API 和批 1 定下的 `_ready.use(snap)` 用法。

## Global Constraints

- 基线分支 `1.1.4-beta.1-database`（须已含 schema 4 和批 1）。本批分支 `feat/gamedata-b3-crafting`，PR 目标 `1.1.4-beta.1-database`。
- **行为不变**：新写 `tools/gamedata_baseline_craft.py` 迁移前存基线，迁移后逐字一致。
- 只改：`sc_mining/crafting/crafting.py`、`wikelo.py`、`itemstats.py`、`acquire.py`（仅 `ship_items` 那一段）、`build_crafting.py`（仅 `build()` 套 `updating()`）、`sc_mining/gamedata/crafting.py`、`gamedata/wikelo.py`、`gamedata/itemstats.py`、`gamedata/__init__.py`（只加导出）、`tools/gamedata_baseline_craft.py`、`tests/test_gamedata_b3.py`、`tests/run_all.py`（加一行）。**不动** `gamedata/_*.py`、`goals.py`、`tasks/*`、`mining/laser.py`（它们只是消费 bp dict）。
- 不改 `pyproject.toml`、不刷 baseline；ruff 过；basedpyright 新文件 0、全项目不高于基线分支。
- 中文注释；不模拟输入；不碰 `userdata/`；测试不读真实 `data/`。
- 每 Task 一提交，不带会话链接；不推送。
- 旧读 JSON 代码删掉，不留开关。`data()` 对“库里没有蓝图”的处理和现在一样：返回 `{"blueprints": []}`，记一次警告。
- `_keys()` 的编号规则不改；`by_key(key)` 对旧编号（只有名字）的兼容（`index.get(f"{key}#1")`）不改。

## Review Focus

1. **bp 对象身份**：`bp_key(bp)` 用 `id(bp)` 查表，两次 `blueprints()` 返回的必须是同一批对象，否则目标清单里每个蓝图的编号都会变成名字（丢掉 `#2`）。→ Task 1 测试 `test_blueprints_same_objects_within_version`。
2. **`solve_slots / craft_slots` 就地改 bp**：若它们改 bp dict，缓存的那份会被污染；现状也如此，但从库还原后若用了 tuple 会直接报错。→ Task 1 测试 `test_blueprint_dicts_are_plain_mutable_like_json`（slots 是 list 不是 tuple）。
3. **`mat_summary` 的最低品质统计**：`needs` 返回 `(qty, minq)`，`gated/gates` 用 `m > 1`；平铺表 `min_q` 列若存成 REAL 会让 `sorted({m})` 输出 `2.0` 而不是 `2`。→ Task 2 测试 `test_mat_summary_gates_are_ints`。
4. **`wikelo.uses` 的 `_same` 比较**（`_fold` 后相等或互为前缀？见 L187-192）：改成 SQL 前先确认规则，不能简化成相等。→ Task 3 测试 `test_wikelo_uses_prefix_rule_preserved`。
5. **`itemstats.item()` 返回 None 的条件**：`uuid` 为空或查不到 → `None`；`s` 字典里数值 vs `{min,max}` 两种形态要还原正确。→ Task 4 测试 `test_itemstats_item_shapes`。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `gamedata/crafting.py` | `blueprints()`（同形 dict 元组，按版本缓存一份）、`by_key(key)`、`by_norm_name(norm_n)` / `by_norm_zh(norm_z)`、`search_rows(q)`、`using_material(material)`（返回 bp 列表，查 `blueprint_materials`）、`meta()`（dismantle_*、version） |
| `gamedata/wikelo.py` | `contracts()`（同形 dict 元组，按版本缓存）、`requiring(norm_n)`、`print_spots(item_name)` |
| `gamedata/itemstats.py` | `item(uuid)`（还原成原 dict 形状）、`version()` |
| `gamedata/ships.py`（可并入 itemstats） | `ships_with(item_name)` |
| `crafting/crafting.py` | `_load/_sig/_FAILED/_clear_data` 删；`data()` → 从 `gamedata.crafting.blueprints()` 组装；`for_item/search/by_key/uses/mat_summary` 改查库；`_keys()` 保留但数据源是库 |
| `crafting/wikelo.py` | `load()` → 库；`uses/search/print_spots` 改查库；`build()` 套 `updating()` |
| `crafting/itemstats.py` | `data()` 删；`item/version` 改查库 |
| `crafting/acquire.py` | `ship_items` 段改 `gamedata.ships.ships_with` |
| `crafting/build_crafting.py` | `build()` 外层套 `updating()`（BUILD_LOCK 在内） |

---

### Task 0: 分支与基线
- [ ] worktree `feat/gamedata-b3-crafting`，拷 `data\`、`tests\samples\`。
- [ ] `tools/gamedata_baseline_craft.py`：`crafting.search` 若干词、`for_item` 若干、`by_key` 若干（含 `#2`）、`mat_summary("Quantainium")`、`uses_report("Tin")`、`wikelo.uses("Medpen")`、`wikelo.search("头盔")`、`wikelo.print_spots(...)`、`itemstats.item(<3 个 uuid>)`、`acquire` 出厂船一例；存 before。提交。

### Task 1: `gamedata/crafting.py` + `crafting.data()/blueprints()/_keys`
- [ ] 测试：`test_blueprints_dict_shape_equals_json`（最小源 3 份蓝图，含重名两份 → 还原的 dict 与源逐字相等）、`test_blueprints_same_objects_within_version`、`test_blueprint_dicts_are_plain_mutable_like_json`、`test_keys_rule_unchanged`（`名字#1/#2`）、`test_data_empty_when_no_blueprints`（库里没蓝图 → `{"blueprints": []}`）。
- [ ] 红 → 实现 → 绿 → 提交。

### Task 2: `for_item / search / by_key / needs / uses / mat_summary / uses_report`
- [ ] 测试：`test_for_item_fold_rule`、`test_search_exact_before_partial_sorted`、`test_by_key_legacy_name_only`、`test_mat_summary_gates_are_ints`、`test_uses_matches_legacy_on_sample`（与把旧实现复制到测试里的 `_legacy_uses` 比）。
- [ ] 红 → 实现（`uses/mat_summary` 先用 `using_material` 拿候选 bp，再在 Python 里跑原来的 `needs` 逻辑——保持 `gated/gates` 计算一字不改）→ 绿 → 提交。

### Task 3: `wikelo`
- [ ] 测试：`test_wikelo_load_shape`、`test_wikelo_uses_prefix_rule_preserved`、`test_wikelo_search`、`test_print_spots`、`test_wikelo_build_runs_inside_updating`。
- [ ] 红 → 实现 → 绿 → 提交。

### Task 4: `itemstats` + `acquire.ship_items`
- [ ] 测试：`test_itemstats_item_shapes`（`{min,max}` 与数值两种）、`test_itemstats_none_for_unknown`、`test_itemstats_version`、`test_ships_with`。
- [ ] 红 → 实现 → 绿 → 提交。

### Task 5: 更新边界
- [ ] 测试：`test_build_crafting_runs_inside_updating`（BUILD_LOCK 在 updating 之内）。
- [ ] 红 → 实现 → 绿 → 提交。

### Task 6: 基线比对、性能、全量、实机
- [ ] after 基线与 before 逐字一致；性能：`crafting.data()` 首次耗时 / 常驻内存、`itemstats.item()` 冷热、`search` ×100；全量、ruff、basedpyright。
- [ ] 实机：制造页搜蓝图、打开一份重名蓝图的第二份、目标清单加一条、维科洛页、属性统计显示。

### Task 7: 审查与交付
- [ ] 新上下文审 diff（重点：bp 身份与形状、`_keys` 规则、`uses` 等价、锁顺序）→ 修 → PR 说明放 `<项目资料>\记录\PR_gamedata_b3.md` → 等负责人验收，不推。
