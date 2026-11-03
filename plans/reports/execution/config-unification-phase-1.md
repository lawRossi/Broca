# 配置统一与环境隔离 — Phase 1: 核心收口 — Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | plans/config-unification-plan.md |
| Phase | Phase 1: 核心收口 — 统一默认值与配置加载 |
| Status | ✅ Pass |

## Plan Anchor Confirmation

- [x] Re-read the plan document section for this phase before starting
- [x] Acceptance criteria for each task confirmed

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| Task 1.1: 标准化端口/URL 默认值 | ✅ | ① 全局搜索无旧端口 ② Python 默认端口 6666 ③ .env.example 用 9001/6666 | ① grep 0 结果 ② socketio_server.py port=6666 ③ 两个 .env.example 已更新 | 无 |
| Task 1.2: 消除硬编码 URL | ✅ | ① scheduler 优先读 configs.json ② service_manager 注入 BROCA_CONFIG ③ 默认值加 fallback 注释 | ① scheduler.py 改为 env > get_configs() > 默认 ② 已确认 line 956/1819 注入 BROCA_CONFIG ③ worktree.py + agent_configs.py 加注释 | 无 |
| Task 1.3: 修正 alembic.ini | ✅ | ① 无 /home/ubuntu 路径 ② worktree 下使用正确 BROCA_DATABASE_DIR | ① sqlalchemy.url 已清空 ② env.py 已有 BROCA_DATABASE_DIR 优先级逻辑 | 无 |

## Changes Summary

### 修改的文件

| 文件 | 改动 |
|------|------|
| `broca/communication/socketio_server.py` | `port: int = 8000` → `port: int = 6666` |
| `broca/scheduler.py` | socket URL 改为 `env > get_configs().socket_server_url > 默认` |
| `broca/agent_configs.py` | `server_url` 加 fallback 注释 |
| `broca/cli/worktree.py` | `DEFAULT_API_BASE_URL` 加 fallback 注释 |
| `broca/alembic.ini` | `sqlalchemy.url` 清空（移除 `/home/ubuntu/` 硬编码） |
| `broca-vscode/src/extension/config.ts` | 默认值 8000 → 9001/6666 |
| `broca-vscode/src/extension/chatWebView.ts` | 4 处 fallback URL 更新 |
| `broca-vscode/src/extension/asrClient.ts` | 注释中 9000 → 9001 |
| `broca-vscode/.../ClientConfigPanel.vue` | 默认值 + placeholder 更新 |
| `broca-vscode/.../GeneralConfigPanel.vue` | placeholder 更新 |
| `broca-web/backend/.env.example` | PORT=9001, BROCA_SOCKETIO_PORT=6666 |
| `broca-web/frontend/.env.example` | 端口更新 + VITE_BROCA_SOCKET_SERVER_URL 改为空 |

## Quality Checklist

- [x] All phase-level ACs satisfied
- [x] All task-level ACs satisfied
- [x] No missing tasks (cross-referenced against plan)
- [x] No extra functionality (only what the plan asked for)
- [x] Manually verified key behaviors (grep verification)
- [x] Code follows project conventions
- [x] Compatible with existing work

## 备注

- `configs/configs.json` 中的 `/home/ubuntu/` 路径留待 Phase 4 Task 4.1 处理
- README/docs 中的旧端口引用也留待 Phase 4 统一更新
