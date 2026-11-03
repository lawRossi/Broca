# 移除环境变量依赖 — 纯文件配置重构

## 概述

- **目标**：彻底移除代码中 `os.getenv("BROCA_*")` 直接调用，所有配置值仅从文件（`.env` / `configs.json` / `llm_config.json`）读取，消除环境变量导致的"隐性隔离失败"
- **背景**：环境变量是最不稳定的配置来源——shell 未继承、supervisor 忘传、子进程丢失——之前 agent 连旧端口 6868 的 bug 根因就是此类问题
- **约束条件**：
  - 子进程管理相关的 `os.environ.copy()` / `os.environ["PATH"]` 等保留不动（这是进程管理，不是配置）
  - CI/CD 场景通过"生成 .env 文件"方式适配，不依赖环境变量注入
  - TUI/CLI 作为独立应用，也需要文件化

## 相关材料

- `broca/configs.py` — 核心配置加载逻辑（get_configs）
- `broca-web/backend/app/core/config.py` — 后端 pydantic Settings
- `broca-tui/broca_tui/config.py` — TUI 配置
- `broca/llm.py` — LLM 客户端（API key 覆盖逻辑）
- `broca/logging_config.py` — 日志配置
- `broca/session/database.py` — 数据库路径
- `broca/snapshot/git_manager.py` — 快照路径
- `scripts/install.sh` — 安装脚本（supervisor env 注入）
- `broca/service_manager.py` — 服务管理
- `docs/configuration.md` — 配置文档

## 总体方案

### 设计原则

```
所有配置来自文件，代码中不出现 os.getenv("BROCA_*") / os.environ.get("BROCA_*")

配置来源只有三类文件:
  1. .env 文件        → "运行参数"（端口/主机/数据库/JWT/SocketIO）
  2. configs.json    → "服务配置"（路径/执行参数/搜索/存储/ASR）
  3. llm_config.json → "LLM 供应商配置"（provider/model/api_key）
```

### 优先级

```
.env 文件 (pydantic DotEnvSettingsSource 直接读文件)
    ↓ 覆盖
configs.json (由 .env 中 BROCA_CONFIG 字段指定路径，或按默认发现规则)
    ↓ 覆盖
代码默认值
```

**关键点**：pydantic Settings 移除 `EnvSettingsSource`，只保留 `DotEnvSettingsSource`。
这意味着即使用户在 shell 中 `export PORT=9999`，也不会影响应用行为。

### BROCA_ENV 的去留

- **移除 `BROCA_ENV` 环境变量读取**
- 保留"环境标识"概念，但仅存在于 .env 文件中（`ENV=dev` / `ENV=production`）
- `broca/` 核心包不再感知"环境模式"——它只使用传入的 configs.json
- 生产安全护栏（JWT/CORS/log_level 检查）由 web 后端的 Settings validator 负责，核心包不做环境判断

### 核心包 (broca/) 的改动策略

核心包作为 library 不拥有 .env 文件。它通过 `get_configs()` 获取所有配置：

```python
# Before
log_dir = os.getenv("BROCA_LOG_DIR") or str(Path.home() / ".broca" / "logs")

# After  
log_dir = get_configs().log_dir  # 从 configs.json 读取
```

为此需要**扩展 `BrocaConfig`**，添加当前只在环境变量中出现的路径字段：

| 新增字段 | 默认值 | 原环境变量 |
|----------|--------|------------|
| `log_dir` | `~/.broca/logs` | `BROCA_LOG_DIR` |
| `agents_config_dir` | `~/.broca/configs/agents` | `BROCA_AGENTS_CONFIG_DIR` |
| `snapshot_home` | `~/.broca/snapshots` | `BROCA_SNAPSHOT_HOME` |
| `components_config` | _(空)_ | `BROCA_COMPONENTS_CONFIG` |

`get_configs()` 签名改为：
```python
def get_configs(config_path: str | Path | None = None) -> BrocaConfig:
    """
    1. config_path 显式指定 → 直接加载该文件
    2. 否则按发现规则: 项目 configs/configs.json → ~/.broca/configs.json
    """
```

