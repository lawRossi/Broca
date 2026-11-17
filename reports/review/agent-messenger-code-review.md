# AgentMessenger — 纯代码审查报告

> 范围：`broca/agent_messenger/*`、`broca/agent.py`、`broca/communication/socketio_{client,server}.py`、`broca/tools/agent_interaction.py`、`broca/components/*`、`broca/session/models.py`、`broca/loop_engine/engine.py`、`broca/agent_configs.py`、`broca/session_runner/orchestrator_runner.py`、`broca/tools/executor.py`。
> 方法：仅静态阅读源码 + 少量只读运行时内省（导入/字段检查）。**未创建、未新增任何测试文件**。
> 规则：只审查、只报告，不修复。

## 结论摘要

整体实现质量高，核心链路（request 阻塞配对/超时/环检测、reply 保障、三模式 routing_failed 快速失败、旧代码删除、ACK 通路）逻辑自洽，D3 bug（`message.content`）已正确修复。代码审查未发现会导致功能失效的 Critical 缺陷。发现 **2 个 Medium**（审计缺口、reply 契约与实现不一致）和若干 Low/代码味道项。

| 严重度 | 数量 | 说明 |
|:------:|:----:|------|
| 🔴 Critical | 0 | — |
| 🟡 Medium | 2 | 审计拒绝路径无记录；`reply()` best-effort 契约可被调用方异常击穿 |
| 🟢 Low | 5 | 死参数、best-effort task 校验、ACK 假值处理、审计深度取值、参数校验 |

---

## 🟡 Medium

### M1. 所有"拒绝"路径均未写审计，`rejection_reason` 字段是死字段

**位置**：`broca/agent_messenger/messenger.py` — `request()` L98-103、`notify()` L213-218、`delegate()` L247-257；`_check_permissions` L291-310；审计模型 `broca/agent_messenger/audit.py` L31-36。

**现象**：
- `CommunicationEvent.result` 的注释声明取值含 `rejected`，并专门定义了 `rejection_reason` 字段；`audit.py` 模块 docstring 声称"every request / reply / notify / delegate attempt produces a JSONL line"。
- 但三方法中所有拒绝分支（ACL `acl_denied`、`chain_cycle`、`chain_depth_exceeded`、`task_id_required`、`task_not_found`、`target_not_found`）都在进入 `try/finally` **之前** `raise`。审计只写在 `finally` 里（`_log_audit`），因此**拒绝路径不产生任何审计行**。
- 全仓库检索确认：`result="rejected"` 与 `rejection_reason=` 在 `broca/` 生产代码中**无任何写入点**，`_log_audit()` 也不接收 `rejection_reason` 参数。

**影响**：ACL 越权、环检测拒绝、task 校验失败这类安全/协议关键事件完全没有审计痕迹，与审计模型的自述和审计设计意图不符；`rejection_reason` 为死字段。

**建议**（不实施，仅建议）：把权限/校验提前到 `try` 内，或用统一包装（如每层 `except AgentCommunicationError as e:` 调 `_log_audit(result="rejected", rejection_reason=e.reason)`）后再 `raise`，并让 `_log_audit` 支持 `rejection_reason`。

### M2. `reply()` 的 "best-effort / 不抛错" 契约被 `_resolve_agent_id` 击穿

**位置**：`broca/agent_messenger/messenger.py` L159-187（`reply()`），尤其 L175 `target_id = self._resolve_agent_id(target_name)`；调用方 `broca/agent.py` L467-472。

**现象**：
- `reply()` docstring 明确写 "a ``routing_failed`` ACK is **not** raised here"，向调用方承诺尽力而为、不抛错。
- 但 L175 的 `_resolve_agent_id()` 在**收件方工厂查不到发件方**（发件方已 abort/下线/被移出 session）时抛 `AgentCommunicationError(reason="target_not_found")`。这是"抛错"，与契约语义相悖——`routing_failed` 被吞掉，但等价的 `target_not_found` 却抛出。
- 目前唯一调用方 `_handle_incoming_request` 的 `finally` 用 `try/except Exception` 兜住了（agent.py L467-472），所以**当前不会导致崩溃**；但任何新调用方按 docstring 信任该契约（不写 try/except）都会踩坑，属于"文档与行为不一致 + 隐藏陷阱"。

**建议**：要么让 `reply()` 真正 best-effort（把 `_resolve_agent_id` 包进 try，失败只记审计不抛）；要么把 docstring 改为准确描述（"解析不到 target 时抛 `target_not_found`，调用方需捕获"），与 `request/notify/delegate` 的强失败语义统一说明。

---

## 🟢 Low / 代码味道

### L1. `socketio_client.send()` 里 `Message(content=content, ...)` 的 `content` 是死参数

**位置**：`broca/communication/socketio_client.py` L465-473。

