# VSCode 插件 — Chat 交互模块设计方案

## 1. 概述

在 VSCode 中实现聊天交互面板，用户可以在侧边栏或编辑器中与 Broca Agent 进行实时对话。功能对标 Web 版的 Chat.vue，针对 VSCode 环境做适配。

## 2. UI 布局

### 2.1 展示位置

#### 关键确认点

> **Q1**: Chat 面板展示在什么位置？
>
> - 方案A: **侧边栏（Side Panel）** — 在侧边栏中打开一个 WebView，与 Session 管理同侧但独立标签
>   - 优点：不占用编辑器空间，与 Session 管理集成度高
>   - 缺点：侧边栏宽度有限，展开/收起不方便
> - 方案B: **编辑器标签页（Editor Tab）** — 在编辑器区域打开一个 WebView 标签
>   - 优点：空间充裕，支持分屏（并排看代码和聊天）
>   - 缺点：标签页多了容易混乱
> - 方案C: **新的侧边栏（Secondary Sidebar）** — VSCode 1.84+ 支持右侧辅助侧边栏
>   - 优点：左右分屏，同时看文件树和聊天
>   - 缺点：需要 VSCode 新版支持，可能影响兼容性
>
> 倾向方案 B（编辑器标签页），因为聊天需要较多空间展示消息列表、工具调用详情等。请确认。

### 2.2 界面组成

消息列表（从上到下）：
1. **消息记录** — 历史消息列表，支持滚动加载更多
2. **输入区域** — 固定在底部

每条消息包含：
- 发送者标识（用户 / Agent 名称 + 头像/图标）
- 消息内容（Markdown 渲染）
- 时间戳
- 消息类型指示（tool_call, system_message 等）

## 3. 核心功能

### 3.1 连接与会话

- 从 Session 列表点击 "Open in Chat" → 创建/打开一个 WebView 标签
- 标签标题显示为 Session 描述或 ID
- WebView 内部自动执行：
  1. 通过 Socket.IO 连接到后端
  2. 订阅该 Session 的消息频道
  3. 加载历史消息
  4. 启动 Runner 状态轮询

### 3.2 消息列表

- 消息按时间顺序从上到下排列
- 自动滚动到最新消息
- 滚动到顶部时触发历史消息加载（"加载更多"）
- 消息类型处理（同 Web 版）：
  - `user_message` — 用户消息，右对齐，显示用户名
  - `agent_response` — Agent 回复，Markdown 渲染，支持工具栏（tool_call）
  - `tool_call` — 工具调用记录，可展开/收起参数和结果
  - `system_message` — 系统消息，居中显示
  - `permission_request` — 权限请求（见 3.6）
  - `agent_query` — Agent 向用户提问（见 3.7）

### 3.3 消息发送

- 底部输入框（VSCode `createInputBox` 或 WebView 内输入框）
- 支持 `@mention` 指定目标 Agent
- 发送按钮 / Enter 发送

#### 关键确认点

> **Q2**: 输入框使用 VSCode 原生 InputBox 还是 WebView 内 Input？
>
> - 方案A: **VSCode InputBox API** — `window.createInputBox()`，原生交互，支持自动补全
>   - 优点：原生体验，支持 `@mention` 自动补全
>   - 缺点：在 WebView 外部，布局不统一，难以嵌入文件上传等功能
> - 方案B: **WebView 内输入框** — 在 HTML 中嵌入输入框，完全自定义
>   - 优点：可复用 ChatInput.vue 的逻辑，功能完整（文件上传、mention 提示等）
>   - 缺点：需要处理键盘事件与 VSCode 的交互
>
> 倾向方案 B，因为文件上传和 mention 提示在 Web 版已经有成熟实现，复用成本低。请确认。

### 3.4 文件上传

- 考虑 VSCode 插件的使用场景，**文件上传的典型场景**：
  - 上传截图/图片让 Agent 分析
  - 上传代码文件让 Agent 审查

#### 关键确认点

> **Q3**: 文件上传方式？（依赖 Q2 方案）
>
> - 方案A: **WebView 内嵌文件选择** — 使用 Web 版的 `<input type="file">` 实现
>   - 优点：复用现有逻辑
>   - 缺点：文件需先上传到 Supabase Storage 再传给后端
> - 方案B: **VSCode 文件 API** — 使用 `vscode.window.showOpenDialog` 选择文件，读取内容后通过消息传递
>   - 优点：与 VSCode 集成更好，可限制文件类型
>   - 缺点：实现路径不同，无法复用 Supabase 上传
> - 方案C: **直接传递文件路径** — 将文件路径作为消息参数发给后端，让后端自行读取
>   - 优点：最简单，无需上传
>   - 缺点：后端需要能访问本地文件系统（通过 Runner 可以）
>
> 倾向方案 C（直接传递文件路径），因为 Runner 运行在用户本地环境，可以直接读写文件。请确认。

### 3.5 Runner 管理

- 在聊天面板中显示 Runner 状态（运行中/已停止/异常）
- 提供启动/停止/重启按钮
- 状态轮询（每 10 秒）
- Runner 异常时提示用户重启

### 3.6 权限请求处理

- Agent 需要执行敏感操作时发送 `permission_request`
- WebView 内弹窗显示请求内容和原因
- 用户选择 "允许" / "拒绝" / "始终允许"

### 3.7 Agent 提问处理

- Agent 需要用户提供额外信息时发送 `agent_query`
- WebView 内弹窗显示问题和选项
- 用户选择或输入回答后提交

### 3.8 撤销与重做

