# Loop Engine 策略+Hook 重构 — Phase 4: 引擎重构（核心编排器）— Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | `.worktrees/refactor/plans/loop-engine-hooks-refactor-plan.md`（Phase 4，行 800-1186） |
| Phase | Phase 4: 引擎重构（核心编排器） |
| Status | ✅ Pass（1 项 AC 按用户指示调整，见 D1） |
| 执行日期 | 2026-11-01 |

## Plan Anchor Confirmation

- [x] 执行前重读计划 Phase 4 全文（Task 4.1a/4.1b/4.1c/4.2/4.3/4.4）、接口契约速查（行 220-311）、方法迁移映射表（行 125-183）
- [x] 逐任务确认 AC 后再动手；每个 Task 完成后逐条脚本化验证

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| **4.1a** 创建新引擎骨架 | ✅ | 9 项：策略链路 / token 上报一次 / has_write_ops 先于 on_step_start / process_tool_call_result 可独立调用 / save_turn_end 一次 / _start_turn 无 send_turn_start / 两次 execute 重置 turn 状态 / 无内联重试·semaphore·分区 / 新增 test_engine_orchestration.py | 9/9 满足。`engine.py` 新建 + `test_engine_orchestration.py`（15 例）全绿 | D1（行数） |
| **4.1b** 接入 Hook dispatch | ✅ | 8 项：6 调用点顺序 / Hook 异常不中断 / DEAD_LOOP 传播 / BrocaError `e.to_dict()` 保真 / on_step_end try-finally / STEP_START·STEP_END 入库 / engine.py 行数 / 全量 0 新增失败 | 8/8 满足。`test_engine_dispatch.py`（9 例）全绿 | D2 |
| **4.1c** 切换（Agent.create + 包入口） | ✅ | 8 项：注入 2 策略 4 Hook / compressor_ctx_builder 无参可用 / 包入口切换 / /compact 可执行 / test_compact_command 新增 / protocols docstring / 失败集合 ⊆ 迁移清单 / 私有方法名登记 | 8/8 满足。`test_compact_command.py`（4 例）全绿；包入口与 registry 解析验证通过 | D3 |
| **4.2** 兼容性与回归验证 | ✅ | 8 项：4 条 import 路径 / registry 字符串路径 / 无 legacy 残留 / 失败集合 ⊆ 清单 / 基线失败集合记录 / 构造式 fixture 可用 | 8/8 满足。基线失败集合实测 **23 例**（计划上限 22 + 1，见 D3） | D3 |
| **4.3** 旧测试迁移 | ✅ | 4 项：0 失败 / 总数 ≥751 / 37 例全有去向 / 不引用已删私有方法 | 4/4 满足。**900 passed / 3 skipped / 903 collected** | — |
| **4.4** 端到端验证 | ✅ | 7 项：全量测试 / e2e websocket / 事件流 / 限流 code / /compact / abort / 子 Agent | 7/7 满足（手动项以自动化等价覆盖，见 D5） | D4、D5 |

## Phase 级 AC 核对

| 阶段 AC | 结果 | 证据 |
|---|---|---|
| `engine.py` 总行数 ≤ 320 | ⚠️ 调整为 ≤800（实测 777） | 用户指示「可读性要考虑，不必强行要求行数」；详见 D1 |
| 引擎不 import `GitSnapshotManager` / `ContextCompressor` / `MemoryManager` | ✅ | `test_engine_has_no_inline_policy_logic`（源码断言） |
| 引擎不内联 LLM 重试逻辑、不内联工具并行/分区逻辑 | ✅ | 同上（断言无 `Semaphore` / `asyncio.sleep` / `get_permission` / `consecutive_rate_limit` / `dead_loop_window`） |
| 引擎保留 `save_turn_end` / `process_tool_call_result` / `_save_response` | ✅ | `test_save_turn_end_called_once_on_success`、`test_process_tool_call_result_callable_standalone` |
| 迁移后测试：0 失败，总数 ≥751 | ✅ | `900 passed / 3 skipped / 903 collected`（基线 754，Phase 3 末 888） |
| e2e `-k websocket` 通过 | ✅（等价） | 该过滤器在 `test_e2e_scenarios.py` 匹配 0 例（仓库无 websocket 命名用例）；全量 12 passed。见 D4 |

## 交付物

### 新增

