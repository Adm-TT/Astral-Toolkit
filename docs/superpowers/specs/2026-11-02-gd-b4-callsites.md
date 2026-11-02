# 游戏数据层 批 4 调用点矩阵（loot 掉落）

日期：2026-11-02　基准分支：`1.1.4-beta.1-database`　状态：定稿（控制台 2026-11-02）；§6 的公共层内容已随 schema 4 合入基线；批 4 开工前逐行复核“调用模块”列

读法同批 1 / 批 2 矩阵。本批只有一个模块 `crafting/loot.py`（557 行），入库的源只有 `loot_index.json`（已在 schema 1 入库为 `loot_rows`），外加 `wiki_items.json` 里的类名（`_wiki_classes` 用）。掉落明细（`loot_details.zip` + `data/loot/*.json`）**不入库**。消费方式以“整表折叠名精确 / 部分匹配”和“按类名前缀筛开采点”为主。

## 0. 使用方式概览（决定表怎么建）

| 函数（行号指 `crafting/loot.py`） | 怎么用数据 | 迁移方式 |
|---|---|---|
| `load_index(auto)` L76-86 | 读 `loot_index.json` 整个 dict `{version, rows}` 存模块全局 `_index`；`auto=True` 且没有文件时联网 `update()` | **保留原样**（更新流程的一部分，同批 1 的 `shops.load()`）：`update()` 的版本兜底、`trade/names._known_names`（批 6）、`tasks/system/about.py` 还在用。本批之后 `find / detail / mine_info` **不再调用它**（`mine_info` 的联网补下载分支除外，见 §1 末） |
| `_folded_rows(idx)` L92-102 | 每行 `(u, en, zh, rar, _fold(en), _fold(zh), cls.lower(), n or 0)`，按 `idx` 对象身份缓存在 `_folded` | 删除。折叠在**导入时**算好进库（`norm_en / norm_zh / cls_lower` 三列，见 §6）；整表折叠行由 `gamedata.loot.rows()` 按 `data_version` 缓存一份（`VersionCache`） |
| `find(name_en, name_zh)` L129-159 | 线性扫全部行：精确（`fe == ke` 或 `fz == kz`）→ 有就按 wiki 类名 / 变体 / `n` 挑；没有再看部分匹配（`ke` ≥6 前缀、`ke` ≥5 子串、`kz` ≥3 子串），去变体后取前 5 | 精确命中走索引 `exact(ke, kz)`；部分匹配在缓存的 `rows()` 上 Python 扫（`startswith / in` 不走 B-tree，1.3 万行可接受，同设计 §3.1 对 `find()` 的约定）。挑选、排序逻辑原样保留在 `crafting/loot.py` |
| `_wiki_classes(name_en)` L113-126 | 扫 `itemsearch.wiki_items()`（读 `wiki_items.json`），`_fold(w.n) == _fold(name_en)` 的 `cls` 和 `alt[]` 全收（小写），减去空串；出错返回空集 | 新表 `wiki_classes(norm_n, cls_lower)`（§6）；**不能**用 `item_source_ids('class')` 代替，原因见 §3 |
| `mine_info(key, top, online)` L394-437 | `load_index(online)`；`_folded_rows` 上按 `cls.startswith(want) and not cls.startswith(skip)` 筛开采点岩石；每个岩石 `detail()` | `gamedata.loot.by_cls_prefix(want)`（`cls_lower` 列，**按字面前缀**，不能用 `LIKE`——类名里的 `_` 是 `LIKE` 通配符），`skip` 在 Python 里排除；`detail()` 不变 |
| `detail(uuid, online)` L289-323 | `load_index(False).get("version", "4.10.2LIVE")` 当版本：拼整包版本比对、缓存文件名 `{version}_{uuid}.json`、网址 | 版本改读库里的 `meta`（§6 的 `loot_index_meta`）；明细读取 / 在线抓取 / 写缓存**原样**，不入库、不套 `updating()`（§2） |
| `summary(d, top)` L329-360 | 纯函数，输入是明细 dict | 不动 |
| `info / text` L486-557 | 组合 `instance_ore / ship_mineral / find / detail / summary` | 函数体不动（只经由 `find / detail / mine_info` 间接迁移）；**文本输出逐字不变**由基线工具覆盖 |
| `instance_ore / ship_mineral / ship_info` L386-483 | 代码内常量 `INSTANCE_ORES / _INSTANCE_ZH`；`mining.data.SIGNATURES`、`mining.locations.where`（批 5 的数据） | 不动 |
| `update / latest_version / _get` L26-73 | 联网下 manifest + search.json，`write_json(INDEX)` 已套 `gamedata.updating()`（收口 1） | **保持**，不再改 |
| `details_version / _from_zip / close_bundle / crawl_details` L173-278 | 读写 `loot_details.zip` | 不动 |

