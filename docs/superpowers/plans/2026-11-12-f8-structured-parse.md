# F8 结构化解析契约落地 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在最新 `origin/dev`（已合入 PR #18 标题/body、取消整屏）上，把 `2026-11-11-f8-structured-parse-design.md` 中仍未满足的契约落到代码：矿物标题命中后补扫 body 取品质/SCU；同步刷新规格差距表与模块注释。

**Architecture:** 不改 OCR 引擎与裁切几何。只改 `inspect_item` 在 `@title` 停名后的「要不要补扫 body」条件，使矿物与非矿物共用同一补扫通道；品质优先级保持 body > 角标；颜色品质带仍为非目标。

**Tech Stack:** 现有 RapidOCR + `trade/inspector.py` + `tests/test_inspector.py`；本机 `tests.run_all` / 涉及读屏时 `sample_sweep`。

**Spec:** `docs/superpowers/specs/2026-11-11-f8-structured-parse-design.md`  
**基线:** 当前分支应基于最新 `origin/dev`（含 `feat/f8-title-body-no-fullscreen`）。

## Global Constraints

- 只读屏幕，不模拟键鼠；不换 OCR 模型；不做 OpenCV 颜色品质带
- 身份对库（`canonical*`）与度量数字解析（`tooltip_*` / `parse_*`）保持分通道，禁止用模糊匹配猜品质/数量
- 注释中文；验证：`ruff` / `basedpyright` / `AT_FEEDBACK_OFF=1 python -X utf8 -m tests.run_all`；读屏相关再 `tools/sample_sweep.py`
- 功能分支提交；不直接推 `main`/`dev` 合并

## 已在新 dev 满足（本计划不重做）

| 契约点 | 证据 |
|---|---|
| 标题后非矿物缺品质 → 补扫 body | `inspect_item` 约 925–939 行；`test_no_extra_scan_when_no_blueprint_or_bonus_in_tokens` |
| 品质 body > 角标 | `quality = row_q if … else cell_q …` |
| 角标 F8/F6 共用 | `cell_labels` 对非矿物始终调用 |
| 取消整屏 / 仅 title+body | PR #18；`HEIGHT_STAGES` 仅 title/body |
| 制造倒推走 body | `_tooltip_body_tokens` + `craft_override` |

## 仍待落地

| 契约点 | 差距 |
|---|---|
| 矿物 `@title` 停名后仍要 body 取品质/SCU | 现条件 `not mineral and row_q is None`，矿物直接跳过补扫 |
| 规格 §3/§8 | 初稿写于 PR #18 前，需改成「新 dev 现状」 |
| 模块头注释 | 仍写「全高的裁切级联」，与现实现不符 |

## File map

| 文件 | 职责 |
|---|---|
| `astral_toolkit/trade/inspector.py` | `@title` 后补扫条件含矿物；模块头与 `inspect_item` 文档串 |
| `tests/test_inspector.py` | 矿物标题命中 → 补扫 body 得到品质与 SCU |
| `docs/superpowers/specs/2026-11-11-f8-structured-parse-design.md` | 纳入分支；更新 §3/§8/变更记录 |
| `docs/superpowers/specs/2026-11-04-f8-title-band-ocr.md` | 变更记录一行：结构化语义以 2026-11-11 为准 |

---

### Task 1: 纳入规格并刷新「现状 / 差距」

**Files:**
- Modify: `docs/superpowers/specs/2026-11-11-f8-structured-parse-design.md`
- Modify: `docs/superpowers/specs/2026-11-04-f8-title-band-ocr.md`（仅变更记录一行）
- Ensure present on branch: 上述 2026-11-11 规格（若尚未在树中则从 `docs/f8-structured-parse` 取出）

**Interfaces:** 无代码接口变化。

- [ ] **Step 1: 确认规格文件在工作区**

```bash
test -f docs/superpowers/specs/2026-11-11-f8-structured-parse-design.md
```

若缺失：

```bash
git checkout docs/f8-structured-parse -- docs/superpowers/specs/2026-11-11-f8-structured-parse-design.md
```

