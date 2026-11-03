# Broca 插件开发指南

本指南介绍如何为 Broca Agent 框架开发第三方插件，替换或扩展内置组件。

## 核心概念

### 组件接口（Component Interface）

Broca 的所有核心功能模块均通过 **ABC（抽象基类）** 定义接口。实现对应的 ABC 即可替换内置行为。

### 组件清单与作用域

| 组件接口 | 作用域 | 默认实现 | 说明 |
|---------|--------|---------|------|
| `LLMClient` | singleton | `LiteLLMClient` | LLM API 客户端 |
| `PermissionProvider` | per-agent | `DefaultPermissionProvider` | 权限管理 |
| `Communicator` | per-agent | `SocketIOCommunicator` | 实时通信 |
| `LoopEngine` | per-agent | `DefaultLoopEngine` | 执行循环引擎 |
| `ToolExecutor` | per-agent | `DefaultToolExecutor` | 工具执行管道 |
| `ContextCompressor` | per-agent | `SessionMemoryCompressor` | 上下文压缩 + 会话记忆 |
| `AgentFactory` | singleton | `DefaultAgentFactory` | Agent 工厂 |
| `MemoryManager` | per-agent | `SubAgentMemoryManager` | 持久记忆 |
| `SnapshotManager` | per-agent | `GitSnapshotManager` | 文件快照 |
| `SessionManager` | per-session | `SQLSessionManager` | 会话存储 |
| `SkillManager` | singleton | `FileSkillManager` | Skill 管理 |
| `ProcessManager` | singleton | `LocalProcessManager` | 进程管理 |
| `Orchestrator` | singleton | `Orchestrator` | 多 Agent 编排 |
| `SessionRunner` | singleton | `IPCSessionRunner` | 会话进程 |
| `ToolManager` | per-agent | `AutoDiscoverToolManager` | 工具发现 |
| `MCPClient` | per-agent | `StdMCPClient` | MCP 协议客户端 |
| `CommandSystem` | per-agent | `FileCommandSystem` | 命令系统 |
| `TaskManager` | per-session | `DBTaskManager` | 任务管理 |

### 作用域说明

- **singleton**：进程内共享一个实例。`Agent.create()` 不传 `scope_key`。
- **per-agent**：每个 Agent 独立实例。`scope_key = agent_id`。
- **per-session**：每个会话独立实例。`scope_key = session_id`。
- **transient**：每次 `get()` 创建新实例，不缓存。

## `initialize()` 契约

所有组件遵循统一的初始化模式：

1. **构造**：`ComponentRegistry.get()` 调用 `ImplClass()` **无参构造**
2. **初始化**：调用 `await component.initialize(**deps)` 注入运行时依赖
3. **幂等**：`initialize()` 可安全重复调用（幂等）
4. **关闭**（仅部分组件）：`await component.shutdown()`

> **重要**：第三方插件的 `__init__` 必须接受 `**kwargs`（Registry 可能传入额外参数），但**不应依赖**任何构造参数。所有依赖通过 `initialize()` 注入。

## 注册插件

### 方式 1：`pyproject.toml` Entry Point（推荐）

在你的插件包 `pyproject.toml` 中声明 entry point：

```toml
[project.entry-points."broca.components"]
tool_executor = "my_package.executor:SandboxToolExecutor"
llm_client = "my_package.llm:LocalLLMClient"
```

安装插件后（`pip install my-plugin`），Broca 启动时自动发现并加载。

**惰性加载**：插件模块仅在 `resolve()` 该接口时才被 import。未使用的插件包不影响启动性能。

### 方式 2：`components.json` 配置文件

在以下路径之一放置 JSON 文件（优先级从高到低）：

1. `$BROCA_COMPONENTS_CONFIG` 环境变量指向的路径
2. `{workspace}/.broca/components.json`
3. `~/.broca/components.json`

```json
{
    "tool_executor": "my_package.executor:SandboxToolExecutor",
    "llm_client": "my_package.llm:LocalLLMClient"
}
```

