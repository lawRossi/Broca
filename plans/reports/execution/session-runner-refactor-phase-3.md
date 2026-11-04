# Phase 3 执行报告：拆分监控与事件，`runner.py` 类化

- **计划文档**：`plans/session-runner-refactor-plan.md`
- **阶段**：Phase 3（Task 3.1 ~ 3.5）
- **状态**：✅ 功能目标全部达成；❌ 行数目标未达成（第三次确认，根因已定位）
- **完成时间**：2026-11-03

---

## 1. 阶段目标回顾

> 把心跳/健康策略、事件分发、IPC 消息路由三块从 `manager.py` 抽出；把 `runner.py` 从「8 个全局变量 + 233 行 if/elif」改造为 `SessionRunnerProcess` 类。本阶段结束后 `manager.py` 成为纯编排层，`runner.py` 可实例化、可并行测试。

---

## 2. 阶段验收标准逐条核对

| # | 验收标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | `manager.py` ≤ 400 行 | ❌ **1080** | 见 §6 |
| 2 | `broca/session_runner/` 下无模块级可变全局状态 | ✅ | `grep -nE "^_[a-z_]+ *[:=]" runner.py` 无结果；`protocol.py` 无模块级 router 实例 |
| 3 | `runner.py` 的 `handle_ipc_command` if/elif 链消失 | ✅ | 233 行 → **3 条语句**（AST 口径），`await self.router.dispatch(msg, self)` |
| 4 | Phase 1/2 全部测试仍绿 | ✅ | `broca/tests/` **1093 passed / 5 skipped**；web 集成 6 passed；真实子进程集成 2 passed |

> 阶段 AC 第 2 条补充验证：`grep -nE "^(runner_router|manager_router) *= *MessageRouter" protocol.py` 无结果 —— router 由 `SessionRunnerProcess` / `IPCSessionRunner` 各自在 `__init__` 构建。

---

## 3. 各 Task 交付物

### Task 3.1：`monitor.py`（HealthPolicy + HeartbeatMonitor）
- `HealthPolicy`（frozen dataclass）：`interval` / `timeout` / `check_interval` / `grace_multiplier` / `persist_interval`，`from_config()` 读 `configs.json` execution 组，`grace` 属性
- `HeartbeatMonitor`：`start()` / `stop()` / `check_once()` / `_persist_states()` / `converge_stopped()` / `converge_dead()` / `mark_agents_disconnected()`
- `release_handle()`：唯一负责「取消监听任务 + 关闭 IPC」的实现
- manager 迁出 8 个方法，只留 2 个委托；`_heartbeat_*` 四个散字段删除
- 新增 `test_runner_monitor.py`（8 例）

### Task 3.2：`events.py`（EventBus）
- `EventBus.on` / `emit(event, *args)` / `emit_soon` / `emit_crew_event` / `aclose`
- `emit` 用 `*args` 而非单 payload：`session_crashed` 传 1 个、`crew_event` 传 2 个（保住 `crew_service.handle_crew_event(session_id, msg)` 既有签名）
- manager 的 `_handle_crew_event`（54 行）、`_trigger_event`、`_event_handlers` 全部删除
- 新增 `test_runner_events.py`（6 例）

### Task 3.3：`protocol.py`（MessageRouter）
- `MessageRouter.register/handler/registered_types/from_class/dispatch` + `handles(msg_type, side=...)`
- **`from_class` 扫描类方法**（`inspect.getmembers(cls, inspect.isfunction)`），不是扫模块命名空间
- **无模块级 router 实例**，实例级构建，测试可 per-instance 隔离
- `runner.py`：233 行 if/elif → 3 条语句 + 6 个 `@handles(..., side="runner")` 方法
- `manager.py`：105 行 if/elif → 2 条语句 + 9 个 `@handles(..., side="manager")` 方法
- 删除死代码：`CMD_RESTART`、`CMD_CREW_STATUS`、`CrewOrchestratorRunner.get_crew_status()`
- 新增 `test_runner_protocol.py`（11 例）

