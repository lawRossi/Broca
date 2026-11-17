# AgentMessenger — Phase 1: 基础设施 — Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | `plans/agent-messenger-plan.md` |
| Phase | Phase 1: 基础设施 |
| Status | ✅ Pass（含 1 处已记录偏离，见「Deviations」） |

## Plan Anchor Confirmation

- [x] 执行前重读计划 Phase 1 及 Task 1.1–1.4 章节
- [x] 用户约束已落实：**可选增强不用做（更激进：连相关配置字段也删掉）** —— 跳过 CommunicationBudget、跳过 notify/delegate 可选环检测；`CommunicationPolicy` 不含 `enable_chain_detection` / `enable_budget` / `max_*_per_turn`；保留全部核心必选机制（ACL / task 校验 / 回复保障 / request 超时 / request 强制环检测 / AuditLogger）
- [x] Phase 0 结论：python-socketio **5.18.1**，`emit(event, data, callback=fn)` 支持、server handler 返回值作为 ACK → **主方案可行**；`TaskManager.get_task` 为 `async def`（`await` 正确）；`CrewOrchestratorRunner` 无 `send_task_*` 调用（迁移为 no-op）

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| Task 1.1: AgentMessenger ABC + 消息模型 + 旧代码删除 | ✅ | 8 抽象方法、枚举增删、AgentCommunication 往返、无残留 grep、模块导入 | 全部满足。`AgentMessenger`（BaseComponent+ABC）8 抽象方法；`MessageType` 增 `AGENT_REQUEST/REQUEST_RESPONSE/NOTIFY/DELEGATE`、删 `TASK_*` 3 值；删 `MessageProtocol.create_task_*`；删 `AssignTask`；agent.py 删 `_handle_task`/start TASK 分支/drain TASK 引用/3 个 task_* handler；engine.py 3 处 `_cross_agent_types`→`AGENT_NOTIFY`；llm.py 3 TASK 分支→`AGENT_NOTIFY` 解析分支；communicator ABC + socketio_client 删 `send_task_*`/TASK 派发/装饰器 | 无（llm.py 的 AGENT_NOTIFY 解析分支为「按需补充」，符合计划 Step 8 的「新 AGENT_* 类型按需补充」） |
| Task 1.2: CallChain + CommunicationPolicy | ✅ | cycle/depth、policy 字段、默认值、from_config | `CallChain` 全方法；`CommunicationPolicy` 仅含 `allowed_targets/allowed_modes/request_timeout=300/max_chain_depth=3`；`_parse_communication_policy` 忽略未知键；`AgentConfig` 接入 `__init__`/`from_config`/`to_json` | 按用户要求删除 `enable_*`/预算字段（计划 Task 1.2 原含这些字段） |
| Task 1.3: AuditLogger（跳过 Budget） | ✅ | 无 budget.py、无 circuit_breaker.py、JSONL、字段齐全 | `CommunicationEvent` 12 字段；`AuditLogger` 追加 JSONL（best-effort，空 workspace no-op）；**未创建** budget.py / circuit_breaker.py | 按用户要求跳过 Budget |
| Task 1.4: 注册 + ABC + SocketIO ACK 通路 | ✅ | registry 实例、send()->dict、get_agent 同步、dispatch table、server 返回 dict、CrewOrchestrator no-op | defaults.py 注册（per-agent）+ entry point + docstring=22；components 导出；communicator ABC `send()->dict`；agent_factory ABC 同步 `get_agent`；socketio_client `send`/`_send_message_with_ack`/`_SEND_TYPE_BY_MODE`/`_ack_timeout=2.0` + AGENT_* dispatch 4 条；socketio_server handler `return` + `_process_message -> dict`（routed/routing_failed，保留 `_send_error(ROUTING_FAILED)`）；orchestrator_runner 注释 no-op | 新增 `DefaultAgentMessenger` **骨架**（见 Deviations） |

## Deviations

