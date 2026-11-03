# LoopEngine 代码审查发现

**审查日期**: 2026-11-01
**修复日期**: 2026-11-01
**审查范围**: `.worktrees/refactor` 分支 `broca/loop_engine/` + `broca/components/loop_engine.py` 及相关文件

## 修复状态

| 编号 | 状态 | 备注 |
|------|------|------|
| 1.1 | ✅ 已修复 | `_persist_step_end` 加了与 `_persist_step_start` 相同的 gate |
| 1.2 | ✅ 已修复 | 新增 `ToolResultProcessingError(BrocaError)`，替换裸 `Exception` |
| 1.3 | ✅ 已修复 | done callback 改为 `logger.warning` 输出异常信息 |
| 1.4 | ✅ 已修复 | `gather` 返回后遍历异常值打 `logger.warning` |
| 1.5 | ✅ 已修复 | `_setup_turn` 的 `except Exception` 改为 `raise SessionError(...)` |
| 1.6 | ✅ 已修复 | `status` 直接存 `result.status.value` |
| 2.1 | ✅ 已修复 | ABC 移除 `context_compressor`/`memory_manager`；统一 `permission_provider`；`initialize()` 改为显式参数 |
| 2.2 | ✅ 已修复 | `broca/loop_engine/__init__.py` 移除 `LoopEngine` 别名，只导出 `DefaultLoopEngine` |
| 2.3 | ⏭️ 跳过 | 用户决定不修 |
| 2.4 | ✅ 已修复 | `initialize()` 重复调用改为 `raise RuntimeError` |
| 2.5 | ✅ 已修复 | `allowed_tools`/`namespace` 改为 `execute()` 的 keyword-only 参数 |
| 2.6 | ✅ 已修复 | `LLMClient._process_chunk` 现在 yield `{"type": "usage", ...}` 事件；`RetryLLMStrategy._stream_once` 从流中取 token 数，不再读 LLMClient 共享实例属性 |
| 3.1 | ✅ 已修复 | `ExecutionResult` 改为 `@dataclass` |
| 3.2 | ✅ 已修复 | chunk/error handler 提升到 turn 级别（`_execute_round` 创建一次） |
| 3.3 | ✅ 已修复 | `logger.warning` → `logger.error` |
| 3.4 | ✅ 已修复 | `_do_initialize` 加空 `tool_mapping` 的 warning |
| 3.5 | ✅ 已修复 | 添加 fallback return 的注释 |
| 4.1 | ✅ 已修复 | 新建 `ContextCleanupHook`，从 `_finalize_turn` 移除 inline truncate |
| 4.2 | ✅ 已修复 | `_check_write_ops` 移到 `SnapshotHook`（注入 `tool_executor`） |
| 4.3 | ⏭️ 暂不做 | 评审建议保持现状 |
| 4.4 | ⏭️ 暂不做 | 评审建议保持现状 |
| 4.7 | ⏭️ 可选 | 性能剖析 hook，当前不紧急 |
| 6.4 | ✅ 已修复 | `compressor_context.py` 移到 `broca/components/compressor_context_factory.py`，原位置保留 re-export |
**审查文件清单**:

| 文件 | 角色 |
|------|------|
| `broca/components/loop_engine.py` | `LoopEngine` ABC + `ExecutionResult`/`ExecutionStatus` |
| `broca/components/loop_hook.py` | `LoopHook` ABC + `TurnContext`/`StepContext` |
| `broca/components/llm_strategy.py` | `LLMStrategy` ABC + `LLMCallResult` |
| `broca/components/tool_strategy.py` | `ToolExecutionStrategy` ABC |
| `broca/components/protocols.py` | `AgentReference` / `CompressorContext` 协议 |
| `broca/components/registry.py` | `ComponentRegistry` 插件注册表 |
| `broca/components/defaults.py` | 默认实现映射 + 作用域映射 |
| `broca/loop_engine/engine.py` | `DefaultLoopEngine` 具体实现 |
| `broca/loop_engine/strategies/factory.py` | 策略工厂 |
| `broca/loop_engine/strategies/retry_llm.py` | `RetryLLMStrategy` |
| `broca/loop_engine/strategies/serial_tool.py` | `SerialToolStrategy` |
| `broca/loop_engine/strategies/parallel_tool.py` | `ParallelToolStrategy` |
| `broca/loop_engine/hooks/factory.py` | Hook 工厂 |
| `broca/loop_engine/hooks/snapshot_hook.py` | `SnapshotHook` |
| `broca/loop_engine/hooks/lifecycle_broadcast_hook.py` | `LifecycleBroadcastHook` |
| `broca/loop_engine/hooks/dead_loop_hook.py` | `DeadLoopHook` |
| `broca/loop_engine/hooks/compression_hook.py` | `CompressionMemoryHook` |
| `broca/loop_engine/compressor_context.py` | 压缩上下文适配器 |
| `broca/loop_engine/__init__.py` | 包入口（含 `LoopEngine` 兼容别名） |
| `broca/agent.py` | Agent 类（调用方） |
| `broca/agent_reference.py` | `AgentReferenceAdapter` |

---

## 一、正确性问题（P0）

### 1.1 `_persist_step_end` 缺少与 `_persist_step_start` 对应的 gate

**文件**: `broca/loop_engine/engine.py`
**位置**: `_persist_step_end()` vs `_persist_step_start()`

`_persist_step_start` 有两个前置 gate：

```python
async def _persist_step_start(self, step_ctx):
    if not getattr(self.config, "enable_snapshot_tracking", True):
        return False
    if not getattr(self.config, "workspace", None):
        return False
    return await self._save_step_message(...)
```

但 `_persist_step_end` **没有同样的 gate**：

