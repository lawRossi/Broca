# Session Runner 模块优化与重构计划

## 概述

- **目标**：修复 `broca/session_runner/` 中已确认的 5 个阻塞性缺陷（P0），并分阶段完成组件化重构——把 1631 行 God Class（`IPCSessionRunner`，40 方法）与 692 行过程式脚本（`runner.py`，8 个模块级全局变量）拆成职责清晰的协作对象，同时消除事件循环阻塞、PID 误杀、抽象泄漏等 P1/P2 问题。
- **背景**：`session_runner` 是整个 Agent 执行链路的底座（每个 Session 一个子进程）。代码注释中累计记录了 15+ 处「历史 bug：…」的补丁痕迹，说明同一块逻辑被反复打补丁而非重构。当前测试仅覆盖心跳与启动恢复（27 例），`ipc.py`、`runner.py` 命令处理、`start_session` 端到端全部零覆盖——而 P0 缺陷恰好全部落在这个盲区里。
- **约束条件**：
  - Python ≥ 3.12（`pyproject.toml`），当前开发环境为 3.14。**必须保证 3.12/3.13 可用**（见 P0-1）。
  - **3.12/3.13 兼容性的验证方式**：本机 `venv` 的编译型依赖（`pydantic_core` 等）为 3.14 构建，`/opt/homebrew/bin/python3.12` 实测无法 `import broca`（`ModuleNotFoundError: pydantic_core._pydantic_core`）。因此不能把「在 3.12 解释器上 import」当作 AC——那会先挂在依赖上、永远走不到注解求值。本计划采用「**AST 静态校验（任意解释器可跑）+ 可选 CI matrix**」双轨，见 Task 1.1。
  - 跨平台：Linux / macOS 用 AF_UNIX，Windows 用 AF_NAMED_PIPE。
  - 每个阶段必须可独立验收、可独立上线；阶段之间不产生「必须一次性提交」的耦合。
  - 允许同步修改 `broca-web/backend` 的 API 层（消除对私有属性的直接访问），但对外 REST 接口契约（路径、响应结构）不得变化。
  - 不引入新的第三方依赖。

---

## 相关材料

### 被改造的代码（按改造顺序）

| 文件 | 行数 | 现状角色 |
|---|---|---|
| `broca/session_runner/models.py` | 164 | 数据模型。**基本保留**，仅补 `stop_requested` 字段与 IPC 地址生成 |
| `broca/session_runner/ipc.py` | 394 | 传输层。Server/Client 重复实现，需抽公共基类 |
| `broca/session_runner/manager.py` | 1631 | 父进程管理 God Class，需拆成 6 个组件 |
| `broca/session_runner/runner.py` | 692 | 子进程主逻辑，过程式 + 8 个全局变量，需类化 |
| `broca/session_runner/orchestrator_runner.py` | 358 | 编排运行器。**基本保留**，仅删除死代码 `get_crew_status()`（Task 3.3）；「全局单例」实指 `runner.py` 的 `_crew_runner`，由 Task 3.4 消除 |
| `broca/session_runner/__init__.py` | 34 | 导出面（`IPCClient`/`IPCServer`/`RunnerManager`）。**Task 3.5 负责更新并加 import 守卫 AC** |

### 依赖与调用方

- `broca/components/session_runner.py` —— `SessionRunner` ABC，当前只有 4 个抽象方法，需扩展
- `broca/components/defaults.py:64,122` —— `SessionRunner: "broca.session_runner.manager:IPCSessionRunner"`，`scope = "singleton"`
- `broca/components/__init__.py:63,98` —— 导出
- `broca/configs.py:38-45` —— `ExecutionConfig`，心跳/并发配置项定义处
- `configs/configs.json:22-24` —— `runner_heartbeat_interval / timeout / check_interval`
- `broca/session/models.py:205-240` —— `SessionRunner` 表模型（`runner_id` 主键，`session_id` 唯一）
- `broca/session/database.py` —— `db_manager.get_session()`
- `broca/utils/datetime_util.py:serialize_dt` —— 序列化工具

### 调用方（broca-web 后端）

- `broca-web/backend/app/main.py:136-195` —— 启动时 `start_heartbeat_monitor()` + `restore_active_sessions()`，注册 `crew_event` / `runner_error` handler
- `broca-web/backend/app/main.py:196-230` —— 关闭时 `shutdown_all()`
- `broca-web/backend/app/api/session_runner.py` —— **抽象泄漏重灾区**：`:117-131` 直接访问 `runner_manager._runners` 与 `._ipc_servers`
- `broca-web/backend/app/api/session.py:38,174,198,384,473,640` —— 6 处 `RunnerManager()` 调用
- `broca-web/backend/app/services/crew_service.py:171,274` —— `send_command()` 调用，`:257-300` 有 SQLite 锁相关的重要注释

### 现有测试（重构会破坏，需同步更新）

- `broca/tests/test_runner_heartbeat.py`（依赖 20 个私有属性，见附录 A）
- `broca/tests/test_runner_restore.py`
- `broca-web/tests/integration/test_api_session_runner.py`（用 `patch("app.api.session_runner.RunnerManager")`）

### 外部参考

- PEP 649 — Deferred Evaluation Of Annotations（Python 3.14）
- `multiprocessing.connection.wait()` — 多连接多路复用
- `subprocess.Popen` 文档 — `preexec_fn` 在多线程进程中不安全，应改用 `start_new_session`
- `asyncio` 文档 — 「Save a reference to the result of this function, to avoid a task disappearing mid-execution」

---

## 总体方案

### 现状问题摘要（已实测验证）

| 编号 | 严重度 | 问题 | 位置 |
|---|---|---|---|
| P0-1 | 阻塞 | 模块级注解引用未定义名 `AgentFactory`。PEP 649 延迟注解 3.14 才落地，**3.12/3.13 上 `import` 直接 NameError**，整个 runner 子进程起不来 | `runner.py:47` |
| P0-2 | 阻塞 | `shell=True` + 参数拼接无引号。workspace 含空格 → 参数错位 → 启动失败 + 白等 15s 超时；且是命令注入面 | `manager.py:296-312,333` |
| P0-3 | 阻塞 | 解释器用裸 `"python"` 而非 `sys.executable`，还主动 `env.pop("VIRTUAL_ENV")` | `manager.py:123-125,326-338` |
| P0-4 | 阻塞 | `Listener` 绑定前不 unlink 旧 socket。硬崩溃后残留 → `EADDRINUSE` → **该 session 永久无法再启动**（本机 `/tmp` 已有 6 个残留） | `ipc.py:80-96` |
| P0-5 | 阻塞 | `process.poll()` 判死不区分状态。用户主动 stop（只置 `SHUTTING_DOWN` 未移出 `_runners`）→ 被判 `dead` + 触发 `session_crashed` + agent 全标 `disconnected` | `manager.py:1150-1165` |
| P1-1 | 高 | `process.wait(timeout=5)` 在 `async def` 内同步阻塞事件循环；`shutdown_all` 串行 N 个 → 最坏 10N 秒全站冻结 | `manager.py:611` |
| P1-2 | 高 | `_force_kill_process` 内 `wait(2)` + `wait(3)` 同步阻塞 | `manager.py:635-669` |
| P1-3 | 高 | `proc.cpu_percent(interval=0.1)` 同步 sleep 100ms（且该方法是死代码） | `manager.py:1617` |
| P1-4 | 高 | 裸 `asyncio.ensure_future` 不持引用（可被 GC，异常静默丢失）+ 心跳每 5s 无节流创建 DB 写任务 | `manager.py:920,938` |
| P1-5 | 中 | DB 写放大：逐 runner 串行 `SELECT+UPDATE`，N 个 runner = 2N 次往返 | `manager.py:1092-1119` |
| P1-6 | 中 | 每 session 一个 daemon 线程轮询 IPC，10 并发 = 10 常驻线程 | `manager.py:1340-1371` |
| P1-7 | 中 | `asyncio.Queue()` 无 maxsize，无背压 | `manager.py:1392`, `runner.py:422` |
| P2-1 | 中 | 只按 `pid_exists` 判活，**PID 复用会误杀无关进程** | `manager.py:466-501,1437-1538` |
| P2-2 | 中 | `_get_active_runner_count` 不数 `ERROR`/`SHUTTING_DOWN` 的活进程 → 并发上限失效 | `manager.py:849-857` |
| P2-3 | 中 | `stop_session` 先 `_runners.pop` 再发 shutdown → `SHUTTING_DOWN` 对外不可见、RESPONSE 永远被丢 | `manager.py:534-633` |
| P2-4 | 中 | `_crew_runner` 全局单例：同 session 第二个编排覆盖引用，第一个无法 abort | `runner.py:50` |
| P2-5 | 低 | 死代码：`CMD_RESTART`、`CMD_CREW_STATUS`、`get_crew_status()`、`register_handler`/`_handlers`/`_running`、`get_resource_usage()` | 多处 |

### 目标架构

```
broca/session_runner/
├── __init__.py                 导出面（保持 RunnerManager 别名）
├── models.py                   [改造] 补 stop_requested；IPC 地址生成 Phase 1 就地改造、Phase 2 迁至 transport 并保留一行转发
├── protocol.py                 [新增] 消息路由注册表（替换两条 if/elif 链）
├── transport/
│   ├── __init__.py
│   ├── base.py                 [新增] _BaseIPC：send/recv/close 公共实现
│   ├── addresses.py            [新增] get_ipc_address/get_ipc_family（tempfile 化 + 长度校验）
│   ├── server.py               [迁移自 ipc.py:IPCServer] 加 bind 前 unlink + send 锁
│   └── client.py               [迁移自 ipc.py:IPCClient] 加 send 锁（修 Windows）
├── repository.py               [新增] RunnerRepository：收敛 5 处 DB 直写 + 批量 upsert
├── process/
│   ├── __init__.py
│   ├── launcher.py             [新增] 子进程启动（argv + sys.executable + start_new_session）
│   ├── reaper.py               [新增] 判活/杀进程（cmdline + create_time 校验，防 PID 复用）
│   └── registry.py             [新增] RunnerHandle + RunnerRegistry（8 个 dict 收成 1 个对象）
├── monitor.py                  [新增] HealthPolicy（阈值/宽限）+ HeartbeatMonitor
├── events.py                   [新增] EventBus（强引用 TaskSet）
├── manager.py                  [重写] IPCSessionRunner 只做编排，目标 ≤ 400 行
├── runner.py                   [重写] SessionRunnerProcess 类，消灭全局变量
└── orchestrator_runner.py      [小改] 仅删除死代码 get_crew_status()（Task 3.3）。注意：计划中的「全局单例」实指 runner.py 的 _crew_runner，由 Task 3.4 消除；本文件本身无模块级单例
```

### 关键设计决策

1. **`RunnerHandle` 收拢状态**：把 `_runners` / `_ipc_servers` / `_ipc_listener_threads` / `_ipc_listener_tasks` / `_agent_status_cache` / `_db_state_cache` 六个并行 dict 合并为 `RunnerRegistry: dict[str, RunnerHandle]`，`RunnerHandle` 持有 `info / ipc / poll_task / poll_thread / agent_status_cache / db_state_cache`。这样测试只需 `registry.clear()` 一行，不再逐个 `.clear()`。
2. **判活必须多因子校验**：`pid_exists(pid)` 单独不可信。`Reaper.is_alive(handle)` 需同时满足 ① pid 存在 ② `create_time()` 与记录的 `started_at` 相差 < 5s ③ `cmdline()` 同时包含 `broca.session_runner.runner` 与 `session_id`。任一不满足 → 视为「不是我们的进程」，**绝不 kill**。
3. **优雅停止走独立状态机**：`RunnerProcessInfo` 增加 `stop_requested: bool`。巡检收敛时按此字段分流：`True` → 发 `session_stopped`；`False` → 发 `session_crashed`。
4. **所有阻塞调用出事件循环**：`process.wait` → `asyncio.to_thread`；`kill` 系列用 `await asyncio.sleep` 轮询（已有 `_force_kill_process_by_pid` 的正确写法可复用）。
5. **`preexec_fn` 改 `start_new_session`**：manager 运行在多线程进程（uvicorn + poll 线程 + executor 线程），`preexec_fn` 有文档化的死锁风险。`start_new_session=True` 等价于 `setsid()` 且安全。
6. **路由表替代 if/elif（实例持有，无模块级状态）**：`protocol.py` **只提供 `MessageRouter` 类与 `@handles(IPCMessageType.CMD_XXX, side="runner")` 装饰器工厂**——装饰器仅在被装饰函数上写 `__ipc_handler__` 属性，不产生模块级注册表；`SessionRunnerProcess` / `IPCSessionRunner` 各自在 `__init__` 里 `MessageRouter.from_class(type(self), ...)` 构建**实例级** router（handler 是类方法，`from_module` 扫不到，详见 Task 3.3）。这样既满足 Phase 3 的「无模块级可变全局状态」，又让测试可 per-instance 隔离（不再依赖 import 副作用）。
7. **ABC 与实现对齐**：`broca/components/session_runner.py` 从 4 个方法扩到 **13** 个（`request_stop` 在 Phase 1 加入，其余 8 个在 Task 4.1 补齐），覆盖 API 层真正需要的全部能力；API 层只依赖 ABC，禁止触碰私有属性。
8. **单线程多路复用 IPC**（Phase 4）：用 `multiprocessing.connection.wait([conn...], timeout)` 在一个线程里轮询全部连接，替代 N 个 daemon 线程。
9. **argv 契约单一来源**：Phase 1 一次性收敛子进程 CLI 参数（保留 `--session-id` / `--workspace` / `--log-file` / `--log-level` / `--config`，**删除未使用的 `--provider` / `--model`**），`RunnerLauncher.spawn` 与 `runner.parse_args` 共用 Task 1.2 的契约表，并有 `test_argv_matches_runner_argparse` 长期守卫。这样不会出现「Phase 3 删了 argparse 但 argv 还在传 → 子进程 `unrecognized arguments` 立即退出」的跨阶段断裂。
10. **3.12/3.13 兼容以静态校验守门**：`from __future__ import annotations` 使注解永不求值，再用 AST 校验「模块级/类级注解中的每个名字都在本模块内已绑定」。该检查不依赖解释器版本、不需要 import 成功，是本机唯一能确定性复现 3.12 语义的手段。

### 阶段划分与依赖

```
Phase 1 (P0 修复)  ──► Phase 2 (传输/持久/进程层拆分 + 解阻塞)
                              │
                              ├──► Phase 3 (监控/事件拆分 + runner 类化)
                              │
                              └──► Phase 4 (抽象泄漏 + 性能优化)
```

- Phase 1 可独立上线，不改变任何架构。
- Phase 2 与 Phase 3 严格串行（Phase 3 依赖 Phase 2 的 `RunnerHandle`/`Repository`）。
- Phase 4 的 Task 4.1（ABC/API 层）依赖 Phase 3 完成；**Task 4.2 → Task 4.4 必须串行**（两者都改 `manager.py` 的 poller 消费路径与 `asyncio.Queue`，同文件同区域）；Task 4.3 可与二者并行（只碰 `repository.py` / `monitor.py` / 配置）。

