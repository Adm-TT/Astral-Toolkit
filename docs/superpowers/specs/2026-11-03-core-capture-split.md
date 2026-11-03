# 截图从 `core/perf` 迁入 `core/capture`

状态：已确认（grill 2026-11-03）  
日期：2026-11-03  
项目：Astral Toolkit（AT）  
范围：把 `core/perf.py` 中截图/几何/涂黑实现物理迁到 `core/capture.py`；行为与符号语义不变。  
配套：修订 `2026-11-02-ocr-engine-ownership-design.md` 中「截图留 perf」的过时表述。

## 变更记录

| 日期 | 改动 | 原因 |
|---|---|---|
| 2026-11-03 | 初稿：边界、非目标、调用方清单、验证 | grill 确认 Q1–Q8 |

---

## 0. 一句话

`perf` 只做进程优先级；截图能力住在 `core/capture.py`。不做统一入口、不拆 overlay 向上依赖、不留 `perf` 转发。

---

## 1. 迁出 / 保留

**迁到 `astral_toolkit/core/capture.py`：**  
`overlay_rect`、`own_window_rects`、`mask_overlay`、`_scale`、`_tls`、`_sct`、`_shot`、`_game_area_cache`、`game_area`、`game_size`、`grab_screen`、`grab_region`、`cursor_on_image`。

**留在 `astral_toolkit/core/perf.py`：**  
`lower_priority`、`boost`（及 `_boost`）。

**不做：** 合并 `mining.screen.grab`；解耦 `capture` → `app.overlay` / `system.showloc`；`perf` / `core.__init__` 再导出截图符号。

---

## 2. 调用方（一次改完）

生产：`mining/screen.py`、`app/api/system.py`、`navigation/displayinfo.py`、`tasks/mining.py`、`app/overlay.py`、`app/engines/pos.py`、`tasks/system/status.py`、`trade/inspector.py`。  
测试：`tests/test_tools.py`（含 monkeypatch 目标）。  
注释里写 `perf.game_area` / `perf.mask_overlay` 的改为 `capture`。

---

## 3. 验证

`ruff check` / `ruff format --check` / `basedpyright` / `tests.run_all`。  
不跑 `sample_sweep`（无识别与像素路径行为变化）。