## 1. loot_index.json（约 1.7 MB，1.3 万行）

结构：`{version: "4.10.2LIVE", rows: [[uuid, en, cls, rarity, n, zh], …]}`。已入库：`loot_rows(uuid PK, en, cls, rarity, n, zh, source_order)`，导入 `_import.import_loot`：`cls / rarity / zh` 为 `None` 时存 `''`，`n` 为 `None` 时存 `0`，**`insert or ignore`**（同 uuid 第二行起被丢）。

| 源字段 | 读它的函数 | 转换 | 目标表.列 | 顺序 |
|---|---|---|---|---|
| `rows[i][0]` uuid | `find` 输出首位；`info` → `detail(u)`；`mine_info` → `detail(r[0])` | 原样 | `loot_rows.uuid`（已有） | `source_order` |
| `rows[i][1]` 英文名 | `find`：`_fold(en)` 精确 / 前缀 / 子串；`_wiki_classes(exact[0][1])`（`name_en` 为空时） | `crafting.loot._fold`（小写、`l→i`、只留 `a-z0-9` 和 CJK）。**不做**中英填反对调（那是 `import_items` 的规则，`find` 读的是原样） | `loot_rows.en`（已有）+ **新列 `norm_en`**，索引 | — |
| `rows[i][5]` 中文名 | `find`：`_fold(zh)` 精确 / 子串（≥3）；`info` 输出 `name = zh or en` | 同上 `_fold` | `loot_rows.zh`（已有）+ **新列 `norm_zh`**，索引 | — |
| `rows[i][2]` 类名 | `find`：`cls.lower()` 判 `_VARIANT`、与 wiki 类名求交；`mine_info`：前缀筛 | `(cls or "").lower()` | `loot_rows.cls`（已有）+ **新列 `cls_lower`**，索引 | 前缀筛结果按 `source_order` |
| `rows[i][3]` 稀有度 | `find` 输出第 4 位 | 原样 | `loot_rows.rarity`（已有） | — |
| `rows[i][4]` n | `find`：精确命中后 `pick.sort(key=-n)`（**稳定排序**，同 `n` 保持源顺序） | `n or 0` | `loot_rows.n`（已有） | 精确集先 `ORDER BY source_order`，再 Python 稳定排序 |
| `version` | `detail`（`idx.get("version", "4.10.2LIVE")`）、`update`（兜底版本）、`about.py`（显示） | 原样 | **新 meta 键 `loot_index_meta`**（§6） | — |

`find` 的两类匹配语义（逐条照搬，不借迁移改）：

- 精确：`(ke and fe == ke) or (kz and fz == kz)`。空的 `ke / kz` 不参与（SQL 写成 `(? <> '' and norm_en = ?) or (? <> '' and norm_zh = ?)`）。
- 部分：`(len(ke) >= 6 and fe.startswith(ke)) or (len(ke) >= 5 and ke in fe) or (len(kz) >= 3 and kz in fz)`；只在没有精确命中时才看；先 `_VARIANT` 过滤，再取前 5（源顺序）。
- 精确命中后：`good = _wiki_classes(name_en or exact[0][1])`（`exact[0]` 是**源顺序第一个**，排序前取）；`pick = 有 good 类名的 or 非变体的 or 全部`；按 `-n` 稳定排序。
- 没有精确命中且 `name_en` 非空且 `_wiki_classes(name_en)` 非空 → 返回 `[]`（物品查询里本来就有这件，不拿“开头像”的别的东西顶）。

