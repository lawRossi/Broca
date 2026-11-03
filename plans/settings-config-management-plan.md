# Settings 页面扩展：支持 configs.json 与 tool_permission_config.json 编辑

## 概述
- **目标**：将 `broca-web/frontend/src/views/Settings.vue` 从仅支持 `~/.broca/configs/llm_config.json` 编辑，扩展为可同时编辑 `~/.broca/configs/configs.json`（基础配置）与 `~/.broca/configs/tool_permission_config.json`（工具权限）的配置管理页面。
- **背景**：
  - 当前 `Settings.vue`（1174 行）整页只用于 LLM 配置编辑，通过 `frontend/src/api/config.ts` 的 `getLLMConfig/saveLLMConfig` 调用后端 `GET/PUT /api/config/llm`。
  - 后端 `broca-web/backend/app/api/config.py` 目前仅有 LLM 相关 4 个端点，无 general / tool-permission 端点。
  - `~/.broca/configs/configs.json` 当前内容为损坏 JSON（缺逗号、多余逗号），无法被 `json.load` 解析，需要编辑入口来修复。
  - `~/.broca/configs/tool_permission_config.json` 结构为 `{ _description, _permission_values, tools: {工具名: allow/ask/forbidden} }`，其中 `_description` / `_permission_values` 为说明性元数据。
- **约束条件**：
  - 与用户确认的三个决策（见「总体方案」）必须遵守。
  - 不改变 `broca` 核心包对配置文件的读取逻辑（`broca/configs.py`、`broca/tools/tool_permission_manager.py` 不动）。
  - 保持现有 LLM 编辑功能不回归（自动保存、脏状态、校验、离开保护、多模态等现有行为）。

## 相关材料
- `broca-web/backend/app/api/config.py` — 现有 LLM 端点、读取/校验/备份原子写模式（`_write_llm_config` 的 `.bak` 备份 + `.tmp` + `os.replace`）
- `broca-web/backend/app/schemas/schemas.py` — `LLMConfigUpdateRequest {config: dict}`、`ApiResponse` 定义
- `broca-web/backend/app/api/__init__.py` — `config_router` 以 `/config` 前缀挂载
- `broca-web/tests/integration/test_api_config.py` — 现有 LLM 端点集成测试写法（monkeypatch 路径常量、async_client、auth_headers）
- `broca-web/frontend/src/api/config.ts` — 前端 API 层（类型定义 + 方法）
- `broca-web/frontend/src/views/Settings.vue` — 待改造页面（完整 1174 行）
- `broca-web/frontend/src/utils/request.ts` — axios 实例；HTTP 错误统一弹 `ElMessage`（404/500 有 detail 提取逻辑）
- `broca/configs.py` — `get_configs()` 读取 configs.json 的优先级：`BROCA_CONFIG` env > `~/.broca/configs.json` > 项目默认 `configs/configs.json`；`BrocaConfig` 已知字段 `database_dir/log_file/log_level/llm_config_file`
- `broca-tui/broca_tui/config.py` — `socket_server_url`（默认 http://localhost:6868）、`api_server_url`（默认 http://localhost:9000）的消费方，从 `~/.broca/configs/configs.json` 读取
- `broca/tools/tool_permission_manager.py` — `VALID_PERMISSIONS = {"allow", "ask", "forbidden"}`；读取顺序 workspace `.broca/` > `~/.broca/configs/` > 默认 allow
- `~/.broca/configs/configs.json`（待修复的损坏文件）、`~/.broca/configs/tool_permission_config.json`（实际内容样例）、`~/.broca/configs/llm_config.json`（已支持）
- `broca-web/frontend/package.json` — `build:dev` = `vue-tsc --noEmit && vite build --mode development`（类型检查 + 构建验证命令）

