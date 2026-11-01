# 游戏数据层 批 5 调用点矩阵（采矿：mining_area / shipsig / 精炼站加成）

日期：2026-11-02　基准分支：`1.1.4-beta.1-database`（须已含批 2 与 schema 6）　状态：定稿（控制台 2026-11-02 按真实数据审定；§7 公共层已做进 **schema 6**——schema 5 被批 3 的可空列修正占了号）；批 5 开工前逐行复核“调用模块”列

读法同批 1 / 批 2 / 批 4 矩阵。行号指本次核对的快照（批 2 合并前）；批 2 合并后 `navigation/navigate.py` 的行号会变，开工前复核。

本批要迁的读文件点只有四处：`mining_area.rocks_table()`（`mining_rocks.json`，`cached_json` + mtime）、`mining_area._spots_raw()`（`mining_spots.json`，**每次读盘**，热路径）、`shipsig.ships()`（`ship_signatures.json`，`lru_cache`）、`uex.apply_live()` 里精炼站加成那半（`prices.json` 的 `yields`，批 1 留下的过渡读法）。`mining_spots`、`mineral_prices` 两张表已在库里；`mining_rocks.json`、`ship_signatures.json`、`prices.json.yields` 已由控制台在 schema 6 入库（§7）。

设计 §4.3 批 5 一行写的是“mining_area / signals / parse”：核对结果是 `signals`、`parse` **自己不读 `data/`**，只经 `mining_area.rocks_table()` 间接读石头表；`rocks_table()` 签名不变，所以这两个模块**一行不改**（§5）。

## 0. 使用方式概览（决定表怎么建）

| 函数（行号指各自文件） | 怎么用数据 | 迁移方式 |
|---|---|---|
| `mining_area.rocks_table()` L59-67 | `cached_json(DATA/"mining_rocks.json", default={})`，返回整个 dict（不是 dict 返回 `{}`）；调用方全是 `.get(段) or {}` 再按键取 | 改走 `gamedata.mining.rocks()`：从库组装**同形** dict，按 `data_version` 缓存一份（`VersionCache`）；库不可用（`GamedataError`）返回 `{}`。签名、返回形状不变 |
| `mining_area.rocks_stamp()` L70-74 | `file_stamp(mining_rocks.json)`：雷达结果 / `navigate.mining_spots` 按它判断要不要重算 | 改成 `gamedata.version()`（`GamedataError` → `None`）。变得更频繁（任何源变都变），只多算一次，无害 |
| `mining_area._spots_raw()` L238-244 | **每次** `json.loads(mining_spots.json)`，出错 `[]`；`_pyro_spot` 和 `area()` 派罗分支各调一次（一次判断读两遍——附录 A 已核实） | 改走批 2 的 `gamedata.mining.spots()`（按版本缓存的 tuple），`GamedataError` → `()`；**函数名保留**（测试 monkeypatch 它） |
| `mining_area._pyro_spot(g)` L250-269 | 遍历 `_spots_raw()` 的 dict：`s.get("sys") / s.get("area") / s.get("kind") / s["x"]…` | 改成读 `MiningSpot` 的属性（`s.sys / s.area / s.kind / s.x…`）；距离、半径、首个命中语义一字不改（§2） |
| `mining_area.area(...)` L103-177 | 组合石头表、挖矿点、星图（`navigate.load()`）、`halo.where`、`locations.LOCATIONS` | 函数体外包一个“尽量钉住快照”（§2 末）：一次判断里石头表、挖矿点、星图同一版本；判断逻辑不动 |
| `mining_area._result / _named / area_for_spot` L77-96、L188-216、L272-285 | 都经 `rocks_table()` 读 `areas` | 不动（经 `rocks_table()` 间接迁移） |
| `mining_area._body_xyz / _starmap_points` L219-235 | `navigate.load()`（批 2 已从库组装） | 不动 |
| `shipsig.ships()` L20-24 | `@lru_cache(maxsize=1)`，`json.loads(...)["ships"]`，返回 list[dict]；文件缺失 / 坏 → **抛异常** | 改走 `gamedata.mining.ship_signatures()`（按版本缓存的 tuple[dict]），`ships()` 返回 `list(...)`；去掉 `lru_cache`；源缺失 / 库不可用 → `[]`（允许差异，§3） |
| `shipsig.match / describe` L35-75 | 遍历 `ships()`，`dict(s, score=…, variants=[])` 把源里**每个键**原样带出去 | 不动（经 `ships()` 间接迁移） |
| `uex.apply_live(data_module)` L75-112 | `OUT.exists()` 判有无；矿价走库（批 1）、库不可用退回读 JSON（过渡）；**`yields` 直接 `json.loads(prices.json)`** | 有无改读 meta `src:prices.json` 是否为空串（文件在就有 sha，坏文件也有——和 `OUT.exists()` 语义一致）；`yields` 改读库 `gamedata.prices.refinery_yields()`；**删掉** `live = json.loads(...)` 和标了“过渡”的矿价退路；库读不到 → `return False`、内置表不动。覆盖语义（0 价不盖、整站替换、不认识的站不加）一字不改 |
| `uex.refresh()` L42-72 | 联网 → `write_json(OUT, {prices, yields})`，已在 `gamedata.updating()` 里 | **保持** |
| `signals.cluster_weight` L438-458、`parse._rock_contains` L373-382 | 调 `rocks_table()` 读 `ores / tiers / contains` | 不动 |

