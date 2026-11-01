# 游戏数据层 批 3 调用点矩阵（crafting / wikelo / itemstats，含 goals / acquire / laser / hover 的相关读取）

日期：2026-11-02　基准：`1.1.4-beta.1-database`（schema 3）　状态：公共层先行 PR（schema 4，已实现）的依据；批 3 开工前逐行复核“调用模块”列

> **schema 4 实现时按真实数据修正（2026-11-02）**：① `blueprints.u` 真实数据有重复和空值，**不作主键**，用自增 `id`，`bp_key` 唯一索引；② `slots[i][2]`（改装列表）随 `slots_json` 整段存，不拆表；③ `item_stats.s` 的形状不只 `{min,max}` / 数值，还有多种嵌套键 → **整段存 `stats_json`**，不建 `item_stat_values`，`itemstats._get` 读时按路径取；④ `wikelo_requirements` 多 `norm_z`（`_fold(z)`），`wikelo_contract_systems` 建了；⑤ `dismantle_efficiency / dismantle_blacklist / crafting_version / wikelo_version / item_stats_version` 进 `meta`；⑥ `print_spots.cls` 来自源的 `class`。表定义以 `sc_mining/gamedata/_schema.py` 为准。

## 0. 使用方式概览（决定表怎么建）

| 模块 | 怎么用数据 | 迁移方式 |
|---|---|---|
| `crafting.data()` / `blueprints()` | 返回整个 dict（`{"blueprints": [bp…]}`），**bp 是嵌套 dict**（`slots` 三层列表、`src` 列表），被 `tasks/goals`、`hover`、`stock`、`trade`、`laser`、`inspector`、`acquire` 当 dict 传来传去；`_keys()` 用 `id(bp)` 做编号表 | 保留 `data()` 的 dict 形状：从库组装、按 `gamedata.version()` 缓存**一份**（同版本内 bp 对象身份稳定，`_keys` 才能工作）；`slots` / `src` 存 JSON 列（同电梯：消费方吃嵌套树） |
| `for_item / search / by_key` | 遍历全部 1618 份按折叠名比 | `blueprints.norm_n`、`norm_z` 列走索引；`by_key` 的「名字#序号」规则在导入时算好存 `bp_key` 列 |
| `needs / uses / mat_summary / uses_report` | 遍历所有 bp 的所有槽找某种矿 | 平铺表 `blueprint_materials(blueprint_u, slot_idx, slot_name, kind, material, qty, min_q)`，按 `material` 索引 |
| `wikelo.load()`（`lru_cache(maxsize=1)`） | 71 份合同整表，`uses(name)` 遍历 `req`，`search` 遍历 | `wikelo_contracts` + `wikelo_requirements` + `wikelo_rewards` 三表；`load()` 保留 dict 形状按版本缓存 |
| `wikelo.print_spots(name)` | `print_spots.json` 的 `items[name]` | `print_spots` + `print_spot_places` |
| `itemstats.data()`（`lru_cache(maxsize=1)`） | 按 uuid 取一条（`item(uuid)`），字段里 `s` 是属性字典 | `item_stats(uuid PK, …)` + `item_stat_values(uuid, stat, min, max, value)`；`item(uuid)` 单条查询，不再整表常驻（1.1 MB） |
| `acquire` 读 `ship_items.json` | `items[部件名]` → 船列表 | `ship_stock_items(item_name, ship, idx)` |

## 1. crafting.json（1.0 MB）

结构：`{version, dismantle_efficiency, dismantle_blacklist[], blueprints: [bp] ×1618, names}`；`bp = {n, z, g, t, s, u, m, sec, d, slots: [[槽名, [[kind, 材料, 数量, 最低品质]…], [改装…]]…], src: [[任务名, 阵营, 职业, 备注, 概率]…], nsrc}`。

| 源字段 | 读它的函数 | 转换 | 目标表.列 | 顺序 |
|---|---|---|---|---|
| `bp.n / z / g / t / s / u / m / sec / d / nsrc` | 全部消费方 | 原样 | `blueprints(u PK, n, z, g, t, s, m, sec, d, nsrc, norm_n, norm_z, bp_key, item_id, slots_json, src_json, source_order)` | 列表顺序 |
| `bp.slots` | `needs`、`craft_slots`、`solve_slots`、`laser_total`、`stats`、`header`、`craft_text` | 嵌套原样 → `slots_json`；另平铺一份供筛选 | `blueprint_materials(blueprint_u, slot_idx, slot_name, kind, material, qty REAL, min_q INTEGER, opt_idx)`；索引 `(material)` | 槽顺序、选项顺序 |
| `bp.src` | `header`、`acquire`（任务来源） | 嵌套原样 | `src_json` | — |
| 派生 `bp_key` | `crafting._keys()` L340-362：名字唯一 → 名字；重名 → `名字#序号`（按出现顺序 1、2…） | 导入时算 | `blueprints.bp_key`（唯一索引） | — |
| 派生 `norm_n / norm_z` | `for_item` 的 `fold`（`re.sub(r"[\W_]+", "", s.lower())`）、`search` 的 `lower().replace(" ", "")`——**两个函数规范化规则不同**，各存各的：`norm_n/norm_z`（for_item 规则）、`search_n/search_z`（search 规则） | 导入时算 | 四列，索引 `(norm_n)`、`(norm_z)` | — |
| 派生 `item_id` | 批 1 的物品身份：`itemsearch.en_key(bp.n)` 若在 `items` 表里 | 导入时算，可空 | `blueprints.item_id` | — |
| `dismantle_efficiency / dismantle_blacklist` | 待核对读者（grep `dismantle`） | — | `meta` 两键 | — |
| `version` | `itemstats.version()` 比对？待核对 | — | `meta: crafting_version` | — |
| `names` | 没人读；含本机路径 | **不入库** | — | — |

