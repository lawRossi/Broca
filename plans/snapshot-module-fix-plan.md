# Snapshot 模块完整修复计划

## 概述
- **目标**：修复 snapshot 模块的 11 个已识别问题（安全、架构、正确性、性能、健壮性），通过分步检查点确保 undo/redo 功能不回退
- **背景**：Review 发现 3 个 P0（shell 注入 / ABC 架空 / diff 命令错误）、5 个 P1（undo 竞态 / revert 非原子 / 子进程过多 / 单例无退出 / 封装违规）、3 个 P2（ABC 不完整 / 字段冗余 / 一致性）
- **约束条件**：不改变公开 API 语义；`GitManager` 的跨进程文件锁机制保持不变；兼容 Windows/Unix 双平台；**每个检查点必须验证 undo/redo 集成测试通过后才可继续**

## 相关材料
- **被修复的源文件**：
  - `broca/snapshot/git_manager.py` — GitManager, FileLock, gc_snapshots
  - `broca/snapshot/track.py` — SnapshotTracker
  - `broca/snapshot/patch.py` — PatchCalculator
  - `broca/snapshot/restore.py` — SnapshotRestorer
  - `broca/snapshot/manager.py` — GitSnapshotManager
  - `broca/snapshot/__init__.py` — 模块导出
  - `broca/components/snapshot_manager.py` — SnapshotManager ABC
  - `broca/session/revert_service.py` — SessionRevertService
  - `broca/loop_engine/hooks/snapshot_hook.py` — SnapshotHook
  - `broca/session/cleanup_service.py` — 调用 GitManager.cleanup()
  - `broca/components/revert_service.py` — RevertServiceABC（SessionRevertService 的父类接口）
- **已有测试**（作为每步检查点的基准）：
  - `broca/tests/test_snapshot_undo_redo.py` — **14 个 undo/redo 集成测试（核心基准）**
  - `broca/tests/test_snapshot_hook.py` — SnapshotHook 单元测试
  - `broca/tests/test_snapshot_gc.py` — GC 测试
  - `broca/tests/test_git_manager_thread_safety.py` — 线程安全测试
  - `broca/tests/test_chinese_filenames.py` — 中文文件名
  - `broca/tests/test_cleanup_service.py` — 清理服务测试
- **参考实现**：`SnapshotHook`（`snapshot_hook.py`）展示了 SnapshotManager ABC 的正确使用方式

## 总体方案

修复分 2 个阶段：

**Phase 1** — 6 个代码修复任务 + 4 个检查点，按依赖关系排列：

| 顺序 | 任务 | 说明 |
|------|------|------|
| 1 | Task 1.1 Shell 注入修复 | P0 安全，低风险 |
| 2 | Task 1.5 健壮性修复 | P2，低风险，与 1.1 并行 |
| **CP1** | **检查点 1** | **跑 undo/redo + hook 测试** |
| 3 | Task 1.2 ABC 补全 + RevertService 统一 | P0 架构，中风险 |
| **CP2** | **检查点 2** | **跑 undo/redo + hook 测试** |
| 4 | Task 1.3 正确性修复 | P1，中风险 |
| **CP3** | **检查点 3** | **跑 undo/redo + hook 测试** |
| 5 | Task 1.4 性能优化（保守） | P1，低风险 |
| **CP4** | **检查点 4** | **跑 undo/redo + hook 测试** |
| 6 | Task 1.6 清理收尾 | 代码整洁 |

**检查点规则**：每个检查点运行 `pytest broca/tests/test_snapshot_undo_redo.py broca/tests/test_snapshot_hook.py -v`，**全部通过才可继续下一步；任何失败立即停止并修复**。

**Phase 2** — 新增回归测试 + 全量验证

---

## 执行计划

### Phase 1: 代码修复

**目标**：修复所有 11 个已识别问题，每步通过检查点验证 undo/redo 不回退

