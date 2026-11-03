# Loop Engine 策略+Hook 重构

## 概述

- **目标**：将 `DefaultLoopEngine`（1427 行 / **52 个方法**）重构为 **纯编排器 + 可插拔策略 + 可组合 Hook** 的三层架构
- **背景**：当前引擎将 LLM 调用（含重试/限流/流式）、工具执行（串行/并行/分区）、快照、通信、压缩、记忆、死循环检测、DB 持久化全部硬编码在一个类中，任何行为变更都需要改核心方法
- **约束条件**：
  - 迁移前测试基线：`pytest broca/tests/ --collect-only` = **754 collected（1 deselected）**
  - Phase 4/5 的通过判据为「**迁移后 0 失败，且总用例数 ≥ 751**」（旧用例会被迁移/改写，不再是"旧测试全绿"）
  - `LoopEngine` ABC 公开方法（`execute` / `abort` / `reset` / `initialize`）保持不变；`initialize` 只**新增带默认值**的参数（`llm_strategy=None` / `tool_strategy=None` / `hooks=None` / `memory_manager=None`），保证 Phase 1~3 期间调用方无需改动
  - `ExecutionStatus` / `ExecutionResult` 不动
  - 不影响 `ComponentRegistry` 插件机制（`defaults.py` 的字符串路径 `broca.loop_engine:DefaultLoopEngine` 必须持续可解析）
  - 性能无回退（策略/Hook 调用是 in-process，无 I/O 开销）
- **行数口径（唯一标准）**：`broca/loop_engine/engine.py` **总行数 ≤ 320 行**，其中核心编排（`execute` / `_setup_turn` / `_execute_round` / `_execute_step` / `_dispatch`）≈ 200 行。其它位置不再出现 200/250/300/350 等口径。
  > ⚠️ **本口径已于 Phase 5 由计划 owner 撤销**（可读性优先）。文中 7 处 `≤320` 引用一并失效，以「结构护栏」替代，详见 **附录 C · C1**。

---

## 修订历史

- **v3（当前）**：修复 Round-2 评审的 1 Critical（`/compact` 调用方）+ 4 Major（回归门禁数字、`tool_executor` 归属、`_save_response` 返回值、error code 保真度）+ 11 Minor。逐条见 **附录 B**。
- **v2**：修复 Round-1 评审的 5 Critical / 18 Major / 16 Minor。逐条见 **附录 A**。

> 正文为执行依据；附录仅供评审追溯，执行时无需阅读。

---

## 相关材料

| 类别 | 文件 | 用途 |
|------|------|------|
| 当前实现 | `broca/loop_engine.py`（1427 行 / 52 个方法） | 重构对象；Phase 1 将被 `git mv` 为 `broca/loop_engine/legacy.py` |
| 组件接口 | `broca/components/loop_engine.py` | `LoopEngine` ABC + `ExecutionStatus` / `ExecutionResult` |
| 基类 | `broca/components/base.py` | `BaseComponent`（只有 `initialize` / `shutdown`，**无** `name`） |
| 组件注册表 | `broca/components/registry.py`、`broca/components/defaults.py:52` | `"broca.loop_engine:DefaultLoopEngine"` 字符串路径 |
| 调用方 | `broca/agent.py:77-192`（`Agent.create()`） | 依赖注入（当前以 kwargs 传入，天然兼容签名变化） |
| LLM 客户端 | `broca/components/llm_client.py`（ABC） | `get_stream_response` / `aggregate_message` / `input_tokens_used` |
| 工具执行 | `broca/components/tool_executor.py`（ABC） | `execute_tool` / `get_permission` / `is_readonly_tool` |
| 工具类型 | `broca/tools/tool.py:14/19/41` | `ToolStatus` / `ToolResult` / `ToolCallContext`（**只有** agent/workspace/session_id/execution_id/namespace/turn_id/agent_id 七个字段，**无 `abort_event`**） |
| Agent 协议 | `broca/components/protocols.py:76` | `AgentReference.on_llm_call_completed(input_tokens, output_tokens)`、`CompressorContext` |
| 快照接口 | `broca/components/snapshot_manager.py` | `track` / `calculate_diff` / `get_diff_summary` / `acquire_lock` |
| 压缩接口 | `broca/components/context_compressor.py` | `check_and_compress(context, compressor_context)` |
| 配置 | `broca/configs.py:28-39`、`broca/agent_configs.py:55-57` | `step_max_errors` / `llm_retry_delay` / `llm_timeout` / `dead_loop_window` / `tool_execution_mode` / `max_parallel_tools` / `enable_snapshot_tracking` |
| 下游依赖（turn） | `broca-web/backend/app/api/session.py:695`、`broca/session/models.py:123` | 依赖 `save_turn_end` 写入的 turn 状态（Critical C3 的根因） |
| **下游依赖（压缩）** | **`broca/commands/builtin/compact/__init__.py:63`** | `/compact` 命令直接调 `execution_engine._build_compressor_context()`；**该路径无任何测试覆盖**（Round2 N1） |
| 协议 docstring | `broca/components/protocols.py:62` | docstring 仍写「proxied … for use by `_build_compressor_context()`」，需同步改名 |
| 测试 | `broca/tests/test_loop_engine.py`（37 例）、`test_e2e_scenarios.py`、`test_agent_composition.py`、`test_image_tool.py:550` | 迁移与回归 |

---

## 总体方案

### 架构总览

```
┌────────────────────────────────────────────────────────────────────────────┐
│                  DefaultLoopEngine（纯编排器，engine.py ≤320 行）            │
│                                                                            │
│  execute(message):                                                         │
│    turn_ctx = _setup_turn(message)        # 每 turn 状态重置 + DB 写入       │
│    dispatch("on_turn_start", turn_ctx)                                     │
│    result = _execute_round(turn_ctx, max_steps)                            │
│    _finalize_turn(turn_ctx, result)       # save_turn_end（DB，engine 负责） │
│                                                                            │
│  _execute_round(turn_ctx, max_steps):                                      │
│    while True:                                                             │
│      if abort → return _build_round_result(ABORTED)                        │
│      step_ctx = _execute_step(turn_ctx)                                    │
│      if step_ctx.status != RUNNING → return _build_round_result(...)       │
│                                                                            │
│  _execute_step(turn_ctx):                                                  │
│    llm = llm_strategy.call(history, tools, on_chunk, on_error, should_abort)│
│    agent_ref.on_llm_call_completed(llm.input_tokens, llm.output_tokens)     │
│    step_ctx.has_write_ops = _check_write_ops(tool_calls)   ← 快照开关        │
│    dispatch("on_step_start", step_ctx)                                     │
│    _save_response(...)                                                     │
│    results = tool_strategy.execute(...)                                    │
│    _process_tool_results(tool_calls, results)   # 广播+DB+context+extra     │
│    dispatch("on_step_end", step_ctx)      # 快照 patch / 死循环 → status     │
│    dispatch("on_post_step", step_ctx)     # 压缩 / 记忆提取                  │
└────────────────────────────────────────────────────────────────────────────┘

     策略层（怎么做）                         Hook 层（额外做什么）
 ┌──────────────────────────┐        ┌────────────────────────────────────────┐
 │ LLMStrategy (ABC)        │        │ LoopHook (ABC)                          │
 │  .call(history, tools,   │        │  .on_turn_start(ctx)                    │
 │    on_chunk, on_error,   │        │  .on_turn_end(ctx)        ← 状态计算     │
 │    should_abort)         │        │  .on_turn_finalized(ctx)  ← 已入库后广播 │
 │  .reset()                │        │  .on_step_start(ctx)                    │
 │ 默认 RetryLLMStrategy     │        │  .on_step_end(ctx)                      │
 │  (重试/限流/超时/空响应/  │        │  .on_post_step(ctx)                     │
 │   流式聚合)              │        │  .reset()                               │
 ├──────────────────────────┤        │                                         │
 │ ToolExecutionStrategy    │        │ 默认实例（顺序固定）:                     │
 │  .execute(tool_calls,    │        │  • SnapshotHook        （on_step/turn）  │
 │    context, mapping,     │        │  • CommunicatorHook    （on_turn/step）  │
 │    should_abort)         │        │  • DeadLoopHook        （on_step_end）   │
 │ 默认 ParallelToolStrategy │        │  • CompressionMemoryHook（on_post_step） │
 │ 备选 SerialToolStrategy   │        │                                         │
 └──────────────────────────┘        │ 子 Agent 精简集：DeadLoop + Compression  │
                                     └────────────────────────────────────────┘
```

### 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 策略 vs Hook 分界 | 策略 = 核心行为的可替换实现；Hook = 附加行为的组合 | 策略是"必须做但可以换做法"，Hook 是"可选做可以不做" |
| **abort 信号传递** | 策略接口显式接收 `should_abort: Callable[[], bool]`（engine 传 `lambda: self.abort_event.is_set()`） | `ToolCallContext` 无 `abort_event`；现有实现就是靠 `self.abort_event` 判定（`_call_llm_with_retry` L362、`_call_llm_streaming` L641），策略不持有 engine 引用也能保持语义 |
| **LLM 错误通知通道** | `LLMStrategy.call()` 增加独立 `on_error(message, code, severity)` 回调（**不**塞进 chunk） | 现有 `_send_llm_error` 有 6 个调用点、含 warning/error 两级语义，混进流式 chunk 会污染聚合逻辑；独立回调语义清晰且可单测 |
| LLM 流式广播归属 | 引擎持有薄广播逻辑（`_make_chunk_handler`），通过 `on_chunk` 回调传给 LLM 策略 | LLM 策略保持纯逻辑（不依赖 communicator）；引擎知道 `interactive` 与 communicator |
| **工具结果处理归属** | 留在 engine：`process_tool_call_result()`（单条）+ `_process_tool_results()`（批量、按原顺序） | 需要 `session_manager`（DB 写入）、`communicator`（广播）、`context`（历史）——Hook 层不宜承担 DB 写入；同时保留 `test_image_tool.py:550` 直接调用 `LoopEngine.process_tool_call_result` 的兼容性 |
| **turn 持久化归属** | `session_manager.save_turn_end` 留在 engine 的 `_finalize_turn()` | 两个 Hook 都不具备 `session_manager` 依赖；web 后端（`api/session.py:695`）依赖该写入 |
| **turn_end 广播时机** | 新增第 6 个生命周期方法 `on_turn_finalized`（DB 入库后调用） | 保持现有「先 `save_turn_end` 再广播」的顺序：`on_turn_end` 只做状态计算（changed_files），`on_turn_finalized` 只做对外通知 |
| **每 turn 状态重置** | `_setup_turn()` 中重置 `abort_event` + 所有 Hook 的 `reset()` + `llm_strategy.reset()` | 对齐现有 `execute()` L1101-1103（清 abort / 清签名历史 / 清零限流计数），避免跨 turn 污染 |
| Hook 接口粒度 | 单一 `LoopHook` ABC，6 个可选生命周期方法 | 比 6 个独立 ABC 更灵活（一个 Hook 可参与多阶段） |
| **Hook `name`** | **非抽象类属性** `name: str = "loop_hook"`，每个 Hook 覆写 | `BaseComponent` 无 `name`；若用 `@property @abstractmethod` 而子类漏写，`build_default_hooks()` 直接 TypeError。默认值 + AC 双保险 |
| 执行顺序 | Hook 按注册顺序依次 await；策略只有一个实例 | `build_default_hooks()` 固定顺序：快照→通信→死循环→压缩。DeadLoop 在 `on_step_end`、Compression 在 `on_post_step`，互不耦合 |
| 错误传播 | Hook 异常 catch + log，不中断；策略异常按现有逻辑处理 | 快照失败不阻塞 LLM；LLM 重试耗尽仍失败才中断 |
| Context 数据类 | `TurnContext`（turn 级）+ `StepContext`（step 级） | 解耦 Hook 间依赖（SnapshotHook 写 snapshot/patch，CommunicatorHook 读它广播） |
| 子 Agent 场景 | `build_subagent_hooks()` 返回精简集（无快照、无通信） | 子 Agent 不需要前端交互和文件快照 |
| **策略选择入口** | 只做 `AgentConfig`（`strategies/factory.py`），`ComponentRegistry` 注册策略留 TODO | 两条路都没落地；先实现一条可测的，避免设计悬空 |
| **包化方式** | Phase 1 直接 `git mv broca/loop_engine.py → broca/loop_engine/legacy.py` + 包 `__init__.py` re-export | 彻底消除「模块文件 vs 同名包」歧义；`__init__.py` 在 Phase 4 切到 `engine.py`，Phase 5 删 `legacy.py` |
| **`LoopEngine` 别名** | 包 `__init__.py` 继续导出 `LoopEngine = DefaultLoopEngine`（具体类），并在 docstring 显式声明「ABC 请从 `broca.components` 导入」 | 现有 `test_loop_engine.py:177` 用 `LoopEngine(...)` 实例化、`test_image_tool.py:484` 用 `MagicMock(spec=LoopEngine)`；改语义会连带破坏，故保留但标注。**使用约定**：`register(...)` / `isinstance` 判定 / 类型标注一律用 `broca.components.LoopEngine`（ABC）；`broca.loop_engine.LoopEngine` 仅供历史 import 兼容 |

### 方法迁移映射表（52 个方法全量去向）

> 行号基于当前 `broca/loop_engine.py`。`engine` 列指 `broca/loop_engine/engine.py`。