## 总体方案
1. **页面布局（已确认）**：`Settings.vue` 顶部加 `el-tabs`，三个标签页：『LLM 配置』『基础配置』『工具权限』。现有 LLM 的 script 逻辑保留不动，仅重构 template（标题栏简化 + 原头部操作按钮/状态行移入 tab1 内容区顶部工具栏）；新增两个自包含子组件 `<GeneralConfigPanel>`、`<ToolPermissionPanel>`。
2. **configs.json（已确认：仅已知字段表单）**：表单编辑 6 个已知字段 `database_dir`、`log_file`、`log_level`（下拉 DEBUG/INFO/WARNING/ERROR/CRITICAL）、`llm_config_file`、`socket_server_url`、`api_server_url`；保存时只写回这些已知字段（未知字段丢弃——用户已接受此风险）。
3. **tool_permission_config.json（已确认：表格 + 仅现有 keys）**：表格展示配置文件中原有的 `tools` 项（工具名 + 权限下拉 allow/ask/forbidden），支持删除条目与手动添加新工具名；`_description`/`_permission_values` 元数据加载时保留、原样写回，界面只读展示读取优先级说明。

## 后端 API 设计
在 `broca-web/backend/app/api/config.py` 新增：
- `GET /api/config/general`：读取 base config 文件；文件不存在 → 404；JSON 损坏 → 500（detail 说明）；成功 → 返回文件完整 dict。
- `PUT /api/config/general`：校验（必须 object；已知字段若存在必须为 string；`log_level` 若存在必须 ∈ {DEBUG, INFO, WARNING, ERROR, CRITICAL}）；未知字段记录 warning 并丢弃；备份（`.bak`）+ 原子写。
- `GET /api/config/tool-permission`：读取工具权限文件；404/500/200 同上的语义。
- `PUT /api/config/tool-permission`：校验（object；`tools` 必须为 dict；每个权限值必须 ∈ {allow, ask, forbidden}；`_description` 若存在必须 string；`_permission_values` 若存在必须 object 且值为 string）；备份 + 原子写；保留请求中全部字段（含元数据）。

路径解析：
- general：`BROCA_CONFIG` 环境变量 > `~/.broca/configs/configs.json`（TUI/运行时新路径，优先于 legacy）> `~/.broca/configs.json`（legacy）> 项目默认 `configs/configs.json`；写回目标 = 解析出的路径（不存在时也用它作为创建路径）。
- tool-permission：固定 `~/.broca/configs/tool_permission_config.json`（与 `ToolPermissionManager` 全局路径一致）。

## 执行计划

### Phase 1: 后端 API + 前端页面扩展（单阶段）
**目标**：完成后端 4 个新端点、前端 API 层、Settings 页面 tabs 化与两个新编辑面板，并全部通过验证。

**阶段验收标准**：
- [ ] 后端新增 4 个端点通过集成测试（success / 404 / 500 / 校验失败 / 备份 各类用例）
- [ ] 前端 `vue-tsc --noEmit` 类型检查通过，`npm run build:dev` 构建成功
- [ ] `/settings` 页面出现三个标签页，LLM 配置功能无回归，基础配置与工具权限可加载、编辑、保存、重置
- [ ] 损坏的 `~/.broca/configs/configs.json` 可在页面中修复（保存后恢复为合法 JSON）

#### Task 1.1: 后端新增 general / tool-permission 配置端点
- **目标**：在 `broca-web/backend/app/api/config.py` 实现读取/校验/原子写入 general 与 tool-permission 配置文件的能力。
- **步骤**：
  1. 在 `app/schemas/schemas.py` 新增 `GeneralConfigUpdateRequest(BaseModel)` 与 `ToolPermissionUpdateRequest(BaseModel)`，均为 `config: dict[str, Any]`（参照 `LLMConfigUpdateRequest`）。
  2. 在 `app/api/config.py` 定义常量：`KNOWN_GENERAL_CONFIG_FIELDS = ("database_dir", "log_file", "log_level", "llm_config_file", "socket_server_url", "api_server_url")`、`VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}`、`VALID_PERMISSIONS = {"allow", "ask", "forbidden"}`、模块级路径常量 `GENERAL_CONFIG_PATH` 与 `TOOL_PERMISSION_PATH`（计算方式见「总体方案-路径解析」，可测试 monkeypatch）。
  3. 抽取通用函数 `_read_json_config(path)`（不存在→404、损坏→500、非 object→500）与 `_atomic_write_json(path, config)`（备份 `.bak` + `.tmp` + `os.replace`，父目录 mkdir），并让现有 `_read_llm_config` / `_write_llm_config` 复用（保持行为不变）。
  4. 实现 `_validate_general_config(config)`：必须 object；已知字段若存在必须 string；`log_level` 必须 ∈ `VALID_LOG_LEVELS`；未知字段 `logger.warning` 并在写回时丢弃（仅保留已知字段，保持 KNOWN 顺序）。
  5. 实现 `_validate_tool_permission_config(config)`：必须 object；`tools` 必须为 dict（可为空）且每个值 ∈ `VALID_PERMISSIONS`；`_description` 若存在必须 string；`_permission_values` 若存在必须 object 且值均为 string。
  6. 新增 4 个路由：`GET/PUT /general`、`GET/PUT /tool-permission`，置于现有 LLM 路由之后（同 `router`）；错误处理与返回格式与现有端点一致（`ApiResponse.success`、HTTPException、logger.exception 包裹）。