**阶段验收标准**：
- [ ] 无 shell 注入风险（`create_subprocess_exec` 替代 `create_subprocess_shell`）
- [ ] `SessionRevertService` 通过 `SnapshotManager` ABC 访问快照功能，不再直接实例化具体类
- [ ] `SnapshotManager` ABC 包含 `calculate_diff` / `get_diff_summary` / `restore` / `restore_file` / `restore_patches` / `get_untracked_files`
- [ ] `patch.py` 中 `to_hash=None` 分支的 diff 命令正确
- [ ] `undo()` / `redo()` 全程持锁，消除竞态窗口
- [ ] `revert_patches` 使用批量 checkout，原子性提升
- [ ] `track()` 中幽灵文件检查从 N 次 subprocess 降为 1 次
- [ ] `GitManager.cleanup()` 后实例从 `_instances` 中移除
- [ ] `patch.py` 和 `restore.py` 的 `ensure_initialized` 使用 `asyncio.to_thread`
- [ ] 4 个检查点全部通过

---

#### Task 1.1: Shell 注入修复（P0 — 安全）

- **目标**：消除 `_run_git_command_no_lock` 中的 shell 注入风险
- **步骤**：
  1. 在 `git_manager.py` 的 `_run_git_command_no_lock` 方法中，将 `asyncio.create_subprocess_shell(cmd_str, ...)` 改为 `asyncio.create_subprocess_exec("git", "-c", "core.quotepath=false", *args, ...)`
  2. 删除 `cmd_str` 拼接行（`"git -c core.quotepath=false " + " ".join(args)`）
  3. 更新 `git.GitCommandError` 的抛出消息，用 `" ".join(["git", "-c", "core.quotepath=false"] + list(args))` 构造可读命令字符串（仅用于错误消息，不用于执行）
  4. 验证 `input_data`（stdin）参数在 `create_subprocess_exec` 下仍然正常工作（`asyncio.subprocess.PIPE` 行为一致）
  5. 确认 `is_ignored_batch`（使用 `input_data` 传递 NUL 分隔路径）不受影响
- **预期产出**：`git_manager.py` 修改完成，git 命令通过参数列表执行，不再经过 shell
- **验收标准**：
  - [ ] `_run_git_command_no_lock` 中无 `create_subprocess_shell` 调用
  - [ ] 无 `cmd_str` 字符串拼接用于执行
  - [ ] 新增测试：文件名含空格和特殊字符（如 `file with spaces.txt`、`file$(whoami).txt`）的 snapshot track/restore 正常工作

---

#### Task 1.5: 健壮性修复（P2 — A3/C1）

> 与 Task 1.1 并行执行，都是低风险改动。

- **目标**：修复 `GitManager` 单例无退出机制和 `ensure_initialized` 一致性问题
- **步骤**：

  **Fix A3 — `GitManager` 单例清理**：
  1. 在 `GitManager.cleanup()` 方法末尾，添加：
     ```python
     with type(self)._class_lock:
         normalized = str(self.workspace_path)
         type(self)._instances.pop(normalized, None)
     ```
  2. 新增 `GitManager.reset(workspace_path: str) -> None` 类方法：
     ```python
     @classmethod
     def reset(cls, workspace_path: str) -> None:
         """显式清除指定 workspace 的 GitManager 单例。"""
         normalized = str(Path(workspace_path).resolve())
         with cls._class_lock:
             cls._instances.pop(normalized, None)
     ```
  3. 修改 `_default_delete` 签名增加 `workspace_path: str | None` 参数；`gc_snapshots` 在调用 `_do_delete` **之前**（`shutil.rmtree` 执行前）已从 `.workspace` 文件读取了 workspace 路径，将其作为参数传入；`_default_delete` 内部 `rmtree` 后调用 `GitManager.reset(workspace_path)`

  **Fix C1 — `ensure_initialized` 一致性**：
  1. 在 `patch.py` 的 `calculate_patch` 方法中，将 `self.git_manager.ensure_initialized()` 改为 `await asyncio.to_thread(self.git_manager.ensure_initialized)`
  2. 在 `patch.py` 的 `calculate_diff` 方法中，同上
  3. 在 `restore.py` 的 `restore` 方法中，同上
  4. 在 `restore.py` 的 `restore_file` 方法中，同上
  5. 在 `restore.py` 的 `revert_patches` 方法中，开头添加 `await asyncio.to_thread(self.git_manager.ensure_initialized)`
