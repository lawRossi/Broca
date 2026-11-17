# AgentMessenger — 统一 Agent 间通信通道

> **摘要**：request / notify / delegate 三模式统一走 `send() -> dict` 同步等传输层 ACK（≤2s，`routing_failed` 一律快速失败）；request 额外阻塞等业务回复（专用 `AGENT_REQUEST_RESPONSE` + `request_id` 配对 + 超时 + 环检测），notify/delegate 不等业务回执。核心防死锁靠 **request 强制环检测**——`run()` 入口无条件把自身 `agent_id` 加入 CallChain，保证首跳环检测生效。历史修订记录见文末「变更历史」附录。

## 概述

- **目标**：提供统一的 Agent 间直接通信机制（request / notify / delegate），替代当前粗粒度的 `assign_task`；控制机制保持精简——核心必选（ACL / task 校验 / 回复保障 / request 超时+环检测）+ 可选增强按需开启。
- **核心设计（本次修订）**：**request 走 ask_user 式同步链路**——发出消息后**阻塞等待回复**，收到回复后工具返回、LLM 在当前 turn 内继续执行；notify / delegate 保持 fire-and-forget（**仅指不等业务回执，仍同步等传输层 ACK**）。request 的回复使用**专用消息类型 `AGENT_REQUEST_RESPONSE`** + `request_id` 配对 + `asyncio.Event` 唤醒 + 超时，与 `AskUser._execute()` 的链路同构。delegate 回执仍复用 `AGENT_NOTIFY`。
- **关键区分——"等 ACK" vs "等回执"（用户澄清）**：三种模式**都同步等传输层 ACK**（`send() -> dict`，emit callback，≤`_ack_timeout=2s`），ACK 为 `routing_failed` 一律快速失败抛 `AgentCommunicationError(reason="routing_failed")`，让调用方（LLM）立即知道消息没投递出去。区别只在**业务层回复**：request 额外阻塞等 `AGENT_REQUEST_RESPONSE`，notify/delegate **不等回执**（发送后立即返回）。"fire-and-forget" 仅修饰回执等待，**不包含 ACK**。
- **背景**：当前 Agent 间交互只有 `assign_task`（全量任务委派）和 Blackboard（编排期间共享状态）。缺少轻量咨询、事件通知、任务委派等交互模式。`assign_task` 只有一种粗粒度交互语义，无权限检查、无深度限制、无预算控制。
- **约束条件**：
  - 复用现有 SocketIO 通信层作为**传输协议**；**通信范围限定为同一进程、同一 session 内的 agent 之间**——name→id 解析依赖 `DefaultAgentFactory.get_agent(session_id, name)`，其实现（`agent_manager.py:543`）只查本地 `self._session_agents[session_id]`，无法解析跨进程 target。跨进程 name→id 远端解析列为后续工作（见风险表"跨进程 target 解析不可用"与"未解决的问题"）
  - 遵循 Broca 的组件化架构（`ComponentRegistry` + ABC + `defaults.py` 注册）
  - **直接删除** `assign_task` tool + `TASK_START/COMPLETE/ERROR` 消息类型，不做向后兼容
  - **新增的通信 tool 直接实现在现有 `broca/tools/agent_interaction.py`，不新建文件**
  - 测试必须使用 `_isolate_home` 隔离（项目规则 #2）

## 相关材料

- `broca/tools/agent_interaction.py` — 现有 `AssignTask` / `AskUser` 实现（AssignTask 要删除；**新增的 `Communicate` tool 就地实现在此文件，不新建文件**）。`AskUser` 是 request 模式的**参照实现**。
- `broca/agent_manager.py` — `TaskManager.get_task(task_id)`，delegate 模式用它校验 task 存在
- `broca/components/base.py` + `broca/components/registry.py` — 组件 ABC 基类 + 注册中心
- `broca/components/defaults.py` — 默认实现映射 + 作用域 + entry point 映射
- `broca/components/communicator.py` — Communicator ABC（SocketIO 通信层接口）
- `broca/agent.py` — Agent 类：`create()` 组合根、`start()` 消息循环、`run()` 执行入口
- `broca/agent_configs.py` — `AgentConfig` 数据类
- `broca/session/models.py` — `MessageType` 枚举 + `Message` 模型
- `broca/orchestration/blackboard.py` — Blackboard（保留，与 AgentMessenger 互补）
- `broca/communication/socketio_client.py` — SocketIO 客户端实现
- `broca/communication/socketio_server.py` — SocketIO 服务端（消息路由）

### ask_user 链路剖析（request 模式的模板）

`AskUser._execute()`（`broca/tools/agent_interaction.py`）的完整链路：

1. 生成 `request_id = uuid4()` + `asyncio.Event()`；
2. 登记到类级 `AskUserToolManager._pending_requests[request_id] = {"event", "answer": None}`（类级 lock）；
3. `communicator.send_message()` 发出 `AGENT_QUERY`（`data.request_id` 携带配对 ID）；
4. **阻塞** `await asyncio.wait_for(response_event.wait(), timeout=agent_query_timeout)`（默认 300s，`broca/configs.py: ExecutionConfig.agent_query_timeout`）；
5. 用户答复经 `user_answer` 事件到达 → communicator 的**独立事件处理器** `AskUserToolManager.handle_user_answer` 按 `request_id` 找到 pending 项、写入 `answer`、`event.set()`；
6. `_execute()` 被唤醒，读出 answer，`ToolResult(SUCCESS, content=answer)` 返回 → LLM 在同一 turn 内带着答案继续；
7. `finally` 清理 pending；超时返回 `ToolResult(ERROR, ...)`。

**关键机制**：回复之所以能在工具阻塞期间送达，是因为 `user_answer` 由 SocketIO 监听任务的 `_trigger_event` 直接派发到注册的 Python handler（`agent.py:148` 注册），**绕过 `start()` 的消息队列**。`request` 模式必须照搬这一点（见"与 mid-turn 消息处理的集成"）。

## 总体方案

### 架构定位

```
Agent
  ├── communicator (SocketIO, per-agent)  — 保留，agent↔user 通信
  ├── messenger (AgentMessenger, per-agent) — 新增，agent↔agent 通信
  └── blackboard tools (per-crew)         — 保留，编排期间共享状态
```

AgentMessenger 是**新增的第 22 个组件**，per-agent 作用域，在 `Agent.create()` 中初始化。

### 三种交互模式

| 模式 | 语义 | 交互方向（ACK / 回执） | 典型场景 |
|------|------|---------|----------|
| `request` | "请你做 X，把结果回给我，我等你" | **同步双段**：投递后阻塞等待回复；收到后工具返回、LLM 当前 turn 继续。**等 ACK + 等业务回复** | "帮我看看这个函数" / "帮我重构这个模块" |
| `notify` | "告诉你 X，不用回" | 单向：**等 ACK、不等回执**（fire-and-forget 仅指回执），**支持 mid-turn 注入** | "我改了接口，注意下" |
| `delegate` | "把 task_id 对应的任务交给你" | 投递 + 强制回执：**等 ACK、不等回执**（发送方不等对方执行完的回执） | 任务分配：把已存在的任务委派给指定 agent |

> **三种模式都等 ACK，区别只在是否等业务回复/回执**：投递都走 `send() -> dict` 并同步等传输层 ACK（≤2s）；ACK=`routing_failed` 一律快速失败（tool 返回 ERROR），避免"消息没投递出去却报告成功"。`request` 额外**阻塞**等 `AGENT_REQUEST_RESPONSE`（靠 `request_id` 配对），收到后返回 `(回复文本, 回复状态)` 交给 `Communicate` tool（状态映射见 Task 2.3），LLM 在同一 turn 内继续。notify / delegate 拿到 `routed` ACK 后立即返回，**不等业务回执**。

**delegate 模式——专用于任务分配，四条硬约束：**

1. **只用于 task 分配**：不是通用咨询/通知，消息内容就是一项任务。
2. **必须指定 `task_id`，且该 task 必须真实存在**：发送前用 `TaskManager.get_task(task_id)` 校验，不存在则拒绝（复刻现有 `AssignTask` background 分支的校验逻辑）。
3. **收信方必须回复**：用 `notify(kind="delegate_receipt", task_id=...)` 回执（try/finally，异常/abort 也回）。
4. **发送方不等回执、但要等 ACK**：同步等传输层 ACK 确认投递成功（`routed`），ACK 失败（目标不可达）立即抛错让委派方知道任务没交出去；拿到 `routed` 后立即返回，**不等待对方执行完的回执**（fire-and-forget 仅修饰回执）。

> delegate = "notify 的非阻塞投递" + "强制回执"；与 request 的差别：携带 `task_id` + 前置校验 + 回执走 `AGENT_NOTIFY`（非专用响应类型）+ **不等回执（但等 ACK）**。投递失败必须上报——否则委派方误以为任务已交出、不再跟进，任务会静默悬空。

### 所有回复的两条通道（关键区分）

| 回复类型 | 消息类型 | 配对方式 | 送达链路 | 发送方是否等业务回复 |
|---------|---------|---------|---------|--------------|
| **request 回复** | `AGENT_REQUEST_RESPONSE`（专用） | `data.request_id` 配对 pending Event | communicator **直接事件处理器** → `messenger.handle_request_response()` → `event.set()` | **是**（`asyncio.wait_for`） |
| **delegate 回执** | `AGENT_NOTIFY`（`kind="delegate_receipt"` + `task_id`） | 无配对 | `message_queue` → mid-turn 注入 / 新 turn | 否（但**等 ACK**） |
| **普通 notify** | `AGENT_NOTIFY`（`kind="notify"`） | 无配对 | 同上 | 否（但**等 ACK**） |

> **传输层 ACK 与业务回复是两件事**：三者在投递时都**同步等 ACK**（`send() -> dict`，≤2s）——ACK 只确认"消息被 server 路由到目标"，失败即快速报错；上表描述的是**业务回复/回执**是否等待。notify/delegate 不等回执，但 ACK 失败一样会抛错。
>
> **为什么 request 回复必须用专用类型 + 直接事件处理器**：发送方在工具调用里阻塞，`start()` 消息循环被 `run()` 占住，回复**不能**进 `message_queue`（否则无人消费 → 死锁）。必须与 `user_answer` 一样，由 SocketIO 监听任务直接触发 handler 唤醒 Event。delegate/notify 的回执不要求发送方继续，走 mid-turn 注入即可。

- `notify`：等 ACK 后 fire-and-forget 通知（不等回执），进入收信方 `message_queue`，mid-turn 注入当前 turn 的下一个 step 前。
- `delegate 回执`：收信方完成任务后用 `notify(kind="delegate_receipt", task_id=...)` 发回委派方，携带 task_id + kind 供业务/审计区分；注入链路与普通 notify 完全相同。
- 因此有 4 类消息类型（`AGENT_REQUEST` / `AGENT_REQUEST_RESPONSE` / `AGENT_NOTIFY` / `AGENT_DELEGATE`）；**无 `AGENT_DELEGATE_RESPONSE`**（回执复用 `AGENT_NOTIFY`）。

### 职责分离

| 层 | 职责 | 不做什么 |
|----|------|---------|
| **Messenger**（传输） | 投递消息到 target、执行前置校验/ACL/可选增强、管理 request 的 pending 配对与超时、记录审计 | 不决定 target 怎么处理、不干预回复内容 |
| **Agent**（决策） | 收到消息后自主决定怎么处理、回复什么内容 | 不管传输细节 |

### 统一通信方式（同进程 / 同 session 范围）

**同一进程、同一 session 内的 agent-to-agent 通信统一走 SocketIO 传输；跨进程 target 不在本期范围**：

```
Agent A (messenger.request)  ──AGENT_REQUEST──→  SocketIO Server  ──→  Agent B
                                                                        │ run() + try/finally
Agent A (event.set → 工具返回 → LLM 继续)  ←─AGENT_REQUEST_RESPONSE─  SocketIO Server  ←─  Agent B (messenger.reply)
```

Messenger 的传输依赖只有 `self.communicator`（SocketIO client），不直接调用 target agent 的方法。此外 delegate 模式额外依赖 `self._task_manager` 做 task 存在性前置校验（仅本地校验，不走 SocketIO）。

> **范围边界（评审 Feasibility #1 / Consistency #3）**：`_resolve_agent_id` 通过同步 `agent_factory.get_agent(session_id, target_name)` 做 name→id 解析，而 `DefaultAgentFactory`（`agent_manager.py:543`）**只查本地 `self._session_agents[session_id]`**，因此 target 必须与发送方处于同一进程、同一 session。跨进程 agent 名字无法在本地 factory 解析，`request` / `notify` / `delegate` 会在投递前抛 `AgentCommunicationError(reason="target_not_found")`。**跨进程 name→id 远端解析（如经 SocketIO 查询 server 端 agent 注册表）列为后续工作**，本期不实现；风险已登记在风险表。

### 与 mid-turn 消息处理的集成（两种链路并存）

**链路 1 — request 回复（同步，绕过消息队列，类 ask_user）**：

```
收信方 messenger.reply()
  → communicator.send(mode="request_reply", data={"request_id", "content", ...})
  → SocketIO Server 按 receiver_id 路由
  → 请求方 communicator "agent_request_response" 事件
  → _MessageDispatcher._table 映射到 "agent_request_response"
  → 注册的 handler = messenger.handle_request_response（ NOT _receive_message ）
  → 按 request_id 找到 _pending_requests[request_id] → 填 reply → event.set()
  → 阻塞中的 messenger.request() 被唤醒 → 返回 (回复文本, 回复状态) → Communicate tool → LLM 继续
```

> `AGENT_REQUEST_RESPONSE` **不加入** `_drain_user_messages` / `_make_message_source._Drainer` 的 `_drain_types`，也**不加入** `_inject_user_message._cross_agent_types`——它由直接事件处理器消费，不进 `message_queue`、不注入 context。这与 `USER_ANSWER` 的处理方式一致。

**链路 2 — notify / delegate 回执（异步，复用 mid-turn）**：

```
incoming AGENT_NOTIFY（普通通知 / delegate 回执）
  → communicator "agent_notify" 事件 → agent._receive_message()
  → client.message_queue
  → loop engine 的 _message_source.drain()（每个非终止 step 之后）
  → _inject_user_message()（from_agent=True）→ context
  → 下一个 step 的 LLM 立即感知（当前 turn 内生效，无需等下一 turn）
```

要点：
- `AGENT_NOTIFY` 加入 `_drain_user_messages` 和 `_make_message_source._Drainer` 的 `_drain_types` 集合（替代旧 TASK_* 同类位置）。
- `_inject_user_message` 的 `_cross_agent_types` 加入 `AGENT_NOTIFY`，使其以 `from_agent=True` 注入，并在末尾 step 不被吞掉（沿用 TC-10 的 terminal-step 处理）。
- 若收信方正忙（run 多 step）：mid-turn 在 step 间注入当前 turn；若空闲：消息留队列，由 `start()` 作为新 turn 处理。
- 普通 notify / delegate 回执以 `data.kind` + `task_id` 区分业务含义。

### 控制机制：核心必选 + 可选增强

只有**防止越权/保证协议正确/防止阻塞死锁**的是必选，其余做成可配置开关、默认关闭。task 校验是 delegate 的前置参数校验（业务语义），不算一层控制机制。

> **重要推论（本次修订）**：request 恢复阻塞等待后，原来的**超时**重新成为**核心必选**（`ask_user` 同样有 `agent_query_timeout`）；**环检测**对 request **始终启用**以防"A 等 B、B 又 request A"的死锁/循环级联。**熔断**仍删除（无跨请求失败统计需求）。notify / delegate 的环检测仍可选、默认关。

#### 核心机制（始终启用，不可关闭）

