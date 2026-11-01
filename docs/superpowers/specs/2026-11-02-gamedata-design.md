# AT 游戏数据层分离设计（第一期：本地数据库 + 统一查询包）

状态：修订版 v2（外部复审意见已合并），设计方向确认；接口细节以地基阶段源码核对和试点验收为准
日期：2026-11-02
项目：Astral Toolkit（AT），Python，Windows 桌面，星际公民辅助工具
范围：仅第一期。本文件是设计，不代表代码已实现或实机测试已通过。

## 变更记录

每次方案有改动都在这里加一行，并在正文对应位置修改；复审时先看这里。

| 日期 | 改动 | 原因 |
|---|---|---|
| 2026-11-02 | 初稿：三节 + 落地方式 + 验证 + 风险 | — |
| 2026-11-02 | v2，合并外部复审意见：① 单文件原子替换改为“版本化库文件 + 当前版本清单”；② 新增操作级快照 `snapshot()`；③ 版本语义拆成 `data_version` / `generation_id` / `build_time`；④ 不再承诺产物字节一致，改为内容版本可复现；⑤ 建库逻辑移入包内 `_build.py`，`tools/` 只做命令行壳；⑥ 迁移改为“地基 → 批 1 试点 → 其余并行”，明确批 3/4 依赖批 1、批 5 依赖批 2；⑦ OCR 候选用轻量 `items.candidates()`；⑧ `find()` 子串搜索不承诺走索引；⑨ 更新边界加跨进程写锁、最外层只重建一次；⑩ 待审 4 问全部定案（§7.1） | Windows 下替换被打开的 SQLite 文件会失败，原稿“原子替换”不成立；其余为复审指出的合同漏洞 |
| 2026-11-02 | v2 未采纳的复审意见：① 多文件更新的暂存 / 批次恢复协议（§4.2 只保留写锁 + 逐文件原子写 + 失败保留旧库，完整批次恢复列为二期候选）；② 价格一律 `Decimal`（改为按源数据实际类型定，见 §3.1）；③ 删除“变更记录”表（已恢复） | 第一期控制复杂度；现有更新器本就是逐文件写，批次恢复是现状之外的新需求 |
| 2026-11-02 | 原“第七个清理 PR”从本文件移出，单独排期 | 与数据层迁移无关，不混在一起审 |
| 2026-11-02 | v3，按源码复审纠正现状描述（已逐条对源码核实）：① 撤回“navigate 按值导入导致缓存过期”——`navigate.py:60` 的 `_data` 是死导入，实际走 `load()`；② 撤回“uex 只在 import 时应用”——`data_pack.clear_caches()` 会再调 `uex.apply_live`；③ “全部线性扫描”改为“商店/星图/城市点/wikelo/crafting 线性扫描，物品搜索已有字符索引和三元组索引”；④ 新增已知缺陷：`itemsearch.py:78` 缓存键漏了 `wiki_items.json`、`name_aliases.json`，只更新这两个文件时索引不刷新；⑤ 新增约束：与用户库存库 `dubhe_inventory.db`（`trade/storage.py`）严格分开；⑥ 新增地基任务：物品身份映射（uex:/scm:/local: 来源编号、游戏类名、实体 uuid）；⑦ 建库发布接在现有 `paths.cached_json / write_json / clear_json_cache / CACHE_HOOKS` 上，不另起一套；⑧ 批 1 试点范围补齐 loot_index、zh_names、name_aliases、wiki_items | 外部复审对照 `release/1.1.4-beta.1` 源码的发现，本文件据此修正 §1.1、§1.3、§2、§4.2、§4.3、§5.1 |
| 2026-11-02 | 地基 PR 实现完成（分支 feat/gamedata-foundation）：包结构、表名、清单字段、入口函数以 `sc_mining/gamedata/` 代码为准。与 §3.1 示例的两处差异：`ShopRow` 按 shops.json 的 7 列原样映射（源里没有 shop_id/place_id/body）；价格是源里的 float 原样。`updating()` 建库失败不抛、记到 `last_error()`。试点批次接口签名在批 1 开工前按调用点矩阵定稿 | 实施反馈 |
| 2026-11-02 | 措辞：§1、§4 里构建输入目录不再写目录名，改指 `paths.BUILD_DIR`（数据来源字样清理） | 清理批 |

---

## 0. 一句话

把散在 20 多个模块里的游戏数据读取，收成一个本地 SQLite 数据层和统一查询包 `sc_mining/gamedata/`。JSON 继续作为源；数据库按版本生成，通过当前版本清单发布；功能模块通过接口查询，同一次业务操作固定使用同一份数据快照。

第一期采用“版本化数据库文件 + 当前版本清单”。不覆盖正在被连接使用的数据库文件；不引入服务器、通用 ORM、增量同步或全文检索。

方案取舍：

