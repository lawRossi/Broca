# 修复 Session Runner 环境变量泄漏到 Bash 工具

## 概述

- **目标**：确保 bash 工具 / ProcessManager（含 Scheduler 定时命令）执行用户命令时使用"干净"的环境，剥离 runner 内部变量，并自动适配 workspace 虚拟环境
- **背景**：`build_runner_env()` 为 runner 子进程设置了 `PYTHONPATH`（repo root 首位）、`PYTHONSAFEPATH=1`、`BROCA_RUNNER_CHILD`、`LITELLM_LOCAL_MODEL_COST_MAP`，并 pop 了 `VIRTUAL_ENV`。Bash 工具和 ProcessManager 通过 `create_subprocess_shell` 执行用户命令时未传 `env` 参数，完整继承了 runner 的污染环境变量，导致：
  - `PYTHONPATH` 中的 repo root 污染用户 Python 项目的 import 解析
  - `PYTHONSAFEPATH=1` 改变 `python -m` 行为（不将 cwd 加入 `sys.path[0]`）
  - `VIRTUAL_ENV` 被移除导致依赖该变量的工具（`pip`/`uv`/`conda`）异常
  - workspace 有自己的 venv 时，`python` 仍指向 Broca 服务 venv
- **约束条件**：
  - 不得影响 runner 自身运行（runner 进程仍需要 `PYTHONPATH`/`PYTHONSAFEPATH`）
  - 向后兼容：无 venv 的 workspace 中，用户命令获得 supervisor 进程的环境（`PYTHONPATH`/`VIRTUAL_ENV` 恢复到服务进程启动前的值）；注意 `PATH` 中仍保留服务 venv 的 `bin/` 路径（`build_runner_env()` 不修改 `PATH`），因此无 venv 的 workspace 中 `python` 仍指向服务 venv 解释器——此为已知限制（见风险表）
  - 同时修复 `bash.py`（前台）、`process_manager.py`（后台）及 Scheduler `_execute_command()`（定时命令，经由 ProcessManager 自动覆盖）

### 术语约定

| 术语 | 说明 |
|------|------|
| **supervisor** | 服务进程（FastAPI backend 所在进程），是 `build_runner_env()` 的调用方，负责写入 `_BROCA_ORIG_*` 变量 |
| **runner** | runner 子进程（`broca.session_runner.runner`），消费 `_BROCA_ORIG_*`，执行工具调用（bash/process_manager） |
| **workspace** | 用户项目目录，即 runner 子进程的 `cwd`（由 launcher `cwd=workspace` 指定） |

## 相关材料

