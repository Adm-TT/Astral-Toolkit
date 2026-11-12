# 物品栏 ROI 面板层（F8/F6）+ 角标子 ROI

状态：待确认  
日期：2026-11-12  
项目：Astral Toolkit（AT）  
范围：`screen_regions.json` / `core/screen_regions.py`、新建 `trade/inventory_panel.py`、`trade/inspector.py`（`cell_labels`）、`trade/count_view.py`、F6 `tasks/count*.py` / `runtime/workers/count.py`；F8 角标路径顺带受益；readlab 可后补识别新字段。  
风险：高（读屏识别：物品栏区域与角标 OCR）

## 变更记录

| 日期 | 改动 | 原因 |
|---|---|---|
| 2026-11-12 | 初稿：面板解析层、左右仓接线、角标贴角 C 档、预留区、等比例多分辨率 | 方案对齐：B 完整地图 + 本轮接线；角标用 cell_box + 相对子 ROI；明确 1K/2K/4K 等比缩放 |
| 2026-11-12 | 补强「分辨率与等比缩放」专节 | 要求支持 1K、4K 等与 2K 标定的等比例缩放 |
| 2026-11-12 | 锁定别名读写与 cell 越界校验约定 | 自审去掉「实施再定」歧义 |
| 2026-11-12 | debug_mode 叠图与 readlab 盘点试跑画出 inventory ROI | 直观核对左右仓/角标/说明框是否套准 |
| 2026-11-13 | `hover.title_rows` / `TITLE_Y1` / `TITLE_ROWS` 底边 0.36→0.30 | 2K 实样：类型/挂点在 ~0.32+，标题带只需名+体积/制造商锚点 |

---

## 0. 一句话

在现有 `screen_regions` 上建立物品栏「面板」ROI 地图与薄解析层：F6 按光标落在左/右仓取区域并盘点；F8 仍用竖带级联（按 2K 收紧）；品质/数量角标在 `cell_box` 上用贴角落、可越界的相对子 ROI；全部区域用归一化比例表达，同一套标定在 1K / 2K / 4K（同比例、同 UI 缩放）下等比生效。

---

## 1. 目标 / 非目标

**目标**

1. 完整物品栏 ROI 地图（左仓、右仓、装备、容量、挂点、说明框参考、格内角标），方便后续功能扩展。
2. 本轮接线：F6 支持左仓 + 右仓（`resolve` 选侧）；F8 说明框保留竖带级联并收紧；角标走 `cell_box` + 相对子 ROI，失败回退旧逻辑。
3. 区域表带轻量元数据（`panel` / `role` / `used_by` / `coord_space` 等），不另建第二份布局文件。
4. **多分辨率等比**：以 16:9 的 2K（2560×1440）为标定语义；1080p（1K）、1440p（2K）、2160p（4K）等只要宽高比接近且游戏 UI 缩放一致，同一套比例框自动映射，不按绝对像素写死。

**非目标**

- 本轮不接线：装备栏盘点、容量 OCR、角色挂点识别、搜索栏逻辑。
- 不按仓切换两套固定 tooltip 框（F8 仍 30–50% / 50–70% 竖带级联）。
- 不用「列 + pitch」完全取代 `cell_box`。
- 不新建独立 `inventory_layout.json`（避免与 `screen_regions` 双真相）。
- 不保证任意 UI 缩放比例（游戏设置里改 UI 缩放导致格距与标定不一致时，只允许「找不到框」，不得给错框——与现有 `cell_grid` 约定一致）。

---

## 2. 决议摘要

| 项 | 选择 |
|---|---|
| 总体方案 | 面板解析层 + 扩展 `screen_regions`（方案 2） |
| 地图范围 | 完整 ROI 地图；本轮只接线左右仓 + 角标 + 收紧竖带 |
| F6 接线 | 左仓 + 右仓，按光标落点选 Panel |
| F8 说明框 | 保留竖带级联，按 2K 收紧上下/带宽 |
| 区域元数据 | 框 + 轻量字段（role / panel / …） |
| 左仓页码/滚动条 | 按「尽量同构」设计；缺则字段 `None`，待截图确认 |
| 角标 | 本轮接线：有 `cell_box` 用相对子 ROI，否则回退旧裁切 |
| 角标相对框 | **C · 宽松贴角**（可越出白框） |

