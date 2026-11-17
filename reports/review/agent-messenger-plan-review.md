# AgentMessenger — 统一 Agent 间通信通道 — Plan Review Report

## Overview

| Item | Content |
|------|---------|
| Plan File | `plans/agent-messenger-plan.md` |
| Reviewed At | 2026-11-16 17:23:50 CST |
| Review Scope | Full plan (Phase 0 + Phase 1/2/3, Tasks 1.1–3.3) |
| Overall Score | ⭐⭐⭐ / 5 |
| Verdict | ❌ **Needs Revision** |
| Grounding | Key claims cross-checked against actual source (`defaults.py`, `agent_manager.py`, `socketio_client.py`, `socketio_server.py`, `agent.py`, `loop_engine/engine.py`, `agent_interaction.py`) |

> 说明：本报告对计划中引用的代码事实做了抽样核验。核验发现 **1 个 Critical、5 个 Major** 问题，其中多数为“计划文本与实际代码契约不符”或“计划内部自相矛盾”。这些问题在按字面执行时会直接导致运行时错误，**必须在执行前修正**。

### Dimension Scores

| # | Dimension | Score | Key Finding |
|:-:|-----------|:-----:|-------------|
| 1 | 📋 Completeness | ⭐⭐⭐⭐ | 必备章节齐全、AC 覆盖到每个 Task；但删除清单遗漏 `loop_engine/engine.py` 中 3 处 `TASK_*` 引用 |
| 2 | 🔍 Clarity | ⭐⭐⭐ | 整体极其详尽；但 Task 2.4 的 server 伪代码与实际 API 不符，`callback` 语义存在命名冲突 |
| 3 | 🎯 AC Quality | ⭐⭐⭐⭐ | 绝大多数 AC 具体、可测（reason 枚举、精确断言）；个别 AC 用“等”字偏泛 |
| 4 | 🏗️ Feasibility | ⭐⭐ | `send()` 返回类型契约破裂（str vs dict）、`get_agent()` sync/async 不一致、Task 2.4 伪代码不可运行 |
| 5 | 🔗 Structure & Dependencies | ⭐⭐⭐ | 阶段顺序合理；但 Task 2.1 依赖 Task 2.4 的 ACK 结果却排在其前，依赖未声明 |
| 6 | ⚠️ Risk Identification | ⭐⭐⭐⭐ | 12 条风险覆盖全面、缓解措施具体；但遗漏了若干代码集成类风险 |
| 7 | ⚖️ Proportionality | ⭐⭐⭐⭐⭐ | 复杂系统配 3 阶段 11 Task + 风险表，详略得当，无过度/不足设计 |
| 8 | ✅ Internal Consistency | ⭐⭐ | 多处硬矛盾：返回类型、sync/async、engine.py 清理范围、Task 2.4 伪代码、组件数量 |
| | **Overall** | **⭐⭐⭐** | 架构思路扎实、细节丰富，但存在 1 个会导致全线崩溃的契约矛盾，需修订后复审 |

---

## Detailed Findings

### 1. 📋 Completeness — ⭐⭐⭐⭐

