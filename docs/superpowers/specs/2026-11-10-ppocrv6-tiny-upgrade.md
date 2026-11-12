# OCR 引擎升级到 PP-OCRv6 tiny

状态：**实现中**（feat/ppocrv6-tiny）；样本基线与 Windows 实机验收待补  
日期：2026-11-10  
项目：Astral Toolkit（AT）  
范围：将识别后端从 `rapidocr-onnxruntime==1.4.4`（PP-OCR 旧代默认模型）迁到新版 `rapidocr`，固定使用 **PP-OCRv6 tiny**；改动集中在 `astral_toolkit/ocr/`、依赖锁、打包与许可、相关测试。  
风险：**高**（读屏识别：`astral_toolkit/ocr/`；连带验证采矿 / 导航 / 交易读屏链路）

## 变更记录

| 日期 | 改动 | 原因 |
|---|---|---|
| 2026-11-10 | 初稿：目标/非目标、依赖与模型、显卡策略变化、改动面、离线打包、验收、tiny→small 退出、回滚与审批 | grill-me 三轮确认（Q1–Q13） |
| 2026-11-10 | 实现钉 `rapidocr==3.10.0`（≥3.7.0 且含 PP-OCRv6 tiny）；本机无 `tests/samples`，§8.1 旧引擎数值基线延后到 Windows 实机 + PR Testing | 开发机 macOS；负责人确认可先落代码/锁/打包 |

---

## 0. 一句话

用新版 RapidOCR 跑 **PP-OCRv6 tiny**，离线打进安装包；业务解析与门面 API 不动，识别正确率不差于现状，必要时按阈值退到 small。

---

## 1. 背景与问题

- 现状依赖：`rapidocr-onnxruntime==1.4.4` + Windows 上 `onnxruntime-directml==1.24.4`（锁文件；安装须 `--no-deps`，避免 rapidocr 顺带拉进 CPU 版 `onnxruntime` 盖掉 DirectML）。
- 引擎宿主在 `astral_toolkit/ocr/runtime.py`：进程内单例、排队 / `urgent` 插队、设置切显卡或 CPU；默认只对 **det** 开 DirectML（`det_use_dml`），**rec** 默认 CPU。
- 业务一律经 `astral_toolkit.ocr`（`recognize` / `read_line` / `raw_*`）；`engine.py` 已分支兼容 `rapidocr_onnxruntime` 与新版 `rapidocr` 两种返回值形状。
- 代码**未**自定义 ONNX 路径，模型随旧包装载；仓库内尚无 PP-OCRv6 升级方案（F8 方案曾明确「不换 OCR 模型」）。
- 公开能力上，新版 `rapidocr`（≥3.x）可选 PP-OCRv5 / v6；DirectML 在 ≥3.7.0 以 `EngineConfig.onnxruntime.use_dml` **整引擎**开关提供（官方标实验性），与现行「只加速 det」不再一一对应。

---

## 2. 目标 / 非目标

### 2.1 目标

1. 识别模型升级为 **PP-OCRv6 tiny**（det + rec 同档）。
2. 依赖迁到新版 **`rapidocr`**（文档约束 **≥3.7.0**，以同时支持 PP-OCRv6 tiny 与实验性 `use_dml`）；**具体小版本在实现时写入锁文件**，本方案不写死补丁号。
3. 卸下 / 停止依赖旧包 `rapidocr_onnxruntime`；迁完后**不再兼容**该包。
4. 模型文件**必须离线打进安装包**；禁止玩家首次启动再从 ModelScope 等源联网下载模型。
5. 保持对外行为契约（见 §4）；`mining` / `navigation` / `trade` 等业务域**零业务逻辑改动**。
6. 正确率以自有样本为据，不劣于升级前基线；不达标时按 §7 退出到 **PP-OCRv6 small**。

### 2.2 非目标

| 非目标 | 说明 |
|---|---|
| 改采矿 / 导航 / 交易业务解析 | 不改面板语义、查库、信号解析逻辑 |
| 重写形近字 / 混淆表 | `i18n`、矿石数字混淆等保持；除非 tiny 引入**新的系统性**错字，再单开变更 |
| 恢复「仅 det 上 DirectML」 | 新 API 无等价官方开关；本期接受整引擎 DML（见 §5） |
| 云端 OCR / VLM | 不上网认字 |
| 改玩家可见设置文案语义 | 仍是「显卡 / CPU」；实现映射变了，文案不另造第三档 |
| 本期就锁死 small / medium | 主路径是 tiny；small 仅退出条件触发后使用 |

**反目标：** 业务模块绕过 `astral_toolkit.ocr` 直接 `import rapidocr`；或安装流程重新引入未加 `--no-deps` 导致 DirectML 被 CPU `onnxruntime` 覆盖。

---

## 3. 现状 → 目标对照

