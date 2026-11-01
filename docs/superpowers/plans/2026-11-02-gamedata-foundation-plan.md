# 游戏数据层地基 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建起 `sc_mining/gamedata/` 包的公共层（类型、写锁、schema、建库发布、清单、快照、连接、版本）和试点批次所需的表与导入，不迁移任何功能模块。

**Architecture:** JSON 仍是源；`_build.py` 按显式源清单读 JSON、算内容版本、建到临时库、校验后落成 `data/gamedata/gamedata-<generation_id>.db`，再原子切换 `current.json`。读端每线程一条只读连接，`snapshot()` 把一次业务操作钉在一个清单版本上。跨进程写锁照 `app/instance.py` 的 `msvcrt.locking` 写法。

**Tech Stack:** Python 3.12 标准库（`sqlite3`、`hashlib`、`msvcrt`/`fcntl`、`threading`、`dataclasses`）；测试用仓库自带 `tests/minipytest`（支持 `tmp_path`、`monkeypatch`、`raises`，不支持 fixture 参数、yield fixture、`monkeypatch.setitem`）。

**Spec:** `docs/superpowers/specs/2026-11-02-gamedata-design.md`（v3）

## Global Constraints

- 新库与用户库存库 `userdata/dubhe_inventory.db`（`trade/storage.py`）完全分开：`gamedata` 不 import `trade.storage`，反向也不行。
- 库文件、清单、临时文件都在 `paths.DATA / "gamedata"` 下；`data/gamedata/` 进 `.gitignore`；不进安装包、不进数据包。
- 源文件写入只走 `paths.write_json`；不新写文件替换逻辑。
- 不改 `pyproject.toml`、不刷 `.basedpyright/baseline.json`；新代码 `ruff check` 和 `basedpyright` 必须零新增诊断。
- 注释、文档字符串、报错文字用中文；游戏名词用汉化组译名。
- 不模拟任何键盘或鼠标输入；不碰 `userdata/`。
- 测试不读真实 `data/`、不写真实 `userdata/`（`tmp_path` + `monkeypatch.setattr(paths, "DATA", ...)`）。
- 每个 Task 在功能分支 `feat/gamedata-foundation` 上独立提交；不直接提交 main；不推送（推送要负责人点头）。
- 提交信息格式照仓库现状：`<type>: <中文一句话>`，不带会话链接。
- 地基阶段**不导出**任何 topic 查询函数（`items.get`、`shops.where` 等），不放 `NotImplementedError` 占位。
- 价格字段：shops.json 的买卖价在源里是 `float`（如 `586.0`），库里存 `REAL`，读出来原样 `float`，不做任何转换。
- 与设计文档 §3.1 示例的差异（按源码核对后的决定，批 1 开工前写回设计文档）：`ShopRow` 字段按 `shops.json` 的 `rows` 7 列原样映射（`uex_item_id, shop_name, place_text, price_buy, price_sell, version, fields[6]`），没有 `shop_id`/`place_id`/`body` 这些源里不存在的列；`Place` 类型本期只定义不填表。
- 测试里的 `raises`、`monkeypatch`、`tmp_path` 写法照 `tests/test_data_pack.py` 现有用法。

## Review Focus

1. **同一进程两个线程同时 `rebuild()`**：第二个应等第一个发布完再检查版本并跳过，不能各建各的后互相覆盖清单。→ Task 6 测试 `test_rebuild_concurrent_same_process`。
2. **源 JSON 坏掉（半截文件）时建库**：必须抛 `BuildError` 并保留旧清单，不能发布空表的库，也不能让下次启动误判“已是最新”。→ Task 5 测试 `test_build_bad_json_keeps_old_manifest`。
3. **清单指向的库文件被人手删了**：`snapshot()` 要抛 `GamedataUnavailable`（有源可重建时由 `ensure_ready()` 重建），不能静默返回空结果。→ Task 4 测试 `test_snapshot_missing_db_file_raises`。
4. **进程 A 持有快照时进程 B 发布新代并试图清理旧代**：B 不能删 A 正在用的文件；第一期直接“有任何其他实例在跑就不清理”。→ Task 6 测试 `test_cleanup_skips_when_other_instance_running`。
5. **`item_source_ids` 里同一 `(source, external_id)` 来自两份源文件指向不同物品**（shops 的 uex id 与 loot 的 uuid 不会冲突，但 `name_aliases` 的旧写法可能指向已存在的别的物品）：导入必须按 `itemsearch._build_locked()` 现有规则——`en_key(old) not in by_en` 才登记——否则搜索行为变。→ Task 5 测试 `test_import_alias_does_not_override_existing_item`。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `sc_mining/gamedata/__init__.py` | 对外入口：`version()`、`snapshot()`、`rebuild()`、`ensure_ready()`、`refresh()`、`updating()`；re-export 类型和异常 |
| `sc_mining/gamedata/_types.py` | `Vec3`、`Item`、`ItemCandidate`、`ShopRow`、`ShopDistance`、`Place`；异常 `GamedataError`、`GamedataUnavailable`、`BuildError` |
| `sc_mining/gamedata/_paths.py` | `gamedata_dir()`、`manifest_path()`、`tmp_dir()`、`db_path(generation_id)`、`lock_path()`——全部由 `paths.DATA` 派生，运行时取值（方便测试 monkeypatch） |
| `sc_mining/gamedata/_lock.py` | `write_lock(timeout)` 上下文管理器：跨进程文件锁 + 进程内 `threading.RLock` |
| `sc_mining/gamedata/_manifest.py` | `Manifest` dataclass；`read_manifest()`、`write_manifest(m)`（临时文件 + `os.replace` + 重试） |
| `sc_mining/gamedata/_schema.py` | `SCHEMA_VERSION`、`IMPORTER_VERSION`、`DDL`（建表 + 索引语句列表） |
| `sc_mining/gamedata/_sources.py` | `SOURCES`：试点所需源文件清单（文件名、必需/可选）；`read_sources()` 一次读字节、同份字节算哈希和解析 |
| `sc_mining/gamedata/_import.py` | 把解析后的源 dict 变成各表的行：`import_items()`、`import_shops()`、`import_prices()`——照抄 `itemsearch._build_locked()` 的合并规则 |
| `sc_mining/gamedata/_build.py` | `data_version(sources)`、`build(sources) -> Path`（临时库→校验→落成）、`publish(db_path, meta)`、`rebuild_if_needed()`、`cleanup_old_generations()` |
| `sc_mining/gamedata/_db.py` | 每线程只读连接、`Snapshot` 对象、`snapshot()` 上下文、`current_version()` |
| `tools/build_gamedata.py` | 命令行壳：`python -X utf8 tools/build_gamedata.py [--force] [--check]` |
| `tools/gamedata_baseline.py` | 迁移前行为基线：跑固定查询列表（`itemsearch.find`、`shops.where/nearest`、`loot.find`、`names.table` 抽样）写 JSON |
| `tests/test_gamedata.py` | 本地基全部测试 |
| `docs/superpowers/specs/2026-11-02-gamedata-callsites.md` | 试点调用点矩阵（源文件 → 字段 → 转换 → 表 → 调用模块 → 返回顺序） |