| # | 方法 | 行号 | 归属 | 说明 |
|:-:|------|:----:|------|------|
| 1 | `__init__` | 59 | engine | 状态字段精简。**必须保留**：`abort_event` / `turn_id` / `step_id` / `execution_id` / `namespace` / `allowed_tools`，以及依赖字段 `agent_ref` / `llm_client` / `context` / `communicator` / `session_manager` / `config` / `tool_mapping` / **`tool_executor`**（`_check_write_ops` 与 `reset` 依赖，且 3 处测试断言 `engine.tool_executor`）。**仅移除**：`snapshot_manager` / `context_compressor` / `persistent_memory_manager`。**保留** legacy 构造式初始化路径 `__init__(agent_ref=..., llm_client=..., ...)`（`test_loop_engine.py:177` fixture 与 `test_image_tool.py` 依赖，成本极低） |
| 2 | `_do_initialize` | 123 | engine | 逻辑合并进 `initialize()`，但**保留 `__init__(agent_ref=...)` 构造式路径**（当 `agent_ref is not None` 时调用同一份 `_do_initialize`）；配置读取保留（含 agent 级覆盖优先级） |
| 3 | `initialize` | 197 | engine | 保持 `**kwargs` 实现（`# type: ignore[override]`），新增 `llm_strategy` / `tool_strategy` / `hooks` |
| 4 | `_initialize_snapshot_tracking` | 208 | SnapshotHook | `on_turn_start` 内 lazy 初始化，受 `config.enable_snapshot_tracking` 控制 |
| 5 | `_generate_step_id` | 219 | engine | 原样 |
| 6 | `_capture_step_init` | 223 | engine（**删除**） | 职责并入 `StepContext` 构造（`has_write_ops=False` 默认） |
| 7 | `_broadcast_step_message` | 227 | CommunicatorHook | 通用 step 消息广播 |
| 8 | `_save_step_message` | 235 | engine | DB 写入，留 engine |
| 9 | `_acquire_step_lock` | 246 | SnapshotHook | `on_step_start` |
| 10 | `_release_step_lock` | 253 | SnapshotHook | `on_step_end`（try/finally 语义） |
| 11 | `_capture_step_start_snapshot` | 259 | SnapshotHook | 写 `ctx.step_start_snapshot` |
| 12 | `_compute_step_end_patch` | 271 | SnapshotHook | 写 `ctx.step_end_snapshot` + `ctx.step_patch` |
| 13 | `_capture_step_start` | 304 | SnapshotHook | `on_step_start` 入口（`has_write_ops` 门控） |
| 14 | `_capture_step_end` | 326 | SnapshotHook | `on_step_end` 入口 |
| 15 | `_call_llm_with_retry` | 348 | RetryLLMStrategy | `call()` 的重试主循环（限流/超时/空响应/其他错误四类分支原样保留） |
| 16 | `_send_llm_error` | 463 | RetryLLMStrategy → `on_error` 回调 | 策略只负责"报告"，engine 的 handler 调 `communicator.send_error` |
| 17 | `_detect_dead_loop` | 471 | DeadLoopHook | `on_step_end` 写 `ctx.status` |
| 18 | `_save_response_and_process_tool_calls` | 487 | engine | 拆为 `_save_response() -> bool`（DB 写入失败返回 `False`，调用方必须中止 step）+ `_run_tools()` |
| 19 | `_trigger_post_step_hooks` | 510 | CompressionMemoryHook | `on_post_step` |
| 20 | `execute_step` | 533 | engine `_execute_step()` | 编排骨架 |
| 21 | `_process_content_chunk` | 570 | RetryLLMStrategy | 聚合 + 通过 `on_chunk` 发出（携带 `index` / `message_id`） |
| 22 | `_process_tool_call_chunk` | 591 | RetryLLMStrategy | 聚合 + 首次出现去重后通过 `on_chunk` 发出 |
| 23 | `_finalize_llm_response` | 615 | RetryLLMStrategy（聚合）+ engine（token 上报） | `aggregate_message()` 在策略内；`agent_ref.on_llm_call_completed` 由 engine 用 `LLMCallResult` 的 token 调用。**语义变化（有意收紧）**：legacy 在每次 attempt（含空响应 attempt）都上报，新设计只在 `success=True` 后上报一次；失败/空响应/abort 早退路径**不上报**。需在 PR 描述中记录，并确认不影响 `last_context_length` 驱动的压缩阈值判断 |
| 24 | `_call_llm_streaming` | 629 | RetryLLMStrategy | `async for chunk` 循环 + `should_abort` 检查 |
| 25 | `_get_tools_list` | 663 | engine | 作为 `call(tools=...)` 的入参 |
| 26 | `_build_tool_context` | 672 | engine | 构造 `ToolCallContext`（7 个字段） |
| 27 | `_build_compressor_context` | 684 | `loop_engine/compressor_context.py::build_compressor_context()` | 独立工厂函数（不依赖 engine 实例），供 CompressionMemoryHook **与 `/compact` 命令**使用。⚠️ 原 engine 方法**删除**，故 `commands/builtin/compact/__init__.py:63` 必须同步改（Task 4.1c 步骤 5） |
| 28 | `_process_tool_calls` | 721 | 分区判定 → `ParallelToolStrategy.execute()`；串行分支 → `SerialToolStrategy.execute()` | 分区规则（`len<=1` 或 mode=serial → 串行）保留在策略内 |
| 29 | `_process_tool_calls_parallel` | 772 | `ParallelToolStrategy.execute()` | semaphore + permission 分区 + 原顺序 |
| 30 | `check_step_has_write_operations` | 860 | engine `_check_write_ops()` | 返回 bool，写入 `step_ctx.has_write_ops` |
| 31 | `_extract_tool_call_signatures` | 879 | DeadLoopHook（staticmethod） | 原样 |
| 32 | `_normalize_arguments` | 902 | DeadLoopHook（staticmethod） | JSON 排序归一化 |
| 33 | `process_tool_call_result` | 930 | engine（**保留公共名**）+ `_process_tool_results()` 批量封装 | 广播 + `save_tool_call` + `context.add_message` + `extra_context_messages` |
| 34 | `_build_round_result` | 998 | engine | 逻辑原样，但**改为同步 `def`**（无 await 逻辑；legacy 是 `async def`，改 sync 后全文调用不带 `await`） |
| 35 | `execute_round` | 1014 | engine `_execute_round()` | 终止条件改为读取 `step_ctx.status` |
| 36 | `_send_execution_error` | 1057 | engine | 需要 `config.interactive` + communicator，engine 已持有 |
| 37 | `_make_error_result` | 1071 | engine | 原样 |
| 38 | `execute` | 1081 | engine | 异常包装 + `_finalize_turn` |
| 39 | `_get_turn_end_message` | 1143 | engine | `_finalize_turn` 内部 |
| 40 | `_compute_turn_level_diff` | 1155 | SnapshotHook | `on_turn_end` → 写 `ctx.result.data["changed_files"]` |
| 41 | `_clear_turn_snapshots` | 1201 | SnapshotHook | `reset()` |
| 42 | `_save_and_broadcast_turn_end` | 1206 | **拆分**：`save_turn_end` → engine `_finalize_turn()`；`send_turn_end` → CommunicatorHook `on_turn_finalized()` | Critical C3 |
| 43 | `_send_turn_error_notification` | 1235 | CommunicatorHook | `on_turn_finalized`（status != COMPLETED 时） |
| 44 | `process_turn_end` | 1254 | engine `_finalize_turn()` | 编排：ABORTED 截断 → dispatch `on_turn_end` → `save_turn_end` → dispatch `on_turn_finalized` |
| 45 | `_start_new_turn` | 1279 | engine `_start_turn()` | **只**做 `_ensure_session` + `start_turn` + 写 `turn_id`；广播移除（M13） |
| 46 | `_save_user_message` | 1296 | engine | 原样（含 from_agent 预生成 message_id 的回归修复） |
| 47 | `_broadcast_user_message` | 1321 | CommunicatorHook | `on_turn_start` |
| 48 | `_setup_execution_context` | 1345 | engine `_setup_turn()` | 返回 `TurnContext`；加入每 turn 状态重置（M12） |
| 49 | `_ensure_session` | 1383 | engine | 原样 |
| 50 | `abort` | 1390 | engine | 原样 |
| 51 | `reset` | 1399 | engine | 追加：遍历 `hook.reset()` + `llm_strategy.reset()` |
| 52 | `_truncate_last_assistant_message_with_tool_calls` | 1414 | engine | ABORTED 分支 |

### 文件结构

```
broca/
├── components/
│   ├── loop_hook.py            # LoopHook ABC + TurnContext + StepContext
│   ├── llm_strategy.py         # LLMStrategy ABC + LLMCallResult
│   ├── tool_strategy.py        # ToolExecutionStrategy ABC
│   └── loop_engine.py          # LoopEngine ABC（initialize 增加可选参数 + add_hook）
├── loop_engine/                # 包（Phase 1 由 loop_engine.py git mv 而来）
│   ├── __init__.py             # 公开名称 re-export（Phase 1 指向 legacy，Phase 4 起指向 engine）
│   ├── legacy.py               # 旧实现（Phase 5 删除）
│   ├── engine.py               # DefaultLoopEngine 编排器（≤320 行）
│   ├── compressor_context.py   # build_compressor_context() 工厂（原 _build_compressor_context）
│   ├── strategies/             # Phase 2 独占（Phase 3 不得修改本目录）
│   │   ├── __init__.py
│   │   ├── factory.py          # create_llm_strategy / create_tool_strategy
│   │   ├── retry_llm.py        # RetryLLMStrategy
│   │   ├── parallel_tool.py    # ParallelToolStrategy
│   │   └── serial_tool.py      # SerialToolStrategy
│   └── hooks/                  # Phase 3 独占（Phase 2 不得修改本目录）
│       ├── __init__.py
│       ├── factory.py          # build_default_hooks / build_subagent_hooks
│       ├── snapshot_hook.py
│       ├── communicator_hook.py
│       ├── compression_hook.py
│       └── dead_loop_hook.py
└── tests/
    ├── fixtures/llm_streaming/*.json   # golden fixtures（Task 2.1）
    ├── test_llm_strategy.py / test_llm_strategy_golden.py
    ├── test_tool_strategy.py
    └── test_loop_hooks.py
```

> **不存在** `broca/loop_engine.py`（模块文件）。Phase 1 即 `git mv` 掉，杜绝「模块 vs 包」同名歧义（Review M10 / m13）。

### 接口契约速查（执行者以此为准）

```python
# ── broca/components/llm_strategy.py ────────────────────────────────────────
@dataclass
class LLMCallResult:
    message: Any | None = None        # 聚合后的 LLMMessage（含 message_id 属性）
    message_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    success: bool = True
    aborted: bool = False             # should_abort 命中 → True（不 sleep、不重试）
    error_code: str = ""
    error_message: str = ""

class LLMStrategy(BaseComponent, ABC):
    name: str = "llm_strategy"        # 类属性，子类覆写

    @abstractmethod
    async def call(
        self,
        history: list,
        tools: list[dict],
        *,
        on_chunk: Callable[[dict], Awaitable[None]] | None = None,
        on_error: Callable[[str, str, str], Awaitable[None]] | None = None,
        should_abort: Callable[[], bool] | None = None,
    ) -> LLMCallResult: ...

    @abstractmethod
    async def initialize(self, *, llm_client: "LLMClient", config: Any) -> None:
        """必需依赖：llm_client / config（provider、model、超时与重试参数均取自 config）。"""
        ...

    def reset(self) -> None: ...       # 默认 no-op

# on_chunk 事件契约（策略负责聚合与去重，engine 只做广播）：
#   {"type": "content",           "data": str,  "index": int, "message_id": str}
#   {"type": "reasoning_content", "data": str,  "index": int, "message_id": str}
#   {"type": "tool_call",         "data": ToolCall, "message_id": str}   # 仅 tool_call 首次出现
# on_error 契约：(message: str, code: str, severity: "warning" | "error")
# should_abort 契约：在每次重试迭代开始、每个 chunk 处理前检查；
#   返回 True 时立即 return LLMCallResult(success=False, aborted=True)（不 sleep、不重试）

# ── broca/components/tool_strategy.py ──────────────────────────────────────
class ToolExecutionStrategy(BaseComponent, ABC):
    name: str = "tool_strategy"

    @abstractmethod
    async def execute(
        self,
        tool_calls: list,
        context: "ToolCallContext",
        tool_mapping: dict,
        *,
        allowed_tools: list[str] | None = None,
        should_abort: Callable[[], bool] | None = None,
    ) -> list["ToolResult"]: ...       # 顺序与输入一致；ToolExecutor 由 initialize 注入

    @abstractmethod
    async def initialize(self, *, tool_executor: "ToolExecutor", config: Any) -> None:
        """必需依赖：tool_executor / config（max_parallel_tools 等取自 config）。"""
        ...

    def reset(self) -> None: ...       # 默认 no-op

# ── broca/components/loop_hook.py ─────────────────────────────────────────
class LoopHook(BaseComponent, ABC):
    name: str = "loop_hook"            # 非抽象；子类覆写

    async def on_turn_start(self, ctx: TurnContext) -> None: ...
    async def on_step_start(self, ctx: StepContext) -> None: ...
    async def on_step_end(self, ctx: StepContext) -> None: ...
    async def on_post_step(self, ctx: StepContext) -> None: ...
    async def on_turn_end(self, ctx: TurnContext) -> None: ...        # 状态计算（diff 等）
    async def on_turn_finalized(self, ctx: TurnContext) -> None: ...  # DB 入库后的对外通知
    def reset(self) -> None: ...                                      # 默认 no-op
```

**生命周期调用顺序（engine 唯一真源）**：

```
_setup_turn → [on_turn_start] → loop:
    llm_strategy.call → _check_write_ops → [on_step_start] → _save_response
    → tool_strategy.execute → _process_tool_results
    → [on_step_end] → [on_post_step]
→ _finalize_turn: [on_turn_end] → save_turn_end → [on_turn_finalized]
```

---

## 执行计划

### Phase 1: 基础设施（接口 + 数据类 + 包骨架）

**目标**：定义所有接口层并完成包化，不改变任何运行时行为

**阶段验收标准**：
- [ ] `LoopHook` ABC + `TurnContext` + `StepContext` 定义完成（`name` 为非抽象类属性）
- [ ] `LLMStrategy` ABC + `LLMCallResult`、`ToolExecutionStrategy` ABC 定义完成
- [ ] 所有类型可从 `broca.components` 导入
- [ ] **不修改任何已有文件的行为**；例外仅三处：`broca/components/loop_engine.py`（Task 1.4 签名）、`broca/components/__init__.py`（re-export）、`broca/loop_engine.py`（Task 1.5 仅 `git mv`，内容不变）
- [ ] `broca/loop_engine/` 包已建立，`broca/loop_engine.py` 已不存在
- [ ] 迁移后测试：**0 失败，总数 ≥751**（基线 754）

#### Task 1.1: 定义 LoopHook ABC + 上下文数据类

