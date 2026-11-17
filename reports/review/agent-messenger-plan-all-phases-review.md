# AgentMessenger — 全阶段（Phase 1/2/3）执行质量评审报告

## Overview

| Item | Content |
|------|---------|
| Plan File | `plans/agent-messenger-plan.md` |
| Review Scope | Phase 1（基础设施）+ Phase 2（核心实现）+ Phase 3（测试 + 收尾） |
| Execution Reports | `plans/reports/execution/agent-messenger-phase-{1,2,3}.md` |
| Test Files (AC 派生) | `broca/tests/test_agent_messenger_{call_chain,audit,core}.py`（已存在，74 tests） |
| Review Date | 2026-11-16 |
| Review Method | 运行 AC 派生测试 + 工作区直接取证（不依赖执行报告自述） |

### Dimension Scores

| # | Dimension | Score | Key Finding |
|:-:|-----------|:-----:|-------------|
| 1 | 📌 Plan Anchoring | ⭐⭐⭐⭐ | 核心机制严格锚定计划；但「跳过 Budget + 可选增强」是重大范围裁减，仅记录在执行报告，**计划正文/附录从未修订**，AC 基线仍写着这些机制 |
| 2 | 🎯 AC Achievement Rate | ⭐⭐⭐ | 核心 AC（request/notify/delegate/ACL/task 校验/回复保障/超时/首跳环检测/routing_failed/旧代码删除）全部达标；但计划中约 10 条 Budget/可选增强 AC 按报告「用户要求」未实现，计划文本层面未达标 |
| 3 | 📦 Completeness | ⭐⭐⭐⭐ | 核心交付物齐全（agent_messenger 包、4 个 handler、Communicate、ACK 通路、配置迁移、3 个测试文件）；`budget.py`/budget 测试/可选开关按范围裁减缺失 |
| 4 | ✅ Correctness | ⭐⭐⭐⭐⭐ | 实现符合计划技术路线且更严谨：修正了计划伪代码 D3 bug（`message.content` → `message.data["content"]`）；全部全局不变量实测成立 |
| 5 | 🧪 Test Quality | ⭐⭐⭐⭐ | 74 tests 全绿、覆盖核心拒绝路径；但缺 3 项 AC 对应测试：`AgentCommunication` 往返、SocketIO `send()` E2E ACK、审计 200 字符截断 |
| 6 | 🔗 Integration Quality | ⭐⭐⭐⭐⭐ | 全量回归 1786 passed / 2 skipped / 1 deselected；5 处 drain、Registry 实例化、dispatch table 实测正确，无回归 |
| 7 | 📋 Report & Deviation Handling | ⭐⭐⭐ | 执行报告对 D1/D2/D3 记录详尽诚实；但最大偏离（砍掉 Budget/可选增强）无计划侧批准记录，且「Task 2.4 E2E 46 passed」缺少落地测试佐证 |
| | **Overall** | **⭐⭐⭐⭐ (≈3.9)** | 核心功能与回归质量优秀；主要短板是范围裁减的计划侧可追溯性 + 少数 AC 测试缺口 |

---

## AC Verification

### Phase 0 — 前置验证

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | emit callback / server handler 返回值作为 ACK 结论落档 | ✅ | 计划「未解决的问题」第 1 项已记录「采用主方案（python-socketio 5.18.1）」；端到端通路在 `socketio_client.py`/`socketio_server.py` 实现完整 |

### Phase 1 — 基础设施