**Summary**: 所有必备章节（概述 / 相关材料 / 总体方案 / 执行计划 / 风险与应对 / 未解决的问题）齐备；Phase 1/2/3 均有阶段验收标准，每个 Task 都有目标、步骤、预期产出、2–10 条 AC。Phase 0 以 checklist 形式给出，未单独写“阶段验收标准”，但作为前置验证可接受。主要缺口是删除清单的范围不完整。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | 🟡 Major | 总体方案「删除清单」/ Task 1.1 Step 6 / Task 2.2 Step 7 | 删除 `TASK_START/TASK_COMPLETE/TASK_ERROR` 枚举时，遗漏了 `broca/loop_engine/engine.py` 中的 **3 处** `_cross_agent_types = (MessageType.TASK_COMPLETE, MessageType.TASK_ERROR)`（约 L394、L453、L459，跨越 2 个函数），以及 `agent.py` 中两处 `_drain_types` 的 docstring 提到 TASK_*。核验确认这些引用真实存在。枚举删除后这些代码路径会抛 `AttributeError`。 | 在删除清单与 Task 1.1 / Task 2.2 步骤中显式列出 `loop_engine/engine.py` 的 3 处引用迁移为 `AGENT_NOTIFY`，并在 Task 3.3 的“无 TASK_* 残留” grep 中覆盖 `broca/loop_engine/`。 |
| 2 | 🟢 Minor | Phase 0「前置验证」 | 只有 checklist，没有像 Phase 1/2/3 那样的显式“阶段验收标准”小标题。 | 补一行“阶段验收标准：4 项检查全部确认，callback 备选方案结论记录到未解决的问题”，保持各阶段结构一致。 |
| 3 | 🟢 Minor | 未解决的问题 | 第 1 项（python-socketio callback）与第 7 项（delegate 回执落库）仍 open；虽然写了“不阻塞”，但第 1 项实际阻塞 Task 2.4 的设计。 | 明确第 1 项的决策截止点（Phase 1 结束前），并将其结论作为 Task 2.4 的前置依赖门槛。 |

---

### 2. 🔍 Clarity — ⭐⭐⭐

**Summary**: 计划对 request 同步链路、双通道回复、核心/可选控制机制的描述非常清晰，尤其是 `ask_user` 链路剖析与 mid-turn 两条链路的对比图。但 Task 2.4 的伪代码与实际代码 API 不符，且 `callback` 术语存在冲突，执行者照做会走偏。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | 🟡 Major | Task 2.4 Step 2 | 伪代码 `result = self._process_message(sid, data); return result` 与实际代码有三处不符（已核验 `socketio_server.py`）：(a) `_process_message` 是 `async def`，必须 `await`；(b) 其签名是 `_process_message(self, sid, message: Message)`，接收 `Message` 对象而非原始 `data` dict；(c) 当前 `_process_message` **不返回**路由结果（`result` 是局部变量，函数隐式返回 `None`）。照伪代码写会得到 coroutine 或 `None`。 | 将伪代码改为 `result = await self._process_message(sid, message)`，并先在 `_process_message` 中 `return {"status": "routed"}` / `{"status": "routing_failed", "reason": ...}`。 |
| 2 | 🟡 Major | Task 2.4 Step 1 + Task 2.1 `_send_and_check_ack` | `SocketIOClient.send_message()` **已有一个 `callback` 参数**（已核验 `socketio_client.py:376`），但其语义是“按 message_id 登记的响应回调”(`self.message_callbacks`)，并非 socketio emit 的 ACK callback。Task 2.4 说“传入 callback 参数，内部用 `sio.emit(..., callback=ack_fn)`”，未区分这两个同名不同义的机制，执行者极易混用。 | 明确区分命名：新增 emit-ACK 用独立参数（如 `ack_fn` / `emit_callback`），并说明它与既有 `message_callbacks` 响应回调的关系（复用还是并存）。 |
| 3 | 🟢 Minor | Task 2.4 Step 2 与既有 `routing_failed` 路径 | Server 当前已通过 `_send_error(..., code="ROUTING_FAILED")` 向发送方反馈路由失败（已核验 `socketio_server.py:444-450`）。计划提出再增加一条“ACK 返回值”机制，但未说明两者是替换、并存还是去重。 | 明确：是保留 `_send_error` 并在客户端 handler 里转换成 ACK，还是完全以 ACK 返回值取代它；避免两套机制重复触发。 |
| 4 | 🟢 Minor | Task 2.1 `_resolve_agent_id` | 该方法在核验中被写为同步 `def`，其中 `self._agent_factory.get_agent(...)` 无 `await`；但 Task 1.4 把 ABC 声明为 `async def get_agent`。执行者不知以哪个为准（详见维度 4/8）。 | 统一为同步（推荐，与实际实现一致）或全程 async，并在两处保持一致。 |

---

### 3. 🎯 AC Quality — ⭐⭐⭐⭐

