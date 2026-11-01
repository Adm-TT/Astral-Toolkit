# 游戏数据层 试点调用点矩阵（批 1：shops / itemsearch / stockplaces）

日期：2026-11-02　基准提交：`main` 4facdc5　状态：地基阶段版本，批 1 开工前逐行复核并补全“调用模块”列

读法：每行一个“源文件字段 → 库里的列”。“转换规则”引用源码位置；“现在没人读”的字段单独列在每节末尾，这些才允许不入库。

## 1. shops.json（4.0 MB）

结构：`{"fmt": 2, "fetched": <epoch>, "items": {<uex_item_id>: [<英文名>, <类别>]}, "rows": [[...7 列...]]}`，`items` 2830 条，`rows` 24141 行。

| 源字段 | 读它的函数 | 转换规则 | 目标表.列 | 返回顺序要求 |
|---|---|---|---|---|
| `items[iid][0]` 英文名 | `itemsearch._build_locked` L95-99；`shops._folded_items` | `entry(en)`：`en_key(en)` 做身份键（`shops._fold`：小写、去非字母数字、`l→i`）；`\xa0`→空格 | `items.en`、`items.item_id`（=en_key）、`item_names(kind='en', norm=ek)` | — |
| `items[iid]` 的键 iid | 同上 L95-99 | `int(iid)`；同一 en 多个 iid 时**第一个**胜出（`e["shop"] is None` 才赋值） | `item_source_ids('uex', str(iid))`；`items.has_shop` | dict 迭代顺序 = JSON 文件顺序 → `source_order` |
| `items[iid][1]` 类别 | 同上 | 首个 iid 的 cat；空→`""` | `items.cat` | — |
| `rows[i][0]` 物品 id | `shops.where/nearest/where_text/buyable/variants` | `== item_id` 过滤 | `shop_rows.uex_item_id` | — |
| `rows[i][1]` 商店名 | `shops.where/nearest` 输出 | 原样 | `shop_rows.shop_name` | `where` 按价格排、同价按商店名（tuple 排序） |
| `rows[i][2]` 位置文字 | 同上 | 原样 | `shop_rows.place_text` | `nearest` 同一 place_text 只留一家 |
| `rows[i][3]` 买价 | `where`（`>0` 才算）、`nearest`、`buyable` | 源是 float，原样 | `shop_rows.price_buy REAL` | `where` 买价升序 |
| `rows[i][4]` 卖价 | `where`（`>0`） | 原样 | `shop_rows.price_sell REAL` | `where` 卖价降序 |
| `rows[i][5]` 版本 | 待批 1 核对（grep `r[5]`） | 原样 | `shop_rows.version` | — |
| `rows[i][6]` 位置字段 6 项 | `shops.shop_point`（算坐标）、`_place` | 原样 6 个字符串；`len(r) > 6` 才有 | `shop_rows.f0..f5` | — |
| `fmt`、`fetched` | `shops.load`（判断要不要更新） | 不入库：属于更新流程，不属于查询 | — | — |

## 2. loot_index.json（1.7 MB）

结构：`{"version": "4.10.2LIVE", "rows": [[uuid, 英文名, 游戏类名, 稀有度, n, 中文名], ...]}`，13457 行。

| 源字段 | 读它的函数 | 转换规则 | 目标表.列 | 顺序 |
|---|---|---|---|---|
| `rows[i][0]` uuid | `loot.find/detail`、`gamekey._index`（按类名取 uuid，**首个**胜出） | 原样 | `loot_rows.uuid`（主键）、`item_source_ids('loot_uuid', uuid)` | `gamekey` 用 `setdefault` → 首个 |
| `rows[i][1]` 英文名 | `itemsearch` L100-112；`loot._folded_rows` | 若英文位有中文且中文位没有 → 对调（L102-105）；`entry(en)`；`loot=True` | `loot_rows.en`；`items.has_loot` | — |
| `rows[i][2]` 类名 | `gamekey`、`loot._wiki_classes` | 小写比较 | `loot_rows.cls`；`item_source_ids('class', cls)` | — |
| `rows[i][3]` 稀有度 | `loot.find` 输出 | 原样 | `loot_rows.rarity` | — |
| `rows[i][4]` n | 待批 1 核对 | 原样 | `loot_rows.n` | — |
| `rows[i][5]` 中文名 | `itemsearch` L106-112 | 无中文字符（`PH - xxx` 占位）→ 空；非空则 `zh_loot` 首个 + `zks.add(zh_key)` | `loot_rows.zh`；`item_names(kind='zh_loot')` | 首个胜出 |
| `version` | `loot.load_index/details_version` | 不入库（更新流程用） | — | — |

## 3. zh_names.json（378 KB）+ zh_only_names.json（33 KB）

结构：`{<中文名>: <英文名>}`，7393 + 若干条。

| 源字段 | 读它的函数 | 转换规则 | 目标表.列 | 顺序 |
|---|---|---|---|---|
| 每对 zh→en | `names.table()` L16-38 | 先过 `_junk(en, known)`（去掉“视差步枪→HD”这种假英文名，L40-47）；`zh_only_names` 只在 `len(_norm_zh(zh)) >= 3` 且 zh 不存在时 `setdefault` | 不单独建表：由 `itemsearch` L113-118 消费——`entry(en)`，`loc=True`，`zh` 首个，`zks.add(zh_key(zh))` → `item_names(kind='zh_loc')`、`items.loc` | 字典顺序 → 首个胜出 |