```python
async def _persist_step_end(self, step_ctx):
    # 无 gate，无条件写入
    return await self._save_step_message(
        MessageProtocol.create_step_end(...)
    )
```

**影响**: 当 `enable_snapshot_tracking=False` 或 `workspace` 为空时，DB 里会出现**没有配对 STEP_START 的孤立 STEP_END 行**。`LifecycleBroadcastHook` 用 `_tracks_snapshots` 属性做了对应的广播 gate，但 DB 持久化层没有。

**修复方案**: 给 `_persist_step_end` 加同样的 gate 条件。

---

### 1.2 `_process_tool_results` 抛出裸 `Exception` 而非业务异常

**文件**: `broca/loop_engine/engine.py`
**位置**: `_process_tool_results()` 最后一行

```python
if not await self.process_tool_call_result(tool_call, result):
    raise Exception("Tool call result processing failed")
```

这个裸 `Exception` 的调用链：
1. `_process_tool_results` → raise
2. 穿透 `_execute_step` 的 `finally` 块（`on_step_end` + `_persist_step_end` 正常执行）
3. 穿透 `_execute_round`（只 catch `BrocaError` + `CancelledError`，**不 catch 裸 `Exception`**）
4. 到达 `execute()` 的兜底 `except Exception` → 标记为 `"UNKNOWN_ERROR"`

**影响**: 工具结果持久化失败是**可预期的业务错误**（比如 DB 连接断开），但前端收到的错误码是 `"UNKNOWN_ERROR"`，文案是 `"执行异常: ..."`——语义不对。

**修复方案**: 在 `broca/errors/` 下定义 `ToolResultProcessingError(BrocaError)`，替换裸 `Exception`；`_execute_round` 的 `except BrocaError` 自然能捕获它。

---

### 1.3 `CompressionMemoryHook._extract_memory` 异常静默吞没

**文件**: `broca/loop_engine/hooks/compression_hook.py`
**位置**: `_extract_memory()` 的 done callback

```python
task.add_done_callback(
    lambda t: t.exception() if not t.cancelled() else None
)
```

`t.exception()` 调用只是为了抑制 Python 的 `"Task exception was never retrieved"` 警告，**没有任何日志输出**。

**影响**: 如果 `memory_manager.check_and_extract()` 持续失败（DB 连接断开、LLM 调用超时），运维**完全不知道**，因为 `asyncio.create_task` 的异常既不打日志也不上抛。

**修复方案**: 改为 `lambda t: logger.warning(f"Memory extraction failed: {t.exception()}") if not t.cancelled() and t.exception() else None`。

---

### 1.4 `ParallelToolStrategy` 的 `gather(return_exceptions=True)` 吞掉任务异常

**文件**: `broca/loop_engine/strategies/parallel_tool.py`
**位置**: `_execute_parallel()` 的 `asyncio.gather`

```python
await asyncio.gather(*tasks, return_exceptions=True)

# 填充 None 槽位
for index in range(len(tool_calls)):
    if results[index] is None:
        results[index] = ToolResult(
            status=ToolStatus.ERROR, content=FAILED_RESULT_CONTENT
        )
```

`return_exceptions=True` 让 `gather` 不抛异常，但如果某个 task 内部异常导致 `results[index]` 未被赋值，这里只填一个通用的 `"Tool execution failed (task cancelled or error)"` 占位符——**原始异常（如 OOM、超时）完全丢失**，没有日志。

**修复方案**: 在 `gather` 之后遍历返回的异常值，对非 `None` 的异常打 `logger.warning`。

---

### 1.5 `_setup_turn` 吞掉所有非 `ValidationError` 异常并统一报 `"SESSION_ERROR"`

**文件**: `broca/loop_engine/engine.py`
**位置**: `_setup_turn()` 的异常处理 + `execute()` 的 `turn_ctx is None` 分支

```python
# _setup_turn 内部
except ValidationError:
    raise
except Exception as e:
    logger.error(f"Error in _setup_turn: {e}")
    return None   # ← 原始异常被吞掉

# execute() 里
turn_ctx = await self._setup_turn(message, from_agent)
if turn_ctx is None:
    await self._send_execution_error(Exception("执行上下文设置失败"), "SESSION_ERROR")
    return ExecutionResult(status=ExecutionStatus.ERROR, ...)
```

`_setup_turn` 内部有三步可能失败：`parse_message` → `_start_turn`（含 `_ensure_session`）→ `_save_user_message`。但所有非 `ValidationError` 的失败都走同一条路：原始异常只进了日志，返回的 `ExecutionResult` 只有笼统的 `"Error setting up execution context"`，错误码统一是 `"SESSION_ERROR"`。

**影响**: 前端无法区分"LLM 格式解析失败"、"DB 连接断开导致 start_turn 失败"和"save_message 写入失败"。排障时只能翻服务端日志。

**修复方案**: `_setup_turn` 把原始异常挂在返回值上（或定义 `TurnSetupError(BrocaError)` 带着原始 cause re-raise），`execute()` 能据此区分错误类型。

---

### 1.6 `_finalize_turn` 的 status 映射丢失信息

**文件**: `broca/loop_engine/engine.py`
**位置**: `_finalize_turn()` 的 `save_turn_end` 调用

```python
saved = await self.session_manager.save_turn_end(
    ...
    status=(
        "completed" if result.status == ExecutionStatus.COMPLETED else "error"
    ),
    ...
)
```

所有非 COMPLETED 的状态（ABORTED、ERROR、DEAD_LOOP、LIMIT_EXCEEDED、SKIPPED）在 DB 里统一存为 `"error"`。

**影响**: Web 后端从 DB 读 turn 状态时，无法区分"用户主动中止"和"LLM 调用失败"。前端如果基于 DB 状态做 UI 分支（比如显示"已中止" vs "出错了"），做不到。

