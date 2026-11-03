# Git Worktree 开发环境隔离指南

在 git worktree 中开发 Broca 时，通过 **3 步** 即可完成与生产环境的完全隔离。

## 核心原理

- `BROCA_ENV=dev`（默认）→ 项目 `configs/configs.json` 优先于 `~/.broca/`
- `BROCA_CONFIG=./configs.dev.json` → 精确指定服务拓扑（端口/数据库路径）
- 前端 `VITE_BACKEND_URL` → 代理指向 worktree 后端，不触及生产

## 3 步操作

### Step 1: 创建 worktree

```bash
git worktree add .worktrees/my-feature my-feature-branch
```

**预期输出**：`Preparing worktree (checking out 'my-feature-branch')`

### Step 2: 配置并启动后端

```bash
cd .worktrees/my-feature/broca-web/backend
```

编辑 `.env`（如果不存在则从 `.env.example` 复制），设置 worktree 专属端口：

```bash
# .env 关键配置（3 行即可完成隔离）
PORT=9002
BROCA_SOCKETIO_PORT=6667
BROCA_CONFIG=./configs.dev.json
```

> **端口选择**：使用 `9001 + worktree_index` 模式避免冲突
> - 主分支: PORT=9001, BROCA_SOCKETIO_PORT=6666
> - worktree 1: PORT=9002, BROCA_SOCKETIO_PORT=6667
> - worktree 2: PORT=9003, BROCA_SOCKETIO_PORT=6668

启动：

```bash
./start.sh
```

**预期输出**：
```
INFO:     Uvicorn running on http://0.0.0.0:9002
INFO:     SocketIOServer started in background: 0.0.0.0:6667
```

验证后端健康：

```bash
curl http://127.0.0.1:9002/api/health
# 预期: {"status":"ok"} 或 HTTP 200
```

### Step 3: 配置并启动前端

```bash
cd .worktrees/my-feature/broca-web/frontend
```

编辑 `.env`，指向 worktree 后端：

```bash
# .env 关键配置
VITE_BACKEND_URL=http://127.0.0.1:9002
```

> 留空 `VITE_BROCA_SOCKET_SERVER_URL` 即可 — Vite 会自动从 `VITE_BACKEND_URL` 推导 SocketIO 代理目标（同 host + 6666 端口）

启动：

```bash
pnpm dev
```

**预期输出**：
```
VITE v7.x.x  ready in xxx ms
➜  Local: https://localhost:7000/
```

验证前端代理：

```bash
curl https://localhost:7000/api/health
# 预期: 代理到 127.0.0.1:9002，返回 200
```

## 隔离保证

| 组件 | 生产环境 | Worktree |
|------|----------|----------|
| 后端 API | 9001 (supervisor) | 9002 (.env) |
| SocketIO | 6666 (supervisor) | 6667 (.env) |
| 前端 | 7001 (nginx) | 7000 (vite) |
| 数据库 | ~/.broca/data | ./.local-data/ |
| 配置来源 | ~/.broca/ (production) | 项目 configs/ (dev) |

## 常见问题

### Q: 前端连不上后端？
确认 `VITE_BACKEND_URL` 指向的端口与后端 `PORT` 一致。

### Q: 端口被占用？
`lsof -i :9002` 查看占用进程，换一个 worktree 端口号。

### Q: 敏感配置（API key）放哪里？
- 本地开发: `broca-web/backend/.env.local`（gitignored）
- 生产: `~/.broca/configs/llm_config.json`

### Q: 如何临时调试不改 .env？
```bash
PORT=9003 BROCA_SOCKETIO_PORT=6668 ./start.sh
```
Inline 环境变量优先级高于 .env 文件。
