# 日志系统统一与质量修复计划

## 概述

- **目标**：统一项目全部日志到 `get_logger()` 单一入口，消除双范式（loguru vs stdlib）并存；修复已发现的 bug、安全问题和资源泄漏；提升代码一致性和可维护性
- **背景**：Review 发现 6 类问题：① Runner 子进程中 `orchestrator_runner.py` 调用 `get_logger()` 触发 `LoggingConfig.init_logging()` 自动初始化，将 `root.handlers` 替换为 `[_StdlibLoguruBridge]`，覆盖了 `setup_logging()` 配置的 stdlib handlers（bug）；② `diagnose=True` 生产环境信息泄露风险；③ per-session runner 日志目录无 GC；④ `init_logging()` 非线程安全；⑤ ~21 个模块仍用 stdlib `logging.getLogger()`，与主范式不一致；⑥ `_StdlibLoguruBridge` 不必要的帧遍历开销
- **约束条件**：
  - 不改变现有日志输出格式（stderr 和文件）
  - 子进程（Runner）仍需独立的 per-session 日志文件（`runners/<session_id>/runner.log`）
  - 保持 loguru 作为主进程日志引擎
  - `broca/alembic/env.py` 的 `fileConfig` 不迁移（alembic 专用）

## 相关材料

- **核心模块**: `broca/logging_config.py` — 统一日志入口（本次改造的主体）
- **Runner 子进程入口**: `broca/session_runner/runner.py` — 含 `setup_logging()` / `build_file_handler()`
- **子进程启动器**: `broca/session_runner/process/launcher.py` — `build_runner_env()` 需添加 `BROCA_RUNNER_CHILD=1`
- **Runner 管理器**: `broca/session_runner/manager.py` — `_get_runner_log_file()` 决定日志路径
- **Web 后端入口**: `broca-web/backend/app/main.py` — `init_logging()` 调用点
- **配置**: `configs/configs.json` — `log_file`, `log_dir`, `log_level`
- **测试**: `broca/tests/test_logging_config.py`
- **桥接器**: `broca/logging_config.py` 内 `_StdlibLoguruBridge` 类

## 总体方案

### 核心设计决策

**1. 子进程检测机制**: 通过环境变量 `BROCA_RUNNER_CHILD=1`（由 `RunnerLauncher.build_runner_env()` 注入）标识子进程。`logging_config.py` 的 `init_logging()` / `get_logger()` 根据此标志自动切换行为：

| 模式 | `init_logging()` 行为 | `get_logger(name)` 返回 |
|------|----------------------|------------------------|
| 主进程（默认） | 配置 loguru handlers + stdlib 桥接 | `logger.bind(name=name)` (loguru) |
| Runner 子进程 | stdlib `basicConfig` + `TimedRotatingFileHandler` | `logging.getLogger(name)` (stdlib) |

**2. 子进程中 `get_logger()` 不自动 init**: 子进程的 `init_logging()` 必须在 `main()` 中显式调用（因为需要先加载 `--config` 参数）。模块级 `logger = get_logger(__name__)` 在 `init_logging()` 之前只是创建 stdlib logger 对象（无 handler，buffer 到 root），不产生副作用。

**3. 消除 `setup_logging()`**: `runner.py` 中的 `setup_logging()` 和 `build_file_handler()` 函数删除，逻辑迁入 `logging_config.py` 的子进程分支。

**4. 日志调用语法兼容**: loguru 和 stdlib 都支持 f-string 和 `%s` 格式，所以现有 `logger.info(f"...")` / `logger.info("...%s", arg)` 两种写法在两种后端下都能正常工作，调用点无需修改。

### 迁移影响范围

需要修改的文件清单（21 个模块 + 2 个内联修复 + 基础设施）:

**session_runner/ 子包**（13 个，其中 `runner.py` 在 Phase 1 Task 1.3 处理）:
`runner.py`*, `manager.py`, `poller.py`, `backpressure.py`, `repository.py`, `protocol.py`, `events.py`, `monitor.py`, `process/launcher.py`, `process/reaper.py`, `transport/base.py`, `transport/client.py`, `transport/server.py`
（* = Phase 1 处理；其余 12 个在 Phase 2 Task 2.1 处理）