修改的现有文件：
- `.gitignore`：加 `/data/gamedata/`
- `sc_mining/update/data_pack.py`：`clear_caches()` 末尾加 `gamedata.refresh()`；`install()` 成功路径包进 `gamedata.updating()`
- `tests/run_all.py`：`MODULES` 加 `"tests.test_gamedata"`
- 应用启动处（`grep -n "warm_up" sc_mining/app` 找到调 `itemsearch.warm_up()` 的位置）：旁边加 `gamedata.warm_up()`

---

### Task 0: 分支、调用点矩阵、行为基线

**Files:**
- Create: `tools/gamedata_baseline.py`
- Create: `docs/superpowers/specs/2026-11-02-gamedata-callsites.md`

**Interfaces:**
- Produces: `测试数据/gamedata_baseline_<日期>.json`（写到 `E:\Claude公主的书\项目资料\测试数据\`，由 `--out` 指定，不进仓库）；矩阵文档被 Task 3/5 引用。

- [ ] **Step 1: 建 worktree 和分支**

```bash
cd E:\Game3\AstralToolkit
git worktree add E:\Game3\AT_wt\gamedata -b feat/gamedata-foundation main
```
Expected: 新目录，`git -C E:\Game3\AT_wt\gamedata branch --show-current` 输出 `feat/gamedata-foundation`。后续所有命令在该 worktree 里跑，Python 用 `E:\Game3\AstralToolkit\.venv\Scripts\python.exe`。

- [ ] **Step 2: 写调用点矩阵**

对试点五份源文件逐个列表（Markdown 表）：

| 源文件 | 读它的函数 | 用到的字段 | 转换规则（引用源码行号） | 目标表.列 | 调用模块 | 返回顺序要求 |

必须覆盖：`shops.json`（`items`、`rows` 的 7 个位置含 `fields[6]`）、`loot_index.json`（`rows` 6 列）、`zh_names.json` + `zh_only_names.json`（`names.table()` 的 `_junk` 过滤和 `_norm_zh` 长度规则）、`name_aliases.json`、`wiki_items.json`（`n/t/s/mfr/cls/d`）、`prices.json`。
对每份源写明“哪些字段现在没人读”（这些才允许不入库）。

- [ ] **Step 3: 写基线工具 `tools/gamedata_baseline.py`**

签名：`main(argv) -> int`；参数 `--out <path>`。固定查询列表写在文件顶部常量 `QUERIES`，至少包含：
- `itemsearch.find(q, limit=30)`：`q` ∈ `["视差步枪", "parallax", "Medpen", "头盔", "劳森", "P4-AR", "Hurston", "xyz不存在"]`
- `itemsearch.lookup("Lawson Mining Laser")`、`lookup("medpen")`
- `shops.where(item_id)` 对 `shops.load()["items"]` 前 20 个 id
- `shops.nearest(item_id, here, n=3)`，`here` 取 `sc_mining/navigation` 里 New Babbage 的坐标常量（grep `New Babbage` 找），对前 5 个 id
- `loot.find(name_en=...)` 对 `["Medpen", "AdrenaPen (Demexatrine)", "Parallax"]`
- `names.table()` 的长度和前 50 个键值对（按键排序）
- `gamekey` 里按名字取类名/uuid 的公开函数（读 `gamekey.py` 第 25 行以后确定函数名）对 `["Medpen", "Lawson Mining Laser"]`

输出 JSON：`{"git": <HEAD sha>, "data_stamps": {文件名: mtime_ns}, "results": {查询字符串: 结果}}`，`ensure_ascii=False, indent=1, sort_keys=True`。结果里的 dict/list 原样 dump。

- [ ] **Step 4: 跑基线并存档**

Run: `E:\Game3\AstralToolkit\.venv\Scripts\python.exe -X utf8 tools\gamedata_baseline.py --out "E:\Claude公主的书\项目资料\测试数据\gamedata_baseline_20261102.json"`
Expected: 退出码 0，文件存在，`results` 下每个查询都有值（不存在的物品是 `[]`）。

- [ ] **Step 5: 记性能基线**

Run: 在同一 Python 里 `import tracemalloc, time`；测三组：① `import sc_mining.crafting.itemsearch; itemsearch._build()` 的耗时和 `tracemalloc` 峰值；② 第二次 `find("视差步枪")` 耗时；③ `mining_area` 区域判断 5 次（调用点见 `mining_area.py:230-245`，输入用 `tests/test_mining.py` 里现有的派罗坐标样例）的耗时。各跑三次取中位数，写进 `测试数据/gamedata_baseline_20261102.md`。

- [ ] **Step 6: 提交**

```bash
git add tools/gamedata_baseline.py docs/superpowers/specs/2026-11-02-gamedata-callsites.md
git commit -m "chore: 游戏数据层迁移前的调用点矩阵和行为基线工具"
```
（`docs/` 被 gitignore：矩阵文档需要 `git add -f`，并在 `.gitignore` 加 `!/docs/superpowers/`。）

---

### Task 1: 类型与路径

**Files:**
- Create: `sc_mining/gamedata/__init__.py`（先只 re-export，入口函数后面 Task 补）
- Create: `sc_mining/gamedata/_types.py`
- Create: `sc_mining/gamedata/_paths.py`
- Modify: `.gitignore`
- Test: `tests/test_gamedata.py`

**Interfaces:**
- Produces:
  ```python
  # _types.py
  @dataclass(frozen=True) class Vec3: x: float; y: float; z: float
  @dataclass(frozen=True) class Item: item_id: str; en: str; zh: str; cat: str; has_shop: bool; has_loot: bool; loc: bool; wiki: bool; wtype: str; wsize: int | None; desc: str; variant: bool
  @dataclass(frozen=True) class ItemCandidate: item_id: str; name: str; aliases: tuple[str, ...]; source_order: int
  @dataclass(frozen=True) class ShopRow: uex_item_id: int; shop_name: str; place_text: str; price_buy: float; price_sell: float; version: str; fields: tuple[str, str, str, str, str, str]; source_order: int
  @dataclass(frozen=True) class ShopDistance: shop: ShopRow; distance_m: float
  @dataclass(frozen=True) class Place: place_id: str; name: str; system: str; body: str; pos: Vec3 | None
  class GamedataError(Exception)
  class GamedataUnavailable(GamedataError)
  class BuildError(GamedataError)
  # _paths.py —— 全部是函数，运行时读 paths.DATA
  def gamedata_dir() -> Path          # paths.DATA / "gamedata"
  def manifest_path() -> Path         # gamedata_dir() / "current.json"
  def tmp_dir() -> Path               # gamedata_dir() / "tmp"
  def db_path(generation_id: str) -> Path   # gamedata_dir() / f"gamedata-{generation_id}.db"
  def lock_path() -> Path             # gamedata_dir() / ".write.lock"
  ```

- [ ] **Step 1: 写测试**

```python
def test_paths_follow_data_root(monkeypatch, tmp_path):
    from sc_mining.core import paths
    from sc_mining.gamedata import _paths
    monkeypatch.setattr(paths, "DATA", tmp_path)
    assert _paths.gamedata_dir() == tmp_path / "gamedata"
    assert _paths.db_path("abc") == tmp_path / "gamedata" / "gamedata-abc.db"
    assert _paths.manifest_path().name == "current.json"

