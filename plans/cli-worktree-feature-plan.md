# Broca CLI Worktree 功能

## 概述
- **目标**：为 Broca CLI 增加 `worktree` 子命令，基于 `git worktree` 实现多分支并行开发，创建 worktree 时自动创建 Broca session（通过 Web API），删除 worktree 时同步删除关联 session
- **背景**：用户希望在同一个 git 仓库中并行工作多个分支，每个分支拥有独立的 Broca session（独立的 Agent 实例、独立的上下文），通过 git worktree 实现文件系统级别的隔离
- **约束条件**：
  - worktree 目录统一放在 `<repo-root>/.worktrees/` 下
  - session 创建/删除通过 Web API（`http://localhost:9000/api/session/`）完成，无需认证（loopback）
  - 分支不存在时自动创建
  - `list` 仅展示 Broca 管理的 worktree（`.worktrees/` 目录下的）

## 相关材料
- CLI 入口：`broca/cli/main.py`（`create_parser()` + `main()` 函数）
- Web API Session 端点：`broca-web/backend/app/api/session.py`
- 现有 CLI HTTP 请求模式：`broca/cli/main.py` 中 `run` 命令的 `urllib.request` 用法
- Session 模型：`broca/session/models.py`（`workspace` 字段关联工作目录）
- Session API 规范：
  - 创建：`POST http://localhost:9000/api/session/sessions` body: `{"workspace": "...", "description": "..."}`
  - 查询：`GET http://localhost:9000/api/session/sessions?limit=100`
  - 删除：`DELETE http://localhost:9000/api/session/{session_id}`
- Git worktree 官方文档：https://git-scm.com/docs/git-worktree

## 总体方案

### 设计思路

`broca worktree` 是一个 CLI 子命令，提供 `create`/`delete`/`list` 三个子操作：

```
broca worktree create <branch> [--description <desc>] [--provider <p>] [--model <m>]
broca worktree delete <branch> [--force]
broca worktree list
```

**核心流程：**

```
create:
  1. 确认当前目录在 git 仓库内（git rev-parse --git-dir）
  2. 确定 worktree 路径：<repo-root>/.worktrees/<branch-name>/
  3. git worktree add <path> <branch>（分支不存在则自动 git branch 创建）
  4. 调用 Web API POST /api/session/sessions 创建 session（workspace = worktree path）
  5. 输出创建结果（session_id、worktree path、branch）

delete:
  1. 确认 worktree 存在
  2. 通过 Web API 查找关联 session（workspace == worktree path）
  3. 调用 Web API DELETE /api/session/{session_id} 删除 session（自动停止 runner + 清理）
  4. git worktree remove <path>（--force 时用 git worktree remove --force）
  5. 如果 worktree 目录为空则删除目录
  6. git worktree prune（清理残留引用）

list:
  1. git worktree list --porcelain（获取所有 worktree）
  2. 过滤出 .worktrees/ 目录下的
  3. 调用 Web API GET /sessions 获取 session 状态
  4. 按 workspace 匹配，展示 branch + worktree path + session 信息
```

### 关键决策

| 决策 | 选择 | 理由 |
|------|------|------|
| worktree 位置 | `<repo-root>/.worktrees/` | 用户选择，IDE 可直接识别 |
| 分支不存在 | 自动创建 | 用户选择，最便捷 |
| session 创建方式 | 调用 Web API | 用户指定，复用完整 session 生命周期（含 runner 启动） |
| session 查找 | GET /sessions + 客户端过滤 workspace | API 无 workspace 过滤参数，客户端过滤最可靠 |
| git 操作方式 | `subprocess.run("git ...")` | CLI 场景是同步的，用 subprocess 比 async 更简洁 |
| HTTP 请求 | stdlib `urllib.request` | 与现有 `run` 命令一致，无额外依赖 |

## 执行计划

### Phase 1: 实现 broca worktree CLI 命令

**目标**：完成 `broca worktree create/delete/list` 三个子命令的完整实现