## 1. mining_rocks.json（数据构建脚本生成，随数据包更新）

**结构（按源码读法推断，待控制台按真实数据核对）**：

```
{
  "tiers":    {稀有度: {"p_cluster": 数, "sizes": [[p, lo, hi], …]}},   # signals.cluster_weight
  "ores":     {矿: {"sig": 整数, "tier": 稀有度, …?}},                  # cluster_weight 读 tier；测试读 sig
  "areas":    {地点名: {石头种类: 百分比}},                              # _result / _named / area_for_spot
  "contains": {石头种类: [矿, …]},                                       # parse._rock_contains
  …其他顶层键?（version / fetched 之类）
}
```

| 源字段 | 读它的函数 | 转换 | 目标表.列 | 顺序 |
|---|---|---|---|---|
| `areas[地点]` | `_result`：`.get(row["name"])` 真值才放 `out["rocks"]`（拷贝）；`_named`：真值才用；`area_for_spot`：**原样返回**（可能是 `{}`，也可能 `None`） | 整条原样（`{}` 也存——`area_for_spot` 区分 `{}` 和 `None`，`navigate.mining_spots` 输出的 `rocks` 会跟着变） | `mining_rock_entries(section='areas', key=地点, value_json)` | 段内源顺序 |
| `areas[地点][石头]` 百分比 | `signals._local_note`：`f"{pct:g}"`；`area()` 结果整个进雷达 / 悬浮窗 | **int / float 原样**（基线 JSON 里 `18` 和 `18.0` 不同） | 同上（在 `value_json` 里，JSON 自带类型） | 石头在地点内的源顺序（`dict(rocks)` 保留） |
| `ores[矿]` | `cluster_weight`：`.get("tier")`；`test_mining` 读 `["sig"]` | 整条原样（不知道有没有别的键，不拆列） | `section='ores'` | 源顺序 |
| `tiers[稀有度]` | `cluster_weight`：`p_cluster`、`sizes` 三元组 | 整条原样 | `section='tiers'` | 源顺序（`sizes` 顺序在 JSON 里） |
| `contains[石头]` | `_rock_contains`：`list(... or [])` | 整条原样 | `section='contains'` | 源顺序 |
| 其他顶层键（若有） | 本快照里没人读 | 原样 | meta `mining_rocks_meta`（§7） | — |

为什么按“段 + 键 → 一条 JSON”存、不拆成五张关系表：① `area_for_spot` 原样返回 `areas[x]`，`{}` 和“没有这个地点”结果不同，拆成 `(area, rock, pct)` 行会丢掉空地点；② 百分比、`sig`、`p_cluster` 的 int / float 要原样（SQLite 的 `REAL / NUMERIC` 亲和性会把 `5` 和 `5.0` 互转）；③ `ores / tiers` 条目里有没有别的键看不到真实数据，拆列会悄悄丢字段；④ 消费方全是“整表 dict 按键取”，`rocks()` 按版本缓存一份 dict，热路径上是 O(1) 取键，不需要 SQL 按键查。保留“段 + 键”一行一条（而不是整份文件一行），以后真有按键查的需求可以直接加索引查询。