def test_types_are_frozen():
    from sc_mining.gamedata import Vec3, ShopRow
    import dataclasses
    v = Vec3(1.0, 2.0, 3.0)
    with raises(dataclasses.FrozenInstanceError):
        v.x = 9  # type: ignore[misc]
    assert ShopRow.__dataclass_params__.frozen
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -X utf8 -m tests.minipytest tests.test_gamedata`（若 minipytest 不支持单模块，临时把 `tests.test_gamedata` 加进 `run_all.MODULES` 后跑 `python -X utf8 -m tests.run_all`）
Expected: ImportError `sc_mining.gamedata`

- [ ] **Step 3: 实现 `_types.py`、`_paths.py`、`__init__.py`**

`__init__.py` 此时只 `from ._types import *`（显式列 `__all__`）。`_paths.py` 每个函数内部 `from ..core import paths` 后取 `paths.DATA`，不在模块顶层绑定。

- [ ] **Step 4: `.gitignore` 加 `/data/gamedata/`**

- [ ] **Step 5: 跑测试通过；跑 `ruff check sc_mining/gamedata tests/test_gamedata.py` 和 `basedpyright sc_mining/gamedata`**

Expected: 全绿、0 诊断。

- [ ] **Step 6: 提交**

```bash
git add sc_mining/gamedata .gitignore tests/test_gamedata.py
git commit -m "feat: 游戏数据层包骨架：公共类型、路径、异常"
```

---

### Task 2: 跨进程写锁与清单读写

**Files:**
- Create: `sc_mining/gamedata/_lock.py`
- Create: `sc_mining/gamedata/_manifest.py`
- Test: `tests/test_gamedata.py`

**Interfaces:**
- Produces:
  ```python
  # _lock.py
  @contextmanager
  def write_lock(timeout: float = 30.0) -> Iterator[None]
      # 先拿进程内 RLock，再对 lock_path() 文件 msvcrt.locking(LK_NBLCK) / fcntl.flock(LOCK_EX|LOCK_NB)，
      # 每 50ms 重试直到 timeout，超时抛 GamedataError("数据目录正被其他 AT 使用")
  def other_instance_running() -> bool
      # 试拿 userdata 的 instance.lock（复用 app.instance._try_lock 的文件名和方式）：拿到就释放返回 False；拿不到返回 True
  # _manifest.py
  @dataclass(frozen=True)
  class Manifest: generation_id: str; data_version: str; schema_version: int; file: str
  def read_manifest() -> Manifest | None        # 没有文件返回 None；JSON 坏或缺字段抛 GamedataUnavailable
  def write_manifest(m: Manifest) -> None        # 写 tmp_dir()/current.json.<pid>.tmp，flush+fsync 后 os.replace；PermissionError 重试 6 次×50ms
  ```

- [ ] **Step 1: 写测试**

```python
def test_write_lock_reentrant_in_process(monkeypatch, tmp_path):
    from sc_mining.core import paths
    from sc_mining.gamedata import _lock
    monkeypatch.setattr(paths, "DATA", tmp_path)
    with _lock.write_lock():
        with _lock.write_lock():   # 同线程可重入
            pass