**阶段验收标准**：
- [ ] `broca worktree create feature/x` 成功创建 worktree 和 session
- [ ] `broca worktree delete feature/x` 成功删除 session 和 worktree
- [ ] `broca worktree list` 正确展示所有 Broca 管理的 worktree 及关联 session
- [ ] 非 git 仓库中运行给出友好错误提示
- [ ] worktree 已存在时给出明确报错
- [ ] 分支不存在时自动创建
- [ ] `--force` 标志对 dirty worktree 生效

#### Task 1.1: 创建 worktree 模块基础结构

- **目标**：创建 `broca/cli/worktree.py` 模块，包含 git 操作辅助函数和 API 调用辅助函数
- **步骤**：
  1. 创建文件 `broca/cli/worktree.py`
  2. 实现 `get_repo_root() -> Path`：运行 `git rev-parse --show-toplevel` 获取仓库根目录，失败则抛 `RuntimeError("Not in a git repository")`
  3. 实现 `get_worktrees_dir(repo_root: Path) -> Path`：返回 `<repo_root>/.worktrees`
  4. 实现 `git_worktree_add(repo_root: Path, branch: str, worktree_path: Path) -> None`：
     - 检查分支是否存在：`git rev-parse --verify <branch>`
     - 如果不存在：`git branch <branch>`（基于 HEAD 创建新分支）
     - 执行 `git worktree add <worktree_path> <branch>`
  5. 实现 `git_worktree_remove(repo_root: Path, worktree_path: Path, force: bool) -> None`：
     - 构建命令 `git worktree remove <path>`，force 时加 `--force`
     - 执行后调用 `git worktree prune`
  6. 实现 `git_worktree_list(repo_root: Path) -> list[dict]`：
     - 执行 `git worktree list --porcelain`
     - 解析输出为 `[{path, branch, bare, detached}, ...]`
  7. 实现 `api_request(method: str, path: str, body: dict | None = None, base_url: str = "http://localhost:9000") -> dict`：
     - 使用 `urllib.request`（与 `run` 命令一致）
     - 返回 `result["data"]`，code != 200 时抛异常
  8. 实现 `find_session_by_workspace(workspace: str, base_url: str) -> dict | None`：
     - 调用 `GET /api/session/sessions?limit=200`
     - 遍历返回的 sessions 列表，匹配 `session["workspace"] == workspace`
     - 返回匹配的 session dict 或 None
- **预期产出**：`broca/cli/worktree.py` 文件，包含所有辅助函数
- **验收标准**：
  - [ ] 所有函数有类型注解和 docstring
  - [ ] `get_repo_root()` 在非 git 目录中抛出带明确消息的 `RuntimeError`
  - [ ] `git_worktree_list` 正确解析 `--porcelain` 输出格式
  - [ ] `api_request` 正确处理 HTTP 错误和非 200 code
  - [ ] 所有 git 操作通过 `subprocess.run(capture_output=True, text=True)` 执行，检查 returncode

#### Task 1.2: 实现 `worktree create` 子命令

