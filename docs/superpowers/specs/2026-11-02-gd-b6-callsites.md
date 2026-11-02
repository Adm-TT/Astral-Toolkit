# 游戏数据层 批 6 调用点矩阵（names / i18n / gamekey：名字与中英对照）

日期：2026-11-02　基准分支：`1.1.4-beta.1-database`（schema 3，含批 1）　状态：**草稿**——公共层先行 PR 的依据；批 6 开工前逐行复核“调用模块”列

读法同批 1 / 批 2 矩阵。本批涉及 4 份源（`zh_names.json`、`zh_only_names.json`、`name_aliases.json`、`wiki_items.json`）外加已入库的 `loot_index.json`（`loot_rows`）；消费方式是“整表装进内存 dict，再按规范化键精确找 / 包含关系模糊找”，几乎没有按条件筛选，所以表只求**原样、有序**，不求索引。

**结论先行**：摸底和设计文档设想的“`names.table()` 直接从 `item_names(kind='zh_loc')` 组装”“`gamekey` 改用 `items.by_name / by_source_id('class')`”两条路**都不等价**（证据见 §6），批 6 需要公共层先加 3 张原样表（§8）。`core/i18n.py` 不读 `data/`，本批不改；`itemsearch.wiki_items()` 还有两个批 6 以外的读者，本批不删。

## 0. 使用方式概览（决定表怎么建）

| 模块 | 怎么用数据 | 迁移方式 |
|---|---|---|
| `trade/names.table()` | 读 `zh_names.json` + `zh_only_names.json`，用 `_junk(en, _known_names())` 过滤，返回 `{中文: 英文}` dict（`lru_cache(maxsize=1)`） | 公共层把 `_import._names_table(sources)` 的结果**原样按顺序**存进新表 `zh_name_pairs`；`table()` 从 `gamedata.names.zh_pairs()` 组装同一个 dict，按库版本缓存；删掉 `_known_names()`（连带删掉对 `shops.load / loot.load_index` 的依赖） |
| `trade/names._index()` | 在 `table()` 上建 `{_norm_zh(zh): (zh, en)}`、`{_fold_en(en): (zh, en)}` 两个 dict（`setdefault`，首个胜出） | 算法不动；缓存改成跟着 `table()` 那份对象走（`VersionCache(identity=True)`，同批 1 `stockplaces._index`） |
| `to_english / canonical / zh_for / suggest` | 只消费 `table()` / `_index()` | 不改 |
| `has_chinese / split_bilingual / _fold_en / _norm_zh / _junk / _CODE` | 纯函数，不读数据 | 不改；对照表的组装规则只在 `gamedata/_import._names_table` 一处，`trade/names` 不再有第二份；**`_junk / _norm_zh / _fold_en / _CODE` 被 `_import` 复用，改了要升 `_build.IMPORTER_VERSION`** |
| `trade/gamekey._index / resolve` | `wiki_items()`（`cached_json`）+ 直接读 `loot_index.json`、`name_aliases.json` 建三个 dict | 公共层新表 `wiki_items` / `wiki_alt_classes` / `name_alias_pairs`（原样）+ 已有 `loot_rows`；`gamekey` 从 `gamedata.names` 取四份有序行，**在自己模块里**按原 `setdefault / 赋值` 语义建 dict，按库版本缓存 |
| `core/i18n` | 只读包内随程序带的 `sc_glossary.json`（`GLOSSARY` 常量，三个 `lru_cache`） | **不迁、不改**（§4） |
| `crafting/itemsearch.wiki_items()` | `cached_json(wiki_items.json)` | **本批不删**：`crafting/loot._wiki_classes`（批 4）和 `update/localization.wiki_class_names`（更新流程）还在用（§5）。**收口 2（GD-K7）已删**：两处都改读 `gamedata.names.wiki_classes()` |

## 1. zh_names.json + zh_only_names.json → `names.table()`

结构：两份都是 `{中文: 英文}`。`zh_names.json` 由 `localization.rebuild()` 从用户汉化包生成（7.4k 条），`zh_only_names.json` 随数据包来（汉化包只有中文名的物品：勋章、计算板…）。