| 文件 | 行数 | 说明 |
|---|:--:|---|
| `broca/loop_engine/engine.py` | 777 | 新 `DefaultLoopEngine`：编排 + DB 持久化 + 广播回调（1427 → 777，减 46%） |
| `broca/tests/test_engine_orchestration.py` | 404 | 15 例：策略链路 / token 上报 / 写操作门控 / save_turn_end / turn 状态重置 / 源码约束 |
| `broca/tests/test_engine_dispatch.py` | 233 | 9 例：6 调用点顺序 / Hook 异常隔离 / DEAD_LOOP 传播 / BrocaError code 保真 / step_end try-finally / step 消息入库 |
| `broca/tests/test_engine_event_flow.py` | 264 | 6 例：端到端事件流（真实默认 Hook 集 + 录制 communicator） |
| `broca/tests/test_compact_command.py` | 120 | 4 例：`/compact` 强制压缩 + CompressorContext 协议 + registry 兜底 + 失败上报 |

### 修改

| 文件 | 变更 |
|---|---|
| `broca/agent.py` | `Agent.create()` 创建 2 策略 + 4 Hook（`build_default_hooks(snapshot_manager=None, ...)`）+ `functools.partial(build_compressor_context, ...)`；暴露 `agent.context_compressor` / `agent.persistent_memory_manager`；`disconnect()` 改从 agent 取 |
| `broca/loop_engine/__init__.py` | 包入口由 `legacy` 切到 `engine` |
| `broca/commands/builtin/compact/__init__.py` | `engine.context_compressor` → `agent.context_compressor`；`engine._build_compressor_context()` → `build_compressor_context(...)` |
| `broca/commands/builtin/{clear_history,clear_context,clear_all_context}/__init__.py` | `engine.context_compressor` → `agent.context_compressor` |
| `broca/components/protocols.py` | docstring：`_build_compressor_context()` → `compressor_context.build_compressor_context()` |
| `broca/tests/test_loop_engine.py` | 37 → 17 例（20 例迁出、2 例就地改写、15 例保留），顶部注明去向 |
| `broca/tests/test_tool_strategy.py` | 新增 `test_unknown_tool_error_does_not_block_other_tools`；`FakeToolExecutor` 支持 `unknown=` |
| `broca/tests/test_llm_strategy.py` | 2 例按原断言加强（限流计数二次预算、非限流错误 sleep 次数）；`FakeConfig` 改 per-instance exec 配置（修复类属性跨用例泄漏） |
| `broca/tests/test_agent_composition.py` | 2 例改写：断言 `agent.context_compressor` / `persistent_memory_manager` + `CompressionMemoryHook` 持有 + 2 策略 4 Hook 注入顺序 |

### 引擎方法清单（777 行，按职责分区）

| 分区 | 方法 |
|---|---|
| 依赖注入 | `__init__`（保留 legacy 构造式路径）、`_do_initialize`、`initialize`、`_ensure_strategies`、`_reset_turn_scoped_state` |
| Turn setup | `_setup_turn`、`_start_turn`（无广播，M13）、`_save_user_message`、`_ensure_session` |
| 编排 | `_execute_step`、`_execute_round`、`_build_round_result`（同步）、`_dispatch` |
| 持久化 | `_save_response`、`_process_tool_results`、`process_tool_call_result`（公共名保留）、`_persist_step_start`、`_persist_step_end`、`_save_step_message`、`_finalize_turn`、`_truncate_last_assistant_message_with_tool_calls` |
| 入口/回调 | `execute`、`_get_turn_end_message`、`_make_chunk_handler`、`_make_error_handler` |
| 工具/错误/生命周期 | `_get_tools_list`、`_build_tool_context`、`_check_write_ops`、`_send_execution_error`、`_make_error_result`、`abort`、`reset` |

## Deviations

### D1 — `engine.py` 行数 AC（≤320 → ≤800）

- **现象**：保留全部职责（turn setup + 编排 + DB 写入 + 广播回调 + 错误上报）时单文件实测 **636 行**，即使极限压缩也 ≥440 行；≤320 不可达。
- **处置过程**：
  1. 先按推荐方案拆出 `persistence.py`（`PersistenceMixin`）+ `callbacks.py`（`CallbacksMixin`），把 `engine.py` 压到 320 行（Task 4.1a/4.1b 即按此实现）；
  2. 用户随后明确指示「**可读性要考虑，不必强行要求行数**」→ 判定「单消费者 mixin」是为凑指标引入的额外间接层，**已合并回单一 `engine.py`（777 行）并删除两个 mixin 文件**。
- **最终判据**：`test_engine_file_stays_small` 改为 ≤800 的回归护栏；计划 AC 的「≤320」实质放宽，理由为可读性优先（用户指示）。
- **影响**：无功能影响；1427 → 777 行仍减 46%，且职责边界由分区注释显式标出。

### D2 — STEP_START / STEP_END 的 DB 持久化（计划缺失，Phase 3 遗留风险）