**其他模块**（8 个，Phase 2 Task 2.2 处理）:
`snapshot/manager.py`, `persistent_memory/manager.py`, `persistent_memory/store.py`, `tools/executor.py`, `tools/mcp_client.py`, `utils/shell_security.py`, `agent_reference.py`, `errors/utils.py`

**内联修复**（2 个）:
`configs.py`（2 处内联 `logging.getLogger`）, `tools/skill.py`（函数内 `import logging`）

---

## 执行计划

### Phase 1: 核心基础设施改造

**目标**：改造 `logging_config.py` 支持双模式（主进程/子进程），添加线程安全和子进程检测，修复安全/性能问题

**阶段验收标准**：
- [ ] `logging_config.py` 支持 `BROCA_RUNNER_CHILD` 环境变量自动切换模式
- [ ] `init_logging()` 线程安全（加 `threading.Lock`）
- [ ] `diagnose=True` 仅在 `log_level=DEBUG` 时启用
- [ ] `get_logger()` 在子进程模式返回 stdlib logger 且不触发自动初始化
- [ ] `_StdlibLoguruBridge.emit()` 移除不必要的帧遍历，直接使用 `record` 已有的 `pathname`/`lineno`/`funcName`
- [ ] 所有 `broca/tests/test_logging_config.py` 测试通过（含新增子进程模式测试）

#### Task 1.1: 改造 `logging_config.py` 支持子进程模式

- **目标**：让 `init_logging()` 和 `get_logger()` 根据 `BROCA_RUNNER_CHILD` 环境变量自动选择 loguru 或 stdlib 后端
- **步骤**：
  1. 添加 `_is_runner_child()` 辅助函数：`return os.environ.get("BROCA_RUNNER_CHILD") == "1"`
  2. 添加 `_init_lock = threading.Lock()` 模块级锁
  3. 重构 `LoggingConfig.init_logging()`:
     - 加 `with cls._init_lock:` 包裹整个初始化
     - 分支：`if _is_runner_child(): await _init_child_logging(...)` else: 现有 loguru 逻辑
     - 添加模块级辅助函数 `_init_child_logging(log_file: Optional[str], log_level: str)`:
       ```python
       def _init_child_logging(log_file, log_level):
           """子进程模式：stdlib logging，配置 root logger。"""
           handlers = [logging.StreamHandler(sys.stderr)]
           if log_file:
               log_dir = os.path.dirname(log_file)
               if log_dir:
                   os.makedirs(log_dir, exist_ok=True)
               handlers.append(TimedRotatingFileHandler(
                   log_file, when="midnight",
                   backupCount=get_runner_log_backup_days(), encoding="utf-8"
               ))
           root = logging.getLogger()
           root.handlers = handlers
           root.setLevel(getattr(logging, log_level.upper(), logging.INFO))
           root.propagate = False
       ```
  4. 修改 `LoggingConfig.get_logger()`:
     - 子进程模式：`return logging.getLogger(name)`（不自动 init）
     - 主进程模式：现有逻辑（auto-init + `logger.bind(name=name)`）
  5. 修改 `init_logging()` 中 `diagnose` 参数：`diagnose = (log_level.upper() == "DEBUG")`
  6. 简化 `_StdlibLoguruBridge.emit()`：**移除整个 `sys._getframe()` 帧遍历块**。
     原因：CPython stdlib `Logger.makeRecord()` 已经正确填充了 `record.pathname`、`record.lineno`、`record.funcName`（指向真正的调用者，而非 `logging/__init__.py` 内部帧），无需二次推导。
     改造后 `emit()` 实现：
     ```python
     def emit(self, record: logging.LogRecord):
         try:
             level = logger.level(record.levelname).name
         except ValueError:
             level = record.levelno
         logger.opt(depth=0, exception=record.exc_info).log(level, record.getMessage())
     ```
     添加测试验证：桥接后的 loguru 日志中 `name` 字段正确反映调用模块名。
  7. 添加 `get_runner_log_backup_days() -> int` 函数（从 configs 读，默认 7）
  8. 修改原 `get_log_level()` 中裸 `except Exception` 的静默吞错，改为 `except (ImportError, OSError, AttributeError)` + `logging.getLogger(__name__).debug(...)` 日志（注意：此处 `logging_config.py` 自身尚未初始化，只能用 stdlib logging）
