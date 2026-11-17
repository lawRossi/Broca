# AgentMessenger — Phase 3: 测试 + 收尾 — Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | `plans/agent-messenger-plan.md` |
| Phase | Phase 3: 测试 + 收尾 |
| Status | ✅ Pass |

## Plan Anchor Confirmation

- [x] Re-read the Phase 3 section of the plan before starting (L1347–1475)
- [x] Acceptance criteria for each task confirmed
- [x] Applied user constraint "可选增强不用做"（无 Budget、无 enable_chain_detection 两态测试）——Task 3.1/3.2 ACs 据此裁剪

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| Task 3.1: 控制原语单元测试 | ✅ | call_chain / audit 单测通过；tmp_path 隔离；无 budget | 新增 `test_agent_messenger_call_chain.py`（19）+ `test_agent_messenger_audit.py`（10），29 passed。覆盖 cycle/depth/add 不可变/序列化往返、JSONL 写入/追加/全字段/空 workspace 静默 | 无 |
| Task 3.2: AgentMessenger 集成测试 | ✅ | 全流程 + 核心机制 + 回复保障 + routing_failed + 链入链 | 新增 `test_agent_messenger_core.py`（45 passed）。见下"覆盖矩阵" | **D3 生产 bug 修复**（见 Deviations） |
| Task 3.3: 全量回归 + 文档 | ✅ | 全量 pytest 通过；grep 无残留；engine cross types=AGENT_NOTIFY；communicate 配置 | 全量 **1786 passed / 2 skipped / 1 deselected**；修复 8 个受影响测试文件；AgentConfig docstring 更新 | 无 |

## 覆盖矩阵（Task 3.2）

- request：同步阻塞（回复前不返回）、request_id 并发配对（逆序回复不串扰）、reply 走专用 `handle_request_response` 直接唤醒（不入队列）、status 映射
- request 超时（0.05s 抛 `request_timeout`）+ pending 清理；滞留回复静默忽略；无 request_id 忽略
- request 环检测（`chain_cycle` 投递前拦截）+ 深度超限 + ACL（targets / modes）
- A↔B 互 request **首跳**即 `chain_cycle` 被拒（不靠超时兜底）
- 三模式 routing_failed 快速失败（messenger 抛错 + Communicate tool → ERROR；delegate 不误报 SUCCESS）
- notify 投递（mode=notify → AGENT_NOTIFY 映射）+ ACL
- delegate：成功（不等回执等 ACK）、task_id_required、task_not_found、ACL
- `_handle_incoming_request` 正常/异常/abort 三路径 reply 保障
- `_handle_incoming_delegate` 正常/task-not-found/异常/abort 四路径回执保障（`kind=delegate_receipt`）
- Communicate tool：request/notify/delegate/未知模式/messenger=None/routing_failed 全映射
- Agent.run 顶层（call_chain=None）自身入链；inbound 链扩展
- mid-turn drain：`_make_message_source().drain()` 与 `_drain_user_messages` 均取 AGENT_NOTIFY；`_receive_message` 入队
- 全局不变量：无 `AGENT_DELEGATE_RESPONSE`；`AGENT_REQUEST_RESPONSE` 存在；send-type map 无 delegate-response

## Deviations

### D3 — 生产 bug 修复：`handle_request_response` 读取 `message.content`

- **What**：`DefaultAgentMessenger.handle_request_response` 原实现 `pending.reply = message.content`。
- **Why**：`Message`（pydantic 模型）没有 `content` 字段——内容存于 `message.data["content"]`（`Message(content=...)` 的 kwarg 被 pydantic `extra="ignore"` 静默丢弃）。真实收包路径下 `message.content` 抛 `AttributeError`，导致 request **永远收不到回复**（只能靠超时结束）。Phase 2 的内联验证用了带 `.content` 的伪消息，未覆盖真实 `Message`。
- **Fix**：改为 `pending.reply = (message.data or {}).get("content", "")`。
- **Regression**：`test_agent_messenger_core.py::TestRequest` 全组（构造真实 `Message`，content 放 data）即回归测试。
- **Impact**：修复核心 request 回复通路；属必要的正确性修复，不影响对外接口。

## Quality Checklist

- [x] All phase-level ACs satisfied（可选增强两态 AC 按用户约束跳过）
- [x] All task-level ACs satisfied
- [x] No missing tasks（Phase 3 = Task 3.1/3.2/3.3，均已建并完成）
- [x] No extra functionality（无 budget.py、无 enable_chain_detection）
- [x] Manually verified key behaviors（request 阻塞/唤醒/超时/环检测/回复保障/delegate 回执）
- [x] Code follows project conventions
- [x] Compatible with existing work（全量 1786 passed）

## Grep 收尾

```
grep -rn "assign_task|task_start|task_complete|task_error|TASK_START|TASK_COMPLETE|TASK_ERROR|send_task_|_handle_task|create_task_" broca/ --include=*.py --exclude-dir=alembic
```
仅剩 `broca/tests/orchestration/test_graph_model.py::test_create_task_node` —— 图编排 `NodeType.TASK` 节点测试，与消息协议无关的**良性误报**。

`broca/loop_engine/engine.py` 3 处 `_cross_agent_types` 均为 `MessageType.AGENT_NOTIFY`。

配置：`configs/configs.json` `communicate_timeout=1800`；`configs/tool_permission_config.json` `"communicate": "allow"`；`configs/agents/Broca.md` tools 含 `communicate`。

## Test Files Updated (Task 3.3)

| 文件 | 处理 |
|------|------|
| test_communicator_abc.py | ABC 抽象集移除 send_task_start/complete/error，加入 send |
| test_llm.py | 删除 test_parse_task_start/complete/error |
| test_handle_task_assigner_defense.py | 整文件删除（针对已删 _handle_task/send_task_*） |
| test_save_user_message_no_mutation.py | TASK_COMPLETE/ERROR → AGENT_NOTIFY（含 delegate_receipt 变体） |
| test_non_blocking_mode.py | create_task_start → AGENT_REQUEST（非 drain 类型） |
| test_tool_bugfixes.py | 删除 TestAssignTaskUnboundLocalError（AssignTask 已删） |
| test_tool_execution_behavior.py | assign_task_timeout → communicate_timeout，assign_task → communicate |
| test_tool_executor.py | assign_task_timeout/_assign_task_timeout → communicate_timeout/_communicate_timeout |

## Final Test Result

```
pytest broca/tests/  →  1786 passed, 2 skipped, 1 deselected (122s)
新增测试：test_agent_messenger_call_chain.py(19) + test_agent_messenger_audit.py(10) + test_agent_messenger_core.py(45) = 74 passed
```