**修复方案**: `status` 字段直接存 `result.status.value`（已经是合法字符串），而不是二元映射。

---

## 二、设计问题（P1）

### 2.1 双初始化路径 + ABC 签名失效

**文件**: `broca/loop_engine/engine.py` + `broca/components/loop_engine.py`

**问题链**：

1. **`__init__` 做了"部分初始化"**：
   ```python
   def __init__(self, agent_ref=None, llm_client=None, ...):
       self.abort_event = asyncio.Event()
       ...
       if agent_ref is not None:
           self._do_initialize(agent_ref=agent_ref, ...)
       # _ensure_strategies() 是 async 的，这里没调
       # 策略要到首次 execute() 才初始化
   ```

2. **`initialize()` 用 `**kwargs` 吞掉 ABC 签名**：
   ```python
   # ABC 声明了 10+ 个具名参数
   # 实现:
   async def initialize(self, **kwargs: Any) -> None:  # type: ignore[override]
       self._do_initialize(**kwargs)
   ```
   `**kwargs` + `# type: ignore` 让 ABC 的参数声明**完全不起类型检查作用**。

3. **ABC 声明了引擎不用的参数**：`context_compressor` 和 `memory_manager` 在 `_do_initialize` 里被 `del` 掉（它们属于 hook 层），但 ABC 签名里仍然声明了——是"为了不让调用方改代码而保留的谎言"。

4. **同一概念三个名字**：
   - ABC: `permission_provider`
   - `__init__`: `tool_permission_manager`
   - `_do_initialize`: `tool_permission_manager or permission_provider`
   - `agent.py` 调用: `tool_permission_manager=agent.permission_provider`

**影响**: "这个引擎到底怎么初始化"需要读三个文件才能搞清楚。类型检查器无法验证参数正确性。新开发者容易传错参数名。

**修复方案**:
- ABC `initialize()` 移除 `context_compressor`/`memory_manager`（hook 工厂已负责组装）
- 统一参数名为 `permission_provider`
- `DefaultLoopEngine.initialize()` 改为显式参数（去掉 `**kwargs`）
- `__init__` 的 `tool_permission_manager` 参数改名为 `permission_provider`

---

### 2.2 `LoopEngine` 命名分裂

**文件**: `broca/loop_engine/__init__.py` vs `broca/components/loop_engine.py`

```python
# broca/components/loop_engine.py
class LoopEngine(BaseComponent, ABC): ...   # ABC 接口

# broca/loop_engine/__init__.py
LoopEngine = DefaultLoopEngine               # 具体实现别名
```

同一个名字 `LoopEngine` 在两个包里指向**完全不同的东西**。`agent.py` 的 import 也分裂：

```python
from broca.loop_engine import ExecutionResult, ExecutionStatus  # 数据类
# 类型标注用
from broca.components import LoopEngine  # ABC
```

**影响**: 阅读代码时看到 `LoopEngine` 不确定指的是 ABC 还是具体类。`isinstance` 检查、注册表查找、类型标注都可能用错。

**修复方案**: `broca/loop_engine/__init__.py` 的别名改为 `ConcreteLoopEngine` 或直接移除（`agent.py` 实际只从 `broca.loop_engine` 导入了 `ExecutionResult`/`ExecutionStatus`，没导入 `LoopEngine` 别名）。

---


### 2.4 `initialize()` 幂等实现与基类契约矛盾

**文件**: `broca/loop_engine/engine.py` + `broca/components/base.py`

```python
# BaseComponent 契约
class BaseComponent:
    async def initialize(self, **deps) -> None:
        """This method must be idempotent — calling it multiple times
        must not produce side-effects."""

# DefaultLoopEngine 实现
async def initialize(self, **kwargs):
    if self._initialized:
        logger.warning("...injected dependencies are ignored: ...")
        return   # ← 不是幂等，是拒绝
    self._do_initialize(**kwargs)
    await self._ensure_strategies()
```

`BaseComponent` 说 "must not produce side-effects"（暗示再次调用应该安全地重新注入或 no-op），但 `DefaultLoopEngine` 是**拒绝重新初始化**（直接 return + warning）。

**影响**: 如果 `ComponentRegistry` 因 scope_key 未变而复用缓存实例，然后 `Agent.create()` 再次调用 `initialize()` 传入新依赖——这些依赖会被**静默丢弃**，但日志只是 warning 不是 error，极易被忽略。

**修复方案**: 已经初始化时应该 `raise`（fail-fast），而不是 silently ignore。

---

### 2.5 `agent.run()` 在引擎外部设置可变状态

**文件**: `broca/agent.py` `run()` 方法

```python
# 设置
self.execution_engine.allowed_tools = allowed_tools
self.execution_engine.namespace = namespace
try:
    return await self.execution_engine.execute(message, max_steps, from_agent)
finally:
    self.execution_engine.allowed_tools = None
```

`allowed_tools` 和 `namespace` 是引擎上的**可变属性**，由调用方在 `execute()` 前后手动设置/清理。这绕过了 `execute()` 的参数列表。

**影响**:
- 引擎的 `execute()` 签名不接受 `allowed_tools`/`namespace`，但实际行为依赖它们——**接口语义不完整**
- 如果 `execute()` 内部 re-entrantly 调用自己（目前不会，但未来可能），状态会被内层覆盖
- 如果 `run()` 的 `try` 块在 `execute()` 返回前被外部 cancel（`asyncio.CancelledError`），`finally` 仍然会执行，但 `execute()` 内部可能已经用 `allowed_tools` 做了决策

**修复方案**: 把 `allowed_tools` 和 `namespace` 作为 `execute()` 的参数传入，去掉引擎上的可变属性。