### 工时估算与关键路径

| Phase | Task 数 | 预估工作量 | 关键路径 |
|---|---|---|---|
| Phase 1（P0 止血） | 5 | 3.0 人日 | 1.1 → 1.2 → 1.3 → 1.4 → 1.5（严格串行） |
| Phase 2（分层 + 解阻塞） | 5 | 5.0 人日 | 2.1 → 2.2 → 2.3 → 2.4 → 2.5（严格串行） |
| Phase 3（监控/事件/类化） | 5 | 4.5 人日 | 3.1 → 3.2 → 3.3 → 3.4 → 3.5（严格串行） |
| Phase 4（抽象泄漏 + 性能） | 4 | 3.5 人日 | 4.1 → 4.2 → 4.4；4.3 可并行 |
| **合计** | **19 Task** | **16 人日** | Phase 2 → Phase 3 不可并行 |

---

## 执行计划

### Phase 1: 修复 P0 阻塞缺陷

**目标**：在不改变任何架构的前提下，修掉 5 个会让功能彻底不可用的缺陷，并建立覆盖这些缺陷的回归测试。本阶段结束后，`session_runner` 在 Python 3.12/3.13 上可用、workspace 含空格可用、崩溃后重启可用、优雅停止不再被误报为崩溃。

**阶段验收标准**：
- [ ] `venv/bin/python -m pytest broca/tests/test_runner_*.py broca/tests/test_ipc_*.py -q` 全绿，且**新增测试 ≥ 22 例**（1.1:4 + 1.2:7 + 1.3:5 + 1.4:6），**总用例数 ≥ 49**（27 基线 + 22）。**注意必须带 `test_ipc_*.py`**——Task 1.3 的 5 个用例在 `test_ipc_socket_cleanup.py` 里，只跑 `test_runner_*.py` 会少收集 5 例（实收 44 < 49）
- [ ] `for m in models ipc manager runner orchestrator_runner; do venv/bin/python -c "import broca.session_runner.$m as m; m.__annotations__" || exit 1; done` 无 NameError（解释器统一为 `venv/bin/python`）
- [ ] `venv/bin/python -m pytest broca/tests/test_runner_module_imports.py -q` 全绿（含 AST 注解绑定校验，覆盖 3.12/3.13 语义）
- [ ] **自动化**集成测试 `test_session_lifecycle_with_spaced_workspace`（`tmp_path / "My Project" / "demo"`）通过——替代原「手工跑一次」
- [ ] **自动化**集成测试 `test_restart_after_sigkill`（真实子进程 bind socket → `os.kill(pid, 9)` → 重新 bind，循环 3 次）通过——替代原「手工 kill -9 三次」
- [ ] 主动 `stop_session` 后，`_trigger_event` 收到的是 `session_stopped` 而非 `session_crashed`

---

#### Task 1.1: 修复 `runner.py` 注解 NameError（P0-1）

- **目标**：让 `broca.session_runner.runner` 在 Python 3.12/3.13/3.14 上都能安全 import。
- **步骤**：
  1. 在 `broca/session_runner/runner.py` 的模块 docstring 之后、所有 import 之前插入 `from __future__ import annotations`（使全模块注解延迟求值）。
  2. 把 `runner.py:47` 的 `_agent_factory: Optional[AgentFactory] = None` 改为显式类型来源：在 `typing` import 处补 `TYPE_CHECKING`，并加
     ```python
     if TYPE_CHECKING:
         from broca.components.agent_factory import AgentFactory
     ```
  3. **AST 静态校验（3.12/3.13 兼容性的确定性守门）**：写一个工具函数，对 `broca/session_runner/**/*.py` 的每个模块
     ① 收集本模块的绑定名集合（`Import` / `ImportFrom` 别名 + 模块级 `def`/`class`/`Assign`/`AnnAssign` 目标 + `builtins` 全部名字）。**必须用 `ast.walk(tree)` 遍历全部节点，不能只遍历 `tree.body`**：`if TYPE_CHECKING:` 下的 `from ... import AgentFactory` 位于 `If` 节点内部，只扫顶层会让「修复后」的注解名字仍被判为未绑定，测试反而变红。参考骨架：
       ```python
       def _bound_names(tree: ast.Module) -> set[str]:
           names = set(dir(builtins))
           for node in ast.walk(tree):          # ← walk，不是 tree.body
               if isinstance(node, (ast.Import, ast.ImportFrom)):
                   names |= {(a.asname or a.name).split(".")[0] for a in node.names}
               elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                   names.add(node.name)
               elif isinstance(node, ast.Assign):
                   names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
               elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                   names.add(node.target.id)
           return names
       ```
     ② 遍历所有**模块级与类级** `AnnAssign.annotation`，把其中的 `ast.Name` 与该集合比对，出现未绑定名即失败。
     该检查不依赖解释器版本、不需要 import 成功，是本机唯一能确定性复现 3.12「注解立即求值」语义的手段。
     > 为什么不用「在 3.12 上 import」：本机 `venv` 的 `pydantic_core` 等编译型依赖为 3.14 构建，`/opt/homebrew/bin/python3.12 -c "import broca.session_runner.runner"` 实测先挂在 `ModuleNotFoundError: pydantic_core._pydantic_core`，永远走不到注解求值——原 AC #3（`/usr/bin/python3` 3.9 检查）即因此空转。
  4. 新增回归测试 `broca/tests/test_runner_module_imports.py`：
     - `test_all_session_runner_modules_importable`：遍历 `broca/session_runner/**/*.py`，逐个 `importlib.import_module`，断言无异常。
     - `test_module_annotations_evaluable`：对每个模块执行 `module.__annotations__`，断言无 `NameError`。
     - `test_module_level_annotations_are_all_bound`：上述 AST 静态校验。**注意**：`from __future__ import annotations` 会让 `__annotations__` 变成字符串，因此上一条测试在修复后恒为绿；本测试才是唯一有效守卫。
     - `test_future_annotations_import_present`：断言 `runner.py` 首部存在 `from __future__ import annotations`。
  5. （可选，不阻塞本 Task）在 CI 增加 `python3.12` / `python3.13` matrix job：建对应版本 venv → `pip install -e .` → `pytest broca/tests/test_runner_module_imports.py`。仓库若无 CI 配置，则把该命令写入 Task 1.5 的验证清单并在 PR 描述中记录「未在 3.12 实跑」。
- **预期产出**：
  - `broca/session_runner/runner.py` 修改 2 处
  - 新增 `broca/tests/test_runner_module_imports.py`（4 个测试）
- **验收标准**：
  - [ ] `venv/bin/python -c "import broca.session_runner.runner as m; m.__annotations__"` 无异常
  - [ ] `venv/bin/python -m pytest broca/tests/test_runner_module_imports.py -q` 全绿（4 例）
  - [ ] `test_module_level_annotations_are_all_bound` 通过，且**故意删掉 `TYPE_CHECKING` 下的 `AgentFactory` import 后该测试变红**（证明守门有效，不是空转 AC）
  - [ ] `grep -n "^from __future__ import annotations" broca/session_runner/runner.py` 有结果
  - [ ] `grep -rn "AgentFactory" broca/session_runner/runner.py` 中每一处出现都有明确 import 或 TYPE_CHECKING 守卫

---

#### Task 1.2: 重构子进程启动命令（P0-2 + P0-3）

- **目标**：消除 `shell=True` 与参数拼接，改用 `sys.executable` + argv 列表，并替换不安全的 `preexec_fn`。
- **步骤**：
  1. 删除 `manager.py:123-125` 的 `_find_runner_script()`，改为模块级常量：
     ```python
     RUNNER_MODULE = "broca.session_runner.runner"
     ```
  2. 重写 `manager.py:283-313` 的命令构造为 argv 列表，**并以下表为唯一契约**（`RunnerLauncher.spawn` 与 `runner.parse_args` 必须逐项一致）：

     | 参数 | 处置 | 用途 |
     |---|---|---|
     | `--session-id` | 保留（必需） | 会话标识 |
     | `--workspace` | 保留 | 仅用于启动日志（`cwd` 由父进程 `Popen(cwd=...)` 指定） |
     | `--log-file` / `--log-level` | 保留 | 日志配置 |
     | `--config` | 保留 | `get_configs(config_path=...)` |
     | `--provider` / `--model` | **本 Task 删除** | `runner.py` 中仅出现在一行启动日志里，无实际用途 |

     ```python
     argv = [sys.executable, "-m", RUNNER_MODULE,
             "--session-id", session_id,
             "--log-file", log_file,
             "--log-level", "INFO"]
     if workspace:   argv += ["--workspace", workspace]
     if config_path: argv += ["--config", config_path]
     ```
     同步删除 `runner.py:71-73` 的 `--provider` / `--model` argparse 定义与 `runner.py:650-658` 日志中的对应字段。
     **这一步必须在 Phase 1 完成**：否则 Task 3.4「删除未使用的 CLI 参数」会让 Phase 3 起的子进程直接 `error: unrecognized arguments` 并退出（原计划的跨阶段契约断裂）。
     删除 `--config "{path}"` 的手工双引号。
     **`IPCSessionRunner.start_session` 的 `provider` / `model` 形参保留但不再使用**：`broca-web/backend/app/api/session.py:39-44` 仍在传这两个值，ABC 也以 `**kwargs` 声明，直接删形参会破调用方。本 Task 在 docstring 标注「已废弃，不参与子进程启动」；彻底删除留到 Task 4.1（那时 API 层已改为只依赖 ABC，可一并清理调用点）。
  3. 修改 `manager.py:325-340` 的 `Popen`：
     - `shell=False`
     - `preexec_fn=os.setsid` → `start_new_session=True`（`sys.platform != "win32"` 时才传；Windows 传 `creationflags=subprocess.CREATE_NEW_PROCESS_GROUP`）
     - 保留 `stdout/stderr=DEVNULL`、`env`、`cwd`
  4. **保留并强化 `env["PYTHONPATH"]` 注入（必须，不是兜底）**：把仓库根插到 `env["PYTHONPATH"]` 首位。
     原因：`Popen(cwd=workspace)` 下 `-m broca.session_runner.runner` 的模块解析会优先命中 `venv/lib/python3.14/site-packages/broca/`（实测存在完整旧副本），**删掉 PYTHONPATH 就等于跑旧代码**，且很难察觉。
     同时删除 `env.pop("VIRTUAL_ENV")` / `env.pop("VIRTUAL_ENV_PROMPT")`——改用 `sys.executable` 后无需污染环境。
  5. `logger.info("Starting runner for session %s: %s", session_id, argv)` 改为记录列表，不要 `" ".join` 后记录（避免日志与真实 argv 不一致）。
  6. 新增回归测试 `broca/tests/test_runner_launcher.py`：
     - `test_argv_quotes_path_with_spaces`：workspace 含空格时，断言 `Popen` 收到的 `args` 是 list 且 workspace 是单个元素
     - `test_uses_sys_executable`：断言 `argv[0] == sys.executable`
     - `test_no_shell_true`：断言 `Popen` 的 `shell` 参数为 `False`
     - `test_start_new_session_not_preexec_fn`：断言 `preexec_fn` 未被传入
     - `test_argv_matches_runner_argparse`：用 `ast` 提取 `runner.parse_args` 中所有 `--xxx` 选项名，断言与 `RunnerLauncher` 拼出的 argv 选项集合完全一致（**长期守卫 argv 契约**，Task 3.4 也必须让它保持绿）
     - `test_pythonpath_points_to_repo_root`：断言传给 `Popen` 的 `env["PYTHONPATH"]` 首项是仓库根；并用该 env 实跑 `[sys.executable, "-c", "import broca; print(broca.__file__)"]`，断言输出在仓库内（防跑 site-packages 旧副本）
  7. 新增集成测试 `broca/tests/test_runner_launcher_integration.py`（`@pytest.mark.integration`，无 LLM / 无 DB 依赖）：
     - `test_session_lifecycle_with_spaced_workspace`：`workspace = tmp_path / "My Project" / "demo"`，先起一个真实 `IPCServer`，再用生成的 argv 以 `cwd=workspace` 启动真实子进程，断言 stderr 中出现 `IPC client connected`，且**不出现** `unrecognized arguments` / `No such file or directory`，然后关闭 server 与子进程。用该测试**替代原「手工跑一次含空格路径」**。
     集成测试通过 `BROCA_RUN_INTEGRATION=1` 启用，默认 `skip`（CI 中设置该环境变量）。
- **预期产出**：
  - `manager.py` 命令构造与 `Popen` 两段重写
  - 新增 `broca/tests/test_runner_launcher.py`（6 个测试，`subprocess.Popen` 用 `unittest.mock.patch` 拦截）
  - 新增 `broca/tests/test_runner_launcher_integration.py`（1 个集成测试）
- **验收标准**：
  - [ ] `grep -n "shell=True" broca/session_runner/manager.py` 无结果
  - [ ] `grep -n "preexec_fn" broca/session_runner/manager.py` 无结果
  - [ ] `grep -n '"python -m' broca/session_runner/manager.py` 无结果
  - [ ] `grep -nE -- "--provider|--model" broca/session_runner/manager.py broca/session_runner/runner.py` 无结果（argv 契约已收敛）
  - [ ] `test_pythonpath_points_to_repo_root` 通过：`broca.__file__` 在仓库内（**PYTHONPATH 保留且指向仓库根**）
  - [ ] `test_argv_matches_runner_argparse` 通过：argv 选项集合与 argparse 完全一致
  - [ ] `test_session_lifecycle_with_spaced_workspace`（集成，`BROCA_RUN_INTEGRATION=1`）通过：stderr 含 `IPC client connected`、不含 `unrecognized arguments`
  - [ ] 上述 7 个新测试全部通过（6 单元 + 1 集成）

---

#### Task 1.3: 修复 IPC socket 残留导致 session 永久不可启动（P0-4）