“有没有石头表”三态：

| 现状 | 旧行为 | 库里怎么判断 / 新行为 |
|---|---|---|
| 没有 `mining_rocks.json` | `rocks_table()` → `{}`；`area()` 结果里没有 `rocks`，`_named` 退回 `None` | meta **没有** `mining_rocks_meta` → `rocks()` 返回 `{}`（同） |
| 有文件、JSON 坏 / 不是 dict | `cached_json` 给 `default={}` → `{}` | 可选源坏 = 当作没有 → `{}`（同） |
| 有文件、是 dict | 原样 dict | 组装：先放 meta 里的非 dict 顶层键，再按段放 `{key: json.loads(value_json)}`。**段缺失时组装成不含该键**（与旧 dict 键集合一致） |

## 2. mining_spots.json（已入库：schema 2 的 `mining_spots`，批 2 的 `gamedata.mining.spots()`）

表与导入是批 2 定的：坐标存**原始米**，每行都留（无 id、重复 id 也留），坏坐标行跳过；`sys / zh / en / kind / area` 为 `None` 时存 `''`。批 5 **不改表、不改 `spots()`**，只把 `_spots_raw()` 接上去。

| 源字段 | `mining_area` 里读它的地方 | 旧 | 新（`MiningSpot` 属性，字段名以批 2 合入的为准） | 差异 |
|---|---|---|---|---|
| `sys` | `_pyro_spot`：`s.get("sys") == "Pyro"` | `None` 时不等 | `s.sys`（`''`）不等 | 无 |
| `area` | `_pyro_spot`：真值才算、`_named(s["area"])` | `None / ''` 假 | `''` 假 | 无 |
| `kind` | `_pyro_spot`：`== "cluster"` 决定半径 | `None` 不等 | `''` 不等 | 无 |
| `x / y / z` | `_pyro_spot`：`math.dist(g, (x, y, z))` | 源值（米），缺键 / 非数 → `KeyError / TypeError` **往外抛**（只在 `sys=="Pyro"` 且 `area` 非空时才碰到） | 库里只有有限浮点三元组 | 坏坐标行不再让 `area()` 抛（**允许差异**：原代码缺陷） |
| 整表是否为空 | `area()` 派罗 L140-149：`not spots and not clusters` → `None` | `[]` | `()` | 无 |

**坐标合同（架构稿 §6.4）**——本批不引入 `Vec3`、不改单位，只把每处比较的坐标系写清楚，作为回归条件：

| 用在哪 | 坐标 | 单位 | 坐标系 / 作用域 | 同坐标系保证 |
|---|---|---|---|---|
| `area(g, system, …)` 入参 `g` | 玩家位置 | 米 | 星系坐标（`system` 指定的那个星系） | 调用方给 |
| `_pyro_spot`：挖矿点 | `mining_spots.x/y/z` | 米（原始，不除 1000） | 星系坐标，按行 `sys` | 只在 `system=="Pyro"` 分支调用，且逐行 `s.sys == "Pyro"` 过滤——别的星系的点不参与比较 |
| `_pyro_spot`：派罗拉格朗日点、派罗星团（L141-152） | 星图 `points.x/y/z` | 米 | 星系坐标，按点 `sys` | 逐点 `sys == "Pyro"` 过滤 |
| 斯坦顿拉格朗日点（L169-174） | 星图 `points` | 米 | 星系坐标 | `p["sys"] == "Stanton"` 过滤 |
| `_body_xyz("Terminus" / "Pyro6" / "Yela")` | 星图 `bodies.x/y/z` | 米 | 星系坐标 | **按名字**取天体、不核对 `sys`——靠名字本身唯一属于派罗 / 斯坦顿；所在分支已按 `system` 分开。保持现状，PR 里记一笔 |
| 尼克斯环带 `hypot(g[0], g[1])` | 入参 `g` | 米 → Gm | 尼克斯星系坐标，恒星在原点（隐含假设） | 只在 `system=="Nyx"` 分支 |
| `area_for_spot(spot, g)`（`navigate` 调） | `g` | 米（`navigate` 传的是**除 1000 之前**的原始值） | 星系坐标 | `navigate` 负责；批 5 不碰 `navigate` |
| `navigate.mining_spots()` 输出 | `x / 1000` | **千米**，`round(…, 3)` | 星系坐标，`b="@星系"` | 批 2 的事，批 5 不动 |
| 半径常量 `CLUSTER_KM / SPOT_KM / LPOINT_KM` | — | 千米，比较时 `× 1000` 成米 | — | 不动 |

