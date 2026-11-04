# Broca 模块 Code Review 修复计划

## 概述

- **目标**：修复两轮 Code Review（核心模块 + 通讯模块）发现的全部问题，按优先级分阶段推进
- **背景**：Review 覆盖了 `broca/` 下的 errors、components、loop_engine、agent、session、communication 等核心模块，共发现 35+ 个问题（P0×1, P1×6, P2×6, P3×6 核心模块；P0×3, P1×6, P2×3, P3×4 通讯模块）
- **约束条件**：
  - 每个 bug 修复后**必须创建回归测试**（AGENTS.md 要求）
  - SessionManager 改动取**窄范围**策略（仅在 engine 关键路径增加 strict 模式，不全面重构）
  - Communicator ABC **补齐关键方法**（高频调用的 6+ 个），低频方法留 Optional
  - 所有改动保持向后兼容，不改变公共 API 签名（只增不改）

## 相关材料

- `broca/errors/types.py` — ErrorCode / ErrorInfo 定义
- `broca/errors/exceptions.py` — BrocaError 异常继承体系
- `broca/errors/utils.py` — safe_call 装饰器
- `broca/components/errors.py` — ComponentError（需修复继承链）
- `broca/components/communicator.py` — Communicator ABC（需补齐方法）
- `broca/communication/socketio_client.py` — SocketIOClient 实现
- `broca/communication/socketio_server.py` — SocketIOServer 实现
- `broca/loop_engine/engine.py` — DefaultLoopEngine（execute / _setup_turn）
- `broca/loop_engine/strategies/retry_llm.py` — RetryLLMStrategy
- `broca/loop_engine/strategies/parallel_tool.py` — ParallelToolStrategy
- `broca/tools/executor.py` — DefaultToolExecutor
- `broca/tools/tool.py` — Tool 基类 / ToolResult
- `broca/session/session_manager.py` — SQLSessionManager
- `broca/llm.py` — LiteLLMClient
- `broca/agent.py` — Agent 类
- `broca/agent_reference.py` — AgentReferenceAdapter
- `broca/context.py` — Context
- `broca/permission_provider.py` — DefaultPermissionProvider
- `broca/tests/` — 现有测试目录（回归测试写在此处）

## 总体方案

按 5 个阶段推进，优先级从高到低：

1. **Phase 1**：P0 紧急修复（traceback bug + connect 异常路径）— 2 个任务
2. **Phase 2**：错误处理体系一致性 — 4 个任务
3. **Phase 3**：通讯模块修复 — 6 个任务
4. **Phase 4**：核心引擎健壮性加固 — 5 个任务
5. **Phase 5**：清理与收尾 — 6 个任务

Phase 1 → 2 → 3 → 4 → 5 严格顺序执行（后续阶段可能依赖前面阶段的接口变更）。同一 Phase 内的任务可并行。

---

### Phase 1: P0 紧急修复

**目标**：修复两个直接导致功能错误 / 数据错误的 P0 bug

**阶段验收标准**：
- [ ] `ErrorInfo.from_exception(cause=e)` 生成的 `traceback_str` 包含 `e` 的调用栈而非 `BrocaError.__init__` 的栈
- [ ] `SocketIOClient.connect()` 超时和异常路径统一返回 `bool`，不再 raise，`Agent.start()` 的 message loop 不会因连接超时崩溃
- [ ] 新增回归测试通过

#### Task 1.1: 修复 ErrorInfo.from_exception() 的 traceback 获取

- **目标**：修复 `traceback.format_exc()` → `traceback.format_exception()` 的 API 误用
- **步骤**：
  1. 修改 `broca/errors/types.py` 中 `ErrorInfo.from_exception()` 方法：
     ```python
     # 旧代码
     traceback_str=traceback.format_exc() if cause else None,
     # 新代码
     traceback_str=(
         "".join(traceback.format_exception(type(cause), cause, cause.__traceback__))
         if cause else None
     ),
     ```
  2. 在 `broca/tests/` 下创建 `test_error_types.py`，编写回归测试：
     - 测试 `ErrorInfo.from_exception(cause=original_exc)` 中 `traceback_str` 包含 `original_exc` 的堆栈帧（如触发异常的函数名）
     - 测试 `cause=None` 时 `traceback_str` 为 `None`
     - 测试 `BrocaError(cause=e)` 后 `e.info.traceback_str` 包含正确的调用栈
- **预期产出**：修复后的 `types.py` + `test_error_types.py`
- **验收标准**：
  - [ ] 触发一个自定义异常后 `raise ToolError(cause=e)`，`e.info.traceback_str` 包含触发异常的源文件路径和行号
  - [ ] `pytest broca/tests/test_error_types.py` 全部通过
  - [ ] 现有 `pytest broca/tests/` 无新增失败

#### Task 1.2: 统一 SocketIOClient.connect() 的异常处理路径

- **目标**：消除 `connect()` 中 `raise CommunicationError`（超时）与 `return False`（其他异常）的不一致
- **步骤**：
  1. 修改 `broca/communication/socketio_client.py` 的 `connect()` 方法：
     ```python
     async def connect(self, timeout: float = 10.0) -> bool:
         if self.connection_info.connected:
             return True
         self._should_reconnect = True  # NOTE: 临时方案 — Task 5.5 将移除此行，改为仅由 enable_auto_reconnect() 设置
         self._connect_event.clear()
         try:
             headers = {
                 "X-Client-Type": self.client_type,
                 "X-Client-ID": self.client_id,
             }
             if self.user_id:
                 headers["X-User-ID"] = self.user_id
             await self.sio.connect(self.server_url, headers=headers,
                                     transports=["websocket", "polling"])
             await asyncio.wait_for(self._connect_event.wait(), timeout=timeout)
             return True
         except asyncio.TimeoutError:
             logger.error(f"Connection timeout after {timeout}s")
             try:
                 await self.sio.disconnect()
             except Exception:
                 pass
             return False  # ← 不再 raise
         except Exception as e:
             logger.error(f"Failed to connect to server: {e}")
             if self.auto_reconnect:
                 self._reconnect_task = asyncio.create_task(self._reconnect())
             return False
     ```
  2. 删除 `raise` 后面的不可达代码 `return False`（死代码）
  3. 删除 `connect()` 事件处理器中的死代码（`headers` 变量构建后未使用）
  4. 在 `broca/tests/` 下创建 `test_socketio_client_connect.py`，编写回归测试：
     - Mock `AsyncClient` 使 `connect` 超时 → 断言返回 `False` 而非 raise
     - Mock `AsyncClient` 使 `connect` 抛出 `ConnectionRefusedError` → 断言返回 `False`
     - Mock 正常连接 → 断言返回 `True`