- **目标**：`IPCServer.start()` 能自动识别并清理崩溃残留的 socket 文件；IPC 地址生成集中化且不硬编码 `/tmp`。
- **步骤**：
  1. 在 `broca/session_runner/models.py` 中改造 `get_ipc_address()`：
     - 在 `models.py` 顶部补 `import hashlib` / `import os` / `import tempfile`（现有 import 只有 `sys`，三者都没有）
     - 用 `tempfile.gettempdir()` 替代硬编码 `/tmp`
     - **按剩余预算动态截断，绝不使用固定的 `session_id[:64]`**。AF_UNIX 路径上限 108 字节，而 macOS 上 `tempfile.gettempdir()` 实测为 **48** 字符：`48 + 1 + len("broca_runner_") + 64 + len(".sock") = 131 > 108`。固定 64 会让开发机上**每次** `start_session` 都抛 `OSError: AF_UNIX path too long`——即把 P0-4 换成一个新的 P0。（即便标准 36 字符 UUID 也是 103 字符，超过下面 100 的预算。）
       ```python
       AF_UNIX_PATH_MAX = 108
       AF_UNIX_PATH_BUDGET = 100          # 预留 8 字节余量
       _PREFIX, _SUFFIX = "broca_runner_", ".sock"

       def _socket_basename(session_id: str, budget: int) -> str:
           # 超长 id 用摘要：长度恒定，且避免「两个长 id 截断后同名」
           if budget <= 0 or len(session_id) > budget:
               return f"{_PREFIX}{hashlib.sha1(session_id.encode()).hexdigest()[:16]}{_SUFFIX}"
           return f"{_PREFIX}{session_id}{_SUFFIX}"

       def get_ipc_address(session_id: str) -> str:
           if sys.platform == "win32":
               return rf"\\.\pipe\broca_runner_{session_id}"
           tmp = tempfile.gettempdir()
           budget = AF_UNIX_PATH_BUDGET - len(tmp) - 1 - len(_PREFIX) - len(_SUFFIX)
           return os.path.join(tmp, _socket_basename(session_id, budget))
       ```
     - 极端情况（`tempdir` 本身 > 84 字符，摘要后仍超限）：在 `IPCServer.start()` 抛带清晰指引的 `IPCConnectionError`，**不要静默截断**，也不要依赖 `assert`（`-O` 下会被移除）。
     - Windows 分支保持 `\\.\pipe\...`（命名管道无 108 字节限制）
  2. 在 `IPCServer.start()`（`ipc.py:80-96`）中，`Listener(...)` 之前插入 stale-socket 探测：
     ```python
     if self.family == "AF_UNIX" and os.path.exists(self.address):
         probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
         probe.settimeout(0.5)
         try:
             probe.connect(self.address)   # 能连上 → 有活的服务端
             probe.close()
             raise IPCConnectionError(f"IPC address {self.address} already in use by a live server")
         except (ConnectionRefusedError, FileNotFoundError, OSError):
             probe.close()
             os.unlink(self.address)       # 连不上 → 残留文件，清理
     ```
  3. 删除 `manager.py:520-531` `_cleanup_ipc_resources` 里硬编码的 `f"/tmp/broca_runner_{session_id}.sock"`，改为 `get_ipc_address(session_id)`。
  4. 消除三处重复删除同一 socket 文件：约定**只有 `IPCServer.close()` 负责删 socket 文件**，`manager._cleanup_ipc_resources` 与 `_cleanup_runner` 只调用 `ipc_server.close()`。
  5. `IPCClient.connect()`（`ipc.py:277-303`）加短重试：3 次 × 0.5s，覆盖「server 刚 bind、client 抢先 connect」的窗口。
  6. 新增回归测试 `broca/tests/test_ipc_socket_cleanup.py`：
     - `test_stale_socket_is_unlinked`：手工创建一个普通 socket 文件（不 listen），调 `IPCServer.start()`，断言成功且旧文件被清理
     - `test_live_socket_is_rejected`：起一个真的 `IPCServer`，再对同一 session 起第二个，断言抛 `IPCConnectionError` 且**不删除**活着的 socket
     - `test_address_not_hardcoded_tmp`：断言 `get_ipc_address()` 前缀是 `tempfile.gettempdir()`
     - `test_address_length_guard`：传 200 字符 session_id，断言 `len(path) <= 100` **且用真实 `tempfile.gettempdir()` 计算**（不写死 108）；再断言两个不同的 200 字符 id 生成**不同**路径（摘要不碰撞）；再断言 36 字符 UUID 也满足 `<= 100`（macOS 下为 103 → 必须走摘要分支）
  7. 新增集成测试 `broca/tests/test_ipc_socket_cleanup.py::test_restart_after_sigkill`（`@pytest.mark.integration`）：
     循环 3 次：`subprocess.Popen([sys.executable, "-c", <脚本>])` 让子进程 `IPCServer.start()` 并 `accept()` → `os.kill(pid, 9)` → 主进程立刻 `IPCServer.start()` 同一 session_id，断言不抛 `EADDRINUSE`。用该测试**替代原「手工 kill -9 三次」**。
- **预期产出**：
  - `models.py:get_ipc_address` 改造
  - `ipc.py:IPCServer.start` + `IPCClient.connect` 改造
  - `manager.py:_cleanup_ipc_resources` 去硬编码
  - 新增 `broca/tests/test_ipc_socket_cleanup.py`（5 个测试：4 单元 + 1 集成）
- **验收标准**：
  - [ ] `grep -rn '"/tmp/broca_runner' broca/session_runner/` 无结果
  - [ ] `venv/bin/python -c "from broca.session_runner.models import get_ipc_address as g; import tempfile; p=g('x'*200); print(len(p), p); assert len(p) <= 100 and p.startswith(tempfile.gettempdir())"` 通过（**在 macOS 真实 tempdir=48 字符下也成立**）
  - [ ] 手工在 `tempfile.gettempdir()` 下创建 `broca_runner_<id>.sock` 后调 `start_session`，能成功启动
  - [ ] 5 个新测试全部通过（4 单元 + 1 集成）
  - [ ] `test_restart_after_sigkill`（集成）：真实子进程 bind → `os.kill(pid, 9)` → 重新 bind，循环 3 次全部成功

---

#### Task 1.4: 区分「优雅停止」与「进程崩溃」（P0-5 + P2-3）

- **目标**：用户主动停止不再被巡检判定为崩溃；`SHUTTING_DOWN` 状态对外可见。
- **步骤**：
  1. `models.py:RunnerProcessInfo` 增加字段 `stop_requested: bool = False`。
  2. `manager.stop_session()`（`manager.py:534-633`）：
     - 删除 `self._runners.pop(session_id, None)`（保留条目，让状态对外可见）
     - 改为 `runner_info.status = RunnerStatus.SHUTTING_DOWN` + `runner_info.stop_requested = True`
     - 等待进程退出的逻辑改到 Task 2.4 处理（本 Task 先保留同步 wait，仅加注释标注 `# Phase 2 Task 2.4 改为 asyncio.to_thread`）
     - 进程确认退出后调用新增的 `_converge_stopped_runner(session_id)`
  3. 新增 `manager._converge_stopped_runner(session_id)`：
     - 写库为 `dead`，`error_message = "Stopped by user"`
     - `await self._trigger_event("session_stopped", runner_info)`（**不是** `session_crashed`）
     - 从 registry 移除、清理 IPC、`_remove_runner_from_db()`
  4. 修改 `_check_heartbeats()`（`manager.py:1150-1165`）的进程维度判定：
     ```python
     if returncode is not None:
         if runner_info.stop_requested or runner_info.status == RunnerStatus.SHUTTING_DOWN:
             stopped_sessions.append(session_id)     # 走优雅停止收敛
         else:
             runner_info.status = RunnerStatus.DEAD
             runner_info.error_message = f"Process exited with code {returncode}"
             dead_sessions.append(session_id)        # 走崩溃收敛
         continue
     ```
  5. 循环末尾按 `stopped_sessions` → `_converge_stopped_runner`、`dead_sessions` → `_converge_dead_runner` 分别处理。
  6. 改造 `broca-web/backend/app/api/session_runner.py:108-155` 的 `stop_runner`：删除对 `runner_manager._runners` / `._ipc_servers` 的直接访问，改为调用新增的 `runner_manager.request_stop(session_id) -> dict`（返回 `{"session_id", "status", "message"}`，内部完成标记 + 发 `CMD_SHUTDOWN` + 返回 `"stopping"`）。
  7. **同步把 `request_stop` 加进 ABC**（1 行签名，不改变架构）：在 `broca/components/session_runner.py` 追加
     ```python
     @abstractmethod
     async def request_stop(self, session_id: str) -> dict: ...
     ```
     否则 Phase 1 结束时 API 层会调用一个不在 ABC 上的方法，同时违反「API 只依赖 ABC」与「Phase 1 不改架构」两条约束，且 Task 4.1 的 `test_abc_covers_all_api_calls` 在此之前一直是红的。ABC 其余 8 个方法仍在 Task 4.1 补齐（Task 3.5 明确不触碰 ABC）。
  8. 新增回归测试 `broca/tests/test_runner_stop_semantics.py`：
     - `test_user_stop_emits_session_stopped_not_crashed`
     - `test_stop_requested_survives_heartbeat_check`
     - `test_shutting_down_status_visible_via_get_session_status`
     - `test_unexpected_exit_still_emits_session_crashed`
     - `test_request_stop_does_not_touch_private_attrs`（断言 API 层不再引用 `_runners`）
     - `test_request_stop_declared_in_abc`（断言 `request_stop` 在 `SessionRunner.__abstractmethods__` 中，且 `IPCSessionRunner.__abstractmethods__` 不含它）
- **预期产出**：
  - `models.py` +1 字段
  - `manager.py` 新增 `_converge_stopped_runner` + `request_stop`，改造 `stop_session` 与 `_check_heartbeats`
  - `broca-web/backend/app/api/session_runner.py:stop_runner` 重写
  - `broca/components/session_runner.py` +1 抽象方法（`request_stop`）
  - 新增 `broca/tests/test_runner_stop_semantics.py`（6 个测试）
- **验收标准**：
  - [ ] 主动 stop 后，`_trigger_event` 收到 `session_stopped`，`session_crashed` 计数为 0
  - [ ] stop 进行中调用 `get_session_status()`，返回 `status == "shutting_down"`（非 `None`）
  - [ ] 非主动退出（`poll()` 返回非 0）仍触发 `session_crashed`
  - [ ] `grep -n "_runners\|_ipc_servers" broca-web/backend/app/api/session_runner.py` 无结果
  - [ ] `request_stop` 已在 ABC 中且 `IPCSessionRunner.__abstractmethods__` 不含它（`test_request_stop_declared_in_abc`）
  - [ ] 6 个新测试全部通过

---

#### Task 1.5: 更新受影响的现有测试并建立基线

- **目标**：让 Phase 1 的改动不破坏既有 27 例测试，并建立后续阶段的测试基线。
- **步骤**：
  1. 运行 `venv/bin/python -m pytest broca/tests/test_runner_heartbeat.py broca/tests/test_runner_restore.py -q`。**预期失败范围是封闭的**——Task 1.2/1.4 只触碰下表 3 个私有属性引用（其余 17 个要到 Phase 2/3 才变），照表逐条改即可，不存在「不知道修完没有」的开放式收尾：

     | 属性 | 位置 | 期望改动 |
     |---|---|---|
     | `_runners` | `test_runner_heartbeat.py`（多处）、`stop_session` 相关用例 | 字段仍在（Task 2.3 才收敛为 `_registry`）；但 `stop_session` 不再 `pop` → 断言改为「stop 后条目仍在且 `status == shutting_down`」 |
     | `_ipc_servers` | `test_runner_heartbeat.py` | 不变 |
     | `_cleanup_ipc_resources` | `test_runner_heartbeat.py` | 内部改用 `get_ipc_address()`，断言不变 |
     | `_find_runner_script` | 无测试引用 | 已删除，无需改动 |

     目标：**27 例 → 27 例全绿**（不新增、不删除用例）。
  2. 在 `test_runner_heartbeat.py` 的 fixture 中补 `mgr._runners.clear()` 之外的新状态（`stop_requested` 相关），确保测试隔离。
  3. 运行 `venv/bin/python -m pytest broca-web/tests/integration/test_api_session_runner.py -q`，修复 `stop_runner` 签名变化导致的失败（`patch` 目标改为 `request_stop`）。
  4. 在 `broca/tests/conftest.py`（已存在）加一个 session 级 fixture，负责在测试结束后清理 `tempfile.gettempdir()` 下所有 `broca_runner_*.sock`，避免测试互相污染。
- **预期产出**：
  - 现有测试全绿
  - `broca/tests/conftest.py` 新增 socket 清理 fixture
- **验收标准**：
  - [ ] `venv/bin/python -m pytest broca/tests/test_runner_heartbeat.py broca/tests/test_runner_restore.py -q` 全绿，**且用例数仍为 27**（不因改动丢用例）
  - [ ] 下列 **7 个文件**合跑全绿，总数 **≥ 49**：`test_runner_heartbeat.py`(15) + `test_runner_restore.py`(12) + `test_runner_module_imports.py`(4) + `test_runner_launcher.py`(6) + `test_runner_launcher_integration.py`(1) + `test_ipc_socket_cleanup.py`(5) + `test_runner_stop_semantics.py`(6) = **49**
  - [ ] `BROCA_RUN_INTEGRATION=1 venv/bin/python -m pytest broca/tests/ -q -m integration -k runner` 全绿（覆盖 1.2/1.3 的集成用例）
  - [ ] `venv/bin/python -m pytest broca-web/tests/integration/test_api_session_runner.py -q` 全绿
  - [ ] 连续运行上述测试 3 次，无 flaky（重点看 socket 残留与单例状态）

---

### Phase 2: 拆分传输层、持久层与进程层，解除事件循环阻塞

**目标**：把 `manager.py` 中三块边界清晰的职责（IPC 传输、DB 持久化、进程启动/回收）抽成独立模块，并把所有阻塞调用移出事件循环。本阶段结束后 `manager.py` 行数下降 ≥ 40%，且 `stop_session` / `shutdown_all` 不再冻结事件循环。

**阶段验收标准**：
- [ ] `manager.py` 行数 ≤ 950
- [ ] `broca/session_runner/` 下所有 `async def` 函数体内无同步阻塞调用（`process.wait`、`time.sleep`、`cpu_percent(interval>0)`）
- [ ] `stop_session` 期间事件循环心跳不被阻塞：mock 一个 `wait()` 阻塞 1s 的 process，期间跑每 20ms tick 的计数器，**tick ≥ 10**（若同步阻塞则为 0~2，相差一个数量级）。**不使用「5s 内 ≥ 80」这类贴近理论上限（5s/50ms=100，即 80% 占空）的阈值**——共享 CI 上必然 flaky
- [ ] Phase 1 全部测试仍绿

---

#### Task 2.1: 抽取 `transport/` 消除 Server/Client 重复