| 项 | 现状 | 目标 |
|---|---|---|
| Python 包 | `rapidocr-onnxruntime==1.4.4` | `rapidocr`（≥3.7.0，实现时钉版本） |
| 模型 | 旧包默认（约 PP-OCRv4 代） | PP-OCRv6 **tiny**（det+rec） |
| 推理 | ONNX Runtime；Win 用 DirectML 包 | 同左；`use_dml` 整引擎 |
| GPU 细粒度 | 默认仅 `det_use_dml` | 选显卡 → `EngineConfig.onnxruntime.use_dml=True` |
| 方向分类 | `use_cls=False` | 保持关闭 |
| 门面 | `astral_toolkit.ocr` | 不变 |
| 打包收集 | `--collect-data rapidocr_onnxruntime` | 改为收集新包（如 `rapidocr`）及 tiny 模型数据，保证离线 |
| 许可清单 | 列 `rapidocr-onnxruntime 1.4.4` | 改为新包名与锁版本；模型仍属 PaddleOCR / RapidOCR 系 Apache-2.0 叙事，按 `collect_licenses` 流程更新 |

---

## 4. 必须保持的行为契约

1. **`use_cls=False`**：不做文本行方向分类。
2. **唯一入口**：生产认字只经 `astral_toolkit.ocr` 公共 API；业务不拿底层引擎对象。
3. **`urgent`**：F8 等插队语义保留（`runtime._Locked.urgent` 或等价）。
4. **`native`**：小裁剪图不强制放大到默认长边（现状约 736px）的语义保留；若新 API 参数名变化，仅在 `ocr/runtime.py`（必要时 `engine.py`）内适配，**调用方关键字与含义不变**。
5. **CPU 回退**：显卡不可用、建引擎失败、或运行中触发既有回退逻辑时，继续可用 CPU；设置再切显卡可重试。
6. **线程纪律**：继续限制 OCR 线程占用（现状 `OCR_THREADS` 上限 6、`inter_op_num_threads=1` 的意图保留；映射到新版等价参数）。

---

## 5. 显卡（DirectML）策略（已知行为变化）

**事实：** 新版公开配置是整引擎  
`params={"EngineConfig.onnxruntime.use_dml": True}`，不是旧的 `det_use_dml` / `rec_use_dml`。

**本期决策：**

- 设置选 **CPU** → 不启用 `use_dml`。
- 设置选 **显卡**，且本机 `DmlExecutionProvider` 可用，且未设 `DUBHE_OCR_CPU=1` → 启用 `use_dml`。
- 建引擎或推理失败 → 沿用现有「回退 CPU 并记住，直到玩家再切设置」的思路。
- **验收以正确率为主**；耗时用 `tools/bench_ocr.py` / `sample_sweep` 对比并记入 PR，不把「必须快于旧 det-only」写成硬门槛，但若显卡路径相对 CPU 明显更慢或更不稳，PR 必须写明，供负责人决定是否默认建议 CPU。

环境变量 `DUBHE_OCR_DML=det,rec` 的旧语义若无法映射，实现时应删除或改为文档说明「已废弃」，避免静默无效。

---

## 6. 改动面（实现指引）

### 6.1 代码（预期）

| 位置 | 做什么 |
|---|---|
| `astral_toolkit/ocr/runtime.py` | 用 `from rapidocr import RapidOCR`；构造时传入 PP-OCRv6 tiny + 线程 + `use_cls` 关闭 + 条件 `use_dml`；调整 `ocr_device()` 等探测若会话结构变化 |
| `astral_toolkit/ocr/engine.py` | 以新包返回值为主路径；去掉对 `rapidocr_onnxruntime` 的分支（或仅留测试不再需要的死代码清理） |
| `tests/test_gpu_ocr.py` 等 | mock / 断言改对新包模块名与构造参数 |
| `tools/build_standalone.py` | `--collect-data` 目标改为新包；确认 tiny 的 onnx（及字典等）进包 |
| `requirements.txt` / 各 `requirements*.lock.txt` | 换包、重锁；安装说明继续强调 `--no-deps` |
| `第三方许可.txt` / `tools/collect_licenses.py` | 包名版本与模型许可条目更新 |

### 6.2 建议构造参数（实现时以所选 rapidocr 版本文档为准）

示意（非最终字面量）：

```python
RapidOCR(
    params={
        "Det.engine_type": EngineType.ONNXRUNTIME,  # 若默认已是 ORT 可省略
        "Det.ocr_version": OCRVersion.PPOCRV6,      # 或文档等价字符串 "PP-OCRv6"
        "Det.model_type": ModelType.TINY,           # 或 "tiny"
        "Rec.engine_type": EngineType.ONNXRUNTIME,
        "Rec.ocr_version": OCRVersion.PPOCRV6,
        "Rec.model_type": ModelType.TINY,
        # 选显卡时：
        # "EngineConfig.onnxruntime.use_dml": True,
        # 另映射 intra_op / inter_op / 关闭 cls 的等价项
    }
)
```

退出到 small 时：仅将 `model_type` 改为 `small`（det+rec 一致），其余不变。

### 6.3 明确不改