| 方案 | 取舍与决定 |
|---|---|
| 继续优化各模块的 JSON 缓存 | 改动小，但解决不了索引、重复对象常驻和访问边界三个问题，未采用。 |
| 固定文件名，关闭全部连接后原子替换 | Windows 下文件被任一连接打开时 `os.replace` 失败；要协调所有线程和多开实例，且替换期间查询阻断，未采用。 |
| 版本化库文件，切换当前版本清单 | 不替换打开的库，在途查询自然完成；代价是要定清楚快照、版本和旧文件回收规则，采用。 |

---

## 1. 现状与问题

### 1.1 数据现状（调研结果）

- 运行时会加载的游戏数据 JSON 约 13 MB，解析后常驻内存约 90 MB。
- 主要数据文件：shops（商店/库存）、starmap（星图：天体、地点、坐标）、city_places、wikelo、crafting、loot、items、mining（矿点/信号）、localization（中英对照）、uex 价格等，20 余个。
- 查询方式：shops / starmap / city_places / wikelo / crafting 是加载进 list/dict 后线性扫描。典型例子：查某物品在哪些商店有货 = for 循环扫整个 shops。物品搜索（`crafting/itemsearch.py`）已经在内存里建了中文字符索引和英文三元组索引，不是线性扫描；迁移必须保留它的候选筛选和排序逻辑。
- 缓存风格有四种并存：
  1. 按文件 mtime 判断是否重读（`paths.cached_json`，以及各模块自己拼的 `file_stamp` 键）；
  2. 模块级全局变量，由 `data_pack.clear_caches()` 统一清，并通过 `CACHE_HOOKS` 让各模块登记清理回调；
  3. 每次调用都重新读文件（含热路径 `mining_area._spots_raw`，采矿区域判断一次读两遍文件，五次判断读十次）；
  4. import 时读一次并应用（`mining/data.py` 末尾调 `uex.apply_live`），`clear_caches()` 时再应用一次。
- 已知缺陷：`itemsearch.py:78` 的索引缓存键只含 `shops.json`、`loot_index.json`、`zh_names.json` 和 `names.table()` 的地址，但建索引时还读 `wiki_items.json` 和 `name_aliases.json`；只更新这两个文件时搜索仍用旧索引。迁移后以数据快照版本统一失效，此缺陷自然消失，列为允许差异。
- 已有基础设施：`paths.cached_json`（按 mtime 的统一 JSON 缓存）、`paths.write_json`（临时文件 + `replace`，Windows 占用时重试）、`paths.clear_json_cache`、`data_pack.CACHE_HOOKS`、数据包安装回退。建库发布接在这套上，不另起一套更新流程。
- 运行时会改写数据文件的模块：`shops.update`、`loot.update / loot.detail`、`starmap.update`、`uex.refresh`、`build_crafting.build`、`wikelo.build`、`localization.rebuild`、`data_pack.install`、`paths.seed_data`。
- `navigate.py:60` `from .starmap import _data` 是死导入（全文件仅此一处），实际读取都走 `starmap.load()`，刷新后能读到新数据；不是缺陷，迁移时顺手删掉该导入即可。
- 物品编号有多套体系（`trade/gamekey.py`）：查价来源编号 `uex:4741` / `scm:43475` / `local:…`、游戏类名、游戏实体 uuid；库存库用 `source_ids` 表把来源编号对到本地 `item_id`。
- 已有一个用户数据 SQLite：`trade/storage.py` 的 `dubhe_inventory.db`（库存、流水、别名、市场缓存，schema 版本 2）。它是用户数据，与本设计无关，新库必须与它分开。
- `data/scmdb`（约 33 MB）和本机构建输入目录（`paths.BUILD_DIR`）只是建数据用的输入目录，运行时模块不读。

以上数据规模、内存占用和调用点来自此前调研，本次修订未重新测量；地基阶段结合当前源码和真实数据核对。

### 1.2 问题

1. 内存：13 MB 文件撑到 90 MB 常驻，且多份重复结构。
2. 查询效率：商店、星图、城市点等是线性扫描，无索引；物品搜索虽有内存索引，但每次重建要把几份 JSON 全读全并。
3. 一致性：四种缓存风格，刷新时机不统一，各模块自己拼缓存键容易漏（itemsearch 漏两个文件）。
4. 耦合：每个功能模块都知道文件名、路径、JSON 结构，数据结构一改所有模块跟着改。
5. 可维护性：协作者加功能时要先学每个文件的读法。

### 1.3 目标

- 功能模块只传必要业务参数，拿到类型明确的结果，不接触数据文件和 SQLite 连接。
- 全应用只有一个当前发布版本；允许在途操作短暂持有上一版本的只读快照。
- 缓存由数据层统一管理，模块不得各自长期保存完整数据集。
- 内存显著下降；按 ID、天体、地点等查询使用索引；子串搜索按实际执行计划和耗时验收。
- 相同输入数据和业务参数下，保留现有输出、排序、匹配优先级和显示精度。已知缺陷修复（itemsearch 缓存键漏文件）单独记录为允许差异。
- 新库只放游戏数据，与用户库存库 `dubhe_inventory.db` 严格分开：整库重建不触碰任何用户记录，两库之间只靠物品身份映射关联。