| 机制 | 适用模式 | 默认值 | 为什么必选 |
|------|---------|--------|-----------|
| **task 存在性校验** | 仅 delegate | `get_task(task_id)` 命中才放行 | delegate 的业务硬约束（复刻旧 `AssignTask` background 校验） |
| **静态 ACL** | 全部 | `allowed_targets=None`（不限制） | 越权通信是安全和正确性底线；配置不限制时零成本 |
| **回复保障** | request / delegate | 收信方 try/finally，异常/abort 也回 | 协议正确性：要求回执的模式无论如何都回一条，否则请求方悬空（request 会等到超时） |
| **request 超时** | 仅 request | `request_timeout=300`（秒），对齐 `agent_query_timeout` | 阻塞等待必须有界；无响应时抛 `AgentCommunicationError(reason="request_timeout")` 让工具返回 ERROR |
| **环检测（request）** | 仅 request | `max_chain_depth=3`，`would_create_cycle` 命中即拒 | 阻塞语义下 A↔B 互 request 会死锁；配合超时双重兜底 |

#### 可选增强（默认关闭，通过 `CommunicationPolicy` 开关启用）

| 机制 | 开关字段 | 适用模式 | 默认值 | 启用后作用 |
|------|---------|---------|--------|-----------|
| 消息链环检测 | `enable_chain_detection` | 仅 notify / delegate（request 已强制启用） | `False` | `max_chain_depth=3`，防 notify/delegate 的无限消息级联/刷屏 |
| Turn 预算 | `enable_budget` | 全部 | `False` | request=3 / notify=5 / delegate=3，限制每 turn 通信次数 |

> **环检测语义**：request 的环检测防"阻塞等待 + 循环 request 导致的死锁"（核心必选）；notify/delegate 的环检测（可选）防"A notify B → B notify A → …"的无限消息级联刷屏。两种情况下 CallChain 都随消息传递，检测在发信方 `_check_permissions` 中执行。
>
> **检查顺序**：task 校验(仅 delegate) → ACL(全部) → request 环检测(仅 request，核心) → 可选增强按开关：预算(全部) → 环检测(notify/delegate) → 投递；回复保障在收信方处理路径 try/finally 强制执行；request 超时在发信方 `wait_for` 处执行。

### 消息类型

新增 4 个 `MessageType` 枚举值：

```python
AGENT_REQUEST = "agent_request"             # source → target: 同步请求（要求回复，发送方阻塞等待）
AGENT_REQUEST_RESPONSE = "agent_request_response"  # target → source: request 回复（携带 request_id 配对，直接事件唤醒 Event）
AGENT_NOTIFY = "agent_notify"               # 普通通知 / delegate 回执（靠 data.kind + task_id 区分，mid-turn 注入）
AGENT_DELEGATE = "agent_delegate"           # source → target: 委派任务（携带 task_id，要求回执，发送方不等回执但等 ACK）
# 无 AGENT_DELEGATE_RESPONSE：delegate 回执复用 AGENT_NOTIFY
```

**删除** 3 个旧枚举值：`TASK_START` / `TASK_COMPLETE` / `TASK_ERROR`

### 删除清单（不做向后兼容）

- `AssignTask` tool 类（`broca/tools/agent_interaction.py`）
- `MessageType.TASK_START` / `TASK_COMPLETE` / `TASK_ERROR`
- `Agent._handle_task()` 方法（其"run + 回执 try/finally"职责由 `_handle_incoming_request` / `_handle_incoming_delegate` 承接）
- `Agent.start()` 中 `TASK_START` / `TASK_COMPLETE` / `TASK_ERROR` 分支
- `MessageProtocol.create_task_start()` / `create_task_complete()` / `create_task_error()`（`broca/session/models.py`）
- `Communicator.send_task_start()` / `send_task_complete()` / `send_task_error()`
- `SocketIOClient` 对应实现（`send_task_*` 方法、`_MessageDispatcher._table` 的 3 个 TASK 条目、`on_task_start` / `on_task_complete` 装饰器）
- **所有 `_cross_agent_types` 中的 TASK 引用**：`broca/loop_engine/engine.py` 共 3 处（`_persist_user_message` 1 处 + `_inject_user_message` 2 处，约 L394/L453/L459），改为 `AGENT_NOTIFY`；`llm.py parse_message()` 中 3 个 TASK_* 分支（约 L228-232）改为处理新类型或删除
- `agent.py` 中两处 `_drain_types` 的 docstring/注释对 `TASK_COMPLETE` / `TASK_ERROR` 的引用（约 L497/L531），随迁移改为 `AGENT_NOTIFY`
- `_drain_user_messages` / `_make_message_source` 中 TASK 相关引用
- `CrewOrchestratorRunner` 中使用 `send_task_start` 的地方改为 `messenger.delegate()`（任务分配走 delegate 模式）
- Agent 配置文档中 `assign_task` 工具引用
- 测试文件中对已删除类型的引用：`test_llm.py` / `test_save_user_message_no_mutation.py` / `test_non_blocking_mode.py` / `test_handle_task_assigner_defense.py` / `test_communicator_abc.py`（详见 Task 3.3；这些测试需随删除同步更新，否则全量回归会失败）
- **不修改**历史迁移 `broca/alembic/versions/259719598877_init_database.py` 中的枚举快照（仅历史记录），但 Task 3.3 的 grep 需排除 alembic 目录

### 废弃策略

**无废弃**——直接删除。Agent 配置中 `tools: ["assign_task"]` 需要改为 `tools: ["communicate"]`。

---

## 执行计划

### 前置验证（Phase 0）

- [ ] 检查 `pyproject.toml` 中 python-socketio 版本（`poetry show python-socketio`）
- [ ] 阅读该版本 `AsyncClient.emit(event, data, callback=fn)` 文档，确认 callback 能接收 server handler 的返回值（Task 2.4 ACK 用）
- [ ] **确认 server 端 `@sio.event async def message(sid, data)` 的 `return` 值会作为 ACK data 回传给 client 的 emit callback**（python-socketio 语义：handler 返回值即 ACK 参数）；这是 Task 2.4 让 `_process_message` 返回路由结果的前提
- [ ] 确认 `AsyncClient` 的 socketio 事件监听任务与 `start()` 消息循环在不同 task 运行（ask_user 链路的前提；已由 `socketio_client.py` 的 `@sio.event async def message` → `_dispatcher.dispatch` → `_trigger_event` 验证）
- [ ] 若 emit callback 不支持：记录备选方案（server 额外 emit `agent_send_ack` 事件），Task 2.4 需调整
- [ ] **确认 `TaskManager.get_task` 是否为协程**（评审 r3 Feasibility #3）：`broca/agent_manager.py` 中 `get_task` 若为同步 `def`，则 `_check_task_exists` / `_handle_incoming_delegate` 中的 `await self._task_manager.get_task(...)` 需去掉 `await`；若为 `async def` 则保留。据此统一 Task 2.1 / Task 2.2 的调用写法

**阶段验收标准**：4 项检查全部确认；emit callback 支持与否的结论记录到"未解决的问题"第 1 项，作为 Task 2.4 的前置依赖门槛（**决策截止：Phase 1 结束前**，未提供备选则 Task 2.4 按主方案执行）。

---

### Phase 1: 基础设施

**目标**：搭建 AgentMessenger 组件骨架 + 全部控制原语 + 清理旧代码

**阶段验收标准**：
- [ ] `AgentMessenger` ABC 定义完成，注册到 `ComponentRegistry`（`defaults.py`）
- [ ] `CallChain`、`CommunicationPolicy`、`CommunicationBudget`、`AuditLogger` 4 个控制原语实现完成（熔断已删除；**request 超时参数在 CommunicationPolicy 中恢复**）
- [ ] `MessageType` 新增 `AGENT_REQUEST` / `AGENT_REQUEST_RESPONSE` / `AGENT_NOTIFY` / `AGENT_DELEGATE` 四个值
- [ ] `MessageType` 旧值 `TASK_START` / `TASK_COMPLETE` / `TASK_ERROR` 已删除
- [ ] `AssignTask` tool 已删除；`MessageProtocol.create_task_start/complete/error` 已删除
- [ ] `Agent._handle_task()` 及相关分支已删除
- [ ] `Communicator` ABC 中 `send_task_*` 方法已删除
- [ ] `broca/loop_engine/engine.py` 3 处 `_cross_agent_types` TASK 引用、`llm.py` 3 个 TASK_* 分支、`agent.py` 两处 `_drain_types` docstring TASK 引用已清理
- [ ] 控制原语通过 import 检查 + inline 断言验证（完整单测在 Phase 3 Task 3.1）
- [ ] **生产代码无引用断裂**：`grep -rn "TASK_START\|TASK_COMPLETE\|TASK_ERROR\|AssignTask\|_handle_task\|send_task_\|create_task_" broca/ --include=*.py --exclude-dir=alembic --exclude-dir=tests` 无结果
- [ ] **测试文件更新时序（评审 Structure #1 / Consistency #2）**：引用已删枚举/方法的 5 个测试文件（`test_llm.py` / `test_save_user_message_no_mutation.py` / `test_non_blocking_mode.py` / `test_handle_task_assigner_defense.py` / `test_communicator_abc.py`）按 Task 1.1 AC 统一在 **Task 3.3** 更新；Phase 1/2 期间这些文件允许 xfail / 收集失败，**不以"全量 pytest 通过"作为本阶段硬门槛**。全量 pytest 通过的硬性验收只在 Phase 3（Task 3.3），保证时序前后一致

---

#### Task 1.1: AgentMessenger ABC + 消息模型 + 删除旧代码

- **目标**：定义 `AgentMessenger` 组件接口 + `AgentCommunication` 数据类 + 删除 `AssignTask` 和相关旧代码
- **步骤**：
  1. 创建 `broca/components/agent_messenger.py`，定义 `AgentMessenger(BaseComponent, ABC)`：
     ```python
     class AgentMessenger(BaseComponent, ABC):
         agent_id: str
         session_id: str
         name: str  # agent name (用于消息标识)

         @abstractmethod
         async def initialize(self, agent_id: str, name: str, session_id: str,
                              communicator: "Communicator",
                              agent_factory: "AgentFactory",
                              task_manager: "TaskManager | None" = None,
                              config: "AgentConfig | None" = None) -> None:
             """初始化 messenger。agent_factory 用于解析 target_name → agent_id，
             task_manager 用于 delegate 的 task 存在性前置校验。

             config 是 AgentConfig（**不是 CommunicationPolicy**）：实现内部须执行
             self._config = config.communication_policy，并用 config.workspace 初始化审计。
             """
             ...

         @abstractmethod
         async def request(self, target_name: str, message: str,
                           context: str = "") -> tuple[str, str]:
             """同步请求（类 ask_user）：投递后阻塞等待收信方的 AGENT_REQUEST_RESPONSE。

             通过 request_id 配对 pending Event；收到后返回 (回复文本, 回复状态)，
             status ∈ {'success','error','aborted'}，供 Communicate tool 据此映射
             ToolResult 状态/内容，LLM 在当前 turn 内继续执行。超时抛
             AgentCommunicationError(reason='request_timeout')。
             """
             ...

         @abstractmethod
         async def notify(self, target_name: str, message: str,
                          task_id: str | None = None,
                          kind: str = "notify") -> None:
             """向目标 agent 发送通知：等 ACK、不等回执（fire-and-forget 仅指回执）。

             ACK 为 routing_failed 时抛 AgentCommunicationError（调用方据此上报）。
             所有通知/回执复用本方法：
               - delegate 回执：kind="delegate_receipt"（带 task_id）
             普通通知用默认 kind="notify"。
             （request 回复不走这里，走专用 reply() → AGENT_REQUEST_RESPONSE。）
             """
             ...

         @abstractmethod
         async def delegate(self, target_name: str, task_id: str,
                            message: str) -> None:
             """把 task_id 对应的任务委派给目标 agent（仅任务分配）。

             task_id 必须存在（前置校验）；**等 ACK**（routing_failed 抛错，
             task 没交出去必须让委派方知道）；拿到 routed 后立即返回——
             fire-and-forget 仅指不等对方执行完的回执，收信方仍必须用 notify() 回执。
             """
             ...

         @abstractmethod
         async def reply(self, request_id: str, target_name: str,
                         content: str, status: str = "success") -> None:
             """回复一条 request（收信方调用），发送专用 AGENT_REQUEST_RESPONSE。

             request_id 必须与收到的 AGENT_REQUEST 一致，供请求方配对唤醒 Event。
             status: success / error / aborted（业务含义，仅供审计与日志）。
             """
             ...

         @abstractmethod
         async def handle_request_response(self, message: "Message") -> None:
             """由 communicator 的 'agent_request_response' 事件直接调用
             （绕过 message_queue，类 ask_user 的 handle_user_answer）。

             按 message.data['request_id'] 找到 pending 请求，写入回复并 event.set()。
             """
             ...

         @abstractmethod
         def set_call_chain(self, chain: "CallChain") -> None:
             """由 Agent.run() 入口设置当前调用链。"""
             ...

         @abstractmethod
         def reset_budget(self) -> None:
             """由 Agent.run() 入口重置 per-turn 通信预算。"""
             ...
     ```
  2. 创建 `broca/agent_messenger/` 目录 + `__init__.py`
  3. 创建 `broca/agent_messenger/message_models.py`：
     ```python
     @dataclass
     class AgentCommunication:
         source_agent: str
         target_agent: str
         mode: str              # "request" | "request_reply" | "notify" | "delegate"
         content: str
         context: str = ""
         task_id: str | None = None     # delegate 投递 + delegate 回执携带
         kind: str = "notify"           # 仅 AGENT_NOTIFY 用："notify" | "delegate_receipt"
         request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])  # request/request_reply 配对
         status: str = "success"        # 仅 request_reply：success / error / aborted（审计用）
         call_chain: dict = field(default_factory=dict)  # CallChain.to_dict()

         def to_dict(self) -> dict:
             return {
                 "source_agent": self.source_agent,
                 "target_agent": self.target_agent,
                 "mode": self.mode,
                 "content": self.content,
                 "context": self.context,
                 "task_id": self.task_id,
                 "kind": self.kind,
                 "request_id": self.request_id,
                 "status": self.status,
                 "call_chain": self.call_chain,
             }

         @classmethod
         def from_message_data(cls, data: dict) -> "AgentCommunication":
             """从 Message.data 反序列化（SocketIO 路由后由 target 端调用）。"""
             return cls(
                 source_agent=data["source_agent"],
                 target_agent=data["target_agent"],
                 mode=data["mode"],
                 content=data["content"],
                 context=data.get("context", ""),
                 task_id=data.get("task_id"),
                 kind=data.get("kind", "notify"),
                 request_id=data.get("request_id", ""),
                 status=data.get("status", "success"),
                 call_chain=data.get("call_chain", {}),
             )
     ```

     > request 回复就是一条 `AgentCommunication(mode="request_reply", request_id=..., content=<回复文本>)`；回复文本放在 `content`，由 `messenger.handle_request_response()` 读出并唤醒 Event。无独立 `AgentRequestResponse` dataclass（数据同构，靠 mode 区分）。
  4. `MessageType` 新增 + 删除（`broca/session/models.py`）：
     ```python
     # 新增
     AGENT_REQUEST = "agent_request"
     AGENT_REQUEST_RESPONSE = "agent_request_response"   # ← 恢复专用 request 回复类型
     AGENT_NOTIFY = "agent_notify"
     AGENT_DELEGATE = "agent_delegate"
     # 无 AGENT_DELEGATE_RESPONSE：delegate 回执复用 AGENT_NOTIFY

     # 删除
     # TASK_START = "task_start"      ← 删
     # TASK_COMPLETE = "task_complete" ← 删
     # TASK_ERROR = "task_error"      ← 删
     ```
     同时删除该类中的 `MessageProtocol.create_task_start()` / `create_task_complete()` / `create_task_error()` 三个静态方法（约 L720-760）。
  5. **删除 `AssignTask`**（`broca/tools/agent_interaction.py`）：
     - 删除 `AssignTask` 类整个定义
     - 保留 `AskUserToolManager` 和 `AskUser`
     - **新增的 `Communicate` tool（含 request/notify/delegate 三模式）直接写入本文件**（见 Task 2.3），不新建 `broca/tools/communicate.py`
  6. **删除 Agent 中 TASK 相关代码**（`broca/agent.py`）：
     - `start()` 消息循环中删除 `TASK_START` / `TASK_COMPLETE` / `TASK_ERROR` 三个 elif 分支
     - 删除 `_handle_task()` 方法
     - `_drain_user_messages` 和 `_make_message_source` 中删除 `TASK_COMPLETE` / `TASK_ERROR` 的引用；同时改这两处 `_drain_types` 的 docstring（约 L497/L531 提到 TASK_* 的措辞）
     - `Agent.create()` 中删除 3 个 `register_event_handler("task_start" / "task_complete" / "task_error", ...)` 调用（约 L136-138）
  7. **清理 `broca/loop_engine/engine.py` 的 3 处 `_cross_agent_types`**（约 L394 / L453 / L459，跨 `_persist_user_message` 与 `_inject_user_message` 两个函数）：本阶段先把 `MessageType.TASK_COMPLETE, MessageType.TASK_ERROR` 引用删除；`AGENT_NOTIFY` 的加入在 Task 2.2 Step 7 统一完成（见评审 Finding 1.1 / 5.2）
  8. **清理 `broca/llm.py` 的 3 个 TASK_* 分支**（`parse_message()` 约 L228-232）：删除 `elif message.message_type == MessageType.TASK_START/COMPLETE/ERROR` 分支；新 AGENT_* 类型的文本解析由 Task 2.2/2.3 按需补充（request 回复不进 LLM 文本解析，notify/delegate 走 USER_MESSAGE 通用解析）
  9. **删除 Communicator ABC 中 `send_task_*` 方法**（`broca/components/communicator.py`）
  10. **删除 SocketIOClient 对应实现**（`broca/communication/socketio_client.py`）：3 个 `send_task_*` 方法、`_MessageDispatcher._table` 的 3 个 TASK 条目、`on_task_start` / `on_task_complete` 事件装饰器
  11. 搜索全代码库清理其他引用：`grep -rn "task_start\|task_complete\|task_error\|TASK_START\|TASK_COMPLETE\|TASK_ERROR\|AssignTask\|_handle_task\|create_task_start\|create_task_complete\|create_task_error" broca/ --include=*.py`（**排除** `broca/alembic/` 历史迁移与测试文件的最终处理在 Task 3.3）
