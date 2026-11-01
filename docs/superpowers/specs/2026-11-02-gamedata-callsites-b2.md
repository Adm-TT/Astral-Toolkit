# 游戏数据层 批 2 调用点矩阵（starmap / position / transit / navigate / 地名对照）

日期：2026-11-02　基准分支：`1.1.4-beta.1-database`　状态：公共层先行 PR 的依据；批 2 开工前逐行复核“调用模块”列

读法同批 1 矩阵。本批源文件有 9 个，全部是坐标 / 地名 / 设施 / 电梯数据；消费方式以“整表遍历算距离、按名字 / 内部名精确找点、地名转中文”为主，几乎没有按条件筛选。

## 0. 使用方式概览（决定表怎么建）

| 模块 | 怎么用数据 | 迁移方式 |
|---|---|---|
| `starmap.load()` | 返回整个 dict `{bodies, pois, points}`；`navigate`、`transit`、`celestial`、`position`、`mining_area`、`shops.shop_point` 都拿这个 dict 遍历或传参 | 保留 `load()` 的 dict 形状（从库组装，按版本缓存一份），消费方本批不改签名；热点查找（`find_point`、`poi_zh`、`place_name`、`city_places`、`station_lifts`）改索引查询 |
| `position.find_point(name/internal)` | 线性扫 `points`（393 条）按规范化名或内部名精确匹配 | `points` 表加 `norm_name`、`internal_lower` 两列索引 |
| `navigation/names.poi_zh(name)` | 合并 `places_zh` + `places_extra_zh`（后者覆盖）成 7.7k 条 dict，按规范化键查 | `place_names` 表：`norm_key → zh`，导入时按“后读覆盖”合并好 |
| `position.place_name(code)` | `places_zh.json` 按前缀找最短键；`place_codes_zh.json` 精确键；`localization.read_ini()`（汉化包 global.ini，**用户数据，不入库**） | `place_names` 表上 `LIKE 'prefix%' ORDER BY length(norm_key)`；`place_codes` 表精确；ini 部分留在原代码 |
| `transit.city_places()` | `cached_json` + `_city_rows` 变换（校验坐标、去重 id、同名加序号、`@sys` 空间点） | **变换在导入时做一次**，表里存变换后的行；读出来还是同样的 dict 列表（`t="City"`、`qt=0` 等常量列不存，读时补） |
| `transit.station_lifts()` | `cached_json` + `_lift_rows` 整站校验，按站名取整站嵌套结构，路由算法在嵌套结构上跑 | 每站存一行：`station_key`、`station`、`sys`、`space`、`ok`、`worst_m`，加一列 `payload_json`（校验通过的整站 JSON）。读出来 `json.loads` 一次按版本缓存。**这是本批唯一允许的 JSON 列**，原因：路由代码消费的是深嵌套树，拆表没有查询收益、只有重组成本 |
| `transit.amenity_targets(kind)` | 遍历 `place_amenities`（258 条），按 `kinds` 筛，再对 `ref.poi/point/internal` 回查星图 | `amenities` 表 + `amenity_kinds(amenity_id, kind)` 子表（按 kind 筛走索引）；`ref` 三种引用拆成三列 |
| `navigate.mining_spots()` | `mining_spots.json`（109 条）按 mtime 缓存 + 坐标 /1000 变换 | `mining_spots` 表；批 5 也读它（`mining_area._spots_raw`），所以本批建表、批 5 直接用 |
| `celestial` | 读的是 `userdata` 的校准文件和太阳系文件，不是游戏数据 | **不迁** |
| `print_spots.json` | 批 3（制造）用 | 不在本批 |

## 1. starmap.json（280 KB）

结构：`{fetched, …其他顶层元数据键, bodies: {名: {sys, x, y, z, rot, adj, r, om, grid}}, pois: [{b, n, t, x, y, z, qt}] ×1961, points: [{n, i, sys, t, x, y, z}] ×393}`。`starmap_fixes.json`（现为 `{}`）：`{点名: [x, y, z]}` 覆盖 `points` 坐标（`_apply_fixes`，L179-204，只接受有限浮点三元组）。

