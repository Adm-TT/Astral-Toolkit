# 库存库正式 schema 迁移通道

状态：实现中（方案 A 已接线；发版版本仍 2）  
日期：2026-11-17  
项目：Astral Toolkit（AT）  
范围：`dubhe_inventory.db`（`astral_toolkit/trade/storage.py`、拟新增 `trade/migrations/` 或 `trade/migrate.py`、`trade/console.py` / `Trade` 打开路径）；**不含** `gamedata`  
风险：中（userdata / 库存文件格式；见 `AGENTS.md` 风险分级）

## 变更记录

| 日期 | 改动 | 原因 |
|---|---|---|
| 2026-11-17 | 初稿：版本模型、打开时序、备份失败策略、与现有启动脚本关系、示范迁移、验收清单 | Grill 共识：先契约后实现；默认原地升级；无绑定真实下一刀 DDL |
| 2026-11-17 | 实现选 **A**：`trade/migrate.py` + `Database` 打开路径接线；发版 `SCHEMA_VERSION` 仍为 **2**；夹具注入测 2→3，不往玩家 SCHEMA 加 demo 表 | 开工令；无真实产品 DDL 不抬发版版本 |

---

## 0. 一句话

给玩家库存 SQLite（`dubhe_inventory.db`）补一条**可重复、可验收**的 schema 升级通道：打开库时按 `PRAGMA user_version` 从旧版本原地升到当前；升前备份；失败不抬版本、库存功能不可用。本轮**只定契约与验收**，不落地实现代码，也不绑定制造变体等产品 DDL。

---

## 1. 目标 / 非目标

**目标**

1. 明确 schema 版本唯一来源与递增规则（`PRAGMA user_version`）。
2. 规定打开库时的升级时序、备份、失败可见性。
3. 划清与现有 `import_v1` / `migrate_cscu` / `normalize_locations` / `fill_keys` 的边界。
4. 用**最小示范迁移**说明「下一刀」怎么写；验收清单可测。
5. 破坏性过大时允许「新文件 + 导入」（路径 B），并写清触发条件。

**非目标**

- 本轮不实现 runner / 不改生产打开路径。
- 不改 `gamedata`（继续换代重建）。
- 不做 down-migrate / 旧客户端打开新库。
- 不把制造变体进主键等产品改动绑进本 spec（另开产品 spec；实现时可与第一刀真实 DDL 合并）。
- 不引入 Alembic / 外部迁移框架 / 第二套 schema 版本号。
- 不自动清理历史备份文件。

---

## 2. 决议摘要

| 项 | 选择 |
|---|---|
| 覆盖范围 | 仅库存 `dubhe_inventory.db` |
| 交付节奏 | 先 spec；实现等真实 DDL 或单独开工令 |
| 升级形态默认 | **A · 原地升级**（ALTER / 补表 / 数据改写在同一库文件） |
| 升级形态例外 | **B · 新文件 + 导入**（见 §6） |
| Schema 版本 | 仅 `PRAGMA user_version` 整数递增 |
| 数据修补登记 | `settings` 或探测式幂等；新修补必须可说明「如何判断已跑」 |
| 触发时机 | 打开库存库时自动（`Database` / `Trade` 构造路径） |
| 失败策略 | 升前备份；失败不抬版本；库存不可用并明示；不静默用半迁移库 |
| 代码落点（实现时） | runner 在 `trade/migrations/` 或 `trade/migrate.py`；DDL / `EXPECTED_SCHEMA` / 当前 `SCHEMA_VERSION` 仍单一来源于 `storage`（或由其导出的「终点」） |
| 示范迁移 | 虚构最小 A 路径（加旁路表或可空列），不绑产品功能 |

---

## 3. 现状（基线，实现时对照）

当前（2026-11-17 / `SCHEMA_VERSION = 2`）**没有** in-place 升级链：

1. **门禁**：`application_id`、`user_version == 2`、表签名与期望一致；否则拒开。
2. **加表**：每次 `CREATE IF NOT EXISTS`（如 `craft_details`）——缺新表不拒开，随后补上；**改列会撞签名**。
3. **启动数据脚本**（`Trade.__init__`）：`import_v1`、`migrate_cscu`、`normalize_locations`、`fill_keys`——幂等靠 flag / 数据探测，失败只打印、不挡启动。
4. **v1→v2**：新文件 `dubhe_inventory.db` + 只读导入旧 `inventory.db`，旧文件不动。

