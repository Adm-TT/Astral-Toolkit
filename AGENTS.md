# AGENTS.md

## 项目

- 名称：AT（Astral Toolkit，中文名天枢 Dubhe）
- 一句话：《星际公民》的免费、非官方中文玩家工具——读屏识别采矿信号和扫描面板、制造蓝图、导航、物品查询、库存和目标清单。给开着游戏边玩边看的中文玩家用。
- 技术栈：Python 3.12（venv + pip，依赖锁版本）；本机 HTTP 服务 + 原生 JS 前端；窗口外壳 C# WinUI3 + WebView2（ATShell，退回 Edge `--app`）；识别用 RapidOCR + ONNX Runtime（CPU / DirectML）；打包 PyInstaller + Velopack；没有数据库，数据是本地 JSON 文件。
- 目标：
  1. 1.1.3（新架构）正式版已发布（2026-11-01）；之后保持稳定，按模块继续拆分（OCR 已拆到 `astral_toolkit/ocr/`）。
  2. 导航（主城、空间站内设施）准确可用。
  3. 项目规范化：本文件、REVIEW.md、PR 模板、验证命令全部落地。
- 非目标：不读写游戏内存、不改游戏文件、不注入；不做挂机、自动战斗、自动开船、自动交易；不用竞品代码；不收费、不卖数据。详见 `产品设计文档.md` 第 3、9 节。

## 约定

- 代码风格由 formatter 和 linter（ruff）决定，不要手工争论格式。
- 分层：界面接口 `astral_toolkit/app/api/` → 业务 `astral_toolkit/tasks/` → 领域 `astral_toolkit/{mining,navigation,crafting,trade}/`；接口层不写业务逻辑，领域层不碰界面。
- 只读屏幕、不碰游戏：不模拟任何键盘或鼠标输入（读剪贴板、读按键状态做热键不算）。
- 联网的地方必须有超时和失败提示，失败了继续用旧数据。
- 文本输出（文档、报告、说明、记录）一律用 Markdown（`.md`）。例外：打进安装包给玩家看的 `使用说明.txt`、`免责声明.txt`、`商标和图标说明.txt`、`第三方许可.txt` 保持 `.txt`（玩家双击直接用记事本打开）。
- 注释和界面文字用中文；游戏名词用汉化组译名，查不到写英文；导航文字双语「中文（English）」。
- 用户数据（`userdata/`：设置、路标、库存、日志）永远不进仓库、不外传。游戏截图里的玩家信息不用处理。
- 测试不依赖用户设置（monkeypatch 换掉设置文件）、不写真实日志（用 tmp_path）、不往服务器发反馈（`AT_FEEDBACK_OFF=1`）。
- 每次改动完成后，创建一个对应的 Git commit，以便追踪和回滚：在功能分支上做，验证全绿后立即提交，不直接提交到 main。
- 基线（`ruff --add-noqa` 加的 `# noqa`、`.basedpyright/baseline.json`）只用来登记接入前的老问题，不准用来掩盖新问题；改了基线要在 PR 里说明。
- 修 bug 时先找根因，不要只压住症状。
- 变更保持小而独立：一个 PR 解决一个问题。
- 涉及方案的改动（新功能、架构调整、接口变化）先写方案文档再动手：放 `docs/superpowers/specs/`，一个方案一个 `.md`，文件名日期开头，顶部保留「变更记录」表；方案后续有改动先在表里加一行再改正文。该目录不进仓库，供负责人送外部复审和并行会话共用。
- 多个会话并行做一个大改动时：每个会话从负责人指定的基线分支切自己的 worktree（`E:\Game3\AT_wt\<名>`，`data\`、`tests\samples\` 从主仓库拷入）；只改自己计划里列的文件，要动公共层就停下来找控制台（审查合并的那个会话）；交活 = 新上下文审查过、全量测试绿、PR 说明（Testing / Risk / How to revert）和台账放 `E:\Claude公主的书\项目资料\记录\`；不推送、不合并，合并和 baseline 刷新由控制台做。
- PR 说明分两版：放 `项目资料\记录\` 的私有版可以写本机路径和细节；贴到 GitHub 的必须是中性摘要——没有本机路径、没有内部流程词、没有会话链接。
- 更多细节见 `产品设计文档.md`（不要把这些细节复制进本文件）。

## 准备环境（第一次）

- 需要：Windows 10/11、Python 3.12（`py` 启动器）、.NET SDK（编 ATShell 用）。
- 游戏数据 `data/` 和截图样本 `tests/samples/` 由项目负责人提供，放进对应目录；部分测试和截图回归需要它们。数据也可以运行 `.venv\Scripts\python.exe -X utf8 -m astral_toolkit.run update` 下载数据包。

## 验证命令（做完任何改动后必须跑，并把输出贴出来）

在 cmd 里运行：

```bat
rem 安装依赖（锁版本；--no-deps 防止拉进 CPU 版 onnxruntime，和 onnxruntime-directml 冲突）
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --no-deps -r requirements-dev.lock.txt

