# 修复 Session Runner 环境变量泄漏到 Bash 工具 — Plan Review Report

## Overview

| Item | Content |
|------|---------|
| Plan File | `plans/fix-runner-env-leak-to-bash.md` |
| Reviewed At | 2026-11-05 16:28 CST |
| Review Scope | 全量评审（Phase 1–3，未指定阶段范围） |
| Overall Score | ⭐⭐⭐ (2.8/5) |
| Verdict | ⚠️ Conditional Pass |

### Dimension Scores

| # | Dimension | Score | Key Finding |
|:-:|-----------|:-----:|-------------|
| 1 | 📋 Completeness | ⭐⭐⭐ | 结构完整、任务可执行；但未引用既有的 `agent_manager._detect_workspace_venvs`，存在重复实现风险 |
| 2 | 🔍 Clarity | ⭐⭐⭐ | 三层剥离/恢复/适配逻辑清晰；但"内部变量"范围未闭环，Task 2.3 引用了不存在的方法名 |
| 3 | 🎯 AC Quality | ⭐⭐ | 缺少端到端 AC —— 没有任何 AC 直接验证"子进程实际看不到 PYTHONPATH 仓库根/PYTHONSAFEPATH" |
| 4 | 🏗️ Feasibility | ⭐⭐ | 技术路线可行（已核实调用点/上下文），但 `pytest --timeout=60` 依赖未安装；PATH 未去污染导致约束不满足 |
| 5 | 🔗 Structure & Dependencies | ⭐⭐⭐ | 阶段顺序合理、并行关系已标注；Task 3.1 应前移至 Phase 1 |
| 6 | ⚠️ Risk Identification | ⭐⭐⭐ | 风险表覆盖面不错（7 条），缺 2 类"残留泄漏"风险 |
| 7 | ⚖️ Proportionality | ⭐⭐⭐⭐ | 3 Phase / 8 Task 对跨切面改动基本相称，个别任务可合并 |
| 8 | ✅ Internal Consistency | ⭐⭐ | 目标"干净环境"与"恢复服务进程 VIRTUAL_ENV"存在语义张力；venv 探测约定与既有代码不一致 |
| | **Overall** | **⭐⭐⭐ (2.8/5)** | **方案方向正确，但有 4 项须在开工前修正的问题** |

### 核实结果（Reviewer 已对照源码验证）

| 计划中的假设 | 核实结论 | 证据 |
|---|---|---|
| `build_runner_env()` 设置了 `PYTHONPATH`/`PYTHONSAFEPATH`/`BROCA_RUNNER_CHILD`/`LITELLM_LOCAL_MODEL_COST_MAP` 并 pop `VIRTUAL_ENV` | ✅ 准确 | `broca/session_runner/process/launcher.py:57-75` |
| 用户命令执行点共 2 处（`bash.py` / `process_manager.py`） | ✅ 准确（全仓仅 2 处 `create_subprocess_shell`） | `broca/tools/bash.py:302`、`broca/process_manager.py:149` |
| `ToolCallContext.workspace` 会被填充，可供 `_execute()` 传递 | ✅ 成立 | `broca/loop_engine/engine.py:1025`（`ctx.workspace = self.config.workspace`） |
| `runner` 进程 cwd == workspace（故 `cwd=None` 时 `os.getcwd()` 即 workspace） | ✅ 成立（launcher 以 `cwd=workspace` 启动，全仓无 `os.chdir`） | `launcher.py:119`、`grep -rn "os.chdir" broca/` 无结果 |
| `broca/utils/__init__.py` 无需修改 | ✅ 准确（空文件），新模块无循环导入风险 | `broca/utils/__init__.py`（空）、`logging_config.py` 仅依赖 stdlib+loguru |
| `scheduler.execute_command_job()` 调用 `ProcessManager.start_process` | ❌ **不准确** —— 实际方法名为 `_execute_command` | `broca/scheduler.py:476-487` |
| `snapshot/git_manager.py` 使用 `create_subprocess_shell` | ❌ **不准确** —— 实际使用 `create_subprocess_exec`（注释里才提到 shell） | `broca/snapshot/git_manager.py:494-498` |

