# agent.py 代码审查修复计划 — Phase 2: Structural Fixes — Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | plans/agent-py-cleanup-plan.md |
| Phase | Phase 2: Structural Fixes |
| Status | ✅ Pass |

## Plan Anchor Confirmation

- [x] Re-read the plan document section for this phase before starting
- [x] Acceptance criteria for each task confirmed
- [x] Phase 1 completion confirmed as prerequisite

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| Task 2.1: 命令拦截上移到 start() | ✅ | ① run() 无 command_manager.parse/_handle_command ② start() USER_MESSAGE 先调 _try_dispatch ③ fallback 不传 from_agent=True ④ 命令消息→handler 被调用、execute 未调用 ⑤ 普通消息→execute 被调用、dispatch 未调用 ⑥ 测试通过 | 新增 `_try_dispatch_inline_command` 方法（紧邻 run() 之前）；start() USER_MESSAGE 分支改为 `if not await self._try_dispatch_inline_command(message): await self.run(message)`；run() 删除命令拦截块并更新 docstring；_handle_command docstring 改为 "intercepted in the start() message loop"，fallback 改为 `self.run(original_message)`（无 from_agent=True）。测试 2.6 覆盖行为验证。14+3 tests passed | 无 |
| Task 2.2: _abort_task truthiness 修复 | ✅ | ① 使用 is not None ② 注释含 DISCONNECTED + status ③ 测试通过 | `self._abort_task` → `self._abort_task is not None`；添加 2 行注释解释"断连时 status 已被覆盖为 DISCONNECTED，无法区分断连前的 running/idle"。14 tests passed | 无 |
| Task 2.3: cls.__new__ 模式修复 | ✅ | ① 前置检查无子类 ② 无 cls.__new__ ③ 使用 cls(...) ④ 测试通过 | grep 确认唯一匹配 `class Agent(BaseModel, table=True)` 是 SQLModel 数据库模型（非 Agent 子类）。`cls.__new__(cls)` + `Agent.__init__(agent, ...)` → `cls(config, llm_client, session_manager, **kwargs)`。14 tests passed | 无 |
| Task 2.4: start() 兜底异常 | ✅ | ① 两级 except ② logger.exception ③ 行为测试 ④ 测试通过 | `except asyncio.TimeoutError: continue` 后添加 `except Exception as e: logger.exception(f"Unexpected error in message loop: {e}")`。行为测试由 Task 2.6 的 `test_start_survives_unexpected_exception` 覆盖。14 tests passed | 无 |
| Task 2.5: permission_manager 别名移除 | ✅ | ① 无 property 定义 ② grep 无残留 ③ components/ 无引用 ④ test_component_interfaces 通过 ⑤ test_agent_composition 通过 | 删除 `@property def permission_manager`；executor.py docstring 中 `agent.permission_manager` → `agent.permission_provider`；grep 确认 `.permission_manager` 无残留（排除模块导入）。42 tests passed | 无 |
| Task 2.6: 命令路由行为测试 | ✅ | ① 文件存在含 3 用例 ② 命令→handler ③ 普通→execute ④ 异常→logger.exception ⑤ pytest 通过 | 新建 `test_agent_command_routing.py`，复用 `test_agent_composition.py` 的 helper 函数和 `fresh_registry` fixture。3 个测试全部通过。 | 测试实现细节：(1) mock `agent.is_connected` 返回 True 跳过连接检查；(2) mock `execution_engine.execute` 为 AsyncMock 防止真实 LLM 调用；(3) `save_history=True` 避免 `run()` finally 中 `reset()` 干扰；(4) `logger.exception` patch 路径为 `broca.agent.logger.exception` |

> ✅ = All ACs met, ⚠️ = Partial (reported), ❌ = Not completed

## Deviations

无功能性偏离。Task 2.6 的实现细节（mock 策略）是测试实现层面的合理选择，不影响被测行为。

## Quality Checklist

- [x] All phase-level ACs satisfied（9/9）
- [x] All task-level ACs satisfied（6 任务 × 各自 AC）
- [x] No missing tasks (cross-referenced against plan: 6/6)
- [x] No extra functionality (only what the plan asked for)
- [x] Manually verified key behaviors (grep + code review + behavior tests)
- [x] Code follows project conventions
- [x] Compatible with existing work

## Test Results

| Test Suite | Result |
|------------|--------|
| `test_agent_composition.py` | 14 passed |
| `test_component_interfaces.py` | 28 passed |
| `test_compact_command.py` + `test_engine_dispatch.py` + `test_engine_event_flow.py` | 25 passed |
| `test_agent_command_routing.py` (new) | 3 passed |

## Modified Files

| File | Changes |
|------|---------|
| `broca/agent.py` | Task 2.1: 新增 `_try_dispatch_inline_command`，修改 `start()`/`run()`/`_handle_command`；Task 2.2: `_abort_task is not None` + 注释；Task 2.3: `cls(...)` 替代 `cls.__new__` + `Agent.__init__`；Task 2.4: `except Exception` 兜底；Task 2.5: 删除 `permission_manager` property |
| `broca/tools/executor.py` | Task 2.5: docstring 中 `agent.permission_manager` → `agent.permission_provider` |
| `broca/tests/test_agent_command_routing.py` | Task 2.6: 新建，3 个行为测试 |
