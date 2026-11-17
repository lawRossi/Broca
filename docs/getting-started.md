# 快速开始与部署

> [← 返回 README](../README.md)

环境要求、安装部署、服务管理、CLI 命令以及各客户端的安装方式。

## 环境要求

| 依赖　　| 最低版本 | 说明　　　　　　　　　　　 |
| ---------| :--------:| ----------------------------|
| Python　| ≥ 3.12　 | 主语言　　　　　　　　　　 |
| pnpm　　| 任意版本 | Web 前端构建（可降级 npm） |
| Node.js | ≥ 18　　 | 前端构建　　　　　　　　　 |
| nginx　 | 任意版本 | 部署前端需要　　　　　　　 |

## 一键安装

```bash
# 克隆项目
git clone https://github.com/lawRossi/Broca && cd broca

# 一键安装
sh scripts/install.sh
```

安装目录结构：

```
~/.broca/
├── configs/
│   ├── configs.json              # 全局配置（含 execution 执行参数）
│   ├── llm_config.json           # LLM 配置（由模板生成，需填写 API Key）
│   ├── decision_config.json      # 决策模型配置
│   ├── tool_permission_config.json # 工具权限配置
│   └── agents/                   # Agent 角色配置
├── data/
│   ├── sessions.db               # broca 主数据库（会话、消息、Agent）
│   └── backend.db                # 后端数据库（用户、认证）
├── media_cache/                  # 媒体物化缓存（按 session/agent 分目录，3 天 TTL）
├── web/
│   ├── backend/                  # FastAPI 后端代码
│   └── frontend/                 # Vue 3 前端源码
├── logs/
│   ├── supervisord.log
│   ├── backend.out.log
│   └── frontend.out.log
├── supervisor/
│   └── supervisord.conf          # supervisor 配置
├── run/
│   └── supervisord.pid
├── install.json                  # 安装信息
└── nginx-broca.conf              # nginx 配置
```

**注意**：首次安装需要在 `~/.broca/configs/llm_config.json` 填写相关 API Key。配置采用 `base_url` / `api_key` / `models` 结构，模型级 `meta.modality` 声明可用模态，`meta.media_limits` 控制图片内联大小；完整示例见仓库中的 `configs/llm_config_template.json`。详见 [配置参考](configuration.md)。

## 服务管理

```bash
# 启动所有生产服务
broca service start

# 查看服务状态
broca service status

# 重启服务
broca service restart

# 停止服务
broca service stop
```

## CLI 命令

| 命令 | 说明 |
|------|------|
| `broca` / `broca tui` | 启动 TUI 终端界面（默认行为） |
| `broca web [frontend\|backend]` | 启动 Web 开发服务（可只启动前端或后端） |
| `broca service install/start/stop/restart/status` | 一键安装 / 管理生产服务（supervisor + nginx） |
| `broca run <yaml>` | 从 YAML 配置运行 Crew 编排 |
| `broca worktree create/delete/list` | 管理 git worktree 及关联会话 |
| `broca snapshot gc` | 清理孤儿快照目录 |
| `broca create-user` | 创建 Web 后端用户 |

## 部署架构

```
浏览器 ──→ nginx(:7001) ──proxy──→ FastAPI(:9001)    REST API
                        ──proxy──→ Socket.IO(:6666)  实时通信
                        ──static──→ /var/www/broca/frontend/  前端静态文件
```

**单端口访问**，只需放行 7001 端口。WebSocket 代理自动处理跨域。

访问地址：

- Web 界面：`http://localhost:7001`
- REST API：`http://localhost:9001/api/`
- Socket.IO：`http://localhost:6666`

## TUI 终端界面

Broca 提供基于 [Textual](https://textual.textualize.io/) 的终端用户界面（TUI），可在终端中直接使用：

```bash
# 启动 TUI 界面
broca
```

TUI 界面功能：

- 实时会话切换
- Agent 侧边栏（显示 Agent 状态和统计信息）
- 消息历史浏览
- 权限请求对话框
- 键盘快捷键操作

更多见 [前端与客户端](clients.md#tui-终端界面)。

## VS Code 扩展安装

安装脚本会自动打包 VS Code 插件，生成 `.vsix` 文件。安装方式如下：

**方式一：通过 VS Code 界面安装（推荐）**

1. 打开 VS Code
2. 点击左侧活动栏的 **Extensions** 图标（或按 `Ctrl+Shift+X`）
3. 点击扩展面板右上角的 `...` 菜单，选择 **Install from VSIX...**
4. 选择 `broca-vscode/broca-chat-0.1.0.vsix` 文件

**方式二：通过命令行安装**

```bash
code --install-extension broca-vscode/broca-chat-0.1.0.vsix
```

安装完成后，VS Code 左侧活动栏会出现 Broca 图标，点击即可使用。

**配置连接**：安装后需要配置 Broca 后端地址（默认为 `http://localhost:9001`）和 WebSocket 地址（默认为 `http://localhost:6666`），可在 VS Code 设置中搜索 `broca` 进行配置。