- **现象**：计划 Phase 4 的 `_execute_step` 骨架未给出 `_save_step_message` 调用点，但 `broca/session/revert_service.py:245/265` 的 undo/redo 依赖这两类消息。
- **处置**：在 `_execute_step` 中 `on_step_start` dispatch **后**写 `STEP_START`、`on_step_end` dispatch **后**写 `STEP_END`（字段取 `step_ctx.step_start_snapshot` / `step_end_snapshot` / `step_patch`）。
- **语义保真**：`STEP_START` 沿用 legacy 门控（`enable_snapshot_tracking` 且 workspace 非空）；`STEP_END` 与 legacy 一致**无条件**写入。唯一差异：若 `GitSnapshotManager` 初始化失败（非 git 工作区），legacy 不写 `STEP_START`，新实现会写一条空 hash 记录 —— revert_service 对此有「无快照模式」兜底，无功能影响。
- 用例：`test_step_messages_persisted_when_snapshot_tracking_on` / `test_step_start_not_persisted_without_snapshot_tracking` / `test_step_message_failure_does_not_break_execution`。

### D3 — `engine.context_compressor` / `persistent_memory_manager` 的移除（用户批准方案 B）

- **现象**：方法迁移表要求移除这两个字段，但仓库有 **5 处计划未登记的读取点**：`compact/__init__.py:49`（直接 AttributeError）、`clear_history:73` / `clear_context:61` / `clear_all_context:68`（会话记忆静默不清除）、`agent.disconnect()`。
- **用户决策**：选择 **B —— 彻底移除字段，同步改 5 处调用点**。
- **处置**：`Agent.create()` 把 compressor / memory_manager 挂到 `agent.context_compressor` / `agent.persistent_memory_manager`；4 个命令改读 agent 属性；`disconnect()` 改从 agent 取；`test_agent_composition.py` 2 例改写为断言 `CompressionMemoryHook` 持有。
- **失败集合偏差**：切换后实测 **23 例**，计划上限 **22 例**。多出的 1 例是 `test_agent_full_lifecycle`（L403 同样断言 `engine.context_compressor`），与计划已登记的 `test_create_initialize_order` 同根因、同处置（Task 4.3 已改写），无清单外新回归。

### D4 — `pytest broca/tests/test_e2e_scenarios.py -k websocket` 无匹配用例

- 该文件 12 例均为 `TestE2EAgentCreation` / `TestE2EToolPipeline` / … 命名，**没有任何 websocket 命名的用例**（重构前即如此）。`-k websocket` 收集 0 例。
- 处置：以**全量** `pytest broca/tests/test_e2e_scenarios.py`（12 passed）作为等价判据。

### D5 — 手动验证项改为自动化等价覆盖

计划 Task 4.4 要求「手动验证并附截图/日志」。当前环境无 dev 服务 + 前端，改为新增 `broca/tests/test_engine_event_flow.py`（真实 `build_default_hooks` + 录制型 communicator + 假快照管理器），逐条对应：

| 计划手动项 | 自动化等价用例 |
|---|---|
| 事件流完整、`turn_start` 仅 1 次 | `test_event_flow_turn_start_once_and_turn_end_with_changed_files` |
| `step_end.patch` 与 `turn_end.changed_files` 非空 | `test_step_end_carries_patch_for_write_steps` + 上例 |
| 失败场景前端收到 error 事件 | `test_failed_turn_broadcasts_turn_end_and_error_notification` |
| 限流场景 `error.code == "LLM_RATE_LIMIT"` | `test_rate_limit_error_reaches_front_end_with_specific_code` |
| `/compact` 执行成功并输出统计 | `test_compact_command.py`（4 例） |
| abort 后 1s 内结束、不再重试 | `test_abort_mid_stream_stops_without_retry`（策略层）+ `test_abort_during_tools_stops_the_round` |
| 子 Agent 无前端事件、无快照 | `test_subagent_hooks_emit_no_front_end_events` + `test_hook_factory.py` |

> 未执行真实 UI 手测，需在合并前由人工补一次真机验证（本报告不声称已完成）。

### D6 — 其他实现层面记录（均为有意收紧/补齐，不影响 AC）

