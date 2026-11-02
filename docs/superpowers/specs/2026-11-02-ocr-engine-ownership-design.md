# OCR 引擎归属迁入 `astral_toolkit/ocr/` 设计

状态：**已批准**（2026-11-02，负责人 Adm_TT 批准；作者 NGU 已授权由本项目按自己的思路定实现细节）；代码尚未改造，排在 RT-B4 之后  
日期：2026-11-02  
项目：Astral Toolkit（AT）  
范围：仅「RapidOCR 引擎单例与排队/设备切换」的归属迁移。不含 LLM 辅助识别实现、不含截图模块重划、不含导航 `gridtext` 旁路改写。  
配套：`2026-11-02-at-architecture.md`（其中 OCR / `core/perf` / OcrGateway 相关约束）

## 变更记录

| 日期 | 改动 | 原因 |
|---|---|---|
| 2026-11-02 | 初稿：意图、目标/非目标、迁什么、兼容策略、验证与风险 | 对话确认「统一门面 + 引擎搬进 ocr」 |
| 2026-11-02 | 批准，§8 三项定为：① 新文件 `ocr/runtime.py`；② `perf` 选 **B**，直接删 OCR 符号、不留转发（项目规矩不留兼容别名；仓库外私有工具已查，不引用这些符号）；③ 对外导出 `warmup()`（暖机，不返回引擎）及 `set_ocr_device / ocr_device / gpu_available / last_ocr_error`，不向业务导出引擎对象；测试和 `tools/bench_ocr.py` 可直接用 `ocr.runtime` 内部符号。验证在 §6 之外再跑一次 `tools/sample_sweep.py` | 控制台定，负责人批准 |

---

## 0. 一句话

把目前放在 `core/perf.py` 里的 RapidOCR 引擎宿主（单例、锁与插队、GPU/CPU 切换）迁到 `astral_toolkit/ocr/`，让「认字能力」的实现与对外入口同属一个包；`perf` 只保留进程优先级与截图等平台性能事务。业务模块继续只通过 `astral_toolkit.ocr` 公共 API 认字，为后续在门面内接入大模型辅助留出空间，但本期不实现 LLM。

---

## 1. 意图与成功标准

### 1.1 为什么现在做

- 采矿、导航、交易悬停/盘点等多条链都依赖 OCR；引擎却住在 `perf`，门面在 `ocr/`，归属分裂。
- 后续计划在 OCR 路径接入大模型辅助识别；若不先收口引擎归属，LLM 与设备/排队逻辑会继续散落。
- 整体架构稿已写明：OCR 应作为受管理资源，调用方不自行取得底层全局引擎。

### 1.2 成功标准（本期）

1. 进程内唯一 RapidOCR 实例的创建、缓存、`swap`、GPU 失败回退，代码物理位置在 `astral_toolkit/ocr/`（建议新文件，见 §3）。
2. 生产业务认字路径仍只经 `astral_toolkit.ocr` 的 `recognize` / `read_line` / `raw_detector` / `raw_recognizer`；行为与现网一致（含 `urgent`、`native`、插队语义）。
3. 设置切 GPU/CPU、状态栏「显卡/CPU」、启动暖机、自检与 `tools/bench_ocr.py` 改为经 `ocr` 公共/兼容出口，不再以「业务应依赖 `perf.rapidocr`」为规范。
4. `core/perf.py` 不再持有引擎实现；若保留符号，仅为有时限的薄转发（见 §4），并在变更记录/PR 标明废弃方向。
5. 现有 OCR 相关单测（尤其 `tests/test_gpu_ocr.py`、`tests/test_ocr_module.py`）全绿；涉及读屏的模块不因迁引擎改变识别结果约定。

### 1.3 非目标 / 反目标

| 非目标 | 说明 |
|---|---|
| 实现 LLM 辅助识别 | 只保证日后可在 `ocr/` 内插；本期不改识别算法 |
| 统一或搬迁截图 | `grab_screen` / `grab_region` / `game_area` 等留在 `perf` |
| 改造 `gridtext` | 字模快路径仍属导航域；本期不强制经 RapidOCR |
| 合并 `raw_*` 与 `recognize` 为单一风格 | 两套 API 继续并存 |
| 拆独立 OCR 进程 / 微服务 | 仍为本机同进程 |
| 改变玩家可见设置项语义 | 「显卡/CPU」切换体验保持 |