全应用一致性是全部迁移完成后的目标。新旧读取路径并存期间，快照保证的边界是“一条已完整迁移的业务链”，不宣称旧 JSON 模块也拿到同一快照，见 §4.2。

### 1.4 非目标（第一期不做）

- 不做服务器端数据库、增量同步、通用缓存框架或新的模糊匹配算法。
- 不改变安装包和数据包的交付格式；生成的数据库、清单和临时文件不进入包和版本控制。
- 不删除 JSON 源文件；数据库始终是可重建的派生物。
- 不承诺数据库文件字节级可复现，也不承诺 SQLite schema 能原样迁移到未来服务器数据库。
- 不做多文件更新的暂存与批次恢复协议（列为二期候选，见 §4.2）。
- 不混入与本次迁移无关的注释、字符串或脚本清理。

---

## 2. 总体结构

| 路径 | 职责 |
|---|---|
| `data/*.json` | 现有源数据，由更新边界协调写入。 |
| `data/gamedata/current.json` | 当前数据库文件名、`generation_id`、`data_version`、`schema_version`。 |
| `data/gamedata/gamedata-<generation_id>.db` | 已完成且发布后不再修改的数据库。 |
| `data/gamedata/tmp/` | 建库临时文件；不可供查询。 |
| `sc_mining/gamedata/__init__.py` | `version()`、`snapshot()`、`rebuild()` 和各 topic 入口。 |
| `sc_mining/gamedata/_db.py` | 只读连接、快照绑定和发布状态检测。 |
| `sc_mining/gamedata/_build.py` | 运行时可调用的建库、校验和发布逻辑。 |
| `sc_mining/gamedata/_schema.py` | 表、约束、索引和 schema 版本。 |
| `sc_mining/gamedata/_types.py` | 公共数据类型、坐标约定和异常类型。 |
| `sc_mining/gamedata/shops.py`、`items.py` | 商店库存、物品和轻量候选词。 |
| `sc_mining/gamedata/starmap.py`、`places.py` | 星图、城市地点和坐标数据。 |
| `sc_mining/gamedata/loot.py`、`crafting.py`、`wikelo.py` | 掉落、制造和兑换数据。 |
| `sc_mining/gamedata/mining.py`、`prices.py`、`names.py` | 矿点信号、UEX 价格、中英名称。 |
| `tools/build_gamedata.py` | 薄命令行入口，调用包内 `_build.py`；运行时不反向依赖 `tools/`。 |

`data/` 指现有 `paths.DATA`（安装后随应用目录），不得默认等同于源码目录或当前工作目录。地基阶段核对安装后该目录可写；打包流程须包含新增运行时代码，不包含派生数据库。

用户库存库 `dubhe_inventory.db` 在 `userdata/`，由 `trade/storage.py` 管理，与 `data/gamedata/` 完全不相干：不同目录、不同连接、不同生命周期。`gamedata` 包不 import `storage`，`storage` 不 import `gamedata` 的内部模块；两者只通过物品身份映射（§3.3）在业务层对接。

### 2.1 数据库文件与发布清单

- 每次确实需要构建时生成唯一 `generation_id`，先写 `tmp/` 下临时库，提交事务、校验、关闭建库连接后，移动为最终 `gamedata-<generation_id>.db`。
- 使用普通回滚日志模式，不启用 WAL；仅发布已提交、已关闭、无需 journal 恢复的库。
- `meta` 表存 `schema_version`、`importer_version`、`data_version`、`generation_id`、`build_time` 和源文件清单及各自 SHA-256。
- 完整性验收：`PRAGMA quick_check`、必需表/字段存在、关键业务约束（如物品 ID 非空唯一）。若用外键需在建库连接上显式启用并跑 `foreign_key_check`。
- `current.json` 示例：

```json
{
  "generation_id": "<unique-generation-id>",
  "data_version": "<content-hash>",
  "schema_version": 1,
  "file": "gamedata-<unique-generation-id>.db"
}
```

- 新库就绪后，把新清单写到同目录临时文件，刷新并关闭句柄后原子替换 `current.json`。读者读清单时短时打开、立即关闭。
- 发布锁保证清单切换串行；Windows 短暂分享冲突允许有限重试，最终失败则报错并保留旧清单。
- 当前清单是唯一发布入口。不扫描目录挑“最新时间”的库；未发布文件不参与查询。
- 这套协议防止正常异常和进程中断暴露半成品；意外断电后仍靠启动校验兜底，不宣称超出文件系统的持久性保证。

### 2.2 内容版本、连接与缓存

三个版本含义分开：

