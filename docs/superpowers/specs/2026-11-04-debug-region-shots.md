# F8/F6 识别区域调试截图

状态：已确认（grill 2026-11-04）  
日期：2026-11-04  
项目：Astral Toolkit（AT）  
范围：`debug_mode` 下为 F8 / F6 落盘级联 OCR 实际裁切区、标注整屏与 meta.json，便于对照「是否按预期区域读图」。  
风险：中（设置项与 userdata 落盘；读屏路径只增调试旁路，默认关）

## 变更记录

| 日期 | 改动 | 原因 |
|---|---|---|
| 2026-11-04 | 初稿：目标、目录、内容、触发、非目标、验证 | grill 确认 Q1–Q16 |

---

## 0. 一句话

调试模式打开时，F8/F6 每次识别（成败都算）在 `userdata/shots/debug/` 异步落下「每一档 OCR crop + 半分辨率画框整屏 + meta.json」，用来核对裁切区域。

---

## 1. 背景与问题

现状：

- `shots/hover/`：半分辨率**整屏** JPEG，不是 OCR 用的竖条/标题带
- F6：**不**往 `shots/` 写图
- `debug_mode`：只把裁切标签/停因打进运行日志，没有可对照的图

调 F8/F6 识别时，需要看见程序**实际送进 OCR 的框**，而不仅是整屏缩略图或文字日志。

---

## 2. 目标 / 非目标

**目标**

1. `debug_mode` 开启时，F8 与 F6 识别落盘区域调试产物（成功、失败都写）。
2. 产物含：级联**每一档**尝试的原像素 crop、半分辨率标注整屏、`meta.json`。
3. 与现有 `shots/hover` 半屏整图并存；反馈打包不收录 debug 目录。
4. 设置里 `debug_mode` 文案说明会落本地调试图。

**非目标**

1. 不改 F5 `live`/`miss`、导航 `di_fail`。
2. 不改默认关闭时的留图行为；不把 OCR 全文写入 JSON。
3. 不做「打开调试目录」等 UI；不同步写盘拖慢热键主路径。
4. 不把 `shots/debug/` 打进反馈包。

---

## 3. 触发与门控

| 项 | 约定 |
|---|---|
| 开关 | 仅 `settings.debug_mode == True` |
| 任务 | F8（hover）、F6（count） |
| 时机 | 每次识别结束（`inspect_item` 成功返回或未认出）；成败都 dump |
| 写入 | 后台线程异步；失败只打日志，不影响识别结果 |
| 旧 hover | `shots/hover/` 半屏整图逻辑不变 |

---

## 4. 目录与命名

```
userdata/shots/debug/
  hover/<YYYYMMDD_HHMMSS_mmm>/
    attempt_00_<label>.png
    attempt_01_<label>.png
    …
    final_overlay.jpg
    meta.json
  count/<YYYYMMDD_HHMMSS_mmm>/
    cell_00/
      attempt_00_<label>.png
      …
      final_overlay.jpg
      meta.json
    cell_01/
      …
```

- `<label>`：区域标签里的 `%` 等不宜做文件名的字符替换为安全字符（如 `30-50@title`）。
- 序号 `attempt_NN` = 级联尝试顺序。
- F6：一次盘点会话一个时间戳根目录；会话内每次识别（含失败重试）递增 `cell_NN`。
- 保留：`hover/`、`count/` 下各留最近 **5** 个时间戳目录，更早整树删除。

---

## 5. 落盘内容

### 5.1 Crop

- 级联里**每一档**实际 `img.crop(box)` 的原像素 PNG（与送 OCR 一致）。
- 额外读区（格子角标另裁、标题带后的 body 补扫等）进 `extras`，同样落 PNG，文件名 `extra_00_<kind>.png` 或写入 attempts 同序约定在实现里统一；JSON 的 `extras[]` 必有。

### 5.2 标注整屏

- 半分辨率 JPEG（宽高各 `//2`，quality≈80）。
- 灰框 = 尝试过但非最终；绿框 = 最终 `where`（或整屏兜底框）。
- 框旁可写短标签（可选，以能辨认为准）。

### 5.3 `meta.json` 字段

```text
task          "hover" | "count"
ok            bool
where         最终标签或 null/""
stop_reason   停因字符串（有则记）
screen        [W, H]
cursor        [x, y] 或 null
attempts[]    { label, stage, box: [l,t,r,b], used: bool }
extras[]      同上结构（可多 kind/label）
name          可选 [zh, en] 或字符串
note          可选
```

不写入 OCR 全文（对照用现有 `trade_log` / runtime_log）。

---

## 6. 架构落点

| 层 | 职责 |
|---|---|
| 新模块（建议 `astral_toolkit/trade/debug_shots.py`） | 收集会话、画框、异步写盘、保留 5 次 |
| `trade/inspector.py` | `debug_mode` 下在 `_read_tooltip` / `inspect_item` 记录 attempts/extras/停因，结束时 `submit` |
| `app/engines/count.py` | 盘点线程开始时绑定 `count` 运行时间戳；结束解绑 |
| `core/settings.py` + `app/web/app.js` | 更新 `debug_mode` 说明文案 |
| `tasks/system/feedback.py` | **不改**（不收录 debug） |

界面层不写业务；领域旁路只服务调试落盘。

---

## 7. 验证

1. `ruff check` / `ruff format --check` / `basedpyright` / `tests.run_all`（`AT_FEEDBACK_OFF=1`）。
2. 单测：`debug_mode` 关 → `shots/debug` 无新目录；开 → hover 一次产生目录与 meta/attempts；count 绑定后多次识别进同一 run 下不同 `cell_*`；超过 5 次删旧；文件名安全。
3. 实机（负责人）：开调试模式，F8 成功/失败、F6 扫几格，目视框是否与预期区域一致。

---

## 8. 风险与回滚

- 磁盘：仅 debug 开、各 5 次上限；仍可能一次 F6 较大——可接受。
- 回滚：删调试模块与 inspector/count/文案挂钩；或默认保持 `debug_mode=false` 即无落盘。
