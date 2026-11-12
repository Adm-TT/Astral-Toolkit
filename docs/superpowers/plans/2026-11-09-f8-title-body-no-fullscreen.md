# F8 标题认名 / Body 品质 / 取消整屏 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 标题带专责认物品名（放宽库精确覆盖多种写法），说明框带专责品质/加成，取消整屏 OCR 与全高竖条，减少误认。

**Architecture:** `_read_tooltip` 高度阶段只保留 `title` + `body`；整屏 `recognize(整图)` 删除。`canonical_exact` / 抽名继续覆盖纯中文、连写「风暴Storm」、短型号 CQ7/TS-2/JS-500、英文模糊≥0.9。标题带库命中后，`inspect_item` 缺品质时补扫 body。

**Tech Stack:** 现有 RapidOCR + `trade/inspector.py` + `trade/names.py`；不换引擎。

**Spec:** `docs/superpowers/specs/2026-11-04-f8-title-band-ocr.md`（2026-11-09 变更）

## Global Constraints

- 只读屏幕，不模拟键鼠
- 注释与界面中文；验证走 `tests.test_inspector` / `tests.test_hover` / `tests.test_f8_retry` / `tests.test_tools_trade` 相关断言
- 不做整屏 OCR 回退

## Review Focus

- 标题带停名后品质是否仍从 body 补到
- CQ7 / TS-2 不被尺寸角标（S1）误收
- 驾驶位中间按 F8 不再整屏、也不误用 HUD 碎字
- F8 第二遍重试不再依赖整屏

## File map

| 文件 | 职责 |
|---|---|
| `astral_toolkit/trade/inspector.py` | 级联阶段、抽名短型号、取消整屏、标题后补 body 品质 |
| `astral_toolkit/trade/names.py` | 库精确已含物品目录与英文模糊；按需微调短键 |
| `docs/superpowers/specs/2026-11-04-f8-title-band-ocr.md` | 变更记录与级联口径 |
| `tests/test_inspector.py` / `test_hover.py` / `test_f8_retry.py` / `test_tools_trade.py` | 级联与整屏相关断言 |

## Task 1: 取消全高档与整屏 OCR

**Files:** `inspector.py`, 相关测试, 方案文档

- [ ] 写/改失败测试：级联只有 title+body；body 之后不再 `recognize` 整图
- [ ] `HEIGHT_STAGES` 去掉 `full`；`_read_tooltip` 删整屏兜底，结束后返回候选或 last
- [ ] 跑相关测试至绿

## Task 2: 短型号与连写名进库精确路径

**Files:** `inspector.py`（`_is_en_name`）, 测试

- [ ] 测试：CQ7、TS-2 算英文名；S1 不算；「风暴Storm」抽名/库精确仍可用
- [ ] `_is_en_name` 字母+数字折叠长 ≥3
- [ ] 跑测试至绿

## Task 3: 标题停名后补扫 body 取品质

**Files:** `inspector.py` `inspect_item`

- [ ] 测试：`where=@title` 且标题 tokens 无品质时，补扫 body 能读到品质行
- [ ] 实现最小补扫（复用 `_tooltip_body_tokens`）
- [ ] 跑测试至绿
