# CI / 生产环境必需环境变量

CI 和容器化部署通过环境变量注入所有配置，**不依赖任何 .env 文件或 configs.json 文件**。

## 必需变量

| 变量 | 值 | 说明 |
|------|-----|------|
| `BROCA_ENV` | `production` | 启用生产安全策略（JWT/CORS/log_level 校验） |
| `BROCA_CONFIG` | `/opt/broca/configs/configs.json` | 服务拓扑配置文件路径 |
| `BROCA_DATABASE_DIR` | `/opt/broca/data` | 数据库文件目录 |
| `BROCA_LLM_CONFIG` | `/opt/broca/configs/llm_config.json` | LLM 提供商配置 |
| `PORT` | `9001` | 后端 HTTP API 端口 |
| `BROCA_SOCKETIO_PORT` | `6666` | SocketIO 端口 |
| `JWT_SECRET` | `<from-secrets>` | JWT 签名密钥（64 位 hex） |
| `CORS_ALLOW_ORIGINS` | `https://your-domain.com` | 允许的跨域来源（逗号分隔） |
| `SQLITE_DATABASE_PATH` | `sqlite:////opt/broca/data/web.db` | Web 后端 SQLite 路径 |

## 可选变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BROCA_SOCKETIO_ENABLED` | `true` | 是否启用内嵌 SocketIO |
| `BROCA_SOCKETIO_HOST` | `0.0.0.0` | SocketIO 绑定地址 |
| `DATABASE_TYPE` | `sqlite` | 数据库类型 (`sqlite` / `postgresql`) |
| `HOST` | `0.0.0.0` | HTTP 绑定地址 |

## Docker / Kubernetes 示例

```yaml
# docker-compose.yml 片段
environment:
  BROCA_ENV: production
  BROCA_CONFIG: /opt/broca/configs/configs.json
  BROCA_DATABASE_DIR: /opt/broca/data
  BROCA_LLM_CONFIG: /opt/broca/configs/llm_config.json
  PORT: "9001"
  BROCA_SOCKETIO_PORT: "6666"
  JWT_SECRET: ${JWT_SECRET}
  CORS_ALLOW_ORIGINS: https://app.example.com
  SQLITE_DATABASE_PATH: sqlite:////opt/broca/data/web.db
```

## 生产 configs.json 模板

```json
{
    "socket_server_url": "http://localhost:6666",
    "api_server_url": "http://localhost:9001",
    "database_dir": "/opt/broca/data",
    "log_file": "/opt/broca/logs/agent.log",
    "log_level": "INFO",
    "llm_config_file": "/opt/broca/configs/llm_config.json"
}
```

> **注意**：`log_level` 设为 `DEBUG` 时会被强制降为 `INFO`（生产环境安全护栏）。
