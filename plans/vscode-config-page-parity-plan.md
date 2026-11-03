# broca-vscode 配置页全量对齐 Web 端设置页

## 概述
- **目标**：将 `broca-vscode` 的 Broca Settings 配置页从"仅客户端本地设置"扩展为与 `broca-web` Settings 页能力对齐的完整配置管理页——新增 **基础配置 / LLM 配置 / 工具权限 / MCP** 四类服务端配置面板（通过后端 `/api/config/*` 接口读写），并保留原有客户端设置。
- **背景**：
  - 当前 `ConfigApp.vue` 只有 4 组客户端设置（Server URL/WS URL、存储 Cloudflare·Supabase、默认 provider·model），存到 VSCode 设置 `broca.*`，与 `config.ts`/`package.json` 一致，本身完整。
  - 后端 `broca-web/backend/app/api/config.py` 已提供 `general / llm / tool-permission / mcp` 的读写接口（含校验、备份、原子写），Web 端 `Settings.vue` 已完整消费；VSCode 端完全未暴露这些能力。
  - 用户已确认：**全量对齐 Web 端设置页**、**LLM 面板完整复刻（含"更多参数"与多模态子参数）**。
- **约束条件**：
  - **UI 用纯 HTML/CSS + VSCode 主题变量**（`--bg-primary`、`--border-color` 等），**不引入** Element Plus / Tailwind；Element 的折叠/表格/弹窗用原生元素（`<details>`/`<table>`/自绘 modal）重写，风格与现有 `ConfigApp.vue` 一致，自动适配 VSCode 明暗主题。
  - **复用后端已有 `/api/config/*` 接口，不改后端**。
  - **不破坏**现有客户端设置（serverUrl/wsUrl/存储/默认 provider·model）的加载/保存行为。
  - 遵循现有 webview↔extension 消息协议模式：webview `postMessage` → extension 调 `ApiClient` → 回 `postToPanel`。
  - 全部 API 调用发生在 extension host（Node axios，自动带 Bearer token），webview 不直连后端，**无需改动 CSP / vite 入口 / 打包配置**（新增 `.vue` 经 import 自动打包）。

## 相关材料
- `broca-vscode/src/webview/src/ConfigApp.vue` — 现有配置页（客户端设置逻辑 + 纯 HTML/CSS 样式范式：section/field/field-input/field-select/toast/divider）
- `broca-vscode/src/extension/config.ts` — `ConfigManager`（客户端设置 `getAll/setAll`，`storageType`）
- `broca-vscode/src/extension/api.ts` — `ApiClient`（需新增 8 个方法；响应拦截器已解包 `ApiResponse{code,data,msg}` → `data`，404/500/401 走 reject）
- `broca-vscode/src/extension/types.ts` — `WebViewMessage` / `ExtensionToWebView` / `WebViewToExtension`（需新增配置类型与消息类型）
- `broca-vscode/src/extension/chatWebView.ts` — `openConfigPage()` 的 `onDidReceiveMessage`（现有 `getConfig/saveConfig/getProviders/getModels` 处理范式，需新增 8 个处理器）
- `broca-vscode/src/webview/src/types.ts` — webview 侧类型（需与 extension 对齐新增类型）
- `broca-vscode/src/webview/src/api/vscode.ts` — `postMessage/onMessage` 桥（`onMessage` 为 `window.addEventListener('message')`，可被多个监听器同时接收）
- `broca-web/backend/app/api/config.py` — 后端 4 类配置接口的**校验规则、路径、`ApiResponse` 语义**（general 的 `KNOWN_*_FIELDS`/`VALID_LOG_LEVELS`/`VALID_DECODING_METHODS`；llm `_validate_llm_config`；tool `_validate_tool_permission_config`；mcp `_validate_mcp_config`）
- `broca-web/frontend/src/api/config.ts` — 前端类型定义权威来源（`GeneralConfig/ExecutionConfig/ASRConfig/LLMConfig/LLMProviderConfig/LLMModelConfig/LLMModelMeta/ToolPermissionConfig/McpServerConfig/McpConfig` + `PERMISSION_VALUES/LOG_LEVELS/MCP_TRANSPORTS`）
- `broca-web/frontend/src/views/Settings.vue` — **LLM 编辑器完整参考**（provider 折叠、模型行内编辑、"更多参数" `openAddExtraParam/setStringParam/setNumberParam/applyExtraBody/applyJsonParam/renameExtraParam`、多模态 `hasModality/toggleModality/openModalityDialog`、`MODALITY_OPTIONS`、自动保存/离开保护）
- `broca-web/frontend/src/views/settings/GeneralConfigPanel.vue` — 基础配置参考（`FIELDS` 6 项 + `EXECUTION_FIELDS` 10 项 + ASR 3 项 + `DECODING_METHODS`）
- `broca-web/frontend/src/views/settings/ToolPermissionPanel.vue` — 工具权限参考（说明块/表格/添加弹窗/自动保存/校验）
- `broca-web/frontend/src/views/settings/McpConfigPanel.vue` — MCP 参考（stdio·http 传输互斥、args 换行、env/headers JSON、`setTransport/applyArgs/applyStringMap/setToolTimeout/renameServer`）
- `broca-vscode/vite.config.ts` — webview 构建（多入口 `index/config/crew`，`@`→`src/webview/src`；新增 `.vue` 自动打包，无需改动）
- `broca-vscode/package.json` — 脚本：`build:extension`（tsc）、`build:webview`（vite）、`check:all`（format:check+lint）、`package`（vsce）

