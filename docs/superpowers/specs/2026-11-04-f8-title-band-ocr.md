# F8 标题带裁切与中英查库加速

状态：已确认（grill 2026-11-04）  
日期：2026-11-04  
项目：Astral Toolkit（AT）  
范围：收紧 F8 说明框 OCR 的垂直裁切级联；同次 OCR 内先中文标题、再英文标题查本地汉化/物品数据；品质/SCU/格子角标逻辑保留但不为它们加大图 OCR。  
风险：高（读屏识别：`trade/inspector.py`、`tasks/hover.py` 相关路径）

## 变更记录

| 日期 | 改动 | 原因 |
|---|---|---|
| 2026-11-04 | 初稿：目标、级联、命中门槛、非目标、验证 | grill 确认 Q1–Q17 |

---

## 0. 一句话

F8 先只 OCR 靠近屏高 24% 的标题带认物（中文→英文查库），不够再加高到 24%–70%、再全高；少送像素以提速，不换 OCR 模型、不做暗色板检测。

---

## 1. 背景与问题

现状 `_read_tooltip`（`astral_toolkit/trade/inspector.py`）按鼠标 X 选**全高**竖条（`get_hover_regions`，top=0、bottom=1），再 RapidOCR。说明框正文、制造商等一并进 det，像素多、偏慢。

观察（待样本复核）：说明框主体大致落在屏高 **24%–70%**；标题中文行贴近 **24%**。

认物并不需要读懂整段描述：本地汉化包 / 物品数据（`trade.names.canonical` 等）可在标题中英上收束。

---

## 2. 目标 / 非目标

**目标**

1. 减少送入 OCR 的像素，降低 F8 识别中位耗时（相对当前全高竖条主路径）。
2. 保持认物准确率不差于现状（样本回归）。
3. 宽度策略、驾驶位保护、品质/SCU/角标**行为保留**（角标等可继续用现有小裁）。

**非目标**

- 黑半透明板视觉检测  
- 换 PP-OCRv5 / v6 或其它 OCR 引擎  
- 本次优化品质 / SCU / 制造槽反推本身  
- 放开整屏兜底（驾驶位保护不变）

---

## 3. 裁切级联

命名常量（初值，可用样本调整；集中定义于 `inspector.py`）：

| 常量 | 初值 | 含义 |
|---|---|---|
| `TITLE_Y0` | `0.24` | 标题带顶（相对截图高） |
| `TITLE_Y1` | `0.36` | 标题带底 |
| `BODY_Y0` | `0.24` | 说明框带顶 |
| `BODY_Y1` | `0.70` | 说明框带底 |

**高度阶段（外层）**

1. **标题带**：`[TITLE_Y0, TITLE_Y1]`，OCR `urgent=True, native=True`  
2. **说明框带**：`[BODY_Y0, BODY_Y1]`，OCR 按现有主路径（非 native，除非实测证明标题带外也该 native）  
3. **全高**：`[0, 1]`，同现有竖条高度  

**宽度（每一高度阶段内）**  
仍调用 `get_hover_regions(cursor, width)`，顺序不变（对侧条带 → 30–70% 等）。

**停止条件**  
某次裁切 OCR 后，按 §4 得到**高把握库命中** → 立刻返回该 tokens / 名字 / 区域标签（标签需能区分阶段，便于日志，如 `30-50%@title`）。

**驾驶位保护**  
与现逻辑一致：鼠标在中间带且全程未见说明框锚点、且无高把握库命中时，**不做整屏**；「全高」仅指当前宽度条带拉满高度，不是 `recognize(整图)`。

失败回退示意：

```
for y0,y1,stage,native in [(0.24,0.36,"title",True), (0.24,0.70,"body",False), (0,1,"full",False)]:
  for 各宽度:
    tokens = recognize(crop, urgent=True, native=native, offset=...)
    name = 抽标题 + 查库（§4）
    if 高把握命中: return
  # 无命中 → 下一高度
# 仍无：与现类似返回 best_candidate / last；中间带无锚点则跳过整屏
```

---

## 4. 标题抽取与查库顺序

同一次 OCR 的 tokens 内：

1. 取靠近标题带上方的**中文名**（沿用 `tooltip_pick` / `_anchor_name` 可用部分；中文折行最多拼 2 行；不拼锚点/属性行）。  
2. **先中文**走 `canonical`（及现有矿物精确路径）。  
3. 仅当中文**非高把握命中**时，用**第二行英文**再查。  
4. 中英都不够 → 本裁切失败，进入下一宽度或下一高度阶段。  
5. 仅有中文、无可用英文（矿石/食物等）且中文未命中 → 直接放大区域，不把正文杂行当第二行。