- **预期产出**：修复后的 `socketio_client.py` + `test_socketio_client_connect.py`
- **验收标准**：
  - [ ] `connect()` 在所有失败路径（超时 / 网络异常 / DNS 解析失败）均返回 `False`，不抛异常
  - [ ] `Agent.start()` 的 `if not await self.connect()` 分支能正确捕获所有失败场景
  - [ ] `pytest broca/tests/test_socketio_client_connect.py` 通过
  - [ ] 现有 `pytest broca/tests/` 无新增失败

---

### Phase 2: 错误处理体系一致性

**目标**：修复错误分类、传播、结构化方面的 4 个 P1 问题

**阶段验收标准**：
- [ ] `ComponentError` 及其子类可被 `except BrocaError` 捕获
- [ ] Engine `_setup_turn` 关键路径的持久化失败能正确传播异常而非静默降级
- [ ] `ToolResult` 保留 `BrocaError` 的结构化错误信息
- [ ] `pre_execute_check` 的双重调用问题已修复或契约已明确
- [ ] 新增回归测试通过

#### Task 2.1: ComponentError 继承 BrocaError

- **目标**：将 `ComponentError` 纳入 `BrocaError` 继承体系
- **步骤**：
  1. 在 `broca/errors/types.py` 的 `ErrorCode` 中新增：
     ```python
     COMPONENT_ERROR = ("COMPONENT_ERROR", "error", "组件系统错误", None)
     COMPONENT_NOT_FOUND = ("COMPONENT_NOT_FOUND", "error", "组件实现未找到", "请检查组件配置")
     COMPONENT_SCOPE_ERROR = ("COMPONENT_SCOPE_ERROR", "error", "组件作用域错误", None)
     ```
  2. 在 `broca/errors/exceptions.py` 中新增：
     ```python
     class ComponentError(BrocaError):
         default_error_code = ErrorCode.COMPONENT_ERROR
     ```
  3. 修改 `broca/components/errors.py`：
     ```python
     from broca.errors.exceptions import ComponentError as _ComponentError
     from broca.errors.types import ErrorCode

     # 保持原有类名，但改变继承链
     class ComponentNotFoundError(_ComponentError):
         default_error_code = ErrorCode.COMPONENT_NOT_FOUND

     class ComponentScopeError(_ComponentError):
         default_error_code = ErrorCode.COMPONENT_SCOPE_ERROR
     ```
     注意：`ComponentError` 基类移到 `errors/exceptions.py`，`components/errors.py` 只保留两个子类（向后兼容 import 路径）
  4. 在 `broca/errors/__init__.py` 中导出 `ComponentError`
  5. 创建回归测试 `test_component_errors.py`：
     - `pytest.raises(BrocaError)` 能捕获 `ComponentNotFoundError`
     - `ComponentNotFoundError("...").error_code == ErrorCode.COMPONENT_NOT_FOUND`
     - `ComponentScopeError("...").to_user_message()` 返回有意义的消息
- **预期产出**：修改后的 `types.py` / `exceptions.py` / `errors/__init__.py` / `components/errors.py` + 测试
- **验收标准**：
  - [ ] `except BrocaError` 能捕获 `ComponentNotFoundError` 和 `ComponentScopeError`
  - [ ] `from broca.components.errors import ComponentNotFoundError` 的 import 路径不变（向后兼容）
  - [ ] `from broca.errors import ComponentError` 可用
  - [ ] 现有 `test_components_registry.py` 仍通过

#### Task 2.2: SessionManager 关键路径 strict 模式

- **目标**：在 engine `_setup_turn` 的关键持久化操作上启用严格异常传播，同时保持其他调用方的静默降级
- **步骤**：
  1. 修改 `broca/session/session_manager.py` 的 `SQLSessionManager`：
     - `save_message()` 新增 `strict: bool = False` 参数。`strict=True` 时 `except` 块中 `raise` 而非 `return False`
     - `start_turn()` 同样新增 `strict: bool = False`
  2. 修改 `broca/loop_engine/engine.py` 的 `_setup_turn()`：
     ```python
     # _start_turn 中
     turn_id = await self.session_manager.start_turn(self.agent_id, strict=True)
     # _save_user_message 中
     saved = await self.session_manager.save_message(..., strict=True)
     ```
  3. `SQLSessionManager` 的 `strict` 路径抛出 `SessionError`（携带原始异常 cause）：
     ```python
     except Exception as e:
         if strict:
             raise SessionError(f"持久化操作失败: {e}", cause=e) from e
         logger.error(f"Failed to save message: {e}")
         return False
     ```
  4. 创建回归测试 `test_session_manager_strict.py`：
     - Mock DB 操作失败 + `strict=True` → 断言抛出 `SessionError`
     - Mock DB 操作失败 + `strict=False`（默认）→ 断言返回 `False`
     - Engine `_setup_turn` 中 DB 失败 → 断言 `execute()` 返回 `ExecutionStatus.ERROR`
- **预期产出**：修改后的 `session_manager.py` / `engine.py` + 测试
- **验收标准**：
  - [ ] `strict=True` 时 `save_message()` 失败抛出 `SessionError`（带 cause）
  - [ ] `strict=False`（默认）行为不变，仍返回 `False`
  - [ ] 现有所有 SessionManager 调用方（非 engine 路径）行为不变
  - [ ] 现有 `test_session_*` 测试全部通过

#### Task 2.3: ToolResult 保留结构化错误信息

- **目标**：`Tool.execute()` 捕获 `BrocaError` 时将 `ErrorInfo` 附加到 `ToolResult`，而非仅保留字符串
- **步骤**：
  1. 修改 `broca/tools/tool.py` 的 `ToolResult`：
     ```python
     class ToolResult:
         def __init__(self, status, content, extra_context_messages=None, error_info=None):
             ...
             self.error_info = error_info  # ErrorInfo | None
     ```
  2. 修改 `Tool.execute()` 的异常处理：
     ```python
     except BrocaError as e:
         return ToolResult(
             status=ToolStatus.ERROR,
             content=e.to_user_message(),
             error_info=e.info,  # 保留结构化信息
         )
     ```
  3. 修改 `ToolResult.to_dict()` 包含 `error_info`（序列化）：
     ```python
     def to_dict(self):
         d = {"status": self.status, "content": self.content}
         if self.error_info:
             d["error_info"] = self.error_info.to_dict()
         return d
     ```
  4. 修改 `broca/tools/executor.py` 的 `DefaultToolExecutor._execute_with_timeout()`：
     - `except (ToolError, BrocaError)` 分支中，如果 `tool.execute` 已内部捕获（返回 ERROR ToolResult），则直接透传
     - 如果 executor 层自身捕获了异常（timeout 等），构造 `ErrorInfo` 附加到 `ToolResult`
  5. 创建回归测试 `test_tool_result_error_info.py`