- **预期产出**：新文件 3 个 + 多文件修改 + 旧代码删除
- **验收标准**：
  - [ ] `AgentMessenger` 是 `BaseComponent` 和 `ABC` 的子类，有 `initialize`、`request`、`notify`、`delegate`、`reply`、`handle_request_response`、`set_call_chain`、`reset_budget` 八个抽象方法
  - [ ] `MessageType.AGENT_REQUEST` / `AGENT_REQUEST_RESPONSE` / `AGENT_NOTIFY` / `AGENT_DELEGATE` 四个值可正常导入，`AGENT_DELEGATE_RESPONSE` 不存在
  - [ ] 无 `AgentRequestResponse` dataclass
  - [ ] `AgentCommunication(mode="delegate", task_id="...")`、`AgentCommunication(mode="request_reply", request_id="R1", content="ok")`、`AgentCommunication(mode="notify", kind="delegate_receipt", task_id="...")` 的 `to_dict()` / `from_message_data()` 往返保留 `kind` / `task_id` / `request_id` / `status`
  - [ ] `MessageType.TASK_START` / `TASK_COMPLETE` / `TASK_ERROR` 不存在（已删除）；`MessageProtocol.create_task_start/complete/error` 不存在
  - [ ] `AssignTask` 类不存在；`Agent._handle_task` 方法不存在
  - [ ] `Agent.start()` 消息循环只处理 `USER_MESSAGE` / `AGENT_REQUEST` / `AGENT_NOTIFY` / `AGENT_DELEGATE` / `COMMAND`；其中 `AGENT_NOTIFY` 加入 drain 类型集合（mid-turn 注入）
  - [ ] `broca/loop_engine/engine.py` 无 `_cross_agent_types` 中残留的 TASK 引用；`broca/llm.py parse_message()` 无 TASK_* 分支
  - [ ] `grep -rn "AssignTask\|_handle_task\|send_task_start\|send_task_complete\|send_task_error\|TASK_START\|TASK_COMPLETE\|TASK_ERROR\|create_task_start\|create_task_complete\|create_task_error" broca/ --include=*.py` 在生产代码中无结果（**排除** `broca/alembic/`；测试文件的同步更新在 Task 3.3 验收）
  - [ ] `from broca.components.agent_messenger import AgentMessenger` 导入成功

---

#### Task 1.2: 消息链追踪 + 通信策略配置

- **目标**：实现 `CallChain`（消息链追踪 + 环检测）和 `CommunicationPolicy`（AgentConfig 新增字段）
> 依赖: Task 1.1（message_models.py 提供 dataclass 基础）
- **步骤**：
  1. 创建 `broca/agent_messenger/call_chain.py`：
     ```python
     @dataclass
     class CallChain:
         """追踪消息转发的 agent 链。request 始终用于防死锁；
         notify/delegate 仅 enable_chain_detection=True 时使用（防刷屏）。

         随消息传递：每跳的接收方把自身 agent_id 追加进链。
         """
         agent_ids: list[str] = field(default_factory=list)

         @property
         def depth(self) -> int:
             return len(self.agent_ids)

         def would_create_cycle(self, target_agent_id: str) -> bool:
             return target_agent_id in self.agent_ids

         def is_within_depth(self, max_depth: int) -> bool:
             return len(self.agent_ids) < max_depth

         def add(self, agent_id: str) -> "CallChain":
             return CallChain(agent_ids=self.agent_ids + [agent_id])

         def to_dict(self) -> dict:
             return {"agent_ids": list(self.agent_ids)}

         @classmethod
         def from_dict(cls, data: dict | None) -> "CallChain":
             if not data:
                 return cls()
             return cls(agent_ids=data.get("agent_ids", []))

         def describe(self) -> str:
             return " → ".join(self.agent_ids) if self.agent_ids else "(empty)"
     ```
  2. 在 `broca/agent_configs.py` 新增 `CommunicationPolicy`：
     ```python
     @dataclass
     class CommunicationPolicy:
         """Agent 间通信策略配置。

         核心机制（ACL / task 校验 / 回复保障 / request 超时+环检测）始终生效；
         enable_* 两个开关默认 False，对应 notify/delegate 的可选增强。
         """
         # --- 核心：ACL（始终生效） ---
         allowed_targets: list[str] | None = None  # None = 不限制
         allowed_modes: list[str] | None = None    # None = 所有模式
         # --- 核心：request 超时（始终生效，对齐 agent_query_timeout） ---
         request_timeout: float = 300.0
         max_chain_depth: int = 3                  # request 环检测也用这个
         # --- 可选增强开关（默认关闭，仅约束 notify/delegate；request 已强制环检测） ---
         enable_chain_detection: bool = False
         enable_budget: bool = False
         # --- 可选增强的参数 ---
         max_requests_per_turn: int = 3
         max_notifies_per_turn: int = 5
         max_delegates_per_turn: int = 3
     ```
  3. `AgentConfig.__init__` 新增 `self.communication_policy = CommunicationPolicy()`
  4. `AgentConfig.from_config()` 处理 dict→dataclass 反序列化
- **预期产出**：`broca/agent_messenger/call_chain.py`、`AgentConfig.communication_policy` 字段
- **验收标准**：
  - [ ] `CallChain(["a", "b"]).would_create_cycle("a")` 返回 `True`
  - [ ] `CallChain(["a", "b", "c"]).is_within_depth(3)` 返回 `False`
  - [ ] `AgentConfig().communication_policy` 两个开关 `enable_chain_detection` / `enable_budget` 默认均为 `False`
  - [ ] `CommunicationPolicy` 无 `enable_circuit_breaker` / 熔断相关字段；**有 `request_timeout=300.0`**
  - [ ] `AgentConfig().communication_policy.max_chain_depth == 3`
  - [ ] `AgentConfig.from_config({"communication_policy": {"enable_budget": True, "request_timeout": 10, "max_chain_depth": 5}})` 正确解析

---

#### Task 1.3: 运行时增强原语（Budget + AuditLogger）

- **目标**：实现 per-turn 预算（**可选增强，默认不启用**）和审计日志（始终启用）
- **说明**：Budget 仅在 `enable_budget=True` 时被 messenger 调用；AuditLogger 不属于控制机制（只是记录），始终启用。熔断原语已删除（无跨请求失败统计需求）。
> 依赖: Task 1.2（`CommunicationPolicy` dataclass 作为 Budget 的配置来源）
- **步骤**：
  1. `broca/agent_messenger/budget.py`：
     ```python
     class CommunicationBudget:
         """Per-agent, per-turn 通信预算（可选增强，enable_budget=True 才接入）。
         每个 turn 开始时 reset()。"""
         def __init__(self, policy: CommunicationPolicy):
             self.policy = policy
             self._counters: dict[str, int] = {}

         def can_communicate(self, mode: str) -> bool:
             limit = self._get_limit(mode)
             return self._counters.get(mode, 0) < limit

         def consume(self, mode: str) -> bool:
             if not self.can_communicate(mode):
                 return False
             self._counters[mode] = self._counters.get(mode, 0) + 1
             return True

         def remaining(self, mode: str) -> int:
             return max(0, self._get_limit(mode) - self._counters.get(mode, 0))

         def reset(self) -> None:
             self._counters.clear()

         def _get_limit(self, mode: str) -> int:
             return {"request": self.policy.max_requests_per_turn,
                     "notify": self.policy.max_notifies_per_turn,
                     "delegate": self.policy.max_delegates_per_turn}.get(mode, 1)
     ```
  2. `broca/agent_messenger/audit.py`：
     ```python
     @dataclass
     class CommunicationEvent:
         timestamp: str
         source_agent: str
         target_agent: str
         mode: str            # "request" | "request_reply" | "notify" | "delegate"
         message_summary: str # 截断到 200 字符
         task_id: str | None = None
         kind: str = "notify"
         request_id: str = ""
         result: str          # routed / replied / rejected / timeout / routing_failed
                              # （routed=已投递待回复；replied=收到回复；由 request() 的局部
                              #  final_result 精确记录，避免 routing_failed 被误记为 timeout）
         call_depth: int
         duration_ms: float
         rejection_reason: str | None = None

     class AuditLogger:
         def __init__(self, workspace: str): ...
         def log(self, event: CommunicationEvent) -> None: ...
     ```
- **预期产出**：2 个文件（`budget.py`、`audit.py`；无 `circuit_breaker.py`）
- **验收标准**：
  - [ ] Budget：`consume("request")` 调用 3 次后返回 `False`
  - [ ] Budget：`consume("delegate")` 调用 3 次后返回 `False`（`max_delegates_per_turn`）
  - [ ] Budget：`reset()` 后重新可消费
  - [ ] `broca/agent_messenger/circuit_breaker.py` 不存在
  - [ ] AuditLogger：`log(event)` 在 workspace 下生成 JSONL 文件

---

#### Task 1.4: 注册到 ComponentRegistry + Communicator ABC 扩展 + AgentFactory 扩展