**反目标：** 迁完之后业务模块（`mining` / `navigation` / `trade` / `tasks`）又直接 import 新的引擎内部模块绕过 `ocr` 包出口。

---

## 2. 现状（已核对源码）

```
领域 / 任务 / 引擎
  → astral_toolkit.ocr.{recognize, read_line, raw_*}
    → ocr.engine._get_engine()
      → core.perf.rapidocr()          ← 真正的单例与 _Locked
        → RapidOCR (+ DirectML 选项)
```

| 位置 | 职责 |
|---|---|
| `astral_toolkit/ocr/engine.py` | 门面：结果整形为 `OcrToken`；`urgent` 时调 `perf.boost()` |
| `astral_toolkit/core/perf.py` | `_Locked`、`_new_engine`、`rapidocr`、`set_ocr_device`、`ocr_device`、`gpu_available`、`is_gpu_preferred`、`last_ocr_error`；另有优先级与截图 |
| 调用 `perf` OCR 符号的非门面点 | `app/engines/manager` 暖机；`tasks/system/settings`；`tasks/system/status`；`selftest`；`tools/bench_ocr`；`tests/test_gpu_ocr` |

已知必须保留的语义：

- `_Locked.swap`：外层对象不变，采矿等处缓存的 `raw_*` 闭包继续有效。
- `urgent` 排队：后台识别让路给 F8/盘点。
- GPU 推理异常：同次锁内切 CPU 重试，设 `_cpu_fallback`，直到用户再切设备。
- `ocr_device()` 查询不因「正在 swap」而与建引擎抢同一把长锁卡死（现实现已区分「已有单例则无锁快路径」）。

---

## 3. 目标结构

### 3.1 包内文件（建议）

| 文件 | 职责 |
|---|---|
| `ocr/models.py` | 不变：`OcrToken` |
| `ocr/engine.py` | 不变对外签名：`recognize` / `read_line` / `raw_*`；内部改为取本包引擎 |
| `ocr/runtime.py`（新建，名称可由实现微调） | 从 `perf` 迁入：`_Locked`、`_new_engine`、单例、`set_ocr_device`、`ocr_device`、`gpu_available`、`is_gpu_preferred`、`last_ocr_error` 及 OCR 相关常量（`OCR_THREADS`、`GPU_PARTS` 等） |
| `ocr/__init__.py` | 继续导出认字 API；**额外导出**设备/状态符号供设置、状态、暖机、自检使用（见下表） |

### 3.2 建议对外（经 `astral_toolkit.ocr`）增加的管理 API

| 符号 | 用途 |
|---|---|
| `warmup` 或继续叫 `rapidocr` | 启动暖机 / 确保引擎已加载；返回共享包装对象 |
| `set_ocr_device` | 设置页切换 |
| `ocr_device` / `gpu_available` / `last_ocr_error` | 状态与自检 |
| （可选）`is_gpu_preferred` | 测试与内部；若不导出则测试改走公开行为 |

认字 API 集合不变。管理 API 与认字 API 同包导出，避免设置/状态再依赖 `perf` 的 OCR 符号。

### 3.3 与 `perf` 的边界

```
ocr/          认字门面 + 引擎宿主 + 设备切换
perf/         lower_priority、boost、grab_*、game_area、遮罩窗口
```

`ocr` **可以**调用 `perf.boost()`（F8 插队抬进程优先级）；**不可以**把截图实现搬进 `ocr`。  
`perf` **不可以**在迁完后仍实现第二套引擎；兼容期转发必须是一行委托到 `ocr`。

### 3.4 依赖方向（迁后）

```
app/engines/manager ──warmup──► ocr
tasks/system/*     ──设备/状态──► ocr
mining|navigation|trade ──认字──► ocr ──(可选)boost──► perf
ocr/runtime ──读设置──► core.settings
ocr/runtime ──记耗时──► core.perfmon.note_ocr（保持现行为）
```