## Detailed Findings

### 1. 📋 Completeness — ⭐⭐⭐

**Summary**: 六个必需章节齐备（概述/相关材料/总体方案/执行计划/风险与应对/未解决的问题），每个 Phase 有阶段 AC，每个 Task 有目标、步骤、预期产出与 2–5 条 AC，达到可执行标准。主要缺口是"相关材料"未覆盖既有实现，导致重复造轮子。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Major | 相关材料 / Task 1.1 | 仓库已有 venv 扫描实现 `DefaultAgentFactory._detect_workspace_venvs()`（`broca/agent_manager.py:477-518`），且候选清单与校验方式与计划不同（见 D8）。计划未引用该文件，将产生第二套 venv 探测逻辑 | 在"相关材料"补充 `broca/agent_manager.py`；Task 1.1 增加一步："评估复用/下沉 `_detect_workspace_venvs` 为公共函数（如 `broca/utils/env.py::find_workspace_venv`），避免两份不一致的实现" |
| 2 | Minor | Task 2.3 | 计划判定 `git_manager.py`"不需修改"，但其 `_run_git` 用 `os.environ.copy()` 构造 env（`git_manager.py:490-492`），因此 `PYTHONSAFEPATH`/`PYTHONPATH` 仍会传入 git hook（pre-commit 等 python 钩子） | 在 Task 2.3 明确记录该泄漏路径的处置结论（接受/改用 `build_user_env(workspace)`），并写入风险表 |
| 3 | Minor | Task 2.1 | bash 工具 `description` 明确写着"Your default python path points to a special standalone python environment"（`bash.py:43-46`）。改动后 workspace 有 venv 时 `python` 会自动切换，提示词与行为不符 | 增加一步：更新 tool description 表述（"优先使用 workspace 的 `.venv`，否则回退服务环境"） |
| 4 | Minor | Task 1.2 | `_BROCA_ORIG_*` 是跨进程契约（supervisor 写入、runner 消费），计划只在代码注释里定义，未指定契约说明位置 | 指定写入位置（如 `launcher.py` 模块 docstring 或 `broca/utils/env.py` 顶部"契约"注释块），与现有 `launcher.py:1-20` 的 argv 契约写法保持一致 |

### 2. 🔍 Clarity — ⭐⭐⭐

**Summary**: 三层（剥离/恢复/适配）模型是本文档最强的部分，优先级规则（第 3 层 > 第 2 层）表述明确。但"内部变量"的边界没有闭环，且存在一处引用不存在 API 的事实性错误。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Major | 总体方案 层1 / Task 1.1 步骤 3 | 只枚举了 4 个待剥离变量，但仓库中还有 `BROCA_HOME`、`BROCA_DATABASE_DIR`、`BROCA_COMPONENTS_CONFIG`、`BROCA_RUN_INTEGRATION` 等 `BROCA_*` 变量（grep 全仓可见）。"剥离 runner 内部变量"的边界不清：是全剥 `BROCA_*`，还是白名单？执行者必须猜 | 明确规则，例如："剥离以下 4 个 runner 标记 + 所有 `_BROCA_ORIG_*` 前缀变量；其余 `BROCA_*`（BROCA_HOME 等）视为用户可用配置**保留**"，并给出保留/剥离的判定理由与一条对应 AC |
| 2 | Major | Task 2.3 步骤 1–3 | 引用不存在的方法 `scheduler.execute_command_job()`（实际为 `broca/scheduler.py:476` 的 `_execute_command`）；同时误判 `git_manager.py` 使用 `create_subprocess_shell`（实为 `create_subprocess_exec`） | 改为 `scheduler._execute_command()`；更正 `git_manager` 的调用方式描述（结论"不需修改"可保留，但理由要重写） |
| 3 | Minor | 概述 / 风险表 / Task 1.2 | 术语混用：`概述`说"服务进程"，`Task 1.2`说"父进程"，风险表说"Runner 进程自身 import 不受影响"，而"服务进程 venv"与"runner venv"实际是同一个解释器。读者易误解 `_BROCA_ORIG_*` 的写入方 | 在"总体方案"开头加术语约定：**supervisor**（写 `_BROCA_ORIG_*` 的进程）/ **runner**（读 `_BROCA_ORIG_*`、执行工具调用）/ **workspace**，全文统一 |
| 4 | Minor | Task 2.2 步骤 2 与 AC #2 | `# cwd 即 workspace 或 None` 未定义：`ProcessManager.start_process(cwd=...)` 的 `cwd` 是任意工作目录（可能是 workspace 子目录或相对路径），与 `context.workspace` 不是同一概念；`build_user_env(cwd)` 在子目录下会漏检 workspace 根 venv | 明确："venv 探测基于 `cwd` 或其父级 workspace 根"，或统一改为传 workspace 根（需说明 scheduler 路径如何获得 workspace） |
| 5 | Minor | Task 1.1 步骤 3 | 未说明 PATH 去重（workspace venv 已在 PATH 中时重复前置）与 `VIRTUAL_ENV_PROMPT` 取值格式（`.venv` 还是 `(.venv) `，与 `activate` 脚本一致？） | 增加两句规范：PATH 前置前去重；`VIRTUAL_ENV_PROMPT` 取值与 venv `bin/activate` 生成值保持一致 |

