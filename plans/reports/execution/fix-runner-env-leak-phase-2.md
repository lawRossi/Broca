# fix-runner-env-leak — Phase 2: 注入点改造 — Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | `plans/fix-runner-env-leak-to-bash.md` |
| Phase | Phase 2: 注入点改造 |
| Status | ✅ Pass |

## Plan Anchor Confirmation

- [x] Re-read the plan document section for this phase before starting
- [x] Acceptance criteria for each task confirmed

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| Task 2.1: 修改 bash.py | ✅ | 4 ACs | 全部满足 | 无（代码变更）；⚠️ 测试覆盖缺口见下 |
| Task 2.2: 修改 process_manager.py | ✅ | 3 ACs | 全部满足 | 无（代码变更）；⚠️ 测试覆盖缺口见下 |
| Task 2.3: 确认全局调用点无遗漏 | ✅ | 3 ACs | 全部满足 | 无 |

### Task 2.1 验收明细

| AC | 验证方式 | 结果 |
|----|---------|------|
| `create_subprocess_shell` 包含 `env=env` | 代码审查：`bash.py` `env=env` | ✅ |
| `_execute()` 传递 `context.workspace` | 代码审查：`bash.py` `workspace=context.workspace` | ✅ |
| 前台/后台均传入干净 env | 前台：`_run_code_async` env=env；后台：经 ProcessManager（Task 2.2） | ✅ |
| 工具 description 更新 | 代码审查：已改为 "Prefer the workspace's virtual environment..." | ✅ |

### Task 2.2 验收明细

| AC | 验证方式 | 结果 |
|----|---------|------|
| `start_process()` 调用 `build_user_env(cwd)` | 代码审查：`process_manager.py` `env=build_user_env(cwd)` | ✅ |
| `cwd=None` 时回退到 `os.getcwd()` | `build_user_env` 内部实现（Phase 1 已验证） | ✅ |
| Scheduler command job 自动获得干净环境 | `scheduler._execute_command()` → `pm.start_process(command, process_id=job_id)` 未传 cwd → None → `os.getcwd()` = workspace | ✅ |

### Task 2.3 全局扫描结果

| 调用类型 | 位置 | 性质 | env 处理 |
|---------|------|------|---------|
| `create_subprocess_shell` | `bash.py` | **用户命令** | ✅ `env=env`（Task 2.1） |
| `create_subprocess_shell` | `process_manager.py` | **用户命令**（含 Scheduler） | ✅ `env=env`（Task 2.2） |
| `create_subprocess_exec` | `git_manager.py` | 内部 git 操作 | ✅ 接受现状（git hook 极少用 Python） |
| `create_subprocess_exec` | `grep.py` | 内部文件搜索 | ✅ 非用户命令 |
| `create_subprocess_exec` | `glob.py` | 内部文件匹配 | ✅ 非用户命令 |
| `subprocess.run/Popen` | `service_manager/cli/agent_manager` | supervisor 进程内部 | ✅ 不受影响 |

## Deviations

### ⚠️ 测试覆盖缺口（M2，已在 review 修复中补齐）

Phase 2 的两个注入点（`bash.py` 的 `env=env`、`process_manager.py` 的 `env=env`）
在 Phase 2 完成时**零断言覆盖**——若删除 `env=env`，全量测试不会失败。
AC 验证依赖代码审查而非自动化测试。

review 修复中已添加 `TestInjectionPointAssertions`（2 个测试），
通过 mock `asyncio.create_subprocess_shell` 断言 `env=` 参数被传递且内容干净。

## 变更文件清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `broca/tools/bash.py` | **修改** | +import `build_user_env`；`_run_code_async` 增加 `workspace` 参数 + `env=build_user_env(workspace)` + `env=env`；`_execute` 传 `context.workspace`；description 更新 |
| `broca/process_manager.py` | **修改** | +import `build_user_env`；`start_process` 增加 `env=build_user_env(cwd)` + `env=env` |

## Quality Checklist

- [x] All phase-level ACs satisfied
- [x] All task-level ACs satisfied
- [x] No missing tasks
- [x] No extra functionality
- [x] Code follows project conventions
- [x] Compatible with existing work

## Test Results

```
test_env_utils.py + test_runner_launcher.py:  44 passed
full suite:                                   1510 passed, 0 failures
```

> 注：Phase 2 未新增测试文件，全量计数与 Phase 1 相同。
> Review 修复后新增 E2E 注入点断言测试，最终计数见 Phase 3 报告。