---

## 3. 分辨率与等比缩放

### 3.1 原则

1. **屏幕空间 ROI**（`inventory.*.grid`、竖带、tooltip 等）：`box = [l, t, r, b]`，取值均为截图宽/高的 **0~1 比例**。运行时  
   `px = (int(W*l), int(H*t), int(W*r), int(H*b))`。  
   同一 `aspect`（如 `16:9`）下，1080p / 1440p / 4K 共用一条比例条目，**不**为每种像素分辨率各存一套像素框。
2. **格子相对 ROI**（`inventory.cell.quality` / `stack`）：`coord_space: cell`，`box` 相对当前 `cell_box` 的宽高比例，允许 `<0` / `>1`（贴角落、略伸出格外）；映射到屏幕后再 **clamp 到截图边界**。格子本身随分辨率变大变小，角标子 ROI 同步等比。
3. **格距等启发式**：继续用相对高度的常量（如现有 `PITCH = 0.097`），随 `H` 缩放；列宽检测仍在 `grid` 裁切内做，不写死 2560 像素列坐标（实现时可把 2K 样本列坐标仅作注释/测试期望，运行时仍现量）。
4. **宽高比**：沿用 `screen_regions` 的 `aspect` 选择（`16:9` / `16:10` / `21:9`…）；本轮标定与初值只保证 **16:9**。其他比例：有条目用条目，差距过大则回退代码默认值（现有 `MAX_ASPECT_GAP` 行为）。
5. **标定基准**：语义与注释以 **2560×1440（2K 16:9）** 为准；验收至少覆盖同比例的 1920×1080 与 3840×2160（可用同一张图缩放仿真，或实机各一帧）。

### 3.2 明确支持的分辨率语义

| 俗称 | 典型像素（16:9） | 行为 |
|---|---|---|
| 1K / 1080p | 1920×1080 | 比例框 × 截图尺寸；角标相对格 |
| 2K / 1440p | 2560×1440 | 标定与初值来源 |
| 4K / 2160p | 3840×2160 | 同上等比 |

非 16:9（超宽等）：本轮不新标定；走现有 aspect 回退。游戏高度 &lt; 1080 的警告逻辑保持不变。

### 3.3 实现约束

- 禁止在 F8/F6 新路径里新增「仅对某一绝对分辨率成立」的像素常量（测试里写 2K 期望值除外，断言应尽量用比例或对缩放后的图再算一遍）。
- `inventory_panel.resolve`、角标裁切、`count_view` 取区一律经 `screen_regions.frac` / `px` 或等价「比例 → 当前截图像素」。
- 用缩放仿真做回归：同一 2K 样本缩到 1080 与 4K，`resolve` 命中侧别一致；角标相对框在格内的归一化位置一致（像素不同、比例相同）。

---

## 4. 架构

| 组件 | 职责 |
|---|---|
| `screen_regions.json` | 唯一运行时区域源；新增 `inventory.*`；`count.*` 为右仓别名 |
| `trade/inventory_panel.py`（新） | `resolve(cursor, size) → Panel \| None`；组装该侧像素框 |
| `trade/count_view.py` | 接受 Panel / 区域键；左右复用列/滚动/页码；缺省字段 `None` |
| `trade/inspector.py` | 竖带收紧；`cell_labels` 优先子 ROI |
| `trade/cell_grid.py` | 仍提供 `cell_box`；本轮不替换算法 |
| 预留区域 | header / capacity / equipment / nodes：只进表 |

**数据流**

```
截图(W×H) + 光标
  → inventory_panel.resolve
      ├─ left/right.grid 命中 → F6：该侧 grid/scrollbar?/page? + inspect_item
      │                         角标：cell_box → cell 相对 ROI（比例）→ clamp → OCR
      └─ 未命中 → F8：hover 竖带级联（比例×W/H）
                   角标：同上（不依赖 Panel）
```