### 3. 🎯 AC Quality — ⭐⭐

**Summary**: 大部分 AC 是"可观测、可断言"的好 AC（例如 `_BROCA_ORIG_PYTHONPATH=/custom/path`、`PATH` 首位为 `.venv/bin`、`0 failures, 0 errors`）。核心缺陷是**整份计划没有任何 AC 直接验证最初要修的 bug 本身**——即"用户命令子进程的环境里不再有 `PYTHONPATH=仓库根` 和 `PYTHONSAFEPATH=1`"。单测只验证"env 字典构造正确"，代码级断言只验证"传了 `env=` 参数"，二者都不覆盖真实子进程。

| # | Severity | Location | AC | Issue | Suggestion |
|:-:|:--------:|:--------:|----|-------|------------|
| 1 | Major | Phase 1/2/3 全部 | 无 | 缺失端到端 AC：没有 AC 断言"实际子进程 env 不含 `PYTHONPATH` 仓库根 / `PYTHONSAFEPATH` / `BROCA_RUNNER_CHILD`" | 新增 Task 2.4（或并入 3.x）：仿照 `broca/tests/test_runner_launcher.py:263-320` 已有的 subprocess 断言模式，用 `build_runner_env()` 构造污染环境后启动 `python -c "import os,sys;print(os.environ.get('PYTHONSAFEPATH'), sys.path[0])"`，断言 `PYTHONSAFEPATH` 为 None 且 `sys.path[0]` 为 `''`（cwd 重新生效） |
| 2 | Major | Phase 3 阶段 AC | "手动验证：在含 venv 的 workspace 中执行 `python --version` 返回 venv 版本" | 手工验证不可复现、无法回归；且 `python --version` 恰好是**区分度最低**的检查（即使 PATH 未改，版本号也可能相同），完全不覆盖 `PYTHONPATH`/`PYTHONSAFEPATH` 泄漏 | 换成可自动化的检查：`python -c "import sys;print(sys.executable)"` 断言指向 `workspace/.venv/bin/python`；并把"仓库根不在 `PYTHONPATH`/`sys.path`"作为断言 |
| 3 | Minor | Task 2.3 AC #1 | "Scheduler 触发的命令执行使用干净环境" | 无验证手段（无测试、无命令），属于不可判定 AC | 明确验证方式：在 `broca/tests/test_process_manager.py` 增加 case，`pm.start_process("python -c \"import os;print(os.environ.get('PYTHONSAFEPATH'))\"")` 后读 stdout 断言为空 |
| 4 | Minor | Phase 1 阶段 AC #4 | "单元测试通过" | 范围模糊（哪一套测试？是否含 `test_runner_launcher.py`？），与 D5 的跨阶段阻塞问题相关 | 改为 "`pytest broca/tests/test_env_utils.py -v` 全绿，且 `pytest broca/tests/test_runner_launcher.py -v` 无新增失败" |

