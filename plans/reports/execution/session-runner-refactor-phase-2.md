# Phase 2 执行报告：拆分传输层、持久层与进程层，解除事件循环阻塞

- **计划文档**：`plans/session-runner-refactor-plan.md`
- **阶段**：Phase 2（Task 2.1 ~ 2.5）
- **状态**：✅ 功能目标全部达成；⚠️ 行数目标未达成（详见「偏差」）
- **完成时间**：2026-11-03

---

## 1. 阶段目标回顾

> 把 `manager.py` 中三块边界清晰的职责（IPC 传输、DB 持久化、进程启动/回收）抽成独立模块，并把所有阻塞调用移出事件循环。本阶段结束后 `manager.py` 行数下降 ≥ 40%，且 `stop_session` / `shutdown_all` 不再冻结事件循环。

---

## 2. 阶段验收标准逐条核对

| # | 验收标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | `manager.py` 行数 ≤ 950 | ❌ **1512** | 见 §6 偏差分析 |
| 2 | `broca/session_runner/` 下所有 `async def` 内无同步阻塞调用 | ✅ | `test_ast_no_blocking_calls_in_async`（AST 静态守卫，已用 8 个正/负样本验证有效） |
| 3 | `stop_session` 期间事件循环 tick ≥ 10 | ✅ | `test_stop_session_does_not_block_event_loop`：1s wait 期间实测 ~50 tick |
| 4 | Phase 1 全部测试仍绿 | ✅ | 10 个 runner/ipc 测试文件合跑 **75 passed / 1 skipped**；`broca/tests/` 全量 **1057 passed / 5 skipped** |

> 补充：阶段 AC 第 3 条只要求 `stop_session`，实际还额外覆盖了 `shutdown_all`（3×1s，tick ≥ 30）。

---

## 3. 各 Task 交付物

### Task 2.1：抽取 `transport/`
- 新增 `transport/{__init__,base,addresses,server,client}.py`
- `ipc.py` → **38 行薄壳** re-export（AC 要求 < 40）
- `models.py` 中 `get_ipc_address` / `get_ipc_family` 改为一行转发，`is` 断言同一对象
- `IPCChannel` Protocol 修正为 `async def start`
- 新增 `test_ipc_transport.py`（6 例）
- **踩坑**：`transport/__init__.py` 不能 eager re-export server/client —— `models.py` 需从 `transport.addresses` 反向引用，会形成循环导入。导出面统一由 `ipc.py` 薄壳提供。

### Task 2.2：抽取 `repository.py`
- 新增 `repository.py`：`RunnerRepository`（`upsert` / `upsert_many`（SQLite `on_conflict_do_update`，单事务一次 commit）/ `delete` / `get` / `list_active` / `set_agent_status` / `mark_agents_disconnected`）
- manager 5 个 DB 方法改为委托；`_persist_runner_state` 批量化
- 删除所有 `db_manager.get_session` / `import sqlmodel`
- 新增 `test_runner_repository.py`（7 例，含 commit 次数断言）

### Task 2.3：抽取 `process/` 三层 + 防 PID 复用误杀
- 新增 `process/{launcher,reaper,registry}.py`
- **7 个并行 dict → 1 个 `RunnerRegistry`**
- `RunnerReaper.is_alive` 三因子：`pid_exists` + `create_time` 容差 5s + `cmdline` 含模块标识与 session_id；cmdline 为空则降级两因子（Windows）
- 删除 `_find_runner_process_by_pid` / `_force_kill_process_by_pid` / `_force_kill_process`
- `restore_active_sessions` 改走 `repo.list_active()` + `reaper.terminate_orphans()`
- 新增 `test_runner_reaper.py`（7 例）
- 迁移 4 个既有测试文件的私有属性引用

### Task 2.4：解除事件循环阻塞
- `stop_session` → `asyncio.to_thread(process.wait, timeout)`
- **删除** `get_resource_usage()`（全仓零调用方，消除 `cpu_percent(interval=0.1)` 同步 sleep）
- 新增 `test_runner_no_blocking.py`（3 例：2 个运行时 + 1 个 AST 长期守卫）

### Task 2.5：`TaskSet` 替代裸任务
- 新增 `events.py`（90 行）：`TaskSet.spawn` / `aclose`
- `manager.py` 3 处 `ensure_future` / 裸 `create_task` → `self._tasks.spawn(...)`
- `_schedule_agent_status_sync`：在途去重（同一 session 不堆积同步任务）
- `runner.py`：`_crew_task` 持引用 + done_callback 记异常
- 新增 `test_runner_taskset.py`（5 例，含 `test_no_untracked_create_task` 长期守卫）

---

## 4. 测试统计

| 时点 | 范围 | 结果 |
|---|---|---|
| Phase 1 结束 | 7 个 runner/ipc 文件 | 54 passed（含 2 个集成） |
| Task 2.2 后 | 同上 + 2 个新文件 | 67 passed |
| Task 2.3 后 | 8 个文件 | 65 passed / 1 skipped |
| Task 2.4 后 | 9 个文件 | 75 passed / 1 skipped |
| **Phase 2 结束** | `broca/tests/` 全量 | **1057 passed / 5 skipped / 1 deselected** |
| Phase 2 结束 | `broca-web/tests/integration/test_api_session_runner.py` | 6 passed |
| Phase 2 结束 | 真实子进程集成测试（`BROCA_RUN_INTEGRATION=1`） | 2 passed |

Flaky 检查：`test_runner_no_blocking.py + test_runner_taskset.py + test_runner_reaper.py + test_runner_heartbeat.py` 连跑 3 次，均 30 passed。