- **目标**：创建 Hook 接口和共享上下文
- **步骤**：
  1. 新建 `broca/components/loop_hook.py`，**文件首行必须 `from __future__ import annotations`**（避免 `"X" | None` 运行期求值报错）
  2. 定义 `TurnContext`：
     ```python
     @dataclass
     class TurnContext:
         turn_id: str
         agent_id: str
         session_id: str
         user_message: dict          # llm_client.parse_message() 的结果
         message_id: str             # 用户消息入库后的 message_id
         sender_id: str = ""
         files: list = field(default_factory=list)   # 用户消息附件（原 message.data["files"]）
         from_agent: bool = False
         raw_input: str = ""
         result: "ExecutionResult | None" = None     # turn 结束时由引擎填充
         data: dict = field(default_factory=dict)    # turn_end_message / turn_end_message_id 等
     ```
  3. 定义 `StepContext`：
     ```python
     @dataclass
     class StepContext:
         step_id: str
         turn_id: str
         agent_id: str
         session_id: str
         response: Any = None
         tool_calls: list = field(default_factory=list)
         tool_results: list = field(default_factory=list)
         has_write_ops: bool = False       # 由引擎在 on_step_start 前填充（Task 4.1a）
         status: "ExecutionStatus" = None  # 引擎初始化 RUNNING；Hook 可改（DeadLoop）
         llm_input_tokens: int = 0
         llm_output_tokens: int = 0
         step_start_snapshot: str = ""
         step_end_snapshot: str = ""
         step_patch: dict = field(default_factory=dict)
         data: dict = field(default_factory=dict)
     ```
  4. 定义 `LoopHook`（6 个生命周期方法 + `reset` + `name`）：
     ```python
     class LoopHook(BaseComponent, ABC):
         """Loop Engine 可插拔生命周期钩子（子类覆写需要的方法，其余 no-op）。"""

         name: str = "loop_hook"        # 非抽象类属性；每个 Hook 必须覆写为唯一名字

         async def on_turn_start(self, ctx: TurnContext) -> None: ...
         async def on_step_start(self, ctx: StepContext) -> None: ...
         async def on_step_end(self, ctx: StepContext) -> None: ...
         async def on_post_step(self, ctx: StepContext) -> None: ...
         async def on_turn_end(self, ctx: TurnContext) -> None:
             """状态计算阶段（在 save_turn_end 之前），不得做对外通知。"""
         async def on_turn_finalized(self, ctx: TurnContext) -> None:
             """对外通知阶段（在 save_turn_end 之后）：广播 turn_end / 错误提示。"""
         def reset(self) -> None:
             """重置 Hook 内部状态（引擎 reset() 与每 turn 开始时调用）。"""
     ```
  5. 在 `broca/components/__init__.py` re-export
- **预期产出**：`broca/components/loop_hook.py`（~100 行）
- **验收标准**：
  - [ ] `LoopHook` 有 `name` 类属性（**非** abstract property）+ 6 个 async 方法（非 abstract，默认 `pass`）+ `reset()`
  - [ ] 定义一个空子类（只覆写 `name`）可成功实例化（防 C5 回归）
  - [ ] `TurnContext` 含 turn_id/agent_id/session_id/user_message/message_id/sender_id/files/result
  - [ ] `StepContext` 含 step_id/response/tool_calls/tool_results/has_write_ops/status + 快照字段
  - [ ] `from broca.components import LoopHook, TurnContext, StepContext` 成功

#### Task 1.2: 定义 LLMStrategy ABC

- **目标**：抽象 LLM 调用的完整生命周期（含中止信号与错误通知）
- **步骤**：
  1. 新建 `broca/components/llm_strategy.py`（**首行 `from __future__ import annotations`**）
  2. 按「接口契约速查」实现 `LLMCallResult` 与 `LLMStrategy`
  3. `provider` / `model` **不进 `call()` 签名**，由 `initialize()` 注入的 config 提供（与架构图 `llm_strategy.call(history, tools, on_chunk)` 一致）
  4. re-export
- **预期产出**：`broca/components/llm_strategy.py`（~70 行）
- **验收标准**：
  - [ ] `call()` 签名含 `on_chunk` / `on_error` / `should_abort` 三个关键字参数
  - [ ] `LLMCallResult` 含 message/message_id/tokens/success/aborted/error 字段
  - [ ] `reset()` 存在且有默认 no-op 实现
  - [ ] 不依赖 communicator / session_manager / context

#### Task 1.3: 定义 ToolExecutionStrategy ABC

- **目标**：抽象工具执行的策略（串行/并行）
- **步骤**：
  1. 新建 `broca/components/tool_strategy.py`（**首行 `from __future__ import annotations`**）
  2. 按「接口契约速查」实现；`ToolExecutor` 由 `initialize(tool_executor, config)` 注入，**不再**出现在 `execute()` 参数中
  3. re-export
- **预期产出**：`broca/components/tool_strategy.py`（~45 行）
- **验收标准**：
  - [ ] `execute()` 返回 `list[ToolResult]`（顺序与输入 tool_calls 一致）
  - [ ] `execute()` 含 `should_abort` 关键字参数（不引用 `ToolCallContext.abort_event`——该字段不存在）
  - [ ] `reset()` 存在且有默认 no-op 实现

#### Task 1.4: 更新 LoopEngine ABC 的 initialize 签名

- **目标**：在 ABC 中声明策略和 Hook 的注入点（**全部带默认值**，避免 Phase 1~3 契约空窗）
- **步骤**：
  1. 修改 `broca/components/loop_engine.py`（该文件已有 `from __future__ import annotations`）：
     ```python
     @abstractmethod
     async def initialize(
         self,
         agent_ref: "AgentReference",
         llm_client: "LLMClient",
         context: "Context",
         tool_executor: "ToolExecutor",
         context_compressor: "ContextCompressor",
         communicator: "Communicator",
         session_manager: "SessionManager",
         config: Any,
         tool_mapping: dict[str, "Tool"],
         permission_provider: "PermissionProvider",
         # ── 新增（全部可选，Phase 1~3 调用方无需改动）──
         llm_strategy: "LLMStrategy | None" = None,
         tool_strategy: "ToolExecutionStrategy | None" = None,
         hooks: list["LoopHook"] | None = None,
         memory_manager: "MemoryManager | None" = None,
     ) -> None: ...
     ```
  2. 新增非抽象 `add_hook()`：
     ```python
     def add_hook(self, hook: "LoopHook") -> None:
         """注册一个生命周期 Hook（可在 initialize 后追加）。默认实现：append 到内部列表。"""
         hooks = getattr(self, "_hooks", None)
         if hooks is None:
             self._hooks = []
             hooks = self._hooks
         hooks.append(hook)
     ```
  3. **不改名**现有参数：`Agent.create()` 目前传的是 `tool_permission_manager=`（与 ABC 声明的 `permission_provider` 名不同，靠实现类 `**kwargs` 兼容）。本次重构保持现状，仅在 ABC docstring 中记录这一历史差异，避免牵动调用方
- **预期产出**：`broca/components/loop_engine.py` 更新
- **验收标准**：
  - [ ] `initialize()` 新增 4 个参数且**全部有默认值**
  - [ ] `add_hook()` 非抽象，可在 `initialize` 后追加
  - [ ] Phase 1 期间 `Agent.create()` 无需任何改动，全量测试仍通过

#### Task 1.5: 包化骨架（消除模块/包同名歧义）

- **目标**：把 `broca/loop_engine.py` 变成包，Phase 2/3 有地方写文件
- **步骤**：
  1. `mkdir -p broca/loop_engine && git mv broca/loop_engine.py broca/loop_engine/legacy.py`
  2. 新建 `broca/loop_engine/__init__.py`：
     ```python
     """Loop Engine 包入口。

     注意：``LoopEngine`` 在此是**具体实现类**（DefaultLoopEngine 的别名），
     供历史代码 ``from broca.loop_engine import LoopEngine`` 使用；
     ABC 请从 ``broca.components`` 或 ``broca.components.loop_engine`` 导入。
     """
     from broca.components.loop_engine import ExecutionResult, ExecutionStatus
     from broca.loop_engine.legacy import DefaultLoopEngine

     LoopEngine = DefaultLoopEngine   # 兼容别名（具体类）

     __all__ = ["DefaultLoopEngine", "LoopEngine", "ExecutionResult", "ExecutionStatus"]
     ```
  3. 新建空骨架：`broca/loop_engine/strategies/__init__.py`、`broca/loop_engine/hooks/__init__.py`
  4. 新建 `broca/tests/fixtures/llm_streaming/.gitkeep`（golden fixture 目录）
  5. 检查 `legacy.py` 内引用（均为 `from broca.components.loop_engine import ...` 绝对导入，无需改动）
- **预期产出**：包骨架 + `legacy.py`
- **验收标准**：
  - [ ] `broca/loop_engine.py` 文件已不存在
  - [ ] `python -c "from broca.loop_engine import DefaultLoopEngine, LoopEngine, ExecutionStatus, ExecutionResult"` 成功
  - [ ] `python -c "from broca.components.defaults import *"` 成功（`"broca.loop_engine:DefaultLoopEngine"` 字符串路径可解析）
  - [ ] `python -c "import broca.loop_engine as m; print(m.__file__)"` 输出 `.../broca/loop_engine/__init__.py`
  - [ ] `pytest broca/tests/ -q` 0 失败，总数 ≥751

---

> **并行约束**：Phase 2 独占 `broca/loop_engine/strategies/`，Phase 3 独占 `broca/loop_engine/hooks/` 与 `broca/loop_engine/compressor_context.py`；两阶段**不得**修改 `engine.py` / `__init__.py` / 对方目录 → 可真正并行，无 merge 冲突。

### Phase 2: 策略实现

**目标**：将现有 LLM 调用和工具执行逻辑封装为策略实现

**阶段验收标准**：
- [ ] `RetryLLMStrategy` 完整封装现有重试/限流/超时/空响应/流式逻辑
- [ ] `ParallelToolStrategy` 完整封装现有并行+permission 分区逻辑；`SerialToolStrategy` 提供串行备选
- [ ] 策略可独立单测（mock LLMClient / ToolExecutor）
- [ ] golden fixture 用例全绿
- [ ] 迁移后测试：0 失败，总数 ≥751

#### Task 2.1: 实现 RetryLLMStrategy

- **目标**：将 `_call_llm_with_retry`(L348-462) + `_send_llm_error`(L463-470) + `_call_llm_streaming`(L629-662) + `_process_content_chunk`(L570-590) + `_process_tool_call_chunk`(L591-614) + `_finalize_llm_response`(L615-628) 封装为策略
- **步骤**：
  1. 新建 `broca/loop_engine/strategies/retry_llm.py`（首行 `from __future__ import annotations`）
  2. 实现 `RetryLLMStrategy(LLMStrategy)`：
     ```python
     class RetryLLMStrategy(LLMStrategy):
         """默认 LLM 策略：重试 + 限流 + 超时 + 空响应 + 流式聚合。"""
         name = "retry_llm"

         def __init__(self):
             self._llm_client = None
             self._config = None
             self._consecutive_rate_limit_errors = 0

         async def initialize(self, llm_client, config):
             self._llm_client = llm_client
             self._config = config
             exec_cfg = getattr(config, "execution_config", None)
             self._max_errors = getattr(exec_cfg, "step_max_errors", 3)
             self._retry_delay = getattr(exec_cfg, "llm_retry_delay", 5)
             self._timeout = getattr(exec_cfg, "llm_timeout", 300)

         async def call(self, history, tools, *, on_chunk=None, on_error=None, should_abort=None):
             # 迁移 _call_llm_with_retry 的四类分支（行为与文案原样保留）：
             #   1) 限流 LLM_RATE_LIMIT → _consecutive_rate_limit_errors += 1，> max 则 raise
             #   2) 其他 LLMError → errors += 1，达到 max 则 raise
             #   3) asyncio.TimeoutError → errors += 1
             #   4) 空响应（aggregate 为空）→ empty_retries += 1（不计入 errors）
             ...

         def reset(self):
             self._consecutive_rate_limit_errors = 0
     ```
  3. **中止语义（Critical C4）**：每次重试迭代开始、每个 chunk 处理前检查
     ```python
     if should_abort and should_abort():
         return LLMCallResult(success=False, aborted=True, error_code="ABORTED")
     ```
     **不得**在 abort 后 `await asyncio.sleep(self._retry_delay)`
  4. **`CancelledError` 语义（有意变化，需在 PR 记录）**：legacy 中 `except asyncio.CancelledError: return None` → `execute_step` 在 `abort_event` 未置位时返回 `ERROR`；新设计**统一映射为 `aborted=True`**（视为中止，引擎返回 `ABORTED`）。理由：真实取消与用户 abort 对调用方而言应一致；若需区分，可在 `should_abort()` 之外保留 `cancelled` 标记（当前不做）
  5. **流式聚合（在策略内，engine 只广播）**：
     ```python
     content_chunks, tool_call_chunks, sent = [], [], set()
     message_id, index = generate_message_id(), 0
     async for chunk in self._llm_client.get_stream_response(provider, model, history, tools):
         if should_abort and should_abort():
             return LLMCallResult(success=False, aborted=True, error_code="ABORTED")
         if chunk["type"] in ("content", "reasoning_content"):
             content_chunks.append(chunk)
             if on_chunk:
                 await on_chunk({**chunk, "index": index, "message_id": message_id})
             index += 1
         elif chunk["type"] == "tool_call":
             tc = chunk["data"]
             tool_call_chunks.append(tc)
             if getattr(tc, "id", None) and tc.id not in sent:
                 if on_chunk:
                     await on_chunk({"type": "tool_call", "data": tc, "message_id": message_id})
                 sent.add(tc.id)
     message = self._llm_client.aggregate_message(content_chunks, tool_call_chunks)
     ```
  6. **token 统计（Major M1）**：`input_tokens = self._llm_client.input_tokens_used`、`output_tokens = self._llm_client.output_tokens_used` 写入 `LLMCallResult`；**不**在策略内调用 `agent_ref.on_llm_call_completed`（engine 负责）
  7. **Golden File Test（手工 fixture，不录制真实流量）**：
     - 在 `broca/tests/fixtures/llm_streaming/` 手工构造 **20 条** chunk 序列 JSON，覆盖矩阵：
       content-only ×3、reasoning-only ×3、tool_call-only ×3、content+reasoning ×3、content+tool_call ×3、多 tool_call 交错 ×2、空流 ×2、tool_call 无 id（异常流）×1
     - 新建 `broca/tests/test_llm_strategy_golden.py`：对每个 fixture 断言
       `RetryLLMStrategy` 聚合出的 `LLMCallResult.message.__dict__` 与 fixture 中 `expected_message` **逐字段相等**（不是逐字节）
     - **fixture schema（写死，执行者不得自行发明）**：
       ```json
       {
         "name": "content_then_tool_call",
         "chunks": [
           {"type": "content", "data": "hello"},
           {"type": "tool_call", "data": {"id": "call_1", "type": "function",
                                          "function": {"name": "read_file", "arguments": "{\"path\": \"a.py\"}"}}}
         ],
         "expected_message": {"content": "hello", "tool_calls": [{"id": "call_1", "type": "function",
                                "function": {"name": "read_file", "arguments": "{\"path\": \"a.py\"}"}}]},
         "expected_on_chunk_events": [{"type": "content", "data": "hello", "index": 0}, {"type": "tool_call", "id": "call_1"}]
       }
       ```
       - 测试内用 `ToolCall(**d)` / `ChatCompletionMessageToolCall(**d)` 把 dict 还原为对象后再喂给策略
       - 断言时只比较**可序列化字段**（`content` / `reasoning_content` / `tool_calls[*].id` / `.function.name` / `.function.arguments`），不比较对象身份
       - `expected_on_chunk_events` 忽略 `message_id`（每次运行随机）