## 总体方案

**架构（webview 侧）**：`ConfigApp.vue` 改造为**纯标签容器**（标签栏 + 懒加载激活面板）。拆出 **5 个自包含面板组件**（放 `src/webview/src/components/settings/`）：
1. `ClientConfigPanel.vue` — 现有客户端设置逻辑/样式整体迁移（行为完全不变）
2. `GeneralConfigPanel.vue` — 基础配置（6 基础字段 + execution 10 项 + asr 3 项）
3. `LLMConfigPanel.vue` — LLM 配置（完整复刻 Web）
4. `ToolPermissionPanel.vue` — 工具权限
5. `McpConfigPanel.vue` — MCP 配置

**面板自治**：每个面板各自 `onMessage` 并按**自身专属消息类型**过滤（避免 5 个监听器串扰），各自 `postMessage` 发请求，各自维护 `loading/saving/dirty/initialJson/damaged/autoSaveBlocked/lastSavedAt/saveFailed` 状态，各自实现 **1.2s 防抖自动保存 + 手动保存 + 重置 + 校验**。`ConfigApp` 不再持有面板数据。

**懒加载 + 保持挂载**：`activeTab`（默认 `client`）+ `activatedTabs: Set`。切到某标签首次时加入集合才 `v-if` 挂载（首次激活才拉取后端配置），之后 `v-show` 保持挂载以保留编辑态（对齐 Web `el-tabs` 行为）。

**消息协议（extension↔webview，每面板独立类型）**：

| 面板 | 请求（webview→ext） | 数据回传（ext→webview） | 保存成功 | 错误 |
|------|--------------------|------------------------|----------|------|
| 客户端 | `getConfig`/`saveConfig`/`getProviders`/`getModels`（不变） | `config`/`providers`/`models` | `saved` | `error` |
| 基础 | `getGeneralConfig`/`saveGeneralConfig` | `generalConfig {config, damaged}` | `generalConfigSaved` | `generalConfigError {message}` |
| LLM | `getLLMConfig`/`saveLLMConfig` | `llmConfig {config, damaged}` | `llmConfigSaved` | `llmConfigError {message}` |
| 工具权限 | `getToolPermissionConfig`/`saveToolPermissionConfig` | `toolPermission {config, damaged}` | `toolPermissionSaved` | `toolPermissionError {message}` |
| MCP | `getMcpConfig`/`saveMcpConfig` | `mcpConfig {config, damaged}` | `mcpSaved` | `mcpError {message}` |

**404/500 → damaged**：extension 的 `get*` 处理器 try 调 API；成功回 `{config, damaged:false}`；`catch` 中若 `e.response?.status ∈ {404,500}`（文件缺失/损坏）回 `{config:<空配置>, damaged:true}`，否则发对应 `*Error`。空配置：general=`{}`、llm=`{}`、tool=`{tools:{}}`、mcp=`{}`。

**鉴权**：后端接口需 token；未登录时 `get*` 会 401 → `ApiClient` 拦截器触发既有 `onAuthError`（自动登出+登录框），与现有 `getProviders` 行为一致；401 **不**判为 damaged。

## 执行计划