**热路径与快照**：旧 `area()` 一次派罗判断读两遍 21 KB JSON；新 `spots()` 是版本缓存，两次调用都是取缓存。`area()` 同时用石头表、挖矿点、星图三个 topic，按设计 §2.2 要钉在一个快照上：函数体外层先 `gamedata.ensure()` 再 `with gamedata.snapshot():`（嵌套复用当前线程快照，`rocks()`、`spots()`、批 2 的 `navigate.load()` 都落在同一版本）。**进入快照失败**（`GamedataError`）时不钉，照常跑函数体——里面各处自己吞 `GamedataError` 当作“没有数据”，与旧代码“文件不在”一致；函数体里抛出的别的异常**不能**被这层吃掉（写法见计划 Task 2）。

## 3. ship_signatures.json（erkul 整理，随数据包更新）

**结构（按源码读法推断，待控制台核对）**：`{"ships": [{"name", "zh"?, "cs": [三个方向截面，从小到大], "em_max", "ir_max", …?}, …], …其他顶层键?}`

| 源字段 | 读它的函数 | 转换 | 目标表.列 | 顺序 |
|---|---|---|---|---|
| `ships[i]` 整条 | `match`：`dict(s, score, variants)`——**所有键原样带给调用方** | 原样；不是 dict 的条目跳过 | **新表** `ship_signatures(source_order, ship_json)` | `source_order`——`hits.sort(key=(score, name))` 是稳定排序，同分同名按源顺序；变体“并到第一行”也依赖这个顺序 |
| `ships[i].cs` | `_cs_score`：`axes[0]`、`axes[-1]`、逐个比；`tuple(cs)` 当变体合并键 | 原样（int / float 原样，合并键对类型敏感：`(1, 2)` 与 `(1.0, 2.0)` 相等，但输出里的数值类型要原样） | 在 `ship_json` 里 | — |
| `ships[i].em_max / ir_max` | `match`：真值才判 | 原样 | 在 `ship_json` 里 | — |
| `ships[i].name / zh` | 排序键、显示 | 原样 | 在 `ship_json` 里 | — |

整条存 JSON 的理由同 §1：`match()` 的对外返回就是源 dict 加两个键，调用方（本快照里看不到，§6）可能读任何键；船只有一两百条，每次 `match` 都是全量遍历，没有按字段查的需求。

三态：

| 现状 | 旧行为 | 新行为 |
|---|---|---|
| 没有文件 / JSON 坏 / 没有 `ships` 键 | `ships()` **抛** `FileNotFoundError / ValueError / KeyError`，`match / describe` 往外抛 | `ships()` → `[]`：`match` 返回 `[]`，`describe` 返回“截面 …：没有对得上的船”。**允许差异**（原代码缺陷：可选数据缺了让扫描功能崩）；须先核对调用方有没有靠这个异常走别的分支（§9） |
| 有文件、`ships` 是空表 | `[]` | `[]`（`src:ship_signatures.json` 非空、表空） |
| 库不可用 | —（旧代码不经库） | `[]`，同上一行 |

## 4. prices.json（已入库一半：`mineral_prices`；`yields` 本批入库）

结构：`{"prices": {矿: {城市: 价}}, "yields": {精炼站: {矿: 加成%}}}`，由 `uex.refresh()` 写（`yields` 来自 UEX `refineries_yields` 的 `row["value"]`，站名取 `terminal_name` 的 `" - "` 后半段，矿名经 `_base()`）。

