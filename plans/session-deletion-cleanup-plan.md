# 完善 Session 删除时的文件与快照清理

## 概述
- **目标**：Session 删除时完整清理所有关联资源，消除残留文件和 git 快照堆积
- **背景**：当前删除流程仅停止 Runner 进程 + 删除 DB 记录（CASCADE），遗漏了 workspace 本地文件、Runner 日志、Git 快照仓库和孤立 scheduled_job
- **约束条件**：
  - Git 快照仓库是 per-workspace 共享的，无法按 session 粒度裁剪 commit 历史
  - 清理操作需容错——单项失败不阻塞其他项，不导致删除 API 失败
  - 单删和批量删除两条路径都需覆盖
  - TUI 通过同一 REST API 调用，无需单独适配

## 相关材料

| 类别 | 路径 / 说明 |
|------|------------|
| 删除 API（单删） | `broca-web/backend/app/api/session.py:430-451` |
| 删除 API（批量） | `broca-web/backend/app/api/session.py:371-395` |
| DB 级删除 | `broca/session/service.py:175-205` — `BaseService.delete()` / `delete_batch()` |
| Runner 停止 | `broca/session_runner/manager.py:443-535` — `RunnerManager.stop_session()` |
| Runner 日志目录 | `broca/session_runner/manager.py:77` — `~/.broca/logs/runners/{session_id}/` |
| Git 快照管理 | `broca/snapshot/git_manager.py` — `GitManager`（per-workspace 单例） |
| Git 快照清理方法 | `GitManager.cleanup()` — `shutil.rmtree(repo_path)`，当前**从未被调用** |
| Session Memory 文件 | `broca/session_memory/memory_manager.py` — `{workspace}/.broca/{session_id}/{agent_id}/` |
| Agent Config Cache | `broca/agent_manager.py:199-215` — `{workspace}/.broca/{session_id}/agents/{name}.json` |
| Session 模型（含 workspace） | `broca/session/models.py` — `Session.workspace` 字段 |
| ScheduledJob 模型 | `broca/session/models.py` — `ondelete="SET NULL"` 导致 job 孤立 |
| TUI 删除入口 | `broca-tui/broca_tui/api/session.py:87-89`（调用同一 REST） |

### 当前遗漏清单

| 资源 | 位置 | 现状 |
|------|------|------|
| Session 本地文件（memory + agent config） | `{workspace}/.broca/{session_id}/` | ❌ 未清理 |
| Runner 日志 | `~/.broca/logs/runners/{session_id}/` | ❌ 未清理 |
| Git 快照仓库 | `~/.broca/snapshots/{workspace_hash}/` | ❌ 未清理（per-workspace） |
| 孤立 ScheduledJob | DB `scheduled_job` 表（`session_id→NULL`） | ❌ 记录残留 |

## 总体方案

新增 `SessionCleanupService`，封装所有清理逻辑，在 DB 删除完成后调用。

**核心设计**：

```
删除 API
  ├─ 1. stop_session()          (已有)
  ├─ 2. session_service.delete() (已有)
  └─ 3. SessionCleanupService.cleanup(session, session_id)  ← 新增
       ├─ cleanup_workspace_files(workspace, session_id)
       │    └─ shutil.rmtree({workspace}/.broca/{session_id}/)
       ├─ cleanup_runner_logs(session_id)
       │    └─ shutil.rmtree(~/.broca/logs/runners/{session_id}/)
       ├─ cleanup_orphaned_jobs(session_id)
       │    └─ DELETE scheduled_job WHERE session_id = ?
       └─ cleanup_snapshots_if_last_session(workspace)
            ├─ 查询该 workspace 下剩余 session 数
            ├─ 若为 0 → GitManager(workspace).cleanup()（删除整个仓库）
            └─ 若 > 0 → 跳过（其他 session 可能仍在写入快照）
```

**容错原则**：每个清理步骤独立 try/except，记录 warning 日志，单项失败不影响其他项，也不影响 API 返回（DB 删除已成功即视为成功）。