**Summary**: AC 质量整体很高。大量 AC 做到了具体、可测、可程序化验证，例如 `reason` 枚举清单、`CallChain(["a","b","c"]).is_within_depth(3) == False`、超时用 `0.05s`、grep 无残留等。扣分项仅为少量偏泛表述与个别缺失断言。

| # | Severity | Location | AC | Issue | Suggestion |
|:-:|:--------:|:--------:|----|-------|------------|
| 1 | 🟡 Major | Task 2.1 验收标准 | 全组 AC 中有一条隐含契约：“`_send_and_check_ack` 收到 `routing_failed` → 立即报错”，但没有任何 AC 校验 `communicator.send()` 的**返回值类型与内容**（实际返回 `str`）。这使最关键的 routing_failed 路径 AC 无法被真正验证（详见维度 4）。 | 增加 AC：“`Communicator.send()` 返回 ACK 结果 dict（`{"status": "routed"\|"routing_failed", ...}`）；`_send_and_check_ack` 对 str 返回值不调用 `.get()`”。 |
| 2 | 🟢 Minor | Task 2.4 验收标准 4 | “现有 SocketIO 功能不受影响（`send_user_message` / `send_agent_response` 等仍正常工作）”——“等”字开放-ended，不够可测。 | 改为“`pytest broca/tests/test_socketio*.py` 与 `test_agent.py` 全量通过（已在风险表出现，可复用为 AC）”。 |
| 3 | 🟢 Minor | Phase 3 阶段验收标准 | 有“request 回复走同步唤醒…无专用 mid-turn 链路”，但没有显式断言“滞留回复（late reply）被忽略、不串扰”（仅在风险表描述）。 | 补一条 AC：“超时后到达的 `AGENT_REQUEST_RESPONSE` 被 `handle_request_response` 静默忽略，pending 表无残留”。 |

Good ACs identified:
- Task 1.2: `CallChain(["a","b"]).would_create_cycle("a") == True` / `is_within_depth(3) == False` — ✅ 精确、边界明确、可直接转单测。
- Task 2.1: 拒绝路径 `reason` 的 8 值枚举 — ✅ 可测、与工具层错误呈现直接对应。
- Task 3.2: request/notify/delegate 三态 + 可选增强开/关两态的逐项测试清单 — ✅ 覆盖了核心机制与可选增强的交叉矩阵，非常完整。

---

### 4. 🏗️ Feasibility — ⭐⭐