- **预期产出**：修改后的 `tool.py` / `executor.py` + 测试
- **验收标准**：
  - [ ] `Tool.execute()` 捕获 `BrocaError` 后，`result.error_info` 非 None 且 `result.error_info.code` 正确
  - [ ] 非 BrocaError 异常（如 `ValueError`）→ `result.error_info` 为 None（向后兼容）
  - [ ] `ToolResult.to_dict()` 在有 `error_info` 时包含 `error_info` 字段
  - [ ] 现有 `test_tool_*` 测试全部通过

#### Task 2.4: 修复 pre_execute_check 双重调用

- **目标**：消除 `pre_execute_check` 对同一 tool call 被调用两次的问题
- **步骤**：
  1. 在 `broca/tools/tool.py` 的 `pre_execute_check` docstring 中增加契约声明：
     ```
     **Contract**: This method MUST be idempotent and side-effect-free.
     It may be called multiple times for the same arguments (e.g. once during
     parallel partitioning and once during execution).
     ```
  2. 修改 `broca/loop_engine/strategies/parallel_tool.py` 的 `_execute_parallel()`：
     - partitioning 阶段调用 `pre_execute_check` 后，将结果缓存到 `context` 的临时 dict 中：
       ```python
       pre_check_cache = {}  # local to _execute_parallel
       for index, tool_call in enumerate(tool_calls):
           ...
           if pre_check_fn:
               result = pre_check_fn(tool_call.function.arguments, context)
               pre_check_cache[tool_call.id] = result
               if result:
                   serial_indices.add(index)
       ```
     - 将 `pre_check_cache` 通过 `ToolCallContext` 传递（新增 `pre_check_cache: dict = None` 字段，用完即弃）
  3. 修改 `broca/tools/executor.py` 的 `execute_tool()` #3.5 步骤：
     ```python
     pre_check_msg = None
     if tool is not None and context.pre_check_cache:
         pre_check_msg = context.pre_check_cache.get(tool_call_id)
     if pre_check_msg is None:
         # 缓存未命中（串行执行路径没有 partitioning 阶段），正常调用
         pre_check_fn = getattr(tool, "pre_execute_check", None)
         pre_check_msg = pre_check_fn(arguments, context) if pre_check_fn else None
     ```
  4. 创建回归测试 `test_pre_execute_check_single_call.py`：
     - 创建一个 mock Tool，其 `pre_execute_check` 记录调用次数
     - 通过 `ParallelToolStrategy` 执行 → 断言 `pre_execute_check` 只被调用一次
     - 通过 `SerialToolStrategy` 执行 → 断言 `pre_execute_check` 只被调用一次
- **预期产出**：修改后的 `tool.py` / `parallel_tool.py` / `executor.py` / `tool.py(ToolCallContext)` + 测试
- **验收标准**：
  - [ ] 并行模式下 `pre_execute_check` 对每个 tool call 只被调用一次
  - [ ] 串行模式下 `pre_execute_check` 对每个 tool call 只被调用一次
  - [ ] 权限请求消息（`pre_check_msg` 返回值）正确传递到 `request_permission`
  - [ ] 现有 `test_tool_strategy.py` / `test_parallel_tool.py` 全部通过

---

### Phase 3: 通讯模块修复

**目标**：修复通讯模块的 13 个问题（P0×3 + P1×6 + P2×3 + P3×1 合并）

**依赖**：Phase 1（Task 1.2 `connect()` 修改）+ Phase 2（软依赖 — `CommunicationError` 定义在 errors 模块，若 Phase 2 变更了 `ErrorCode` 枚举则需同步）

**⚠️ 执行注意**：Task 3.1 / 3.2 / 3.3 / 3.5 均修改 `socketio_client.py`，多 agent 并行执行时应**顺序执行**同文件任务以避免合并冲突。

**阶段验收标准**：
- [ ] `_MessageDispatcher` 能路由所有 `MessageType` 枚举值
- [ ] `message_callbacks` 有超时清理机制
- [ ] `send_message()` 最终失败抛 `CommunicationError` 而非原始异常
- [ ] Server 端校验 `client_id` 唯一性
- [ ] `Communicator` ABC 补齐 6+ 关键方法
- [ ] 新增回归测试通过

**Issue 映射**（13 个原始 review issue → 6 个任务）：

| Task | 覆盖的原始 Issue |
|------|-----------------|
| 3.1 | #P0-1 (dispatcher 不完整), #P2-1 (connect 死代码) |
| 3.2 | #P1-1 (callbacks 内存泄漏) |
| 3.3 | #P0-2 (send_message 异常不一致), #P1-2 (subscribe/unsubscribe 不一致) |
| 3.4 | #P0-3 (client_id 冲突), #P1-3 (未知 receiver 无反馈) |
| 3.5 | #P2-2 (CONNECT role 错误), #P3-1 (TTL 注释不一致), #P1-4 (_pending_messages) |
| 3.6 | #P1-5 (ABC 方法缺失), #P2-3 (方法签名不一致) |

#### Task 3.1: 补全 _MessageDispatcher 分发表 + 清理死代码

- **目标**：让所有 `MessageType` 都能被正确路由，移除死代码
- **步骤**：
  1. 修改 `broca/communication/socketio_client.py` 的 `_MessageDispatcher.__init__`：
     - 补全缺失的类型映射：
       ```python
       MessageType.AGENT_ERROR: "agent_error",
       MessageType.AGENT_SYSTEM_MESSAGE: "agent_system_message",
       MessageType.SYSTEM_MESSAGE: "system_message",
       MessageType.STEP_START: "step_start",
       MessageType.STEP_END: "step_end",
       MessageType.CONNECT: "connect",
       MessageType.DISCONNECT: "disconnect",
       MessageType.PING: "ping",
       MessageType.PONG: "pong",
       ```
     - 移除 `_table` 中的 `SUBSCRIBE` 和 `UNSUBSCRIBE` 条目（已被前置 `if` 分支处理，table 中是死代码）
  2. 删除 `connect()` 事件处理器中未使用的 `headers` 变量
  3. 创建/补充测试：遍历 `MessageType` 枚举的每个值，断言 dispatcher 都能路由（不落入 "Unhandled" 分支）
- **预期产出**：修改后的 `socketio_client.py` + 测试
- **验收标准**：
  - [ ] 所有 `MessageType` 枚举值在 `_MessageDispatcher._table` 中有对应条目（SUBSCRIBE/UNSUBSCRIBE 除外，它们走前置分支）
  - [ ] 无 "Unhandled message type" 日志
  - [ ] `connect()` handler 中无死代码