| 字段 | 含义 |
|---|---|
| `data_version` | 由源文件清单及内容、`schema_version`、`importer_version` 共同决定的稳定内容版本；派生缓存的版本键。 |
| `generation_id` | 一次已完成构建的唯一身份，用于识别实际连接的文件。 |
| `build_time` | 诊断信息，不参与版本计算，不用于缓存失效。 |

- 内容哈希包含排序后的相对源路径、文件存在/缺失状态及原始字节哈希，并纳入 `schema_version`、`importer_version` 和影响结果的导入配置。
- schema 或导入规则变更时提升相应版本。源和规则未变且当前库通过校验则跳过重建；修复损坏库会得到新 `generation_id`，`data_version` 可相同。
- `version()` 在快照内返回该快照的 `data_version`，在快照外从当前清单解析；不能通过旧连接判断是否已有新版本。
- 每线程一个可复用只读连接（URI `mode=ro`），不对外暴露；连接只在创建它的线程使用和关闭。
- `snapshot()` 在业务操作开始时绑定清单、库文件和版本，并核对清单与库内 `meta` 一致。操作期间不切换；嵌套调用复用当前线程快照，退出最外层后才允许换代。
- 快照获取时若旧文件已被维护清理而无法打开，重新读取当前清单并有限重试，不创建空库。已成功打开的快照保持有效至操作结束。
- 无显式快照的单次 topic 调用自动建立短快照；多 topic 组合、OCR 候选构建和需要一致结果的连续查询必须由外层显式固定快照。
- 缓存键 = 实际查询快照的 `data_version` + 必要业务参数；不能先在外面读版本、再另开可能不同版本的查询。
- 数据层只保留当前代和仍被在途操作使用的缓存；在途旧缓存随最后一个使用者释放。禁止按版本无限积累 `lru_cache(maxsize=None)` 或全局字典。
- 可共享候选集用不可变容器；一般查询返回 list 时，不把同一个可变 list 暴露给多个调用者。

使用方式示意：

```python
with gamedata.snapshot() as snap:
    candidates = snap.items.candidates()
    matches = existing_matcher(text, candidates)
    shops = snap.shops.item(matches[0].item_id) if matches else []
```

示例中的匹配器只是现有调用链的占位；实际迁移保留现有算法和候选展开方式。

### 2.3 并发、旧版本和失败处理

- 建库与源数据写入共用数据目录级写锁。进程内互斥之外，应用多开或命令行建库也必须取得同一跨进程写锁。
- 锁在进程退出后由操作系统释放（文件锁，非“锁文件存在即占用”）。优先复用项目已有锁设施，具体实现由地基 PR 确定。
- 更新期间旧快照可继续查询；建库和发布失败不修改旧库。各线程只在自身安全边界关闭旧连接，更新线程不强制关闭其他线程的连接。
- 第一期不在正常查询期间删除旧库。启动或退出时的维护仅在确认没有其他实例/快照使用该数据目录时回收旧代；无法确认就跳过。单独取得写锁不等于没有读者，该确认需覆盖读者生命周期。
- 清理时保留当前库和至少一个已知有效的前代；失败或被占用的文件留待下次。不删除当前清单引用的库。
- 有与当前代码兼容的旧库时，更新失败可继续用旧数据，但明确提示“更新失败，仍在使用旧数据”。没有可用库、库损坏且无法重建、或 schema 不兼容时，抛出明确错误，不冒充查询无结果。
- `rebuild()` 是阻塞维护操作，在工作线程运行；UI 的“更新成功”提示只能在新清单发布成功后发出。

### 2.4 返回值与业务语义

- 业务行返回 `frozen=True` 的 dataclass，集合返回其 list 或不可变 tuple；不返回 sqlite Row 或任意结构的 dict。
- 查不到返回 `None` 或空集合；参数非法抛 `ValueError`；库不可用、源数据损坏、建库/发布失败抛明确的数据层异常。不把运行故障吞成空结果。
- 冻结类型内部的别名、坐标等不依靠共享可变 list/dict 保存。
- 字段用业务名。价格不擅自取整、截断或改变舍入规则；源数据含小数时保留精度，由调用层保持原显示格式。
- 列表顺序属于接口合同。需要保留原 JSON 顺序时存 `source_order` 并显式 `ORDER BY`；同分、同距离、同名记录的后续排序键也要明确。
- 重名、别名冲突、缺失字段、大小写/Unicode、空字符串以及 `%`/`_` 字面搜索规则，按现有行为逐项确定，不借迁移改变匹配语义。
- `Vec3` 的坐标系和单位写入公共类型合同；不同天体局部坐标或不同星系坐标不能直接算距离。源字段、单位换算、缺失坐标处理由地基调用点矩阵核实。

---

## 3. 接口设计

以下为语义示例，不代表所有字段和签名已核对源码。地基 PR 建立完整调用点矩阵，试点验证后冻结公共快照机制、共享类型和已实现 topic 的合同。其余 topic 在各自批次开工前完成字段映射并由公共层负责人审定，不为并行方便一次猜定全部 schema。