rem lint + 格式检查
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .

rem 类型检查（自动读 .basedpyright\baseline.json）。只能跑全项目：跑子集会自动改写 baseline.json，跑完 git checkout -- .basedpyright\baseline.json
.venv\Scripts\basedpyright.exe

rem 单元测试（没装 pytest；新测试文件要加进 tests\run_all.py 的 MODULES）
set "AT_FEEDBACK_OFF=1"
.venv\Scripts\python.exe -X utf8 -m tests.run_all

rem 垃圾代码检查（CI 每个 PR 都跑，全量测试也带着它）：和 tools\junk_baseline.json 登记的老问题比，只许减不许加；清掉老问题后按提示加 --write-baseline 收紧
.venv\Scripts\python.exe -X utf8 tools\junk_check.py

rem 构建（PyInstaller + ATShell；需打包依赖和 .NET SDK）
.venv\Scripts\python.exe -m pip install --no-deps -r requirements-build.lock.txt
.venv\Scripts\python.exe -X utf8 tools\build_standalone.py
```

- 说"完成"之前必须实际运行上面的命令，并展示结果，不接受口头确认。
- 通过远程工具操作这台电脑时，单条命令 60 秒会断线：全量测试、建库这类长命令用 `Invoke-CimMethod Win32_Process Create` 起后台 `cmd /c … > 日志文件` 再读文件，别在前台等。
- UI 变更：在 ATShell 窗口里跑一遍，截图并对照 `产品设计文档.md` 第 5 节；悬浮窗变更要在游戏里看。
- 涉及读屏识别（`astral_toolkit/{mining,navigation}/`、`astral_toolkit/runtime/workers/`、`astral_toolkit/ocr/`、`astral_toolkit/trade/inspector.py`、`astral_toolkit/tasks/{hover,count,count_analysis,mining,mining_analysis,navigation_analysis,position}.py`）的改动：额外运行 `.venv\Scripts\python.exe -X utf8 tools\sample_sweep.py`（真实截图全量回归），高风险的再由负责人实机验证。
- 发版时才打安装包：`.venv\Scripts\python.exe -X utf8 tools\build_velopack.py "更新内容"`（vpk 位置见脚本里的 `VPK`）。

## 提交前流程

1. 跑完上面的验证命令，全部绿。
2. 用一个**新上下文的 subagent** 审查完整 diff（不要用写代码的那个上下文自审）：subagent 先读 `REVIEW.md`，按它的标准和摘要格式审。
3. 在功能分支上运行 `/code-review` 和 `/security-review`，逐条处理发现：要么修，要么在 PR 里写明为什么不修。
4. 审查最多 3 轮；第 3 轮后仍有问题，停下来重新考虑方案，而不是继续打补丁。
5. 开 PR 时填写模板中的 **Testing**、**Risk**、**How to revert** 三项。
6. 发起这次变更的人对 PR 内容负责并签字；agent 的批准不算人的批准。

## 风险与审批

- 低风险（文档、文案、开关后面的纯新增）：本地验证全绿、输出贴进 PR，负责人确认后合并。
- 中风险（普通产品改动；设置项和 userdata 文件格式、数据下载与缓存）：1 人批准。
- 高风险（读屏识别、自动更新和升级回滚、输入相关（热键、剪贴板）、数据包发布、安装与打包脚本（含 `tools/build_*.py`）、本机服务的令牌校验、问题反馈上传、远程关功能）：非作者的开发者审代码 + 负责人实机验收，各自在 PR 上批准；只有一位开发者时，用负责人的实机验收记录代替第二人。永远需要人。
- 任何新 commit 都会使已有批准失效。

## 相关文件

- `REVIEW.md`：代码审查器要关注什么
- `产品设计文档.md`：产品定位、设计原则、功能、界面、架构
- `.github/PULL_REQUEST_TEMPLATE.md`：PR 模板