**Summary**: 架构思路（复用 ask_user 链路、统一 SocketIO、专用响应类型 + Event 唤醒）技术上成立，且已核验 `ask_user` 的 handler 注册方式确实存在（`agent.py:147` 注册 `AskUserToolManager.handle_user_answer`）。但计划中有 3 处与实际代码契约不符的硬伤，按字面执行会产生运行时错误。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | 🔴 Critical | Task 1.4 `Communicator.send` 声明 + Task 2.1 `_send_and_check_ack` | **返回类型契约破裂（已核验）**：`Communicator.send` ABC 声明 `-> str`（Task 1.4 Step 3）；`SocketIOClient.send()` 返回 `await self.send_message(msg)`，而 `send_message()` 实际返回 `message.message_id`（`str`，见 `socketio_client.py:419`）。但 `_send_and_check_ack` 写的是 `result = await ...send(...)` 然后 `result.get("status")`。**`str` 没有 `.get()`，第一次通信即抛 `AttributeError`，request/notify/delegate 全线崩溃。** Task 2.4 虽提出用 emit callback 拿 server 的 dict，但未说明如何把该 dict 变成 `send()` 的返回值。 | 统一契约二选一并写进计划：①把 `send()`/`send_message()` 的返回类型改为 ACK 结果 dict（并同步 ABC 签名与其所有调用点）；②或保持 `str` 返回，改为从独立 channel（如 `message_callbacks` / Future）读取 ACK，`_send_and_check_ack` 不再对返回值 `.get()`。给出明确的数据流伪代码。 |
| 2 | 🟡 Major | Task 1.4 Step 4 + Task 2.1 `_resolve_agent_id` | **sync/async 不一致（已核验）**：`agent_manager.py:543` 的实际实现是 `def get_agent(...)`（同步）；Task 2.1 的 `_resolve_agent_id`（同步 `def`）也按同步调用、无 `await`；但 Task 1.4 要求在 `AgentFactory` ABC 中声明 `async def get_agent(...)`。三方矛盾，执行者无论照哪版写都会与另一版冲突。 | 将 ABC 声明改为同步 `def get_agent(...)`（与现有实现和调用点一致），并删除所有 `async` 措辞；或若确需 async，则同步改造 `DefaultAgentFactory.get_agent` 与 `_resolve_agent_id`（加 `await`）。 |
| 3 | 🟡 Major | Task 2.4 Step 1/2 | 伪代码不可运行（见维度 2 #1/#2）：`_process_message` 需 `await`、需接收 `Message`、需显式 `return` 路由结果；且既有 `callback` 参数语义冲突。 | 按维度 2 建议修正伪代码，并在 Phase 0 增加“确认 server event handler 返回值会作为 socketio ACK data 回传”的验证项。 |
| 4 | 🟢 Minor | Phase 0 与 Task 2.4 | 备选方案（server 额外 emit `agent_send_ack`）仅在未解决问题中一句话带过，没有对应任务/文件/验收标准，若主方案失败则 Task 2.4 无可执行路径。 | 在 Task 2.4 中补充备选方案的分支步骤与 AC，或明确标注“若 Phase 0 判定不支持则回到 create-plan 修订”。 |

---

### 5. 🔗 Structure & Dependencies — ⭐⭐⭐

**Summary**: 阶段顺序（基础设施 → 核心实现 → 测试收尾）与 Task 内依赖声明（`> 依赖:`）总体清晰合理；`AGENT_REQUEST_RESPONSE` 直接 handler、notify 走 mid-turn 的双链路划分逻辑自洽。主要问题是 ACK 数据流的依赖顺序没有正确表达。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | 🟡 Major | Task 2.1 vs Task 2.4 | Task 2.1 的 `_send_and_check_ack` 依赖 Task 2.4 提供的 ACK 返回值，但计划把 2.1 排在 2.4 之前，且 Task 2.1 的依赖行只列了 Phase 1 任务、未列 Task 2.4。执行者做完 2.1 时 `send()` 仍只返回 str，2.1 的 AC 无法通过。 | 要么把 ACK 能力前移到 Task 1.4（作为 `send` 契约的一部分），要么在 Task 2.1 依赖中显式加入 Task 2.4，并调整执行顺序为 2.4 → 2.1，或在 2.1 先用桩、2.4 再接通。 |
| 2 | 🟢 Minor | Task 2.2 Step 7 vs Task 1.1 Step 6 | mid-turn drain/inject 集合的迁移被分散在 Task 1.1（删除 TASK_*）与 Task 2.2（加入 AGENT_NOTIFY）两处，且 engine.py 的 3 处只在 2.2 提到 1 处（见维度 1 #1）。同一组集合的“删旧/加新”应集中描述，否则易漏改。 | 在 Task 1.1 一次性列出所有需迁移的 drain/inject 集合位置（agent.py 2 处 + engine.py 3 处），Task 2.2 专注 Agent 集成逻辑。 |
| 3 | 🟢 Minor | Task 3.1 vs Task 3.2 | 两者都依赖 Phase 1，但 3.2 还依赖 Phase 2 全部任务，依赖关系已注明，正确；无需改动，仅记录评审已确认。 | — |

---

### 6. ⚠️ Risk Identification — ⭐⭐⭐⭐

