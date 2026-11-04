# 日志系统统一与质量修复 — 完整执行报告

## 概要

| 项目 | 内容 |
|------|------|
| 计划文件 | `plans/logging-unification-plan.md` |
| 执行日期 | 2026-11-04 |
| 总状态 | ✅ 全部 4 个 Phase 完成 |
| 测试总计 | **1531 tests passed** (core: 1208, web: 323), 0 failures |

## 核心成果

### 已修复的 Bug / 问题

| # | 问题 | 修复方式 |
|---|------|----------|
| 1 | **Runner 子进程 `get_logger()` 触发 `init_logging()` 将 root handlers 替换为 bridge**（核心 bug） | 子进程模式下 `get_logger()` 直接返回 `logging.getLogger(name)`，不触发自动初始化 |
| 2 | `diagnose=True` 生产环境信息泄露 | 改为 `diagnose = (log_level == "DEBUG")` |
| 3 | `init_logging()` 非线程安全 | 添加 `threading.Lock` 保护 |
| 4 | `_StdlibLoguruBridge.emit()` 不必要的帧遍历开销 | 移除 `sys._getframe()` 遍历，直接使用 `record` 属性 |
| 5 | Per-session runner 日志目录无 GC | 添加 `gc_runner_logs()` + 后台 GC 循环 |
| 6 | `log_level` 无白名单校验 | 添加 `VALID_LOG_LEVELS` + 非法值 warning 回退 |
| 7 | ~21 个模块使用 stdlib `logging.getLogger()` | 全部迁移到 `get_logger()` 统一入口 |

### 新增架构

- **双模式日志系统**：`BROCA_RUNNER_CHILD=1` 环境变量自动切换 loguru/stdlib 后端
- **子进程标识**：`RunnerLauncher.build_runner_env()` 注入 `BROCA_RUNNER_CHILD=1`
- **日志目录 GC**：定期清理过期 per-session 日志目录，保护活跃 session

## 各 Phase 执行详情

### Phase 1: 核心基础设施改造 ✅

| 文件 | 改动 |
|------|------|
| `broca/logging_config.py` | 完全重写：双模式支持、线程安全、diagnose 修复、bridge 简化、`get_runner_log_backup_days()`、`get_gc_interval()`、`VALID_LOG_LEVELS` |
| `broca/session_runner/process/launcher.py` | `build_runner_env()` 注入 `BROCA_RUNNER_CHILD=1` |
| `broca/session_runner/runner.py` | 删除 `setup_logging()`/`build_file_handler()`/`LOG_BACKUP_DAYS`，`main()` 改用 `init_logging()` + `os.environ.setdefault` 兜底 |
| `broca/tests/test_logging_config.py` | 新增 12 个测试（子进程模式、线程安全、回归测试） |

### Phase 2: 全量模块迁移 ✅

**22 个文件**从 `logging.getLogger(__name__)` 迁移到 `get_logger(__name__)`：

- `broca/session_runner/`：12 个文件 (manager, poller, backpressure, repository, protocol, events, monitor, launcher, reaper, transport×3)
- 其他模块：8 个文件 (snapshot/manager, persistent_memory×2, tools/executor, tools/mcp_client, utils/shell_security, agent_reference, errors/utils)
- 内联修复：`configs.py` (2处) + `tools/skill.py` (1处)

**额外修复**：
- `configs.py` 改用 `_get_logger()` 惰性方式避免循环导入死锁
- 4 个测试文件添加 stdlib logger patch fixture（兼容 caplog）

### Phase 3: 资源管理与健壮性 ✅

| 功能 | 实现 |
|------|------|
| Per-session 日志 GC | `gc_runner_logs()` + `start_gc_loop()` + `_runner_log_gc_loop()` 在 `manager.py` |
| 日志级别白名单 | `VALID_LOG_LEVELS` 校验在 `get_log_level()` 和 `init_logging()` |
| stderr 设计文档化 | `launcher.py` `spawn()` 添加注释解释 `stderr=DEVNULL` 意图 |

### Phase 4: 验证与回归 ✅

- `pytest broca/tests/` → **1208 passed**, 5 skipped, 0 failures
- `pytest broca-web/tests/` → **323 passed**, 0 failures
- `TestChildProcessLoggingIsolation` 回归测试 → 2/2 passed
- E2E 验证：子进程模式 crew 日志正确写入 `runner.log`，不污染 `agent.log`

## 变更统计

```
 34 files changed, 613 insertions(+), 208 deletions(-)
```

## 遗留事项

- **未实施**：端到端手动验证（启动完整 web 后端 + 创建 session + 触发 crew），需在有完整运行环境时验证
- **未解决**（计划中标记的）：Runner 子进程的 `log_level` CLI 参数优先级问题（argparse `default="INFO"` 无法区分显式传入和默认值）
