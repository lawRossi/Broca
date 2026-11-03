# Loop Engine 策略 + Hook 重构 — 评审整改报告

> 来源评审：`reports/review/loop-engine-hooks-refactor-review.md`（全阶段 Phase 1~5，Conditional Pass 4.1/5）
> 整改范围：C1（按用户指示跳过代码拆分，仅做书面留痕）+ M1~M6 + m1~m8
> 整改日期：2026-11-01

## Overview

| Item | Content |
|------|---------|
| 评审结论 | ⚠️ Conditional Pass（4.1/5）：1 Critical / 6 Major / 8 Minor |
| 用户裁定 | **C1 行数无关**（不拆代码）；其余按「A. 修正优先」方案处理 |
| 代码整改 | 7 项（M1 / M3 / m1 / m2 / m3 / m5 / m7） |
| 文档整改 | 3 项（C1 书面留痕 / M5 清单补登 / m6 命名对齐 / M4 顺序登记） |
| 流程整改 | 1 项（M2：`git add` 重构相关路径，形成可回退基线） |
| 未整改 | 1 项（M6：真实前端手测，无法自动化，仍需合并前人工补） |
| 测试结果 | **920 passed / 3 skipped / 924 collected / 0 failed**（整改前 905 → +15 例） |
| 全量基线 | 754（重构前）→ 924 collected |

---

## 逐项处置

### 🔴 C1 — `engine.py` 行数 AC（≤320）未达成

**用户裁定**：行数无关，不拆代码。

**整改**：不做代码拆分；改为**书面留痕 + 判据替换**（评审指出真正的问题是「计划未修订、无留痕」）。

| 动作 | 位置 |
|------|------|
| 在计划概述处标注该口径已由 owner 撤销，列出受影响的 7 处引用 | `plans/loop-engine-hooks-refactor-plan.md:14-15` |
| 新增**附录 C · C1**，记录撤销理由、替代判据（4 条结构护栏）、受影响位置清单 | 同上，行 1379+ |
| **删除**人为设定的行数断言 `assert len(source.splitlines()) <= 800`（评审指出它本身就是「降低验收标准」的痕迹） | `test_engine_orchestration.py` |
| 替换为 `test_engine_is_an_orchestrator_not_a_monolith`：断言引擎方法数 ≤ 40（legacy 为 52） | 同上 |

**替代判据（现状全部满足）**

| # | 判据 | 现状 |
|:-:|------|------|
| 1 | `legacy.py` 已删除，`broca/loop_engine/` 无 ≥1000 行文件 | ✅ 最大 `engine.py` 820 行 |
| 2 | 引擎 import 不含 `SnapshotManager` / `ContextCompressor` / `MemoryManager` | ✅ `test_engine_imports_no_hook_owned_components` |
| 3 | 引擎无内联策略逻辑（`Semaphore` / `asyncio.sleep` / `get_permission` / `dead_loop_window`） | ✅ `test_engine_has_no_inline_policy_logic` |
| 4 | 引擎方法数 ≤ 40 | ✅ 35 个方法（legacy 52） |

规模趋势（非 AC）：`engine.py` 820 行 / 35 方法；`strategies/` 627 行；`hooks/` 686 行 —— 策略 + Hook 层已超过引擎本身。

---

### 🟡 M1 — `build_subagent_hooks()` 生产零调用

**问题**：子 Agent（记忆提取 / Skill 进化 / 持久记忆）经 `Agent.create()` 仍拿到 `build_default_hooks`，即仍会建 Git 快照 + 向前端广播。

**整改**：新增角色路由，在唯一的接线点按 `config.role` 选择 Hook 集。

```python
# broca/loop_engine/hooks/factory.py
SUBAGENT_ROLES = frozenset(
    {"session_memory_manager", "skill_evolution", "persistent_memory_manager"}
)

def is_subagent_config(config) -> bool: ...
def build_hooks_for(config, *, ...) -> list[LoopHook]:
    """子 Agent → build_subagent_hooks；主 Agent → build_default_hooks。"""
```

```python
# broca/agent.py — Agent.create() 第 5 步
from broca.loop_engine.hooks.factory import build_hooks_for
hooks = build_hooks_for(config, snapshot_manager=None, communicator=agent.communicator, ...)
```