- **目标**：注册 `AgentMessenger` + 扩展 `Communicator` ABC + 扩展 `AgentFactory` ABC + 迁移 `CrewOrchestratorRunner`
> 依赖: Task 1.1（AgentMessenger ABC + message models）、Task 1.2（CommunicationPolicy）
- **步骤**：
  1. `broca/components/defaults.py`：
     - `_DEFAULT_IMPLS` 新增：`AgentMessenger: "broca.agent_messenger.messenger:DefaultAgentMessenger"`
     - `COMPONENT_SCOPES` 新增：`AgentMessenger: "per-agent"`
     - `ENTRY_POINT_NAMES` 新增：`"agent_messenger": AgentMessenger`
     - 更新文件头 docstring：删去过时的"**Phase 1** populates only the 7 core components. The remaining 16 components are added incrementally in Phase 5 / Phase 6."（实际 `_DEFAULT_IMPLS` 有 21 条，7+16=23 的说法已过时），改为准确表述："**All components** are registered here and resolved incrementally as they are implemented (21 existing + `AgentMessenger` = 22)." 同时把第 45 行 `# Phase 1: 7 core components.` 与第 108 行 `# Phase 1: 7 core components. Phase 5 will add the remaining 16.` 两处注释同步改为 `# Component implementations (22 total).`
  2. `broca/components/__init__.py` 导出 `AgentMessenger`
  3. **`send()` 返回契约（关键，统一 str/dict 矛盾——见评审 Critical）**：`send()` 是全新方法，无历史调用者，**统一契约定义为「返回 ACK 路由结果 dict」**：
     ```python
     # broca/components/communicator.py
     @abstractmethod
     async def send(
         self, content: str, data: dict, receiver_id: str
     ) -> dict:
         """发送 agent-to-agent 通信消息，返回 server 的路由 ACK。

         返回值为路由结果 dict：
           {"status": "routed"} 或
           {"status": "routing_failed", "reason": "unknown_receiver", ...}
         所有消息（请求/回复/通知/委派/回执）都走这一个方法；
         message_type 由 data["mode"] 决定（见 SocketIOClient._SEND_TYPE_BY_MODE）。
         注意：这与 send_message() 的 -> str (message_id) 是两个不同方法；
         send_message() 保持不变，不影响现有 10+ 调用者。
         """
         ...
     ```
     > **数据流（贯穿 ABC → 实现 → 调用点）**：`messenger → communicator.send() -> dict` → `messenger._send_and_check_ack()` 直接对**这个 dict** 调 `.get("status")`。**不得**对 `send_message()` 的 `str` 返回值调 `.get()`。
  4. `broca/components/agent_factory.py` 新增 `get_agent()` 方法（**同步 `def`，不是 `async def`——见评审 Major #2**）：
     ```python
     @abstractmethod
     def get_agent(self, session_id: str, agent_name: str) -> "Agent | None":
         """按 name 查找当前 session 中已创建的 agent 实例（同步方法）。"""
         ...
     ```
     > `DefaultAgentFactory.get_agent()`（`agent_manager.py:543`）现有实现就是同步 `def`，`messenger._resolve_agent_id()` 也按同步调用（无 `await`）。ABC 声明必须与之保持一致，全文不得出现 `await get_agent(...)`。
  5. `SocketIOClient` 实现 `send` + **ACK 通道**（把原 Task 2.4 的 emit callback 能力前移到这里，使 `send()` 一旦就绪即返回 dict，消除 Task 2.1↔2.4 依赖倒置——见评审 Major #5）：
     ```python
     _SEND_TYPE_BY_MODE = {
         "request": MessageType.AGENT_REQUEST,
         "request_reply": MessageType.AGENT_REQUEST_RESPONSE,  # ← 专用 request 回复
         "notify": MessageType.AGENT_NOTIFY,
         "delegate": MessageType.AGENT_DELEGATE,
     }

     async def send(self, content, data, receiver_id) -> dict:
         msg = Message(
             message_type=self._SEND_TYPE_BY_MODE[data["mode"]],
             role=MessageRole.AGENT,
             sender_id=self.agent_id,
             receiver_id=receiver_id,       # ← 在 Message 构造时设置
             subscription=self.session_id,
             content=content,
             data=data,
         )
         return await self._send_message_with_ack(msg)

     async def _send_message_with_ack(self, message: Message) -> dict:
         """用 socketio emit callback 拿 server handler 的返回值作为 ACK。

         与 send_message() 的 callback 参数（按 message_id 的响应回调，写入
         self.message_callbacks）是两套不同机制：这里用独立参数名 ack_fn +
         独立 Future，不复用也不冲突。
         """
         loop = asyncio.get_running_loop()  # Python 3.14 已弃用 get_event_loop()，async 上下文取运行中 loop（评审 r3 Feasibility #2）
         ack_future: asyncio.Future = loop.create_future()
         def ack_fn(result):
             if not ack_future.done():
                 ack_future.set_result(result)
         await self.sio.emit("message", MessageProtocol.to_dict(message), callback=ack_fn)
         try:
             return await asyncio.wait_for(ack_future, timeout=self._ack_timeout)
         except asyncio.TimeoutError:
             return {"status": "routing_failed", "reason": "ack_timeout"}
     ```
     > `_ack_timeout` 为新增实例字段，在 `SocketIOClient.__init__` 中初始化（默认 2.0s，仅覆盖 server 本地路由确认的往返，不占用 `request_timeout` 的 300s 预算）。
     >
     > **server 端配套改动（也在本 Task 完成）**：
     > ```python
     > # socketio_server.py — message 事件 handler（约 L301）
     > @self.sio.event
     > async def message(sid, data):
     >     ...  # 解析出 message
     >     result = await self._process_message(sid, message)
     >     return result   # ← server handler 的返回值即 emit callback 收到的 ACK data
     >
     > # _process_message（约 L430）签名不变，但显式返回路由结果
     > async def _process_message(self, sid: str, message: Message) -> dict:
     >     ...
     >     if message.receiver_id:
     >         result = await self._send_to_client(message.receiver_id, message)
     >         if result is False:
     >             await self._send_error(sid, {"code": "ROUTING_FAILED", ...}, message.sender_id)
     >             return {"status": "routing_failed", "reason": "unknown_receiver"}
     >         return {"status": "routed"}
     >     ...  # room/subscription/broadcast 分支各自 return {"status": "routed"}
     >     return {"status": "routed"}
     > ```
     > **与既有 `_send_error(ROUTING_FAILED)` 的关系（评审 Minor #1）**：两者**并存、消费方不同、不重复触发**。ACK 返回值是给 messenger 做快速失败的**程序化信号**；`_send_error` 发出的 `MessageType.ERROR` 是给 UI/前端展示的**用户可见错误消息**，保持现有行为不变。Phase 0 确认 server handler 返回值可作为 ACK data；若不支持，见 Task 2.4 备选方案。
  6. 更新 `SocketIOClient` 中 `_MessageDispatcher._table`：
     - 删除 `MessageType.TASK_START` / `TASK_COMPLETE` / `TASK_ERROR` 对应的 3 个条目
     - 新增 4 个条目：
       ```python
       MessageType.AGENT_REQUEST: "agent_request",                     # → _receive_message → start() → _handle_incoming_request
       MessageType.AGENT_REQUEST_RESPONSE: "agent_request_response",   # → messenger.handle_request_response（直接 set Event，不进 queue）
       MessageType.AGENT_NOTIFY: "agent_notify",                       # → _receive_message → message_queue（mid-turn）
       MessageType.AGENT_DELEGATE: "agent_delegate",                   # → _receive_message → start() → _handle_incoming_delegate
       ```
     - 在 `Agent.create()` 注册事件处理器（详见 Task 2.2 Step 3）——**注意 request 回复走专用 handler，绕过 message_queue**：
       ```python
       agent.communicator.register_event_handler("agent_request", agent._receive_message)
       agent.communicator.register_event_handler(
           "agent_request_response", agent.messenger.handle_request_response
       )  # ← 类 ask_user 的 user_answer handler，直接唤醒 Event
       agent.communicator.register_event_handler("agent_notify", agent._receive_message)
       agent.communicator.register_event_handler("agent_delegate", agent._receive_message)
       ```
     - `AGENT_NOTIFY` 加入两处 drain 类型集合 + `engine.py` 3 处 `_cross_agent_types`（共 5 处，详见 Task 2.2 Step 7）；`AGENT_REQUEST_RESPONSE` **不加**
  7. **迁移 `CrewOrchestratorRunner`**（`broca/session_runner/orchestrator_runner.py`）：
     - 搜索所有 `send_task_start` / `send_task_complete` / `send_task_error` 调用点
      - `send_task_start` → `messenger.delegate(target, task_id, task)`（任务分配改走 delegate：携带 task_id、强制回执、发送方不等回执但**等 ACK**——投递失败抛错由编排器处理，避免任务静默悬空；拿到 routed ACK 后保持 fire-and-forget 时序）
     - `send_task_complete` / `send_task_error` → target agent 侧由 delegate 的强制回执承载（**回执用 `notify()` 发 `AGENT_NOTIFY`，带 `kind="delegate_receipt"` + `task_id`**），不再单独发消息
     - 注意：编排场景**必须用 `delegate()`**（任务分配专用模式）。request 现在是阻塞的，会改变编排时序，禁止用它替代 `send_task_start`；在 Task 1.4 Step 7 迁移时明确注释
- **预期产出**：`defaults.py` 修改、`__init__.py` 修改、`communicator.py` 新增 `send`、`agent_factory.py` 新增方法、`socketio_client.py` 新增实现 + dispatch table 更新、`orchestrator_runner.py` 迁移
- **验收标准**：
  - [ ] `from broca.components import AgentMessenger` 导入成功
  - [ ] `ComponentRegistry.get(AgentMessenger, scope_key="test")` 返回实例
  - [ ] `AgentFactory` ABC 包含 **`同步 def`** `get_agent()` 方法声明；与 `DefaultAgentFactory.get_agent` 及 `_resolve_agent_id` 调用点（无 `await`）三处口径一致；全文无 `await ...get_agent(...)`
  - [ ] `defaults.py` docstring 无 "7 core" / "16 remaining" / "7+16=23" 过时表述；明确 21 现有 + 1 新增 = 22
  - [ ] `test_components_registry.py` 全量通过
  - [ ] `Communicator.send` ABC 签名返回类型为 `dict`（非 `str`）；`SocketIOClient.send` 返回类型同为 `dict`
  - [ ] `SocketIOClient.send` 正确构造 Message（`receiver_id` 在 Message 对象上）；`mode="request_reply"` → `AGENT_REQUEST_RESPONSE`，`mode="delegate"` → `AGENT_DELEGATE`，`mode="notify"` → `AGENT_NOTIFY`
  - [ ] `Communicator` / `SocketIOClient` 无 `reply` 方法（reply 通过 `send(mode="request_reply")`）
  - [ ] `_send_message_with_ack` 用独立 `ack_fn` + Future，与 `send_message()` 的 `callback`（`message_callbacks`）互不影响；`send()` 返回 `{"status": "routed"}` 或 `{"status": "routing_failed", ...}`，超时返回 `{"status": "routing_failed", "reason": "ack_timeout"}`
  - [ ] server `message` handler `return await self._process_message(sid, message)`；`_process_message` 显式返回 dict（routed / routing_failed）；既有 `_send_error(ROUTING_FAILED)` 保留不变
  - [ ] `_MessageDispatcher._table` 无 `TASK_*` 条目，包含 4 个新 `AGENT_*` 条目；`agent_request_response` 映射到专用 handler 而非 `_receive_message`
  - [ ] `CrewOrchestratorRunner` 无 `send_task_*` 引用，`send_task_start` 已迁移为 `messenger.delegate()`

---

### Phase 2: 核心实现

**目标**：完成 `DefaultAgentMessenger` 实现 + Agent 集成 + `Communicate` tool + ACK 通路端到端验证（ACK 实现已在 Task 1.4 前移完成）

**阶段验收标准**：
- [ ] `DefaultAgentMessenger` 实现 `request`（阻塞+配对+超时）/ `reply` / `handle_request_response` / `notify` / `delegate` 五种操作
- [ ] Agent 的 `create()` 初始化 `self.messenger`
- [ ] Agent 的 `start()` 消息循环处理 `AGENT_REQUEST` / `AGENT_NOTIFY` / `AGENT_DELEGATE`（无 `AGENT_REQUEST_RESPONSE` 分支——它由事件处理器消费）
- [ ] `AGENT_NOTIFY` 进入 `message_queue` 的 drain 类型集合，支持 mid-turn 注入；`AGENT_REQUEST_RESPONSE` **不**进入
- [ ] 收到 `AGENT_REQUEST` 后 `_handle_incoming_request` 自主处理 + **保证用 `reply()` 回复**（try/finally）
- [ ] 收到 `AGENT_DELEGATE` 校验 task_id 后执行任务 + **保证回执**（try/finally，用 `notify()` 发回），发送方不等回执（但等 ACK）
- [ ] `Communicate` tool 可用，实现在 `broca/tools/agent_interaction.py`（三模式 request/notify/delegate）
- [ ] **三种模式都同步等 ACK**：routing_failed 一律快速失败（tool 返回 `ToolStatus.ERROR`），notify/delegate 不等业务回执；不存在"投递失败却报告成功"
- [ ] SocketIO ACK 通路（Task 1.4 实现）经 Task 2.4 端到端验证；主/备选方案有明确结论
- [ ] `Agent.run()` 的 `_run_lock`（`asyncio.Lock`，不可重入）在"处理 request 过程中又触发嵌套 run"场景不会自死锁——由 request 强制环检测（CallChain）+ 超时兜底；已在 Task 3.2 增加对应测试（评审 Risk #7）
- [ ] 受影响的 5 个测试文件仍按 Task 3.3 时序更新（见 Phase 1 阶段 AC）；**本阶段不以"全量 pytest 通过"为硬门槛**，全量回归验收在 Phase 3（Task 3.3）。本阶段只要求 `pytest broca/tests/test_socketio*.py` + `test_agent.py`（Task 2.4 指定）与新增模块 import 检查通过

---

#### Task 2.1: DefaultAgentMessenger 实现