**阶段级 AC：**

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | `AgentMessenger` ABC 定义 + 注册 `ComponentRegistry` | ✅ | `broca/components/agent_messenger.py` 定义 8 抽象方法（实测 `__abstractmethods__` 齐全）；`defaults.py` 注册（L74/110/134/165）；`ComponentRegistry.get_instance().get(AgentMessenger, scope_key=...)` 实测返回 `DefaultAgentMessenger` |
| 2 | CallChain / CommunicationPolicy / **CommunicationBudget** / AuditLogger 4 原语 | ⚠️ | 3 个已实现；**CommunicationBudget 未实现**（无 `budget.py`），报告称「用户要求可选增强不用做」，计划未修订记录 |
| 3 | MessageType 新增 4 值 / 删除 TASK_* 3 值 | ✅ | `models.py` L78-81 有 4 个 `AGENT_*`；实测 `TASK_START` 不存在、`AGENT_DELEGATE_RESPONSE` 不存在 |
| 4 | AssignTask / create_task_* / _handle_task 删除 | ✅ | 生产代码 grep 无残留（排除 alembic/tests）；`MessageProtocol.create_task_*` 已删 |
| 5 | Communicator ABC `send_task_*` 删除 | ✅ | `communicator.py` 用 `send() -> dict` 替代；grep 无 `send_task_*` |
| 6 | engine.py 3 处 / llm.py 3 处 / agent.py 2 处 TASK 引用清理 | ✅ | `engine.py` L394/453/459 均为 `AGENT_NOTIFY`；llm.py/agent.py grep 无 TASK_* |
| 7 | 生产代码无引用断裂（grep） | ✅ | 实测 grep（`--exclude-dir=alembic`，排除 tests）无结果 |
| 8 | 5 个受影响测试文件延后至 Task 3.3 更新 | ✅ | Phase 3 报告确认已更新，全量回归通过 |

#### Task 1.1 — AgentMessenger ABC + 消息模型 + 删旧代码

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | ABC 8 抽象方法 | ✅ | 实测 `AgentMessenger.__abstractmethods__` = 8 个（initialize/request/notify/delegate/reply/handle_request_response/set_call_chain/reset_budget） |
| 2 | 4 个 AGENT_* 可导入、无 AGENT_DELEGATE_RESPONSE | ✅ | 实测 hasattr 验证 |
| 3 | 无 AgentRequestResponse dataclass | ✅ | `message_models.py` 仅 `AgentCommunication` |
| 4 | `AgentCommunication` to_dict/from_message_data 往返保留 kind/task_id/request_id/status | ⚠️ | **手动实测通过**（`task_id=T1`/`kind=delegate_receipt`/`status=error` 均往返保留），但**无自动化测试用例**专门断言 `AgentCommunication` 往返（core 测试仅 import 该类用于构造 handler 入参） |
| 5 | TASK_* 枚举/create_task_* 删除 | ✅ | 见阶段 AC 3/4 |
| 6 | AssignTask / _handle_task 删除 | ✅ | 见阶段 AC 4 |
| 7 | start() 处理 5 类消息、AGENT_NOTIFY 进 drain | ✅ | `agent.py` L695-709 分支正确 |
| 8 | engine.py / llm.py 无 TASK 残留 | ✅ | grep 验证 |
| 9 | 生产代码 grep 无残留 | ✅ | 验证 |
| 10 | `from broca.components.agent_messenger import AgentMessenger` 成功 | ✅ | 实测导入成功 |
| — | **AC Rate**: 9/10 完整达标 + 1 项手动验证通过 | | |

#### Task 1.2 — CallChain + CommunicationPolicy

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | `would_create_cycle` 三例 | ✅ | `test_agent_messenger_call_chain.py`（19 tests 覆盖空/单/多节点） |
| 2 | `is_within_depth(3)` 边界 | ✅ | 同上（`TestIsWithinDepth`） |
| 3 | **两个开关 enable_chain_detection / enable_budget 默认 False** | ❌ | `CommunicationPolicy` 字段实测仅 `[allowed_targets, allowed_modes, request_timeout, max_chain_depth]`——两开关字段按报告被删除。计划文本 AC 未达标（范围裁减） |
| 4 | 无熔断字段、有 request_timeout=300 | ✅ | 实测字段列表无 `enable_circuit_breaker`，`request_timeout=300.0` |
| 5 | max_chain_depth == 3 | ✅ | 实测 |
| 6 | from_config 解析 enable_budget=True 等 | ⚠️ | `_parse_communication_policy` 用 `fields` 白名单过滤未知键，`enable_budget` 被忽略而非「解析为 True」——按范围裁减行为合理，但计划 AC 字面未达标 |
| — | **AC Rate**: 4/6（2 项因范围裁减未达标） | | |