#### Task 3.2: message_callbacks 超时清理

- **目标**：防止 `send_message(callback=fn)` 注册的回调因响应永不到达而内存泄漏
- **步骤**：
  1. 修改 `broca/communication/socketio_client.py`：
     - 新增常量 `MESSAGE_CALLBACK_TIMEOUT: float = 120.0`
     - `message_callbacks` 从 `Dict[str, Callable]` 改为 `Dict[str, Tuple[Callable, float]]`（callback + 注册时间戳）
     - 新增 `_cleanup_expired_callbacks()` 方法：遍历并移除超时条目
     - 在 `send_message()` 中注册 callback 时记录时间戳
     - 在 `message` 事件处理中 pop callback 时只取 tuple 的第一个元素
     - 新增后台清理任务：在 `connect()` 成功后启动 `asyncio.create_task(self._callback_cleanup_loop())`
     - `disconnect()` 时取消清理任务
  2. 创建回归测试：
     - 注册 callback → 模拟 120s 后 → 断言 callback 已被清理
     - 注册 callback → 在超时前收到响应 → 断言 callback 正常触发且被清理
- **预期产出**：修改后的 `socketio_client.py` + 测试
- **验收标准**：
  - [ ] 未收到响应的 callback 在 `MESSAGE_CALLBACK_TIMEOUT` 后被自动清理
  - [ ] 正常收到响应的 callback 不受影响
  - [ ] `disconnect()` 后无残留的后台清理任务

#### Task 3.3: 统一 send_message() 异常类型 + 修复 subscribe/unsubscribe 一致性

- **目标**：`send_message()` 最终失败抛 `CommunicationError`；`subscribe()`/`unsubscribe()` 走统一连接检查路径
- **步骤**：
  1. 修改 `send_message()` 的重试逻辑：
     ```python
     else:
         logger.error(f"Failed to send message after {max_retries} attempts: {e}")
         raise CommunicationError(
             f"Failed to send message after {max_retries} attempts", cause=e
         ) from e
     ```
     删除末尾不可达的 `return ""`
  2. 修改 `subscribe()` / `unsubscribe()`：
     - 保留现有的 `if not self.connection_info.connected: raise` 前置检查
     - 将 `self.sio.emit(...)` 调用包裹在 try/except 中，失败时抛 `CommunicationError`（与 `send_message` 一致）
  3. 创建回归测试
- **预期产出**：修改后的 `socketio_client.py` + 测试
- **验收标准**：
  - [ ] `send_message()` 重试耗尽后抛 `CommunicationError`（非原始 `Exception`）
  - [ ] `except CommunicationError` 能捕获所有 `send_message` 失败场景
  - [ ] `subscribe()` 在 emit 失败时抛 `CommunicationError`

#### Task 3.4: Server 端 client_id 唯一性校验 + 未知 receiver_id 回送错误

- **目标**：防止 client_id 冲突导致消息路由错乱；未知 receiver 时向发送方反馈
- **步骤**：
  1. 修改 `broca/communication/socketio_server.py` 的 `connect` handler：
     ```python
     async with self._lock:
         # 检查 client_id 冲突
         existing_sid = self.client_sids.get(client_id)
         if existing_sid and existing_sid != sid:
             logger.warning(
                 f"Client ID conflict: {client_id} already registered "
                 f"to sid={existing_sid}, new connection sid={sid} takes over"
             )
             # 清理旧连接的映射
             old_info = self.clients.pop(existing_sid, None)
             if old_info:
                 for sub in old_info.subscriptions:
                     if sub in self.subscriptions:
                         self.subscriptions[sub].discard(client_id)
         self.clients[sid] = client_info
         self.client_sids[client_id] = sid
     ```
  2. 修改 `_send_to_client()` 返回 `bool` 表示是否成功路由：
     ```python
     async def _send_to_client(self, client_id: str, data: dict) -> bool:
         sid = self.client_sids.get(client_id)
         if sid is None:
             return False
         await self.sio.emit_to(sid, "message", data)
         return True
     ```
  3. 在 `_process_message()` 中利用发送方的 `sid` 回送错误：
     ```python
     # _process_message 已持有 sender_sid（即 message 来源的 socket id）
     success = await self._send_to_client(receiver_id, message_data)
     if not success:
         await self.sio.emit_to(sender_sid, "error", {
             "type": "routing_failed",
             "receiver_id": receiver_id,
             "message": f"Unknown receiver: {receiver_id}",
         })
     ```
  4. 创建回归测试
- **预期产出**：修改后的 `socketio_server.py` + 测试
- **验收标准**：
  - [ ] 相同 `client_id` 的第二个连接会接管路由，旧连接的映射被清理
  - [ ] 向未知 `receiver_id` 发消息时，发送方能收到 `type="routing_failed"` 的 error 反馈
  - [ ] 现有 `test_socketio_server.py` 测试通过（无新增失败）

#### Task 3.5: 修复 CONNECT 消息 role + TTL 注释 + _pending_messages

- **目标**：修正语义错误和文档不一致
- **步骤**：
  1. 修改 `socketio_client.py` 的 `connect()` handler：
     ```python
     # 旧: MessageProtocol.create_user_message(..., role=USER)
     # 新: 直接构造 Message(role=SYSTEM)
     connect_msg = Message(
         message_type=MessageType.CONNECT,
         role=MessageRole.SYSTEM,
         sender_id=self.client_id,
         data={"content": "Connected to server"},
     )
     await self.send_message(connect_msg)
     ```
  2. 修正 `socketio_server.py` 中 `_cache_pending_message` 的注释：
     ```
     # 旧: 缓存条目有 TTL（600s）
     # 新: 缓存条目 TTL 由 permission_request_ttl(默认90s) / agent_query_ttl(默认300s) 控制
     ```
- **预期产出**：修改后的 `socketio_client.py` / `socketio_server.py`
- **验收标准**：
  - [ ] 连接时发送的 CONNECT 消息 `role == MessageRole.SYSTEM`
  - [ ] 注释与实际 TTL 参数一致

#### Task 3.6: 补齐 Communicator ABC 关键方法