`table()` 的规则逐条列出，**每条对一个批 6 测试**（测试都在 `tests/test_gamedata_b6.py`，最小源上与“旧实现”`_legacy_table(data_dir)` 逐条比对；旧实现是把现在 `table()` + `_known_names()` 的函数体原样复制进测试文件，只在测试里存在）：

| # | 规则（`trade/names.py` 行号） | 现状行为 | 迁后怎么保证 | 测试 |
|---|---|---|---|---|
| R1 | `zh_names.json` 读不到 / JSON 坏（L20-23） | 直接返回 `{}`，**不再看 `zh_only_names`** | `_import._names_table` 已一致（地基 `test_names_table_without_zh_names_is_empty`）；表为空 → `table()` 为 `{}` | `test_table_empty_when_zh_names_missing_even_with_zh_only` |
| R2 | `zh_only_names.json` 读不到 / JSON 坏（L26-33 `except (OSError, ValueError)`） | 只用 `zh_names` 的结果 | `_d(..., {})` → 跳过 | `test_table_zh_only_broken_keeps_zh_names` |
| R3 | `zh_names` 每条过 `_junk(en, known)`（L25） | 假英文名（`视差步枪→HD`、`…S1`、`XII-IR`、`12 SCU`）去掉 | 导入时同一函数过滤 | `test_table_drops_code_like_english` |
| R4 | `_junk` 第一句：`_fold_en(en) in known` → **不算假**（L44-45） | 商店 / 掉落里真有这个英文名就留（`锡→Tin`） | `_import._known_en` 从同一批源算 | `test_table_keeps_short_name_known_in_shop` |
| R5 | `known` 来自商店 `items` 的 `v[0]` 和掉落 `rows` 的 **`r[1]` 原值**（L49-69），不做中英对调 | 掉落里有一行英文位是中文（`夹克 - 名称`）→ `known` 里混进空串 `""` → 所有 `_fold_en(en) == ""`（纯中文 / 纯符号英文）的条目**都不算假、照留** | `_known_en` 同样取 `r[1]` 原值；保持这个怪行为，不借迁移修 | `test_table_known_includes_raw_loot_en_quirk` |
| R6 | `zh_only_names` 每条也过 `_junk`，且 `len(_norm_zh(zh)) >= 3`（L30） | `章→Badge` 这种短中文不收 | 同一函数 | `test_table_zh_only_needs_three_chars` |
| R7 | `zh_only_names` 用 `setdefault`（L31） | 同一中文在 `zh_names` 已有 → **`zh_names` 胜出**，不覆盖 | 导入同样 `setdefault`；表里只有最终胜出的一行 | `test_table_zh_names_wins_over_zh_only` |
| R8 | 返回 dict 的**插入顺序** = `zh_names` 过滤后顺序，再接 `zh_only` 新增的 | 顺序影响 `to_english` 模糊命中次序、`_index` 首个胜出、`suggest` 同分次序、`tasks/trade._zh_of` 反查（后者**后写覆盖**） | 新表 `source_order` = 导入时 dict 的枚举序号；读时 `ORDER BY source_order` | `test_table_equals_legacy_on_edge_sample`（`list(table().items()) == list(_legacy_table().items())`，Review Focus 1） |
| R9 | 值是**源文件里的英文原文**（不规范化、不去 `\xa0`） | `to_english` 返回原文拼写 | 新表 `en` 原样存 | `test_to_english_returns_source_spelling_not_item_en`（Review Focus 3） |
| R10 | 失效：`lru_cache(maxsize=1)`，只靠 `localization._write_name_files` 和 `data_pack.clear_caches` 按名字清 | 只更新 `shops.json` / `loot_index.json`（`known` 变了）时 `table()` 不刷新——**现状缺陷** | 按库 `data_version` 失效；`cache_clear` 属性保留 | `test_table_refreshes_after_rebuild_and_cache_clear_kept`（Review Focus 4）；缺陷修复列为允许差异 |
| R11 | 读不到库（没有 `shops.json` 建不出库） | 现状：`zh_names` 在就照常返回（`known` 少了商店那部分） | 迁后：捕获 `GamedataError` → 返回 `{}`、不缓存 | `test_names_empty_when_db_unavailable`；**行为差异，待控制台定**（§9 第 1 条） |