### Phase 1: 扩展侧能力（Extension host）
**目标**：扩展 `ApiClient`、`openConfigPage` 消息处理与共享类型，为 webview 面板提供数据通道。

**阶段验收标准**：
- [ ] `npm run build:extension`（tsc）通过
- [ ] `ApiClient` 暴露 8 个新方法，路径与后端 `config.py` 一致，保存方法 body 为 `{config}`
- [ ] `openConfigPage` 处理 8 个新消息类型；404/500 → `*Config {config, damaged:true}`，其它错误 → `*Error`；保存成功 → `*Saved`
- [ ] 现有 `getConfig/saveConfig/getProviders/getModels` 行为不变
- [ ] 新增类型在 `extension/types.ts` 与 `webview/types.ts` 双侧一致

#### Task 1.1: 新增共享配置类型
- **目标**：在 `src/extension/types.ts` 与 `src/webview/src/types.ts` 各新增配置类型，并扩展消息类型联合。
- **步骤**：
  1. 新增（字段严格对齐 `broca-web/frontend/src/api/config.ts`）：`LLMModelMeta`、`LLMModelConfig`、`LLMProviderConfig`、`LLMConfig`、`ASRConfig`、`ExecutionConfig`（10 项）、`GeneralConfig`（含 `execution?/asr?`）、`ToolPermissionConfig`、`McpServerConfig`、`McpConfig`；常量 `PERMISSION_VALUES`、`LOG_LEVELS`、`MCP_TRANSPORTS`（webview 侧用；extension 侧可不放常量）。
  2. `extension/types.ts`：`ExtensionToWebView.type` 联合追加 `generalConfig|generalConfigSaved|generalConfigError|llmConfig|llmConfigSaved|llmConfigError|toolPermission|toolPermissionSaved|toolPermissionError|mcpConfig|mcpSaved|mcpError`；`WebViewToExtension.type` 追加 `getGeneralConfig|saveGeneralConfig|getLLMConfig|saveLLMConfig|getToolPermissionConfig|saveToolPermissionConfig|getMcpConfig|saveMcpConfig`。
  3. `webview/types.ts` 同步新增上述类型（webview 侧为单一消息 `any` 即可，但类型供面板引用）。
- **预期产出**：两个 `types.ts` 更新。
- **验收标准**：
  - [ ] 类型字段与 web `api/config.ts` 一一对应（execution 10 项、asr 3 项、mcp 的 command/args/env/cwd/url/headers/tool_timeout）
  - [ ] 新增消息类型在两侧联合类型齐全
  - [ ] tsc 通过

#### Task 1.2: `ApiClient` 新增 8 个配置读写方法
- **目标**：在 `api.ts` 的 "Config API" 区新增方法。
- **步骤**：
  1. `getGeneralConfig(): Promise<GeneralConfig>` → `GET /config/general`。
  2. `saveGeneralConfig(config)` → `PUT /config/general`，body `{ config }`。
  3. `getLLMConfig(): Promise<LLMConfig>` / `saveLLMConfig(config)` → `GET/PUT /config/llm`。
  4. `getToolPermissionConfig()` / `saveToolPermissionConfig(config)` → `GET/PUT /config/tool-permission`。
  5. `getMcpConfig()` / `saveMcpConfig(config)` → `GET/PUT /config/mcp`。
- **预期产出**：`api.ts` 新增 8 方法。
- **验收标准**：
  - [ ] 8 个方法路径与后端 `config.py` 路由一致（`/general`、`/llm`、`/tool-permission`、`/mcp`，baseURL 已含 `/api`）
  - [ ] 保存方法 body 为 `{ config }`（与 web `configApi` 一致）
  - [ ] 404/500/401 走 axios reject（`e.response.status` 可用），供处理器识别

#### Task 1.3: `openConfigPage` 新增 8 个消息处理器
- **目标**：在 `chatWebView.ts` 的 `openConfigPage()` → `panel.webview.onDidReceiveMessage` 中新增处理分支（与现有 `getConfig/saveConfig/getProviders/getModels` 并列）。
- **步骤**：
  1. 定义本地小工具：`emptyConfigFor(kind)` 返回 `{}`/`{tools:{}}` 等；`isFileError(e)=e?.response?.status===404||e?.response?.status===500`。
  2. `getGeneralConfig/getLLMConfig/getToolPermissionConfig/getMcpConfig`：`try` 调 `apiClient.getXxx()` → `postToPanel {type:'xxxConfig', payload:{config, damaged:false}}`；`catch` 若 `isFileError` → `postToPanel {type:'xxxConfig', payload:{config:emptyConfigFor(xxx), damaged:true}}`，否则 `postToPanel {type:'xxxError', payload:{message:extractErrorMessage(e)}}`。
  3. `saveGeneralConfig/saveLLMConfig/saveToolPermissionConfig/saveMcpConfig`：`try` 调 `apiClient.saveXxx(message.payload)` → `postToPanel {type:'xxxSaved'}`；`catch` → `postToPanel {type:'xxxError', payload:{message:extractErrorMessage(e)}}`。
