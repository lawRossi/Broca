# Broca 配置统一与环境隔离方案

## 概述
- **目标**：收口分散在 10+ 处配置加载点中的配置管理，建立清晰的分层机制，使生产/开发/测试环境可轻松隔离
- **背景**：refactor 分支创建 session 后 chat 页面无反应，消息发到了生产服务。根因：端口/URL 配置散落各处（`configs.json`、`.env`、代码硬编码默认值），worktree 未正确覆盖导致前端代理指向了生产实例
- **约束条件**：
  - 保持 `broca` 核心包的独立性（TUI/CLI/VSCode 扩展都能复用）
  - Web 后端保留 pydantic-settings + .env 机制（应用自身参数）
  - 不能破坏现有 `~/.broca/` 安装目录结构（已部署环境兼容）

## 相关材料
- `broca/configs.py` — 核心配置加载（`get_configs()` / `BrocaConfig`）
- `broca-web/backend/app/core/config.py` — Web 后端 pydantic Settings
- `broca-web/backend/.env` — worktree 本地测试配置
- `broca-web/backend/.test-configs.json` — worktree 测试 configs.json
- `broca-web/frontend/.env` — 前端环境变量
- `broca-web/frontend/vite.config.ts` — Vite 代理配置
- `configs/configs.json` — 项目默认全局配置
- `broca-tui/broca_tui/config.py` — TUI 配置加载
- `broca/agent_configs.py` — AgentConfig（含硬编码 `server_url`）
- `broca/communication/socketio_server.py` — SocketIOServer（默认 port=8000，不一致）
- `broca-web/backend/app/api/config.py` — Web 后端 API 配置路径解析
- `broca/service_manager.py` — Supervisor 环境变量构建
- `scripts/install.sh` — 安装脚本（端口/nginx/supervisor 配置生成）

## 总体方案

### 分层模型

```
┌─────────────────────────────────────────────────────────┐
│  Layer 3: 环境变量 (最高优先级)                            │
│  BROCA_CONFIG, BROCA_SOCKETIO_PORT, PORT, VITE_* ...    │
├─────────────────────────────────────────────────────────┤
│  Layer 2: 应用配置 (.env / .env.local / .env.{profile})  │
│  Web 后端: JWT, DATABASE_TYPE, CORS, PORT ...           │
│  Web 前端: VITE_BACKEND_URL, VITE_BROCA_SOCKET_SERVER_URL│
├─────────────────────────────────────────────────────────┤
│  Layer 1: 服务拓扑 (configs.json)                        │
│  socket_server_url, api_server_url, database_dir ...    │
│  解析: BROCA_CONFIG > ~/.broca/configs.json > 项目默认   │
└─────────────────────────────────────────────────────────┘
```

**核心原则**：
- **Layer 1（configs.json）** 管"服务在哪"：标准端口、URL、路径、全局执行参数 — 由 `broca.configs.get_configs()` 统一加载，**包含标准默认值（6666/9001），git-tracked**
- **Layer 2（.env）** 管"应用怎么跑" + **覆盖端口**：JWT 密钥、DB 类型、CORS、`PORT`/`BROCA_SOCKETIO_PORT` — 由 pydantic-settings / Vite 加载，gitignored
- **Layer 3（环境变量）** 覆盖一切，用于 CI/容器/临时调试

**覆盖链路（以端口为例）**：
```
configs/configs.json (git-tracked, 标准值: 6666/9001)
    ↑ 被覆盖
.env (gitignored, worktree 个性化: PORT=9002, BROCA_SOCKETIO_PORT=6667)
    ↑ 被覆盖
export BROCA_SOCKETIO_PORT=6668 (临时调试/CI 注入)
```

**configs.json 的角色**：
- **生产环境**：`~/.broca/configs/configs.json`（由 install.sh 创建）+ supervisor 注入 env 覆盖
- **开发环境**：项目 `configs/configs.json`（git-tracked，标准默认值）+ `.env` 覆盖端口
- **开发便捷模式**：可选使用 `configs.dev.json`（通过 `BROCA_CONFIG` 指向），预设了本地化的 `database_dir`/`log_level` 等，减少 `.env` 配置行数

`get_configs()` 始终能返回完整 URL。实际运行时端口由 env 决定（最高优先级）。

