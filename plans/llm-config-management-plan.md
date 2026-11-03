# broca-web LLM 配置管理功能计划

## 概述
- **目标**：为 broca-web 增加 LLM 配置管理能力——后端提供读取/保存完整 LLM 配置（`llm_config.json`）的轻量接口；前端新增「设置」页面，以结构化表单展示并编辑「提供商 → 模型」两级配置，支持新增/删除提供商与模型、API Key 掩码显示、保存（自动备份）。
- **背景**：目前后端仅有两个只读接口（`GET /api/config/llm/providers`、`GET /api/config/llm/models/{provider}`），无法在 Web 端管理配置；运行时实际使用的配置文件为 `~/.broca/configs/llm_config.json`（由 `BROCA_LLM_CONFIG` 环境变量或 `configs.json` 的 `llm_config_file` 决定），格式为 `provider → {base_url, api_key, models: {别名: {model, temperature, max_tokens, extra_body, reasoning_effort, allowed_openai_params, meta: {modality, context_window}}}}`。
- **约束条件**：
  - 用户已确认范围：**仅前端展示 + 编辑现有配置**（不做 LLM 连通性测试），交互采用**结构化表单**。
  - 技术栈不变：后端 FastAPI + `ApiResponse` 统一响应；前端 Vue 3 + TS + Element Plus + Tailwind + Pinia 风格保持一致。
  - 不得破坏现有只读接口及 `broca/llm.py` 对配置文件的消费方式。

## 相关材料
- 后端现有配置接口：`broca-web/backend/app/api/config.py`（`LLM_CONFIG_PATH` 解析逻辑在此，新接口直接复用）
- 路由注册：`broca-web/backend/app/api/__init__.py`（config_router 已挂载在 `/api/config` 前缀下，新接口路径无需再带 `/config`）
- 统一响应模型：`broca-web/backend/app/schemas/schemas.py`（`ApiResponse.success / ApiResponse.error`）
- 配置真实格式样例：`~/.broca/configs/llm_config.json`（provider 下有 `models` 嵌套与 `meta` 字段）；仓库内 `configs/llm_config.json` 为旧版平铺格式，**勿以其为准**
- 配置消费方（只读参考，勿改动）：`broca/llm.py`（`LLMClient` 读取 `provider → models → meta.modality`）
- 后端集成测试参考：`broca-web/tests/integration/test_api_config.py`（mock `LLM_CONFIG_PATH` 与 `builtins.open` 的模式）、`broca-web/tests/conftest.py`（`async_client` / `auth_headers` fixture）
- 前端 API 封装：`broca-web/frontend/src/api/config.ts`、请求封装 `broca-web/frontend/src/utils/request.ts`（响应拦截器自动解包 `data.data`，错误自动 `ElMessage` 提示）
- 路由注册：`broca-web/frontend/src/router/index.ts`（`requiresAuth: true` 模式）
- 导航入口：`broca-web/frontend/src/views/Home.vue`（功能导航卡片 grid，当前 4 个卡片）
- 前端页面编写范式参考：`broca-web/frontend/src/views/Jobs.vue`、`broca-web/frontend/src/components/AgentSidebar.vue`（Element Plus 组件用法）

## 总体方案

1. **后端**（Phase 1）：在现有 `app/api/config.py` 中新增两个接口，复用模块级 `LLM_CONFIG_PATH`：
   - `GET /api/config/llm`：读取完整配置 JSON 并原样返回（含 api_key，本工具为本地/内网使用，且回环请求免鉴权；风险章节有说明）。
   - `PUT /api/config/llm`：接收完整配置对象，做结构校验（顶层为 dict；每个 provider 为 dict 且含 `base_url`/`api_key`/`models`，`models` 为 dict），校验通过后先写备份文件 `llm_config.json.bak`，再以临时文件 + `os.replace` 原子覆盖写回。校验失败返回 400。
   - 在 `schemas.py` 中新增 `LLMConfigUpdateRequest`（`config: dict[str, Any]`）。
2. **前端**（Phase 2）：
   - `src/api/config.ts` 新增 `getLLMConfig()` / `saveLLMConfig()` 与 TS 类型（`LLMConfig`、`LLMProviderConfig`、`LLMModelConfig`）。
   - 新建 `src/views/Settings.vue`：提供商折叠面板（el-collapse）+ 模型表格（el-table）；提供商可编辑 `base_url`、`api_key`（密码框可切换明文）；模型行内编辑别名/实际模型名/temperature/max_tokens；支持新增/删除提供商与模型；顶部「保存 / 重置」按钮，脏状态跟踪，保存成功后 `ElMessage.success`。
   - 路由注册 `/settings`（`requiresAuth: true`），`Home.vue` 功能导航新增「LLM 配置」卡片（grid 调整为 `sm:grid-cols-3 lg:grid-cols-5`）。