角色取值来源（全仓 3 处，均已覆盖）：`context_compressor.py:581`（`session_memory_manager`）、`skill/skill_evolution.py:51`（`skill_evolution`）、`persistent_memory/manager.py:273`（`persistent_memory_manager`）。

**新增测试（8 例）**

| 测试 | 断言 |
|------|------|
| `test_subagent_roles_get_the_reduced_set` | 3 个角色均无 `snapshot` / `communicator`，但保留 `dead_loop` |
| `test_main_agent_gets_the_full_set` | `role=None` → 4 个 Hook 固定顺序 |
| `test_unknown_role_gets_the_full_set` | `role="coding"` → 全量 |
| `test_is_subagent_config` | 3 个角色 True，其余 False |
| `test_missing_role_attribute_is_not_a_subagent` | 无 `role` 属性的 config → 全量（不误伤） |
| `test_subagent_set_still_gets_compression_when_enabled` | 子 Agent 在 `enable_context_compression=True` 时保留压缩 Hook |
| `test_main_agent_gets_the_full_hook_set`（integration） | `Agent.create(role="coding")` → `["snapshot","communicator","dead_loop","compression"]` |
| `test_subagent_gets_the_reduced_hook_set`（integration） | `Agent.create(role="session_memory_manager")` → 无 snapshot/communicator |

**影响面**：子 Agent 不再在用户工作区创建 Git 快照、不再向前端广播 step/turn 事件。风险提示：子 Agent 的 `write_file`（记忆落盘）不再进入 undo/redo 快照链 —— 与「子 Agent 是后台内部行为」的设计意图一致，但属**行为变更**，已在此登记。

---

### 🟡 M2 — 重构未纳入版本控制

**整改**：`git add` 本次重构相关路径，形成可回退基线（**不 commit**）。

| 路径 | 说明 |
|------|------|
| `broca/loop_engine/` | 新包（engine / strategies / hooks / compressor_context） |
| `broca/loop_engine.py`（删除） | Phase 1 包化后删除 |
| `broca/components/` | LoopHook / LLMStrategy / ToolExecutionStrategy / LoopEngine ABC 等接口 |
| `broca/agent.py` | 策略 + Hook 注入、`build_hooks_for` 接线 |
| `broca/commands/builtin/{compact,clear_history,clear_context,clear_all_context}/` | 压缩上下文调用点 |
| `broca/tests/*` | 14 个重构专项测试文件 + fixtures |
| `scripts/perf/` / `reports/perf/` | 基准脚本与 JSON |
| `plans/loop-engine-hooks-refactor-plan.md` / `plans/reports/execution/loop-engine-hooks-refactor-phase-*.md` | 计划与 5 份报告 |

未纳入：其他 plan（component-plugin-architecture / config-unification）的改动，保持原状不干扰。

---

### 🟡 M3 — abort 占位工具结果被落库 + 广播

**问题**：legacy 串行模式 abort 后 `return`，剩余工具既不执行也不入库；新实现为剩余每个工具生成 `ToolResult(ERROR, "Execution aborted")` 并全部落库/广播 → 多出 N 条 `save_tool_call` 与 N 个前端事件。

**整改**：引擎跳过「从未执行」的占位结果。

```python
# broca/components/tool_strategy.py — 共享契约常量
ABORTED_TOOL_RESULT_CONTENT = "Execution aborted"

# broca/loop_engine/engine.py
def _is_abort_placeholder(self, result) -> bool:
    return (
        self.abort_event.is_set()
        and result.status == ToolStatus.ERROR
        and result.content == ABORTED_TOOL_RESULT_CONTENT
    )
```

`_process_tool_results()` 对占位结果 `continue`（不写 DB、不广播、不进 context）。

**为什么安全**：ABORTED 路径在 `_finalize_turn` 会调用 `_truncate_last_assistant_message_with_tool_calls()` 删除整条带 `tool_calls` 的 assistant 消息，因此不会留下「有 tool_call 无 tool 消息」的悬空结构（OpenAI 协议要求成对）。

**新增测试（2 例）**

| 测试 | 断言 |
|------|------|
| `test_abort_placeholders_are_not_persisted` | abort 中 → 只持久化真正执行过的结果（1/2） |
| `test_aborted_content_is_persisted_when_no_abort_is_in_flight` | 无 abort 在飞时，内容恰好是 "Execution aborted" 的真实结果仍持久化（避免误杀） |

---

