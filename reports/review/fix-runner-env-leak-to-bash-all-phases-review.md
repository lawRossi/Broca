# 修复 Session Runner 环境变量泄漏到 Bash 工具 — Phase 1–3 执行质量评审报告

## Overview

| Item | Content |
|------|---------|
| Plan File | `plans/fix-runner-env-leak-to-bash.md` |
| Review Scope | 全部 3 个 Phase（Phase 1 环境工具层 / Phase 2 注入点改造 / Phase 3 回归验证） |
| Execution Reports | `plans/reports/execution/fix-runner-env-leak-phase-1.md`、`-phase-2.md`、`-phase-3.md` |
| Reviewed At | 2026-11-04 |
| Test Strategy | **按用户要求未创建任何新测试**，直接复用执行期已有的 `test_env_utils.py` / `test_env_e2e.py` / `test_runner_launcher.py`，并补充 ad-hoc 脚本做交叉验证（脚本置于 `/tmp`，未入库） |
| Overall Score | ⭐⭐⭐ (3.0/5) |
| Verdict | ⚠️ Conditional Pass（1 项须修复后放行） |

### Dimension Scores

| # | Dimension | Score | Key Finding |
|:-:|-----------|:-----:|-------------|
| 1 | 📌 Plan Anchoring | ⭐⭐⭐ | 三层方案（剥离/恢复/适配）落地一致；但 3 处实现路径偏离计划步骤（`find_workspace_venv()` 未被 `agent_manager` 复用、`build_user_env()` 未整体 try/except、场景 C 换了验证载体），报告均记为"无偏差" |
| 2 | 🎯 AC Achievement Rate | ⭐⭐⭐⭐ | 42/47 完全达标（89.4%），5 项部分达标，0 项失败；其中 `agent_manager` 行为等价 AC 在 Windows 上不成立 |
| 3 | 📦 Completeness | ⭐⭐⭐⭐ | 计划要求的产出全部交付（`env.py`、`launcher.py`、`bash.py`、`process_manager.py`、3 个测试文件）；存在 1 处未被使用的死代码 |
| 4 | ✅ Correctness | ⭐⭐⭐ | 核心逻辑经真实子进程验证正确（前台/后台两条路径环境均干净）；但引入 1 个 Windows 平台回归 + 异常兜底范围小于计划要求 |
| 5 | 🧪 Test Quality | ⭐⭐⭐ | 49 个新增/更新测试全绿、AC 映射清晰；但 Phase 2 的两个注入点（`env=` 参数）**零断言**，删掉 `env=env` 不会有任何测试失败 |
| 6 | 🔗 Integration Quality | ⭐⭐⭐⭐ | 全量 `broca/tests/` 1520 passed / 5 skipped（均为既有条件跳过）、无新增 xfail；无循环导入；真实 E2E 双路径验证通过 |
| 7 | 📋 Report & Deviation Handling | ⭐⭐ | Phase 3 报告偏差记录诚实详尽；Phase 1/2 报告称"无偏差"与事实不符，且用"全量测试通过"当作"行为不变"的证据（无任何测试覆盖该函数），skip/passed 计数三阶段之间对不上 |
| | **Overall** | **⭐⭐⭐ (3.0/5)** | **功能目标已达成（可用），但含 1 个平台回归与若干报告/测试盲区** |

---

## AC Verification

### Phase 1: 环境工具层

**Phase-level ACs**

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | `broca/utils/env.py` 存在且含 `build_user_env()` / `find_workspace_venv()` | ✅ | `broca/utils/env.py:159` / `:89` |
| 2 | `build_runner_env()` 保存 `_BROCA_ORIG_PYTHONPATH`/`_BROCA_ORIG_VIRTUAL_ENV`/`_BROCA_ORIG_VIRTUAL_ENV_PROMPT` | ✅ | `launcher.py:79-93`；`test_broca_orig_*` 5 例通过 |
| 3 | `build_user_env()` 还原 PYTHONPATH，检测到 workspace venv 时 PATH 首位为 venv/bin | ✅ | `env.py:132-136`、`env.py:199-203`；`test_workspace_venv_adaptation` 通过 |
| 4 | `pytest broca/tests/test_env_utils.py -v` 全绿 | ✅ | 30 passed（实测） |
| 5 | `pytest broca/tests/test_runner_launcher.py -v` 全绿（含新增 case） | ✅ | 14 passed（实测：9 原有 + 5 新增） |