### 新增测试文件汇总（本阶段）

| 文件 | 用例数 |
|---|---|
| `test_ipc_transport.py` | 6 |
| `test_runner_repository.py` | 7 |
| `test_runner_reaper.py` | 7 |
| `test_runner_no_blocking.py` | 3 |
| `test_runner_taskset.py` | 5 |

---

## 5. 关键设计决策

1. **`ipc.py` 作为唯一导出面**：`transport/__init__.py` 保持空壳，避免 `models.py ↔ transport` 循环导入。
2. **`RunnerHandle` 收拢全部运行时状态**：`info` + `ipc` + `poll_thread` + `poll_task` + 三个缓存 + `pending_responses`。任何一处漏改都不会再产生「有 runner 没 ipc」的幽灵状态；测试隔离也从 7 行 `clear()` 变成 1 行 `mgr._registry.clear()`。
3. **多因子判活是「宁可漏杀，不可误杀」**：`is_alive` 任一因子不满足即返回 False 且不 kill；`AccessDenied` / 空 cmdline 一律保守判活。
4. **静态守卫优于一次性脚本**：Task 2.4 的 AST 扫描脚本与 Task 2.5 的 `create_task` 审计都固化成了测试，后续重构会立刻失败。两者都做过反向验证（临时注入违规代码 → 测试失败）。
5. **`get_resource_usage` 直接删除而非异步化**：全仓零调用方，保留即负债。

---

## 6. ⚠️ 偏差：行数目标系统性不可达

### 实测数据

| 时点 | 计划预估 | 实测 |
|---|---|---|
| Phase 2 开始（Task 2.1 前） | — | 1658 |
| Task 2.2 后 | ≤ 1300 | 1658 |
| Task 2.3 后 | ≈ 1433 | 1524 |
| Task 2.4 后 | ≈ 1399 | 1486 |
| Task 2.5 后 | ≈ 1399 | **1512** |
| **Phase 2 AC** | **≤ 950** | **1512** |
| Task 3.5 AC | ≤ 400 | 预计仍远超 |

### 根因（三条，均为计划本身的问题，非执行偏差）

1. **计划未计入 Phase 1 的增量**。Phase 1 新增了 `build_runner_argv` / `build_runner_env` / `platform_popen_kwargs`（~85 行，后来才迁到 `launcher.py`，但 Task 2.1~2.2 期间确实存在于 manager.py），以及 `stop_requested` 语义分流、`request_stop` 等方法（~60 行）。计划的行数预估基于改造前基线，未把这些计入。
2. **高估了 Task 3.2 的减行量**。计划声称 `_handle_crew_event` 迁出可减 176 行，实测该函数仅 **54 行**。这意味着 Phase 3 的 ≤400 目标缺口约 120 行。
3. **新增的抽象带来了不可忽略的注释/docstring 成本**。本次改造的一个明确目标是「可读性」，`_converge_*`、`_reaper` 等关键路径都加了长注释说明历史 bug 与判定依据；纯行数指标与这个目标天然冲突。

### 实际取得的进展

- 职责切分目标 **100% 达成**：传输层（`transport/`，38 行薄壳 `ipc.py`）、持久层（`repository.py`）、进程层（`process/` 3 文件）、任务容器（`events.py`）全部独立。
- `manager.py` 的**状态字段从 7 个降为 1 个**，`ensure_future` 清零，同步阻塞调用清零。
- 行数 1658 → 1512（−146，−8.8%），远低于计划的 −40%。

### 建议

**建议在 Phase 3 结束前重新校准行数 AC**，改用可验证的**结构指标**替代纯行数：

- `manager.py` 中不再出现 `IPCServer` / `IPCClient` 的直接实例化（传输细节已隔离）
- `manager.py` 中不再出现 SQL/SQLModel 相关调用（持久细节已隔离）
- `manager.py` 中不再出现 `subprocess` / `psutil` / `os.kill`（进程细节已隔离）
- `IPCSessionRunner` 的公开方法数 ≤ 12

这些指标能真实反映「God Class 是否被拆开」，且不会因注释密度而失真。

---

## 7. 遗留问题

1. **`_kill_runner` 保留**：Task 2.3 计划要求删除，但 `start_session` 的失败清理路径仍需要「按 session_id 杀」的语义。已改为一行委托 `self._reaper.terminate(handle)`，不再是同步阻塞实现。**这是有意保留的薄封装，不是遗漏。**
2. **静态守卫的已知盲区**：`test_ast_no_blocking_calls_in_async` 只能识别 `*thread*.join()` 形式的线程 join；`t.join()` 会漏报（`subprocess.run` / `str.join` 误报太多，未纳入）。已在测试注释中说明。
3. **全量跑 `broca/tests/` 时的 `RuntimeWarning: coroutine 'Event.wait' was never awaited`**：跨用例泄漏，单跑不出现，非本次改动引入（Phase 1 报告已记录），未处理。
4. **`runner.py` 仍有 8 个模块级全局变量**：Phase 3 Task 3.4 才类化为 `SessionRunnerProcess`。

---

## 8. 结论

Phase 2 的**功能目标全部达成**：三块职责已彻底切出、事件循环不再被阻塞、fire-and-forget 任务全部可追踪。**唯一的未达标项是纯行数指标**，且根因是计划的行数预估失准（未计入 Phase 1 增量、高估 Task 3.2 减行量、与「加注释说明历史 bug」的改造目标冲突）。

建议带着「结构指标替代行数指标」的校准进入 Phase 3。
