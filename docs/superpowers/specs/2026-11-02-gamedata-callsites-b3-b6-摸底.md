# 游戏数据层 批 3 / 4 / 6 数据摸底（开工前各批补成完整矩阵）

日期：2026-11-02　基准：`1.1.4-beta.1-database`　状态：只到“源结构 + 读者 + 建议表”这一层；字段级转换规则由各批开工时按批 1/批 2 矩阵的格式补齐，公共层据此出 schema 3。

## 批 3：制造 / 维科洛 / 物品属性（crafting / wikelo / itemstats，含 goals、acquire 的相关读取）

| 源 | 结构 | 读者 | 建议表 |
|---|---|---|---|
| `crafting.json`（1.0 MB） | `{version, dismantle_efficiency, dismantle_blacklist[], blueprints: [{n, z, g, t, s, u, m, sec, d, slots: [[槽名, [[品质档, 材料, 数量, …]], […]]]}] ×1618, names}` | `crafting/crafting.py`（L15 `DATA`、L295 读取）、`build_crafting.build` 写、`localization.rebuild` 重建 | `blueprints(u PK, n, z, g, t, s, m, sec, d, source_order)` + `blueprint_slots(blueprint_u, slot_idx, slot_name)` + `blueprint_slot_options(blueprint_u, slot_idx, opt_idx, grade, material, qty, extra)`；`dismantle_blacklist` 进 `meta` 或小表；`names` 字段是一条带本机路径的说明字符串——**不入库**，同时在清理批次里让生成脚本不再写它 |
| `wikelo.json`（40 KB） | `{version, contracts: [{id, type, t, te, rz, rewards[], req: [{n, …}], …8 keys}] ×71}` | `crafting/wikelo.py`（`load` 有 `lru_cache`，`data_pack.clear_caches` 清）、`trade/console.material_source`、`test_tools.test_wikelo_materials_all_have_source` | `wikelo_contracts(id PK, type, t, te, rz, source_order)` + `wikelo_rewards(contract_id, idx, item)` + `wikelo_requirements(contract_id, idx, n, …)` |
| `item_stats.json`（1.1 MB） | `{version, fetched, items: {uuid: {n, size, grade, cls, type, sub, mass, ver, mfr, cn, s: {属性: {min,max} 或数值}}} ×1612}` | `crafting/itemstats.py`（`data()` 有 `lru_cache`） | `item_stats(uuid PK, n, size, grade, cls, type, sub, mass, mfr, cn, source_order)` + `item_stat_values(uuid, stat, min, max, value)`；`uuid` 应与 `item_source_ids('loot_uuid')` 对得上——批 3 核对 |
| `print_spots.json` | `{items: {物品名: {zh, class, where[]}}}` | `crafting/wikelo.py` L241-250 | `print_spots(item_name PK, zh, cls)` + `print_spot_places(item_name, idx, where)` |
| `ship_items.json`（130 KB） | `{game, items: {部件名: [船名…]}} ×574` | `crafting/acquire.py` L159-170（“自带这个部件出厂的船”） | `ship_stock_items(item_name, ship, idx)` |

依赖：批 3 的 `blueprints.n` / `item_stats.n` 都要对到批 1 定的 `items.item_id`（`en_key`）——批 1 合并后再定映射列。

## 批 4：掉落（loot）

| 源 | 结构 | 读者 | 建议表 |
|---|---|---|---|
| `loot_index.json` | 已在 schema 1 入库为 `loot_rows` | `crafting/loot.py` 的 `load_index / _folded_rows / find / _wiki_classes`、`gamekey._index`（按类名取 uuid） | 已有表够用；批 4 补 `loot_rows.norm_en` 列（`loot._fold`）供 `find` 走索引 |
| `loot_details.zip` + `data/loot/*.json` | 每个 uuid 一份明细 JSON（在线抓取 / 数据包捆绑） | `loot.detail(uuid, online)`、`_from_zip`、`crawl_details`、`loot.update` | **不入库**（几千个文件、按需读一份、还会在线补抓）；只把“本地有哪些 uuid 的明细”做成 `loot_detail_index(uuid, source, mtime)` 方便 `summary/info` 判断有无 |
| `instance_ore` / `ship_mineral` 常量表 | 代码内常量 | `loot.py` L363-400 | 不动 |

## 批 6：名字与中英对照（names / i18n）

| 源 | 结构 | 读者 | 建议表 |
|---|---|---|---|
| `zh_names.json` + `zh_only_names.json` | `{中文: 英文}` | `trade/names.table()`（`_junk` 过滤 + `_known_names` 依赖 shops/loot）、`names.to_english`、`core/i18n` | 已在 schema 1 以 `item_names(kind='zh_loc')` 入库；批 6 让 `names.table()` 直接从 `item_names` 组装，`_known_names` 用 `items.has_shop/has_loot`，删掉对 `shops.load / loot.load_index` 的依赖 |
| `name_aliases.json` | `{旧写法: 正名}` | `itemsearch`（批 1 已迁）、`gamekey._index` | 已入库 `item_names(kind='aka')`；批 6 让 `gamekey` 用 `items.by_name / by_source_id('class')`，删 `wiki_items()` 读取 |
| `sc_glossary.json`、`names_zh.json`（随程序带，在 `sc_mining/` 里） | 固定对照 | `core/i18n` | **不入库**（随代码走的常量） |
| 用户汉化包 `global.ini`（`localization.read_ini`） | 用户数据 | `position.place_name`、`localization.rebuild` | 不入库 |

## 对清理批次的补充发现
- `crafting.json.names` 是一条含本机游戏安装路径的字符串（`game:D:\…\global.ini|…`）；`item_stats.json`、`crafting.json`、`starmap.json`、`wiki_items.json` 顶层都有来源元数据键。下一版数据包生成时去掉这些键（本机路径不该出现在发给玩家的文件里）；读取方先兼容缺键。

## 顺序建议
批 1 与清理批次都合并后，再开批 2/3/4/6——清理会改 `build_crafting / crafting / wikelo / itemstats / mining_area / loot` 的文档字符串，先合它，后面的批次就不会跟它冲突。
