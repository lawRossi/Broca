# Loop Engine Hooks 重构 — Phase 5: 清理 + 加固 — 执行报告

## Overview

| Item | Content |
|------|---------|
| Plan File | `.worktrees/refactor/plans/loop-engine-hooks-refactor-plan.md`（Phase 5，行 1187-1266） |
| Phase | Phase 5: 清理 + 加固 |
| Status | ✅ Pass（1 项 AC 按用户既定指示调整，见 D3） |
| 评审整改 | `reports/review/loop-engine-hooks-refactor-review.md` 的整改见 **`loop-engine-hooks-refactor-phase-5-review-fixes.md`**（C1 留痕 / M1~M6 / m1~m8） |
| Tasks | 3/3 完成（Task 5.1 / 5.2 / 5.3） |
| Task-level ACs | 15/16 满足，1 项调整（`engine.py` 行数，D3） |
| Phase-level ACs | 3/3 满足 |
| Test result | **905 passed / 3 skipped / 908 collected / 0 failed**（1 deselected 为既有 perf 标记） |
| Test baseline | Phase 4 末 903 collected → 908（新增 5 例） |

## Plan Anchor Confirmation

- [x] 执行前重读 Phase 5 计划（行 1187-1266）、方法迁移映射表（行 125-183）、风险表 R9/R10/R12/R13
- [x] 逐任务确认 3 个 Task 的步骤、预期产出、验收标准
- [x] 确认无遗漏任务（计划 Phase 5 仅含 Task 5.1 / 5.2 / 5.3）

---

## Task Completion

### Task 5.1: 清理遗留代码 — ✅

| # | 验收标准（计划原文） | 实际结果 | 判定 |
|:-:|---------------------|----------|:----:|
| 1 | `broca/loop_engine/legacy.py` 不存在 | 已删除（原 1425 行） | ✅ |
| 2 | `engine.py` 总行数 ≤ 320 | 780 行 | ⚠️ D3 |
| 3 | `engine.py` 不包含 `SnapshotManager` / `ContextCompressor` / `MemoryManager` 的 import | 引擎 import 仅 12 条，无上述三者；新增源码级护栏测试 | ✅ |
| 4 | `session_manager.save_turn_end` 仍被调用（grep + 单测断言） | `engine.py:560`（`_finalize_turn`）+ 3 个单测（`test_save_turn_end_called_once_on_success` / `..._status_error_on_failure` / `..._skipped_when_setup_fails`） | ✅ |
| 5 | `process_tool_call_result` 仍在 engine 上 | `engine.py:445`；`test_image_tool.py` 全绿 | ✅ |
| 6 | 迁移后测试 0 失败，总数 ≥751 | 903 → 905 passed / 0 failed | ✅ |

**步骤 2 — 52 项方法迁移核对（脚本化证据）**

用 AST 脚本按「方法迁移映射表」逐项核对，结果 `52/52` 通过：

| 分类 | 数量 | 核对方式 |
|------|:----:|----------|
| 迁出到 `strategies/` / `hooks/` / `compressor_context.py` | 26 | 断言 `engine.py` **不再定义**同名方法 |
| 删除（职责并入 `StepContext` 构造 / 内联） | 2（`_capture_step_init` / `_generate_step_id`） | 断言 `engine.py` 无定义 |
| 改名保留在 engine | 7（`execute_step→_execute_step`、`execute_round→_execute_round`、`check_step_has_write_operations→_check_write_ops`、`process_turn_end→_finalize_turn`、`_start_new_turn→_start_turn`、`_setup_execution_context→_setup_turn`、`_save_response_and_process_tool_calls→_save_response`） | 断言旧名不存在 + 新名存在 |
| 原样保留 | 17（含 `__init__` / `_do_initialize` / `initialize` / `execute` / `abort` / `reset` / `process_tool_call_result` / `_save_step_message` / `_build_tool_context` 等） | 断言新名存在 |
| **合计** | **52** | 与计划映射表条目数一致 |

字段核对（Round2 N2）：必需 8 个字段（`agent_ref` / `llm_client` / `context` / `communicator` / `session_manager` / `config` / `tool_mapping` / **`tool_executor`**）全部存在；禁用 3 个字段（`snapshot_manager` / `context_compressor` / `persistent_memory_manager`）全部不存在 → 由新增测试 `test_engine_keeps_required_dependency_fields` 长期固化。

**步骤 4 — 精简 `initialize()` 参数消费逻辑**