- **预期产出**：`chatWebView.ts` `openConfigPage` 新增 8 分支。
- **验收标准**：
  - [ ] 8 个请求类型均有处理器且类型匹配 `ExtensionToWebView`
  - [ ] 404/500 → `*Config {config:空, damaged:true}`；401/其它 → `*Error`
  - [ ] 保存成功 → `*Saved`；现有 4 个客户端消息处理行为不变
  - [ ] tsc 通过

### Phase 2: Webview 面板
**目标**：把 `ConfigApp` 变成 5 标签容器，实现 5 个自包含面板（客户端 + 4 个后端面板），纯 HTML/CSS + VSCode 主题变量。

**阶段验收标准**：
- [ ] `npm run build:webview`（vite）成功，`dist/webview/config.*` 含新面板
- [ ] 配置页出现 5 个标签（客户端设置/基础配置/LLM 配置/工具权限/MCP 配置），默认"客户端设置"
- [ ] 5 个面板均可 加载→编辑→自动/手动保存→重置；保存成功有提示，错误有 toast
- [ ] 客户端设置（含存储二选一、默认 provider 联动拉模型）无回归
- [ ] 标签懒加载：切到后端标签才拉取；已加载面板切换不丢编辑态

#### Task 2.1: `ConfigApp` 改造为标签容器 + 拆出 `ClientConfigPanel`
- **目标**：`ConfigApp.vue` 变为纯容器；现有客户端逻辑/样式迁移到 `components/settings/ClientConfigPanel.vue`。
- **步骤**：
  1. 新建 `components/settings/ClientConfigPanel.vue`：迁移现有 `config` ref、`providers/models`、`onMessage`（仅处理 `config/providers/models/saved/error`）、`saveConfig`、`onProviderChange`、错误 toast，以及现有"Server/Storage/Default LLM"三段 template 与相关 `<style>`。对外不暴露（自包含）。
  2. 新建共享样式：将 `ConfigApp.vue` 中的通用样式（`*` reset、`section/field/field-label/field-input/field-select/field-hint/toast/divider` 等）抽到 `components/settings/settings.css`（或全局 style），供 5 面板 `import`，统一视觉。
  3. 重写 `ConfigApp.vue`：顶部标题 "Broca Settings" + 标签栏（5 项）；`activeTab=ref('client')`、`activatedTabs=ref(new Set(['client']))`；`switchTab(key)` 时加入 `activatedTabs`；按 `v-if="activatedTabs.has(key)" v-show="activeTab===key"` 渲染 5 个面板组件；`import` 5 个组件。ConfigApp 不再持有数据/监听。
- **预期产出**：`ConfigApp.vue`（容器）、`ClientConfigPanel.vue`、`settings.css`。
- **验收标准**：
  - [ ] 默认激活"客户端设置"，其加载/保存/存储二选一/默认 provider 联动拉模型行为与改造前一致
  - [ ] 5 个标签可见可切换；切到后端标签才首次 `postMessage` 拉取；已加载面板 `v-show` 保留编辑态
  - [ ] `build:webview` 成功