## 执行计划

### Phase 1: 实现清理服务并集成到删除流程

**目标**：新增 `SessionCleanupService` 并在单删/批量删 API 中集成调用

**阶段验收标准**：
- [ ] 新增 `SessionCleanupService` 类，包含 4 个清理方法
- [ ] 单删 API（`DELETE /session/{id}`）在 DB 删除后调用清理
- [ ] 批量删 API（`DELETE /session/sessions`）在 DB 批量删除后调用清理
- [ ] 每个清理步骤独立容错，单项异常不阻塞其他项
- [ ] 清理失败仅 log warning，不影响 API 成功响应

---

#### Task 1.1: 创建 SessionCleanupService

- **目标**：新建 `broca/session/cleanup_service.py`，封装所有清理逻辑
- **步骤**：
  1. 创建 `broca/session/cleanup_service.py`，定义 `SessionCleanupService` 类
  2. 实现 `async def cleanup_session(self, workspace: Optional[str], session_id: str) -> None`
     - 内部顺序调用 4 个子方法，每个用 try/except 包裹
  3. 实现 `async def cleanup_workspace_files(self, workspace: str, session_id: str) -> None`
     - 删除 `{workspace}/.broca/{session_id}/` 目录（含 session-memory、agent config cache 等）
     - 使用 `shutil.rmtree(..., ignore_errors=True)`
     - workspace 为空时跳过并 log
  4. 实现 `async def cleanup_runner_logs(self, session_id: str) -> None`
     - 删除 `~/.broca/logs/runners/{session_id}/` 目录
     - 使用 `shutil.rmtree(..., ignore_errors=True)`
  5. 实现 `async def cleanup_orphaned_jobs(self, session_id: str) -> int`
     - 查询 `scheduled_job` 表中 `session_id == session_id` 的记录
     - 对每条记录：将 `status` 设为 `CANCELLED`，然后删除记录（CASCADE 会删除 `job_execution`）
     - 返回删除的 job 数量
  6. 实现 `async def cleanup_snapshots_if_last_session(self, workspace: str) -> None`
     - 查询该 workspace 下剩余 session 数量（`SELECT COUNT(*) FROM session WHERE workspace = ?`）
     - 若为 0：实例化 `GitManager(workspace)`，调用 `cleanup()` 删除整个仓库目录（`shutil.rmtree`）
     - 若 > 0：跳过，不做任何操作（其他 session 可能仍在写入快照，不宜操作活跃仓库）
     - workspace 为空时跳过
     - 用文件锁保护：在 `GitManager.cleanup()` 调用前先 `acquire_lock()` 再 `release_lock()`
  7. 提供单例获取方式（与 `RunnerManager` 一致）
- **预期产出**：`broca/session/cleanup_service.py` 文件
- **验收标准**：
  - [ ] `SessionCleanupService` 类包含 `cleanup_session` 入口方法和 4 个子清理方法
  - [ ] `cleanup_session` 中每个子方法调用都被 try/except 包裹，异常仅 log warning 不向上抛
  - [ ] `cleanup_workspace_files` 在 workspace 为 None/空时直接 return
  - [ ] `cleanup_orphaned_jobs` 使用 `db_manager.get_session()` 操作 DB，先 cancel 再 delete
  - [ ] `cleanup_snapshots_if_last_session` 查询剩余 session 数：为 0 则调用 `GitManager.cleanup()`，否则跳过
  - [ ] 所有路径构造使用 `Path` 对象，正确处理跨平台

#### Task 1.2: 集成到单删 API

- **目标**：修改 `DELETE /session/{session_id}` 端点，在 DB 删除后调用 `SessionCleanupService`
- **步骤**：
  1. 在 `broca-web/backend/app/api/session.py` 中 `delete_session` 函数里：
     - 在 `await session_service.delete(session_id)` 之前，先获取 session 的 `workspace` 字段（`session.workspace`）
     - 在 DB 删除成功后，调用 `SessionCleanupService().cleanup_session(workspace, session_id)`
  2. 注意：`session` 对象在 `session_service.delete()` 后可能被 GC，所以需要在 delete 前提取 `workspace` 值
  3. 在 `delete_session` 函数顶部添加 `from broca.session.cleanup_service import SessionCleanupService` 导入
