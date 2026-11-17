# 前端与客户端

> [← 返回 README](../README.md)

Broca 提供三种客户端：Web 前端、TUI 终端界面、VS Code 扩展，均通过 Socket.IO 与后端实时交互。安装方式见 [快速开始](getting-started.md)。

## TUI 终端界面

`broca-tui/` — 基于 [Textual](https://textual.textualize.io/) 的终端用户界面

- **特性**：轻量级，无需浏览器或图形界面，直接在终端运行
- **组件**：会话列表、消息流、Agent 状态侧边栏、输入框、权限对话框
- **实时通信**：Socket.IO 客户端订阅 Agent 消息流
- **键盘快捷键**：`Ctrl+P` 切换会话、`Ctrl+N` 新建会话、`Ctrl+D` 删除会话
- **启动方式**：直接运行 `broca` 命令即可启动 TUI

## Web 前端

`broca-web/frontend/` — Vue 3 + TypeScript 单页应用

- **页面**：Auth（登录）、Home、Chat（对话）、Sessions（会话管理）、Crews（编排）、Files（文件浏览）、Jobs（任务）、Tasks（任务看板）、Settings（含 LLM / 运行参数配置）
- **组件**：消息列表、TurnCard、输入框、Agent 侧边栏、权限对话框、文件预览、Agent 提问对话框等
- **状态管理**：Pinia stores（chat、session、agent、socket、task、user）
- **实时通信**：Socket.IO 客户端订阅 Agent 消息流
- **特性**：Markdown 渲染、代码高亮、文件拖拽上传、主题切换、非阻塞追加消息提示、简洁模式过滤 `tool_injected` 消息、回到页面软刷新保留未发送草稿

## Web 后端

`broca-web/backend/` — FastAPI REST API 服务

- **API 路由**：sessions、session_runner、files（上传/raw 读取）、tasks、jobs、crews、commands、config、skills、tools、asr、user
- **SocketIO Runtime**：集成 Broca SocketIO Server 运行时
- **认证**：Supabase JWT token 验证
- **Runner 集成**：管理 Session Runner 子进程
- **会话删除**：调用 `SessionCleanupService` 清理媒体缓存、runner 日志、定时任务与快照仓库

环境变量与端口配置见 [配置参考](configuration.md)。

## VS Code 扩展

`broca-vscode/` — TypeScript 扩展

- 自定义 Chat Webview
- VS Code API 集成
- Socket.IO 实时通信
- 会话管理树视图
