# Loop Engine 策略 + Hook 重构 — Phase 3: Hook 实现 — 执行报告

## Overview

| Item | Content |
|------|---------|
| Plan File | `.worktrees/refactor/plans/loop-engine-hooks-refactor-plan.md`（Phase 3，行 664-799） |
| Phase | Phase 3: Hook 实现 |
| Status | ✅ Pass（1 项偏离已说明：D1） |
| 执行日期 | 2026-11-01 |
| 测试结果 | `pytest broca/tests/ -q` → **885 passed / 3 skipped / 888 collected / 0 failed**（新增 67 例） |

## Plan Anchor Confirmation

- [x] 执行前重读计划 Phase 3 全文（行 664-799）、接口契约速查（行 220-311）、方法迁移映射表（行 125-183）、关键设计决策（行 103-124）
- [x] 逐个任务确认 AC（Task 3.1~3.5 共 27 条任务级 AC + 3 条阶段级 AC）
- [x] 重读 legacy 迁移源：`_initialize_snapshot_tracking`(L208)、`_acquire/_release_step_lock`(L246-258)、`_capture_step_start_snapshot`(L259)、`_compute_step_end_patch`(L271)、`_capture_step_start/_end`(L304/L326)、`_detect_dead_loop`(L471)、`_trigger_post_step_hooks`(L510)、`_build_compressor_context`(L684)、`_extract_tool_call_signatures`(L879)、`_normalize_arguments`(L902)、`_compute_turn_level_diff`(L1155)、`_clear_turn_snapshots`(L1201)、`_send_turn_error_notification`(L1235)、`_broadcast_user_message`(L1321)

## 产出文件

| 文件 | 行数 | 说明 |
|------|:----:|------|
| `broca/loop_engine/hooks/snapshot_hook.py` | 232 | `SnapshotHook`（name=`snapshot`）：step/turn 快照 + patch + turn-level diff + 锁管理 |
| `broca/loop_engine/hooks/communicator_hook.py` | 164 | `CommunicatorHook`（name=`communicator`）：turn_start / step_start / step_end / turn_finalized 广播 |
| `broca/loop_engine/hooks/compression_hook.py` | 111 | `CompressionMemoryHook`（name=`compression`）：post-step 压缩 + fire-and-forget 记忆提取 |
| `broca/loop_engine/hooks/dead_loop_hook.py` | 85 | `DeadLoopHook`（name=`dead_loop`）：step-end 死循环检测 + 签名归一化 |
| `broca/loop_engine/hooks/factory.py` | 94 | `build_default_hooks` / `build_subagent_hooks` + `dead_loop_window` 解析 |
| `broca/loop_engine/hooks/__init__.py` | 24 | re-export 4 个 Hook + 2 个构建器（Phase 1 空骨架 → 完整导出） |
| `broca/loop_engine/compressor_context.py` | 80 | `build_compressor_context()` 独立工厂函数（原 engine 私有方法迁移） |
| `broca/tests/test_snapshot_hook.py` | — | 14 例 |
| `broca/tests/test_communicator_hook.py` | — | 14 例 |
| `broca/tests/test_compression_hook.py` | — | 13 例 |
| `broca/tests/test_dead_loop_hook.py` | — | 14 例 |
| `broca/tests/test_hook_factory.py` | — | 12 例 |

**未改动**：`broca/loop_engine/legacy.py`、`broca/loop_engine/__init__.py`、`broca/loop_engine/strategies/*`、`broca/components/*`、`broca/agent.py`、`broca/commands/**`（均属 Phase 2/4 归属，本阶段零改动）。

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| Task 3.1: SnapshotHook | ✅ | 7 条 | 见下方逐条 | D1（AC2 解释） |
| Task 3.2: CommunicatorHook | ✅ | 5 条 | 见下方逐条 | — |
| Task 3.3: CompressionMemoryHook | ✅ | 6 条 | 见下方逐条 | — |
| Task 3.4: DeadLoopHook | ✅ | 4 条 | 见下方逐条 | — |
| Task 3.5: Hook 构建器 | ✅ | 4 条 | 见下方逐条 | — |

### Task 3.1 — SnapshotHook（7/7）