- **预期产出**：`retry_llm.py`（~180 行）+ 20 个 fixture + `test_llm_strategy_golden.py`
- **验收标准**：
  - [ ] 重试行为与现有 `_call_llm_with_retry` 一致：限流 / 超时 / 空响应 / 其他 LLMError 四条路径均有用例
  - [ ] `should_abort() == True` 时立即返回 `aborted=True`，**不 sleep、不重试**（用例：abort 后 `call()` 耗时 < 0.1s）
  - [ ] `on_error` 在 6 个提示点被调用（限流 warning / 超时 warning / 空响应 warning / 空响应放弃 error / 重试 error / 失败 error），`severity` 正确
  - [ ] `on_chunk` 只发出 3 种 type；`tool_call` 每个 id 只发一次
  - [ ] 20 条 golden fixture 全绿，且 `LLMCallResult.message` 与期望逐字段相等
  - [ ] 策略不 import `communicator` / `session_manager` / `context` / `agent_ref`

#### Task 2.2: 实现 ParallelToolStrategy / SerialToolStrategy

- **目标**：将 `_process_tool_calls`(L721) + `_process_tool_calls_parallel`(L772) 的**执行部分**封装（结果处理留在 engine）
- **步骤**：
  1. 新建 `broca/loop_engine/strategies/parallel_tool.py`：
     ```python
     class ParallelToolStrategy(ToolExecutionStrategy):
         name = "parallel_tool"
         async def initialize(self, tool_executor, config):
             self._tool_executor = tool_executor
             exec_cfg = getattr(config, "execution_config", None)
             self._max_parallel = self._resolve_max_parallel(config, exec_cfg)
         async def execute(self, tool_calls, context, tool_mapping, *, allowed_tools=None, should_abort=None):
             # 1) 分区：tool_executor.get_permission(name) == "ask" → 串行
             # 2) 并行执行 parallel-safe（asyncio.Semaphore(max_parallel)）
             # 3) 串行执行 ask-permission 工具（独立 task）
             # 4) gather(return_exceptions=True) + None 兜底为 ToolResult(ERROR, "Tool execution failed ...")
             # 5) 返回按原始索引排列的 results（不做 DB/广播）
     ```
  2. 新建 `broca/loop_engine/strategies/serial_tool.py`：`name = "serial_tool"`，for 循环执行（含 `should_abort` 检查，abort 时该条返回 `ToolResult(ERROR, "Execution aborted")`）
  3. **abort 语义**：所有 abort 判断改为 `should_abort()`（`ToolCallContext` 无 `abort_event`）
  4. 串行/并行的选择（`mode == "serial" or len(tool_calls) <= 1`）保留在 `ParallelToolStrategy.execute` 内部（与现有行为一致）
- **预期产出**：`parallel_tool.py`（~110 行）+ `serial_tool.py`（~35 行）
- **验收标准**：
  - [ ] permission 分区逻辑与现有一致（`ask` 工具串行、其余并行）
  - [ ] 结果列表顺序与输入 tool_calls 顺序一致
  - [ ] `should_abort() == True` 时剩余工具返回 `ToolResult(status=ERROR, content="Execution aborted")`，不抛异常
  - [ ] 策略**不**调用 `session_manager` / `communicator` / `context`（不写 DB、不广播）
  - [ ] 单测：mock ToolExecutor，验证并发度上限、串行分区、顺序、异常兜底

#### Task 2.3: 策略工厂 + 配置优先级

- **目标**：根据配置选择策略实例（**配置优先级显式化**）
- **步骤**：
  1. 新建 `broca/loop_engine/strategies/factory.py`：
     ```python
     def create_llm_strategy(config) -> LLMStrategy:
         return RetryLLMStrategy()          # 预留扩展点（registry 注册留 TODO）

     def create_tool_strategy(config) -> ToolExecutionStrategy:
         """优先级：显式参数 > AgentConfig 属性 > execution_config > 默认值。"""
         exec_cfg = getattr(config, "execution_config", None)
         mode = (
             getattr(config, "tool_execution_mode", None)       # agent 级覆盖（agent_configs.py:56）
             or getattr(exec_cfg, "tool_execution_mode", None)  # 全局 execution 配置
             or "parallel"
         )
         return SerialToolStrategy() if mode == "serial" else ParallelToolStrategy()
     ```
  2. `max_parallel_tools` / `step_max_errors` / `llm_retry_delay` / `llm_timeout` 的读取同样遵循该优先级（在策略 `initialize` 内实现）
- **预期产出**：`strategies/factory.py`（~40 行）
- **验收标准**：
  - [ ] `AgentConfig(tool_execution_mode="serial")` → `SerialToolStrategy`（agent 级覆盖生效）
  - [ ] `execution_config.tool_execution_mode = "serial"` 且 agent 级为 `None` → `SerialToolStrategy`
  - [ ] 两者均为 `None` → `ParallelToolStrategy`
  - [ ] 优先级注释与实现一致（代码内有明确注释）

---

### Phase 3: Hook 实现

**目标**：将横切关注点抽为独立 Hook 类

**阶段验收标准**：
- [ ] 4 个 Hook 类实现完成，**每个都有唯一 `name` 类属性**
- [ ] 每个 Hook 可独立单测
- [ ] 迁移后测试：0 失败，总数 ≥751

#### Task 3.1: SnapshotHook

- **目标**：快照 step/turn 捕获 + patch 计算 + turn-level diff
- **步骤**：
  1. 新建 `broca/loop_engine/hooks/snapshot_hook.py`
  2. 实现 `SnapshotHook(LoopHook)`，`name = "snapshot"`：
     - `__init__(snapshot_manager, workspace, config)`；`self._enabled = getattr(config, "enable_snapshot_tracking", True) and snapshot_manager is not None`（`snapshot_manager` 为 `None` 时在 `on_turn_start` 内 lazy 初始化，与原 `_initialize_snapshot_tracking` 一致）
     - `on_turn_start`：`_enabled` 为真时 lazy 初始化 SnapshotManager，并清空 `_turn_first_hash` / `_turn_last_hash`
     - `on_step_start`：`ctx.has_write_ops` 为真 → `acquire_lock` + `track` → 写 `ctx.step_start_snapshot`、`_turn_first_hash`（首次）
     - `on_step_end`：`track` + `calculate_patch` → 写 `ctx.step_end_snapshot` / `ctx.step_patch` / `_turn_last_hash`；**`finally` 中释放锁**
     - `on_turn_end`：迁移 `_compute_turn_level_diff`（含"异常终止时补结束快照"分支）→ 写 `ctx.result.data["changed_files"]`
     - `reset()`：迁移 `_clear_turn_snapshots`，清空全部 hash 状态与锁标记
  3. 迁移 `_acquire_step_lock` / `_release_step_lock` / `_capture_step_start_snapshot` / `_compute_step_end_patch` / `_capture_step_start` / `_capture_step_end`
- **预期产出**：`hooks/snapshot_hook.py`（~120 行）
- **验收标准**：
  - [ ] `enable_snapshot_tracking=False` 时**所有方法 no-op**（不调用任何 SnapshotManager 方法）
  - [ ] `snapshot_manager=None` 时同样 no-op，且不抛异常
  - [ ] `has_write_ops=False` 时 `on_step_start` / `on_step_end` 直接 return
  - [ ] 锁在 `on_step_start` 获取、`on_step_end` 释放（**patch 计算抛异常也释放**——`try/finally`）
  - [ ] `on_turn_end` 把 diff 写入 `ctx.result.data["changed_files"]`（无变更时写 `None`）
  - [ ] `reset()` 后连续两次 turn 互不影响（第二次 turn 的 `first_hash` 不为上一 turn 残留）
  - [ ] 单测：mock SnapshotManager，验证调用序列、lock 获取/释放、no-op 开关

#### Task 3.2: CommunicatorHook

- **目标**：前端通信广播（turn/step 事件 + 错误通知），**turn_start 的唯一广播来源**
- **步骤**：
  1. 新建 `broca/loop_engine/hooks/communicator_hook.py`，`name = "communicator"`
  2. 实现 `CommunicatorHook(LoopHook)`，`__init__(communicator, config, session_id)`；`config.interactive=False` 时所有方法 no-op
     - `on_turn_start`：`send_turn_start(turn_id, turn_description, subscription)` + 迁移 `_broadcast_user_message`（`MessageProtocol.create_user_message`，含 `files` / `raw_input`；`from_agent` 时跳过）
     - `on_step_start`：广播 `MessageProtocol.create_step_start`
     - `on_step_end`：广播 `MessageProtocol.create_step_end`（含 `ctx.step_patch`）
     - `on_turn_finalized`：`send_turn_end(turn_id, result=ctx.result.status.value, message_id=ctx.data["turn_end_message_id"], changed_files=ctx.result.data.get("changed_files"))`；`status != COMPLETED` 时再发 `send_error`（迁移 `_send_turn_error_notification` 的 error_info 结构）
     - `on_turn_end`：**不实现**（广播统一放 `on_turn_finalized`，保证在 `save_turn_end` 之后）
  3. LLM streaming chunk 广播**不在**本 Hook（由 engine 的 `on_chunk` handler 处理）
- **预期产出**：`hooks/communicator_hook.py`（~120 行）
- **验收标准**：
  - [ ] `config.interactive=False` 时所有方法 no-op
  - [ ] 一次 turn **只广播 1 次** `turn_start`（`send_turn_start` 调用次数 == 1；配合 Task 4.1a 移除 `_start_turn` 中的广播）
  - [ ] `on_turn_finalized` 广播的 `changed_files` 取自 `ctx.result.data`（由 SnapshotHook 写入）
  - [ ] `on_step_end` 广播包含 `ctx.step_patch`
  - [ ] 单测：mock Communicator，验证各事件发送参数与调用次数

#### Task 3.3: CompressionMemoryHook

- **目标**：post-step 的上下文压缩 + 记忆提取
- **步骤**：
  1. 新建 `broca/loop_engine/compressor_context.py`：迁移 `_build_compressor_context`(L684-719) 为**独立工厂函数**
     ```python
     def build_compressor_context(*, agent_ref, config, communicator, session_manager, agent_id, session_id) -> "CompressorContext":
         """返回满足 CompressorContext 协议的轻量适配器（逻辑原样迁移）。"""
     ```
     迁移时保留 5 个属性：`last_context_length` / `compact_config` / `provider` / `model` / `workspace`
  2. 新建 `broca/loop_engine/hooks/compression_hook.py`，`name = "compression"`
  3. 实现 `CompressionMemoryHook(LoopHook)`：
     - `__init__(context_compressor, memory_manager, config, context, compressor_ctx_builder)`（`compressor_ctx_builder` 为**无参 callable**，通常传 `functools.partial(build_compressor_context, ...)`）
     - `on_post_step`：迁移 `_trigger_post_step_hooks`（压缩 `await check_and_compress`；记忆 `increment_step` + `create_task(check_and_extract)` + `done_callback`）
- **预期产出**：`compressor_context.py`（~45 行）+ `hooks/compression_hook.py`（~65 行）
- **验收标准**：
  - [ ] 压缩调用 `check_and_compress(context=..., compressor_context=compressor_ctx_builder())`
  - [ ] 记忆提取是 fire-and-forget（`asyncio.create_task` + `done_callback` 吞异常）
  - [ ] `enable_context_compression=False` 或 compressor 为 `None` → 跳过压缩
  - [ ] `persistent_memory_config.auto_extract=False` 或 memory_manager 为 `None` → 跳过记忆
  - [ ] `build_compressor_context()` 返回对象具备 5 个协议属性（单测断言）
  - [ ] 单测：mock compressor + memory_manager，验证调用条件与参数

#### Task 3.4: DeadLoopHook

- **目标**：step-end 时的死循环检测
- **步骤**：
  1. 新建 `broca/loop_engine/hooks/dead_loop_hook.py`，`name = "dead_loop"`
  2. 实现 `DeadLoopHook(LoopHook)`：
     - `__init__(window=3)`
     - `on_step_end`：`self._signatures.extend(_extract_tool_call_signatures(ctx.tool_calls))`；若长度 ≥ `window` 且**签名列表最后 `window` 个元素全部相同** → `ctx.status = ExecutionStatus.DEAD_LOOP` 并 log warning
     - `reset()`：清空 `self._signatures`
  3. 迁移 `_extract_tool_call_signatures`(L879) / `_normalize_arguments`(L902) 为 `staticmethod`
- **预期产出**：`hooks/dead_loop_hook.py`（~70 行）
- **验收标准**：
  - [ ] **语义明确**：判定条件是「扁平化签名列表最后 `window` 个元素全部相同」（一个 step 含 2 个 tool_call 贡献 2 个签名，故"window 次"= 签名数，不是 step 数）
  - [ ] 3 次相同 → `DEAD_LOOP`；2 次相同 → 不触发；`reset()` 后重新计数
  - [ ] 签名归一化与现有 `_normalize_arguments` 一致（JSON sort_keys）
  - [ ] 单测覆盖上述 4 条

#### Task 3.5: Hook 构建器

- **目标**：定义默认 Hook 集和子 Agent 精简集
- **步骤**：
  1. 新建 `broca/loop_engine/hooks/factory.py`：
     ```python
     def build_default_hooks(
         config, *, snapshot_manager=None, communicator=None,
         context_compressor=None, memory_manager=None,
         context=None, session_id="", compressor_ctx_builder=None,
     ) -> list[LoopHook]:
         """主 Agent 完整 Hook 集。

         顺序固定：快照 → 通信 → 死循环 → 压缩。
         （DeadLoop 只在 on_step_end 生效、Compression 只在 on_post_step 生效，顺序无耦合；
           快照必须先于通信，因为 CommunicatorHook 要读 SnapshotHook 写的 patch。）
         """
         window = getattr(getattr(config, "execution_config", None), "dead_loop_window", 3)
         return [
             SnapshotHook(snapshot_manager, config.workspace, config),
             CommunicatorHook(communicator, config, session_id),
             DeadLoopHook(window=window),
             CompressionMemoryHook(context_compressor, memory_manager, config, context, compressor_ctx_builder),
         ]

     def build_subagent_hooks(config, *, context_compressor=None, memory_manager=None,
                              context=None, compressor_ctx_builder=None) -> list[LoopHook]:
         """子 Agent 精简集：无快照、无通信。"""
         window = getattr(getattr(config, "execution_config", None), "dead_loop_window", 3)
         hooks = [DeadLoopHook(window=window)]
         if getattr(config, "enable_context_compression", False):
             hooks.append(CompressionMemoryHook(context_compressor, memory_manager, config, context, compressor_ctx_builder))
         return hooks
     ```
  2. **None 语义写死**：依赖为 `None` 时对应 Hook **仍被创建**，但其所有生命周期方法 no-op（由各 Hook 的 `_enabled` 判定），**不采用**"跳过创建"