**现象**：`Message`（pydantic 模型，`broca/session/models.py` L249+）**没有 `content` 字段**，extra 字段被静默忽略（只读内省确认：构造后 `hasattr(m, "content") == False`，`m.data` 不含自动注入的 content）。真正的内容随 `data`（`comm.to_dict()` 内含 `"content"`）传输，`handle_request_response` 也从 `message.data["content"]` 读取。因此功能正确，但 `Message(content=content, ...)` 这行是**误导性死代码**——正是 D3 bug（计划伪代码写 `message.content`）的同源陷阱，容易诱使后来者以为 content 在 `Message` 字段上。

**建议**：删除该 `content=content` 实参，或加注释说明 content 只走 `data`；`send()` 的 `content` 形参可考虑只用于 `comm`（若上层未放进 data 则在此显式写入 `data["content"]`）。

### L2. `_check_task_exists` 在 `task_manager is None` 时放行 delegate

**位置**：`broca/agent_messenger/messenger.py` L281-289（`"No task manager wired — cannot pre-check; allow (best-effort)."`）。

**现象**：计划把"task 存在性校验"列为 delegate 的**核心必选硬约束**。生产路径 `Agent.create()` 恒传入 `TaskManager()`（agent.py L171），所以线上校验生效；但在未注入 task_manager 的上下文（如某些单测/embedding）里 delegate 会**跳过校验直接投递**，与"task 必须真实存在"的硬约束语义有出入。与 `_handle_incoming_delegate`（agent.py L487-492）在收件方 task_manager 为 None 时按"not found"处理的行为也不完全对称。

**建议**：明确策略——要么无 task_manager 即拒（`task_not_found`/内部错误），要么在文档/注释中把它标为"仅测试环境宽松"。

### L3. `_send_and_check_ack` 与 `reply()` 对 ACK 假值的处理不一致

**位置**：`messenger.py` L312-319（`if result and result.get("status") == "routing_failed"`）vs L179（`ok = bool(result) and result.get("status") == "routed"`）。

**现象**：真实 `SocketIOClient.send()` 恒返回 dict，故无实际 bug。但二者对 `None`/`{}` 等假值 ACK 的方向相反：`_send_and_check_ack` 把假值当**成功**（不抛错），`reply()` 把假值当**失败**。若未来换成返回 `None` 的 Communicator 实现，request/notify/delegate 会"静默成功"，与"投递失败必须上报"的核心承诺冲突。

**建议**：统一为"既非 `routed` 即视为失败"的白名单判断，与 `send()` 的契约（`-> dict`，`status ∈ {routed, routing_failed}`）保持一致。

### L4. 审计 `call_depth` 取自审计时刻的 `self._call_chain`，非发送时刻

**位置**：`messenger.py` `_log_audit()` 中 `call_depth=self._call_chain.depth`，被 request/notify/delegate/reply 的 `finally` 调用。

**现象**：`_call_chain` 是 messenger 实例状态，由 `Agent.run()` 在每次入口 `set_call_chain(...)` 改写。请求发出后到 `finally` 写审计之间若发生嵌套 `run()`（调用链被改写），审计记录的 `call_depth` 会是该消息**发送之后**的链深度，而非投递时的真实深度。当前 request 在等待回复期间 messenger 通常不被复用，风险低；但属于"记录取值时机不准"的隐患。

**建议**：在构造 `AgentCommunication` 时把 `self._call_chain.depth` 存入局部变量，审计时使用该快照。

### L5. `AgentCommunication.from_message_data()` 对必需键无校验

**位置**：`broca/agent_messenger/message_models.py` `from_message_data()` —— 用 `data["source_agent"]`、`data["target_agent"]`、`data["mode"]`、`data["content"]` 直接下标取值。

**现象**：若收到结构残缺或恶意构造的 `AGENT_REQUEST`/`AGENT_DELEGATE` data（如缺少 `content`），会抛 `KeyError`。该调用在 `agent.py` `start()` 消息循环里（L700/L704），外层有 `except Exception` 兜底不会崩，但会导致该消息被静默丢弃；对 request 而言发件方会等到超时。属健壮性问题，非当前主链路缺陷。

**建议**：改用 `.get()` 并提供默认值，或在入口做一次结构校验并快速回错。

---

## 已确认正确 / 值得肯定的点（审查取证）