`_junk / _CODE / _norm_zh / _fold_en` 改了任何一处 → 必须升 `_schema.IMPORTER_VERSION`（表里存的是过滤后的结果）。在 `trade/names.py` 这几处加注释写明。

## 2. `names` 内部派生（不入库，算法不动）

| 函数 | 数据来源 | 顺序 / 冲突语义（必须保持） | 测试 |
|---|---|---|---|
| `to_english(query, limit=8)` L80-96 | 每次调用现建 `norm = {_norm(k): v for k, v in table().items()}` | 精确命中用的是 **dict 推导 → 同一 `_norm` 键后写覆盖**（`医疗笔` 与 `医疗 笔` 都在时取后者）；模糊命中按 `table()` 顺序、按 `en` 去重、到 `limit` 截断；返回 `list[str]` | `test_to_english_exact_last_wins_index_first_wins`（Review Focus 2）、`test_to_english_fuzzy_order_and_limit` |
| `_index()` L119-126 | `table()` | 两个 dict 都 `setdefault` → **首个胜出**（与上一行相反，别统一） | 同上 |
| `canonical(zh, en)` L200-226 | `_index()` + `i18n` 矿物表（包内常量） | 顺序：拆中英连写 → 矿物 → 英文精确 → 中文精确 → 英文近似 → 矿名错一字 → 中文近似 | `test_canonical_and_zh_for_unchanged`（最小源上与旧实现比） |
| `zh_for(en)` L229-232 | `_mineral` 或 `_index()[1]` | — | 同上 |
| `suggest(query, limit)` L235-274 | `table()` | `sorted(..., key=-score)` 稳定排序 → 同分按 `table()` 顺序 | `test_suggest_tie_order_follows_table` |

`to_english` 每次重建 `norm` 是 O(n)（7k 条）。本批**不优化**（行为优先）；若性能测量需要，可以把 `norm` 也挂在 `table()` 对象上用 identity 缓存——但必须保留“后写覆盖”，单独提交。

## 3. gamekey：wiki_items.json + loot_index.json + name_aliases.json → `gamekey.resolve(name_en)`

`resolve` 只有一个生产调用方 `trade/catalog.Catalog.fill_keys`（逐个库存物品调，可能几千次）。

| # | 规则（`trade/gamekey.py` 行号） | 现状行为 | 迁后怎么保证 | 测试 |
|---|---|---|---|---|
| G1 | 折叠函数 `gamekey._fold` L15-16 = `re.sub("[^a-z0-9]", "", s.lower())` | **不做 `l→i`、不做 NFKC**（与 `itemsearch.en_key` / `shops._fold` 不同——批 1 矩阵 §4 写“都是 `shops._fold` → 是”，**与源码不符**） | `gamekey` 继续用自己的 `_fold` 在内存里建键；不用 `items.item_id` | `test_gamekey_fold_does_not_merge_l_and_i` |
| G2 | `by_name`：wiki `items` 按 `_fold(n)` `setdefault`（L26-28） | 同折叠名**首个 wiki 行**胜出 | `wiki_items` 表 `ORDER BY source_order` | `test_gamekey_resolve_equals_legacy_on_sample`（Review Focus 5） |
| G3 | wiki 行**全部**参与（含 `_wiki_noise` 被物品目录丢掉的涂装、杂项） | 涂装等只在 wiki 里的物品也能解析出类名 | `wiki_items` 表存全部行，不经 `import_items` 的两轮过滤 | 同上（样本含一条 `t="Paints"` 的 wiki 行） |
| G4 | `uuid`：`loot_index.rows` 按 `cls.lower()` `setdefault`（L30-39） | 同类名**首个**掉落行的 uuid | 复用已有 `loot_rows`（`cls` 原样存，读时 `.lower()`），`ORDER BY source_order` | 同上 |
| G5 | `alias`：`name_aliases` 逐条 `alias[_fold(old)] = new`（L40-47） | **后写覆盖**；不检查 `old` 是否已是别的物品（`itemsearch` 那条规则 `en_key(old) not in by_en` 这里没有） | 新表 `name_alias_pairs` 原样存全部对；`item_names(kind='aka')` 是过滤后的，**不能用** | `test_gamekey_alias_last_wins_and_unfiltered` |
| G6 | 解析：`by_name[k] or by_name[_fold(alias[k])]`（L58） | 先正名后旧写法 | 代码不动 | Review Focus 5 测试 |
| G7 | `w["cls"]` 为空 → `None`；返回 `cls.lower()` | — | `wiki_items.cls` 原样（空串存 `''`） | 同上 |
| G8 | uuid 找不到时按 `w["alt"]` 顺序逐个找，首个命中（L62-69）；都没有 → `''` | — | `wiki_alt_classes(wiki_id, idx, cls)`，`ORDER BY idx` | `test_gamekey_alt_class_fallback_in_order` |
| G9 | 任一文件缺失 / 坏 → 那部分为空，不抛 | `wiki_items()` 缺 → `[]` → 全部 `None` | 库不可用（`GamedataError`）→ `resolve` 返回 `None`、不缓存 | `test_gamekey_none_when_db_unavailable` |
| G10 | 缓存：`_IDX["key"] is rows`（只认 `wiki_items()` 那份 list 的身份） | 只更新 `name_aliases.json` 或 `loot_index.json` 时索引不刷新——**现状缺陷**（同设计文档 §1.1 记的 `itemsearch.py:78`） | `VersionCache` 按 `data_version` | `test_gamekey_refreshes_after_alias_change`；缺陷修复列为允许差异 |