支持 `module:Class` 和 `module.Class` 两种格式。

### 方式 3：代码中手动覆盖（测试/运行时）

```python
from broca.components.registry import ComponentRegistry
from broca.components.tool_executor import ToolExecutor

registry = ComponentRegistry.get_instance()
registry.set_override(ToolExecutor, MySandboxExecutor)
```

## 开发示例

### 示例 1：自定义 ToolExecutor（沙箱工具执行器）

完整可运行示例见 [`examples/plugins/sandbox_tool_executor/`](../examples/plugins/sandbox_tool_executor/)。

核心实现：

```python
from broca.components.tool_executor import ToolExecutor, ToolExecutionOutcome

class SandboxToolExecutor(ToolExecutor):
    """所有工具在沙箱环境中执行。"""

    def __init__(self, **kwargs):
        self._sandbox = None

    async def initialize(self, tool_mapping, permission_provider, config, communicator):
        self._tool_mapping = tool_mapping
        self._permission_provider = permission_provider
        self._config = config
        self._communicator = communicator
        # 启动沙箱环境...

    async def execute_tool(self, tool_name, arguments, tool_call_id, context, tool, allowed_tools=None):
        # 在沙箱中执行工具
        result = await self._sandbox.run(tool_name, arguments)
        return ToolExecutionOutcome(
            result=result,
            session_action=None,
        )

    def get_permission(self, tool_name):
        return self._permission_provider.get_permission(tool_name)

    def is_readonly_tool(self, tool_name):
        return tool_name in ("read_file", "list_dir", "grep")

    async def shutdown(self):
        await self._sandbox.stop()
```

`pyproject.toml` 配置：

```toml
[project]
name = "my-sandbox-plugin"
version = "0.1.0"

[project.entry-points."broca.components"]
tool_executor = "my_sandbox_plugin:SandboxToolExecutor"
```

### 示例 2：自定义 LLMClient（本地模型）

完整可运行示例见 [`examples/plugins/local_llm_client/`](../examples/plugins/local_llm_client/)。

```python
from broca.components.llm_client import LLMClient

class LocalLLMClient(LLMClient):
    """使用本地 Ollama 模型替代云端 API。"""

    def __init__(self, **kwargs):
        self.model = kwargs.get("model", "llama3")
        self.base_url = "http://localhost:11434"

    async def get_stream_response(self, messages, **kwargs):
        # 调用本地模型 API，yield 流式响应
        async for chunk in self._ollama_stream(messages):
            yield {"type": "content", "data": chunk}
        yield {"type": "finish", "data": "stop"}

    def aggregate_message(self, chunks):
        from litellm import Message
        content = "".join(c["data"] for c in chunks if c["type"] == "content")
        return Message(role="assistant", content=content)
```

## 插件信任边界

> ⚠️ **安全声明**

Broca 插件运行在 **Agent 进程内部**，拥有与 Agent 相同的权限：

- 可访问 `ToolCallContext.agent`，进而访问 Agent 配置、Session Manager、文件系统
- 可执行任意 Python 代码（包括网络请求、文件读写、进程创建）
- 可读取环境变量中的 API Key 和凭据

**插件等同于完全信任的代码。** 请仅安装来自可信来源的插件。

未来版本将引入 `BROCA_ALLOW_PLUGINS` 环境变量开关，允许在不受信任的环境中禁用插件加载。

## 调试

### 查看已注册的组件

```python
from broca.components.registry import ComponentRegistry
from broca.components.tool_executor import ToolExecutor

registry = ComponentRegistry.get_instance()
print(f"Resolved ToolExecutor: {registry.resolve(ToolExecutor)}")
print(f"Scope: {registry._scopes.get(ToolExecutor)}")
```

### 启用调试日志

```bash
BROCA_LOG_LEVEL=DEBUG broca run
```

将看到组件发现、解析、初始化、关闭的完整日志。