- **预期产出**：改造后的 `broca/logging_config.py`
- **验收标准**：
  - [ ] 设置 `BROCA_RUNNER_CHILD=1` 后调用 `init_logging(log_file="test.log")` 创建 root logger 带 `TimedRotatingFileHandler`
  - [ ] 设置 `BROCA_RUNNER_CHILD=1` 后调用 `get_logger("x")` 返回 `logging.Logger` 实例且不触发初始化
  - [ ] 未设置 `BROCA_RUNNER_CHILD` 时行为与改造前完全一致（loguru）
  - [ ] 10 个线程并发调用 `init_logging()` 无异常、仅初始化一次
  - [ ] `log_level="INFO"` 时 `diagnose=False`；`log_level="DEBUG"` 时 `diagnose=True`

#### Task 1.2: `RunnerLauncher.build_runner_env()` 注入子进程标识

- **目标**：让 runner 子进程启动时携带 `BROCA_RUNNER_CHILD=1` 环境变量
- **步骤**：
  1. 打开 `broca/session_runner/process/launcher.py`
  2. 在 `build_runner_env()` 函数中，`env.pop("VIRTUAL_ENV", None)` 之后添加 `env["BROCA_RUNNER_CHILD"] = "1"`
  3. 添加注释说明此变量的用途
- **预期产出**：修改后的 `launcher.py`
- **验收标准**：
  - [ ] `build_runner_env()` 返回的 dict 包含 `{"BROCA_RUNNER_CHILD": "1"}`
  - [ ] 现有 `test_runner_launcher.py` 全部通过
  - [ ] 添加测试断言 `env["BROCA_RUNNER_CHILD"] == "1"`

#### Task 1.3: 简化 `runner.py` — 移除 `setup_logging` / `build_file_handler`

- **目标**：`runner.py` 的 `main()` 改用 `logging_config.init_logging()`，删除本地 `setup_logging()` 和 `build_file_handler()` 函数
- **步骤**：
  1. 打开 `broca/session_runner/runner.py`
  2. 删除 `from logging.handlers import TimedRotatingFileHandler` import
  3. 删除 `LOG_BACKUP_DAYS` 常量（已迁入 `logging_config.py`）
  4. 删除 `build_file_handler()` 函数
  5. 删除 `setup_logging()` 函数
  6. 文件顶部统一 import：`from broca.logging_config import get_logger, init_logging`
  7. 将 `logger = logging.getLogger(__name__)` 改为 `logger = get_logger(__name__)`
  8. 在 `main()` 中：
     ```python
     # 替换原 setup_logging(args.log_file, args.log_level)
     # 兜底：手动 `python -m broca.session_runner.runner` 启动时环境变量可能缺失
     os.environ.setdefault("BROCA_RUNNER_CHILD", "1")
     init_logging(log_file=args.log_file, log_level=args.log_level)
     ```
  9. 如果 `import logging` 不再被其他地方使用（检查 `logging.Handler`、`logging.StreamHandler` 等引用），则删除
- **预期产出**：简化后的 `runner.py`
- **验收标准**：
  - [ ] `runner.py` 中不再包含 `setup_logging` 或 `build_file_handler` 函数
  - [ ] `main()` 开头有 `os.environ.setdefault("BROCA_RUNNER_CHILD", "1")` 兜底
  - [ ] `main()` 中调用 `init_logging(log_file=..., log_level=...)`
  - [ ] 子进程启动后 `runner.log` 文件正常创建并写入日志（依赖 Task 1.2 完成）
  - [ ] 手动 `python -m broca.session_runner.runner --session-id test` 不会进入 loguru 模式
  - [ ] 现有 runner 相关测试通过

#### Task 1.4: 添加线程安全测试 + 子进程模式测试 + 回归测试

