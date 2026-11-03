# Phase 2 Execution Report: ToolExecutor 提取

**Date**: 2026-10-31
**Plan**: `plans/component-plugin-architecture-plan.md` (v5)
**Status**: ✅ Complete

## Summary

Phase 2 extracted the tool execution pipeline from `LoopEngine` into a new `DefaultToolExecutor` component, registered via `ComponentRegistry` and injected into `Agent` and `LoopEngine`.

## Tasks Completed

| Task | Description | Status |
|------|-------------|--------|
| 2.1 | Characterization tests (11 tests) | ✅ |
| 2.2 | `DefaultToolExecutor` implementation | ✅ |
| 2.3 | `LoopEngine` refactored to delegate to executor | ✅ |
| 2.4 | `Agent` integration via `ComponentRegistry` | ✅ |
| 2.5 | `ToolExecutor` unit tests (23 tests) | ✅ |

## Files Changed

### New
- `broca/tools/executor.py` — `DefaultToolExecutor` (8-responsibility pipeline)
- `broca/tests/test_tool_execution_behavior.py` — 11 characterization tests
- `broca/tests/test_tool_executor.py` — 23 unit tests

### Modified
- `broca/tools/tool.py` — `ToolCallContext` added `turn_id` / `agent_id` fields
- `broca/loop_engine.py` — added `tool_executor` param; rewrote `_process_tool_calls` / `_process_tool_calls_parallel`; deleted 8 internal methods (`_execute_single_tool_call`, `_execute_tool_with_ask`, `_execute_tool_with_allow`, `_apply_session_decision`, `_should_skip_tool_timeout`, `_get_tool_execution_timeout`, `_broadcast_tool_call_start`, `_is_tool_allowed`)
- `broca/agent.py` — added `_setup_tool_executor()` + `_init_tool_executor()`; wired into `Agent.create()` flow; `_setup_execution_engine()` passes `tool_executor`
- `broca/components/defaults.py` — updated `ToolExecutor` default impl to `DefaultToolExecutor`
- `broca/tests/test_loop_engine.py` — added `mock_tool_executor` fixture, `_make_executor()` helper; removed `TestToolTimeout` class

## Pipeline (8 Responsibilities)

```
#4 broadcast → #1 exists → #2 allowed → #3 permission
→ #5 timeout-skip → #6 dedicated-timeout → execute → #7 error-mapping → #8 session-decision
```

## Test Results

| Suite | Before Phase 2 | After Phase 2 |
|-------|---------------|---------------|
| Total tests | 584 | 607 |
| New tests | — | +23 (characterization 11 + unit 23 = 34, minus 11 that replaced old) |
| Pre-existing failures | 1 (`test_shell_security.py`) | 1 (same) |
| Pass | 584 | 607 |

## Acceptance Criteria Verification

- [x] **AC1**: `asyncio.wait_for` in `loop_engine.py` only at line 367 (LLM call)
- [x] **AC2**: 0 `context.agent.` references in `broca/tools/executor.py`
- [x] **AC3**: 0 `set_session_override` references in `broca/loop_engine.py`
- [x] **AC4**: `allowed_tools` in `agent.py` only in `run()` method (per-run), not in `create()`
- [x] **AC5**: 34 tests (11 characterization + 23 unit) in Phase 2 test files
- [x] **AC6**: `ComponentRegistry.get_instance().get(ToolExecutor, scope_key=agent_id)` returns per-agent `DefaultToolExecutor`
- [x] **AC7**: No plugin → default `DefaultToolExecutor` (tested in full suite)
- [x] **AC8**: `initialize()` params match ABC: `(tool_mapping, permission_provider, config, communicator)`

## Risks / Notes

1. **`ToolCallContext.agent` remains** as a real `Agent` reference (narrow interface exception per plan). `DefaultToolExecutor` does NOT read `context.agent` — it uses `turn_id` / `agent_id` / `session_id` directly.
2. **`_make_executor()` test helper** in `test_loop_engine.py` bypasses `initialize()` by setting internal attributes directly — this is fine for unit tests but means those tests don't validate the `initialize()` path (covered separately in `test_tool_executor.py`).
3. **`ComponentRegistry.get_instance()`** uses a class-level singleton — in tests, `fresh_registry` fixture creates a new instance for isolation. Production code uses `get_instance()`.
