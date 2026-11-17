# Broca 配置参考

## 分层模型

Broca 采用**纯文件配置**模型（不读取系统环境变量），配置优先级如下（高层覆盖低层）：

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 2: .env 文件                                               │
│   运行参数: 端口/主机/数据库/JWT/SocketIO                        │
│   后端: broca-web/backend/.env                                   │
│   加载顺序: .env → .env.local → .env.development/.production    │
│   前端: broca-web/frontend/.env                                  │
├─────────────────────────────────────────────────────────────────┤
│ Layer 1: configs.json (服务配置)                                  │
│   路径/执行参数/搜索/存储/ASR                                    │
│   发现规则:                                                      │
│     1. .env 中 BROCA_CONFIG 指定的路径                            │
│     2. 项目 configs/configs.json                                 │
│     3. ~/.broca/configs.json                                     │
├─────────────────────────────────────────────────────────────────┤
│ Layer 0: 代码默认值                                              │
│   port=9001, socketio_port=6666, log_level=INFO 等              │
└─────────────────────────────────────────────────────────────────┘
```

### 关键设计

- **不读取 `os.environ`**：pydantic Settings 移除了 `EnvSettingsSource`，仅通过 `DotEnvSettingsSource` 从 .env 文件读取
- **BROCA_CONFIG**：在 .env 文件中设置，指向特定的 configs.json 路径
- **BROCA_ENV 不再存在**：环境标识通过 .env 文件中的 `ENV=dev/production` 表达
- **CI/CD**：通过生成 `.env.local` 文件注入 secrets，而非环境变量

---

## 配置项清单

### configs.json（Layer 1）

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `database_dir` | `~/.broca/data` | 数据库文件目录 |
| `log_file` | `~/.broca/logs/agent.log` | 日志文件路径 |
| `log_dir` | `~/.broca/logs` | 日志目录 |
| `log_level` | `"INFO"` | 日志级别（production 下 DEBUG 强制降为 INFO） |
| `llm_config_file` | `~/.broca/configs/llm_config.json` | LLM 配置文件路径 |
| `decision_config_file` | — | 决策配置文件路径（可选） |
| `agents_config_dir` | `~/.broca/configs/agents` | Agent 角色配置目录 |
| `snapshot_home` | `~/.broca/snapshots` | 快照 Git 仓库目录 |
| `components_config` | `""` | 组件覆盖配置路径 |
| `socket_server_url` | `http://localhost:6666` | SocketIO 服务端地址 |
| `api_server_url` | `http://localhost:9001` | REST API 地址 |

#### execution 分组

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `step_max_errors` | `3` | LLM 最大重试次数 |
| `llm_retry_delay` | `5` | LLM 重试间隔（秒） |
| `tool_call_timeout` | `120` | 工具执行超时（秒） |
| `assign_task_timeout` | `1800` | assign_task 超时（秒） |
| `llm_timeout` | `300` | LLM 流式请求超时（秒） |
| `llm_first_chunk_timeout` | `30` | LLM 首块超时（秒） |
| `dead_loop_window` | `3` | 死循环判定窗口 |
| `message_queue_size` | `3` | 消息队列大小 |
| `permission_request_timeout` | `90` | 权限请求等待超时（秒） |
| `agent_query_timeout` | `300` | ask_user 等待超时（秒） |
| `tool_execution_mode` | `"parallel"` | 工具执行模式 |
| `execution_mode` | `"non_blocking"` | 执行模式：`non_blocking`（非阻塞）/ `blocking`（阻塞） |
| `max_parallel_tools` | `10` | 并行模式最大并发数 |
| `max_concurrent_runners` | `10` | 最大并发 session runner |
| `runner_heartbeat_interval` | `5` | Runner 上报心跳间隔（秒） |
| `runner_heartbeat_timeout` | `45` | 心跳超时判定阈值（秒，≈9 个周期） |
| `runner_heartbeat_check_interval` | `15` | Manager 心跳巡检间隔（秒） |
| `runner_status_persist_interval` | `60` | 心跳状态落库最小间隔（秒），避免每轮巡检都写库 |
| `runner_ipc_queue_size` | `1000` | 每个 session 的 IPC 消息队列上限。队列满时：心跳丢最旧的、其它消息丢新的，均计入 `get_stats()["dropped_events"]` |

#### search 分组

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `tavily_api_key` | `""` | Tavily API Key |
| `anysearch_api_key` | `""` | AnySearch API Key |
| `anysearch_api_base_url` | `https://api.anysearch.com` | AnySearch URL |
| `default_search_provider` | `"tavily"` | 默认搜索提供商 |
| `default_fetch_provider` | `"anysearch"` | 默认 fetch 提供商 |