def test_write_lock_blocks_other_process(monkeypatch, tmp_path):
    # 用 subprocess 起一个 python 子进程持锁 2 秒，主进程 timeout=0.3 应抛 GamedataError
    ...
    with raises(GamedataError):
        with _lock.write_lock(timeout=0.3): pass

def test_manifest_roundtrip(monkeypatch, tmp_path):
    m = Manifest("g1", "v1", 1, "gamedata-g1.db")
    write_manifest(m); assert read_manifest() == m

def test_manifest_missing_is_none(monkeypatch, tmp_path):
    assert read_manifest() is None

def test_manifest_corrupt_raises(monkeypatch, tmp_path):
    manifest_path().parent.mkdir(parents=True); manifest_path().write_text("{", encoding="utf-8")
    with raises(GamedataUnavailable): read_manifest()
```
子进程脚本用 `sys.executable -c` 内联，把 `tmp_path` 传进去并 `monkeypatch` 同样的 `paths.DATA`。

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现 `_lock.py`、`_manifest.py`**

`write_lock` 的文件锁部分照 `sc_mining/app/instance.py:22-40` 的分支结构（Windows `msvcrt`、其他 `fcntl`）。

- [ ] **Step 4: 跑测试通过；ruff + basedpyright 零诊断**
- [ ] **Step 5: 提交**

```bash
git commit -am "feat: 游戏数据层的跨进程写锁和当前版本清单"
```

---

### Task 3: schema 与源清单

**Files:**
- Create: `sc_mining/gamedata/_schema.py`
- Create: `sc_mining/gamedata/_sources.py`
- Test: `tests/test_gamedata.py`

**Interfaces:**
- Produces:
  ```python
  # _schema.py
  SCHEMA_VERSION = 1
  IMPORTER_VERSION = 1
  DDL: list[str]   # 建表 + 索引，顺序执行
  # 表：
  # meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)
  # items(item_id TEXT PRIMARY KEY, en TEXT NOT NULL, zh TEXT NOT NULL DEFAULT '', cat TEXT NOT NULL DEFAULT '',
  #       has_shop INTEGER NOT NULL, has_loot INTEGER NOT NULL, loc INTEGER NOT NULL, wiki INTEGER NOT NULL,
  #       wtype TEXT NOT NULL DEFAULT '', wsize INTEGER, desc TEXT NOT NULL DEFAULT '', variant INTEGER NOT NULL,
  #       zlen INTEGER NOT NULL, source_order INTEGER NOT NULL)
  # item_names(item_id TEXT NOT NULL REFERENCES items(item_id), lang TEXT NOT NULL, name TEXT NOT NULL,
  #            kind TEXT NOT NULL, norm TEXT NOT NULL, source_order INTEGER NOT NULL)
  #     kind ∈ {'en','zh_loc','zh_loot','aka'}；norm = zh_key()/en_key() 后的比较键
  #     索引 idx_item_names_norm(norm), idx_item_names_item(item_id)
  # item_source_ids(source TEXT NOT NULL, external_id TEXT NOT NULL, item_id TEXT NOT NULL REFERENCES items(item_id),
  #                 PRIMARY KEY(source, external_id))
  #     source ∈ {'uex','loot_uuid','class'}
  # shop_rows(rowid 隐含, uex_item_id INTEGER NOT NULL, shop_name TEXT NOT NULL, place_text TEXT NOT NULL,
  #           price_buy REAL NOT NULL, price_sell REAL NOT NULL, version TEXT NOT NULL,
  #           f0..f5 TEXT NOT NULL, source_order INTEGER NOT NULL)
  #     索引 idx_shop_rows_item(uex_item_id), idx_shop_rows_shop(shop_name)
  # loot_rows(uuid TEXT PRIMARY KEY, en TEXT NOT NULL, cls TEXT NOT NULL, rarity TEXT NOT NULL, n INTEGER NOT NULL, zh TEXT NOT NULL DEFAULT '', source_order INTEGER NOT NULL)
  #     索引 idx_loot_rows_cls(cls)
  # mineral_prices(mineral TEXT NOT NULL, city TEXT NOT NULL, price REAL NOT NULL, PRIMARY KEY(mineral, city))
  # _sources.py
  @dataclass(frozen=True) class Source: name: str; required: bool
  SOURCES: tuple[Source, ...] = (
      Source("shops.json", True), Source("loot_index.json", False), Source("zh_names.json", False),
      Source("zh_only_names.json", False), Source("name_aliases.json", False), Source("wiki_items.json", False),
      Source("prices.json", False),
  )
  @dataclass(frozen=True) class SourceBytes: name: str; present: bool; sha256: str; data: object | None
  def read_sources(data_dir: Path) -> dict[str, SourceBytes]
      # 每个文件读一次字节；sha256 对字节算；json.loads 同一份字节；缺必需文件抛 BuildError；可选文件缺 → present=False, data=None, sha256=""
      # JSON 解析失败抛 BuildError（文件名 + 原始异常）
  ```

- [ ] **Step 1: 写测试**

```python
def test_ddl_creates_all_tables(tmp_path):
    import sqlite3
    from sc_mining.gamedata._schema import DDL
    c = sqlite3.connect(tmp_path / "x.db")
    for s in DDL: c.execute(s)
    names = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
    assert names == {"meta","items","item_names","item_source_ids","shop_rows","loot_rows","mineral_prices"}