## 4. core/i18n —— 不迁

逐个核对了 `sc_mining/core/i18n.py` 的全部数据读取：

| 函数 | 读什么 | 归类 |
|---|---|---|
| `_tables(ship_only)`（`lru_cache`）→ `mineral_en / mineral_zh` | `GLOSSARY = sc_mining/sc_glossary.json`（包内） | 随程序带的常量，**不入库** |
| `_maps()` → `method_zh / station_zh` | 同上 | 同上 |
| `_gear_zh()` → `gear_label / gear_zh_of_item` | 同上 | 同上；注意 `gear_zh_of_item` 被 `_import.import_items` 调用（派生 `items.zh`），改 `sc_glossary.json` 内容会让物品中文名变——这是现状，`data_version` 已含程序版本兜住 |
| `CONFUSABLE`、`SHOP_CAT_ZH` / `shop_cat_zh` | 代码内常量 | 不动 |

`i18n` **没有任何一处读 `paths.DATA`**。`names_zh.json`（包内）的读者是 `update/localization.names_source()`（没有游戏汉化包时的兜底源），也不是 `i18n`。用户汉化包 `global.ini`（`localization.read_ini`）是用户数据，不入库。→ 文件清单里 `core/i18n.py` **不改**；基线工具仍抽查几个 `i18n` 函数当护栏。

## 5. `crafting/itemsearch.wiki_items()` —— 本批不删（收口 2 / GD-K7 已删，改读 `gamedata.names.wiki_classes()`）

| 读者 | 批次 | 迁后 |
|---|---|---|
| `trade/gamekey._index` | 6 | 改走 `gamedata.names.wiki_classes()` |
| `crafting/loot._wiki_classes(name_en)` L113-125（`n / cls / alt`） | 4 | 批 4 可直接用本批新建的 `wiki_items` / `wiki_alt_classes` 表（顺手省掉 3.6 MB JSON 的进程内副本） |
| `update/localization.wiki_class_names()` L109-120（`cls / alt / n`，**保留原大小写**当键） | 更新流程 | 读源文件生成源文件，留在 JSON 路径合理；若要迁，`wiki_items.cls` 必须存原大小写（§8 已这样定） |

→ 批 6 之后 `wiki_items()` 仍有两个读者；删除留到批 4 合并后由清理批次判断。

## 6. 为什么不用 `item_names` / `items.by_name / by_source_id`（证据）

`item_names(kind='zh_loc')` 是 `import_items` 第 3 段把 `_names_table(sources)` **并进物品目录之后**的产物，与 `names.table()` 有 6 处不等价：

