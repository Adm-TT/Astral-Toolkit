# 游戏数据层 批 1 试点（shops / itemsearch / stockplaces / prices）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让商店、物品搜索、库存地点、矿价四个模块的数据读取全部改走 `sc_mining/gamedata`，删掉它们直接读 JSON 的代码，调用方和对外行为一个字不变。

**Architecture:** 保持 `crafting/shops.py`、`crafting/itemsearch.py`、`crafting/stockplaces.py`、`update/uex.apply_live` 现有公开函数的**签名和返回形状不变**（它们的调用方——`acquire`、`trade`、`console`、`position`、`stock`、`count`——本批不动），只把函数体里的“读 JSON → 内存结构 → 扫描”换成 `gamedata` 的 topic 查询。新增四个 topic：`gamedata/items.py`、`gamedata/shops.py`、`gamedata/prices.py`（地基已建好表和导入，本批写查询函数），以及 `gamedata/_ready.py`（首次查询前确保库已建好）。`itemsearch` 的字符索引 / 三元组索引仍在内存里建，只是候选从 `items.candidates()` 来、缓存键改成 `gamedata.version()`。

**Tech Stack:** Python 3.12 标准库 `sqlite3`；测试用 `tests/minipytest`。

**Spec:** `docs/superpowers/specs/2026-11-02-gamedata-design.md`（v3）；调用点矩阵 `docs/superpowers/specs/2026-11-02-gamedata-callsites.md`；地基 API 见 `sc_mining/gamedata/__init__.py` 文档字符串。

## Global Constraints

- 基线分支 `1.1.4-beta.1-database`（含地基）。本批分支 `feat/gamedata-b1-shops`，worktree 放 `E:\Game3\AT_wt\b1`（本机路径只出现在开工说明里，不进文档正文）。PR 目标分支 `1.1.4-beta.1-database`。
- **行为不变是硬指标**：`tools/gamedata_baseline.py --out <新文件>` 跑出来的 JSON 与迁移前基线（`<项目资料>\测试数据\gamedata_baseline_20261102.json`）`results` 段逐字相同（`git`、`data_stamps` 两段允许不同）。任何差异都要么修掉、要么在 PR 里逐条说明并得到负责人批准。
- 不改任何公开函数的签名、返回类型、排序、截断；不改 OCR 纠错 / 模糊匹配算法。
- 只改这几个文件：`sc_mining/crafting/shops.py`、`sc_mining/crafting/itemsearch.py`、`sc_mining/crafting/stockplaces.py`、`sc_mining/update/uex.py`、`sc_mining/update/shops_update`（若 `shops.update` 单独成文件）、`sc_mining/gamedata/items.py`、`sc_mining/gamedata/shops.py`、`sc_mining/gamedata/prices.py`、`sc_mining/gamedata/_ready.py`、`sc_mining/gamedata/__init__.py`（只加导出）、`tests/test_gamedata_b1.py`、`tests/run_all.py`（只加一行）。**不动** `gamedata/_db.py / _build.py / _schema.py / _import.py / _sources.py / _types.py`——要改公共层，停下来单独开 PR。
- 不改 `pyproject.toml`、不刷 `.basedpyright/baseline.json`；新改动 ruff 全过，basedpyright 新文件 0 诊断、全项目总数不高于基线分支。
- 中文注释；不模拟输入；不碰 `userdata/`；测试不读真实 `data/`。
- 每个 Task 一个提交；提交信息 `<type>: <中文一句话>`，不带会话链接；不推送（推送要负责人点头）。
- 旧的读 JSON 代码在本批**删掉**，不留开关、不留双路径。`shops.load()` 本身保留（它是更新流程的一部分，且 `trade/names.py`、`run.py`、`data_pack.py` 还在用——那是批 6 的事），但本批之后 `shops.py` 内部的查询函数一律不再调用 `load()`。
- 更新流程接入：`shops.update()`、`uex.refresh()` 写完 JSON 后必须处在 `gamedata.updating()` 里（最外层调用处套，不是在每个 `write_json` 旁边套）。
- 首次查询时库可能还没建好（后台 `warm_up` 未完成）：topic 函数统一经 `_ready.ensure()` 同步等待一次（最多等 `warm_up` 完成，再不行就自己 `rebuild()`），不向调用方抛 `GamedataUnavailable`；真的建不出库才抛。

## Review Focus