- **预期产出**：`app/api/config.py`、`app/schemas/schemas.py` 修改完成，4 个新端点可调用。
- **验收标准**：
  - [ ] `GET /api/config/general` 在文件存在且合法 JSON 时返回 200 + 文件内容；不存在时 404；损坏 JSON 时 500 且 detail 含解析错误信息。
  - [ ] `PUT /api/config/general` 写入后文件重新加载为合法 JSON，且仅包含 KNOWN 字段（未知字段被丢弃、顺序保持）；旧文件备份为 `configs.json.bak`。
  - [ ] `PUT /api/config/general` 传入非法 `log_level` 时返回 400；传入非 object 时返回 400。
  - [ ] `GET /api/config/tool-permission` 在文件存在/不存在/损坏时分别返回 200/404/500；`PUT` 校验非法权限值返回 400，合法写入后 `_description`/`_permission_values` 原样保留，旧文件备份为 `.bak`。

#### Task 1.2: 后端集成测试扩展
- **目标**：为新增端点补充集成测试，确保行为可回归验证。
- **步骤**：
  1. 阅读 `broca-web/tests/integration/test_api_config.py` 现有 LLM 测试的写法（`async_client`、`auth_headers`、monkeypatch 路径常量到 `tmp_path`）。
  2. 新增测试类/函数覆盖 general 端点：get success（含完整 dict 返回）、get 404、get 500（损坏 JSON）、put success（写入正确 + `.bak` 存在 + 未知字段丢弃）、put 非法 log_level → 400、put 非 object → 400。
  3. 新增 tool-permission 测试：get success、get 404、get 500、put success（元数据保留）、put 非法权限值 → 400、put tools 非 object → 400。
  4. 运行 `cd broca-web/backend && pytest tests/integration/test_api_config.py -q` 确保全部通过；同时运行 `pytest tests/unit -q` 与 `pytest tests/integration -q` 确认无回归（若集成套件耗时过长，至少跑 `test_api_config.py` 与 `test_api_auth.py` 冒烟）。
- **预期产出**：`broca-web/tests/integration/test_api_config.py` 扩展完成，新端点的测试全部通过。
- **验收标准**：
  - [ ] 所有新增测试用例编写完成且断言覆盖 200/404/500/400 与备份文件、字段丢弃、元数据保留行为。
  - [ ] `pytest tests/integration/test_api_config.py -q` 全绿；现有 LLM 测试未因重构（函数抽取）而失败。

#### Task 1.3: 前端 API 层扩展
- **目标**：在 `frontend/src/api/config.ts` 增加 general / tool-permission 的类型与方法。
- **步骤**：
  1. 新增接口：
     ```ts
     export interface GeneralConfig {
       database_dir?: string
       log_file?: string
       log_level?: string
       llm_config_file?: string
       socket_server_url?: string
       api_server_url?: string
     }
     export interface ToolPermissionConfig {
       _description?: string
       _permission_values?: Record<string, string>
       tools: Record<string, string>
     }
     export const PERMISSION_VALUES = ['allow', 'ask', 'forbidden'] as const
     export type PermissionValue = (typeof PERMISSION_VALUES)[number]
     export const LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const
     ```
  2. 在 `configApi` 中新增：`getGeneralConfig(): Promise<GeneralConfig>`（GET `/config/general`）、`saveGeneralConfig(config: GeneralConfig)`（PUT `/config/general`，body `{ config }`）、`getToolPermissionConfig(): Promise<ToolPermissionConfig>`（GET `/config/tool-permission`）、`saveToolPermissionConfig(config: ToolPermissionConfig)`（PUT `/config/tool-permission`，body `{ config }`）。
  3. 常量导出供组件使用（`PERMISSION_VALUES`、`LOG_LEVELS`）。
