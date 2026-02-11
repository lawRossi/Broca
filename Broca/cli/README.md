# Broca CLI

基于 TUI (Terminal User Interface) 的命令行客户端，提供比传统命令行更好的交互体验。

## 功能特性

- **现代化界面**：使用 Rich 库实现彩色终端界面
- **实时消息显示**：即时显示助手回复
- **连接状态监控**：实时显示连接状态
- **命令支持**：支持多种命令（/help, /clear, /status 等）
- **消息历史**：保存聊天历史记录
- **错误处理**：优雅的错误处理和显示

## 安装

```bash
pip install -r requirements.txt
```

## 使用方法

### 基本用法

```bash
python -m Broca.cli.main
```

### 指定服务器地址

```bash
python -m Broca.cli.main --server http://localhost:8001
```

### 命令行参数

```
--server, -s     Socket.io 服务器地址 (默认: http://localhost:8001)
--client-type, -t  客户端类型 (默认: cli)
--client-id, -c    客户端标识符 (可选)
--user-id, -u      用户标识符 (可选)
```

## 可用命令

在聊天界面中，可以使用以下命令：

- `/help` - 显示帮助信息
- `/clear` - 清除聊天历史
- `/status` - 显示连接状态
- `/history` - 显示命令历史
- `/quit` 或 `/exit` - 退出程序

## 界面说明

### 状态栏
顶部显示当前连接状态：
- 🟢 绿色：已连接
- 🟡 黄色：连接中
- 🔴 红色：已断开

### 消息类型
不同类型的消息会用不同颜色显示：
- 🟢 **You**: 用户发送的消息
- 🔵 **Assistant**: 助手的回复
- ⚪ **System**: 系统消息
- 🔴 **Error**: 错误消息
- 🟠 **Tool**: 工具调用消息
- 🟣 **Permission**: 权限请求消息

## 与原有 demo.py 的对比

### 原有 demo.py
- 使用简单的 `input()` 函数
- 交互体验较差
- 没有状态显示
- 消息格式简单

### 新的 TUI CLI
- 彩色终端界面
- 实时状态显示
- 格式化消息输出
- 命令支持
- 更好的错误处理
- 消息历史记录

## 依赖

- `rich` - 终端界面库
- `loguru` - 日志库
- `python-socketio` - Socket.io 客户端
- `asyncio-throttle` - 异步限流

## 注意事项

1. 确保 Socket.io 服务器正在运行
2. 服务器地址默认是 `http://localhost:8001`
3. 使用 Ctrl+C 可以随时中断并退出
4. 命令以 `/` 开头，普通消息直接输入