“有没有掉落索引”的判断要分清三态（`mine_info` 依赖它）：

| 现状 | 旧行为 | 库里怎么判断 |
|---|---|---|
| 没有 `loot_index.json` | `load_index(False)` → `None`：`find` 返回 `[]`；`mine_info(online=True)` 联网 `update()` 再查，`online=False` 返回 `None` | meta 里**没有** `loot_index_meta` 键 |
| 有文件、`rows` 为空 | `idx` 真值：`find` 返回 `[]`；`mine_info` 不联网，返回 `groups: []` 的 dict | 有 meta 键，`loot_rows` 为空 |
| 有文件、JSON 坏 | 旧代码 `json.loads` 抛 → `find` 往外抛 | 可选源坏 = 当作没有（`_sources` 规则）→ 第一行；**行为变化**，属“原代码缺陷”，PR 里写明 |

`mine_info(online=True)` 在“没有索引”时仍走 `load_index(True)`（打印 + `update()`，`update()` 已在 `updating()` 里会重建库），之后**重新查库**；`update()` 失败或重建失败 → 返回 `None`（旧代码在重建失败时还能用内存里的 `_index`，这是唯一可接受的差异，写进 PR）。

## 2. loot_details.zip + data/loot/*.json（明细，不入库）

结构：zip 内 `version.txt` + `<uuid>.json` ×约 1.3 万；`data/loot/{version}_{uuid}.json` 是在线现查的缓存。

| 源 | 读它的函数 | 处理 |
|---|---|---|
| `loot_details.zip` | `_from_zip`（按 mtime 重开、版本不符当没有）、`details_version`、`close_bundle`；`data_pack._update_loot`（替换整包）、`data_pack` 打包 L429-435 | **不入库、不动** |
| `data/loot/*.json` | `detail()` 读；在线抓取后 `write_json(f, d)` | **不入库、不动** |

**`detail()` 的在线抓取写文件不套 `gamedata.updating()`**，理由：

1. 明细文件不在 `_sources.SOURCES` 里，不参与 `data_version`；写它不需要、也不会触发建库。套了反而每抓一件就要拿数据目录跨进程写锁、在出口跑一次 `rebuild_if_needed()`（读全部源算哈希，真实数据 50–70 ms）。
2. `detail()` 由 F8 悬停、物品页后台线程调；`updating()` 会在“更新数据”装包期间把这些线程卡在写锁上，违背“查询不卡死”。
3. 写入本身已经是 `paths.write_json` 的临时文件 + `replace`，坏文件有 `ValueError → unlink` 兜底，不需要库的一致性保证。
4. `_update_loot` 替换整包同理不在边界内（现状如此，本批不动）。

**与设计文档的出入**：设计 §4.2 把 `loot.detail` 列进了统一更新边界入口。本矩阵的结论是“明细不是库的源，不进边界”，需控制台在设计文档变更记录里补一行。

`loot_detail_index(uuid, source, mtime)` 表（摸底时的建议）**不采纳**：现在没有任何调用方需要“本地有没有这件的明细”（`summary / info` 都是先 `detail()` 再看结果）；而且在线补抓写的文件不在更新边界里，这张表一定会过期。

## 3. wiki_items.json（只看 `_wiki_classes` 用到的部分）

结构：`{items: [{n, t, s, d, cls, alt[], mfr, …}], version, source, fetched}`。已入库的只有 `items / item_source_ids('class')`，`alt` 没入库（批 1 矩阵：`wiki_items.alt` 未入库）。

| 源字段 | 读它的函数 | 转换 | 目标表.列 |
|---|---|---|---|
| `items[i].n` | `_wiki_classes`：`_fold(w.get("n")) == _fold(name_en)` | `crafting.loot._fold`（**不是** `itemsearch.en_key`）；`n` 缺失折叠成 `''` 也存（旧代码 `_fold(None) == ''`，保持） | **新表** `wiki_classes.norm_n`，索引 |
| `items[i].cls` | 同上，收 `cls.lower()` | 小写；空串不存（旧代码最后 `- {""}`） | `wiki_classes.cls_lower` |
| `items[i].alt[]` | 同上，逐个收 `.lower()` | 小写；空串不存 | `wiki_classes.cls_lower`（与 `cls` 同列，多行） |