- **目标**：实现核心通信逻辑（ACL + delegate task 前置校验 + request 同步配对/超时）+ 可选增强（环检测/预算，按开关）+ 统一 SocketIO 传输
> 依赖: Task 1.1（ABC + message models）、Task 1.2（CallChain + CommunicationPolicy）、Task 1.3（Budget + Audit）、Task 1.4（Registry + `AgentFactory.get_agent()` 同步签名 + **`send() -> dict` ACK 契约**）
>
> **依赖已收敛**：ACK 能力已前移到 Task 1.4，本 Task 的 `_send_and_check_ack` 直接使用 `send()` 返回的 dict，不再依赖 Task 2.4（评审 Major #5）。`_resolve_agent_id` 按同步 `get_agent()` 调用，无 `await`（评审 Major #2 / Minor #4）。
- **步骤**：
  1. 创建 `broca/agent_messenger/messenger.py`：
     ```python
     @dataclass
     class _PendingRequest:
         event: asyncio.Event
         target_name: str
         started_at: float
         reply: str = ""
         status: str = "success"

     class DefaultAgentMessenger(AgentMessenger):
         def __init__(self):
             self.agent_id = ""
             self.name = ""
             self.session_id = ""
             self.communicator = None
             self._agent_factory = None
             self._task_manager = None
             self._config: CommunicationPolicy = CommunicationPolicy()
             self._budget = None
             self._call_chain = CallChain()
             self._audit = None
             self._pending_requests: dict[str, _PendingRequest] = {}   # ← request_id → pending
             self._lock = asyncio.Lock()                               # ← 保护 pending 表

         async def initialize(self, agent_id, name, session_id, communicator,
                              agent_factory, task_manager=None,
                              config: "AgentConfig | None" = None):
             # config 是 AgentConfig，不是 CommunicationPolicy（评审 Clarity #1 / Consistency #4）
             self._config = (config.communication_policy
                             if config is not None else CommunicationPolicy())
             self._audit = AuditLogger(config.workspace if config is not None else "")
             self._budget = CommunicationBudget(self._config)
             # ... 其余字段赋值（agent_id / name / session_id / communicator /
             #     _agent_factory / _task_manager）同原方案


         async def request(self, target_name, message, context=""):
             """同步请求（类 ask_user）：投递 → 阻塞等待 → 返回回复文本。"""
             target_id = self._resolve_agent_id(target_name)  # name → agent_id
             ok, reason = self._check_permissions(target_name, target_id, "request")
             if not ok:
                 raise AgentCommunicationError(reason)

             request_id = uuid.uuid4().hex[:16]
             event = asyncio.Event()
             started = time.monotonic()
             async with self._lock:
                 self._pending_requests[request_id] = _PendingRequest(
                     event=event, target_name=target_name, started_at=started
                 )

             comm = AgentCommunication(
                 source_agent=self.name, target_agent=target_name,
                 mode="request", content=message, context=context,
                 request_id=request_id, call_chain=self._call_chain.to_dict(),
             )
             final_result = "routing_failed"  # 局部结果变量：finally 据此写审计（评审 Clarity #3）
             try:
                 # 1. 投递（routing_failed ACK → 立即报错，ACK 实现见 Task 1.4，验证见 Task 2.4）
                 await self._send_and_check_ack(comm, target_id)
                 final_result = "routed"

                 # 2. 计入预算（可选增强：enable_budget=True 时 _check_permissions 已先 check
                 #    can_communicate；这里成功后 consume，与 notify/delegate 对称。
                 #    评审 AC Quality #1 / Consistency #1 —— request 必须 consume，否则预算 AC 不可达）
                 self._budget.consume("request")

                 # 3. 阻塞等待回复（类 ask_user 的 wait_for）
                 try:
                     await asyncio.wait_for(
                         event.wait(), timeout=self._config.request_timeout
                     )
                 except asyncio.TimeoutError:
                     final_result = "timeout"
                     raise AgentCommunicationError(
                         f"Request {request_id} to '{target_name}' timed out",
                         reason="request_timeout",
                     )

                 # 4. 读取回复文本 + 状态并返回（供 Communicate tool 映射 ToolResult）
                 async with self._lock:
                     pending = self._pending_requests[request_id]
                     reply, reply_status = pending.reply, pending.status
                 final_result = "replied"
                 return reply, reply_status
             finally:
                 async with self._lock:
                     self._pending_requests.pop(request_id, None)
                 self._audit.log(CommunicationEvent(
                     timestamp=now_iso(), source_agent=self.name,
                     target_agent=target_name, mode="request",
                     message_summary=message[:200], request_id=request_id,
                     result=final_result,  # routed/replied/timeout/routing_failed，不再用 event.is_set() 误判
                     call_depth=self._call_chain.depth,
                     duration_ms=(time.monotonic() - started) * 1000,
                 ))

         async def reply(self, request_id, target_name, content, status="success"):
             """回一条 request（收信方调用），发送专用 AGENT_REQUEST_RESPONSE。

             ACK 语义 = best-effort（评审 r3 Feasibility #4 / Consistency #2）：
             请求方可能已超时/abort 离线，send() 返回 routing_failed 时**不抛错**
             （否则会冒出收信方的处理路径），但记录一条 result=routing_failed 审计。
             这与 request/notify/delegate 的强失败语义（routing_failed 抛错）刻意不同。
             """
             comm = AgentCommunication(
                 source_agent=self.name, target_agent=target_name,
                 mode="request_reply", content=content,
                 request_id=request_id, status=status,
                 call_chain=self._call_chain.to_dict(),
             )
             target_id = self._resolve_agent_id(target_name)  # 请求方可能已离线 → 抛错由调用方处理
             # best-effort：不抛错，消费 send() 的 ACK dict 仅用于审计
             result = await self.communicator.send(
                 content=content, data=comm.to_dict(), receiver_id=target_id
             )
             ok = bool(result) and result.get("status") == "routed"
             self._audit.log(CommunicationEvent(
                 timestamp=now_iso(), source_agent=self.name,
                 target_agent=target_name, mode="request_reply",
                 message_summary=content[:200], request_id=request_id,
                 result="replied" if ok else "routing_failed",
                 call_depth=self._call_chain.depth, duration_ms=0.0,
             ))
             # reply 是协议义务：不再做 ACL/预算/环检测拦截（否则请求方会悬空到超时）

         async def handle_request_response(self, message):
             """由 'agent_request_response' 事件直接调用（类 handle_user_answer）。"""
             data = message.data or {}
             request_id = data.get("request_id")
             if not request_id:
                 return
             async with self._lock:
                 pending = self._pending_requests.get(request_id)
                 if pending is None:
                     return  # 超时/abort 后到达的滞留回复，忽略
                 pending.reply = message.content
                 pending.status = data.get("status", "success")
                 pending.event.set()

         async def notify(self, target_name, message, task_id=None, kind="notify"):
             """等 ACK、不等回执的通知（fire-and-forget 仅修饰回执）；
             delegate 回执也走这里（kind=delegate_receipt）。"""
             started = time.monotonic()
             target_id = self._resolve_agent_id(target_name)  # 解析一次后复用（评审 r3 Clarity #2）
             ok, reason = self._check_with_mode(target_name, target_id, "notify")
             if not ok:
                 raise AgentCommunicationError(reason)
             comm = AgentCommunication(
                 source_agent=self.name, target_agent=target_name,
                 mode="notify", content=message, task_id=task_id, kind=kind,
                 call_chain=self._call_chain.to_dict(),
             )
             # 同步等 ACK：routing_failed 抛错（调用方据此上报）；不等业务回执
             final_result = "routing_failed"
             try:
                 await self._send_and_check_ack(comm, target_id)
                 final_result = "routed"
                 self._budget.consume("notify")
             finally:
                 self._audit.log(CommunicationEvent(
                     timestamp=now_iso(), source_agent=self.name,
                     target_agent=target_name, mode="notify",
                     message_summary=message[:200], task_id=task_id, kind=kind,
                     result=final_result,  # routed / routing_failed
                     call_depth=self._call_chain.depth,
                     duration_ms=(time.monotonic() - started) * 1000,  # started 见方法开头
                 ))

         async def delegate(self, target_name, task_id, message):
             """等 ACK、不等回执的任务分配：task_id 必须存在；强制对方回执。
             ACK=routing_failed 必须抛错——否则委派方误以为任务已交出、静默悬空。"""
             started = time.monotonic()
             ok, reason = await self._check_task_exists(task_id)
             if not ok:
                 raise AgentCommunicationError(reason)
             target_id = self._resolve_agent_id(target_name)  # 解析一次后复用（评审 r3 Clarity #2）
             ok, reason = self._check_with_mode(target_name, target_id, "delegate")
             if not ok:
                 raise AgentCommunicationError(reason)
             comm = AgentCommunication(
                 source_agent=self.name, target_agent=target_name,
                 mode="delegate", content=message, task_id=task_id,
                 call_chain=self._call_chain.to_dict(),
             )
             # 同步等 ACK：routing_failed 抛错，task 没交出去必须让委派方知道；不等执行回执
             final_result = "routing_failed"
             try:
                 await self._send_and_check_ack(comm, target_id)
                 final_result = "routed"
                 self._budget.consume("delegate")
             finally:
                 self._audit.log(CommunicationEvent(
                     timestamp=now_iso(), source_agent=self.name,
                     target_agent=target_name, mode="delegate",
                     message_summary=message[:200], task_id=task_id,
                     result=final_result,  # routed / routing_failed
                     call_depth=self._call_chain.depth,
                     duration_ms=(time.monotonic() - started) * 1000,  # started 见方法开头
                 ))

         # ---- 校验辅助 ----
         async def _check_task_exists(self, task_id):
             if not task_id: return False, "task_id_required"
             if await self._task_manager.get_task(task_id) is None:
                 return False, "task_not_found"
             return True, None

         async def _check_with_mode(self, target_name, target_id, mode):
             """notify/delegate 用：ACL + 预算(可选) + 环检测(可选)。
             target_id 由调用方解析后传入，避免二次解析（评审 r3 Clarity #2）。"""
             return self._check_permissions(target_name, target_id, mode)

         def _check_permissions(self, target_name, target_id, mode):
             # 核心：ACL
             if self._config.allowed_targets is not None and target_name not in self._config.allowed_targets:
                 return False, "acl_denied"
             if self._config.allowed_modes is not None and mode not in self._config.allowed_modes:
                 return False, "acl_denied"
             # 核心：request 环检测（防阻塞死锁，始终启用；用 target_id 比对链中 agent_id）
             if mode == "request":
                 if self._call_chain.would_create_cycle(target_id):
                     return False, "chain_cycle"
                 if not self._call_chain.is_within_depth(self._config.max_chain_depth):
                     return False, "chain_depth_exceeded"
             # 可选：预算（全部模式）
             if self._config.enable_budget and not self._budget.can_communicate(mode):
                 return False, "budget_exhausted"
             # 可选：环检测（notify/delegate，防刷屏；request 已在上面强制检测，这里 mode != "request" 排除）
             if self._config.enable_chain_detection and mode != "request":
                 if self._call_chain.would_create_cycle(target_id):
                     return False, "chain_cycle"
                 if not self._call_chain.is_within_depth(self._config.max_chain_depth):
                     return False, "chain_depth_exceeded"
             return True, None

         async def _send_and_check_ack(self, comm, target_id):
             # send() 返回 server 的 ACK dict（Task 1.4 统一契约），不是 message_id str
             result = await self.communicator.send(
                 content=comm.content, data=comm.to_dict(), receiver_id=target_id
             )
             if result and result.get("status") == "routing_failed":
                 raise AgentCommunicationError(
                     f"Agent unreachable: {result.get('reason')}", reason="routing_failed"
                 )

         def _resolve_agent_id(self, target_name):
             """同步方法：DefaultAgentFactory.get_agent 是同步 def，无 await。
             仅解析同进程、同 session 内的 agent（见概述范围边界）。"""
             target = self._agent_factory.get_agent(self.session_id, target_name)
             if target is None:
                 raise AgentCommunicationError(
                     f"Agent '{target_name}' not found in session",
                     reason="target_not_found",  # 评审 Completeness #2 / Minor #3
                 )
             return target.agent_id

         # ---- 生命周期/状态钩子（ABC 要求的另外两个抽象方法，评审 r3 Completeness #1）----
         def set_call_chain(self, chain: "CallChain") -> None:
             """由 Agent.run() 入口无条件设置当前调用链（含发起方自身 agent_id）。"""
             self._call_chain = chain

         def reset_budget(self) -> None:
             """由 Agent.run() 入口重置 per-turn 通信预算。"""
             self._budget.reset()
      ```
   2. 定义 `AgentCommunicationError(Exception)`：
      ```python
      class AgentCommunicationError(Exception):
          def __init__(self, message: str, reason: str | None = None):
              super().__init__(message)
              self.reason = reason  # "task_id_required" | "task_not_found" | "target_not_found"
                                    # | "acl_denied" | "budget_exhausted" | "chain_cycle"
                                    # | "chain_depth_exceeded" | "request_timeout" | "routing_failed"
      ```
- **预期产出**：`broca/agent_messenger/messenger.py`
- **验收标准**：
  - [ ] `communicator.send()` 及其返回值按 **dict（ACK 结果）** 契约使用：`_send_and_check_ack` 对返回的 dict 调 `.get("status")`；**不存在**对 `send_message()` 的 `str` 返回值调 `.get()` 的代码（评审 Critical / AC Finding #1）
  - [ ] `_resolve_agent_id` 为同步 `def`，调用 `get_agent()` 无 `await`（评审 Major #2）
  - [ ] `request()` 持有 pending + 调用 `communicator.send()` 后**阻塞在 `asyncio.wait_for(event.wait(), timeout=request_timeout)`**，回复到达后返回 `(回复文本, 回复状态)` 元组（`status ∈ success/error/aborted`）
  - [ ] `request()` 投递成功后调用 `self._budget.consume("request")`（与 notify/delegate 对称），使 `enable_budget=True` 时第 4 次 request 可被拒（评审 AC Quality #1 / Consistency #1）
  - [ ] 有 `_pending_requests` + `asyncio.Lock`；`handle_request_response()` 按 `request_id` 填 reply/status 并 `event.set()`；`finally` 清理 pending；审计 `result` 取局部 `final_result`（`routed`/`replied`/`timeout`/`routing_failed`），routing_failed 不再误记为 timeout（评审 Clarity #3）
  - [ ] 超时抛 `AgentCommunicationError(reason="request_timeout")`
  - [ ] `reply()` 发送 `mode="request_reply"` → `AGENT_REQUEST_RESPONSE`，带 `request_id`，不做 ACL/预算拦截
  - [ ] `notify()` **同步等 ACK**（走 `_send_and_check_ack`），routed 后立即返回**不等回执**；ACK 为 `routing_failed` 抛 `AgentCommunicationError(reason="routing_failed")`；审计 result 记为 routed/routing_failed；`kind="delegate_receipt"` 用于 delegate 回执
  - [ ] `delegate()` 先做 task 前置校验，再走 ACL + 可选增强，**同步等 ACK**：routed 后立即返回、不等对方执行回执（fire-and-forget 仅修饰回执）；**ACK=routing_failed 必须抛错**（task 没交出去必须让委派方知道，不能静默 SUCCESS）
  - [ ] `request` 的默认环检测（防死锁）始终生效，与 `enable_chain_detection` 开关无关；notify/delegate 的环检测仅开关打开时生效；`_check_permissions` / `_check_with_mode` 无 `force_chain_check` 死参数（评审 Clarity #2）
  - [ ] 拒绝路径抛 `AgentCommunicationError`，`reason` 属性值：`'task_id_required'` / `'task_not_found'` / `'target_not_found'` / `'acl_denied'` / `'budget_exhausted'` / `'chain_cycle'` / `'chain_depth_exceeded'` / `'request_timeout'` / `'routing_failed'`
  - [ ] `initialize()` 签名的 `config` 标注为 `"AgentConfig | None"`；内部显式 `self._config = config.communication_policy` + `AuditLogger(config.workspace)`，不把 AgentConfig 直接当 policy 用（评审 Clarity #1 / Consistency #4）
  - [ ] `_resolve_agent_id` 对本地 factory 查不到的 target 抛 `reason="target_not_found"`（跨进程 target 同样走此路径，见概述范围边界）
  - [ ] `DefaultAgentMessenger` 实现 **全部 8 个抽象方法**（`initialize` / `request` / `notify` / `delegate` / `reply` / `handle_request_response` / `set_call_chain` / `reset_budget`），`set_call_chain` 直接赋值 `self._call_chain = chain`、`reset_budget` 调用 `self._budget.reset()`；可经 `ComponentRegistry` 实例化（无 `TypeError: Can't instantiate abstract class`）（评审 r3 Completeness #1）
  - [ ] `notify()` / `delegate()` 只调用一次 `_resolve_agent_id(target_name)`，把已解析的 `target_id` 传给 `_check_with_mode(target_name, target_id, mode)`，`_check_with_mode` 内部**不再二次解析**（评审 r3 Clarity #2）
  - [ ] `reply()` 为 best-effort：`send()` 返回 `routing_failed` 时**不抛错**，但写一条 `mode="request_reply"`、`result=routing_failed` 的审计；与 request/notify/delegate 的强失败语义区分（评审 r3 Feasibility #4 / Consistency #2）
  - [ ] **`request()` 首跳环检测前提**：`self._call_chain` 在 `Agent.run()` 入口已无条件含发起方自身 `agent_id`（见 Task 2.2 Step 6）；当 `self._call_chain.would_create_cycle(target_id)` 命中（含 A↔B 互 request 的首跳）时 `_check_permissions` 返回 `chain_cycle` 并拒绝投递（评审 r3 Major）

---

#### Task 2.2: Agent 集成