- **目标**：`ipc.py` 拆为 `transport/{base,addresses,server,client}.py`，公共逻辑收敛到 `_BaseIPC`。
- **步骤**：
  1. 新建 `broca/session_runner/transport/addresses.py`，迁入 `models.py` 的 `get_ipc_address` / `get_ipc_family`（Task 1.3 已就地改造的实现）。`models.py` 中改为**一行转发**：`from broca.session_runner.transport.addresses import get_ipc_address, get_ipc_family  # noqa: F401`，保证 `from broca.session_runner.models import get_ipc_address` 的既有引用不变，且两处是**同一个对象**（AC 用 `is` 断言）。
  2. 新建 `transport/base.py`：
     ```python
     class _BaseIPC:
         session_id: str
         address: str
         family: str
         _connection: Any
         _send_lock: threading.Lock
         _recv_lock: threading.Lock
         def _encode(self, msg: IPCMessage) -> str: ...
         def _decode(self, raw: Any) -> IPCMessage: ...
         def send_message(self, msg: IPCMessage) -> None:   # 统一加 _send_lock
         def receive_message(self, timeout: float = 10.0) -> IPCMessage | None:
         def close(self) -> None:
     ```
     注意：`_send_lock` **必须在 Client 也生效**（修 Windows 命名管道并发写问题，见 P2 表）。
  3. `transport/server.py` 迁入 `IPCServer`（继承 `_BaseIPC`），保留 `accept()` / `start()` / stale-socket 探测（Task 1.3 成果）。
  4. `transport/client.py` 迁入 `IPCClient`（继承 `_BaseIPC`），保留 `connect()` 重试。
  5. 删除 `ipc.py`，改为 `broca/session_runner/ipc.py` 薄壳 re-export（`from broca.session_runner.transport import *`），保证 `from broca.session_runner.ipc import ...` 的既有引用（`manager.py`、`runner.py`、`orchestrator_runner.py`、两个测试文件）不破。
  6. 删除死代码 `IPCServer._handlers` / `register_handler` / `_running`。**直接删除，不做「先留半成品」**——Task 3.3 的 `MessageRouter` 是实例级路由（语义不同），不需要复用这套模块级注册表。
  7. 修正 `IPCChannel` Protocol：`async def start(self) -> None`，与实际实现对齐。
  8. **随改随迁测试**：`test_runner_heartbeat.py` 中引用 `_ipc_listener_loop` / `_ipc_listener_threads` 的 fixture 在本 Task 内一并改为「直接构造 `IPCServer` / `IPCClient` 对」或「注入 `handle.ipc`」（`RunnerHandle` 在 Task 2.3 落地）。**不允许把测试迁移集中推到 Task 3.5**——否则 Task 2.1~3.4 期间 Phase 1 的测试一直是红的，与本计划「每个 Task 的 AC 都要求 Phase 1 测试仍绿」直接冲突。
  9. 新增 `broca/tests/test_ipc_transport.py`：
     - `test_server_client_roundtrip`：起 server + client，双向收发各 10 条
     - `test_concurrent_send_is_not_interleaved`：4 线程并发 `send_message` 各 100 条，接收端断言 400 条且 JSON 全部可解析（验证 `_send_lock`）
     - `test_send_and_recv_do_not_block_each_other`：send 线程持续发，recv 侧 `poll(2s)` 期间 send 延迟 < 100ms（验证双锁分离）
     - `test_close_is_idempotent`：连续 `close()` 3 次不抛异常
- **预期产出**：
  - 新增 `transport/` 目录 4 个文件
  - `ipc.py` 变薄壳
  - 新增 `broca/tests/test_ipc_transport.py`（4 个测试）
- **验收标准**：
  - [ ] `wc -l broca/session_runner/ipc.py` < 40
  - [ ] `transport/base.py` 被 Server 与 Client 同时继承（`grep "class IPCServer(_BaseIPC)"`、`grep "class IPCClient(_BaseIPC)"`）
  - [ ] `send_message` 的锁保护在两个子类中都不再重复实现
  - [ ] `venv/bin/python -c "from broca.session_runner.models import get_ipc_address as a; from broca.session_runner.transport.addresses import get_ipc_address as b; assert a is b"` 通过（re-export 为同一对象）
  - [ ] 4 个新测试通过，且 `test_concurrent_send_is_not_interleaved` 连续跑 20 次无 flaky
  - [ ] Phase 1 全部测试仍绿

---

#### Task 2.2: 抽取 `repository.py` 收敛 DB 直写

- **目标**：把 `manager.py` 中 5 处 `async with db_manager.get_session()` 直写 SQLModel 的逻辑收敛到 `RunnerRepository`。
- **步骤**：
  1. 新建 `broca/session_runner/repository.py`：
     ```python
     class RunnerRepository:
         async def upsert(self, info: RunnerProcessInfo) -> None
         async def upsert_many(self, infos: Iterable[RunnerProcessInfo]) -> int
         async def delete(self, session_id: str) -> bool
         async def get(self, session_id: str) -> Optional[RunnerProcessInfo]
         async def list_active(self) -> list[RunnerProcessInfo]      # status != dead
         async def set_agent_status(self, session_id: str, statuses: dict[str, str]) -> int
         async def mark_agents_disconnected(self, session_id: str) -> int
     ```
  2. `upsert` 用 SQLite 原生 upsert（`from sqlalchemy.dialects.sqlite import insert`，`on_conflict_do_update(index_elements=["session_id"], set_={...})`），替代「先 SELECT 再 UPDATE」。
  3. `upsert_many` 在**单个 DB session 内**循环 add + 一次 `commit()`，把 N 次往返降为 1 次（P1-5 的「单事务批量」部分）。
     **P1-5 分工边界（避免与 Task 4.3 重复实现）**：本 Task 只做「单事务批量」，**不做**「时间维度聚合」——`persist_interval` 合并归 Task 4.3，本 Task 不实现、也不新增相关配置项。
  4. `manager.py` 中 `_save_runner_to_db` / `_remove_runner_from_db` / `_get_runner_from_db` / `_mark_session_agents_disconnected` / `_sync_agent_statuses` 全部改为委托 `self._repo.<method>()`，方法体只保留缓存更新与日志。
  5. 删除 `manager.py` 中所有函数内 `import sqlmodel` / `from broca.session.models import ...`（8 处）。
  6. 新增 `broca/tests/test_runner_repository.py`（用内存 SQLite）：
     - `test_upsert_insert_then_update`：同 session 连续 upsert 两次，断言只有一行且字段被更新
     - `test_upsert_many_single_transaction`：断言 N 条只触发 1 次 commit（用 mock 计数）
     - `test_mark_agents_disconnected_clears_cache_hook`：断言返回值是受影响行数
     - `test_get_returns_none_for_missing`
- **预期产出**：
  - 新增 `broca/session_runner/repository.py`
  - `manager.py` 5 个方法瘦身为委托
  - 新增 `broca/tests/test_runner_repository.py`（4 个测试）
- **验收标准**：
  - [ ] `grep -c "db_manager.get_session" broca/session_runner/manager.py` == 0
  - [ ] `grep -c "import sqlmodel" broca/session_runner/manager.py` == 0
  - [ ] `manager.py` 行数 ≤ 1300（相对 Phase 1 下降 ≥ 300）
  - [ ] `_persist_runner_state` 处理 5 个 runner 时只产生 1 次 DB commit（用 mock 断言）
  - [ ] 4 个新测试通过，Phase 1 测试全绿

---

#### Task 2.3: 抽取 `process/` 三层，防 PID 复用误杀

- **目标**：把进程启动、判活/杀进程、内存注册表拆成 `launcher.py` / `reaper.py` / `registry.py`，并引入多因子判活（P2-1）。
- **步骤**：
  1. 新建 `process/launcher.py`：
     ```python
     class RunnerLauncher:
         def spawn(self, session_id, workspace, log_file, config_path) -> subprocess.Popen
     ```
     内部即 Task 1.2 的 argv 构造逻辑，从 manager 迁出。**`provider` / `model` 形参不再保留**——它们对应的 CLI 参数已在 Task 1.2 删除，留着就是两个无消费者的死参数（`test_argv_matches_runner_argparse` 也不会覆盖到它们）。
  2. 新建 `process/reaper.py`：
     ```python
     class RunnerReaper:
         def is_alive(self, handle: RunnerHandle) -> bool          # 多因子校验
         async def terminate(self, handle: RunnerHandle, timeout: float = 5.0) -> bool
         async def terminate_by_pid(self, pid: int, *, session_id: str) -> bool
         async def terminate_orphans(self, records: list[RunnerProcessInfo]) -> int
     ```
     `is_alive` 三因子：① `psutil.pid_exists` ② `abs(create_time - started_at.timestamp()) < 5` ③ `cmdline()` 同时包含 `"broca.session_runner.runner"` 与 `session_id`。**任一不满足 → 返回 False 且绝不 kill。**
     **Windows 降级**：`cmdline()` 在 Windows 上可能返回空 list、或抛 `AccessDenied`（进程已退出/权限不足）。此时**降级为两因子**（①+②）并记 DEBUG 日志——不得因取不到 cmdline 就判死（会误杀正常 runner）。
     `terminate` 用 `asyncio.to_thread(process.wait, timeout)` + `await asyncio.sleep` 轮询，全部异步。
  3. 新建 `process/registry.py`：
     ```python
     @dataclass
     class RunnerHandle:
         info: RunnerProcessInfo
         ipc: Optional[IPCChannel] = None
         poll_thread: Optional[threading.Thread] = None
         poll_task: Optional[asyncio.Task] = None
         agent_status_cache: Optional[dict] = None
         db_state_cache: Optional[tuple] = None
         pending_responses: dict = field(default_factory=dict)

     class RunnerRegistry:
         def add(self, handle) -> None
         def get(self, session_id) -> Optional[RunnerHandle]
         def pop(self, session_id) -> Optional[RunnerHandle]
         def all(self) -> list[RunnerHandle]
         def active_count(self) -> int            # 修正 P2-2：计入 ERROR/SHUTTING_DOWN
         def clear(self) -> None
     ```
     内部用 `threading.RLock` 保护（poll 线程与事件循环都会访问）。
  4. `manager.py` 的 `_runners` / `_ipc_servers` / `_ipc_listener_threads` / `_ipc_listener_tasks` / `_agent_status_cache` / `_db_state_cache` / `_pending_responses` 七个字段替换为单个 `self._registry: RunnerRegistry`。
  5. `_get_active_runner_count()` 改为 `self._registry.active_count()`，并把判定改为「进程存活即计数」（`ALIVE/STARTING/ERROR/SHUTTING_DOWN`），修正 P2-2。
  6. `_find_runner_process_by_pid` / `_force_kill_process_by_pid` / `_force_kill_process` / `_kill_runner` 全部删除，改调 `self._reaper`。
  7. `restore_active_sessions()` 改用 `self._repo.list_active()` + `self._reaper.terminate_orphans()`；顺带修掉「detached ORM 对象 re-add 到新 session」的反模式（P2 表第 7 条）——改为先读出纯数据 `list[RunnerProcessInfo]`，再按需 upsert。
  8. 新增 `broca/tests/test_runner_reaper.py`：
     - `test_pid_reuse_is_not_killed`：构造 `started_at` 与目标进程 `create_time` 相差 1 小时的记录，断言 `is_alive() == False` 且 `terminate` 未被调用
     - `test_cmdline_mismatch_is_not_killed`：`cmdline()` 不含 session_id，断言不 kill
     - `test_windows_empty_cmdline_degrades_to_two_factors`：patch `psutil` 让 `cmdline()` 返回 `[]`（模拟 Windows），断言 `is_alive()` 仍按 ①+② 判定为 True，且未调用 `terminate`
     - `test_genuine_runner_is_killed`：mock 三因子全匹配，断言 `terminate` 被调用
     - `test_registry_active_count_includes_error_status`
     - `test_registry_is_thread_safe`：8 线程并发 add/pop 各 1000 次，断言无异常且最终一致
- **预期产出**：
  - 新增 `process/` 目录 3 个文件
  - `manager.py` 7 个状态字段收敛为 1 个 `_registry`
  - 新增 `broca/tests/test_runner_reaper.py`（6 个测试）
- **验收标准**：
  - [ ] `grep -c "_ipc_servers\|_agent_status_cache\|_db_state_cache\|_ipc_listener_threads" broca/session_runner/manager.py` == 0
  - [ ] `grep -n "pid_exists" broca/session_runner/manager.py` 无结果（已迁至 reaper）
  - [ ] `restore_active_sessions` 不再对 detached ORM 对象调用 `session.add()`
  - [ ] 6 个新测试通过，Phase 1 与 Task 2.1/2.2 测试全绿
  - [ ] 需同步更新 `test_runner_heartbeat.py` / `test_runner_restore.py` 中对旧字段的引用（fixture 改为 `mgr._registry.clear()`）

---

#### Task 2.4: 解除事件循环阻塞（P1-1 / P1-2 / P1-3）

- **目标**：`async def` 中不再出现任何同步阻塞调用。
- **步骤**：
  1. `stop_session`（`manager.py:611`）：`runner_info.process.wait(timeout=timeout)` → `await asyncio.to_thread(runner_info.process.wait, timeout)`。
  2. `_force_kill_process` 的同步实现已由 Task 2.3 迁入 `RunnerReaper.terminate()`，确认其内部全部是 `await asyncio.sleep` 轮询 + `asyncio.to_thread(wait)`。
  3. `get_resource_usage()`（`manager.py:1595-1628`）：**删除**（已决策，见「已决策事项」）。全仓无调用方，方法与其测试一起删，不保留「异步化」版本——删除后 `cpu_percent(interval=0.1)` 的同步 sleep 自然消失，无需再包 `to_thread`。
  4. 全量扫描：写一个一次性脚本，用 `ast` 找出 `broca/session_runner/` 下所有 `AsyncFunctionDef` 内未 `await` 的 `.wait(` / `.sleep(` / `.join(` / `cpu_percent(` 调用，逐个人工确认。
  5. 新增 `broca/tests/test_runner_no_blocking.py`：
     - `test_stop_session_does_not_block_event_loop`：mock 一个 `wait()` 会阻塞 1s 的 process，在 `stop_session` 期间跑 `asyncio.create_task` 计数 tick（每 20ms），断言 **tick ≥ 10**（若同步阻塞则为 0~2，相差一个数量级；**不用 ≥ 40 这类贴近上限的阈值**）
     - `test_ast_no_blocking_calls_in_async`：用 `ast` 静态扫描 `broca/session_runner/**/*.py`，断言 `async def` 内不存在白名单外的阻塞调用
- **预期产出**：
  - `manager.py` 阻塞调用清零
  - 新增 `broca/tests/test_runner_no_blocking.py`（2 个测试，第 2 个是长期守卫）
- **验收标准**：
  - [ ] 上述 ast 扫描脚本输出为空
  - [ ] `test_stop_session_does_not_block_event_loop` 通过
  - [ ] `shutdown_all()` 停止 3 个 mock runner（每个 wait 阻塞 1s）时，事件循环 tick 数 **≥ 30**（3s 理论上限 150，取 1/5 作数量级判据；串行同步阻塞时为 0~2）
  - [ ] Phase 1 与 Task 2.1~2.3 测试全绿

---

#### Task 2.5: 引入 `TaskSet` 替代裸 `ensure_future` / `create_task`（P1-4）