**环境隔离 = 一份 .env（覆盖端口/数据库路径）+ 可选的 configs.dev.json（BROCA_CONFIG 指向）**

### 端口标准化

| 服务 | 端口 | 说明 |
|------|------|------|
| Socket.IO | **6666** | 唯一默认值（移除 8000/6868） |
| 后端 REST API | **9001** | 唯一默认值（移除 9000） |
| 前端 (nginx/prod) | **7001** | 生产入口 |
| 前端 (vite dev) | **7000** | 开发用 |
| HTTPS (nginx) | **8443** | 移动端 SSL |

---

## Pre-execution: 安全前置

- [ ] 将 `broca-web/backend/.test-configs.json` 加入 `.gitignore`（含真实 API 密钥，防止误提交）
- [ ] 确认 `.gitignore` 包含：`.env.local`、`.env.development`、`dev.db`、`.local-data/`

## 执行计划

### Phase 1: 核心收口 — 验证 + 补漏

> ⚠️ **本分支已部分完成端口标准化。** Phase 1 的主要工作为：(1) 验证已完成项（grep verify），(2) 修复遗漏项（README、`configs/configs.json` 路径）。

**目标**：确认端口标准化完成；修复遗留的硬编码路径和文档引用

**阶段验收标准**：
- [ ] `grep -rn "localhost:8000\|localhost:9000\|localhost:6868\|127.0.0.1:8000\|127.0.0.1:9000" broca/ broca-web/ broca-tui/ broca-vscode/` 无结果（plans/ 除外）
- [ ] 所有 Python 代码中 SocketIO 默认端口为 6666，API 默认端口为 9001
- [ ] `broca/alembic.ini` 中无 `/home/ubuntu` 路径
- [ ] `broca.configs.get_configs()` 是所有 Python 组件获取服务拓扑的唯一入口

#### Task 1.1: 验证端口标准化 + 修复遗漏
- **目标**：验证已完成的端口标准化，修复遗漏项
- **步骤**：
  1. **验证**（grep 确认已完成）：
     - `broca/communication/socketio_server.py` — `port: int = 6666` ✅
     - `broca-web/backend/.env.example` — `PORT=9001`，`BROCA_SOCKETIO_PORT=6666` ✅
     - `broca-web/frontend/.env.example` — 端口 9001/6666 ✅
     - `broca-vscode/src/extension/config.ts` — `localhost:9001`/`localhost:6666` ✅
     - `broca-vscode` 中 `ClientConfigPanel.vue`/`GeneralConfigPanel.vue`/`chatWebView.ts` ✅
  2. **修复遗漏**：
     - `broca-web/README.md` 中 `localhost:8000` → `localhost:9001`/`localhost:6666`
     - 根 `README.md` 中 `localhost:8000` → `localhost:9001`
  3. 全局 grep 确认无残留（排除 plans/）
- **预期产出**：所有代码和文档中端口默认值一致
- **验收标准**：
  - [ ] 全局搜索无 `localhost:8000`、`localhost:9000`、`localhost:6868`、`127.0.0.1:8000`、`127.0.0.1:9000`、`127.0.0.1:6868`（排除 plans/）
  - [ ] 所有 Python `dataclass`/`__init__`/函数参数中 SocketIO 默认端口为 6666
  - [ ] README 文件中无旧端口引用

#### Task 1.2: 验证硬编码 URL 消除 + 补充遗漏
- **目标**：验证已完成的改动，补充默认值注释
- **步骤**：
  1. **验证**（已完成的改动）：
     - `broca/scheduler.py` — 已使用 `get_configs().socket_server_url`（env 覆盖）✅
     - `broca/service_manager.py` — 已注入 `BROCA_CONFIG` 到 supervisor 环境变量 ✅
     - `broca/agent_configs.py` — `server_url` 已加 fallback 注释 ✅
     - `broca/cli/worktree.py` — `DEFAULT_API_BASE_URL` 已加注释 ✅
  2. **补充**（如有遗漏）：
     - `broca-web/backend/app/core/socketio_runtime.py` — 确认 `SocketIOServerConfig.port` 从 env/settings 获取（Phase 2 Task 2.2 会进一步完善）