`data()` 现有的容错（L294-311：文件没有 / 坏了 → `{"blueprints": []}` 并记一次警告）保留为“库里 `blueprints` 空 → 同样返回空列表”。

## 2. wikelo.json（40 KB）

结构：`{version, contracts: [{id, type, t, te, rz, rewards[], req: [{n, z, q, u}], systems[]}] ×71}`。

| 源字段 | 读者 | 目标表.列 |
|---|---|---|
| `id, type, t, te, rz` | `wikelo.describe / search / uses_text` | `wikelo_contracts(id PK, type, t, te, rz, source_order)` |
| `rewards[]` | `describe` | `wikelo_rewards(contract_id, idx, item)` |
| `req[]`（n, z, q, u） | `uses`（按 `_same(_fold(n))` 比）、`req_label`、`console.material_source`、`test_tools.test_wikelo_materials_all_have_source` | `wikelo_requirements(contract_id, idx, n, z, q REAL, u, norm_n, norm_z)`；索引 `(norm_n)` |
| `systems[]` | 待核对 | `wikelo_contract_systems(contract_id, system)` |
| `version` | 待核对 | `meta: wikelo_version` |

## 3. item_stats.json（1.1 MB）

结构：`{version, fetched, items: {uuid: {n, size, grade, cls, type, sub, mass, ver, mfr, cn, s: {属性: {min, max} 或 数值}}} ×1612}`。

| 源字段 | 读者 | 目标表.列 |
|---|---|---|
| `items[uuid]` 标量字段 | `itemstats.item(uuid)` → `crafting.stats/header`（按 `bp["u"]`） | `item_stats(uuid PK, n, size, grade, cls, type, sub, mass REAL, ver, mfr, cn, source_order)` |
| `items[uuid].s` | `itemstats._get(d, *path)` 按属性键取 `min/max` 或数值 | `item_stat_values(uuid, stat, min REAL, max REAL, value REAL)`；读时拼回 `{stat: {min,max}}` / `{stat: value}` 的 dict（`_get` 不改） |
| `version` | `itemstats.version()` | `meta: item_stats_version` |
| `fetched` 等顶层键 | 没人读 | 不入库 |

## 4. print_spots.json、ship_items.json

| 源 | 结构 | 读者 | 目标表 |
|---|---|---|---|
| `print_spots.json` | `{items: {物品名: {zh, class, where[]}}}` | `wikelo.print_spots(name)` L240-253 | `print_spots(item_name PK, zh, cls, source_order)` + `print_spot_places(item_name, idx, place)` |
| `ship_items.json`（130 KB） | `{game, items: {部件名: [船名…]}}` ×574 | `acquire` L159-170 | `ship_stock_items(item_name, idx, ship)`；索引 `(item_name)` |

## 5. 更新流程

- `build_crafting.build()`（重建 `crafting.json`，持 `BUILD_LOCK`）、`wikelo.build()`、`localization.rebuild()`（也重建 `crafting.json`）：最外层套 `gamedata.updating()`，**updating 在外、BUILD_LOCK 在内**。
- `item_stats.json`、`print_spots.json`、`ship_items.json` 随数据包来（已在边界内）。

## 6. 公共层先行 PR 要做的（schema 4）

新表：`blueprints`、`blueprint_materials`、`wikelo_contracts`、`wikelo_rewards`、`wikelo_requirements`、`wikelo_contract_systems`、`item_stats`、`item_stat_values`、`print_spots`、`print_spot_places`、`ship_stock_items`。`SOURCES` 加 5 个可选源。导入：`bp_key` 规则**直接复用** `crafting._keys()` 的算法（抽成纯函数 `crafting.assign_keys(bps) -> dict[id, key]`，和 `_keys` 共用）；`for_item` 的 `fold` 抽成模块级 `_fold_name`；`norm` 规则不抄。

## 7. 批 3 开工前必须补的核对

- `dismantle_*`、`crafting.version`、`wikelo.systems/version` 的读者。
- `goals.py`、`tasks/goals.py` 是否把 `bp` 存进 userdata（存的是 `bp_key` 字符串还是整份 dict）——决定 `by_key` 的兼容要求。
- `solve_slots / parse_mods / craft_slots` 是否修改 `bp` 对象（若就地改，`data()` 的缓存 dict 会被污染——现状也是如此，但要确认）。
- `itemstats` 的 `uuid` 与 `item_source_ids('loot_uuid')` 是否同一套 uuid（若是，`item_stats.uuid` 可直接关联物品）。