- **预期产出**：`frontend/src/api/config.ts` 扩展完成。
- **验收标准**：
  - [ ] 类型定义与 4 个方法与现有 `request` 封装风格一致（成功返回 `data.data`）。
  - [ ] `npm run build:dev` 之前 `vue-tsc --noEmit` 对本文件无类型错误。

#### Task 1.4: Settings.vue 改造为 Tabs 容器
- **目标**：将 `Settings.vue` 改成三标签页容器，保留全部现有 LLM 编辑逻辑。
- **步骤**：
  1. script 部分：`<script setup>` 保留现有全部 LLM 逻辑不动；新增 `activeTab = ref('llm')`；新增 `generalDirty` / `toolDirty` 两个 ref（由子组件 `dirty-change` 事件更新）；新增 `generalPanelRef` / `toolPanelRef`（`ref<InstanceType<typeof GeneralConfigPanel>>` 等）。
  2. 导入 `GeneralConfigPanel`、`ToolPermissionPanel`（`@/views/settings/...`，见 Task 1.5/1.6 命名）。
  3. template 重构：
     - 顶部标题栏简化为「设置」标题（保留 `Setting` 图标），并把现有头部操作按钮行（添加提供商 / 重置 / 保存、状态文案、统计、`saving`/`saveFailed`/`autoSaveBlocked`/`lastSavedAt`/`dirty` 指示）移到 tab1 内容区的顶部工具栏，作为 LLM 面板的专属工具栏。
     - 主内容区包进 `<el-tabs v-model="activeTab">`：
       - `<el-tab-pane label="LLM 配置" name="llm">`：现有主内容区（加载/空状态/提供商 collapse/各对话框）与原头部按钮行组合的工具栏。
       - `<el-tab-pane label="基础配置" name="general">`：`<GeneralConfigPanel ref="generalPanelRef" @dirty-change="generalDirty = $event" />`。
       - `<el-tab-pane label="工具权限" name="tool-permission">`：`<ToolPermissionPanel ref="toolPanelRef" @dirty-change="toolDirty = $event" />`。
  4. 离开保护改造：`onBeforeRouteLeave` 中除现有 LLM 逻辑外，若 `generalDirty` 或 `toolDirty` 为 true，先调用对应面板 `saveNow()`（暴露方法）；保存失败或校验不过时询问「放弃修改并离开 / 留在本页」。`handleBeforeUnload` 同理聚合三个 dirty（任一 dirty 即阻止）。
  5. 删除不再需要的头部按钮逻辑时保持各函数引用完整（按钮只是移动到 tab1 工具栏，函数不变）。
- **预期产出**：`frontend/src/views/Settings.vue` 改造完成。
- **验收标准**：
  - [ ] 页面顶部出现三个标签页，默认选中「LLM 配置」；切换标签页时各面板独立加载、互不重置。
  - [ ] LLM 配置功能行为与改造前一致（自动保存、校验、多模态、添加/删除提供商与模型、重置）。
  - [ ] 任一面板有未保存修改时，离开路由会先尝试自动保存，保存失败则弹确认框。
  - [ ] `vue-tsc --noEmit` 通过（含子组件引用与事件类型）。