- **目标**：将实际高频调用的方法加到 `Communicator` ABC，让插件开发者有完整契约
- **步骤**：
  1. 修改 `broca/components/communicator.py`，新增以下 abstractmethod：
     ```python
     # ── 高频调用（必须实现） ──
     @abstractmethod
     async def send_agent_response(...) -> str: ...
     @abstractmethod
     async def send_turn_start(...) -> str: ...
     @abstractmethod
     async def send_turn_end(...) -> str: ...
     @abstractmethod
     async def send_task_complete(...) -> str: ...
     @abstractmethod
     async def send_task_error(...) -> str: ...
     @abstractmethod
     async def send_permission_request(...) -> str: ...

     # ── 事件系统（必须实现） ──
     @abstractmethod
     def register_event_handler(self, event_name: str, func: Callable) -> None: ...

     # ── 订阅（必须实现） ──
     @abstractmethod
     async def subscribe(self, subscription: str) -> str: ...
     @abstractmethod
     async def unsubscribe(self, subscription: str) -> str: ...

     # ── 低频方法（非 abstract，提供默认空实现） ──
     async def send_command_result(self, ...) -> str: ...
     async def send_task_start(self, ...) -> str: ...
     async def send_user_answer(self, ...) -> str: ...
     async def send_broadcast(self, ...) -> str: ...
     async def send_agent_system_message(self, ...) -> str: ...
     ```
  2. 方法签名与 `SocketIOClient` 中的对应方法完全一致（参数名、类型、默认值）
  3. 创建测试验证 ABC 完整性：
     - 尝试实例化一个只实现了部分方法的 mock → 应报 `TypeError: Can't instantiate abstract class`
     - `SocketIOClient` 能正常实例化（实现了所有 abstract 方法）
- **预期产出**：修改后的 `communicator.py` + 测试
- **验收标准**：
  - [ ] `Communicator` ABC 包含 10 个 abstract 方法（4 原有 + 6 新增）+ 5 个可选方法
  - [ ] `SocketIOClient` 满足 ABC 全部 abstract 方法
  - [ ] 缺少任何 abstract 方法的子类无法实例化
  - [ ] 现有 `test_component_interfaces.py` 通过（可能需要更新 mock）

---

### Phase 4: 核心引擎健壮性加固

**目标**：修复核心执行引擎和组件的 5 个 P1/P2 问题

**阶段验收标准**：
- [ ] `LiteLLMClient` 无可变实例状态（或已标记 deprecated）
- [ ] `CancelledError` 后 `_finalize_turn` 有防护
- [ ] `Tool.TOOL_RESULT_CACHE_DIR` 使用绝对路径
- [ ] `_save_user_message` 不突变输入参数
- [ ] `Agent._handle_task` 对 `assigner=None` 有防御
- [ ] 新增回归测试通过

#### Task 4.1: 清理 LiteLLMClient 可变实例状态

- **目标**：移除 `input_tokens_used` / `output_tokens_used` 实例属性，消除 singleton 共享风险
- **步骤**：
  1. 修改 `broca/llm.py` 的 `LiteLLMClient`：
     - 删除 `self.input_tokens_used = 0` 和 `self.output_tokens_used = 0`
     - 删除 `_process_chunk` 中对这两个属性的赋值（保留 `yield {"type": "usage", ...}` 事件）
  2. 全局搜索 `input_tokens_used` / `output_tokens_used` 的引用，确认无其他代码依赖这两个属性
  3. **更新 `broca/tests/test_llm.py`**：删除 `test_token_counters_init` 测试方法（~line 110-117）中 `assert client.input_tokens_used == 0` 和 `assert client.output_tokens_used == 0` 断言。改为验证 `vars(client)` 中不存在这两个属性
  4. 如果其他代码有外部引用，改为从 `_process_chunk` 的 `usage` 事件读取
  5. 创建回归测试：两个并发 `get_stream_response` 调用不交叉污染 token 计数
- **预期产出**：修改后的 `llm.py` + 更新的 `test_llm.py` + 新测试
- **验收标准**：
  - [ ] `LiteLLMClient` 实例无可变状态（`vars(client)` 中无 `input_tokens_used`）
  - [ ] token 计数完全通过 stream `usage` 事件传递
  - [ ] `test_llm.py` 已更新（不再断言已移除的属性），全部通过
  - [ ] 现有 `test_llm_strategy.py` 通过

#### Task 4.2: CancelledError 后 _finalize_turn 防护

- **目标**：防止 `CancelledError` 后在已取消的 event loop 上执行 DB 操作
- **步骤**：
  1. 修改 `broca/loop_engine/engine.py` 的 `_finalize_turn` 方法：
     - 在 `_finalize_turn` 内部包裹 `try/except (RuntimeError, asyncio.CancelledError)` 防护
     ```python
     async def _finalize_turn(self, turn_ctx, ...):
         try:
             # ... 现有 DB 操作逻辑 ...
             await self.session_manager.save_turn_end(...)
         except (RuntimeError, asyncio.CancelledError) as e:
             logger.warning(f"_finalize_turn failed (loop may be cancelled): {e}")
             # 不传播异常，避免在已取消的 loop 上进一步失败
     ```
  2. 修改 `execute()` 的 `except asyncio.CancelledError` 分支：
     ```python
     except asyncio.CancelledError:
         logger.info("Execution cancelled by user")
         result = ExecutionResult(status=ExecutionStatus.ABORTED, ...)
         if turn_ctx is not None:
             # 仍尝试 _finalize_turn，但内部已有防护不会抛异常
             try:
                 await self._finalize_turn(turn_ctx, ...)
             except Exception:
                 pass
         return result
     ```
  3. 创建回归测试：mock `CancelledError` 在 `_execute_round` 中抛出 → 断言 `session_manager.save_turn_end` 要么未被调用，要么其异常被捕获并记录日志（不向外传播）
- **预期产出**：修改后的 `engine.py` + 测试
- **验收标准**：
  - [ ] `CancelledError` 后 `execute()` 正常返回 `ExecutionStatus.ABORTED`
  - [ ] 当 `CancelledError` 在 `_execute_round` 中抛出时，`session_manager.save_turn_end` 要么未被调用，要么其异常被 `_finalize_turn` 内部捕获并记录日志（不向外传播）
  - [ ] 现有 `test_loop_engine.py` / `test_engine_event_flow.py` 通过

#### Task 4.3: Tool.TOOL_RESULT_CACHE_DIR 改为绝对路径

- **目标**：缓存目录基于 workspace 而非 CWD
- **步骤**：
  1. 修改 `broca/tools/tool.py`：
     - 删除类属性 `TOOL_RESULT_CACHE_DIR = Path(".broca/tool_result_cache")`
     - 在 `_post_process_result` 中改为从 `context.workspace` 构造路径：
       ```python
       def _get_cache_dir(self, context: ToolCallContext) -> Path:
           workspace = context.workspace or os.getcwd()
           cache_dir = Path(workspace) / ".broca" / "tool_result_cache"
           return cache_dir
       ```
     - `cleanup_tool_result_cache` 函数改为接收 `workspace` 参数
  2. 修改所有调用 `cleanup_tool_result_cache()` 的地方传入 workspace
  3. 创建回归测试：设置不同 CWD 但相同 workspace → 缓存文件写入 workspace 目录