Good ACs identified:
- Task 1.2: "父进程有 `PYTHONPATH=/custom/path` 时，runner env 中 `_BROCA_ORIG_PYTHONPATH=/custom/path`" — ✅ 具体、可断言、双向覆盖（有值/无值两条）。
- Task 1.1: "workspace 含 `.venv` 时 PATH 首位为 `.venv/bin`，`VIRTUAL_ENV`/`VIRTUAL_ENV_PROMPT` 正确设置" — ✅ 可观测且与层 3 目标一一对应。
- Task 1.3: "`pytest broca/tests/test_env_utils.py -v` 全绿" — ✅ 可执行、可判定的门禁。
- Task 3.2: "0 failures, 0 errors / 无新增 skip/xfail" — ✅ 明确量化，能防"用 skip 掩盖回归"。

### 4. 🏗️ Feasibility — ⭐⭐

**Summary**: 技术路线成立——已核实调用点仅 2 处、`context.workspace` 可用、runner cwd 即 workspace、`utils/__init__.py` 为空故无循环导入、`build_runner_env()` 每次 spawn 重新调用故重启无状态残留。两处实现层面的问题会让计划在第一步就卡住或达不到自定约束。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Major | Task 3.2 步骤 1 / Phase 3 AC | `pytest broca/tests/ -x --timeout=60` 不可执行：`pytest-timeout` 既不在 `pyproject.toml` 依赖中，也未安装在当前 venv（`import pytest_timeout` → `ModuleNotFoundError`）。命令会以 "unrecognized arguments: --timeout=60" 失败，而这是 Phase 3 的唯一自动化门禁 | 二选一并写入计划：①去掉 `--timeout=60`（`pyproject.toml:59-63` 已有 `addopts = -m 'not perf'`）；②新增 Task 声明"把 `pytest-timeout` 加入 dev 依赖" |
| 2 | Major | 约束条件 / 层 2 / Task 2.2 | 约束"无 venv 的 workspace 行为应等同于用户普通 shell"**不成立**：层 2 只恢复 `PYTHONPATH`/`VIRTUAL_ENV`/`VIRTUAL_ENV_PROMPT`，而 `PATH` 里仍保留 supervisor 的 `venv/bin` 首位（`build_runner_env()` 从不改 PATH），故无 venv 的 workspace 中 `python` 仍指向 Broca 服务 venv，且 `VIRTUAL_ENV` 被恢复成服务 venv | 显式决策并写入计划：①保留现状（服务 venv 作为兜底解释器）→ 修改约束表述并在 AC/风险中记录；或 ②层 2 同时把服务 venv 的 `bin` 从 PATH 中剔除（需处理"剔除后无 python 可用"的边界） |
| 3 | Minor | Task 1.3 / 风险表 Windows 行 | 用 `monkeypatch` 改 `os.name` 模拟 Windows 不可靠：`pathlib.Path` 仍按 POSIX 语义解析，`Scripts\activate.bat` 路径拼装/`os.pathsep` 行为与真实 Windows 不一致，容易写出"通过但无效"的测试 | 把平台差异下沉为纯函数（`_venv_bin_dir(venv_root, platform: str)` / `_activate_relpath(platform)`），单测直接以参数注入平台字符串，避免 monkeypatch `os.name` |
| 4 | Minor | Task 2.2 | `build_user_env(cwd)` 传入相对路径或子目录时 venv 探测失效（`_find_workspace_venv` 只在给定目录下找 3 个候选名），而 `start_process` 的 `cwd` 语义是任意工作目录 | 规定 `build_user_env` 入参必须为绝对 workspace 根；或探测时向上回溯（并限制深度），在 Task 1.1 中写明 |

### 5. 🔗 Structure & Dependencies — ⭐⭐⭐