#### Task 2.2: `GeneralConfigPanel.vue`（基础配置）
- **目标**：复刻 web `GeneralConfigPanel`：6 基础字段 + execution 10 项（数字）+ asr 3 项。
- **步骤**：
  1. 状态：`loading/saving/config:GeneralConfig/initialJson/dirty/damaged/autoSaveBlocked/saveFailed/lastSavedAt`。
  2. 加载：`onMounted`（或首次激活触发）`postMessage getGeneralConfig`；`onMessage` 收 `generalConfig` → 深拷贝入 `config`、置 `damaged`、记 `initialJson`。
  3. 表单（纯 HTML）：
     - 6 基础字段：`database_dir`(input)、`log_file`(input)、`log_level`(**select**: DEBUG/INFO/WARNING/ERROR/CRITICAL)、`llm_config_file`(input)、`socket_server_url`(input)、`api_server_url`(input)；每项带 hint。
     - execution 分组：10 项数字 input（`step_max_errors/llm_retry_delay/tool_call_timeout/assign_task_timeout/llm_timeout/llm_first_chunk_timeout/dead_loop_window/message_queue_size/permission_request_timeout/agent_query_timeout`），标签+单位（秒/次/条）+ min/step（对齐 web `EXECUTION_FIELDS`）。
     - asr 分组：`model_name`(input)、`decoding_method`(**select**: `modified_beam_search`/`greedy_search`)、`noise_gate_rms`(数字 input，0 禁用)。
  4. 校验 `validateBeforeSave()`：`log_level` ∈ `LOG_LEVELS`（select 保证）；execution 若存在须为非负数字；asr 字段合法。返回错误串或 null。
  5. 自动保存（1.2s 防抖 `watch(config,deep)` + `mutatedDuringSave`）+ 手动 `saveNow()`（先校验，`postMessage saveGeneralConfig`）+ `reset()`（重拉）。保存成功回 `generalConfigSaved` → 更新 `initialJson`/`lastSavedAt`。
  6. damaged 警示条（文件缺失/损坏，保存将创建/修复）。
- **验收标准**：
  - [ ] 加载显示 `configs.json` 当前值（含 execution/asr 分组）；文件缺失/损坏显示警示条且可编辑保存
  - [ ] execution 10 项、asr 3 项均可编辑并正确写入 `config` 分组
  - [ ] 自动/手动保存、重置、`generalConfigSaved` 更新基线；保存调 `saveGeneralConfig`，成功 toast

#### Task 2.3: `LLMConfigPanel.vue`（LLM 配置，完整复刻）
- **目标**：复刻 web `Settings.vue` 的 LLM 编辑（含"更多参数"与多模态子参数）。
- **步骤**：
  1. 状态：`config:LLMConfig/initialJson/dirty/loading/saving/damaged/activeProviders`（折叠展开）`/expandedParams`/`jsonEditErrors`/`inputDrafts`（失焦写回草稿，对齐 web 交互）`/saveFailed/autoSaveBlocked/lastSavedAt`。
  2. 加载：`getLLMConfig`（404/500→`damaged`+空 `{}`）→ 深拷贝、`activeProviders`=首个、清草稿/错误。
  3. provider 折叠（`<details>`/自绘可折叠块，标题=provider id + 模型数徽标 + 删除按钮）：
     - `base_url`(input)、`api_key`(password，带"显示/隐藏"切换)
     - "添加提供商"（自绘 modal：provider id 非空且不重复）、"删除提供商"（自绘 confirm，提示将删其下所有模型）
  4. 模型表格（`<table>`）行内编辑：
     - 别名：失焦写回 + **key 迁移**（保持顺序，重名/空回退）
     - `model`(input)、`temperature`(数字 0–2 step0.1)、`max_tokens`(数字)、上下文窗口(数字，写 `meta.context_window`)
     - `extra_body`：JSON textarea，失焦解析（空串清除；非法→`jsonEditErrors`+保留草稿）
     - "添加模型"（自绘 modal：别名/实际模型名/max_tokens/上下文窗口/多模态勾选，默认勾 text）；"删除模型"（confirm）
  5. **更多参数**（`EXTRA_PARAM_EXCLUDED={model,max_tokens,extra_body,meta}`）：每模型可展开，列出其余字段，按 `paramValueType`（boolean→checkbox、number→数字 input、string→文本 input 自动识别数字/布尔/JSON、array/object/null→JSON textarea）渲染；支持
     - 添加参数（自绘 modal 输入 key，校验非空/非保留/不重复，写入 `modelConfig[key]=''` 并展开）
     - 重命名 key（保留/重名校验 + 草稿迁移）
     - 删除（`delete modelConfig[key]`）
     - 值编辑：`setStringParam`（`JSON.parse` 命中非字符串则按解析值存，否则存文本）、`setNumberParam`（清空移除）、`applyJsonParam`（非法保留草稿）
  6. **多模态**：`MODALITY_OPTIONS=[text,image,video,audio]` 4 个 checkbox；`hasModality`（key 存在即启用）；`toggleModality`（勾→补默认 `text:''` 其余 `{}`，取消→删 key）；"参数"弹窗（自绘 modal）编辑 image/video/audio 的 JSON 子参数（仅对已启用能力），确认后合并回 `meta.modality`。
  7. 校验 `validateBeforeSave()`：provider id 非空、每 provider 有 `models`；模型别名非空且 provider 内唯一、`model` 非空、至少一项多模态、`extra_body`/JSON 参数合法（`jsonEditErrors` 非空即拦截）。
  8. 自动保存（1.2s 防抖）+ `saveNow()`（先校验，`postMessage saveLLMConfig`）+ `reset()`；`llmConfigSaved` → 更新基线。damaged 警示条。
