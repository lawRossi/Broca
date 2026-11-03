# 消息通讯修复计划

## 概述
- **目标**：修复 `.worktrees/refactor` 分支消息通讯层的代码质量 + 性能问题
- **背景**：架构评审发现组件化整体良好，但存在 4 类代码质量问题和 4 类性能问题
- **约束条件**：
  - 在 `.worktrees/refactor` 分支上修改
  - 不改变 SocketIO 协议和消息格式（前端无需改动）
  - IPC 通道保留用于进程管理（心跳/命令/编排），移除 CMD_EXECUTE
  - 所有修改需通过 `pytest broca/tests/` 现有测试

## 相关材料
- `broca/communication/socketio_client.py` — SocketIOClient (~600 行，含 18 个 `_handle_*` + if-elif 链 + 20 个 `send_*` + 10+ `on_*` 装饰器)
- `broca/communication/socketio_server.py` — SocketIOServer，`_pending_messages` 缓存 (L69-71)、`_cache_pending_message` (L99)
- `broca/communication/agent_communicator.py` — SocketIOCommunicator 双继承 (L25)，末尾残留注释 (L67-73)
- `broca/components/communicator.py` — Communicator ABC 接口定义
- `broca/components/registry.py` — ComponentRegistry，Communicator → SocketIOCommunicator 映射
- `broca/components/defaults.py` — 默认组件注册
- `broca/agent.py` — Agent 中 ~20 处 `self.communicator.send_*` 调用
- `broca/components/command_system.py` — CommandSystem（命令执行+结果发送）
- `broca/session_runner/models.py` — IPCMessageType 枚举 (L29: CMD_EXECUTE)
- `broca/session_runner/ipc.py` — IPCServer/IPCClient 实现
- `broca/session_runner/runner.py` — Runner 进程，CMD_EXECUTE handler (L393-425)、ipc_listener_loop (L460-488)
- `broca/session_runner/manager.py` — Manager 进程，_ipc_listener_loop (L1109-1130)、send_command (L707-745)
- `broca/loop_engine/engine.py` — _make_chunk_handler (L395-430) 流式 chunk 广播
- `broca/loop_engine/hooks/lifecycle_broadcast_hook.py` — LifecycleBroadcastHook
- `broca-web/backend/app/core/socketio_runtime.py` — SocketIOServer 启动配置

## 总体方案

| Phase | 类型 | 内容 |
|-------|------|------|
| 1 | 基础清理 | 移除 IPC CMD_EXECUTE + 残留注释 + IPC 层加 Protocol 抽象 |
| 2 | 代码质量 | SocketIOClient 瘦身 + 消除双继承 + Agent communicator 收敛 |
| 3 | 性能 | IPC 监听改专用线程 + pending cache 定期清理 + chunk 节流 |

依赖关系：Phase 1 → Phase 2 → Phase 3（顺序执行）。Phase 3 的 3 个 Task 互相独立可并行。

---

### Phase 1: 通讯基础清理

**目标**：删除废弃代码路径，为后续重构扫清障碍

**阶段验收标准**：
- [ ] `broca/` 目录下 `grep -r "CMD_EXECUTE\|cmd_execute" --include="*.py"` 零匹配
- [ ] `agent_communicator.py` 末尾无残留注释
- [ ] `broca/session_runner/ipc.py` 新增 `IPCChannel` Protocol
- [ ] `RunnerManager` 中 `_ipc_servers` 类型注解使用 `IPCChannel`
- [ ] `pytest broca/tests/ -x` 通过

#### Task 1.1: 移除 IPC CMD_EXECUTE 定义和处理器

- **目标**：用户消息仅走 SocketIO，IPC 仅保留进程管理用途
- **步骤**：
  1. `broca/session_runner/models.py` L29：删除 `CMD_EXECUTE = "cmd_execute"` 行
  2. `broca/session_runner/runner.py` `handle_ipc_command` 函数：删除 `elif msg.type == IPCMessageType.CMD_EXECUTE:` 整个分支（L393-L425）
  3. 在 `handle_ipc_command` 末尾添加 fallback：
     ```python
     else:
         logger.warning("Unknown IPC command: %s (session=%s)", msg.type.value, msg.session_id)
     ```
- **验收标准**：
  - [ ] `grep "CMD_EXECUTE" -r broca/` 无匹配
  - [ ] `grep "cmd_execute" -r .` 无匹配
  - [ ] `handle_ipc_command` 对未知 type 有 log warning fallback

#### Task 1.2: 清理 agent_communicator.py 残留注释

- **目标**：删除文件末尾废弃的注释代码
- **步骤**：
  1. 删除 `broca/communication/agent_communicator.py` 末尾 7 行注释掉的 `send_to_user` / `send_to_room` / `send_to_subscription` 方法
- **验收标准**：
  - [ ] 文件无 `# async def send_to_` 行
  - [ ] `python -c "from broca.communication import SocketIOCommunicator"` 成功

#### Task 1.3: IPC 层加 Protocol 抽象