- **D3 修复正确**：`handle_request_response()`（messenger.py L189-205）从 `message.data["content"]` 读取回复文本，与 `reply()` 写入 `comm.to_dict()` 的 `content` 字段一致；实测 `Message` 无 `content` 属性，故该修复是必要的且正确。
- **首跳环检测成立**：`Agent.run()`（agent.py L773-774）无条件 `(call_chain or CallChain()).add(self.agent_id)`，顶层发起方自身 id 入链；`_check_permissions` 用 `target_id`（agent_id）比对链中 agent_id，`_resolve_agent_id` 返回 `target.agent_id`（agent_manager.py L543-546 按 name 索引返回 Agent；`create()` 用 `scope_key=agent.agent_id` 使 communicator.client_id == agent_id），路由 id 口径自洽。
- **request 生命周期**：pending 表 + `asyncio.Lock` + `wait_for(event.wait(), request_timeout)` + `finally` 清理 + 按 `request_id` 配对 + 滞留回复忽略，逻辑完整无竞态漏洞（pending 只被本请求 finally 移除）。
- **三模式 ACK 失败语义**：`_send_and_check_ack` 对 `routing_failed` 抛 `AgentCommunicationError(reason="routing_failed")`；`Communicate._execute` 捕获后返回 `ToolStatus.ERROR`（agent_interaction.py L331-334），不存在"delegate 投递失败却 SUCCESS"。
- **dispatch 隔离**：`AGENT_REQUEST_RESPONSE` 映射到专用 handler `handle_request_response`（`socketio_client.py` L56 + `agent.py` L177），不在任何 `_drain_types`/`_cross_agent_types`（已核实 agent.py L625/655、engine.py L394/453/459 仅含 `AGENT_NOTIFY`）；无通用 `"message"` handler 二次入队。
- **旧代码删除**：生产代码（排除 alembic/tests）grep 无 `assign_task|TASK_*|send_task_|_handle_task|create_task_` 残留；`MessageType` 新增 4 值、删 3 值，`AGENT_DELEGATE_RESPONSE` 不存在。
- **配置迁移**：`configs/configs.json` 用 `communicate_timeout=1800`、`tool_permission_config.json` 用 `communicate: allow`、Broca.md tools 含 `communicate`；executor `_get_timeout("communicate")` 返回 1800s，覆盖 request 最长 300s 阻塞。

---

## 建议优先级

1. **先修 M1、M2**：补齐拒绝路径审计 + 修正 `reply()` 契约，二者都涉及对外承诺（可审计性、异常契约）。
2. **再处理 L1-L3**：消除死参数、统一 task 校验策略与 ACK 假值判断，降低后续误用风险。
3. **L4-L5 视需要**：属于健壮性增强，非阻断项。

---

## ✅ 修复记录（已按本报告实施）

全部 M1–M2 与 L1–L5 已修复，并新增回归测试 `broca/tests/test_agent_messenger_review_fixes.py`（19 个用例）。全量测试：**1805 passed / 2 skipped / 1 deselected**。

| 编号 | 处理方式 | 落点 |
|:----:|----------|------|
| **M1** | `request/notify/delegate` 校验提前进 `try`，拒绝分支置 `final_result="rejected"` + `rejection_reason=<reason>`，由 `finally` 的 `_log_audit` 统一落审计；`_log_audit` 新增 `rejection_reason` 参数。`rejection_reason` 不再是死字段。 | `messenger.py` |
| **M2** | `reply()` 真正 best-effort：`_resolve_agent_id` 包 `try/except AgentCommunicationError`，失败仅记审计（`result="routing_failed"`, `rejection_reason="target_not_found"`）后 `return`，不抛错；docstring 同步更新。 | `messenger.py` |
| **L1** | 删除 `Message(content=content, ...)` 死参数；若 `data` 缺 `content` 则显式写入 `data["content"]=content`，并加注释说明 content 只走 `data`。 | `socketio_client.py` |
| **L2** | `_check_task_exists` 在 `task_manager is None` 时改为 **fail-closed**（`task_not_found`），与收件方 `_handle_incoming_delegate` 语义对齐；生产恒注入 TaskManager，仅影响嵌入/测试上下文。 | `messenger.py` |
| **L3** | `_send_and_check_ack` 改为白名单：仅 `status=="routed"` 算成功，falsy / 无 status 的 ACK 一律按 `routing_failed` 抛错，与 `reply()` 判定一致。 | `messenger.py` |
| **L4** | 各方法入口捕获 `chain_depth = self._call_chain.depth` 快照并透传给 `_log_audit(call_depth=...)`，审计记录发送时刻深度而非 `finally` 时刻。 | `messenger.py` |
| **L5** | `from_message_data` 改用 `.get()` + 默认值（含 `data or {}`），残缺/恶意 payload 不再抛 `KeyError`。 | `message_models.py` |

### 追加：防止 Agent 向自己发消息（self-target guard）

在 `_check_permissions` 最前面加入自投递拦截：`target_id == self.agent_id` 时返回 `self_target` 拒绝（`request`/`notify`/`delegate` 三模式统一生效，经 M1 修复后自动落审计 `result="rejected", rejection_reason="self_target"`）。原因：自 `request` 会永久阻塞等自己的回复（死锁），自 `notify`/`delegate` 会让自身消息队列自循环。

回归测试：`TestSelfTargetGuard`（4 例：request/notify/delegate 自投递拒绝 + 正常跨 Agent 发送不受影响）。
