# 游戏数据层 批 2（starmap / position / transit / navigate / 地名对照）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 星图、位置、城市 / 空间站中转、地表导航、地名中文对照这五块的数据读取全部改走 `sc_mining/gamedata`（schema 2 的 11 张表，公共层先行 PR 已合），删掉它们直接读 JSON 的代码，对外行为不变。

**Architecture:** 公开函数签名和返回形状不变。`starmap.load()` 继续返回 `{bodies, pois, points, fetched}` 这个 dict——但从库组装、按 `gamedata.version()` 缓存一份，`navigate / transit / celestial / mining_area / shops.shop_point` 这些拿 dict 的消费方本批不动；热点查找（`position.find_point`、`names.poi_zh`、`position.place_name`、`transit.city_places / station_lifts / amenity_targets`、`navigate.mining_spots`）改成库查询。新增 topic：`gamedata/starmap.py`、`gamedata/places.py`（城市地点 + 设施 + 电梯 + 地名对照）、`gamedata/mining.py`（本批只放 `spots()`，批 5 扩）。

**Tech Stack:** Python 3.12 标准库；`tests/minipytest`。

**Spec:** 设计文档 v3；矩阵 `docs/superpowers/specs/2026-11-02-gamedata-callsites-b2.md`；地基 API `sc_mining/gamedata/__init__.py`；批 1 定下的 `_ready.ensure()` 用法（topic 函数先 `ensure()` 再 `snapshot()`，支持传入已有 `Snapshot`）。

## Global Constraints

- 基线分支 `1.1.4-beta.1-database`（须已含 schema 2 和批 1）。本批分支 `feat/gamedata-b2-nav`，PR 目标 `1.1.4-beta.1-database`。
- **行为不变**：新写 `tools/gamedata_baseline_nav.py`（Task 0）在迁移前存一份基线，迁移后逐字一致；差异只能是“原代码缺陷”且在 PR 里逐条写明。
- 只改：`sc_mining/navigation/starmap.py`、`position.py`、`transit.py`、`navigate.py`、`names.py`、`sc_mining/gamedata/starmap.py`、`gamedata/places.py`、`gamedata/mining.py`、`gamedata/__init__.py`（只加导出）、`tools/gamedata_baseline_nav.py`、`tests/test_gamedata_b2.py`、`tests/run_all.py`（加一行）。**不动** `gamedata/_*.py`、`celestial.py`（读 userdata，不迁）、`stockplaces.py`（批 1）、`mining_area.py`（批 5）。
- 不改 `pyproject.toml`、不刷 baseline；ruff 过；basedpyright 新文件 0、全项目不高于基线分支。
- 中文注释；不模拟输入；不碰 `userdata/`；测试不读真实 `data/`。
- 每 Task 一提交，信息 `<type>: <中文一句话>`，不带会话链接；不推送。
- 旧读 JSON 代码删掉，不留开关。`starmap.update()` 保留（写 JSON 的更新流程），最外层套 `gamedata.updating()`；`localization.rebuild()` 最外层套 `updating()`（**updating 在外、BUILD_LOCK 在内**，和 `data_pack.install` 一致）。
- `position.place_name` 里读汉化包 `read_ini()` 的部分是用户数据，**保留原样**，只把 `places_zh / place_codes_zh` 两份换成库查询。
- `points.i` 不唯一：按内部名查一律 `ORDER BY source_order LIMIT 1`。

## Review Focus