def test_read_sources_hash_matches_bytes(tmp_path):
    (tmp_path/"shops.json").write_text('{"items":{},"rows":[]}', encoding="utf-8")
    s = read_sources(tmp_path)
    assert s["shops.json"].sha256 == hashlib.sha256(b'{"items":{},"rows":[]}').hexdigest()
    assert s["loot_index.json"].present is False

def test_read_sources_missing_required_raises(tmp_path):
    with raises(BuildError): read_sources(tmp_path)

def test_read_sources_bad_json_raises(tmp_path):
    (tmp_path/"shops.json").write_text('{"items":', encoding="utf-8")
    with raises(BuildError): read_sources(tmp_path)
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现 `_schema.py`、`_sources.py`**
- [ ] **Step 4: 跑测试通过；ruff + basedpyright 零诊断**
- [ ] **Step 5: 提交**

```bash
git commit -am "feat: 游戏数据层的表结构和试点源文件清单"
```

---

### Task 4: 只读连接与快照

**Files:**
- Create: `sc_mining/gamedata/_db.py`
- Modify: `sc_mining/gamedata/__init__.py`
- Test: `tests/test_gamedata.py`

**Interfaces:**
- Consumes: `Manifest`、`read_manifest()`、`db_path()`、`GamedataUnavailable`
- Produces:
  ```python
  # _db.py
  class Snapshot:
      manifest: Manifest
      @property data_version(self) -> str
      def execute(self, sql: str, params: tuple = ()) -> list[tuple]   # 只读查询；包内 topic 用，不对外
  @contextmanager
  def snapshot() -> Iterator[Snapshot]
      # 同线程嵌套复用最外层快照；最外层退出后清掉 thread-local 绑定
      # 进入时 read_manifest()；None → GamedataUnavailable("游戏数据库还没建")；
      # 打开 sqlite3.connect(f"file:{path}?mode=ro", uri=True)；文件不存在 → 重读清单一次再试，仍失败 → GamedataUnavailable
      # 打开后核对 meta.generation_id == manifest.generation_id，不符 → GamedataUnavailable
      # 连接按 (thread, generation_id) 缓存；同线程换代时关旧连接
  def current_version() -> str | None   # 快照内返回快照的 data_version；快照外 read_manifest() 的 data_version；没有清单 None
  def close_thread_connections() -> None
  # __init__.py 新增
  version = current_version
  snapshot = snapshot
  ```

- [ ] **Step 1: 写测试**

用一个辅助 `_make_db(tmp_path, gen, data_version)`：按 `DDL` 建库、写 `meta` 四个键、写清单。