| 源字段 | 读它的函数 | 转换 | 目标表.列 | 顺序 |
|---|---|---|---|---|
| `prices[矿][城市]` | `apply_live` → `CITY_PRICES` | 已入库（批 1）：`REAL`，读出时整数值还原 `int`；`0` 价不盖内置价 | `mineral_prices`（已有，不动） | rowid |
| `yields[站]` 整条 | `apply_live`：`refs[站] = (refs[站][0], bonus)`——**整站替换**（live 里没有的矿加成变 0，不回落内置值）；站名不在内置 `REFINERIES` 里的跳过 | 原样；`{}` 也存（旧代码会把这个站的加成清空）；不是 dict 的条目跳过（**允许差异**：旧代码会把非 dict 塞进 `REFINERIES`，`refinery` 一用就崩） | **新表** `refinery_yields(station, bonus_json)` | `source_order`（`bonus` 内的矿顺序在 JSON 里） |
| `yields[站][矿]` | `refinery.refined_scu / best_stations`、`locations.report`、`tasks/mining._station_bonus`、`tasks/trade` | **int / float 原样**（不经 `REAL`） | 在 `bonus_json` 里 | — |
| 文件有没有 | `apply_live` 第一行 `OUT.exists()` | — | meta `src:prices.json` 非空（地基每份源都有这个键；缺文件是 `''`） | — |

`apply_live` 迁移后的三态（矿价、加成一起，在**一个快照**里读）：

| 现状 | 旧（批 1 过渡）行为 | 新行为 |
|---|---|---|
| 没有 `prices.json` | `return False`，内置表不动 | meta `src:prices.json` 为 `''` → `return False`（同） |
| `prices.json` 坏 | `json.loads` 抛，`data.py` / `clear_caches` 的 `try` 吞掉 → 内置表不动 | 当作没有 → `return False`（结果相同，不再靠外层吞错） |
| 库不可用 | 矿价退回读 JSON、加成读 JSON → `True` | **`return False`，内置表不动**（删掉过渡退路，`uex.py` L87-89 注释里写明归批 5 删）。**允许差异**，PR 写明 |
| 正常 | 矿价读库、加成读 JSON | 两者都读库；覆盖语义一字不改 |

内置常量 `CITY_PRICES`、`REFINERIES`（`mining/data.py` L375-534）**不入库**：它们是代码里的快照，`apply_live` 在其上覆盖。`REFINERIES` 只换已有键的值、不增删键（`refinery.py` 在 import 时绑定了这个 dict），保持。

## 5. 不读 `data/` 的采矿模块（整个划出本批，一行不改）

| 模块 | 读什么 | 结论 |
|---|---|---|
| `mining/signals.py` | 常量 `data.SIGNATURES / RARITY / MAX_CLUSTER`；`rocks_table()`（L441）；**用户数据** `USER/my_signatures.json`（`cached_json` / `write_json`，L469-499）；`screen` 的 OCR | 不改。石头表经 `rocks_table()` 间接迁移；`my_signatures.json` 是用户数据，不动 |
| `mining/parse.py` | `core.i18n.mineral_en`（批 6）、`quality_tiers.TIERS`（常量）、`rocks_table()`（L378） | 不改 |
| `mining/refinery.py` | 常量 `REFINERIES / REFINING_METHODS / DEFAULT_METHODS`、`best_price` | 不改（`REFINERIES` 的值由 `apply_live` 换） |
| `mining/locations.py` | 常量 `LOCATIONS / _ZH`；`gems.GEMS`；`crafting.uses`（批 3）；`core.i18n`（批 6） | 不改 |
| `mining/laser.py` | 常量表；`crafting.blueprints()`（批 3，`head_blueprint / craft_slots` 的 `lru_cache` 由 `data_pack.clear_caches` 清）；**用户数据** `USER/observations.csv` | 不改 |
| `mining/data.py` | 全是常量；末尾 import 时调 `uex.apply_live` | 不改（`apply_live` 在 `uex.py` 里改） |
| `ore_log.json`（`USER`） | 本快照里没有读它的代码 | 用户数据，不动 |