- **目标**：为 IPC 通道定义 Protocol 接口，使 `RunnerManager` 和 `runner.py` 依赖抽象而非具体类，为未来替换 IPC 实现预留空间
- **步骤**：
  1. 在 `broca/session_runner/ipc.py` 中新增 Protocol 定义：
     ```python
     from typing import Protocol, runtime_checkable

     @runtime_checkable
     class IPCChannel(Protocol):
         """IPC 通道统一接口。

         IPCServer（Web 进程）和 IPCClient（Runner 进程）均满足此 Protocol。
         发送和接收是独立操作，可在不同线程/协程中并发调用。
         """

         session_id: str
         address: str

         def start(self) -> None: ...
         def send_message(self, msg: IPCMessage) -> None: ...
         def receive_message(self, timeout: float = 10.0) -> IPCMessage | None: ...
         def close(self) -> None: ...
     ```
  2. 在 `IPCServer` 类定义后添加兼容性断言（开发期验证）：
     ```python
     assert isinstance(IPCServer("test"), IPCChannel)  # 开发期
     ```
     或改用 `# type: ignore` 注释说明。
  3. `broca/session_runner/manager.py`：
     - `_ipc_servers` 类型注解从 `Dict[str, IPCServer]` 改为 `Dict[str, IPCChannel]`
     - `_ipc_listener_loop` / `send_command` / `stop_session` 中的 `ipc_server` 局部变量类型注解改为 `IPCChannel`
  4. `broca/session_runner/runner.py`：
     - `IPCClient` 使用处类型注解改为 `IPCChannel`
  5. **`IPCClient` 补充 `start()` 方法**（满足 Protocol 接口）：
     ```python
     def start(self) -> None:
         """Protocol 兼容：包装 connect()。"""
         if not self.connect():
             raise IPCConnectionError(f"IPCClient failed to connect to {self.address}")
     ```
  6. 在 `IPCClient` 类头部添加并发安全注释：
     ```python
     # 注意：multiprocessing.connection.Client 底层是 socket，send()/recv()
     # 是不同方向的独立操作，Unix Domain Socket 上可跨线程并发调用。
     # ⚠️ Windows AF_PIPE (named pipe) 是串行的，并发 send/recv 未经验证。
     # 若需跨平台支持，应为此类添加 threading.Lock 保护。
     ```
- **验收标准**：
  - [ ] `IPCChannel` Protocol 定义在 `ipc.py` 中
  - [ ] `from typing import get_type_hints` 检查 `IPCSessionRunner._ipc_servers` 类型为 `Dict[str, IPCChannel]`
  - [ ] `IPCServer` 和 `IPCClient` 均满足 `IPCChannel`（`isinstance` 检查通过）
  - [ ] 现有测试通过

---

### Phase 2: SocketIO 代码质量重构

**前置依赖**：Phase 1 Task 1.3 必须完成（`IPCChannel` Protocol 可用），Task 2.2 中 `manager.py` 类型注解依赖此 Protocol。

**目标**：SocketIOClient 瘦身、消除双继承、收敛 Agent 中散落的 communicator 调用

**阶段验收标准**：
- [ ] `socketio_client.py` 中不再有 `_handle_user_message` / `_handle_agent_response` / ... 等 18 个独立方法
- [ ] `SocketIOClient` 直接实现 `Communicator` ABC（`issubclass(SocketIOClient, Communicator)` 为 True）
- [ ] `SocketIOCommunicator` 类被删除，registry 映射改为 `Communicator → SocketIOClient`
- [ ] `Agent._on_command` / `_handle_command` 中不再有直接的 `self.communicator.send_*` 调用
- [ ] `pytest broca/tests/ -x` 通过

#### Task 2.1: SocketIOClient 事件分发提取