- **预期产出**：GitManager 生命周期可管理，事件循环不会被阻塞
- **验收标准**：
  - [ ] `cleanup()` 后 `GitManager._instances` 中不再包含该 workspace 的条目
  - [ ] `GitManager.reset(path)` 可从外部强制清除单例
  - [ ] `patch.py` 和 `restore.py` 中无直接同步调用 `ensure_initialized()`：`grep -n 'ensure_initialized()' broca/snapshot/patch.py broca/snapshot/restore.py` 无匹配（所有调用应为 `await asyncio.to_thread(self.git_manager.ensure_initialized)` 形式）

---

#### ⛳ 检查点 1

- **操作**：`pytest broca/tests/test_snapshot_undo_redo.py broca/tests/test_snapshot_hook.py -v`
- **通过标准**：全部测试通过（0 个失败、0 个 error）
- **失败处理**：立即停止，回退 Task 1.1 / 1.5 的改动，定位原因后重新执行

---

#### Task 1.2: ABC 补全 + RevertService 架构统一（P0 — 架构）

- **目标**：补全 `SnapshotManager` ABC 接口，消除双轨制，让 `SessionRevertService` 通过 ABC 访问快照功能
- **步骤**：

  **Part A — 扩展 `SnapshotManager` ABC**（`broca/components/snapshot_manager.py`）：
  1. 添加接口方法 `async def calculate_diff(self, from_hash: str, to_hash: str) -> str`（**非** `@abstractmethod`，默认返回 `""`）
  2. 添加接口方法 `def get_diff_summary(self, diff_content: str) -> Dict[str, Any]`（**非** `@abstractmethod`，默认返回 `{"total_files": 0, ...}` 空 dict）
  3. 添加接口方法 `async def restore(self, tree_hash: str) -> None`（**非** `@abstractmethod`，默认 `pass`）
  4. 添加接口方法 `async def restore_file(self, tree_hash: str, file_path: str) -> None`（**非** `@abstractmethod`，默认 `pass`）
  5. 添加接口方法 `async def restore_patches(self, patches: list) -> None`（**非** `@abstractmethod`，默认 `pass`）
  6. 添加接口方法 `async def get_untracked_files(self) -> set[str]`（**非** `@abstractmethod`，默认返回 `set()`；解决 B5 封装违规）
  > **兼容性**：6 个新增方法均**不使用 `@abstractmethod` 装饰器**，而是提供返回安全默认值的具体实现。已有插件子类无需修改即可实例化。原有的 5 个方法（`track` / `calculate_patch` / `acquire_lock` / `release_lock` / `is_tracked`）保持 `@abstractmethod` 不变。

  **Part B — `GitSnapshotManager` 实现新方法**（`broca/snapshot/manager.py`）：
  1. 添加 `self._restorer: SnapshotRestorer | None = None` 字段
  2. `initialize()` 中创建 `self._restorer = SnapshotRestorer(workspace)`
  3. 实现 `calculate_diff` → 委托 `self._patch_calculator.calculate_diff()`
  4. 实现 `get_diff_summary` → 委托 `self._patch_calculator.get_diff_summary()`
  5. 实现 `restore` → 委托 `self._restorer.restore()`
  6. 实现 `restore_file` → 委托 `self._restorer.restore_file()`
  7. 实现 `restore_patches` → 委托 `self._restorer.revert_patches()`
  8. 实现 `get_untracked_files` → `await self._git_manager._run_git_command("ls-files", "--others", "--exclude-standard", "-z")`，解析 NUL 分隔输出返回 `set[str]`
  9. 删除冗余的 `self._workspace` 字段（A4 在此完成）
  10. 在 `restore` / `restore_file` / `restore_patches` 方法中添加守卫：`if not self._available or self._restorer is None: return`（与 `track` / `calculate_patch` 的降级模式一致，防止 `initialize` 异常后 `_restorer=None` 导致 `AttributeError`）

  **Part C — 重构 `SessionRevertService`**（`broca/session/revert_service.py`）：
  1. 构造函数参数从 `(session_manager, workspace_path, enable_snapshot_tracking)` 改为 `(session_manager, snapshot_manager: SnapshotManager, workspace_path, enable_snapshot_tracking: bool = True)`
     > **约束**：`snapshot_manager` 参数始终必传（不接受 `None`）。即使 `enable_snapshot_tracking=False`，也必须传入一个实例（可传 `GitSnapshotManager` 的 disabled 模式实例——`initialize()` 时 `_available=False`，所有方法返回安全默认值），不接受 `None`
  2. 删除 `self.snapshot_tracker` / `self.patch_calculator` / `self.snapshot_restorer` 三个直接实例化
  3. 添加 `self._sm: SnapshotManager` 字段
  4. 所有 `self.snapshot_tracker.track()` → `await self._sm.track(self.workspace_path)`
  5. 所有 `self.snapshot_restorer.revert_patches(...)` → `await self._sm.restore_patches(...)`
  6. 所有 `self.snapshot_restorer.restore(...)` → `await self._sm.restore(...)`
  7. 所有 `self.patch_calculator.calculate_diff(...)` → `await self._sm.calculate_diff(...)`
  8. 所有 `self.patch_calculator.get_diff_summary(...)` → `self._sm.get_diff_summary(...)`
  9. `redo` 中的 `self.snapshot_tracker.git_manager._run_git_command(...)` → `await self._sm.get_untracked_files()`（解决 B5）
  10. `redo` 中孤儿文件清理的 `self.snapshot_restorer.workspace_path` → `self.workspace_path`

  **Part D — 更新调用方**：
  1. 搜索所有创建 `SessionRevertService` 的位置，传入 `SnapshotManager` 实例
  2. 更新 `broca/components/defaults.py` 中 `RevertServiceABC` 的默认实现映射（如果需要）