#### Task 1.3 — AuditLogger（Budget 按范围裁减）

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | Budget: consume("request") 3 次后 False | ❌ | 无 `budget.py`（范围裁减） |
| 2 | Budget: consume("delegate") 3 次后 False | ❌ | 同上 |
| 3 | Budget: reset() 后可消费 | ❌ | 同上 |
| 4 | circuit_breaker.py 不存在 | ✅ | 实测不存在 |
| 5 | AuditLogger log 生成 JSONL | ✅ | `test_agent_messenger_audit.py`（10 tests） |
| — | **AC Rate**: 2/5（3 项 Budget AC 因范围裁减未达标） | | |

#### Task 1.4 — 注册 + Communicator 扩展 + ACK 通路

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | `from broca.components import AgentMessenger` | ✅ | 实测导入成功 |
| 2 | `ComponentRegistry.get(AgentMessenger, scope_key="test")` 返回实例 | ✅ | 实测返回 `DefaultAgentMessenger` |
| 3 | AgentFactory ABC 同步 `get_agent()`，全文无 `await ...get_agent` | ✅ | `agent_factory.py` + `_resolve_agent_id` 同步调用 |
| 4 | defaults.py docstring 无过时 7/16 表述 | ✅ | L9「21 existing + AgentMessenger = 22」、L46/110「22 total」 |
| 5 | test_components_registry.py 全量通过 | ✅ | Phase 1 报告 27 passed（本次全量回归亦含） |
| 6 | Communicator.send / SocketIOClient.send 返回 dict | ✅ | `communicator.py`、`socketio_client.py` L454 签名 `-> dict` |
| 7 | send() 构造 Message，mode→AGENT_* 映射 | ✅ | `_SEND_TYPE_BY_MODE` L448-451 四条映射正确 |
| 8 | Communicator/SocketIOClient 无 reply 方法 | ✅ | grep 无独立 reply |
| 9 | `_send_message_with_ack` 独立 ack_fn+Future，不混用 message_callbacks | ✅ | 代码实现符合；超时返回 `routing_failed/ack_timeout` |
| 10 | server handler `return await _process_message`；`_send_error` 保留 | ✅ | `socketio_server.py` L314、L432-457 实测 |
| 11 | dispatch table 无 TASK_*、含 4 AGENT_*、request_response→专用 handler | ✅ | `socketio_client.py` L55-58 + `agent.py` L177 |
| 12 | CrewOrchestratorRunner 无 send_task_*，迁移 delegate | ✅ | `orchestrator_runner.py` 仅 L43 注释提及，无调用 |
| — | **AC Rate**: 12/12 | | |

### Phase 2 — 核心实现

**阶段级 AC：** 全部核心项达标；「可选增强两态」相关项因范围裁减未达标（详见维度 2）。`_run_lock` 自死锁防护经 Task 3.2 首跳环检测测试覆盖。

