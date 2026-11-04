# Session Runner 模块优化与重构 — Phase 1: 修复 P0 阻塞缺陷 — Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | `plans/session-runner-refactor-plan.md` |
| Phase | Phase 1: 修复 P0 阻塞缺陷 |
| Status | ✅ Pass |

## Plan Anchor Confirmation

- [x] 开工前重读计划文档 Phase 1 章节（Task 1.1 ~ 1.5 的 goal / steps / 预期产出 / AC）
- [x] 每个 Task 开工前重新锚定其 AC，完成后逐条手工验证
- [x] 阶段级 6 条 AC 全部逐条验证（见下）

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| 1.1 修复 `runner.py` 注解 NameError（P0-1） | ✅ | ①`import runner; __annotations__` 无异常 ②`test_runner_module_imports.py` 全绿 ③AST 校验通过且删守卫后变红 ④`grep ^from __future__` 有结果 ⑤`AgentFactory` 每处都有守卫 | ①✅ ②✅ 5 passed ③✅ 实测删掉 `TYPE_CHECKING` import 后 `unbound=['AgentFactory']` ④✅ `runner.py:14` ⑤✅ 仅 `TYPE_CHECKING` 守卫 + 函数内局部 import | 测试数 4 → **5**（新增 `test_agent_factory_reference_is_guarded`，把 AC⑤ 从手工检查变成长期守卫） |
| 1.2 重构子进程启动命令（P0-2 + P0-3） | ✅ | ①`shell=True` 无结果 ②`preexec_fn` 无结果 ③`"python -m` 无结果 ④`--provider/--model` 无结果 ⑤`test_pythonpath_points_to_repo_root` 通过 ⑥`test_argv_matches_runner_argparse` 通过 ⑦含空格 workspace 集成测试通过 ⑧7 个新测试通过 | ①~④ 全部 `grep` 计数 0 ⑤✅ 实跑 `import broca` 落在仓库内 ⑥✅ 选项集合 `{--session-id,--workspace,--log-file,--log-level,--config}` 完全一致 ⑦✅ stderr 含 `IPC client connected`、无 `unrecognized arguments` ⑧✅ 7 unit + 1 integration | 测试数 6 → **7**（新增 `test_platform_popen_kwargs_selects_correct_branch`，锁住 Windows/Posix 分支选择，对应风险表「Windows 需 CI 验证」） |
| 1.3 修复 IPC socket 残留（P0-4） | ✅ | ①硬编码 `/tmp/broca_runner` 无结果 ②200 字符 id 路径 ≤100 且以真实 tempdir 开头 ③残留 socket 后能成功启动 ④5 个新测试通过 ⑤SIGKILL 重启循环 3 次成功 | ①✅（仅 `.pyc` 缓存残留，源码 0 命中）②✅ 实测 `len=83`，tempdir=48 字符 ③✅ `test_stale_socket_is_unlinked` ④✅ 5 unit + 1 integration ⑤✅ `test_restart_after_sigkill` 3 轮全过 | 测试数 5 → **6**（新增 `test_address_is_stable_for_same_id`，守卫「重启后能定位同一个残留文件」） |
| 1.4 区分优雅停止与崩溃（P0-5 + P2-3） | ✅ | ①`session_stopped` 且 `session_crashed`=0 ②stop 中 `get_session_status()` 返回 `shutting_down` ③`poll()!=0` 仍触发 `session_crashed` ④API 层无私有属性访问 ⑤`request_stop` 在 ABC 且不在实现类 `__abstractmethods__` ⑥6 个新测试通过 | ①✅ ②✅ ③✅ ④✅（精确模式 `\._runners|\._ipc_servers` 为空）⑤✅ `['on','request_stop','send_command','start_session','stop_session']` ⑥✅ 8 passed | 测试数 6 → **8**（新增 `test_request_stop_sends_shutdown_and_keeps_entry`、`test_request_stop_is_async`） |
| 1.5 更新现有测试并建立基线 | ✅ | ①27 例仍全绿 ②7 文件合跑 ≥49 ③`-m integration -k runner` 全绿 ④web 集成测试全绿 ⑤连续 3 次无 flaky | ①✅ 27 passed ②✅ **54 passed**（带 `BROCA_RUN_INTEGRATION=1`）③✅ ④✅ 6 passed ⑤✅ 3×54 passed，耗时 9.73~9.76s | 无 |