3. **验证**：后端跑集成测试；前端跑 `pnpm lint` + `pnpm build:dev`（vue-tsc 类型检查）。

## 执行计划

### Phase 1: 后端 LLM 配置读写接口
**目标**：提供完整配置的读取与保存（含备份、校验）能力，且不破坏现有只读接口。

**阶段验收标准**：
- [ ] `GET /api/config/llm` 返回完整配置 JSON（`ApiResponse` 包装，`data` 为配置对象）
- [ ] `PUT /api/config/llm` 能将合法配置写入 `LLM_CONFIG_PATH`，且写入前生成 `*.bak` 备份
- [ ] 非法配置（缺 `base_url`/`api_key`/`models`、类型错误）返回 400，且不改动原文件
- [ ] 现有 `GET /api/config/llm/providers`、`GET /api/config/llm/models/{provider}` 行为不变
- [ ] 集成测试全部通过

#### Task 1.1: 新增 GET/PUT /api/config/llm 接口
- **目标**：在 `broca-web/backend/app/api/config.py` 中实现完整配置的读取与保存。
- **步骤**：
  1. 在 `broca-web/backend/app/schemas/schemas.py` 中新增请求模型：
     ```python
     class LLMConfigUpdateRequest(BaseModel):
         """保存完整 LLM 配置的请求模型"""
         config: dict[str, Any]
     ```
  2. 在 `app/api/config.py` 中新增模块级辅助函数：
     - `_read_llm_config() -> dict`：`LLM_CONFIG_PATH` 不存在时抛 `HTTPException(404, "LLM config file not found")`；JSON 解析失败抛 `HTTPException(500, ...)`；返回 dict。
     - `_validate_llm_config(config: dict) -> None`：校验规则——顶层必须为 dict；每个 provider 值必须为 dict 且包含 `base_url`(str)、`api_key`(str)、`models`(dict)；`models` 中每个模型值必须为 dict。不合法抛 `HTTPException(400, 具体原因)`。
     - `_write_llm_config(config: dict) -> None`：若目标文件已存在，先复制为 `LLM_CONFIG_PATH.with_suffix('.json.bak')`；写入临时文件（同目录 `llm_config.json.tmp`）后 `os.replace` 原子替换；写入内容 `json.dump(config, ensure_ascii=False, indent=4)`。
  3. 新增两个路由：
     - `GET /llm`（挂载后完整路径 `/api/config/llm`）：调用 `_read_llm_config()`，`ApiResponse.success(config, msg="LLM config retrieved successfully")`。
     - `PUT /llm`：请求体为 `LLMConfigUpdateRequest`；依次调用 `_validate_llm_config` → `_write_llm_config`；成功返回 `ApiResponse.success(msg="LLM config saved successfully")`。
  4. 异常处理与现有代码风格一致：`try/except` + `logger.exception` + 转换为 `HTTPException(500)`（`HTTPException` 直接透传，参考现有写法用 `except HTTPException: raise` 或统一捕获后判断）。
- **预期产出**：`app/api/config.py` 新增 2 个路由与 3 个辅助函数；`app/schemas/schemas.py` 新增 1 个请求模型。
- **验收标准**：
  - [ ] `GET /api/config/llm` 对存在的配置文件返回 `code=200` 且 `data` 与文件内容一致
  - [ ] `PUT /api/config/llm` 传入合法配置后，目标文件内容被更新且格式为 4 空格缩进 JSON；同目录出现 `.bak` 备份且内容为旧配置
  - [ ] `PUT /api/config/llm` 传入缺少 `models` 的 provider 时返回 400，原文件未被修改
  - [ ] `mypy`/`ruff`（若项目配置了检查命令）不报新错误