- **预期产出**：运行时 URL 解析链路清晰：`env > configs.json > dataclass 默认值`
- **验收标准**：
  - [ ] `broca/scheduler.py` 中 socket URL 优先读 configs.json
  - [ ] `service_manager.py` 构建的 supervisor 环境变量包含 `BROCA_CONFIG`
  - [ ] 代码注释中标注了"默认值仅为 fallback，生产环境必须通过 configs.json 或 env 配置"

#### Task 1.3: 修正 alembic.ini 中的遗留硬编码路径
- **目标**：消除 `sqlite:////home/ubuntu/code/Broca/data/sessions.db` 硬编码
- **步骤**：
  1. `broca/alembic.ini` — 将 `sqlalchemy.url` 改为空或占位符 `sqlite:///$(BROCA_DATABASE_DIR)/sessions.db`
  2. 确认 `broca/alembic/env.py` 中 `get_database_url()` 能正确解析（已有 `BROCA_DATABASE_DIR` 逻辑）
  3. `broca-web/backend/alembic.ini` — 确认其 `env.py` 动态获取逻辑无遗留
- **预期产出**：alembic 迁移不再依赖硬编码绝对路径
- **验收标准**：
  - [ ] `broca/alembic.ini` 中无 `/home/ubuntu` 路径
  - [ ] `alembic upgrade head` 在 worktree 下使用正确的 `BROCA_DATABASE_DIR`

---

### Phase 2: Web 后端/前端配置收口

**目标**：Web 后端的 pydantic Settings 与 configs.json 的边界清晰；前端 .env 成为唯一入口

**阶段验收标准**：
- [ ] `BROCA_ENV=dev`（默认）时，web 配置页面和 runner 子进程读项目 `configs/configs.json`，不读 `~/.broca/`
- [ ] `BROCA_ENV=production` 时，读 `~/.broca/configs.json`（生产行为不变）
- [ ] Web 后端启动时，端口/URL 可从 configs.json 继承（无 configs.json 时回退到 .env 或默认值）
- [ ] 前端 `.env` 中 `VITE_BACKEND_URL` 和 `VITE_BROCA_SOCKET_SERVER_URL` 是**唯二**决定代理目标的变量
- [ ] worktree 只需创建/修改两个 `.env` 文件（后端 + 前端），每个 3-5 行即可隔离

#### Task 2.1: 配置解析优先级按环境切换（核心修复）
- **目标**：修复"worktree 测试服务读到 `~/.broca/` 下生产配置"的根本问题。通过 `BROCA_ENV` 控制优先级，dev 环境优先读项目配置
- **步骤**（以下为逻辑参考，执行时根据实际代码结构调整）：
  1. `broca/configs.py` — 修改 `get_configs()` 优先级逻辑：
     ```python
     def get_configs() -> BrocaConfig:
         """
         读取配置，优先级按环境区分:
         
         生产 (BROCA_ENV=production):
           1. BROCA_CONFIG 环境变量
           2. ~/.broca/configs.json
           3. 项目 configs/configs.json
         
         开发 (BROCA_ENV=dev, 默认):
           1. BROCA_CONFIG 环境变量
           2. 项目 configs/configs.json  ← 提升优先级
           3. ~/.broca/configs.json
         """
         env = os.getenv("BROCA_ENV", "dev")
         
         # 1. BROCA_CONFIG 环境变量（始终最高优先级）
         env_path = os.getenv("BROCA_CONFIG")
         if env_path:
             config = _load_config_file(Path(env_path))
             if config is not None:
                 return config
         
         # 2-3. 按环境决定项目配置和用户配置的顺序
         project_config = Path(__file__).parent.parent / "configs" / "configs.json"
         user_config = Path.home() / ".broca" / "configs.json"
         
         if env == "production":
             # 生产: 用户配置优先
             config = _load_config_file(user_config)
             if config is not None:
                 return config
             config = _load_config_file(project_config)
         else:
             # 开发: 项目配置优先（worktree 开发场景）
             config = _load_config_file(project_config)
             if config is not None:
                 return config
             config = _load_config_file(user_config)
         
         if config is not None:
             return config
         return BrocaConfig()
     ```
  2. `broca-web/backend/app/api/config.py` — `_resolve_general_config_path()` 同步修改：
     ```python
     def _resolve_general_config_path() -> Path:
         env = os.getenv("BROCA_ENV", "dev")
         
         # 1. BROCA_CONFIG
         env_path = os.getenv("BROCA_CONFIG")
         if env_path:
             return Path(env_path).expanduser()
         
          # parents[4]: app/api/config.py → api → app → backend → broca-web → 项目根
          project_config = Path(__file__).resolve().parents[4] / "configs" / "configs.json"
         user_configs_new = Path.home() / ".broca" / "configs" / "configs.json"
         user_config_legacy = Path.home() / ".broca" / "configs.json"
         
         if env == "production":
             # 生产: 用户配置优先
             if user_configs_new.exists():
                 return user_configs_new
             if user_config_legacy.exists():
                 return user_config_legacy
             return project_config
         else:
             # 开发: 项目配置优先
             if project_config.exists():
                 return project_config
             if user_configs_new.exists():
                 return user_configs_new
             if user_config_legacy.exists():
                 return user_config_legacy
             return project_config
     ```
  3. `broca-tui/broca_tui/config.py` — `_load_configs_json()` 同理：dev 环境优先读项目 `configs/configs.json`
  4. `broca-web/backend/.env` — 添加 `BROCA_ENV=dev`（worktree 开发默认值）
  5. `broca-web/backend/.env.example` — 添加 `BROCA_ENV` 说明
  6. 生产 supervisor 配置中注入 `BROCA_ENV=production`（在 Task 3.3 中处理）