### 🟡 M4 — STEP_START「先广播后入库」

**处置**：**登记为有意变更，不改代码**（用户方案 A）。

**原因**：`step_start_snapshot` 由 `SnapshotHook.on_step_start` 写入 `StepContext`，引擎必须在 `_dispatch("on_step_start")` **之后**才能拿到 hash 去持久化；若改成「先存后播」，入库的 `snapshot_hash` 恒为空字符串。要严格对齐 legacy 只能让引擎感知具体 Hook 类型（先调 SnapshotHook 再存再播），破坏「Hook 顺序固定、引擎不感知实现」的架构。

**风险评估**：差额为微秒级；广播事件本身已携带 `snapshot_hash`，前端不依赖 DB 行存在性 → 可接受。

**留痕**：`plans/loop-engine-hooks-refactor-plan.md` 附录 C · M4。

---

### 🟡 M5 — Task 4.2 失败集合 23 vs 计划上限 22

**处置**：计划侧补登（非执行超限）。

`plans/loop-engine-hooks-refactor-plan.md` 附录 C · M5 已记录：Task 4.2 的基线失败集合应为 **23 例**（22 + `test_agent_composition.py::test_agent_full_lifecycle`，同根因 `engine.context_compressor` 移除、同处置）。性质与附录 B 的 N8 相同，属计划清单漏项。

---

### 🟡 M6 — 真实前端手测缺失

**处置**：无法自动化，保留为**合并前人工 checklist**（本次未做）。

合并前需人工补：

1. Web 前端：一轮正常对话 → 观察 `turn_start` / `step_start` / `step_end` / `turn_end` 事件渲染与 `changed_files` 展示；
2. TUI：同上（事件消费路径不同）；
3. 执行中点击中止 → 确认 1s 内停止、前端不再出现后续工具事件；
4. 执行 `/compact` 与 `/clear_context` → 确认压缩生效且无 `AttributeError`。

> 自动化等价覆盖已存在：`test_engine_event_flow.py`（真实默认 Hook 集 + 录制 communicator，6 例）、`test_compact_command.py`（6 例）。但这些不能替代真实 UI 渲染与浏览器兼容性验证。

---

### 🟢 Minor

| # | 问题 | 处置 | 测试 |
|:-:|------|------|------|
| **m1** | `_process_tool_results` 的 `zip()` 静默截断 | 结果数 < 调用数时**补位**并 `logger.error`（补位结果 = `ERROR "Tool execution failed (missing result)"`） | `test_missing_tool_results_are_padded_not_truncated` |
| **m2** | `initialize()` 重复调用静默忽略新策略/Hook | 幂等短路保留，但改为 `logger.warning` 并列出被忽略的参数 | `test_reinitialize_is_ignored_and_does_not_swap_strategies` |
| **m3** | `CommunicatorHook.on_step_start` 无条件广播（legacy 无快照跟踪时不播） | 新增 `_tracks_snapshots` 门控（`enable_snapshot_tracking` **且** `workspace` 非空），`on_step_end` 保持无条件（对齐 legacy） | `test_step_start_skipped_when_snapshot_tracking_disabled` / `test_step_start_skipped_without_workspace` / `test_step_end_still_broadcast_without_snapshot_tracking` |
| **m4** | `_persist_step_end` 在异常路径也写 STEP_END | 保持（Phase 4 D2 已登记；`revert_service` 有兜底） | — |
| **m5** | perf 脚本 `--impl legacy` 现 `ImportError` | 前置检查：模块不存在时打印指引并 `exit 2`，指向已提交的 baseline JSON；`build_legacy_engine` 抛 `LegacyEngineGone` 带说明 | 手工验证：`--impl legacy` → `exit=2` + 指引文案 |
| **m6** | 测试文件命名与计划不一致 | 计划附录 C · m6 对齐（保留按 Hook 拆分） | — |
| **m7** | `engine.py` 末尾 `LoopEngine = DefaultLoopEngine` 遮蔽了导入的 ABC | 删除该别名（包 `__init__.py` 已提供兼容别名）；模块内 `LoopEngine` 现在只指 ABC | 全量测试 + `broca.loop_engine.LoopEngine` 别名仍可用 |
| **m8** | ABC 仍把 `context_compressor` / `memory_manager` 声明为必填 | 保持（计划遗留事项 2），本次不改 ABC 签名（避免第三方 LoopEngine 实现破坏 LSP） | — |

