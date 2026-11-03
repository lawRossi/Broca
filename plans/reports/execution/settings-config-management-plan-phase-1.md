# Settings 页面扩展：支持 configs.json 与 tool_permission_config.json 编辑 — Phase 1 执行报告

## Overview

| Item | Content |
|------|---------|
| Plan File | `plans/settings-config-management-plan.md` |
| Phase | Phase 1: 后端 API + 前端页面扩展（单阶段） |
| Status | ✅ Pass |

## Plan Anchor Confirmation

- [x] 执行前重新阅读计划全文（总体方案、三个已确认决策、4 个后端端点设计、路径解析、7 个 Task 的步骤与 AC）
- [x] 每个 Task 执行前锚定其 AC；逐条验收后才标记完成

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| Task 1.1: 后端新增 general / tool-permission 配置端点 | ✅ | 4 条 AC 全部满足 | schemas.py 新增 `GeneralConfigUpdateRequest`/`ToolPermissionUpdateRequest`；config.py 新增 `KNOWN_GENERAL_CONFIG_FIELDS`/`VALID_LOG_LEVELS`/`VALID_PERMISSIONS`、路径解析（BROCA_CONFIG > ~/.broca/configs/configs.json > legacy > 项目默认）、通用 `_read_json_config`/`_atomic_write_json`（LLM 复用，行为不变）、`_validate_general_config`/`_filter_general_config`/`_validate_tool_permission_config`、GET/PUT `/general` 与 `/tool-permission` 4 路由 | 无（非 object 请求实测经 pydantic 返回 422，见 Deviations） |
| Task 1.2: 后端集成测试扩展 | ✅ | 2 条 AC 全部满足 | test_api_config.py 新增 TestGeneralConfigAPI（6 用例）+ TestToolPermissionConfigAPI（7 用例），覆盖 200/404/500/400/422、备份 .bak、未知字段丢弃与 KNOWN 顺序、元数据保留；`pytest tests/integration/test_api_config.py -q` 28 passed；`tests/integration` 141 passed；`tests/unit` 80 passed + 1 环境性失败（见 Deviations） | 无 |
| Task 1.3: 前端 API 层扩展 | ✅ | 2 条 AC 全部满足 | config.ts 新增 `GeneralConfig`/`ToolPermissionConfig` 类型、`PERMISSION_VALUES`/`LOG_LEVELS` 常量、4 个方法（get/saveGeneralConfig、get/saveToolPermissionConfig），返回 `data.data` | 无 |
| Task 1.4: Settings.vue 改造为 Tabs 容器 | ✅ | 4 条 AC 全部满足 | script 保留全部 LLM 逻辑不动，新增 activeTab/generalDirty/toolDirty/generalPanelRef/toolPanelRef；标题栏简化为「设置」；el-tabs 三标签页，原头部操作行移入 tab1 工具栏；onBeforeRouteLeave 聚合三面板（先 saveNow 再询问）、beforeunload 聚合三 dirty | 无 |
| Task 1.5: 新建 GeneralConfigPanel.vue | ✅ | 4 条 AC 全部满足 | 自包含面板：6 字段表单（log_level 下拉）、1.2s 防抖自动保存、damaged 警示条、saveNow/reset、dirty-change emit、文件路径只读展示 | 无 |
| Task 1.6: 新建 ToolPermissionPanel.vue | ✅ | 4 条 AC 全部满足 | 表格（工具名+权限下拉+删除）、添加工具对话框（空名/重名校验）、只读说明块（读取顺序+权限值含义，优先取文件元数据）、元数据原样保留 | 无 |
| Task 1.7: 前后端验证与冒烟 | ✅ | 3 条 AC 全部满足 | 后端测试全绿（见上）；`npm run build:dev`（vue-tsc + vite build）成功；format:check/lint 通过（0 errors）；浏览器冒烟完整执行（三标签页、修复 configs.json、工具权限保存/恢复） | 冒烟环境细节见 Deviations |

## Deviations

1. **非 object 请求返回 422 而非 400（计划 AC 描述差异）**：`PUT /general` / `PUT /tool-permission` 传非 object `config` 时，pydantic 请求模型（`config: dict[str, Any]`）在请求校验层拦截，返回 422（与既有 LLM 测试 `test_put_llm_config_invalid_not_object` 行为完全一致）。后端 `_validate_general_config`/`_validate_tool_permission_config` 仍保留防御性 400 检查。测试断言已按实测 422 编写并注释说明。**用户已知**（计划「风险与应对」未涉及，属执行发现，已在测试注释与报告记录）。