- **预期产出**：worktree 开发时配置页面和 runner 子进程都读项目配置，不再误读 `~/.broca/` 下的生产配置
- **验收标准**：
  - [ ] `BROCA_ENV=dev`（默认）时，`get_configs()` 优先返回项目 `configs/configs.json`
  - [ ] `BROCA_ENV=production` 时，`get_configs()` 优先返回 `~/.broca/configs.json`
  - [ ] `BROCA_CONFIG` env 始终最高优先级（无论 dev/production）
  - [ ] Web 配置页面在 dev 环境下读写项目 `configs/configs.json`
  - [ ] worktree 中不设置 `BROCA_CONFIG` 时，消息不再发到生产

#### Task 2.2: Web 后端 Settings 与 configs.json 端口对齐
- **目标**：`Settings.port` 默认值从 `get_configs()` 的 `api_server_url`/`socket_server_url` 提取端口，.env 作为覆盖
- **注意**：此改动使 `broca-web` 依赖 `broca` core package（`from broca.configs import get_configs`）。若 broca 未安装，使用 try/except ImportError fallback 到 .env PORT 或默认 9001。
- **步骤**：
  1. `broca-web/backend/app/core/config.py` — 在 `Settings` 类中使用 `@model_validator(mode='before')` 延迟读取：
     - `port` 优先级：`PORT` env > `get_configs().api_server_url` 提取端口 > 默认 9001
     - 新增 `socketio_port` 字段：`BROCA_SOCKETIO_PORT` env > `get_configs().socket_server_url` 提取端口 > 默认 6666
     - 使用 `try/except ImportError` 包裹 `get_configs()` 调用，fallback 到硬编码默认
  2. `broca-web/backend/app/main.py` — `startup()` 中 SocketIO 端口改为读 `settings.socketio_port`（而非直接读 env）
  3. `broca-web/backend/app/core/socketio_runtime.py` — `SocketIOServerConfig` 从 settings 获取端口
  4. 更新 `.env.example` 注释说明优先级
- **预期产出**：后端启动时自动从 configs.json 继承端口，无需 .env 重复配置
- **验收标准**：
  - [ ] 不设置 `PORT` env 且 configs.json 中 `api_server_url=http://localhost:9001` 时，后端监听 9001
  - [ ] 设置 `PORT=9999` env 时覆盖 configs.json
  - [ ] SocketIO 端口同理
  - [ ] 模拟 `broca` 未安装场景（mock ImportError），后端仍能用 .env PORT 启动