#### Task 1.5: 新建 GeneralConfigPanel.vue（基础配置表单）
- **目标**：实现 configs.json 的「仅已知字段」表单编辑面板。
- **步骤**：
  1. 新建 `frontend/src/views/settings/GeneralConfigPanel.vue`，`<script setup lang="ts">` 风格与现有页面一致。
  2. 状态与数据流（自包含，模式参照 Settings.vue 现有自动保存实现）：
     - `loading` / `saving` / `config: GeneralConfig` / `initialJson` / `dirty`（computed JSON 比较）/
     - `damaged`（加载时 404 或 500 → 置 true，表单用默认值、显示警示条「文件缺失或损坏，填写并保存将重建/修复（旧文件自动备份为 .bak）」）
     - `lastSavedAt` / `saveFailed` / `autoSaveBlocked`（语义与 Settings.vue 一致）
     - `AUTO_SAVE_DELAY = 1200` 防抖自动保存 + `watch(config, deep)`；`mutatedDuringSave` 逻辑同现有。
  3. 表单 UI：`el-form` 六行：
     - `database_dir`（el-input，placeholder 如 `~/.broca/data`）
     - `log_file`（el-input，如 `~/.broca/logs/agent.log`）
     - `log_level`（el-select，选项 `LOG_LEVELS`，默认 INFO）
     - `llm_config_file`（el-input，如 `~/.broca/configs/llm_config.json`）
     - `socket_server_url`（el-input，placeholder `http://localhost:6868`）
     - `api_server_url`（el-input，placeholder `http://localhost:9000`）
     每个字段下加 12px 灰字说明（消费方：数据库目录、日志、LLM 配置、TUI SocketIO/API 地址）。
  4. 工具栏：保存 / 重置按钮 + 状态文案（保存中/失败/校验未通过/已保存/即将自动保存）+ 当前文件路径显示（从 GET 响应或默认路径计算，展示只读文本）。
  5. 校验 `validateBeforeSave`：`log_level` 必须 ∈ `LOG_LEVELS`（select 已保证）；其余字段允许为空。
  6. 对外接口：`defineEmits(['dirty-change'])`（dirty 变化时 emit）；`defineExpose({ saveNow, reset })`：`saveNow(): Promise<boolean>` 立即校验+保存并返回是否成功；`reset()` 重新加载。
  7. 警示文案：保存将把文件重写为仅含上述 6 个字段的 JSON，「文件中未被识别的字段将被移除」。
- **预期产出**：`frontend/src/views/settings/GeneralConfigPanel.vue` 完成。
- **验收标准**：
  - [ ] 加载成功时表单显示 6 个字段的当前值；dirty 变更触发自动保存（1.2s 防抖）并在成功后更新 basetime、toast 提示。
  - [ ] 文件缺失/损坏时显示警示条，表单仍可编辑；保存后文件成为合法 JSON（含 6 字段），损坏旧文件备份为 `.bak`。
  - [ ] `saveNow()` 返回保存是否成功；`reset()` 重新加载并清除脏状态；dirty 变化通过事件上报父组件。
  - [ ] `vue-tsc --noEmit` 通过。

#### Task 1.6: 新建 ToolPermissionPanel.vue（工具权限表格）
- **目标**：实现 tool_permission_config.json 的表格编辑面板（仅现有 keys + 手动添加）。
- **步骤**：
  1. 新建 `frontend/src/views/settings/ToolPermissionPanel.vue`，`<script setup lang="ts">` 风格一致。
  2. 状态与数据流：与 GeneralConfigPanel 相同的自包含模式（loading/saving/config/initialJson/dirty/damaged/自动保存/状态文案/`dirty-change` emit/`defineExpose({ saveNow, reset })`）。
  3. 加载 `getToolPermissionConfig()`：404 → `tools: {}` 并 `damaged=true`（警示「文件缺失，保存将创建」）；500（损坏 JSON）→ 同样 `damaged=true`；成功 → 完整保留 `_description` / `_permission_values` 于 `config` 对象中。
  4. UI：
     - 顶部只读说明块：展示读取顺序（① workspace/.broca/ → ② ~/.broca/configs/ → ③ 全部默认 allow）与权限值含义（allow/ask/forbidden，优先取文件内 `_description`/`_permission_values`，缺失时用内置文案）。
     - `el-table`：列 = 工具名（只读文本）/ 权限（`el-select` 选项 `PERMISSION_VALUES` / 操作（删除按钮））；空状态提示「暂无工具配置，点击添加」。
     - 「添加工具」按钮 → `el-dialog`（工具名输入 + 权限默认 allow；空名/重名校验）。
     - 每行权限变化、添加、删除均写入 config（dirty 自动触发保存）。
  5. 校验 `validateBeforeSave`：工具名非空且唯一；权限值 ∈ `PERMISSION_VALUES`（select 保证）；`tools` 必须为 object。
  6. 保存 `saveToolPermissionConfig(config)`：提交完整对象（`_description`/`_permission_values` 原样 + 修改后 `tools`），成功后 toast「工具权限已保存（新 Session 生效）」。