#### Task 1.2: 后端集成测试
- **目标**：为新增接口补充集成测试，覆盖成功、文件缺失、非法配置、备份生成。
- **步骤**：
  1. 在 `broca-web/tests/integration/test_api_config.py` 中新增 `TestLLMConfigAPI` 类，复用现有 `async_client`、`auth_headers` fixture 与 mock 模式（`patch("app.api.config.LLM_CONFIG_PATH")` + `mock_open`）。
  2. 用例清单：
     - `test_get_llm_config_success`：mock 文件存在且内容为合法 JSON，断言 200、`data` 为 dict 且包含预期 provider。
     - `test_get_llm_config_no_file`：mock `exists` 为 False，断言 404 或 500（与现有测试断言风格一致，用 `in (404, 500)`）。
     - `test_put_llm_config_success`：mock 文件存在，`PUT` 合法配置（含一个 provider 两个 model），断言 200；并断言写入句柄收到的内容包含新 provider（可通过 `mock_open` 的 `write_args` 或改用 `tmp_path` 真实文件验证）。
     - `test_put_llm_config_invalid`：`PUT` 缺少 `models` 键的 provider，断言 400。
     - `test_put_creates_backup`：使用 `tmp_path` 真实文件（monkeypatch `app.api.config.LLM_CONFIG_PATH`）验证保存后生成 `.bak` 且内容为旧配置。
  3. 运行：`cd broca-web && python -m pytest tests/integration/test_api_config.py -v`。
- **预期产出**：`tests/integration/test_api_config.py` 新增 ≥5 个测试用例，全部通过。
- **验收标准**：
  - [ ] 新增用例全部通过，且既有用例无回归
  - [ ] 备份行为有真实文件级验证（非纯 mock）

### Phase 2: 前端 LLM 配置管理页面
**目标**：新增「设置」页面，以结构化表单查看/编辑 LLM 配置，并接入导航。

**阶段验收标准**：
- [ ] 访问 `/settings` 可看到所有提供商及其模型的配置，数据来自 `GET /api/config/llm`
- [ ] 可编辑 base_url / api_key / 模型字段，可新增/删除提供商与模型
- [ ] 点击保存调用 `PUT /api/config/llm` 成功后有成功提示；有未保存修改时给出脏状态提示
- [ ] `pnpm lint` 与 `pnpm build:dev`（含 vue-tsc 类型检查）通过

#### Task 2.1: API 封装与类型定义
- **目标**：在 `broca-web/frontend/src/api/config.ts` 中补充完整配置读写接口与类型。
- **步骤**：
  1. 新增类型定义：
     ```ts
     export interface LLMModelMeta {
       modality?: Record<string, unknown>
       context_window?: number
       [key: string]: unknown
     }
     export interface LLMModelConfig {
       model: string
       temperature?: number
       max_tokens?: number
       extra_body?: Record<string, unknown>
       reasoning_effort?: string
       allowed_openai_params?: string[]
       meta?: LLMModelMeta
       [key: string]: unknown
     }
     export interface LLMProviderConfig {
       base_url: string
       api_key: string
       models: Record<string, LLMModelConfig>
       [key: string]: unknown
     }
     export type LLMConfig = Record<string, LLMProviderConfig>
     ```
  2. 在 `configApi` 中新增：
     - `getLLMConfig(): Promise<LLMConfig>` → `request.get('/config/llm')`
     - `saveLLMConfig(config: LLMConfig): Promise<void>` → `request.put('/config/llm', { config })`
- **预期产出**：`src/api/config.ts` 新增 4 个类型与 2 个方法。
- **验收标准**：
  - [ ] 类型编译通过（vue-tsc 无错误）
  - [ ] 方法路径与后端路由一致（`/config/llm`，request 实例 baseURL 已含 `/api`）

#### Task 2.2: Settings.vue 结构化表单页面
- **目标**：新建 LLM 配置管理页面，结构化展示与编辑。
- **步骤**：
  1. 新建 `broca-web/frontend/src/views/Settings.vue`，`<script setup lang="ts">` 风格与现有页面一致（参考 `Jobs.vue`）。
  2. 数据加载：`onMounted` 调用 `configApi.getLLMConfig()`；为避免直接改动接口返回对象，深拷贝到本地响应式状态（`reactive`/`ref` + `JSON.parse(JSON.stringify(...))`）；加载中显示 `LoadingOverlay` 或 `v-loading`。
  3. 提供商展示：使用 `el-collapse`，每个 provider 一个面板，标题显示「provider id + 模型数量」徽标；面板内：
     - `base_url`：`el-input`；
     - `api_key`：`el-input` `show-password`（掩码可切换明文）；
     - 模型列表：`el-table` 列——模型别名（可编辑 `el-input`，作为 models 的 key，改名时需做 key 迁移）、实际模型名 `model`、`temperature`（`el-input-number` :min="0" :max="2" :step="0.1"）、`max_tokens`（`el-input-number`，可空）、操作列（删除按钮 + `ElMessageBox.confirm` 确认）。
     - 「添加模型」按钮：展开一行内联表单或小对话框，填写别名与 `model`（必填），其余字段留默认。
  4. 提供商级操作：「添加提供商」按钮（对话框输入 provider id，校验非空且不与现有重复）；每个面板头部或内部提供「删除提供商」按钮（`ElMessageBox.confirm` 警告文案说明将删除其下所有模型）。
  5. 保存与重置：顶部工具栏「保存」「重置」按钮；保存前做轻量前端校验（provider id 非空、模型别名非空且 provider 内不重复、`model` 非空）；调用 `saveLLMConfig`，成功 `ElMessage.success('配置已保存')` 并重新加载；重置则放弃本地修改重新拉取。用 `JSON.stringify` 对比初始/当前状态实现脏标记（标题或按钮上显示未保存圆点）。
  6. 样式：沿用 Tailwind 工具类与现有页面布局习惯（页面容器、卡片、间距），不引入新依赖。