#### Task 2.3: 前端 .env 收口 + Vite 代理逻辑简化
- **目标**：前端只有 `VITE_BACKEND_URL` 和 `VITE_BROCA_SOCKET_SERVER_URL` 两个关键变量；为空时自动走同域代理（Vite dev 或 nginx）
- **步骤**：
  1. `broca-web/frontend/.env` — 确认 `VITE_BROCA_SOCKET_SERVER_URL` 为空（走 Vite 代理），`VITE_BACKEND_URL` 指向正确的后端
  2. `broca-web/frontend/vite.config.ts` — 代理 target 逻辑：
     - `/api` → `VITE_BACKEND_URL || http://127.0.0.1:9001`
     - `/socket.io` → `VITE_BROCA_SOCKET_SERVER_URL || VITE_BACKEND_URL 同端口 || http://127.0.0.1:6666`
     - **关键改动**：当 `VITE_BROCA_SOCKET_SERVER_URL` 为空时，SocketIO 代理应指向 `VITE_BACKEND_URL` 同源的 6666 端口（因为 SocketIO 和 API 在同一进程）
  3. 删除 `.env` 中的注释掉的重复行
  4. `broca-web/frontend/.env.example` — 端口更新为 9001/6666，添加清晰的注释说明
- **预期产出**：前端代理配置简洁明了
- **验收标准**：
  - [ ] `vite.config.ts` 中 `/socket.io` 代理 target 默认值使用 6666（非 6868/8000）
  - [ ] 设置 `VITE_BACKEND_URL=http://127.0.0.1:9001` 后，`/api` 和 `/socket.io` 都能正确代理到本地后端
  - [ ] `.env.example` 中端口为 9001/6666

#### Task 2.4: 移除 .test-configs.json，统一到 .env 机制
- **目标**：worktree 的测试配置不再需要单独的 `.test-configs.json`，通过 `.env` 中 `BROCA_CONFIG` 指向一份干净的 configs.json
- **步骤**：
  1. 创建 `broca-web/backend/configs.dev.json`（git-tracked，无敏感信息）作为开发环境的服务拓扑配置：
     ```json
     {
       "socket_server_url": "http://localhost:6666",
       "api_server_url": "http://localhost:9001",
       "database_dir": "./.local-data",
       "log_file": "agent.log",
       "log_level": "DEBUG"
     }
     ```
  2. `.env` 中 `BROCA_CONFIG` 指向 `configs.dev.json`（相对路径），不再指向 `.test-configs.json`
  3. 敏感信息（Cloudflare keys、API keys）放入 `.env.local`（gitignored）或 `~/.broca/configs/llm_config.json`
  4. 删除 `.test-configs.json`，将其中的非敏感配置合并到 `configs.dev.json`
  5. 确认 `.gitignore` 包含 `.env.local`、`.env.development`、`dev.db`、`.local-data/`
- **预期产出**：worktree 配置自包含，无敏感信息泄露
- **验收标准**：
  - [ ] `.test-configs.json` 已删除
  - [ ] `configs.dev.json` 中无 API key、无 Cloudflare 密钥
  - [ ] `.env` 中 `BROCA_CONFIG` 指向 `configs.dev.json`
  - [ ] `git status` 不显示敏感文件

---

### Phase 3: 环境隔离机制

**目标**：一套简单的机制让开发（worktree）、测试（CI）、生产（部署）互不干扰

**阶段验收标准**：
- [ ] 同一台机器可同时运行生产（7001/8443/9001/6666）和开发（7000 + 自定义端口）
- [ ] worktree 开发只需创建/修改两个 `.env` 文件（后端 + 前端），每个 3-5 行配置
- [ ] CI 环境通过环境变量注入，无需修改文件

#### Task 3.1: 环境 Profile 补充安全策略（Phase 2 已实现优先级切换，此处补充安全约束）
- **目标**：在 `BROCA_ENV` 优先级切换基础上，增加生产环境安全约束
- **步骤**：
  1. `broca-web/backend/app/core/config.py` — Settings 增加 `env: str = os.getenv("BROCA_ENV", "dev")` 字段，根据 env 调整默认值：
     - `dev`: RELOAD=true, JWT 用默认 dev secret, CORS=*
     - `production`: RELOAD=false, **JWT_SECRET 必须显式设置（否则启动报错）**, CORS 必须显式设置
  2. `broca/configs.py` — 如果 `BROCA_ENV=production` 且 `log_level=DEBUG`，强制回退为 `INFO` 并 warning
  3. 创建 `broca-web/backend/.env.production.example` 作为生产模板