### .env 文件（Layer 2，Web 后端）

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `ENV` | `dev` | 环境标识: `dev` / `production` |
| `PORT` | `9001` | HTTP API 端口 |
| `HOST` | `0.0.0.0` | HTTP 绑定地址 |
| `BROCA_SOCKETIO_PORT` | `6666` | SocketIO 端口 |
| `BROCA_SOCKETIO_ENABLED` | `true` | 是否启用内嵌 SocketIO |
| `BROCA_SOCKETIO_HOST` | `0.0.0.0` | SocketIO 绑定地址 |
| `BROCA_SOCKETIO_CORS` | `*` | SocketIO CORS |
| `CORS_ALLOW_ORIGINS` | `*` | HTTP API CORS（生产必须显式设置） |
| `DATABASE_TYPE` | `sqlite` | 数据库类型 |
| `SQLITE_DATABASE_PATH` | `sqlite:///./dev.db` | SQLite 路径 |
| `DATABASE_URL` | `""` | PostgreSQL 连接串 |
| `JWT_SECRET` | dev 默认值 | JWT 密钥（生产必须设置） |
| `JWT_EXPIRE_MINUTES` | `2880` | Token 过期时间（分钟） |
| `BROCA_CONFIG` | `""` | configs.json 路径（**唯一**决定 broca 数据目录/日志/快照的配置源） |
| `RELOAD` | `true` | uvicorn 热重载 |

> ⚠️ **没有 `BROCA_DATABASE_DIR` 字段**。`Settings` 是纯 `.env` 文件驱动
> （`settings_customise_sources` 移除了 `env_settings`），不读 `os.environ`。
> broca 侧的数据库目录由 `BROCA_CONFIG` 指向的 `configs.json` 的
> `database_dir` 决定；`.env` 里写 `BROCA_DATABASE_DIR` 属于"看起来生效其实无效"的陷阱。
> 该变量仅在 **alembic 迁移**时作为兜底被 `broca/alembic/env.py` 读取
> （优先级低于 `-x db_url=`）。

### 前端 .env（Vite）

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `VITE_BACKEND_URL` | `http://127.0.0.1:9001` | Vite proxy 目标 |
| `VITE_BROCA_SOCKET_SERVER_URL` | _(空=自动推导)_ | SocketIO URL |
| `VITE_API_MOCK` | `false` | MSW mock 模式 |
| `VITE_DEV_PORT` | `7000` | Vite dev server 端口 |

### LLM 配置 (llm_config.json)

| 字段 | 说明 |
|------|------|
| `__default__` | 全局默认 provider/model |
| `{provider}.base_url` | API 地址 |
| `{provider}.api_key` | API Key（直接在此配置，无环境变量覆盖） |
| `{provider}.models.{name}` | 模型配置（temperature, max_tokens 等） |
| `{provider}.models.{name}.meta.modality` | 支持的模态（`text`/`image`/`video`/`audio`）；**只放 wire 允许键**（如 `image.detail`），不得放业务配置 |
| `{provider}.models.{name}.meta.media_limits.max_inline_mb` | base64 内联阈值（MB，默认 4）。超过则先压缩，压不下去报错 |
| `{provider}.files_api` | （可选）**provider 级**供应商原生文件上传策略；配置后该 provider 优先走 files_api，否则走 base64 |

#### 媒体物化策略（ref → wire）

消息历史/DB 中图片以轻量 `ref://` 保存（含 `sha256/mime/size` 与展示 URL），发请求前才物化为 wire 表示。单张媒体 part 的决策顺序：

1. 该 model 的 `meta.modality` 不支持对应模态 → 降级为**文本链接**。
2. 该 provider 配置了 `files_api`（**provider 级**，同一 provider 共享同一上传端点/认证/配额）→ **files_api 模式**：`size <= files_api.max_size_mb` 上传并以 file_id 引用；否则先压缩，仍超 → 报错。
3. 未配置（或 `type` 未知/构造失败 → 安全兜底）→ **base64 模式**：`size <= media_limits.max_inline_mb` 内联 base64；否则先压缩，仍超 → 报错。
4. **无 url 兜底**：任何失败都抛明确错误提醒用户，绝不静默回退为公网 url。

> ⚠️ `media_limits` 必须放在 model 的 `meta` 下（**不得放进 `meta.modality.image`**——否则会被 `parse_message` 的 `image_part.update(modality["image"])` 混入发往 LLM 的 `image_url` part，造成非法参数/供应商报错）。`files_api` 则放在 **provider 级**（与 `base_url`/`api_key` 平级）。

#### `{provider}.files_api` 字段

| 字段 | 说明 | 默认 |
|------|------|------|
| `type` | 策略类型：`deepseek`（已实现）；`gemini`/`anthropic`/`openai` 预留 | 无（未配置即走 base64） |
| `purpose` | 上传用途（DeepSeek `user_data`） | `user_data` |
| `expires_seconds` | 文件保留秒数（3600–2592000）；file_id 缓存 TTL 取 `min(3天, 本值)` | 不设置=不过期 |
| `max_size_mb` | files_api 单文件阈值（MB） | 按 provider，DeepSeek 64 |

示例（`files_api` 位于 provider 级，与 `base_url`/`api_key` 平级）：

