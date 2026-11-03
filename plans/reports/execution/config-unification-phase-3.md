# Phase 3 执行报告：环境隔离与部署

## 状态: ✅ 完成

## Task 3.1: 环境 Profile 补充安全策略 ✅

**改动文件**:
| 文件 | 改动 |
|------|------|
| `broca-web/backend/app/core/config.py` | 新增 `env` 字段 + `cors_allow_origins` 字段 + `_enforce_production_safety` validator |
| `broca/configs.py` | 修复 `get_configs()` 提前 return 绕过 log_level 检查的 bug + 生产环境 log_level 强制降级 |
| `broca-web/backend/.env.production.example` | **新建**（生产环境配置模板） |
| `broca-web/backend/.env` | 添加 `BROCA_ENV=dev` |
| `broca-web/backend/.env.example` | 添加 BROCA_ENV 说明 + 端口优先级注释 |

**安全策略实现**:
- `BROCA_ENV=production` 时：
  - JWT_SECRET 必须显式设置（不能为空或默认 dev 值）
  - CORS_ALLOW_ORIGINS 不允许 `*`
  - log_level 强制从 DEBUG 降为 INFO
- `BROCA_ENV=dev`（默认）时：无限制，方便开发调试

**额外修复**:
- `get_configs()` 原代码中 BROCA_CONFIG 路径直接 `return` 导致跳过 log_level 检查 → 改为 `if config is None` 模式，所有路径汇聚到末尾统一检查
- `socketio_port` 和 `env` 字段的 `validation_alias` 不识别字段名 → 改为 `AliasChoices` 包含字段名本身（`populate_by_name` 在 pydantic 2.12 中已弃用）

## Task 3.2: Worktree 开发隔离方案 ✅

**改动文件**:
| 文件 | 改动 |
|------|------|
| `docs/dev-worktree-setup.md` | **新建**（3 步指南 + 端口表 + FAQ） |
| `broca-web/backend/configs.dev.json` | **新建**（Task 2.4 已创建） |
| `broca-web/frontend/.env.example` | 已有 worktree 端口示例注释（Task 2.3） |

**文档内容**:
- 3 步操作（创建 worktree → 配置启动后端 → 配置启动前端）
- 端口选择规则（9001 + index / 6666 + index）
- 隔离保证表（生产 vs worktree）
- 常见问题 FAQ

## Task 3.3: CI/生产环境配置 ✅

**改动文件**:
| 文件 | 改动 |
|------|------|
| `scripts/install.sh` | supervisor environment 补充 `BROCA_ENV=production` + `PORT` + `BROCA_SOCKETIO_PORT` |
| `docs/ci-environment-variables.md` | **新建**（CI 必需变量表 + Docker 示例 + 生产 configs.json 模板） |

**改动详情**:
- install.sh 默认端口已正确（9001/6666），nginx proxy_pass 使用变量
- supervisor 配置新增 `BROCA_ENV=production` 确保生产安全策略生效
- supervisor 配置新增 `PORT` 和 `BROCA_SOCKETIO_PORT` 显式传递端口

## 自检结果

```
✅ Test 1: Production blocks wildcard CORS
✅ Test 2: Production with valid config works
✅ Test 3: Dev mode (port=9002, socketio=6666)
✅ Test 4: socketio_port init kwarg works
✅ Test 5: env init kwarg works
✅ Test 6: get_configs (api=http://localhost:9001, socket=http://localhost:6666)
```