- **预期产出**：生产环境有安全护栏
- **验收标准**：
  - [ ] `BROCA_ENV=production` 时未设置 `JWT_SECRET` 会 raise 启动错误
  - [ ] `BROCA_ENV=production` 时 `log_level=DEBUG` 会被强制降为 `INFO`
  - [ ] `BROCA_ENV=dev`（默认）时行为与现在一致
  - [ ] `.env.production.example` 存在且包含所有生产必需项

#### Task 3.2: Worktree 开发隔离方案
- **目标**：在 git worktree 中开发时，3 步即可完成环境隔离
- **步骤**：
  1. 编写 `docs/dev-worktree-setup.md`，说明 3 步：
      ```bash
      # Step 1: 创建 worktree
      git worktree add .worktrees/refactor refactor

      # Step 2: 配置后端 .env（推荐写入 .env 文件，临时调试可用 inline env vars）
      cd .worktrees/refactor/broca-web/backend
      # 写入 .env:
      #   PORT=9002
      #   BROCA_SOCKETIO_PORT=6667
      #   BROCA_CONFIG=./configs.dev.json
      ./start.sh
      # 或临时调试:
      # PORT=9002 BROCA_SOCKETIO_PORT=6667 BROCA_CONFIG=./configs.dev.json ./start.sh

      # Step 3: 配置前端 .env 并启动（指向本地后端）
      cd .worktrees/refactor/broca-web/frontend
      # 写入 .env: VITE_BACKEND_URL=http://127.0.0.1:9002
      pnpm dev
      ```
  2. 创建 `broca-web/backend/configs.dev.json`（已在 Task 2.4 中创建）
  3. `configs.dev.json` 中端口使用占位，实际由 env 覆盖（避免 worktree 间端口冲突）
  4. 更新 `broca-web/frontend/.env.example` 添加 worktree 示例注释
- **预期产出**：开发者按文档 3 步即可完成隔离
- **验收标准**：
  - [ ] 按文档操作后，worktree 前端只连接 worktree 后端（不触及生产）
  - [ ] 生产环境（supervisor 管理）不受 worktree 影响
   - [ ] 文档包含完整 3 步命令，每步有预期输出说明；按步骤操作后 `curl http://localhost:7000/api/health` 返回 200

#### Task 3.3: CI/生产环境配置
- **目标**：CI 和生产通过环境变量注入，不依赖文件
- **步骤**：
  1. 生产：`scripts/install.sh` 已生成 supervisor 配置注入 `BROCA_CONFIG`/`BROCA_DATABASE_DIR`/`PORT`/`BROCA_SOCKETIO_PORT` — 确认其生成的值与新端口一致
  2. CI：添加 `.github/workflows/env.example` 或在 CI 配置文档中说明必需环境变量：
     ```
     BROCA_ENV=production
     BROCA_CONFIG=/opt/broca/configs/configs.json
     BROCA_DATABASE_DIR=/opt/broca/data
     BROCA_LLM_CONFIG=/opt/broca/configs/llm_config.json
     PORT=9001
     BROCA_SOCKETIO_PORT=6666
     JWT_SECRET=<from-secrets>
     SQLITE_DATABASE_PATH=sqlite:////opt/broca/data/web.db
     ```
  3. 更新 `scripts/install.sh` 中的默认端口为新标准（9001/6666），确认 nginx 配置 proxy_pass 正确
- **预期产出**：CI/生产环境配置通过 env 注入
- **验收标准**：
  - [ ] `install.sh` 生成的 supervisor 配置包含正确的端口和 `BROCA_CONFIG` 路径
  - [ ] 生产 nginx 代理 `127.0.0.1:9001` 和 `127.0.0.1:6666`
  - [ ] 所有 CI 必需环境变量有文档说明

---

### Phase 4: 清理与文档

**目标**：清理遗留文件，更新文档，确保配置说明一致

**阶段验收标准**：
- [ ] 无遗留的旧端口引用
- [ ] 配置相关文档已更新
- [ ] 敏感信息不在 git 中