**Summary**: Phase 1（工具层）→ Phase 2（注入点）→ Phase 3（回归）符合"先能力后接入再验证"的自然顺序；Task 1.1/1.2 与 Task 2.1/2.2 的并行关系已在阶段内显式标注（本计划优于同类文档的一点）。问题集中在测试任务与实现任务的阶段错配。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Major | Task 3.1 vs Task 1.2 / Phase 1 AC | Task 1.2 修改 `build_runner_env()` 会立即影响 `broca/tests/test_runner_launcher.py`（该文件从 `broca.session_runner.manager` re-export 导入，见 `manager.py:44-49`），但更新它的任务排在 Phase 3。若 Phase 1 门禁包含该文件，则 Phase 1 无法收尾；若不含，则 Phase 1 会带着"未验证的既有测试"进入 Phase 2 | 把 Task 3.1 拆成两半：`1.4 更新 test_runner_launcher.py 的 env 断言`（紧跟 1.2，Phase 1 内完成）；Phase 3 只保留全量回归。或在 Phase 1 AC 中显式排除该文件并说明原因 |
| 2 | Minor | Task 2.3 | "确认/验证"型任务夹在实现阶段末尾，与 Phase 3 职责重叠；若 grep 发现新遗漏点，计划未给处理路径 | 为 Task 2.3 增加出口条件："若发现未覆盖的用户命令执行点，新增 Task 2.4 处理并更新 Phase 2 AC，不得只记录结论" |
| 3 | Minor | Task 3.2 | 隐含依赖 Task 3.1（先改测试再全量跑），未声明 | 在 Task 3.2 标注"依赖 Task 3.1 完成" |

### 6. ⚠️ Risk Identification — ⭐⭐⭐

**Summary**: 风险表存在且质量中上——7 条风险覆盖了 venv 命名覆盖度、`_BROCA_ORIG_*` 被用户脚本误用、异常 fallback、Windows 兼容、`PYTHONSAFEPATH` 依赖方、runner 自身不受影响、重启后无状态残留。缺口是两类"修复不彻底"的残留泄漏没有被识别为风险，而它们正是本 bug 的同类问题。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Major | 风险表 | 缺"supervisor 自身已带 `PYTHONPATH`（如开发模式 `PYTHONPATH=. python -m broca`）→ 层 2 恢复后仍把仓库根传给用户命令"的风险。此时修复对该类部署无效，但计划未声明这一已知限制 | 增加风险行：影响=开发/自托管场景仍有残留污染；应对=文档声明"只恢复到 supervisor 环境"，并加一条 AC 或"未解决问题"条目 |
| 2 | Major | 风险表 | 缺"PATH 首位仍为 Broca 服务 venv（无 venv 的 workspace）"风险——与 D4-2 同源，但作为风险未登记，容易被当成已解决 | 与 D4-2 的决策保持一致地登记风险及应对 |
| 3 | Minor | 风险表 | 缺"现有后台/长任务测试（`test_process_manager.py`、`test_long_running_task.py`）行为变化"风险：这些测试真实 `start_process`，注入 env 后解释器/PATH 可能变化 | 增加一行，应对=Phase 3 全量回归 + 失败即回滚单点改动 |
| 4 | Minor | 风险表 Windows 行 | 缓解措施"用 `os.name == "nt"` 判断；测试用 monkeypatch"在测试侧不可靠（见 D4-3） | 改为"平台差异参数化，测试注入平台字符串" |

### 7. ⚖️ Proportionality — ⭐⭐⭐⭐

**Summary**: 3 Phase / 8 Task / 约 70 行新代码 + 2 处注入点，对"影响所有用户命令执行环境"的跨切面改动来说比例合适——不算过度设计（没有引入开关框架/配置层），也没有明显欠开发（有单测、有回归、有风险表）。仅个别任务粒度偏细。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Minor | Task 3.1 | 其前提"检查现有断言是否因新增变量而失败"经核实大概率不成立：`test_runner_launcher.py` 只断言 `PYTHONPATH` 首项与 `PYTHONSAFEPATH == "1"`（第 213-262 行），没有 env 全等断言，新增 `_BROCA_ORIG_*` 不会破坏现有断言 | 把 Task 3.1 收敛为"新增 2 个 `_BROCA_ORIG_*` case"（去掉"修既有断言"的假设），并与 D5-1 的前移建议合并 |
| 2 | Minor | Task 2.3 | 纯 grep 确认工作，单独成 Task 略重 | 可合并进 Task 2.2 的步骤或作为 Phase 2 的收尾检查项 |