**Task 1.1: 创建 `broca/utils/env.py`**

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | runner 环境正确还原 PYTHONPATH/VIRTUAL_ENV | ✅ | `test_runner_env_restores_values`、`test_restores_virtual_env` |
| 2 | 非 runner 环境仅剥离 4 个已知内部变量 | ✅ | `test_non_runner_env_strips_only`、`test_pops_pythonpath_when_no_orig`（第 4 个即 PYTHONPATH） |
| 3 | 保留 `BROCA_HOME`/`BROCA_DATABASE_DIR` 等 | ✅ | `test_preserves_broca_config_vars`（两处） |
| 4 | workspace 含 `.venv` 时 PATH 首位为 `.venv/bin`，VIRTUAL_ENV/PROMPT 正确 | ✅ | `test_workspace_venv_adaptation`、`test_workspace_venv_name_in_prompt` |
| 5 | 无 venv 时不修改 PATH | ✅ | `test_no_venv_no_path_change` |
| 6 | PATH 前置前自动去重 | ✅ | `test_path_dedup`（精确字符串匹配；尾斜杠变体仍会重复，见 M4） |
| 7 | 异常时不抛出，fallback 并 log warning | ⚠️ | 仅"第 3 层 venv 适配"被 try/except 包裹（`env.py:182-189`）；计划步骤 4 要求"整体包裹"。实测 `build_user_env(object())` 抛出未捕获 `TypeError`（来自 `env.py:174` `os.path.abspath`） |
| 8 | `agent_manager._detect_workspace_venvs()` 行为不变（调用 `find_workspace_venv()` 后逻辑等价） | ⚠️ | 两处偏离：① 实际未调用 `find_workspace_venv()`，而是跨模块 import 私有符号（`agent_manager.py:483`）；② **行为确实变化**：`_validate_venv_dir(venv_path)` 未传 platform（默认 `"posix"`，`env.py:74`），Windows 的 `Scripts/python.exe` venv 会被过滤掉（实测 `_detect_workspace_venvs()` 对 Scripts 型 venv 返回 `[]`，重构前会返回该 venv）；③ 候选顺序由 `venv` 优先改为 `.venv` 优先，返回列表顺序变化 |
| — | **AC Rate: 6 ✅ / 2 ⚠️（8）** | | |

**Task 1.2: 修改 `build_runner_env()`**

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | 有 `PYTHONPATH` → 保存 `_BROCA_ORIG_PYTHONPATH` | ✅ | `test_broca_orig_pythonpath_saved` |
| 2 | 无 `PYTHONPATH` → 不设 | ✅ | `test_broca_orig_pythonpath_absent_when_unset` |
| 3 | 有 `VIRTUAL_ENV` → 保存 | ✅ | `test_broca_orig_virtual_env_saved` |
| 4 | 原有 `PYTHONPATH`/`PYTHONSAFEPATH`/`BROCA_RUNNER_CHILD`/`LITELLM_*` 行为不变 | ✅ | `test_pythonpath_points_to_repo_root`、`test_build_runner_env_includes_pythonsafepath`、`test_runner_env_prevents_cwd_broca_shadowing` |
| 5 | 重启无状态泄漏 | ✅ | 每次 spawn 重新调用 `build_runner_env()`（`launcher.py`），`os.environ.copy()` 无累积 |
| 6 | 模块 docstring 含 `_BROCA_ORIG_*` 契约 | ✅ | `launcher.py:9-19` |
| — | **AC Rate: 6/6** | | |

**Task 1.3: 编写 `build_user_env` 单元测试**

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | 所有场景测试通过 | ✅ | 30 passed；计划列举的 11 个场景中 8 个直接覆盖，`relative/None` 归一化、`.env`/`virtualenv` 候选、`build_user_env` 级 platform 注入 3 项未覆盖（见 m3） |
| 2 | `pytest broca/tests/test_env_utils.py -v` 全绿 | ✅ | 实测 30 passed |
| — | **AC Rate: 2/2** | | |

