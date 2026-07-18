# Phase 1: ProcessManager 核心模块 — Test Mapping
> Plan: plans/long-running-task-optimization-plan.md

## Task 1.1: 创建 ProcessManager 类

| AC | Test Function |
|----|---------------|
| start_process("echo hello") → stdout.log 包含 "hello" | `test_ac01_stdout_contains_hello` |
| start_process("sleep 30") → get_status() 返回 RUNNING | `test_ac02_long_running_is_running` |
| 进程自然结束后 status=COMPLETED, exit_code=0 | `test_ac03_natural_completion` |
| stop_process(force=False) → SIGTERM 优雅退出 | `test_ac04_stop_graceful_sigterm` |
| stop_process(force=True) → SIGKILL 立即终止 | `test_ac05_stop_force_sigkill` |
| meta.json 随状态变化实时更新 | `test_ac06_meta_json_updates_on_start`, `test_ac06_meta_json_updates_on_completion`, `test_ac06_meta_json_updates_on_stop` |
| list_processes() 返回所有活跃进程 | `test_ac07_list_processes_returns_all` |

## Task 1.2: ProcessManager 单元测试

| AC | Test Function |
|----|---------------|
| 所有测试用例通过 | `test_ac01_all_tests_pass` |
| 覆盖正常、异常、边界场景 | `test_ac02_covers_normal_exception_boundary` |

## Phase Integration Tests

| Test File | What It Verifies |
|-----------|------------------|
| `phase-ac-tests/test_phase01_integration.py` | Phase AC 1-7: 单例模式、文件重定向、状态查询、信号发送、meta.json 更新、自动清理、三层防御 |
