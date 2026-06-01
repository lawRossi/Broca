# Broca VSCode 多 Agent 编排适配方案

## 概述

Broca 系统已引入多 Agent 编排（Crew）能力，支持 6 种协作拓扑（Pipeline、Supervisor-Worker、Round-Table、Broadcast、Consensus、Composite）。broca-web 已提供完整的编排管理 UI，现需在 broca-vscode 扩展中进行对应适配。

本方案聚焦于「不需要代码细节」的 UI 适配思路，以 broca-web 为参考，梳理 broca-vscode 需要修改的范围和方案。

---

## 一、适配范围总览

| 模块 | 需适配内容 | 优先级 |
|------|-----------|--------|
| 会话创建 | 新增 `category` 字段（normal / agent-orchestration） | P0 |
| 会话树 | 编排会话标记、展示编排执行状态 | P1 |
| 聊天 WebView | 编排会话只读模式（隐藏输入框、显示只读提示） | P0 |
| Extension API | 新增 Crew API 接口 | P0 |
| Commands | 新增「提交编排」「查看编排」等命令 | P1 |
| 配置文件操作 | 读取/列出 workspace 下 `crew_configs/` 目录 | P2 |

> **注意**：broca-web 中的 CrewYamlEditor（YAML 编辑器组件）**不需要** 在 VS Code 中实现，因为 VS Code 本身具备优秀的 YAML 编辑能力，用户可以直接在编辑器中编辑 `crew_configs/*.yaml` 文件。

---

## 二、各模块适配方案

### 2.1 会话创建 — 新增 category 字段

**现状**：`openCreateSessionDialog()` 中的 HTML 表单只有 description、provider、model、workspace 四个字段。

**适配方案**：

1. **在创建会话表单中增加「会话类型」选择控件**，提供两个选项：
   - **普通会话**（normal）：创建内置 Agent（Broca、sub-agent、explorer），适合日常对话和任务
   - **Agent 编排会话**（agent-orchestration）：不创建内置 Agent，从工作空间加载自定义 Agent，适合多 Agent 编排工作流

2. **类型选择控件的交互参考**：
   - 使用 radio button 或 select 控件
   - 每个选项附带简要说明文字
   - 选中 agent-orchestration 时，可提示用户需要在 workspace 的 `.broca/agents/` 目录下准备自定义 Agent 配置

3. **提交时携带 category 字段**：`POST /session/sessions` 请求体中增加 `category` 参数

4. **对应类型修改**：`CreateSessionParams` 接口增加 `category?: string` 字段

### 2.2 会话树 — 编排信息展示与导航

**现状**：`SessionTreeItem` 展示 session_id、description、workspace、runner_status，tooltip 包含基本信息。双击/点击打开聊天 Panel。

**适配方案**：

1. **编排会话视觉标记**：
   - 对于 `category === 'agent-orchestration'` 的会话，使用不同的图标（如连接图标）区别于普通会话
   - 在 tooltip 中增加 `Category: Agent Orchestration` 信息

2. **编排执行状态展示（可选 P1）**：
   - 在会话树节点的 description 后附加编排状态信息，如 `[Executing]` 或 `[Crew: pipeline]`
   - 参照 broca-web 的 `statusTypeMap`，用不同颜色图标表示编排执行状态

3. **点击行为差异化**：
   - **普通会话**（normal）：双击/点击 → 打开聊天 Panel（保持现有行为不变）
   - **编排会话**（agent-orchestration）：双击/点击 → **直接打开执行管理 Panel**（`broca.crews`，自动过滤到该 session 的执行记录），**不**打开聊天 Panel

4. **右键菜单新增命令**：
   - 「提交编排」（提交当前 workspace 中的某 YAML 配置）
   - 「查看编排执行记录」（打开执行记录列表视图）
   - 「查看聊天日志」（手动打开聊天 Panel，用于查看执行日志）

### 2.3 聊天 WebView — 编排会话适配

**现状**：App.vue 包含三栏布局（AgentSidebar + ChatMessageList/ChatInput + ChatInfoSidebar），聊天输入框始终显示。

**适配方案**：

#### 2.3.1 编排会话只读模式（从执行管理 Panel 进入）

1. **入口**：编排会话的聊天 Panel **不从会话树直接打开**，而是从执行管理 Panel 中的执行记录项点击「查看聊天日志」进入（见 §3.1）。