- **预期产出**：ABC 完整，`SessionRevertService` 通过接口访问，双轨制消除
- **验收标准**：
  - [ ] `SnapshotManager` ABC 包含全部 11 个方法（5 个原有 `@abstractmethod` + 6 个新增接口方法，新增方法均提供默认实现）
  - [ ] `GitSnapshotManager` 实现所有方法
  - [ ] `SessionRevertService` 中无 `SnapshotTracker` / `PatchCalculator` / `SnapshotRestorer` 的直接 import 和实例化
  - [ ] `SessionRevertService` 构造函数接受 `SnapshotManager` 类型
  - [ ] 所有 `SessionRevertService` 的调用方已更新

---

#### ⛳ 检查点 2

- **操作**：`pytest broca/tests/test_snapshot_undo_redo.py broca/tests/test_snapshot_hook.py -v`
- **通过标准**：全部测试通过
- **重点关注**：ABC 重构后 `SessionRevertService` 的 undo/redo 流程是否正确委托到 `GitSnapshotManager`
- **失败处理**：立即停止，对比重构前后 `SessionRevertService` 的调用链，定位委托链断裂点

---

#### Task 1.3: 正确性修复（P1 — B2/B3/B4/B5）

- **目标**：修复 4 个逻辑/正确性问题
- **步骤**：

  **Fix B2 — `patch.py` 中 `to_hash=None` 的 diff 命令**：
  1. 在 `patch.py` 的 `_get_changed_files` 方法中，找到 `to_hash` 为 None 的分支
  2. 将 `self.git_manager._run_git_command("diff", "--name-only", "HEAD", "--", ".")` 改为 `self.git_manager._run_git_command("diff", "--name-only", "--", ".")`
  3. 保留 `read-tree from_hash` 和 `reset --mixed`（`read-tree` 修改了 index，`reset --mixed` 恢复 index 到 HEAD）

  **Fix B3 — `undo()` / `redo()` 全程持锁**：
  1. 在 `SessionRevertService.undo()` 方法中，在第一个 `track()` 之前调用 `await asyncio.to_thread(self._sm.acquire_lock)`（`acquire_lock` 底层 `fcntl.flock` 是同步阻塞调用，必须用 `to_thread` 包装避免阻塞事件循环，与 `track.py` 第 38 行模式一致）
  2. 用 `try / finally` 包裹整个 undo 逻辑，在 `finally` 中调用 `await asyncio.to_thread(self._sm.release_lock)`
  3. 验证 `track()` / `restore_patches()` / `calculate_diff()` 内部的 `_run_git_command` 通过 `self._lock.is_held` 检测到锁已持有，**跳过重复获取**（现有逻辑已支持，验证即可）
  4. 同样对 `redo()` 方法加锁：`await asyncio.to_thread(self._sm.acquire_lock)` → restore + orphan cleanup → `await asyncio.to_thread(self._sm.release_lock)`
  5. **死锁防护**：`acquire_lock` 使用 `FileLock` 的重入计数（`_count`），同一线程/进程内的重入调用安全。确认 `undo()` / `redo()` 中不存在嵌套调用 `acquire_lock` 的路径

  **Fix B4 — `revert_patches` 批量原子化**：
  1. 在 `restore.py` 的 `revert_patches` 方法中，改为：
     - 收集所有 `(file_path, tree_hash)` 对
     - 按 `tree_hash` 分组：`{tree_hash: [file1, file2, ...]}`
     - 对每个 `tree_hash` 组，执行一条 `git checkout <tree_hash> -- <file1> <file2> ...`
     - 整个操作在单次 `acquire_lock` / `release_lock` 内完成（如果外部已持锁则复用）
  2. 对于 `git checkout` 失败的文件（文件不存在于目标 tree），在批量 checkout 后单独处理：
     - 对每个 checkout 失败的文件，执行 `git ls-tree -r --name-only <tree_hash> -- <file>` 检查
     - 如果文件不在 tree 中且磁盘上存在 → 删除该文件（与原 `restore_file` 的 fallback 逻辑一致）
  3. **兼容性保障**：保持 `revert_patches` 的函数签名和返回行为不变

  **Fix B5 — 封装违规**（已在 Task 1.2 Part C 步骤 9 中解决）：
  - 确认 `SessionRevertService.redo()` 中使用 `self._sm.get_untracked_files()` 替代直接访问 `git_manager`