本快照没有上传 `mining/gems.py`、`quality.py`、`quality_tiers.py`、`screen.py`，开工前确认它们不读 `data/`（§9）。

## 6. 调用方

| 调用方 | 调的什么 | 本批是否改 |
|---|---|---|
| `navigation/navigate.py` `mining_spots()`（批 2 后：`gamedata.mining.spots()`，缓存键 `(gamedata.version(), rocks_stamp())`） | `rocks_stamp()`、`area_for_spot()` | **不改**。`rocks_stamp()` 改成返回 `gamedata.version()` 后，这个键里两项相同，冗余但正确；整合清理时再收 |
| 雷达 / 扫描任务（`rocks_stamp` 的文档字符串说“雷达结果按它判断要不要重新发”；`area()` 的结果进 `signals.guesses / describe_all`） | `mining_area.area / rocks_stamp / filter_text` | 不改。**本快照的 `tasks/mining.py` 里没有找到这些调用**（任务说明里写在 `tasks/mining.py`），开工前 grep 全仓。要点：调用方应**先**取 `rocks_stamp()` **再**算 `area()`，否则“新版本号 + 旧数据”会让结果一直不重算（§9） |
| `shipsig.match / describe` 的调用方 | — | **本快照里没有找到调用方**，开工前 grep；确认对“数据缺失时抛异常”有没有依赖（§3） |
| `tasks/mining.py` L293-296 `_station_bonus` | `REFINERIES.get(station)` | 不改 |
| `tasks/trade.py` L458-481 | `best_price`、`REFINERIES.items()` | 不改 |
| `trade/console.py` L561 | `locations.where / zh_name` | 不改 |
| `update/data_pack.py` L28-48 `FILES` | 已含 `prices.json`、`ship_signatures.json`、`mining_rocks.json`、`mining_spots.json`；`install()` 已在 `updating()` 里 | 不改 |
| `update/data_pack.py` L200 `_clear("mining.shipsig", "ships")` | `ships.cache_clear()` | **不改**。去掉 `lru_cache` 后 `hasattr(f, "cache_clear")` 为假，这行变成空操作、不报错；整合清理时删 |
| `update/data_pack.py` L193 `paths.clear_json_cache()` | 以前清 `rocks_table` 的 `cached_json` | 不改（别的模块还要它） |
| `update/data_pack.py` L207-215 | `uex.apply_live(data)`（`try / except Exception`） | 不改。迁移后库刷新由 L234-238 `gamedata.refresh()` 负责；注意 `apply_live` 在 `refresh()` **之前**调用——同线程旧连接可能还没关，`apply_live` 里先 `gamedata.ensure()` 再开快照，快照按清单绑定，读到的是新库（§9 核对 `_db` 的实现） |
| `mining/data.py` L548-554 | import 时 `apply_live(本模块)` | 不改（首次 import 可能同步建库，同批 1 现状） |
| `tests/test_mining.py` L1634-1840（5 个测试） | `M.area / _result / _table / rocks_table / _spots_raw`；monkeypatch `M._spots_raw`、`M.rocks_table`、`M._ROCKS` | 只改 `test_review_104_rocks_reload_and_order` 一个（它直接写 `mining_rocks.json` 不重建库，见计划 Task 5）；其余靠“函数名保留、按模块全局调用”不改 |
| `tests/test_gamedata_b1.py` L390-416、L888-910 | `test_apply_live_reads_gamedata` 末尾断言“加成照旧读 prices.json”；`test_apply_live_yields_when_db_unavailable` 断言库坏时退回读 JSON | **改**：这两条断言的就是本批要删的过渡行为（计划 Task 4） |
| `tests/test_gamedata.py` L135-155 | 期望的表名集合 | 控制台随 schema 6 已加 |

## 7. 公共层先行 PR 要做的（已做进 schema 6，表定义以 `gamedata/_schema.py` 为准）