- **目标**：将 18 个 `_handle_*` 方法和 `_handle_message` 的 if-elif 链提取为独立的 `_MessageDispatcher`，`SocketIOClient` 瘦身 ~200 行
- **步骤**：
  1. 在 `socketio_client.py` 中新增 `_MessageDispatcher` 内部类：
     ```python
     class _MessageDispatcher:
         """消息事件分发器：根据 message_type 路由到对应的 event handler。

         从 SocketIOClient 提取，将 if-elif 链替换为 dispatch table 查找。
         """

         def __init__(self, trigger_event: Callable):
             self._trigger = trigger_event
             self._table: Dict[MessageType, str] = {
                 MessageType.USER_MESSAGE: "user_message",
                 MessageType.AGENT_RESPONSE: "agent_response",
                 MessageType.TASK_START: "task_start",
                 MessageType.TASK_COMPLETE: "task_complete",
                 MessageType.TASK_ERROR: "task_error",
                 MessageType.TURN_START: "turn_start",
                 MessageType.TURN_END: "turn_end",
                 MessageType.TOOL_CALL: "tool_call",
                 MessageType.COMMAND: "command",
                 MessageType.COMMAND_RESULT: "command_result",
                 MessageType.PERMISSION_REQUEST: "permission_request",
                 MessageType.PERMISSION_RESPONSE: "permission_response",
                 MessageType.AGENT_QUERY: "agent_query",
                 MessageType.USER_ANSWER: "user_answer",
                 MessageType.ERROR: "error",
                 MessageType.SUBSCRIBE: "subscribe",
                 MessageType.UNSUBSCRIBE: "unsubscribe",
                 MessageType.BROADCAST: "broadcast",
             }

         async def dispatch(self, message: Message) -> None:
             event_name = self._table.get(message.message_type)
             if event_name is None:
                 logger.debug(f"Unhandled message type: {message.message_type}")
                 return
             await self._trigger(event_name, message)
     ```
  2. 在 `SocketIOClient.__init__` 中创建 dispatcher：
     ```python
     self._dispatcher = _MessageDispatcher(self._trigger_event)
     ```
  3. 修改 `_setup_event_handlers` 中的 `message` 事件处理器：
     ```python
     @self.sio.event
     async def message(data):
         try:
             message_data = json.loads(data) if isinstance(data, str) else data
             message = MessageProtocol.from_dict(message_data)
             logger.debug(f"Received message: {message}")
             await self._dispatcher.dispatch(message)
             await self._trigger_event("message", message)
             if message.message_id in self.message_callbacks:
                 callback = self.message_callbacks.pop(message.message_id)
                 await callback(message)
         except json.JSONDecodeError as e:
             logger.error(f"Failed to parse message: {e}")
         except Exception as e:
             logger.error(f"Error processing message: {e}")
     ```
  4. **删除**以下 18 个方法（全部由 dispatch table 替代）：
     - `_handle_message`（if-elif 链）
     - `_handle_user_message`、`_handle_agent_response`、`_handle_task_start`、`_handle_task_complete`、`_handle_turn_start`、`_handle_turn_end`、`_handle_tool_call`、`_handle_command`、`_handle_command_result`、`_handle_permission_request`、`_handle_permission_response`、`_handle_agent_query`、`_handle_user_answer`、`_handle_error`、`_handle_subscribe`、`_handle_unsubscribe`、`_handle_broadcast`
     - 注意：`_handle_subscribe` 和 `_handle_unsubscribe` 有副作用（更新 `connection_info.subscriptions`），需要保留逻辑但移到 dispatcher 中：
       ```python
       class _MessageDispatcher:
           def __init__(self, trigger_event, get_connection_info):
               self._trigger = trigger_event
               self._get_info = get_connection_info
               ...

           async def dispatch(self, message):
               # subscribe/unsubscribe 有额外副作用
               if message.message_type == MessageType.SUBSCRIBE:
                   info = self._get_info()
                   if message.subscription and message.subscription not in info.subscriptions:
                       info.subscriptions.append(message.subscription)
                   await self._trigger("subscribe", message)
                   return
               if message.message_type == MessageType.UNSUBSCRIBE:
                   info = self._get_info()
                   if message.subscription and message.subscription in info.subscriptions:
                       info.subscriptions.remove(message.subscription)
                   await self._trigger("unsubscribe", message)
                   return
               # ... 通用 dispatch
       ```
- **预期产出**：`socketio_client.py` 减少 ~180 行，`_MessageDispatcher` 类 ~50 行
- **验收标准**：
  - [ ] `socketio_client.py` 中 `grep "_handle_"` 无匹配（`_handle_message` 等全部删除）
  - [ ] `_MessageDispatcher._table` 覆盖 `MessageType` 中所有需要路由的类型
  - [ ] `subscribe`/`unsubscribe` 事件仍正确更新 `connection_info.subscriptions`
  - [ ] 所有 `on_*` 装饰器注册的事件仍能正常触发
  - [ ] `pytest broca/tests/ -x` 通过

#### Task 2.2: 消除 SocketIOCommunicator 双继承

