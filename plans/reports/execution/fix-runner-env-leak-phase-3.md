# fix-runner-env-leak — Phase 3: 回归验证 + Review 修复 — Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | `plans/fix-runner-env-leak-to-bash.md` |
| Phase | Phase 3: 回归验证 |
| Review Fix | `reports/review/fix-runner-env-leak-to-bash-all-phases-review.md` |
| Status | ✅ Pass |

## Plan Anchor Confirmation

- [x] Re-read the plan document section for this phase before starting
- [x] Acceptance criteria for each task confirmed

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| Task 3.1: E2E 子进程验证测试 | ✅ | 4 ACs | 全部满足（含 review 修复后扩展） | 2 处（见下） |
| Task 3.2: 全量测试回归 | ✅ | 2 ACs | 全部满足 | 无 |
| Review: C1 Windows venv 检测回归 | ✅ | — | `agent_manager` 传 platform 参数 | 无 |
| Review: M1 异常兜底范围 | ✅ | — | `build_user_env` 整体 try/except | 无 |
| Review: M2 注入点断言 | ✅ | — | `TestInjectionPointAssertions` 2 tests | 无 |
| Review: M3 ProcessManager E2E | ✅ | — | `TestE2EProcessManager` 真正调用 `pm.start_process()` | 无 |
| Review: M4 PATH normpath | ✅ | — | `_apply_workspace_venv` 使用 `os.path.normpath` | 无 |
| Review: M5 报告修正 | ✅ | — | Phase 1/2 报告已更正偏差记录 | 无 |
| Review: m1 死代码删除 | ✅ | — | `_venv_python_exe` 已删除 | 无 |
| Review: m2 公共 API | ✅ | — | `VENV_CANDIDATES` / `validate_venv_dir` 已提升 | 无 |
| Review: m3 缺失测试 | ✅ | — | 5 个新测试（relative/None, .env, virtualenv, windows, M1） | 无 |
| Review: m5 Known limitations | ✅ | — | `env.py` 模块 docstring 已增补 | 无 |
| Review: m6 runner-only 说明 | ✅ | — | `build_user_env` docstring 已增补 | 无 |

### Task 3.1 验收明细

| AC | 验证方式 | 结果 |
|----|---------|------|
| 场景 A：子进程 PYTHONSAFEPATH 为 ABSENT，sys.path[0] 为 '' | `test_subprocess_has_no_polluted_vars` | ✅ |
| 场景 B：子进程 VIRTUAL_ENV/VIRTUAL_ENV_PROMPT 指向 workspace venv | `test_subprocess_uses_workspace_venv` | ✅（偏差 1） |
| 场景 C：ProcessManager 路径子进程 env 干净 | `TestE2EProcessManager`（2 tests，真正调用 `pm.start_process()`） | ✅（review 修复后） |
| 场景 D：注入点 `env=` 参数断言 | `TestInjectionPointAssertions`（2 tests，mock `create_subprocess_shell`） | ✅（review 修复后） |
| 所有 E2E 测试通过 | `pytest broca/tests/test_env_e2e.py -v` → 9 passed | ✅ |

### Task 3.1 偏差说明（Phase 3 原始版本）

**偏差 1 — 场景 B 验证方式**：计划写的是验证 `sys.executable` 指向 venv。实际 `sys.executable` 会解析 symlink 链到最终目标，无法可靠反映 venv 路径。改为验证 `VIRTUAL_ENV` / `VIRTUAL_ENV_PROMPT` 环境变量。

**偏差 2 — 场景 C 实现方式**（Phase 3 原始版本）：原始测试仅验证 `build_user_env(None)` + `subprocess.run`，未调用 `pm.start_process()`。**review 修复中已补正**：通过 `monkeypatch.setattr(ProcessManager, "OUTPUT_DIR", tmp_path/...)` 解决相对路径问题，真正调用 `pm.start_process()`。

## 变更文件清单（Phase 3 + Review 修复汇总）

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `broca/utils/env.py` | **修改** | C1 前置: `validate_venv_dir` 公共 API; M1: 整体 try/except; M4: normpath; m1: 删除 `_venv_python_exe`; m5: Known limitations; m6: runner-only |
| `broca/agent_manager.py` | **修改** | C1: 传 platform 参数; m2: 使用公共 API |
| `broca/tests/test_env_utils.py` | **修改** | m3: +5 tests; M1: +1 test; M4: +1 test |
| `broca/tests/test_env_e2e.py` | **修改** | M3: `TestE2EProcessManager` 真正调用 `pm.start_process()` (2 tests); M2: `TestInjectionPointAssertions` (2 tests) |
| `plans/reports/execution/fix-runner-env-leak-phase-1.md` | **修改** | M5: 偏差记录更正 (3 处偏差) |
| `plans/reports/execution/fix-runner-env-leak-phase-2.md` | **修改** | M5: 测试覆盖缺口记录 |

## Quality Checklist

- [x] All phase-level ACs satisfied
- [x] All task-level ACs satisfied
- [x] All review issues addressed (C1, M1-M5, m1-m6)
- [x] No missing tasks
- [x] No extra functionality
- [x] Code follows project conventions
- [x] Compatible with existing work
- [x] No regressions in the full test suite

## Test Results

```
test_env_utils.py:          38 passed
test_env_e2e.py:            9 passed
test_runner_launcher.py:    14 passed
Full suite (broca/tests/):  1530 passed, 5 skipped, 0 failures in 58.50s
```

### 测试计数说明（m4 修正）

| 阶段 | 新增测试 | 全量 passed |
|------|---------|------------|
| 基线（fix 前） | — | 1475 |
| Phase 1 | +35 (env_utils 30 + launcher 5) | 1510 |
| Phase 2 | 0 | 1510 |
| Phase 3 原始 | +5 (env_e2e) | 1515 |
| Phase 3 + review fix | +15 (env_utils +7, env_e2e +4, 含 M3/M2 新测试) | **1530** |

> 5 skipped 均为既有平台条件跳过（`BROCA_RUN_INTEGRATION` ×2、self-mapped ABC ×3）。
> 1 deselected 为 `pyproject.toml` 既有 `-m 'not perf'`。
