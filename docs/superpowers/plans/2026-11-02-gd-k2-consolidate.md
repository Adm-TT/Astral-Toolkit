# 游戏数据层 收口 2（GD-K2：批 1–6 合并后的整合清理）

| 日期 | 变更 | 原因 |
|---|---|---|
| 2026-11-02 | 初稿 | 批 1–6 与收口 1 已合入基线；各批故意留给「整合清理」的死代码 / 空操作 / 空门面集中扫掉，避免架构 D 或发版前继续被复制 |

## 合同摘要（已定案）

| 项 | 决定 |
|---|---|
| 边界 | 只做整合清理：删死代码、空操作、空 `cache_clear` 门面；**不**重写 `clear_caches` 合同；**不**回收架构 EX-01/02/03；**不**做 bootstrap / runtime |
| 验收 | 对外行为不变；测试锁死「`rebuild` 后不调 `clear_caches`，已迁查询已换代」 |
| 时机 | 现在做（批 1–6 已齐），先于架构 D / 发版清场 |
| 清单 | **封闭**：见下方删除清单；清单外不开口，另开 follow-up |
| 文档 | 仅本 plan；不另开 specs |
| 归属 | **控制台单会话**改 `update/data_pack.py` 及清单内文件；禁止并行会话再碰 `data_pack.py` |
| 风险 | **高风险**：非作者审代码 + 负责人实机（更新 / 装包后抽查商店、掉落、采矿、制造各一条查询） |
| 验证 | `ruff check` + `ruff format --check`；全项目 `basedpyright`（跑完还原 baseline）；`AT_FEEDBACK_OFF=1` + `tests.run_all`。**不**把门禁绑在将删的 `gamedata_baseline_*.py` 分册上 |

**Goal:** 把批 2–6 留下的「等整合清理再删」的脚手架一次拆掉；`clear_caches` 只删死枝、保留仍有真实读者的活枝；已迁链路的换代靠库版本 / `VersionCache`，不靠清缓存钩子。对外行为不变。

**Architecture:** 不引入新缓存机制。删除无人读的模块级空壳与对已无 `cache_clear` 的 `_clear` 调用；拆掉 `trade/names` 上仅为兼容按名调用而挂的空 `cache_clear`；收掉 `navigate.mining_spots()` 缓存键里与 `rocks_stamp()` 重复的一项；删除各批迁移专用基线分册。`clear_caches` 仍负责旁路 JSON、内置表热更新、`gamedata.refresh` 与 `CACHE_HOOKS`。

**Tech Stack:** Python 3.12；现有 `tests/minipytest` / `tests.run_all`。

## 非目标（本 PR 不做）

- 改 `shops.load` / `loot.load_index` / `itemsearch.wiki_items` 不再读 JSON
- 掉落明细入库、多文件更新批次恢复
- 架构 EX-01（库不可用吞成空）、EX-02（首查同步 `ensure`）、EX-03（功能直连 topic）；bootstrap / runtime / ResultStore
- 设计稿移出的「第七个清理 PR」（注释 / 字符串 / 本机路径字样大扫除）
- 改口行为或允许差异清单
- 把 `clear_caches` 重写成全新合同（只删死枝 + 写保留理由表）

## 封闭删除清单

| # | 项 | 依据 |
|---|---|---|
| 1 | 删 `crafting/loot.py` 的 `_folded` 空壳；删 `data_pack.clear_caches` 里 `loot._folded.update(...)` | 批 4 计划 / 矩阵：无人读，只给 clear_caches 写 |
| 2 | 删 `mining/mining_area.py` 的 `_ROCKS`；改 `tests/test_mining.py` 里对它的 `clear` | 批 5：业务不用，仅测试在清 |
| 3 | 删 `clear_caches` 里已成空操作的 `_clear`：至少 `_clear("mining.shipsig", "ships")`；以及能确认已无 `cache_clear`、无副作用的同类（如对已迁且无门面的 `crafting.data` / `wikelo.load` / `itemstats.data`——**逐项确认后再删，不确定的保留并记入保留表**） | 批 5 矩阵；其它同类同理 |
| 4 | 拆 `trade/names` 空 `cache_clear` 门面（`_Cached` / `_with_clear`）：先改掉 `update/localization.py`、`data_pack.clear_caches`、`tests/test_trade.py`、`tests/test_goals.py`、`tests/test_gamedata_b6.py` 的按名调用，再删门面 | 批 6 PR「需要控制台改」 |
| 5 | 收 `navigation/navigate.py` 的 `mining_spots()` 缓存键：去掉与 `rocks_stamp()` 重复的那一项（`rocks_stamp()` 已是 `gamedata.version()`） | 批 5 矩阵 / 计划 |
| 6 | 删除 `tools/gamedata_baseline_nav.py`、`_craft.py`、`_loot.py`、`_mining.py`、`_names.py`（及若仅被它们引用的注册）；**不**并进总入口 | 批 6 工具头注释；定案直接删 |