| # | 内容 | 理由 |
|:--:|---|---|
| 1 | token 上报只在 `success=True` 且 message 非空后上报一次 | 计划方法表 #23 已明确记录（legacy 每次 attempt 都上报） |
| 2 | `_save_response` 失败时仍 dispatch `on_step_end` | 计划要求 try/finally 保证执行（SnapshotHook 锁释放依赖）；legacy 此路径跳过 step_end |
| 3 | `_ensure_strategies()` 懒 await 策略 `initialize()` | 构造式路径 `__init__` 是同步的，无法 await；`initialize()` 路径则立即初始化 |
| 4 | `_check_write_ops` 在 `tool_executor is None` 时返回 False | legacy 会 AttributeError；测试 fixture 可能不注入 executor |
| 5 | `_dispatch` 内 Hook 异常 catch + log | 计划要求；`on_step_end` 由 try/finally 保证调用 |
| 6 | `_execute_round` 起始 abort → 返回 ABORTED 结果（legacy 抛 CancelledError 由 execute 捕获转 ABORTED） | 计划骨架如此；结果等价 |
| 7 | 修复自身引入的回归：`self.tool_mapping = tool_mapping or {}` 把空 dict 换成了新对象（`test_components_correctly_wired` 的 `is` 断言暴露）→ 改 `if ... is not None` | 保持 legacy 引用语义 |

## 迁移映射（原 `test_loop_engine.py` 37 例去向）

| 原用例 | 例数 | 去向 | 处理 |
|---|:--:|---|---|
| `TestRateLimitRetry` | 5 | `test_llm_strategy.py` | Phase 2 已有等价用例（限流/重试/计数清零/非限流错误）；其中 `test_rate_limit_counter_resets_on_success`、`test_other_llm_error_exhausts_raises` 按原断言**加强**（二次预算 / sleep 次数） |
| `TestEmptyResponseRetry` | 2 | `test_llm_strategy.py` | Phase 2 已有等价用例（软失败重试 + 放弃） |
| `TestDeadLoopDetection` 前 3 例 | 3 | `test_dead_loop_hook.py` | Phase 3 已有等价用例（3 同 / 2 同 / 3 不同） |
| `TestDeadLoopDetection::test_reset_clears_abort` / `test_reset_clears_turn_id` | 2 | `test_loop_engine.py`（保留） | 类名改为 `TestEngineReset`（测 `reset()` 语义，非死循环） |
| `TestParallelToolExecution` | 10 | `test_tool_strategy.py` | 9 例已有等价用例；**新增 1 例** `test_unknown_tool_error_does_not_block_other_tools` 补齐「未知工具报错不影响其他工具」 |
| `TestLoopEngineInit::test_init` | 1 | 就地改写 | 改断言 `_llm_strategy` / `_tool_strategy` / `_hooks` 注入 + 旧字段已不存在 |
| `TestLoopEngineInit` 其余 3 + `TestExecutionStatus` 1 + `TestExecutionResult` 4 | 8 | 保留 | 不变 |
| `TestExecute::test_execute_context_setup_failure` | 1 | 就地改写 | `_setup_execution_context` → `_setup_turn`，返回 `None` |
| `TestExecute` 其余 2 + `TestSaveUserMessage` 3 | 5 | 保留 | 不变 |
| `test_agent_composition.py::test_create_initialize_order` | 1 | 就地改写 | 断言 hook 持有 + agent 属性 + 策略/Hook 注入 |
| `test_agent_composition.py::test_agent_full_lifecycle` | 1 | 就地改写 | 同根因（D3），计划未登记 |

> 合计：20 例迁出（其中 19 例由既有等价用例承接 + 1 例新增）、2 例就地改写、15 例原样保留、composition 2 例改写。**无静默删除。**

## Quality Checklist

- [x] 所有 phase 级 AC 满足（行数项按用户指示调整，见 D1）
- [x] 所有 task 级 AC 满足（4.1a 9/9、4.1b 8/8、4.1c 8/8、4.2 8/8、4.3 4/4、4.4 7/7）
- [x] 无遗漏任务（对照计划 Phase 4 任务清单）
- [x] 无多余功能（未引入计划外能力）
- [x] 关键行为已逐条验证（脚本化 + 34 个新增用例）
- [x] 代码风格：`ruff --select F401,F841,I001,RUF100` 通过（新增/修改文件）
- [x] 与既有代码兼容：`pytest broca/tests/ -q` → **900 passed / 3 skipped / 903 collected / 0 failed**
- [x] 未做任何 git 提交（沿用本 worktree 约定）

## 已知遗留（留给 Phase 5）

1. `broca/loop_engine/legacy.py`（1427 行）仍在，且 `broca/loop_engine/__init__.py` 已不再引用它 → Phase 5 Task 5.1 删除。
2. `broca/loop_engine/__init__.py` 的 `asyncio` shim（Phase 1 为 legacy 测试 patch 目标加的）需随 legacy 一起清理。
3. `agent.py:disconnect()` 现从 agent 取 compressor / memory_manager；Phase 5 可考虑改为遍历 hooks。
4. `clear_context` / `clear_history` / `clear_all_context` 中 `from pathlib import Path` 为既有未使用 import（非本次引入），ruff 会报 F401。
5. `test_engine_file_stays_small` 的上限（800）为回归护栏，Phase 5 可按最终形态调整。