### 3.1 shops

```python
@dataclass(frozen=True)
class ShopRow:
    shop_id: str
    shop_name: str
    place_id: str
    body: str
    item_id: str
    item_name: str
    price_buy: Price | None
    price_sell: Price | None
    stock: str | None

@dataclass(frozen=True)
class ShopDistance:
    shop: ShopRow
    distance_m: float

def item(item_id: str) -> list[ShopRow]: ...
def find(name_fragment: str, limit: int | None = None) -> list[ShopRow]: ...
def where(*, item_id: str | None = None, body: str | None = None,
          place_id: str | None = None, sells: bool | None = None) -> list[ShopRow]: ...
def nearest(item_id: str, pos: Vec3) -> list[ShopDistance]: ...
def places() -> list[Place]: ...
```

- `stock` 第一期保留原字符串和空值；需要分类时增加派生字段，不覆盖原值。
- `Price` 的具体类型在地基阶段按源数据实际情况定：源全是整数 aUEC 就用 `int`；有小数则用 `Decimal`。无论哪种，不经过 `int()` 截断或不必要的浮点转换，对旧调用层的格式适配在试点确定。
- `sells` 以商店视角解释；价格字段的买卖视角在调用点矩阵记录并保持一致。
- `find()` 保留字面子串语义；`LIKE '%词%'` 不走普通 B-tree 索引。几千条名称允许扫描，先测量再决定是否另立搜索优化任务。
- `limit=None` 表示不截断；现有调用原本有限制的显式传原值，不新增默认上限。
- `nearest()` 先由 SQL 缩小候选集（按物品 / 天体），再由 Python 沿用现有距离计算和排序；统一坐标系和单位，保留同距离优先级。无坐标候选的处理在试点前按旧行为确认。

### 3.2 starmap

```python
def body(name: str) -> Body | None: ...
def point(name: str) -> Point | None: ...
def points(body: str, kind: str | None = None) -> list[Point]: ...
def pois(body: str) -> list[Point]: ...
def nearest_body(pos: Vec3) -> Body | None: ...
```

`Body`、`Point`、`Place`、`Vec3` 的完整字段在调用点矩阵中定义。地点若不能仅凭名称唯一识别，增加 ID 或作用域参数；现有按名接口保留有依据的冲突优先级，不随机返回一条。

### 3.3 items

```python
@dataclass(frozen=True)
class ItemCandidate:
    item_id: str
    name: str
    aliases: tuple[str, ...]
    source_order: int

def get(item_id: str) -> Item | None: ...
def all() -> list[Item]: ...
def candidates() -> tuple[ItemCandidate, ...]: ...
def by_name(name: str) -> Item | None: ...
def by_source_id(source: str, external_id: str) -> Item | None: ...   # "uex" / "scm" / "local" / "class" / "uuid"
def search(fragment: str, limit: int | None = None) -> list[Item]: ...
```

- **物品身份映射是地基任务。** 现状有多套编号：查价来源编号（`uex:4741`、`scm:43475`、`local:…`）、游戏类名、游戏实体 uuid、汉化名、wiki 英文名、`name_aliases.json` 的旧写法。库里 `item_id` 是本库自己的稳定主键（由规范化英文名派生，地基阶段按 `gamekey.py` 和 `itemsearch.entry()` 的现有合并规则定），另有 `item_source_ids(source, external_id, item_id)` 表存各来源编号到主键的映射，`item_names(item_id, lang, name, kind, source_order)` 表存中文名、英文名、别名、旧写法。接口里的 `item_id` 一律指本库主键；要按来源编号查的走 `items.by_source_id(source, external_id)`。不把任何一种外部编号直接当 `item_id`。
- OCR 和模糊匹配只取轻量 `candidates()`，不以 `all()` 缓存完整物品行；真正需要全量物品的调用仍可用 `all()`。
- `candidates()` 按快照 `data_version` 缓存，保持原有候选顺序、别名顺序、重复项处理和来源优先级；示例字段不够用时在试点补齐。
- `by_name()` 保留现有中英文尝试顺序；名称不唯一时有固定优先级。需要全部同名项的调用另提供集合查询。

### 3.4 其他 topic 与索引

loot / crafting / wikelo / places / mining / prices / names 按实际调用提供 ID 查询、条件查询和必要的全量查询，不为统一外形增加没有调用者的接口。

建库前形成“源文件 → 实际使用字段 → 转换规则 → 表/索引 → 调用模块 → 返回顺序”的矩阵。仅剥离确实未被使用的字段；涉及来源优先级、顺序或回归解释的字段不当调试信息删掉。

按实际查询定义索引，用开发脚本和测试中的 `EXPLAIN QUERY PLAN` 检查关键 ID/关联查询；第一期不公开 `explain()` API，也不要求每种搜索都走索引。

### 3.5 对模糊匹配的影响

