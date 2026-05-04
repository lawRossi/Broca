# VSCode 插件 — Session 管理模块设计方案

## 1. 概述

在 VSCode 侧边栏（Activity Bar）中实现 Session 管理面板，功能对标 Web 版的 Sessions.vue，但针对 VSCode 环境做适配调整。

## 2. UI 布局

采用 VSCode 的 TreeView + WebView 混合方式：

- **主容器**：VSCode 的 `TreeDataProvider` 驱动的侧边栏视图（`broca.sessionManager`）
- **列表项**：每个 Session 为 TreeView 的一个 item，显示：
  - 会话描述（主文本）
  - Session ID（截断显示，monospace 字体）
  - Runner 状态指示器（颜色圆点 + 文字标签）
  - 工作空间路径（如果存在）
  - 创建时间

### 关键确认点

> **Q1**: Session 列表是纯 TreeView，还是用 WebView 实现富交互？
>
> - 方案A: **纯 TreeView** — 原生 VSCode 风格，交互简单，性能好，但 UI 定制能力有限（如无法在列表项内做内联编辑描述）
> - 方案B: **WebView** — 可复用现有 Vue 组件代码，交互丰富（内联编辑、拖拽等），但需要额外管理 WebView 生命周期
> - 方案C: **混合** — 列表用 TreeView，创建/编辑弹窗用 QuickPick 或 WebView
>
> 倾向方案 C，请确认。

## 3. 核心功能

### 3.1 Session 列表展示

- 从后端 API 获取当前用户的 session 列表
- **过滤逻辑**：只展示 `workspace` 与当前 VSCode 打开的项目路径（`vscode.workspace.workspaceFolders[0]`）**匹配** 的 session
  - 匹配规则：session.workspace 以当前项目路径为前缀，或相同路径
  - 如果 VSCode 未打开任何项目，则展示所有 session
- 列表按 `created_at` 降序排列
- 每个 item 展示 Runner 进程状态

### 3.2 创建 Session

- 点击 "+" 按钮或通过命令面板触发
- **简化创建流程**：
  - 自动获取当前 VSCode 项目根路径作为 `workspace` 参数
  - 弹出 QuickPick 让用户输入 `description`（可选）
  - 弹出 QuickPick 让用户选择 LLM Provider（可选，从 API 动态加载）
  - 弹出 QuickPick 让用户选择 Model（可选，依赖 Provider 选择）
  - 确认后调用 API 创建
- 创建成功后自动刷新列表

### 3.3 删除 Session

- 右键菜单项 "Delete Session"
- 确认弹窗（VSCode 原生 `showWarningMessage`）
- 调用 API 删除后刷新列表

### 3.4 Session 操作

右键菜单提供：
- **Open in Chat** — 打开该 Session 的聊天面板（见 Chat 交互方案）
- **Delete Session** — 删除确认
- **Copy Session ID** — 复制 ID 到剪贴板
- **Copy Workspace Path** — 复制工作空间路径（如果有）
- **Run Session** — 如果 runner 未运行，启动 runner
- **Stop Session** — 如果 runner 运行中，停止 runner
- **Restart Session** — 重启 runner 进程

### 3.5 状态同步

- 进入侧边栏时自动拉取 session 列表
- 手动刷新按钮（工具栏）
- 定时轮询 runner 状态（每 30 秒）

## 4. 与 Web 版的关键差异

| 功能 | Web 版 | VSCode 版 |
|------|--------|-----------|
| 认证 | Supabase Auth 完整流程 | **复用现有 token**，或集成 VSCode 认证 API |
| Workspace 选择器 | FileBrowser 组件浏览选择 | **自动使用**当前 VSCode 项目路径 |
| 文件浏览 | 独立的 Files 页面 | **不需要**，使用 VSCode 原生文件管理器 |
| 分页 | 有分页器 | **滚动加载**（VSCode 侧边栏风格） |
| 批量选择 | Checkbox + 批量操作栏 | **不需要**，VSCode 不适合批量操作 |
| 内联编辑描述 | 双击编辑 | 可以保留，但交互方式需适配 |
| Session 搜索 | 搜索输入框 | **可用**，置于列表上方 |

## 5. 认证与初始化

### 关键确认点

> **Q2**: VSCode 插件如何获取用户认证信息？
>
> ✅ **最终决策**：**方案A — Supabase 直接集成**
>
> 插件中直接内嵌 Supabase JS SDK，复用 Web 版的 auth 流程：
> - 登录/注册/登出均通过 Supabase Auth 完成
> - 获取到的 `access_token` 既用于后端 API 请求（`Authorization` header），也用于 Supabase Storage 文件上传
> - 可复用 Web 版 `user.ts` store 的完整逻辑

## 6. 数据流

```
VSCode Extension (TreeView)
    │
    ├── activate() → 初始化
    │   ├── 获取当前项目路径 (workspace.rootPath)
    │   ├── 读取存储的 token
    │   └── 注册侧边栏视图
    │
    ├── refresh() → 拉取 session 列表
    │   └── GET /api/session/sessions?keyword=&skip=0&limit=50
    │       └── 过滤 workspace.matches(projectPath)
    │
    ├── createSession() → 创建新 session
    │   ├── 自动填充 workspace = projectPath
    │   ├── QuickPick 收集 description / provider / model
    │   └── POST /api/session/sessions
    │
    ├── deleteSession(id) → 删除
    │   └── DELETE /api/session/{id}
    │
    ├── onDidChangeSession(event) → 监听切换
    │   └── 打开对应的 Chat WebView
    │
    └── dispose() → 清理
        └── 取消轮询、清理资源
```

## 7. 技术选型

### 关键确认点

> **Q3**: 使用什么方式渲染侧边栏 UI？
>
> - 方案A: **VSCode TreeView API** — `TreeDataProvider<T>` + `TreeItem`，原生性能，但功能有限
> - 方案B: **WebView API** — 在侧边栏中加载一个 WebView，可复用小部分 Vue 组件，但初始化成本高
> - 方案C: **仅用 TreeView**，交互弹窗使用 `window.showInputBox` / `window.showQuickPick` 等原生 API
>
> 倾向方案 C（TreeView + 原生交互），轻量且符合 VSCode UX 规范。创建/配置等复杂交互可考虑 WebView。请确认。