```python
def test_snapshot_reads_meta(monkeypatch, tmp_path):
    _make_db(tmp_path, "g1", "v1")
    with snapshot() as s:
        assert s.data_version == "v1"
        assert s.execute("select value from meta where key='generation_id'") == [("g1",)]

def test_snapshot_nested_reuses_outer(monkeypatch, tmp_path):
    _make_db(tmp_path, "g1", "v1")
    with snapshot() as a:
        _make_db(tmp_path, "g2", "v2")     # 中途发布新代
        with snapshot() as b:
            assert b is a and b.data_version == "v1"
    with snapshot() as c:
        assert c.data_version == "v2"

def test_snapshot_no_manifest_raises(monkeypatch, tmp_path):
    with raises(GamedataUnavailable): 
        with snapshot(): pass

def test_snapshot_missing_db_file_raises(monkeypatch, tmp_path):
    _make_db(tmp_path, "g1", "v1"); db_path("g1").unlink()
    with raises(GamedataUnavailable):
        with snapshot(): pass

def test_snapshot_generation_mismatch_raises(monkeypatch, tmp_path):
    _make_db(tmp_path, "g1", "v1")
    write_manifest(Manifest("g9", "v1", 1, "gamedata-g1.db"))   # 清单说 g9，库里 meta 是 g1
    with raises(GamedataUnavailable):
        with snapshot(): pass

def test_version_outside_snapshot_follows_manifest(monkeypatch, tmp_path):
    assert current_version() is None
    _make_db(tmp_path, "g1", "v1"); assert current_version() == "v1"
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现 `_db.py`，`__init__.py` 导出 `version`、`snapshot`**
- [ ] **Step 4: 跑测试通过；ruff + basedpyright 零诊断**
- [ ] **Step 5: 提交**

```bash
git commit -am "feat: 游戏数据层的只读连接和操作级快照"
```

---

### Task 5: 导入与建库

**Files:**
- Create: `sc_mining/gamedata/_import.py`
- Create: `sc_mining/gamedata/_build.py`
- Test: `tests/test_gamedata.py`

**Interfaces:**
- Consumes: `read_sources`、`SourceBytes`、`DDL`、`SCHEMA_VERSION`、`IMPORTER_VERSION`、`write_manifest`、`db_path`、`tmp_dir`
- Produces:
  ```python
  # _import.py
  def import_items(conn, sources: dict[str, SourceBytes]) -> None
      # 复现 crafting/itemsearch.py:_build_locked() 的合并顺序和规则：
      #   1. shops.items → entry(en)，首次出现的 uex id 和 cat
      #   2. loot_index.rows → 中英填反纠正、占位名不算中文、loot=True、zh_loot 首个
      #   3. names.table()（直接调 trade.names.table() 复用 _junk 过滤；但它读 paths.DATA，测试里 monkeypatch 即可）→ loc=True、zh 首个
      #   4. wiki_items.items → setdefault wiki、wtype/wsize/desc
      #   5. name_aliases → 仅当 en_key(old) not in by_en 才作为 aka 登记
      #   6. 两轮过滤：zks 与有数据物品重合的仅汉化项去掉；_wiki_noise 去掉
      #   7. zh = zh or zh_loot；gear_zh_of_item 覆盖；variant、has_data、zlen
      # item_id = en_key(en)（itemsearch.en_key，含 shops._fold 的 l→i）；source_order = rows 里的下标
      # item_names：en(kind='en', norm=ek)、每个 zks 一行（kind 按来源 zh_loc/zh_loot，norm=zh_key）、每个 aka 一行（norm=en_key(old)）
      # item_source_ids：('uex', str(iid))、('loot_uuid', uuid)、('class', cls) ；同键重复以先到为准（INSERT OR IGNORE）
  def import_shops(conn, sources) -> None     # shops.rows 原样 7 列展开，source_order = 下标
  def import_loot(conn, sources) -> None      # loot_index.rows 原样 6 列
  def import_prices(conn, sources) -> None    # prices.json["prices"][mineral][city]
  # _build.py
  def data_version(sources: dict[str, SourceBytes]) -> str
      # sha256(json.dumps({"schema": SCHEMA_VERSION, "importer": IMPORTER_VERSION,
      #                    "files": sorted([(name, present, sha256) ...])}, sort_keys=True))
  def new_generation_id() -> str      # time.strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(3)
  def build(sources, generation_id: str) -> Path
      # tmp_dir()/gamedata-<gen>.db.tmp：执行 DDL → 四个 import_* → 写 meta(schema_version, importer_version, data_version, generation_id, build_time, 以及每个源 'src:<name>' = sha256)
      # → commit → PRAGMA quick_check 必须返回 'ok' → 必需表非空检查（items、shop_rows 至少 1 行；源 rows 为空时允许 0 行，测试用小数据）→ close → os.replace 到 db_path(gen)
      # 任一步失败：删临时文件，抛 BuildError
  def publish(generation_id: str, dv: str) -> Manifest   # write_manifest(Manifest(gen, dv, SCHEMA_VERSION, db_path(gen).name))
  def rebuild_if_needed(force: bool = False) -> Manifest
      # with write_lock(): sources = read_sources(paths.DATA)；dv = data_version(sources)；m = read_manifest()
      #   若 not force 且 m 且 m.data_version == dv 且 m.schema_version == SCHEMA_VERSION 且 db_path(m.generation_id).exists() → 返回 m
      #   否则 gen = new_generation_id(); build(...); return publish(gen, dv)
  def cleanup_old_generations(keep: int = 1) -> list[Path]
      # other_instance_running() 为 True → 返回 []（不清理）
      # with write_lock(): 列 gamedata-*.db，排除当前清单的；按 mtime 倒序保留 keep 个；其余 unlink（PermissionError 跳过）；返回删掉的
  ```

- [ ] **Step 1: 写测试**

测试数据用一个最小 JSON 集合（放在 `tests/test_gamedata.py` 里的常量，写进 `tmp_path`）：shops 2 个物品 3 行；loot 2 行（其中一行中英填反）；zh_names 2 条（其中一条是 `_junk` 会过滤的 "HD"）；name_aliases 2 条（一条旧写法已是别的物品的 en）；wiki_items 2 条（一条 `t="Paints"`）；prices 1 矿 2 城。

```python
def test_build_publish_roundtrip(monkeypatch, tmp_path):
    _write_min_sources(tmp_path)
    m = rebuild_if_needed()
    assert read_manifest() == m and db_path(m.generation_id).exists()
    with snapshot() as s:
        assert s.data_version == m.data_version
        assert s.execute("select count(*) from shop_rows") == [(3,)]

