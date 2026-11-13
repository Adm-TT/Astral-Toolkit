# F8 首屏先介绍、后补品质；再按即抢占

状态：已确认  
日期：2026-11-12  
项目：Astral Toolkit（AT）  
范围：`tasks/hover.py`、`trade/inspector.py`、`app/inputs/hotkeys.py`、`app/api/vision.py`、窗口 `hover` 事件；F6 不传新参数。  
风险：中高（读屏识别路径展示时序 + F8 热键并发）

## 变更记录

| 日期 | 改动 | 原因 |
|---|---|---|
| 2026-11-12 | 初稿：渐进 HUD、合作式抢占、非目标、验证 | 方案确认：介绍先出、品质同步后补；再按 F8 作废当前 |

---

## 0. 一句话

认准物品名后立刻把本机介绍推到悬浮窗，同一次调用里继续认品质/数量并马上改第一行；再按 F8 用世代号作废旧识别、立刻开新一轮。

---

## 1. 目标 / 非目标

**目标**

1. 缩短「识别中…」到有用内容的空等（体感首屏更快）。
2. 品质/数量仍在同一次 F8 内同步认完后立刻补上。
3. 再按 F8：作废当前识别与后台补价，启动新一轮（不再「请稍候」）。

**非目标**

- 不中断 OCR 引擎单次推理；不并行 OCR。
- 不把游戏长 `desc` 塞进悬浮窗。
- 不改裁切级联与认名门槛；F6 盘点语义不变。

---

## 2. 渐进展示

`inspect_item(..., on_identified=None)`：在 `zh/en/canon` 定稿后、body 补扫 / 角标 / 制造倒推之前，若 `sure` 且回调非空，调用一次。

`hover_once`：

1. `begin()` 分配 `seq`。
2. 回调：名字 + `_hover_lines`（购买/维科洛/蓝图等）；首行无品质数量；`bus.publish` 带 `pending_quality: True`。
3. `inspect_item` 返回后：补品质/数量/材料品质行；再 publish；再开 `_hover_more`。
4. 第一遍未 sure：不早刷（避免重试前闪错名）。

---

## 3. 抢占

1. 热键 / 窗口「识别」：hover 已在跑也起新任务（`run_task`），入口先 `begin()` 作废旧 `seq`。
2. `inspect_item(..., should_abort=None)`：级联每档后、回调前后、body/角标/craft 检查点；为真则返回 `None`。
3. `hover_once` 各写 HUD / publish / 开补价前核对 `seq`；`RETRY_WAIT` 短睡轮询。
4. `busy`：仅当 `_recognize` 结束且当前无 hover 任务在跑时清掉，避免抢占后被旧线程清 busy。

---

## 4. 验证

单元测试：回调时机、双刷 HUD、seq 作废、热键再按起新任务。全量 `ruff` / `basedpyright` / `tests.run_all` / `junk_check`。