- **预期产出**：修改后的 `tool.py` + 测试
- **验收标准**：
  - [ ] 缓存文件始终写入 `{workspace}/.broca/tool_result_cache/`
  - [ ] `os.chdir()` 到别处后缓存路径不变
  - [ ] 现有 `test_tool_base.py` 通过

#### Task 4.4: _save_user_message 避免突变输入参数

- **目标**：不修改传入的 `message.data` dict
- **步骤**：
  1. 修改 `broca/loop_engine/engine.py` 的 `_save_user_message()`：
     ```python
     async def _save_user_message(self, user_message, message, turn_id, from_agent):
         # 不突变 message.data，而是构造一个新的 data dict
         message_data = dict(message.data) if message.data else {}
         message_data["from_agent"] = from_agent
         if user_message.get("raw_input"):
             message_data["raw_input"] = user_message["raw_input"]

         message_id = f"msg_{uuid.uuid4().hex[:16]}" if from_agent else message.message_id
         saved = await self.session_manager.save_message(
             ..., data=message_data, message_id=message_id, strict=True
         )
         return message_id if saved else None
     ```
  2. 创建回归测试：调用 `_save_user_message` 后断言原始 `message.data` 未被修改
- **预期产出**：修改后的 `engine.py` + 测试
- **验收标准**：
  - [ ] `_save_user_message` 执行后 `message.data` 的原始键值不变
  - [ ] 数据库存储的 `data` 字段包含 `from_agent` 和 `raw_input`

#### Task 4.5: Agent._handle_task 的 assigner=None 防御

- **目标**：`assigner` 为 None 时不尝试发送 task_error
- **步骤**：
  1. 修改 `broca/agent.py` 的 `_handle_task()`：
     ```python
     except Exception as e:
         logger.error(f"Error processing task: {e}")
         if assigner is None:
             logger.error(f"Task {task_id} failed and no assigner to notify")
             return
         result = f"The agent {self.agent_id} failed to finish the task: {e}"
         await self.communicator.send_task_error(task_id, result, receiver_id=assigner)
     ```
  2. 同样对 `TASK_COMPLETE` / `TASK_ERROR` 的正常路径中的 `send_task_complete` 加防御
  3. 创建回归测试
- **预期产出**：修改后的 `agent.py` + 测试
- **验收标准**：
  - [ ] `assigner=None` + 执行失败 → 不抛异常，只 log
  - [ ] `assigner=None` + 执行成功 → 不抛异常
  - [ ] `assigner="agent-123"` + 执行失败 → 正常发送 task_error

---

### Phase 5: 清理与收尾

**目标**：修复 P3 级别问题（代码卫生、死代码、类型标注、文档）

**阶段验收标准**：
- [ ] 所有拼写错误已修正
- [ ] 死代码已移除
- [ ] LLM 异常处理用映射表压缩
- [ ] 新增/修改代码通过 `ruff check` 无错误

#### Task 5.1: Context typo + _check_write_ops 死代码 + send_tool_call 类型标注

- **目标**：修正小问题
- **步骤**：
  1. `broca/context.py`：`session_memeory_path` → `session_memory_path`（两处）
  2. `broca/loop_engine/engine.py`：删除 `_check_write_ops` 方法（已废弃的 no-op stub，grep 确认无外部调用者）
  3. `broca/components/communicator.py`：`send_tool_call` 的 `arguments` 参数类型从 `str` 改为 `Optional[str]`
- **预期产出**：修改后的 3 个文件
- **验收标准**：
  - [ ] `grep -r "memeory" broca/` 无结果
  - [ ] `grep -r "_check_write_ops" broca/` 仅在设计文档中出现
  - [ ] `send_tool_call(arguments=None)` 类型检查通过

#### Task 5.2: LLM 异常处理压缩为映射表