1. **OCR 把 l 认成 I 的物品名**（如 `Sol-lI`）：`shops.find_close` 以前在折叠名（含 `l→i`）上做 difflib，迁移后必须仍在同一套折叠名上比，否则 F8 识别率会掉。→ Task 3 测试 `test_find_close_still_folds_l_to_i`。
2. **同一英文名对应多个 uex id**（如 Lawson Mining Laser 两个 id）：`shops.find` 返回的 id 顺序、`where_by_name` 遍历的 id 顺序要和 JSON 里 `items` 的字典顺序一致。→ Task 3 测试 `test_find_keeps_source_order_for_duplicate_names`。
3. **更新数据正在建库时玩家按 F8**：查询不能读到半截库、也不能卡死。→ Task 6 测试 `test_query_during_rebuild_sees_old_or_new_never_error`。
4. **库存地点在新数据里消失**（商店终端被 UEX 移除）：`stockplaces.match` 以前靠 `_FALLBACK` 兜底，`places()` 的 `lru_cache(maxsize=1)` 以前由 `data_pack.clear_caches` 清——迁移后要改成按 `gamedata.version()` 失效，否则更新后地点列表不刷新。→ Task 4 测试 `test_places_refresh_after_version_change`。
5. **prices.json 里 0 价不盖内置价**（`apply_live` 现有规则）：从库读后必须保留这一条。→ Task 5 测试 `test_apply_live_zero_price_keeps_builtin`。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `sc_mining/gamedata/_ready.py` | `ensure()`：库没好就等后台 `warm_up`，没在跑就同步 `rebuild()`；进程内只做一次 |
| `sc_mining/gamedata/items.py` | 物品目录 topic：`get / all / candidates / by_name / by_source_id / search / search_rows` |
| `sc_mining/gamedata/shops.py` | 商店 topic：`catalog / rows_for_item / buyable / place_fields / find_folded` |
| `sc_mining/gamedata/prices.py` | 矿价 topic：`city_prices()` |
| `sc_mining/crafting/shops.py` | 公开函数签名不变，函数体改走 `gamedata.shops` / `gamedata.items` |
| `sc_mining/crafting/itemsearch.py` | `_build_locked()` 改从 `gamedata.items` 取行，缓存键改 `gamedata.version()`；`wiki_items()` 保留给 `loot`/`gamekey`/`localization` 用（它们是批 4/6 的事） |
| `sc_mining/crafting/stockplaces.py` | `_raw_places()` 改走 `gamedata.shops.place_fields()`；`places()` 缓存按版本失效 |
| `sc_mining/update/uex.py` | `apply_live` 改从 `gamedata.prices` 读；`refresh` 外层套 `updating()` |
| `tests/test_gamedata_b1.py` | 本批全部测试 |

---

### Task 0: 分支、基线复核