**Summary**: 风险表有 12 条，覆盖 request 阻塞卡死、循环死锁、滞留回复、mids-turn 边界、删除旧代码引用断裂、callback 影响现有 send 方法、编排误用 request、delegate 回执丢失等关键风险，缓解措施具体且与 Task 对应（例如 request 超时/环检测列为必选、ACK 快速失败、TC-10 terminal-step 规则）。扣分主要因为缺少“计划自身代码契约错误”类风险。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | 🟡 Major | 风险表 | 未识别“`send_message` 返回 `str` 却被当作 dict 使用”“`get_agent` sync/async 不一致”“engine.py 3 处 TASK_* 引用未迁移”——这些不是外部风险而是计划内在缺陷，直接执行必然失败。 | 这类问题应作为修订项直接修入计划（已在本报告维度 4/8 列出），而非仅记入风险表。 |
| 2 | 🟢 Minor | 风险表「request 循环死锁」 | 缓解依赖 `CallChain` 随消息传递并在 `run()` 里 `set_call_chain(call_chain.add(self.agent_id))`。但计划未说明当同一 agent 嵌套 `run()`（request 处理中又触发 request）时 `_run_lock` 是否可重入——若不可重入，B 处理 request 时再 request A 会在拿到锁前就卡住。 | 补充验证：`Agent.run()` 的 `_run_lock` 在“request 处理中发起新 request”场景下是否会造成自死锁；如需可重入则在 Task 2.2 明确改造。 |
| 3 | 🟢 Minor | 风险表「request 阻塞导致 turn 卡住」 | `request_timeout=300s` 与 `agent_query_timeout` 对齐合理，但未提及多个并发 request 同时阻塞时的资源占用上限。 | 可选补充：并发 pending 请求数上限或告警，作为可选增强的候选。 |

---

### 7. ⚖️ Proportionality — ⭐⭐⭐⭐⭐

**Summary**: 任务复杂度（新增第 22 个组件、4 类消息类型、阻塞式 request 同步链路、删除旧协议、全量回归）与计划详略高度匹配：3 个执行阶段 + Phase 0 前置验证 + 11 个 Task + 12 条风险，符合“复杂系统需多阶段与详细 AC”的预期，没有过度工程化，也没有对关键链路含糊其辞。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| — | — | — | 未发现比例失当问题。 | 保持现状。 |

---

### 8. ✅ Internal Consistency — ⭐⭐

**Summary**: 方案层面的语义高度一致（request 专用响应类型恢复、超时恢复、熔断删除、`AGENT_DELEGATE_RESPONSE` 不存在、编排场景禁用 request 等在多处反复对齐）。但代码级契约存在多处硬矛盾，使“计划内部自洽”这一维度得分很低。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | 🔴 Critical | Task 1.4 vs Task 2.1 | `send()` 返回 `str`（ABC 与实际实现）vs `_send_and_check_ack` 当作 dict 调用 `.get()`——同一计划内对同一方法返回值给出两种互斥定义（同维度 4 #1）。 | 统一返回契约并贯穿 ABC、实现、调用点与伪代码。 |
| 2 | 🟡 Major | Task 1.4 vs Task 2.1 vs 实际代码 | `get_agent` 在 ABC 是 `async def`，在实现和调用点是 sync——同一计划内三种口径（同维度 4 #2）。 | 统一为同步。 |
| 3 | 🟡 Major | 总体方案删除清单 vs engine.py 实际代码 | 计划宣称清理 `TASK_*` 全局无残留，但 engine.py 3 处引用未纳入清理范围；Task 3.3 的 grep AC 若只扫部分目录会漏检（同维度 1 #1）。 | 扩展删除清单与 grep 范围至 `broca/loop_engine/`。 |
| 4 | 🟡 Major | Task 2.4 伪代码 vs 实际 server API | `await` 缺失、参数类型错、返回值缺失，使 Task 2.4 与项目现状不自洽（同维度 2 #1）。 | 按实际 API 修正伪代码。 |
| 5 | 🟢 Minor | 概述「第 22 个组件」 vs `defaults.py` docstring | 计划要求把文件头 docstring 从“7 core components”改成“22 components”。但核验发现当前 `defaults.py` 注释写的是“7 core + 16 remaining = 23”，而 `_DEFAULT_IMPLS` 实际有 21 条；21+1=22 与计划一致，但 docstring 的“16 remaining/23”本身已过时。计划只说改成 22，未纠正“16 remaining”这句，改完仍会自相矛盾。 | 明确改为准确表述（如“22 components total, registered incrementally”），同时修正“7 + 16”这句过时注释。 |