---

### 2.6 `RetryLLMStrategy._stream_once` 从 LLMClient 实例属性偷读 token 数

**文件**: `broca/loop_engine/strategies/retry_llm.py`
**位置**: `_stream_once()` 的返回值

```python
return LLMCallResult(
    message=message,
    message_id=message_id,
    input_tokens=getattr(self._llm_client, "input_tokens_used", 0),
    output_tokens=getattr(self._llm_client, "output_tokens_used", 0),
    ...
)
```

从 `LLMClient` 的**可变实例属性**上读 token 数，而不是从流式响应的 usage 信息里取。

**影响**:
- 如果 LLM client 在两次调用之间被其他代码（并行 sub-agent）修改了这些属性，token 数会**错乱**
- 在 `asyncio.wait_for` 超时重试场景下，第一次调用的 token 会被第二次调用覆盖——`LLMCallResult` 里的 token 数不代表这次调用的真实消耗
- 策略本应"side-effect free"，但从外部对象读可变状态违反了这一原则

**修复方案**: LLM client 的 `get_stream_response` 应在 yield 的最后一个 chunk 或返回值中携带 usage 信息；策略从返回值里取 token 数。

---

## 三、小问题（P2）

### 3.1 `ExecutionResult` 是普通 class 而非 dataclass

**文件**: `broca/components/loop_engine.py`

`ExecutionResult` 用 `__init__` 手动定义，有 `to_dict()` 和 `__str__`。而同包的 `TurnContext`/`StepContext`/`LLMCallResult` 都用 `@dataclass`。风格不一致。

### 3.2 `_make_chunk_handler` / `_make_error_handler` 每个 step 都创建新闭包

**文件**: `broca/loop_engine/engine.py`，`_execute_step()` 内

```python
llm = await self._llm_strategy.call(
    ...
    on_chunk=self._make_chunk_handler(),   # 每次 step 创建新闭包
    on_error=self._make_error_handler(),
    ...
)
```

每个 step 都创建两个新闭包对象。功能上无问题（闭包捕获的 `self` 不变），但可以提升到 turn 级别只创建一次。

### 3.3 `SnapshotHook._ensure_manager` 懒加载失败只打 `warning`

**文件**: `broca/loop_engine/hooks/snapshot_hook.py`

```python
except Exception as e:
    logger.warning(f"Snapshot tracking unavailable, disabling: {e}")
    self._snapshot_manager = None
```

Snapshot tracking 默认开启（`enable_snapshot_tracking=True`），初始化失败意味着用户**丢失 undo/redo 能力**而只收到一条 warning 日志。应该用 `logger.error`。

### 3.4 `_do_initialize` 里 `tool_mapping=None` 静默降级为空 dict

```python
self.tool_mapping = tool_mapping if tool_mapping is not None else {}
```

如果 Registry 路径没传 `tool_mapping`（比如新组件忘了传），引擎能正常运行但**没有任何工具可用**——没有 warning 也没有 error。

### 3.5 `RetryLLMStrategy.call()` 的 `while errors < self._max_errors` 循环缺少最终 fallback

```python
while errors < self._max_errors:
    # ... 各种异常处理，有些 continue，有些 raise/return ...

return LLMCallResult(
    success=False, error_code="LLM_ERROR", error_message="Too many LLM errors"
)
```

这个 fallback return 在 `while` 循环正常结束后执行。但循环内的各种分支（`raise`、`return`、`continue`）使得正常退出循环的路径非常窄——实际上只有"非 rate-limit 的 `LLMError` 重试耗尽后 raise"和"所有 continue 路径最终 `errors >= max_errors`"两种。如果 `self._max_errors` 被设为 0（`_resolve` 允许任意正整数，但如果 config 传了 `0`……等等，`_resolve` 检查 `isinstance(value, (int, float)) and not isinstance(value, bool)`，`0` 会通过），`while 0 < 0` 直接跳过循环，走到 fallback return——行为是合理的，但缺少注释说明。

---

## 四、应该提炼为 Hook 但未提炼的逻辑

当前 hook 覆盖了：**快照**（SnapshotHook）、**广播**（LifecycleBroadcastHook）、**死循环检测**（DeadLoopHook）、**压缩+记忆**（CompressionMemoryHook）。

以下是引擎内嵌的、属于"副作用/可选行为"的逻辑，按适合程度排序：

### 4.1 `_truncate_last_assistant_message_with_tool_calls` → 适合提炼

**文件**: `engine.py` `_finalize_turn()` 内

```python
if result.status == ExecutionStatus.ABORTED:
    await self._truncate_last_assistant_message_with_tool_calls()
```

**现状**: 引擎在 turn 结束时根据状态码做 context 清理——删除末尾的 assistant tool-call 消息。这是一个**状态驱动的副作用**，不是核心编排逻辑。

**为什么适合做 hook**:
- 只在 `ABORTED` 状态下触发，是条件性行为
- 操作对象是 `context`（conversation history），不操作 DB
- `TurnContext` 已有 `result`（引擎在 dispatch 前设好）、`turn_id`、`agent_id`
- hook 需要 `context` 引用——`CompressionMemoryHook` 已经在构造函数里接收了 `context`，模式一致
- 提炼后引擎的 `_finalize_turn` 更薄：`hooks → save_turn_end → hooks`，纯粹是"持久化 + 分发"

**建议**: 新建 `ContextCleanupHook`（或并入现有的某个 hook），在 `on_turn_end` 里检查 `ctx.result.status == ABORTED` 然后执行 truncate。

---

### 4.2 `_check_write_ops` → 适合移到 SnapshotHook

**文件**: `engine.py` `_execute_step()` 内

