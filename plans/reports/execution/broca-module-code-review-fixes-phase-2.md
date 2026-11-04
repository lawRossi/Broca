# Broca 模块 Code Review 修复 — Phase 2: 错误处理体系一致性 — Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | `plans/broca-module-code-review-fixes.md` |
| Phase | Phase 2: 错误处理体系一致性 |
| Status | ✅ Pass |

## Plan Anchor Confirmation

- [x] Re-read the plan document section for this phase before starting
- [x] Acceptance criteria for each task confirmed

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| Task 2.1: ComponentError 继承 | ✅ | (1) except BrocaError 能捕获子类 (2) import 路径不变 (3) from broca.errors import ComponentError 可用 (4) test_components_registry 通过 | (1) ✅ 13 tests (2) ✅ (3) ✅ (4) ✅ 27 tests | None |
| Task 2.2: SessionManager strict | ✅ | (1) strict=True 抛 SessionError (2) strict=False 返回 False (3) 非 engine 调用方不变 (4) test_session_* 通过 | (1) ✅ 7 tests (2) ✅ (3) ✅ default=False (4) ✅ 20 tests | None |
| Task 2.3: ToolResult error_info | ✅ | (1) BrocaError→error_info 非 None (2) 非 BrocaError→None (3) to_dict 包含 (4) test_tool_* 通过 | (1) ✅ 8 tests (2) ✅ (3) ✅ (4) ✅ 106 tests | None |
| Task 2.4: pre_execute_check 幂等 | ✅ | (1) 并行模式只调用一次 (2) 串行模式只调用一次 (3) pre_check_msg 正确传递 (4) test_tool_strategy 通过 | (1) ✅ 3 tests (2) ✅ (3) ✅ (4) ✅ 51 tests | None |

## Phase AC Verification

- [x] `ComponentError` 及其子类可被 `except BrocaError` 捕获
- [x] Engine `_setup_turn` 关键路径的持久化失败能正确传播异常而非静默降级
- [x] `ToolResult` 保留 `BrocaError` 的结构化错误信息
- [x] `pre_execute_check` 的双重调用问题已修复（契约声明 + 缓存机制）
- [x] 新增回归测试通过

## Changes Made

### Task 2.1
- **`broca/errors/types.py`**: Added 3 ErrorCode entries (COMPONENT_ERROR, COMPONENT_NOT_FOUND, COMPONENT_SCOPE_ERROR)
- **`broca/errors/exceptions.py`**: Added `ComponentError(BrocaError)` base class
- **`broca/components/errors.py`**: Changed `ComponentNotFoundError`/`ComponentScopeError` to inherit from `broca.errors.exceptions.ComponentError`; re-exported base for backward compat
- **`broca/errors/__init__.py`**: Exported `ComponentError`
- **`broca/tests/test_component_errors.py`**: New file, 13 tests

### Task 2.2
- **`broca/session/session_manager.py`**: Added `strict: bool = False` to `save_message()` and `start_turn()`; strict path raises `SessionError` with cause
- **`broca/loop_engine/engine.py`**: `_start_turn` and `_save_user_message` now pass `strict=True`
- **`broca/tests/test_session_manager_strict.py`**: New file, 7 tests

### Task 2.3
- **`broca/tools/tool.py`**: Added `error_info` field to `ToolResult`; `execute()` sets `error_info=e.info` on `BrocaError`; `to_dict()` includes `error_info`
- **`broca/tests/test_tool_result_error_info.py`**: New file, 8 tests

### Task 2.4
- **`broca/tools/tool.py`**: Added `pre_check_cache: Optional[dict]` to `ToolCallContext`; added contract docstring to `pre_execute_check`
- **`broca/loop_engine/strategies/parallel_tool.py`**: Partitioning phase now caches `pre_execute_check` results in `context.pre_check_cache`
- **`broca/tools/executor.py`**: `execute_tool()` checks `context.pre_check_cache` before calling `pre_execute_check`
- **`broca/tests/test_pre_execute_check_single_call.py`**: New file, 3 tests

## Deviations

None. Implementation strictly follows the plan.

## Quality Checklist

- [x] All phase-level ACs satisfied
- [x] All task-level ACs satisfied
- [x] No missing tasks (cross-referenced against plan)
- [x] No extra functionality (only what the plan asked for)
- [x] Manually verified key behaviors
- [x] Code follows project conventions
- [x] Compatible with existing work

## Test Summary

| Test File | Tests | Result |
|-----------|:-----:|:------:|
| `test_component_errors.py` | 13 | ✅ All pass |
| `test_session_manager_strict.py` | 7 | ✅ All pass |
| `test_tool_result_error_info.py` | 8 | ✅ All pass |
| `test_pre_execute_check_single_call.py` | 3 | ✅ All pass |
| Full suite (`broca/tests/`) | 1273 passed, 5 skipped | ✅ No new failures |