- **目标**：将 `LiteLLMClient.get_stream_response()` 的 11 个 except 块压缩为 2 个（`InvalidRequestError` 单独 + `Exception` 映射循环）
- **⚠️ 关键设计约束**：`ContextWindowExceededError` 和 `ContentPolicyViolationError` 是 `litellm.exceptions.BadRequestError` 的**子类**，因此**不能**使用独立的 `except BadRequestError` 子句（会 shadow 子类）。`InvalidRequestError` 继承自 `openai.BadRequestError`（非 `litellm.exceptions.BadRequestError`），因此可以安全保留为独立 except 子句。
- **步骤**：
  1. **提取 `_classify_request_error` 方法**（前置依赖）：
     - 将 `except InvalidRequestError` 块中现有的内联子分类逻辑（`llm.py:231-251`，检测 model-not-found）提取为 `LiteLLMClient._classify_request_error(self, e, provider, model_name, prefix)` 方法
     - 将 `except BadRequestError` 块中的内联子分类逻辑（检测 auth/api-key 错误）提取为同一方法的一部分
     ```python
     def _classify_request_error(self, e: Exception, provider: str, model_name: str, prefix: str) -> LLMError:
         """子分类 InvalidRequestError / BadRequestError 为更精确的 ErrorCode"""
         error_msg = str(e).lower()
         # InvalidRequestError: 模型不存在/不可用
         if isinstance(e, InvalidRequestError) and "model" in error_msg and (
             "not found" in error_msg or "not exist" in error_msg
             or "not support" in error_msg or "does not exist" in error_msg
         ):
             return LLMError(
                 message=f"模型不可用 (provider: {provider}, model: {model_name}): {e}",
                 error_code=ErrorCode.LLM_INVALID_MODEL,
                 details={"provider": provider, "model": model_name},
                 cause=e,
             )
         # BadRequestError: 某些提供商对无效 API Key 返回 400 而非 401
         if isinstance(e, BadRequestError) and (
             "auth" in error_msg or "api key" in error_msg or "invalid" in error_msg
         ):
             return LLMError(
                 message=f"API Key 认证失败 (provider: {provider}): {e}",
                 error_code=ErrorCode.LLM_AUTH_ERROR,
                 details={"provider": provider, "model": model_name},
                 cause=e,
             )
         # 通用 fallback
         return LLMError(
             message=f"{prefix} (provider: {provider}): {e}",
             error_code=ErrorCode.LLM_ERROR,
             details={"provider": provider, "model": model_name},
             cause=e,
         )
     ```
  2. 在 `broca/llm.py` 模块顶部定义**有序**映射表（**顺序关键**：子类必须在父类之前）：
     ```python
     # NOTE: 映射顺序有严格要求 — 子类必须排在父类前面，否则 isinstance() 会先匹配父类
     # 异常继承关系（litellm）：
     #   ContextWindowExceededError / ContentPolicyViolationError  →  BadRequestError (litellm)
     #   Timeout (litellm)  →  APITimeoutError  →  APIConnectionError
     #   InvalidRequestError → openai.BadRequestError（与 litellm.BadRequestError 无继承关系）
     _EXCEPTION_MAP: list[tuple[type, ErrorCode, str]] = [
         # ── BadRequestError 子类（必须在 BadRequestError 之前）──
         (ContextWindowExceededError,  ErrorCode.LLM_CONTEXT_WINDOW_EXCEEDED,  "对话超出上下文长度限制"),
         (ContentPolicyViolationError, ErrorCode.LLM_ERROR,                    "LLM 内容安全策略拒绝"),
         # ── APIConnectionError 子类（必须在 APIConnectionError 之前）──
         (Timeout,                     ErrorCode.LLM_TIMEOUT,                  "LLM 请求超时"),
         # ── 独立异常（无继承冲突）──
         (AuthenticationError,         ErrorCode.LLM_AUTH_ERROR,               "API Key 认证失败"),
         (BudgetExceededError,         ErrorCode.LLM_QUOTA_EXCEEDED,           "API 额度不足"),
         (RateLimitError,              ErrorCode.LLM_RATE_LIMIT,               "请求频率过高，触发限流"),
         (InternalServerError,          ErrorCode.LLM_SERVICE_UNAVAILABLE,      "LLM 服务暂不可用"),
         (ServiceUnavailableError,     ErrorCode.LLM_SERVICE_UNAVAILABLE,      "LLM 服务暂不可用"),
         (APIConnectionError,          ErrorCode.LLM_SERVICE_UNAVAILABLE,      "无法连接到 LLM 服务"),
         # ── 父类（必须在所有子类之后）──
         (BadRequestError,             ErrorCode.LLM_ERROR,                    "LLM 请求错误"),
     ]
     ```
     注意：`Timeout` 来自 `from litellm.exceptions import Timeout`（即 `litellm.exceptions.Timeout`，继承链 `Timeout → APITimeoutError → APIConnectionError`），非 `asyncio.TimeoutError`。
  3. 替换 11 个 except 块为 **2 个**：
     ```python
     except InvalidRequestError as e:
         # InvalidRequestError 继承自 openai.BadRequestError（非 litellm.BadRequestError），
         # 不会被 except Exception 中的 BadRequestError isinstance 匹配，需独立处理
         raise self._classify_request_error(e, provider, model_name, "LLM 请求参数错误") from e
     except Exception as e:
         for exc_type, code, prefix in _EXCEPTION_MAP:
             if isinstance(e, exc_type):
                 # BadRequestError 需要子分类（auth key 检测）
                 if exc_type is BadRequestError:
                     raise self._classify_request_error(e, provider, model_name, prefix) from e
                 raise LLMError(
                     message=f"{prefix} (provider: {provider}): {e}",
                     error_code=code,
                     details={"provider": provider, "model": model_name},
                     cause=e,
                 ) from e
         # 兜底
         raise LLMError(
             message=f"LLM 请求失败 (provider: {provider}, model: {model_name}): {e}",
             error_code=ErrorCode.LLM_ERROR,
             details={"provider": provider, "model": model_name},
             cause=e,
         ) from e
     ```
  4. 运行现有 `test_llm.py` / `test_llm_strategy.py` 确认行为不变
- **预期产出**：重构后的 `llm.py`（含 `_classify_request_error` 方法）+ 映射表
- **验收标准**：
  - [ ] `get_stream_response()` 的 except 块从 11 个减少到 2 个（`InvalidRequestError` + `Exception`）
  - [ ] 抛出 `ContextWindowExceededError` → 映射为 `ErrorCode.LLM_CONTEXT_WINDOW_EXCEEDED`（不被 `BadRequestError` 拦截）
  - [ ] 抛出 `ContentPolicyViolationError` → 映射为 `ErrorCode.LLM_ERROR` 且消息含 "内容安全策略"
  - [ ] 抛出纯 `BadRequestError`（含 "api key" 关键字）→ 映射为 `ErrorCode.LLM_AUTH_ERROR`
  - [ ] 每种 litellm 异常仍映射到正确的 `ErrorCode`
  - [ ] 现有 LLM 相关测试全部通过

#### Task 5.3: Agent.__init__ 副作用迁移到 create()

- **目标**：构造函数中不执行 Git 操作
- **步骤**：
  1. 修改 `broca/agent.py`：
     - `__init__` 中删除 `_snap_mgr = GitSnapshotManager()` / `_snap_mgr.initialize(...)` / `self.revert_service = SessionRevertService(...)`
     - 改为 `self.revert_service = None`（半初始化安全）
     - 在 `create()` 的 Step 1 中（No runtime deps）添加：
       ```python
       _snap_mgr = GitSnapshotManager()
       _snap_mgr.initialize(agent.config.workspace)
       agent.revert_service = SessionRevertService(
           session_manager, _snap_mgr, agent.config.workspace,
           enable_snapshot_tracking=getattr(agent.config, "enable_snapshot_tracking", True),
       )
       ```
  2. 全局搜索 `self.revert_service` 的引用，确认在 `create()` 完成前不会被访问
  3. 创建回归测试：`Agent(config, llm, sm)` 构造后不触发 git 操作（mock GitSnapshotManager 断言 `initialize` 未被调用）
- **预期产出**：修改后的 `agent.py` + 测试
- **验收标准**：
  - [ ] `Agent.__init__()` 不创建 `GitSnapshotManager` 或调用其 `initialize()`
  - [ ] `Agent.create()` 完成后 `agent.revert_service` 可用
  - [ ] 现有 `test_agent_*` 测试通过

#### Task 5.4: AgentReferenceAdapter.__getattr__ 增加警告

- **目标**：减少 `__getattr__` 通配兜底的隐性风险
- **步骤**：
  1. 修改 `broca/agent_reference.py` 的 `__getattr__`：
     ```python
     _KNOWN_AGENT_ATTRS = frozenset({
         "name", "config", "agent_id", "session_id", "turn_id",
         "llm_client", "tool_mapping", "tools", "status",
         "context", "communicator", "session_manager",
     })

     def __getattr__(self, name: str) -> Any:
         agent = object.__getattribute__(self, "_agent")
         if name not in self._KNOWN_AGENT_ATTRS:
             logger.debug(
                 "AgentReferenceAdapter.__getattr__('%s') — not in known set; "
                 "falling through to Agent. Consider adding to AgentReference protocol.",
                 name,
             )
         return getattr(agent, name)
     ```
  2. 不改变行为（仍然 passthrough），只增加 debug 日志帮助发现应该加入 protocol 的属性
