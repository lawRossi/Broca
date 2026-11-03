# broca-web LLM 配置管理功能 — Phase 2: 前端 LLM 配置管理页面 — Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | plans/llm-config-management-plan.md |
| Phase | Phase 2: 前端 LLM 配置管理页面 |
| Status | ✅ Pass |

## Plan Anchor Confirmation

- [x] 执行前重读计划 Phase 2 章节
- [x] 确认每个任务的验收标准（Task 2.1~2.4）

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| Task 2.1: API 封装与类型定义 | ✅ | ① vue-tsc 类型编译通过 | `vue-tsc --noEmit` 通过 | 无 |
| | | ② 方法路径与后端一致 | `/config/llm`（request baseURL 已含 `/api`） | 无 |
| Task 2.2: Settings.vue 页面 | ✅ | ① 正确渲染真实配置 | 浏览器实测：6 提供商（deepseek 4 / Stepfun 1 / nvidia 5 / z-ai 1 / openrouter 3 / omlx 1）共 15 模型，与 llm_config.json 完全一致 | 无 |
| | | ② 增删改保存后持久化 | 浏览器实测：添加模型→保存→文件出现新模型；删除模型→保存→文件移除；.bak 均正确生成 | 无 |
| | | ③ api_key 掩码可切换 | 默认 `••••` 掩码，点击眼睛图标显示明文（实测切出 sk-e208...） | 无 |
| | | ④ 非法输入被拦截 | 实测：重复 provider id →「已存在」警告；空模型别名 →「不能为空」警告 | 无 |
| Task 2.3: 路由与导航入口 | ✅ | ① 未登录跳 /auth，登录后可进入 | 沿用现有 requiresAuth 守卫（与 /jobs 等同机制）；浏览器实测 localhost 自动登录后正常进入 /settings | 无 |
| | | ② Home 卡片可进入 /settings | Home.vue 新增「LLM 配置」卡片，grid 调整为 sm:grid-cols-3 lg:grid-cols-5 | 无 |
| Task 2.4: 前端质量验证 | ✅ | ① pnpm lint 0 error | 0 errors, 5 warnings（均为既存 ChatMessageItem/ChatTurnCard 的 v-html 提示，与本次无关） | 无 |
| | | ② pnpm build:dev 成功 | vue-tsc + vite build 成功（chunk 体积警告为既存主包问题） | 无 |

## Deviations

1. **联调环境（非代码偏差）**：vite 代理硬编码指向 `127.0.0.1:9000`（用户真实后端占用中，不可动）。联调时以 `VITE_API_BASE_URL=http://127.0.0.1:18765/api` 启动 dev server 直连测试后端（`BROCA_LLM_CONFIG` 指向临时配置副本），未修改任何项目文件；测试后已停止全部测试进程。
2. **审查报告遗留项落实**：添加模型采用 el-dialog 小对话框（与添加提供商一致）。
3. **观察项（非缺陷）**：el-input-number 浮点步进存在精度显示（如 0.3499999940395355），为 Element Plus 组件固有行为，存储值正确（0.35），不影响功能。

## Quality Checklist

- [x] 所有 Phase 级 AC 满足
- [x] 所有 Task 级 AC 满足
- [x] 无遗漏任务（Task 2.1~2.4 均完成）
- [x] 无额外功能（未做连通性测试、未做 JSON 双模式编辑）
- [x] 关键行为已手动验证（浏览器端到端：渲染/掩码/增删改/保存/校验/脏标记）
- [x] 代码遵循项目规范（script setup + TS、Element Plus、Tailwind、request.ts 封装）
- [x] 与既有工作兼容（仅新增文件与追加式修改：config.ts 追加、router 追加路由、Home.vue 追加卡片）

## Evidence

- 截图：`plans/reports/execution/assets/llm-config-settings-page.png`（设置页真实数据渲染）
- 浏览器实测流程：打开 /settings → 自动 local-login → 渲染 6 提供商 15 模型 → api_key 明文切换 → 添加模型 web-e2e-test（temperature 0.35）→ 脏标记出现 → 保存 → 文件持久化 + .bak 生成 → 删除该模型 → 保存 → 文件复原（15 模型）→ 重复 ID/空别名被拦截
- 测试配置副本 `/tmp/llm_cfg_test/`，用户真实配置 `~/.broca/configs/llm_config.json` 未被触碰
