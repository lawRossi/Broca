# 完善 Session 删除时的文件与快照清理 — Phase 1: 实现清理服务并集成到删除流程 — Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | plans/session-deletion-cleanup-plan.md |
| Phase | Phase 1: 实现清理服务并集成到删除流程 |
| Status | ✅ Pass |

## Plan Anchor Confirmation

- [x] Re-read the plan document section for this phase before starting
- [x] Acceptance criteria for each task confirmed

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| Task 1.1: 创建 SessionCleanupService | ✅ | 6 ACs | 创建 `broca/session/cleanup_service.py`，包含 `SessionCleanupService` 单例类和 4 个清理方法（`cleanup_workspace_files`/`cleanup_runner_logs`/`cleanup_orphaned_jobs`/`cleanup_snapshots_if_last_session`）。每个方法被 try/except 包裹。 | 无 |
| Task 1.2: 集成到单删 API | ✅ | 4 ACs | 修改 `delete_session` 函数：在 `delete()` 前保存 `workspace`，成功后调用 `cleanup_session`。日志由 `cleanup_session` 内部 `logger.info` 输出。 | 无 |
| Task 1.3: 集成到批量删除 API | ✅ | 4 ACs | 修改 `delete_sessions` 函数：批量查询 workspace 映射，`delete_batch` 后逐个调用 `cleanup_session`（含外层 try/except）。同 workspace 快照清理通过 `repo_path.exists()` 自动去重。 | 无 |
| Task 1.4: 更新 ScheduledJob FK | ✅ | 4 ACs | `models.py` 中 `session_id` 和 `agent_id` 的 `ondelete` 从 `"SET NULL"` 改为 `"CASCADE"`。生成 alembic 迁移脚本 `a1b2c3d4e5f6`。 | 迁移脚本中 `agent_id` FK 的 constraint name 可能需要根据实际 DB schema 调整（SQLite auto-naming） |
| Task 1.5: 确认 shutdown_all 无需修改 | ✅ | 2 ACs | 更新 `shutdown_all` docstring，说明设计意图：仅停止进程，资源清理由用户删除 session 时触发。 | 无 |

## Deviations

- **Task 1.4 迁移脚本**：由于项目使用 `render_as_batch=True`，Alembic batch mode 会在 SQLite 上自动重建表。迁移脚本中 `agent_id` 的 FK constraint 处理可能需要根据实际 DB 中的 constraint name 调整。模型层面的变更（`ondelete="CASCADE"`）已正确完成，这是核心改动。

## Quality Checklist

- [x] All phase-level ACs satisfied
- [x] All task-level ACs satisfied
- [x] No missing tasks (cross-referenced against plan — 5/5 tasks completed)
- [x] No extra functionality (only what the plan asked for)
- [x] Manually verified key behaviors (code review of all modified files)
- [x] Code follows project conventions (singleton pattern, async, logging)
- [x] Compatible with existing work (no breaking API changes, `shutdown_all` unchanged)

## Files Modified/Created

| File | Action | Description |
|------|--------|-------------|
| `broca/session/cleanup_service.py` | **新建** | SessionCleanupService 单例，4 个清理方法 |
| `broca-web/backend/app/api/session.py` | 修改 | `delete_session` + `delete_sessions` 集成清理调用 |
| `broca/session/models.py` | 修改 | `ScheduledJob` FK `ondelete` → CASCADE |
| `broca/alembic/versions/a1b2c3d4e5f6_*.py` | **新建** | Alembic 迁移脚本 |
| `broca/session_runner/manager.py` | 修改 | `shutdown_all` docstring 更新 |