### 8. ✅ Internal Consistency — ⭐⭐

**Summary**: 垂直一致性良好（Task AC → Phase AC → 目标基本对得上）。水平一致性有两处实质冲突：一处是"干净环境"目标与"恢复服务进程 `VIRTUAL_ENV`"的语义张力，一处是与既有 venv 探测约定的不一致。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Major | 概述目标 vs 总体方案 层 2 | 目标写"确保…使用'干净'的环境，剥离 runner 内部变量"，层 2 却把 supervisor 的 `VIRTUAL_ENV`/`VIRTUAL_ENV_PROMPT` 恢复到用户命令环境里——即把服务 venv 身份注入用户 shell。计划既未说明为何需要恢复（"依赖该变量的工具异常"具体是哪些工具？），也未给出对应 AC 来界定"恢复"的边界 | 二选一并补理由：①确实需要恢复 → 在总体方案加一段"为什么恢复优于剥离"，并列出受影响工具（如 `pip`/`uv` 行为）；②不需要 → 层 2 只恢复 `PYTHONPATH`，`VIRTUAL_ENV` 保持剥离，并加 AC 断言用户命令 env 中无 `VIRTUAL_ENV` |
| 2 | Major | Task 1.1 vs `broca/agent_manager.py:477-518` | venv 探测约定不一致：计划用 `(.venv, venv, env)` + 校验 `bin/activate`/`Scripts/activate.bat`；既有代码用 `(venv, .venv, env, .env, virtualenv)` + 校验 `bin/python`/`bin/python3`/`Scripts/python.exe`。两套实现会在"workspace 只有 `virtualenv/` 或只有 `python` 无 `activate`"时给出相反结论 | 统一为单一实现（建议下沉 `agent_manager` 的版本并作为唯一来源），计划中注明"venv 候选清单与校验方式的唯一来源"，并说明优先级顺序选择的理由 |
| 3 | Minor | Task 1.3 步骤 2 | "使用 `tmp_path` + `monkeypatch.setenv` 隔离，不依赖真实文件系统"自相矛盾：`tmp_path` 就是真实文件系统 | 改为"使用 `tmp_path` 构造隔离的真实目录结构（不触碰用户 workspace），`monkeypatch.setenv` 隔离环境变量" |
| 4 | Minor | Phase 2 AC #1 vs Task 2.1 步骤 6 | Phase 2 AC 说 `_run_code_async()` 传 `env`，Task 2.1 步骤 6 说 `_run_background()` 无需修改；两处结论一致，但 Phase 2 AC 未覆盖"后台路径经 ProcessManager 间接获得 env"这一事实，读者可能以为后台路径未验证 | 在 Phase 2 AC 增加一条"后台执行路径（`background: true`）同样通过 ProcessManager 获得干净 env"，与 Task 2.1 AC #3 对齐 |

## Issue Summary

| Severity | Count | Description |
|:--------:|:-----:|-------------|
| 🔴 Critical | 0 | Must fix before execution |
| 🟡 Major | 8 | Should fix for quality |
| 🟢 Minor | 13 | Consider improving |

### 🔴 Critical Issues (Must Fix)

| # | Dimension | Location | Issue | Suggestion |
|:-:|:---------:|:--------:|-------|------------|
| — | — | — | 无 | — |

### 🟡 Major Issues (Should Fix)