批 5 会话**不改** `gamedata/_*.py`。下面三张表和 `SOURCES` 两个源控制台已做（JSON 列方案，不是备选关系表）；真实数据往返：rocks 四段逐字相等、ships 191 条逐字相等、yields 20 站逐字相等（2026-11-02）。**没有加 `ship_signatures_meta` / `prices_meta`**：地基 meta 本来就有 `src:<文件名>`（在 = sha256，缺 = `''`），批 5 用它判「文件在不在」；`mining_rocks_meta` 保留（要还原段顺序和非 dict 顶层键）。

1. **`SOURCES` 加两个可选源**：`Source("mining_rocks.json", False)`、`Source("ship_signatures.json", False)`。`prices.json` 已在。
2. **新表 `mining_rock_entries`**（`import_mining_rocks`）：

   ```sql
   -- mining_rocks.json：顶层每个 dict 段（tiers / ores / areas / contains / …）按“段 + 键”一行，值整条存 JSON（类型、空 dict、未知字段都原样）
   CREATE TABLE mining_rock_entries (
       section TEXT NOT NULL,
       key TEXT NOT NULL,
       value_json TEXT NOT NULL,
       source_order INTEGER NOT NULL,   -- 段内源顺序
       PRIMARY KEY (section, key)
   )
   ```

   规则：源是 dict 才导；顶层值是 dict 的键当段，逐条 `json.dumps(v, ensure_ascii=False)`。meta 新键 **`mining_rocks_meta`** = `json.dumps({"sections": [段名，按顶层顺序，含空段], "extra": {非 dict 顶层键: 原值}}, ensure_ascii=False)`——`rocks()` 靠 `sections` 还原“哪些段在”（空段 `{}` 也算在），靠 `extra` 还原其余顶层键。源缺失 / 坏 / 不是 dict → **不写这个键**（§1 三态）。
3. **新表 `ship_signatures`**（`import_ship_signatures`）：

   ```sql
   -- ship_signatures.json 的 ships[]：整条原样 JSON（match() 把源 dict 的所有键带给调用方）
   CREATE TABLE ship_signatures (
       source_order INTEGER PRIMARY KEY,
       ship_json TEXT NOT NULL
   )
   ```

   规则：源是 dict 且 `ships` 是 list 才导；条目不是 dict 的跳过（`source_order` 用源下标，留空号）。「文件在不在」看 `src:ship_signatures.json`。
4. **新表 `refinery_yields`**（扩 `import_prices`，或新 `import_refinery_yields`）：

   ```sql
   -- prices.json 的 yields：精炼站 → {矿: 加成%}，整站原样 JSON（int / float 原样；{} 也存）
   CREATE TABLE refinery_yields (
       station TEXT PRIMARY KEY,
       bonus_json TEXT NOT NULL,
       source_order INTEGER NOT NULL
   )
   ```

   规则：`prices.json` 是 dict 且 `yields` 是 dict 才导；值不是 dict 的站跳过。「文件在不在」看 `src:prices.json`（控制台定：不另加键）。
5. `SCHEMA_VERSION = 6`、`IMPORTER_VERSION = 6`；`tests/test_gamedata.py` 的期望表名已加三张新表；公共层测试 `tests/test_gamedata_mining.py`。
6. `mining_spots` 表**不动**（批 2 已定）；`mineral_prices` 表**不动**。

备选（控制台若不接受 JSON 列）：`mining_rock_areas(area, rock, pct 无类型声明, area_order, source_order)` + `mining_rock_area_names(area PK, source_order)`（保住空地点）+ `mining_rock_ores(mineral PK, sig, tier, source_order)` + `mining_rock_tiers(tier PK, p_cluster, source_order)` + `mining_rock_tier_sizes(tier, p, lo, hi, source_order)` + `mining_rock_contains(rock, mineral, rock_order, source_order)`；`refinery_yields(station, mineral, value 无类型声明, source_order)` + `refinery_yield_stations(station PK, source_order)`。数值列**不声明类型**（无亲和性，int / float 原样存取；声明 `REAL / NUMERIC / ANY` 都会改类型）。代价：未知字段丢失须先核实真实数据里不存在；`ship_signatures` 仍建议整条 JSON。

不做：内置常量表（`CITY_PRICES`、`REFINERIES`、`SIGNATURES`、`LOCATIONS` 等）入库；用户数据（`ore_log.json`、`my_signatures.json`、`observations.csv`）入库。