| # | 差异 | 来源（`gamedata/_import.py`） | 后果 |
|---|---|---|---|
| D1 | 只汉化包有、且中文比较键与有商店 / 掉落物品撞了的条目被第一轮过滤**整条丢掉** | L128-133 | 例：`zh_names` 有 `医疗 笔→Old Medpen Name`，掉落里 `医疗笔` 已占 → `item_names` 没这条；现状 `to_english("医疗笔")` 精确命中走“后写覆盖”返回 `Old Medpen Name`，改用 `item_names` 后变成 `Medpen` |
| D2 | `en_key(en)` 为空（纯中文 / 纯符号英文，R5 留下来的那些）→ `entry()` 返回 `None` 丢掉 | L53-55 | 这些对在 `table()` 里有、在库里没有 |
| D3 | 英文值变成物品目录的首见拼写（商店 / 掉落优先，`\xa0`→空格） | L58-59 | `to_english` 返回拼写变（R9） |
| D4 | `gear_zh_of_item` 额外插入 `zh_loc` 行（`霍夫斯泰德`） | L143-146 | `table()` 多出不存在的对 |
| D5 | 顺序按物品目录顺序，不是 `zh_names` 文件顺序 | L175-179 | R8 全部受影响 |
| D6 | `zh_names` 与 `zh_only_names` 都记成 `zh_loc`，分不出来源 | L104-109 | 无法核对 R7 |

`gamekey` 不能用 `items.by_name / by_source_id('class')`：G1（折叠函数不同）、G3（wiki 噪声物品已被丢）、G5（别名经过过滤且首个胜出）、`item_source_ids('class')` 混了掉落类名和 wiki 类名且 `INSERT OR IGNORE` 首个胜出、`alt` 根本没入库（批 1 矩阵 §5 “地基不入库”）。

→ `items.candidates / names_of / by_name / by_source_id / search` 本批**不用**；它们是否还有用途（批 3 / 批 4）由控制台另判。

## 7. 调用方清单（本批都不改签名；“改动”列只指本批）

| 调用模块 | 用到的 | 改动 |
|---|---|---|
| `trade/catalog.py` L25 `fill_keys` | `gamekey.resolve` | 不改；Task 4 冒烟 |
| `trade/catalog.py` L63 `search` | `names.to_english` | 不改 |
| `trade/parser.py` L4/L37 | `to_english` | 不改 |
| `trade/market_service.py` L8/L80-88 | `has_chinese`、`to_english(query)[:3]`（调两次，依赖两次结果一致——同版本缓存保证） | 不改 |
| `trade/inspector.py` L16/L540-555 | `canonical`、`has_chinese`；L511 `i18n.mineral_en` | 不改 |
| `trade/console.py` L42/L138-157/L870 | `has_chinese`、`to_english`、`_fold_en`（私有名被外部 import，**保留**）、`canonical`、`zh_for` | 不改 |
| `tasks/hover.py` L154 | `C.has_chinese`（经 console） | 不改 |
| `tasks/trade.py` L195 `_zh_of` | `names.table()`，反查 dict **挂在函数属性 `_zh_of._rev` 上永不失效**（更新数据后不刷新——现状缺陷，不在本批文件清单） | 不改；§9 第 4 条 |
| `tasks/trade.py` L106/L211/L391/L459 | `i18n.shop_cat_zh / gear_zh_of_item / mineral_zh / station_zh` | 不改 |
| `crafting/loot.py` L116、L425-461 | `itemsearch.wiki_items`、`i18n.mineral_*` | 不改（批 4） |
| `update/localization.py` L112-120 | `itemsearch.wiki_items` | 不改（收口 2 改读 `gamedata.names.wiki_classes`） |
| `update/localization.py` L304-310 `_write_name_files` | `names.table.cache_clear()`、`names._index.cache_clear()`——**直接调，不判 `hasattr`**（外面包了 `try/except Exception`，属性没了会静默失效） | 不改；靠保留 `cache_clear` 属性 |
| `update/data_pack.py` L192 `clear_caches` | `_clear("trade.names", "table", "_index")`（判 `hasattr`） | 不改 |
| `gamedata/_import.py` L17-41 | `trade.names._fold_en / _junk / _norm_zh` | 不改；`trade/names.py` **模块顶层不能 import `gamedata`**（建库时会循环），一律函数内延迟 import |
| `navigation/waypoints.py` L15、`navigation/celestial.py` L22 | `navigation.names`（`POINT_ZH / SYS_ZH / _norm / label …`）——**是导航的地名模块，不是 `trade.names`** | 不在本批（批 2 已处理 `poi_zh`） |
| `navigation/navigate.py`、`starmap.py`、`transit.py` | 不在本机；按名字只知道 import `navigation.names` | **待核**：是否有人 import `trade.names` / `gamekey` |
| `crafting/acquire.py`、`tasks/system/about.py` | grep 未见 `trade.names` / `gamekey` / `i18n` | **待核**（随上传给到，未见调用） |