**Task 1.4: 更新 `test_runner_launcher.py`**

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | `pytest broca/tests/test_runner_launcher.py -v` 全绿 | ✅ | 14 passed |
| 2 | 覆盖 `_BROCA_ORIG_*` 保存（有值/无值） | ✅ | 5 个新 case（PYTHONPATH 有/无、VIRTUAL_ENV 有/无、PROMPT 有） |
| — | **AC Rate: 2/2** | | |

### Phase 2: 注入点改造

**Phase-level ACs**

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | `bash.py::_run_code_async()` 传 `env`（由 `build_user_env()` 构建） | ✅ | `bash.py:285` + `bash.py:312`；ad-hoc E2E 实测前台路径环境干净 |
| 2 | `process_manager.py::start_process()` 传 `env` | ✅ | `process_manager.py:151` + `:158`；ad-hoc E2E 实测后台路径环境干净 |
| 3 | 后台路径（Scheduler → ProcessManager）同样获得干净 env | ✅ | `scheduler._execute_command()`（`scheduler.py:487`）不传 cwd → `build_user_env(None)` → `os.getcwd()`；Scheduler 为进程内单例，仅由 `tools/cron.py:26`、`tools/bash.py:243`（均在 runner 进程）实例化，故 cwd == workspace |
| 4 | 已有测试仍通过 | ✅ | 全量 1520 passed / 5 skipped |

**Task 2.1: 修改 `broca/tools/bash.py`**

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | `create_subprocess_shell` 含 `env=env` | ✅ | `bash.py:312` |
| 2 | `_execute()` 传递 `context.workspace` | ✅ | `bash.py:108` |
| 3 | 前台/后台看到相同（干净）环境 | ✅ | ad-hoc E2E：前台 `PS=ABSENT PP=/orig/py/path VE=<ws>/.venv RC=ABSENT ORIG=[] SP0=[]`；后台 `PS=ABSENT PP=/orig/py/path VE=<ws>/.venv`。**注意：该 AC 在仓库测试中无任何断言覆盖**（见 M2） |
| 4 | 工具 description 与新行为一致 | ✅ | `bash.py:42-44` 改为 "Prefer the workspace's virtual environment (`.venv`)..." |
| — | **AC Rate: 4/4** | | |

**Task 2.2: 修改 `broca/process_manager.py`**

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | `start_process()` 调用 `build_user_env(cwd)` | ✅ | `process_manager.py:151` |
| 2 | `cwd=None` 回退 `os.getcwd()` | ✅ | `env.py:174`；`test_scheduler_path_clean_env` 覆盖 `build_user_env(None)` |
| 3 | Scheduler 命令 job 自动获得干净环境 | ✅ | `scheduler.py:487` + ad-hoc E2E 后台验证 |
| — | **AC Rate: 3/3** | | |

**Task 2.3: 确认全局调用点无遗漏**

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | Scheduler 触发命令使用干净环境 | ✅ | 同 Task 2.2#3 |
| 2 | 所有用户命令执行点均传 `env` | ✅ | `grep -rn create_subprocess_shell broca/` 仅 2 处（`bash.py:307`、`process_manager.py:154`），均带 `env`；`create_subprocess_exec` 3 处（`git_manager.py:498`、`grep.py:94`、`glob.py:97`）均为内部命令 |
| 3 | 内部工具（git snapshot）不受影响且理由已记录 | ✅ | 风险表已记录"接受现状"结论 |
| 4 | 若发现未覆盖点则新增 Task | ✅ | 未发现新遗漏点；`service_manager.py` 的 `subprocess.*` 全部运行于 supervisor，不涉及用户命令 |
| — | **AC Rate: 4/4** | | |

### Phase 3: 回归验证