def test_rebuild_skips_when_unchanged(monkeypatch, tmp_path):
    m1 = rebuild_if_needed(); m2 = rebuild_if_needed()
    assert m1 == m2   # 同一 generation_id

def test_rebuild_when_source_changes(monkeypatch, tmp_path):
    m1 = rebuild_if_needed(); 改 prices.json 一个数字; m2 = rebuild_if_needed()
    assert m2.generation_id != m1.generation_id and m2.data_version != m1.data_version

def test_build_bad_json_keeps_old_manifest(monkeypatch, tmp_path):
    m1 = rebuild_if_needed(); (tmp_path/"shops.json").write_text("{", encoding="utf-8")
    with raises(BuildError): rebuild_if_needed()
    assert read_manifest() == m1 and not list(tmp_dir().glob("*.tmp"))

def test_import_items_follows_itemsearch_rules(monkeypatch, tmp_path):
    rebuild_if_needed()
    with snapshot() as s:
        # 中英填反的 loot 行：en/zh 已纠正
        # 'HD' 这种假英文名没进 items
        # Paints 类 wiki 项没进 items
        # 有商店的物品 has_shop=1，item_source_ids 里有 ('uex', '171')
        ...

def test_import_alias_does_not_override_existing_item(monkeypatch, tmp_path):
    # name_aliases 里 old 的 en_key 已经是另一物品的 en：不得登记为 aka
    ...

def test_data_version_depends_on_missing_flag(tmp_path):
    # 同样内容，一个可选文件存在但空 vs 不存在 → 版本不同
    ...
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现 `_import.py`**

`import_items` 的内部结构直接按 `itemsearch._build_locked()` 的 7 段顺序写，每段注释标源码行号，便于审查对照。`en_key`、`zh_key`、`_has_cjk`、`_variant`、`_wiki_noise`、`gear_zh_of_item` **直接 import 复用**，不复制。

- [ ] **Step 4: 实现 `_build.py`**
- [ ] **Step 5: 跑测试通过；ruff + basedpyright 零诊断**
- [ ] **Step 6: 用真实 data/ 跑一次（手动验证，不进测试）**

Run: 临时脚本 `from sc_mining.gamedata import _build; m = _build.rebuild_if_needed(force=True); print(m)`，在 worktree 里跑（它的 `paths.DATA` 指向 worktree 的 `data/`，把主仓库 `data/*.json` 复制过去）。
Expected: 几秒内完成；`select count(*) from items` 与 `len(itemsearch._build()["rows"])` 相等；`select count(*) from shop_rows` = 24141（或当前 rows 数）。记录耗时和库文件大小到 `测试数据/gamedata_baseline_20261102.md`。

- [ ] **Step 7: 提交**

```bash
git commit -am "feat: 游戏数据层的试点导入和建库发布"
```

---

### Task 6: 对外入口、并发、清理、启动接入

**Files:**
- Modify: `sc_mining/gamedata/__init__.py`
- Modify: `sc_mining/update/data_pack.py`
- Modify: 应用启动处（调 `itemsearch.warm_up()` 的文件）
- Modify: `tests/run_all.py`
- Test: `tests/test_gamedata.py`

**Interfaces:**
- Produces（`__init__.py`）：
  ```python
  def version() -> str | None                 # = _db.current_version
  def snapshot()                              # = _db.snapshot
  def rebuild(force: bool = False) -> Manifest    # = _build.rebuild_if_needed；阻塞，调用方自己放工作线程
  def ensure_ready() -> Manifest              # 启动用：rebuild_if_needed() 然后 cleanup_old_generations()
  def warm_up() -> None                       # daemon 线程跑 ensure_ready()，异常只打日志（paths.log 或 print），不抛
  def refresh() -> None                       # 清掉本线程的连接缓存并丢弃快照外的版本缓存；供 data_pack.clear_caches 调
  @contextmanager
  def updating() -> Iterator[None]            # 更新边界：with write_lock(): yield；退出时（无异常）rebuild_if_needed()
      # 嵌套 updating() 只在最外层重建
  ```

- [ ] **Step 1: 写测试**