```python
step_ctx.has_write_ops = self._check_write_ops(step_ctx.tool_calls)
```

```python
def _check_write_ops(self, tool_calls):
    if not tool_calls or self.tool_executor is None:
        return False
    return any(
        not self.tool_executor.is_readonly_tool(tc.function.name) for tc in tool_calls
    )
```

**现状**: 引擎在 `on_step_start` 分发前计算 `has_write_ops` 并存入 `StepContext`，唯一的消费者是 `SnapshotHook.on_step_start`（决定是否获取快照锁）。

**为什么适合移到 hook**:
- 唯一的读取者是 `SnapshotHook`，其他 hook 和策略都不读 `has_write_ops`
- 计算依赖 `tool_executor.is_readonly_tool()`——这是 tool 层的知识，不是引擎的编排逻辑
- 如果移到 `SnapshotHook.on_step_start`，hook 自己检查 `ctx.tool_calls` + `tool_executor`，引擎就不需要知道"什么是写操作"
- `SnapshotHook` 的构造函数可以加一个 `tool_executor` 参数（或 `tool_mapping`）

**注意事项**: 需要给 `SnapshotHook` 注入 `tool_executor` 或 `tool_mapping` 引用。目前 hook 工厂的 `build_default_hooks` 不传这些——需要扩展。

---

### 4.3 `on_llm_call_completed`（token 统计上报）→ 边际适合

**文件**: `engine.py` `_execute_step()` 内

```python
await self.agent_ref.on_llm_call_completed(llm.input_tokens, llm.output_tokens)
```

**现状**: 引擎在每次成功的 LLM 调用后，回调 `agent_ref` 更新 token 统计。注释说"Token accounting stays in the engine (strategies stay side-effect free)"。

**为什么"边际"适合**:
- `StepContext` 已有 `llm_input_tokens` / `llm_output_tokens` 字段（引擎在调用 `on_step_end` 前填好）
- 一个 `StatsHook.on_step_end` 可以读这些字段并上报
- **但**：它需要 `agent_ref`（或至少 `on_llm_call_completed` 方法），而 hook 的构造参数里目前没有 `agent_ref`
- 如果加 `agent_ref` 到 hook 构造参数，hook 就不再是"纯副作用"——它依赖了 agent 的行为

**建议**: 当前一行代码放在引擎里也可以接受。如果未来统计需求变复杂（比如按模型分维度统计、写 Prometheus），再提炼为 hook。

---

### 4.4 `_send_execution_error`（pre-turn 错误广播）→ 可考虑但不紧迫

**文件**: `engine.py` `execute()` 的异常处理分支

```python
except ValidationError as e:
    await self._send_execution_error(e, "VALIDATION_ERROR")
except asyncio.CancelledError:
    ...
except BrocaError as e:
    await self._send_execution_error(e, "BROCA_ERROR")
except Exception as e:
    await self._send_execution_error(e, "UNKNOWN_ERROR")
```

**现状**: 当 turn 建立之前就出错（parse 失败、DB 连接断开），引擎直接调 `communicator.send_error`。`LifecycleBroadcastHook` 只覆盖 turn 生命周期内的事件（`on_turn_start` 到 `on_turn_finalized`），不覆盖 turn 建立前的错误。

**为什么不太适合做 hook**:
- 此时 `TurnContext` 不存在（`_setup_turn` 失败返回 None），没有标准的 hook context 可传
- 需要定义一个新的 hook 回调签名（如 `on_setup_error(error, code)`），只有 4 个调用点
- 代码量小（一个 `if interactive: communicator.send_error(...)` ）
- 提炼的收益 < 引入新回调签名的复杂度

**建议**: 保持现状。如果未来 pre-turn 错误处理变复杂（比如要重试、要通知多个订阅者），再考虑。

---

### 4.5 `_on_chunk` / `_on_error` 流式广播回调 → 不适合做 hook

**文件**: `engine.py` `_make_chunk_handler()` / `_make_error_handler()`

**现状**: 引擎创建闭包回调传给 LLM 策略，策略在流式读取时调用这些回调来广播 content/reasoning/tool_call 事件。

**为什么不适合做 hook**:
- LLM 策略的接口只接受 `on_chunk: Callable[[dict], Awaitable[None]]`——通用回调，不认识 hook
- 如果让 `LifecycleBroadcastHook` 提供 `on_chunk`，hook 需要被传入策略——破坏了策略的接口设计（策略只依赖 `LLMClient`）
- 每个 token 都 dispatch 到 N 个 hook 代价太高（一个 LLM 响应可能有几百个 content chunk）
- 当前引擎直接调 `communicator` 是最短路径

**建议**: 保持现状。这是策略接口的固有约束，不是引擎的设计失误。

---

### 4.6 引擎内嵌广播 vs LifecycleBroadcastHook 的边界模糊

**现状**: 引擎有 6 处直接调用 `self.communicator.*`：

| 行号 | 调用 | 场景 |
|------|------|------|
| 392 | `send_error` | `_execute_round` 中 `BrocaError` |
| 497 | `send_tool_call` | `process_tool_call_result` 广播工具结果 |
| 702 | `send_agent_response` | `_on_chunk` 流式内容 |
| 717 | `send_tool_call` | `_on_chunk` tool_call 首见 |
| 737 | `send_error` | `_on_error` LLM 错误 |
| 781 | `send_error` | `_send_execution_error` |

其中 #2（`process_tool_call_result` 里的 `send_tool_call`）比较值得注意——`LifecycleBroadcastHook` 负责了 turn/step 级别的生命周期广播，但**工具结果级别的广播**留在引擎里。这不是"忘记提炼"，而是 `process_tool_call_result` 同时做了 DB 持久化 + 广播 + context 更新三件事，是一个原子操作，拆开会引入事务一致性问题。