- [ ] **Step 1**：`git worktree add <worktree> -b feat/gamedata-b1-shops 1.1.4-beta.1-database`；把主仓库 `data\` 整个目录拷进 worktree（含 `loot/`、`loot_details.zip`，否则 `test_tools` 会挂）。
- [ ] **Step 2**：在 worktree 里跑 `python -X utf8 tools\gamedata_baseline.py --out <项目资料>\测试数据\gamedata_baseline_b1_before.json`，与 `gamedata_baseline_20261102.json` 的 `results` 段 diff，必须为空（证明基线分支本身没漂）。不为空就停，先弄清为什么。
- [ ] **Step 3**：`python -X utf8 tools\build_gamedata.py --check` 正常。记录 `python -X utf8 -m tests.run_all` 的通过数作为基数（基线分支 522）。

---

### Task 1: `_ready.ensure()`

**Interfaces:**
- Produces:
  ```python
  # gamedata/_ready.py
  def ensure(timeout: float = 30.0) -> None
      # 1) read_manifest() 有且 _db_usable → 返回
      # 2) 有 warm_up 线程在跑（__init__ 记录的 _state["warm_thread"]）→ join(timeout)
      # 3) 仍没有 → rebuild()（阻塞）；失败抛 BuildError
      # 进程内用一把锁，防止多个线程同时走到 3)
  ```
- `gamedata/__init__.py`：`warm_up()` 把线程对象存进 `_state["warm_thread"]`；导出 `ensure`。

- [ ] **Step 1 测试**：`test_ensure_builds_when_missing`（空库目录 + 最小源 → `ensure()` 后 `read_manifest()` 非空）；`test_ensure_waits_for_warm_up`（先 `warm_up()`，立刻 `ensure()`，返回时清单已存在且只建了一代）；`test_ensure_raises_when_no_sources`（没有 shops.json → `BuildError`）。
- [ ] **Step 2** 跑 → 红。**Step 3** 实现。**Step 4** 跑 → 绿；ruff + basedpyright。**Step 5** 提交 `feat: 游戏数据层首次查询前的就绪等待`。

---

### Task 2: `gamedata/items.py` 与 `gamedata/shops.py` 与 `gamedata/prices.py`

**Interfaces:**
- Produces（全部返回冻结 dataclass 或 tuple；内部先 `_ready.ensure()` 再 `snapshot()`；都支持传入已有 `Snapshot`）：
  ```python
  # items.py
  @dataclass(frozen=True) class ItemRow(Item):   # 继承 _types.Item，多两列
      zlen: int; source_order: int
  def get(item_id: str, snap=None) -> ItemRow | None
  def all(snap=None) -> tuple[ItemRow, ...]                     # 按 source_order
  def candidates(snap=None) -> tuple[ItemCandidate, ...]        # (item_id, en, aliases=aka 们, source_order)，按 source_order；进程内按 data_version 缓存一份
  def names_of(item_id: str, snap=None) -> tuple[tuple[str, str, str], ...]   # (kind, name, norm)，按 source_order 再 kind
  def zh_keys_of_all(snap=None) -> dict[str, tuple[str, ...]]   # item_id → 该物品所有中文比较键（kind in zh_loc/zh_loot），顺序 = 导入顺序；itemsearch 建索引用
  def by_name(name: str, snap=None) -> ItemRow | None           # en_key(name) 精确命中 items.item_id，其次 item_names.norm（kind='aka'）
  def by_source_id(source: str, external_id: str, snap=None) -> ItemRow | None
  def search(fragment: str, limit: int | None = None, snap=None) -> tuple[ItemRow, ...]   # en 或任一名字 LIKE %fragment%，按 source_order；limit None 不截断

  # shops.py
  @dataclass(frozen=True) class CatalogItem: uex_item_id: int; en: str; cat: str; folded: str; source_order: int
  def catalog(snap=None) -> tuple[CatalogItem, ...]             # shops.json 的 items，按源顺序；folded = shops._fold(en)；进程内按 data_version 缓存
  def rows_for_item(uex_item_id: int, snap=None) -> tuple[ShopRow, ...]     # 按 source_order
  def buyable(uex_item_id: int, snap=None) -> bool                           # exists price_buy > 0
  def place_fields(snap=None) -> tuple[tuple[str, str, str, str, str, str], ...]   # 所有行的 (f0..f5)，按 source_order，**不去重**（stockplaces 自己去重，保持原顺序语义）
  def lagrange_rows(snap=None) -> tuple[ShopRow, ...]            # f2 含 'Lagrange' 且 (f4 or f5) 非空，按 source_order；position._station_at 用

  # prices.py
  def city_prices(snap=None) -> dict[str, dict[str, float]]       # mineral → city → price，按表自然顺序；没有 prices 源时 {}
  def has_live(snap=None) -> bool                                  # mineral_prices 表非空
  ```
- `gamedata/__init__.py` 导出 `items, shops, prices`（作为子模块）。

- [ ] **Step 1 测试**（用地基测试里的 `_write_min_sources` 同款最小数据）：每个函数一条：命中、未命中、顺序、`limit=None`、`by_source_id('uex','201')` 命中同一物品、`candidates()` 的 aliases 含 `Medi Pen`、`place_fields()` 行数 = 3、`city_prices()['Aluminum']['Lorville'] == 3000.0`、`has_live()`。再加一条 `test_topic_calls_share_outer_snapshot`：外层 `snapshot()` 内调两个 topic，中途发布新代，两次结果仍来自旧代。
- [ ] **Step 2** 红 → **Step 3** 实现（SQL 只在这三个文件里；`candidates()`/`catalog()` 的进程内缓存用 `dict[data_version] -> tuple`，只保留当前一个版本）。→ **Step 4** 绿 + lint。→ **Step 5** 提交 `feat: 游戏数据层 items / shops / prices 三个查询主题`。

---

### Task 3: `crafting/shops.py` 改走数据层

**Files:** Modify `sc_mining/crafting/shops.py`（函数：`_folded_items`、`find`、`find_close`、`where`、`where_text`、`where_by_name`、`nearest`、`buyable`、`variants`；`load`/`update`/`_place`/`shop_point`/`base_names` 不动）。

**Interfaces:**
- Consumes：Task 2 的 `gamedata.shops.catalog / rows_for_item / buyable`、`gamedata.items`（不需要）。
- 保持：所有公开函数签名与返回形状完全不变（`find → [(id, en, cat)]`，`where → (buy, sell)` 各为 `(价, 店, 地)` 列表，`nearest → [(距离, 价, 店, 地)]`）。

- [ ] **Step 1 测试**（`tests/test_gamedata_b1.py`，用最小源建库后调 `crafting.shops` 的函数）：
  - `test_find_exact_before_partial_and_limit`：`find("Lawson")` → 两个 id（200、201）顺序如源；`find("arms", limit=1)` 长度 1。
  - `test_find_keeps_source_order_for_duplicate_names`（Review Focus 2）。
  - `test_find_close_still_folds_l_to_i`（Review Focus 1）：`find_close("Lawson Mining Iaser")` 命中 200。
  - `test_where_sorts_buy_asc_sell_desc`、`test_nearest_dedups_place`（用 `monkeypatch` 把 `navigation.position.distance` 换成按 f5 排序的假函数）、`test_buyable`、`test_variants_prefers_buyable`、`test_where_by_name_first_buyable`。
  - `test_shops_query_functions_do_not_call_load`：`monkeypatch.setattr(shops, "load", 抛 AssertionError)`，跑完上面全部查询函数不报错。
- [ ] **Step 2** 红。**Step 3** 实现：`_folded_items()` 改为 `gamedata.shops.catalog()` 映射成同样的 `(id, en, cat, folded)` 元组列表（保留此函数名，`acquire` 没用它但保留以防）；`where` 用 `rows_for_item`；`buyable` 用 `gamedata.shops.buyable`；`nearest`/`variants`/`where_by_name` 改用 catalog + rows_for_item，循环结构照旧。删掉 `_folded` 全局和 `_data` 在查询路径上的使用（`load()` 仍维护 `_data` 给更新流程）。
- [ ] **Step 4** 绿 + lint。**Step 5** 提交 `refactor: 商店查询改走游戏数据层，删掉查询路径上的 JSON 读取`。

---

### Task 4: `crafting/stockplaces.py` 与 `navigation/position._station_at`

- [ ] **Step 1 测试**：`test_raw_places_from_gamedata`（最小源 3 行同一地点 → 1 个地点）；`test_places_refresh_after_version_change`（Review Focus 4：改 shops.json 加一行新地点、`rebuild()`、`places()` 里出现新地点，不需要 `clear_caches`）；`test_station_at_uses_lagrange_rows`（给一行 f2=`Lagrange Point 1`、f4=`Station X`，`monkeypatch` `shops.shop_point` 返回 `{"i": "ARC_L1"}` → `_station_at("ARC_L1") == "Station X"`）。
- [ ] **Step 2** 红。**Step 3** 实现：`_raw_places()` 遍历 `gamedata.shops.place_fields()`，其余逻辑原样；`places()` 去掉 `lru_cache(maxsize=1)`，改为模块级 `{"ver": None, "list": None}` 按 `gamedata.version()` 失效（`_index()` 同理）；`data_pack.clear_caches` 里 `_clear("crafting.stockplaces", "places", "_index")` 这一行**保留**（它对没有 `cache_clear` 的函数静默跳过，不用改 data_pack）。`position._station_at` 改用 `gamedata.shops.lagrange_rows()`。
- [ ] **Step 4** 绿 + lint。**Step 5** 提交 `refactor: 库存地点和拉格朗日站名改走游戏数据层`。

---

### Task 5: `update/uex.apply_live` 与更新流程接入

- [ ] **Step 1 测试**：`test_apply_live_reads_gamedata`（最小源 → 假 data 模块 `CITY_PRICES={"Aluminum":{"Area18":1,"Lorville":2}}`，`apply_live` 后 Area18=3800、Lorville=3000）；`test_apply_live_zero_price_keeps_builtin`（Review Focus 5）；`test_apply_live_false_when_no_prices_table`；`test_refresh_runs_inside_updating`（`monkeypatch` `_get` 返回空、`write_json` 记录调用、`gamedata.updating` 换成计数器 → 计数 1）；`test_shops_update_runs_inside_updating` 同理。
- [ ] **Step 2** 红。**Step 3** 实现：`apply_live` 用 `gamedata.prices.city_prices()`，`yields` 这部分——地基没有 `refinery_yields` 表，**本批保留从 `prices.json` 读 `yields`**，并在函数注释写明“yields 等 mining 批次（批 5）建表后迁”；`refresh()` 和 `shops.update()` 的函数体最外层套 `with gamedata.updating():`。
- [ ] **Step 4** 绿 + lint。**Step 5** 提交 `refactor: 矿价改走游戏数据层，UEX 刷新和商店更新接入更新边界`。

---

### Task 6: `crafting/itemsearch.py` 改从数据层建索引

**Files:** Modify `_build_locked()`、`_cache` 键；`find`/`lookup`/`_rank_*`/`warm_up`/`wiki_items` 不动。

- [ ] **Step 1 测试**：
  - `test_itemsearch_find_matches_json_build_on_sample`：在最小源上，先用“旧实现”（把 `_build_locked` 的旧函数体复制到测试文件里命名 `_legacy_build`，只在测试里存在）建索引，再用新实现建，`find()` 对 `["医疗笔", "Medpen", "Lawson", "荣誉勋章", "xyz"]` 的输出逐字相同。
  - `test_itemsearch_cache_keyed_by_version`：建索引后 `rebuild(force=True)`（版本不变）不重建；改源后重建。
  - `test_query_during_rebuild_sees_old_or_new_never_error`（Review Focus 3）：一个线程循环 `find("Medpen")` 200 次，主线程同时 `rebuild(force=True)` 两次；断言没有异常、每次结果非空。
  - `test_itemsearch_does_not_read_json`：`monkeypatch` `paths.DATA` 指向只有 `gamedata/` 的空目录（库已建好），`_build()` 成功。
- [ ] **Step 2** 红。**Step 3** 实现：`_build_locked()` 开 `gamedata.snapshot()`，`rows = items.all(snap)`，`zks` 用 `items.zh_keys_of_all(snap)`，`aka` 用 `names_of`（kind='aka'），`by_en` 用 `item_id` 和 aka 的 norm；`has_data = has_shop or has_loot`；`e["shop"]` 用 `shops.catalog()` 里该物品 en 折叠后首个匹配的 uex id（或 `items.by_source_id` 反查——选前者，与源顺序一致）；`by_char`/`by_tri` 建法不变。缓存键 `(snap.data_version,)`。删掉对 `shops.load / loot.load_index / names.table / wiki_items / name_aliases.json` 的读取。
- [ ] **Step 4** 绿 + lint。**Step 5** 提交 `refactor: 物品搜索索引改从游戏数据层建，缓存按内容版本失效`。

---

### Task 7: 行为基线比对、性能、全量

- [ ] **Step 1**：`python -X utf8 tools\gamedata_baseline.py --out <项目资料>\测试数据\gamedata_baseline_b1_after.json`，与 `gamedata_baseline_20261102.json` 的 `results` 段 diff（用 `python -c` 载入两份 JSON 比较 `results`）。**必须为空**；有差异逐条分析，确属原代码缺陷（如 itemsearch 缓存键漏文件导致的）才记入 PR“允许差异”。
- [ ] **Step 2**：跑地基留下的性能脚本（`<AT_server>\tmp\perf_baseline.py`，把 worktree 路径改成本批的），记录 `itemsearch._build` 首次耗时 / 峰值内存、热查询耗时；与 `gamedata_baseline_20261102.md` 对照写进 `<项目资料>\测试数据\gamedata_b1_perf.md`。目标：首次建索引耗时和峰值内存都下降；不降就先定位再合。
- [ ] **Step 3**：`set AT_FEEDBACK_OFF=1 && python -X utf8 -m tests.run_all` 全绿（基数 522 + 本批新增）；ruff；basedpyright 不高于基数。
- [ ] **Step 4**：实机：启动 AT → 物品查询搜「视差步枪」「Medpen」→ 结果和顺序与基线分支一致；F8 一次；「更新数据」一次后再搜；库存页地点列表正常。

---

### Task 8: 审查与交付

- [ ] 新上下文 subagent 读 `REVIEW.md` 后审完整 diff（`git diff 1.1.4-beta.1-database...feat/gamedata-b1-shops`）；重点：行为等价、`load()` 是否仍被查询路径调用、缓存失效、锁顺序（`updating()` 在最外层、`BUILD_LOCK` 在内）。
- [ ] 修完复跑 Task 7。写 PR 说明（Testing / Risk / How to revert）放 `<项目资料>\记录\PR_gamedata_b1.md`，Risk 里写明“允许差异”清单（若有）。
- [ ] 停下等负责人实机验收并签字；不推送。