- **预期产出**：4 个正确性 bug 修复
- **验收标准**：
  - [ ] `patch.py` 中 `to_hash=None` 分支使用 `git diff --name-only -- .`（无 HEAD 参数）
  - [ ] `SessionRevertService.undo()` 和 `redo()` 从开始到结束全程持有文件锁
  - [ ] `revert_patches` 对同一 `tree_hash` 的多个文件使用单条 `git checkout` 命令
  - [ ] `revert_patches` 中 `git checkout` 失败时，有 fallback 到 `ls-tree` 检查 + 删除的逻辑
  - [ ] `SessionRevertService` 中无 `snapshot_tracker.git_manager` 或 `snapshot_restorer.workspace_path` 的访问

---

#### ⛳ 检查点 3

- **操作**：`pytest broca/tests/test_snapshot_undo_redo.py broca/tests/test_snapshot_hook.py -v`
- **通过标准**：全部测试通过
- **重点关注**：
  - undo/redo 加锁后是否有死锁（测试会超时）
  - `revert_patches` 批量 checkout 后文件状态是否正确
- **失败处理**：立即停止。如果是死锁 → 检查锁重入逻辑；如果是文件状态错误 → 检查批量 checkout 的分组逻辑

---

#### Task 1.4: 性能优化 — 减少幽灵文件 subprocess（P1，保守方案）