| 项 | 改动前 | 改动后 |
|----|--------|--------|
| `__init__` | `**_legacy_kwargs: Any`（静默吞掉一切未知参数） | 已删除 |
| `_do_initialize` | `**kwargs: Any` + `kwargs.get("permission_provider")` | 显式 `permission_provider: Optional[Any] = None`；`context_compressor` / `memory_manager` 显式声明后 `del`（ABC 签名要求，engine 不再持有） |

**步骤 5 — 文档清理**

- `broca/loop_engine/__init__.py`：重写 docstring，补充包结构（engine / strategies / hooks / compressor_context），去掉「历史遗留」表述；asyncio shim 在 Phase 4 已不存在（本轮确认）
- `strategies/retry_llm.py` / `strategies/parallel_tool.py`：去掉指向已删模块 `broca.loop_engine.legacy` 的 docstring 引用
- `tests/test_engine_orchestration.py`：去掉「包入口仍指向 legacy engine until Task 4.1c」的过期注释
- 3 个 `clear_*` 命令：删除既有未使用 `from pathlib import Path`（ruff F401）

**新增回归护栏（3 例）**

| 测试 | 作用 |
|------|------|
| `test_legacy_engine_module_is_gone` | `importlib.util.find_spec("broca.loop_engine.legacy") is None`，防止巨石类回归 |
| `test_engine_imports_no_hook_owned_components` | 引擎 import 行不含 `SnapshotManager` / `ContextCompressor` / `MemoryManager` |
| `test_engine_keeps_required_dependency_fields` | 8 个必需字段在、3 个禁用字段不在（Round2 N2） |

---

### Task 5.2: 策略 + Hook 专项测试 — ✅

| # | 验收标准（计划原文） | 实际结果 | 判定 |
|:-:|---------------------|----------|:----:|
| 1 | 每个策略 ≥ 3 个用例（`RetryLLMStrategy` ≥ 10） | Retry 19 / Golden 21 / Parallel 11 / Serial 3 / Factory 14 | ✅ |
| 2 | 每个 Hook ≥ 3 个用例 | Snapshot 14 / Communicator 14 / Compression 13 / DeadLoop 14 / Factory 12 | ✅ |
| 3 | 使用 `unittest.mock.AsyncMock` 隔离外部依赖 | 全部外部依赖（LLMClient / ToolExecutor / SessionManager / Communicator / Compressor / MemoryManager / SnapshotManager）均为 `AsyncMock`/`MagicMock` | ✅ |
| 4 | 全部新测试通过，总数 ≥751 | 905 passed / 908 collected | ✅ |

**覆盖矩阵（计划要求点 → 现有用例）**