- **目标**：为 Task 1.1 的改造添加充分的测试覆盖，包括核心 bug 的回归测试（TDD：先写测试确认能复现问题，改造后验证通过）
- **步骤**：
  1. 打开 `broca/tests/test_logging_config.py`
  2. 添加 `TestChildProcessMode` 类：
     - `test_get_logger_returns_stdlib`：设 `BROCA_RUNNER_CHILD=1`，验证 `get_logger("x")` 返回 `logging.Logger`
     - `test_init_child_creates_timed_handler`：验证 root logger 有 `TimedRotatingFileHandler`
     - `test_get_logger_no_auto_init_in_child`：验证子进程中 `get_logger()` 不触发 `init_logging`
  3. 添加 `TestThreadSafety` 类：
     - `test_concurrent_init`：10 线程并发调 `init_logging()`，验证无异常
  4. 添加 `TestDiagnoseFlag` 类：
     - `test_diagnose_disabled_at_info`：INFO 级别时 loguru handler 的 `diagnose` 为 False
  5. 添加 `TestChildProcessLoggingIsolation` 类（**核心 bug 回归测试**）：
     ```python
     class TestChildProcessLoggingIsolation:
         """回归测试：子进程中 crew 编排不应破坏 per-session 日志隔离。
         
         原 bug：orchestrator_runner.py 的 get_logger() 触发 init_logging()，
         将 root.handlers 替换为 [_StdlibLoguruBridge]，覆盖了 setup_logging() 
         配置的 TimedRotatingFileHandler。
         """
         
         def test_init_in_child_does_not_install_bridge(self, monkeypatch):
             """子进程 init_logging 只配置 stdlib handler，不安装 loguru bridge"""
             monkeypatch.setenv("BROCA_RUNNER_CHILD", "1")
             init_logging(log_file=str(tmp_path / "runner.log"))
             root = logging.getLogger()
             handler_types = [type(h).__name__ for h in root.handlers]
             assert "_StdlibLoguruBridge" not in handler_types
             assert "TimedRotatingFileHandler" in handler_types
         
         def test_get_logger_in_child_does_not_clobber_handlers(self, monkeypatch, tmp_path):
             """子进程中 get_logger() 不改变 root logger handlers"""
             monkeypatch.setenv("BROCA_RUNNER_CHILD", "1")
             init_logging(log_file=str(tmp_path / "runner.log"))
             handlers_before = list(logging.getLogger().handlers)
             # 模拟 orchestrator_runner 模块 import 时的 get_logger 调用
             get_logger("broca.session_runner.orchestrator_runner")
             handlers_after = list(logging.getLogger().handlers)
             assert handlers_before == handlers_after
     ```
  6. 所有测试用 `monkeypatch.setenv` / `monkeypatch.delenv` 管理环境变量
- **预期产出**：扩展后的测试文件（含回归测试）
- **验收标准**：
  - [ ] `TestChildProcessLoggingIsolation` 在改造前运行会失败（root handlers 被 bridge 替换）
  - [ ] 改造后全部测试通过
  - [ ] 测试结束后环境变量被正确清理（不污染其他测试）
  - [ ] `pytest broca/tests/test_logging_config.py` 全绿

---

### Phase 2: 全量模块迁移

**目标**：将所有 `logging.getLogger(__name__)` 迁移为 `get_logger(__name__)`，统一日志入口

**阶段验收标准**：
- [ ] `broca/` 下（除 `alembic/env.py`）不再有任何 `logging.getLogger(__name__)` 用于获取 logger
- [ ] 不再有任何函数体内 `import logging` 仅为了 `logging.getLogger`
- [ ] 所有模块的日志调用语法（f-string / `%s`）保持不变
- [ ] 全量测试通过：`pytest broca/tests/`
- [ ] Web 后端测试通过：`pytest broca-web/tests/`

#### Task 2.1: 迁移 `broca/session_runner/` 子包（12 个文件）

- **目标**：session_runner 子包所有文件统一使用 `get_logger()`
- **步骤**（对每个文件执行相同模式）：
  1. 删除 `import logging`（如该文件不再用 `logging` 的其他功能）
  2. 添加 `from broca.logging_config import get_logger`
  3. 将 `logger = logging.getLogger(__name__)` 改为 `logger = get_logger(__name__)`
  4. 如果文件中有 `from logging.handlers import ...` 等非 logger 用途的 import，保留
- **文件列表**：
  - `broca/session_runner/manager.py`
  - `broca/session_runner/poller.py`
  - `broca/session_runner/backpressure.py`
  - `broca/session_runner/repository.py`
  - `broca/session_runner/protocol.py`
  - `broca/session_runner/events.py`
  - `broca/session_runner/monitor.py`
  - `broca/session_runner/process/launcher.py`
  - `broca/session_runner/process/reaper.py`
  - `broca/session_runner/transport/base.py`
  - `broca/session_runner/transport/client.py`
  - `broca/session_runner/transport/server.py`