- **目标**：将 `track()` 中幽灵文件检查从 N 次 subprocess 降为 1 次（8+N → 8+1），**不替换原有 3 条变更发现命令**
- **说明**：`git status --porcelain` 替换 3 条命令的方案风险高（rename / submodule / sparse checkout 等边缘场景行为不同），留作后续独立优化项
- **步骤**：

  **优化 — 批量幽灵文件检查**：
  1. 在 `track.py` 的 `_filter_files` 方法中，先将文件分为两组：
     - `disk_files`：`full_path.is_file()` 为 True 的文件（走原有的大小检查）
     - `ghost_candidates`：不在磁盘上的文件
  2. 如果 `ghost_candidates` 非空，用 **1 次** `git ls-files --cached -z -- <file1> <file2> ...` 批量查询哪些在索引中
  3. 根据返回结果：在索引中的 → 保留（加入 `filtered_files`）；不在的 → 过滤掉
  4. 删除原来逐文件的 `ls-files --cached` 调用
  5. **注意**：如果 `ghost_candidates` 为空，完全跳过 git 调用（避免无意义的 subprocess）

- **预期产出**：`_filter_files` 的幽灵文件检查从 N 次 subprocess 降为最多 1 次
- **验收标准**：
  - [ ] `_filter_files` 中对不在磁盘上的文件，`ls-files --cached` 最多调用 1 次（通过 mock 验证）
  - [ ] 当无幽灵文件时，`_filter_files` 不调用 `ls-files`（mock 计数为 0）
  - [ ] 所有 `test_snapshot_undo_redo.py` 测试通过（包括 ghost file 相关测试 Test 1/2/3/12）
  - [ ] 原有的 3 条变更发现命令（`diff-files` / `diff-index` / `ls-files --others`）保持不变

---

#### ⛳ 检查点 4

- **操作**：`pytest broca/tests/test_snapshot_undo_redo.py broca/tests/test_snapshot_hook.py -v`
- **通过标准**：全部测试通过
- **失败处理**：立即停止，回退 Task 1.4 的改动

---

#### Task 1.6: 清理与收尾

- **目标**：清理代码中的冗余部分，更新模块导出
- **步骤**：
  1. 验证 A4 已完成：`grep -n 'self._workspace' broca/snapshot/manager.py` 无结果（A4 在 Task 1.2 Part B Step 9 执行；若未执行则在此删除）
  2. 更新 `broca/snapshot/__init__.py`：确认所有导出与 ABC 实现一致
  3. 更新 `broca/snapshot/manager.py` 的模块 docstring，反映新增的 ABC 方法
  4. 检查 `git_manager.py` 中 `import asyncio` 在文件顶部
  5. 在 `FileLock._fallback_mode` 处添加注释：说明 sticky 设计意图（"一旦进入 fallback 不再回退到 flock，因为 NFS 等文件系统不支持 flock 是永久性限制"）
  6. 在 `track.py` 中添加 TODO 注释：`# TODO(optimization): 考虑用 git status --porcelain -z 替换 3 条变更发现命令，需充分测试 rename/submodule 场景`
- **预期产出**：代码整洁，无冗余，后续优化有明确入口
- **验收标准**：
  - [ ] `grep -n "self._workspace" broca/snapshot/manager.py` 无结果
  - [ ] `git_manager.py` 有 `import asyncio` 在文件顶部
  - [ ] `track.py` 有 `git status` 优化 TODO 注释

---

### Phase 2: 回归测试

**目标**：新增回归测试覆盖所有修复点，并验证无功能回归

**阶段验收标准**：
- [ ] 新增测试全部通过
- [ ] 所有已有 snapshot 相关测试通过
- [ ] `pytest broca/tests/test_snapshot*.py broca/tests/test_git_manager*.py broca/tests/test_chinese_filenames.py` 全部绿色

---

#### Task 2.1: 新增回归测试