2. **会话分类判断**：extension host 在 `openChat()` 时获取 session 详情，将 `category` 和 `execution_id` 信息通过 init data 注入 webview

3. **WebView 端根据 category 切换模式**：
   - 普通会话（normal）：保持现有交互不变
   - 编排会话（agent-orchestration）：
     - **隐藏 ChatInput 组件**
     - **在输入框位置显示只读提示条**：内容参照 broca-web 的「此会话为 Agent 编排会话，聊天仅用于查看执行日志」
     - **增加「返回编排管理」按钮**，点击跳转到执行管理 Panel
     - **禁用撤销/重做功能**（broca-web 的 chat store 中已有 `isAgentOrchestration` 控制）

4. **编排执行 ID 过滤**：
   - 从 init data 中接收 `execution_id` 参数
   - 在 `loadHistory` 的 API 请求中传递此参数，仅返回该编排执行产生的消息（见 `GET /session/{session_id}/messages?execution_id=xxx`）
   - 在会话标题区域展示当前编排名称

#### 2.3.2 编排进度展示（由执行管理 Panel 展示，数据通过 Extension Host Socket 转发）

编排进度数据通过 extension host 已有的 Socket.IO 连接获取，转发给执行管理 Panel 的 WebView：

1. **Extension Host 订阅编排频道**：当执行管理 Panel 打开时，extension host 为该 session 订阅 `crew:session_id` 频道（复用现有的 `SocketClient` 机制）
2. **实时事件转发**：收到 `system_message` 且 `data.crew_event` 存在时，通过 `postMessage` 直接推送给执行管理 Panel 的 WebView
3. **REST API 兜底**：Panel 初始化时通过 `GET /crews/{execution_id}` 获取完整数据，后续靠 Socket 实时更新
4. **取消订阅**：Panel 关闭时，extension host 取消 `crew:session_id` 频道的订阅

聊天 WebView **不参与**任何编排数据的中转或展示。

#### 2.3.3 Socket 事件处理 — 聊天 WebView 不做编排事件订阅

**现状**：`chatWebView.ts` 的 `SocketClient` 已支持普通 chat 频道订阅。

**适配方案**：

- 聊天 WebView 的 Socket 连接**仅订阅普通会话频道**（`session_id`），不订阅 `crew:session_id`
- 编排事件的订阅由 extension host 统一管理（见 §2.3.2）：当执行管理 Panel 打开时，extension host 订阅 `crew:session_id` 并将事件推送给该 Panel
- 聊天 WebView 关闭时只需取消普通频道的订阅，无需处理编排频道

> **说明**：extension host 的 `SocketClient` 已具备多频道管理能力（`subscribe`/`unsubscribe`），编排频道与聊天频道在 extension host 层是平级的，各自独立。

#### 2.3.4 WebView Chat Store 新增编排会话标记

在 `webview/src/stores/chat.ts` 中仅需新增：
- `isAgentOrchestration` 标记（来自 init data 的 session category 字段）
- 用于控制 ChatInput 显示/隐藏、禁用撤销/重做

无需新增编排执行状态或事件处理方法（这些归属执行管理 Panel）。

### 2.4 Extension API — 新增 Crew 接口

**现状**：`ApiClient` 仅有 Session、Runner、Agent、Message、Auth、Config 相关接口。

**适配方案**：

在 `src/extension/api.ts` 中新增以下方法：

| 方法 | 端点 | 说明 |
|------|------|------|
| `submitCrew(data)` | `POST /crews` | 提交编排执行 |
| `validateCrew(data)` | `POST /crews/validate` | 校验 YAML 配置 |
| `getCrews(params)` | `GET /crews` | 列出编排执行记录 |
| `getCrewDetail(id)` | `GET /crews/{execution_id}` | 获取编排详情 |
| `abortCrew(id)` | `POST /crews/{execution_id}/abort` | 中止编排 |
| `deleteCrew(id)` | `DELETE /crews/{execution_id}` | 删除编排记录 |
| `listCrewConfigs(workspace)` | `GET /crews/configs` | 列出 workspace 配置 |
| `getCrewConfig(filename, ws)` | `GET /crews/configs/{filename}` | 获取配置文件内容 |
| `saveCrewConfig(filename, ws, content)` | `PUT /crews/configs/{filename}` | 保存配置文件 |

### 2.5 Types 扩展