| AC | 证据 |
|----|------|
| `enable_snapshot_tracking=False` → 所有方法 no-op | `TestGating::test_disabled_by_config_is_noop`：`track/acquire_lock/release_lock/calculate_patch/calculate_diff` 调用计数全 0，`changed_files is None` |
| `snapshot_manager=None` → no-op 且不抛异常 | `TestGating::test_missing_manager_without_workspace_is_noop` + `test_lazy_init_failure_does_not_raise`（monkeypatch `GitSnapshotManager.__init__` 抛异常）→ 不抛、`_snapshot_manager is None`。**见 D1** |
| `has_write_ops=False` → step 钩子直接 return | `TestGating::test_no_write_ops_skips_step_hooks`：`track` 0 次、`acquire_lock` 0 次 |
| 锁在 on_step_start 获取、on_step_end 释放（异常也释放） | `TestStepSnapshots::test_lock_released_when_patch_computation_raises`（`calculate_patch` 抛错 → `release_lock` 调用 1 次、`_lock_held is False`）；实现为 `on_step_end` 的 `try/finally` |
| `on_turn_end` 写 `ctx.result.data["changed_files"]`（无变更 None） | `TestTurnDiff::test_turn_end_writes_changed_files` / `test_turn_end_writes_none_without_changes` |
| `reset()` 后两次 turn 互不影响 | `TestReset::test_reset_clears_state_between_turns`（第二次 turn 的 `first_hash` = `hash-2`，非上一 turn 残留）；`test_reset_releases_held_lock` |
| 单测 mock SnapshotManager 验证调用序列/lock/no-op 开关 | 14 例全绿（调用序列、异常补偿快照 `test_abnormal_turn_end_captures_final_snapshot`） |

### Task 3.2 — CommunicatorHook（5/5）

| AC | 证据 |
|----|------|
| `interactive=False` → 全 no-op | `TestGating::test_non_interactive_is_noop`（4 个 send_* 调用计数 0）；`test_missing_communicator_is_noop` |
| 一次 turn 只广播 1 次 `turn_start` | `TestTurnStart::test_broadcasts_turn_start_once`（`send_turn_start.await_count == 1`）。引擎侧移除 `_start_turn` 广播属 Task 4.1a |
| `on_turn_finalized` 的 `changed_files` 取自 `ctx.result.data` | `TestTurnFinalized::test_broadcasts_changed_files_from_result` |
| `on_step_end` 广播含 `ctx.step_patch` | `TestStepBroadcasts::test_step_end_carries_patch`（`message.data["patch"] == patch`） |
| 单测 mock Communicator 验证参数与次数 | 14 例全绿；另 `test_on_turn_end_not_overridden` 固化「广播只在 on_turn_finalized」 |

### Task 3.3 — CompressionMemoryHook（6/6）

| AC | 证据 |
|----|------|
| `check_and_compress(context=..., compressor_context=builder())` | `TestCompressionGating::test_compression_called_with_context_and_compressor_context`（`assert_awaited_once_with`） |
| 记忆提取 fire-and-forget（create_task + done_callback 吞异常） | `TestMemoryGating::test_memory_extraction_is_fire_and_forget`；实现用 `asyncio.create_task` + `add_done_callback(lambda t: t.exception() if not t.cancelled() else None)` |
| `enable_context_compression=False` 或 compressor=None → 跳过压缩 | `test_disabled_by_config_skips_compression` / `test_missing_compressor_skips_compression` |
| `auto_extract=False` 或 memory_manager=None → 跳过记忆 | `test_auto_extract_false_skips_memory` / `test_missing_memory_manager_skips_memory` / `test_missing_persistent_memory_config_skips_memory` |
| `build_compressor_context()` 具备 5 个协议属性 | `TestCompressorContextFactory::test_exposes_protocol_attributes`（last_context_length / compact_config / provider / model / workspace）+ `test_provider_and_model_are_lazy` |
| 单测 mock compressor + memory_manager | 13 例全绿 |

### Task 3.4 — DeadLoopHook（4/4）

| AC | 证据 |
|----|------|
| 语义：扁平化签名列表最后 `window` 个元素全部相同 | `TestDetection::test_window_counts_signatures_not_steps`：window=3、每 step 2 个相同调用 → 第 2 步即 `DEAD_LOOP` |
| 3 次相同 → DEAD_LOOP；2 次 → 不触发；reset() 后重新计数 | `test_three_identical_calls_trigger_dead_loop` / `test_two_identical_calls_do_not_trigger` / `TestReset::test_reset_restarts_counting` |
| 归一化与 `_normalize_arguments` 一致（JSON sort_keys） | `TestNormalization` 5 例（键序归一、空值、非法 JSON 回退 strip、list 保序、签名格式） |
| 单测覆盖上述 4 条 | 14 例全绿；另 `test_no_tool_calls_never_triggers` |