- **目标**：实现 `cmd_worktree_create(args)` 函数
- **步骤**：
  1. 在 `worktree.py` 中实现 `cmd_worktree_create(args) -> None`：
     ```
     流程：
     1. repo_root = get_repo_root()
     2. worktrees_dir = get_worktrees_dir(repo_root)
        - 如果不存在则 mkdir -p
     3. branch = args.branch（必需参数）
     4. worktree_path = worktrees_dir / branch
        - 将 branch 中的 `/` 替换为 `_` 作为目录名（避免嵌套目录问题）
        - 例：branch="feature/auth" → dir_name="feature_auth"
     5. 检查 worktree_path 是否已存在：
        - 如果存在：检查是否已有 git worktree（git worktree list 中查找）
        - 如果已有 worktree：报错 "Worktree for branch '<branch>' already exists at <path>"
        - 如果只有残留目录：尝试 `git worktree prune` 后重试
     6. git_worktree_add(repo_root, branch, worktree_path)
     7. 调用 Web API 创建 session：
        - description: f"worktree:{branch}"
        - workspace: str(worktree_path.resolve())
        - provider/model: 从 args 获取（可选）
        - 如果 Web API 不可达（ConnectionRefusedError），warning 提示但仍成功（session 可后续手动创建）
     8. 输出结果：
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         ✓ Worktree created
         Branch:     feature/auth
         Path:       /repo/.worktrees/feature_auth
         Session:    session_abcd1234
         Workspace:  /repo/.worktrees/feature_auth
         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
     ```
  2. 在 `broca/cli/main.py` 的 `create_parser()` 中注册 `worktree` 子命令：
     ```python
     wt_sub = sub.add_parser("worktree", help="Manage git worktrees with Broca sessions",
                              formatter_class=argparse.RawDescriptionHelpFormatter)
     wt_sub.add_argument("action", choices=["create", "delete", "list"], help="Action to perform")
     wt_sub.add_argument("branch", nargs="?", default=None, help="Branch name (required for create/delete)")
     wt_sub.add_argument("--description", "-d", default=None, help="Session description")
     wt_sub.add_argument("--provider", "-p", default=None, help="LLM provider override")
     wt_sub.add_argument("--model", "-m", default=None, help="LLM model override")
     wt_sub.add_argument("--force", "-f", action="store_true", help="Force remove (for dirty worktrees)")
     ```
  3. 在 `main()` 函数中添加 dispatch：
     ```python
     elif command == "worktree":
         from broca.cli.worktree import cmd_worktree_create, cmd_worktree_delete, cmd_worktree_list
         if args.action == "create":
             cmd_worktree_create(args)
         elif args.action == "delete":
             cmd_worktree_delete(args)
         elif args.action == "list":
             cmd_worktree_list(args)
     ```
- **预期产出**：`broca worktree create <branch>` 命令可执行
- **验收标准**：
  - [ ] 在 git 仓库中运行 `broca worktree create feature/test` 成功创建 worktree 和 session
  - [ ] 分支不存在时自动创建（`git branch feature/test`）
  - [ ] worktree 已存在时报错且退出码非零
  - [ ] 非 git 目录中运行提示 "Not in a git repository" 并退出
  - [ ] Web API 不可达时输出 warning 但 worktree 创建成功
  - [ ] 输出的 session_id 可通过 `GET /api/session/{session_id}` 验证存在

#### Task 1.3: 实现 `worktree delete` 子命令

- **目标**：实现 `cmd_worktree_delete(args)` 函数
- **步骤**：
  1. 在 `worktree.py` 中实现 `cmd_worktree_delete(args) -> None`：
     ```
     流程：
     1. repo_root = get_repo_root()
     2. branch = args.branch（必需）
     3. 计算 worktree_path（同 create 的命名规则）
     4. 验证 worktree 存在：
        - 通过 git_worktree_list 检查
        - 如果不存在：报错 "No worktree found for branch '<branch>'"
     5. 查找关联 session：
        - find_session_by_workspace(str(worktree_path.resolve()))
        - 如果找到：
          - 输出 "Deleting session: {session_id}"
          - 调用 DELETE /api/session/{session_id}
          - 如果 API 失败，warning 提示（继续执行 git 删除）
        - 如果未找到：提示 "No Broca session found for this worktree"
     6. git_worktree_remove(repo_root, worktree_path, force=args.force)
        - 如果 git worktree remove 失败（dirty）且未加 --force：
          报错 "Worktree has uncommitted changes. Use --force to discard."
     7. 输出结果：
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         ✓ Worktree deleted
         Branch:     feature/test
         Path:       /repo/.worktrees/feature_test
         Session:    session_abcd1234 (deleted)
         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
     ```
  2. 错误处理：
     - worktree 有未提交更改且未 `--force`：拒绝删除，提示用户
     - session 删除失败：warning 但继续删除 worktree
     - git worktree remove 失败：输出 git 错误信息
- **预期产出**：`broca worktree delete <branch>` 命令可执行
- **验收标准**：
  - [ ] 正常删除：session 从 DB 中消失 + worktree 目录被移除 + `git worktree list` 中不再显示
  - [ ] dirty worktree 无 `--force` 时拒绝删除并给出明确提示
  - [ ] dirty worktree 加 `--force` 时强制删除
  - [ ] worktree 不存在时报错退出
  - [ ] Web API 不可达时仍成功删除 worktree（仅 warning）
  - [ ] 删除后 `.worktrees/<branch>/` 目录不存在

#### Task 1.4: 实现 `worktree list` 子命令