- 消息列表上方显示撤销按钮（当有可撤销的 turn 时）
- 撤销成功后显示重做按钮
- 通过发送 `command: undo` / `command: redo` 实现

## 4. 与 Web 版的关键差异

| 功能 | Web 版 | VSCode 版 |
|------|--------|-----------|
| Agent 侧边栏 | 左侧 Agent 列表，显示 agent 状态和配置 | **简化为一个状态指示器**，点击后 QuickPick 切换 |
| 信息侧边栏 | 右侧 Runner 状态、消息统计等 | **集成到消息面板顶部**，不单独占用空间 |
| 文件上传 | Supabase Storage 上传 | **直接传文件路径**给后端 |
| 认证 | Supabase Auth | **复用插件层 token** |
| 权限/提问弹窗 | Element Plus Dialog | **WebView 内嵌弹窗**或 VSCode 原生弹窗 |
| 消息渲染 | 自定义 Markdown + 工具栏 | **可复用** Web 版的 ChatMessageItem 逻辑 |

### 关键确认点

> **Q4**: 权限请求和 Agent 提问使用什么方式展示？
>
> - 方案A: **VSCode 原生弹窗** — `window.showInformationMessage` + modal
>   - 优点：原生体验，简单
>   - 缺点：无法展示复杂 UI（如选项列表），交互有限
> - 方案B: **WebView 内嵌弹窗** — 在 WebView 中实现 Dialog 组件
>   - 优点：可复用现有组件，功能完整
>   - 缺点：与 VSCode UI 风格可能不一致
>
> 倾向方案 B（如果采用 WebView 展示 Chat），保持与 Web 版一致的交互体验。请确认。

## 5. 数据流

```
Session List (TreeView)
    │
    ├── "Open in Chat" 点击
    │   └── 打开 WebView Panel (editor tab)
    │       ├── 创建 WebView
    │       ├── 注入 HTML + JS
    │       └── 初始化连接
    │
    ├── WebView → Extension Host 通信 (postMessage)
    │   ├── ready → 插件开始初始化
    │   ├── getToken → 插件返回存储的 token
    │   ├── sendMessage(msg) → 插件调用 Socket.IO 发送
    │   ├── loadHistory(skip, limit) → 插件调用 API 获取
    │   ├── createConnection(sessionId) → 插件建立 Socket.IO
    │   ├── respondPermission(...) → 插件发送权限响应
    │   ├── respondAgentQuery(...) → 插件发送回答
    │   └── redo() / abort() → 插件发送命令
    │
    └── Extension Host → WebView 通信 (postMessage)
        ├── onMessage(msg) → 实时消息推送到 WebView
        ├── onConnected → 连接状态更新
        ├── onRunnerStatus(status) → Runner 状态更新
        ├── onHistoryLoaded(messages) → 历史消息数据
        └── onError(error) → 错误信息
```

## 6. WebView 代码复用策略

如果采用 WebView 方案，可复用 Web 版的 Vue 组件：

| 组件 | 复用程度 | 需要修改 |
|------|---------|----------|
| ChatMessageItem.vue | **高** | 消息渲染逻辑、tool_call 展开/收起几乎完全复用 |
| ChatMessageList.vue | **中** | 滚动加载逻辑复用，但数据源改为 WebView ↔ Extension 通信 |
| ChatInput.vue | **中** | 输入 + @mention 逻辑复用，文件上传改为路径模式 |
| ChatHeader.vue | **低** | 替换为 VSCode 风格标题栏 |
| PermissionDialog.vue | **高** | 仅需调整样式 |
| AgentQueryDialog.vue | **高** | 仅需调整样式 |

架构调整：
- **移除**：FileBrowser, WorkspacePicker, SessionSearchFilter 等无关组件
- **替换**：Element Plus UI → VSCode WebView UI (CSS Variables 适配 VSCode 主题)
- **新增**：VSCode 主题适配层，将 VSCode 的 CSS 变量映射到 WebView

## 7. 技术选型

### 关键确认点

> **Q5**: WebView 内使用什么前端框架？
>
> - 方案A: **Vue 3 + 编译打包** — 复用现有 Vue 组件，通过 Vite 构建为独立 JS 包注入 WebView
>   - 优点：代码复用率最高，组件化开发
>   - 缺点：构建配置复杂，需处理 VSCode 主题适配
> - 方案B: **原生 HTML/CSS/JS** — 手写轻量 UI，仅实现核心功能
>   - 优点：无框架依赖，加载快，体积小
>   - 缺点：开发成本高，需重写所有交互逻辑
> - 方案C: **React/Preact** — 使用更轻量的框架
>   - 优点：生态成熟
>   - 缺点：与现有 Vue 代码无法复用
>
> 倾向方案 A（Vue 3），最大化代码复用，降低开发成本。请确认。

---

## 总结：待确认决策项

| 编号 | 决策项 | 倾向方案 |
|------|--------|---------|
| SM-Q1 | Session 列表的 UI 实现方式 | 方案 C: TreeView + 原生交互 |
| SM-Q2 | 认证方式 | 方案 B: 通过后端 API 代理 |
| SM-Q3 | Session 列表创建交互 | QuickPick 收集参数 |
| CH-Q1 | Chat 面板展示位置 | 方案 B: 编辑器标签页 (WebView) |
| CH-Q2 | 输入框实现方式 | 方案 B: WebView 内输入框 |
| CH-Q3 | 文件上传方式 | 方案 C: 直接传递文件路径 |
| CH-Q4 | 权限/提问弹窗 | 方案 B: WebView 内嵌弹窗 |
| CH-Q5 | WebView 前端框架 | 方案 A: Vue 3 |
