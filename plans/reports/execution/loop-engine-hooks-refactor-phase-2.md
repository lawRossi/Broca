# Loop Engine 策略+Hook 重构 — Phase 2: 策略实现 — Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | `.worktrees/refactor/plans/loop-engine-hooks-refactor-plan.md` |
| Phase | Phase 2: 策略实现 |
| Status | ✅ Pass（无偏离） |
| Executed | 2026-11-01 |
| Test Result | **818 passed / 3 skipped / 1 deselected = 821 collected，0 失败**（Phase 1 末为 754 collected，本阶段新增 67 例） |

## Plan Anchor Confirmation

- [x] 执行前重读计划 Phase 2 段（行 499–663）与「接口契约速查」
- [x] 逐任务确认 AC（Task 2.1 / 2.2 / 2.3）
- [x] 遵守并行约束：仅改动 `broca/loop_engine/strategies/`，**未修改** `engine.py`（尚不存在）/`__init__.py`/`hooks/`/`components/`

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| **2.1** RetryLLMStrategy | ✅ | ① 四条重试路径均有用例；② `should_abort` 立即返回 `aborted=True`、不 sleep 不重试（耗时 < 0.1s）；③ `on_error` 6 个提示点 + severity 正确；④ `on_chunk` 只发 3 种 type、`tool_call` 每 id 一次；⑤ 20 条 golden fixture 全绿且逐字段相等；⑥ 不 import communicator/session_manager/context/agent_ref | 新建 `broca/loop_engine/strategies/retry_llm.py`（311 行）：完整迁移限流/其他 LLMError/超时/空响应/通用异常五类分支（文案与 legacy 逐字一致）；`_stream_once()` 负责聚合与 `on_chunk` 去重；`LLMCallResult` 携带 token；`reset()` 清零限流计数。测试：`test_llm_strategy.py` 19 例 + `test_llm_strategy_golden.py` 21 例 + 20 个 fixture | 无 |
| **2.2** Parallel / Serial Tool Strategy | ✅ | ① permission 分区与现有一致；② 结果顺序与输入一致；③ abort 时剩余工具返回 `ToolResult(ERROR, "Execution aborted")` 不抛异常；④ 不调用 session_manager/communicator/context；⑤ 单测覆盖并发度/分区/顺序/异常兜底 | 新建 `parallel_tool.py`（172 行）+ `serial_tool.py`（92 行）；`serial_tool.run_serially()` 为并行策略的降级路径复用；`test_tool_strategy.py` 13 例 | 无 |
| **2.3** 策略工厂 + 配置优先级 | ✅ | ① `AgentConfig(tool_execution_mode="serial")` → Serial；② `execution_config` 生效当 agent 级为 None；③ 两者 None → Parallel；④ 优先级注释与实现一致 | 新建 `factory.py`（51 行）：`resolve_tool_execution_mode` / `create_llm_strategy` / `create_tool_strategy`，含优先级注释；`test_strategy_factory.py` 14 例（含 `max_parallel_tools` / LLM 三参数的优先级与默认值） | 无 |

> ✅ = All ACs met, ⚠️ = Partial (reported), ❌ = Not completed

## Deviations

无功能性偏离。三点实现层面的记录（均不改变契约）：

1. **`_resolve()` 增加类型校验**：计划伪代码为 `getattr(config, name, None) or ...`，实测 `MagicMock` 配置会把自动生成的属性当成有效值（`TypeError: '<' not supported between int and MagicMock`）。改为「仅接受 `int/float`（排除 bool）」，非法值回退下一优先级 —— 与 legacy `isinstance` 校验风格一致。
2. **日志改为 f-string**：legacy 使用 `logger.error("... %d ...", value)`，但项目 logger（loguru 风格）不做 `%` 插值，会原样输出 `%d`。迁移时统一改为 f-string（仅日志文本，无行为影响）。
3. **`test_llm_strategy.py` / `test_tool_strategy.py` / `test_strategy_factory.py` 提前创建**：Task 2.1/2.2/2.3 的 AC 要求「均有用例」，而计划把这些测试文件列在 Task 5.2。本阶段创建最小必要用例以满足 Phase 2 AC；Task 5.2 仍可在其基础上补齐/扩展（不冲突）。
4. **`strategies/__init__.py` 增加 re-export**：便于 Phase 4 引擎以 `from broca.loop_engine.strategies import create_*_strategy` 接入。

## Quality Checklist

- [x] All phase-level ACs satisfied
- [x] All task-level ACs satisfied
- [x] No missing tasks（Task 2.1 / 2.2 / 2.3 全部完成）
- [x] No extra functionality（未实现 Hook、未改引擎、未接入调用链）
- [x] Manually verified key behaviors（见下）
- [x] Code follows project conventions（`from __future__ import annotations`、TYPE_CHECKING、ruff `I001/F401/F841/RUF100` 全绿）
- [x] Compatible with existing work（legacy 引擎仍为主路径，`pytest broca/tests/` 0 失败）

## 验证证据

### 1. 全量测试
```
python -m pytest broca/tests/ -q
→ 818 passed, 3 skipped, 1 deselected, 20 warnings in 37.63s

python -m pytest broca/tests/ --collect-only -q
→ 821/822 tests collected (1 deselected)     # Phase 1 末为 754
```