### D1（已记录，Phase 2 完成）：新增 `DefaultAgentMessenger` 骨架
- **现象**：Task 1.4 的 AC 要求 `ComponentRegistry.get(AgentMessenger, scope_key="test")` 返回实例，但 `DefaultAgentMessenger` 的完整实现计划在 Phase 2（Task 2.1）。
- **原因**：`ComponentRegistry._build_default_implementations` 在实现模块缺失时回退到 ABC 本身，而 ABC 含抽象方法无法实例化 → 无法满足该 AC。
- **处理**：在 Phase 1 新建 `broca/agent_messenger/messenger.py`，提供可实例化的 `DefaultAgentMessenger` **骨架**（`initialize`/`set_call_chain`/`reset_budget` 已实现；`request`/`notify`/`delegate`/`reply`/`handle_request_response` 暂 `raise NotImplementedError` 并标注「Phase 2 (Task 2.1)」），并定义 `AgentCommunicationError`。Task 2.1 将替换为完整实现。
- **影响**：无功能影响（Phase 1 不调用这些方法）；仅为满足注册与实例化 AC。

## Quality Checklist

- [x] 所有 Phase 级 AC 满足（含预算/可选环检测的「按用户要求跳过」调整）
- [x] 所有 Task 级 AC 满足（Task 1.2/1.3 已按用户约束调整 AC）
- [x] 无遗漏任务（Phase 1 共 4 个 Task，全部创建并完成）
- [x] 无额外功能（除 D1 骨架、llm.py AGENT_NOTIFY 解析分支两项已说明的最小必要补充）
- [x] 关键行为手动验证（inline 断言 + 导入检查）
- [x] 代码遵循项目约定（组件注册/ABC/懒加载模式一致）
- [x] 与既有代码兼容

## 测试结果

| 范围 | 结果 |
|------|------|
| `test_components_registry.py` | 27 passed |
| `socketio*` + `test_agent*` | 55 passed |
| `test_component_interfaces.py` / `test_component_errors.py` / `test_engine_orchestration.py` | 59 passed |
| 全量 `--co` 收集 | 1726/1727 collected（0 collection error） |
| **5 个待更新测试文件**（计划 Task 3.3 统一更新） | 13 failed（**预期内**）：`test_llm.py`(3) / `test_save_user_message_no_mutation.py`(2) / `test_non_blocking_mode.py`(1) / `test_handle_task_assigner_defense.py`(6) / `test_communicator_abc.py`(1) |

> 说明：计划明确 Phase 1 **不以「全量 pytest 通过」为硬门槛**，5 个受影响测试文件统一在 Task 3.3 更新。上述 13 个失败均为对已删除 `TASK_*`/`send_task_*`/`_handle_task` 的引用，属计划预期。

## Phase 级 AC 核对

- [x] `AgentMessenger` ABC 定义完成，注册到 `ComponentRegistry`（`defaults.py`，per-agent scope + entry point）
- [x] `CallChain`、`CommunicationPolicy`、`AuditLogger` 3 个控制原语实现完成（**Budget 与 notify/delegate 可选环检测按用户要求跳过**；`request_timeout` 保留）
- [x] `MessageType` 新增 `AGENT_REQUEST` / `AGENT_REQUEST_RESPONSE` / `AGENT_NOTIFY` / `AGENT_DELEGATE`
- [x] `MessageType` 旧值 `TASK_START` / `TASK_COMPLETE` / `TASK_ERROR` 已删除
- [x] `AssignTask` tool 已删除；`MessageProtocol.create_task_start/complete/error` 已删除
- [x] `Agent._handle_task()` 及相关分支已删除
- [x] `Communicator` ABC 中 `send_task_*` 方法已删除
- [x] `engine.py` 3 处 `_cross_agent_types`、`llm.py` 3 个 TASK_* 分支、`agent.py` 两处 `_drain_types` docstring TASK 引用已清理
- [x] 控制原语通过 import 检查 + inline 断言验证
- [x] 生产代码无引用断裂：`grep -rn "TASK_START\|TASK_COMPLETE\|TASK_ERROR\|AssignTask\|_handle_task\|send_task_\|create_task_" broca/ --include=*.py --exclude-dir=alembic --exclude-dir=tests` → **无结果**
- [x] 5 个受影响测试文件按计划延后至 Task 3.3 更新（Phase 1 允许失败）

## 变更文件清单

**新增**：`broca/agent_messenger/{__init__,message_models,call_chain,audit,messenger}.py`、`broca/components/agent_messenger.py`

**修改**：`broca/session/models.py`、`broca/tools/agent_interaction.py`、`broca/agent.py`、`broca/loop_engine/engine.py`、`broca/llm.py`、`broca/components/communicator.py`、`broca/communication/socketio_client.py`、`broca/communication/socketio_server.py`、`broca/components/defaults.py`、`broca/components/__init__.py`、`broca/components/agent_factory.py`、`broca/agent_configs.py`、`broca/session_runner/orchestrator_runner.py`