- **目标**：`SocketIOClient` 直接实现 `Communicator` ABC，删除 `SocketIOCommunicator` 中间层
- **步骤**：
  1. 确认 `SocketIOClient` 已具备 `Communicator` ABC 的所有方法：
     - `connect(timeout)` ✅ 已有
     - `disconnect()` ✅ 已有
     - `is_connected()` ✅ 已有
     - `send_message(message, callback, retry_on_disconnect)` ✅ 已有
     - `send_user_message(content, subscription, receiver_id)` ⚠️ 已有 (L458) 但签名不一致 → 需对齐
     - `send_tool_call(tool_call_id, tool_name, arguments, turn_id, agent_id, subscription)` ⚠️ 已有但参数顺序不同 → 需对齐
     - `send_error(error_info, receiver_id, room, subscription, callback)` ✅ 已有
     - `initialize(agent_id, session_id, config)` ❌ 缺失 → 新增
  2. 在 `SocketIOClient` 中修复/新增方法：
     - **`send_user_message` 签名对齐**（保留现有全部参数以向后兼容）：
       现有签名：`send_user_message(self, content, receiver_id=None, room=None, subscription=None, callback=None)`
       修改为（对齐 ABC 参数顺序 + 保留扩展参数）：
       ```python
       async def send_user_message(
           self, content: str, subscription: str | None = None, receiver_id: str | None = None,
           room: str | None = None, callback: Callable | None = None,
       ) -> str:
           msg = MessageProtocol.create_user_message(
               content=content, sender_id=self.client_id,
               subscription=subscription or room, receiver_id=receiver_id,
           )
           return await self.send_message(msg, callback=callback)
       ```
       ⚠️ 注意：参数顺序变更（`subscription` 提前），需检查所有调用方是否使用位置参数。若存在位置参数调用，需同步更新调用方。
     - **`send_tool_call` 参数顺序对齐**：
       现有签名：`send_tool_call(self, tool_name, arguments, tool_call_id, result, status, turn_id, agent_id, receiver_id, room, subscription, callback, message_id)`
       ABC 签名：`send_tool_call(self, tool_call_id, tool_name, arguments, turn_id, agent_id, subscription)`
       修改为（ABC 三参数前置对齐，扩展参数保留在后）：
       ```python
       async def send_tool_call(
           self,
           tool_call_id: str | None = None,
           tool_name: str = "",
           arguments: str | None = None,
           turn_id: str | None = None,
           agent_id: str | None = None,
           subscription: str | None = None,
           # 以下为 SocketIOClient 扩展参数
           result: str | None = None,
           status: bool | None = None,
           receiver_id: str | None = None,
           room: str | None = None,
           callback: Callable | None = None,
           message_id: str | None = None,
       ) -> str:
       ```
       ✅ 安全：已确认所有现有调用方（`engine.py` 的 `_make_chunk_handler`、Agent 代码）均使用关键字参数，无位置参数调用，重排不会导致 TypeError。
     - **新增 `initialize`**（registry 无参构造后调用）：
     ```python
     async def initialize(
         self, agent_id: str | None = None, session_id: str | None = None, config: Any = None
     ) -> None:
         """延迟初始化（registry 无参构造后调用）"""
         self._session_id = session_id
         if agent_id is not None:
             self.client_id = agent_id
             self.connection_info.client_id = agent_id
             if config is not None and getattr(config, "server_url", None):
                 self.server_url = config.server_url
                 self.connection_info.server_url = config.server_url
     ```
  3. 修改 `SocketIOClient` 类声明：
     ```python
     class SocketIOClient(Communicator):
         # 不再继承 ABC 标记（Communicator 本身就是 ABC）
     ```
     注意：`Communicator` 继承自 `BaseComponent`，所以 `SocketIOClient` 也获得了 `BaseComponent` 的生命周期方法（`initialize`/`shutdown`）。
  3b. **Override `shutdown()`**（BaseComponent 默认空实现，需映射到 `disconnect`）：
     ```python
     async def shutdown(self) -> None:
         """BaseComponent 生命周期：断开 SocketIO 连接。"""
         await self.disconnect()
     ```
  4. 删除 `broca/communication/agent_communicator.py` 整个文件
  5. 修改 `broca/communication/__init__.py`：
     ```python
     from .socketio_client import SocketIOClient
     from .socketio_server import SocketIOServer
     __all__ = ["SocketIOServer", "SocketIOClient"]
     ```
  6. 修改 `broca/components/defaults.py` 中的 registry 映射：
     ```python
     # 原来: registry.register(Communicator, SocketIOCommunicator)
     # 改为:
     registry.register(Communicator, SocketIOClient)
     ```
  7. 全局搜索替换 `SocketIOCommunicator` → `SocketIOClient`（含 import 语句、类型注解、注释）
  8. 删除 `AgentCommunicator = SocketIOCommunicator` 别名（在 agent_communicator.py 中，文件已删除）；如有其他文件引用 `AgentCommunicator`，改为 `SocketIOClient`
- **验收标准**：
  - [ ] `broca/communication/agent_communicator.py` 文件不存在
  - [ ] `issubclass(SocketIOClient, Communicator)` 为 `True`
  - [ ] `ComponentRegistry` 中 `Communicator` 映射到 `SocketIOClient`
  - [ ] 全项目 `grep "SocketIOCommunicator"` 无匹配
  - [ ] 全项目 `grep "AgentCommunicator"` 无匹配
  - [ ] `Agent.create()` 中 `registry.get(Communicator, scope_key=key)` 返回 `SocketIOClient` 实例
  - [ ] 冒烟测试：`registry.get(Communicator)` 无参构造 + `await client.initialize()` 后 `is_connected()` 方法可调（不抛异常）
  - [ ] `pytest broca/tests/ -x` 通过

#### Task 2.3: Agent communicator 调用收敛