| 源字段 | 读它的函数 | 转换 | 目标表.列 | 顺序 |
|---|---|---|---|---|
| `bodies[name]` 9 个数值 | `celestial.*`（自转相位用 `rot/adj`）、`navigate.where_am_i/_find_body`、`transit.target_system`、`mining_area` | 原样 float | `bodies(name PK, sys, x, y, z, rot, adj, r, om, grid, source_order)` | dict 顺序 |
| `pois[i]` | `transit.amenity_targets`（按 `_norm(n)` 首个）、`navigate.search`（遍历）、`transit.nearest` | 原样 | `pois(id, b, n, t, x, y, z, qt, norm_n, source_order)`；索引 `(b)`、`(norm_n)` | 列表顺序 |
| `points[i]` | `position.find_point`（按 `i` 小写 / `n` 规范化）、`shops.shop_point`、`transit.amenity_targets`（`pts` by `n`、`pts_id` by `i`）、`navigate.space_points` | `_apply_fixes` 先套坐标修正 | `points(id, n, i, sys, t, x, y, z, norm_n, i_lower, source_order)`；索引 `(norm_n)`、`(i_lower)` | 列表顺序；`find_point` 是**首个**命中 |
| `fetched` | `navigate` L443 打印“星图数据：starmap.space（日期）” | 入 `meta`：`starmap_fetched` | — |
| 其他顶层元数据键 | 没人读 | 不入库 | — |

**`points.i` 不唯一**（真实数据里 `ab_pyro_final_set_dungeon-001` 对应两个不同的点），所以 `i_lower` 不是主键；`find_point(internal=…)` 取首个 → 查询必须 `ORDER BY source_order LIMIT 1`。同理 `norm_n` 也按首个。

`position.find_point` 的规范化：`re.sub(r"[^a-z0-9]", "", name.lower())`；`transit` 用的 `_norm` 来自 `navigation/names.py:118`，已核对：两者是同一规则（`re.sub(r"[^a-z0-9]", "", s.lower())`），`norm_n` 一列够用。

## 2. city_places.json（447 KB，928 条）

结构：`[{city, body, cat, en, src, zh, zh_src, area, x, y, z, kinds[], site_en, site_zh, line?, stop?, up?[3], space?, sys?}]`。

| 源字段 | 读它的函数 | 转换（`transit._city_rows` L43-107） | 目标表.列 |
|---|---|---|---|
| 整条 | `transit.city_places()` → `city_targets/site_at/site_nearest/city_route/_metro_lines` | 过滤：无 `body`（且非 `space+sys`）或无 `en` 或坐标非有限 → 丢；`id = src or "#i"`，重复加 `+`；同 `(city, zh)` 第二次起加 ` 2`、` 3`；`b = "@"+sys`（space）或 `body`；`city_zh = site_zh or CITY_ZH[city]`；`up` 三元组 | `city_places(id PK, b, n, zh, x, y, z, cat, area, city, city_zh, site_en, line, stop, space, sys, up_x, up_y, up_z, source_order)` + `city_place_kinds(place_id, kind)`；索引 `(city)`、`(city, line)` |
| `zh_src` | 没人读 | 不入库 |
| 常量 `t="City"`、`qt=0` | `_city_rows` 补 | 不存，读时补 |

## 3. place_amenities.json（53 KB，258 条）

结构：`[{en, zh, kinds[], rec, ref: {poi | point | internal}}]`。

| 源字段 | 读它的函数 | 转换 | 目标表.列 |
|---|---|---|---|
| `en, zh, rec` | `transit.amenity_targets` L170-242 | strip；`rec.lower()` 与 `city_targets(kind)` 的 `city` 比对 | `amenities(id, en, zh, rec_lower, ref_poi, ref_point, ref_internal, source_order)` |
| `kinds[]` | 同上，`kind in kinds` 筛 | — | `amenity_kinds(amenity_id, kind)`；索引 `(kind)` |
| `ref.*` | 回查 `pois`（`_norm`）/ `points`（`n`）/ `points`（`i`） | 读时回查，不在导入时解析（星图和设施可能分开更新） | 三列原样 |

## 4. station_lifts.json（663 KB，40 站）

结构：`{version, hangar_lift_local: {Large/Medium/Small: {lift[3], spawn[3]}}, stations: {key: {station, ok, worst_m, areas{}, lifts[], hangars[], places{}, sys, space}}}`。

| 源字段 | 读它的函数 | 转换（`transit._lift_rows` L570-627） | 目标表.列 |
|---|---|---|---|
| `stations[key]` 整站 | `transit.station_lifts()` → `zone_kind/_station_points/_hangar_lift/station_route/station_leg` | 整站结构校验（`ok is False` 丢；`areas/places/lifts/hangars` 类型与坐标有限性逐项查），不通过整站丢 | `station_lifts(station_key PK, station, sys, space, worst_m, payload_json, source_order)`；`payload_json` = 校验通过的整站原样 JSON |
| `hangar_lift_local`、`version` | 代码里没人读（grep 为空） | — | 不入库 |