---

## 变更文件清单

| 文件 | 变更 |
|------|------|
| `broca/loop_engine/engine.py` | 删除 `LoopEngine` 模块别名（m7）；`_process_tool_results` 补位 + 跳过占位（m1/M3）；`_is_abort_placeholder()` 新增；`initialize()` 重复调用告警（m2）；新增常量 `_MISSING_RESULT_CONTENT` |
| `broca/loop_engine/hooks/communicator_hook.py` | 新增 `_tracks_snapshots` 门控 + `on_step_start` 早退（m3） |
| `broca/loop_engine/hooks/factory.py` | 新增 `SUBAGENT_ROLES` / `is_subagent_config()` / `build_hooks_for()`（M1） |
| `broca/loop_engine/hooks/__init__.py` | 导出上述 3 个新符号 |
| `broca/loop_engine/strategies/serial_tool.py` | `ABORTED_TOOL_RESULT_CONTENT` 改为从 `components.tool_strategy` 导入（保持同名导出） |
| `broca/components/tool_strategy.py` | 新增共享契约常量 `ABORTED_TOOL_RESULT_CONTENT` |
| `broca/agent.py` | `build_default_hooks` → `build_hooks_for`（M1） |
| `scripts/perf/loop_engine_bench.py` | legacy 分支降级为「指引 + exit 2」（m5） |
| `plans/loop-engine-hooks-refactor-plan.md` | 概述标注 + **附录 C**（C1 / M5 / m6 / M4） |
| `broca/tests/test_engine_orchestration.py` | 行数断言 → 方法数护栏（C1） |
| `broca/tests/test_engine_dispatch.py` | +4 例（M3×2 / m1 / m2） |
| `broca/tests/test_communicator_hook.py` | `FakeConfig` 补 `enable_snapshot_tracking` / `workspace`；+3 例（m3） |
| `broca/tests/test_hook_factory.py` | +6 例（M1 角色路由） |
| `broca/tests/test_agent_composition.py` | +2 例（M1 端到端接线） |

## 测试结果

```
$ pytest broca/tests/ -q
920 passed, 3 skipped, 1 deselected, 21 warnings in 26.61s
→ 0 failed / 924 collected（整改前 905 passed / 908 collected，+15 例）
```

| 文件 | 整改前 | 整改后 | 增量 |
|------|:------:|:------:|:----:|
| `test_engine_orchestration.py` | 18 | 18 | 0（行数护栏 → 方法数护栏） |
| `test_engine_dispatch.py` | 9 | 13 | +4 |
| `test_communicator_hook.py` | 14 | 17 | +3 |
| `test_hook_factory.py` | 12 | 18 | +6 |
| `test_agent_composition.py` | 12 | 14 | +2 |

## 性能复测（整改后）

| benchmark | legacy baseline | 整改后 | delta | AC |
|-----------|----------------:|-------:|------:|:--:|
| `llm_call` | 0.013371 ms | 0.0135 ms | +0.01 µs | ✅ <1ms |
| `parallel_tools` | 0.082637 ms | 0.0821 ms | −0.6% | ✅ <2% |
| `execute_round` | 0.069112 ms | 0.0747 ms | +8.1%（+5.6 µs） | — 可接受 |
| `hook_dispatch` | 非等价 | 0.0074 ms | — | ✅ <0.02ms |

> `execute_round` 增幅略升（+6.46% → +8.1%），来自新增的 `_is_abort_placeholder()` 判定与 `on_step_start` 门控，绝对量 +5.6 µs，相对真实 LLM 往返 < 0.005%，不影响结论。

## 遗留事项

1. **M6 真实前端手测**（合并前人工，见上）。
2. **m8**：`LoopEngine.initialize()` ABC 仍把 `context_compressor` / `memory_manager` 声明为必填 → 后续可从 ABC 移除（需同步 `agent.py`，并删除 `_do_initialize` 的 `del` 兼容参数）。
3. `broca/loop_engine/__init__.py` 的 `LoopEngine = DefaultLoopEngine` 别名长期是否废弃（计划 TODO 4）。
4. `ComponentRegistry` 的策略注册机制（计划 TODO 1）。
5. `test_agent_composition.py` 存在既有未使用 import（ruff F401，非本次引入，未清理以免无关 churn）。