**为什么不能复用 `item_source_ids(source='class')`**：① 它没有 `alt`；② 主键是 `(source, external_id)` + `insert or ignore`，同一类名只映射到首个物品；③ 只登记了导入后**保留下来**的物品（`ek in kept`）；④ 物品身份用 `en_key` 折叠，`_wiki_classes` 用 `loot._fold`（`l→i`、保留 CJK），两者对同一名字可能不等。四条任何一条都会让“同名多实体挑哪个”变掉。

`_wiki_classes` 返回集合，顺序无关；整个函数 `except Exception → set()` 的吞错**保留**（`find` 依赖它不抛）。

## 4. 代码内常量

| 常量 | 位置 | 处理 |
|---|---|---|
| `INSTANCE_ORES`、`_INSTANCE_ZH` | L365-383 | 不动 |
| `_VARIANT` 正则 | L107-110 | 不动（`find` 里照用） |
| `PLACED`、`BASE`、`UA`、`_UUID_RE`、`_VER_RE` | 各处 | 不动 |
| `INDEX`、`CACHE_DIR`、`DETAILS` | L16-17、L168 | 不动（`update / load_index / detail / data_pack` 还在用；测试里 monkeypatch 它们） |

## 5. 调用方

| 调用方 | 调的什么 | 本批是否改 |
|---|---|---|
| `crafting/acquire.py` L95-99 | `loot.text(name_en, name_zh)` | 不改（签名、文本不变） |
| `crafting/acquire.py` L280-286 | `loot.info(name_en or name, name_zh, online=loot_online)`；前面 L242 用 `itemsearch` 的 `hit["loot"]`（`items.has_loot`，批 1 已走库）决定要不要查 | 不改。注：两次查询各开一个快照，更新数据瞬间可能分属两代——批 4 不处理（acquire 不在本批） |
| `tasks/trade.py` L223-230 `item_loot` | `loot.info(name, zh)`（在线） | 不改 |
| `tasks/hover.py` L213-215 | `loot.info(info["name"] or en, zh)`（在线） | 不改 |
| `trade/console.py` L575-604 `loot_source` | `loot.info(..., top=2, online=False)` | 不改 |
| `trade/console.py` L611-619 `finder_flow` | `loot.find(...)` 取 `lh[0]` 的 `(u, en, zh, _)` | 不改。console 里**没有**用 `loot._folded` |
| `tasks/system/about.py` L61-64 | `loot.load_index(False).get("version")` 显示掉落数据版本 | **不改**（`load_index` 保留；改成读 meta 是一行事，留给批 6 / 清理批随 `load_index` 一起收，避免本批碰 tasks/） |
| `trade/names.py` L62-65 `_known_names` | `loot.load_index(False)["rows"]` | **不改**（批 6） |
| `trade/gamekey.py` L31-35 | 直接读 `DATA / "loot_index.json"`（按类名首个 uuid） | **不改**（批 6） |
| `update/data_pack.py` L202-205 `clear_caches` | `loot._index = None`；`loot._folded.update(of=None, rows=[])`（同一个 `try/except Exception` 里） | **不改**。批 4 保留 `_index`（`load_index` 还在用）；`_folded` 保留成**无人读取的空壳**（注释写明“只给 data_pack.clear_caches 写，整合清理时随这两行一起删”），这样不碰 `data_pack.py`。两行由控制台在批 6 合并后的整合清理里删 |
| `update/data_pack.py` L339-358 `_update_loot`、L429-435 打包 | `details_version / close_bundle / DETAILS` | 不改 |
| `update/data_pack.py` L34 `FILES` | 数据包含 `loot_index.json`，`install()` 已在 `updating()` 里（L256） | 不改 |
| `run.py`（本机无此文件） | `loot.update()` | 不改；`update()` 已在 `updating()` 里 |
| `tests/test_gamedata.py` L825-834 | monkeypatch `loot.INDEX / loot._index`（批 1 的 itemsearch 旧实现对照） | 不改；`INDEX / _index` 保留即可 |