保留现有匹配评分、OCR 纠错和并列命中处理算法，只替换候选读取与必要的类型适配。回归同时验证候选内容、顺序、别名展开和最终命中，不以“算法代码没改”代替行为验证。

---

## 4. 落地方式

### 4.1 建库与启动

- `tools/build_gamedata.py` 和运行时 `rebuild()` 调用同一份 `_build.py`。
- 使用显式运行时源清单，不把 `data/*.json` 中任意新增文件自动当输入；记录必需/可选文件、缺失规则。`data/scmdb`、本机构建输入目录不纳入运行时建库。
- 对源文件读取一次字节，用同一份字节算 SHA-256 和解析，避免哈希与实际入库内容不一致。
- 当前版本可用且 `data_version` 未变则不重建。相同输入和转换规则保证相同业务行、顺序和内容版本，不要求库文件字节相同。
- 启动先校验清单、文件、schema/导入版本及源哈希；首次使用、兼容性变化或输入变化时重建。清单损坏或缺失时显式重建，不把目录中任意旧库自动认作当前版本。
- “秒级建库”是待测目标；记录完整建库、校验、发布耗时和峰值内存，不在 UI 主线程阻塞执行。

### 4.2 更新边界

纳入统一更新边界的入口：`shops.update`、`loot.update / loot.detail`、`starmap.update`、`uex.refresh`、`build_crafting.build`、`wikelo.build`、`localization.rebuild`、`data_pack.install`，以及确认会创建或改写源文件的 `paths.seed_data`。

第一期规则（刻意保持简单）：

1. 网络请求、解析、业务转换在锁外进行，和现在一样。
2. 写源文件统一走现有 `paths.write_json`（临时文件 + `replace` + Windows 占用重试），在它外面加数据目录写锁；不另写一套文件写入。需要先读现有源再合并的更新器，在锁内重新读取当前源再合并，不用锁前的旧副本整文件覆盖。
3. 本批源文件全部写完后，在同一写锁内调用一次建库 + 发布；子更新函数只标记“数据有变”，由最外层统一触发一次重建。短时连续刷新合并为一次。
4. 建库或发布失败：旧库和旧清单不动，返回失败并提示“仍在使用旧数据”；下次更新或启动校验时因源哈希与库不符而重建。
5. 发布成功后的通知复用现有 `data_pack.clear_caches()` / `CACHE_HOOKS`：`gamedata` 向 `CACHE_HOOKS` 登记一个回调，在清缓存时重新读清单换代；尚未迁移模块的旧缓存清理（含 `uex.apply_live` 再应用）原样保留。不机械改成每调用一次 `clear_caches` 就 `rebuild()`。全部读者迁移后再移除旧清理分支。

明确不做：多文件更新的暂存区、批次标记和中断恢复。现有更新器本来就是逐文件写，进程在多文件写入中途退出会留下“部分新部分旧”的源，这是现状已有的风险，第一期不扩大也不消除；启动校验会用这组源重建库，不会读到半截文件。若后续实测发现这是真实问题，作为二期需求单独设计。

过渡期规则：每次迁移必须覆盖一条业务操作的全部数据依赖；同一操作不混用旧 JSON 读取与新数据层快照，依赖未就绪则整条链留在旧路径。源已提交而库发布失败时，新旧链路可能短暂看到不同版本，应用保留“数据更新未完成”状态，不宣称全应用已同步。

### 4.3 迁移顺序与责任划分

**地基 PR：**

- 完成调用点、输入文件和字段矩阵；先保存现有 `sample_sweep` 回归输出与性能基线。
- 实现公共类型、快照、连接、版本、写锁、建库发布和失败处理。
- 实现试点（批 1）所需的表、索引与导入；其余 topic 按已核对矩阵在对应批次加入，影响已有构建内容的扩展须提升 schema/导入版本。
- 未实现的 topic 不导出为可用接口；不把一套 `NotImplementedError` 占位视作接口验收。
- 完成 Windows 并发切换、失败处理与安装后路径验证。

**批 1 是端到端试点，验收后再展开其余批次：**

| 批 | 功能模块 | 负责的数据层与依赖 |
|---|---|---|
| 1（试点） | shops / itemsearch / stockplaces | `shops`、`items`、`prices`；含 UEX 刷新接入和 OCR 轻量候选。`itemsearch` 现在合并 `shops.json`、`loot_index.json`、`zh_names.json`、`name_aliases.json`、`wiki_items.json` 五份数据建索引，试点的 `items` 表和身份映射必须覆盖全部五份，否则搜索行为变。试点需要的地点/名称映射由公共层先打通。 |
| 2 | starmap / position / transit / navigate | `starmap`、`places`；接续试点地点接口，验证坐标与导航刷新；顺手删 `navigate.py:60` 的死导入 `_data`。 |
| 3 | crafting / wikelo / itemstats | `crafting`、`wikelo`；依赖批 1 冻结的物品身份和候选合同。 |
| 4 | loot | `loot`；依赖批 1 物品身份合同，覆盖 `loot.detail` 写入。 |
| 5 | mining_area / signals / parse | `mining`；依赖批 2 的坐标/地点合同，批 2 合并后再集成；解决热路径 `_spots_raw` 重复读文件。 |
| 6 | names / i18n | `names`；接续试点名称映射，保留原优先级和缺失回退。 |