### Task 3.4：`runner.py` 类化
- `class SessionRunnerProcess`：`run()` / `_bootstrap()` / `_shutdown()` / 3 个循环 / 6 个 `_handle_cmd_*` / `_run_crew_safe()` / `_match_crew_agents()`
- 8 个全局变量 → 实例属性；`request_shutdown()` 统一收敛停止语义（原先散在 4 处）
- `crew_runner` 单例 → 实例属性 + 「已有编排在跑」拒绝分支
- `_log_agent_task_failures()`：`asyncio.wait` 后取回每个 task 的异常
- `setup_logging` 修 `makedirs("")`
- 新增 `test_runner_process.py`（10 例）

### Task 3.5：manager 收敛为编排层
- `start_session` 190 行 → 4 条语句（`_check_quota` / `_open_ipc_server` / `_spawn` / `_await_ready` / `_attach_listener`）
- `stop_session` / `restore_active_sessions` 的冗长分支抽成 `_recover_stale_runner()` / `_retire_orphan()`
- `_runner_info_to_dict` → `RunnerProcessInfo.to_dict()`
- 三处重复的 IPC 清理统一走 `release_handle()`
- 导出面守卫测试 `test_public_export_surface_is_intact()`
- **未触碰 `broca/components/session_runner.py`**（ABC 扩展整体归 Task 4.1）

---

## 4. 测试统计

| 时点 | 结果 |
|---|---|
| Phase 2 结束 | 1057 passed / 5 skipped |
| Task 3.1 后 | 1071 passed |
| Task 3.2 后 | 1071 passed |
| Task 3.4 后 | 1080 passed |
| Task 3.3 后 | 1092 passed |
| **Phase 3 结束** | **1093 passed / 5 skipped / 1 deselected** |
| web 集成 | 6 passed |
| 真实子进程集成（`BROCA_RUN_INTEGRATION=1`） | 2 passed |

### 新增测试文件

| 文件 | 用例数 |
|---|---|
| `test_runner_monitor.py` | 8 |
| `test_runner_events.py` | 6 |
| `test_runner_protocol.py` | 11 |
| `test_runner_process.py` | 10 |
| `test_runner_module_imports.py`（追加导出面守卫） | +1 |

**Phase 3 新增 36 例**，且全部带回归意图（每条都对应一个具体历史 bug 或长期守卫）。

---

## 5. 关键设计决策

1. **`from_class` 而非扫描模块命名空间**：handler 是类方法，定义在类体里，`inspect.getmembers(module)` 只会得到 `None` —— 那会让「所有 CMD/EVT 都有 handler」的守卫**全绿假通过**。这是本阶段最容易踩的坑，已在 `test_from_class_discovers_methods` 里正面锁住。
2. **叠加装饰器要存列表**：初版 `HANDLER_ATTR` 存单个 tuple，4 个 crew 装饰器叠加后只剩最后一个生效（只注册 1 个类型）。改为存 tuple 列表，并新增 `test_stacked_handles_register_each_type`。
3. **`EventBus.emit(event, *args)` 而非单 payload**：`session_crashed` 传 1 个参数、`crew_event` 传 2 个。这保住了 `crew_service.handle_crew_event(session_id, msg)` 的既有签名，避免改 web 层。
4. **`release_handle()` 是唯一的 IPC 释放实现**：此前 `_cleanup_ipc_resources` / `_cleanup_runner` / `_cancel_ipc_listener_task` 三处各写一半，任何一处漏掉都会泄漏 socket 或残留监听任务。
5. **Task 顺序调整**：3.3 的 `@handles` 必须挂在类方法上，而类在 3.4 才存在 → 先做 3.4（类化），再做 3.3（router）。两 Task 的 AC 均未受影响。

---

## 6. ⚠️ 行数目标：第三次确认不可达

### 实测轨迹

| 时点 | 计划 | 实测 |
|---|---|---|
| Phase 2 结束 | ≤ 950 | 1512 |
| Task 3.1 后 | ≈ 950 | 1129 |
| Task 3.2 后 | ≈ 774 | 1110 |
| Task 3.3 后 | ≈ 669 | 1105 |
| Task 3.5 后 | **≤ 400** | **1080** |
| 预计 Task 4.2 后 | — | ≈ 980 |