### 高把握 vs 弱命中

「停」必须是高把握，避免弱模糊中文唯一命中跳过英文：

| 算高把握 | 不算（继续英文或放大） |
|---|---|
| 英文 fold 精确命中汉化索引 | 仅中文 `canonical` 模糊档（当前 ratio≥0.75 那档）且无英文精确 |
| 中文规范化后精确命中 | 多个候选、不唯一 |
| 矿物精确 / 现有 `_mineral` 精确 | `canonical` 返回 `None` |
| （可选实现）英文模糊且 ratio≥0.9 且唯一 | `plausible_name` 有名但未入库 |

实现可抽小函数（如 `_strong_canonical(zh, en) -> (zh,en)|None`），内部复用 `names` 精确路径；弱模糊留给放大后再用完整 `canonical`，或仅在全高阶段放宽——**默认：弱模糊不在标题带阶段停**。

`sure`：窄带路径下以**高把握库命中**为准（不再强依赖「体积」锚点才 sure）；放大后若出现锚点，仍可与现逻辑组合。

黑名单（`_NOT_ITEM`、句子、锚点当名等）仍适用于抽行，避免聊天/HUD 进查库。

---

## 5. 品质 / SCU / 角标

- **保留** `tooltip_row` / `tooltip_quality` / `cell_labels` / 制造反推等现有逻辑。  
- **不为品质**再扫一整段说明框。  
- 标题带 tokens 里碰巧有品质行则用；否则依赖格子角标小 OCR（已有 `native=True`）及现有倒推；拿不到则与现在一样为空/`0` 规则不变。

---

## 6. 触及文件（实现时）

| 文件 | 改动 |
|---|---|
| `astral_toolkit/trade/inspector.py` | 高度常量；`_read_tooltip` 级联；标题抽行+强命中；区域标签 |
| `astral_toolkit/trade/names.py` | 可选：导出「仅精确/强命中」辅助，避免复制 fold 逻辑 |
| `astral_toolkit/tasks/hover.py` | 若依赖 `_read_tooltip` 返回值/日志字段，仅适配标签与耗时说明 |
| `tests/test_inspector.py`、`tests/test_tools.py`（hover 相关） | 级联、native、强命中、驾驶位、中英顺序 |
| `tools/sample_sweep.py` / `tools/bench_ocr.py` | 若写死全高 `HOVER_REGION`，改为可测新阶段或保持对比基线 |

`app/engines/hover.py` 热键入口不改合同。

---

## 7. 验证

说完成前必须实跑（见 `AGENTS.md`）：

1. `ruff check` / `ruff format --check` / `basedpyright` / `AT_FEEDBACK_OFF=1 tests.run_all`  
2. **读屏相关**：`.venv\Scripts\python.exe -X utf8 tools\sample_sweep.py`  
3. `tools\bench_ocr.py`：对比标题带 vs 旧中间全高中位 ms（记录到测试笔记即可）  
4. 人工抽查：标准库存悬停、仅中文名物品、聊天旁说明框、驾驶位中间按 F8（不应整屏）

**通过标准**

- 样本回归认物不差于改前（负责人抽查或 sweep 基线）。  
- 主路径（标题带即命中）中位耗时下降（预期随像素减少；不设死百分比，以 bench 数字为准）。  
- 驾驶位仍不整屏。

---

## 8. 风险与回滚

| 风险 | 缓解 |
|---|---|
| `TITLE_Y1=0.36` 裁掉折行中文第二行 | 样本调常量；失败进 24%–70% |
| 弱模糊被误当成功 | §4 强命中门槛 |
| 品质更少从说明框读到 | 已接受；角标路径保留 |
| UI 缩放导致 24% 不准 | 比例裁切 + 级联放大；极端再调常量 |

回滚：恢复 `_read_tooltip` 全高级联前逻辑（单 PR 易逆）。

---

## 9. 实现顺序建议

1. 加常量与纯函数：给定 `(l,t,r,b)` 列表的阶段生成；强命中判定单测。  
2. 改 `_read_tooltip` 级联；测宽度×高度顺序与驾驶位。  
3. 接 `inspect_item` 日志/`where`；跑 sweep + bench。  
4. PR：Testing / Risk / How to revert；高风险需负责人实机验收。