- `broca/session_runner/process/launcher.py` — `build_runner_env()` 定义 + `_BROCA_ORIG_*` 契约写入方
- `broca/tools/bash.py` — `_run_code_async()` 前台执行（`create_subprocess_shell`）
- `broca/process_manager.py` — `start_process()` 后台执行（`create_subprocess_shell`）
- `broca/scheduler.py` — `_execute_command()` 定时命令执行（调用 `ProcessManager.start_process()`）
- `broca/snapshot/git_manager.py` — `_run_git()` 内部 git 操作（`create_subprocess_exec`，非用户命令）
- `broca/agent_manager.py` — `DefaultAgentFactory._detect_workspace_venvs()`：既有 venv 扫描实现（候选列表 + 校验方式），Task 1.1 需下沉复用
- `broca/tools/tool.py` — `ToolCallContext`（含 `workspace` 字段）
- `broca/utils/__init__.py` — 无需修改（空文件），新模块 `env.py` 自动加入包
- `broca/tests/test_runner_launcher.py` — launcher 测试（含 env 断言）
- `broca/tests/test_process_manager.py` — ProcessManager 测试
- 参考：[Python venv 文档](https://docs.python.org/3/library/venv.html) — venv 目录结构约定

## 总体方案

核心思路：**在 `build_runner_env()` 中保存服务进程原始值（`_BROCA_ORIG_*`），新增 `build_user_env(workspace)` 工具函数在用户命令执行前重建干净环境。**

### `_BROCA_ORIG_*` 跨进程契约

```
supervisor（服务进程）                         runner（子进程）
─────────────────────                         ────────────────
build_runner_env() 写入:                       build_user_env() 读取并消费:
  _BROCA_ORIG_PYTHONPATH                       → 还原 PYTHONPATH
  _BROCA_ORIG_VIRTUAL_ENV                      → 还原 VIRTUAL_ENV
  _BROCA_ORIG_VIRTUAL_ENV_PROMPT               → 还原 VIRTUAL_ENV_PROMPT

runner 进程 os.environ 保留 _BROCA_ORIG_*（不 pop），
build_user_env() 在构造用户命令 env 时 pop 掉全部 _BROCA_ORIG_* 前缀变量，
确保用户命令子进程看不到这些内部变量。
```

> 契约文档落点：`launcher.py` 模块 docstring（与现有 argv 契约写法一致）+ `broca/utils/env.py` 顶部注释。

### 环境重建逻辑（三层）

| 层 | 操作 | 目的 |
|----|------|------|
| 1. 剥离 | 移除 runner 内部标记变量 + 全部 `_BROCA_ORIG_*` 前缀变量 | 不让 runner 内部标记泄漏到用户 shell |
| 2. 恢复 | 从 `_BROCA_ORIG_*` 恢复 `PYTHONPATH`/`VIRTUAL_ENV`/`VIRTUAL_ENV_PROMPT` 到 supervisor 进程原始值 | 还原用户"本应拥有"的环境 |
| 3. 适配 | 若 workspace 存在 venv，将其 `bin/`（或 `Scripts/`）加入 PATH 首位并设置 `VIRTUAL_ENV`/`VIRTUAL_ENV_PROMPT` | 让 `python` 指向 workspace venv（与用户手动 activate 等效） |

**第 1 层剥离清单（精确规则）**：

| 剥离 | 保留 |
|------|------|
| `PYTHONSAFEPATH` | `BROCA_HOME` |
| `BROCA_RUNNER_CHILD` | `BROCA_DATABASE_DIR` |
| `LITELLM_LOCAL_MODEL_COST_MAP` | `BROCA_COMPONENTS_CONFIG` |
| 所有 `_BROCA_ORIG_*` 前缀变量 | `BROCA_RUN_INTEGRATION` |
| `PYTHONPATH`（将在第 2 层按需恢复） | 其他 `BROCA_*` 用户配置变量 |

> 判定理由：上表"剥离"列是 runner 进程自身的运行时标记，用户 shell 不需要；"保留"列是用户/部署侧的配置变量，用户命令中可能需要（如 `BROCA_DATABASE_DIR` 指向自定义 DB 路径）。

**第 2 层为什么恢复 `VIRTUAL_ENV`（而非仅剥离）**：
- `pip`/`uv` 等工具依赖 `VIRTUAL_ENV` 判断目标环境。用户 `source .venv/bin/activate` 后启动 Broca，服务进程 `os.environ` 含 `VIRTUAL_ENV`。若 runner 不恢复，用户命令中 `pip install` 会作用于系统环境而非用户 venv，产生难以排查的"装到错误环境"问题
- `build_runner_env()` 之所以 pop `VIRTUAL_ENV` 是因为 runner 子进程用 `sys.executable`（= 服务 venv 解释器）启动，`VIRTUAL_ENV` 指向用户 venv 会导致 `python -m` 行为混乱。但用户命令是独立 shell，恢复 `VIRTUAL_ENV` 无此问题

**第 3 层优先级高于第 2 层**：workspace venv 覆盖服务进程 venv。

**venv 探测唯一来源**：`broca/utils/env.py::find_workspace_venv()`，候选列表与校验方式与 `DefaultAgentFactory._detect_workspace_venvs()`（`broca/agent_manager.py:477-518`）保持一致：
- 候选（按优先级）：`.venv` → `venv` → `env` → `.env` → `virtualenv`
- 校验：检查 `bin/python` / `bin/python3` / `Scripts/python.exe` 存在（而非 `bin/activate`——后者不覆盖仅有 `python` 软链的 venv 构建方式）
- Task 1.1 需将 `agent_manager._detect_workspace_venvs()` 中的 venv 目录检测逻辑下沉为 `find_workspace_venv()` 公共函数，`agent_manager` 改为调用该公共函数，避免两套实现分叉

## 执行计划

### Phase 1: 环境工具层

**目标**：创建通用的 `build_user_env()` 函数，修改 `build_runner_env()` 保存原始值，更新既有 launcher 测试

> **并行说明**：Task 1.1 与 Task 1.2 互相独立（1.1 创建新文件，1.2 修改现有文件），可并行执行。Task 1.3 依赖 Task 1.1。Task 1.4 依赖 Task 1.2。

**阶段验收标准**：
- [ ] `broca/utils/env.py` 模块存在且包含 `build_user_env()` 和 `find_workspace_venv()`
- [ ] `build_runner_env()` 保存 `_BROCA_ORIG_PYTHONPATH`/`_BROCA_ORIG_VIRTUAL_ENV`/`_BROCA_ORIG_VIRTUAL_ENV_PROMPT`
- [ ] `build_user_env()` 在含 `_BROCA_ORIG_*` 的环境下将 PYTHONPATH 还原为原始值，检测到 workspace venv 时 PATH 首位为 venv/bin
- [ ] `pytest broca/tests/test_env_utils.py -v` 全绿
- [ ] `pytest broca/tests/test_runner_launcher.py -v` 全绿（含新增 `_BROCA_ORIG_*` case）

#### Task 1.1: 创建 `broca/utils/env.py`

- **目标**：提供 `build_user_env(workspace)` 和 `find_workspace_venv(workspace)` 工具函数
- **步骤**：
  1. 新建 `broca/utils/env.py`
  2. 实现 `find_workspace_venv(workspace: str) -> Path | None`：
     - 候选列表：`workspace/.venv`、`workspace/venv`、`workspace/env`、`workspace/.env`、`workspace/virtualenv`
     - 校验方式：`bin/python` → `bin/python3` → `Scripts/python.exe`（与 `agent_manager._detect_workspace_venvs` 一致）
     - 返回 venv 根目录 Path，未找到返回 None
     - **`workspace` 入参必须为绝对路径**；若调用方传入相对路径/None，函数内 `os.path.abspath()` 转换
  3. 实现 `build_user_env(workspace: str | None = None) -> dict[str, str]`：
     - `workspace=None` 时默认用 `os.getcwd()`（runner 进程 cwd == workspace）
     - 从 `os.environ` copy 开始
     - **剥离**（精确清单，见总体方案表格）：`PYTHONSAFEPATH`、`BROCA_RUNNER_CHILD`、`LITELLM_LOCAL_MODEL_COST_MAP`、所有 `_BROCA_ORIG_*` 前缀变量
     - **恢复 PYTHONPATH**：若 `_BROCA_ORIG_PYTHONPATH` 存在则设回，否则 pop `PYTHONPATH`
     - **恢复 VIRTUAL_ENV/VIRTUAL_ENV_PROMPT**：若 `_BROCA_ORIG_VIRTUAL_ENV` 存在则设回，否则 pop
     - **适配 workspace venv**（优先级最高）：调用 `find_workspace_venv()`，若找到则：
       - `PATH` = `venv_bin + os.pathsep + 现有 PATH`（**前置前先去重**：若 venv bin 路径已在 PATH 中，不重复插入）
       - `VIRTUAL_ENV` = venv 绝对路径
       - `VIRTUAL_ENV_PROMPT` = venv 目录名（如 `.venv`，与 `bin/activate` 脚本生成的值一致）
     - **平台处理**：`_venv_bin_dir(venv_root, platform: str)` 纯函数，`platform="posix"` → `venv_root/"bin"`，`platform="nt"` → `venv_root/"Scripts"`。`build_user_env()` 内部用 `sys.platform` 调用，测试直接注入 platform 参数
  4. **防御性处理**：`build_user_env()` 整体包裹 try/except，异常时 log warning 并 fallback 到"仅剥离第 1 层清单变量 + 从 `_BROCA_ORIG_*` 恢复，跳过 venv 适配"，确保用户命令不因 env 构建失败而无法执行
  5. **下沉 `agent_manager._detect_workspace_venvs()`**：将该方法中 venv 目录检测逻辑（候选列表 + `bin/python` 校验）重构为调用 `find_workspace_venv()`，保留 `_detect_workspace_venvs()` 的返回格式不变（`list[tuple[str, str]]`）
- **预期产出**：`broca/utils/env.py`（~80 行）+ 修改后的 `agent_manager.py`
- **验收标准**：
  - [ ] `build_user_env()` 在 runner 环境下（有 `_BROCA_ORIG_*`）正确还原 PYTHONPATH/VIRTUAL_ENV
  - [ ] `build_user_env()` 在非 runner 环境下（无 `_BROCA_ORIG_*`）仅剥离 4 个已知内部变量
  - [ ] 保留 `BROCA_HOME`、`BROCA_DATABASE_DIR` 等非 runner 标记变量
  - [ ] workspace 含 `.venv`（含 `bin/python`）时 PATH 首位为 `.venv/bin`，`VIRTUAL_ENV`/`VIRTUAL_ENV_PROMPT` 正确设置
  - [ ] workspace 无 venv 时不修改 PATH
  - [ ] PATH 前置前自动去重（venv bin 已在 PATH 中时不重复）
  - [ ] `build_user_env()` 遇到异常时不抛出，fallback 并 log warning
  - [ ] `agent_manager._detect_workspace_venvs()` 行为不变（调用 `find_workspace_venv()` 后逻辑等价）

#### Task 1.2: 修改 `build_runner_env()` 保存原始值

- **目标**：在 `launcher.py` 的 `build_runner_env()` 中保存 supervisor 进程原始环境变量
- **步骤**：
  1. 在修改 `PYTHONPATH` 之前，若原变量存在且非空，将原始值存入 `_BROCA_ORIG_PYTHONPATH`
  2. 在 pop `VIRTUAL_ENV` 之前，若原变量存在，将原始值存入 `_BROCA_ORIG_VIRTUAL_ENV`
  3. 同理处理 `VIRTUAL_ENV_PROMPT`
  4. 仅在原变量存在时才存（避免引入无意义的空值）
  5. 在 `launcher.py` 模块 docstring 的契约区域增加 `_BROCA_ORIG_*` 变量契约说明（与现有 argv 契约写法保持一致）
- **预期产出**：修改后的 `launcher.py`
- **验收标准**：
  - [ ] supervisor 进程有 `PYTHONPATH=/custom/path` 时，runner env 中 `_BROCA_ORIG_PYTHONPATH=/custom/path`
  - [ ] supervisor 进程无 `PYTHONPATH` 时，不设 `_BROCA_ORIG_PYTHONPATH`
  - [ ] supervisor 进程有 `VIRTUAL_ENV=/some/venv` 时，`_BROCA_ORIG_VIRTUAL_ENV=/some/venv` 被保存
  - [ ] 原有 `PYTHONPATH`/`PYTHONSAFEPATH`/`BROCA_RUNNER_CHILD`/`LITELLM_LOCAL_MODEL_COST_MAP` 行为不变
  - [ ] Runner 重启时 supervisor 重新调用 `build_runner_env()`，`_BROCA_ORIG_*` 基于新 supervisor 进程环境重建，无状态泄漏
  - [ ] `launcher.py` 模块 docstring 包含 `_BROCA_ORIG_*` 契约说明

#### Task 1.3: 编写 `build_user_env` 单元测试

- **目标**：覆盖 `build_user_env()` 和 `find_workspace_venv()` 的核心场景
- **步骤**：
  1. 新建 `broca/tests/test_env_utils.py`
  2. 测试场景：
     - runner 环境（有 `_BROCA_ORIG_*`）→ 还原 PYTHONPATH 为原始值，还原 VIRTUAL_ENV
     - 非 runner 环境（无 `_BROCA_ORIG_*`）→ 仅剥离 4 个内部变量
     - 非 runner 环境 → `BROCA_HOME`/`BROCA_DATABASE_DIR` 等保留
     - workspace 有 `.venv`（`tmp_path` 构造含 `bin/python` 的目录结构）→ PATH/VIRTUAL_ENV/VIRTUAL_ENV_PROMPT 正确
     - workspace 有 `venv` → 同上
     - workspace 有 `env` 但无 `bin/python`/`bin/python3`/`Scripts/python.exe` → 不识别为 venv
     - workspace 无任何 venv → PATH 不变
     - 优先级：workspace venv > 服务进程 VIRTUAL_ENV
     - PATH 去重：venv bin 已在 PATH 中时不重复前置
     - Windows 路径：`platform="nt"` 参数注入 → 检查 `Scripts/python.exe`（不 monkeypatch `os.name`）
     - 异常 fallback：`find_workspace_venv` 抛异常时 `build_user_env` 不崩溃
  3. 使用 `tmp_path` 构造隔离的真实目录结构（不触碰用户 workspace），`monkeypatch.setenv` 隔离环境变量
- **预期产出**：`broca/tests/test_env_utils.py`
- **验收标准**：
  - [ ] 所有场景测试通过
  - [ ] `pytest broca/tests/test_env_utils.py -v` 全绿

#### Task 1.4: 更新 `test_runner_launcher.py`

- **目标**：适配 `build_runner_env()` 新增的 `_BROCA_ORIG_*` 变量，新增保存逻辑测试
- **步骤**：
  1. 检查现有 env 断言是否因新增变量而失败（预计不失败——现有断言仅检查 `PYTHONPATH` 首项和 `PYTHONSAFEPATH`，无 env 全等断言）
  2. 新增 case：supervisor 进程有 `PYTHONPATH` 时 `_BROCA_ORIG_PYTHONPATH` 正确保存
  3. 新增 case：supervisor 进程无 `PYTHONPATH` 时不设 `_BROCA_ORIG_PYTHONPATH`
  4. 新增 case：supervisor 进程有 `VIRTUAL_ENV` 时 `_BROCA_ORIG_VIRTUAL_ENV` 正确保存
- **预期产出**：更新后的 `test_runner_launcher.py`
- **验收标准**：
  - [ ] `pytest broca/tests/test_runner_launcher.py -v` 全绿
  - [ ] 覆盖了 `_BROCA_ORIG_*` 保存逻辑（有值/无值两种 case）
- **依赖**：Task 1.2 完成

### Phase 2: 注入点改造

**目标**：在 bash 工具和 ProcessManager 执行用户命令时传入干净 env（Scheduler 定时命令经由 ProcessManager 自动覆盖）

> **并行说明**：Task 2.1 与 Task 2.2 互相独立（分别修改不同文件），可并行执行。Task 2.3 为验证步骤，依赖 2.1/2.2 完成。

**阶段验收标准**：
- [ ] `bash.py` 的 `_run_code_async()` 传入 `env` 参数（由 `build_user_env()` 构建）
- [ ] `process_manager.py` 的 `start_process()` 传入 `env` 参数（由 `build_user_env()` 构建）
- [ ] 后台执行路径（`background: true`，经 Scheduler → ProcessManager）同样获得干净 env
- [ ] 已有测试（`test_runner_launcher.py`、bash 相关测试）仍通过

#### Task 2.1: 修改 `broca/tools/bash.py`

- **目标**：`_run_code_async()` 使用干净 env
- **步骤**：
  1. 顶部添加 `from broca.utils.env import build_user_env`
  2. `_run_code_async()` 签名增加 `workspace: str | None = None` 参数
  3. 函数开头：`env = build_user_env(workspace)`
  4. `create_subprocess_shell(...)` 调用增加 `env=env`
  5. `_execute()` 中调用 `_run_code_async(code, workspace=context.workspace)` 传入 workspace
  6. `_run_background()` 无需修改：其路径经 Scheduler `_execute_command()` → ProcessManager 执行，已由 Task 2.2 覆盖
  7. 更新 bash 工具 `description` 属性：将 "Your default python path points to a special standalone python environment" 改为 "Prefer the workspace's virtual environment (`.venv`) when available; otherwise falls back to the service environment"
- **预期产出**：修改后的 `bash.py`
- **验收标准**：
  - [ ] `create_subprocess_shell` 调用包含 `env=env` 参数
  - [ ] `_execute()` 正确传递 `context.workspace`
  - [ ] 前台 `_run_code_async` 和后台 ProcessManager 均传入 `env=build_user_env(...)`，用户命令在两种模式下看到相同的环境（均不含 `PYTHONSAFEPATH`/`BROCA_RUNNER_CHILD`）
  - [ ] 工具 description 与"自动 venv 适配"新行为一致

#### Task 2.2: 修改 `broca/process_manager.py`

- **目标**：`start_process()` 使用干净 env
- **步骤**：
  1. 顶部添加 `from broca.utils.env import build_user_env`
  2. `start_process()` 中，在 `create_subprocess_shell` 调用前：
     ```python
     # cwd 是工作目录；venv 探测基于 cwd 所在目录（runner cwd == workspace）
     # Scheduler 调用时 cwd=None → build_user_env 回退到 os.getcwd() == workspace
     env = build_user_env(cwd)
     ```
  3. `create_subprocess_shell(wrapped_command, ..., env=env)` 增加 `env=env`
- **预期产出**：修改后的 `process_manager.py`
- **验收标准**：
  - [ ] `start_process()` 调用 `build_user_env(cwd)` 构建 env
  - [ ] `cwd=None` 时 `build_user_env` 回退到 `os.getcwd()`（runner 的 cwd = workspace）
  - [ ] Scheduler 触发的 command job（`scheduler._execute_command()` → `pm.start_process(command, process_id=job_id)`，`cwd` 未传 → None）自动获得干净环境

#### Task 2.3: 确认全局调用点无遗漏

- **目标**：验证所有用户命令执行点已覆盖，内部命令不需修改
- **步骤**：
  1. 确认 `scheduler._execute_command()` → `ProcessManager.start_process(command, process_id=job_id)` 未传 `cwd`：
     - `start_process` 中 `cwd=None` → `build_user_env(None)` → `os.getcwd()` = workspace（runner 进程 cwd）✓
  2. 运行 `grep -rn "create_subprocess_shell" broca/` 确认所有调用点：
     - `bash.py:302` → Task 2.1 已覆盖 ✓
     - `process_manager.py:149` → Task 2.2 已覆盖 ✓
  3. 运行 `grep -rn "create_subprocess_exec" broca/` 确认内部命令：
     - `snapshot/git_manager.py:498` → 内部 git 操作（非用户命令），`_run_git()` 用 `os.environ.copy()` 构造 env，`PYTHONPATH`/`PYTHONSAFEPATH` 会传入 git 子进程。**结论：接受现状**（git 钩子极少使用 Python，`PYTHONSAFEPATH` 对 git 无影响）；记入风险表
  4. 检查是否有其他调用点遗漏（如 `subprocess.run`/`subprocess.Popen` 直接调用）
- **预期产出**：无需代码修改或最小修改
- **验收标准**：
  - [ ] Scheduler 触发的命令执行使用干净环境（经由 ProcessManager）
  - [ ] `grep -rn "create_subprocess_shell" broca/` 输出中每个用户命令执行点均已传入 `env` 参数
  - [ ] 内部工具（如 git snapshot）不受影响（已记录接受理由）
  - [ ] 若发现未覆盖的用户命令执行点，新增 Task 处理并更新 Phase 2 AC（不得只记录结论）

### Phase 3: 回归验证

**目标**：确保修改不破坏现有功能，端到端验证"用户命令子进程环境确实干净"

**阶段验收标准**：
- [ ] `pytest broca/tests/ -x` 全量通过（0 failures, 0 errors，无新增 skip/xfail）
- [ ] `pytest broca/tests/test_runner_launcher.py -v` 中 env 相关断言全绿
- [ ] 端到端子进程测试：在含 venv 的 workspace 中，用户命令子进程的 `sys.executable` 指向 workspace venv，`PYTHONSAFEPATH` 不存在，`sys.path[0]` 为 `''`（cwd 重新生效）

#### Task 3.1: 端到端子进程验证测试

- **目标**：新增 subprocess 级 E2E 测试，直接验证"用户命令子进程的环境确实不再收到 `PYTHONPATH=仓库根`/`PYTHONSAFEPATH`"
- **步骤**：
  1. 在 `broca/tests/test_env_utils.py`（或新建 `test_env_e2e.py`）中新增测试
  2. 测试场景 A（核心 bug 验证）：
     - 用 `build_runner_env()` 构造"污染环境"
     - 用 `build_user_env(workspace)` 从污染 env 重建干净 env（需先 set 到 `os.environ` 再调 `build_user_env`）
     - 启动 `python -c "import os,sys; print(os.environ.get('PYTHONSAFEPATH')); print(sys.path[0])"`
     - 断言 stdout 第一行为空（`PYTHONSAFEPATH` 不存在），第二行为 `''`（cwd 重新生效）
  3. 测试场景 B（venv 适配验证）：
     - 构造含 `.venv/bin/python` 的 tmp workspace
     - `build_user_env(workspace)` 后启动 `python -c "import sys; print(sys.executable)"`
     - 断言 `sys.executable` 指向 workspace `.venv/bin/python`
  4. 测试场景 C（Scheduler 路径验证）：
     - 在 `test_process_manager.py` 增加 case：`pm.start_process("python -c \"import os;print(os.environ.get('PYTHONSAFEPATH'))\"")`
     - 等进程结束后读 stdout，断言为空
- **预期产出**：E2E 测试用例
- **验收标准**：
  - [ ] 场景 A：子进程 `PYTHONSAFEPATH` 为 None，`sys.path[0]` 为 `''`
  - [ ] 场景 B：子进程 `sys.executable` 指向 workspace venv
  - [ ] 场景 C：Scheduler/ProcessManager 路径子进程 `PYTHONSAFEPATH` 为空
  - [ ] 所有 E2E 测试通过

#### Task 3.2: 全量测试回归

- **目标**：确保无回归
- **步骤**：
  1. 运行 `pytest broca/tests/ -x`（`pyproject.toml` 已配置 `addopts = "-m 'not perf'"`，无需 `--timeout` 参数）
  2. 若有失败，分析是否由 env 变化引起并修复
  3. Windows `Scripts/` 路径验证：当前测试通过 `platform` 参数注入覆盖逻辑正确性，完整 Windows 环境验证 deferred to CI
- **预期产出**：全量测试通过
- **验收标准**：
  - [ ] 0 failures, 0 errors
  - [ ] 无新增 skip/xfail
- **依赖**：Task 3.1 完成

## 风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| 用户 workspace 的 venv 名称不在候选列表 `(.venv, venv, env, .env, virtualenv)` 中 | venv 未被自动检测，`python` 指向服务 venv | 候选列表与 `agent_manager` 一致覆盖常见场景；后续可扩展为读取 `pyproject.toml`/`setup.py` 声明 |
| `_BROCA_ORIG_*` 变量被用户 shell 脚本意外使用 | 极低概率（以下划线开头 + 明确前缀） | 文档说明；用户命令执行前已 pop 掉全部 `_BROCA_ORIG_*` |
| `build_user_env()` 抛出异常（如 workspace 路径不可访问） | 用户命令无法执行 | 函数内部 try/except 包裹，异常时 log warning 并 fallback 到"仅剥离 + 恢复，跳过 venv 适配" |
| Windows `Scripts/` 路径兼容性 | `build_user_env` 需正确处理 | 平台差异下沉为 `_venv_bin_dir(venv_root, platform)` 纯函数；测试直接注入 platform 参数（不 monkeypatch `os.name`） |
| 某些工具依赖 `PYTHONSAFEPATH`（极少见） | 用户命令中 `python -m` 行为变化 | 这是 *修复* 而非 *破坏*：用户命令本就不应受此限制 |
| Runner 进程自身 import 不受影响 | 无 | `build_user_env` 仅用于 `create_subprocess_shell`（用户命令），runner 进程自身的 `os.environ` 不变 |
| Runner 崩溃后 supervisor 重启 | `_BROCA_ORIG_*` 丢失 | 重启时 supervisor 重新调用 `build_runner_env()`，基于新 supervisor 进程环境重建，无状态泄漏风险 |
| **supervisor 自身 `PYTHONPATH` 污染**（开发模式 `PYTHONPATH=. python -m broca`） | 层 2 恢复后仍把 supervisor 进程的 `PYTHONPATH`（含仓库根）传给用户命令，修复对该类部署无效 | **已知限制**：层 2 设计目标是"恢复到 supervisor 进程启动时的环境"，若 supervisor 本身带脏 `PYTHONPATH` 则用户命令继承该污染。文档声明此限制；用户应通过 `virtualenv -p python3.12 broca_venv && source activate` 而非 `PYTHONPATH` 方式部署 |
| **PATH 中服务 venv 残留**（无 venv 的 workspace） | 无 venv 的 workspace 中，`PATH` 首位仍为 Broca 服务 venv `bin/`，`python` 指向服务 venv 解释器而非用户系统 Python | **已知限制**：`build_runner_env()` 不修改 `PATH`，`build_user_env()` 也不剔除服务 venv 的 PATH 条目（剔除后可能导致无 `python` 可用）。若 workspace 有 venv 则第 3 层自动覆盖；无 venv 时用户可 `PATH=$(echo $PATH | tr ':' '\n' | grep -v '.broca' | paste -sd:) cmd` 手动清除 |
| **既有后台/长任务测试行为变化**（`test_process_manager.py`、`test_long_running_task.py`） | 这些测试真实 `start_process`，注入 env 后解释器/PATH 可能变化导致测试失败 | Phase 3 全量回归 + 失败即分析是否 env 引起，必要时调整测试断言 |
| **`git_manager._run_git` 的 `os.environ.copy()` 残留泄漏** | `PYTHONPATH`/`PYTHONSAFEPATH` 会传入 git 子进程，git hook（pre-commit 等 Python 钩子）可能受影响 | **接受现状**：git hook 极少使用 Python 解释器，且 `PYTHONPATH` 对 git 本身无影响。后续可改为 `build_user_env()` 但不阻塞本次修复 |

## 未解决的问题

- 是否需要支持 Conda 环境自动检测？（当前方案仅覆盖 venv/virtualenv；Conda 用户可通过 `source activate myenv && cmd` 手动指定）
- 无 venv 的 workspace 中是否应从 `PATH` 中剔除服务 venv 的 `bin/`？（当前保留，作为兜底解释器；剔除后用户命令可能无 `python` 可用）