#### Task 2.1 — DefaultAgentMessenger 实现

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | send() 按 dict 契约、无对 str 调 .get() | ✅ | `_send_and_check_ack` 对 dict 调 `.get("status")`；无 `send_message()` 误用 |
| 2 | `_resolve_agent_id` 同步、无 await | ✅ | 实测代码 |
| 3 | request() 阻塞 wait_for、返回 (文本,状态) | ✅ | `test_request_blocks_until_reply` / `test_request_status_maps_from_reply` |
| 4 | request() 调 `_budget.consume("request")` | ❌ | 无 budget（范围裁减） |
| 5 | pending+Lock、handle_request_response 配对唤醒、finally 清理、审计 final_result | ✅ | `TestRequest*` / `TestRequestTimeoutAndLateReply`（含 late reply 忽略） |
| 6 | 超时抛 request_timeout | ✅ | `test_request_timeout_raises_and_cleans_pending` |
| 7 | reply() 发 request_reply、best-effort 不抛错 | ✅ | 代码 + `TestRequestReplyGuarantee` |
| 8 | notify() 等 ACK、routing_failed 抛错、delegate_receipt kind | ✅ | `TestNotify` / `TestRoutingFailed` |
| 9 | delegate() task 前置校验 + 等 ACK + routing_failed 抛错 | ✅ | `TestDelegate` / `test_delegate_routing_failed_fast` |
| 10 | request 强制环检测始终生效、无 force_chain_check 死参数 | ✅ | `_check_permissions` 实测；`TestRequestCycleAndACL` |
| 11 | 全部 reason 值 | ✅ | 代码实现齐全（task_id_required/task_not_found/target_not_found/acl_denied/chain_cycle/chain_depth_exceeded/request_timeout/routing_failed） |
| 12 | initialize config 为 AgentConfig、显式取 communication_policy | ✅ | `messenger.py` L72-94 |
| 13 | target_not_found | ✅ | `_resolve_agent_id` 实测 |
| 14 | 8 抽象方法全实现、可 Registry 实例化 | ✅ | 实测 |
| 15 | notify/delegate 只解析一次 target_id | ✅ | 代码实测 |
| 16 | reply best-effort 审计 routing_failed | ✅ | 代码实测 |
| 17 | 首跳环检测（run 入链含自身） | ✅ | `test_a_to_b_mutual_request_rejected_first_hop` / `TestRunChainEntry` |
| — | **AC Rate**: 16/17（1 项 Budget 因范围裁减） | | |

#### Task 2.2 — Agent 集成

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | create() 初始化 messenger + 注入 agent_factory | ✅ | `agent.py` L161-171 实测 |
| 2 | request_response→专用 handler、无 _on_agent_reply | ✅ | `agent.py` L177 |
| 3 | _handle_incoming_request try/finally reply 三路径 | ✅ | `TestRequestReplyGuarantee`（normal/error/abort/exception） |
| 4 | AGENT_REQUEST_RESPONSE 不进 queue/drain | ✅ | `TestRequestReplyGuarantee` + `TestGlobalInvariants`；drain 集合实测无该类型 |
| 5 | _handle_incoming_delegate 回执、三路径 | ✅ | `TestDelegateReceiptGuarantee`（normal/not-found/exception/abort） |
| 6 | AGENT_NOTIFY 进入全部 5 处跨 agent 识别 | ✅ | `agent.py` L625/655 + `engine.py` L394/453/459 实测 |
| 7 | AGENT_NOTIFY 忙时 mid-turn / 空闲新 turn | ✅ | `TestMidTurnDrain` / `TestReceiveMessageEnqueues` |
| 8 | context.py 无改动、run() 重置 budget+更新 chain | ✅ | 代码实测；`TestRunChainEntry` |
| 9 | run() 无条件把自身 id 入链（无 if call_chain 守卫） | ✅ | `agent.py` L773-774 `(call_chain or CallChain()).add(self.agent_id)` |
| 10 | 现有 test_agent.py 全量通过 | ✅ | 全量回归通过 |
| — | **AC Rate**: 10/10 | | |