---

## 5. 区域键与元数据

### 5.1 键表

| 键 | role | 本轮 | 说明 |
|---|---|---|---|
| `inventory.left.grid` | grid | 接线 | 个人仓格子区 |
| `inventory.left.scrollbar` | scrollbar | 接线* | 缺则 `None` |
| `inventory.left.page` | page | 接线* | 缺则 `None` |
| `inventory.left.header` | header | 预留 | 搜索/筛选 |
| `inventory.left.capacity` | capacity | 预留 | 容量条 |
| `inventory.left.equipment` | equipment | 预留 | 下方装备栏 |
| `inventory.right.grid` | grid | 接线 | 现 `count.grid` 别名 |
| `inventory.right.scrollbar` | scrollbar | 接线 | 现 `count.scrollbar` |
| `inventory.right.page` | page | 接线 | 现 `count.page` |
| `inventory.right.header` | header | 预留 | |
| `inventory.right.capacity` | capacity | 预留 | |
| `inventory.tooltip` | tooltip | 参考 | 现 `count.tooltip`；F8 仍竖带 |
| `inventory.character.nodes` | nodes | 预留 | 角色挂点区 |
| `inventory.cell.quality` | cell_badge | 接线 | 相对格子；贴左上角 |
| `inventory.cell.stack` | cell_badge | 接线 | 相对格子；贴右上角 |
| `hover.band_*` / `title_rows` / `body_rows` | hover | 接线 | 级联保留，2K 收紧 |

\*左仓 scrollbar/page：结构未证实前允许缺省。

### 5.2 条目轻量字段

在现有 `aspect` / `box` / `kind` / `note` 上增加（未知字段读写忽略，兼容旧 readlab）：

```text
panel: left | right | center | shared
role: grid | scrollbar | page | header | capacity | equipment | tooltip | nodes | cell_badge | hover
scrollable: true | false
cols_hint: 4 | null
used_by: ["f6","f8"] | ["reserve"]
coord_space: screen | cell    # cell.* 用 cell；其余 screen
```

`coord_space: cell` 时：`box` 相对 `cell_box`，**允许分量超出 [0,1]**。`screen_regions` 对这类条目放宽 `_box_ok`（仅要求 `l<r`、`t<b`，不强制落在 0~1）；默认值仍写在代码里，JSON 可覆盖。不做第二套存储结构。

### 5.3 兼容别名

- 读：优先 `inventory.right.*` / `inventory.tooltip`，缺则回退 `count.*`（及代码默认）。  
- 写（readlab / 存盘）：只写 `inventory.*` 新键；为免旧工具立刻空白，迁移期可**额外**把右仓四键镜像写入 `count.*`（同一 `box`），但运行时以读路径 fallback 为准，禁止两处手改成不同值。

### 5.4 2K 16:9 初值（比例，待 readlab 微调）

右仓（沿用现 v7，已按样本标定）：

| 键 | box `[l,t,r,b]` |
|---|---|
| `inventory.right.grid` | `[0.7336, 0.2309, 0.9683, 0.8327]` |
| `inventory.right.scrollbar` | `[0.9688, 0.2167, 0.9766, 0.8354]` |
| `inventory.right.page` | `[0.8369, 0.8464, 0.8676, 0.8718]` |
| `inventory.tooltip` | `[0.5, 0.1191, 0.7132, 0.8345]` |

左仓（按同图估的初值，**须实机/readlab 校准**）：

| 键 | box（初值） |
|---|---|
| `inventory.left.grid` | `[0.025, 0.2309, 0.265, 0.65]` |
| `inventory.left.equipment` | `[0.025, 0.66, 0.265, 0.83]`（预留） |
| `inventory.left.header` / `capacity` | 约 `[0.025, 0.12, 0.265, 0.23]`（预留） |
| `inventory.left.scrollbar` / `page` | 待有翻页/滚动截图再填 |

角标（相对格子，**C · 宽松贴角**）：