清单外发现「好像也能清」的，开 follow-up，不塞进本 PR。

## `clear_caches` 保留理由表（收口后仍必须留下）

| 保留分支 | 理由 |
|---|---|
| `gamedata.refresh()` | 关掉本线程旧连接，下次查询重读清单 |
| `CACHE_HOOKS` | goals / navigation 等仍登记清理回调 |
| `paths.clear_json_cache()` | 仍有 JSON 旁路与 `cached_json` 读者 |
| `loot._index = None` | `load_index` / about 等仍读 `loot_index.json` |
| `shops._data = None` | `shops.load` / acquire 等仍读 `shops.json` |
| `uex.apply_live(data)` | 矿价 / 精炼站加成写回内置表 |
| 仍带真实 `cache_clear` 的 `_clear`（如 `crafting.goals.where_to_get`、`mining.laser.*`、`stockplaces` 若仍挂清法） | 未迁或仍靠按名清理；收口时核对后写入本表定稿行 |

已迁且仅靠 `VersionCache` 的路径：`rebuild` 后不调 `clear_caches` 也必须换新——用测试锁死（可复用 / 加强各批已有 `*_refreshes_after_rebuild_without_clear_caches`）。

## Global Constraints

- 基线分支：`1.1.4-beta.1-database`（含批 5 merge）。本批分支：`chore/gd-k2-consolidate`。
- 只改删除清单与保留表涉及的文件，外加本 plan、`tests/test_gd_k2.py`（新）、`tests/run_all.py` 注册行。动 `gamedata/_*.py` 公共层前停下来重新评估（本批默认**不动**公共层）。
- 行为不变：玩家可见查询、更新、装包后热更新路径与收口前一致。
- 每 Task 一提交；新上下文按 `REVIEW.md` 审 diff；验证命令全绿；不推送，等负责人实机验收后由控制台合并。

## Tasks

### Task 1: 掉落空壳 + shipsig 空 `_clear` + `_ROCKS`
- [ ] 删 `loot._folded` 与 `clear_caches` 中对应 `update`；保留 `loot._index = None`。
- [ ] 删 `_clear("mining.shipsig", "ships")`；逐项核对其它空 `_clear`，能确认的删、不能确认的列入保留表。
- [ ] 删 `mining_area._ROCKS`；改 `tests/test_mining.py`。
- [ ] 测试：`test_clear_caches_still_safe` 类用例不再断言 `_folded`；`rebuild` 后不调 `clear_caches` 掉落 / 飞船信号仍换代（已有则保留，缺则补）。

### Task 2: `names.cache_clear` 门面
- [ ] 去掉 localization / data_pack / 相关测试对 `names.table.cache_clear` / `names._index.cache_clear` 的依赖（换代靠库版本即可处改为不调用或只测 `rebuild`）。
- [ ] 删 `_Cached` / `_with_clear`（或等价空门面）。
- [ ] 测试：`test_table_refreshes_after_rebuild_*` 仍绿；按名 `cache_clear` 不再作为合同。

### Task 3: `mining_spots` 缓存键
- [ ] `navigate.mining_spots()` 缓存键去掉与 `rocks_stamp()` 重复项；行为与失效时机与收口前一致（任一游戏数据更新仍使结果重算）。
- [ ] 相关导航 / 采矿测试绿。

### Task 4: 删除批专用基线工具
- [ ] 删 `tools/gamedata_baseline_{nav,craft,loot,mining,names}.py`；清理对它们的引用（若有）。
- [ ] 确认 `tests.run_all` / 文档无断链；总门禁不依赖这些分册。

### Task 5: 收口测试与交付
- [ ] 新增 `tests/test_gd_k2.py`（或分散加强）：覆盖「保留分支仍存在且可调用」「已迁路径 rebuild 无需 clear_caches」「`_folded` / `_ROCKS` 已不存在」。
- [ ] `run_all` 注册；全量 ruff / basedpyright / `tests.run_all`；新上下文审查；PR 说明含 Testing / Risk / How to revert，Risk 写明高风险与实机抽查项；停下等负责人验收，不推送。