- **目标**：将 `AgentMessenger` 注入 Agent + 消息循环处理 + request 回复保障（专用响应直接唤醒 Event）+ delegate 回执保障
> 依赖: Task 2.1（DefaultAgentMessenger 实现）
- **步骤**：
  1. `Agent.__init__` 新增：`self.messenger: AgentMessenger | None = None`
  2. `Agent.create()` 中初始化（Tool layer 之后）：
     ```python
     agent.messenger = registry.get(AgentMessenger, scope_key=key)
     agent_factory = registry.get(AgentFactory)
     await agent.messenger.initialize(
         agent_id=key, name=config.name,
         session_id=session_manager.session_id,
         communicator=agent.communicator,
         agent_factory=agent_factory,
         task_manager=TaskManager(),
         config=config,
     )
     ```
  3. `Agent.create()` 注册事件处理器（**request 回复走专用 handler，绕过 message_queue**）：
     ```python
     agent.communicator.register_event_handler("agent_request", agent._receive_message)
     agent.communicator.register_event_handler(
         "agent_request_response", agent.messenger.handle_request_response
     )  # ← 类 ask_user 的 user_answer handler：直接 set Event，不进 message_queue
     agent.communicator.register_event_handler("agent_notify", agent._receive_message)
     agent.communicator.register_event_handler("agent_delegate", agent._receive_message)
     ```
  4. `Agent` 新增消息处理方法：
     ```python
     async def _handle_incoming_request(self, comm: AgentCommunication):
         """处理收到的 request：agent 自主处理，并保证用 reply() 回一条（类 _handle_task 的 try/finally）。"""
         call_chain = CallChain.from_dict(comm.call_chain)
         reply_text, status = "", "success"
         try:
             msg = MessageProtocol.create_user_message(
                 content=f"[Request from {comm.source_agent}]: {comm.content}"
             )
             if comm.context:
                 msg.data["context"] = comm.context
             result = await self.run(msg, from_agent=True, call_chain=call_chain)
             if result.status == ExecutionStatus.ABORTED:
                 reply_text, status = "aborted by user", "aborted"
             elif result.status in (ExecutionStatus.ERROR, ExecutionStatus.DEAD_LOOP):
                 reply_text, status = f"failed: {result.message or result.error}", "error"
             else:
                 reply_text = self.context.get_latest_assistant_message() or result.message or ""
         except Exception as e:
             reply_text, status = f"failed: {e}", "error"
         finally:
             try:
                 await self.messenger.reply(comm.request_id, comm.source_agent,
                                            reply_text, status)
             except Exception as e:
                 logger.error(f"Failed to send request reply {comm.request_id}: {e}")

     async def _handle_incoming_delegate(self, comm: AgentCommunication):
         """处理收到的 delegate（任务分配）。强制回执，try/finally 单次回执。
         与 request 的区别：回执用 notify() 发 AGENT_NOTIFY（kind=delegate_receipt），发送方不等回执（但等 ACK）。
         评审 r3 Consistency #3：统一为 try/finally，任意路径（正常/not-found/异常）都只回执一次，
         避免 try 内 notify 抛错又落进 except 二次回执。
         """
         call_chain = CallChain.from_dict(comm.call_chain)
         task_id = comm.task_id
         receipt = "done"
         try:
             task = await self.messenger._task_manager.get_task(task_id)
             if task is None:
                 receipt = "Task not found"
                 return  # finally 仍会回执一次
             msg = MessageProtocol.create_user_message(
                 content=f"[Delegate task {task_id} from {comm.source_agent}]: {comm.content}"
             )
             msg.data["task_id"] = task_id
             result = await self.run(msg, from_agent=True, call_chain=call_chain)
             receipt = ("aborted by user" if result.status == ExecutionStatus.ABORTED
                        else (result.message or "done"))
         except Exception as e:
             receipt = f"Failed: {e}"
         finally:
             # 单次回执（best-effort）：notify 等 ACK，委派方离线时 routing_failed 只记日志，不再嵌套 notify
             try:
                 await self.messenger.notify(
                     comm.source_agent, f"[Delegate {task_id}] {receipt}",
                     task_id=task_id, kind="delegate_receipt",
                 )
             except AgentCommunicationError as notify_err:
                 logger.warning(f"Delegate receipt undeliverable for {task_id}: {notify_err}")
      ```

     **notify / delegate 回执的 mid-turn 处理**：两者都是 `AGENT_NOTIFY`，无 `_handle_incoming_notify`。消息由 `_receive_message` 放入 `message_queue`，复用框架现有链路（见 Step 7）：忙时由 engine 的 `_message_source.drain()` 在 step 间注入当前 turn；空闲时由 `start()` 循环作为新 turn 处理。request 回复**不走这里**——它由 `messenger.handle_request_response` 直接消费。
  5. `Agent.start()` 消息循环新增分支（替代已删除的 TASK 分支）：
     ```python
     elif message.message_type == MessageType.AGENT_REQUEST:
         await self._handle_incoming_request(
             AgentCommunication.from_message_data(message.data)
         )
     elif message.message_type == MessageType.AGENT_DELEGATE:
         await self._handle_incoming_delegate(
             AgentCommunication.from_message_data(message.data)
         )
     elif message.message_type == MessageType.AGENT_NOTIFY:
         # 空闲时收到的 notify / delegate 回执（忙时已被 engine mid-turn drain 消费）
         await self.run(message, from_agent=True)
     ```
     > `AGENT_NOTIFY` 若在本端忙时到达，已被 `_message_source.drain()` 在 step 间取走并注入当前 turn；只有空闲时（或 terminal step 后按 TC-10 规则留在队列）才会走到 start() 这里作为新 turn 处理。**无 `AGENT_REQUEST_RESPONSE` 分支**——它由 `handle_request_response` 事件处理器直接消费，不进 `message_queue`。
  6. `Agent.run()` 新增 `call_chain` 参数 + budget 重置：
     ```python
     async def run(self, message, max_steps=None, from_agent=False,
                   allowed_tools=None, namespace=None, message_source=None,
                   call_chain: CallChain | None = None) -> ExecutionResult:
         async with self._run_lock:
             if self.messenger:
                 self.messenger.reset_budget()
                 # 无条件把自身 agent_id 入链：顶层 turn（call_chain=None）时也要让
                 # 发起方自身 id 进入 CallChain，否则 A→B→A 的首跳环检测失效，
                 # 核心防死锁退化为 300s 超时兜底（评审 r3 Feasibility #1 / Consistency #1）。
                 self.messenger.set_call_chain(
                     (call_chain or CallChain()).add(self.agent_id)
                 )
             ...
     ```
     > **关键（评审 r3 Major）**：`call_chain` 为 `None`（顶层用户 turn 触发）时，绝不能用 `if call_chain:` 守卫跳过入链——那样发起方自身 id 从不入链，A 顶层发起 `request(B)` 时携带的 `call_chain` 为空，B 回发 `request(A)` 时 `would_create_cycle(A)` 判 `False`，A↔B 互 request 死锁无法在投递前拦截。改为 `(call_chain or CallChain()).add(self.agent_id)` 无条件入链后，A 发出的首跳 `call_chain` 已含 A，B 再 request A 时命中 `chain_cycle` 被拒。
     > `context.py` 无改动：notify 注入复用 engine 的 `message_source` 链路；request 回复根本不进 context（由 Event 唤醒工具）。
  7. **复用现有 mid-turn 机制**（`broca/agent.py` + `broca/loop_engine/engine.py`，共 **5 处**，与 Task 1.1 Step 6/7 的"删旧"集中对应）：
     - `agent.py` 2 处：
       1. `Agent._drain_user_messages` 的 `_drain_types` 集合
       2. `Agent._make_message_source._Drainer` 的 `_drain_types` 集合
     - `engine.py` **3 处 `_cross_agent_types`**（评审 Finding 1.1 / 5.2 —— 这是原计划遗漏点）：
       3. `_persist_user_message()` 约 L394
       4. `_inject_user_message()` 第 1 处约 L453
       5. `_inject_user_message()` 第 2 处约 L459
     全部把旧的 `(TASK_COMPLETE, TASK_ERROR)` 替换为 `(AGENT_NOTIFY,)`：
     ```python
     # agent.py — 两处 _drain_types
     _drain_types = {
         MessageType.USER_MESSAGE,
         MessageType.AGENT_NOTIFY,   # ← 新增（mid-turn 注入 + 空闲 turn）
     }
     # engine.py — 三处 _cross_agent_types（L394 / L453 / L459 全部）
     _cross_agent_types = (MessageType.AGENT_NOTIFY,)  # ← 新增，替换 TASK_*
     ```
     > 这 5 处是同一组"跨 agent 来源识别"逻辑：Task 1.1 负责删除 TASK_* 引用（避免枚举删除后 `AttributeError`），本步负责加入 `AGENT_NOTIFY`。两阶段集中列出，避免遗漏。`AGENT_REQUEST_RESPONSE` **不加入**这些集合。注入内容格式：普通通知 `[Notify from X]: ...`、delegate 回执 `[Delegate T1] ...`；业务层靠 `kind` + `task_id` 区分。
- **预期产出**：`agent.py` 新增 ~95 行、修改 2 处 drain 集合 + `engine.py` 修改 3 处 `_cross_agent_types`（共 5 处）；**`context.py` 无改动**
- **验收标准**：
  - [ ] `Agent.create()` 后 `agent.messenger` 是 `AgentMessenger` 实例，`agent_factory` 已注入
  - [ ] 注册了 `agent_request_response` → `messenger.handle_request_response`（非 `_receive_message`）；无 `_on_agent_reply` 方法
  - [ ] 收到 `AGENT_REQUEST` 后调用 `_handle_incoming_request`，其 try/finally 保证用 `messenger.reply()` 回复（正常/abort/异常三路径），`request_id` 正确透传
  - [ ] `AGENT_REQUEST_RESPONSE` 不进 `message_queue`、不在 drain/inject 类型集合中
  - [ ] 收到 `AGENT_DELEGATE` 后调用 `_handle_incoming_delegate`，task_id 缺失/不存在时用 `notify(kind="delegate_receipt")` 回执；try/finally 保证三路径都回执
  - [ ] `AGENT_NOTIFY` 已进入全部 5 处跨 agent 识别逻辑：`agent.py` 的 `_drain_user_messages` / `_make_message_source._Drainer` 两处 `_drain_types`，以及 `engine.py` 的 `_persist_user_message` + `_inject_user_message` 共 3 处 `_cross_agent_types`；这 3 处不再残留 `TASK_COMPLETE` / `TASK_ERROR`
  - [ ] 收到 `AGENT_NOTIFY` 后：忙时 step 间 mid-turn 注入当前 turn、空闲时经 start() 作为新 turn
  - [ ] `context.py` 无改动；`agent.run()` 调用后 budget 重置、call_chain 更新
  - [ ] **`run()` 无条件把自身 `agent_id` 入链**：`run()` 中无 `if call_chain:` 守卫，写作 `self.messenger.set_call_chain((call_chain or CallChain()).add(self.agent_id))`；断言顶层 turn（`call_chain=None`）执行后 `messenger._call_chain.agent_ids` 含发起方自身 `agent_id`（评审 r3 Major / Feasibility #1）
  - [ ] 现有 `test_agent.py` 全量通过

---

#### Task 2.3: Communicate tool

- **目标**：实现统一的 `communicate` tool（替代已删除的 `assign_task`），**就地实现在 `broca/tools/agent_interaction.py`，不新建文件**
> 依赖: Task 2.1（messenger 接口）、Task 2.2（agent.messenger 已注入）
- **步骤**：
  1. 在 **`broca/tools/agent_interaction.py`** 中（删除 `AssignTask` 后原有的位置）新增 `Communicate(Tool)` 类：
     ```python
     class Communicate(Tool):
         is_readonly = False

         @property
         def name(self):
             return "communicate"

         @property
         def description(self):
             return (
                 "Send a message to another agent. "
                 "mode='request': ask target to do something and BLOCK until it replies "
                 "(like ask_user); the target's reply is returned as this tool's result, "
                 "so you can continue immediately with the answer. "
                  "mode='notify': inform target, no reply, returns immediately once delivered. "
                  "mode='delegate': assign a pre-existing task (task_id required) to target; "
                  "target sends a receipt but this call returns immediately once delivered — "
                  "monitor via task_management. All modes confirm delivery first: if the target "
                  "is unreachable the call returns an ERROR (message was NOT sent) — retry or "
                  "pick another target."
              )

         @property
         def parameters(self):
             return {
                 "type": "object",
                 "properties": {
                     "target": {"type": "string", "description": "name of the target agent"},
                     "mode": {
                         "type": "string", "enum": ["request", "notify", "delegate"],
                         "description": (
                             "'request': target must reply; this call BLOCKS until the reply "
                             "arrives and returns it (use when you need the result to continue). "
                              "'notify': no reply, returns immediately once delivered. "
                              "'delegate': task assignment, task_id must reference an existing "
                              "task; target sends a receipt but this call does not wait for it. "
                              "All modes confirm delivery first; unreachable target => ERROR."
                          ),
                     },
                     "message": {"type": "string", "description": "the message/task/question content"},
                     "context": {"type": "string", "description": "optional additional context for the target"},
                     "task_id": {
                         "type": "string",
                         "description": "REQUIRED when mode='delegate'; must be a pre-created task. Ignored otherwise.",
                     },
                 },
                 "required": ["target", "mode", "message"],
             }

         async def _execute(self, arguments, context: ToolCallContext) -> ToolResult:
             agent = context.agent
             messenger = agent.messenger
             if messenger is None:
                 return ToolResult(status=ToolStatus.ERROR, content="AgentMessenger not initialized")

             target = arguments["target"]
             mode = arguments["mode"]
             message = arguments["message"]
             ctx = arguments.get("context", "")
             task_id = arguments.get("task_id")

             try:
                 if mode == "request":
                     # 阻塞等待回复；拿到 (文本, 状态) 后按 reply.status 映射 ToolResult，
                     # 避免 error/aborted 的回复被当作 SUCCESS 误导 LLM（评审 AC Quality #2）
                     reply, reply_status = await messenger.request(target, message, ctx)
                     # 审计/语义：reply_status ∈ success / error / aborted
                     tool_status = (ToolStatus.SUCCESS if reply_status == "success"
                                    else ToolStatus.ERROR)
                     status_tag = "" if reply_status == "success" else f" [status={reply_status}]"
                     return ToolResult(
                         status=tool_status,
                         content=f"[Reply from '{target}'{status_tag}]: {reply}",
                     )
                 elif mode == "notify":
                     # notify 内部等 ACK；routing_failed 会抛错落到下方 except → ERROR
                     await messenger.notify(target, message)
                     return ToolResult(status=ToolStatus.SUCCESS,
                                       content=f"Notification delivered to '{target}'.")
                 elif mode == "delegate":
                     # delegate 内部等 ACK；routing_failed 会抛错 → ERROR，
                     # 不会误报 "delegated"，避免委派方以为任务已交出而静默悬空
                     await messenger.delegate(target, task_id, message)
                     return ToolResult(status=ToolStatus.SUCCESS,
                                       content=(
                                           f"Task '{task_id}' delegated to '{target}' (delivery confirmed). "
                                           f"Target will send a receipt asynchronously; monitor via "
                                           f"task_management (action='get', task_id='{task_id}')."
                                       ))
                 else:
                     return ToolResult(status=ToolStatus.ERROR, content=f"Unknown mode: {mode}")
             except AgentCommunicationError as e:
                 return ToolResult(status=ToolStatus.ERROR,
                                   content=str(e) + (f" (reason: {e.reason})" if e.reason else ""))
     ```
  2. 确认 `broca/tools/communicate.py` **不存在**（未新建）；`AutoDiscoverToolManager` 仍扫描 `broca/tools/` 下的 `Tool` 子类，`Communicate` 会被自动发现
  3. 更新内置 agent 配置中的 tools 列表：`"assign_task"` → `"communicate"`
- **预期产出**：**仅修改** `broca/tools/agent_interaction.py` + 配置更新（无新增文件）
- **验收标准**：
  - [ ] `broca/tools/communicate.py` 不存在
  - [ ] `Communicate` 定义在 `broca/tools/agent_interaction.py`，且 `communicate` tool 出现在 Agent 的 `tool_mapping` 中
  - [ ] `communicate(target="x", mode="request", message="...")` 调用并 **await** `messenger.request()`，把返回的 `(回复文本, 回复状态)` 映射到 `ToolResult`：`status=="success"` → `ToolStatus.SUCCESS`，`error`/`aborted` → `ToolStatus.ERROR` 且 content 标注 `[status=...]`（LLM 不误判），LLM 可继续（评审 AC Quality #2）
  - [ ] `communicate(target="x", mode="notify", message="...")` 调用 `messenger.notify()`，投递成功（ACK=routed）才返回 SUCCESS；不等回执
  - [ ] `communicate(target="x", mode="delegate", task_id="T1", message="...")` 调用 `messenger.delegate()`，投递成功（ACK=routed）才返回 SUCCESS、立即返回**不等回执**
  - [ ] `communicate(mode="delegate")` 缺少 `task_id`、task 不存在、ACK=`routing_failed`（目标不可达）、以及 request 超时时，`AgentCommunicationError` 被捕获返回 `ToolResult(status=ERROR)`——**不存在"投递失败却 SUCCESS"**（避免任务静默悬空）
  - [ ] 配置文件中无 `assign_task` 引用

---

#### Task 2.4: SocketIO ACK 端到端验证 + 备选方案

- **目标**：验证 Task 1.4 已实现的 `send() -> dict` ACK 通路（client emit callback + server handler 返回值）；若 Phase 0 判定 emit callback 不可用，则切换到备选方案
> 依赖: Phase 0（emit callback 支持结论；**决策截止 Phase 1 结束前**）、Task 1.4（`send()` / `_send_message_with_ack` / server `_process_message` 已实现）、Task 2.1（`_send_and_check_ack` 消费 ACK）
>
> **实现已在 Task 1.4 完成**（评审 Major #5：消除 2.1↔2.4 依赖倒置）。本 Task 只做端到端验证 + 主/备选方案决断，不再新增生产代码（备选方案除外）。
- **步骤**：
  1. **主方案验证**（Phase 0 确认 server handler 返回值可作为 ACK data）：
     - 验证 `SocketIOClient._send_message_with_ack` 用 `sio.emit("message", data, callback=ack_fn)` + 独立 Future 拿 ACK；`send_message()` 原有的 `callback`（`message_callbacks` 响应回调）**不受影响、不混用**（评审 Clarity #2）
     - 验证 server `message` handler 使用 `await self._process_message(sid, message)`（`_process_message` 是 async，参数是 `Message` 对象不是原始 `data` dict）并 `return result`；`_process_message` 显式返回 dict（评审 Clarity #1 / Consistency #4）
     - 验证既有 `_send_error(..., code="ROUTING_FAILED")` 仍保留（UI 可见错误），与 ACK 返回值并存、不重复触发（评审 Clarity #3）
  2. **ACK 消费验证**（见 Task 2.1）：
      - `request` 投递后 ACK 为 `routing_failed` → 立即抛 `AgentCommunicationError(reason="routing_failed")`（不进入超时等待）
      - `notify` / `delegate` ACK 为 `routing_failed` → **同样抛 `AgentCommunicationError(reason="routing_failed")`**（三种模式都同步等 ACK），审计记录 result=routing_failed；`Communicate` tool 据此返回 `ToolStatus.ERROR`，调用方知道消息没投递出去
  3. **备选方案（仅当 Phase 0 判定 emit callback 不可用时执行）**：
     - server 在 `_process_message` 路由结束后额外 `emit("agent_send_ack", {"request_id": ..., "status": ..., "reason": ...}, room=sid)`；`request_id` 从 `message.data["request_id"]` 取
     - `SocketIOClient` 注册 `agent_send_ack` 事件 → 按 request_id 路由到对应 Future（新增 `self._ack_waiters: dict[str, Future]`）；`_send_message_with_ack` 改为等待该 Future
     - 对应新增 AC：见下方"备选方案 AC"；若走备选方案，Task 1.4 的 `send() -> dict` 契约不变，仅底层 `_send_message_with_ack` 实现切换