在 `src/extension/types.ts` 和 `src/webview/src/types.ts` 中新增：

```typescript
// 编排相关类型（两端共享）
interface OrchestratorType = 'pipeline' | 'supervisor-worker' | 'round-table' | 'broadcast' | 'consensus' | 'composite'
interface ExecutionStatus = 'pending' | 'running' | 'completed' | 'failed' | 'aborted'
interface PhaseResult { name, status, agents, output?, error?, started_at?, completed_at? }
interface CrewExecution { execution_id, session_id, crew_name, description, orchestrator_type, agent_count, status, error?, result?, phases?, phases_total?, progress?, created_at, completed_at? }
interface CrewConfigFile { filename, path, name, description, orchestrator_type, agent_count, agent_names, modified_time, parse_error? }
interface CrewConfigDetail { filename, path, content, summary, modified_time }

// Session 扩展
interface Session { ..., category?: 'normal' | 'agent-orchestration' }
interface CreateSessionParams { ..., category?: string }
interface CreateSessionResponse { ..., category?: string }
```

### 2.6 Commands 注册

在 `activation.ts` 中新增 VS Code 命令：

| 命令 ID | 功能 | 触发方式 |
|---------|------|---------|
| `broca.submitCrew` | 提交当前 workspace 的编排配置 | 命令面板 / 会话树右键 |
| `broca.openCrewList` | 打开编排执行记录列表 | 命令面板 / 会话树右键 |
| `broca.refreshCrews` | 刷新编排执行列表 | 命令面板 |

> **Panel 内部控制**：`broca.openCrewDetail`（查看详情）、`broca.abortCrew`（中止）、`broca.deleteCrew`（删除）等操作通过执行管理 Panel 的 WebView 消息协议（见 §2.7）由 extension host 响应处理，无需注册为全局命令。

### 2.7 WebView 消息协议扩展

在 `WebViewMessage` / `ExtensionToWebView` 类型中新增消息类型：

**Extension → WebView**（新增）：
- `crewExecutions` — 编排执行列表
- `crewDetail` — 编排执行详情
- `crewEvent` — 实时编排事件推送
- `crewConfigs` — workspace 配置文件列表
- `crewConfigDetail` — 配置文件内容

**WebView → Extension**（新增）：
- `fetchCrewExecutions` — 请求编排列表
- `fetchCrewDetail` — 请求编排详情
- `submitCrew` — 提交编排
- `abortCrew` — 中止编排
- `deleteCrew` — 删除编排记录
- `fetchCrewConfigs` — 请求配置文件列表
- `fetchCrewConfigDetail` — 请求配置文件内容
- `saveCrewConfig` — 保存配置文件

---

## 三、UI 布局参考

### 3.1 编排执行管理页面（含进度 DAG）

通过独立 WebView Panel（`broca.crews`）实现，包含列表和详情两个视图，DAG 进度展示在详情面板中。

**列表视图**：

```
┌─────────────────────────────────────────────┐
│  🔗 编排管理    [刷新]                       │
├─────────────────────────────────────────────┤
│  [全部状态 ▼]  共 N 条                       │
├─────────────────────────────────────────────┤
│  ┌─────────────────────────────────────┐    │
│  │ [运行中] 辩论实验     pipeline      │    │
│  │ Agent: 3个  阶段: 2/5              │    │
│  │ ████████████░░░░░░░ 60%            │    │
│  │ [查看进度] [中止] [删除]            │    │
│  └─────────────────────────────────────┘    │
│  ┌─────────────────────────────────────┐    │
│  │ [已完成] 代码审查    round-table    │    │
│  │ Agent: 4个  阶段: 3/3              │    │
│  │ ████████████████████ 100%           │    │
│  │ [查看进度] [删除]                   │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

**详情/进度 DAG 面板**（点击「查看进度」展开）：

```
┌─────────────────────────────────────────┐
│ 编排详情 — 辩论实验                      │
├─────────────────────────────────────────┤
│ 执行状态: 运行中    ████████░░ 80%       │
│ 拓扑类型: pipeline   Agent: 3个          │
├─────────────────────────────────────────┤
│ ● 分析需求         [completed] ✔        │
│   └ agent: analyst                      │
│ ● 生成代码         [running] 🔄         │
│   └ agent: coder                        │
│ ● 审查代码         [pending] ⏳          │
│   └ agent: reviewer                     │
├─────────────────────────────────────────┤
│ 执行结果（完成后展示）                    │
│ ┌──────────────────────────────────┐   │
│ │ { "final_output": ... }          │   │
│ └──────────────────────────────────┘   │
├─────────────────────────────────────────┤
│   [查看聊天日志]  [中止]  [删除]         │
└─────────────────────────────────────────┘
```

**布局要点**：
- 列表视图 + 详情面板 = 主从结构（类似 broca-web 的 list + drawer）
- 详情面板在 VS Code 中可以用右侧 WebView Panel 或 overlay 面板实现
- 进度 DAG 参照 broca-web 的 `CrewProgressDag.vue`，包含：整体进度条、阶段节点列表（每节点含名称/状态图标/Agent标签/错误信息）
- 每条执行记录提供「查看聊天日志」按钮，点击后打开聊天 Panel 并传入 `execution_id` 参数过滤消息

**导航闭环**：
```
会话树点击编排会话
    ↓