- `astral_toolkit/mining/**`、`navigation/**`、`trade/**` 的解析与 UI 逻辑（除非发现调用了已删除的旧包私有符号——应改为继续走 `ocr` 门面）。
- 形近字表、数字混淆表（默认）。

---

## 7. tiny → small 退出条件

主路径锁定 **tiny**。若同时满足：

1. 已按 §8 在**旧引擎**上留下基线；且  
2. 升级后对比基线：采矿面板解析、导航坐标（Display Info）、F8 物品名三条关键链路中，**任一**链路在 `tools/score_samples.py`（有 `answers.json` 时）出现 **净增多的错题（错误题数 − 正确题数的恶化）≥ 3**；**或** `tools/sample_sweep.py` 相对基线**新增异常**；

则允许改锁 **PP-OCRv6 small**，并在本文件「变更记录」加一行说明触发原因与样本摘要。不默认跳到 medium。

无 `answers.json` / 样本时：以 `sample_sweep` 无新增异常 + 负责人实机验收为主；退出条件中的「≥3 净错题」不适用，改由负责人书面判定。

---

## 8. 验收

### 8.1 升级前基线（必须）

在**仍使用旧引擎**的提交上：

1. 有答案时：跑 `score_samples`，记录采矿 / 导航 / F8（或工具实际报告的）关键计数。  
2. 跑 `sample_sweep`，记录异常数与主要耗时摘要。  
3. 将数字写入本方案变更记录或 PR **Testing**（二选一，PR 必有；方案侧至少引用「基线见 PR」或贴摘要）。

### 8.2 升级后（必须全绿才可称完成）

在 cmd / 项目约定环境中：

```bat
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .
.venv\Scripts\basedpyright.exe
set "AT_FEEDBACK_OFF=1"
.venv\Scripts\python.exe -X utf8 -m tests.run_all
.venv\Scripts\python.exe -X utf8 tools\junk_check.py
.venv\Scripts\python.exe -X utf8 tools\sample_sweep.py
```

有 `answers.json` 时再跑 `score_samples`，与 §8.1 对比，满足 §2.1 / §7。

另确认：

- 安装包构建路径能收集到新包模型（抽查输出目录存在 tiny 相关 onnx，且断网可启动认字）。  
- CPU 模式可用；显卡模式在可用机器上可切换，失败能回退。  
- 涉及读屏的改动按 AGENTS：**高风险**——非作者开发者审代码 + 负责人实机验收（仅一位开发者时用实机记录代替第二人）。

### 8.3 UI

设置里「显卡 / CPU」切换与状态展示仍可用；无新增设置项要求。

---

## 9. 风险与回滚

| 风险 | 缓解 |
|---|---|
| tiny 在中文 HUD / 形近字上变差 | §8 基线对比；§7 退 small |
| DirectML 整引擎导致 rec 更慢或不稳 | bench / sweep 记录；可默认建议 CPU；失败回退 |
| 新包首次联网下模型 | 打包强制 collect；断网冒烟 |
| `--no-deps` / 双 onnxruntime 冲突复发 | 锁文件与 AGENTS 安装说明；CI/本地按锁安装 |
| `_native` / 会话探测 API 变更 | 契约测 + `test_gpu_ocr` / `test_ocr_module` |
| 许可与包名遗漏 | `collect_licenses` + 抽查 `第三方许可.txt` |

**How to revert：** 回退本升级 PR（恢复 `rapidocr-onnxruntime==1.4.4`、旧 `runtime`/`engine`、旧 `--collect-data` 与许可）。不提供双引擎运行时热切换。

---

## 10. 文档与流程位置

- 本文件：实现与审查的规格来源。  
- 实现阶段可再拆票（例如：依赖与 runtime、打包离线、样本对比与是否触发 small）；每票仍以本文件为准。  
- 开 PR 时填写模板 **Testing / Risk / How to revert**；Testing 须含基线对比摘要。

---

## 11. 已拍板决策索引（grill）

| 编号 | 决策 |
|---|---|
| Q1 | 产物为 specs 方案规格，非逐步手册 |
| Q2 | 主路径 tiny；达标失败可升 small |
| Q3 | 整包迁到新 `rapidocr`，保留 DirectML 装法纪律 |
| Q4 | 业务解析 / 默认不改混淆表 / 不改「设置语义」以外的 GPU 产品叙事中的 VLM 等均为非目标 |
| Q5 | 全量 lint/type/test/junk + sample_sweep + 有答案则 score + 打包与 CPU 回退 |
| Q6 | 显卡 = 整引擎 `use_dml`；接受相对旧 det-only 的行为变化 |
| Q7 | 模型必须离线进安装包 |
| Q8 | 净错题 ≥3 或 sweep 新异常 → 允许 small |
| Q9 | 只改 ocr 宿主/门面适配 + 锁/打包/许可/测试；不兼容旧包 |
| Q10 | 大纲与路径即本文件 |
| Q11 | 文档约束 ≥3.7.0；补丁版本实现时锁 |
| Q12 | `use_cls=False`、门面、`urgent`、`native` 必须保持 |
| Q13 | 必须先旧引擎基线再对比 |