**Phase-level ACs**

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | `pytest broca/tests/ -x` 全量通过（0 failures/errors，无新增 skip/xfail） | ✅ | 实测 `1520 passed, 5 skipped, 1 deselected`（1 deselected 为 `pyproject.toml` 既有 `-m 'not perf'`）；5 skipped 为既有条件跳过（`BROCA_RUN_INTEGRATION` ×2、self-mapped ABC ×3） |
| 2 | `test_runner_launcher.py` env 断言全绿 | ✅ | 14 passed |
| 3 | 端到端：含 venv 的 workspace 中子进程 `sys.executable` 指向 workspace venv、`PYTHONSAFEPATH` 不存在、`sys.path[0]` 为 `''` | ⚠️ | `PYTHONSAFEPATH` 不存在 ✅、`sys.path[0] == ''` ✅（`test_subprocess_has_no_polluted_vars`）；`sys.executable` 一项**未按字面验证**（改用 `VIRTUAL_ENV`/`VIRTUAL_ENV_PROMPT`）。实测确认该偏差有技术依据：symlink 型 venv 中 CPython 会把 `sys.executable` 解析为基解释器（`/opt/homebrew/opt/python@3.14/bin/python3.14`） |

**Task 3.1: 端到端子进程验证测试**

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | 场景 A：`PYTHONSAFEPATH` 为 None，`sys.path[0]` 为 `''` | ✅ | `test_subprocess_has_no_polluted_vars`（`PS=ABSENT`、`SP0=[]`） |
| 2 | 场景 B：子进程 `sys.executable` 指向 workspace venv | ⚠️ | `test_subprocess_uses_workspace_venv` 断言的是 `VIRTUAL_ENV`/`VIRTUAL_ENV_PROMPT`。偏差理由成立（symlink 解析，见上），但若用真实 `python -m venv` 创建 venv 则原 AC 本可实现——偏差属"可避免但成本较高" |
| 3 | 场景 C：Scheduler/ProcessManager 路径子进程 `PYTHONSAFEPATH` 为空 | ⚠️ | `test_scheduler_path_clean_env` 仅验证 `build_user_env(None)` + `subprocess.run`，**未调用 `pm.start_process()`**；`test_process_manager.py` 中虽有 13 个 `start_process` 用例被执行，但无一条断言 env 干净 |
| 4 | 所有 E2E 测试通过 | ✅ | 5 passed |
| — | **AC Rate: 2 ✅ / 2 ⚠️（4）** | | |

**Task 3.2: 全量测试回归**

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | 0 failures, 0 errors | ✅ | 实测 1520 passed, 0 failed, 0 error |
| 2 | 无新增 skip/xfail | ✅ | 5 个 skip 均为既有（集成开关 + ABC 自映射）；无 xfail |
| — | **AC Rate: 2/2** | | |

---

## Test Results

### 复用既有测试（未新建测试文件）

```
$ ./venv/bin/python -m pytest broca/tests/test_env_utils.py broca/tests/test_env_e2e.py broca/tests/test_runner_launcher.py -v
→ 49 passed, 19 warnings in 1.19s
  （test_env_utils 30 + test_env_e2e 5 + test_runner_launcher 14）

$ ./venv/bin/python -m pytest broca/tests/test_process_manager.py broca/tests/test_bash_logic.py broca/tests/test_long_running_task.py -q
→ 31 passed in 11.63s
```

### 全量回归

```
$ ./venv/bin/python -m pytest broca/tests/ -x -q -rs
SKIPPED [1] test_component_compatibility.py:88:  Self-mapped interface (ABC is its own default)
SKIPPED [1] test_component_compatibility.py:102: Self-mapped interface (ABC is its own default)
SKIPPED [1] test_component_compatibility.py:121: Self-mapped interface (ABC is its own default)
SKIPPED [1] test_ipc_socket_cleanup.py:141:    set BROCA_RUN_INTEGRATION=1 to run
SKIPPED [1] test_runner_launcher_integration.py:37: set BROCA_RUN_INTEGRATION=1 to run
→ 1520 passed, 5 skipped, 1 deselected, 199 warnings in 56.48s
```

### 交叉验证（reviewer 自建 ad-hoc 脚本，未入库）

模拟 runner 进程（`os.environ.update(build_runner_env())` + `PYTHONPATH=/repo/root` 污染 + `_BROCA_ORIG_PYTHONPATH=/orig/py/path`），workspace 含 `.venv/bin/python`，`cwd == workspace`：