## 6. 公共层先行 PR 要做的（已随 schema 4 合入，表定义以 `gamedata/_schema.py` 为准）

批 4 会话**不改** `gamedata/_*.py`；下面四项控制台已做进 schema 4。

1. **`loot_rows` 加三列**：`norm_en TEXT NOT NULL`、`norm_zh TEXT NOT NULL`、`cls_lower TEXT NOT NULL`；索引 `idx_loot_rows_norm_en(norm_en)`、`idx_loot_rows_norm_zh(norm_zh)`、`idx_loot_rows_cls_lower(cls_lower)`。`import_loot` 里 **import 复用** `crafting.loot._fold`（同 `shops._fold` 的做法，不抄），对源里的原样 `en / zh` 折叠（不做填反对调）；`cls_lower = (cls or "").lower()`。
2. **meta 新键 `loot_index_meta`**：`loot_index.json` 存在且解析成 dict 时写 `json.dumps({"version": data["version"]})`（源里有 `version` 键时）或 `"{}"`（没有时），原值类型原样保存；文件缺失 / 坏掉时**不写这个键**。批 4 用它区分 §1 的三态，并给 `detail()` 取版本。
3. **新表 `wiki_classes`**：`wiki_classes(norm_n TEXT NOT NULL, cls_lower TEXT NOT NULL, source_order INTEGER NOT NULL)`，索引 `(norm_n)`；来自 `wiki_items.json` 的 `items[i].cls` 和 `items[i].alt[]`，规则见 §3。批 6 的 `gamekey` 以后也可以用。
4. `SCHEMA_VERSION`、`IMPORTER_VERSION` 各加 1。`SOURCES` **不加**（两份源都已在清单里）。

条件项——**已在真实数据上核过（2026-11-02）：13457 行、uuid 无重复、每行 6 列、`cls / rarity / zh / n` 无 `None`（空串有：cls 63、rarity 7858、zh 1584），`wiki_items` 带 `alt` 的 631 件 / 6730 条 alt。第 5、6 条都不触发，不改**：

5. 若真实 `loot_index.json` 里有**重复 uuid**：`insert or ignore` 会丢后面的行，而旧 `find` 两行都扫——需把 `uuid` 从主键改为普通索引、主键用 `source_order`。没有重复则不动。
6. 若真实数据里 `cls / rarity / zh` 有 `None`：库里存成了 `''`，`find` 输出的 `zh / rarity` 会从 `None` 变 `''`（`json` 基线里 `null` → `""`）。下游全是 `zh or en` / 真值判断，显示不变；二选一：列改成可空原样存，或记为“允许差异”。

不做：`loot_detail_index` 表（§2）；明细入库。

## 7. 更新流程

- `loot.update()`：`write_json(INDEX)` 已在 `gamedata.updating()` 里（收口 1），**保持**；`update()` 末尾 `_index = data` 也保持（批 6 的读者还靠它）。
- `crawl_details()`：作者用，内部调 `update()`（已在边界里），写的是 zip（不是源），不动。
- `detail()` 在线抓取写 `data/loot/`：**不进边界**，理由见 §2。
- `data_pack.install()`：已在边界里，装进来的 `loot_index.json` 出口统一重建。
- `data_pack.clear_caches()`：批 4 之后 `find / mine_info / detail` 不靠它刷新（`rows()` 按 `data_version` 失效）；那两行保留无害。

## 8. 批 4 开工前必须补的核对

- 真实 `loot_index.json`：行数 = `select count(*) from loot_rows`？（不等 = 有重复 uuid → §6 第 5 条）；`cls / rarity / zh / n` 为 `None` 的行数（§6 第 6 条）；每行是否都是 6 列（旧 `_folded_rows` 按 6 列解包，导入按 `len > 5` 兜底）。
- `wiki_items.json` 里 `alt` 的实际分布（有多少物品带 `alt`），确认 `_wiki_classes` 在真实数据上用得到 alt。
- `run.py` 里对 `loot` 的全部调用（本机没有这个文件），确认除 `update()` 外没有直接读 `_index / _folded / load_index`。
- 批 3（crafting）是否也要动 `schema` 版本号——两个公共层 PR 的版本序号由控制台排，避免撞号。