- **目标**：将 Agent 中命令结果/错误发送逻辑下沉到 `CommandSystem` 组件，Agent 不再直接调用 `self.communicator.send_command_result` / `send_error`
- **步骤**：
  1. 分析 `agent.py` 中所有 `self.communicator.send_*` 调用点：
     - `_handle_command` (L~290)：`send_error` + `send_command_result` → 属于命令系统
     - `_on_command` (L~350)：`send_command_result` + `send_error` → 属于命令系统
     - `_handle_task` (L~320)：`send_task_complete` + `send_task_error` → 属于任务协议，保留在 Agent
  2. 在 **`FileCommandSystem`**（`broca/commands/manager.py`，`CommandSystem` 的具体实现）中新增方法：
     > ⚠️ 不放到 `CommandSystem` ABC 中——ABC 不应包含依赖运行时注入的 `self._communicator` 的实现逻辑。
     ```python
     # 在 FileCommandSystem 类中新增：
     async def send_result(self, name: str, result: DispatchResult, subscription: str) -> None:
         """将命令结果发送回前端"""
         if self._communicator is None:
             logger.warning("send_result called but communicator not initialized")
             return
         if result.type == "error":
             await self._communicator.send_error(
                 {"message": result.value, "code": "COMMAND_ERROR", "severity": "error"},
                 subscription=subscription,
             )
         else:
             cmd = self.registry.get(name)
             if cmd is not None and getattr(cmd, "show_result", False):
                 await self._communicator.send_command_result(
                     command=name,
                     result={"code": 0, "message": result.value},
                     subscription=subscription,
                 )

     async def send_dispatch_error(self, command: str, subscription: str) -> None:
         if self._communicator is None:
             logger.warning("send_dispatch_error called but communicator not initialized")
             return
         await self._communicator.send_error(
             {"message": f"未知命令: {command}", "code": "COMMAND_ERROR", "severity": "error"},
             subscription=subscription,
         )
     ```
  3. 确保 `CommandSystem.initialize()` 接收 `communicator` 参数并保存：
     ```python
     async def initialize(self, agent: Any, communicator: Any = None, **kwargs):
         # ... 现有逻辑
         self._communicator = communicator or getattr(agent, "communicator", None)
     ```
  4. 修改 `Agent.create()` 中的 `command_manager.initialize` 调用，显式传入 communicator：
     ```python
     await agent.command_manager.initialize(agent=agent, communicator=agent.communicator)
     ```
  5. 修改 `Agent._handle_command`：
     ```python
     # 原来:
     #   if result.type == "error": await self.communicator.send_error(...)
     #   else: ... self.communicator.send_command_result(...)
     # 改为:
     await self.command_manager.send_result(name, result, self.session_id)
     ```
  6. 修改 `Agent._on_command`：
     ```python
     # 原来:
     #   if result: await self.communicator.send_command_result(...)
     #   else: await self.communicator.send_error(...)
     # 改为:
     if result:
         await self.command_manager.send_result(command, result, self.session_id)
     else:
         await self.command_manager.send_dispatch_error(command, self.session_id)
     ```
  7. `_handle_task` 中的 `send_task_complete` / `send_task_error` 保留在 Agent（这是 Agent 间的任务协议，不属于命令系统）
- **预期产出**：`agent.py` 中 `self.communicator.send_*` 调用从 ~10 处降到 ~2 处（仅 `_handle_task` 中的任务协议）
- **验收标准**：
  - [ ] `agent.py` 中 `grep "self.communicator.send_"` 仅剩 `_handle_task` 中的 `send_task_complete` / `send_task_error`
  - [ ] `CommandSystem` 有 `_communicator` 属性和 `send_result` / `send_dispatch_error` 方法
  - [ ] 命令 `/help` 等仍正确将结果发送回前端
  - [ ] 未知命令仍返回错误消息
  - [ ] `pytest broca/tests/ -x` 通过

---

### Phase 3: 性能优化

**目标**：消除 IPC 线程池竞争、修复内存泄漏、降低流式广播频率

**阶段验收标准**：
- [ ] Manager 和 Runner 侧 IPC 监听均使用专用 daemon 线程（`grep "run_in_executor" .../runner.py` 和 `.../manager.py` 中仅剩 `start_session`/`send_command` 的一次性调用）
- [ ] SocketIOServer 启动后台清理任务，60s 周期清除过期 `_pending_messages`
- [ ] LLM 流式输出时，按混合策略（累计 ≥128 字符或 ≥100ms 兜底）合并同类型 content chunk 为单次 emit
- [ ] `pytest broca/tests/ -x` 通过
- [ ] 手动验证：启动 Web → 创建 session → 发消息 → 正常回复 → 停止 session 无残留线程

#### Task 3.1: IPC 监听改专用线程（Manager + Runner）