**建议**: 保持现状，但在 `LifecycleBroadcastHook` 的文档里明确说明"工具结果级广播由引擎的 `process_tool_call_result` 负责，不在本 hook 范围"。

---

### 4.7 缺失的 hook：步骤计时 / 性能剖析

**现状**: 没有任何机制记录每个 step 的耗时（LLM 调用时间、工具执行时间）。排障时只能靠日志时间戳手动计算。

**建议**: 如果性能调优是需求，可以加一个 `ProfilingHook`，在 `on_step_start` 记录 `time.monotonic()`，在 `on_step_end` 计算差值并 `logger.info` 或写入 `ctx.data`。当前不紧急。

---

## 五、持久化逻辑为什么不适合提炼为 Hook

引擎里有 8 组 DB 写入操作，占了引擎代码量的 ~40%。直觉上它们像是"副作用"，适合做 hook。但逐一分析后，结论是：**持久化应该留在引擎，正确的扩展点是 `SessionManager` 组件而非 hook。**

### 5.1 引擎的全部持久化操作

| # | 方法 | DB 操作 | context 操作 | 在生命周期中的位置 |
|---|------|---------|-------------|-------------------|
| A | `_ensure_session` | `create_session()` | — | turn 前（prerequisite） |
| B | `_start_turn` | `start_turn()` | — | turn 前（prerequisite） |
| C | `_save_user_message` | `save_message()` | `add_message()` | `_setup_turn` 内 |
| D | `_save_response` | `save_agent_response()` | `add_message()` | step 内，LLM 调用后 |
| E | `process_tool_call_result` | `save_tool_call()` + `save_message()`(extra) | `add_message()` ×2 | step 内，工具执行后 |
| F | `_persist_step_start` | `save_message()`(STEP_START) | — | step 内，`on_step_start` 后 |
| G | `_persist_step_end` | `save_message()`(STEP_END) | — | step 内，`on_step_end` 后 |
| H | `_finalize_turn` | `save_turn_end()` | `truncate...()`(abort时) | turn 结束后 |

### 5.2 为什么不能做成 Hook——四个根本原因

**原因 1：失败语义不同**

Hook 失败是**非致命的**——`_dispatch` 捕获所有异常只打 warning，引擎继续运行：

```python
async def _dispatch(self, method, ctx):
    for hook in self._hooks:
        try:
            await getattr(hook, method)(ctx)
        except Exception as e:
            logger.warning(f"Hook ... failed: {e}")  # 吞掉，继续
```

但持久化失败是**致命的**——引擎用返回值决定后续流程：

```python
# _save_response 失败 → 整个 step 标记 ERROR，不执行工具
if not await self._save_response(step_ctx.response):
    step_ctx.status = ExecutionStatus.ERROR
elif step_ctx.tool_calls:
    ...  # 只有 response 保存成功才执行工具
```

如果 `_save_response` 变成 hook，hook 失败了 `_dispatch` 会吞掉异常，引擎**看不到失败**，会继续执行工具——DB 里没有 response 记录但工具已经跑完了，状态不一致。

要让 hook 能表达"我失败了，请停止"，只能靠修改 `ctx.status`（像 `DeadLoopHook` 那样）。但 `_dispatch` 在 `for hook in self._hooks` 循环里按序执行——如果持久化 hook 排在第 2 位并设置了 `ctx.status = ERROR`，排在第 3 位的 hook 仍然会执行（`_dispatch` 不检查中间状态）。需要改 `_dispatch` 的语义，影响所有现有 hook。

**原因 2：DB 写入和 context 更新是原子操作**

看 `_save_response`：

```python
async def _save_response(self, response) -> bool:
    message_id = getattr(response, "message_id", None)
    if not await self.session_manager.save_agent_response(...):
        return False          # DB 写入失败
    await self.context.add_message(response, message_id)  # context 更新
    return True
```

DB 写入和 context 更新**必须同时成功或同时不执行**。如果拆成"hook 写 DB + 引擎更新 context"：
- hook 写 DB 成功但被 `_dispatch` 认为"可能失败了"（比如 hook 内部 timeout 但 DB 实际写入了）→ 引擎不更新 context → **context 和 DB 不一致**
- hook 写 DB 失败 → 引擎不更新 context → 一致 ✓

`process_tool_call_result` 更复杂——它在一个方法里做了 4 件事：

```python
async def process_tool_call_result(self, tool_call, tool_result) -> bool:
    # 1. 广播到前端
    await self.communicator.send_tool_call(...)
    # 2. DB: save_tool_call
    await self.session_manager.save_tool_call(...)
    # 3. DB: 读回刚写的 message（为了 format）
    message = await self.session_manager.message_service.get(message_id)
    # 4. context: add formatted result
    await self.context.add_message(self.context.format_tool_call_result(message), message_id)
    # 5. 可能的 extra context messages (images etc.)
    for extra in tool_result.extra_context_messages:
        await self.session_manager.save_message(...)
        await self.context.add_message(...)
```

步骤 2→3 有**读依赖**（刚写入的 message 要读回来做 format），步骤 4 依赖步骤 3 的结果。这不是"写一行 DB"能拆的——它是一个多步事务。

**原因 3：顺序保证**

引擎保证的持久化顺序：

```
save_user_message → [step: save_response → save_tool_call × N → STEP_START → STEP_END] → save_turn_end
```