| # | Dimension | Location | Issue | Suggestion |
|:-:|:---------:|:--------:|-------|------------|
| 1 | 🏗️ Feasibility | Task 3.2 / Phase 3 AC | `pytest ... --timeout=60` 依赖未安装的 `pytest-timeout`，唯一自动化门禁命令会直接报参数错误 | 去掉 `--timeout=60`，或新增任务把 `pytest-timeout` 加入 dev 依赖 |
| 2 | 🎯 AC Quality | 全局 | 无任何 AC 端到端验证"子进程实际不再收到 `PYTHONPATH=仓库根`/`PYTHONSAFEPATH`" | 新增 subprocess 级 E2E 测试任务（复用 `test_runner_launcher.py:263-320` 模式） |
| 3 | 🎯 AC Quality | Phase 3 阶段 AC | "手动验证 `python --version`"不可复现、区分度低、不覆盖核心缺陷 | 改为自动化断言 `sys.executable` 指向 workspace venv + `sys.path` 无仓库根 |
| 4 | ✅ Consistency | 概述目标 vs 层 2 | "干净环境"目标与"恢复 supervisor `VIRTUAL_ENV`"冲突，未给理由与边界 AC | 明确取舍：要么补"为何恢复"并列出受影响工具，要么保持剥离并加 AC |
| 5 | ✅ Consistency | Task 1.1 vs `agent_manager.py:477-518` | 两套 venv 探测规则（候选清单/校验方式/优先级）不一致，结论会分叉 | 统一为单一实现，计划中指定唯一来源 |
| 6 | 🔍 Clarity | 总体方案 层 1 / Task 1.1 | "内部变量"边界未闭环：其余 `BROCA_*`（`BROCA_HOME`、`BROCA_DATABASE_DIR` 等）剥还是留未定义 | 明确白名单/黑名单规则并补 AC |
| 7 | 🔍 Clarity | Task 2.3 | 引用不存在的方法 `scheduler.execute_command_job()`；误判 `git_manager` 使用 `create_subprocess_shell` | 更正为 `_execute_command` 与 `create_subprocess_exec` |
| 8 | 🔗 Structure | Task 3.1 vs Task 1.2 | 测试更新任务滞后于会破坏它的实现任务，Phase 1 门禁可能无法收尾 | 把 `test_runner_launcher.py` 的 env 断言更新前移到 Phase 1 |

### 🟢 Minor Issues (Consider)

| # | Dimension | Location | Issue | Suggestion |
|:-:|:---------:|:--------:|-------|------------|
| 1 | 📋 Completeness | Task 2.3 | `git_manager._run_git` 用 `os.environ.copy()`，污染仍会进入 git hook | 记录结论（接受/改用 `build_user_env`） |
| 2 | 📋 Completeness | Task 2.1 | bash 工具 description 与"自动 venv 适配"新行为不符 | 增加更新 description 的步骤 |
| 3 | 📋 Completeness | Task 1.2 | `_BROCA_ORIG_*` 跨进程契约无文档落点 | 写入 `launcher.py` docstring 或 `utils/env.py` 契约注释 |
| 4 | 🔍 Clarity | 全文 | supervisor / 服务进程 / runner 术语混用 | 加术语约定并统一 |
| 5 | 🔍 Clarity | Task 2.2 | `cwd` 与 `workspace` 概念混同 | 定义清楚或统一传 workspace 根 |
| 6 | 🔍 Clarity | Task 1.1 | PATH 去重、`VIRTUAL_ENV_PROMPT` 格式未规定 | 补两句规范 |
| 7 | 🎯 AC Quality | Task 2.3 AC #1 | "Scheduler 触发的命令执行使用干净环境"无验证手段 | 加 `test_process_manager.py` case |
| 8 | 🎯 AC Quality | Phase 1 AC #4 | "单元测试通过"范围模糊 | 指明具体测试文件 |
| 9 | 🏗️ Feasibility | Task 1.3 / 风险表 | `monkeypatch os.name` 无法可靠模拟 Windows 路径语义 | 平台差异参数化后注入 |
| 10 | 🏗️ Feasibility | Task 2.2 | `build_user_env(cwd)` 遇相对路径/子目录漏检 venv | 规定绝对 workspace 根或向上回溯 |
| 11 | 🔗 Structure | Task 2.3 / Task 3.2 | 验证型任务职责重叠；Task 3.2 依赖未声明 | 加出口条件与依赖标注 |
| 12 | ⚠️ Risk | 风险表 | 缺 supervisor 自身 `PYTHONPATH` 污染、PATH 服务 venv 残留、既有进程测试受影响 3 类风险 | 补 3 行风险 |
| 13 | ⚖️ Proportionality / ✅ Consistency | Task 3.1 / Task 1.3 步骤 2 | Task 3.1 前提大概率不成立；"`tmp_path` 不依赖真实文件系统"自相矛盾 | 收敛 Task 3.1；修正措辞 |