- **预期产出**：主方案为验证性改动（测试 + 可能的微调）；备选方案为 `socketio_client.py` + `socketio_server.py` + `components/communicator.py` 的 ACK 通路替换
- **验收标准**：
  - [ ] 主方案：路由成功时 `send()` 返回 `{"status": "routed"}`；路由失败时返回 `{"status": "routing_failed", ...}`（client 经 emit callback 拿到 server handler 返回值）
  - [ ] 主方案：确认 `sio.emit(callback=fn)` 与 `send_message(callback=...)`（message_callbacks）是两套机制，互不干扰；`send_user_message` / `send_agent_response` 等现有 send 方法行为不变
  - [ ] 主方案：server `message` handler 返回 `await self._process_message(sid, message)` 的结果，`_process_message` 为 `async def ... -> dict`
  - [ ] 路由失败（目标不在线）：**三种模式**都立即报 `routing_failed`——`request()` 不进入超时等待，`notify()` / `delegate()` 也抛错（经 `Communicate` 返回 tool ERROR），并写审计日志；不存在"投递失败却 SUCCESS"
  - [ ] `pytest broca/tests/test_socketio*.py` 与 `pytest broca/tests/test_agent.py` 全量通过（替换原"等仍正常工作"的泛化表述，评审 AC Quality #2）
  - [ ] **备选方案 AC**（仅当走备选时启用）：server emit `agent_send_ack`，client 按 request_id 匹配 Future；`send()` 仍返回同样的 dict 契约；AC 全数复用上述主方案断言
  - [ ] **Phase 0 决策已落到"未解决的问题"第 1 项**：记录主/备选的采用结论与截止点

---

### Phase 3: 测试 + 收尾

**目标**：完整测试覆盖 + 全量回归

**阶段验收标准**：
- [ ] 控制原语单元测试全部通过（Budget 作为可选原语仍单测其自身逻辑）
- [ ] AgentMessenger 集成测试覆盖 request/notify/delegate 全流程
- [ ] 核心机制拒绝路径均有测试（ACL、task 存在性校验、request 环检测、request 超时）
- [ ] 每个可选增强在**开关打开时**的拒绝路径有测试、在**默认关闭时**不拦截（环检测/预算）
- [ ] 回复保障测试（异常/abort/正常 三种路径都用 `reply()` 回 `AGENT_REQUEST_RESPONSE`；delegate 用 `notify(kind="delegate_receipt")`）
- [ ] **request 回复走同步唤醒**：`AGENT_REQUEST_RESPONSE` 经 `handle_request_response` 按 `request_id` 唤醒 Event，工具返回回复后 LLM 继续（不进 message_queue、不 mid-turn 注入、无专用 mid-turn 链路）
- [ ] **滞留回复（late reply）被静默忽略**：超时/abort 后到达的 `AGENT_REQUEST_RESPONSE` 不串扰、pending 表无残留（评审 AC Quality #3）
- [ ] delegate 测试：task 必填 + 存在性、强制回执、发送方不等回执（但等 ACK）
- [ ] **投递失败快速失败测试**：三种模式在 ACK=`routing_failed`（目标不在线）时都抛 `AgentCommunicationError(reason="routing_failed")`，`Communicate` tool 返回 `ToolStatus.ERROR`；尤其 delegate 不存在"投递失败却 SUCCESS 导致任务悬空"
- [ ] `pytest broca/tests/` 全量通过
- [ ] Agent 配置文档更新（含 delegate 模式说明）

---

#### Task 3.1: 控制原语单元测试

- **目标**：为控制原语编写单元测试
> 依赖: Phase 1 全部完成
- **步骤**：
  1. `broca/tests/test_agent_messenger_call_chain.py`：
     - 空链 `would_create_cycle` → False
     - 单节点链 `would_create_cycle(self)` → True
     - 多节点链 `would_create_cycle(last_node)` → True
     - `is_within_depth` 边界（depth == max）
     - `add()` 返回新实例（不可变语义）
     - `to_dict()` / `from_dict()` 往返一致性
  2. `broca/tests/test_agent_messenger_budget.py`：
     - 正常消耗：`consume("request")` 前 3 次 True，第 4 次 False
     - `reset()` 后重新可消费
     - `remaining("request")` 递减
     - `consume("delegate")` 前 3 次 True，第 4 次 False（max_delegates_per_turn）
     - 不同 mode 独立计数（request 耗尽不影响 notify / delegate）
  3. `broca/tests/test_agent_messenger_audit.py`：
     - `log(event)` 生成 JSONL 文件
     - 多事件追加（非覆盖）
     - 截断：`message_summary` 超过 200 字符被截断
     - 使用 `tmp_path` 作为 workspace
- **验收标准**：
  - [ ] 3 个测试文件全部通过（`call_chain` / `budget` / `audit`；无 `circuit_breaker` 测试）
  - [ ] 使用 `tmp_path` 隔离

---

#### Task 3.2: AgentMessenger 集成测试

- **目标**：测试 request/notify/delegate 完整流程 + 核心控制 + 可选增强(开关打开/关闭两态) + 回复保障
> 依赖: Task 2.1-2.4 全部完成
- **步骤**：
  1. `broca/tests/test_agent_messenger_core.py`：
     - **【默认配置：两个可选开关全关；核心机制（ACL / task 校验 / request 超时+环检测）生效】**
     - **request 正常流程（同步阻塞）**：A 起 task 调 `messenger.request()` → 阻塞；B 收到 AGENT_REQUEST → run() → `reply(request_id, ...)` → A 的 `handle_request_response` 按 request_id set Event → `request()` 返回 `(回复文本, 回复状态)` → `Communicate` tool 把它映射为 ToolResult 返回（LLM 同 turn 继续）。断言 `request()` 在回复到达前不返回
     - **request_id 配对**：两个并发 request（不同 request_id），回复按各自 request_id route 到正确 pending，不串扰
     - **request 走专用事件、不进队列**：断言 `AGENT_REQUEST_RESPONSE` 由 `handle_request_response` 直接消费；不在 `_drain_types` / `_cross_agent_types`；未调用 `_receive_message` 注入 context
     - **request 超时**：B 不回复 → `request()` 在 `request_timeout`（测试内设为 0.05s）后抛 `AgentCommunicationError(reason="request_timeout")`；pending 被清理
     - **滞留回复被忽略（late reply）**：request 超时后，再投递同 request_id 的 `AGENT_REQUEST_RESPONSE` → `handle_request_response` 查不到 pending 直接忽略，不影响其它并发 request，pending 表无残留（评审 AC Quality #3）
     - **嵌套 run 不自死锁**：A 处理 B 的 request 时（run() 持 `_run_lock`）B 又向 A 发 request → request 强制环检测（CallChain 命中）在投递前拒绝，不会因 `_run_lock` 不可重入而卡死（评审 Risk #7）；断言拒绝 reason=`chain_cycle`
     - **顶层发起方自身入链（首跳环检测生效）**：A 顶层 turn（`call_chain=None`）调 `run()` 后 `messenger._call_chain.agent_ids` 含 A；A 发起 `request(B)` 时随消息发送的 `call_chain` 已含 A；B 收到后回发 `request(A)` 时 `would_create_cycle(A)` 为 True、以 `chain_cycle` 被拒——**不会退化为 300s 超时兜底**（评审 r3 Major / Feasibility #1 / Consistency #1）
     - **A↔B 互 request 首跳即被拒**：构造 A 顶层发起 request(B)、B 在 run 中 request(A) 的场景，断言 B 的 request 在投递前抛 `AgentCommunicationError(reason="chain_cycle")`，而非靠超时结束（评审 r3 Major）
     - **request ACL 拒绝（必选核心）**：`allowed_targets=["A"]`，request("C") 被拒（`acl_denied`），不投递
     - **request 环检测（必选核心）**：call_chain 含 B 时 request(B) 被拒（`chain_cycle`），与 `enable_chain_detection` 开关无关
     - **回复保障**：B 的 run() 抛异常 → B 仍用 `reply(status="error")` 回一条 AGENT_REQUEST_RESPONSE；B 被 abort → 回 `status="aborted"`。三种路径 A 都能收到回复并结束等待
     - **routing_failed（request）**：目标不在线 → `request()` 收到 `routing_failed` ACK 立即报错，不进入超时等待
     - **routing_failed（notify/delegate）**：目标不在线 → `notify()` / `delegate()` 同样收到 `routing_failed` ACK 立即抛 `AgentCommunicationError(reason="routing_failed")`；经 `Communicate` tool 返回 `ToolStatus.ERROR`；**不存在"投递失败却 SUCCESS"**（用户澄清：不等回执但要等 ACK）
     - **notify 正常（空闲）**：B 空闲时 A notify B → 消息进 B 的 message_queue → start() 作为新 turn 处理 → B 的 context 收到
     - **notify mid-turn 注入**：B 正忙（run() 执行多 step）时 A notify B → 消息进 message_queue → engine 的 `_message_source.drain()` 在 step 间取走 → `_inject_user_message(from_agent=True)` → 下一 step 的 LLM 看到（**当前 turn 内生效**）
     - **notify 走 agent 消息源**：验证 `AGENT_NOTIFY` 在 `_drain_types` 与 `_cross_agent_types` 中，无需经 `context.add_pending_message`
     - **delegate 正常流程**：A 先 task_management.create 得到 task_id → A delegate B(task_id) → B 收到并执行任务 → B 用 `notify(kind="delegate_receipt", task_id=...)` 回执 → A 的 message_queue 收到 AGENT_NOTIFY → mid-turn 注入或新 turn 处理
     - **delegate 回执走 notify**：断言回执消息 message_type == `AGENT_NOTIFY`、data.kind == `"delegate_receipt"`、data.task_id 正确；**不存在** `AGENT_DELEGATE_RESPONSE`
     - **delegate task_id 必填**：task_id 为空 → `AgentCommunicationError(reason="task_id_required")`，不投递
     - **delegate task 不存在**：task_id 指向不存在的 task → `reason="task_not_found"`，不投递
     - **delegate 发送方不等回执但等 ACK**：mock communicator.send 返回 `{"status":"routed"}` 后验证 `delegate()` 已立即返回（不在回执上阻塞）；send 返回 `routing_failed` 时验证抛错（不静默成功）
     - **delegate 强制回执**：B 的 run() 抛异常 → B 仍用 `notify(kind="delegate_receipt")` 回 failure；B 被 abort → 回 "aborted"
     - **delegate 收件方二次校验**：B 收到的 task 中途被删除 → 用 `notify(kind="delegate_receipt")` 回 "not found"，不执行 run()
     - **delegate ACL 拒绝（必选核心）**：`allowed_targets` 拒绝一次
     - **【可选增强关闭态】**：默认配置下 notify/delegate 的 A→B→A 不被环检测拦截、无预算拒绝
     - **【可选增强打开态——逐项单独打开开关】**：
       - **环检测** `enable_chain_detection=True`：notify/delegate 的 A→B→A 消息被拒（`chain_cycle`），防无限级联；这两种 mode 受约束（request 始终受约束，见上）
       - **预算** `enable_budget=True`：连续 4 次 request（默认 3）第 4 次被拒（`budget_exhausted`）；delegate 预算耗尽被拒；三种 mode 独立计数（**可达性依赖 Task 2.1 中 `request()` 投递成功后 `self._budget.consume("request")`，评审 AC Quality #1 / Consistency #1**）
  2. Fixture 设计：
     - `make_agent(name, config)`: mock agent（mock communicator + mock LLM）
     - `make_messenger(agent)`: 初始化 DefaultAgentMessenger
     - Mock `communicator.send` 模拟 SocketIO 路由；提供 `deliver_request_reply(messenger, request_id, content)` 手动触发 `handle_request_response`（模拟事件处理器）
     - 超时测试用 `request_timeout=0.05`（参考现有 `test_dialog_delivery_regression.py` 的 `agent_query_timeout=0.05` 用法）
- **验收标准**：
  - [ ] 全部测试通过
  - [ ] 验证 request 同步语义：阻塞直到 reply 到达、`request_id` 正确配对、超时抛错、回复唤醒后工具返回结果
  - [ ] 验证 request 回复走专用 `AGENT_REQUEST_RESPONSE` + `handle_request_response`，不进 message_queue、不 mid-turn 注入
  - [ ] 验证 request 的回复保障（正常/异常/abort 三条路径都用 `reply()` 回 AGENT_REQUEST_RESPONSE）
  - [ ] 验证 request 环检测（核心，始终启用）与超时（核心）
  - [ ] 验证**顶层发起方自身 id 入链**：`run(call_chain=None)` 后 `messenger._call_chain.agent_ids` 含自身 id；A↔B 互 request 的**首跳**即以 `chain_cycle` 被拒（不靠超时兜底）（评审 r3 Major / Feasibility #1 / Consistency #1）
  - [ ] 验证 notify 两种消费路径：忙时 mid-turn 注入当前 turn（不新建 run）、空闲时经 start() 作为新 turn
  - [ ] 验证环检测（可选开关打开时）约束 notify/delegate（防消息循环）；默认关闭时不拦截
  - [ ] 验证预算默认关闭不拦截、打开时对应拒绝路径生效
  - [ ] 验证 delegate 强制回执（正常/异常/abort 三路径均以 `AGENT_NOTIFY` + `kind="delegate_receipt"` 回执）、发送方不等回执但等 ACK
  - [ ] 验证三种模式投递失败（ACK=routing_failed）都快速失败：messenger 抛 `AgentCommunicationError(reason="routing_failed")`、`Communicate` tool 返回 `ToolStatus.ERROR`；delegate 的失败不被误报为 SUCCESS
  - [ ] 验证全局无 `AGENT_DELEGATE_RESPONSE` 引用；`AGENT_REQUEST_RESPONSE` 存在且仅用于 request 回复
  - [ ] 使用 `_isolate_home` fixture

---

#### Task 3.3: 全量回归 + 文档

- **目标**：全量测试 + 文档更新
> 依赖: Task 3.1 + 3.2 完成
- **步骤**：
  1. 运行 `pytest broca/tests/ -x --timeout=120` 全量测试，修复回归
  2. 搜索清理遗漏的旧引用（**全 `broca/` 范围**，排除 `broca/alembic/` 历史迁移）
  3. 更新受影响的测试文件：`test_llm.py`（删 3 个 TASK_* parse 测试）、`test_save_user_message_no_mutation.py`（TASK_COMPLETE/ERROR 的 `_cross_agent_types` 断言改为 AGENT_NOTIFY）、`test_non_blocking_mode.py`（`create_task_start` → 用新消息类型或删除用例）、`test_handle_task_assigner_defense.py`（整个文件针对已删除的 `_handle_task`/`send_task_*`，删除或重写）、`test_communicator_abc.py`（从 ABC 抽象方法清单移除 `send_task_*`、加入 `send`）
  4. 更新 `configs/agents/` 中的示例配置（`assign_task` → `communicate`）
  5. 更新 `AgentConfig` docstring 说明 `communication_policy` 字段（含 `request_timeout` / 环检测核心语义）