#### Task 4.1: 清理遗留配置与文件
- **目标**：删除/归档不再需要的配置文件
- **步骤**：
  1. 删除 `broca-web/backend/.test-configs.json`（已在 Task 2.4 中处理）
  2. 检查 `configs/configs.json`（项目根）— 更新路径为相对或 `~/.broca/` 风格，移除 `/home/ubuntu/` 绝对路径
  3. 检查 `.gitignore` 确保覆盖：`.env.local`, `.env.development`, `dev.db`, `.local-data/`, `*.log`
  4. 检查是否有其他 git-tracked 文件包含敏感信息（grep `api_key\|secret\|password`）
- **预期产出**：无敏感信息泄露，无遗留文件
- **验收标准**：
  - [ ] `git ls-files | xargs grep -l "secret\|api_key"` 结果中无真实密钥
  - [ ] `configs/configs.json` 中无 `/home/ubuntu/` 路径
  - [ ] `.gitignore` 包含所有本地开发产物

#### Task 4.2: 更新配置文档
- **目标**：一份文档说清所有配置项及其优先级
- **步骤**：
  1. 创建/更新 `docs/configuration.md`，内容包含：
     - 分层模型图（Layer 1/2/3）
     - 所有环境变量清单（名称/用途/默认值/影响范围）
     - configs.json 字段说明
     - .env 字段说明（后端/前端）
     - 环境隔离指南（dev/worktree/CI/production）
     - 端口标准表
  2. 更新 `broca-web/README.md` 中的启动说明（端口、配置）
  3. 更新项目根 `README.md` 中的配置章节
- **预期产出**：完整的配置参考文档
- **验收标准**：
  - [ ] `docs/configuration.md` 存在且包含分层模型、env 变量表、端口表
   - [ ] 文档包含从 clone 到运行完整开发环境的步骤清单（≤10 步），每步有验证命令
  - [ ] README 中的端口/URL 与新标准一致

---

## 风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| 已部署生产环境使用旧端口 9000/6868 | 升级后生产断裂 | 生产通过 supervisor env 显式注入端口，不依赖代码默认值；`install.sh` 升级时检测 `~/.broca/configs/configs.json` 中旧端口并自动迁移为 9001/6666 |
| **生产环境未设置 `BROCA_ENV`**（默认 `"dev"`） | 配置优先级静默切换为"项目优先"，如果部署目录含 git-tracked `configs/configs.json` 会读错文件 | 在 `get_configs()` 中增加安全网：如果 `BROCA_ENV` 未显式设置、无 `BROCA_CONFIG`、项目 `configs.json` 存在但 `~/.broca/configs.json` 也存在，log WARNING 提示"检测到多配置文件，请显式设置 BROCA_ENV"。supervisor/install.sh 中强制注入 `BROCA_ENV=production` |
| `get_configs()` 在 web 后端 import 时触发文件 IO | 启动变慢 | configs.json 读取 <1ms（小文件），可接受；未来可加 lru_cache |
| 多 worktree 端口冲突 | 开发体验差 | 文档建议 `PORT=$((9001 + worktree_index))` 模式 |
| 前端 Vite 代理在 `VITE_BROCA_SOCKET_SERVER_URL` 为空时的 fallback 逻辑 | 如果后端不在 6666 则代理失败 | 文档强调 worktree 必须显式设置 `VITE_BACKEND_URL`；vite.config 中 socket 代理从 backend URL 推导端口 |
| pydantic Settings 中 `os.getenv` 在 class 定义时执行（非实例化时） | 环境变量在 import 后才设置时不生效 | Task 2.2 中使用 `@model_validator(mode='before')` 延迟读取环境变量 |
| **`.test-configs.json` 含真实 API 密钥** | 误提交到 git 导致密钥泄露 | **Pre-execution**：立即将 `.test-configs.json` 加入 `.gitignore`；Task 2.4 执行前删除该文件 |
| `broca-web` 依赖 `broca` core package（`get_configs()`） | 如果 `broca-web` 需要独立部署（不安装 broca），import 会失败 | Task 2.2 中使用 `try/except ImportError` fallback：若 broca 未安装，使用 `.env` 中的 PORT 或硬编码默认 9001 |

## 未解决的问题
- 是否需要支持 `BROCA_PROFILE` 文件（如 `~/.broca/profiles/dev.json`）来进一步简化多环境切换？（当前方案通过 env + 单一 configs.json 已够用，暂不做）