- [ ] **Step 2: 在 2026-11-11 规格顶部变更记录加一行，并改 §3 / §8**

变更记录新增：

| 2026-11-12 | §3/§8 按 origin/dev（PR #18）重写：非矿物标题补 body 已落地；仍缺矿物标题补 body | 在新 dev 执行开发前对齐 |

§3 补充：新 `dev` 上 `_read_tooltip` 仅 title→body；`inspect_item` 对非矿物 `@title` 且无 `row_q` 会 `_tooltip_body_tokens`。

§8 差距表改为：

| 点 | 新 dev 现状 | 目标 |
|---|---|---|
| 非矿物标题缺品质 | 已补扫 body | 已满足 |
| **矿物标题缺品质/SCU** | **不补扫**（`not mineral` 条件） | **补扫 body** |
| 品质优先级 / 角标 / 双通道 / 颜色带 | 已符合或非目标 | 保持 |

- [ ] **Step 3: 2026-11-04 规格变更记录加一行**

| 2026-11-12 | 结构化职责（品质优先级、矿物 body 量、双通道）以 `2026-11-11-f8-structured-parse-design.md` 为准；裁切几何仍以本文为准 | 避免两份规格打架 |

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-11-11-f8-structured-parse-design.md \
        docs/superpowers/specs/2026-11-04-f8-title-band-ocr.md
git commit -m "$(cat <<'EOF'
对齐 F8 结构化解析规格与新 dev（PR #18）现状，标出矿物标题补 body 缺口。

EOF
)"
```

---

### Task 2: 矿物 `@title` 停名后补扫 body（TDD）

**Files:**
- Modify: `tests/test_inspector.py`
- Modify: `astral_toolkit/trade/inspector.py`（`inspect_item` 补扫条件；模块头注释）

**Interfaces:**
- Consumes: `_tooltip_body_tokens(img, cursor, where, body_box) -> tokens | None`
- Produces: `inspect_item` 在 `where.endswith("@title")` 且矿物缺 `row_q` 或 `row_amt` 时更新 `tokens` / `quality` / `qty` / `unit`

- [ ] **Step 1: 写失败测试**

在 `tests/test_inspector.py` 末尾附近新增：

```python
def test_mineral_title_hit_rescans_body_for_quality_and_scu(monkeypatch):
    """矿物标题带库命中：标题 tokens 无品质/SCU 时仍补扫 body（契约 2026-11-11 §4.3）"""
    from astral_toolkit import ocr
    from astral_toolkit.trade import inspector

    title = [
        OcrToken("塔兰导电石", 90, (350, 40, 100, 18)),
        OcrToken("Taranite", 90, (350, 64, 100, 18)),
    ]
    body = title + [
        OcrToken("体积：1000000uSCU", 90, (350, 120, 100, 18)),
        OcrToken("925", 90, (500, 400, 30, 16)),
        OcrToken("0.495SCU", 90, (540, 400, 60, 16)),
    ]
    calls = []
    monkeypatch.setattr(
        ocr,
        "recognize",
        lambda img, urgent=False, offset=(0, 0), native=False: (
            calls.append(1) or body
        ),
    )
    monkeypatch.setattr(
        inspector,
        "_read_tooltip",
        lambda img, cur: (title, ("塔兰导电石", "Taranite"), "30-50%@title"),
    )
    monkeypatch.setattr(inspector, "cell_labels", lambda *a, **k: (None, None))
    monkeypatch.setattr(
        inspector, "_is_mineral", lambda zh, en, fuzzy=True: True
    )
    res = inspector.inspect_item(MockImage(), (400, 500))
    assert res is not None
    assert calls == [1], "矿物标题停名后应补扫 body 一次"
    assert res["quality"] == 925
    assert res["qty"] == 0.495 and res["unit"] == "SCU"
    assert res["where"].endswith("@title")