- **预期产出**：`hooks/factory.py`（~70 行）
- **验收标准**：
  - [ ] `build_default_hooks` 返回 4 个 Hook，顺序严格为 `[snapshot, communicator, dead_loop, compression]`
  - [ ] `build_subagent_hooks` 返回 1~2 个 Hook，且**不含** SnapshotHook / CommunicatorHook
  - [ ] 所有参数为 `None` 时仍能成功创建 4 个 Hook 且不抛异常（no-op 语义）
  - [ ] 单测断言每个 Hook 的 `name` 唯一（`{"snapshot","communicator","dead_loop","compression"}`）

---

### Phase 4: 引擎重构（核心编排器）

**目标**：将 `DefaultLoopEngine` 重写为使用策略 + Hook 的纯编排器

**阶段验收标准**：
- [ ] `engine.py` 总行数 ≤ 320
- [ ] 引擎不 import `GitSnapshotManager` / `ContextCompressor` / `MemoryManager`
- [ ] 引擎不内联 LLM 重试逻辑、不内联工具并行/分区逻辑
- [ ] 引擎保留 `save_turn_end` / `process_tool_call_result` / `_save_response`（DB 写入职责）
- [ ] 迁移后测试：**0 失败，总数 ≥751**
- [ ] e2e：`pytest broca/tests/test_e2e_scenarios.py -k websocket` 通过

#### Task 4.1a: 创建新引擎骨架（策略接入 + DB 职责）

- **目标**：创建 `broca/loop_engine/engine.py`，接入策略，暂不接入 Hook
- **步骤**：
  1. 新建 `engine.py`（首行 `from __future__ import annotations`），`DefaultLoopEngine(LoopEngine)`：
     ```python
     async def initialize(self, **kwargs) -> None:   # type: ignore[override]
         """ABC 声明完整签名；实现类用 **kwargs 接收（与 legacy 一致）。
         llm_strategy / tool_strategy 为 None 时回退内置默认（Phase 2/3 完成后可用）。"""
         self._llm_strategy = kwargs.get("llm_strategy") or create_llm_strategy(kwargs["config"])
         self._tool_strategy = kwargs.get("tool_strategy") or create_tool_strategy(kwargs["config"])
         self._hooks = list(kwargs.get("hooks") or [])
         await self._llm_strategy.initialize(llm_client=kwargs["llm_client"], config=kwargs["config"])
         await self._tool_strategy.initialize(tool_executor=kwargs["tool_executor"], config=kwargs["config"])
         # ... 其余依赖注入（agent_ref / context / tool_mapping / communicator / session_manager / config）
     ```
  2. `_setup_turn(message, from_agent) -> TurnContext | None`（迁移 `_setup_execution_context`）：
     ```python
     self.abort_event.clear()                 # 对齐 legacy execute() L1101
     self._reset_turn_scoped_state()          # ← 每 turn 状态重置（M12）
     # parse → _ensure_session → _start_turn → _save_user_message → context.add_message
     ```
     `_reset_turn_scoped_state()`：遍历 `self._hooks` 调 `hook.reset()` + `self._llm_strategy.reset()`
  3. `_start_turn(...)`（迁移 `_start_new_turn`）：**只**做 `_ensure_session` + `session_manager.start_turn` + 写 `self.turn_id` / `agent_ref.turn_id`；**删除其中的 `send_turn_start` 广播**（M13）
  4. `_execute_step(turn_ctx) -> StepContext`：
     ```python
     step_ctx = StepContext(step_id=self._generate_step_id(), turn_id=self.turn_id,
                            agent_id=self.agent_id, session_id=self.session_id)
     self.step_id = step_ctx.step_id

     llm = await self._llm_strategy.call(
         history=self.context.history,
         tools=self._get_tools_list(),
         on_chunk=self._make_chunk_handler(),
         on_error=self._make_error_handler(),
         should_abort=lambda: self.abort_event.is_set(),
     )
     if llm.aborted or self.abort_event.is_set():
         step_ctx.status = ExecutionStatus.ABORTED
         return step_ctx
     if not llm.success or llm.message is None:
         step_ctx.status = ExecutionStatus.ERROR
         return step_ctx

     # M1：token 统计上抛（策略保持纯净）。
     # 注意：仅在 success=True 且 message 非空时上报一次——legacy 是每次 attempt 都上报
     # （含空响应 attempt），此处有意收紧；ERROR/ABORTED 早退路径不上报（见方法表 #23）
     await self.agent_ref.on_llm_call_completed(llm.input_tokens, llm.output_tokens)

     step_ctx.response = llm.message
     step_ctx.tool_calls = list(llm.message.tool_calls or [])
     step_ctx.llm_input_tokens, step_ctx.llm_output_tokens = llm.input_tokens, llm.output_tokens
     # M2：快照开关必须先于 on_step_start dispatch
     step_ctx.has_write_ops = self._check_write_ops(step_ctx.tool_calls)
     step_ctx.status = ExecutionStatus.RUNNING
     ```
  5. `_process_tool_results(tool_calls, results) -> None`（批量封装 `process_tool_call_result`，**Critical C2**）：
     ```python
     for i, tc in enumerate(tool_calls):
         if not await self.process_tool_call_result(tc, results[i]):
             raise Exception("Tool call result processing failed")
     ```
     `process_tool_call_result()` 保留**公共方法名与签名**（广播 + `save_tool_call` + `context.add_message` + `extra_context_messages`），以便 `test_image_tool.py:550` 的 `LoopEngine.process_tool_call_result(engine, ...)` 继续可用
  6. `_finalize_turn(turn_ctx, result) -> bool`（迁移 `process_turn_end`，**Critical C3**）：
     ```python
     if result.status == ExecutionStatus.ABORTED:
         await self._truncate_last_assistant_message_with_tool_calls()
     turn_ctx.result = result
     turn_ctx.data["turn_end_message"] = self._get_turn_end_message(result)
     turn_ctx.data["turn_end_message_id"] = f"msg_{uuid.uuid4().hex[:16]}"
     await self._dispatch("on_turn_end", turn_ctx)          # SnapshotHook 写 changed_files
     saved = await self.session_manager.save_turn_end(     # ← 留 engine（Hook 无 session_manager）
         turn_id=self.turn_id, agent_id=self.agent_id,
         message=turn_ctx.data["turn_end_message"],
         status="completed" if result.status == ExecutionStatus.COMPLETED else "error",
         message_id=turn_ctx.data["turn_end_message_id"],
         changed_files=result.data.get("changed_files"),
     )
     await self._dispatch("on_turn_finalized", turn_ctx)    # CommunicatorHook 广播
     return saved
     ```
  7. `execute()` 骨架：`_setup_turn` → `dispatch("on_turn_start")` → `_execute_round` → `_finalize_turn`；保留 BrocaError / ValidationError / CancelledError / Exception 四类异常包装与 `_send_execution_error` / `_make_error_result`：
     ```python
     if not message:
         return ExecutionResult(status=ExecutionStatus.SKIPPED)

     turn_ctx, result = None, None
     try:
         turn_ctx = await self._setup_turn(message, from_agent)
         if turn_ctx is None:                      # 迁移 legacy 的 SESSION_ERROR 分支
             await self._send_execution_error(Exception("执行上下文设置失败"), "SESSION_ERROR")
             return ExecutionResult(status=ExecutionStatus.ERROR,
                                    message="Error setting up execution context")
         await self._dispatch("on_turn_start", turn_ctx)
         result = await self._execute_round(turn_ctx, max_steps)
     except ValidationError as e:
         logger.error(f"ValidationError in execute: {e}")
         await self._send_execution_error(e, "VALIDATION_ERROR")
         result = self._make_error_result(ExecutionStatus.ERROR, e)
     except asyncio.CancelledError:
         result = ExecutionResult(status=ExecutionStatus.ABORTED,
                                  message="Execution cancelled by user")
     except BrocaError as e:
         await self._send_execution_error(e, "BROCA_ERROR")
         result = self._make_error_result(ExecutionStatus.ERROR, e)
     except Exception as e:
         await self._send_execution_error(e, "UNKNOWN_ERROR")
         result = self._make_error_result(ExecutionStatus.ERROR, e)

     if turn_ctx is not None:
         if not await self._finalize_turn(turn_ctx, result):
             logger.warning("Turn end processing failed")
     else:
         # setup 阶段就抛异常（如 ValidationError）→ 无 turn_id。
         # legacy 会写一条 turn_id=None 的 turn_end 记录；本次有意收紧：不写脏记录，仅告警。
         logger.warning("Turn setup failed; skip turn_end persistence")
     return result
     ```
  8. 保留 `_build_round_result`（同步 `def`）/ `_save_response`（返回 `bool`）/ `_get_tools_list` / `_build_tool_context` / `_ensure_session` / `_save_user_message` / `abort` / `reset`
  9. 本步骤 `_dispatch` 先留空实现（`async def _dispatch(self, method, ctx): pass`），只验证策略链路与 DB 职责
- **预期产出**：`broca/loop_engine/engine.py`（≤320 行）
- **验收标准**：
  - [ ] 策略链路：`llm_strategy.call()` → `tool_strategy.execute()` → `_process_tool_results()` 正确执行
  - [ ] `agent_ref.on_llm_call_completed(input_tokens, output_tokens)` 在每次成功 LLM 调用后被调用一次（单测断言）
  - [ ] `step_ctx.has_write_ops` 在 `on_step_start` 之前已由 `_check_write_ops()` 填好（写操作工具 → True）
  - [ ] `process_tool_call_result()` 仍在 engine 上且可独立调用（`test_image_tool.py` 通过）
  - [ ] `save_turn_end` 被调用一次（单测 mock session_manager 断言）
  - [ ] `_start_turn()` 内**没有** `send_turn_start` 调用（grep 断言）
  - [ ] 连续两次 `execute()` 后死循环签名历史与限流计数均已重置（M12）
  - [ ] `engine.py` 中不存在重试循环 / semaphore / permission 分区逻辑
  - [ ] 本步骤验证方式：新增 `broca/tests/test_engine_orchestration.py`，**直接** `from broca.loop_engine.engine import DefaultLoopEngine` 实例化验证（此时包 `__init__` 仍指向 legacy，故全量旧测试不受影响）

#### Task 4.1b: 接入 Hook dispatch

- **目标**：实现 `_dispatch` 与全部 6 个生命周期调用点
- **步骤**：
  1. 实现 `_dispatch`：
     ```python
     async def _dispatch(self, method: str, ctx) -> None:
         """按注册顺序调用所有 Hook 的生命周期方法；Hook 异常 catch + log，不中断。"""
         for hook in self._hooks:
             try:
                 await getattr(hook, method)(ctx)
             except Exception as e:
                 logger.warning(f"Hook {hook.name}.{method} failed: {e}")
     ```
  2. 插入 6 个调用点（顺序见「接口契约速查」）：
     `on_turn_start`（`_setup_turn` 后）→ `on_step_start`（`has_write_ops` 计算后、保存响应前）→ `on_step_end`（工具结果处理完成后）→ `on_post_step`（step 结束）→ `on_turn_end`（`_finalize_turn` 内、`save_turn_end` 前）→ `on_turn_finalized`（`save_turn_end` 后）
  3. **DEAD_LOOP 状态传播（Major M3）**——`_execute_round` 显式读取 `step_ctx.status`：
     ```python
     async def _execute_round(self, turn_ctx, max_steps) -> ExecutionResult:
         steps = 0
         while True:
             if self.abort_event.is_set():
                 return self._build_round_result(ExecutionStatus.ABORTED, steps)   # sync，无 await
             try:
                 step_ctx = await self._execute_step(turn_ctx)
                 steps += 1
                 if step_ctx.status in (
                     ExecutionStatus.COMPLETED, ExecutionStatus.ABORTED,
                     ExecutionStatus.ERROR, ExecutionStatus.DEAD_LOOP,
                 ):
                     return self._build_round_result(step_ctx.status, steps)
                 if max_steps is not None and steps >= max_steps:
                     return self._build_round_result(ExecutionStatus.LIMIT_EXCEEDED, steps)
             # ── 必须保留 legacy 的内层异常处理（Round2 N4）──
             except BrocaError as e:
                 # 用 e.to_dict() 上报，保住具体 code（如 LLM_RATE_LIMIT），
                 # 不要让它冒泡到 execute() 的 except BrocaError 而退化为 BROCA_ERROR
                 if self.config.interactive:
                     await self.communicator.send_error(e.to_dict(), subscription=self.session_id)
                 return ExecutionResult(status=ExecutionStatus.ERROR, message=e.to_user_message())
             except asyncio.CancelledError:
                 return ExecutionResult(status=ExecutionStatus.ABORTED, message="Round aborted by user")
     ```
     > `_build_round_result` 统一为**同步 `def`**（Round2 N13），全文调用不带 `await`。
  4. `try/finally` 保证 `on_step_end` 一定执行（SnapshotHook 的锁释放依赖它）：
     ```python
     await self._dispatch("on_step_start", step_ctx)
     try:
         # _save_response 返回 bool；DB 写入失败必须中止 step（Round2 N3）
         if not await self._save_response(step_ctx.response):
             step_ctx.status = ExecutionStatus.ERROR
             return step_ctx                      # finally 仍会执行 on_step_end（释放锁）
         if step_ctx.tool_calls:
             results = await self._tool_strategy.execute(
                 step_ctx.tool_calls, self._build_tool_context(), self.tool_mapping,
                 allowed_tools=self.allowed_tools, should_abort=lambda: self.abort_event.is_set(),
             )
             step_ctx.tool_results = results
             await self._process_tool_results(step_ctx.tool_calls, results)
         else:
             step_ctx.status = ExecutionStatus.COMPLETED
     finally:
         await self._dispatch("on_step_end", step_ctx)
     await self._dispatch("on_post_step", step_ctx)
     ```
  5. `_make_chunk_handler()`：把策略发来的 3 类 chunk 转成 communicator 调用（`send_agent_response` / `send_tool_call`），`interactive=False` 时 no-op，异常 catch + warning
  6. `_make_error_handler()`：`on_error(message, code, severity)` → `communicator.send_error({"message":..., "code":..., "severity":...}, subscription=self.session_id)`（`interactive=False` 时 no-op）。
     **修正**：删除"abort 在 LLM streaming 期间由 llm_client 的 cancel 机制检查"这一错误描述；实际机制是策略内 `should_abort()` 检查
  7. `reset()`：`abort_event.clear()` + `turn_id=None` + 清 session 权限覆盖 + 遍历 `hook.reset()` + `llm_strategy.reset()`