- **预期产出**：12 个文件修改
- **验收标准**：
  - [ ] `grep -r "logging.getLogger" broca/session_runner/` 无结果
  - [ ] 每个文件的 `logger` 变量通过 `get_logger(__name__)` 获取
  - [ ] `pytest broca/tests/ -k runner` 全绿
  - [ ] 日志输出格式不变（stdlib 模式下 `%s` 格式仍正常工作）

#### Task 2.2: 迁移其他模块（8 个文件 + 2 个内联修复）

- **目标**：完成剩余模块的统一迁移
- **步骤**：
  1. **常规迁移**（同 Task 2.1 模式）：
     - `broca/snapshot/manager.py`
     - `broca/persistent_memory/manager.py`
     - `broca/persistent_memory/store.py`
     - `broca/tools/executor.py`
     - `broca/tools/mcp_client.py`
     - `broca/utils/shell_security.py`
     - `broca/agent_reference.py`
     - `broca/errors/utils.py`（注意：此文件的 `safe_call` 装饰器内部有 `logging.getLogger(logger_name or f.__module__)`，需改为 `get_logger(logger_name or f.__module__)`）
  2. **`broca/configs.py` 内联修复**：
     - Line ~190: `logging.getLogger(__name__).warning(...)` → 在文件顶部添加 `from broca.logging_config import get_logger` + `logger = get_logger(__name__)`，将内联调用改为 `logger.warning(...)`
     - Line ~244: 同上
  3. **`broca/tools/skill.py` 内联修复**：
     - 删除函数内的 `import logging` + `logging.getLogger(__name__).warning(...)`
     - 改为使用文件顶部的 `logger`（需要先在文件顶部添加 `from broca.logging_config import get_logger` + `logger = get_logger(__name__)`，如果还没有的话）
- **预期产出**：10 个文件修改
- **验收标准**：
  - [ ] `grep -r "logging.getLogger" broca/ --include="*.py"` 仅返回 `alembic/env.py`（如果有）和 `logging_config.py` 本身
  - [ ] `grep -r "import logging" broca/ --include="*.py"` 仅返回 `logging_config.py` 和 `alembic/env.py`
  - [ ] `pytest broca/tests/` 全绿

#### Task 2.3: 添加约定文档

- **目标**：在 `logging_config.py` 的模块 docstring 中明确日志使用规范
- **步骤**：
  1. 修改 `broca/logging_config.py` 顶部 docstring，添加：
     ```
     使用规范：
       • 所有模块统一使用 `from broca.logging_config import get_logger`
       • 禁止直接 `logging.getLogger()` 或 `from loguru import logger`
       • 日志调用支持 f-string 和 %s 两种格式（均兼容）
       • 子进程（BROCA_RUNNER_CHILD=1）自动切换为 stdlib 后端
       • 例外：broca/alembic/env.py 使用 alembic 专用的 fileConfig
     ```
- **预期产出**：更新后的 docstring
- **验收标准**：
  - [ ] docstring 清晰描述了使用规范
  - [ ] 新人阅读 docstring 后知道该用什么、不该用什么

---

### Phase 3: 资源管理与健壮性

**目标**：修复 per-session 日志目录泄漏，增强配置校验

**阶段验收标准**：
- [ ] Session 删除后对应的 `runners/<session_id>/` 目录被清理
- [ ] 定期 GC 任务自动清理超过 N 天无活动的 runner 日志目录
- [ ] `log_level` 配置值有白名单校验，非法值触发 WARNING 并回退 INFO
- [ ] 相关测试覆盖通过

#### Task 3.1: Per-session Runner 日志目录 GC

