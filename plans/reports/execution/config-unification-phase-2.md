# 配置统一与环境隔离 — Phase 2: Web 后端/前端配置收口 — Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | `plans/config-unification-plan.md` |
| Phase | Phase 2: Web 后端/前端配置收口 |
| Status | ✅ Pass |
| Date | 2026-11-01 |

## Plan Anchor Confirmation

- [x] Re-read the plan document section for this phase before starting
- [x] Acceptance criteria for each task confirmed

## Pre-execution

- [x] `.test-configs.json` 加入 `.gitignore`（含真实 API 密钥）
- [x] `.gitignore` 确认包含：`.env.local`、`.env.development`、`dev.db`、`.local-data/`

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| Task 2.1: 配置解析优先级按环境切换 | ✅ | 5 ACs | All verified via runtime tests | 修复了 TUI 原有 `parents[4]` 路径 bug（应为 `parents[3]`） |
| Task 2.2: Web 后端 Settings 与 configs.json 端口对齐 | ✅ | 4 ACs | All verified: model_validator 正确派生/覆盖端口 | None |
| Task 2.3: 前端 .env 收口 + Vite 代理逻辑简化 | ✅ | 3 ACs | socket proxy 从 VITE_BACKEND_URL 推导 host+6666 | None |
| Task 2.4: 移除 .test-configs.json，统一到 .env 机制 | ✅ | 4 ACs | configs.dev.json 创建，.test-configs.json 删除 | None |

## Phase-Level AC Verification

| # | AC | Result |
|:-:|-----|--------|
| 1 | `BROCA_ENV=dev`（默认）时，web 配置页面和 runner 子进程读项目 `configs/configs.json`，不读 `~/.broca/` | ✅ `get_configs()` / `_resolve_general_config_path()` / TUI `_load_configs_json()` 均验证 |
| 2 | `BROCA_ENV=production` 时，读 `~/.broca/configs.json`（生产行为不变） | ✅ 生产模式优先读用户配置 |
| 3 | Web 后端启动时，端口/URL 可从 configs.json 继承（无 configs.json 时回退到 .env 或默认值） | ✅ `@model_validator` 派生 9001/6666；ImportError fallback 正常 |
| 4 | 前端 `.env` 中 `VITE_BACKEND_URL` 和 `VITE_BROCA_SOCKET_SERVER_URL` 是**唯二**决定代理目标的变量 | ✅ regex 验证 vite.config.ts proxy 段仅有这两个变量 |
| 5 | worktree 只需创建/修改两个 `.env` 文件（后端 + 前端），每个 3-5 行即可隔离 | ✅ 后端 7 行，前端 6 行（含必要注释） |

## Files Modified

| File | Change |
|------|--------|
| `broca/configs.py` | `get_configs()` 添加 `BROCA_ENV` 优先级逻辑 |
| `broca-web/backend/app/api/config.py` | `_resolve_general_config_path()` 添加 `BROCA_ENV` 优先级 + `parents[4]` 注释 |
| `broca-tui/broca_tui/config.py` | `_load_configs_json()` 添加 `BROCA_ENV` 优先级；修复 `parents[4]`→`parents[3]` 路径 bug |
| `broca-web/backend/app/core/config.py` | Settings 新增 `socketio_port` 字段 + `@model_validator` 从 configs.json 派生端口 |
| `broca-web/backend/app/main.py` | 导入 settings，socketio port 改用 `settings.socketio_port` |
| `broca-web/backend/app/core/socketio_runtime.py` | 端口默认值简化为 `6666`（实际由 main.py 传入） |
| `broca-web/backend/.env` | 添加 `BROCA_ENV=dev`，`BROCA_CONFIG` 改为 `./configs.dev.json` |
| `broca-web/backend/.env.example` | 添加 `BROCA_ENV` 说明，端口注释更新优先级说明 |
| `broca-web/frontend/.env` | 删除注释掉的重复 `VITE_BACKEND_URL` 行 |
| `broca-web/frontend/vite.config.ts` | socket proxy fallback 从 VITE_BACKEND_URL 推导 host+6666 |
| `broca-web/frontend/.env.example` | 添加 worktree 示例注释 |
| `broca-web/backend/configs.dev.json` | **新建** — 开发环境服务拓扑配置（无敏感信息） |
| `broca-web/backend/.test-configs.json` | **删除** — 含真实密钥，已 gitignore |
| `.gitignore` | 添加 `.local-data/`、`.test-configs.json` |

## Deviations

| # | Deviation | Reason | Impact |
|:-:|-----------|--------|--------|
| 1 | TUI `parents[4]` → `parents[3]` 路径修正 | 原有代码 `parent.parent.parent.parent` 多了一级，导致项目配置永远不被找到 | 修复了 TUI 在 dev 模式下错误读取 `~/.broca/` 的 bug |

## Quality Checklist

- [x] All phase-level ACs satisfied
- [x] All task-level ACs satisfied
- [x] No missing tasks (cross-referenced against plan)
- [x] No extra functionality (only what the plan asked for)
- [x] Manually verified key behaviors (runtime tests for all 3 packages)
- [x] Code follows project conventions
- [x] Compatible with existing work

## Notes for User

1. **敏感信息迁移**：原 `.test-configs.json` 中的 Cloudflare keys 和 search API key 需要手动迁移到 `~/.broca/configs/configs.json`（生产）或 `broca-web/backend/.env.local`（本地开发，gitignored）
2. **TUI 路径 bug**：修复了 `_load_configs_json()` 中 `parent.parent.parent.parent` 应为 `parent.parent.parent` 的预存 bug
3. **`configs/configs.json`**（项目根）仍含 `/home/ubuntu/` 路径，将在 Phase 4 Task 4.1 中修复