地基实际做法（2026-11-02 审查后更正）：导入**不调用** `trade.names.table()`（它经 `shops.load()` / `loot.load_index()` 走模块级缓存，建库时换不掉根目录），而是 `_import._names_table()` 直接 import 复用 `names._junk / _fold_en / _norm_zh`，`known` 集合从已读的 shops/loot 源算——规则与 `_known_names()` 相同；`zh_names.json` 缺失时同样返回空表、不补 `zh_only_names`。**维护约束**：改 `names.table()` 的规则必须同步改 `_import._names_table` 并提升 `IMPORTER_VERSION`。批 6（names/i18n）再决定是否把过滤规则搬进库。

## 4. name_aliases.json（10 KB）

结构：`{<旧写法>: <正名>}`。由 `localization.rebuild` 写。

| 源字段 | 读它的函数 | 转换规则 | 目标表.列 |
|---|---|---|---|
| old→real | `itemsearch` L141-150 | `e = by_en.get(en_key(real))`；**仅当 `en_key(old) not in by_en`** 才 `e["aka"].append(old)`；之后 `by_en.setdefault(en_key(old), e)`（L163-165） | `item_names(kind='aka', name=old, norm=en_key(old))` |
| 同上 | `gamekey._index` L41-48 | `alias[_fold(old)] = new`，解析时 `by_name.get(_fold(alias.get(k)))` | 同一张 `item_names(kind='aka')` 可覆盖；批 1 核对 `_fold` 与 `en_key` 是否同一函数（都是 `shops._fold` → 是） |

## 5. wiki_items.json（3.6 MB）

结构：`{"version", "source", "fetched", "items": [{"n", "t", "s", "mfr", "cls", "d", "alt"?}]}`，7830 条。

| 源字段 | 读它的函数 | 转换规则 | 目标表.列 |
|---|---|---|---|
| `n` 英文名 | `itemsearch` L132-140；`gamekey._index` L27-28（`_fold(n)` 首个胜出） | `entry(n)`；`setdefault("wiki", True)` | `items.wiki`（仅在无 shop/loot/loc 时才对外显示为 wiki，见 `find` 输出 L306） |
| `t` 类型 | `itemsearch` L135；`_wiki_noise` | 原样；`Paints/misc/flair_surface` 且无其他数据 → 整条物品丢弃 | `items.wtype` |
| `s` 尺寸 | `itemsearch` L135 | 原样（int 或 None） | `items.wsize` |
| `d` 描述 | `itemsearch` L135 | 原样 | `items.desc` |
| `cls` 类名 | `gamekey.resolve` | 小写 | `item_source_ids('class', cls)`（与 loot 的 class 同一表；重复 `INSERT OR IGNORE`） |
| `alt` 备用类名 | `gamekey.resolve` L62-66 | 逐个在 uuid 表里找 | 批 1 决定：存 `item_source_ids('class_alt', ...)` 或由 gamekey 保留读 JSON；地基**不入库** |
| `mfr` 厂商 | 现在没人读 | 不入库 | — |
| `version`、`source`、`fetched` | 没人读 | 不入库 | — |

## 6. prices.json（8 KB）

结构：`{"prices": {<矿物>: {<城市>: <价格>}}, ...}`。由 `uex.refresh` 写；`mining/data.py` 末尾和 `data_pack.clear_caches()` 里 `uex.apply_live(data)` 把它套进内置矿价表。

| 源字段 | 读它的函数 | 转换规则 | 目标表.列 |
|---|---|---|---|
| `prices[mineral][city]` | `uex.apply_live` | 批 1 核对 `apply_live` 的覆盖规则（0 价是否视为无数据） | `mineral_prices(mineral, city, price REAL)` |
| 其他顶层键 | 批 1 核对 `uex.py` L40 以后 | 地基不入库 | — |

## 7. itemsearch 索引合成后的派生字段（不在任何源里，由导入算出）

| 字段 | 规则（`itemsearch._build_locked` 行号） | 目标列 |
|---|---|---|
| `zh` | `zh or zh_loot`（L167）；`gear_zh_of_item(en)` 非空则覆盖并追加 zks（L168-175） | `items.zh`、`item_names(kind='zh_loc')` 追加一行 |
| `zlen` | `min(len(k) for k in zks)`，空则 99（L176） | `items.zlen` |
| `variant` | en 含 `"` 或 zh 含中文引号（`_variant`，L177） | `items.variant` |
| `has_data` | `shop is not None or loot`（L178） | 查询时由 `has_shop OR has_loot` 算，不存列 |
| 两轮过滤 | ① 仅汉化、且 zks 与有数据物品重合 → 丢（L151-155）；② 无 shop/loot/loc 且 `_wiki_noise` → 丢（L156-160） | 导入时丢弃，不入 `items` |
| `by_char` / `by_tri` | 字符索引、三元组索引（L166-186） | **不入库**：批 1 在内存里从 `items.candidates()` 重建，算法不变 |

## 8. 现在没人读、建库时不入库的字段汇总

`shops.fmt/fetched`、`loot_index.version`、`wiki_items.version/source/fetched/mfr`、`wiki_items.alt`（地基阶段；批 1 决定）。

## 9. 批 1 开工前必须补的核对

- `shop_rows.version`（`rows[i][5]`）、`loot_rows.n` 的读者。
- `stockplaces.py` 读哪些字段（本矩阵尚未覆盖该模块）。
- `uex.apply_live` 的覆盖规则和 `prices.json` 其余顶层键。
- `wiki_items.alt` 的归宿。