| 计划要求 | 覆盖用例 | 文件 |
|----------|----------|------|
| Retry：重试次数 | `test_rate_limit_exhausts_retries_raises`、`test_other_llm_error_exhausts_raises` | test_llm_strategy.py |
| Retry：限流计数 | `test_rate_limit_then_success`、`test_rate_limit_counter_resets_on_success`、`test_reset_clears_rate_limit_counter` | 同上 |
| Retry：超时 | `test_timeout_retried_then_succeeds`、`test_timeout_exhausts_returns_failure` | 同上 |
| Retry：空响应 | `test_empty_response_retried_then_succeeds`、`test_empty_response_exhausts_returns_failure` | 同上 |
| Retry：`on_chunk` 3 类 | `test_only_three_event_types_and_tool_call_dedup` + 21 条 golden fixture（content / reasoning_content / tool_call / 混合 / 空流 / 多 tool_call 交错） | test_llm_strategy.py / test_llm_strategy_golden.py |
| Retry：`on_error` 6 个提示点 | `test_all_six_notification_points` | test_llm_strategy.py |
| Retry：`should_abort` | `test_abort_before_call_returns_immediately`、`test_abort_mid_stream_stops_without_retry`、`test_cancelled_error_maps_to_aborted` | 同上 |
| Parallel：并发度上限 | `test_concurrency_bounded_by_max_parallel` | test_tool_strategy.py |
| Parallel：permission 分区 | `test_ask_permission_tools_run_serially_and_in_order`、`test_unknown_tool_is_not_partitioned_as_ask` | 同上 |
| Parallel：结果顺序 | `test_results_order_matches_input_with_varying_delays` | 同上 |
| Parallel：abort | `test_abort_marks_remaining_tools_as_error`、`test_exception_fallback_fills_missing_result` | 同上 |
| Parallel：未知工具 | `test_unknown_tool_error_does_not_block_other_tools` | 同上 |
| Serial：串行顺序 / abort | `test_executes_in_order`、`test_abort_skips_remaining_calls`、`test_allowed_tools_is_forwarded_to_executor` | 同上 |
| Snapshot：step start/end | `test_step_start_and_end_call_sequence`、`test_empty_patch_drops_patch_but_keeps_hash` | test_snapshot_hook.py |
| Snapshot：turn end | `test_turn_end_writes_changed_files`、`test_turn_end_writes_none_without_changes`、`test_abnormal_turn_end_captures_final_snapshot`、`test_turn_end_without_result_uses_ctx_data` | 同上 |
| Snapshot：lock 释放（异常路径） | `test_lock_released_when_patch_computation_raises` | 同上 |
| Snapshot：`enable_snapshot_tracking=False` no-op | `test_disabled_by_config_is_noop`、`test_missing_manager_without_workspace_is_noop`、`test_no_write_ops_skips_step_hooks` | 同上 |
| Snapshot：`reset()` | `test_reset_clears_state_between_turns`、`test_reset_releases_held_lock` | 同上 |
| Communicator：interactive / 非 interactive | `test_non_interactive_is_noop`、`test_missing_communicator_is_noop` | test_communicator_hook.py |
| Communicator：`turn_start` 仅 1 次 | `test_broadcasts_turn_start_once`、`test_broadcasts_user_message_with_files_and_raw_input` | 同上 |
| Communicator：`on_turn_finalized` 参数 | `test_broadcasts_changed_files_from_result`、`test_sends_error_notification_for_non_completed_status`、`test_turn_end_without_result_is_noop`、`test_broadcast_failures_are_swallowed` | 同上 |
| Compression：压缩触发条件 | `test_compression_called_with_context_and_compressor_context`、`test_disabled_by_config_skips_compression`、`test_missing_compressor_skips_compression`、`test_compression_failure_is_swallowed` | test_compression_hook.py |
| Compression：记忆 fire-and-forget | `test_memory_extraction_is_fire_and_forget`、`test_auto_extract_false_skips_memory`、`test_missing_memory_manager_skips_memory`、`test_missing_persistent_memory_config_skips_memory` | 同上 |
| DeadLoop：检测 / 不检测 / reset / window | `test_three_identical_calls_trigger_dead_loop`、`test_two_identical_calls_do_not_trigger`、`test_window_counts_signatures_not_steps`、`test_reset_restarts_counting`、`test_invalid_window_falls_back` | test_dead_loop_hook.py |
| Factory：4 个且顺序固定 / name 唯一 | `test_returns_four_hooks_in_fixed_order`、`test_names_are_unique` | test_hook_factory.py |
| Factory：subagent 无 snapshot/communicator | `test_never_contains_snapshot_or_communicator`、`test_compression_included_when_enabled`、`test_compression_omitted_when_disabled` | 同上 |
| Factory：全 None 参数 no-op 可创建 | `test_all_dependencies_none_still_creates_four_hooks`、`test_none_dependencies_do_not_raise` | 同上 |
| `/compact`：`check_and_compress(force=True)` + 协议 5 属性 | `test_compact_forces_compression_and_passes_compressor_context`、`test_compact_context_satisfies_compressor_context_protocol`、`test_compact_falls_back_to_registry_when_agent_has_no_compressor`、`test_compact_reports_error_when_compression_fails` | test_compact_command.py |
| `/compact`：不再引用 `_build_compressor_context` | **新增** `test_compact_no_longer_uses_the_engine_private_builder` + `test_clear_commands_do_not_use_the_engine_private_builder` | 同上 |
| Engine：6 个生命周期 dispatch 顺序 | `test_lifecycle_call_order`（断言完整序列 `turn_start → [step_start → step_end → post_step] ×2 → turn_end → turn_finalized`） | test_engine_dispatch.py |
| Engine：DEAD_LOOP 传播 | `test_dead_loop_status_propagates_to_result` | 同上 |
| Engine：`save_turn_end` 调用 | 3 例（见 Task 5.1 AC4） | test_engine_orchestration.py |
| Engine：token 上报 | `test_llm_call_completed_reported_once_per_successful_call`、`test_token_reporting_skipped_on_failed_llm_call` | 同上 |
| Engine：每 turn 状态重置 | `test_two_executions_reset_turn_scoped_state` | 同上 |

**本任务新增 2 例**（其余为核对既有覆盖，无缺口需补）：