- **目标**：防止 `~/.broca/logs/runners/` 目录无限增长
- **步骤**：
  1. 在 `broca/session_runner/manager.py` 的 `IPCSessionRunner` 类中添加方法：
     ```python
     async def gc_runner_logs(self, max_age_days: int = 30) -> int:
         """清理超过 max_age_days 未修改的 runner 日志目录。
         
         通过 RunnerRegistry 获取活跃 session 集合，GC 时跳过这些 session 的目录。
         """
     ```
     实现逻辑：
     - `active_sessions = set(self._registry.keys())` 获取活跃 session
     - 遍历 `self._log_dir` 下的子目录
     - 跳过 `active_sessions` 中的目录
     - 如果目录 mtime 超过 `max_age_days`，`shutil.rmtree` 删除
     - 返回删除的目录数
  2. 在 `IPCSessionRunner.__init__` 末尾创建独立的 GC 后台任务：
     ```python
     self._gc_task: Optional[asyncio.Task] = None
     
     # 在 __init__ 末尾（或 start 方法中）:
     self._gc_task = asyncio.create_task(self._runner_log_gc_loop())
     
     async def _runner_log_gc_loop(self):
         """定期清理过期的 runner 日志目录。"""
         gc_interval = get_gc_interval()  # 默认 3600s，从 configs 读
         while True:
             await asyncio.sleep(gc_interval)
             try:
                 removed = await self.gc_runner_logs()
                 if removed:
                     logger.info("GC: removed %d stale runner log dirs", removed)
             except Exception as e:
                 logger.warning("GC runner logs error: %s", e)
     ```
     在 `shutdown_all()` / 实例销毁时 `self._gc_task.cancel()`
  3. 在 `stop_session()` 的清理路径中（`session_manager.delete_session()` 调用链最终触发 `stop_session()`），如果 session 被永久删除（非暂停/暂停后恢复），立即 `shutil.rmtree` 对应的 `self._log_dir/<session_id>/` 目录
  4. 在 `configs.py` 的 `ExecutionConfig` 中添加字段：
     - 在 `ExecutionConfig.__init__` 中添加 `self.runner_log_gc_days: int = 30`
     - `_load_config_file` 的 `execution` 解析逻辑会自动读取 JSON 中的同名字段，无需额外代码
- **预期产出**：`manager.py` 新增 GC 方法 + 后台循环 + 配置项
- **验收标准**：
  - [ ] 手动创建 `~/.broca/logs/runners/fake-session/` 目录并设置 mtime 为 40 天前，调用 `gc_runner_logs()` 后目录被删除
  - [ ] 通过 `RunnerRegistry` 判断活跃 session：活跃的 runner（`self._registry` 中有对应条目）的日志目录不被删除
  - [ ] `stop_session` 后（进程已退出），调用 `gc_runner_logs()` 会清理该目录
  - [ ] `_gc_loop` 在 `shutdown_all()` 时被正确 cancel
  - [ ] 添加单元测试 `test_gc_runner_logs`（含活跃 session 保护测试）

#### Task 3.2: 日志级别白名单校验

- **目标**：防止非法 `log_level` 值导致静默降级或异常
- **步骤**：
  1. 在 `broca/logging_config.py` 中添加常量：
     ```python
     VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
     ```
  2. 在 `get_log_level()` 中：如果读取到的 level 不在白名单中，`logger.warning(...)` + 回退 `"INFO"`
  3. 在 `init_logging()` 入口处校验 `log_level` 参数，非法值同样 warning + 回退
  4. 删除文件底部的 `DEBUG = "DEBUG"` / `INFO = "INFO"` 等冗余常量（与 `logging` 模块的 `logging.DEBUG` 等混淆，且代码中从未使用过这些常量）— 如果 grep 确认无引用则删除
- **预期产出**：校验逻辑 + 清理冗余常量
- **验收标准**：
  - [ ] `configs.json` 中设 `log_level="VERBOSE"` 时，启动时出现 WARNING 日志且实际使用 INFO
  - [ ] `get_log_level()` 对非法值返回 `"INFO"` 而非原值
  - [ ] 删除的常量确实无引用（grep 确认）

#### Task 3.3: `runner.py` 中 stderr 处理增强