- **预期产出**：修改后的 `delete_session` API 端点
- **验收标准**：
  - [ ] 在 `session_service.delete()` 调用前保存 `workspace = session.workspace`
  - [ ] 在 `session_service.delete()` 成功后调用 `await cleanup_service.cleanup_session(workspace, session_id)`
  - [ ] 清理调用在 API 的 try 块内，即使清理抛异常也不影响已成功的删除
  - [ ] 添加适当的日志：清理前 log `Cleaning up session {session_id} artifacts...`

#### Task 1.3: 集成到批量删除 API

- **目标**：修改 `DELETE /session/sessions` 端点，批量删除后逐个调用清理
- **步骤**：
  1. 在 `delete_sessions` 函数中：
     - 在 `session_service.delete_batch()` 之前，批量查询所有待删 session 的 `workspace` 信息（`SELECT session_id, workspace FROM session WHERE session_id IN (...)`)
     - 构建 `{session_id: workspace}` 映射
     - 在 `delete_batch()` 成功后，遍历每个 session_id 调用 `cleanup_session(workspace, session_id)`
  2. 为提升批量清理效率，对相同 workspace 的 session 合并快照清理（只需检查一次 workspace 剩余 session 数）
  3. 快照清理逻辑：收集所有被删 session 涉及的 workspace 集合，对每个 workspace 检查是否还有其他未删除的 session，若为 0 则调用 `GitManager.cleanup()`
- **预期产出**：修改后的 `delete_sessions` API 端点
- **验收标准**：
  - [ ] 批量删除前提取所有 session 的 workspace 映射
  - [ ] 批量删除后逐个调用 `cleanup_session`
  - [ ] 同一 workspace 的多个 session 共享一次快照检查（不重复调用 `cleanup()`）
  - [ ] 单个 session 清理失败不影响其他 session 的清理

#### Task 1.4: 更新 `ScheduledJob` 的 FK 策略

- **目标**：将 `ScheduledJob.session_id` 的 `ondelete` 从 `"SET NULL"` 改为 `"CASCADE"`，使 DB 层自动级联删除
- **步骤**：
  1. 在 `broca/session/models.py` 中 `ScheduledJob` 模型：
     - 将 `session_id` 字段的 `ondelete="SET NULL"` 改为 `ondelete="CASCADE"`
     - 同时将 `agent_id` 字段的 `ondelete="SET NULL"` 改为 `ondelete="CASCADE"`（agent 删除时 job 也应删除）
  2. 在 `Session` 模型中 `scheduled_jobs` 的 `cascade_delete` 关系保持不变
  3. 生成 alembic 迁移脚本（SQLite 下需要重建表）：
     - `alembic revision --autogenerate -m "change scheduled_job ondelete to cascade"`
     - 审查迁移脚本确保正确
  4. `cleanup_orphaned_jobs` 方法保留作为**兜底**（处理历史遗留的 `session_id=NULL` 孤儿记录）
- **预期产出**：修改后的模型 + alembic 迁移脚本
- **验收标准**：
  - [ ] `ScheduledJob.session_id` 的 `ondelete` 值为 `"CASCADE"`
  - [ ] `ScheduledJob.agent_id` 的 `ondelete` 值为 `"CASCADE"`
  - [ ] 生成对应的 alembic 迁移脚本
  - [ ] 删除 session 后 `scheduled_job` 表中无该 session_id 的记录

#### Task 1.5: 确认 `shutdown_all` 无需修改（设计文档化）