- **预期产出**：完整 `engine.py`（≤320 行）
- **验收标准**：
  - [ ] `_dispatch()` 严格按 `self._hooks` 列表顺序 await
  - [ ] 6 个生命周期调用点位置与「接口契约速查」一致（顺序错乱时 `changed_files` 为空 → 有用例覆盖）
  - [ ] Hook 异常被 catch + log，不中断核心流程（单测：抛异常的 Hook）
  - [ ] `_process_tool_results` 抛异常时 `on_step_end` 仍被调用（SnapshotHook 锁不泄漏）
  - [ ] `_save_response()` 返回 `False` 时 `step_ctx.status = ERROR`，**不执行工具**，且 `on_step_end` 仍被调用（Round2 N3）
  - [ ] `_execute_round` 捕获 `BrocaError` 并用 `e.to_dict()` 上报：限流场景前端 `error.code == "LLM_RATE_LIMIT"`（**不是** `BROCA_ERROR`）（Round2 N4）
  - [ ] `DeadLoopHook` 设 `ctx.status = DEAD_LOOP` 后，`_execute_round` 返回 `ExecutionResult(status=DEAD_LOOP)`
  - [ ] `reset()` 调用所有 Hook 的 `reset()` + `llm_strategy.reset()`
  - [ ] `on_chunk` / `on_error` handler 只做广播（`interactive=False` 时零 communicator 调用）
  - [ ] 注册 4 个默认 Hook 后，`test_e2e_scenarios.py` 通过

#### Task 4.1c: 切换（`Agent.create()` + 包入口）（**唯一改动归属**）

- **目标**：让 `Agent.create()` 创建并注入策略 + Hook，同时把包入口切到新引擎
- **⚠️ 前置约束**：`Agent.create()` 与 `broca/loop_engine/__init__.py` **必须在同一步骤内一起改**。若只改 `agent.py`，`registry.get(LoopEngine)` 仍会解析到 `legacy.DefaultLoopEngine`，其 `_do_initialize(**kwargs)` 不认 `llm_strategy` / `tool_strategy` / `hooks` → 直接 `TypeError`
- **步骤**：
  1. 在 `broca/agent.py` 的 `Agent.create()` 中（第 5 步 execution engine 之前）：
     ```python
     import functools
     from broca.loop_engine.hooks.factory import build_default_hooks
     from broca.loop_engine.compressor_context import build_compressor_context
     from broca.loop_engine.strategies.factory import create_llm_strategy, create_tool_strategy

     agent_ref = AgentReferenceAdapter(agent)
     llm_strategy = create_llm_strategy(config)
     tool_strategy = create_tool_strategy(config)
     hooks = build_default_hooks(
         config,
         snapshot_manager=None,      # SnapshotHook 内部 lazy 初始化（受 enable_snapshot_tracking 控制）
         communicator=agent.communicator,
         context_compressor=context_compressor,
         memory_manager=memory_manager,
         context=agent.context,
         session_id=session_manager.session_id,
         compressor_ctx_builder=functools.partial(
             build_compressor_context,
             agent_ref=agent_ref,
             config=config,
             communicator=agent.communicator,
             session_manager=session_manager,
             agent_id=agent.agent_id,
             session_id=session_manager.session_id,
         ),
     )

     await agent.execution_engine.initialize(
         agent_ref=agent_ref, llm_client=llm_client, context=agent.context,
         tool_mapping=agent.tool_mapping, config=config,
         communicator=agent.communicator, session_manager=session_manager,
         tool_executor=tool_executor, context_compressor=context_compressor,
         memory_manager=memory_manager, tool_permission_manager=agent.permission_provider,
         llm_strategy=llm_strategy, tool_strategy=tool_strategy, hooks=hooks,
     )
     ```
  2. 同步更新 `broca/loop_engine/__init__.py`，把 `from broca.loop_engine.legacy import DefaultLoopEngine` 改为 `from broca.loop_engine.engine import DefaultLoopEngine`（其余不变）
  3. **不修改** `broca/components/defaults.py`（字符串路径 `"broca.loop_engine:DefaultLoopEngine"` 会随 `__init__` 自动指向新引擎）
  4. `compressor_ctx_builder` 使用 `functools.partial(build_compressor_context, ...)`，**不依赖 engine 实例**（`_build_compressor_context` 原本是 engine 的私有方法，已迁至 `compressor_context.py`）
  5. **同步修复 `/compact` 命令调用方（Round2 N1 — Critical）**：`broca/commands/builtin/compact/__init__.py:63` 的
     ```python
     cc_ctx = execution_engine._build_compressor_context()      # ← 方法已删除，会 AttributeError
     ```
     改为：
     ```python
     from broca.loop_engine.compressor_context import build_compressor_context

     cc_ctx = build_compressor_context(
         agent_ref=agent,                       # 该命令内已有 agent 对象
         config=agent.config,
         communicator=agent.communicator,
         session_manager=execution_engine.session_manager,
         agent_id=agent.agent_id,
         session_id=execution_engine.session_id,
     )
     ```
  6. 顺手更新 `broca/components/protocols.py:62` 的 docstring：`_build_compressor_context()` → `compressor_context.build_compressor_context()`
  7. **全仓 grep 私有方法名**（`_build_compressor_context` / `check_step_has_write_operations` / `_setup_execution_context` / `process_tool_call_result`），把每个外部引用登记到 PR 描述并逐一处理（防 Round2 N1 同类问题）
- **预期产出**：`broca/agent.py`、`broca/loop_engine/__init__.py`、`broca/commands/builtin/compact/__init__.py`、`broca/components/protocols.py`（仅 docstring）更新
- **验收标准**：
  - [ ] `Agent.create()` 创建并注入 2 个策略 + 4 个 Hook
  - [ ] `compressor_ctx_builder()` 可无参调用并返回满足 `CompressorContext` 协议的对象
  - [ ] `broca.loop_engine.DefaultLoopEngine is broca.loop_engine.engine.DefaultLoopEngine`（包入口已切换）
  - [ ] **`/compact` 命令可执行**：`grep -rn "_build_compressor_context" broca/ --include=*.py` 仅命中 `broca/loop_engine/legacy.py`（Phase 5 删除）与注释；命令层已改调 `build_compressor_context(...)`（Round2 N1）
  - [ ] 新增 `broca/tests/test_compact_command.py`：mock `ContextCompressor`，执行 `/compact` 断言 `check_and_compress(force=True)` 被调用且 `compressor_context` 非空（该路径此前**零覆盖**）
  - [ ] `broca/components/protocols.py:62` docstring 已改名（不再提及 `_build_compressor_context()`）
  - [ ] 切换后测试：失败集合 ⊆ Task 4.3 迁移清单（出现清单外失败即回退排查）

**Task 4.1 总体验收标准**（4.1a + 4.1b + 4.1c 全部完成后；完整判据见 4.2/4.3）：
- [ ] `engine.py` 总行数 ≤ 320
- [ ] `engine.py` 不 import `GitSnapshotManager` / `ContextCompressor` / `MemoryManager`
- [ ] 引擎通过 `self._llm_strategy.call(...)` 调用 LLM、通过 `self._tool_strategy.execute(...)` 执行工具
- [ ] 引擎保留 `save_turn_end` / `process_tool_call_result` / `_save_response`（DB 写入）
- [ ] `on_chunk` / `on_error` handler 只做广播
- [ ] 切换后失败集合 ⊆ Task 4.3 迁移清单（上限 22 例，由 Task 4.3 处理）

#### Task 4.2: 兼容性与回归验证

- **目标**：确认切换后所有既有 import 路径、注册表字符串路径、调用方行为均不受影响
- **步骤**：
  1. 逐条验证 import 路径（见 AC）
  2. 验证 `broca/components/defaults.py:52` 的 `"broca.loop_engine:DefaultLoopEngine"` 解析到新引擎（无需改文件）
  3. 全仓 grep 确认无 `from broca.loop_engine.legacy import` 残留（`legacy.py` 自身除外，Phase 5 删除）
  4. 运行 `pytest broca/tests/ -q`，确认失败集合 **⊆ Task 4.3 迁移清单**（出现清单外失败即说明切换引入了额外回归，必须回退排查）
- **预期产出**：验证记录（贴入 PR description）
- **验收标准**：
  - [ ] `from broca.loop_engine import DefaultLoopEngine` 有效且指向 `engine.py` 的实现
  - [ ] `from broca.loop_engine import ExecutionStatus, ExecutionResult` 有效
  - [ ] `from broca.loop_engine import LoopEngine` 得到**具体类**（与改动前语义一致）
  - [ ] `from broca.components.loop_engine import LoopEngine` 有效（ABC）
  - [ ] `ComponentRegistry` 能通过字符串路径解析 `DefaultLoopEngine`
  - [ ] `pytest broca/tests/ -q` 的失败集合 **⊆ Task 4.3 的迁移清单**（清单外出现任何失败 → 回退排查，不得放行）
  - [ ] 明确记录**基线失败集合**（贴入 PR）：切换当下预期为 **22 例上限** —— `TestRateLimitRetry` 5 + `TestEmptyResponseRetry` 2 + `TestDeadLoopDetection` 3 + `TestParallelToolExecution` 10 + `TestLoopEngineInit::test_init` 1 + `TestExecute::test_execute_context_setup_failure` 1；实际可少于该数，但**不得超出**（另：`test_agent_composition.py::test_create_initialize_order` 因断言 `engine.context_compressor` 而失败，发生在 **Task 5.1** 删除字段时，不计入本步）
  - [ ] `test_loop_engine.py` 的 `loop_engine` fixture（`LoopEngine(agent_ref=...)` 构造式路径）**仍可正常创建**（Round2 N8④）

#### Task 4.3: 旧测试迁移（**新增，Major M14**）

> **执行时机**：必须在 Task 4.1c 切换（`Agent.create()` + 包入口）**之后**执行——此时测试才会真正跑到新引擎，旧的私有方法级用例才会暴露失败。

- **目标**：把依赖被删私有方法的用例迁移到策略/Hook 测试，使"测试全绿"重新可达
- **步骤**：
  1. 按归属拆分 `broca/tests/test_loop_engine.py`（37 例）：

     | 原测试类 / 用例 | 例数 | 去向 | 处理方式 |
     |---|:--:|---|---|
     | `TestRateLimitRetry` | 5 | `broca/tests/test_llm_strategy.py` | mock `LLMClient.get_stream_response`，测 `RetryLLMStrategy.call()` 的限流/重试/计数清零（`_consecutive_rate_limit_errors` 已迁至策略） |
     | `TestEmptyResponseRetry` | 2 | `broca/tests/test_llm_strategy.py` | 同上，测空响应软失败重试与放弃 |
     | `TestDeadLoopDetection::test_no_dead_loop` / `test_dead_loop_detected` / `test_less_than_three_signatures` | 3 | `broca/tests/test_loop_hooks.py` | 直接驱动 `DeadLoopHook.on_step_end(ctx)`（断言 `ctx.status`） |
     | `TestDeadLoopDetection::test_reset_clears_abort` / `test_reset_clears_turn_id` | 2 | **保留在 `test_loop_engine.py`** | 它们测的是 `engine.reset()` 语义（非死循环检测），必须留在 engine 层（Round2 N9） |
     | `TestParallelToolExecution` | 10 | `broca/tests/test_tool_strategy.py` | mock `ToolExecutor`，测 `ParallelToolStrategy.execute()` 的并发/分区/顺序/abort/unknown tool |
     | **`TestLoopEngineInit::test_init`** | **1** | `test_loop_engine.py`（**改写断言**） | 原断言 `step_max_errors` / `llm_retry_delay` / `tool_call_timeout` / `_recent_tool_call_signatures` / `_consecutive_rate_limit_errors` 已迁往策略/Hook → 改为断言 `agent_id` / `session_id` / `abort_event` / `_llm_strategy` / `_tool_strategy` / `_hooks` 已注入（Round2 N8①） |
     | `TestLoopEngineInit` 其余 3 例 + `TestExecutionStatus` 1 + `TestExecutionResult` 4 | 8 | 保留 `test_loop_engine.py` | 不改（只依赖公开 API） |
     | **`TestExecute::test_execute_context_setup_failure`** | **1** | `test_loop_engine.py`（**改 mock 目标**） | `_setup_execution_context` → `_setup_turn`，且返回值由 `False` 改为 `None`（Round2 N8③） |
     | `TestExecute` 其余 2 例 + `TestSaveUserMessage` 3 | 5 | 保留 `test_loop_engine.py` | 不改（只依赖公开/engine 层方法） |
     | **`test_agent_composition.py::test_create_initialize_order`** | **1** | `test_agent_composition.py`（**改写断言**） | 原断言 `engine.context_compressor`（L340）/ `engine.persistent_memory_manager`（L344）已不在 engine → 改为断言 `CompressionMemoryHook` 持有 compressor/memory_manager、`engine.tool_executor` 仍存在（Round2 N8②） |

     > 计数核对：`test_loop_engine.py` 37 例 = **20 例迁出**（5+2+3+10）+ **2 例就地改写**（`test_init`、`test_execute_context_setup_failure`）+ **15 例原样保留**；另有 `test_agent_composition.py::test_create_initialize_order` 1 例就地改写。合计需处理 **23 处**，其中在 Task 4.1c 切换后**失败的上限为 22 例**，第 23 处随 Task 5.1 删字段才失败。

  2. `test_image_tool.py:550` 的 `LoopEngine.process_tool_call_result(engine, ...)`：保持可用（Task 4.1a 步骤 5 已保留该方法），无需改动
  3. `test_loop_engine.py` 在 Phase 4 结束时**只保留** `execute` / `abort` / `reset` / 结果类型 / 用户消息持久化级别用例
  4. 在 `test_loop_engine.py` 顶部注释注明"私有方法级用例已迁至 `test_llm_strategy.py` / `test_tool_strategy.py` / `test_loop_hooks.py`"
- **预期产出**：5 个测试文件（迁移后：`test_llm_strategy.py` / `test_tool_strategy.py` / `test_loop_hooks.py` / `test_loop_engine.py` / `test_agent_composition.py`）
- **验收标准**：
  - [ ] `pytest broca/tests/ -q` **0 失败**
  - [ ] 总用例数 ≥ 751（迁移前 754，迁移只允许"等价改写"或新增）
  - [ ] 原 37 例全部有明确去向（无静默删除；删除需在 PR 描述中逐条说明理由）
  - [ ] 迁移后的用例**不引用**任何已被删除的私有方法名

