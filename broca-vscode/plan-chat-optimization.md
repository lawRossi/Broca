# broca-vscode Chat 插件版优化方案

> 目标：基于 broca/web/frontend 的 Chat 功能，对 broca-vscode 插件版的 Chat 页面进行全面交互和 UI 对齐

---

## 一、架构差异概述

| 维度 | Web 版 (broca/web/frontend) | VSCode 插件版 (broca-vscode) |
|------|----------------------------|------------------------------|
| **通信方式** | Socket.IO 直连后端（`brocaSocket.ts`） | postMessage ↔ Extension Host 中转 |
| **状态管理** | 6 个 Pinia Store（chat / socket / agent / session / user / job / task） | 1 个 Pinia Store（chat.ts） |
| **UI 框架** | Element Plus + Tailwind CSS | 纯 CSS（VSCode 主题变量映射） |
| **布局** | 三栏式（AgentSidebar + 消息区 + ChatInfoSidebar） | 单栏垂直 |
| **路由** | Vue Router（`/chat/:session_id?`） | 无路由（initData 直接注入） |
| **组件数** | Chat 相关 12 个组件 | Chat 相关 8 个组件 |

---

## 二、组件级差异详解

### 2.1 App.vue — 主视图编排

| 对比项 | Web 版 | VSCode 插件版 |
|--------|--------|--------------|
| **布局** | 三栏：AgentSidebar \| ChatMessageList+ChatInput \| ChatInfoSidebar | 单栏：RunnerStatusBar → ChatMessageList → ChatInput |
| **加载状态** | LoadingOverlay 组件 | 无 |
| **额外组件** | ChatHeader（顶部标题/连接状态/侧栏切换） | RunnerStatusBar（连接+进程状态） |
| **生命周期** | init() + autoConnectAndSubscribe() + cleanup() | init() 仅注册 onMessage 监听 |

**缺失：**
- 无 LoadingOverlay
- 无三栏布局
- 无 ChatHeader

### 2.2 ChatHeader.vue — 顶部状态栏

| 对比项 | Web 版 | VSCode 插件版 |
|--------|--------|--------------|
| **标题** | "Broca" 粗体标题 | 无（由 RunnerStatusBar 替代） |
| **连接状态** | `<el-tag>` 显示 connected/connecting/disconnected | RunnerStatusBar 中圆点指示 |
| **侧栏切换** | 移动端侧栏切换按钮（⚙️/📊） | 无 |
| **额外** | 无 | RunnerStatusBar 同时显示 Runner 进程状态 |

**优化方向：**
- 保留 RunnerStatusBar 的功能（连接状态 + 进程状态），但可增强为更丰富的 Header
- 可增加 "返回会话列表" 等快捷操作

### 2.3 ChatMessageList.vue — 消息列表

| 对比项 | Web 版 | VSCode 插件版 |
|--------|--------|--------------|
| **滚动加载历史** | loadMoreHistory + 滚动位置保持（saveScrollState / restoreScrollState） | 基本 loadMoreHistory，无位置保持 |
| **自动滚动** | 按 messages.length 和 content 变化双监听 | 同 |
| **加载指示器** | "加载中..." + "没有更多历史消息" | "Loading more..." |
| **空状态** | 区分 "正在自动连接" / "已连接，等待消息" / "未设置session_id" | "Connecting..." / "Connected..." |
| **重做按钮** | `<el-button>` 圆角样式 | 基本 `<button>` |
| **加载更多触发** | scrollTop < 50 + 保存/恢复滚动状态 | scrollTop < 50 |

**缺失：**
- 无滚动位置保持（加载历史后页面跳跃）
- 无加载完成提示（"没有更多历史消息"）

### 2.4 ChatMessageItem.vue — 单条消息（最大差异）