- **目标**：所有 fire-and-forget 任务——**`asyncio.ensure_future` 与裸 `asyncio.create_task` 全部计入**——都被持有引用、异常被记录，且同类任务不重复堆积。
- **步骤**：
  1. 新建 `broca/session_runner/events.py`（本 Task 先只放任务容器，事件总线的完整能力在 Task 3.2 补齐）：
     ```python
     class TaskSet:
         def __init__(self, name: str)
         def spawn(self, coro) -> asyncio.Task        # 持引用 + add_done_callback 记异常 + 完成后自动移除
         async def aclose(self) -> None
     ```
  2. **全量改造点清单**（实测：`ensure_future` 2 处 + `asyncio.create_task` 6 处）：

     | 位置 | 现状 | 处置 |
     |---|---|---|
     | `manager.py:920` | `asyncio.ensure_future(self._sync_agent_statuses(...))` | → `self._tasks.spawn(...)` |
     | `manager.py:938` | `asyncio.ensure_future(self._trigger_event(...))` | → `self._tasks.spawn(...)` |
     | `manager.py:1015` | `asyncio.create_task(handler(session_id, msg))`（crew 事件回调，**无引用、异常静默**） | → `self._tasks.spawn(...)` |
     | `runner.py:333` | `asyncio.create_task(_run_crew_safe())`（**无引用、异常静默**） | → 由 `SessionRunnerProcess` 持有 `self._crew_task`，并在 `done_callback` 记 ERROR（Task 3.4 落地） |
     | `runner.py:564` | `asyncio.create_task(agent.start())` | 已存入 `agent_tasks` 列表 → **白名单** |
     | `manager.py:438` | `self._ipc_listener_tasks[sid] = asyncio.create_task(...)` | 已持引用 → **白名单** |
     | `manager.py:1058` | `self._heartbeat_monitor_task = asyncio.create_task(...)` | 已持引用 → **白名单** |
     | `orchestrator_runner.py:152` | `self._task = asyncio.create_task(...)` | 已持引用 → **白名单** |

     runner 侧与 manager 侧分属两个进程，**runner 不引入 `TaskSet`**，用单个 `self._crew_task` 字段即可。
  3. `manager.py:920` / `:938` / `:1015` 三处改为 `self._tasks.spawn(...)`。
  4. 给 `_sync_agent_statuses` 加**去重节流**：在 `RunnerHandle` 上存 `agent_status_sync_task: asyncio.Task | None`，若上一个未完成则跳过本次（或 coalesce：记录 pending payload，完成后立即跑最新一次）。
  5. `manager.py:1433` 的 `asyncio.sleep(0.5)` 错误退避保持不变，但循环退出路径要 `await self._tasks.aclose()`。
  6. 新增 `broca/tests/test_runner_taskset.py`：
     - `test_spawned_task_exception_is_logged`：spawn 一个抛异常的协程，断言 logger 收到 ERROR
     - `test_task_reference_held_until_done`：`gc.collect()` 后任务仍存活
     - `test_agent_status_sync_is_coalesced`：连续 10 次心跳（间隔 1ms），断言实际 DB 写 ≤ 2 次
     - `test_no_untracked_create_task`：用 `ast` 扫描 `broca/session_runner/**/*.py` 中所有 `asyncio.create_task(` 调用，断言每个调用的结果要么被赋值给变量/属性、要么位于上表白名单行号内——防止后续新增裸 `create_task`
- **预期产出**：
  - 新增 `events.py`（TaskSet）
  - `manager.py` 3 处（`:920` / `:938` / `:1015`）替换为 `self._tasks.spawn(...)` + 节流
  - `runner.py:333` 的 `_crew_task` 持有引用（随 Task 3.4 类化落地）
  - 新增 `broca/tests/test_runner_taskset.py`（4 个测试）
- **验收标准**：
  - [ ] `grep -cE "ensure_future" broca/session_runner/` == 0
  - [ ] `grep -rnE "ensure_future|asyncio\.create_task" broca/session_runner/` 的每条命中都落在白名单（`runner.py:564` 的 `agent_tasks`、`manager.py:438` 的 `_ipc_listener_tasks`、`manager.py:1058` 的 `_heartbeat_monitor_task`、`orchestrator_runner.py:152` 的 `self._task`）内，**且 `runner.py:333` 与 `manager.py:1015` 已不在命中列表**
  - [ ] `test_no_untracked_create_task` 通过（长期守卫）
  - [ ] 4 个新测试通过
  - [ ] Phase 1 与 Task 2.1~2.4 测试全绿
  - [ ] `manager.py` 行数 ≤ 950（Phase 2 阶段验收项）

---

### Phase 3: 拆分监控与事件，`runner.py` 类化

**目标**：把心跳/健康策略、事件分发、IPC 消息路由三块从 `manager.py` 抽出；把 `runner.py` 从「8 个全局变量 + 233 行 if/elif」改造为 `SessionRunnerProcess` 类。本阶段结束后 `manager.py` 成为纯编排层，`runner.py` 可实例化、可并行测试。

**阶段验收标准**：
- [ ] `manager.py` 行数 ≤ 400（原定 350 的减行路径已把余量吃到 ≤ 55 行，任何一处迁移不彻底就会红；400 相对 1631 行仍下降 75%，足以证明「不再是 God Class」。减行来源见 Task 3.5 步骤 8）
- [ ] `broca/session_runner/` 下无模块级可变全局状态：`runner.py` 的 8 个全局变量全部消失，**且路由表不是模块级单例**——`MessageRouter` 实例由 `SessionRunnerProcess` / `IPCSessionRunner` 各自持有（见 Task 3.3），`protocol.py` 只提供类与装饰器工厂
- [ ] `runner.py` 的 `handle_ipc_command` 233 行 if/elif 链消失，改为 `await self.router.dispatch(msg, self)`
- [ ] Phase 1/2 全部测试仍绿（需同步更新测试对私有属性的依赖）

---

#### Task 3.1: 抽取 `monitor.py`（HealthPolicy + HeartbeatMonitor）

- **目标**：心跳阈值、宽限策略、巡检判定逻辑独立可测。
- **步骤**：
  1. 新建 `broca/session_runner/monitor.py`：
     ```python
     @dataclass(frozen=True)
     class HealthPolicy:
         interval: float          # 上报间隔
         timeout: float           # 判定超时
         check_interval: float    # 巡检间隔
         grace_multiplier: float = 3.0
         persist_interval: float = 60.0
         @classmethod
         def from_config(cls) -> "HealthPolicy"      # 读 configs.json execution 组
         @property
         def grace(self) -> float

     class HeartbeatMonitor:
         def __init__(self, policy: HealthPolicy, registry: RunnerRegistry, repo: RunnerRepository,
                      reaper: RunnerReaper, events: EventBus)
         async def start(self) -> None
         async def stop(self) -> None
         async def check_once(self) -> None           # 可单测的纯入口
         async def _persist_states(self) -> None      # 内部改调 repo.upsert_many
     ```
  2. 把 `manager.py` 的 `start_heartbeat_monitor` / `stop_heartbeat_monitor` / `_heartbeat_monitor_loop` / `_persist_runner_state` / `_check_heartbeats` / `_converge_dead_runner` / `_converge_stopped_runner` 全部迁入 `HeartbeatMonitor`。
  3. `_persist_runner_state` 改用 Task 2.2 的 `repo.upsert_many()`（一次 commit）。
  4. `manager.py` 只保留 `start_heartbeat_monitor()` / `stop_heartbeat_monitor()` 两个委托方法（保持 ABC 契约）。
  5. 顺带修 P2 表第 14 条：`HeartbeatMonitor.start()` 增加「本进程是否已有监控在跑」的防护，并在日志中输出 `pid`，便于多 worker 场景排查。
  6. 新增 `broca/tests/test_runner_monitor.py`：
     - `test_policy_from_config_matches_configs_json`：断言读到的三个阈值与 `configs/configs.json` 一致
     - `test_grace_period_does_not_flip_status`（从现有 heartbeat 测试迁移）
     - `test_process_exit_converges_to_dead`（迁移）
     - `test_stop_requested_converges_to_stopped`（迁移）
     - `test_persist_uses_single_commit_for_n_runners`：5 个 runner，断言 commit 次数 == 1
- **预期产出**：
  - 新增 `monitor.py`
  - `manager.py` 减少约 264 行
  - `broca/tests/test_runner_monitor.py`（5 个测试，含从旧文件迁移）
- **验收标准**：
  - [ ] `grep -n "_check_heartbeats\|_persist_runner_state\|_converge_dead_runner" broca/session_runner/manager.py` 无结果
  - [ ] `HeartbeatMonitor.check_once()` 可在不启动后台循环的情况下被单独调用并断言结果
  - [ ] 5 个测试通过；`test_persist_uses_single_commit_for_n_runners` 断言 commit == 1
  - [ ] Phase 1/2 测试全绿

---

#### Task 3.2: 抽取 `events.py`（EventBus）

- **目标**：事件注册与分发独立，`TaskSet` 与 EventBus 合并成统一模块。
- **步骤**：
  1. 在 Task 2.5 建立的 `events.py` 中新增：
     ```python
     class EventBus:
         def on(self, event: str, handler: Callable) -> None
         async def emit(self, event: str, payload: Any) -> None      # 串行 await，单个 handler 异常隔离
         def emit_soon(self, event: str, payload: Any) -> None       # 走 TaskSet.spawn
         async def aclose(self) -> None
     ```
  2. 把 `manager.py` 的 `on` / `_trigger_event` / `_handle_crew_event` 迁入。
  3. `_handle_crew_event` 中 `asyncio.create_task(handler(...))` 改为 `self._tasks.spawn(handler(...))`，消除又一处 fire-and-forget。
  4. `manager.py` 的 `on()` 保留为委托（ABC 要求）。
  5. 新增 `broca/tests/test_runner_events.py`：
     - `test_handler_exception_does_not_break_others`
     - `test_async_and_sync_handlers_both_supported`
     - `test_emit_soon_tasks_are_tracked_and_closed`
- **预期产出**：
  - `events.py` 补全 EventBus
  - `manager.py` 减少约 176 行
  - 新增 `broca/tests/test_runner_events.py`（3 个测试）
- **验收标准**：
  - [ ] `grep -n "_trigger_event\|_event_handlers" broca/session_runner/manager.py` 无结果
  - [ ] 3 个新测试通过
  - [ ] Phase 1/2 与 Task 3.1 测试全绿

---

#### Task 3.3: 抽取 `protocol.py`（消息路由注册表）

- **目标**：替换 `runner.py:169-402`（233 行）与 `manager.py:859-965`（105 行）两条 if/elif 链。
- **步骤**：
  1. **先写 10 行最小验证再动 233 行 if/elif**（这是本计划引入的唯一新机制，先证明分发能通）：两个类、三个带标记的方法、一次 `dispatch`，断言路由到正确的方法。验证通过后再迁移 `runner.py`。
  2. 新建 `broca/session_runner/protocol.py`，**只提供类与装饰器工厂，不定义模块级 router 实例**：
     ```python
     HANDLER_ATTR = "__ipc_handler__"

     class MessageRouter:
         def __init__(self, handlers: Iterable[tuple[IPCMessageType, Callable]] = ()): ...
         def register(self, msg_type: IPCMessageType, fn: Callable) -> None: ...
         def handler(self, msg_type) -> Optional[Callable]: ...
         async def dispatch(self, msg: IPCMessage, ctx: Any) -> None:
             fn = self.handler(msg.type)
             if fn is None:
                 logger.warning("No handler for %s", msg.type)
                 return
             await fn(ctx, msg)          # ← 全项目唯一调用约定：handler(ctx, msg)

         @classmethod
         def from_class(cls, target_cls: type, side: str) -> "MessageRouter":
             """扫描 target_cls（含继承链）中带 @handles 标记的**方法**"""
             router = cls()
             for _name, fn in inspect.getmembers(target_cls, predicate=inspect.isfunction):
                 marked = getattr(fn, HANDLER_ATTR, None)
                 if marked and marked[1] == side:
                     router.register(marked[0], fn)
             return router

     def handles(msg_type: IPCMessageType, *, side: str) -> Callable:
         """装饰器工厂：只给函数打标记，不产生模块级状态"""
         def deco(fn):
             setattr(fn, HANDLER_ATTR, (msg_type, side))
             return fn
         return deco
     ```
     **为什么是 `from_class` 而不是 `from_module`**：handler 是类方法（`_handle_cmd_xxx(self, msg)`），定义在**类体**里、不在模块命名空间，`from_module` 扫描模块只会得到 `None`，守卫测试会全绿假通过/全红。`inspect.getmembers(target_cls, inspect.isfunction)` 拿到的就是未绑定函数，`fn(ctx, msg)` 中 `ctx` 即 `self`，与 `_handle_cmd_xxx(self, msg)` 签名天然对齐。
     `SessionRunnerProcess.__init__` 与 `IPCSessionRunner.__init__` 各自调用 `MessageRouter.from_class(type(self), "runner"/"manager")` 构建**实例级** router。这样：① 满足 Phase 3 AC「无模块级可变全局状态」；② 测试可 per-instance 隔离（不依赖 import 副作用，也不需要一个全局 `reset()`）；③ 装饰器写法与迁移成本都很低。
  3. `runner.py` 中每个 `CMD_*` 分支抽成独立方法 `async def _handle_cmd_xxx(self, msg)`（每个 ≤ 30 条语句），用 `@handles(IPCMessageType.CMD_XXX, side="runner")` 标记。`handle_ipc_command` 变成 2 行：`await self.router.dispatch(msg, self)`（`dispatch` 内部 `await fn(ctx, msg)`，`ctx == self`）。
  4. `manager.py` 中 `EVT_HEARTBEAT` / `EVT_ERROR` / `EVT_SHUTDOWN_COMPLETE` / `EVT_STATUS_CHANGE` / 4 个 `EVT_CREW_*` / `RESPONSE` 同样抽成 `async def _handle_evt_xxx(self, msg)` 并用 `@handles(..., side="manager")` 标记，由 `IPCSessionRunner.router` 分发（调用约定同上：`await fn(self, msg)`）。
  5. **清理死代码**（P2 表第 5 条，已拍板删除）：从 `models.py` 删除 `CMD_RESTART` 与 `CMD_CREW_STATUS` 枚举值，并删除 `orchestrator_runner.get_crew_status()`（重启语义走 REST 的 `restart_session`，IPC 命令属重复语义）。删除后 `test_all_cmd_types_have_runner_handler` 会自动覆盖「不留无 handler 的命令类型」。
  6. 新增 `broca/tests/test_runner_protocol.py`：
     - `test_all_cmd_types_have_runner_handler`：用 `MessageRouter.from_class(SessionRunnerProcess, "runner")` 构建 router，遍历 `IPCMessageType` 中所有 `CMD_*`，断言 `router.handler(t)` 非 None（把死代码问题变成永久测试守卫）
     - `test_all_evt_types_have_manager_handler`：同上（`MessageRouter.from_class(IPCSessionRunner, "manager")`）
     - `test_from_class_discovers_methods`：最小用例——定义一个含 2 个 `@handles` 方法的类，断言 `from_class` 恰好发现 2 个（**直接锁住本轮修复的机制本身**，防止以后退回「按模块命名空间扫描」的错误实现）。注意：本测试的源码里**不要出现 `from_module` 字面量**，否则下面「grep 无结果」的 AC 会自相矛盾
     - `test_dispatch_passes_ctx_as_first_arg`：断言 handler 收到的第一个参数就是 `ctx`（调用约定守卫）
     - `test_router_instances_are_isolated`：同一类构建的两个 router 互不影响（验证无模块级共享状态）
     - `test_unknown_type_does_not_raise`：分发未注册类型时记 warning 且不抛
     - `test_dispatch_routes_to_correct_handler`