## 8. 更新流程

- `uex.refresh()`：`write_json(OUT)` 已在 `gamedata.updating()` 里（批 1），**保持**。
- `mining_rocks.json`、`ship_signatures.json`、`mining_spots.json`：只随 `data_pack.install()` 来（已在 `updating()` 里）。本快照里没有别的写入点（数据构建脚本在本机构建目录，不在运行时）。
- `data_pack.clear_caches()`：批 5 之后 `rocks_table / spots / ships` 按 `data_version` 失效，不靠它；`_clear("mining.shipsig", "ships")` 变空操作；`apply_live` 照旧在这里被调、从库重读。
- `rocks_stamp()` 不再依赖文件 mtime：`data_pack.install()` 出口重建后 `version()` 变 → 消费方重算。

## 9. 批 5 开工前必须补的核对（控制台 2026-11-02 已核的标 ✔）

- ✔ 真实 `mining_rocks.json`：顶层只有 `tiers / ores / areas / contains` 四段，都是 dict；`ores[*]` 只有 `sig`(int) / `tier`；`tiers[*]` 只有 `p_cluster`(float) / `sizes`；`areas` 的百分比是 float；没有空地点。JSON 列原样存，类型不变。原文：顶层键集合；`ores[*]`、`tiers[*]` 的键集合（是否只有 `sig / tier`、`p_cluster / sizes`）；`areas` 里有没有空 dict；百分比、`sig`、`p_cluster` 是整数还是小数（决定 §7 第 2 条用 JSON 列还是备选关系表）。
- ✔ 真实 `ship_signatures.json`：顶层 `source / note / ships`；191 条，键 `id / name / full / role / size / cs(3 个数) / em_max / ir_max / em_rest`，`zh` 168 条有；无非 dict 条目。原文：顶层键；`ships[*]` 的键集合与条数；`cs` 是不是都 3 个数；有没有非 dict 条目。
- ✔ 真实 `prices.json.yields`：20 站，值全是 int（正负），没有空站 / 非 dict 站。原文：`value` 的类型（int / float / null）；有没有空站、非 dict 站；站名与 `REFINERIES` 键的重合情况（`" - "` 拆分后）。
- ✔ 全仓 grep：`rocks_stamp` 的调用方是 `app/engines/live.py:480-489`（实时引擎缓存键）、`navigation/navigate.py:202-213`（`mining_spots` 缓存键，批 2 在改）、`tasks/navigation.py:546-573`（先取 `rocks_stamp()` 再算 `area()`，是）；`shipsig.match/describe` 的调用方只有 `tests/test_tools.py::test_ship_signature_match`（文件缺时 skip，不依赖抛异常）和 mining 包内。`mining/gems / quality / quality_tiers / screen` 不读 `data/`。
- `mining/gems.py / quality.py / quality_tiers.py / screen.py` 不读 `data/`。
- 批 2 合入的 `gamedata/mining.py`：`spots()` 的返回类型名和字段名（本矩阵按 `MiningSpot(spot_id, sys, zh, en, kind, area, x, y, z, source_order)` 写）；批 2 的 `navigate.load()` 在库不可用时抛不抛（`area()` 斯坦顿分支 L167-170 没包 `try`）；`gamedata.snapshot()` 嵌套是否确实复用当前线程快照。
- ✔ `gamedata.version()` 在快照外每次读 `current.json`（171 字节，~50 µs）；`live.py` 每帧调一次 `rocks_stamp()` 可接受，但 Task 5 性能项要测；若超预算在 `gamedata/_db.current_version` 加按文件 mtime 的缓存（找控制台，公共层）。原文：`rocks_stamp()` 在雷达热路径上，若每次读文件要在 topic 里缓存或改由调用方降频（性能项，不改语义）。
- ✔ `apply_live` 在 `clear_caches` 里排在 `refresh()` 之前：`snapshot()` 每次读清单、代号变了就换连接（`_db._thread_conn`），绑定的是新清单，没问题。原文：确认 `ensure() + snapshot()` 绑定的是新清单而不是本线程缓存的旧连接。
