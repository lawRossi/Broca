# Phase 4: CronTool / Agent 查询接口增强 — Test Mapping
> Plan: plans/long-running-task-optimization-plan.md

## Task 4.1: CronTool 新增进程管理操作

| AC | Test Function |
|----|---------------|
| track_process 返回 status/PID/时间/路径 | `test_ac01_track_running_process`, `test_ac01_track_completed_process` |
| list_processes 列出所有活跃进程 | `test_ac02_list_all_processes`, `test_ac02_list_empty` |
| stop_process 优雅/强制停止 | `test_ac03_stop_process_graceful`, `test_ac03_stop_process_force` |
| 不存在的 process_id 返回错误 | `test_ac04_track_nonexistent_process`, `test_ac04_stop_nonexistent_process` |
| get_job 结果中增加进程状态信息 | `test_ac05_get_job_with_process_status`, `test_ac05_get_job_no_process` |

## Task 4.2: 集成测试

| AC | Test Function |
|----|---------------|
| 所有集成测试通过 | `test_ac01_all_integration_tests_pass` |
| 模拟完整用户场景 | `test_ac02_full_user_scenario`, `test_ac02_scenario_with_http_server` |

## Phase Integration Tests

| Test File | What It Verifies |
|-----------|------------------|
| `phase-ac-tests/test_phase04_integration.py` | Phase AC 1-3: 三个新操作存在、Agent 全场景、文件路径暴露 |