- **预期产出**：
  - 新增 `protocol.py`
  - `runner.py` / `manager.py` 的 if/elif 链消除
  - 新增 `broca/tests/test_runner_protocol.py`（7 个测试）
- **验收标准**：
  - [ ] `handle_ipc_command` 语句数 ≤ 5、`_handle_runner_event` 语句数 ≤ 15。**计量口径统一为 AST 语句数**（`len(node.body)`，不含空行与注释），检查命令：
        ```bash
        venv/bin/python - <<'EOF'
        import ast
        for path, names in [("broca/session_runner/runner.py", ["handle_ipc_command"]),
                            ("broca/session_runner/manager.py", ["_handle_runner_event"])]:
            tree = ast.parse(open(path).read())
            for n in ast.walk(tree):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names:
                    print(path, n.name, len(n.body))
        EOF
        ```
  - [ ] `grep -nE "^(runner_router|manager_router) *= *MessageRouter" broca/session_runner/protocol.py` 无结果（无模块级 router 实例）
  - [ ] `grep -n "from_module" broca/session_runner/protocol.py broca/tests/test_runner_protocol.py` 无结果（统一用 `from_class`）
  - [ ] `test_all_cmd_types_have_runner_handler` 与 `test_all_evt_types_have_manager_handler` 通过（死类型已删除，测试仍须通过）
  - [ ] `test_from_class_discovers_methods` 与 `test_dispatch_passes_ctx_as_first_arg` 通过（分发机制本身被守卫）
  - [ ] 7 个新测试通过，Phase 1/2 与 Task 3.1/3.2 测试全绿

---

#### Task 3.4: `runner.py` 类化（消灭 8 个全局变量）

- **目标**：`runner.py` 从过程式脚本改造为可实例化的 `SessionRunnerProcess`。
- **步骤**：
  1. 定义类骨架：
     ```python
     class SessionRunnerProcess:
         def __init__(self, args: argparse.Namespace, ipc: IPCChannel):
             self.args = args
             self.ipc = ipc
             self.running = False
             self.ipc_lost = False
             self.shutdown_event = asyncio.Event()
             self.agents: list[Agent] = []
             self.agent_factory: Any = None
             self.session_manager: Any = None
             self.crew_runner: CrewOrchestratorRunner | None = None
             self.start_time = 0.0
             self.agent_tasks: list[asyncio.Task] = []
         async def run(self) -> None
         async def _bootstrap(self) -> None            # 恢复 agent + 发 READY + connect
         async def _heartbeat_loop(self) -> None
         async def _ipc_listener_loop(self) -> None
         async def _agent_monitor_loop(self) -> None
         async def _shutdown(self) -> None
         def request_shutdown(self, reason: str) -> None   # 统一 _running=False + event.set()
     ```
  2. 8 个模块级全局变量（`_running` / `_shutdown_event` / `_ipc_lost` / `_agent_factory` / `_agents` / `_session_manager` / `_crew_runner` / `_start_time`）全部删除，改为实例属性。
  3. `request_shutdown()` 统一收敛「`running=False` + `shutdown_event.set()` + `ipc_lost` 标记」三处重复逻辑（当前散落在 4 个地方）。
  4. 修 P2 表第 4 条：`_crew_runner` 单例 → `self.crew_runner`，并在 `_handle_cmd_run_crew` 中增加「已有编排在跑」的拒绝分支（返回 `IPCStatusCode.ERROR`，payload 含 `active_crew_id`）。
  5. 修 P2 表第 8 条：`await asyncio.wait(agent_tasks, timeout=2.0)` 后检查 `done` 集合，对每个 task 调 `task.exception()` 并记 ERROR 日志。
  6. 修 `runner.py:60` 的 `os.makedirs(os.path.dirname(log_file))`：`dirname` 为空时跳过。
  7. **argv 契约收尾（不得引入新参数）**：`--provider` / `--model` 已在 Task 1.2 从 `runner.parse_args` 与 `RunnerLauncher.spawn` **同步删除**；`--workspace` 保留（仅用于启动日志，`cwd` 由父进程指定）。本步骤只做一致性校验：Task 1.2 建立的 `test_argv_matches_runner_argparse` 必须仍绿；若本 Task 需要新增任何 CLI 参数，必须同时更新 `RunnerLauncher.spawn` 与该测试。
  8. `main()` 改为：解析 args → 建 `IPCClient` → `asyncio.run(SessionRunnerProcess(args, ipc).run())`。
  9. 新增 `broca/tests/test_runner_process.py`：
     - `test_two_instances_do_not_share_state`：同时实例化两个 `SessionRunnerProcess`，断言 `agents`/`running`/`crew_runner` 互不影响
     - `test_request_shutdown_sets_all_flags`
     - `test_second_crew_is_rejected_while_first_running`
     - `test_agent_task_exception_is_logged`
- **预期产出**：
  - `runner.py` 重写为类
  - 新增 `broca/tests/test_runner_process.py`（4 个测试）
- **验收标准**：
  - [ ] `grep -nE "^_[a-z_]+ *[:=]" broca/session_runner/runner.py` 无结果（除模块常量）
  - [ ] `SessionRunnerProcess` 可被测试直接实例化，无需 monkeypatch 全局变量
  - [ ] 同一 session 提交第二个编排时返回 `IPCStatusCode.ERROR`，且第一个编排仍可 abort
  - [ ] `test_argv_matches_runner_argparse`（Task 1.2 建立）仍绿——Phase 1 的 argv 契约未被破坏
  - [ ] 4 个新测试通过，Phase 1/2 与 Task 3.1~3.3 测试全绿

---

#### Task 3.5: `manager.py` 收敛为编排层 + 更新组件契约

- **目标**：`manager.py` 只保留「把上面这些组件串起来」的编排逻辑。
- **步骤**：
  1. `IPCSessionRunner.__init__` 组装依赖：
     ```python
     self._repo = RunnerRepository()
     self._reaper = RunnerReaper()
     self._launcher = RunnerLauncher()
     self._registry = RunnerRegistry()
     self._events = EventBus()
     self._tasks = TaskSet("runner-manager")
     self._monitor = HeartbeatMonitor(policy, self._registry, self._repo, self._reaper, self._events)
     self._poller = IPCPoller(self._registry, self._events)      # Phase 4 Task 4.2 替换
     ```
  2. 保留的公共方法（全部瘦身为编排）：`start_session` / `stop_session` / `request_stop` / `restart_session` / `send_command` / `get_session_status` / `list_sessions` / `get_stats` / `on` / `start_heartbeat_monitor` / `stop_heartbeat_monitor` / `restore_active_sessions` / `shutdown_all`。
  3. `start_session`（原 207 行）拆为私有小步：`_check_quota()` / `_spawn()` / `_await_ready()` / `_attach_listener()`，每个 < 40 行。
  4. `_runner_info_to_dict` 迁到 `models.py` 作为 `RunnerProcessInfo.to_dict()`。
  5. **本 Task 不触碰 `broca/components/session_runner.py`**。ABC 扩展**整体归 Task 4.1**（Phase 3 只改实现、不改契约），避免两个 Task 各写一半签名导致 `__abstractmethods__` 停在「半实现」状态。`request_stop` 已在 Task 1.4 进入 ABC，本 Task 只需保证 `IPCSessionRunner` 的实现与之一致。
  6. 同步更新 `broca/tests/test_runner_heartbeat.py` / `test_runner_restore.py` 到新结构（fixture 改为构造 mock 的 `registry`/`repo`/`events`，注入 `IPCSessionRunner`）。
  7. **更新导出面**：`broca/session_runner/__init__.py`（`IPCClient` / `IPCServer` / `RunnerManager`）与 `broca/components/__init__.py:63,98`。拆分后 `IPCClient` / `IPCServer` 来自 `transport/`，`RunnerManager` 仍是 `IPCSessionRunner` 的别名，必须逐个确认可导入。
  8. **≤ 400 行的减行来源**（原定 350 只剩 ≤ 55 行余量，风险过高）：Phase 1 结束 ≈1670 → Task 2.2 ≤1300 → Phase 2 ≤950 → Task 3.1 −264 → Task 3.2 −176 → Task 3.3 −105 ≈ 405 行；本 Task 再通过 ①`_runner_info_to_dict` 迁到 `RunnerProcessInfo.to_dict()`（约 20 行）②`start_session` 拆成 4 个私有方法后删除的内联注释与日志（约 15 行）③`restore_active_sessions` 委托 `repo` + `reaper` 后删掉的进程探测逻辑（约 20 行）收敛到 ≤ 400。
- **预期产出**：
  - `manager.py` ≤ 400 行
  - 导出面更新（`session_runner/__init__.py`、`components/__init__.py`）
  - 测试文件迁移
- **验收标准**：
  - [ ] `wc -l broca/session_runner/manager.py` ≤ 400
  - [ ] `manager.py` 中 `start_session` 语句数 ≤ 60（AST 口径，同 Task 3.3 的检查命令）
  - [ ] `broca/session_runner/` 下每个文件行数 ≤ 500（无 God Class 复现）
  - [ ] `venv/bin/python -c "from broca.session_runner import IPCClient, IPCServer, RunnerManager"` 无异常（导出面未断）
  - [ ] `venv/bin/python -c "import broca.components"` 无异常，且 `broca/components/__init__.py:63,98` 的导出项可导入
  - [ ] `grep -n "get_session_status\|request_stop" broca/components/session_runner.py` 只命中 Task 1.4 已加入的 `request_stop`（本 Task 未改动 ABC）
  - [ ] Phase 1/2 与 Task 3.1~3.4 全部测试绿
  - [ ] `venv/bin/python -m pytest broca/tests/ -q -k runner` 全绿

---

### Phase 4: 消除抽象泄漏与性能优化

**目标**：API 层不再触碰私有属性；IPC 由 N 线程降为 1 线程多路复用；DB 写入批量合并；队列有背压；日志有轮转。

**阶段验收标准**：
- [ ] `grep -rn "runner_manager\._\|RunnerManager()\._" broca-web/backend/` 无结果
- [ ] 10 个并发 session 下，`session_runner` 相关线程数 ≤ 3（原为 10+）
- [ ] 心跳状态同步在 10 个 session 下每分钟 DB commit 次数 ≤ 2
- [ ] Phase 1~3 全部测试仍绿

---

#### Task 4.1: 扩展 `SessionRunner` ABC + API 层改造

- **目标**：彻底消除抽象泄漏。
- **步骤**：
  1. `broca/components/session_runner.py` 补充抽象方法（`request_stop` 已在 Task 1.4 加入，本 Task 补齐其余 8 个；现有 4 + 1 + 8 = **13**，**本 Task 是 ABC 的唯一修改方**）：
     ```python
     async def start_session(self, session_id, **kwargs) -> Any
     async def stop_session(self, session_id, timeout: float = 5.0) -> bool
     async def request_stop(self, session_id) -> dict
     async def restart_session(self, session_id) -> Any
     async def send_command(self, session_id, msg_type, payload, **kwargs) -> Any
     def get_status(self, session_id) -> Optional[dict]
     def list_sessions(self) -> list[dict]
     def get_stats(self) -> dict
     def on(self, event, handler) -> None
     async def start_heartbeat_monitor(self) -> None
     async def stop_heartbeat_monitor(self) -> None
     async def restore_active_sessions(self) -> int
     async def shutdown_all(self) -> int
     ```
  2. `IPCSessionRunner` 重命名 `get_session_status` → `get_status`（保留旧名作为 deprecated 别名一版，加 `DeprecationWarning`）。
     **同步把相关测试切到新名**：`test_runner_stop_semantics.py::test_shutting_down_status_visible_via_get_session_status` 改名为 `..._via_get_status` 并调用新方法；新增 `test_legacy_get_session_status_emits_deprecation_warning`（`pytest.warns(DeprecationWarning)`）。不允许留下一条「永久测旧名」的用例。
  3. 改造 `broca-web/backend/app/api/session_runner.py`：全部改用 ABC 方法，删除 `_runners` / `_ipc_servers` 访问（Task 1.4 已改 `stop_runner`，本 Task 覆盖其余端点）。
  4. 改造 `broca-web/backend/app/api/session.py` 的 6 处调用，确认只用 ABC 方法；**同时清理 Task 1.2 遗留的 `provider` / `model` 死形参**：删除 `IPCSessionRunner.start_session` 的这两个形参与 `session.py:39-44` 的传值（此时 ABC 已是 `**kwargs`，改动面封闭）。
  5. `broca/components/defaults.py:64` 的实现映射不变（`manager:IPCSessionRunner`），`scope = "singleton"` 不变。
  6. **建立 REST 响应基线（把「对比记录」落成可执行定义）**：
     - 新增脚本 `broca-web/tests/snapshot_runner_api.py`：用 `fastapi.testclient.TestClient` + `unittest.mock.patch` 固定 `RunnerManager` 返回值，覆盖 4 个端点（`GET /{sid}/runner`、`POST /{sid}/runner/start`、`POST /{sid}/runner/stop`、`POST /{sid}/runner/restart`），把每个响应体 `json.dumps(sort_keys=True, indent=2)` 写入 `--out` 指定文件。
     - **改造前**先生成基线：`venv/bin/python broca-web/tests/snapshot_runner_api.py --out broca-web/tests/fixtures/session_runner_responses.before.json`。
     - 改造后生成 `...after.json`，`diff` 两文件**必须为空**。脚本与两个基线文件一并入库，作为后续回归依据。
  7. 新增 `broca/tests/test_session_runner_abc.py`：
     - `test_ipc_session_runner_implements_abc`：`assert issubclass(IPCSessionRunner, SessionRunner)` 且 `IPCSessionRunner.__abstractmethods__ == frozenset()`
     - `test_abc_covers_all_api_calls`：静态扫描 `broca-web/backend/app/api/session_runner.py` 中 `runner_manager.<attr>` 的所有 attr，断言每个都在 ABC 中定义
     - `test_no_private_attr_access_in_api`：ast 扫描断言无 `._` 属性访问
     - `test_legacy_get_session_status_emits_deprecation_warning`：旧名仍可用但触发 `DeprecationWarning`
     - `test_abc_method_count_is_13`：断言 `SessionRunner.__abstractmethods__` 恰好 13 个，与 Task 1.4 + 本 Task 的清单一致（防止两个 Task 各写一半后无人发现）
- **预期产出**：
  - ABC 从 4 方法扩到 13 方法（现有 4 + Task 1.4 的 `request_stop` + 本 Task 的 8 个）
  - API 层 2 个文件改造
  - 新增 `broca-web/tests/snapshot_runner_api.py` 与 `broca-web/tests/fixtures/session_runner_responses.{before,after}.json`
  - 新增 `broca/tests/test_session_runner_abc.py`（5 个测试）