| 测试 | 作用 |
|------|------|
| `test_compact_no_longer_uses_the_engine_private_builder` | R14 护栏：`/compact` 源码不得再出现 `_build_compressor_context`，且必须使用 `build_compressor_context` |
| `test_clear_commands_do_not_use_the_engine_private_builder` | 同上，覆盖 `clear_history` / `clear_context` / `clear_all_context` |

---

### Task 5.3: 性能验证 — ✅

| # | 验收标准（计划原文） | 实际结果 | 判定 |
|:-:|---------------------|----------|:----:|
| 1 | baseline 文件已提交（缺失则本 Task 视为未完成） | `reports/perf/loop-engine-baseline.json` | ✅ |
| 2 | LLM 调用延迟差异 < 1ms | **−0.00007 ms**（−0.07 µs） | ✅ |
| 3 | 10 个 parallel tools 的总耗时差异 < 2% | **−0.95%**（0.08264 → 0.08185 ms） | ✅ |
| 4 | Hook dispatch 单次调用开销 < 0.02ms，单 step（12 次 await）合计 < 0.25ms | 单次 `_dispatch`（4 hook await）= **0.00742 ms** → 单 hook await **0.00186 ms**；单 step = 3 × 0.00742 = **0.0223 ms** | ✅ |

**采集方式**

- 脚本：`scripts/perf/loop_engine_bench.py`（`--impl legacy|new`，`time.perf_counter`，warmup 3 次 + 实测 10 次；dispatch 基准 2000 次）
- baseline 在删除 `legacy.py` **之前**采集（见 D1）
- 输出：`reports/perf/loop-engine-baseline.json` + `reports/perf/loop-engine-after.json`

**方法映射（两个实现已无同名私有方法）**

| legacy | 重构后 |
|--------|--------|
| `engine.execute_round(max_steps=1)` | `engine._execute_round(turn_ctx, max_steps=1)` |
| `engine._call_llm_with_retry()` | `RetryLLMStrategy.call(history, tools, ...)` |
| `engine._process_tool_calls_parallel(tool_calls, ctx)` | `ParallelToolStrategy.execute(tool_calls, ctx, tool_mapping, ...)` |
| `engine._broadcast_step_message(msg)`（legacy 无 dispatch 概念） | `engine._dispatch("on_step_start", ctx)` |

**结果对比**

| benchmark | legacy (ms) | 重构后 (ms) | delta | delta% | 说明 |
|-----------|------------:|------------:|------:|-------:|------|
| `execute_round` | 0.06911 | 0.07358 | +0.00446 | +6.46% | 一轮完整 step（含 3 次 hook dispatch + STEP_END 落库）；绝对值 +4.5 µs |
| `llm_call` | 0.01337 | 0.01330 | −0.00007 | −0.53% | 3 个 chunk 的流式聚合，策略层零额外开销 |
| `parallel_tools` | 0.08264 | 0.08185 | −0.00079 | −0.95% | 10 个 mock 工具并发执行（结果处理已 stub，隔离执行逻辑） |
| `hook_dispatch` | 0.04681（非等价基线） | 0.00742 | −0.03938 | −84.14% | legacy 无 dispatch，基线取「一次 step 消息广播」，**不可直接对比** |

**结论**

1. **策略层无性能回退**：LLM 调用 −0.07 µs，并行工具 −0.95%，均在噪声范围内（3 次重复实测波动 ±0.5%）。
2. **`execute_round` +6.46%（+4.5 µs）** 来自新增的 3 次 hook dispatch（3 × 2.2 µs ≈ 6.6 µs）。相对于真实 LLM 往返（数百 ms ~ 数秒），占比 < 0.005%，可忽略。
3. **`_dispatch` 开销极低**：单 hook await 1.86 µs，单 step（12 次 await）合计 22.3 µs，远低于 AC 上限（0.25 ms），留有约 11 倍余量。
4. 所有基准均在 mock 环境下测量，绝对值为「纯编排开销」，不含网络/磁盘。

---

## Deviations

### D1 — 执行顺序：Task 5.3 步骤 0 必须先于 Task 5.1 删除动作

- **原因**：`legacy.py` 是 **untracked** 文件（Phase 1 `git mv` 未提交），删除后不可恢复；而 Task 5.3 步骤 0 要求 `from broca.loop_engine.legacy import DefaultLoopEngine` 采集 baseline。
- **处理**：实际执行顺序 `5.3-step0 → 5.1 → 5.2 → 5.3-step1~3`，baseline 已落盘后才删除 `legacy.py`。
- **影响**：无。计划本身在 Task 5.3 步骤 0 已注明「`legacy.py` 到 Task 5.1 才删除，无需回退切换」，本偏离只是把该约束显式化。

