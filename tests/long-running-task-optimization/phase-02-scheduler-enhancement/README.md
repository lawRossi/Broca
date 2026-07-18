# Phase 2: Scheduler 后台命令修复与增强 — Test Mapping
> Plan: plans/long-running-task-optimization-plan.md

## Task 2.1: 重写 Scheduler._execute_command() 集成 ProcessManager

| AC | Test Function |
|----|---------------|
| sleep 300 不会被 600s 超时杀死 | `test_ac01_no_hard_timeout_for_long_command`, `test_ac01_long_running_no_premature_timeout` |
| notify=True → Agent 收到通知 | `test_ac02_notify_true_sends_notification` |
| notify=False → Agent 不收通知（默认） | `test_ac03_notify_false_no_notification` |
| cancel_job_execution 能取消运行中命令 | `test_ac04_cancel_job_execution`, `test_ac04_cancel_non_existent_job` |
| 命令完成后更新 JobExecution 记录 | `test_ac05_command_updates_execution_record` |

## Task 2.2: Scheduler.add_job() 增加 notify 参数

| AC | Test Function |
|----|---------------|
| add_job(notify=True) 存入 _job_notify_map | `test_ac01_notify_true_stores_in_map`, `test_ac01_notify_true_only_for_command_type` |
| add_job(notify=False) 不存入 | `test_ac02_notify_false_not_stored`, `test_ac02_multiple_jobs_notify_mixed` |
| 不传 notify 默认 False | `test_ac03_default_notify_is_false` |

## Phase Integration Tests

| Test File | What It Verifies |
|-----------|------------------|
| `phase-ac-tests/test_phase02_integration.py` | Phase AC 1-4: Scheduler 使用 ProcessManager、notify 标志控制、add_job notify 参数、取消执行 |