---

## Issue Summary

| Severity | Count | Description |
|:--------:|:-----:|-------------|
| 🔴 Critical | 1 | 必须修复后才能执行（send 返回类型契约破裂） |
| 🟡 Major | 9 | 应修复以保证质量与可执行性 |
| 🟢 Minor | 9 | 建议改进 |

> 注：9 个 Major 中，部分为同一根因在不同维度的体现（返回类型、sync/async、engine.py 清理、Task 2.4 伪代码各被计入 2 个维度），实际独立根因为 **5 个**：① send 返回类型契约；② get_agent sync/async；③ engine.py 3 处 TASK_* 清理遗漏；④ Task 2.4 伪代码/回调语义；⑤ Task 2.1↔2.4 ACK 依赖顺序。

### 🔴 Critical Issues (Must Fix)

| # | Dimension | Location | Issue | Suggestion |
|:-:|:---------:|:--------:|-------|------------|
| 1 | Feasibility / Consistency | Task 1.4 `send` 声明 + Task 2.1 `_send_and_check_ack` | `send()` 返回 `str`（message_id），但 `_send_and_check_ack` 调用 `result.get("status")` → `AttributeError`，request/notify/delegate 首次通信即崩溃。 | 统一返回契约为 ACK 结果 dict（或改用独立 Future 读取 ACK），并同步 ABC、实现、调用点、伪代码与 AC。 |

### 🟡 Major Issues (Should Fix)

| # | Dimension | Location | Issue | Suggestion |
|:-:|:---------:|:--------:|-------|------------|
| 1 | Consistency/Feasibility | Task 1.4 / 2.1 / 代码 | `get_agent` ABC `async` vs 实现与调用点 sync | 统一为同步 `def`。 |
| 2 | Completeness/Consistency | 删除清单 / Task 1.1 / 2.2 | engine.py 3 处 `_cross_agent_types` TASK_* 引用未纳入迁移 | 加入删除清单与步骤，扩大 grep 范围。 |
| 3 | Clarity/Feasibility | Task 2.4 Step 2 | server 伪代码缺 `await`、参数类型错、无 `return` | 按实际 `_process_message(sid, message: Message)` 修正。 |
| 4 | Clarity/Feasibility | Task 2.4 Step 1 | `callback` 与既有 `message_callbacks` 参数同名异义 | 区分命名并说明关系。 |
| 5 | Structure | Task 2.1 vs 2.4 | 2.1 依赖 2.4 的 ACK 却排在前面、依赖未声明 | 前移 ACK 能力或调整顺序/声明依赖。 |
| 6 | AC Quality | Task 2.1 验收标准 | 缺对 `send()` 返回类型的断言，routing_failed AC 无法真验证 | 补返回值类型 AC。 |
| 7 | Risk | 风险表 | 遗漏代码契约类风险与 `run()` 锁可重入风险 | 契约问题直接修入计划；锁问题补验证项。 |
| 8 | Completeness | Phase 0 | 无显式阶段验收标准；callback 决策截止点不清 | 补验收标准与决策门槛。 |
| 9 | Consistency | defaults.py docstring | “7+16=23”过时注释与“22 components”并存 | 一并修正为准确表述。 |

### 🟢 Minor Issues (Consider)