## 8. 公共层先行 PR 要做的（已随 schema 4 合入，表定义以 `gamedata/_schema.py` 为准）

三张新表，全部**原样、有序**，不过物品目录的合并 / 过滤：

```sql
-- _import._names_table(sources) 的结果原样：src = 'zh_names' / 'zh_only'；source_order = 返回 dict 的枚举序号
CREATE TABLE zh_name_pairs (
    source_order INTEGER PRIMARY KEY,
    zh TEXT NOT NULL,
    en TEXT NOT NULL,
    src TEXT NOT NULL
);
-- wiki_items.json 的 items 原样（全部行，含 _wiki_noise）；cls 保留原大小写（localization.wiki_class_names 按原样当键）
CREATE TABLE wiki_items (
    id INTEGER PRIMARY KEY,          -- = source_order
    n TEXT NOT NULL,
    cls TEXT NOT NULL DEFAULT ''
);
CREATE TABLE wiki_alt_classes (
    wiki_id INTEGER NOT NULL REFERENCES wiki_items(id),
    idx INTEGER NOT NULL,
    cls TEXT NOT NULL,
    PRIMARY KEY (wiki_id, idx)
);
-- name_aliases.json 原样：全部字符串对，按 dict 顺序（item_names(kind='aka') 是过滤后的，gamekey 用不了）
CREATE TABLE name_alias_pairs (
    source_order INTEGER PRIMARY KEY,
    old TEXT NOT NULL,
    new TEXT NOT NULL
);
```

- 导入：`import_name_pairs(conn, sources)`：调一次 `_names_table(sources)`（建议让它顺带返回每条来源，或在 `import_name_pairs` 里按“是否在过滤后的 `zh_names` 里”判 `src`）；`import_wiki_rows`：`n` 不是字符串的行跳过（`import_items` 现在对缺 `n` 会 `KeyError`——公共层顺手核对 `_build` 是否把它包成 `BuildError`）；`alt` 只收字符串；`import_alias_pairs`：只收 `str→str`。
- 不加索引（三张表都是整表读进内存）；`loot_rows` 不改。
- `SOURCES` 不变（4 份源都已在清单里）。`SCHEMA_VERSION`、`IMPORTER_VERSION` 各 +1。
- `_import._names_table` 被调两次（`import_items` 第 3 段和新函数）：可以在 `build()` 里算一次传两处，公共层自定。
- 地基测试补：`test_zh_name_pairs_equal_names_table_rule`（把 `test_names_table_without_zh_names_is_empty` 扩成有序全量比对）、`test_wiki_rows_keep_noise_and_alt_order`、`test_alias_pairs_unfiltered`。

## 9. 批 6 开工前必须补的核对（控制台 2026-11-02 已定的标 ✔）

1. ✔ **R11**：接受为允许差异。`shops.json` 随安装包的 `data/` 一起带，"有汉化没商店表"不是正常状态；`shops.json` 保持唯一必需源。PR 里写明。
2. ✔ uuid 唯一（真实数据 13457 行无重复，2026-11-02 核过）。
3. `navigation/navigate.py / starmap.py / transit.py`、`crafting/acquire.py` 是否 import `trade.names` / `gamekey`（本机未见）。
4. ✔ `tasks/trade._zh_of._rev` 永不失效：**批 6 顺手修**（跟着 `table()` 对象身份走，一行），`tasks/trade.py` 加入文件清单，补一条测试。
5. ✔ 批 1 矩阵 §4 那句已更正（`gamekey._fold` 不做 l→i）。