- **目标**：Runner 子进程的 `RunnerLauncher.spawn()` 将 `stderr=subprocess.DEVNULL`，导致子进程的 stderr 日志丢失（仅写入文件）。考虑改为重定向到父进程的日志或保留 DEVNULL
- **步骤**：
  1. 评估当前方案：`stderr=subprocess.DEVNULL` + 文件 handler → 子进程日志只写入 `runner.log` 文件
  2. 确认这是否是有意的（避免子进程 stderr 污染 supervisor 的 backend.err.log）
  3. 如果有意的，在 `launcher.py` 的 `spawn()` 方法中添加注释解释为什么用 DEVNULL
  4. 如果不是有意的，改为 `stderr=subprocess.PIPE` 并由父进程读取（但注意：长驻子进程的 PIPE 可能阻塞 — 需要后台线程消费）
  5. **保守决策**：保持 DEVNULL，但添加注释 + 确保文件 handler 一定被配置（`log_file` 参数非 None）
- **预期产出**：代码注释或行为变更
- **验收标准**：
  - [ ] `launcher.py` 的 `spawn()` 方法中有注释解释 `stderr=DEVNULL` 的设计意图（避免子进程 stderr 污染 supervisor 的 backend.err.log）
  - [ ] `init_logging()` 子进程分支在 `log_file=None` 时仍配置 `StreamHandler(stderr)`（确保日志不丢失）

---

### Phase 4: 验证与回归

**目标**：确保所有改动无回归，核心场景端到端验证

**阶段验收标准**：
- [ ] `pytest broca/tests/ -x` 全绿（核心包测试）
- [ ] `pytest broca-web/tests/ -x` 全绿（Web 后端测试）
- [ ] 手动验证：启动 web 后端 + 创建 session → runner 子进程日志写入正确的 per-session 文件
- [ ] 手动验证：在 runner 子进程中触发 crew 编排 → 日志仍写入 per-session 文件（而非 agent.log）
- [ ] 回归测试 `TestChildProcessLoggingIsolation`（Phase 1 Task 1.4）持续通过

#### Task 4.1: 全量测试运行与修复

- **目标**：运行所有测试，修复迁移引入的任何回归
- **步骤**：
  1. `cd /Users/luoweiang/code/Broca && venv/bin/python -m pytest broca/tests/ -x -q`
  2. 如果失败，分析原因并修复
  3. `cd broca-web/backend && ../venv/bin/python -m pytest tests/ -x -q`
  4. 如果失败，分析并修复
  5. 特别关注 `test_logging_config.py`、`test_runner_*.py`、`test_launcher.py` 相关测试
- **预期产出**：全量测试通过
- **验收标准**：
  - [ ] `pytest broca/tests/` 0 failures
  - [ ] `pytest broca-web/tests/` 0 failures
  - [ ] 无新增 warning（pytest 的 `-W error` 级别）

#### Task 4.2: 端到端集成验证

- **目标**：验证子进程日志隔离在 crew 场景下仍有效（即原 bug 已修复）
- **步骤**：
  1. 启动 web 后端：`venv/bin/python -m broca.cli.main` 或 `broca service start`
  2. 通过 API 创建一个 session（触发 runner 子进程启动）
  3. 验证 `~/.broca/logs/runners/<session_id>/runner.log` 文件存在且有心跳日志
  4. 通过 API 触发一次 crew 编排（CMD_RUN_CREW）
  5. 等待 crew 执行完成
  6. 验证 `runner.log` 在 crew 执行期间仍有新日志写入（不切换到 agent.log）
  7. 验证 `agent.log` 中没有该 session 的 runner 日志
- **预期产出**：验证通过（或发现并修复问题）
- **验收标准**：
  - [ ] Crew 执行后 `runner.log` 文件 mtime 更新且包含 crew 相关日志
  - [ ] `agent.log` 中不出现 `broca.session_runner.runner` 或 `broca.session_runner.orchestrator_runner` 的日志
  - [ ] 子进程 stderr 为 DEVNULL（日志仅写入 `runner.log` 文件），可通过临时改为 `stderr=subprocess.PIPE` + 后台读取验证无意外输出

> **注**：核心 bug 的回归测试（`TestChildProcessLoggingIsolation`）已在 Phase 1 Task 1.4 中完成（TDD 模式）。

---

## 执行顺序与依赖