### Task 3.5 — Hook 构建器（4/4）

| AC | 证据 |
|----|------|
| `build_default_hooks` 返回 4 个 Hook，顺序严格 `[snapshot, communicator, dead_loop, compression]` | `TestDefaultHooks::test_returns_four_hooks_in_fixed_order` |
| `build_subagent_hooks` 返回 1~2 个，且不含 Snapshot/Communicator | `TestSubagentHooks::test_compression_included_when_enabled`（2 个）/ `test_compression_omitted_when_disabled`（1 个）/ `test_never_contains_snapshot_or_communicator` |
| 所有参数为 None 时仍创建 4 个 Hook 且不抛异常 | `TestDefaultHooks::test_all_dependencies_none_still_creates_four_hooks` |
| 单测断言 name 唯一 | `test_names_are_unique` == `{"snapshot","communicator","dead_loop","compression"}` |

## 阶段级 AC

| Phase AC | 结果 |
|----------|------|
| 4 个 Hook 类实现完成，每个都有唯一 `name` 类属性 | ✅ 脚本验证：`names = [snapshot, communicator, dead_loop, compression]`，`len(set)==4`；4 个类均 `issubclass(LoopHook)`、`__abstractmethods__ == frozenset()`、`name` 为类属性、可无参实例化 |
| 每个 Hook 可独立单测 | ✅ 5 个独立测试文件，67 例；无 Hook 需要 engine/DB/网络即可测试（依赖全部为 mock） |
| 迁移后测试：0 失败，总数 ≥751 | ✅ **885 passed / 3 skipped / 888 collected / 0 failed**（Phase 2 末 821 collected → +67） |

## Deviations

### D1（需知悉）：Task 3.1 AC2 与计划正文冲突，按「lazy 初始化」实现

- **冲突**：Task 3.1 步骤 2 写「`snapshot_manager` 为 `None` 时在 `on_turn_start` 内 lazy 初始化（与原 `_initialize_snapshot_tracking` 一致）」，但 AC2 写「`snapshot_manager=None` 时同样 no-op，且不抛异常」。二者不能同时成立。
- **判定依据**：Phase 4 Task 4.1c 的 `Agent.create()` 明确传 `snapshot_manager=None`，并注明「SnapshotHook 内部 lazy 初始化（受 `enable_snapshot_tracking` 控制）」。若按 AC2 字面实现（None 即永久禁用），切换后 undo/redo 快照功能会整体失效 —— 属功能回归。
- **实际实现**：`_enabled = config.enable_snapshot_tracking and manager is not None`；`on_turn_start` 在 `manager is None` 且 `enable_snapshot_tracking=True` 且 `workspace` 非空时 lazy 创建 `GitSnapshotManager`；创建失败则 catch + log 并永久降级为 no-op。
- **AC2 的满足方式**：no-op 语义落在「无法 lazy 初始化」场景（无 workspace / 初始化抛异常），由 `test_missing_manager_without_workspace_is_noop` 与 `test_lazy_init_failure_does_not_raise` 覆盖。
- **影响面**：仅 `SnapshotHook` 内部；对 Phase 4 无额外要求（正是其所需语义）。

### 实现层面记录（非偏离，供后续阶段知悉）