- **目标**：分析 `RunnerManager.shutdown_all()`（Web 服务关闭场景）是否需要额外清理逻辑
- **步骤**：
  1. 分析 `shutdown_all()` 当前行为：它调用 `stop_session()` 但不做 DB 删除和文件清理
  2. Web 服务关闭时的清理范围与用户主动删除不同——不应删除 DB 记录（session 还在）
  3. Runner 日志目录保留（服务重启后 session 可能恢复）
  4. **结论**：`shutdown_all` 不需要额外改动——它只是停止进程，不清理文件/DB。Session 文件在下次启动时仍可恢复
  5. 在 `shutdown_all` 方法 docstring 中补充说明：此方法仅停止进程，不执行资源清理（文件/日志/快照），资源清理由用户删除 session 时触发
- **预期产出**：`shutdown_all` docstring 更新
- **验收标准**：
  - [ ] `shutdown_all()` 行为不变（仅停止进程）
  - [ ] docstring 明确说明为何不做文件清理（设计意图：服务重启后 session 可恢复）

---

### Phase 2: 测试验证

**目标**：验证清理逻辑的正确性和容错性

**阶段验收标准**：
- [ ] 单元测试覆盖 4 个清理方法
- [ ] 集成测试验证单删和批量删的完整清理流程
- [ ] 容错测试：单项清理失败不影响其他项
- [ ] 边界场景：workspace 为空、目录不存在、git repo 不存在

---

#### Task 2.1: SessionCleanupService 单元测试

- **目标**：为 4 个清理方法编写单元测试
- **步骤**：
  1. 创建 `broca/tests/test_cleanup_service.py`
  2. `test_cleanup_workspace_files`：
     - 用 `tmp_path` fixture 模拟 workspace，创建 `.broca/{session_id}/` 目录及子文件
     - 调用后断言目录已删除
     - workspace 为 None 时调用后不抛异常
     - 目录不存在时调用后不抛异常
  3. `test_cleanup_runner_logs`：
     - 用 `tmp_path` 模拟 `~/.broca/logs/runners/` 目录结构
     - 调用后断言目录已删除
  4. `test_cleanup_orphaned_jobs`：
     - 用测试 DB 创建 session + scheduled_job
     - 调用后断言 job 被删除
     - 无关联 job 时调用后返回 0
  5. `test_cleanup_snapshots_if_last_session`：
     - mock `GitManager` 和 session 查询
     - 场景 A：剩余 session 数 = 0 → 调用 `cleanup()`
     - 场景 B：剩余 session 数 > 0 → 不操作（`cleanup()` 未被调用）
     - workspace 为 None → 跳过
  6. `test_cleanup_session_resilience`：
     - 让其中一个子方法抛异常
     - 验证其他子方法仍被执行
     - `cleanup_session` 不向上抛异常
- **预期产出**：`broca/tests/test_cleanup_service.py`
- **验收标准**：
  - [ ] 所有测试用例通过（`pytest broca/tests/test_cleanup_service.py -v`）
  - [ ] 覆盖容错场景（单项失败不阻塞）
  - [ ] 覆盖边界场景（空 workspace、不存在的目录）
  - [ ] `GitManager` 和 DB 操作使用 mock，不依赖真实文件系统/DB

#### Task 2.2: API 集成测试