- **验收标准**：
  - [ ] `grep -rn "runner_manager\._" broca-web/backend/` 无结果
  - [ ] 5 个新测试通过
  - [ ] `broca-web/tests/integration/test_api_session_runner.py` 全绿
  - [ ] `diff broca-web/tests/fixtures/session_runner_responses.before.json broca-web/tests/fixtures/session_runner_responses.after.json` 为空（**这就是「响应结构与改造前一致」的可执行定义**）
  - [ ] `grep -rn "\.get_session_status(" broca/tests/ | grep -v "test_legacy_"` 无结果（除步骤 2 新增的 `test_legacy_get_session_status_emits_deprecation_warning` 外，无测试再调用旧名；**不能写成「`broca/tests/` 下 grep 为空」——那与步骤 2 要求新增的 deprecated 用例直接互斥**）
  - [ ] Phase 1~3 测试全绿

---

#### Task 4.2: IPC 单线程多路复用（P1-6）

- **目标**：用 `multiprocessing.connection.wait()` 在一个线程里轮询所有连接，消除 N 个 daemon 线程。
- **步骤**：
  1. `IPCServer` 暴露 `connection` 只读属性（返回底层 `_connection`）。
  2. 新建 `broca/session_runner/poller.py`：
     ```python
     class IPCPoller:
         def __init__(self, registry: RunnerRegistry, events: EventBus)
         def start(self, loop: asyncio.AbstractEventLoop) -> None
         def register(self, session_id: str, conn: Any) -> None
         def unregister(self, session_id: str) -> None
         def stop(self) -> None
         # 内部单线程：wait(list(conns), timeout=0.5) → 对每个 ready conn recv → call_soon_threadsafe
     ```
  3. 每个 session 一个 `asyncio.Queue`（maxsize 见 Task 4.4）用于跨线程投递；`IPCPoller` 负责 `call_soon_threadsafe(queue.put_nowait, msg)`。
  4. 删除 `manager._start_poll_thread` / `_ipc_listener_loop` 的线程创建逻辑，改为 `self._poller.register(session_id, ipc_server.connection)` + 一个消费 task。
     **注册时序必须明确**：`IPCServer._connection` 初值为 `None`，只有在 `accept()` 之后才被赋值。因此 `register` 必须发生在 `_await_ready()` 收到 `EVT_READY`（即 accept 已完成）**之后**——在 `start_session` 的代码顺序上，`register` 要排在 `await self._await_ready(session_id)` 之后，并加断言 `conn is not None`（否则会注册一个 `None`，静默丢消息）。
  5. `IPCPoller` 需处理：连接断开（`recv` 抛 `EOFError`）→ `unregister` + 通知事件总线；空连接列表时 sleep 100ms 避免忙等。轮询线程统一命名为 `ipc-poller`（便于测试与线上排查）。
  6. **灰度开关**（与风险表对应，原计划只在风险表提到、无 Task 实现）：新增配置项 `execution.runner_ipc_multiplexing: bool`（默认 `true`）到 `broca/configs.py:ExecutionConfig` 与 `configs/configs.json`。`start_session` 按开关二选一：`true` → `IPCPoller`；`false` → 旧 `_start_poll_thread`。
     **旧实现必须迁到独立文件**：把 `_start_poll_thread` / `_ipc_listener_loop` 整段搬到新文件 `broca/session_runner/manager_legacy.py`（`class LegacyPollThreadMixin`），`IPCSessionRunner` 按开关选择是否混入。这样：① AC「`grep -c "threading.Thread" manager.py == 0`」**成立**（否则保留回滚路径会让该 AC 恒红）；② 「Phase 4 收尾删除回滚路径」退化为删一个文件，比在 God Class 里拔逻辑干净。
  7. 新增 `broca/tests/test_runner_poller.py`：
     - `test_single_thread_handles_multiple_connections`：注册 10 个连接，各自发消息，断言全部被投递且线程数 == 1
     - `test_broken_connection_is_unregistered`
     - `test_poller_does_not_busy_wait`：**用 mock 计数代替 CPU 采样**——patch `multiprocessing.connection.wait`，在无连接状态下跑 1s，断言 `wait` 调用次数 ≤ 20（忙等会 > 1000）。CPU 采样受同机其他进程影响，天然 flaky，不作为 AC
     - `test_unregister_during_wait_is_safe`
     - `test_multiplexing_flag_off_uses_legacy_thread`：配置为 `false` 时走 `LegacyPollThreadMixin`，断言线程被创建且消息仍可达
- **预期产出**：
  - 新增 `poller.py`
  - 新增 `manager_legacy.py`（`LegacyPollThreadMixin`，回滚路径，Phase 4 收尾删除）
  - `manager.py` 线程创建逻辑删除
  - 新增 `broca/tests/test_runner_poller.py`（5 个测试）
  - 新增配置项 `execution.runner_ipc_multiplexing`（2 处）
- **验收标准**：
  - [ ] 10 个 mock session 下 `threading.active_count()` 增量 ≤ 3，**且新增线程名均以 `ipc-poller` 为前缀**（`active_count()` 是进程级全局量，只看增量会被 pytest 并行/前序测试遗留线程误判）
  - [ ] `grep -c "threading.Thread" broca/session_runner/manager.py` == 0（**回滚路径在 `manager_legacy.py`，不影响本 AC**）
  - [ ] `grep -c "threading.Thread" broca/session_runner/manager_legacy.py` >= 1（回滚路径确实被保留）
  - [ ] `execution.runner_ipc_multiplexing` 开关生效：`true` 用 `IPCPoller`、`false` 用 `LegacyPollThreadMixin`，两种实现都能起停
  - [ ] 5 个新测试通过
  - [ ] Phase 1~3 与 Task 4.1 测试全绿

---

#### Task 4.3: DB 批量写入 + 心跳同步节流（P1-5）

- **目标**：心跳状态同步的 DB 写入量与 session 数解耦。
- **步骤**：
  1. `RunnerRepository.set_agent_status` 支持批量：一次 `SELECT ... WHERE session_id IN (...)` + 一次 `commit()`。
  2. `HeartbeatMonitor._persist_states` 已用 `upsert_many`（Task 3.1），本 Task 补充「按 `persist_interval` 聚合」：把 60s 内的多次状态变化合并为一次写。**P1-5 分工**：Task 2.2 只做「单事务批量」，本 Task 只做「时间维度聚合」，两者不重叠、不重复实现。
  3. `_sync_agent_statuses` 的缓存比对改为「按 session 批量比对 + 单次提交」，避免 10 个 session 产生 10 次 commit。
  4. 新增配置项 `execution.runner_status_persist_interval`（默认 60）到 `broca/configs.py:ExecutionConfig` 与 `configs/configs.json`。
  5. 新增 `broca/tests/test_runner_db_batching.py`：
     - `test_n_sessions_produce_single_commit`
     - `test_status_change_within_interval_is_coalesced`
     - `test_persist_interval_from_config`
- **预期产出**：
  - `repository.py` 批量方法
  - 新增配置项 2 处
  - 新增 `broca/tests/test_runner_db_batching.py`（3 个测试）
- **验收标准**：
  - [ ] 10 个 session 心跳同步一轮，commit 次数 == 1
  - [ ] 3 个新测试通过
  - [ ] `configs/configs.json` 与 `ExecutionConfig` 的字段一一对应（有测试守卫）
  - [ ] Phase 1~3 与 Task 4.1/4.2 测试全绿

---

#### Task 4.4: 队列背压 + 日志轮转清理（P1-7）

- **目标**：事件循环卡顿时 IPC 队列不无界增长；runner 日志不无限膨胀。
- **步骤**：
  1. 所有 `asyncio.Queue()` 加 `maxsize`（默认 1000，可配置 `execution.runner_ipc_queue_size`）。
  2. 投递策略：`put_nowait` 抛 `QueueFull` 时按消息类型分流——`EVT_HEARTBEAT` **丢弃最旧的**（心跳可合并，只保留最新）；其他类型记 WARNING 后丢弃，并累加 `dropped_count` 暴露到 `get_stats()`。
  3. `manager.py:1392` 与 `runner.py:422` 两处同时改造。
  4. runner 日志：`setup_logging` 改用 `logging.handlers.TimedRotatingFileHandler`（`when="midnight"`，`backupCount=7`）；manager 的 `_get_runner_log_file` 改为固定文件名（`runner.log`），由 handler 负责轮转，避免「跨天不轮转」问题。
  5. 新增 `broca/tests/test_runner_backpressure.py`：
     - `test_queue_full_drops_oldest_heartbeat`
     - `test_queue_full_drops_non_heartbeat_and_counts`
     - `test_dropped_count_in_stats`
     - `test_log_rotation_creates_backup`
- **预期产出**：
  - 队列背压 + 日志轮转
  - 新增配置项 `execution.runner_ipc_queue_size`
  - 新增 `broca/tests/test_runner_backpressure.py`（4 个测试）
- **验收标准**：
  - [ ] `grep -n "asyncio.Queue()" broca/session_runner/` 无结果（全部带 maxsize）
  - [ ] `get_stats()` 返回含 `dropped_events` 字段
  - [ ] 4 个新测试通过
  - [ ] Phase 1~3 与 Task 4.1~4.3 测试全绿

---

## 风险与应对

| 风险 | 影响 | 应对策略 |
|---|---|---|
| **Phase 2/3 重构破坏现有 27 例测试**（它们依赖 20 个私有属性） | 无法区分「重构引入的回归」与「测试断言过时」 | **测试随改随迁，不集中推到最后**：Task 2.1 / 2.3 各自负责本 Task 触碰到的 fixture（`_ipc_listener_*`、`_runners` 等），Task 3.5 只做收尾；每个 Task 的 AC 都要求「Phase 1 测试仍绿」；迁移时先改断言再改实现（红→绿） |
| **`venv/lib/python3.14/site-packages/broca/` 存在一份旧安装副本** | 若 `-m` 解析到 site-packages，跑的是旧代码，且极难察觉 | **Task 1.2 必须保留 `env["PYTHONPATH"]` 并把仓库根置于首位**。删除 PYTHONPATH 恰恰会命中本风险：`Popen(cwd=workspace)` 下 `-m` 会优先解析 site-packages。AC 加 `test_pythonpath_points_to_repo_root`（实跑 `python -c "import broca; print(broca.__file__)"` 断言输出在仓库内） |
| **AF_UNIX 路径长度**：`tempfile.gettempdir()` 在 macOS 长达 48 字符，叠加 `broca_runner_` + `session_id` + `.sock` 极易突破 108 上限（固定 `[:64]` 时实测 131） | `IPCServer.start()` 抛 `OSError: AF_UNIX path too long`，开发机上每次 `start_session` 都失败——等于把 P0-4 换成新 P0 | Task 1.3 按剩余预算动态截断，超长 id 用 `sha1[:16]` 摘要；AC 用**真实 tempdir** 断言 `len(path) <= 100`，不写死 108；`tempdir` 极端过长时抛带指引的 `IPCConnectionError` 而非静默截断 |
| **计时型 AC 在共享/负载 CI 上 flaky**（tick 计数、CPU 采样） | 阈值贴近理论上限时机器一抖动就红，绿灯失去守门意义 | 统一改为**数量级判据**（阻塞 1s 时 tick ≥ 10，而同步阻塞为 0~2），并把 CPU 采样换成 mock 调用计数；禁止「5s 内 ≥ 80」（80% 占空）这类阈值 |
| **Phase 2/3 无回滚手段**（改结构，出问题只能 revert 整个 Phase） | 线上问题无法灰度止血 | ① 每个 Phase 以单个 PR 落地，保留上一版 `manager.py` 分支可回切；② Task 4.2 用 `execution.runner_ipc_multiplexing` 开关双实现并行；③ Phase 2 的 `repository.py` / `process/` 均为新增文件，可让 `manager.py` 回退到内联实现 |
| **Windows 上无法本地验证**（AF_PIPE 行为、`start_new_session`） | 跨平台回归 | Task 2.1 的 `_send_lock` 与 `IPCChannel` Protocol 对齐覆盖了大部分差异；在 AC 中标注「Windows 需 CI 验证」；保留 `sys.platform` 分支并加单测覆盖分支选择逻辑 |
| **`multiprocessing.connection.wait()` 在 macOS 上基于 kqueue，对已关闭连接的语义有差异** | Task 4.2 可能 flaky | `test_broken_connection_is_unregistered` 覆盖此场景；`IPCPoller` 内对 `recv` 异常做兜底 `unregister` + 重试 |
| **判活三因子过于严格，误杀正常 runner** | 正常进程被判死，session 被强停 | `create_time` 容差设 5s（`Popen` 到 `psutil` 读取的窗口通常 < 100ms）；`cmdline` 用子串匹配而非全等；加 `test_genuine_runner_is_killed` 与真实进程集成测试 |
| **`upsert` 依赖 SQLite 方言**（`sqlalchemy.dialects.sqlite.insert`） | 若将来换 PostgreSQL 会失效 | 在 `repository.py` 中按 `db_manager.engine.dialect.name` 分支；当前只有 SQLite，注释标注扩展点 |
| **Phase 4 Task 4.2 改动面大，可能引入消息丢失** | 心跳/响应丢失 → 误判崩溃 | 保留 `IPCPoller` 与旧 `_start_poll_thread` 的双实现开关（配置 `execution.runner_ipc_multiplexing: bool`），灰度后可回滚 |
| **`preexec_fn` → `start_new_session` 在 Windows 上不生效** | Windows 下进程组管理差异 | Windows 分支用 `creationflags=CREATE_NEW_PROCESS_GROUP`；`RunnerReaper.terminate` 在 Windows 走 `process.kill()`（现状已如此） |

---

## 已决策事项（原「未解决的问题」）

> 以下 4 条原本把决策推给执行期（会在 Task 2.4 / 3.3 处卡住）。现按建议**直接拍板**，让「未解决的问题」归零。若负责人有不同意见，请在开工前提出，不要留到执行中途。

- **`get_resource_usage()`：删除**（已落入 Task 2.4 步骤 3）。全仓无调用方，前端也无字段消费；不保留异步化版本。若将来需要，走独立 issue 新增「异步 + 缓存」实现。
- **`CMD_RESTART` / `CMD_CREW_STATUS`：删除枚举值**（已落入 Task 3.3 步骤 4）。重启语义走 REST 的 `restart_session`，IPC 命令属重复语义；`CMD_CREW_STATUS` 既无 handler 也无调用方。`orchestrator_runner.get_crew_status()` 一并删除。
- **`session_crashed` 事件的消费方：本计划范围内不做**。仅保证事件语义正确（Task 1.4），前端通知 handler 另行排期。
- **`broca-web/backend/app/api/session_runner.py` 的路由顺序问题：独立 issue**。不在本计划范围；Task 4.1 改该文件时若顺手可修，但**不得改变既有响应结构**（受 Task 4.1 的基线 diff AC 约束）。

---

## 附录 A：现有测试依赖的私有属性清单

重构（尤其 Task 2.3 / 3.1 / 3.5）会导致以下引用失效，需同步迁移：

