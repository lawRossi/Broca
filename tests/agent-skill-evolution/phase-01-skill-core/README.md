# Phase 1: Skill Core — Test Mapping
> Plan: plans/agent-skill-evolution-plan.md

## Task 1.1: SkillStore

| AC | Test Function |
|----|---------------|
| 可读写 `.skill_store.json`，并发锁生效 | `test_ac01_store_creates_json_file`, `test_ac01_store_read_write_roundtrip`, `test_ac01_lock_file_created_and_cleaned`, `test_ac01_atomic_write` |
| `archive_skill()` 移入 `.archive/` + 状态更新 | `test_ac02_archive_agent_skill`, `test_ac02_archive_nonexistent_skill_fails`, `test_ac02_archive_already_archived_fails` |
| `restore_skill()` 从 `.archive/` 恢复 + 状态更新 | `test_ac03_restore_archived_skill`, `test_ac03_restore_nonexistent_fails`, `test_ac03_restore_conflict_fails` |
| 对 builtin Skill 执行 archive/restore 时报错 | `test_ac04_archive_builtin_fails`, `test_ac04_archive_builtin_does_not_move` |
| `record_use()` / `record_view()` 正确递增 | `test_ac05_record_use_increments`, `test_ac05_record_view_increments`, `test_ac05_record_updates_timestamp` |

## Task 1.2: /skill LocalCommand

| AC | Test Function |
|----|---------------|
| `/skill list` 列出所有 Skill | `test_ac01_list_all_skills` |
| `/skill list archived` 只显示 archived | `test_ac02_list_archived_only` |
| `/skill view my-skill` 显示内容 + 元数据 | `test_ac03_view_shows_content_and_metadata`, `test_ac03_view_nonexistent_skill`, `test_ac03_view_records_view_count` |
| `/skill archive my-skill` 归档 | `test_ac04_archive_agent_skill` |
| `/skill restore my-skill` 恢复 | `test_ac05_restore_archived_skill` |
| 对内置 Skill archive 时报错 | `test_ac06_archive_builtin_returns_error` |

## Phase Integration Tests

| Test File | What It Verifies |
|-----------|------------------|
| `phase-ac-tests/test_phase_integration.py` | Phase AC: 完整的 list→view→archive→restore 流程, archive builtin 被拒, 使用计数 |