1. **压缩异常改为 Hook 内吞掉**：legacy `_trigger_post_step_hooks` 未捕获异常，压缩失败会冒泡到 `execute()` 的兜底 `except Exception` → turn 变 ERROR。新实现按计划「Hook 异常 catch + log，不中断」在 Hook 内 catch + `logger.warning`。属**有意收紧**（压缩失败不再破坏 turn）。
2. **错误通知文案来源**：`CommunicatorHook._send_turn_error_notification` 的 `message` 取 `ctx.data["turn_end_message"]`（engine `_finalize_turn` 写入，见 Task 4.1a 步骤 6），回退 `"Turn failed"`。legacy 由 `_get_turn_end_message(result)` 生成 —— **Phase 4 必须保证写入该 key**，否则文案退化为回退值。
3. **`send_turn_start` / `send_turn_end` 不在 `Communicator` ABC 上**：仅 `SocketIOClient`（及其子类 `SocketIOCommunicator`）提供。Hook 沿用 legacy 的鸭子类型调用 + `try/except` 包裹。是否补进 ABC 属 Phase 5 可选项，本阶段不动接口。
4. **`_build_compressor_context` 适配器字段**：计划要求「保留 5 个属性」，实现保留 5 个协议属性（`last_context_length` / `compact_config` / `provider` / `model` / `workspace`）**外加** `agent_id` / `session_id` / `communicator` / `session_manager` —— 因为 `ContextCompressor` 实际使用 `communicator` 与 `session_manager`（`context_compressor.py:370/405/503/575/622`），少传会 AttributeError。
5. **`DeadLoopHook` 窗口参数校验**：非正整数 / bool / 非 int → 回退 `3`（`DEFAULT_DEAD_LOOP_WINDOW`），工厂层同样校验，避免 `window=0` 造成 `last_n[1:]` 空列表误判。
6. **`_capture_step_start` / `_capture_step_end` 的拆分**：迁移时只取「快照捕获」部分；DB 写入（`_save_step_message`）留 engine、广播进 `CommunicatorHook`。

## ⚠️ 遗留风险（Phase 4 必须处理）

**STEP_START / STEP_END 消息的 DB 持久化没有明确归属**。

- legacy：`_capture_step_start()` / `_capture_step_end()` 内 `_save_step_message(step_start_msg / step_end_msg)` 写库 + 广播。
- 新架构：快照 → `SnapshotHook`，广播 → `CommunicatorHook`（已实现），**DB 写入仍应在 engine**（映射表 #8 `_save_step_message` 归属 engine；Hook 无 `session_manager`）。
- 但 Phase 4 计划（Task 4.1a 步骤 4/8、4.1b 步骤 4）的 `_execute_step` 骨架**没有给出 `_save_step_message` 的调用点**。
- 影响：`broca/session/revert_service.py:245/265` 依赖 `MessageType.STEP_START` / `STEP_END` 消息做 undo/redo；若不写库，快照撤销将无法定位 step 边界。
- 建议（Phase 4 执行时落实）：在 `_execute_step` 中 `on_step_start` dispatch 之后、`on_step_end` dispatch 之后各调用一次 `_save_step_message(...)`（消息构造与 legacy 一致，字段取自 `step_ctx.step_start_snapshot` / `step_ctx.step_end_snapshot` / `step_ctx.step_patch`），或由 `_save_response` 一并在同一处写入。

## Quality Checklist

- [x] 阶段级 AC 全部满足（4 个 Hook + 唯一 name / 可独立单测 / 0 失败且总数 ≥751）
- [x] 任务级 AC 全部满足（27/27，D1 已说明）
- [x] 无遗漏任务（对照计划 Task 3.1~3.5，逐一建任务并执行）
- [x] 无额外功能（未新增计划外 Hook、未改接口、未动 Phase 2/4 归属文件）
- [x] 关键行为已手工验证（脚本化校验：类属性/抽象方法/工厂顺序/依赖注入/依赖白名单 AST 检查）
- [x] 代码符合项目约定（`from __future__ import annotations`、loguru f-string、`get_logger(__name__)`；`ruff --select F401,F841,I001,RUF100` 全通过）
- [x] 与既有代码兼容（`broca/tests/` 全量 885 passed；legacy 引擎仍为主路径，`broca.loop_engine.__init__` 未改）
- [x] 未做任何 git 提交（工作区改动保持未提交状态）

## 验证命令记录

```bash
# 阶段测试（新增 67 例）
python -m pytest broca/tests/test_snapshot_hook.py broca/tests/test_communicator_hook.py \
  broca/tests/test_compression_hook.py broca/tests/test_dead_loop_hook.py \
  broca/tests/test_hook_factory.py -q
# → 67 passed

# 全量回归
python -m pytest broca/tests/ -q
# → 885 passed, 3 skipped, 1 deselected, 888 collected, 0 failed
#   注：`RuntimeWarning: coroutine 'Event.wait' was never awaited` 为既有问题
#   （test_permission_manager.py / test_tool_permission_manager.py 触发），与本次改动无关

# 静态检查
python -m ruff check broca/loop_engine/hooks/ broca/loop_engine/compressor_context.py \
  broca/tests/test_*hook*.py --select F401,F841,I001,RUF100
# → All checks passed
```
