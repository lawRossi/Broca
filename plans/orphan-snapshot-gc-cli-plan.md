# Orphan Snapshot GC - CLI 集成计划（v2）

## 概述
- **目标**：将 legacy 分支的 `gc_snapshots()` 移植并增强，集成到 `broca snapshot gc` CLI 子命令
- **背景**：legacy 分支已有基础实现（`.workspace` 元数据 + 扫描），但缺少 DB 对比、FileLock、dry-run 模式和 CLI 集成
- **约束条件**：
  - CLI 同步，DB 异步，需 `asyncio.run()` 桥接
  - 必须使用 FileLock 保护删除操作
  - 默认 dry-run，`--force` 才执行删除
  - 需向后兼容：无 `.workspace` 元数据的旧目录，通过 hash 对比 DB 来判定

## 相关材料
- **Legacy 实现**: `git show 3f9598d` — `gc_snapshots()` + `.workspace` 元数据
- **CLI 入口**: `broca/cli/main.py` — `create_parser()` / `main()`
- **GitManager**: `broca/snapshot/git_manager.py` — `initialize()` / `cleanup()` / `FileLock` / `_get_repo_path()`
- **Config**: `broca/configs.py` — `get_configs().snapshot_home`
- **测试参考**: `broca/tests/test_cleanup_service.py`

## 总体方案

### 检测逻辑（双通道）

对 `~/.broca/snapshots/<dir>/` 下每个子目录：

| 通道 | 条件 | 判定 |
|------|------|------|
| A: `.workspace` 元数据 | 目录存在 → 读 `.workspace` → workspace 路径不存在 | 孤儿 |
| B: DB hash 对比 | 无 `.workspace` 文件 → 用 hash 对比 DB 中所有 workspace 的 hash | 不在集合中 → 孤儿 |

两个通道互补：通道 A 覆盖"workspace 目录被删"的场景，通道 B 覆盖"workspace 还在但 session 全删了"的场景。

### 命令设计

```
broca snapshot gc [OPTIONS]

  -y, --force    实际执行删除（默认为 dry-run）
  --home PATH    指定 snapshot 根目录
```

## 执行计划

### Phase 1: 移植 + 增强 + CLI 集成

**目标**：完成 `broca snapshot gc` 完整实现

**阶段验收标准**：
- [ ] `broca snapshot gc` dry-run 正确列出孤儿（两种检测通道）
- [ ] `broca snapshot gc --force` 正确删除（带 FileLock）
- [ ] `GitManager.initialize()` 自动写入 `.workspace` 元数据
- [ ] 回归测试通过

#### Task 1.1: 移植 `.workspace` 元数据 + 增强 `gc_snapshots()`

- **目标**：在 `broca/snapshot/git_manager.py` 中移植 legacy 的 `.workspace` 写入逻辑，新增增强版 `gc_snapshots()`
- **步骤**：
  1. 在 `GitManager.initialize()` 中添加：首次初始化时写入 `.workspace` 文件（`self.repo_path / ".workspace"` 内容为 `str(self.workspace_path)`）
  2. 新增模块级函数 `gc_snapshots(snapshot_home=None, *, dry_run=False, delete_fn=None) -> list[dict]`：
     - `snapshot_home` 参数：默认 `get_configs().snapshot_home`
     - `dry_run`：True 时只收集不删除
     - `delete_fn`：可注入的删除函数（方便测试），默认使用 FileLock + rmtree
  3. 对每个子目录执行双通道检测：
     - 通道 A：有 `.workspace` 文件 → 读路径 → `Path(ws).exists()` 为 False → 孤儿
     - 通道 B：无 `.workspace` 文件 → 计算 DB 中所有 workspace 的 hash 集合 → 目录名不在集合中 → 孤儿
  4. 返回 `list[dict]`，每项 `{"name": dir_name, "workspace": str|None, "reason": "workspace_deleted"|"no_session"}`
  5. 不使用 `_gc_done` 模块级标志（CLI 按需调用）
- **预期产出**：`broca/snapshot/git_manager.py` 中新增 `gc_snapshots()` 函数 + `initialize()` 中 `.workspace` 写入
- **验收标准**：
  - [ ] 新初始化的 workspace 的 snapshot 目录包含 `.workspace` 文件
  - [ ] `gc_snapshots(dry_run=True)` 返回孤儿列表但不删除
  - [ ] `gc_snapshots(dry_run=False)` 使用 FileLock 保护删除
  - [ ] 无 `.workspace` 的旧目录通过 hash 对比 DB 来判定
  - [ ] 无模块级状态（可多次调用）

#### Task 1.2: CLI 集成 — `broca snapshot gc`

- **目标**：在 `broca/cli/main.py` 中新增 `snapshot gc` 子命令
- **步骤**：
  1. `create_parser()` 中新增 `snapshot` 子解析器 → `gc` 子命令（`--force/-y`、`--home`）
  2. 实现 `cmd_snapshot_gc(args)`：
     - 调用 `gc_snapshots(snapshot_home=args.home, dry_run=not args.force)`
     - 无孤儿：打印 "✅ 无孤儿 snapshot 目录"
     - dry-run：打印孤儿列表（目录名、workspace 路径/原因、磁盘占用）
     - force：删除后打印成功/失败汇总
  3. `main()` 添加 `command == "snapshot"` 分发
  4. 更新顶部 docstring 和 epilog
- **预期产出**：`broca/cli/main.py` 中新增 `cmd_snapshot_gc()` + parser 配置
- **验收标准**：
  - [ ] `broca snapshot gc --help` 正确显示帮助
  - [ ] `broca snapshot gc` dry-run 模式列出孤儿，不删除
  - [ ] `broca snapshot gc --force` 实际删除并报告结果

#### Task 1.3: 编写回归测试

- **目标**：`broca/tests/test_snapshot_gc.py`
- **步骤**：
  1. 创建测试文件，覆盖以下用例：
     - `test_gc_workspace_deleted`：`.workspace` 指向不存在路径 → 判定孤儿
     - `test_gc_workspace_exists`：`.workspace` 指向存在路径 → 非孤儿
     - `test_gc_no_workspace_file_db_match`：无 `.workspace`，hash 在 DB workspace 集合中 → 非孤儿
     - `test_gc_no_workspace_file_no_db_match`：无 `.workspace`，hash 不在集合中 → 孤儿
     - `test_gc_dry_run_no_delete`：dry_run=True 时不删除
     - `test_gc_delete_with_lock`：dry_run=False 时调用 delete_fn
     - `test_gc_empty_home`：snapshot_home 不存在 → 返回空
     - `test_gc_initialize_writes_workspace_file`：initialize() 后 `.workspace` 存在且内容正确
  2. 使用 `tmp_path` fixture 模拟目录结构
  3. DB 查询通过 `delete_fn` 参数或 mock 注入，避免依赖真实 DB
  4. 运行 `pytest broca/tests/test_snapshot_gc.py -v`
- **预期产出**：`broca/tests/test_snapshot_gc.py`
- **验收标准**：
  - [ ] 所有测试通过
  - [ ] 覆盖双通道检测（通道 A + 通道 B）
  - [ ] 覆盖 dry-run / force / 空目录 / 初始化元数据

## 风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| 旧 snapshot 目录无 `.workspace` 文件 | 通道 A 失效 | 通道 B 兜底（hash 对比 DB） |
| DB 文件不存在 | 通道 B 失效 | 仅通道 A 有效；全为孤儿风险由 dry-run 默认模式保护 |
| 并发删除 | 数据损坏 | FileLock 保护每个目录的删除操作 |