本 spec 要把「拒开旧版本」变成「可升级的旧版本 → 升到当前再打开」；**高于当前的 `user_version` 仍拒开**。

---

## 4. 版本模型

1. **`PRAGMA user_version`**：唯一 schema 代际。当前代码为 `2`；第一次落地迁移框架时，示范或真实 DDL 将把它升到 `3`（或实现时选定的下一整数）。
2. **迁移单元**：`N → N+1` 一步一脚本（或一步一函数），按序执行；不允许跳步。
3. **成功条件**：该步 DDL/数据改写提交成功后，才把 `user_version` 设为 `N+1`。整链跑完后 `user_version == SCHEMA_VERSION`，且通过现有（或更新后的）`EXPECTED_SCHEMA` 签名校验。
4. **数据修补**（不改表形或仅改行内容）：
   - 可挂在「打开且 schema 已是最新」之后；
   - 必须可幂等（`settings` 键或「无目标行则 noop」）；
   - **新**修补必须在文档/代码注释写清判断条件；旧的 `migrate_cscu` / `normalize_locations` 可保留探测式，不强行改写进 schema 链。
5. **不引入**平行的「迁移表版本号」与 `user_version` 双真相；若实现时用 `schema_migrations` 表仅作审计日志，不得与 `user_version` 冲突（以 `user_version` 为准）。

---

## 5. 打开库时序（实现后目标行为）

```
打开 dubhe_inventory.db
  → 读 application_id（不符 → 拒开）
  → 读 user_version V
  → V > SCHEMA_VERSION → 拒开（「库比程序新」）
  → V == SCHEMA_VERSION → 签名校验 → 可用
  → V < SCHEMA_VERSION →
        备份文件（失败则中止，不改库）
        → 按序执行 V→V+1 … → SCHEMA_VERSION
        → 任一步失败：回滚该步事务（能包住的）、不抬 version、库存功能不可用 + 明确错误（含备份路径）
        → 全成功：签名校验 → 可用
  → （schema 已最新后）既有/登记的数据修补（cscu、地点归位等）
  → import_v1 仍仅在「新库且未导入」时走，不属于 in-place 链
```

约定：

- **升级失败时不得假装空库继续写入。**
- 程序其它非库存功能是否可进，沿用现有 Trade 惰性/装配行为；spec 只约束：**库存读写路径必须感知失败**。

---

## 6. 路径 A / B

### A · 原地升级（默认）

适用于：`CREATE TABLE`、加可空列、重建索引、可在事务内完成的数据改写、能保持单文件的约束调整。

### B · 新文件 + 导入（例外）

仅当迁移说明里写明满足**至少一条**：

1. 必须拆/改 `stocks`（或其它余额表）主键，或无法在单库事务内安全完成的约束变更；
2. 需要与旧客户端长期并行、两套文件并存（类比 v1→v2）。

本 spec 的示范迁移走 **A**。走 B 时仍须：备份、可追溯说明、导入失败不覆盖唯一完好副本（细则在该次迁移的产品/实现笔记里写死）。

---

## 7. 备份

- 目录：与库相同的 `SCTradeCompanion`（或测试注入的 directory）。
- 命名：带时间戳，风格对齐现有 `inventory_换算前备份_YYYYMMDD_HHMMSS.db`。
- 每次**升级尝试**成功写出 **1** 份完整文件备份后再改库。
- **备份失败 → 不升级、不抬版本。**
- 不自动删除历史备份；由玩家或支持手动清理。

---

## 8. 与现有启动脚本的关系