### 2. 本阶段新增测试（67 例）
| 文件 | 用例数 | 覆盖 |
|------|:-----:|------|
| `test_llm_strategy.py` | 19 | 限流（重试/耗尽/计数清零）、其他 LLMError（重试/耗尽抛错）、超时（重试/耗尽）、空响应（重试/耗尽）、通用异常（重试/耗尽）、6 个 `on_error` 提示点顺序与 severity、abort（调用前 / 流中 / CancelledError 映射）、`on_chunk` 3 类事件 + tool_call 去重、token 上报、模块依赖白名单 |
| `test_llm_strategy_golden.py` | 21 | 20 条 golden fixture（真实 `LiteLLMClient.aggregate_message` 聚合逻辑）+ 矩阵完整性断言 |
| `test_tool_strategy.py` | 13 | 并发度上限、ask 分区串行、顺序保持、abort→"Execution aborted"、异常兜底、未知工具不分区、serial 降级、单调用串行、空批次、无 session/communicator 依赖、`allowed_tools` 透传、serial 顺序/abort |
| `test_strategy_factory.py` | 14 | 策略选择三级优先级（含 agent 级 parallel 覆盖全局 serial）、默认值、非法值回退、LLM 三参数优先级 |

### 3. Golden fixture 覆盖矩阵（20 条，全部手工构造）
| 类别 | 条数 | 说明 |
|------|:----:|------|
| content-only | 3 | 单块 / 多块拼接 / 空字符串（→ 空响应） |
| reasoning-only | 3 | 单块 / 多块 / 空字符串（→ 空响应） |
| tool_call-only | 3 | 单调用 / 两调用 / 同 id 分片（arguments 拼接，`on_chunk` 仅一次） |
| content+reasoning | 3 | 顺序两种 + 交错 |
| content+tool_call | 3 | 正文先/后 + reasoning+content+tool_call |
| 多 tool_call 交错 | 2 | 与正文交错 / 同名不同参数三调用 |
| 空流 | 2 | 无 chunk / 仅 `finish` |
| 无 id 的 tool_call（异常流） | 1 | `on_chunk` 不发事件；聚合仍记录（id 由 litellm 生成，断言用 `<any>` 通配） |

> fixture schema 严格遵循计划：`{name, chunks, expected_message, expected_on_chunk_events}`；`tool_call.data` 额外带 `index`（真实流的 delta 必然携带，聚合按 index 合并，缺 index 会误合并不同调用 —— 已在 fixture 中显式给出）。

### 4. 关键行为手工验证
| 行为 | 结果 |
|------|------|
| abort 后 `call()` 立即返回、`attempts == 0`、`sleep` 未调用、耗时 < 0.1s | ✅ |
| abort 于流中第一个 chunk 之后 → 仅 1 个事件、无重试、`aborted=True` | ✅ |
| 限流连续超阈值 → 抛 `LLMError(LLM_RATE_LIMIT)`（error code 保真，供 Phase 4 `except BrocaError` 上报） | ✅ |
| 空响应耗尽 → `success=False`, `error_code="LLM_EMPTY_RESPONSE"`，warning→error 两级通知 | ✅ |
| `ask` 权限工具在并行模式下串行执行，结果仍按输入顺序返回 | ✅ |
| 并行模式 `max_parallel_tools=2`、6 个调用 → 实测并发度 ≤ 2 | ✅ |

## 变更文件清单

| 文件 | 类型 | 行数 | 说明 |
|------|------|:----:|------|
| `broca/loop_engine/strategies/retry_llm.py` | 新增 | 311 | `RetryLLMStrategy` |
| `broca/loop_engine/strategies/parallel_tool.py` | 新增 | 172 | `ParallelToolStrategy` |
| `broca/loop_engine/strategies/serial_tool.py` | 新增 | 92 | `SerialToolStrategy` + `run_serially` / `aborted_result` |
| `broca/loop_engine/strategies/factory.py` | 新增 | 51 | `create_llm_strategy` / `create_tool_strategy` / `resolve_tool_execution_mode` |
| `broca/loop_engine/strategies/__init__.py` | 修改 | 27 | re-export |
| `broca/tests/fixtures/llm_streaming/*.json` | 新增 | 20 文件 | golden fixtures |
| `broca/tests/test_llm_strategy.py` | 新增 | 19 例 | 重试/abort/回调契约单测 |
| `broca/tests/test_llm_strategy_golden.py` | 新增 | 21 例 | golden 聚合测试 |
| `broca/tests/test_tool_strategy.py` | 新增 | 13 例 | 工具策略单测 |
| `broca/tests/test_strategy_factory.py` | 新增 | 14 例 | 工厂 + 优先级单测 |

## 对后续 Phase 的影响 / 提示

1. **Phase 3** 可并行开工：仅需 `broca/loop_engine/hooks/` 与 `compressor_context.py`，与 `strategies/` 无交叉。
2. **Phase 4（Task 4.1a）** 接入策略时注意：
   - `RetryLLMStrategy.call()` 在**限流耗尽 / 其他 LLMError 耗尽**时 **raise `LLMError`**（error code 保真），引擎必须保留 `except BrocaError` 分支用 `e.to_dict()` 上报（N4）。
   - 失败/空响应路径返回 `LLMCallResult(success=False)`，不再返回 `None`；`aborted=True` 时引擎应直接走 `ABORTED`。
   - token 上报由引擎在 `success=True` 后调用一次（M23 语义收紧）。
   - `should_abort` 由引擎传入 `lambda: self.abort_event.is_set()`。
   - `tools` 入参由引擎传 `[t.format() for t in tool_mapping.values()]`。
3. **Phase 4（Task 4.1a）** 接入工具策略时：`execute()` **只执行**，广播/DB/context 仍由引擎的 `process_tool_call_result()` 按原顺序处理。
4. **Task 5.2** 可在现有 67 例基础上扩展（尤其 golden fixture 可继续加矩阵），无需重写。