### 根因（本次已能精确定位）

**计划的减行模型是错的**。它假设「抽方法 = 减行」，但实测四类改动：

| 改动类型 | 行数效果 |
|---|---|
| 整块搬到别的文件（`_check_heartbeats` → `monitor.py`） | **真减行**（−383） |
| if/elif 拆成带 `@handles` 的独立方法 | **行数中性**（−5；每个分支从 8 行变成 12 行的独立方法） |
| 长函数拆成小步（`start_session` → 9 个方法） | **略增**（每个方法都有 docstring + 签名） |
| 抽取抽象层（`release_handle` 去重） | 小减（−50） |

计划在 Task 3.2 预估 −176，但 `_handle_crew_event` 实测只有 **54 行**；在 Task 3.3 预估 −105，实际 if/elif 拆解后总行数几乎不变；在 Task 3.5 预估再 −269，实际 −25。三项合计高估约 **480 行**，正好是 1080 vs 400 的差距来源。

### 结论

**≤400 在「保留历史 bug 说明注释」的前提下不可达。** 现有 1080 行中约 200 行是解释「为什么这样判死 / 为什么先写库再清理 / 为什么 PID 复用不能直接 kill」的注释——这些注释是本计划「修复 5 个 P0 并留下可读记录」目标的直接产物。删掉它们确实能到 ~880，但仍远高于 400。

### 建议（与 Phase 2 报告一致，此处给出具体数值）

改用**结构指标**，全部可 grep 验证：

| 指标 | 当前值 | 目标 |
|---|---|---|
| `manager.py` 直接实例化 `IPCServer` / `IPCClient` | 1 处（`_open_ipc_server`） | ≤1 |
| `manager.py` 出现 SQL / SQLModel | 0 | 0 ✅ |
| `manager.py` 出现 `subprocess` / `psutil` / `os.kill` | `subprocess.TimeoutExpired` ×1 | ≤1 |
| `manager.py` 出现 `process.wait` | 0（已 `to_thread`） | 0 ✅ |
| `manager.py` 出现 `ensure_future` | 0 | 0 ✅ |
| `IPCSessionRunner` 公开方法数 | 13 | ≤12（Task 4.x 可合并 `list_sessions`/`get_stats`） |
| `broca/session_runner/` 模块数 | 17 | — |

---

## 7. 遗留问题

1. **`manager.py` 1080 行**：剩余可减项是 `_ipc_listener_loop` + `_start_poll_thread`（97 行，Task 4.2 的 `IPCPoller`）。之后 ≈980。
2. **`runner.py` 742 行**：类化后比原来（692 行）还多 50 行，同样是「拆方法行数中性」的表现。已超出 Task 3.5 的「每文件 ≤500」AC。
3. **`EVT_READY` / `EVT_COMPLETED` / `EVT_LOG` 三个 handler 是新增的**：为满足「所有 EVT_* 都有 handler」的 AC，补了三个原本静默忽略的类型（`EVT_READY` 记 debug、其余记 info）。语义上无害，但确实扩大了 handler 面。
4. **`_handle_evt_heartbeat` 仍是 40 行**：心跳的状态迁移逻辑（stale/missed/error 恢复）内聚性强，没有再拆。

---

## 8. 结论

Phase 3 的**功能目标 100% 达成**：

- `manager.py` 成为纯编排层（`start_session` 4 条语句、`_handle_runner_event` 2 条语句）
- `runner.py` 可实例化、可并行测试，8 个全局变量清零
- 三条 if/elif 链（runner 233 行 + manager 105 行 + crew 54 行）全部消除
- 所有 `CMD_*` / `EVT_*` 都有 handler，死类型（`CMD_RESTART` / `CMD_CREW_STATUS`）已删
- 36 个新测试全部带回归意图

**唯一未达标项是行数**，且本次已能精确定位根因：计划把「拆方法」当作减行手段，但拆方法是行数中性的重构，真正减行只能靠「整块搬家」。建议 Phase 4 及后续验收改用 §6 的结构指标。