- **目标**：为每个修复点编写对应的回归测试
- **步骤**：

  **测试文件**：在 `broca/tests/test_snapshot_fixes.py` 中新增以下测试类：

  **TestShellSafety**（对应 Task 1.1）：
  1. `test_track_file_with_spaces`：创建 `my file.txt`，track + restore，验证内容正确
  2. `test_track_file_with_shell_metachars`：创建 `test$(echo hacked).txt`，track 后验证文件存在且无 `hacked` 文件被创建
  3. `test_track_file_with_semicolon`：创建 `test;ls.txt`，track 后验证无额外文件创建
  4. `test_ignored_batch_with_special_chars`：`is_ignored_batch` 传入含空格路径，验证正确识别

  **TestToHashNoneFix**（对应 Task 1.3 Fix B2）：
  5. `test_calculate_patch_to_hash_none`：创建 file_a → track(snap1) → 修改 file_a → `calculate_patch(snap1)` 不传 to_hash，验证返回的 files 包含 file_a
  6. `test_calculate_patch_to_hash_none_no_false_positive`：创建 file_a → track(snap1) → 不修改 → `calculate_patch(snap1)` 验证返回空

  **TestUndoLock**（对应 Task 1.3 Fix B3）：
  7. `test_undo_holds_lock_for_entire_operation`：mock `SnapshotManager.acquire_lock` / `release_lock`，验证 `undo()` 中 `acquire_lock` 在第一个 `track` 之前调用、`release_lock` 在最后一个操作之后调用
  8. `test_redo_holds_lock`：同上验证 `redo()`

  **TestRevertAtomicity**（对应 Task 1.3 Fix B4）：
  9. `test_revert_patches_batch_checkout`：3 个文件来自同一 tree_hash，mock `GitManager._run_git_command` 验证 `git checkout` 只被调用 1 次（包含所有 3 个文件参数）
  10. `test_revert_patches_mixed_hashes`：2 个文件来自 tree A，1 个来自 tree B，验证 `git checkout` 被调用 2 次
  11. `test_revert_patches_fallback_delete`：文件不在目标 tree 中 → 验证 `ls-tree` 被调用且文件被删除

  **TestGhostFileBatch**（对应 Task 1.4）：
  12. `test_filter_files_batch_ghost_check`：3 个幽灵文件，mock 验证 `ls-files --cached` 只被调用 1 次
  13. `test_filter_files_no_ghost_no_git_call`：所有文件都在磁盘上，mock 验证 `ls-files --cached` 调用 0 次

  **TestGitManagerLifecycle**（对应 Task 1.5 Fix A3）：
  14. `test_cleanup_removes_singleton`：创建 `GitManager(ws)`，验证 `ws` 在 `_instances` 中；调用 `cleanup()`，验证 `ws` 不在 `_instances` 中
  15. `test_reset_removes_singleton`：创建 `GitManager(ws)`，调用 `GitManager.reset(ws)`，验证 `_instances` 中无 `ws`

  **测试 fixture 复用**：使用 `test_snapshot_undo_redo.py` 中已有的 `workspace` / `tracker` / `restorer` / `calculator` fixture 模式

- **预期产出**：`broca/tests/test_snapshot_fixes.py`，包含 15 个测试
- **验收标准**：
  - [ ] 15 个新测试全部通过
  - [ ] 测试使用 `pytest.mark.asyncio` 异步标记
  - [ ] Shell 安全测试验证了含 `$(...)` 和 `;` 的文件名不被执行
  - [ ] 批量优化测试使用 mock 计数而非实际计时

---

#### Task 2.2: 全量回归验证