1. **拉格朗日点内部名的大小写**（`RR_ARC_L1` → `ARC_L1`、Pyro 的 `P1_L1`）：`find_point(internal=)` 以前 `.lower()` 比，库里 `i_lower` 必须同样规则；`shops.shop_point` 用它给商店定位，错了“最近买点”全错。→ Task 2 测试 `test_find_point_internal_case_insensitive_first_match`。
2. **`place_name` 的前缀最短键**：以前 `sorted(keys, key=len)[0]`，Python 排序稳定、同长按插入顺序；SQL `ORDER BY length(norm_key), source_order LIMIT 1` 才等价。→ Task 3 测试 `test_place_name_prefix_shortest_then_first`。
3. **更新数据后导航立刻用新星图**：`starmap.load()` 的 dict 缓存要在换代后失效，而 `navigate` 里有 `data=None` 形参的函数每次都调 `load()`。→ Task 1 测试 `test_starmap_load_refreshes_after_rebuild`。
4. **同名城市地点加序号**（`公寓大堂 2`）：序号在导入时算好进库，`transit.city_places()` 读出来必须与 `_city_rows` 直接算的一致，包括 `空间点 @sys`。→ Task 4 测试 `test_city_places_equal_to_legacy_transform`。
5. **`amenity_targets` 的三种引用回查**（poi / point / internal）在星图和设施分开更新时仍然各查各的当前数据。→ Task 4 测试 `test_amenity_targets_resolves_three_ref_kinds`。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `gamedata/starmap.py` | `bodies() / pois() / points()`（整表 tuple，按版本缓存）、`body(name)`、`point_by_internal(i)`、`point_by_name(name)`、`poi_by_norm(norm)`、`data_dict()`（组装成旧 `load()` 的 dict，按版本缓存）、`fetched()` |
| `gamedata/places.py` | `city_places()`（变换后的 dict 列表，按版本缓存）、`city_places_by(city, line=None)`、`amenities(kind)`、`station_lifts()`（`{key: 整站 dict}`，按版本缓存）、`station_lift(key)`、`zh_of(norm_key)`、`zh_by_prefix(prefix)`、`code_zh(code)` |
| `gamedata/mining.py` | `spots()`（原始米坐标 tuple，按版本缓存） |
| `navigation/starmap.py` | `load()` → `gamedata.starmap.data_dict()`；删 `_data / _data_stamp / _files_stamp / _apply_fixes` 的读路径（`fix_points` 留给导入用）；`update()` 套 `updating()` |
| `navigation/position.py` | `points() / find_point / _places_zh / _zh_name / place_name` 改库查询；`_station_at` 已在批 1 改 |
| `navigation/transit.py` | `city_places / station_lifts / amenity_targets` 改库；`_city_rows / _lift_rows` 保留（导入在用） |
| `navigation/navigate.py` | `mining_spots()` 改 `gamedata.mining.spots()`，缓存键改 `(gamedata.version(), rocks_stamp())`；删死导入 `_data`、`_data_stamp` |
| `navigation/names.py` | `poi_zh` 改 `places.zh_of`，删 `_places_zh` 合并缓存 |
| `tools/gamedata_baseline_nav.py` | 固定查询：`find_point` 若干内部名/名字、`place_name` 若干代码、`poi_zh` 若干名、`city_places()` 长度和前 20 条、`station_lifts()` 键集合、`amenity_targets("医疗")` 名字列表、`mining_spots()` 前 10、`navigate.search("Lorville")`、`transit.nearest(...)` 一例 |
| `tests/test_gamedata_b2.py` | 本批测试（复用 `tests/test_gamedata_nav.py` 的 `_NAV_SOURCES` 最小数据） |

---