- **目标**：消除 `run_in_executor` 对默认线程池的竞争
- **步骤**：

  **3.1a Manager 侧** (`broca/session_runner/manager.py`)：

  1. 新增 `import threading`
  2. `IPCSessionRunner.__init__` 新增 `self._ipc_listener_threads: Dict[str, threading.Thread] = {}`
  3. 重写 `_ipc_listener_loop`：
     ```python
     async def _ipc_listener_loop(self, session_id: str) -> None:
         ipc_server = self._ipc_servers.get(session_id)
         if not ipc_server:
             return
         loop = asyncio.get_running_loop()
         msg_queue: asyncio.Queue[IPCMessage | None] = asyncio.Queue()

         def _thread_poll():
             while session_id in self._runners:
                 try:
                     msg = ipc_server.receive_message(5.0)
                     if msg:
                         loop.call_soon_threadsafe(msg_queue.put_nowait, msg)
                 except IPCConnectionError:
                     loop.call_soon_threadsafe(msg_queue.put_nowait, None)
                     break
                 except Exception as e:
                     logger.error("IPC listener thread error for %s: %s", session_id, e)
                     loop.call_soon_threadsafe(msg_queue.put_nowait, None)
                     break

         thread = threading.Thread(target=_thread_poll, name=f"ipc-poll-{session_id}", daemon=True)
         thread.start()
         self._ipc_listener_threads[session_id] = thread

         while session_id in self._runners:
             try:
                 msg = await asyncio.wait_for(msg_queue.get(), timeout=1.0)
                 if msg is None:
                     break
                 self._handle_runner_event(session_id, msg)
             except asyncio.TimeoutError:
                 continue

     ```
  4. `_cleanup_runner` 中：`self._ipc_listener_threads.pop(session_id, None)`（线程是 daemon，`ipc_server.close()` 触发 `IPCConnectionError` → 线程自然退出）
  5. 保留 `send_command` 和 `start_session` 中的 `run_in_executor` 不变

  **3.1b Runner 侧** (`broca/session_runner/runner.py`)：

  1. 新增 `import threading`
  2. 重写 `ipc_listener_loop`：
     ```python
     async def ipc_listener_loop(ipc_client: IPCChannel) -> None:
         global _running, _ipc_lost
         loop = asyncio.get_running_loop()
         msg_queue: asyncio.Queue = asyncio.Queue()

         def _thread_poll():
             while _running and not _ipc_lost:
                 try:
                     msg = ipc_client.receive_message(0.5)
                     if msg:
                         loop.call_soon_threadsafe(msg_queue.put_nowait, msg)
                 except IPCConnectionError as e:
                     logger.warning("IPC connection lost: %s", e)
                     loop.call_soon_threadsafe(msg_queue.put_nowait, None)
                     break
                 except Exception as e:
                     logger.error("IPC listener thread error: %s", e)
                     loop.call_soon_threadsafe(msg_queue.put_nowait, None)
                     break

         thread = threading.Thread(target=_thread_poll, name="ipc-poll-runner", daemon=True)
         thread.start()

         while _running and not _ipc_lost:
             try:
                 msg = await asyncio.wait_for(msg_queue.get(), timeout=1.0)
                 if msg is None:
                     _ipc_lost = True
                     _running = False
                     if _shutdown_event is not None:
                         _shutdown_event.set()
                     break
                 await handle_ipc_command(msg, ipc_client)
             except asyncio.TimeoutError:
                 continue
     ```
  3. `heartbeat_loop` 保持不变（只 `send_message`，不 `receive`）
  4. 在 `IPCClient` 类头部添加设计假设注释：
     ```python
     # 注意：multiprocessing.connection.Client 底层是 socket。
     # send() 和 recv() 是不同方向的独立操作，可在不同线程/协程中并发调用。
     # heartbeat_loop (event loop 线程) 调用 send，_thread_poll (daemon 线程) 调用 recv。
     ```
- **验收标准**：
  - [ ] `grep "run_in_executor" broca/session_runner/runner.py` 无匹配
  - [ ] `grep "run_in_executor" broca/session_runner/manager.py` 仅匹配 `start_session`（accept + first_msg）和 `send_command`（≤3 处）
  - [ ] 启动 session 后 `ps -T -p <runner_pid>` 能看到 `ipc-poll-runner` 线程
  - [ ] Web 进程 `ps -T -p <web_pid> | grep ipc-poll` 能看到每个 session 的线程
  - [ ] `stop_session` 后 5s 内对应线程 `is_alive() == False`
  - [ ] 心跳 / CMD_ABORT / CMD_SHUTDOWN / CMD_RUN_CREW 均正常工作
  - [ ] 后端被 kill 后 Runner 在 10s 内优雅退出

#### Task 3.2: Pending Message Cache 定期清理

- **目标**：防止断连客户端的未响应请求导致 `_pending_messages` 无限增长
- **步骤**：
  1. `SocketIOServer.__init__` 新增 `self._cleanup_task: Optional[asyncio.Task] = None`
  2. 新增 `_cleanup_expired_pending` 协程：
     ```python
     async def _cleanup_expired_pending(self) -> None:
         """每 60s 扫描并清除 _pending_messages 中的过期条目"""
         while True:
             try:
                 await asyncio.sleep(60)
                 now = time.time()
                 async with self._lock:
                     for sub in list(self._pending_messages.keys()):
                         entries = self._pending_messages[sub]
                         expired = [k for k, e in entries.items() if now > e["expire_at"]]
                         for k in expired:
                             rid = entries[k]["request_id"]
                             del entries[k]
                             self._request_to_subscription.pop(rid, None)
                         if not entries:
                             del self._pending_messages[sub]
                         if expired:
                             logger.info("Cleaned %d expired pending msgs from %s", len(expired), sub)
             except asyncio.CancelledError:
                 break
             except Exception as e:
                 logger.error("Pending cleanup error: %s", e)
     ```
  3. `start()` 中：`self._cleanup_task = asyncio.create_task(self._cleanup_expired_pending())`
  4. `stop()` 中：cancel + await `_cleanup_task`