试点验收须覆盖“JSON 更新 → 建库 → 发布 → 新操作读到新版 → 在途操作完成旧版”，并验证构建失败时仍明确使用旧版。试点用到的公共依赖必须有真实实现，不留调到占位函数的链路。

### 4.4 并行与合并规则

- 地基和批 1 合并后，批 2/3/4/6 可并行推进；批 5 等批 2 合并后集成。六批不是完全独立。
- `_db.py`、`_build.py`、`_schema.py`、`_types.py` 和写锁由一名公共层负责人维护。各 topic 需要的表/索引/导入变更由其协调先行 PR；相关 topic PR 显式依赖这些公共变更。
- 各批只改自己的 topic 和对应调用模块；`items`、`prices` 由批 1 定责，后续跨批调整走公共协调，不重复实现。
- 每批迁移完整调用链后删除该链旧读文件代码，不保留切换开关或双路径；未迁移链路保留旧行为和必要清缓存。
- 每批添加自己的测试；地基阶段先核实 `tests.run_all` 的发现方式，若需注册，交公共负责人更新，不能因“不改 run_all”使新测试从未运行。
- 不随手改 `pyproject.toml` 或批量刷新类型检查 baseline。确需的公共配置变更单独评审；最终 baseline 更新前逐条审查新增诊断，不用重刷掩盖类型错误。
- 保留 `REVIEW.md` 审查流程；目标三轮内收敛，未解决的阻塞问题不能因轮数用尽直接合并。

### 4.5 流程

地基核对与原行为基线 → 公共基础 PR → 批 1 端到端试点 → 试点验收 → 批 2/3/4/6 并行、逐批合并 → 批 5 集成 → 旧路径清理、类型检查与全量回归 → 负责人 Windows 实机验收。

---

## 5. 验证与验收

### 5.1 行为与数据合同

- 每个 topic 用测试现建的小型假库验证过滤、排序、重复名、空值、价格精度、名称/别名优先级和 limit 参数，不依赖真实 `data/`。
- 增加 JSON → 建库 → topic 查询的集成测试，防止假库测试绕过导入转换错误。
- 同一份固定源数据上保存迁移前 `tools/sample_sweep.py` 输出，与迁移后逐字比对；记录原版本和输入清单，不用实时变化数据作基准。
- OCR 同时比较候选序列、别名展开和最终命中；覆盖同分、同名、中英文及特殊字符。
- navigate 过期缓存修复单列预期差异：更新后必须读到新星图；其他未批准差异视作回归。
- `nearest()` 覆盖坐标单位、跨坐标系、缺失坐标及同距离顺序。
- 确认所有新增测试被 `tests.run_all` 实际执行，全量测试和类型检查通过。

### 5.2 生命周期、并发与失败

- 在 Windows 验证多个线程持有旧快照时发布新版本；旧查询完成旧版，新操作读取新版，不替换打开的库。
- 验证版本键与实际查询内容一致、嵌套快照不换代、候选构建期间发布不会混用新旧数据。
- 验证应用多开 / CLI 建库竞争时写锁生效，读者能在操作边界发现外部发布。
- 模拟 JSON 损坏、必需文件缺失、建库失败、清单切换失败及首次启动无旧库。
- 覆盖不重启进程的失败重试、两次并发更新，确认后者等锁、不互相覆盖。
- 过渡期检查单条业务链不混用 JSON 与数据库，更新失败状态不会错误显示全应用已刷新。
- 验证旧代清理不会删除当前库、在用库；无法取得独占条件时跳过清理。
- 检查 schema 不兼容时不静默使用旧库，也不以空结果隐藏失败。

### 5.3 性能与资源

同一机器、同一源数据、同一操作脚本下，前后各跑三组取中位数，记录：

| 指标 | 测量要求 |
|---|---|
| 启动常驻内存 | 区分已有可用库启动与首次建库启动。 |
| 首次与重复物品查询 | 分别记录冷/热查询，包含结果对象构造。 |
| 首次 OCR 后内存 | 防止候选加载后重新常驻完整物品数据。 |
| 采矿扫描一轮耗时 | 确认热路径不再重复读取 JSON。 |
| 全量重建 | 分别记录源读取、建库、校验、发布耗时，以及峰值内存与磁盘占用。 |
| 连续刷新后资源 | 多轮释放在途快照后观察内存、连接数及旧代磁盘占用。 |

内存下降和性能改善用实测值说明，不先承诺固定百分比；试点若未改善或出现回退，先定位原因再扩大迁移。