执行管理 Panel（当前 session 的执行记录列表）
    ├── 点击执行记录 → 详情 DAG 进度面板
    └── 点击「查看聊天日志」 → 聊天 Panel（只读模式，按 execution_id 过滤）
                              └── 点击「返回编排管理」 → 回到执行管理 Panel
```

### 3.2 创建会话对话框增强

在现有 Create Session 表单中增加分类选择，放在 description 字段上方：

```
┌─ Create Session ──────────────────────┐
│                                       │
│ 会话类型:                              │
│ ○ 普通会话                            │
│   创建内置 Agent，适合日常对话和任务      │
│ ● Agent 编排会话                       │
│   从工作空间加载自定义 Agent，适合多     │
│   Agent 编排工作流                     │
│                                       │
│ Description: [                  ]     │
│ LLM Provider: [select ▼]              │
│ LLM Model: [select ▼]                 │
│ Workspace: [........................]  │
│                                       │
│            [Cancel] [Create Session]   │
└───────────────────────────────────────┘
```

---

## 四、工作拆分建议

### Phase 1 — 基础适配（P0，核心功能）

1. **Types 扩展**：在 extension 和 webview 两侧的类型定义中新增编排相关类型
2. **API 扩展**：`ApiClient` 新增 Crew 相关 REST 接口
3. **会话创建增强**：`openCreateSessionDialog` 增加 category 字段
4. **WebView 只读模式**：根据 category 切换 ChatInput 显示/隐藏，显示只读提示
5. **Extension 消息协议**：新增 crew 相关消息类型的传输和处理

### Phase 2 — 编排管理（P1）

1. **编排执行管理 Panel**：实现 `broca.crews` 独立 WebView Panel，包含执行记录列表
2. **详情 DAG 进度面板**：列表项点击后展开详情视图，内嵌进度 DAG 展示（参照 `CrewProgressDag.vue`）
3. **Socket 事件订阅**：extension host 为执行管理 Panel 订阅 `crew:session_id` 频道，实时推送进度事件更新 DAG
4. **Commands 注册**：新增编排相关 VS Code 命令

### Phase 3 — 增强功能（P2）

1. **配置文件操作**：支持从 VS Code 中直接读取/列出 workspace 的 `crew_configs/`
2. **会话树增强**：编排会话特殊图标和状态展示

---

## 五、与 broca-web 的关键差异

| 特性　　　　 | broca-web　　　　　　　　　　　　　| broca-vscode　　　　　　　　　　　　　　　　　　　　　　　 |
| --------------| ------------------------------------| ------------------------------------------------------------|
| YAML 编辑器　| 内置 `CrewYamlEditor.vue` 组件　　 | **不需要**，利用 VS Code 原生 YAML 编辑能力　　　　　　　　|
| 编排管理入口 | 独立路由 `/crews`　　　　　　　　　| 独立 WebView Panel　　　　　　　　　　　　　　　　　　　　 |
| 实时推送　　 | Socket.IO 原生支持（浏览器）　　　 | 扩展层已有 Socket.IO 集成，订阅 `crew:session_id` 频道即可 |
| 工作空间关联 | 通过 session 的 workspace 自动关联 | 通过 VS Code 当前打开的文件夹路径关联　　　　　　　　　　　|
| 编排配置创建 | UI 内编辑和保存　　　　　　　　　　| 用户在 VS Code 中直接编辑 `crew_configs/*.yaml`　　　　　　|