- **目标**：确认所有修改未引入回归
- **步骤**：
  1. 运行 `pytest broca/tests/test_snapshot_undo_redo.py -v` — 14 个集成测试
  2. 运行 `pytest broca/tests/test_snapshot_hook.py -v` — SnapshotHook 单元测试
  3. 运行 `pytest broca/tests/test_snapshot_gc.py -v` — GC 测试
  4. 运行 `pytest broca/tests/test_git_manager_thread_safety.py -v` — 线程安全
  5. 运行 `pytest broca/tests/test_chinese_filenames.py -v` — 中文文件名
  6. 运行 `pytest broca/tests/test_snapshot_fixes.py -v` — 新增回归测试
  7. 运行 `pytest broca/tests/test_cleanup_service.py -v` — 清理服务
  8. 运行 `pytest broca/tests/ -k "snapshot or revert or git_manager" -v` — 全量 snapshot 相关
- **预期产出**：全量测试通过报告
- **验收标准**：
  - [ ] 所有测试通过（0 个失败）
  - [ ] 无新增 warning（除已知的 deprecation 外）

---

## 依赖关系

```
                   ┌─ Task 1.1 (Shell) ──┐
                   │                      ├→ ⛳ CP1 → Task 1.2 (ABC) → ⛳ CP2
                   └─ Task 1.5 (健壮性) ─┘                         │
                                                                  ⛳ CP3 → Task 1.4 (性能)
                                                                         │
                                                                        ⛳ CP4 → Task 1.6 → Phase 2
```

> Task 1.1 和 1.5 并行执行，均完成后进入 CP1。
- Task 1.2 依赖 CP1 通过
- Task 1.3 依赖 Task 1.2（RevertService 重构后才能加锁）
- Task 1.4 依赖 Task 1.3（修改 `track.py` 需确保正确性已修复）
- Task 1.6 在所有代码修复完成后执行
- Phase 2 依赖 Phase 1 全部完成

## 风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| `create_subprocess_exec` 在 Windows 上处理 `GIT_DIR` / `GIT_WORK_TREE` 环境变量 | Windows 兼容性 | `env` 参数行为与 `create_subprocess_shell` 一致；CI 中覆盖 Windows |
| ABC 扩展导致第三方 `SnapshotManager` 插件实现需要更新 | 插件兼容性 | 新增 6 个方法提供**默认实现**（返回安全默认值），不强制已有插件立即适配 |
| `undo()` 全程持锁时间变长，可能阻塞其他 agent 的快照操作 | 并发性能 | 锁是 per-workspace 的，不同 workspace 互不影响；`FileLock` 支持重入，同进程内的嵌套调用安全 |
| `revert_patches` 改为批量 checkout 后，单文件失败的行为从"跳过"变为"部分失败" | 恢复完整性 | 批量 checkout 失败的文件 fallback 到 `ls-tree` 检查 + 单文件处理（与原 `restore_file` 逻辑一致） |
| `undo()` / `redo()` 中 `acquire_lock` 同步调用阻塞事件循环 | 心跳/超时机制失效，Manager 误判进程异常 | 使用 `await asyncio.to_thread(...)` 包装（已在 Fix B3 步骤中明确） |
| `GitManager.reset()` 执行时其他进程持有旧 `FileLock` | 新实例创建新 `FileLock`，但锁文件相同 | `reset()` 仅删除 Python 层单例，不删除磁盘锁文件；`fcntl.flock` 基于文件 fd 而非 Python 对象，新实例的 `FileLock` 对同一锁文件操作仍与旧锁互斥 |
| `SessionRevertService` 构造函数签名变化导致调用方 break | 集成风险 | Task 1.2 Part D 要求搜索并更新所有调用方；CP2 验证 |
| 幽灵文件批量检查：`git ls-files --cached` 参数数量超过系统 ARG_MAX | 极端场景 | 实际场景中幽灵文件数量 < 100；如超 200 个则分批（每批 100 个） |

## 后续优化（不在本计划范围）
- **`git status --porcelain -z` 替换 3 条变更发现命令**：需充分测试 rename / submodule / sparse checkout 场景，建议独立计划 + 独立分支
- **GitPython in-process API**：减少 subprocess 开销，需评估 `git.Repo.git` 对象与 `asyncio` 的兼容性