- **目标**：验证删除 API 的端到端清理流程
- **步骤**：
  1. 创建 `broca-web/backend/tests/test_session_delete_cleanup.py`
  2. `test_delete_session_cleans_files`：
     - 创建 session（指定 workspace），在 workspace 下创建 `.broca/{session_id}/test-file.md`
     - 创建 runner log 目录
     - 调用 `DELETE /session/{id}`
     - 断言：DB 中 session 不存在、`.broca/{session_id}/` 目录已删除、log 目录已删除
  3. `test_delete_session_cleans_orphaned_jobs`：
     - 创建 session + scheduled_job
     - 调用删除 API
     - 断言：`scheduled_job` 表中无该 session 的记录
  4. `test_batch_delete_sessions_cleans_all`：
     - 创建 3 个 session（2 个同 workspace，1 个不同）
     - 批量删除
     - 断言：所有文件/日志/DB 记录均已清理
     - 同 workspace 的快照清理只执行一次
  5. `test_delete_session_snapshot_cleanup_on_last_session`：
     - 创建 workspace，创建 1 个 session，初始化 git snapshot repo
     - 删除该 session
     - 断言：snapshot repo 目录被删除（`GitManager.cleanup()` 被调用）
  6. `test_delete_session_keeps_snapshot_when_other_sessions_exist`：
     - 创建 workspace，创建 2 个 session
     - 删除 1 个
     - 断言：snapshot repo 目录仍存在（未被删除）
  7. `test_cleanup_failure_does_not_fail_delete`：
     - mock 文件删除抛 `PermissionError`
     - 调用删除 API
     - 断言：API 返回 200（删除成功），日志中有 warning
- **预期产出**：`broca-web/backend/tests/test_session_delete_cleanup.py`
- **验收标准**：
  - [ ] 所有集成测试通过
  - [ ] 验证 DB 删除 + 文件清理 + 日志清理 + 快照清理完整链路
  - [ ] 容错：清理异常不影响 API 返回
  - [ ] 批量删除正确合并同 workspace 的快照清理

### Phase 3: 清理历史残留数据（一次性）

**目标**：清理由于旧版删除逻辑不完善而残留的历史数据，执行前必须向用户展示清单并确认

**阶段验收标准**：
- [ ] 提供 `broca session-cleanup` CLI 命令（支持 `--dry-run` 和 `--confirm`）
- [ ] `--dry-run` 模式仅扫描并展示待清理清单，不执行任何删除
- [ ] 用户确认后才执行实际清理
- [ ] 清理完成后输出清理报告（各类资源的数量和路径）

---

#### Task 3.1: 实现 `broca session-cleanup` CLI 命令

- **目标**：新建 CLI 子命令 `broca session-cleanup`，扫描并清理所有历史残留
- **步骤**：
  1. 在 `broca/cli/` 下创建 `session_cleanup.py`，注册 `session-cleanup` 子命令
  2. 实现扫描逻辑（`scan_residuals()`），识别以下残留：
     - **a. 孤立 workspace 文件**：遍历已知 workspace 的 `.broca/` 目录，找出 session_id 在 DB 中不存在的子目录
       - 遍历 `~/.broca/logs/runners/` 获取所有出现过的 workspace（也可从 DB `SELECT DISTINCT workspace FROM session` 获取）
       - 对每个 workspace，列出 `.broca/` 下的子目录，与 DB 中该 workspace 的活跃 session_id 对比
       - 不在 DB 中的即为残留
     - **b. 孤立 Runner 日志**：`~/.broca/logs/runners/{session_id}/` 中 session_id 在 DB 不存在的目录
     - **c. 孤立 Git 快照仓库**：`~/.broca/snapshots/` 下的子目录，其对应的 workspace_hash 反查不到任何活跃 session 的 workspace
       - 注：workspace_hash 是 `sha256(workspace_path)[:16]`，不可逆。改为正向遍历 DB 中所有 workspace，计算其 hash，与 `~/.broca/snapshots/` 目录对比
     - **d. 孤儿 ScheduledJob**：DB 中 `session_id IS NULL` 的记录
  3. 实现 `--dry-run`（默认模式）：
     - 输出分类清单，格式如：
       ```
       🔍 扫描完成，发现以下历史残留：
       
       [workspace 文件] 3 项
         - /Users/xxx/project-a/.broca/session-abc123/  (2.3 MB)
         - /Users/xxx/project-b/.broca/session-def456/  (1.1 MB)
         - ...
       
       [runner 日志] 2 项
         - ~/.broca/logs/runners/session-abc123/  (540 KB)
         - ...
       
       [git 快照仓库] 1 项
         - ~/.broca/snapshots/a1b2c3d4e5f6/  (12.4 MB)  (workspace: /Users/xxx/project-a)
       
       [孤儿 scheduled_job] 2 项
         - job-xxx: "reminder: 开会" (created: 2025-11-02)
         - ...
       
       总计: 8 项, 约 16.4 MB
       ```
     - 提示用户：`使用 --confirm 执行清理`
  4. 实现 `--confirm` 模式：
     - 执行扫描后，再次展示清单
     - 调用 `input("确认清理以上所有残留？(y/N): ")` 等待用户输入
     - 用户输入 `y` 后，调用 `SessionCleanupService` 的清理方法逐项清理
     - 输出清理结果报告：
       ```
       ✅ 清理完成：
         - 删除 workspace 文件: 3 项 (3.4 MB)
         - 删除 runner 日志: 2 项 (540 KB)
         - 删除 git 快照仓库: 1 项 (12.4 MB)
         - 删除孤儿 scheduled_job: 2 条
       总计释放: ~16.4 MB
       ```
  5. 支持 `--workspace <path>` 参数：仅扫描/清理指定 workspace 的残留
  6. 支持 `--type <types>` 参数：仅清理指定类型（`files,logs,snapshots,jobs`，逗号分隔）
