# Phase 2 执行报告：回归测试 + 全量验证

**计划**: `plans/snapshot-module-fix-plan.md`
**日期**: 2026-11-04
**状态**: ✅ 完成

---

## Task 2.1: 新增回归测试

**文件**: `broca/tests/test_snapshot_fixes.py`

6 个测试类，共 15 个测试，全部通过：

| 测试类 | 测试数 | 覆盖的修复 | 结果 |
|--------|--------|-----------|------|
| `TestShellSafety` | 4 | Task 1.1: `create_subprocess_exec` 替代 shell | ✅ |
| `TestToHashNoneFix` | 2 | Task 1.3 B2: `to_hash=None` 使用 `--name-only -- .` | ✅ |
| `TestUndoLock` | 2 | Task 1.3 B3: undo/redo 全程持锁 | ✅ |
| `TestRevertAtomicity` | 3 | Task 1.3 B4: `revert_patches` 按 tree_hash 分组批量 checkout | ✅ |
| `TestGhostFileBatch` | 2 | Task 1.4: `_filter_files` 批量 ghost 检查 | ✅ |
| `TestGitManagerLifecycle` | 2 | Task 1.5: `cleanup()` / `reset()` 单例管理 | ✅ |

### 调试过程

初次运行 13/15 通过，2 个测试失败：

1. **`TestToHashNoneFix::test_calculate_patch_to_hash_none_no_false_positive`**
   - 原因：使用 empty tree hash 作为 `from_hash` + `to_hash=None`，但 `git diff`（index vs worktree）不显示未跟踪文件
   - 修复：改用 `track()` 返回的实际 snapshot hash

2. **`TestUndoLock::test_undo_holds_lock_for_entire_operation`**
   - 原因：`messages_from_pivot` 只返回 `msg_2`，缺少 pivot 消息本身，导致 `collecting` 标志未被触发
   - 修复：在 mock 返回列表中先包含 pivot 消息（`message_id="msg_pivot"`）

---

## Task 2.2: 全量回归验证

```
pytest broca/tests/ -v
1168 passed, 5 skipped, 1 deselected, 183 warnings in 59.30s
```

**零失败**。所有既有测试（包括 Phase 1 中修复的 `test_chinese_filenames.py`）和新回归测试全部通过。

---

## 总结

| 指标 | 值 |
|------|-----|
| 修复的源文件 | 11 |
| 新增测试文件 | 1 (`test_snapshot_fixes.py`) |
| 新增回归测试 | 15 |
| 全量测试通过 | 1168/1173 (5 skipped, 1 deselected) |
| 全量测试失败 | 0 |

**Phase 1 + Phase 2 全部完成。**