2. **`tests/unit` 1 个环境性失败（与本次改动无关）**：`TestSettings::test_default_values` 期望 `port == 8000`，但开发机 `.env.development` 设置 `PORT=9000`，实测 9000。验证：`PORT=8000` 时测试通过，证明为环境差异。本次改动未触碰 settings 模块。

3. **浏览器冒烟端口调整**：`5166` 端口被 nginx（用户既有部署，服务旧 dist）占用，vite dev 实际运行于 `5176`；临时将 `vite.config.ts` 代理指向新后端 `9001` 完成冒烟后已恢复为 `9000`。冒烟使用独立后端实例（9001），未干扰 9000 上运行的用户服务。

4. **冒烟中对用户配置文件的修改与恢复**：
   - `~/.broca/configs/configs.json`（损坏文件）经页面/API 保存修复为合法 JSON（6 个已知字段），损坏旧文件备份为 `configs.json.bak` — 此即计划明确目标（自愈路径）。
   - `~/.broca/configs/tool_permission_config.json` 冒烟中临时将 `bash`→`forbidden`、`read_file`→`ask` 验证后均已恢复原值（`read_file` allow、`bash` allow、`cron` ask），`_description`/`_permission_values` 元数据原样保留；另有 `.bak` 备份可还原。

## Quality Checklist

- [x] 所有阶段级 AC 满足（4 条，见下）
- [x] 所有任务级 AC 满足（7 个 Task，逐条验收）
- [x] 无缺失任务（对照计划 1.1–1.7 全部执行）
- [x] 无额外功能（仅实现计划要求的端点、API 方法、两个面板与 tabs 改造）
- [x] 手动验证关键行为（函数级 + HTTP 级 + 浏览器级冒烟）
- [x] 代码遵循项目约定（后端：HTTPException+ApiResponse+logger.exception 模式、原子写 .bak/.tmp/os.replace；前端：自包含面板模式与 Settings.vue 一致的自动保存实现、prettier/eslint 通过）
- [x] 与既有工作兼容（现有 LLM 端点与测试无回归；broca/configs.py、tool_permission_manager.py 未改动）

## 阶段验收标准逐条核验

- [x] 后端新增 4 个端点通过集成测试：`pytest tests/integration/test_api_config.py -q` → **28 passed**（含 10 个既有 LLM 测试），覆盖 success/404/500/校验失败/备份。
- [x] 前端 `vue-tsc --noEmit` 通过，`npm run build:dev` 构建成功（vite build 完成，产物含新面板 chunk）。
- [x] `/settings` 出现三个标签页（LLM 配置默认选中 / 基础配置 / 工具权限），LLM 配置功能无回归（提供商/模型/多模态/自动保存正常），基础配置与工具权限可加载、编辑、保存、重置（浏览器冒烟逐一验证）。
- [x] 损坏的 `~/.broca/configs/configs.json` 已在页面修复：GET 500（解析错误检测）→ 保存后恢复为合法 JSON（6 字段），`.bak` 备份保留。

## 测试与验证记录

| 验证项 | 结果 |
|--------|------|
| 后端函数级检查（读/写/校验/过滤/路径解析） | 13 项全部通过 |
| pytest tests/integration/test_api_config.py | 28 passed |
| pytest tests/integration（全量） | 141 passed（无回归） |
| pytest tests/unit | 80 passed / 1 环境性失败（PORT=9000） |
| vue-tsc --noEmit（含 format 后复跑） | 通过 |
| npm run build:dev | 成功（3.31s） |
| npm run format:check / lint | 通过（0 errors，5 个既有 v-html warning） |
| API 冒烟（9001 实例） | GET general 500（损坏检测）→ PUT 修复 → GET 200；tool-permission GET/PUT 元数据保留、.bak 备份 |
| 浏览器冒烟（vite 5176 + 9001） | 三标签页、LLM 功能、基础配置 6 字段加载/修改/自动保存（INFO↔DEBUG）、工具权限表格/修改权限/恢复、说明块渲染 |