- **预期产出**：`src/views/Settings.vue` 完整可用的管理页面。
- **验收标准**：
  - [ ] 页面能正确渲染 `~/.broca/configs/llm_config.json` 中的真实数据（provider/模型数量与文件一致）
  - [ ] 新增/删除提供商与模型、修改字段后保存，刷新页面后数据持久化正确
  - [ ] api_key 默认掩码显示，可切换明文
  - [ ] 非法输入（空 provider id、重复模型别名、空 model）被前端校验拦截并提示

#### Task 2.3: 路由与导航入口
- **目标**：注册 `/settings` 路由并在 Home 页导航中添加入口。
- **步骤**：
  1. `src/router/index.ts`：新增路由 `{ path: '/settings', name: 'Settings', component: () => import('@/views/Settings.vue'), meta: { requiresAuth: true } }`。
  2. `src/views/Home.vue`：功能导航 grid 类名由 `grid-cols-1 sm:grid-cols-4` 调整为 `grid-cols-1 sm:grid-cols-3 lg:grid-cols-5`，新增第 5 个 `router-link` 卡片指向 `/settings`（图标 ⚙️，标题「LLM 配置」，描述「管理 LLM 提供商与模型」）。
- **预期产出**：路由可访问；Home 页出现新导航卡片。
- **验收标准**：
  - [ ] 未登录访问 `/settings` 跳转 `/auth`，登录后可正常进入
  - [ ] Home 页导航卡片点击可进入 `/settings`

#### Task 2.4: 前端质量验证
- **目标**：确保前端改动通过 lint 与类型检查/构建。
- **步骤**：
  1. `cd broca-web/frontend && pnpm lint`（如有格式问题先 `pnpm format`）。
  2. `pnpm build:dev` 验证 vue-tsc 类型检查与构建通过。
- **预期产出**：lint 与 build 全部通过。
- **验收标准**：
  - [ ] `pnpm lint` 0 error
  - [ ] `pnpm build:dev` 成功产出构建产物

**任务依赖**：Task 2.1 → Task 2.2 → Task 2.3 → Task 2.4（顺序执行）；Phase 1 与 Phase 2 的 Task 2.1/2.2 开发可并行，但联调验证需 Phase 1 完成。

## 风险与应对
| 风险 | 影响 | 应对策略 |
|------|------|----------|
| GET 接口返回明文 api_key，存在泄露面 | 中 | 本工具定位为本地/内网使用（回环请求免鉴权）；接口在鉴权保护下；如后续需加固，可增加「仅写不读 key」或脱敏+显式 reveal 参数，本期不做 |
| 写坏配置导致 `broca/llm.py`（Runner 进程）启动失败 | 高 | PUT 前强制结构校验；写入前自动生成 `.bak` 备份；写入使用临时文件 + `os.replace` 原子替换，避免写一半 |
| 仓库内 `configs/llm_config.json`（旧平铺格式）与运行时格式不一致，误导实现 | 中 | 计划已明确以运行时格式（`models` 嵌套 + `meta`）为准；校验逻辑按运行时格式实现 |
| 正在运行的 Session 持有旧配置，保存后不立即生效 | 低 | 在设置页保存成功提示中注明「新配置对新启动的 Session 生效」；不做热重载 |
| 前端编辑模型别名（作为 JSON key）遗漏迁移导致数据错乱 | 中 | 别名编辑实现为「删除旧 key + 写入新 key」的原子迁移，且校验 provider 内唯一性 |

## 未解决的问题
（无——范围与交互形式已与用户确认：仅展示+编辑现有配置、结构化表单、不做连通性测试）