### D2 — Hook 测试文件按 Hook 拆分，而非计划要求的单文件 `test_loop_hooks.py`

- **计划**：Task 5.2 步骤 3/4 要求 `test_loop_hooks.py` + `test_loop_hooks_factory.py`。
- **实际**：Phase 3 已建成 `test_snapshot_hook.py`(14) / `test_communicator_hook.py`(14) / `test_compression_hook.py`(13) / `test_dead_loop_hook.py`(14) / `test_hook_factory.py`(12)。
- **理由**：单文件会超过 600 行；按 Hook 拆分更符合用户「可读性优先」的既定指示，且每个 Hook 可独立运行。
- **影响**：覆盖点 100% 对齐（见覆盖矩阵），无遗漏。

### D3 — `engine.py` 行数 AC（≤320）不可达，沿用 Phase 4 用户裁定

- **计划**：Task 5.1 AC「`engine.py` 总行数 ≤ 320」。
- **实测**：Phase 4 极限压缩后 636 行，拆分 mixin 可到 320 但损害可读性；**用户明确指示「可读性要考虑，不必强行要求行数」** → Phase 4 合并回单文件 777 行。
- **本阶段**：清理后 780 行（+3 行来自显式参数与 docstring）。未做进一步压缩，**该 AC 不作为判据**，改为「`legacy.py` 已删除 + `broca/loop_engine/` 无 ≥1000 行文件（最大 `engine.py` 780 行）+ 无死代码」。
- **影响**：`test_engine_file_stays_small` 上限保持 800 行，当前 780 行，余量 20 行。

### D4 — 保留 `context_compressor` / `memory_manager` 作为 `_do_initialize` 的「显式接受并忽略」参数

- **原因**：`LoopEngine.initialize()` ABC 仍把它们声明为**必填**参数（Phase 1 只追加了可选的可插拔参数，未删旧必填项），`agent.py` 必须继续传；若 `_do_initialize` 不声明就会 `TypeError`。
- **处理**：显式声明后 `del`，并加注释说明「hook-owned, accepted for ABC compat」。比原来的 `**kwargs` 静默吞参更明确，且不会误留字段。
- **影响**：engine 实例上无这两个属性（已由 `test_engine_keeps_required_dependency_fields` 固化）；ABC 签名未变（符合 R4 向后兼容要求）。

---

## Quality Checklist

- [x] 所有 Phase 级 AC 满足（legacy 删除 / 新增专项测试 / 0 失败且总数 ≥751）
- [x] 所有 Task 级 AC 满足（1 项按用户既定指示调整，见 D3）
- [x] 无遗漏任务（计划 Phase 5 仅 3 个 Task，均已创建并执行）
- [x] 无计划外功能（新增内容仅为 AC 要求的清理项与 5 个回归护栏测试）
- [x] 关键行为已手动/脚本化验证（52 项方法核对、registry 字符串路径解析、字段齐备性、benchmark）
- [x] 代码符合项目规范（ruff `F401,F841,RUF100,I001` 全绿）
- [x] 与既有工作兼容（全量 `pytest broca/tests/` 905 passed / 0 failed；`broca.loop_engine:DefaultLoopEngine` 字符串路径仍可解析 → `broca.loop_engine.engine:DefaultLoopEngine`）

## 遗留事项（不阻塞本次合并）

> 评审整改后的最新状态以 `loop-engine-hooks-refactor-phase-5-review-fixes.md` 为准；
> 测试数已由 905 增至 **920 passed / 924 collected**，`engine.py` 为 820 行 / 35 方法
> （行数口径已由 owner 撤销，见计划附录 C · C1）。

1. **真实前端手测**：Phase 4 D5 记录的「真实 Web/TUI 前端手测」仍需合并前人工补一次（自动化 `test_engine_event_flow.py` 已等价覆盖事件流，但不能替代真实 UI 渲染）。
2. `LoopEngine.initialize()` ABC 仍声明 `context_compressor` / `memory_manager` 为必填 → 后续可从 ABC 移除（需同步 `agent.py`），届时 D4 的兼容参数可一并删除。
3. `broca/loop_engine/__init__.py` 的 `LoopEngine = DefaultLoopEngine` 别名长期是否废弃（计划「未解决的问题」TODO 4）。
4. `ComponentRegistry` 的策略注册机制（计划 TODO 1）——当前 `strategies/factory.py` 硬编码默认实现。
5. `test_engine_file_stays_small` 的 800 行上限，若后续新增功能可考虑改为「方法数 / 复杂度」指标。