| 对比项 | Web 版 | VSCode 插件版 |
|--------|--------|--------------|
| **消息图标** | 按类型显示不同 emoji（👤/🤖/🔧/⚠️） | 仅 tool_call 显示 🔧 |
| **发送者名称** | "You → @AgentName"（显示 @mention 目标） | "You" 或 agentName |
| **时间格式** | formatBeijingTimeShort | toLocaleTimeString |
| **背景色** | 颜色编码：蓝/绿/紫/灰 + 左边框指示条 | 纯色背景（bg-tertiary） |
| **Markdown 渲染** | ✅ 完整样式（h1-h6/table/blockquote/code/pre/img/strong/em/del/hr） | ✅ 基础（marked + breaks + gfm） |
| **推理内容** | ▶ 思考 展开/收起 + 琥珀色底色 | 🧠 Reasoning 展开/收起 + 灰色底色 |
| **文件附件** | 点击打开 FilePreview 弹窗（显示图标+名称+大小+类型） | `<a>` 链接新标签打开 |
| **撤销按钮** | hover 显示 "↩️ 撤销" + ElMessageBox 确认 | 无 |
| **用户消息渲染** | `<pre>` 纯文本 | 同 |

**特殊工具调用渲染（核心缺失）：**

| 工具类型 | Web 版 | VSCode 插件版 |
|---------|--------|--------------|
| **edit_file** | ✅ Diff 展示（`diff` 库计算，+/- 行标记，暗色模式适配） | ❌ 仅展示 JSON 参数 |
| **write_file** | ✅ 文件内容预览（紫色底色，可滚动） | ❌ 仅展示 JSON 参数 |
| **read_file** | ✅ 文件内容预览 | ❌ 仅展示 JSON 参数 |
| **todo_management** | ✅ Todo 列表渲染（✅/⏳/⬜️ 状态图标） | ❌ 仅展示 JSON 参数 |
| **ask_user** | ✅ 问题 + 选项列表渲染 | ❌ 仅展示 JSON 参数 |
| **其他工具** | JSON 格式化展示 | JSON 格式化展示 |

**消息状态管理（messageStates）：**
- Web 版：每个消息的 showParameters / showResult / showReasoning 存储在 chatStore.messageStates Map 中
- VSCode 版：每个 ChatMessageItem 组件内部使用 ref 管理展开状态（showParameters / showResult / showReasoning）
- ⚠️ 组件内状态在虚拟滚动或重渲染时会丢失

### 2.5 ChatInput.vue — 输入组件

| 对比项 | Web 版 | VSCode 插件版 |
|--------|--------|--------------|
| **@mention 智能提示** | ✅ 输入 @ 后弹出过滤列表，键盘上下选择，Enter 确认，Escape 关闭 | ❌ 仅用正则 `@(\w+)` 简单解析，无 UI 提示 |
| **文件上传** | Supabase Storage（带进度条、上传状态） | Supabase Storage（基本版） |
| **/redo 命令** | ✅ handleSendMessage 中检测 `/redo` → 调用 socketStore.sendRedo | ❌ 无 |
| **禁用遮罩** | 通过 disabled 属性禁止输入 | 透明遮罩层覆盖输入区 |
| **目标agent提示** | "发送给: @AgentName" 显示当前目标 | 无 |
| **UI 控件** | Element Plus `<el-input>` + `<el-button>` | 原生 `<textarea>` + `<button>` |
| **输入框** | el-input（Element Plus） | textarea（原生） |
| **发送快捷键** | Enter 发送，无 Shift+Enter 换行 | Enter 发送，Shift+Enter 换行 |
| **文件按钮禁用** | runner 未运行或正在上传时禁用 | supabase 未配置时禁用 |
| **文件预览外观** | 带边框颜色编码（红/绿/蓝）+ 进度条 | 基本文字+上传状态 |

**缺失：**
- @mention 智能提示列表
- /redo 命令支持
- 目标 agent 显示
- 文件上传进度条

### 2.6 ChatInfoSidebar.vue — 信息侧栏（完全缺失）

**功能模块：**
1. **Session Info 面板**
   - Session ID 显示
   - Total Messages 统计
   - Jobs 数量（可点击跳转）
   - Tasks 数量（可点击跳转）
2. **Runner Status 面板**
   - 进程状态标签（运行中/启动中/异常/已停止）+ 颜色编码
   - PID 显示
   - 运行时长（格式化）
   - CPU / 内存使用率
   - 启动/停止/重启操作按钮
   - 手动刷新按钮