| 键 | box（相对 cell） |
|---|---|
| `inventory.cell.quality` | `[-0.10, -0.12, 0.48, 0.28]` |
| `inventory.cell.stack` | `[0.52, -0.12, 1.10, 0.28]` |

Hover 收紧：保留 `band_30_50` / `band_50_70` / `band_30_70`；`title_rows` / `body_rows` 按 2K 说明框实样微调（实施时对照样本，本方案不锁死新数字，原则是「收紧、不改级联规则」）。

---

## 6. 调用时序与回退

### 6.1 `resolve`

- 光标 ∈ `inventory.left.grid`（像素）→ `Panel(side=left, …)`  
- 光标 ∈ `inventory.right.grid` → `Panel(side=right, …)`  
- 否则 → `None`

### 6.2 F6

```
grab → resolve
  → 无 Panel：本 tick 不记格身份
  → 有 Panel：
        count_view.spot(panel)   # scrollbar/page 可 None
        cell_box → 角标子 ROI OCR（失败则旧 cell_labels）
        inspect_item(..., body_box=tooltip 参考框)
```

### 6.3 F8

```
grab → 竖带级联 inspect_item
  → 非矿角标：同样优先 cell_box + 子 ROI，失败回退
  → 不依赖 Panel
```

### 6.4 角标裁切

1. 取 `cell_box`。  
2. 相对框 × 格宽高 → 屏幕像素（可越出格）。  
3. clamp 到 `[0,W]×[0,H]`。  
4. `native` OCR；`parse_qlabel` / `parse_count` 不变。

### 6.5 失败表

| 失败 | 回退 |
|---|---|
| 无 Panel | F6 不记格；F8 不受影响 |
| 无 scrollbar/page | Spot 字段 `None`，不伪造 |
| 无 cell_box | 旧光标周围 `cell_labels` |
| 角标 OCR 空 | `cell_q/n = None`，后续品质链不变 |
| 缺新区域键 | 代码默认值；`count.*` 仍可读右仓 |
| 非 16:9 / UI 缩放不对 | 现有 aspect 回退；找不到框优于错框 |

---

## 7. 测试与验收

1. 全量：`ruff` / `basedpyright` / `tests.run_all` / `junk_check`。  
2. 单测：  
   - `resolve` 左 / 右 / 外 → Panel / None  
   - 角标相对框：给定 `cell_box`，C 档映射与 clamp  
   - `count.*` ↔ `inventory.right.*` 别名  
   - **等比缩放**：同一逻辑图缩到 1920×1080 与 3840×2160，命中侧别与角标相对位置（归一化）一致  
3. 样本：右仓盘点不差于现状；左仓至少 resolve + 尝试识别不崩。  
4. 读屏改动跑 `sample_sweep`（无新样本则在 PR 注明）。

---

## 8. 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| 左仓结构不同于右仓 | 中 | 字段可 None；待截图 |
| 贴角越界吃到邻格 | 中 | C 档可再收；保留旧裁切回退 |
| cell_box 半透明失败 | 已有 | 回退旧逻辑 |
| JSON 新字段 / 越界 box 校验 | 低 | cell 放宽或常量默认；旧工具忽略未知字段 |
| 别名不同步 | 低 | 读 fallback；写路径单一约定 |
| UI 缩放 ≠ 标定 | 中 | 文档声明；找不到框；不按分辨率特判瞎偏置 |

---

## 9. 回滚

还原 `screen_regions.json` 与 `inventory_panel` / `inspector` 角标 / `count_view` 相关改动；仅靠 `count.*` 旧键即可恢复右仓盘点路径。

---

## 10. 实施顺序（供后续 writing-plans）

1. 扩展区域 JSON 与 `screen_regions` 对 `coord_space=cell` / 元数据的支持。  
2. 实现 `inventory_panel.resolve` + 别名。  
3. F6 接 Panel；左仓缺省安全。  
4. `cell_labels` 接 C 档子 ROI + 回退。  
5. Hover 带收紧（样本对照）。  
6. 1K/4K 缩放单测 + 样本/实机抽检。