```
=== FOREGROUND (bash._run_code_async) ===
PS=ABSENT              # PYTHONSAFEPATH 已剥离 ✅
PP=/orig/py/path       # 仓库根污染已还原为 supervisor 原始值 ✅
VE=<ws>/.venv          # workspace venv 适配 ✅
RC=ABSENT              # BROCA_RUNNER_CHILD 已剥离 ✅
ORIG=[]                # 无 _BROCA_ORIG_* 残留 ✅
SP0=[]                 # sys.path[0] 为 '' ✅

=== BACKGROUND (ProcessManager.start_process, cwd=None) ===
PS=ABSENT / PP=/orig/py/path / VE=<ws>/.venv   ✅ 与前台一致
```

> 结论：**修复目标（bug 本身）在真实子进程层面确实达成**，且前台/后台两条路径行为一致。这部分强于执行报告的自述（报告仅以"代码审查"作证据）。

---

## Issues Found

### 🔴 Critical（must fix）

| # | Task | Dimension | Issue | Suggestion |
|:-:|:----:|:---------:|-------|------------|
| C1 | 1.1 | Correctness / AC | **Windows 平台 venv 检测回归**：`agent_manager._detect_workspace_venvs()` 现调用 `_validate_venv_dir(venv_path)` 未传 platform（`env.py:74` 默认 `"posix"`，`agent_manager.py:492`），Windows 的 `Scripts/python.exe` venv 会被 `continue` 跳过。重构前该函数显式检查 `Scripts/python.exe`。实测：`_detect_workspace_venvs()` 对仅含 `venv/Scripts/python.exe` 的目录返回 `[]`。后果：Windows 上 agent 系统提示中的 "Workspace Python virtual environments" 恒为 `(none detected)`，直接违反 Task 1.1 AC #8「行为不变」 | 改为 `_validate_venv_dir(venv_path, "nt" if sys.platform == "win32" else "posix")`；或按计划步骤 5 直接调用 `find_workspace_venv()`（其内部已按平台分派），彻底消除双实现 |

### 🟡 Medium（should fix）

| # | Task | Dimension | Issue | Suggestion |
|:-:|:----:|:---------:|-------|------------|
| M1 | 1.1 | Correctness / AC | **异常兜底范围小于计划**：计划步骤 4 要求 `build_user_env()` "整体包裹 try/except"，实现只包裹第 3 层（`env.py:182-189`）。实测 `build_user_env(object())` 抛出未捕获 `TypeError`（`os.path.abspath`，`env.py:174`）。Task 1.1 AC #7「遇到异常时不抛出」只对 venv 适配路径成立 | 将 `ws = ...`、`os.environ.copy()` 一并纳入 try；或对 `workspace` 做类型/存在性防御后再 abspath |
| M2 | 2.1 / 2.2 | Test Quality | **两个注入点零断言**：`bash.py:312` 的 `env=env`、`process_manager.py:158` 的 `env=env` 若被删除，现有 1520 个测试全部照过。执行报告以"代码审查"作为 AC 证据，缺少回归保护（本次 reviewer 只能用 ad-hoc 脚本补证） | 至少各加 1 条断言型用例（如断言 `build_user_env` 被调用 / 子进程 stdout 中 `PYTHONSAFEPATH` 为空），把 `test_env_e2e.py::TestE2EProcessManagerPath` 升级为真正调用 `pm.start_process()` |
| M3 | 3.1 | AC / Test Quality | **场景 C 换了验证载体**：计划要求在 `test_process_manager.py` 直接驱动 `pm.start_process()`；实际只测 `build_user_env(None)`。执行报告已如实记录（偏差 2，理由：`OUTPUT_DIR` 相对路径 + 单例清理任务干扰），理由成立，但 AC「Scheduler/ProcessManager 路径子进程 PYTHONSAFEPATH 为空」仍属间接验证 | 在测试内 `monkeypatch.chdir(tmp_path)` 后调用 `pm.start_process`，或临时把 `OUTPUT_DIR` 指向 `tmp_path`，再断言 stdout |
| M4 | 1.1 | Correctness（轻） | PATH 去重为精确字符串比较（`env.py:201-203`）：`/ws/.venv/bin/`（尾斜杠）或 symlink 形式不会被识别为同一路径，会产生近似重复项 | 去重前 `os.path.normpath` 归一化（并对 symlink 场景用 `realpath` 兜底） |
| M5 | Phase 1/2 | Report Honesty | 两份执行报告均声明「**无偏差**」，但实际存在 3 处偏离计划步骤：① `agent_manager` 未复用 `find_workspace_venv()` 而 import 私有符号（`agent_manager.py:483`）；② `build_user_env` 未整体 try/except；③ 候选顺序由 `venv` 优先改为 `.venv` 优先导致返回顺序变化。同时 Phase 1 报告用「全量 1510 tests passed」作为「`_detect_workspace_venvs` 行为不变」的证据，而**仓库中不存在任何覆盖该函数的测试**，该证据无效 | 补齐偏差记录；对无测试覆盖的等价性结论，标注"代码审查 + 手工验证"而非"测试通过" |