- **目标**：实现 `cmd_worktree_list(args)` 函数
- **步骤**：
  1. 在 `worktree.py` 中实现 `cmd_worktree_list(args) -> None`：
     ```
     流程：
     1. repo_root = get_repo_root()
     2. worktrees = git_worktree_list(repo_root)
     3. 过滤：仅保留 path 在 worktrees_dir 下的
     4. 获取 sessions：
        - 尝试调用 GET /api/session/sessions?limit=200
        - 如果 API 不可达，sessions = []（降级展示）
        - 建立 workspace → session 的映射
     5. 输出表格：
        BRANCH            PATH                                  SESSION           STATUS
        feature/auth      .worktrees/feature_auth               session_xxx       running
        bugfix/123        .worktrees/bugfix_123                 -                 -
        ─────────────────────────────────────────────────────────────────────────────
        2 worktrees
     ```
     - BRANCH：从 worktree 的 branch 字段获取（detached HEAD 显示 "DETACHED"）
     - PATH：相对于 repo_root 的路径
     - SESSION：关联的 session_id（无则显示 `-`）
     - STATUS：runner 状态（running/stopped/-）
  2. 如果没有 Broca 管理的 worktree：输出 "No Broca worktrees found."
- **预期产出**：`broca worktree list` 命令可执行
- **验收标准**：
  - [ ] 正确列出 `.worktrees/` 下的所有 worktree
  - [ ] 关联的 session 和 runner 状态正确显示
  - [ ] 无 Broca worktree 时友好提示
  - [ ] Web API 不可达时降级展示（仅 git worktree 信息，session 列显示 `-`）
  - [ ] 不显示 main worktree 和其他非 `.worktrees/` 下的 worktree

#### Task 1.5: 处理 `.gitignore` 和边缘情况

- **目标**：确保 `.worktrees/` 目录被正确忽略，处理各种边缘情况
- **步骤**：
  1. 在 `worktree.py` 中实现 `ensure_worktrees_gitignored(repo_root: Path) -> None`：
     - 检查 `<repo_root>/.gitignore` 是否包含 `.worktrees/`
     - 如果没有，追加 `.worktrees/` 到 `.gitignore`（末尾加换行）
     - 在 `cmd_worktree_create` 中首次创建 worktree 前调用
  2. 处理以下边缘情况：
     - `repo_root/.worktrees` 目录已存在但不是 git worktree 目录：提示用户
     - 仓库无 `main`/`master` 分支（bare repo 或 empty repo）：`git worktree add` 会失败，传递 git 错误信息
     - branch 名称包含特殊字符（如 `/`）：目录名用 `_` 替代
     - 磁盘空间不足：传递 git 原始错误
  3. 添加 `broca/cli/worktree.py` 到 `broca/cli/__init__.py`（如果有的话）或确认导入路径正确
- **预期产出**：`.worktrees/` 自动加入 `.gitignore`，边缘情况有合理处理
- **验收标准**：
  - [ ] 首次 create 后 `.gitignore` 包含 `.worktrees/`
  - [ ] 重复 create 不会重复追加 `.gitignore`
  - [ ] 分支名 `feature/sub-branch` 对应的目录为 `feature_sub-branch`（不含 `/`）
  - [ ] 所有 git 命令失败时输出 stderr 信息给用户

## 风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| Web API 未启动时 create 仍应成功 | worktree 已创建但无 session | 捕获 ConnectionRefusedError，输出 warning，提示用户启动服务后手动创建 session |
| 用户手动删除了 `.worktrees/` 目录但 git worktree 记录仍在 | `git worktree list` 显示 stale entry | `list` 时自动调用 `git worktree prune` 清理 |
| 两个 CLI 进程同时操作同一 worktree | git 锁竞争 | `git worktree add/remove` 本身有文件锁保护，失败时传递 git 错误 |
| session 已存在但 worktree 被手动删除 | 孤儿 session | `list` 中显示 worktree 状态为 "missing"，`delete` 时先检查 worktree 是否存在 |
| `.gitignore` 文件不存在 | 无法追加 | 创建新的 `.gitignore` 文件 |

## 未解决的问题
- 暂无（所有关键设计决策已与用户确认）