```

另加一条：标题 tokens 已带 `925`+`0.495SCU` 时不补扫（`calls == []`）。

- [ ] **Step 2: 跑测试确认失败**

```bat
set AT_FEEDBACK_OFF=1
.venv\Scripts\python.exe -X utf8 -c "from tests.test_inspector import test_mineral_title_hit_rescans_body_for_quality_and_scu; import pytest; pytest.main(['-q', 'tests/test_inspector.py::test_mineral_title_hit_rescans_body_for_quality_and_scu'])"
```

（macOS / 本仓库若无 pytest 入口，用项目惯用方式：把新测试挂进 `tests/run_all.py` 已含的 `test_inspector` 模块后跑）

```bat
set AT_FEEDBACK_OFF=1
.venv\Scripts\python.exe -X utf8 -m tests.run_all
```

预期：矿物标题用例失败（`calls == []` 或品质/SCU 不对）。

- [ ] **Step 3: 最小实现**

改 `inspect_item` 中补扫条件（约 925–931 行）为：

```python
        need_body_metrics = (
            isinstance(where, str)
            and where.endswith("@title")
            and (
                (not mineral and row_q is None)
                or (mineral and (row_q is None or row_amt is None))
            )
        )
        if need_body_metrics:
            body = _tooltip_body_tokens(img, cursor, where, body_box)
            if body:
                tokens = body
                body_rescanned = True
                row_q, row_amt = tooltip_row(tokens)
                q_from_row_label = False
                if row_q is None:
                    row_q = tooltip_quality(tokens)
                    q_from_row_label = row_q is not None
```

同步：

1. 模块头第 5 行：级联改为「标题带 → 说明框带」（去掉「全高」）。
2. `inspect_item` 文档串：注明矿物 `@title` 缺品质或 SCU 时也会补扫 body。

- [ ] **Step 4: 跑测试至绿**

```bat
set AT_FEEDBACK_OFF=1
.venv\Scripts\python.exe -X utf8 -m tests.run_all
.venv\Scripts\ruff.exe check astral_toolkit/trade/inspector.py tests/test_inspector.py
.venv\Scripts\ruff.exe format --check astral_toolkit/trade/inspector.py tests/test_inspector.py
```

预期：全绿；新矿物补扫用例通过；原有非矿物补扫用例不回归。

- [ ] **Step 5: Commit**

```bash
git add astral_toolkit/trade/inspector.py tests/test_inspector.py
git commit -m "$(cat <<'EOF'
矿物标题带命中后补扫 body 取品质与 SCU，对齐结构化解析契约。

EOF
)"
```

---

### Task 3: 验证与读屏回归

**Files:** 无新增；跑命令。

- [ ] **Step 1: 类型与垃圾检查**

```bat
.venv\Scripts\basedpyright.exe
.venv\Scripts\python.exe -X utf8 tools\junk_check.py
```

预期：exit 0；若 basedpyright 误改 baseline，恢复：

```bat
git checkout -- .basedpyright\baseline.json
```

- [ ] **Step 2: 读屏样本（有样本时）**

```bat
.venv\Scripts\python.exe -X utf8 tools\sample_sweep.py
```

预期：无新增异常；若环境无样本则在 PR 写明跳过原因。

- [ ] **Step 3: 规格变更记录勾「实现已落地」**

在 `2026-11-11` 规格变更记录加：

| 2026-11-12 | 实现：矿物 `@title` 缺品质/SCU 时补扫 body；§8 对应项关闭 | Task 2 |

Commit：

```bash
git add docs/superpowers/specs/2026-11-11-f8-structured-parse-design.md
git commit -m "$(cat <<'EOF'
记录矿物标题补扫 body 已实现。

EOF
)"
```

---

## Spec coverage (self-review)

| 规格条款 | 任务 |
|---|---|
| §4.1 标题身份 / body 品质+矿物 SCU / 角标共用 | Task 2（矿物 body）；角标已有 |
| §4.2 品质 body > 角标 | 已有，不改 |
| §4.3 标题后必跑 body（需度量时） | Task 2 |
| §4.3 降级路径 / 默认 quality=0 | 已有，不改 |
| §5 双通道 | 保持；本计划不加模糊到度量 |
| §7 颜色品质带 | 非目标，不实现 |
| §8 差距表 | Task 1 + Task 3 |

无 TBD /「类似 Task N」占位。