3. **Message Statistics 面板**
   - User Messages 计数
   - Assistant Responses 计数
   - System Messages 计数
   - Tool Call Errors 计数（异常时高亮）
   - Tool Calls 计数
   - 手动刷新按钮（带 auto-refresh 提示）
4. **数据来源**
   - `sessionApi.getSessionStats()` — 消息类型统计
   - `jobApi.getJobs()` — Job 数量
   - `taskApi.getTasks()` — Task 数量
   - `sessionApi.getRunnerStatus()` — Runner 信息（每 10s 轮询）

### 2.7 AgentSidebar.vue — Agent 侧栏（完全缺失）

**功能模块：**
1. Agent 列表（图标 + 名称 + 状态颜色标签）
2. Agent 运行时状态（idle/running/connecting/disconnected）
3. 选中 Agent 的配置展示（从 API 获取 agentConfig）
4. Agent 配置详情弹窗
5. 自动刷新机制

**Agent 状态更新流程（Web 版）：**
- `turn_start` → agent.status = 'running'
- `turn_end` → agent.status = 'idle'
- `agent_response` / `tool_call` → agent.status = 'running'

### 2.8 PermissionDialog.vue + AgentQueryDialog.vue（基本对齐）

两个弹窗组件在 Web 版和 VSCode 版基本功能一致，差异较小：

| 对比项 | Web 版 | VSCode 插件版 |
|--------|--------|--------------|
| **技术实现** | Element Plus `<el-dialog>` + `<el-button>` | 纯 CSS + Teleport（无 UI 库） |
| **布局样式** | Element Plus 主题 | 自定义遮罩 + 卡片 |
| **功能** | 权限请求/问答弹窗 | 同 |

### 2.9 RunnerStatusBar.vue（VSCode 特有）

VSCode 版独有的组件，Web 版中 Runner 状态在 ChatInfoSidebar 中展示。

| 功能 | 实现 |
|------|------|
| 连接状态 | 圆点指示器（绿/黄） + "Connected"/"Connecting..." |
| Runner 状态 | 圆点指示器（绿/黄/红/灰） + "Running"/"Starting..."/"Error"/"Stopped" |

---

## 三、Store 层差异

### 3.1 chat.ts（核心差异）

| 功能 | Web 版（~400 行） | VSCode 插件版（~310 行） |
|------|------------------|------------------------|
| **消息处理** | processMessage + addMessageToList（含 pendingChunks 池化管理）| processMessage + addMessage（直接合并） |
| **agent_response 合并** | pendingChunks Map 收集所有 chunk → mergeAgentResponseChunks 排序合并 | 直接查找相同 message_id 合并 |
| **工具调用状态追踪** | messageStates Map（每个消息的展开状态） | 组件内 ref |
| **消息过滤** | 完整过滤逻辑 | 基本一致 |
| **Runner 管理** | fetchRunnerStatus / restartRunner / stopRunner + 10s 轮询 | 无（由 Extension Host 推送 `runnerStatus` 事件） |
| **撤销/重做** | 通过 socketStore.sendUndo / sendRedo + ElMessage 反馈 | 通过 postMessage 发送 'undo'/'redo' |
| **Session 管理** | autoConnectAndSubscribe / cleanupSession / loadHistory（API 直连） | init（onMessage 注册）+ loadHistory（postMessage 中转）|
| **侧栏状态** | showLeftSidebar / showRightSidebar / isMobile / toggle | 无 |
| **响应响应** | respondPermission / respondUserAnswer（通过 socketStore） | respondPermission / respondAgentQuery（通过 postMessage） |

### 3.2 socket.ts — VSCode 无此 Store

Web 版的 Socket Store 封装了：
- WebSocket 连接/断开/订阅管理
- 事件回调钩子（onConnect / onDisconnect / onMessage / onTurnStart / onTurnEnd / onAgentResponse / onToolCall / onPermissionRequest / onAgentQuery）
- 消息发送方法（sendUserMessage / sendAbort / respondPermission / sendUserAnswer / sendUndo / sendRedo）
- 连接状态管理

VSCode 版中，这部分功能分散在：
- Extension Host（实际 Socket.IO 连接维护）
- api/vscode.ts（postMessage 通信桥）
- stores/chat.ts（onMessage 回调注册 + 消息分发）