| # | Dimension | Location | Issue | Suggestion |
|:-:|:---------:|:--------:|-------|------------|
| 1 | Clarity | Task 2.4 | server `_send_error(ROUTING_FAILED)` 与新 ACK 机制是否并存未说明 | 明确替换/并存关系。 |
| 2 | AC Quality | Task 2.4 AC4 | “等仍正常工作”偏泛 | 用具体测试文件与命令替代。 |
| 3 | AC Quality | Phase 3 AC | 缺“滞留回复被忽略、pending 无残留”断言 | 补一条 AC。 |
| 4 | Clarity | Task 2.1 `_resolve_agent_id` | sync/async 口径导致执行者无所适从 | 明确单一口径。 |
| 5 | Completeness | 未解决的问题 #1 | callback 决策阻塞 Task 2.4 却未标门槛 | 标注决策截止点。 |
| 6 | Risk | request 死锁风险 | 未验证 `_run_lock` 可重入性 | 补验证。 |
| 7 | Risk | request 阻塞风险 | 未提并发 pending 上限 | 可选补充。 |
| 8 | Structure | Task 1.1/2.2 | drain/inject 集合“删旧/加新”分散描述 | 集中到 Task 1.1。 |
| 9 | Consistency | 概述组件计数 | docstring 过时 | 见 Major #9。 |

---

## Verdict

**Overall Score**: ⭐⭐⭐ / 5（27/40 换算后约 3.4，取 3）

**Verdict**: ❌ **Needs Revision**

| Verdict | Condition | Met? |
|---------|-----------|------|
| ✅ Pass | 无 Critical，所有维度 ≥ 3 星 | ❌ 存在 1 个 Critical，且 Feasibility/Consistency 为 2 星 |
| ⚠️ Conditional Pass | 轻微 Critical 或部分维度 < 3 星 | ❌ Critical 为阻塞级（首次通信即崩溃），非轻微 |
| ❌ Needs Revision | 存在 Critical 或总体 < 3 星 | ✅ 符合 |

**Recommendation**（按优先级修订后需重新评审）:

1. **P0（阻塞）— 统一 `send()` 返回契约**：明确 ACK 结果如何从 server 传回并成为 `Communicator.send()` 的返回值；同步修改 ABC 签名、`SocketIOClient.send`、`_send_and_check_ack`、Task 2.4 伪代码与相关 AC。这是唯一会导致全线崩溃的问题，必须先定。
2. **P0 — 统一 `get_agent` 为同步**：把 Task 1.4 ABC 声明改为 `def get_agent(...)`，与实际实现（`agent_manager.py:543`）和 `_resolve_agent_id` 调用保持一致。
3. **P0 — 补全 engine.py 清理**：把 `broca/loop_engine/engine.py` 的 3 处 `_cross_agent_types`（L394/L453/L459）纳入 Task 1.1 删除清单与 Task 2.2 迁移步骤，并把 Task 3.3 的 grep 范围扩展到全 `broca/`。
4. **P1 — 修正 Task 2.4 server 伪代码与回调语义**：`await self._process_message(sid, message)` + 显式返回路由结果；区分 emit-ACK 回调与既有 `message_callbacks`；说明与 `_send_error(ROUTING_FAILED)` 的关系。
5. **P1 — 重排 Task 2.1 ↔ 2.4 依赖**：让 ACK 能力先于（或作为）`send` 契约就绪，并在依赖行显式声明。
6. **P2 — 收尾一致性**：修正 `defaults.py` 组件计数注释、补 Phase 0 验收标准、补滞留回复与锁可重入的验证断言。

**Summary**:
该计划在**架构层面质量很高**：request 复用 ask_user 同步链路、专用 `AGENT_REQUEST_RESPONSE` + `request_id` 配对 + Event 唤醒、notify/delegate 走 mid-turn 双通道、核心/可选控制机制划分、编排场景禁用 request 等设计决策清晰自洽，风险识别与测试矩阵也相当完备。**但代码级契约存在 1 个 Critical（send 返回值 str/dict 矛盾，首次通信即崩溃）与 4 个 Major 根因（get_agent sync/async、engine.py TASK_* 清理遗漏、Task 2.4 伪代码错误、ACK 依赖顺序）**，这些问题是在核验实际源码后确认的，按计划字面执行无法通过。建议按上述 P0→P2 顺序修订后重新运行 `review-plan`。