#### Task 2.3 — Communicate tool

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | communicate.py 不存在 | ✅ | 实测不存在 |
| 2 | Communicate 定义在 agent_interaction.py、入 tool_mapping | ✅ | `agent_interaction.py` L216；配置 Broca.md 含 communicate |
| 3 | request 映射 (文本,状态)→ToolResult，error/aborted→ERROR+[status] | ✅ | `TestCommunicateTool`（success/error status 映射） |
| 4 | notify 投递成功才 SUCCESS、不等回执 | ✅ | `test_notify_success_maps_success` |
| 5 | delegate 投递成功才 SUCCESS、立即返回不等回执 | ✅ | `test_delegate_success_maps_success` |
| 6 | delegate 缺 task_id/task 不存在/routing_failed/超时→ERROR | ✅ | `test_routing_failed_maps_error` / `test_delegate_routing_failed_not_false_success` |
| 7 | 配置无 assign_task | ✅ | grep configs 无残留 |
| — | **AC Rate**: 7/7 | | |

#### Task 2.4 — SocketIO ACK 端到端验证

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | 路由成功→routed、失败→routing_failed dict | ⚠️ | 生产代码契约正确（`_send_message_with_ack` + server `return dict`）；但**无已提交的自动化测试**直接调用真实 `SocketIOClient.send()` 断言 dict——执行报告所述「46 passed」来自既有 socketio/agent 测试，未见新增 E2E 测试文件 |
| 2 | emit callback 与 message_callbacks 两套机制互不干扰 | ✅ | 代码实现独立（ack_fn + 独立 Future） |
| 3 | server handler return _process_message、async→dict | ✅ | 代码实测 |
| 4 | 路由失败三模式快速失败 + 审计 | ✅ | `TestRoutingFailed`（3 tests，用 mock communicator 返回 routing_failed 验证 messenger 层）；真实 server 侧未见落地测试 |
| 5 | test_socketio*.py + test_agent.py 全通过 | ✅ | 全量回归通过 |
| 6 | Phase 0 决策落档 | ✅ | 见 Phase 0 |
| — | **AC Rate**: 5/6 完整 + 1 项生产代码正确但测试佐证不足 | | |

### Phase 3 — 测试 + 收尾

#### Task 3.1 — 控制原语单元测试

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | call_chain / budget / audit 3 个测试文件 | ⚠️ | call_chain(19) + audit(10) 存在且通过；**budget 测试文件不存在**（范围裁减，文件头已注明） |
| 2 | 使用 tmp_path 隔离 | ✅ | `test_agent_messenger_audit.py` 用 `tmp_path`；`_isolate_home` 为 conftest autouse fixture 全局生效 |
| 3 | 审计 200 字符截断测试 | ⚠️ | 生产代码在 messenger 侧 `message[:200]` 已截断，但 `test_agent_messenger_audit.py` 无专门截断断言 |
| — | **AC Rate**: 2/3 完整 + 1 部分 | | |

#### Task 3.2 — AgentMessenger 集成测试

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | 全部测试通过 | ✅ | 45 passed |
| 2 | request 同步语义（阻塞/配对/超时/唤醒） | ✅ | `TestRequest` / `TestRequestTimeoutAndLateReply` |
| 3 | request 回复走专用事件、不进队列 | ✅ | `test_request_reply_not_enqueued_directly_consumed` |
| 4 | request 回复保障三路径 | ✅ | `TestRequestReplyGuarantee` |
| 5 | request 环检测（核心）+ 超时 | ✅ | `TestRequestCycleAndACL` |
| 6 | 顶层自身入链、A↔B 首跳拒绝 | ✅ | `TestRunChainEntry` / `test_a_to_b_mutual_request_rejected_first_hop` |
| 7 | notify 两消费路径 | ✅ | `TestMidTurnDrain` / `TestReceiveMessageEnqueues` |
| 8 | **环检测开关打开约束 notify/delegate；默认不拦截** | ❌ | 无开关、无对应测试（范围裁减） |
| 9 | **预算默认不拦截、打开时拒绝** | ❌ | 无 budget、无对应测试（范围裁减） |
| 10 | delegate 强制回执四路径 + 等 ACK 不等回执 | ✅ | `TestDelegateReceiptGuarantee` / `TestDelegate` |
| 11 | 三模式 routing_failed 快速失败 + tool ERROR | ✅ | `TestRoutingFailed` / `TestCommunicateTool` |
| 12 | 无 AGENT_DELEGATE_RESPONSE、REQUEST_RESPONSE 存在 | ✅ | `TestGlobalInvariants` |
| 13 | 使用 _isolate_home | ✅ | conftest autouse（隐式全局生效） |
| — | **AC Rate**: 11/13（2 项可选增强因范围裁减） | | |