- **预期产出**：`broca/cli/session_cleanup.py` + CLI 注册
- **验收标准**：
  - [ ] `broca session-cleanup` 默认 dry-run 模式，输出分类清单 + 大小
  - [ ] `broca session-cleanup --confirm` 先展示清单，再要求用户输入 `y` 确认，然后执行清理
  - [ ] `--workspace` 参数可限定扫描范围
  - [ ] `--type` 参数可按类别选择性清理
  - [ ] 清理过程中每项失败不影响其他项
  - [ ] 扫描逻辑正确：不会误删活跃 session 的文件

#### Task 3.2: 执行历史残留清理

- **目标**：在开发/生产环境执行 `broca session-cleanup` 清理历史残留
- **步骤**：
  1. 先执行 `broca session-cleanup`（dry-run）查看残留清单
  2. **将清单展示给用户确认**
  3. 用户确认后执行 `broca session-cleanup --confirm`
  4. 验证清理结果：确认目录/记录已删除
- **预期产出**：历史残留全部清理，输出清理报告
- **验收标准**：
  - [ ] 执行前向用户展示 dry-run 清单并获得确认
  - [ ] 清理后 `~/.broca/logs/runners/` 下无孤立 session 目录
  - [ ] 清理后各 workspace 的 `.broca/` 下无孤立 session 子目录
  - [ ] 清理后 `~/.broca/snapshots/` 下无无主仓库
  - [ ] DB 中无 `session_id=NULL` 的 `scheduled_job` 记录

## 风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| `ondelete` 从 `SET NULL` 改为 `CASCADE` 需要重建表（SQLite 限制） | 迁移复杂，可能锁表 | alembic 迁移中使用 SQLite 标准的 12-step table recreation；生产环境提前测试 |
| 并发删除 + 快照操作竞态 | 两个 session 同时删除时，两个都认为自己是"最后一个" | `cleanup_snapshots_if_last_session` 通过 `GitManager` 的文件锁保护；查询剩余 session 数在锁内执行，若发现仍有 session 则跳过 cleanup |
| workspace 路径不存在（用户手动删除了目录） | 文件清理 `shutil.rmtree` 失败 | 使用 `ignore_errors=True`；Git 操作使用 `exists()` 预检 |
| `GitManager.cleanup()` 在 runner 进程仍写快照时执行 | 文件被占用/写入冲突 | 调用 cleanup 前先通过 `acquire_lock()` 获取锁，确保无并发 git 操作 |
| 历史遗留的 `session_id=NULL` 孤儿 job | 无法通过 session_id 关联到具体 session | `cleanup_orphaned_jobs` 作为兜底：删除 API 调用时额外清理所有 `session_id IS NULL` 且创建时间早于一定阈值的记录（可选，由配置控制） |

## 未解决的问题

（无——所有关键决策已与用户确认）
