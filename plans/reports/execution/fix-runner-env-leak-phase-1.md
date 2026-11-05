# fix-runner-env-leak — Phase 1: 环境工具层 — Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | `plans/fix-runner-env-leak-to-bash.md` |
| Phase | Phase 1: 环境工具层 |
| Status | ✅ Pass |

## Plan Anchor Confirmation

- [x] Re-read the plan document section for this phase before starting
- [x] Acceptance criteria for each task confirmed

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| Task 1.1: 创建 broca/utils/env.py | ✅ | 8 ACs | 6/8 满足，2 项偏差（见下） | ①② |
| Task 1.2: 修改 build_runner_env() | ✅ | 6 ACs | 全部满足 | 无 |
| Task 1.3: 编写 build_user_env 单元测试 | ✅ | 2 ACs | 30 tests passed | 无 |
| Task 1.4: 更新 test_runner_launcher.py | ✅ | 2 ACs | 14 tests passed（9 原有 + 5 新增） | 无 |

### Task 1.1 验收明细

| AC | 验证方式 | 结果 |
|----|---------|------|
| build_user_env() 在 runner 环境下正确还原 PYTHONPATH/VIRTUAL_ENV | `test_runner_env_restores_values` | ✅ |
| 非 runner 环境仅剥离 4 个内部变量 | `test_non_runner_env_strips_only` + `TestStripAndRestore` | ✅ |
| 保留 BROCA_HOME/BROCA_DATABASE_DIR 等 | `test_preserves_broca_config_vars` (×2) | ✅ |
| workspace 含 .venv 时 PATH 首位正确 | `test_workspace_venv_adaptation` | ✅ |
| workspace 无 venv 时不修改 PATH | `test_no_venv_no_path_change` | ✅ |
| PATH 前置前去重 | `test_path_dedup` | ✅ |
| 异常 fallback 不抛出 | `test_exception_fallback` — 仅覆盖第 3 层 venv 适配路径 | ⚠️ 偏差 ② |
| agent_manager._detect_workspace_venvs 行为不变 | 代码审查 + 手工验证（仓库中无覆盖此函数的测试） | ⚠️ 偏差 ① |

## Deviations

### 偏差 ①：`agent_manager._detect_workspace_venvs()` 未复用 `find_workspace_venv()`

计划步骤 5 要求 `_detect_workspace_venvs()` 调用 `find_workspace_venv()` 以统一 venv 检测逻辑。实际实现跨模块 import 私有符号 `_VENV_CANDIDATES` + `_validate_venv_dir`，未调用 `find_workspace_venv()`。

原因：`_detect_workspace_venvs()` 需返回**所有** venv（供系统提示），而 `find_workspace_venv()` 只返回第一个。

**后续影响**：`_validate_venv_dir(venv_path)` 未传 platform 参数（默认 `"posix"`），导致 Windows 上 `Scripts/python.exe` venv 被过滤（C1）。已在 review 修复中改为传 platform 参数 + 提升为公共 API。

### 偏差 ②：`build_user_env()` 异常兜底范围小于计划

计划步骤 4 要求"整体包裹 try/except"。实际实现仅将第 3 层（venv 适配）包在 try/except 中，`os.path.abspath(workspace)` 和 `os.environ.copy()` 未被保护。传入非法类型（如 `object()`）会抛出未捕获 `TypeError`。

已在 review 修复中扩展为整体 try/except + workspace 类型防御。

### 偏差 ③（m4 关联）：`_detect_workspace_venvs` 行为等价性无测试覆盖

Phase 1 报告原始版本以"全量 1510 tests passed"作为行为不变的证据，但仓库中不存在任何覆盖 `_detect_workspace_venvs` 函数的测试，该证据无效。正确验证方式为代码审查 + 手工验证。

## 变更文件清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `broca/utils/env.py` | **新建** (~170 行) | `find_workspace_venv` + `build_user_env` + `_strip_and_restore` + `_apply_workspace_venv` + `validate_venv_dir` + `_venv_bin_dir` + `VENV_CANDIDATES` |
| `broca/session_runner/process/launcher.py` | **修改** | `build_runner_env()` 增加 `_BROCA_ORIG_*` 保存逻辑；模块 docstring 增加契约说明 |
| `broca/agent_manager.py` | **修改** | `_detect_workspace_venvs()` 下沉复用 `VENV_CANDIDATES` + `validate_venv_dir`（review 修复后传 platform） |
| `broca/tests/test_env_utils.py` | **新建** | 30+ 个测试用例 |
| `broca/tests/test_runner_launcher.py` | **修改** | 新增 5 个 `_BROCA_ORIG_*` 测试 |

## Quality Checklist

- [x] All phase-level ACs satisfied (with noted deviations)
- [x] All task-level ACs satisfied (with noted deviations)
- [x] No missing tasks (cross-referenced against plan)
- [x] No extra functionality (only what the plan asked for)
- [x] Manually verified key behaviors
- [x] Code follows project conventions
- [x] Compatible with existing work

## Test Results

```
test_env_utils.py:         30+ passed
test_runner_launcher.py:   14 passed
full suite:                1510 passed, 0 failures
```

> 注：Phase 1 报告原始版本写 "1510 passed, 3 skipped"，Phase 3 写 "1520 passed, 5 skipped"。
> 计数差异源于测试收集范围变化（Phase 3 新增 test_env_e2e.py 5 个测试）。
> Review 修复后新增更多测试，最终计数见 Phase 3 报告。