### 5.4 安装环境与文档

- 现有交付方式下确认 `_build.py` 可导入、数据目录可写、首次无数据库可成功建立；不依赖源码目录中的工具脚本。
- 检查运行时源清单覆盖全部迁移 topic，数据包安装及 seed 操作被纳入更新边界。
- 核对文档、字段矩阵、实际签名和测试一致；区分设计目标、已实现功能和已运行验证。

---

## 6. 风险与取舍

| 风险 | 第一期应对 |
|---|---|
| Windows 占用导致数据库替换失败 | 新建独立代文件，仅原子切换短时打开的清单，不覆盖在用库。 |
| 版本检测仍读旧连接，或缓存键与查询版本错配 | 清单独立发现发布；一次操作固定快照；缓存键取自该快照。 |
| 多开或 CLI 与应用同时建库 | 数据目录级跨进程写锁，串行发布。 |
| 多处更新重复触发全量重建 | 最外层统一触发一次，内容未变跳过；第一期不做增量。 |
| 旧代缓存或数据库积累 | 有界缓存、在途引用释放；独占维护窗口清理旧代，持续测量实际占用。 |
| 字段、别名、顺序或精度丢失 | 调用点矩阵、导入集成测试、`source_order` 及固定输入回归。 |
| 子串搜索没有索引加速 | 明确扫描成本，优先索引 ID/筛选列，按需另立优化任务。 |
| 更新失败、磁盘满或目录只读 | 保留兼容旧库并明确告知失败；无可用库时报错；安装环境验证可写路径。 |
| 公共 schema 和类型产生跨批冲突 | 先试点，公共负责人协调版本化变更，各批显式声明依赖。 |
| 过渡期旧 JSON 模块缓存未刷新 | 未迁移链路保留旧清理，已迁移链路走快照；最终移除旧机制。 |
| 多文件更新中途进程退出留下半新半旧源 | 现状已有，第一期不扩大也不消除；启动校验用当前源重建。二期候选。 |

SQLite 的主要收益是统一访问边界、减少完整 Python 对象常驻和支持结构化索引查询。第一期保留 JSON，便于复用现有数据获取流程和回退。后续服务器化可参考逻辑实体与接口合同，但需重新评估数据库类型、同步协议与部署约束。

---

## 7. 决定与实施前核对

### 7.1 已确定

| 原待审项 | 决定 |
|---|---|
| `stock` 是否归一为枚举 | 保留原字符串；确有需要时新增派生分类字段。 |
| OCR 是否调用 `items.all()` | 使用轻量 `items.candidates()`，按快照版本有界缓存。 |
| 距离排序在哪里计算 | SQL 筛候选，Python 沿用原算法计算距离并稳定排序。 |
| 是否公开 `explain()` | 第一期仅开发脚本/测试辅助，不加入公共 API。 |
| 数据库如何热切换 | 版本化库文件 + 原子切换当前清单 + 操作级固定快照。 |
| 是否保证产物字节一致 | 不保证；保证业务内容、顺序和内容版本可复现，未变则跳过构建。 |
| 是否立即六批并行 | 先地基与批 1 试点；其余按明确依赖展开。 |
| 价格类型 | 按源数据实际类型定（整数 → `int`，含小数 → `Decimal`），不截断。 |
| 多文件更新批次恢复 | 第一期不做，二期候选。 |

### 7.2 地基阶段必须从源码核实

- 实际运行时源清单、每个写入入口和完整调用链，包括 `paths.seed_data`、UEX 导入时应用逻辑及 `loot.detail`。
- 各源字段类型、价格精度、坐标系与单位、重名优先级、候选顺序、缺失回退和旧有截断规则。
- 应用实例管理、工作线程、现有跨进程锁和安全维护窗口；为读者生命周期与旧文件清理给出可验证实现。
- 安装后路径、运行时代码包含方式及 `tests.run_all` 的测试发现机制。

以上是实施人员结合源码完成的合同核对，不要求重新决定已确认的架构；若发现必须改变业务行为或第一期范围，单独提出具体差异并记入变更记录。

---

## 8. 技术依据

- [SQLite：打开期间删除或重命名数据库的风险](https://www.sqlite.org/howtocorrupt.html#_unlinking_or_renaming_a_database_file_while_in_use)
- [SQLite：LIKE 优化的适用条件](https://www.sqlite.org/optoverview.html#the_like_optimization)
- [SQLite：ORDER BY 与未定义结果顺序](https://www.sqlite.org/lang_select.html#the_order_by_clause)
- [Python：sqlite3 连接线程约束与只读 URI](https://docs.python.org/3/library/sqlite3.html)
- [Python：functools 缓存行为](https://docs.python.org/3/library/functools.html)

这些资料支撑文件生命周期、查询顺序和索引限制的设计判断；文中 AT 数据规模和功能现状以项目源码与实测为准。