> ✅ = All ACs met, ⚠️ = Partial (reported), ❌ = Not completed

## Phase 级 AC 逐条验证

| # | 阶段 AC | 结果 | 证据 |
|---|---------|------|------|
| 1 | `pytest broca/tests/test_runner_*.py broca/tests/test_ipc_*.py -q` 全绿，新增 ≥22 例，总数 ≥49 | ✅ | `54 passed`（27 基线 + 27 新增；含 2 个集成用例）。必须带 `test_ipc_*.py` 已遵守 |
| 2 | 5 个模块 `import ... ; __annotations__` 无 NameError | ✅ | 循环执行输出 `ALL IMPORTS OK` |
| 3 | `pytest broca/tests/test_runner_module_imports.py -q` 全绿（AST 注解绑定校验） | ✅ | 5 passed |
| 4 | 集成测试 `test_session_lifecycle_with_spaced_workspace` 通过 | ✅ | `tmp_path / "My Project" / "demo"`，真实子进程，stderr 含 `IPC client connected` |
| 5 | 集成测试 `test_restart_after_sigkill` 通过（循环 3 次） | ✅ | 真实子进程 bind → `os.kill(pid,9)` → 立刻重新 bind，3 轮全过 |
| 6 | 主动 `stop_session` 后收到 `session_stopped` 而非 `session_crashed` | ✅ | `test_user_stop_emits_session_stopped_not_crashed`：`events == ["session_stopped"]` |

## Deviations

1. **测试数超出计划下限（累计 +4）**：1.1 4→5、1.2 6→7、1.3 5→6、1.4 6→8。新增用例都用于把计划中的**手工/弱自动化 AC 变成长期守卫**（AC 要求「总数 ≥ 49」，54 ≥ 49 成立）。未增加任何计划外功能。
2. **Task 1.4 的 AC④ 与既有函数名冲突**：`grep -n "_runners\|_ipc_servers" broca-web/backend/app/api/session_runner.py` 的朴素模式会命中既有路由函数名 `list_runners`（与本缺陷无关）。已改用精确模式 `grep -nE "\._runners|\._ipc_servers"`，结果为空，证明**没有任何属性访问**。未重命名 `list_runners` 以避免计划外改动。
3. **修复了 1 个「改动前就是红」的既有测试**：`broca-web/tests/integration/test_api_session_runner.py::TestRestartRunnerAPI::test_restart_runner`。该用例断言的 `restart_runner` 返回值（`pid`/`status=="running"`）早已与实现（后台启动 + 立即返回 `starting`）不符，改动前即失败（已用 `git stash` 双向验证）。Task 1.5 AC④ 要求该文件全绿，故一并修正为对齐真实行为。
4. **`_cleanup_ipc_resources` 不再手动 unlink socket**：按计划 Task 1.3 步骤 4「只有 `IPCServer.close()` 负责删 socket 文件」，消除了与 `multiprocessing` Finalize 回调的重复删除竞争（此前会打出 `FileNotFoundError` 告警）。
5. **`stop_session` 改为收敛而非就地清理**：进程退出后调用新增 `_converge_stopped_runner`（写库 dead → 发 `session_stopped` → 清内存/IPC → 删 DB 记录），保持与旧实现「停止即清理」的外部行为一致。

## Quality Checklist

- [x] All phase-level ACs satisfied
- [x] All task-level ACs satisfied
- [x] No missing tasks (Phase 1 计划 5 个 Task，全部创建并完成)
- [x] No extra functionality (仅新增守卫测试与必要的测试修正)
- [x] Manually verified key behaviors（含真实子进程集成测试）
- [x] Code follows project conventions（中文注释、docstring 说明历史 bug 成因）
- [x] Compatible with existing work（`broca/tests/` 全量 968 passed / 5 skipped）

## 回归基线

| 范围 | 结果 |
|---|---|
| `broca/tests/`（全量，排除 orchestration） | 968 passed, 5 skipped |
| `broca/tests/test_runner_*.py + test_ipc_*.py`（`BROCA_RUN_INTEGRATION=1`） | 54 passed |
| `broca-web/tests/integration/test_api_session_runner.py` | 6 passed |
| 组件/配置测试（ABC 改动影响面） | 171 passed, 3 skipped |
| 连续 3 次重跑 | 无 flaky |