### 3.3 agent.ts — VSCode 无此 Store

Web 版的 Agent Store 管理：
- Agent 列表（从 sessionApi.getSessionAgents 获取）
- Agent 状态更新（idle / running / connecting / disconnected）
- @mention 解析（parseMention — 匹配 agent name）
- Agent 配置获取/缓存
- currentAgentId / currentAgentName（默认发送目标）

VSCode 版中：Extension Host 通过 'agents' 事件推送 agents 信息，chatStore 中仅存储 `agentNames` 映射表用于显示名称。

---

## 四、功能缺失清单（按优先级）

### P0 — 核心交互缺失（严重影响用户体验）

| # | 功能 | Web 版 | VSCode 插件版 | 影响 |
|---|------|--------|--------------|------|
| 1 | **@mention 智能提示** | 输入 @ 弹出过滤列表，可键盘选择 | 仅正则解析，无 UI | 用户无法直观看到可选 Agent |
| 2 | **edit_file Diff 展示** | 行级 diff（+/- 标记），暗色模式 | 仅显示 JSON 参数 | 无法直观查看代码变更 |
| 3 | **todo_management 渲染** | 待办列表（✅/⏳/⬜️） | 仅显示 JSON | 无法直观查看任务状态 |
| 4 | **ask_user 渲染** | 问题 + 选项列表展示 | 仅显示 JSON | 无法直观查看 Agent 提问 |
| 5 | **write_file / read_file 内容预览** | 代码内容直接展示 | 仅显示 JSON | 无法直观查看文件内容 |

### P1 — 重要功能缺失

| # | 功能 | 说明 |
|---|------|------|
| 6 | **AgentSidebar（左侧 Agent 列表）** | 显示所有 Agent 及其状态，选择目标 Agent |
| 7 | **ChatInfoSidebar（右侧信息侧栏）** | Session 信息、Runner 管理（启/停/重启）、消息统计 |
| 8 | **消息撤销按钮（hover 显示）** | hover 消息时显示 "↩️ 撤销"，含确认弹窗 |
| 9 | **消息滚动位置保持** | 加载历史后保持当前滚动位置不跳跃 |
| 10 | **/redo 命令支持** | 输入 `/redo` 触发重做 |

### P2 — UI 对齐优化

| # | 功能 | 说明 |
|---|------|------|
| 11 | **消息背景色编码** | 用户消息蓝色、Agent 消息绿色、工具调用紫色、系统消息灰色 + 左边框 |
| 12 | **消息图标按类型显示** | 👤 用户 / 🤖 Agent / 🔧 工具 / ⚠️ 错误 |
| 13 | **发送者名称显示 @mention** | "You → @AgentName" 或 "@SenderName" |
| 14 | **文件预览弹窗** | 点击文件附件弹出 FilePreview 查看内容 |
| 15 | **推理内容样式优化** | 采用琥珀色底色 + 左边框样式 |
| 16 | **Runner 状态管理面板** | 显示 PID/运行时长/CPU/内存，提供启停操作 |
| 17 | **加载更多提示** | "没有更多历史消息了" 和 "加载中..." |

### P3 — 体验细节完善

| # | 功能 | 说明 |
|---|------|------|
| 18 | **空状态优化** | 区分 "正在连接" / "已连接，等待消息" / "未设置 session" |
| 19 | **消息时间格式化** | 使用北京时间格式 |
| 20 | **Agent 状态更新** | 根据 turn_start/end/tool_call 更新 Agent 运行状态 |
| 21 | **文件上传进度条** | 显示上传进度百分比 |
| 22 | **LoadingOverlay** | 页面加载时显示遮罩 |
| 23 | **消息展开状态持久化** | 组件内 ref → Store 层管理（避免重渲染丢失） |

---

## 五、优化实施建议

### 5.1 第一阶段（P0 — 核心差异化功能）

**目标**：补齐最影响用户体验的工具调用渲染