这个顺序是 undo/redo 正确性的基础——`RevertService` 依赖 STEP_START/STEP_END 行来重建快照。如果持久化分散到多个 hook，顺序取决于 hook 的注册顺序和 `_dispatch` 的调用时机。比如：
- `SnapshotHook.on_step_start` 计算了 `step_start_snapshot`
- 引擎在 `on_step_start` 之后写 STEP_START 行（包含 snapshot hash）
- 如果"持久化 hook"也在 `on_step_start` 里写，它排在 SnapshotHook 前面就读不到 snapshot hash

**原因 4：`SessionManager` 已经是持久化的扩展点**

组件架构里，`SessionManager` 是一个可插拔组件（registry 注册，默认 `SQLSessionManager`）：

```python
# defaults.py
SessionManager: "broca.session.session_manager:SQLSessionManager"
```

如果要换持久化后端（比如事件溯源、内存模式用于测试），正确做法是：

```python
registry.set_override(SessionManager, MyEventSourcingSessionManager)
```

引擎代码不用改一行。再加一个"持久化 hook"就是**同一个关注点的第二个扩展点**——使用者会困惑：我到底该换 `SessionManager` 还是加一个 hook？

### 5.3 逐项分析：哪些"看起来像"可以提炼

| 操作 | 能提炼吗 | 理由 |
|------|---------|------|
| A. `_ensure_session` | ❌ | Turn 的前置条件，此时连 `TurnContext` 都没有，没有 hook 可挂载 |
| B. `_start_turn` | ❌ | 同上。且 `turn_id` 的返回值是后续所有操作的 key |
| C. `_save_user_message` | ⚠️ 理论上可以 | `on_turn_start` hook 可以写 DB。但 `message_id` 的返回值被引擎用来构建 `TurnContext`——hook 需要把 `message_id` 写回 `ctx`（通过 `ctx.message_id` 字段），形成隐式契约。且 DB 写入失败需要阻止 turn 继续（和原因 1 的失败语义问题） |
| D. `_save_response` | ❌ | DB 写入 + context 更新是原子操作（原因 2）。失败必须阻止后续工具执行（原因 1） |
| E. `process_tool_call_result` | ❌ | 4 步事务（广播→DB 写→DB 读→context 更新），不可拆分 |
| F. `_persist_step_start` | ⚠️ 最接近可以 | 只写一行 DB，不更新 context。但 snapshot hash 由 `SnapshotHook` 在 `on_step_start` 里计算，持久化必须在 SnapshotHook **之后**——需要严格的 hook 顺序保证 |
| G. `_persist_step_end` | ⚠️ 同 F | 同理，依赖 `SnapshotHook.on_step_end` 先计算 patch |
| H. `save_turn_end` | ❌ | 引擎的文档明确写了"must stay in the engine: hooks have no session_manager and the web backend reads the persisted turn status"。这是外部系统（web 后端）依赖的最终状态写入 |

**结论**：只有 F 和 G（STEP_START/STEP_END 行写入）在技术上最接近可以做成 hook，但即便如此也需要解决"hook 顺序依赖"（必须在 SnapshotHook 之后）和"失败语义"（写入失败是否需要阻止 turn 继续）两个问题。收益（引擎少 ~20 行代码）不抵风险。

### 5.4 那引擎"太胖"的问题怎么解？

引擎有 ~500 行代码，其中持久化相关 ~200 行。如果觉得引擎太胖，有两条路：

**路线 A：提取 `TurnPersistenceService`（推荐）**

把纯 DB 操作提取到一个内部 service 类，不是 hook：

```python
class TurnPersistenceService:
    """Engine-internal service that encapsulates all DB writes for one turn."""
    
    def __init__(self, session_manager, context, agent_id, turn_id, ...):
        ...
    
    async def save_user_message(self, ...) -> Optional[str]: ...
    async def save_response(self, ...) -> bool: ...
    async def save_tool_result(self, ...) -> bool: ...
    async def persist_step_start(self, ...) -> bool: ...
    async def persist_step_end(self, ...) -> bool: ...
    async def save_turn_end(self, ...) -> bool: ...
```

- 引擎变成：编排 + 调用 service 方法
- 持久化逻辑集中在一个类里，引擎代码量减半
- **不是 hook**——引擎直接 `await self._persistence.save_response(...)`，返回值仍然能控制流程
- 可测试性提升：mock 一个 `TurnPersistenceService` 就能测引擎的编排逻辑
- 不引入新的扩展点（`SessionManager` 仍然是持久化后端的扩展点）

**路线 B：保持现状**

引擎直接持有 `session_manager` 并调用。代码多但直白，"DB 写入在哪里发生"一目了然（都在引擎里）。

两条路都不需要改 hook 系统。

---

## 六、架构层面的观察（非 bug，但值得记录）

### 6.1 引擎仍然持有 `communicator` 引用

重构的目标是让引擎变成"纯编排器"，广播全部委托给 `LifecycleBroadcastHook`。但引擎仍然：
- 持有 `self.communicator`
- 在 6 处直接调用 `self.communicator.*`
- 构造 `_on_chunk` / `_on_error` 闭包时引用 `self.communicator`

前两个是因为"工具结果广播"和"pre-turn 错误广播"确实留在引擎（见 4.4、4.6）。第三个是 LLM 策略接口的约束。所以 `communicator` 依赖是**合理的残留**，不是遗漏。但如果未来 LLM 策略接口改为接受 hook 而非回调，这个依赖就可以彻底移除。

### 6.2 `agent_ref` 的用途比 `AgentReference` 协议声明的宽

`AgentReference` 协议声明了 5 个成员：`agent_id`、`session_id`、`turn_id`（read-write）、`last_context_length`、`on_llm_call_completed`、`ask_for_permission`、`ask_for_tool_permission`。

但引擎实际只用到了：
- `agent_ref.agent_id`（初始化时）
- `agent_ref.turn_id`（读写）
- `agent_ref.on_llm_call_completed()`（token 统计）
- `agent_ref` 作为 `ToolCallContext.agent`（工具调用上下文）