- **验收标准**：
  - [ ] `SocketIOServer.stop()` 后 `_cleanup_task` 为 None
  - [ ] 手动注入一个 `expire_at = time.time() - 1` 的条目，等待 60s 后被清除
  - [ ] 正常 PERMISSION_REQUEST → PERMISSION_RESPONSE 流程不受影响

#### Task 3.3: LLM chunk 广播节流（混合策略）

- **目标**：LLM 流式输出时，按**累计长度 ≥ 128 字符**或**距上次 flush ≥ 100ms**（先到先触发）合并 chunk 为单次 SocketIO emit，减少 5-10x 网络 I/O
- **步骤**：
  1. `DefaultLoopEngine` 新增实例变量（`__init__` 和 `_do_initialize` 中初始化）：
     ```python
     self._chunk_buffer: list[dict] = []
     self._chunk_buffer_len: int = 0
     self._chunk_flush_task: asyncio.Task | None = None
     self._CHUNK_FLUSH_CHARS: int = 128    # 长度阈值
     self._CHUNK_FLUSH_INTERVAL: float = 0.1  # 时间兜底 100ms
     self._CHUNK_BUFFER_MAX: int = 1000    # buffer 安全阀上限
     ```
  2. 新增 `_schedule_chunk_flush` / `_flush_chunks` / `_merge_consecutive_chunks` 方法：
     ```python
     def _schedule_chunk_flush(self) -> None:
         """调度一个延迟 flush（时间兜底）"""
         if self._chunk_flush_task is None or self._chunk_flush_task.done():
             self._chunk_flush_task = asyncio.create_task(self._flush_chunks())

     def _flush_now(self) -> None:
         """立即 flush（长度达到阈值时调用）"""
         if self._chunk_flush_task and not self._chunk_flush_task.done():
             self._chunk_flush_task.cancel()
         self._chunk_flush_task = None
         asyncio.ensure_future(self._flush_chunks())

     async def _flush_chunks(self) -> None:
         """等待 FLUSH_INTERVAL 后合并发送 buffer 中的 chunks（时间兜底路径）"""
         await asyncio.sleep(self._CHUNK_FLUSH_INTERVAL)
         await self._do_flush()

     async def _do_flush(self) -> None:
         """实际执行 flush：取出 buffer → merge → emit"""
         if not self._chunk_buffer:
             return
         chunks = self._chunk_buffer[:]
         self._chunk_buffer.clear()
         self._chunk_buffer_len = 0
         self._chunk_flush_task = None

         merged = self._merge_consecutive_chunks(chunks)
         for chunk in merged:
             try:
                 kind = chunk.get("type")
                 if kind in ("content", "reasoning_content"):
                     await self.communicator.send_agent_response(
                         content=chunk.get("data", "") if kind == "content" else "",
                         reasoning_content=(
                             chunk.get("data", "") if kind == "reasoning_content" else ""
                         ),
                         index=chunk.get("index", 0),
                         turn_id=self.turn_id,
                         agent_id=self.agent_id,
                         message_id=chunk.get("message_id", ""),
                         subscription=self.session_id,
                     )
                 # tool_call 不在 buffer 中（已在 _on_chunk 中直接发送）
             except Exception as e:
                 logger.warning(f"Failed to broadcast merged LLM chunk: {e}")

     @staticmethod
     def _merge_consecutive_chunks(chunks: list) -> list:
         """合并连续同类型 (content/reasoning_content) chunks 的 data 字段"""
         if not chunks:
             return chunks
         merged = [chunks[0]]
         for chunk in chunks[1:]:
             prev = merged[-1]
             if (
                 chunk.get("type") == prev.get("type")
                 and chunk.get("type") in ("content", "reasoning_content")
                 and chunk.get("index") == prev.get("index")
                 and chunk.get("message_id") == prev.get("message_id")
             ):
                 prev["data"] = prev.get("data", "") + chunk.get("data", "")
             else:
                 merged.append(chunk)
         return merged
     ```
  3. 修改 `_make_chunk_handler`：
     ```python
     def _make_chunk_handler(self):
         async def _on_chunk(event: dict) -> None:
             if not getattr(self.config, "interactive", False):
                 return
             kind = event.get("type")

             # tool_call 绕过 buffer，立即发送（不参与长度累计和合并）
             if kind == "tool_call":
                 try:
                     tool_call = event.get("data")
                     name = getattr(getattr(tool_call, "function", None), "name", None)
                     if name:
                         await self.communicator.send_tool_call(
                             tool_name=name,
                             arguments=None,
                             tool_call_id=getattr(tool_call, "id", None),
                             turn_id=self.turn_id,
                             agent_id=self.agent_id,
                             subscription=self.session_id,
                         )
                 except Exception as e:
                     logger.warning(f"Failed to send tool_call chunk: {e}")
                 return

             # buffer 安全阀：防止 event loop 阻塞导致无限增长
             if len(self._chunk_buffer) > self._CHUNK_BUFFER_MAX:
                 self._flush_now()

             self._chunk_buffer.append(event)
             self._chunk_buffer_len += len(event.get("data", "") or "")
             if self._chunk_buffer_len >= self._CHUNK_FLUSH_CHARS:
                 self._flush_now()           # 长度够了，立即 flush
             else:
                 self._schedule_chunk_flush()  # 没攒够，等 100ms 兜底
         return _on_chunk
     ```
  4. `_reset_turn_scoped_state` 中清空 buffer + cancel flush task：
     ```python
     self._chunk_buffer.clear()
     self._chunk_buffer_len = 0
     if self._chunk_flush_task and not self._chunk_flush_task.done():
         self._chunk_flush_task.cancel()
         self._chunk_flush_task = None
     ```
  5. `abort()` 中立即 flush 残余 buffer：
     ```python
     def abort(self):
         self.abort_event.set()
         # 注意：abort() 是同步方法，假设在 event loop 线程内调用（SocketIO 事件 / 引擎内部）。
         # 若未来存在跨线程调用场景，需改用 loop.call_soon_threadsafe()。
         if self._chunk_buffer:
             try:
                 asyncio.ensure_future(self._do_flush())
             except RuntimeError:
                 # 无 running event loop（跨线程调用场景），降级为同步清空
                 self._chunk_buffer.clear()
                 self._chunk_buffer_len = 0
     ```