1. **ChatMessageItem.vue 增强**
   - 实现 `edit_file` Diff 展示（复用 `diff` 库，参考 Web 版 `computeDiff` 逻辑）
   - 实现 `todo_management` Todo 列表渲染
   - 实现 `ask_user` 问题+选项展示
   - 实现 `write_file` / `read_file` 内容预览
   - 实现按消息类型设置不同的背景色和图标

2. **ChatInput.vue 增强**
   - 实现 @mention 智能提示列表（监听 @ 输入 → 过滤 agents → 键盘选择）
   - 实现 `/redo` 命令检测

### 5.2 第二阶段（P1 — 重要功能补充）

**目标**：补齐侧栏、撤销、滚动等交互功能

1. **新增 AgentSidebar 组件**
   - 从 Extension Host 获取 agents 列表
   - 显示 Agent 状态（idle/running/connecting/disconnected）
   - Agent 选择与切换

2. **新增 ChatInfoSidebar 组件**
   - Session 信息面板（ID/消息数/Jobs/Tasks）
   - Runner 状态面板（状态/PID/运行时长/CPU/内存 + 启停按钮）
   - 消息统计面板（按类型分类计数）

3. **聊天消息撤销功能**
   - ChatMessageItem hover 显示撤销按钮
   - 确认弹窗（ElMessageBox → 纯 CSS 实现）
   - 通过 postMessage 发送 undo 命令
   - 接收 command_result 后刷新消息列表

4. **滚动位置保持**
   - 加载历史前保存 scrollTop/scrollHeight
   - 加载后计算高度差并恢复 scrollTop

### 5.3 第三阶段（P2 — UI 对齐优化）

**目标**：视觉风格与 Web 版一致

1. **消息样式对齐**
   - 使用颜色编码背景（蓝/绿/紫/灰 + 左边框）
   - 图标按类型显示
   - 发送者名称格式统一
   
2. **文件预览**
   - 新增 FilePreview 组件（支持通过 URL 或路径预览文件）

3. **Runner 状态管理**
   - RunnerStatusBar 增强为可点击展开详情面板
   - 或在新侧栏中展示完整 Runner 信息

4. **加载提示优化**
   - 区分空状态场景
   - 加载完成提示

### 5.4 第四阶段（P3 — 体验细节完善）

**目标**：打磨细节，提升整体体验

1. 消息状态管理迁移到 Store（防止组件重渲染丢失展开状态）
2. 时间格式化统一
3. Agent 运行状态同步（利用 turn_start/turn_end 事件）
4. 文件上传进度条
5. LoadingOverlay 实现

---

## 六、通信协议注意事项

VSCode 插件版通过 postMessage ↔ Extension Host 通信，所有需要后端 API 的功能（如 Runner 管理、Session 统计）需要通过 Extension Host 中转。

### 需新增的通信协议

| 方向 | type | payload | 说明 |
|------|------|---------|------|
| WebView → Host | `fetchSessionStats` | `{ sessionId }` | 获取 Session 统计数据 |
| Host → WebView | `sessionStats` | `SessionStats` | 返回统计数据 |
| WebView → Host | `fetchRunnerAction` | `{ sessionId, action: 'start'|'stop'|'restart' }` | Runner 操作 |
| Host → WebView | `runnerActionResult` | `{ success, error? }` | 操作结果 |
| WebView → Host | `fetchAgents` | `{ sessionId }` | 获取 Agent 列表 |
| Host → WebView | `agents` | `{ agents, defaultAgentId }` | 已有此协议，可复用 |
| WebView → Host | `fetchAgentConfig` | `{ sessionId, agentId }` | 获取 Agent 配置 |
| WebView → Host | `openFile` | `{ path }` | 在 VSCode 中打开文件 |

---

## 七、文件改动清单

### 修改文件（6 个）

| 文件 | 改动内容 |
|------|---------|
| `src/stores/chat.ts` | 新增 messageStates 管理、Agent 状态、Runner 操作接口、滚动位置保持状态 |
| `src/components/ChatMessageItem.vue` | 增强工具调用渲染（diff/todo/ask_user/write_file/read_file）、消息样式、撤销按钮 |
| `src/components/ChatMessageList.vue` | 滚动位置保持、加载完成提示、空状态优化 |
| `src/components/ChatInput.vue` | @mention 智能提示、/redo 命令、目标 agent 显示 |
| `src/App.vue` | 引入新组件、调整布局 |
| `src/api/vscode.ts` | 新增通信协议类型 |

