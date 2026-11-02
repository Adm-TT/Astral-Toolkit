# OCR 引擎归属迁入 ocr/ Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans (inline). Spec decisions already locked in changelog.

**Goal:** 把 RapidOCR 单例与设备切换从 `core/perf.py` 剪切到 `astral_toolkit/ocr/runtime.py`，公共管理 API 经 `astral_toolkit.ocr` 导出。

**Architecture:** `ocr/runtime.py` 持有唯一引擎；`engine.py` 经本包取引擎；`perf` 只留优先级与截图（方案 B，无转发）。

**Tech Stack:** 现有 RapidOCR / ONNX Runtime；不改识别算法。

**Spec:** `docs/superpowers/specs/2026-11-02-ocr-engine-ownership-design.md`（批准项：`runtime.py`；perf 删符号；导出 `warmup()` 不返回引擎 + 设备/状态四个符号；测试可用 `ocr.runtime`；另跑 sample_sweep）

## Global Constraints

- 禁止双单例；禁止业务 import 引擎对象
- `import astral_toolkit.ocr` 不建引擎
- 保留 swap / urgent / GPU fallback 语义

## Tasks

- [x] T1 新建 `ocr/runtime.py`，从 `perf` 剪切 OCR 宿主；`perf` 删除 OCR 符号并更新模块头注释
- [x] T2 改 `engine._get_engine`、`ocr/__init__.py` 导出
- [x] T3 改 manager / settings / status / selftest / bench_ocr
- [x] T4 改 `tests/test_gpu_ocr.py` / `test_ocr_module.py` / `test_tools` 暖机补丁
- [x] T5 验证：ruff 通过；basedpyright exit 0（基线条目从 perf 迁到 runtime）；`tests.test_gpu_ocr`+`test_ocr_module` 18 passed；全量 run_all 另有与本改动无关的环境/数据失败（见实现记录）