#### Task 3.3 — 全量回归 + 文档

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | 全量 pytest 通过 | ✅ | 本次实测 `1786 passed, 2 skipped, 1 deselected in 148s`（执行报告称 122s/1786 passed，量级一致） |
| 2 | grep 无旧引用残留 | ✅ | 实测 prod grep 无结果；仅 `test_graph_model.py::test_create_task_node` 为良性误报（与消息协议无关） |
| 3 | engine.py 3 处 cross types 均 AGENT_NOTIFY | ✅ | L394/453/459 实测 |
| 4 | 配置使用 communicate | ✅ | configs.json `communicate_timeout=1800`、tool_permission_config.json `"communicate": "allow"`、Broca.md tools 含 communicate |
| — | **AC Rate**: 4/4 | | |

---

## Test Results

### AgentMessenger AC 派生测试（本次新运行）
```
venv/bin/python -m pytest \
  broca/tests/test_agent_messenger_call_chain.py \
  broca/tests/test_agent_messenger_audit.py \
  broca/tests/test_agent_messenger_core.py --tb=short -q
→ 74 passed in 7.14s (call_chain 19 + audit 10 + core 45)
```

### 全量回归（本次新运行）
```
venv/bin/python -m pytest broca/tests/ -q
→ 1786 passed, 2 skipped, 1 deselected in 148.02s
```
> 注：计划 AC 中的 `--timeout=120` 依赖 pytest-timeout，本环境未安装，去掉该 flag 后全量通过；结果无失败。执行报告自述值（1786 passed）与本次实测完全一致。

---

## Issues Found

### 🔴 Critical (must fix)
| # | Task | Dimension | Issue | Suggestion |
|:-:|:----:|:---------:|-------|------------|
| — | — | — | 无 Critical 问题 | — |

### 🟡 Medium (should fix)
| # | Task | Dimension | Issue | Suggestion |
|:-:|:----:|:---------:|-------|------------|
| 1 | Phase 1/2/3（跨阶段） | 📌 Plan Anchoring / 📋 Deviation Handling | **最大范围裁减（彻底删除 CommunicationBudget + enable_budget/enable_chain_detection 两个开关 + 可选环检测/预算机制）仅在 3 份执行报告的 Deviation 段落自述为「用户要求/用户批准」，计划正文与变更历史附录从未修订**。计划仍保留约 10 条相关 AC（Phase 1 阶段 AC、Task 1.2 开关、Task 1.3 Budget、Task 2.1 consume、Task 3.1 budget 测试、Task 3.2 两态测试），导致「计划 AC 基线」与「实际执行」永久错位。虽前 3 轮 plan review 的修订都能写入附录，此次裁减却无计划侧痕迹。 | 在计划「变更历史」附录补一条修订记录：注明「用户要求可选增强本期不做」、裁减的具体 AC 清单与批准时间/上下文；或在计划正文将这些 AC 标注为「已按用户决定移出本期范围」。使 AC 基线可追溯、评审可复核。 |
| 2 | Task 2.4 | 🧪 Test Quality / 📋 Report Honesty | 计划核心 AC「路由成功/失败 send() 返回 dict 的**端到端**验证」缺少落地自动化测试。执行报告称「真实 aiohttp server + 真实 SocketIOClient 端到端验证……46 passed」，但仓库中未找到调用真实 `SocketIOClient.send()` 并断言 routed/routing_failed 的测试文件；46 passed 实为既有 socketio/agent 测试。核心 ACK 通路仅生产代码正确，无回归保护。 | 新增一个使用真实 aiohttp + SocketIO server/client 的 E2E 测试（或明确记录该验证为一次性手动脚本及其命令/输出），确保 ACK 主方案有可重跑的回归断言。 |
| 3 | Task 1.1 / 3.1 | 🧪 Test Quality | 计划 AC 明确要求 `AgentCommunication.to_dict()/from_message_data()` 往返保留 `kind/task_id/request_id/status`，但无专门自动化测试（本次评审手动验证通过）。审计 200 字符截断 AC 同样无专门测试（截断在 messenger 侧实现，审计测试未覆盖）。 | 在 `test_agent_messenger_core.py`/`test_agent_messenger_audit.py` 各补 1 个针对性测试，闭合这两条 AC 的 AC⇔Test 双射。 |

