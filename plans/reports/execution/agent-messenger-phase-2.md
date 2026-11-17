# AgentMessenger — Phase 2: 核心实现 — Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | `plans/agent-messenger-plan.md` |
| Phase | Phase 2: 核心实现 |
| Status | ✅ Pass |

## Plan Anchor Confirmation

- [x] Re-read Phase 2 section (plan L719-1346) before starting
- [x] Acceptance criteria for each task confirmed
- [x] User-approved scope extension (彻底清理 assign_task 残留 + 修复 communicate 超时) applied

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| Task 2.1: DefaultAgentMessenger 实现 | ✅ | 实现 8 方法 / request 阻塞配对超时 / reply best-effort / handle_request_response / notify·delegate ACK 快速失败 / delegate task 前置校验 / _check_permissions 仅 ACL+request 环检测 / _resolve_agent_id 同步 / 无 budget | `broca/agent_messenger/messenger.py` 全量实现（补全 Phase 1 骨架）。inline 验证：notify/delegate OK、task_id_required、task_not_found、target_not_found、routing_failed 快速失败、request_timeout、chain_cycle、request 成功配对、acl_denied；Registry 可实例化；无 budget.py | 无 |
| Task 2.2: Agent 集成 | ✅ | create() 初始化 messenger / 注册 4 handler / _handle_incoming_request 保证 reply / _handle_incoming_delegate 保证回执 / start() 三分支 / run() 无条件入链 / 5 处 drain 集合加 AGENT_NOTIFY | `broca/agent.py`：__init__ 加 self.messenger；create() 解析 AgentMessenger(per-agent)+AgentFactory+TaskManager 并 initialize、注册 agent_request/agent_notify/agent_delegate→_receive_message、agent_request_response→handle_request_response；新增两 handler；start() 加 3 分支；run() 加 call_chain 参数 + `(call_chain or CallChain()).add(agent_id)`；2 处 _drain_types 加 AGENT_NOTIFY（engine.py 3 处 Phase 1 已改）。验证：agent+socketio 测试 40 passed；inline 验证 run 顶层链含自身 id / 嵌套 [B,A] / request 正常·异常均 reply / delegate not-found·异常均单次回执 | 见 D1（TaskManager 用具体 DBTaskManager 而非 ABC） |
| Task 2.3: Communicate tool | ✅ | 无 communicate.py / Communicate 在 agent_interaction.py 且入 tool_mapping / request 映射状态 / notify·delegate 投递成功才 SUCCESS / 失败→ERROR / 配置无 assign_task | `Communicate` 实现在 `broca/tools/agent_interaction.py`；自动发现为 communicate，assign_task 不在列表。inline 全模式检查通过。彻底清理（用户批准）：Broca.md/tool_permission_config.json assign_task→communicate；executor.py `_assign_task_timeout`→`_communicate_timeout`（tool_name=="communicate"）；configs.py/configs.json `assign_task_timeout`→`communicate_timeout`；tool_manager READONLY_TOOLS 移除过期 assign_task | 见 D2（超计划范围彻底清理，用户批准） |
| Task 2.4: SocketIO ACK 端到端验证 | ✅ | send() routed/routing_failed dict / emit-callback 与 message_callbacks 不混用 / server handler 返回 _process_message dict / 三模式 routing_failed 快速失败 / socketio+agent 测试通过 / Phase0 决策落档 | 真实 aiohttp server + 真实 SocketIOClient 端到端验证：send() routed→{"status":"routed"}、routing_failed→{"status":"routing_failed","reason":"unknown_receiver"}、未知 mode 不 emit 返回 routing_failed；_process_message 返回 dict 契约（routed/unknown_receiver/unknown_sid）。结论写入计划"未解决的问题"第 1 项（主方案）。46 passed | 无 |

## Deviations

### D1 — TaskManager 具体实现 vs ABC
计划伪代码写 `task_manager=TaskManager()`，但 `broca.components.TaskManager` 是 ABC（不可实例化）。改用 `from broca.task_manager import TaskManager`（=DBTaskManager 具体实现，与 `broca/tools/task.py` 用法一致）。修复后 test_agent_composition 全部通过。

### D2 — 彻底清理 assign_task 残留 + 修复超时缺口（用户批准）
计划 Task 2.3 仅要求改 agent_interaction.py + agent tools 列表。执行中发现：
1. 配置/管道残留 `assign_task`：`configs/agents/Broca.md`、`configs/tool_permission_config.json`、`configs/configs.json`、`broca/configs.py`、`broca/tools/executor.py`、`broca/tools/tool_manager.py`。
2. **功能缺口**：`communicate` request 模式内部阻塞最长 `request_timeout`(默认300s)，但 executor 外层工具超时默认仅 120s → 长请求被提前杀掉。

经 ask_user 确认选择"彻底清理+修复超时"：将 `assign_task_timeout` 全链路改名为 `communicate_timeout`（executor `_get_timeout("communicate")` 返回 1800s 专用超时），移除 READONLY_TOOLS 过期项，配置文件 assign_task→communicate。生产+配置已无 assign_task 残留（grep 验证）。

## Quality Checklist

- [x] All phase-level ACs satisfied
- [x] All task-level ACs satisfied
- [x] No missing tasks (4 tasks cross-referenced against plan)
- [x] No extra functionality beyond plan + user-approved cleanup
- [x] Manually verified key behaviors (messenger 8 方法、handlers 三路径、run 入链、Communicate 全模式、真实 E2E ACK)
- [x] Code follows project conventions
- [x] Compatible with existing work (1705 passed)

## Test Results

| 范围 | 结果 |
|------|------|
| 全量 `--co` 收集 | 1726/1727 collected, 0 errors |
| 全量 pytest | **1705 passed, 19 failed, 2 skipped** |
| test_agent* + test_socketio_client_connect + test_server_client_id_routing | 46 passed |
| test_readonly_tools_and_snapshot_lock | 16 passed |

### 19 失败全部为测试文件引用已删除/改名的 assign_task / TASK_*（生产代码无回归）

**计划内延后（13，5 文件，Task 3.3 更新）：**
- test_communicator_abc.py::test_abstract_method_count (1)
- test_handle_task_assigner_defense.py (6)
- test_llm.py::test_parse_task_* (3)
- test_non_blocking_mode.py::test_selective_drain (1)
- test_save_user_message_no_mutation.py::test_task_* (2)

**超出计划的额外测试文件（6，3 文件，同样归 Task 3.3）：**
- test_tool_bugfixes.py::TestAssignTaskUnboundLocalError (3) — 测试 Phase 1 已删除的 AssignTask 工具
- test_tool_execution_behavior.py::TestDedicatedTimeout::test_assign_task_uses_dedicated_timeout (1) — 引用 assign_task 专用超时
- test_tool_executor.py::TestDedicatedTimeout::test_assign_task_gets_longer_timeout (1) + TestDelegationAndInit::test_initialize_reads_config (1) — 引用 `_assign_task_timeout`/`assign_task_timeout`

> 说明：Phase 2 不以全量 pytest 通过为硬门槛（计划明确）。上述失败均为测试引用旧 assign_task/TASK_* 符号，需在 Task 3.3 统一更新（原计划 5 文件，现因彻底清理增至约 8 文件）。生产代码全部 import OK、无回归。

## 待后续（Task 3.3）注意

- 需更新的测试文件由计划 5 个增至约 8 个（新增 test_tool_bugfixes、test_tool_execution_behavior、test_tool_executor），因 assign_task_timeout→communicate_timeout 改名。