#### Task 4.4: 端到端验证

- **目标**：验证重构后的完整执行流程
- **步骤**：
  1. 运行全部测试：`pytest broca/tests/ -q`
  2. 运行 e2e 场景测试：`pytest broca/tests/test_e2e_scenarios.py -k websocket`
  3. 运行组合测试：`pytest broca/tests/test_agent_composition.py -q`
  4. **手动验证**（不阻塞 CI，但 PR author 必须完成并附日志/截图）：
     - 启动 dev 服务 → 创建 session → 发送消息
     - 前端依次收到 `turn_start`（**仅 1 次**）→ `step_start` → `step_end`（含 patch）→ `turn_end`（含 changed_files）
     - 文件修改后 `step_end.patch` 与 `turn_end.changed_files` 均非空
     - 错误场景（LLM 超时 / 工具失败）前端收到 `error` 事件（含 warning/error 两级），且**限流场景 `error.code == "LLM_RATE_LIMIT"`**（Round2 N4）
     - 触发 abort 后：1s 内停止，不再重试
     - 子 Agent（`assign_task`）：无前端事件、无快照
- **预期产出**：测试通过 + 手动验证日志（附 PR description）
- **验收标准**：
  - [ ] `pytest broca/tests/ -q` 0 失败，总数 ≥751
  - [ ] `pytest broca/tests/test_e2e_scenarios.py -k websocket` 通过
  - [ ] 前端 WebSocket 事件流完整且 `turn_start` 不重复（手动验证，附截图/日志）
  - [ ] 限流场景前端 `error.code == "LLM_RATE_LIMIT"`（**不是** `BROCA_ERROR`）（Round2 N4，手动验证附日志）
  - [ ] `/compact` 命令执行成功且输出压缩统计（Round2 N1，手动验证附截图）
  - [ ] abort 后无重试 sleep（手动验证：abort 后 1s 内结束）
  - [ ] 子 Agent 执行不触发通信/快照（`test_agent_composition.py` + 手动验证）

---

### Phase 5: 清理 + 加固

**目标**：移除旧代码，补充测试

**阶段验收标准**：
- [ ] `broca/loop_engine/legacy.py` 已删除，仓库内无 1400+ 行巨石类
- [ ] 新增 Hook/策略专项测试
- [ ] 迁移后测试 0 失败，总数 ≥751（含新增用例后应 ≥ 754）

#### Task 5.1: 清理遗留代码

- **目标**：删除不再使用的旧实现
- **步骤**：
  1. `git rm broca/loop_engine/legacy.py`
  2. 对照「方法迁移映射表」逐行核对 52 项，确认 `engine.py` 中已无被策略/Hook 替代的方法
  3. 删除 `engine.py` 中不再需要的依赖字段：**仅** `snapshot_manager` / `context_compressor` / `persistent_memory_manager`。
     ⚠️ **必须保留** `tool_executor`（`_check_write_ops()` 调 `is_readonly_tool()`、`reset()` 调 `tool_executor._permission_provider.clear_session_overrides()`，且 `test_agent_composition.py:191/335`、`test_e2e_scenarios.py:419` 断言 `engine.tool_executor`），以及 `agent_ref` / `llm_client` / `context` / `communicator` / `session_manager` / `config` / `tool_mapping`（Round2 N2）
  4. 精简 `initialize()` 的参数消费逻辑
  5. 更新 `broca/loop_engine/__init__.py` 的 docstring（去掉 legacy 提及）
- **预期产出**：精简后的 `engine.py`
- **验收标准**：
  - [ ] `broca/loop_engine/legacy.py` 不存在
  - [ ] `engine.py` 总行数 ≤ 320
  - [ ] `engine.py` 不包含 `SnapshotManager` / `ContextCompressor` / `MemoryManager` 的 import
  - [ ] **`session_manager.save_turn_end` 仍被调用**（grep `engine.py` 有该调用 + 单测断言；防 Critical C3 回归）
  - [ ] `process_tool_call_result` 仍在 engine 上（`test_image_tool.py` 通过）
  - [ ] 迁移后测试 0 失败，总数 ≥751

#### Task 5.2: 策略 + Hook 专项测试

- **目标**：补齐新增结构的测试覆盖
- **步骤**：
  1. `broca/tests/test_llm_strategy.py`（含 Task 4.3 迁移的 7 例）+ `test_llm_strategy_golden.py`（20 条 fixture）
     - RetryLLMStrategy：重试次数、限流计数、超时、空响应、`on_chunk`（3 类）、`on_error`（6 个提示点）、`should_abort`
  2. `broca/tests/test_tool_strategy.py`（含迁移的 10 例）
     - ParallelToolStrategy：并发度上限、permission 分区、结果顺序、abort、未知工具
     - SerialToolStrategy：串行顺序、abort
  3. `broca/tests/test_loop_hooks.py`（含 Task 4.3 迁移的 3 例）
     - SnapshotHook：step start/end、turn end、lock 释放（异常路径）、`enable_snapshot_tracking=False` no-op、`reset()`
     - CommunicatorHook：interactive/non-interactive、`turn_start` 仅 1 次、`on_turn_finalized` 参数
     - CompressionMemoryHook：压缩触发条件、记忆 fire-and-forget
     - DeadLoopHook：检测/不检测/reset/window 语义
  4. `broca/tests/test_loop_hooks_factory.py`
     - `build_default_hooks` 返回 4 个且顺序固定、`name` 唯一
     - `build_subagent_hooks` 无 snapshot/communicator
     - 全 `None` 参数时 no-op 可创建
  5. `broca/tests/test_compact_command.py`（Round2 N1 补充）
     - mock `ContextCompressor`：执行 `/compact` → 断言 `check_and_compress(force=True)` 被调用、`compressor_context` 满足协议（5 个属性）
     - 断言不再引用 `execution_engine._build_compressor_context`
  6. `broca/tests/test_engine_orchestration.py`
     - 6 个生命周期 dispatch 顺序（用记录型假 Hook 断言调用序列）
     - DEAD_LOOP 传播、`save_turn_end` 调用、token 上报、每 turn 状态重置
- **预期产出**：6 个测试文件（~560 行）
- **验收标准**：
  - [ ] 每个策略 ≥ 3 个用例（`RetryLLMStrategy` ≥ 10）
  - [ ] 每个 Hook ≥ 3 个用例
  - [ ] 使用 `unittest.mock.AsyncMock` 隔离外部依赖
  - [ ] 全部新测试通过，总数 ≥751

#### Task 5.3: 性能验证

- **目标**：确认重构无性能回退
- **步骤**：
  0. **采集 baseline**：直接 `from broca.loop_engine.legacy import DefaultLoopEngine` 跑（`legacy.py` 到 Task 5.1 才删除，**无需回退切换**）。用 `time.perf_counter` 对 legacy 引擎跑
     - 10 次 `_execute_round`（mock LLM/工具）
     - 10 次 `_call_llm_with_retry`（mock 3 个 chunk）
     - 10 次 `_process_tool_calls_parallel`（10 个 mock 工具）
     结果写入 `reports/perf/loop-engine-baseline.json`
  1. 用同一组基准跑新引擎，写入 `reports/perf/loop-engine-after.json`
  2. 对比策略调用开销（相对直接方法调用）
  3. 统计 `_dispatch` 开销：**每 step 3 次**（`on_step_start` / `on_step_end` / `on_post_step`），每 turn 另加 3 次（`on_turn_start` / `on_turn_end` / `on_turn_finalized`）；4 个 Hook 时单 step 合计 12 次 await
- **预期产出**：`reports/perf/loop-engine-baseline.json` + `loop-engine-after.json` + 对比结论
- **验收标准**：
  - [ ] baseline 文件已提交（缺失则本 Task 视为未完成）
  - [ ] LLM 调用延迟差异 < 1ms（策略是 in-process 方法调用）
  - [ ] 10 个 parallel tools 的总耗时差异 < 2%
  - [ ] Hook dispatch 单次调用开销 < 0.02ms，单 step（12 次 await）合计 < 0.25ms

---

## 风险与应对

| # | 风险 | 影响 | 触发信号 | 应对策略 | 验证方式 |
|:-:|------|------|----------|----------|----------|
| R1 | 策略/Hook 初始化顺序错误 | `Agent.create()` 时策略未 ready | 首次 `execute()` 抛 `AttributeError: NoneType` | `initialize()` 中显式 await 策略的 `initialize()`，顺序固定（LLM → Tool → Hooks） | `test_agent_composition.py` 通过 |
| R2 | `on_chunk` / `on_error` 中 communicator 未连接 | 流式广播/错误提示丢失 | 前端无流式输出但 DB 有响应 | handler 内 try/except + warning（与现有行为一致） | e2e 手动验证 + `test_e2e_scenarios.py` |
| R3 | Hook 间数据依赖顺序（Snapshot 写 → Communicator 读） | patch / changed_files 为空 | `step_end.patch == {}` 而实际有改动 | `build_default_hooks()` 固定顺序；`on_turn_end`（计算）与 `on_turn_finalized`（广播）分阶段 | `test_engine_orchestration.py` 顺序断言 + `test_loop_hooks.py` |
| R4 | 第三方插件通过 registry 替换 LoopEngine | ABC 签名变化 | 插件初始化 TypeError | 新参数**全部有默认值**；实现类可用 `**kwargs`；不传策略时 engine 回退内置默认 | `test_component_interfaces.py` + 插件冒烟 |
| R5 | **LLM streaming 聚合逻辑迁移遗漏边界 case** | 生产流式聚合错误（off-by-one / chunk 丢失 / tool_call 顺序） | golden fixture 不一致 | 20 条手工 fixture 覆盖矩阵（content/reasoning/tool_call/混合/空流/多 tool_call 交错） | `test_llm_strategy_golden.py` 全绿 |
| R6 | **Hook 状态残留（abort 后 stale state）** | 下个 turn 使用过期快照/签名 | 第二次 turn 误判 DEAD_LOOP / changed_files 含上一 turn 改动 | `LoopHook.reset()` 契约 + 每 turn `_reset_turn_scoped_state()` + `engine.reset()` | 单测「连续两次 execute 互不影响」 |
| R7 | 大文件重构中意外破坏 | 测试失败 | Phase 4 迁移后批量失败 | 4.1a→4.1b→4.1c→4.2→4.3 分步验证，每步可回退 | 每步 `pytest broca/tests/ -q` |
| R8 | `AgentReference` protocol 变更 | 压缩上下文构建失败 | `/compact` 报错 | 不改 protocol；`compressor_ctx_builder` 作为 callable 传入 Hook | `test_context_compressor.py` + 手动 `/compact` |
| R9 | **现有测试直接依赖私有方法**（37 例） | Phase 4 起批量 `AttributeError`，CI 全红 | Task 4.1c 切换后 `test_loop_engine.py` 失败 ≤22 例 | 新增 Task 4.3 迁移（在 4.1c 切换后执行）；Phase 4 判据改为「迁移后 0 失败」 | 迁移映射表逐行核对 + 全量 pytest |
| R10 | **abort 语义回归** | 用户中止后仍跑满 `3 × 5s` 重试 | abort 后 15s 才停止 | `should_abort` 参数化，策略在每个重试点/chunk 前检查且不 sleep | 单测「abort 后 `call()` 耗时 < 0.1s」+ 手动验证 |
| R11 | 包/模块同名导致 import 歧义 | 加载到错误实现 | `broca.loop_engine.__file__` 指向 `.py` | Phase 1 即 `git mv` 消除；禁止重新创建 `broca/loop_engine.py` | `python -c "import broca.loop_engine as m; print(m.__file__)"` |
| R12 | turn 状态永远停在 active | web 后端会话列表/继续对话异常 | DB `turn.status == "active"` 且无 turn_end | `save_turn_end` 留在 engine `_finalize_turn()`；Task 5.1 AC 强制断言 | 单测 mock `session_manager.save_turn_end` + `broca-web` 手动验证 |
| R13 | 工具结果处理（68 行）拆分后丢逻辑 | `extra_context_messages`（图片注入）丢失 / DB 无 tool_call 记录 | 图片工具后模型看不到图 | `process_tool_call_result` 整体保留在 engine，不拆到 Hook | `test_image_tool.py` 通过 |
| R14 | **无测试覆盖的外部调用方静默失效**（如 `/compact` 调 `_build_compressor_context`） | 线上命令报错，但 CI 全绿 → 无人发现 | 用户执行 `/compact` 报 `AttributeError` | 迁移前全仓 grep 私有方法名的外部引用并逐一登记（Task 4.1c 步骤 7）；为每个调用方补至少 1 个单测 | `grep -rn "_build_compressor_context" broca/ --include=*.py` 除 `legacy.py` 外无命中 + `test_compact_command.py` 通过 |

---

## 未解决的问题

**已在本版拍板（不再作为待决策项）**：

1. **abort 传递方式** → 策略接口显式 `should_abort: Callable[[], bool]`（不引入 `ToolCallContext.abort_event`）
2. **LLM 错误通知通道** → 独立 `on_error(message, code, severity)` 回调（不进 chunk）
3. **工具结果处理归属** → engine 的 `process_tool_call_result()` + `_process_tool_results()`（不引入 `ToolResultHook`，避免 Hook 层做 DB 写入）
4. **turn 持久化归属** → engine `_finalize_turn()`；广播拆到 `on_turn_finalized`
5. **策略选择入口** → 只做 `AgentConfig`（`strategies/factory.py`）
6. **包化方式** → Phase 1 `git mv` 为 `loop_engine/legacy.py`，Phase 5 删除

**剩余 TODO（不阻塞执行，记录备查）**：

1. `ComponentRegistry` 策略注册机制（当前 `create_*_strategy` 硬编码默认实现）
2. `ToolExecutionStrategy` 是否需要一个"并发度自适应"变体（如按工具类型分组）
3. ABC 参数名 `permission_provider` 与调用方 `tool_permission_manager` 的历史不一致（本次不动，后续统一）
4. `broca/loop_engine/__init__.py` 的 `LoopEngine` 别名长期是否废弃（需先迁移 `test_loop_engine.py` / `test_image_tool.py` 的用法）

---

## 附录 A：v2 修订记录（Round-1 → v2）

> 上一轮评审结论：⭐⭐ 2.6/5，❌ Needs Revision（5 Critical / 18 Major / 16 Minor）。本版逐条修订如下。