### 🟢 Minor（reference）

| # | Task | Dimension | Issue | Suggestion |
|:-:|:----:|:---------:|-------|------------|
| m1 | 1.1 | Completeness | `_venv_python_exe()`（`env.py:57-64`）**从未被调用**，属死代码（计划未要求该函数） | 删除，或让 `_validate_venv_dir`/`agent_manager` 复用后消除重复的 python 路径探测分支 |
| m2 | 1.1 | Completeness | `agent_manager.py` 跨模块 import 私有名 `_VENV_CANDIDATES` / `_validate_venv_dir`，而计划要求的是公共 `find_workspace_venv()` | 若保留 helper 方案，至少将其提升为公共 API（`VENV_CANDIDATES` / `validate_venv_dir`） |
| m3 | 1.3 | Test Quality | 计划列举的场景中 3 项未覆盖：`find_workspace_venv` 的相对路径/`None` 归一化；`.env`/`virtualenv` 候选目录；`build_user_env` 层级的 Windows 分支（`build_user_env` 无 platform 参数，只能 mock `sys.platform`） | 补 3 条参数化用例 |
| m4 | 3.2 | Report Honesty | 计数对不上：Phase 1 报告「1510 passed, 3 skipped」，Phase 3 报告「1520 passed, 5 skipped」，但 Phase 3 只新增 5 个测试（1510+5=1515≠1520）；且 Phase 3 命令写了 `--ignore=integration`，而 `broca/tests/` 下并无 `integration` 目录（该参数为无效参数） | 统一复现命令与基线数字；移除无效参数 |
| m5 | 全 Phase | Docs | 计划风险表要求"**文档声明**"两条已知限制（supervisor 自身 `PYTHONPATH` 污染、无 venv 时 PATH 残留服务 venv `bin/`），改动文件中无任何相关说明 | 在 `broca/utils/env.py` 模块 docstring 增补"Known limitations"小节 |
| m6 | 2.2 | Design note | `build_user_env()` 在 **supervisor 进程**内调用会剥离该进程自身的 `VIRTUAL_ENV`/`PYTHONPATH`（无 `_BROCA_ORIG_*` 时一律 pop）。当前无此调用方（`start_process` 仅由 runner 内的 Scheduler 调用），但函数语义未在 docstring 说明"仅限 runner 进程使用" | docstring 增加调用约束说明 |

---

## Conclusion

**AC Achievement Rate**: **89.4%**（42/47 完全达标；5 项部分达标；0 项失败）

- Phase 1：21/23（`agent_manager` 行为等价 ⚠️、异常兜底范围 ⚠️）
- Phase 2：15/15 ✅
- Phase 3：6/9（Phase AC #3 与 Task 3.1 场景 B/C ⚠️）
- 测试结果：复用既有测试 49 passed；全量 `broca/tests/` **1520 passed, 5 skipped, 0 failed**（无新增 skip/xfail）
- 核心 bug 已被真实子进程验证修复（前台 bash / 后台 ProcessManager 双路径环境均干净）

**Overall**: ⚠️ **Conditional Pass**

**Next Step**:
1. 必修 **C1**（Windows venv 检测回归）——一行 platform 传参即可，但属明确的行为回归，且违反 Task 1.1 AC #8。
2. 建议修 **M1**（`build_user_env` 整体兜底）与 **M2**（给两个注入点补断言型测试，把 `pm.start_process()` 真正纳入 E2E）。
3. 文档侧补 **M5/m5**（已知限制），并把 Phase 1/2 报告的"无偏差"更正为真实偏差清单（**M5**）。