### 新增文件（4 个）

| 文件 | 说明 |
|------|------|
| `src/components/AgentSidebar.vue` | 左侧 Agent 列表侧栏 |
| `src/components/ChatInfoSidebar.vue` | 右侧信息侧栏（Session/Runner/统计） |
| `src/components/FilePreview.vue` | 文件预览弹窗 |
| `src/components/LoadingOverlay.vue` | 加载遮罩组件 |

### 可复用逻辑（参考 Web 版）

| Web 版文件 | 复用到 VSCode 插件版 |
|-----------|-------------------|
| `ChatMessageItem.vue` 的 `computeDiff()` / `isEditFile()` / `getEditFileParams()` / Diff CSS 样式 | `ChatMessageItem.vue` |
| `ChatMessageItem.vue` 的 `isTodoManagement()` / `getTodos()` / Todo CSS 样式 | `ChatMessageItem.vue` |
| `ChatMessageItem.vue` 的 `isAskUser()` / `getAskUserParams()` / `getAskUserResult()` | `ChatMessageItem.vue` |
| `ChatMessageItem.vue` 的 `isWriteFile()` / `getWriteFileContent()` | `ChatMessageItem.vue` |
| `ChatMessageItem.vue` 的 `isReadFile()` | `ChatMessageItem.vue` |
| `ChatMessageItem.vue` 的悬浮撤销按钮逻辑 + ElMessageBox 确认 | `ChatMessageItem.vue` |
| `ChatMessageItem.vue` 的 FilePreview 集成 | `ChatMessageItem.vue` + `FilePreview.vue` |
| `ChatInput.vue` 的 @mention 智能提示（watch + 过滤 + 键盘事件 + 选择逻辑） | `ChatInput.vue` |
| `ChatInput.vue` 的 `/redo` 命令检测 | `ChatInput.vue` |
| `ChatMessageList.vue` 的 `saveScrollState()` / `restoreScrollState()` | `ChatMessageList.vue` |
| `ChatInfoSidebar.vue` 的逻辑 | `ChatInfoSidebar.vue`（需适配 postMessage 通信） |
| `AgentSidebar.vue` 的逻辑 | `AgentSidebar.vue`（需适配 postMessage 通信） |

---

## 八、UI 框架注意事项

VSCode 插件版使用纯 CSS 且无 Element Plus / Tailwind 可用，所有 UI 对齐需注意：

1. **Element Plus 组件替代方案**
   - `<el-tag>` → CSS class + `--button-bg` 等主题变量
   - `<el-button>` → 原生 `<button>` + CSS class
   - `<el-input>` → `<textarea>` 或 `<input>`
   - `<el-icon>` → emoji 或 SVG
   - `<el-dialog>` → 纯 CSS 弹窗（已有 PermissionDialog 示范）
   - `<el-message-box>` → 自定义确认弹窗
   - `<el-tooltip>` → CSS `:hover` + `::after` 伪元素

2. **CSS 变量复用**
   - 已有的 `theme.ts` 已映射 VSCode 主题变量，可直接使用
   - 新增变量按需添加（如 `--message-user-bg`、`--message-agent-bg` 等）

3. **响应式布局**
   - VSCode WebView 宽度由插件控制（通常固定），无需复杂的响应式
   - 侧栏可采用抽屉式（slide-in）而非 Web 版的 grid 布局

---

## 九、总结

本次优化共涉及 **10 个文件**（6 修改 + 4 新增），核心目标是让 VSCode 插件版的 Chat 在交互和 UI 上全面对齐 Web 版。最关键的三项工作是：

1. **工具调用渲染增强**（edit_file diff、todo_management 列表、ask_user 问题、write_file/read_file 内容预览）
2. **输入体验提升**（@mention 智能提示、/redo 命令）
3. **侧栏信息面板补齐**（Agent 列表、Session/Runner 信息、消息统计）

建议按 P0→P1→P2→P3 的优先级分阶段实施，每个阶段完成后即可发布，逐步提升用户体验。