- **预期产出**：`frontend/src/views/settings/ToolPermissionPanel.vue` 完成。
- **验收标准**：
  - [ ] 表格展示当前文件中全部 `tools` 项；修改权限/删除/添加工具名均正确反映在保存后的文件里。
  - [ ] 保存后文件的 `_description`/`_permission_values` 与加载时一致（原样保留）。
  - [ ] 文件缺失时创建保存成功；损坏 JSON 时先备份后修复。
  - [ ] 自动保存、`saveNow()`、`reset()`、`dirty-change` 行为与 1.5 验收标准 1/3 一致；`vue-tsc --noEmit` 通过。

#### Task 1.7: 前后端验证与冒烟
- **目标**：全链路验证新功能可用、无回归。
- **步骤**：
  1. 后端：`cd broca-web/backend && pytest tests/integration/test_api_config.py -q`（新增用例全绿）+ `pytest tests/unit -q` 无回归。
  2. 前端：`cd broca-web/frontend && npm run build:dev`（`vue-tsc --noEmit` + vite build）成功；`npm run format` 后 `npm run format:check && npm run lint` 通过（或按仓库现状只做格式与 lint 检查）。
  3. 手动冒烟（可选，按环境情况）：启动后端与前端 dev server，浏览器打开 `/settings`：
     - 三标签页切换正常；LLM 配置功能可用。
     - 基础配置页能加载（当前文件损坏 → 显示警示条），修改 `log_level` 后保存，`~/.broca/configs/configs.json` 修复为合法 JSON 且含 6 个已知字段；`.bak` 存在。
     - 工具权限页表格展示现有 tools，修改一项权限保存，文件内容正确且元数据保留。
- **预期产出**：全部验证通过的执行记录。
- **验收标准**：
  - [ ] `pytest tests/integration/test_api_config.py -q` 全绿，`tests/unit` 无回归。
  - [ ] `npm run build:dev` 成功（类型检查 + 构建通过）。
  - [ ] 冒烟记录（或说明未执行的原因）确认三标签页、修复损坏 configs.json、工具权限保存三个场景可用。

## 风险与应对
| 风险 | 影响 | 应对策略 |
|------|------|----------|
| Settings.vue template 重构破坏现有 LLM 编辑功能 | 高 | script 逻辑零改动；按钮行仅平移；Task 1.7 冒烟回归；`vue-tsc` + 构建拦截类型错误 |
| 通用函数抽取（读取/原子写）引入 LLM 端点行为变化 | 中 | 抽取后保持原函数签名与行为；Task 1.2 运行既有 LLM 测试确认无回归 |
| 写回 configs.json 丢弃未知字段（用户已接受）影响其他组件 | 低-中 | 表单页与保存接口都只处理 KNOWN 字段；面板 UI 明示「未识别字段将被移除」；后端对未知字段仅 warning 不报错 |
| 当前 configs.json 已损坏，GET 必 500 | 中 | 前端 `damaged` 状态：警示 + 允许编辑保存（PUT 备份后重写修复），形成自愈路径 |
| 自动保存 + 离开保护在三个面板间协调复杂 | 中 | 子组件统一模式（`dirty-change` emit + `saveNow` expose）；父组件聚合 dirty，先自动保存再询问；避免重复弹窗 |
| BROCA_CONFIG 环境变量指向不可写路径时保存失败 | 低 | 保存失败显示错误提示；后端在目标路径不存在时自动创建父目录 |

## 未解决的问题
- 无（三个关键决策已与用户确认；执行中若发现 BROWCA_CONFIG 实际运行路径与预期不一致，以运行时 `os.getenv("BROCA_CONFIG")` 为准并记录）。