- **验收标准**：
  - [ ] 快速生成（每 chunk 20 字符，10ms 间隔）：每 ~7 个 chunk 触发一次 flush（128/20≈6.4），emit 次数 ≈ N/7
  - [ ] 慢速生成（每 80ms 一个 10 字符 chunk）：100ms 兜底触发，约每 1-2 个 chunk flush 一次
  - [ ] 前端收到的 content 拼接后与不节流时完全一致
  - [ ] `tool_call` 类型 chunk 不参与长度累计，在 flush 时立即发送
  - [ ] turn 结束后 `_chunk_buffer == []` 且 `_chunk_buffer_len == 0`
  - [ ] `pytest broca/tests/test_engine_event_flow.py` 通过

---

## 风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| 移除 CMD_EXECUTE 后 TUI/VSCode 走 IPC 发消息会断 | 高 | 已确认 TUI 和 VSCode 均通过 SocketIO 连接（`SocketIOClient`），CMD_EXECUTE 在当前代码中无调用方 |
| `SocketIOClient` 继承 `Communicator(BaseComponent, ABC)` 后引入 `BaseComponent` 的额外行为 | 中 | `BaseComponent` 只有 `initialize`/`shutdown` 两个方法，`SocketIOClient` 已有同名方法，无冲突。`shutdown` 映射到 `disconnect` |
| 删除 `SocketIOCommunicator` 后 import 路径变更 | 中 | 全局搜索替换，`from broca.communication import SocketIOClient` 替代。`__init__.py` 的 `__all__` 同步更新 |
| `CommandSystem` 原来不持有 communicator，新增后需修改 `initialize` 签名 | 低 | `communicator` 参数有默认值 `None`，fallback 到 `agent.communicator`，向后兼容 |
| IPC 专用线程 + `call_soon_threadsafe` 在 event loop 关闭时丢失消息 | 中 | daemon 线程随进程退出。`stop_session` 先 pop `_runners` 使线程退出 while，再 close IPC |
| Chunk 合并后 `message_id` 重复 | 低 | 合并保留首个 chunk 的 `message_id`，前端按 `message_id` 做"追加"语义（与 LLM 流式输出的天然模式一致） |
| `send_user_message` 签名变更（参数顺序调整）导致位置参数调用方 TypeError | 中 | 保留全部现有参数（`receiver_id`, `room`, `subscription`, `callback`），仅调整 `subscription` 位置以对齐 ABC；执行前 grep 所有调用方确认无位置参数调用 |
| Windows AF_PIPE 并发 `send`/`recv` 未经验证（heartbeat 线程 send + poll 线程 recv） | 中 | 当前目标平台为 macOS/Linux（Unix Domain Socket 天然支持并发）。若需 Windows 支持，`IPCClient` 需加 `threading.Lock` |
| Event loop 阻塞（CPU-bound tool）导致 `_chunk_buffer` 无限增长 | 低 | 添加 `_CHUNK_BUFFER_MAX = 1000` 安全阀，超出时强制 flush |

## 未解决的问题
- （无）