### 🟢 Minor (reference)
| # | Task | Dimension | Issue | Suggestion |
|:-:|:----:|:---------:|-------|------------|
| 1 | Task 2.1 | ✅ Correctness | `_check_task_exists` 在 `task_manager is None` 时「cannot pre-check; allow (best-effort)」。生产路径 `agent.py` 恒传 `TaskManager()`，行为正确；但单元测试中未传 task_manager 时 delegate 会跳过存在性校验，与「task 必填+必存在」硬约束的严格语义有细微出入。 | 在测试中始终注入 FakeTaskManager（现已如此）；可考虑无 task_manager 时拒绝而非放行。 |
| 2 | Task 3.3 | 📋 Report Honesty | 执行报告称全量测试 122s，本次实测 148s；结果一致（1786 passed），仅耗时差异。 | 无行动项，环境差异。 |
| 3 | Task 2.3（D2 偏离） | 📌 Plan Anchoring | `assign_task_timeout` → `communicate_timeout`（1800s）改名与超时值调整超出计划 Task 2.3 字面范围，执行报告称经 ask_user 批准，但同样无计划侧记录。 | 与 Medium #1 一并补入计划变更历史。 |

---

## Conclusion

**AC Achievement Rate**：核心机制层面约 **95%**（74 个 AC 派生测试全绿、全量回归 1786 passed、核心拒绝/保障/配对路径覆盖完整）；**按计划文本逐条计约 85%**——差距集中在被范围裁减的 Budget/可选增强 AC（Task 1.2×2、1.3×3、2.1×1、3.1×1、3.2×2）及 2 项测试佐证不足（Task 1.1 往返、2.4 E2E）。

**Overall**: ⚠️ **Conditional Pass（条件通过）**

核心实现质量高：request 同步链路、request_id 配对/超时/滞留回复、首跳环检测、reply/delegate 回执保障、三模式 routing_failed 快速失败、旧代码彻底删除、全量回归零回归——均实测达标且测试充分。D3 生产 bug 的主动修复体现了实现质量高于计划伪代码。

**未给予无条件通过的原因**并非功能缺陷，而是**可追溯性与测试闭合度**：最大范围裁减（砍掉 Budget/可选增强）只在执行报告自述、未写入计划；两条计划 AC 的测试（AgentCommunication 往返、SocketIO send() E2E）缺失或仅有手动验证。

**Next Step**（按优先级）：
1. 将「可选增强范围裁减 + communicate_timeout 改名」补录到计划变更历史附录，明确批准来源，恢复 AC 基线可追溯性（对应 Medium #1/#3）。
2. 补一条真实 SocketIO server/client 的 `send()` ACK E2E 测试，闭合 Task 2.4 主方案回归保护（Medium #2）。
3. 补 `AgentCommunication` 往返 + 审计截断两个针对性测试（Medium #3）。
4. 以上完成后可将结论升级为 ✅ Pass。