```
Phase 1 (基础设施)          Phase 2 (迁移)           Phase 3 (健壮性)       Phase 4 (验证)
┌─────────────────────┐   ┌─────────────────┐      ┌─────────────────┐   ┌─────────────────┐
│ Task 1.1            │   │ Task 2.1        │      │ Task 3.1        │   │ Task 4.1        │
│ logging_config      │   │ session_runner  │      │ GC runner logs  │   │ Full test run   │
│ 双模式改造          │──▶│ 12 files        │─────▶│ (asyncio.Task)  │──▶│                 │
└─────────────────────┘   │                 │      │ Task 3.2        │   │ Task 4.2        │
  Task 1.2 (代码并行)    │ Task 2.2        │      │ Level validation│   │ E2E verify      │
  Launcher env var       │ 8+2 files       │      │                 │   │                 │
                         │                 │      │ Task 3.3        │   │ (回归测试已在    │
  Task 1.3              │                 │      │ stderr handling │   │  Phase 1 完成)   │
  Simplify runner.py    │ Task 2.3        │      │                 │   │                 │
  (验证依赖 Task 1.2)   │ Convention doc  │      │                 │   │                 │
                         │                 │      │                 │   │                 │
  Task 1.4             │                 │      │                 │   │                 │
  Tests + 回归测试      │                 │      │                 │   │                 │
└─────────────────────┘   └─────────────────┘      └─────────────────┘   └─────────────────┘
```

- Phase 1 的 Task 1.1 是其余所有工作的前置依赖
- Task 1.2 和 Task 1.3 的**代码编写**可并行，但 Task 1.3 的**端到端验证**（`runner.log` 文件创建测试）依赖 Task 1.2 完成（`BROCA_RUNNER_CHILD=1` 必须被注入）
- Phase 2 依赖 Phase 1 完成
- Phase 3 与 Phase 2 可部分并行（Task 3.1 依赖 manager.py 已迁移）
- Phase 4 最后执行

---

## 风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| loguru 的 `logger.exception()` 与 stdlib 的 `logger.exception()` 行为差异 | 子进程中异常日志格式不同 | 验证：两种后端的 `exception()` 都输出 traceback，格式略有不同但语义一致 |
| 子进程中某些第三方库（如 `litellm`）使用 `logging.getLogger` 且期望有 handler | 第三方库日志丢失 | 子进程 `init_logging()` 配置 root logger handler，第三方库的 `logging.getLogger("xxx")` 会自动 propagate 到 root |
| `BROCA_RUNNER_CHILD` 环境变量被外部意外设置 | 主进程误入子进程模式 | 变量名足够特异；`init_logging()` 中额外检查 `sys.argv` 是否包含 `--session-id`（双重确认） |
| 大量文件同时迁移引入 typo | 测试失败 | 逐文件迁移 + 每完成一个子包就运行一次 `pytest`；使用统一的 diff 模式便于 review |
| `timedRotatingFileHandler` 在多 runner 进程写同一文件时冲突 | 日志交错 | 每个 runner 有独立的 `<session_id>/runner.log`，不存在写同一文件的情况 |
| 删除 `setup_logging()` 后外部代码引用断裂 | ImportError | grep 确认 `setup_logging` 仅在 `runner.py` 内部使用，无外部 import |
| `_StdlibLoguruBridge` 简化后（移除帧遍历）第三方库日志格式变化 | 日志中 `name` 字段可能显示为 `logging` 而非调用模块 | 改造前 `record.pathname` 已由 `makeRecord()` 正确设置，简化后 loguru 从 record 属性读取，行为不变；添加对比测试 |
| 开发者手动 `python -m broca.session_runner.runner` 启动时 `BROCA_RUNNER_CHILD` 未设置 | runner 误入 loguru 模式，复现原 bug | `runner.py` 的 `main()` 开头 `os.environ.setdefault("BROCA_RUNNER_CHILD", "1")` 兜底（已在 Task 1.3 中处理） |

---

## 未解决的问题

- **Runner 子进程的 log_level 传递优先级**：当前设计为 CLI 参数（`--log-level`）> `configs.json` > 默认值 `"INFO"`。`init_logging(log_level=args.log_level)` 中如果 `args.log_level` 为默认值 `"INFO"` 且 `configs.json` 配了 `"DEBUG"`，CLI 参数会覆盖 configs。需确认：是否应改为"CLI 参数显式指定时优先，未指定时 fallback 到 configs"？（当前 argparse `default="INFO"` 无法区分"用户显式传了 INFO"和"未传参使用默认值"，需改为 `default=None` 再 fallback）