`ask_for_permission` / `ask_for_tool_permission` 引擎**完全不用**——它们是 `ToolExecutor` 需要的，但被放进了 `AgentReference` 协议里。这意味着 `AgentReference` 协议比引擎实际需要的面更宽。

### 6.3 `Context` 对象同时被引擎和 hook 直接操作

引擎调 `context.add_message()` 7 次，`CompressionMemoryHook` 调 `context_compressor.check_and_compress(context=...)` 也间接操作 context。两者对同一个 `Context` 实例的并发访问没有同步机制。当前设计中引擎是串行的（一个 step 完成才开始下一个），所以实际不会并发——但如果未来引入 step 级并行（比如"speculative execution"），这里会成为隐患。

### 6.4 `compressor_context.py` 放错了包

**文件**: `broca/loop_engine/compressor_context.py`

**现状**: 这个模块是一个**协议适配工厂**——把 agent 级依赖（`agent_ref`、`config`、`communicator`、`session_manager`）打包成 `CompressorContext` 协议的实现对象。它被放在 `broca/loop_engine/` 包下。

**为什么放错了**:

1. **历史原因**：它原本是 `DefaultLoopEngine._build_compressor_context()` 方法。引擎瘦身时把它提取为模块级函数，"就近"放在了引擎的包目录里。但"曾经属于引擎"不等于"应该待在引擎的包里"。

2. **消费者跨子系统**：
   ```
   broca/loop_engine/hooks/compression_hook.py  ← 在 loop_engine 内部 ✓
   broca/commands/builtin/compact/__init__.py   ← 命令系统，和 loop 无关 ✗
   broca/agent.py                               ← 顶层调用方
   ```
   `/compact` 命令 `from broca.loop_engine.compressor_context import build_compressor_context`——命令系统（高层功能）依赖执行引擎（底层组件）的内部模块，**依赖方向反了**。

3. **离协议定义太远**：`CompressorContext` 协议定义在 `broca/components/protocols.py`。构建协议实现的工厂离协议定义跨了两个包。

4. **模块名和包名不匹配**：`loop_engine/compressor_context.py`——"压缩上下文"和"循环引擎"在概念上无关联。读者看到 `broca.loop_engine.compressor_context` 会困惑：为什么压缩相关的东西在 loop 引擎里？

**正确的放置位置**（按优先级）：

| 方案 | 路径 | 理由 |
|------|------|------|
| A（推荐） | `broca/components/compressor_context_factory.py` | 协议在 `components/protocols.py`，工厂和协议放一起。消除 `commands → loop_engine` 的反向依赖 |
| B | `broca/context_compressor/context_factory.py` | 放在消费者（compressor）旁边。但会让 `context_compressor` 包依赖 `agent_ref`/`communicator`/`session_manager`，引入新的跨包依赖 |
| C（最小改动） | 保持在 `loop_engine/`，但把 `commands/compact` 的 import 改为通过 `agent.py` 暴露的接口间接获取 | 不移动文件，只改 import 路径 |

**影响**: 移动文件 + 更新 4 处 import（`agent.py`、`commands/compact`、2 个测试文件）。`protocols.py` 的 docstring 里有一句引用 `loop_engine.compressor_context.build_compressor_context()` 也需要更新。

---

## 修复优先级建议

| 优先级 | 编号 | 改动量 | 风险 | 涉及文件 |
|--------|------|--------|------|----------|
| **P0** | 1.1 | 3 行 | 无 | engine.py |
| **P0** | 1.2 | ~15 行 | 低 | errors/, engine.py |
| **P0** | 1.3 | 2 行 | 无 | compression_hook.py |
| **P0** | 1.4 | ~5 行 | 无 | parallel_tool.py |
| **P0** | 1.5 | ~20 行 | 低 | engine.py |
| **P0** | 1.6 | 2 行 | 低（需确认前端兼容） | engine.py |
| **P1** | 2.1 | ~40 行 | 中 | components/loop_engine.py, engine.py, agent.py |
| **P1** | 2.2 | ~5 行 | 低 | loop_engine/__init__.py |
| **P1** | 2.3 | ~10 行 | 低 | factory.py, agent.py |
| **P1** | 2.4 | ~3 行 | 低 | engine.py |
| **P1** | 2.5 | ~20 行 | 中 | engine.py, agent.py |
| **P1** | 2.6 | 取决于 LLMClient 改动 | 高 | retry_llm.py, llm_client |
| **P2** | 3.1 | ~15 行 | 无 | components/loop_engine.py |
| **P2** | 3.2 | ~5 行 | 无 | engine.py |
| **P2** | 3.3 | 1 行 | 无 | snapshot_hook.py |
| **P2** | 3.4 | ~3 行 | 无 | engine.py |
| **P2** | 3.5 | 注释 | 无 | retry_llm.py |
| **Hook** | 4.1 | ~30 行（新 hook 文件 + 工厂更新） | 低 | 新文件, hooks/factory.py, engine.py |
| **Hook** | 4.2 | ~20 行 | 低 | snapshot_hook.py, hooks/factory.py, engine.py |
| **Hook** | 4.3 | 暂不做 | — | — |
| **Hook** | 4.4 | 暂不做 | — | — |
| **Hook** | 4.7 | ~20 行（新 hook） | 无（可选） | 新文件 |
| **架构** | 6.4 | ~10 行（移文件 + 改 4 处 import） | 低 | compressor_context.py, agent.py, commands/compact, tests |

**推荐执行顺序**: P0 全部 → P1（跳过 2.6）→ P2 → Hook（4.1 + 4.2）→ 6.4（移文件）→ 其余可选