### Task 0: 分支与基线
- [ ] worktree `feat/gamedata-b2-nav`，拷 `data\`（含 `loot\`、`loot_details.zip`）。
- [ ] 写 `tools/gamedata_baseline_nav.py`（查询列表见上表，输出格式同 `gamedata_baseline.py`），跑一次存 `<项目资料>\测试数据\gamedata_baseline_nav_before.json`；`tests.run_all` 记基数。提交 `chore: 导航数据迁移前的行为基线工具`。

### Task 1: `gamedata/starmap.py` + `navigation/starmap.load()`
- [ ] 测试：`test_points_tuple_order`、`test_point_by_internal_first_of_duplicates`（两条同 `i`，取 `source_order` 小的）、`test_data_dict_shape_matches_legacy`（键集合 `{bodies, pois, points, fetched}`，`bodies` 是 `{name: {sys,x,y,z,rot,adj,r,om,grid}}`，`pois/points` 字段名与源一致、无多余列）、`test_starmap_load_refreshes_after_rebuild`（Review Focus 3）、`test_starmap_update_runs_inside_updating`。
- [ ] 红 → 实现 → 绿 → 提交 `refactor: 星图改从游戏数据层组装，缓存按内容版本失效`。

### Task 2: `position.points / find_point`
- [ ] 测试：`test_find_point_internal_case_insensitive_first_match`（Review Focus 1）、`test_find_point_name_norm`、`test_find_point_pyro_roman`（`pyroiii` → `Pyro3`）、`test_from_code_lagrange`。
- [ ] 红 → 实现（`find_point` 走 `gamedata.starmap.point_by_internal / point_by_name`，返回**与旧 dict 同形**的 dict `{n,i,sys,t,x,y,z}`，因为调用方取 `p["i"]`、`p["x"]`）→ 绿 → 提交。

### Task 3: 地名对照（`names.poi_zh`、`position._places_zh / _zh_name / place_name`）
- [ ] 测试：`test_poi_zh_extra_overrides`、`test_poi_zh_strips_bracket_notes`、`test_place_name_prefix_shortest_then_first`（Review Focus 2）、`test_place_name_code_table_then_ini`（`read_ini` 用 monkeypatch 返回一个覆盖项，库值被 ini 覆盖——保持原顺序）、`test_zh_name_station_suffix_fallback`。
- [ ] 红 → 实现（`position._places_zh()` 的调用方只有 `_zh_name` / `place_name`：改为 `places.zh_of / zh_by_prefix`；若核对发现 `position` 必须只看 `places_zh` 不看 extra，用 `src='zh'` 过滤并在 PR 里写明）→ 绿 → 提交。

### Task 4: `transit.city_places / station_lifts / amenity_targets`
- [ ] 测试：`test_city_places_equal_to_legacy_transform`（Review Focus 4：对最小源，`transit.city_places()` 结果与 `transit._city_rows(json)` 逐条相等，含 `t="City"`、`qt=0`、`up` 元组）、`test_station_lifts_equal_to_legacy`、`test_amenity_targets_resolves_three_ref_kinds`（Review Focus 5）、`test_transit_does_not_read_json`（`paths.DATA` 指向只有 `gamedata/` 的目录仍能工作）。
- [ ] 红 → 实现 → 绿 → 提交 `refactor: 城市地点、设施、空间站电梯改走游戏数据层`。

### Task 5: `navigate.mining_spots` + 死导入
- [ ] 测试：`test_mining_spots_divides_by_1000_and_merges`（与旧实现在最小源上逐条相等）、`test_navigate_has_no_starmap_private_imports`（`"_data" not in dir(navigate)` 且 import 不报错）。
- [ ] 红 → 实现 → 绿 → 提交。

### Task 6: `localization.rebuild` 套更新边界
- [ ] 测试：`test_localization_rebuild_runs_inside_updating`（monkeypatch `write_json` 和 `gamedata.updating` 计数，`BUILD_LOCK` 在 `updating` 之内）。
- [ ] 红 → 实现 → 绿 → 提交。

### Task 7: 基线比对、性能、全量
- [ ] `gamedata_baseline_nav.py --out …_after.json`，与 before 的 `results` 逐字比对为空。
- [ ] 性能：`starmap.load()` 首次耗时、`find_point` ×1000 耗时、`transit.city_places()` 首次耗时，前后对照写 `<项目资料>\测试数据\gamedata_b2_perf.md`。
- [ ] 全量测试、ruff、basedpyright。
- [ ] 实机：导航页搜地点、去一个城市地点、空间站电梯路线、更新数据后再搜。

### Task 8: 审查与交付
- [ ] 新上下文审 diff（重点：dict 形状等价、首个命中语义、缓存失效、锁顺序）→ 修 → 复跑 Task 7 → PR 说明放 `<项目资料>\记录\PR_gamedata_b2.md` → 等负责人实机验收，不推。