- **预期产出**：修改后的 `agent_reference.py`
- **验收标准**：
  - [ ] 访问已知属性（`name` / `config`）无 debug 日志
  - [ ] 访问未知属性有 debug 日志提示
  - [ ] 行为不变（仍然 passthrough）

#### Task 5.5: SocketIOClient connect() 的 _should_reconnect 语义修正

- **目标**：手动 `connect()` 不应隐式启用自动重连
- **步骤**：
  1. 修改 `socketio_client.py` 的 `connect()`：
     - **移除**方法开头的 `self._should_reconnect = True`
     - `_should_reconnect` 仅在显式调用 `enable_auto_reconnect()` 时设为 True（该方法已存在，无需新增 API）
  2. 检查 `Agent.start()` 中调用 `connect()` 的地方，确认不需要自动重连（因为 `start()` 本身有 `while self.running` 循环会重试）
- **预期产出**：修改后的 `socketio_client.py`
- **验收标准**：
  - [ ] 手动调用 `connect()` 后断线不触发自动重连（除非显式调用 `enable_auto_reconnect()`）
  - [ ] `enable_auto_reconnect()` 调用后断线仍触发 `_reconnect()`
  - [ ] `_reconnect()` 逻辑不变

#### Task 5.6: safe_call 支持动态 details

- **目标**：允许被装饰函数在运行时传入 details
- **步骤**：
  1. 修改 `broca/errors/utils.py` 的 `safe_call`：
     - 在被装饰函数的 `*args` / `**kwargs` 中支持一个可选的 `_details: dict` 关键字参数
     - 如果提供了 `_details`，覆盖装饰器级别的静态 `details`
     - 在 wrapper 中 `kwargs.pop("_details", None)` 提取后从传给原函数的 kwargs 中移除
  2. 更新 docstring 和示例
  3. 创建回归测试
- **预期产出**：修改后的 `errors/utils.py` + 测试
- **验收标准**：
  - [ ] `@safe_call(details={"static": 1})` 装饰的函数可被 `func(..., _details={"dynamic": 2})` 调用
  - [ ] 动态 details 覆盖静态 details
  - [ ] `_details` 不会传递给被装饰函数的实际参数
  - [ ] 不传 `_details` 时行为不变

---

## 任务依赖与执行顺序

```
Phase 1 (P0 紧急修复)
├── Task 1.1: ErrorInfo traceback fix      ─┐ 可并行
└── Task 1.2: SocketIOClient connect fix   ─┘

Phase 2 (错误处理体系)  ← 依赖 Phase 1
├── Task 2.1: ComponentError 继承          ─┐
├── Task 2.2: SessionManager strict        ├── 可并行
├── Task 2.3: ToolResult error_info        │
└── Task 2.4: pre_execute_check 幂等       ─┘

Phase 3 (通讯模块)  ← 依赖 Phase 1 (Task 1.2) + Phase 2 (软依赖)
│  ⚠️ 3.1/3.2/3.3/3.5 同文件(socketio_client.py)，应顺序执行
├── Task 3.1: Dispatcher 补全 + 死代码     ─┐
├── Task 3.2: callbacks 超时清理           │
├── Task 3.3: send_message 异常统一        ├── 可并行
├── Task 3.4: client_id 唯一性 + 路由反馈  │
├── Task 3.5: CONNECT role + TTL 注释     │
└── Task 3.6: Communicator ABC 补齐       ─┘

Phase 4 (引擎健壮性)  ← 依赖 Phase 2
├── Task 4.1: LiteLLMClient 状态清理      ─┐
├── Task 4.2: CancelledError 防护         │
├── Task 4.3: TOOL_RESULT_CACHE_DIR       ├── 可并行
├── Task 4.4: _save_user_message 不可变   │
└── Task 4.5: _handle_task assigner 防御  ─┘

Phase 5 (清理收尾)  ← 依赖 Phase 4
├── Task 5.1: typo + 死代码 + 类型标注    ─┐
├── Task 5.2: LLM 异常映射表              │
├── Task 5.3: Agent.__init__ 副作用迁移   ├── 可并行
├── Task 5.4: AgentReferenceAdapter 日志  │
├── Task 5.5: _should_reconnect 语义      │
└── Task 5.6: safe_call 动态 details      ─┘
```

**总计**：5 个 Phase，23 个 Task

## 风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| Task 2.2 (strict 模式) 改变了 `save_message` 签名 | 其他调用方可能未预期 strict 行为 | `strict` 默认 `False`，只有 engine 显式传 `True`。不影响现有调用方 |
| Task 2.4 (pre_check_cache) 给 `ToolCallContext` 加字段 | 可能影响 `ToolCallContext` 的序列化 | `pre_check_cache` 不参与 `to_dict`，仅运行时使用。用完即弃 |
| Task 3.6 (ABC 补齐) 导致现有 mock 需要更新 | 测试中的 `Mock(Communicator)` 可能缺方法 | 使用 `unittest.mock.MagicMock(spec=Communicator)` 自动补全。逐一检查 `mock_components.py` |
| Task 5.2 (LLM 异常映射表) 异常继承层级 shadowing | `ContextWindowExceededError` / `ContentPolicyViolationError` 是 `BadRequestError` 子类，若 `BadRequestError` 条目在映射表中排在子类前面，`isinstance()` 会先匹配父类导致误分类 | 映射表**严格按子类→父类顺序排列**（已在 Task 5.2 步骤 2 中标注）。添加单元测试显式验证子类异常的映射正确性 |
| Task 5.2 (LLM 异常映射表) 改变异常链 | `InvalidRequestError` / `BadRequestError` 的子分类逻辑较复杂 | `InvalidRequestError`（继承 `openai.BadRequestError`）保留为独立 except 块；`BadRequestError`（litellm）走映射表但触发 `_classify_request_error` 子分类 |
| Task 4.1 (移除 token 属性) 导致现有测试失败 | `test_llm.py:116-117` 断言 `client.input_tokens_used == 0`，移除后触发 `AttributeError` | Task 4.1 步骤 3 已包含更新 `test_llm.py` 断言的步骤。执行时同步修改测试 |
| Task 4.3 (缓存路径) 可能影响正在运行的进程 | 旧进程仍用 CWD 相对路径 | 仅影响新启动的进程。旧缓存文件自然过期（1h TTL） |

## 未解决的问题

- **RetryLLMStrategy 计数器语义（#6）**：两个独立计数器的设计可能是有意为之（rate limit 和其他错误确实不同质）。建议**只加 docstring 说明语义**（"max_errors 分别限制两类错误的连续/累计次数"），不改变行为。如果确认需要统一，可作为后续独立任务。
- **Context 不在 Registry 中（#18）**：短期标注 "intentional exception" 即可，纳入 Registry 需要较大的接口设计工作，建议单独立项。