| 现有逻辑 | 归类 | 本通道中的位置 |
|---|---|---|
| `import_v1` | 跨代导入（旧 `inventory.db` → 新库） | **不进** in-place 链；单独保留；`settings.v1_imported` |
| `migrate_cscu` | 数据修补 | schema 最新后的 data migration；可继续「有 cSCU 才跑」 |
| `normalize_locations` | 数据修补 | 同上；可继续 match 探测 |
| `catalog.fill_keys` | 业务补全 | **不叫** migration |
| `CREATE IF NOT EXISTS` 补新表 | 现状权宜 | 实现通道后：新表应通过 `N→N+1` 迁移显式加入，并抬 `user_version`；避免再靠「签名对缺表睁一只眼」加结构性对象 |

---

## 9. 代码落点（实现时，本轮不建）

建议：

- `astral_toolkit/trade/migrate.py`（步骤少时）或 `astral_toolkit/trade/migrations/`（包 + 逐步模块）。
- 每步：`from_version: int`、`to_version: int`、`upgrade(connection) -> None`、简短说明（中文）。
- `storage.Database`：打开路径接入 runner；`SCHEMA_VERSION` / `SCHEMA` / `EXPECTED_SCHEMA` 保持单一终点真相。
- 测试：临时目录下的最小夹具库，不碰真实 `%LOCALAPPDATA%`。

---

## 10. 示范迁移（契约用例，非本轮必交付代码）

用最小 **A** 路径证明写法（实现第一刀时可替换为真实 DDL）：

**示例：`2 → 3`**

- 目的：证明补表 + 抬版本。
- DDL：例如 `CREATE TABLE IF NOT EXISTS schema_migration_demo (id INTEGER PRIMARY KEY, note TEXT NOT NULL DEFAULT '');`（正式第一刀若有真实表则改用真实表，删掉 demo）。
- 成功：`user_version=3`，签名含新表，读写 stocks 不受影响。
- 失败注入：备份已存在、`user_version` 仍为 2、再次打开可重试。

禁止把未产品化的 demo 表留在正式发版玩家库而不清理；若仅用测试夹具验证 runner，可不对发版 `SCHEMA_VERSION` 升 3。

---

## 11. 验收清单

实现本通道时至少覆盖：

1. **已是最新**：打开 noop，无新备份或可规定「不备份」。
2. **空库新建**：直接到当前 `SCHEMA_VERSION`，不跑升级链。
3. **旧版夹具**：`user_version = SCHEMA_VERSION - 1`（或从 2 升到实现后的当前值）的最小库，升完可读写 stocks / 记一笔 movement。
4. **升级失败**：注入使某步失败 → version 不涨、有备份、错误明确；修复后可再次打开重试。
5. **库比程序新**：`user_version > SCHEMA_VERSION` → 拒开。
6. **回归**：`v1_imported` / 无 cSCU 时 `migrate_cscu` noop；有 cSCU 的夹具仍能换算（若该脚本仍启用）。
7. **备份失败**：模拟无法写备份 → 不改库。

---

## 12. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 半迁移库被继续写入 | 失败不抬 version；库存 API 拒写；打开路径统一 |
| 备份撑满磁盘 | 备份失败即中止；文档提示可手动删旧备份 |
| 签名校验与逐步 DDL 不一致 | 每步结束后的「终点」必须与 `EXPECTED_SCHEMA` 生成方式一致 |
| 与探测式 data migration 双跑 | 数据修补保持幂等；schema 链不重复做同一改写 |
| 投机框架无真实 DDL | 本 spec 允许「先契约」；无开工令不合并空 runner |

**How to revert（实现合入后）**：发版前发现问题 → 恢复升级前备份文件为 `dubhe_inventory.db`；程序回退到不含新迁移的版本。不提供自动 down-migrate。

---

## 13. 风险分级与审查

- 按 `AGENTS.md`：**中风险**（库存文件格式）。
- 实现 PR 须填 Testing / Risk / How to revert；建议附夹具测试输出。
- 本文件仅方案；实现前若决议变更，先在「变更记录」加行再改正文。

---

## 14. 开放项（实现前可再定，不阻塞本契约）

1. 第一步落地是「只合 runner + 测试用 2→3 demo」还是「必须带真实产品 DDL」——由负责人开工令决定（与 §1 非目标一致）。
2. `schema_migrations` 审计表是否要做——可选，非必须。
3. 备份是否在「noop 最新打开」时也写——默认否（§11.1）。