- **验收标准**：
  - [ ] `pytest broca/tests/ -x --timeout=120` 全量通过
  - [ ] `grep -rn "assign_task\|task_start\|task_complete\|task_error\|TASK_START\|TASK_COMPLETE\|TASK_ERROR\|send_task_\|_handle_task\|create_task_" broca/ --include=*.py --exclude-dir=alembic` 无结果
  - [ ] `broca/loop_engine/engine.py` 3 处 `_cross_agent_types` 均为 `AGENT_NOTIFY`，无 TASK_* 残留（评审 Finding 1.1）
  - [ ] Agent 配置使用 `communicate` tool

---

## 风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| **request 阻塞导致 turn 卡住**：目标不回复/处理很慢时，请求方工具一直等待 | 中 | **request 超时为核心机制**（`request_timeout=300`，对齐 `agent_query_timeout`）；超时抛 `AgentCommunicationError(reason="request_timeout")`，工具返回 ERROR，LLM 可据此决策。Task 1.4 的 `send() -> dict` ACK（Task 2.4 验证）让"目标不可达"立即报错，不进入等待 |
| **request 循环死锁 / `_run_lock` 不可重入自死锁**：A request B → B 处理时 request A → A 的 `_run_lock`（`asyncio.Lock`，不可重入）被自身 run() 持住，嵌套 run 会卡在拿锁；若无人处理 B 的请求，A 又等 B 回复 | 中 | **request 环检测为核心机制（始终启用）**：`Agent.run()` 入口**无条件**把自身 `agent_id` 加入 CallChain（`(call_chain or CallChain()).add(self.agent_id)`），因此 A 顶层发起的首跳 request 携带的链已含 A；B 回发 request(A) 时 `would_create_cycle(A)` 命中即拒（`chain_cycle`），在**投递前**就拦截，不会走到嵌套 run 拿锁。配合 `max_chain_depth=3` + 超时双重兜底。链中比对 agent_id（经同步 `_resolve_agent_id` 解析）。Task 3.2 增加"嵌套 run 不自死锁""顶层发起方自身入链""A↔B 首跳即拒"测试（评审 Risk #7 / r3 Major） |
| **request 回复在请求方 abort/超时后才到达**：滞留回复找不到 pending 项 | 低 | `handle_request_response` 查不到 request_id 时直接忽略；`request()` 的 `finally` 清理 pending。无内存泄漏，无串扰（按 request_id 配对） |
| **无限消息级联/刷屏（notify/delegate）**：A notify B → B notify A → … | 中 | notify/delegate 环检测是**可选增强、默认关闭**：`enable_chain_detection=True` 时启用。默认靠小规模稀疏性 + `dead_loop` hook 兜底 |
| **可选增强默认关闭导致保护缺失**：notify/delegate 环检测/预算默认关 | 中 | 刻意取舍：request 的核心保护（超时/环检测/回复保障）始终生效；notify/delegate 非阻塞、靠 `dead_loop` hook 兜底，出问题再按 agent 配置打开开关 |
| **request 回复误入 message_queue 导致死锁**：若把 `AGENT_REQUEST_RESPONSE` 当普通消息注入，请求方 start() 已被 run() 占住，无人消费 | 高 | `AGENT_REQUEST_RESPONSE` 由 communicator 的 `agent_request_response` 事件**直接**派发到 `messenger.handle_request_response`（类 ask_user 的 user_answer handler），**不进 message_queue**、不在 drain/inject 集合中。Phase 0 验证监听任务与 start() 在不同 task |
| **同进程 SocketIO loopback 延迟**：统一走 SocketIO，request 阻塞等待对延迟更敏感 | 低 | 本机 loopback < 1ms，相对 300s 超时可忽略；Task 2.4 ACK 覆盖"目标不可达"快速失败 |
| **跨进程 target 解析不可用**（评审 Feasibility #1 / Risk #1）：`_resolve_agent_id` 依赖本地 `DefaultAgentFactory.get_agent()`（仅查 `self._session_agents[session_id]`），跨进程的 target name 无法解析 → request/notify/delegate 全部在投递前报错 | 中 | 本期**明确限定同进程、同 session 通信**（见概述约束 / 统一通信方式）；解析失败抛 `AgentCommunicationError(reason="target_not_found")`，不静默投递。跨进程 name→id 远端解析（如经 SocketIO 查询 server 注册表）列为后续工作，不在本期范围 |
| **直接删除 TASK_* 导致外部引用断裂** | 中 | 全量 grep 清理 + CI 全量测试兜底 |
| **ACK 通路改动影响现有 10+ send 方法**：Task 1.4 新增 `_send_message_with_ack`（独立 `ack_fn` + Future），不改 `send_message()` 本体及其 `callback` 语义 | 中 | `send()` 是全新方法（无历史调用者），ACK 走独立方法；`send_message()` 及 `message_callbacks` 响应回调保持原样。全量运行 `pytest broca/tests/test_socketio*.py` + `test_agent.py` 验证无回归（评审 Clarity #2 / Minor） |
| **计划内代码契约不一致导致首次通信即崩溃**（评审 Critical）：`send()` 返回 `str` 却 `.get()`、依赖倒置等 | 高 | 已在 Task 1.4 统一契约为 `send() -> dict`，并前移 ACK 实现；`get_agent()` 统一为同步；engine.py 3 处 TASK 清理纳入 Task 1.1/2.2。这些不是外部风险而是计划缺陷，已直接修入对应 Task 与 AC，评审 Major/Critical 均已消解 |
| **编排场景误用 request**：`CrewOrchestratorRunner` 原 `send_task_start` 是异步任务分配 | 中 | 编排场景**必须**用 `messenger.delegate()`：request 现在阻塞，会改变编排时序。Task 1.4 Step 7 迁移时明确注释禁止用 request 替代 |
| **delegate 投递失败导致任务静默悬空**（用户澄清）：目标不在线、ACK=`routing_failed`，若仍报 SUCCESS，委派方误以为任务已交出、不再跟进，task 永远 pending | 高 | **三种模式都同步等 ACK**：delegate 的 `send()` 返回 `routing_failed` 立即抛 `AgentCommunicationError`，`Communicate` tool 返回 `ToolStatus.ERROR`，委派方可重试/换 target；审计记录 result=routing_failed。Task 2.1/2.3/2.4/3.2 均有对应 AC 与测试 |
| **delegate 回执丢失**（投递成功但收件方未回执）：发送方不等回执 | 中 | 符合 delegate 语义（fire-and-forget 仅修饰回执）：ACK 已确认投递成功，任务确实交给了目标；回执是 `AGENT_NOTIFY`，仅作记录/mid-turn 注入。任务状态以 `task_management` 为准。注意区分"投递失败"（已快速失败上报）与"回执丢失"（可接受） |
| **notify mid-turn 注入被打断的边界**：notify 到达时恰逢 terminal step 或无后续 step | 中 | 沿用 TC-10 规则：terminal step 不注入、消息留队列交 start() 作为新 turn 处理。delegate 回执同理，最终都会被引擎或 start() 消费 |

## 未解决的问题

- ~~notify/delegate 投递失败是否快速失败~~ → **已明确（用户澄清）**：**三种模式都同步等传输层 ACK**（`send() -> dict`，≤2s），ACK=`routing_failed` 一律抛 `AgentCommunicationError(reason="routing_failed")`，`Communicate` tool 返回 `ToolStatus.ERROR`。"fire-and-forget" 仅指 notify/delegate **不等业务回执**，不含 ACK。这样避免 delegate 投递失败却报 SUCCESS 导致任务静默悬空（已登记风险表并加测试）
- ~~是否支持跨进程 agent 通信~~ → **已明确（本次修订）**：本期**仅支持同进程、同 session 内**的 agent 通信。`_resolve_agent_id` 依赖本地 `DefaultAgentFactory.get_agent()`（`agent_manager.py:543` 仅查 `self._session_agents[session_id]`），无远端 name→id 解析能力；跨进程 target 解析失败抛 `AgentCommunicationError(reason="target_not_found")`。跨进程 name→id 远端解析（经 SocketIO 查询 server 注册表）列为**后续工作**，已登记风险（评审 Feasibility #1 / Consistency #3）
- ~~**python-socketio emit callback 特性（决策门槛：Phase 1 结束前必须定稿）**：需确认当前版本是否支持 `sio.emit(event, data, callback=fn)` 且 server `@sio.event message` handler 的 `return value` 会作为 ACK data 回传。~~
  - **结论（Phase 0 确认 + Task 2.4 端到端验证）：采用主方案**。python-socketio 5.18.1 支持 `sio.emit(event, data, callback=fn)`，server `@sio.event message` handler 的 `return` 值作为 ACK data 回传 client 的 emit callback。Task 2.4 用真实 aiohttp server + 真实 SocketIOClient 端到端验证：`send()` 路由成功返回 `{"status":"routed"}`、失败返回 `{"status":"routing_failed",...}`；未走备选方案（无需 `agent_send_ack`）
- ~~notify 如何 mid-turn 处理~~ → **已明确**：不新增 Context pending 缓冲区，复用 `message_queue` → `_message_source.drain()` → `_inject_user_message` 链路（Task 2.2 Step 7），`AGENT_NOTIFY` 加入相应 drain/inject 类型集合
- ~~request 回复如何处理~~ → **已明确（本次修订）**：request 走 **ask_user 式同步链路**——`messenger.request()` 投递后阻塞在 `asyncio.wait_for(event.wait())`；收信方用 `reply()` 发 `AGENT_REQUEST_RESPONSE`（带 `request_id`），由 communicator 的 `agent_request_response` 事件**直接**调用 `handle_request_response` 唤醒 Event；工具返回回复文本，LLM 当前 turn 继续。专用响应类型恢复，超时恢复；环检测对 request 强制启用。`agent_reply` 不作为注入事件，而是直接唤醒 Event
- ~~超时/熔断是否保留~~ → **已明确**：**超时恢复为 request 核心机制**（`request_timeout`，对齐 `agent_query_timeout`）；**熔断删除**（无跨请求失败统计需求）；**环检测对 request 强制启用**（防阻塞死锁），对 notify/delegate 仍可选
- ~~delegate 回执是否用专用消息类型~~ → **已明确**：复用 `AGENT_NOTIFY`（`kind="delegate_receipt"` + `task_id`），无 `AGENT_DELEGATE_RESPONSE`
- ~~编排场景迁移策略~~ → **已明确**：Task 1.4 Step 7 用 `messenger.delegate()` 保持异步语义（request 阻塞，禁止用于任务分配）
- **delegate 回执内容的落库位置**：回执作为 `AGENT_NOTIFY` mid-turn 注入委派方 LLM 后，是否额外写入 task 报告？
  - **建议**：不额外写——收件方 run() 内已通过 `task_management` 更新 task 报告；回执仅作即时通知。若需审计，`notify()` 的 `kind="delegate_receipt"` 已进审计日志。Phase 3 前定稿即可，不阻塞前面阶段

---

## 附录：变更历史

> 本附录收录历次评审驱动的修订记录，属过程元信息，不影响正文结论。最新结论见文首摘要。

### 修订记录（2026-11-16，依据 `reports/review/agent-messenger-plan-review-r3.md`）

已消解 Round 3 的 2 Major（同一根因）+ 8 Minor：

- **Major（Feasibility #1 / Consistency #1）— CallChain 起点缺发起方自身 id**：`run()` 原先 `if call_chain: set_call_chain(call_chain.add(self.agent_id))` 在顶层 turn（`call_chain=None`）时发起方自身 id 不入链，导致 A↔B 互 request 首跳环检测失效、退化为 300s 超时兜底。**修复**：改为无条件 `self.messenger.set_call_chain((call_chain or CallChain()).add(self.agent_id))`（Task 2.2 Step 6），并在 Task 2.1 / Task 3.2 增加"顶层 request 的 call_chain 含自身 agent_id""A↔B 互 request 首跳即 `chain_cycle` 被拒"断言；同步校正风险表「request 循环死锁」表述。
- **Minor（Completeness #1）**：Task 2.1 补齐 `set_call_chain` / `reset_budget` 实现，并加"8 抽象方法可实现、可经 Registry 实例化"AC。
- **Minor（Clarity #1）**：校对 Task 2.1 / Task 2.3 伪代码缩进（`_execute` 的 `try:`、`_check_permissions` 的可选段）。
- **Minor（Clarity #2）**：`notify()` / `delegate()` 只解析一次 `target_id`，`_check_with_mode` 改为接收已解析的 `target_id`，消除二次解析。
- **Minor（Feasibility #2）**：`_send_message_with_ack` 的 `asyncio.get_event_loop()` → `asyncio.get_running_loop()`（Task 1.4）。
- **Minor（Feasibility #3）**：Phase 0 增补"确认 `TaskManager.get_task` 是否协程"核实项。
- **Minor（Feasibility #4 / Consistency #2）**：明确 `reply()` 为 best-effort（不抛错、但记录 `result=routing_failed` 审计），与 request/notify/delegate 的强失败语义区分并在 AC 写清。
- **Minor（Proportionality #1）**：三段修订记录移入本附录，正文开头仅留摘要。
- **Minor（Consistency #3）**：`_handle_incoming_delegate` 伪代码改为 `try/finally` 单次回执，与 AC 一致，消除双重回执风险。

### 修订记录（2026-11-16，用户澄清 ACK 语义）

- **Task 2.1**：`notify()` / `delegate()` 改用 `_send_and_check_ack()`（原为裸 `send()`），routing_failed 抛 `AgentCommunicationError(reason="routing_failed")`；审计 result 用局部 `final_result` 记录 routed/routing_failed。
- **Task 2.3**：`Communicate` 的 notify/delegate 分支因异常被捕获 → 返回 `ToolStatus.ERROR`，不再无条件 SUCCESS；避免"任务没委派出去却报告成功"导致任务静默悬空。
- **Task 2.4 / Phase 2 / 风险表 / Task 3.2**：投递失败语义从"仅记审计日志"改为"快速失败 + tool ERROR + 审计"；新增 notify/delegate routing_failed 测试用例。

### 修订记录（2026-11-16，依据 `reports/review/agent-messenger-plan-review-r2.md`）

- **Major — request 预算不可达**：`request()` 投递成功后补 `self._budget.consume("request")`，与 AC 的 `budget_exhausted` 断言对齐（Task 2.1）。
- **Major — Phase 1 全量 pytest 与测试更新时序冲突**：Phase 1/2 阶段 AC 放宽为"生产代码无引用断裂"，明确 5 个受影响测试文件统一在 Task 3.3 更新；全量 pytest 通过的硬性门槛只保留在 Phase 3 的 Task 3.3。
- **Major — 跨进程表述与本地解析能力矛盾**：通信范围明确为**同进程、同 session**；`_resolve_agent_id` 仅查本地 factory，跨进程列为后续工作并登记风险。
- **Major — `config` 二义**：`initialize(config: "AgentConfig | None")` 明确类型，内部显式 `self._config = config.communication_policy` + `AuditLogger(config.workspace)`。
- **Minor**：删除 `force_chain_check` 死参数；审计 result 改用局部结果变量；补 `target_not_found` reason；`Communicate` 按 `reply.status` 映射 `ToolResult` 状态；风险表补跨进程解析风险。

### 修订记录（2026-11-16，依据 `reports/review/agent-messenger-plan-review.md`）

- **Critical — `send()` 返回契约**：统一为 `send() -> dict`（ACK 结果）。
- **Major — `get_agent` sync/async**：统一为同步 `def`。
- **Major — engine.py 3 处 TASK_* 清理遗漏**：纳入删除清单 + Task 1.1/2.2 + grep/AC。
- **Major — Task 2.4 伪代码错误 + callback 命名冲突**：新增 `_send_message_with_ack`（独立 `ack_fn`）。
- **Major — Task 2.1↔2.4 依赖倒置**：ACK 实现前移到 Task 1.4。
- **Minor**：Phase 0 补阶段验收标准；`send()` 返回类型 AC；滞留回复/嵌套 run 测试；`defaults.py` 组件计数注释。