禁止：`ocr` → `app` / `tasks` / 领域模块。

---

## 4. 兼容与迁移步骤（给实现）

推荐单 PR 或「实现 + 删转发」两 PR，由实现选型；语义一次迁完，避免双单例。

1. **新建** `ocr/runtime.py`，把引擎相关代码从 `perf` **剪切**过来（含 `_cpu_fallback` / `_last_error` 行为）。
2. **改** `ocr/engine._get_engine`：改为本包 `runtime` 取单例，不再 `from ..core.perf import rapidocr`。
3. **改** `ocr/__init__.py`：导出管理 API。
4. **改调用方**：`manager` 暖机、`settings`、`status`、`selftest`、`bench_ocr`、相关测试 → `astral_toolkit.ocr`（或 `astral_toolkit.ocr.runtime` 仅限测试若文档允许；优先包出口）。
5. **`perf` 处理（二选一，实现选定并在 PR 写明）：**
   - **A（推荐）：** 删除 OCR 实现；若担心外部脚本，保留 `rapidocr = ...` 等委托到 `ocr` 并在注释标废弃。
   - **B：** 无转发，直接删符号；同步改尽仓库内引用。
6. **不改**领域认字调用点（已走 `ocr`），除非发现直接碰 `perf` OCR 的遗漏。

**禁止：** `perf` 与 `ocr` 各持一个 `_engine` 真实例。

---

## 5. 与整体架构稿的关系

| 架构稿说法 | 本期落地 |
|---|---|
| OCR 已有独立入口，重点调整资源归属 | 本设计的核心 |
| `OcrGateway` / 受管理 OCR 资源 | 本期以 `ocr` 包 + `runtime` 单例为落地形态；不强制先引入新类名 `OcrGateway`。若后续 bootstrap 装配需要网关对象，再包一层，不阻塞本期 |
| `core/perf`：OCR/抓屏留平台适配 | **修订为本期决策：** OCR 引擎改归 `ocr/`；抓屏仍留 `perf`。与架构稿「资源归属阶段」一致方向，归属更明确 |
| 导入功能不得加载 OCR | 保持：仅暖机线程 / 首次认字才加载；`import astral_toolkit.ocr` 不建引擎 |

---

## 6. 验证

按 `AGENTS.md` 常规命令，并额外关注：

- `tests/test_ocr_module.py`、`tests/test_gpu_ocr.py`（含 swap 后闭包仍指向同一外层对象、urgent 语义、CPU fallback）。
- 设置切设备后状态文案与 `ocr_device()` 一致。
- 启动暖机仍指向迁后入口，且进程中仅一份引擎。
- 不要求本期跑全量 `sample_sweep`（未改识别算法）；若实现时误触 `engine.py` 预处理行为，再补 sweep。

---

## 7. 风险

| 风险 | 缓解 |
|---|---|
| 双单例（perf 与 ocr 各建一份） | 剪切而非复制；测试断言 `ocr` 暖机与 `recognize` 同源 |
| 测试大量 patch `astral_toolkit.core.perf.rapidocr` | 迁测试补丁目标；兼容转发期内可双路径但仍只测真源 |
| `perfmon.note_ocr` / `settings` 循环导入 | 保持函数内 import；禁止 `ocr` 顶层 import app |
| 文档/架构稿仍写「引擎在 perf」 | 本文件 §5 + 架构稿后续变更记录补一句 |

---

## 8. 留给实现的决定（不阻塞设计批准）

- 新文件名用 `runtime.py` 还是 `host.py` / `backend.py`。
- `perf` 选兼容转发（A）还是直接删除（B）。
- 管理 API 是否使用 `warmup()` 别名，或继续导出 `rapidocr` 之名以降低测试改名量。

---

## 9. 明确不在本期、供后续议题

- 在 `recognize` / `read_line` 内接入 LLM 辅助（门面已收口后再做）。
- 截图统一入口（与 `mining.screen.grab` 关系）。
- `gridtext` 是否视为 OCR 门面的一种后端。
- 架构级 `OcrGateway` 类与 bootstrap 注入。