- **验收标准**：
  - [ ] 正确渲染真实 `llm_config.json`（provider/模型数量与文件一致）
  - [ ] 增删 provider、增删模型、重命名模型别名（key 迁移）均生效
  - [ ] 行内编辑 temperature/max_tokens/上下文窗口/extra_body 生效；extra_body 非法 JSON 报错并保留草稿
  - [ ] 更多参数：布尔/数字/字符串/JSON 四种编辑器按值类型正确渲染，可 添加/重命名/删除 参数；字符串参数自动识别数字/布尔/JSON
  - [ ] 多模态勾选正确写 `meta.modality`（text 默认 `''`，其余 `{}`）；多模态参数弹窗可编辑 image/video/audio JSON 并合并
  - [ ] 自动/手动保存、重置、damaged 语义与 web 一致；保存调 `saveLLMConfig`
  - [ ] `build:webview` 成功

#### Task 2.4: `ToolPermissionPanel.vue`（工具权限）
- **目标**：复刻 web `ToolPermissionPanel`。
- **步骤**：
  1. 状态同其它面板；`config:ToolPermissionConfig={_description?,_permission_values?,tools}`。
  2. 只读说明块：读取优先级（① workspace/.broca/ → ② ~/.broca/configs/ → ③ 默认 allow）+ 权限值含义（优先取文件内 `_description/_permission_values`，缺失用内置文案）。
  3. 表格（`<table>`）：工具名（只读）/ 权限（**select**: allow/ask/forbidden，选项带含义）/ 删除；空态提示。
  4. "添加工具"（自绘 modal：工具名 + 权限 select，默认 allow；空名/重名校验）。
  5. 保存**完整对象**（`_description/_permission_values` 原样 + 修改后 `tools`）→ `saveToolPermissionConfig`；文件缺失/损坏 → damaged 空 `{tools:{}}` 可创建。
  6. 校验：工具名非空唯一、权限值 ∈ `PERMISSION_VALUES`。自动/手动保存 + 重置。
- **验收标准**：
  - [ ] 加载展示 `tools` 全部项；改权限/删除/添加均正确写入
  - [ ] 保存保留 `_description/_permission_values` 原样
  - [ ] 校验（非空唯一 + 合法权限值）生效；保存调 `saveToolPermissionConfig`，文件缺失可创建

#### Task 2.5: `McpConfigPanel.vue`（MCP 配置）
- **目标**：复刻 web `McpConfigPanel`。
- **步骤**：
  1. 状态同其它面板；`config:McpConfig`（服务器名→配置）。
  2. 只读说明块（stdio 需 `command`，http 需 `url`；读取优先级 workspace > 全局）。
  3. 服务器折叠（`<details>`，标题=服务器名 + 传输 tag + 删除）：
     - 服务器名（失焦 `renameServer`：重名/空回退 + 折叠态同步）
     - 传输方式（自绘单选 stdio/http）；`setTransport` 互斥清理另一传输专属字段
     - stdio：`command`、`cwd`、`args`（textarea 换行分隔 `applyArgs`）、`env`（JSON string→string `applyStringMap`）
     - http：`url`、`headers`（JSON string→string）
     - `tool_timeout`（数字，正数；清空移除）
  4. "添加服务器"（自绘 modal：名/传输/command 或 url/args/env 或 headers/tool_timeout，校验与后端一致）。
  5. 校验 `validateBeforeSave()`（对齐后端 `_validate_mcp_config`：command/url 二选一且非空、args 字符串数组、env/headers 为 string→string、cwd 字符串、tool_timeout 正数、JSON 字段合法）。
  6. 保存 → `saveMcpConfig`；文件缺失/损坏 → damaged 空 `{}` 可创建。自动/手动保存 + 重置。