Web 后端启动时从 Settings 读取 `BROCA_CONFIG`，传给 `get_configs(config_path=settings.broca_config)`。
TUI/CLI 直接调 `get_configs()`，走默认发现逻辑。

### Web 后端的改动策略

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[".env", ".env.local", ".env.development", ".env.production"],
        extra="ignore",
    )
    
    def settings_customise_sources(cls, settings_cls, init_settings, 
                                     env_settings, dotenv_settings, file_secret_settings):
        # 关键：去掉 env_settings → 不读 os.environ
        return (init_settings, dotenv_settings, file_secret_settings)
```

- 移除 `load_dotenv()` 调用（pydantic 的 `DotEnvSettingsSource` 自动处理 .env 文件）
- 移除所有 `os.getenv(...)` 作为 field default 的写法
- 所有 `os.getenv("BROCA_SOCKETIO_*")` 等改为 `settings.xxx`

### CI/CD 适配

```yaml
# GitHub Actions 示例
- name: Generate .env for CI
  run: |
    cat > broca-web/backend/.env.local <<EOF
    JWT_SECRET=${{ secrets.JWT_SECRET }}
    DATABASE_URL=${{ secrets.DATABASE_URL }}
    ENV=production
    EOF
- run: pytest
```

CI 通过"生成 .env.local 文件"注入 secrets，仍然走文件通道。

### 不动的部分

| 代码 | 原因 |
|------|------|
| `os.environ.copy()` for subprocess | 进程管理，不是配置 |
| `os.environ["PATH"] = ...` in cli/main.py | venv PATH 注入 |
| `env["GIT_DIR"] = ...` in git_manager.py | git subprocess 管理 |
| `os.environ.get("USER")` in service_manager.py | 系统用户信息 |
| `os.environ["HF_ENDPOINT"]` in download_asr_model.py | 一次性脚本 |
| `os.environ.copy()` in cli/main.py (runner subprocess) | 子进程继承 |

---

## 执行计划

### Phase 1: 基础设施 — 扩展 BrocaConfig + get_configs() 改造

**目标**：让核心包具备"纯文件读取"能力，为后续迁移铺路

**阶段验收标准**：
- [ ] `BrocaConfig` 新增 `log_dir` / `agents_config_dir` / `snapshot_home` / `components_config` 字段
- [ ] `get_configs(config_path=None)` 支持显式路径参数
- [ ] `get_configs()` 不再调用 `os.getenv("BROCA_CONFIG")` 和 `os.getenv("BROCA_ENV")`
- [ ] 默认发现逻辑保留：项目 `configs/configs.json` → `~/.broca/configs.json`
- [ ] `configs/configs.json` 模板添加新字段
- [ ] 单元测试通过

#### Task 1.1: 扩展 BrocaConfig 字段
- **目标**：在 `BrocaConfig` 类中添加缺失的路径字段
- **步骤**：
  1. 在 `broca/configs.py` 的 `BrocaConfig.__init__` 中添加：
     - `self.log_dir = "~/.broca/logs"`
     - `self.agents_config_dir = "~/.broca/configs/agents"`
     - `self.snapshot_home = "~/.broca/snapshots"`
     - `self.components_config = ""`
  2. 在 `from_config` 的 `path_key` 展开列表中追加这些字段
  3. 更新 `configs/configs.json` 模板添加这些字段（带默认值）
  4. 更新 `broca-web/backend/configs.dev.json` 添加新字段
- **预期产出**：`BrocaConfig` 对象包含所有路径信息
- **验收标准**：
  - [ ] `BrocaConfig()` 实例化后 `log_dir` / `agents_config_dir` / `snapshot_home` 属性存在且有默认值
  - [ ] `BrocaConfig.from_config({"log_dir": "/custom"})` 正确加载
  - [ ] `configs/configs.json` 包含新字段

#### Task 1.2: 改造 get_configs() 函数
- **目标**：移除 `os.getenv("BROCA_CONFIG")` 和 `os.getenv("BROCA_ENV")`，改为参数传入
- **步骤**：
  1. 签名改为 `def get_configs(config_path: str | Path | None = None, _cached: bool = True) -> BrocaConfig`
  2. 逻辑改为：
     ```python
     if config_path is not None:
         config = _load_config_file(Path(config_path).expanduser())
     if config is None:
         # 默认发现：项目 → 用户
         project_config = Path(__file__).parent.parent / "configs" / "configs.json"
         user_config = Path.home() / ".broca" / "configs.json"
         config = _load_config_file(project_config) or _load_config_file(user_config)
     if config is None:
         config = BrocaConfig()
     ```
  3. 移除 `BROCA_ENV` 相关的所有逻辑（dev/production 优先级区分）
  4. 保留 production log_level 护栏，但改为由调用方传入 `enforce_production=True` 参数
  5. 更新 `get_llm_defaults()` 中的 `_resolve_llm_config_path()`：不再读 `os.getenv("BROCA_LLM_CONFIG")`，改为从 `get_configs().llm_config_file` 读取
  6. 添加模块级单例缓存（`_config_instance`），避免重复加载
- **预期产出**：`get_configs()` 纯文件驱动
- **验收标准**：
  - [ ] `get_configs("/custom/path.json")` 正确加载指定文件
  - [ ] `get_configs()` 无参数时按"项目→用户"顺序发现
  - [ ] grep `os.getenv` 在 `configs.py` 中返回 0 结果
  - [ ] 现有 `test_configs.py` 测试适配后通过

#### Task 1.3: 适配 _resolve_llm_config_path()
- **目标**：`_resolve_llm_config_path()` 不再读环境变量
- **步骤**：
  1. 改为从 `get_configs().llm_config_file` 读取路径
  2. 如果 `llm_config_file` 为空，回退到项目 `configs/llm_config.json`
  3. 注意避免循环依赖：`get_configs()` → `_resolve_llm_config_path()` → `get_configs()`
     - 解决：`_resolve_llm_config_path()` 直接读 `BrocaConfig` 的 `llm_config_file` 字段，不调 `get_configs()` 的完整逻辑
- **预期产出**：LLM 配置路径纯文件驱动
- **验收标准**：
  - [ ] `configs.json` 中 `llm_config_file` 字段能正确被 LLMClient 使用
  - [ ] 无循环 import

---

### Phase 2: 核心包迁移 (broca/)

**目标**：`broca/` 目录（排除 tests/）中不再出现 `os.getenv("BROCA_*")` 或 `os.environ.get("BROCA_*")`

**阶段验收标准**：
- [ ] `grep -r 'os.getenv\|os.environ.get' broca/ --include="*.py" | grep -v tests/ | grep "BROCA_"` 返回 0 结果
- [ ] `grep -r 'os.getenv\|os.environ.get' broca/ --include="*.py" | grep -v tests/ | grep "ANYSEARCH\|TAVILY"` 返回 0 结果
- [ ] 所有功能通过单元测试验证

#### Task 2.1: 迁移 logging_config.py
- **目标**：日志配置全部从 `get_configs()` 读取
- **步骤**：
  1. `get_log_dir()`: 改为 `get_configs().log_dir`（去掉 `os.getenv("BROCA_LOG_DIR")`）
  2. `get_log_level()`: 改为 `get_configs().log_level`（去掉 `os.getenv("BROCA_LOG_LEVEL")`）
  3. `_resolve_config_file()`: 改为 `get_configs()` 已解析的路径（去掉 `os.getenv("BROCA_CONFIG")`）
  4. 注意：`logging_config.py` 被 `broca/configs.py` 的 log 使用，注意避免循环 import
- **预期产出**：日志配置纯文件驱动
- **验收标准**：
  - [ ] `grep "os.getenv\|os.environ" broca/logging_config.py` 返回 0 结果
  - [ ] `test_logging_config.py` 适配后通过（patch `get_configs` 而非 env）

#### Task 2.2: 迁移 llm.py
- **目标**：LLM 配置路径和 API key 覆盖逻辑文件化
- **步骤**：
  1. `config_path` 改为 `get_configs().llm_config_file`（或回退到项目默认）
  2. **移除 `_apply_env_overrides()` 整个方法**——API key 应该在 `llm_config.json` 中配置
  3. 如果用户需要临时覆盖 API key，编辑 `llm_config.json` 或通过 `BROCA_CONFIG` 指向不同文件
  4. 更新文档说明 API key 配置方式
- **预期产出**：LLM 配置完全文件化
- **验收标准**：
  - [ ] `grep "os.getenv\|os.environ" broca/llm.py` 返回 0 结果
  - [ ] `test_llm.py` 适配后通过
  - [ ] `llm_config.json` 中的 `api_key` 字段能正确被使用

#### Task 2.3: 迁移 session/database.py + alembic/env.py
- **目标**：数据库目录从 configs.json 读取
- **步骤**：
  1. `broca/session/database.py:26`: `os.getenv("BROCA_DATABASE_DIR")` → `get_configs().database_dir`
  2. `broca/alembic/env.py:34`: 同上
- **预期产出**：数据库路径纯文件驱动
- **验收标准**：
  - [ ] `grep "BROCA_DATABASE_DIR" broca/session/database.py broca/alembic/env.py` 返回 0
  - [ ] `test_database.py` 适配后通过

#### Task 2.4: 迁移 agent_manager.py
- **目标**：Agent 配置目录从 configs.json 读取
- **步骤**：
  1. `broca/agent_manager.py:34`: `os.getenv("BROCA_AGENTS_CONFIG_DIR")` → `get_configs().agents_config_dir`
- **预期产出**：Agent 配置路径文件化
- **验收标准**：
  - [ ] `grep "BROCA_AGENTS_CONFIG_DIR" broca/agent_manager.py` 返回 0

#### Task 2.5: 迁移 snapshot/git_manager.py
- **目标**：快照目录从 configs.json 读取
- **步骤**：
  1. `broca/snapshot/git_manager.py:267`: `os.environ.get("BROCA_SNAPSHOT_HOME", ...)` → `get_configs().snapshot_home`
  2. 保留 `os.environ.copy()` for git subprocess（进程管理）
- **预期产出**：快照路径文件化
- **验收标准**：
  - [ ] `grep "BROCA_SNAPSHOT_HOME" broca/snapshot/git_manager.py` 返回 0
  - [ ] git subprocess env 逻辑不变

#### Task 2.6: 迁移 scheduler.py
- **目标**：Scheduler 的 server_url 从 configs.json 读取
- **步骤**：
  1. `broca/scheduler.py:649`: `os.getenv("BROCA_SERVER_URL")` → `get_configs().socket_server_url`
  2. 去掉 if/else，直接用 `get_configs().socket_server_url or "http://localhost:6666"`
- **预期产出**：Scheduler 配置文件化
- **验收标准**：
  - [ ] `grep "BROCA_SERVER_URL" broca/scheduler.py` 返回 0

#### Task 2.7: 迁移 tools/web.py（搜索 API Key）
- **目标**：搜索 API key 仅从 configs.json 读取
- **步骤**：
  1. `broca/tools/web.py:26`: `os.environ.get("ANYSEARCH_API_KEY")` → 仅用 `cfg.search.anysearch_api_key`
  2. `broca/tools/web.py:33`: 同上
  3. `broca/tools/web.py:479`: `os.environ.get("TAVILY_API_KEY")` → 仅用 `cfg.search.tavily_api_key`
  4. `broca/tools/web.py:488-491`: 同理
  5. API key 在 `configs.json` 的 `search` 分组中配置
- **预期产出**：搜索配置纯文件驱动
- **验收标准**：
  - [ ] `grep "ANYSEARCH_API_KEY\|TAVILY_API_KEY" broca/tools/web.py` 返回 0
  - [ ] `configs.json` 中 `search.tavily_api_key` 能正确生效

#### Task 2.8: 迁移 components/registry.py
- **目标**：组件配置路径文件化
- **步骤**：
  1. `broca/components/registry.py:146`: `os.getenv("BROCA_COMPONENTS_CONFIG")` → `get_configs().components_config`
- **预期产出**：组件配置路径文件化
- **验收标准**：
  - [ ] `grep "BROCA_COMPONENTS_CONFIG" broca/components/registry.py` 返回 0

#### Task 2.9: 迁移 context_compressor.py
- **目标**：LLM 配置路径读取方式统一
- **步骤**：
  1. `broca/context_compressor.py:249`: `os.getenv("BROCA_LLM_CONFIG")` → `get_configs().llm_config_file`
- **预期产出**：统一 LLM 配置路径来源
- **验收标准**：
  - [ ] `grep "BROCA_LLM_CONFIG" broca/context_compressor.py` 返回 0

#### Task 2.10: 更新核心包测试
- **目标**：所有 `patch.dict(os.environ, {"BROCA_*": ...})` 改为 patch 配置对象
- **步骤**：
  1. `test_configs.py`: 改为测试 `get_configs(config_path=...)` 参数
  2. `test_database.py`: 改为 patch `get_configs` 返回的 `database_dir`
  3. `test_logging_config.py`: 改为 patch `get_configs` 返回的 `log_dir` / `log_level`
  4. `test_llm.py`: 改为测试 `llm_config_file` 路径加载
  5. 添加新 fixture：`mock_configs` (pytest fixture 返回预设的 BrocaConfig)
- **预期产出**：测试不依赖环境变量
- **验收标准**：
  - [ ] `grep "BROCA_" broca/tests/` 返回 0 结果（或仅剩合理引用）
  - [ ] `pytest broca/tests/` 全部通过

---

### Phase 3: Web 后端迁移 (broca-web/backend/)

**目标**：后端代码中不再出现 `os.getenv("BROCA_*")` 或 `os.getenv("PORT/HOST/JWT_*/DATABASE_*")` 直接调用

**阶段验收标准**：
- [ ] `grep -r 'os.getenv\|os.environ.get' broca-web/backend/app/ --include="*.py"` 返回 0 结果（`conftest.py` 除外，见 Task 3.4）
- [ ] `Settings` 不再使用 `EnvSettingsSource`
- [ ] `load_dotenv` 调用被移除
- [ ] 后端能正常启动并连接 SocketIO

#### Task 3.1: 改造 Settings (core/config.py)
- **目标**：pydantic Settings 只从 .env 文件读取，不读 os.environ
- **步骤**：
  1. 移除顶部的 `load_dotenv()` 循环调用（pydantic `DotEnvSettingsSource` 自动处理）
  2. 添加 `settings_customise_sources` 方法，去掉 `env_settings`：
     ```python
     @classmethod
     def settings_customise_sources(cls, settings_cls, init_settings, 
                                     env_settings, dotenv_settings, file_secret_settings):
         return (init_settings, dotenv_settings, file_secret_settings)
     ```
  3. 移除所有 field default 中的 `os.getenv(...)` 调用：
     - `database_type`: 改为 `str = "sqlite"`
     - `database_url`: 改为 `str = ""`
     - `sqlite_database_path`: 改为 `str = "sqlite:///./dev.db"`
     - `host`: 改为 `str = "0.0.0.0"`
     - `jwt_secret`: 改为 `str = "broca-default-dev-secret-change-in-production"`
     - `jwt_expire_minutes`: 改为 `int = 2880`
  4. `env` 字段：保留 `AliasChoices("env", "BROCA_ENV", "ENV")` 但仅从 .env 文件匹配
  5. 添加 `broca_config: str = ""` 字段（指向 configs.json 路径）
  6. `model_validator(_derive_ports_from_configs_json)`: 保留，但改为从 `self.broca_config` 读取路径传给 `get_configs()`
- **预期产出**：Settings 纯 .env 文件驱动
- **验收标准**：
  - [ ] `grep "os.getenv\|load_dotenv" broca-web/backend/app/core/config.py` 返回 0
  - [ ] `Settings()` 在无环境变量时能正确从 .env 文件读取值
  - [ ] shell 中 `export PORT=9999` 后启动后端仍使用 .env 中的端口

#### Task 3.2: 迁移 main.py + socketio_runtime.py
- **目标**：SocketIO 相关配置从 settings 对象读取
- **步骤**：
  1. `main.py:117`: `os.getenv("BROCA_SOCKETIO_ENABLED", ...)` → `settings.broca_socketio_enabled`
  2. `main.py:118`: `os.getenv("BROCA_SOCKETIO_HOST", ...)` → `settings.broca_socketio_host`
  3. `main.py:120`: `os.getenv("BROCA_SOCKETIO_CORS", ...)` → `settings.broca_socketio_cors`
  4. `socketio_runtime.py:31`: 同上
  5. 在 Settings 中确认有 `broca_socketio_enabled` / `broca_socketio_host` / `broca_socketio_cors` 字段
- **预期产出**：SocketIO 配置从 settings 读取
- **验收标准**：
  - [ ] `grep "os.getenv" broca-web/backend/app/main.py` 返回 0
  - [ ] `grep "os.getenv" broca-web/backend/app/core/socketio_runtime.py` 返回 0

#### Task 3.3: 迁移 asr/config.py + api/config.py
- **目标**：ASR 和 API 配置从 settings / get_configs 读取
- **步骤**：
  1. `asr/config.py:90`: `os.getenv("BROCA_CONFIG")` → `settings.broca_config`
  2. `asr/config.py:123/128/133`: `os.environ.get("BROCA_ASR_*")` → 从 configs.json 的 `asr` 分组读取（已有逻辑），移除 env 覆盖
  3. `api/config.py:22`: `os.getenv("BROCA_LLM_CONFIG")` → `get_configs().llm_config_file`
  4. `api/config.py:104/107`: `os.getenv("BROCA_ENV")` / `os.getenv("BROCA_CONFIG")` → `settings.env` / `settings.broca_config`
- **预期产出**：ASR/API 配置文件化
- **验收标准**：
  - [ ] `grep "os.getenv\|os.environ" broca-web/backend/app/asr/config.py` 返回 0
  - [ ] `grep "os.getenv" broca-web/backend/app/api/config.py` 返回 0

#### Task 3.4: 迁移 manage.py + 适配 tests/conftest.py
- **目标**：manage.py 和测试配置不依赖环境变量
- **步骤**：
  1. `manage.py:115-117`: 从 settings 对象读取（或改为接受命令行参数）
  2. `tests/conftest.py:29-31`: 改为直接构造 Settings 对象或 patch settings：
     ```python
     # Before
     os.environ["JWT_SECRET"] = "test-secret-key"
     # After
     from app.core.config import settings
     settings.jwt_secret = "test-secret-key"
     settings.broca_socketio_enabled = False
     ```
  3. `setup_admin.py:59/131/132`: 从 settings 读取或保留 argparse（CLI 脚本，argparse 优先）
- **预期产出**：管理脚本和测试不依赖环境变量
- **验收标准**：
  - [ ] `grep "os.getenv\|os.environ" broca-web/backend/manage.py` 返回 0
  - [ ] `pytest broca-web/backend/tests/` 通过

---

### Phase 4: TUI/CLI 迁移 (broca-tui/ + broca/cli/)

**目标**：TUI 和 CLI 的配置读取不依赖环境变量

**阶段验收标准**：
- [ ] `grep -r 'os.getenv\|os.environ.get' broca-tui/broca_tui/ --include="*.py"` 中无 `BROCA_*` 匹配
- [ ] `broca/cli/main.py:948` 的 `os.environ["BROCA_SOCKET_SERVER_URL"]` 保留（子进程传递）
- [ ] TUI 正常启动连接

#### Task 4.1: 改造 TUI config.py
- **目标**：TUI 配置从 `get_configs()` 读取
- **步骤**：
  1. `_get_broca_home()`: 保留 `os.environ.get("BROCA_HOME")` 或改为固定 `~/.broca`（TUI 是终端工具，BROCA_HOME 不太可能变）
     - 决定：移除 env 读取，固定为 `Path.home() / ".broca"`
  2. `_load_configs_json()`: 移除 `os.getenv("BROCA_ENV")` 和 `os.getenv("BROCA_CONFIG")`，改为调用 `broca.configs.get_configs()`
  3. `load_config()`: 所有 `os.environ.get("BROCA_SOCKET_SERVER_URL", ...)` 等 → 从 `get_configs()` 返回的对象读取
  4. TUI 特有的 `client_id` / `user_id` / `theme`：改为从 `configs.json` 的新 `tui` 分组读取，或使用 dataclass 默认值
- **预期产出**：TUI 配置纯文件驱动
- **验收标准**：
  - [ ] `grep "os.getenv\|os.environ" broca-tui/broca_tui/config.py` 返回 0
  - [ ] TUI 能正常启动并连接 SocketIO server

#### Task 4.2: CLI main.py 适配
- **目标**：CLI 中合理保留进程管理 env，移除配置读取 env
- **步骤**：
  1. `cli/main.py:948` `os.environ["BROCA_SOCKET_SERVER_URL"] = server_url` → **保留**（向子进程传递配置）
  2. 其他 `os.getenv` 调用检查是否可改为从 `get_configs()` 读取
  3. `os.environ.copy()` for subprocess → **保留**
- **预期产出**：CLI 配置读取文件化，子进程管理不变
- **验收标准**：
  - [ ] CLI 能正常启动
  - [ ] runner 子进程能正确继承配置

---

### Phase 5: 脚本与部署 (install.sh + service_manager.py)

**目标**：安装/部署脚本生成 .env 文件替代环境变量注入

**阶段验收标准**：
- [ ] `install.sh` 不再向 supervisor 注入 `BROCA_*` 环境变量
- [ ] `install.sh` 生成 `~/.broca/.env` 文件
- [ ] `service_manager.py` 从 .env 文件读取配置
- [ ] 生产部署后服务能正常启动

#### Task 5.1: 改造 install.sh
- **目标**：supervisor 配置改为指向 .env 文件
- **步骤**：
  1. 将 supervisor `environment=` 行中的 `BROCA_ENV/BROCA_CONFIG/BROCA_DATABASE_DIR/BROCA_LLM_CONFIG/...` 移除
  2. 改为在 `~/.broca/` 下生成 `.env` 文件：
     ```bash
     cat > "$BROCA_HOME/.env" <<EOF
     ENV=production
     PORT=${BROCA_BACKEND_PORT}
     BROCA_SOCKETIO_PORT=${BROCA_SOCKETIO_PORT}
     BROCA_CONFIG=${BROCA_HOME}/configs/configs.json
     BROCA_DATABASE_DIR=${BROCA_HOME}/data
     BROCA_LLM_CONFIG=${BROCA_HOME}/configs/llm_config.json
     JWT_SECRET=${JWT_SECRET}
     CORS_ALLOW_ORIGINS=${CORS_ORIGINS}
     EOF
     ```
  3. supervisor `environment=` 仅保留 `PYTHONPATH`
  4. supervisor `directory=` 指向包含 .env 的目录（backend/）
- **预期产出**：supervisor 配置极简
- **验收标准**：
  - [ ] 生成的 supervisor.conf 的 `environment=` 只有 `PYTHONPATH`
  - [ ] `~/.broca/.env` 文件包含所有必要配置
  - [ ] `sh scripts/install.sh` 后 `broca service start` 能正常启动

#### Task 5.2: 改造 service_manager.py
- **目标**：服务管理从 .env 文件读取配置
- **步骤**：
  1. `service_manager.py:952`: 构建 subprocess env 时，从 .env 文件解析值（或让 subprocess 自己加载 .env）
  2. `service_manager.py:1819`: 同上
  3. 移除 `os.getenv("BROCA_*")` 读取，改为从 .env 文件解析
- **预期产出**：服务管理配置文件化
- **验收标准**：
  - [ ] `grep "BROCA_" broca/service_manager.py | grep -v "BROCA_HOME\|comment"` 结果中无 `os.getenv`
  - [ ] 服务启动/停止功能正常

---

### Phase 6: 文档与示例更新

**目标**：所有文档反映新的"纯文件配置"方式

**阶段验收标准**：
- [ ] `docs/configuration.md` 重写
- [ ] `.env.example` 更新
- [ ] README 中的配置说明更新
- [ ] 无残留"export BROCA_..."指令

#### Task 6.1: 重写 docs/configuration.md
- **目标**：准确反映新的配置系统
- **步骤**：
  1. 移除所有"环境变量"层描述
  2. 配置来源改为：`.env` → `configs.json` → 默认值
  3. 更新所有配置项表格（移除环境变量列，添加 .env 文件名）
  4. 添加"CI/CD 适配"章节（生成 .env.local）
  5. 更新 worktree 隔离说明（纯文件操作）
- **预期产出**：准确的配置文档
- **验收标准**：
  - [ ] 文档中无"export BROCA_"或"设置环境变量"指令
  - [ ] 配置优先级图清晰准确

#### Task 6.2: 更新 .env.example 文件
- **目标**：示例文件反映新配置方式
- **步骤**：
  1. `broca-web/backend/.env.example`: 添加 `BROCA_CONFIG` 字段，移除注释中的"环境变量"措辞
  2. `broca-web/frontend/.env.example`: 不变（VITE_* 是 Vite 内置机制，不受影响）
  3. `broca-web/backend/.env.production.example`: 更新注释
- **预期产出**：清晰的配置模板
- **验收标准**：
  - [ ] 新用户可以按 .env.example 完成配置，不需要设置任何 shell 环境变量

#### Task 6.3: 更新 README + dev-worktree-setup.md
- **目标**：快速开始和工作指南反映新方式
- **步骤**：
  1. README 中"开发模式"说明：只需 `.env` 文件，无需 export
  2. `docs/dev-worktree-setup.md`：worktree 隔离步骤改为"修改 .env 文件"
  3. 移除所有 "export BROCA_CONFIG=..." 示例
- **预期产出**：用户文档一致
- **验收标准**：
  - [ ] README 和 dev-worktree-setup.md 中无环境变量设置步骤

---

## 风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| pydantic 移除 `EnvSettingsSource` 后某些隐式依赖 os.environ 的代码失效 | 运行时配置读取为空 | Phase 3 完成后全量启动测试，grep 确认无遗漏 |
| `get_configs()` 单例缓存在多进程（web + runner）中不一致 | runner 子进程读到旧配置 | runner 子进程启动时由父进程传入 `config_path` 参数，不依赖全局缓存 |
| TUI 不依赖 .env 文件（终端环境），配置发现可能找不到文件 | TUI 连接失败 | TUI 保留 `~/.broca/configs.json` 发现逻辑作为兜底 |
| 已有用户/服务器依赖环境变量方式部署 | 升级后配置丢失 | install.sh 重新运行即可生成 .env；在 release notes 中说明 breaking change |
| `load_dotenv` 移除后，CI 环境注入方式需改变 | CI 构建失败 | 提供 `ci/generate-env.sh` 脚本，CI 中先生成 .env.local 再跑测试 |

## 已确认的决策

- **`BROCA_HOME`**：移除。TUI 中 `os.environ.get("BROCA_HOME", ...)` 改为固定 `Path.home() / ".broca"`，与 service_manager.py / install.sh 保持一致。
- **`HF_ENDPOINT`**（`download_asr_model.py`）：保留。这是 HuggingFace 下载镜像设置，属于第三方工具的运行时参数，不是 Broca 配置。