## Verdict

**Overall Score**: ⭐⭐⭐ (2.8/5)

**Verdict**: ⚠️ Conditional Pass

| Verdict | Condition |
|---------|-----------|
| ✅ **Pass** | No critical issues, all dimensions ≥ 3 stars. Plan is ready for execution. |
| ⚠️ **Conditional Pass** | Minor critical issues OR some dimensions < 3 stars. Fix recommended issues before execution. |
| ❌ **Needs Revision** | Critical issues exist OR overall < 3 stars. Plan must be revised before execution. |

**判定说明**：无 🔴 Critical 问题——技术路线正确、调用点与假设均已核实、改动面可控（2 处注入 + 1 个新模块）。但 4 个维度低于 3 星（AC Quality / Feasibility / Internal Consistency 均为 ⭐⭐），且存在 8 项 Major 问题，其中"回归门禁命令不可执行""无端到端 AC""PATH 未去污染"会直接影响执行结果的可信度，因此判定为 **Conditional Pass**：按下方 P0 清单修正后即可开工，无需重写计划。

**Recommendation**:

1. **P0（开工前必须修正，约 30–60 分钟编辑）**
   - 修正 Task 3.2 的测试命令（去掉 `--timeout=60` 或声明新增 `pytest-timeout` dev 依赖）。
   - 新增"端到端验证"任务与 AC：subprocess 级断言 `PYTHONSAFEPATH` 缺失、`sys.path` 不含仓库根、`sys.executable` 指向 workspace venv；替换 Phase 3 的手工 `python --version` 验证。
   - 就"层 2 是否恢复 `VIRTUAL_ENV`"给出明确决策与理由，并补相应 AC（当前目标与实现语义冲突）。
   - 统一 venv 探测实现：与 `broca/agent_manager.py:477-518` 对齐或下沉为公共函数，并把该文件补入"相关材料"。
2. **P1（建议同批修正）**
   - 明确"内部变量"剥离边界（4 个标记 + `_BROCA_ORIG_*` 前缀，其余 `BROCA_*` 保留），补 AC。
   - 更正 Task 2.3 中的 `scheduler.execute_command_job()` → `_execute_command`、`git_manager` 的 `create_subprocess_exec`。
   - 把 `test_runner_launcher.py` 断言更新前移到 Phase 1（或显式排除出 Phase 1 门禁）。
   - 补 3 类残留泄漏风险（supervisor `PYTHONPATH`、PATH 中服务 venv、既有进程测试行为变化）。
3. **P2（可选优化）**
   - 术语统一、PATH 去重、`VIRTUAL_ENV_PROMPT` 格式、Windows 测试参数化、Task 2.3 合并、bash 工具 description 更新。
4. **复评建议**：P0 全部落实后运行一次轻量复评（重点看 AC Quality 与 Internal Consistency 是否升到 ≥ 3 星），即可进入 `create-tasks`。P1 可在执行阶段随任务落地。

**Summary**:
这份计划的问题定位准确、三层环境重建模型清晰、调用点与关键假设（`context.workspace`、runner cwd、仅 2 处 `create_subprocess_shell`）经核实全部成立，是一份方向正确的计划。主要短板在验证层——没有任何 AC 直接证明"用户命令真的不再看到 `PYTHONPATH=仓库根`/`PYTHONSAFEPATH`"，加上回归门禁命令因缺少 `pytest-timeout` 而不可执行，使得"改完了但没证明修好"的风险偏高；此外目标与"恢复服务进程 `VIRTUAL_ENV`"存在语义张力，venv 探测又与既有 `agent_manager` 实现分叉。完成 P0 的 4 项修正后，计划即可进入执行。