- **验收标准**：
  - [ ] stdio 与 http 两种传输字段正确切换（互斥清理专属字段）
  - [ ] args(换行)、env/headers(JSON string→string)、cwd、tool_timeout(正数) 编辑正确
  - [ ] 添加/重命名/删除服务器正确；校验与后端 `_validate_mcp_config` 一致
  - [ ] 保存调 `saveMcpConfig`，文件缺失可创建；`build:webview` 成功

### Phase 3: 验证与打包
**目标**：全链路构建/静态检查通过，产出可安装 vsix，冒烟确认无回归。

**阶段验收标准**：
- [ ] `npm run build:extension` + `npm run build:webview` + `npm run check:all`（format:check + lint）全通过
- [ ] `npm run package` 生成新 vsix
- [ ] 冒烟（可选）：加载扩展打开 Settings，5 标签可用，客户端设置无回归，至少一个后端面板完成 加载→编辑→保存 闭环

#### Task 3.1: 构建与静态检查
- **步骤**：`cd broca-vscode && npm run build:extension && npm run build:webview && npm run check:all`；修复所有类型/构建/lint/prettier 错误（必要时先 `npm run format`）。
- **验收标准**：
  - [ ] `build:extension`（tsc）0 错误
  - [ ] `build:webview`（vite）成功产出 `dist/webview`（含 config 入口 + 新面板 chunk）
  - [ ] `check:all`（format:check + lint）通过

#### Task 3.2: 打包与冒烟
- **步骤**：`npm run package` 生成 `broca-chat-*.vsix`（覆盖旧包）；如环境允许，在 VSCode 中加载扩展并打开 `broca.configure` 冒烟：默认"客户端设置"正常；切到"基础配置/LLM/工具权限/MCP"分别验证 加载→编辑→保存 闭环与错误提示。
- **验收标准**：
  - [ ] 生成新 vsix
  - [ ] 冒烟记录（或说明未执行原因）：5 标签可切换、客户端设置无回归、至少一个后端面板完成保存闭环

## 风险与应对
| 风险 | 影响 | 应对策略 |
|------|------|----------|
| `LLMConfigPanel` 体量大、交互复杂（草稿态/JSON 解析/key 迁移/多模态） | 高 | 逐字段对齐 web `Settings.vue` 逻辑（本计划已列出全部关键函数语义）；先核心字段后"更多参数"；tsc+vite 拦截；Task 2.3 AC 逐项覆盖 |
| 5 个面板各自 `onMessage` 串扰（每个 `window` 监听器都会收到所有消息） | 中 | 每面板使用**独立消息类型**严格过滤，互不处理对方类型；ConfigApp 不再持有监听（纯容器） |
| 拆 `ClientConfigPanel` 引入回归 | 中 | 纯代码迁移、不改逻辑；Task 2.1 AC 明确"行为与改造前一致"；共享样式抽到 `settings.css` 保持视觉一致；构建+冒烟验证 |
| 未登录时后端 `get*` 401 触发自动登录、误报 damaged | 低 | `isFileError` 仅按 `status∈{404,500}` 判 damaged；401 走既有 `onAuthError`（与 `getProviders` 一致） |
| webview dispose 时未保存编辑丢失 | 低 | 面板卸载前 `onBeforeUnmount` 清定时器；若 dirty 可 best-effort 触发一次保存；主保存仍靠自动/手动保存 |
| 纯 HTML 重写 Element 交互（折叠/表格/弹窗）观感差异 | 低 | 复用 `settings.css` 统一范式；折叠用 `<details>`/自绘、弹窗用自绘 modal（复用 toast 的 fixed 定位风格）；以"功能对齐 + 风格统一"为准 |
| 后端 `configs.json` 可能缺失/损坏导致 GET 500/404 | 中 | 前端 `damaged` 状态：警示条 + 允许编辑保存（后端 PUT 备份后重写修复），形成自愈路径 |

## 未解决的问题
- 无。三项关键决策已与用户确认：**① 范围=全量对齐 Web 端设置页**；**② UI=纯 HTML/CSS + VSCode 主题变量（不引入 Element Plus/Tailwind）**；**③ LLM 面板=完整复刻（含"更多参数"与多模态子参数）**。执行中若发现后端接口字段与 web 类型不一致，以 `broca-web/backend/app/api/config.py` 实际契约为准并记录。