```json
"deepseek": {
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "...",
    "files_api": {
        "type": "deepseek",
        "purpose": "user_data",
        "expires_seconds": 86400,
        "max_size_mb": 64
    },
    "models": {
        "deepseek-v4-flash": {
            "model": "openai/deepseek-v4-flash",
            "meta": {
                "modality": {"text": "", "image": {}},
                "media_limits": {"max_inline_mb": 4}
            }
        }
    }
}
```

#### Provider 差异表

| Provider | 上传端点 / 认证 | 引用块形态 | 单文件上限 | 备注 |
|----------|----------------|-----------|-----------|------|
| **DeepSeek** | `POST {base_url}/files` multipart（`purpose=user_data`） | 双 key：`{"type":"file","file":{"file_id":...},"file_id":...}` | 64 MiB | 模型用 `openai/` 前缀经 openai provider 下发；`file` 喂 litellm、顶层 `file_id` 喂 DeepSeek（已冒烟验证） |
| Gemini | File API 上传，返回 `uri` | `file_data`（含 `file_uri`） | ~2 GB | 预留 |
| Anthropic | `POST /v1/files` + `anthropic-beta` 头 | `{"type":"image","source":{"type":"file",...}}` | 500 MB | 预留 |
| OpenAI | `POST /v1/files` | chat 图**不支持** file_id（仅 Assistants） | —— | 预留，chat 场景仍走 base64 |

---

## 端口标准

| 服务 | 标准端口 | .env 字段 | 默认值来源 |
|------|----------|-----------|-----------|
| 后端 HTTP API | 9001 | `PORT` | configs.json `api_server_url` |
| Socket.IO | 6666 | `BROCA_SOCKETIO_PORT` | configs.json `socket_server_url` |
| 前端 (nginx) | 7001 | — | nginx 配置 |
| 前端 HTTPS | 8443 | — | nginx 配置 |
| 前端 dev (vite) | 7000 | `VITE_DEV_PORT` | vite.config.ts |

### Worktree 端口方案

```
主分支:     PORT=9001, BROCA_SOCKETIO_PORT=6666, VITE_DEV_PORT=7000
worktree 1: PORT=9002, BROCA_SOCKETIO_PORT=6667, VITE_DEV_PORT=7002
worktree 2: PORT=9003, BROCA_SOCKETIO_PORT=6668, VITE_DEV_PORT=7003
```

---

## 环境隔离

### 开发环境（Worktree 隔离）

每个 worktree 通过**独立的 .env 文件**实现完全隔离，无需设置任何环境变量：

```bash
# worktree/broca-web/backend/.env
ENV=dev
PORT=9002
BROCA_SOCKETIO_PORT=6667
# 数据目录隔离靠 configs.dev.json 的 database_dir（不是环境变量）
BROCA_CONFIG=./configs.dev.json
SQLITE_DATABASE_PATH=sqlite:///./.local-data/backend.db
```

```bash
# worktree/broca-web/frontend/.env
VITE_BACKEND_URL=http://127.0.0.1:9002
VITE_DEV_PORT=7002
```

### 生产环境

`install.sh` 自动生成 `~/.broca/web/backend/.env`（由 `scripts/gen_backend_env.py` 生成并自检）：

```bash
# ~/.broca/web/backend/.env（install.sh 自动生成）
ENV=production
PORT=9000
BROCA_SOCKETIO_PORT=6868
BROCA_CONFIG=/Users/xxx/.broca/configs/configs.json
SQLITE_DATABASE_PATH=sqlite:////Users/xxx/.broca/data/backend.db
JWT_SECRET=<strong-random-secret>
CORS_ALLOW_ORIGINS=http://localhost:5166,https://localhost:8443,...
```

**迁移目标库**：`install.sh` 用 `alembic -x db_url=sqlite:///<库路径>` 显式指定，
库路径从上面的 `configs.json`（sessions.db）与 `.env`（backend.db）同源反解，
保证"迁移的库 == 运行时读写的库"。不要再用环境变量传目标库 ——
`Settings` 与 `broca.configs` 都不读 `os.environ`，那会导致迁移静默写到别的文件。

**生产安全护栏**（启动时强制校验）：
- `JWT_SECRET` 不能为空或默认 dev 值
- `CORS_ALLOW_ORIGINS` 不能为 `*`
- `log_level=DEBUG` 强制降为 INFO

### CI/CD 适配

```yaml
# GitHub Actions 示例
- name: Generate .env for CI
  run: |
    cd broca-web/backend
    cat > .env.local <<EOF
    ENV=production
    JWT_SECRET=${{ secrets.JWT_SECRET }}
    CORS_ALLOW_ORIGINS=https://ci-test.example.com
    EOF

- name: Run tests
  run: pytest
```

---

## 快速参考

```bash
# 本地开发
cd broca-web && ./dev.sh

# 验证
curl http://localhost:9001/api/health
curl http://localhost:6666/socket.io/?EIO=4&transport=polling

# 生产部署
sh scripts/install.sh
broca service start
```
