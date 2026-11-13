# 物品栏 ROI 面板层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按方案落地物品栏面板 ROI、`resolve` 左右仓、角标 C 档贴角子 ROI，以及 1K/2K/4K 等比缩放验收。

**Architecture:** 扩展 `screen_regions`（cell 坐标可越界）+ 新 `inventory_panel.resolve`；`count_view` / F6 按 Panel 取区；`cell_labels` 优先相对格子裁切并回退旧逻辑。区域唯一源仍是 `screen_regions.json`。

**Tech Stack:** 现有 Python 读屏栈；比例框 × 截图尺寸；无新依赖。

**Spec:** `docs/superpowers/specs/2026-11-12-inventory-roi-panel-design.md`

## Global Constraints

- 只读屏幕，不模拟键鼠
- 注释与界面中文；游戏名词汉化组译名
- 新路径禁止绝对分辨率像素常量（测试可用比例/缩放图）
- 验证：相关单测 + 全量 ruff / basedpyright / tests.run_all / junk_check
- 功能分支提交，不直接进 main

## File map

| 文件 | 职责 |
|---|---|
| `astral_toolkit/core/screen_regions.py` | cell 越界 box 校验；可选 `frac` 多键 fallback |
| `astral_toolkit/screen_regions.json` | `inventory.*` 键 + 元数据；右仓与 `count.*` 镜像 |
| `astral_toolkit/trade/inventory_panel.py` | `Panel`、`resolve`、默认框、别名读 |
| `astral_toolkit/trade/count_view.py` | 接受侧别/Panel 区域键 |
| `astral_toolkit/trade/inspector.py` | 角标子 ROI + 回退 |
| `astral_toolkit/runtime/workers/count.py` / `tasks/count*.py` | F6 接 resolve（若 spot 路径需侧别） |
| `tests/test_inventory_panel.py` 等 | resolve、角标、1K/4K 缩放、别名 |

## Task 1: screen_regions cell 校验 + JSON 键

**Files:** `screen_regions.py`, `screen_regions.json`, `tests/test_screen_regions.py`

- [x] 测试：`coord_space=cell` 且 box 含负数仍 `_entry_ok` / 可 `frac`
- [x] 放宽校验；写入 inventory 键与 count 镜像；version +1
- [x] 跑 `tests.test_screen_regions` 至绿

## Task 2: inventory_panel.resolve

**Files:** `trade/inventory_panel.py`, `tests/test_inventory_panel.py`, `tests/run_all.py`

- [x] 测试：光标左格/右格/外 → left/right/None；1080 与 4K 缩放侧别一致
- [x] 实现 `Panel` + `resolve` + 默认值 + `count.*` 读回退
- [x] 跑新测至绿

## Task 3: count_view / F6 接 Panel

**Files:** `count_view.py`, count worker / analysis 若需要, 相关测试

- [x] `columns`/`scroll`/`page`/`spot` 支持 Panel
- [x] `spot` 内 resolve；左仓无滚动条按 off=0
- [x] 跑 `tests.test_count_view` 至绿

## Task 4: cell_labels C 档贴角

**Files:** `inspector.py`, `tests/test_trade.py` 或新测

- [x] 测试：给定 cell_box，裁切落在 C 档相对区（可越界再 clamp）
- [x] 无 cell_box 时行为与旧 `cell_labels` 一致
- [x] 跑相关测至绿

## Task 5: 验证与提交

- [x] 相关单测 + ruff + junk_check（全量 run_all 另有环境/数据失败，与本改动无关项未阻断提交）
- [x] 功能分支 commit