```python
def test_rebuild_concurrent_same_process(monkeypatch, tmp_path):
    # 两个线程同时 rebuild(force=False)：结束后只有一个 generation，清单一致
    ...
    assert len(list(gamedata_dir().glob("gamedata-*.db"))) == 1

def test_updating_rebuilds_once_at_outermost(monkeypatch, tmp_path):
    calls = []; monkeypatch.setattr(_build, "rebuild_if_needed", lambda force=False: calls.append(1) or Manifest(...))
    with updating():
        with updating(): pass
    assert calls == [1]

def test_cleanup_skips_when_other_instance_running(monkeypatch, tmp_path):
    monkeypatch.setattr(_lock, "other_instance_running", lambda: True)
    建两代; assert cleanup_old_generations() == []

def test_cleanup_keeps_current_and_one_previous(monkeypatch, tmp_path):
    monkeypatch.setattr(_lock, "other_instance_running", lambda: False)
    建三代（g1,g2,g3，清单指 g3）; removed = cleanup_old_generations(keep=1)
    assert [p.name for p in removed] == ["gamedata-g1.db"]

def test_warm_up_swallows_errors(monkeypatch, tmp_path):
    # 没有 shops.json：warm_up() 不抛，线程结束后 read_manifest() 仍是 None
    ...

def test_data_pack_clear_caches_calls_refresh(monkeypatch):
    called = []; monkeypatch.setattr(gamedata, "refresh", lambda: called.append(1))
    data_pack.clear_caches(); assert called == [1]
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现 `__init__.py` 入口**
- [ ] **Step 4: `data_pack.clear_caches()` 末尾（`CACHE_HOOKS` 循环之前）加**

```python
try:
    from .. import gamedata
    gamedata.refresh()
except Exception:
    pass
```

- [ ] **Step 5: `data_pack.install()` 成功路径包进更新边界**

把 `with BUILD_LOCK:` 整块外面套 `with gamedata.updating():`（`updating` 在最外层、`BUILD_LOCK` 在里面）；失败回退路径不变（`updating` 遇异常不重建）。

- [ ] **Step 6: 启动接入**

`grep -rn "warm_up()" sc_mining/app` 找到调 `itemsearch.warm_up()` 的那行，紧跟着加 `gamedata.warm_up()`（import 放函数内，和周围写法一致）。

- [ ] **Step 7: `tests/run_all.py` 的 `MODULES` 加 `"tests.test_gamedata"`**

- [ ] **Step 8: 跑全量**

Run: `set AT_FEEDBACK_OFF=1 && python -X utf8 -m tests.run_all`
Expected: 原 468 个全过 + 本文件全部新增用例通过。
Run: `ruff check . && basedpyright --pythonpath .venv\Scripts\python.exe`
Expected: ruff 0 问题；basedpyright 诊断数等于 baseline（无新增）。

- [ ] **Step 9: 提交**

```bash
git commit -am "feat: 游戏数据层对外入口、更新边界、启动预热"
```

---

### Task 7: 命令行工具与文档收尾

**Files:**
- Create: `tools/build_gamedata.py`
- Modify: `docs/superpowers/specs/2026-11-02-gamedata-design.md`（变更记录加一行“地基已实现，签名以代码为准”）

**Interfaces:**
- Produces: `python -X utf8 tools\build_gamedata.py [--force] [--check] [--data <dir>]`
  - 无参：`rebuild_if_needed()`，打印清单
  - `--force`：强制重建
  - `--check`：只读清单和库做 `quick_check` + meta 对照，不建库；不一致退出码 2
  - `--data`：临时覆盖 `paths.DATA`（开发用）

- [ ] **Step 1: 写测试**

```python
def test_cli_build_and_check(monkeypatch, tmp_path):
    _write_min_sources(tmp_path)
    from tools import build_gamedata as T   # tools 目录没有 __init__：用 runpy 或 sys.path 处理，照 tests/test_tools.py 现有做法
    assert T.main(["--data", str(tmp_path)]) == 0
    assert T.main(["--data", str(tmp_path), "--check"]) == 0
    db_path(read_manifest().generation_id).write_bytes(b"garbage")
    assert T.main(["--data", str(tmp_path), "--check"]) == 2
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现 `tools/build_gamedata.py`**（`main(argv) -> int`，`argparse`；运行时逻辑全部 import 自 `sc_mining.gamedata._build`，自己不写建库代码）
- [ ] **Step 4: 跑测试通过；ruff + basedpyright 零诊断**
- [ ] **Step 5: 设计文档变更记录加一行**

`| <日期> | 地基 PR 实现完成：包结构、表名、清单字段、入口函数以 `sc_mining/gamedata/` 代码为准；试点批次接口签名在批 1 开工前按调用点矩阵定稿 | 实施反馈 |`

- [ ] **Step 6: 提交**

```bash
git add tools/build_gamedata.py tests/test_gamedata.py
git add -f docs/superpowers/specs/2026-11-02-gamedata-design.md
git commit -m "feat: 游戏数据库命令行建库工具"
```

---

### Task 8: 审查与交付

- [ ] **Step 1: 新上下文 subagent 读 `REVIEW.md` 后审完整 diff**（`git diff main...feat/gamedata-foundation`），按其摘要格式输出。
- [ ] **Step 2: 在分支上跑 `/code-review` 和 `/security-review`**，逐条修或在 PR 说明里写明不修的理由。≤3 轮。
- [ ] **Step 3: 复跑 Task 6 Step 8 的全量命令**，全绿。
- [ ] **Step 4: 写 PR 说明草稿**（Testing / Risk / How to revert 三项），放 `E:\Claude公主的书\项目资料\记录\PR_gamedata_foundation.md`。Risk 必须写：本 PR 不改任何功能模块的读数据路径，运行时唯一可见变化是启动后台多建一个 `data/gamedata/` 目录和一次建库；How to revert：删分支合并提交 + 删 `data/gamedata/`。
- [ ] **Step 5: 停下等负责人**：实机跑一遍（启动 → 看 `data/gamedata/current.json` 出现 → 更新数据一次 → 清单换代 → 库存功能正常、`dubhe_inventory.db` 字节不变），签字后再推。