## 5. places_zh.json（378 KB，7.7k）+ places_extra_zh.json（37 KB，899）+ place_codes_zh.json（74 KB，1.4k）

结构：三个都是 `{键: 中文}`。`places_zh` 键是汉化包里的地点键（有脏数据：`94824nnn…: "患者 ID\n\n"`、`target: "可选：…"`）；`places_extra_zh` 键是规范化英文名；`place_codes_zh` 键是小写地点代码。

| 源 | 读它的函数 | 转换 | 目标表.列 |
|---|---|---|---|
| `places_zh` + `places_extra_zh` | `navigation/names.poi_zh` L122-160（合并，**extra 覆盖**，只收非空字符串）；`position._places_zh/_zh_name`（只读 `places_zh`，按 `k` 或去 `station` 后缀的 `k`）；`position.place_name` 按前缀取最短键；`stockplaces.places` 经 `poi_zh` | 合并规则按 `poi_zh`；`position` 只读 `places_zh` 这一点是差异——批 2 核对两处是否可统一（若 `position` 必须只看 `places_zh`，表里加 `src` 列区分） | `place_names(norm_key PK, zh, src, source_order)`；索引默认主键；前缀查询用 `WHERE norm_key LIKE ? ORDER BY length(norm_key) LIMIT 1` |
| `place_codes_zh` | `position` L184-195（`table.update` 后再被 `read_ini()` 的值覆盖） | 键已是小写 | `place_codes(code PK, zh, source_order)` |
| 脏键（含 `nnn`、`\n`） | 现在都原样进 dict，查不到就是查不到 | 导入**不过滤**，保持行为 | — |

`read_ini()` 读用户汉化包，是运行时用户数据，留在 `position` 原处，不入库。

## 6. mining_spots.json（21 KB，109 条）

结构：`[{id, sys, zh, en, kind, area, x, y, z}]`。

| 源字段 | 读它的函数 | 转换 | 目标表.列 |
|---|---|---|---|
| 整条 | `navigate.mining_spots()` L197-271（坐标 `/1000`，再和石头表、星图合并，缓存键含 `rocks_stamp()` 和 `_data_stamp`）；`mining_area._spots_raw()`（原样，每次读盘——批 5） | 表里存**原始**坐标（米），`/1000` 留在 `navigate` 的变换里（两处消费单位不同） | `mining_spots(id PK, sys, zh, en, kind, area, x, y, z, source_order)` |

## 7. 更新流程

- `starmap.update()`：写 `starmap.json`（`compact()` 后 `write_json`），`_apply_fixes` 在读时套；本批把 `update()` 包进 `gamedata.updating()`。
- `city_places / place_amenities / station_lifts / places_extra_zh / mining_spots`：随数据包 `data_pack.install()` 来（已在更新边界内）。
- `places_zh.json`、`place_codes_zh.json`、`name_aliases.json`、`zh_names.json`：由 `localization.rebuild()`（L270-282）用 `write_json` 写，它持有 `BUILD_LOCK`——本批给 `rebuild()` 最外层套 `gamedata.updating()`，**顺序必须是 updating 在外、BUILD_LOCK 在内**（与 `data_pack.install` 一致，否则死锁）。

## 8. 公共层先行 PR 要做的（schema 2）

新表：`bodies`、`pois`、`points`、`city_places`、`city_place_kinds`、`amenities`、`amenity_kinds`、`station_lifts`、`place_names`、`place_codes`、`mining_spots`。`SOURCES` 加 9 个可选源。`_import` 新增 `import_starmap / import_city_places / import_amenities / import_station_lifts / import_place_names / import_mining_spots`，变换逻辑**直接 import 复用** `transit._city_rows`、`transit._lift_rows`、`starmap._apply_fixes`（不抄）。`SCHEMA_VERSION = 2`、`IMPORTER_VERSION = 2`。

## 9. 批 2 开工前必须补的核对

- `position._places_zh` 只读 `places_zh` 而 `poi_zh` 合并 extra：是现状差异还是 bug。
- `navigate.search`、`transit.nearest` 对 `pois` 遍历的排序键（同距离时的次序）。