```
_agent_status_cache      _check_heartbeats        _cleanup_ipc_resources
_db_state_cache          _event_handlers          _force_kill_process_by_pid
_handle_runner_event     _heartbeat_check_interval _heartbeat_interval
_heartbeat_timeout       _ipc_listener_loop       _ipc_listener_tasks
_ipc_listener_threads    _ipc_servers             _mark_session_agents_disconnected
_pending_responses       _persist_runner_state    _runners
_save_runner_to_db       _trigger_event
```

来源：`broca/tests/test_runner_heartbeat.py`（19 个）、`broca/tests/test_runner_restore.py`（1 个：`_force_kill_process_by_pid`）。

重新生成清单（**注意：必须先去前缀再 `sort -u`**——`mgr._x` 与 `manager._x` 会被当成两个不同的字符串，直接 `sort -u` 会得到虚高的 27，而不是真实的 20）：

```bash
grep -ohE "(mgr|manager)\._[a-zA-Z_]+" broca/tests/test_runner_*.py \
  | sed -E 's/^[a-z]+\.//' | sort -u
# 预期输出 20 行
```

## 附录 B：逐阶段预期收益

| 阶段 | 主要收益 | 可量化指标 |
|---|---|---|
| Phase 1 | 5 个阻塞性缺陷清零，3.12/3.13 可用 | 新增 ≥ 22 测试（总数 27 → ≥ 49）；含空格 workspace 与 SIGKILL 重启均为自动化集成测试 |
| Phase 2 | 传输/持久/进程三层独立；事件循环不再冻结 | `manager.py` −40%；阻塞 1s 期间事件循环 tick ≥ 10（同步阻塞为 0~2） |
| Phase 3 | 监控/事件/路由独立；`runner.py` 可实例化 | `manager.py` ≤ 400 行；全局变量 0 个；模块级 router 实例 0 个；if/elif 链 0 条 |
| Phase 4 | 抽象泄漏清零；线程数降一个数量级 | API 层私有访问 0 处；10 session 线程 ≤ 3；commit 次数 ≤ 2/min |

---

## 附录 C：评审意见落实对照（2026-11-03 修订）

本计划已按 `reports/review/session-runner-refactor-plan-review.md` 完成定向修订。下表为逐条对照，便于定向复核。

### 阻塞项（原 Critical 1 + Major 3）

| 评审项 | 结论 | 修订位置 |
|---|---|---|
| **Critical #1** AF_UNIX 路径长度算术不成立（macOS tempdir=48，`[:64]` → 131 > 108） | 已修 | Task 1.3 步骤 1 改为「按剩余预算动态截断 + 超长 id 用 `sha1[:16]` 摘要」；`test_address_length_guard` 改为「用真实 tempdir 断言 ≤ 100」；风险表新增该行 |
| **Major #1** `PYTHONPATH` 正文「保留」vs 风险表「删除」 | 已修（统一为**保留**） | Task 1.2 步骤 4 改为「必须保留并置仓库根于首位」并说明原因；风险表该行改写；新增 AC `test_pythonpath_points_to_repo_root` |
| **Major #2** CLI 参数跨阶段契约断裂（1.2 传 `--provider/--model/--workspace`，3.4 删定义） | 已修 | Task 1.2 步骤 2 新增 argv 契约表，**Phase 1 即删除 `--provider`/`--model`**（argv + argparse 同步）；新增 `test_argv_matches_runner_argparse` 长期守卫；Task 3.4 步骤 7 改为「只做一致性校验」 |
| **Major #3** Task 1.1 AC #3 空转（3.9 上先挂 `datetime.UTC`） | 已修 | 改为 **AST 注解绑定静态校验**（`test_module_level_annotations_are_all_bound`）+ `test_future_annotations_import_present`；并在正文说明「本机 python3.12 因 pydantic_core 为 3.14 构建而无法 import」的实测结论；真实 3.12/3.13 验证降级为可选 CI matrix |

### 质量项（Major 4~12）

| 评审项 | 结论 | 修订位置 |
|---|---|---|
| Major #4 手工 AC 无法 CI 化（含空格 workspace、SIGKILL 重启） | 已修 | 新增 `test_session_lifecycle_with_spaced_workspace`（Task 1.2）与 `test_restart_after_sigkill`（Task 1.3），均标 `@pytest.mark.integration`、`BROCA_RUN_INTEGRATION=1` 启用；原手工步骤降级为补充 smoke |
| Major #5 Task 2.5 AC 弱于目标（3 处裸 `create_task` 未覆盖） | 已修 | Task 2.5 新增**全量改造点表**（8 处，含 4 处白名单），显式改造 `runner.py:333`、`manager.py:1015`；AC 改为「命中全部落入白名单」+ 新增守卫测试 `test_no_untracked_create_task` |
| Major #6 计时型 AC flaky | 已修 | Phase 2 / Task 2.4 / Task 4.2 的阈值统一改为**数量级判据**（阻塞 1s 时 tick ≥ 10；`shutdown_all` ≥ 30）；`test_poller_does_not_busy_wait` 由 CPU 采样改为 **mock `wait()` 调用计数 ≤ 20**；风险表新增该行 |
| Major #7 ABC 归属重复（Task 3.5 vs 4.1） | 已修 | **ABC 唯一修改方 = Task 4.1**；Task 3.5 步骤 5 明确「本 Task 不触碰 `components/session_runner.py`」并加 AC 校验；新增 `test_abc_method_count_is_13` |
| Major #8 Task 1.4 提前用 `request_stop` 但 ABC 未声明 | 已修 | Task 1.4 新增步骤 7：**Phase 1 就把 `request_stop` 加进 ABC**（1 行签名），并加 `test_request_stop_declared_in_abc` |
| Major #9 3.12/3.13 无验证手段 | 已修 | 同 Major #3；约束条件新增「验证方式」条目 |
| Major #10 Phase 3 AC 与 `runner_router`/`manager_router` 模块级单例冲突 | 已修 | Task 3.3 改为**实例级 router**：`protocol.py` 只提供 `MessageRouter` 类 + `@handles(...)` 装饰器工厂（仅打函数标记），router 由 `SessionRunnerProcess` / `IPCSessionRunner` 各自 `from_class()` 构建；新增 `test_router_instances_are_isolated`；Phase 3 AC 相应改写 |
| Major #11 Task 4.1「对比记录」未定义 | 已修 | 落地为 `broca-web/tests/snapshot_runner_api.py` + `fixtures/session_runner_responses.{before,after}.json` + `diff` 为空的 AC |
| Major #12 风险表缺 3 行 | 已修 | 新增 AF_UNIX 路径长度、计时型 AC flaky、Phase 2/3 无回滚三行 |

### 次要项（Minor）

| 评审项 | 结论 | 修订位置 |
|---|---|---|
| `__init__.py` / `components/__init__.py` 导出面无归属 | 已修 | Task 3.5 新增步骤 7 + 2 条 import AC；相关材料表标注归属 |
| `orchestrator_runner`「去全局单例耦合」无 Task 承担 | 已澄清 | 目标架构改为「仅删除 `get_crew_status()`」，并说明「全局单例」实指 `runner.py` 的 `_crew_runner`（Task 3.4 已覆盖） |
| 无工时估算 | 已补 | 新增「工时估算与关键路径」表（19 Task / 16 人日） |
| 附录 A 属性数「20」疑似不符（评审实测 27） | **核实为 20，原计划正确** | 评审的 27 是 `mgr._x` 与 `manager._x` 被当成不同字符串所致；附录 A 补上「先去前缀再 `sort -u`」的正确命令与 19+1 的来源拆分 |
| Task 3.3「函数体行数」计量未定义 | 已修 | 统一为 **AST 语句数** `len(node.body)`，并给出可直接运行的检查命令 |
| 灰度开关只在风险表出现 | 已修 | Task 4.2 新增步骤 6（`execution.runner_ipc_multiplexing` + 双实现 + `test_multiplexing_flag_off_uses_legacy_thread`） |
| Task 1.5 开放式收尾 | 已修 | 改为封闭清单（4 行属性表 + 「27 → 27 全绿」目标） |
| Phase 1 AC 用裸 `python` | 已修 | 统一 `venv/bin/python` |
| 「4.2~4.4 可并行」不成立 | 已修 | 改为「4.2 → 4.4 串行，4.3 可并行」 |
| 测试迁移集中在 Task 3.5 导致中间阶段红 | 已修 | Task 2.1 步骤 8 新增「随改随迁」；风险表同步改写 |
| P1-5 归属在 2.2 / 3.1 / 4.3 间摇摆 | 已修 | 明确「2.2 单事务批量 / 4.3 时间维度聚合」，两处正文互相引用 |
| Task 3.5 350 行余量仅 ~55 行 | 已修 | Phase 3 AC 与 Task 3.5 放宽到 **≤ 400**，并在 Task 3.5 步骤 8 列出减行来源 |
| Task 4.2 `register` 时序竞态 | 已修 | Task 4.2 步骤 4 明确「必须在 `_await_ready()` 收到 `EVT_READY` 之后 register，并断言 `conn is not None`」 |
| Windows `cmdline()` 可能为空 | 已修 | Task 2.3 明确「降级为两因子」+ `test_windows_empty_cmdline_degrades_to_two_factors` |
| `get_session_status` → `get_status` 后无测试迁移 | 已修 | Task 4.1 步骤 2 补「切测试 + 旧名 `DeprecationWarning` 用例」，AC 加 `grep -rn "get_session_status" broca/tests/` 为空 |
| 地址生成「迁至 transport」时序表述分散 | 已修 | 目标架构 `models.py` 行补「Phase 1 就地改造 / Phase 2 迁走并保留一行转发」；Task 2.1 步骤 1 加 `is` 同一性 AC |
| 「未解决的问题」阻塞执行 | 已拍板 | 整节改为「已决策事项」：删除 `get_resource_usage()`、删除 `CMD_RESTART`/`CMD_CREW_STATUS` |

### 修订后自检

- 新增/调整测试计数：Phase 1 = 4（1.1）+ 7（1.2）+ 5（1.3）+ 6（1.4）= **22**，总数 27 → **≥ 49**，与 Phase 1 AC 一致。
- 全文阈值统一：`manager.py` ≤ **400** 行（架构树、Phase 3 AC、Task 3.5 产出与 AC 四处一致）。
- 全文术语统一：`venv/bin/python`、AST 语句数口径、`@pytest.mark.integration` + `BROCA_RUN_INTEGRATION=1`。
- 代码块围栏平衡（50 个围栏，成对闭合）。

---

## 附录 D：第二轮评审意见落实对照（2026-11-03 复审后修订）

依据 `reports/review/session-runner-refactor-plan-review-r2.md`（Round 2 判定 ✅ Pass，3 Major + 7 Minor）。
本轮问题全部是「新增内容与既有 AC 未同步」的形态，因此修订重点是**让 AC 与步骤互相可满足**。

### Major（3 条）

| 评审项 | 结论 | 修订内容 |
|---|---|---|
| **M1** Task 4.2 步骤 6 ↔ AC #2 互斥：回滚路径保留 `_start_poll_thread`，但 AC 要求 `grep "threading.Thread" manager.py == 0` | 已修（采用评审推荐的方案 ②） | 旧实现整体迁到新文件 **`broca/session_runner/manager_legacy.py`（`LegacyPollThreadMixin`）**；`manager.py` 的 grep 仍为 0；新增 AC「`manager_legacy.py` 的 `threading.Thread` 计数 ≥ 1」确认回滚路径确实保留；「Phase 4 收尾」退化为删一个文件 |
| **M2** Task 4.1 步骤 2/7 ↔ AC #5 互斥：新增 `test_legacy_get_session_status_...` 自身含旧名，AC 却要求 `broca/tests/` grep 为空 | 已修 | AC 改为 `grep -rn "\.get_session_status(" broca/tests/ \| grep -v "test_legacy_"` 为空，并在括号里写明「不能写成整目录 grep 为空，否则与步骤 2 互斥」 |
| **M3** Task 3.3 `from_module` 发现不了类方法；`dispatch` 调用约定未定义 | 已修 | `MessageRouter.from_module` → **`from_class(cls, target_cls, side)`**（`inspect.getmembers(target_cls, inspect.isfunction)`，可发现类体内及继承链上的方法）；**统一调用约定 `await fn(ctx, msg)`**（`ctx` 即 `self`，与 `_handle_cmd_xxx(self, msg)` 天然对齐）；新增最小验证步骤（先写 10 行验证分发再动 233 行 if/elif）；新增 `test_from_class_discovers_methods` 与 `test_dispatch_passes_ctx_as_first_arg` 锁住机制本身；AC 加 `grep "from_module" protocol.py` 为空 |

### Minor（7 条）

| 评审项 | 结论 | 修订内容 |
|---|---|---|
| Phase 1 AC #1 的 glob 漏掉 `test_ipc_socket_cleanup.py`（实收 44 < 49） | 已修 | 改为 `pytest broca/tests/test_runner_*.py broca/tests/test_ipc_*.py`，并在 AC 中注明「必须带 `test_ipc_*.py`，否则少收 5 例」 |
| Task 1.5 AC #2「6 个文件」实需 7 个 | 已修 | 改为 **7 个文件**并逐个标注用例数（15+12+4+6+1+5+6 = 49） |
| Task 2.1 出现两个「步骤 8」 | 已修 | 重编号为 8（随改随迁）/ 9（新增测试） |
| Task 2.3 `RunnerLauncher.spawn` 保留 `provider`/`model` 死形参 | 已修 | 签名改为 `spawn(session_id, workspace, log_file, config_path)`；并顺带澄清 `start_session` 的这两个形参在 Phase 1「保留但标注废弃」、Task 4.1 彻底清理（`api/session.py:39-44` 仍在传值，不能直接删） |
| Task 1.1 步骤 3 未说明 `ast.walk`（`TYPE_CHECKING` 在 `If` 节点内） | 已修 | 明确「必须 `ast.walk(tree)` 而非 `tree.body`」并给出 `_bound_names()` 骨架代码 |
| Task 2.4 步骤 3「判定去留」与「已决策删除」不一致 | 已修 | 改为陈述句「**删除**（已决策）」，并说明删除后同步 sleep 自然消失、无需 `to_thread` |
| Task 1.3 步骤 1 未提示补 `hashlib` / `tempfile` import | 已修 | 步骤首行补「在 `models.py` 顶部补 `import hashlib` / `import os` / `import tempfile`（现有 import 只有 `sys`）」 |

### 修订后自检（Round 2）

- 3 处 AC↔步骤互斥已全部解除：`manager.py` 的线程 grep（迁 legacy 文件）、`get_session_status` 的 grep（收窄 + 白名单）、`from_module` 的机制（改 `from_class`）。
- Task 3.3 测试数 5 → **7**（新增 `test_from_class_discovers_methods`、`test_dispatch_passes_ctx_as_first_arg`）。
- 全文 `from_module` 已无残留（设计决策 #6、附录 C 的 Major #10 记录一并更正为 `from_class`）。
- Phase 1 的 49 例口径在 Phase 1 AC 与 Task 1.5 AC 两处一致（7 个文件，逐个标注用例数）。