| Review 编号 | 问题 | 本版修订位置 |
|:---:|------|------|
| **C1** | 缺 52 个方法的迁移映射表，约 20 个方法无归属 | 新增「**方法迁移映射表**」（52 行，逐方法指定归属）；「未解决的问题」改为已拍板 |
| **C2** | `process_tool_call_result`（68 行）无归属 | 归属 engine：保留 `process_tool_call_result()` + 新增 `_process_tool_results()`（Task 4.1a 步骤 5、AC） |
| **C3** | `session_manager.save_turn_end` 被拆给不具备依赖的 Hook → turn 永远 active | `save_turn_end` 归 engine 的 `_finalize_turn()`；SnapshotHook 只算 `changed_files`；CommunicatorHook 只广播（Task 4.1a 步骤 6、Task 5.1 AC） |
| **C4** | abort 信号未进策略接口；4.1b 关于 "llm_client cancel 机制" 的描述与实现不符 | `LLMStrategy.call` / `ToolExecutionStrategy.execute` 增加 `should_abort: Callable[[], bool]`；删除错误描述（Task 1.2/1.3/2.1/2.2/4.1b） |
| **C5** | 四个 Hook 未定义 `name`，而 `LoopHook.name` 是 abstract property → 实例化即 TypeError | `LoopHook.name` 改为**非抽象类属性**（默认 `"loop_hook"`）+ 每个 Hook AC 强制定义 `name`（Task 1.1/3.1~3.4） |
| **M1** | `agent_ref.on_llm_call_completed` 无归属 → token 统计丢失 | `LLMCallResult` 携带 token；engine 在策略返回后调用（Task 4.1a 步骤 4、AC） |
| **M2** | `StepContext.has_write_ops` 填充责任未指定 | engine 在 `on_step_start` dispatch **之前**调 `_check_write_ops()` 写入（Task 4.1a 步骤 4、4.1b AC） |
| **M3** | `ctx.status = DEAD_LOOP` 后的终止与结果构造未定义 | `_execute_round` 显式读取 `step_ctx.status` → `_build_round_result`（Task 4.1b 步骤 3） |
| **M4** | `on_chunk` 无 error 类型，6 处 `_send_llm_error` 通知会丢失 | 新增独立 `on_error(message, code, severity)` 回调契约（Task 1.2 / 2.1 / 4.1b） |
| **M5** | Task 2.2 AC 引用不存在的 `context.abort_event` | 改用 `should_abort` 参数；明确 `ToolCallContext` 只有 7 个字段（Task 2.2 AC） |
| **M6** | 4.1c ↔ 4.2 前向引用 + 同一改动重复描述 | `Agent.create()` 与包 `__init__` 切换**唯一**放 4.1c；4.2 只做兼容性/回归验证 |
| **M7** | 配置优先级未定义，agent 级覆盖会失效 | Task 2.3 写出「显式参数 > AgentConfig > execution_config > 默认」+ AC |
| **M8** | 包在 Phase 4 才创建，Phase 2/3 无处写文件 | 新增 **Task 1.5 包化骨架**（Phase 1） |
| **M9** | Phase 2/3 都要改 `builder.py` → 并行必冲突 | 拆为 `strategies/factory.py`（Phase 2 独占）+ `hooks/factory.py`（Phase 3 独占） |
| **M10** | `broca/loop_engine.py` shim 被同名包遮蔽，是死代码 | 直接删除该文件（Task 1.5 `git mv` → `loop_engine/legacy.py`；Task 5.1 删除 legacy） |
| **M11** | Phase 1 加必填参数但调用方 Phase 4 才更新 → 契约空窗 | 新参数全部带 `None` 默认值；`DefaultLoopEngine` 在 `None` 时回退内置默认（Task 1.4 / 4.1a） |
| **M12** | 每 turn 状态重置缺失（死循环签名 / 限流计数跨 turn 累积） | `_setup_turn()` 中重置 `abort_event` + `DeadLoopHook.reset()` + `llm_strategy.reset()`（Task 4.1a 步骤 2、AC） |
| **M13** | turn_start 事件双发（`_start_new_turn` 已广播） | `_start_turn()` 只写 DB + `turn_id`；广播唯一来源 = `CommunicatorHook.on_turn_start`（Task 3.2 AC、4.1a 步骤 3） |
| **M14** | "全部测试通过（≥751）" 在 Phase 4/5 不可达 | 新增 **Task 4.3 旧测试迁移**（37 例映射表）；判据改为「迁移后 0 失败且总数 ≥751」 |
| **M15** | Phase 1 AC "不修改已有文件" 与 Task 1.4 冲突 | 改为「除 `components/loop_engine.py`、`components/__init__.py` 外不修改已有文件」 |
| **M16/M17** | 风险表缺"测试依赖私有方法"、"abort 语义回归" | 风险表新增 R9 / R10 |
| **M18** | 行数目标四种口径 | 统一为 `engine.py` 总行数 ≤ 320（见概述） |
| **m1** | SnapshotHook 未体现 `enable_snapshot_tracking` 开关 | Task 3.1 AC 增加 no-op 断言 |
| **m2** | "未解决的问题" 为空但存在待决策项 | 改为已拍板决策 + 剩余 TODO |
| **m3** | `"X" \| None` 需 future import | Task 1.1/1.2/1.3 步骤显式要求 `from __future__ import annotations` |
| **m4** | 决策表"ComponentRegistry 或 AgentConfig"未拍板 | 拍板：先只做 `AgentConfig`，registry 留 TODO |
| **m5** | Task 5.3 缺 baseline 采集；"4×5" 描述错误 | 增加步骤 0 采集 baseline；修正为「每 step 3 次 dispatch」 |
| **m6** | Task 3.4 `window` 语义不清 | 明确「签名列表最后 `window` 个元素」 |
| **m7** | Task 3.5 AC "lazy 初始化或跳过" 二义 | 写死为 no-op 语义 |
| **m8** | golden test 数据来源未定义 | 手工 fixture 到 `broca/tests/fixtures/llm_streaming/*.json`（20 条覆盖矩阵） |
| **m9** | `initialize(*, ...)` 与 ABC 位置参数冲突（mypy） | 明确 `# type: ignore[override]` |
| **m10** | Task 3.5 docstring 顺序与代码不一致 | 统一为「快照→通信→死循环→压缩」 |
| **m11** | "59 个方法" 实为 52 | 概述已修正 |
| **m12/m13** | 文件树两个 `└──`、`loop_engine.py` 兼容入口与包冲突 | 文件结构树重写 |
| **m15/m16** | 风险表无"验证方式"列、缺包/模块同名风险 | 风险表新增「触发信号」「验证方式」两列 + R11 |
| **m14** | Task 2.1 vs 2.3 粒度不均 | 接受（2.3 本质是接线），不合并 |

---

## 附录 B：v3 修订记录（Round-2 → v3）

> 上一轮评审结论：⭐⭐⭐⭐ 4.1/5，⚠️ Conditional Pass（1 Critical / 4 Major / 11 Minor）。

| Review 编号 | 级别 | 问题 | 本版修订 |
|:---:|:---:|------|------|
| **N1** | 🔴 Critical | `/compact` 命令（`commands/builtin/compact/__init__.py:63`）仍调已迁走的 `_build_compressor_context()`，且该路径零测试覆盖 → CI 全绿但线上命令失效 | 相关材料新增该调用方 + protocols.py:62 docstring；Task 4.1c 新增步骤 5/6/7；AC 增加 `/compact` 可执行 + `test_compact_command.py`；风险新增 R14 |
| **N2** | 🟡 Major | `engine.tool_executor` 归属未写明（`_check_write_ops` / `reset` / 3 处测试依赖），Task 5.1 可能误删 | 方法表 #1 补齐「必须保留」字段清单（含 `tool_executor`）；Task 5.1 步骤 3 写死「仅删 3 个字段」+ 显式保留清单 |
| **N3** | 🟡 Major | `_save_response()` 返回值被忽略 → DB 写失败仍继续，context/DB 不一致 | 方法表 #18 标注返回 `bool`；Task 4.1b 伪代码改为失败即 `status=ERROR` 并 return；AC 新增断言 |
| **N4** | 🟡 Major | `_execute_round` 丢掉 legacy 的 `except BrocaError` → 前端 error code 从 `LLM_RATE_LIMIT` 退化为 `BROCA_ERROR` | Task 4.1b 伪代码补 `except BrocaError`（用 `e.to_dict()` 上报）+ `except CancelledError`；AC 新增「限流场景 code == LLM_RATE_LIMIT」；Task 4.4 e2e AC 增加 code 断言 |
| **N8** | 🟡 Major | 「失败集合恰好 22 例」低估（`test_init` / `test_create_initialize_order` / `test_execute_context_setup_failure` 必失败）；若丢构造式初始化路径则 37 例全崩 | 改为「失败集合 ⊆ 迁移清单」+ 22 例上限清单；Task 4.3 表补 3 行并重算计数（20 迁出 + 2 就地改写 + 15 保留 + composition 1）；方法表 #1/#2 明确**保留** `__init__(agent_ref=...)` 构造式路径 |
| **N5** | 🟢 Minor | 契约速查未声明两个策略的 `initialize` 抽象签名与必需依赖 | 契约块补 `initialize(*, llm_client, config)` / `initialize(*, tool_executor, config)` |
| **N6** | 🟢 Minor | `_setup_turn()` 返回 `None` 的分支未写出 | Task 4.1a 步骤 7 补 `SESSION_ERROR` 分支伪代码 |
| **N7** | 🟢 Minor | token 上报时机变化未声明（失败/空响应 attempt 不再上报） | 方法表 #23 + Task 4.1a 步骤 4 明确「有意收紧」及其影响面 |
| **N9** | 🟢 Minor | `TestDeadLoopDetection` 中 2 例实为 `engine.reset` 语义 | Task 4.3 表拆分为「3 例迁出 + 2 例保留」 |
| **N10** | 🟢 Minor | golden fixture 含 `ToolCall` 对象，缺反序列化 schema | Task 2.1 步骤 7 补完整 fixture schema + 还原/断言约定 |
| **N11** | 🟢 Minor | Task 5.3 步骤 0「在 4.1c 前执行」与 Phase 5 时序矛盾 | 改为「直接 `from broca.loop_engine.legacy import DefaultLoopEngine` 跑 baseline，无需回退」 |
| **N12** | 🟢 Minor | `CancelledError → aborted=True` 与 legacy 不完全等价 | Task 2.1 步骤 4 显式声明该语义变化与理由 |
| **N13** | 🟢 Minor | `_build_round_result` async/sync 不一致（伪代码无 await） | 方法表 #34 与 Task 4.1b 伪代码统一为**同步 `def`** |
| **N14** | 🟢 Minor | 风险表缺「无测试覆盖的外部调用方静默失效」 | 新增 R14 |
| **N15** | 🟢 Minor | 修订记录占正文 3.6%，稀释执行者注意力 | v2 记录整体移入**附录 A**，正文只留 2 行指针；v3 记录移入**附录 B** |
| **N16** | 🟢 Minor | `LoopEngine` 别名的使用场景未界定 | 决策表补使用约定：注册/isinstance/类型标注用 `broca.components.LoopEngine` |

---

## 附录 C：v4 修订记录（Phase 5 执行后 · 评审整改）

> 来源：`reports/review/loop-engine-hooks-refactor-review.md`（全阶段评审，Conditional Pass 4.1/5）。
> 本附录只记录**计划口径的正式变更**与**执行清单的补登**；代码整改见
> `plans/reports/execution/loop-engine-hooks-refactor-phase-5-review-fixes.md`。

| 编号 | 级别 | 问题 | 本版处置 |
|:----:|:----:|------|----------|
| **C1** | 🔴 Critical | `engine.py` 实测 780 行，计划「唯一标准」为 ≤320 行；执行者以「用户口头指示：可读性优先」放宽至 ≤800，但计划未修订、无书面留痕 | **由计划 owner（用户）正式撤销该口径**：`engine.py` 行数**不再作为验收判据**，理由是 Phase 4 实测单文件极限压缩 ≥440 行、进一步拆分 mixin 会显著损害可读性，owner 明确要求「可读性优先，不必强行要求行数」。替代判据改为**结构护栏**：①`legacy.py` 已删除且 `broca/loop_engine/` 无 ≥1000 行文件；②引擎 import 不含 `SnapshotManager`/`ContextCompressor`/`MemoryManager`；③引擎无内联策略逻辑（`Semaphore`/`asyncio.sleep`/`get_permission`/`dead_loop_window`）；④引擎方法数 ≤ 40（legacy 为 52）。**受影响的 7 处口径**：行 14（概述）、行 56（架构图）、行 196（文件树）、行 805（Phase 4 阶段 AC）、行 932 / 1013（Task 4.1a / 4.1b 预期产出）、行 1102（Task 4.2 AC）、行 1209（Task 5.1 AC）；另有附录 A 的 M18 条目（历史记录，不改）。同时**删除**回归护栏中人为设定的 `assert <= 800` 行数断言（该断言本身即是「降低验收标准」的痕迹），改为 `test_engine_is_an_orchestrator_not_a_monolith`（方法数护栏） |
| **M5** | 🟡 Major | Task 4.2 的「失败集合 ⊆ 清单（上限 22 例）」漏登记 `test_agent_composition.py::test_agent_full_lifecycle` | **补登**：Task 4.2 基线失败集合应为 **23 例**（22 + `test_agent_full_lifecycle`，同根因同处置：`engine.context_compressor` 移除）。清单漏项性质与附录 B 的 N8 相同，属计划侧遗漏而非执行超限 |
| **m6** | 🟢 Minor | Task 5.2 要求 `test_loop_hooks.py` + `test_loop_hooks_factory.py` 单文件 | **命名对齐**：实际为按 Hook 拆分的 `test_snapshot_hook.py` / `test_communicator_hook.py` / `test_compression_hook.py` / `test_dead_loop_hook.py` + `test_hook_factory.py`。覆盖点与计划逐项一致（见 Phase 5 报告覆盖矩阵），保留拆分形式（符合 owner「可读性优先」的裁定） |
| **M4** | 🟡 Major | STEP_START「先广播后入库」，与 legacy「先入库后广播」相反 | **登记为有意变更**（不改代码）：`step_start_snapshot` 由 `SnapshotHook.on_step_start` 产生，引擎必须在 `_dispatch` **之后**才能持久化，否则入库的 `snapshot_hash` 恒为空。改回「先存后播」需让引擎感知具体 Hook 类型（破坏「Hook 顺序固定、引擎不感知实现」的架构），代价大于收益。风险评估：差额为微秒级，且广播事件本身已携带 `snapshot_hash`，前端不依赖 DB 行存在性 |

### C1 之后的 `engine.py` 规模口径

不再设行数上限。可观测的规模指标（仅作趋势参考，非 AC）：`engine.py` 820 行 / 35 方法；
`strategies/` 627 行 / `hooks/` 686 行 —— 策略与 Hook 层合计已超过引擎本身，符合「引擎退化为薄编排器」的设计意图。
