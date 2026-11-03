# Broca 系统组件化 / 插件化升级改造计划

## 概述

- **目标**：将 Broca Agent 框架的主要逻辑模块提取为可插拔组件（Plugin），现有实现作为默认实现，支持通过 Python entry points 或配置文件轻松替换为第三方插件
- **背景**：当前系统各模块间耦合严重——`Agent.create()` 是单一组合根，`LoopEngine` 硬编码了工具执行管道，`SessionMemoryManager` 与 `ContextCompressor` 逻辑割裂，`Agent` 与 `LoopEngine` 存在循环依赖，各组件均为具体类无抽象接口
- **约束条件**：
  - 所有现有功能必须保持不变（行为等价重构）
  - 现有测试必须全部通过
  - 插件机制不能增加正常启动时的性能开销（懒加载）
  - 第三方插件只需 `pip install` + entry point 声明即可生效

## 相关材料

- 现有代码结构：`broca/` 包（核心框架）、`broca-web/backend/`（Web 服务）、`broca-tui/`（终端 UI）
- 现有抽象模式参考：`Tool` 基类（模板方法）、`Orchestrator` ABC（工厂模式）、`CommandManager`（注册表+调度器）
- 已有优化计划参考：`plans/session-memory-extraction-compression-optimization.md`（SessionMemory 合入 ContextCompressor 的详细设计）
- 参考插件架构：Python `importlib.metadata.entry_points()` 标准插件发现机制

## 总体方案

### 架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                        Agent (组合根)                            │
│  Agent.create() 通过 ComponentRegistry 解析所有组件实现           │
└────┬──────────┬──────────┬──────────┬──────────┬────────────────┘
     │          │          │          │          │
     ▼          ▼          ▼          ▼          ▼
┌────────┐ ┌──────────┐ ┌────────┐ ┌──────────┐ ┌──────────┐
│LoopEngine│ │LLMClient │ │Context │ │ToolExecu-│ │Permission│
│(执行引擎)│ │(LLM调用) │ │Compres-│ │tor(工具) │ │Provider  │
│         │ │          │ │sor(压缩)│ │          │ │(权限)    │
└────────┘ └──────────┘ └────────┘ └──────────┘ └──────────┘
     │                              │
     ▼                              ▼
  各组件通过 ABC 接口解耦，ComponentRegistry 负责实例化
```

### 核心设计模式

1. **组件接口层** (`broca/components/`)：每个组件定义一个 ABC 接口
2. **ComponentRegistry**：统一的插件发现、解析、实例化机制
   - 自动发现：`importlib.metadata.entry_points(group="broca.components")`
   - 配置覆盖：`{workspace}/.broca/components.json` 或 `~/.broca/components.json`
   - 默认回退：未指定时使用 `broca/components/defaults.py` 中的映射
3. **依赖注入**：组件通过构造函数注入其依赖，而非通过 `agent` 对象回溯获取
4. **窄接口协议**：组件间通过 Protocol 类型传递，而非传递整个 Agent 对象

### 23 个组件清单

| # | 组件接口 | 默认实现 | 说明 |
|---|---------|---------|------|
| 1 | `ToolExecutor` | `DefaultToolExecutor` | 工具执行管道 |
| 2 | `ContextCompressor` | `SessionMemoryCompressor` | 上下文压缩（含 SessionMemory） |
| 3 | `LLMClient` | `LiteLLMClient` | LLM 调用抽象 |
| 4 | `PermissionProvider` | `DefaultPermissionProvider` | 权限管理 |
| 5 | `Communicator` | `SocketIOCommunicator` | 通信/消息广播 |
| 6 | `Orchestrator` | 已有 ABC | 多智能体编排 |
| 7 | `MemoryManager` | `SubAgentMemoryManager` | 持久化记忆 |
| 8 | `SnapshotManager` | `GitSnapshotManager` | 快照/Undo-Redo |
| 9 | `AgentFactory` | `DefaultAgentFactory` | Agent 创建/恢复 |
| 10 | `SessionManager` | `SQLSessionManager` | 会话/消息持久化 |
| 11 | `SkillManager` | `FileSkillManager` | Skill 加载 |
| 12 | `ProcessManager` | `LocalProcessManager` | 后台进程管理 |
| 13 | `LoopEngine` | `DefaultLoopEngine` | 执行引擎 |
| 14 | `ContentSecurityScanner` | `RegexContentScanner` | 内容安全扫描 |
| 15 | `SessionRunner` | `IPCSessionRunner` | Runner 进程 + IPC |
| 16 | `ErrorStrategy` | `DefaultErrorStrategy` | 错误处理策略 |
| 17 | `ToolManager` | `AutoDiscoverToolManager` | 工具注册/发现 |
| 18 | `MCPClient` | `StdMCPClient` | MCP 协议层 |
| 19 | `Scheduler` | `APSchedulerAdapter` | 定时任务 |
| 20 | `CommandSystem` | `FileCommandSystem` | 命令系统 |
| 21 | `TaskManager` | `DBTaskManager` | 任务管理 |
| 22 | `ConfigManager` | `FileConfigManager` | 配置管理 |
| 23 | `Logger` | `LoguruLogger` | 日志 |

---

## 测试策略

### 测试金字塔

```
                ┌─────────────────┐
                │  E2E 集成测试    │  ← Phase 7：完整 Agent 对话流程
               ┌┤  (5~10 个)      ├┐
              ┌│  插件加载验证     ││
             ┌┤  组件替换验证      │││
            ┌┤  核心循环集成测试   ││├┐  ← Phase 2~4：组件交互
           ┌─┤  组件单元测试       ││├┤  ← 每个 Task 附带
          ┌─┤  ABC 接口兼容性测试  ││├┤│  ← Phase 1：基础
         ┌─┤  Registry 单元测试    ││├┤││
         └─┤  Protocol 测试       ││├┤│└─┐
           └──┤  Fixture/Mock     ││├┤│ └─┐
              └──┤  conftest.py   ││├┤│  ─┤
                 └────────────────┘│├┤│   └──────────
                                  └┤│└─────────────────────────
                                   └──────────────────────────
```

### 测试基础设施（Phase 1 建立）

- **`broca/tests/conftest.py`**：共享 fixture
  - `mock_communicator`：`AsyncMock` 的 `Communicator` 接口
  - `mock_llm_client`：`AsyncMock` 的 `LLMClient` 接口（返回预定义流式响应）
  - `mock_permission_provider`：可配置 allow/ask/forbidden 的 `PermissionProvider` mock
  - `test_context`：最小化的 `Context` 实例（空消息列表）
  - `test_tool`：简单的测试用 `Tool` 子类
  - `fresh_registry`：`ComponentRegistry` 实例 + `reset()` 清理（防止测试间状态污染）
  - `test_workspace`：临时目录作为 workspace
- **`broca/tests/mock_components.py`**：所有 23 个组件的 mock/stub 实现（用于隔离测试）
- **`ComponentRegistry.reset()`**：清除 `_instances` 缓存和 `_overrides`，在 fixture 的 teardown 中调用

### 各 Phase 测试重点

| Phase | 测试重点 | 新增/修改测试文件 |
|-------|---------|-----------------|
| 1 | ABC 接口兼容性、Registry 发现/覆盖/回退、Protocol 行为 | `test_components_registry.py`、`test_component_interfaces.py` |
| 2 | ToolExecutor 完整管道（权限×3、超时、并行/串行）、LoopEngine 委托 | `test_tool_executor.py`、更新 `test_loop_engine.py` |
| 3 | ContextCompressor 压缩流程（阈值触发、强制、pivot 计算、记忆提取） | `test_context_compressor.py`（更新）、`test_memory_manager.py`（适配） |
| 4 | 核心循环集成：LLM→工具→结果→压缩；PermissionProvider 合并行为；AgentReference 适配器 | `test_execution_engine.py`（新增）、`test_permission_provider.py`（新增）、更新 `test_llm.py` |
| 5 | 各组件 ABC-默认实现配对验证、接口兼容性 | 更新现有测试文件 + `test_component_compatibility.py` |
| 6 | Agent.create() 组合流程、AgentReferenceAdapter 行为、组件间连接正确性 | `test_agent_composition.py`（新增） |
| 7 | 全量回归、覆盖率对比、插件 E2E、配置覆盖验证 | 全量 + `test_plugin_loading.py`（新增） |

### 覆盖率要求

- 改造前基线：522 个测试（`pytest broca/tests/ --collect-only` 统计）
- 改造后要求：测试总数 ≥ 600（新增 ~80+ 测试）
- 核心模块行覆盖率（`broca/components/`、`broca/tools/executor.py`、`broca/loop_engine.py`、`broca/context_compressor.py`）≥ 80%
- 每个 Phase 完成时运行 `pytest broca/tests/ --cov=broca --cov-report=term-missing` 并对比

### 关键回归测试场景（Phase 7 E2E）

1. **基础对话**：发送消息 → LLM 返回纯文本 → 无工具调用 → 对话完成
2. **工具调用**：发送消息 → LLM 返回工具调用 → 权限 allow → 工具执行 → 结果返回
3. **权限 ask 流程**：LLM 返回工具调用 → 权限 ask → 用户拒绝 → 错误返回 LLM
4. **并行工具**：LLM 一次返回 3 个工具调用 → 并行执行 → 全部结果汇总
5. **上下文压缩**：构造 >150K token 的历史 → 触发自动压缩 → session memory 提取
6. **强制压缩**：`/compact` 命令 → 跳过阈值检查 → 立即压缩
7. **死循环检测**：相同工具+参数重复 N 次 → 触发死循环中断
8. **组件替换**：通过 `components.json` 替换 ToolExecutor → 工具执行走自定义实现
9. **插件发现**：模拟 entry point 注册 → `ComponentRegistry` 自动发现并使用
10. **错误恢复**：LLM 返回格式错误 → ErrorStrategy 分类 → 重试或用户提示

---

## 执行计划

### Phase 1: 基础架构

**目标**：建立组件化基础——接口定义、ComponentRegistry、插件加载机制、组件配置

**阶段验收标准**：
- [ ] `broca/components/` 包创建完成，包含所有 23 个组件的 ABC 接口
- [ ] `ComponentRegistry` 实现完成，支持 entry points 发现 + 配置覆盖 + 默认回退
- [ ] 组件配置文件格式定义完成（`.broca/components.json`）
- [ ] `pyproject.toml` 中声明 `broca.components` entry point group
- [ ] 接口单元测试通过

#### Task 1.1: 创建组件接口层

- **目标**：在 `broca/components/` 包中定义所有 23 个组件的 ABC 接口
- **步骤**：
  1. 创建 `broca/components/` 包目录结构
  2. 创建 `broca/components/base.py`——定义 `BaseComponent` 基类（可选的 `initialize()`/`shutdown()` 生命周期钩子）
  3. 为每个组件创建接口文件，定义 ABC：
  
  **关键接口设计（优先级最高的 3 个）**：
  
  ```python
  # broca/components/tool_executor.py
  class ToolExecutor(ABC):
      """工具执行器接口——封装权限检查、执行、后处理管道"""
      
      @abstractmethod
      async def execute_tool(
          self,
          tool_name: str,
          arguments: str,
          context: ToolCallContext,
          tool: Tool,
      ) -> ToolResult:
          """执行单个工具调用（含权限检查、超时、后处理）"""
          ...
      
      @abstractmethod
      def is_readonly_tool(self, tool_name: str) -> bool:
          """判断工具是否为只读（用于快照决策）"""
          ...
      
      @abstractmethod
      async def initialize(self, tool_mapping: dict, config: Any) -> None:
          ...
  ```
  
  ```python
  # broca/components/context_compressor.py
  class ContextCompressor(ABC):
      """上下文压缩器接口——统一的 token 监控 + 压缩策略"""
      
      @abstractmethod
      async def check_and_compress(
          self,
          context: Context,
          compressor_context: CompressorContext,
          force: bool = False,
      ) -> CompressionStats:
          """检查 token 阈值并触发压缩（含记忆提取 + 截断）"""
          ...
      
      @abstractmethod
      async def force_compress(
          self, context: Context, compressor_context: CompressorContext
      ) -> CompressionStats:
          ...
  ```
  
  **关键设计：`CompressorContext` 协议**——替代直接传递 `agent` 对象：
  
  ```python
  # broca/components/protocols.py
  class CompressorContext(Protocol):
      """ContextCompressor 所需的窄接口"""
      session_manager: SessionManager
      agent_id: str
      session_id: str
      communicator: "Communicator"
      
      @property
      def compact_config(self) -> ContextCompactConfig: ...
      @property
      def provider(self) -> str: ...
      @property
      def model(self) -> str: ...
      last_context_length: Optional[int]
  ```
  
  4. 其余 20 个组件接口按相同模式定义（每个 1-3 个核心方法）
  5. 创建 `broca/components/protocols.py`——定义组件间共享的 Protocol 类型（如 `CompressorContext`、`ExecutionContext`、`PermissionContext`）
  6. 创建 `broca/components/__init__.py`——导出所有接口

- **预期产出**：`broca/components/` 包，包含 23 个 ABC 接口文件 + protocols.py + base.py
- **验收标准**：
  - [ ] `broca/components/` 包含 23 个接口文件，每个 ABC 有完整的 docstring 和类型注解
  - [ ] `protocols.py` 定义了 `CompressorContext`、`ExecutionContext`、`PermissionContext` 等 Protocol
  - [ ] 所有 ABC 的抽象方法签名与现有实现的方法签名兼容
  - [ ] `from broca.components import ToolExecutor, ContextCompressor, ...` 可成功导入

#### Task 1.2: 实现 ComponentRegistry

- **目标**：实现统一的组件插件发现、解析、实例化机制
- **步骤**：
  1. 创建 `broca/components/registry.py`
  2. 实现 `ComponentRegistry` 类：
  
  ```python
  class ComponentRegistry:
      """组件注册表——管理所有组件接口的实现解析"""
      
      _instance: Optional["ComponentRegistry"] = None
      
      def __init__(self):
          self._overrides: dict[type, type] = {}   # 配置覆盖
          self._discovered: dict[type, type] = {}   # entry points 发现
          self._defaults: dict[type, type] = {}     # 内置默认
          self._instances: dict[type, Any] = {}     # 已实例化缓存
      
      def register_defaults(self):
          """注册所有内置默认实现"""
          from broca.components.defaults import DEFAULT_IMPLEMENTATIONS
          self._defaults = DEFAULT_IMPLEMENTATIONS
      
      def discover_plugins(self):
          """通过 entry points 发现第三方插件"""
          for ep in importlib.metadata.entry_points(group="broca.components"):
              impl_class = ep.load()
              # ep.value 格式: "tool_executor" 或 "context_compressor"
              interface = self._name_to_interface.get(ep.name)
              if interface:
                  self._discovered[interface] = impl_class
      
      def load_config_overrides(self, workspace: str | None):
          """加载 components.json 配置覆盖"""
          # 优先级: {workspace}/.broca/components.json > ~/.broca/components.json
          # 格式: {"tool_executor": "my_package.module:ClassName"}
      
      def resolve(self, interface: type) -> type:
          """解析接口对应的实现类：override > discovered > default"""
          if interface in self._overrides: return self._overrides[interface]
          if interface in self._discovered: return self._discovered[interface]
          if interface in self._defaults: return self._defaults[interface]
          raise ComponentError(f"No implementation for {interface.__name__}")
      
      def get(self, interface: type, **kwargs) -> Any:
          """获取组件实例（单例缓存）"""
          if interface not in self._instances:
              impl_cls = self.resolve(interface)
              self._instances[interface] = impl_cls(**kwargs)
          return self._instances[interface]
  ```
  
  3. 创建 `broca/components/defaults.py`——映射表：接口 → 默认实现类
  4. 创建 `broca/components/errors.py`——`ComponentError`、`ComponentNotFoundError`
  5. 在 `pyproject.toml` 中添加 entry point 声明（用于内置组件的自注册，也作为文档）：
  
  ```toml
  [project.entry-points."broca.components"]
  tool_executor = "broca.tools.executor:DefaultToolExecutor"
  context_compressor = "broca.context_compressor:SessionMemoryCompressor"
  # ... 其余 21 个
  ```

- **预期产出**：`ComponentRegistry` 完整实现 + 默认映射表 + entry point 声明
- **验收标准**：
  - [ ] `ComponentRegistry.discover_plugins()` 能正确发现 entry points 注册的插件
  - [ ] 配置文件的优先级正确：override > discovered > default
  - [ ] `ComponentRegistry.get(ToolExecutor)` 返回默认实现（未安装插件时）
  - [ ] 单例缓存工作正常：同一接口多次 `get()` 返回同一实例
  - [ ] 单元测试覆盖：发现、覆盖、默认回退、未找到异常

#### Task 1.3: 组件配置机制

- **目标**：定义组件覆盖配置的文件格式和加载逻辑
- **步骤**：
  1. 定义配置文件格式：`{workspace}/.broca/components.json`
  
  ```json
  {
    "tool_executor": "my_package.executor:SandboxToolExecutor",
    "llm_client": "my_package.llm:LocalLLMClient"
  }
  ```
  
  2. 支持全局配置：`~/.broca/components.json`（优先级低于 workspace 级）
  3. 在 `ComponentRegistry.load_config_overrides()` 中实现加载逻辑
  4. 支持环境变量 `BROCA_COMPONENTS_CONFIG` 指定自定义配置路径

- **预期产出**：配置文件格式文档 + 加载逻辑实现
- **验收标准**：
  - [ ] 配置文件中的 "module:ClassName" 格式能正确解析并导入
  - [ ] 不存在的模块/类名给出清晰的错误信息
  - [ ] workspace 级配置优先于全局配置
  - [ ] 配置文件不存在时不影响正常运行

#### Task 1.4: 测试基础设施搭建

- **目标**：建立组件化改造的测试基础设施，确保后续所有 Phase 的测试有一致的 mock/fixture 环境
- **步骤**：
  1. 创建 `broca/tests/conftest.py`，包含以下 fixture：
     - `mock_communicator`：`AsyncMock` 实现 `Communicator` 接口
     - `mock_llm_client`：`AsyncMock` 实现 `LLMClient` 接口（预定义流式响应 + `aggregate_message` 返回）
     - `mock_permission_provider`：可配置行为的 `PermissionProvider` mock（`allow_all`、`forbid_all`、`ask_all` 三种模式）
     - `test_context`：最小化 `Context` 实例
     - `test_tool`：简单测试用 `Tool` 子类（`execute` 返回固定结果）
     - `fresh_registry`：`ComponentRegistry` 实例 + teardown 时 `reset()`
     - `test_workspace`：`tmp_path` 作为 workspace 根目录
  2. 创建 `broca/tests/mock_components.py`：所有 23 个组件的 `Mock*` 实现（`AsyncMock` 或简单 stub），用于隔离测试
  3. 在 `ComponentRegistry` 中实现 `reset()` 方法：
     ```python
     def reset(self):
         """清除所有缓存实例，用于测试隔离"""
         self._instances.clear()
         self._overrides.clear()
     ```
  4. 在 `pyproject.toml` 或 `pytest.ini` 中配置 `pytest-cov`（如尚未配置）：
     ```ini
     [tool.pytest.ini_options]
     addopts = "--cov=broca --cov-report=term-missing"
     ```

- **预期产出**：`broca/tests/conftest.py`、`broca/tests/mock_components.py`、`ComponentRegistry.reset()`
- **验收标准**：
  - [ ] 所有 fixture 在 `pytest --fixtures` 中可见
  - [ ] `fresh_registry` fixture 保证每个测试的 Registry 状态干净
  - [ ] `mock_llm_client` 能正确模拟流式响应 + `aggregate_message`
  - [ ] `mock_components.py` 中 23 个 Mock 实现可导入
  - [ ] 覆盖率报告可正常生成

---

### Phase 2: ToolExecutor 组件提取（最高优先级）

**目标**：将工具执行管道从 `LoopEngine` 中提取为独立的 `ToolExecutor` 组件

**阶段验收标准**：
- [ ] `ToolExecutor` ABC 接口就位（Phase 1 已创建）
- [ ] `DefaultToolExecutor` 实现完成，包含完整的权限检查→执行→后处理管道
- [ ] `LoopEngine` 中的 `_process_tool_calls()` / `_execute_single_tool_call()` 委托给 `ToolExecutor`
- [ ] 现有工具执行行为完全不变（所有工具测试通过）
- [ ] 支持通过组件配置替换为自定义 ToolExecutor（如沙箱执行器）
- [ ] 工具执行相关测试全部通过

#### Task 2.1: 实现 DefaultToolExecutor

- **目标**：从 `LoopEngine` 提取工具执行逻辑到 `DefaultToolExecutor`
- **步骤**：
  1. 创建 `broca/tools/executor.py`
  2. 从 `LoopEngine` 提取以下方法到 `DefaultToolExecutor`：
     - `_execute_single_tool_call()` → `execute_tool()`（核心方法）
     - `_execute_tool_with_ask()` → 内部方法 `_execute_with_ask()`
     - `_execute_tool_with_allow()` → 内部方法 `_execute_with_allow()`
     - 权限检查逻辑（`tool_permission_manager.get_permission()`）
     - `asyncio.wait_for(timeout)` 超时逻辑
     - `ToolManager.READONLY_TOOLS` 判断 → `is_readonly_tool()`
  3. `DefaultToolExecutor` 的依赖通过构造函数注入：
  
  ```python
  class DefaultToolExecutor(ToolExecutor):
      def __init__(self):
          self._tool_mapping: dict[str, Tool] = {}
          self._tool_permission_manager: ToolPermissionManager | None = None
          self._permission_provider: PermissionProvider | None = None
          self._config: Any = None
          self._tool_call_timeout: int = 120
          self._tool_execution_mode: str = "parallel"
          self._max_parallel_tools: int = 10
      
      async def initialize(self, tool_mapping, permission_provider, config):
          self._tool_mapping = tool_mapping
          self._permission_provider = permission_provider
          self._config = config
          # ... 从 config 读取超时、并行度等参数
      
      async def execute_tool(self, tool_name, arguments, context, tool) -> ToolResult:
          """完整管道：权限检查 → 执行 → 后处理"""
          # 1. 权限检查
          permission = self._get_permission(tool_name)
          if permission == "forbidden":
              return ToolResult(status=ToolStatus.ERROR, content="Tool is forbidden")
          if permission == "ask":
              return await self._execute_with_ask(tool_name, arguments, context, tool)
          # 2. 执行（带超时）
          result = await asyncio.wait_for(
              tool.execute(arguments, context), timeout=self._tool_call_timeout
          )
          return result
      
      def is_readonly_tool(self, tool_name: str) -> bool:
          return tool_name in ToolManager.READONLY_TOOLS
  ```
  
  4. 处理 `ToolCallContext.agent` 的解耦：
     - `DefaultToolExecutor` 通过 `PermissionProvider` 接口请求权限，而非通过 `context.agent.ask_for_tool_permission()`
     - `ToolCallContext` 中的 `agent` 字段保留（向后兼容），但 `DefaultToolExecutor` 不依赖它

- **预期产出**：`broca/tools/executor.py`（`DefaultToolExecutor` 类）
- **验收标准**：
  - [ ] `DefaultToolExecutor` 实现了 `ToolExecutor` ABC 的所有方法
  - [ ] 权限检查逻辑完整：forbidden / ask / allow 三种分支
  - [ ] 超时处理正确：超时返回 `ToolResult(status=ERROR)`
  - [ ] 不再通过 `context.agent` 访问权限管理器
  - [ ] `is_readonly_tool()` 返回正确结果

#### Task 2.2: 重构 LoopEngine 使用 ToolExecutor

- **目标**：修改 `LoopEngine` 将工具执行委托给 `ToolExecutor`
- **步骤**：
  1. `LoopEngine.__init__()` 新增 `tool_executor: ToolExecutor` 参数
  2. `_process_tool_calls()` 方法修改：
     - 原来直接调用 `_execute_single_tool_call()` 
     - 改为调用 `self.tool_executor.execute_tool(tool_name, arguments, context, tool)`
     - 保留并行/串行调度逻辑（`asyncio.Semaphore`）在 LoopEngine 中
     - 保留结果处理逻辑（broadcast、save to DB、add to context）在 LoopEngine 中
  3. `check_step_has_write_operations()` 改为使用 `self.tool_executor.is_readonly_tool(tool_name)`
  4. 删除 `LoopEngine` 中的 `_execute_single_tool_call()`、`_execute_tool_with_ask()`、`_execute_tool_with_allow()` 方法
  5. 删除 `LoopEngine` 中直接引用 `ToolPermissionManager` 的代码（通过 `tool_executor` 间接访问）

- **预期产出**：重构后的 `broca/loop_engine.py`
- **验收标准**：
  - [ ] `LoopEngine` 不再包含任何工具执行的具体逻辑（权限检查、超时处理）
  - [ ] `_process_tool_calls()` 通过 `self.tool_executor.execute_tool()` 执行工具
  - [ ] 并行/串行模式切换仍然正确工作
  - [ ] 结果处理（broadcast、DB save、context add）仍在 LoopEngine 中
  - [ ] 现有 `test_loop_engine.py` 测试全部通过（可能需要适配 mock）

#### Task 2.3: Agent.create() 适配 ToolExecutor

- **目标**：在 Agent 创建流程中通过 ComponentRegistry 初始化 ToolExecutor
- **步骤**：
  1. `Agent.create()` 中新增：
     ```python
     registry = ComponentRegistry.get_instance()
     tool_executor = registry.get(ToolExecutor)
     await tool_executor.initialize(
         tool_mapping=agent.tool_mapping,
         permission_provider=agent.permission_manager,
         config=agent.config,
     )
     ```
  2. `Agent._setup_execution_engine()` 传入 `tool_executor`：
     ```python
     self.execution_engine = LoopEngine(
         ...,
         tool_executor=tool_executor,
     )
     ```
  3. 确保 `ToolCallContext` 的构造不依赖 Agent 对象（在 LoopEngine._build_tool_context 中调整）

- **预期产出**：修改后的 `broca/agent.py`
- **验收标准**：
  - [ ] `Agent.create()` 通过 `ComponentRegistry.get(ToolExecutor)` 获取执行器
  - [ ] 不配置任何插件时，行为与改造前完全一致
  - [ ] Agent 创建流程不会因组件缺失而失败（有默认回退）

> **注意**：本 Task 对 `Agent.create()` 的修改是**中间步骤**——仅引入 `ToolExecutor` 的获取和初始化。Phase 6.1 将对 `Agent.create()` 进行彻底重构（所有组件均通过 Registry 获取）。本 Phase 中 `Agent.create()` 仍然直接 `new` 其他组件（Communicator、Context 等），只有 `ToolExecutor` 走了 Registry 路径。

#### Task 2.4: ToolExecutor 测试

- **目标**：为 ToolExecutor 编写独立的单元测试
- **步骤**：
  1. 创建 `broca/tests/test_tool_executor.py`
  2. 测试用例：
     - `test_execute_tool_allow` — 权限为 allow 时直接执行
     - `test_execute_tool_forbidden` — 权限为 forbidden 时返回错误
     - `test_execute_tool_ask_denied` — 权限为 ask 且用户拒绝
     - `test_execute_tool_timeout` — 执行超时
     - `test_readonly_tool` — 只读工具判断
     - `test_parallel_execution` — 并行执行模式
     - `test_serial_execution` — 串行执行模式
  3. 使用 mock 的 `Tool`、`PermissionProvider`、`ToolCallContext`

- **预期产出**：`broca/tests/test_tool_executor.py`
- **验收标准**：
  - [ ] 所有测试用例通过
  - [ ] 覆盖了权限检查的三种分支
  - [ ] 覆盖了超时、并行/串行模式
  - [ ] 测试不依赖 Agent 实例

---

### Phase 3: ContextCompressor 合入 SessionMemory

**目标**：将 `SessionMemoryManager` 的提取/pivot/冻结逻辑合入 `ContextCompressor`，消除独立的 SessionMemoryManager 类

**阶段验收标准**：
- [ ] `ContextCompressor` 包含完整的 token 监控 + 记忆提取 + 截断压缩流程
- [ ] `SessionMemoryManager` 类不再被外部直接引用（作为内部实现或完全删除）
- [ ] `LoopEngine._trigger_post_step_hooks()` 只调用 `ContextCompressor`
- [ ] `/compact` 命令通过 `ContextCompressor.force_compress()` 工作
- [ ] 上下文压缩相关测试全部通过
- [ ] SessionMemory 的提取子代理机制保持不变

#### Task 3.1: 重构 ContextCompressor 合入 SessionMemory

- **目标**：将 `SessionMemoryManager` 的核心逻辑合入 `ContextCompressor`
- **步骤**：
  1. 参考 `plans/session-memory-extraction-compression-optimization.md` 中的设计
  2. 重构 `broca/context_compressor.py`：
     - `check_and_compress()` 接收 `CompressorContext`（Protocol）而非 `agent`
     - 内部方法 `_do_session_memory_compress()` 包含：
       - `compute_keep_pivot()`（从 SessionMemoryManager 搬入）
       - `extract()`（从 SessionMemoryManager 搬入，保留子代理机制）
       - `frozen_session_memory()`（搬入）
       - `mark_messages_before_as_truncated()`（调用 session_manager）
       - `build_history_from_session()`（调用 context）
     - `force_compress()` 跳过 token 检查直接压缩
  3. 将 `SessionMemoryManager` 的路径管理逻辑（`snapshot_memory_path`、`memory_path`、`_ensure_template_exists`）合入 `ContextCompressor`
  4. `SessionMemoryManager` 类保留但标记为 `@deprecated`（向后兼容），内部委托给 `ContextCompressor`
  
  ```python
  class ContextCompressor(ABC):
      """统一的上下文压缩器（含 SessionMemory 提取）"""
      
      # === 路径管理（原 SessionMemoryManager）===
      FROZEN_MEMORY_FILENAME = "session-memory.md"
      SNAPSHOT_MEMORY_FILENAME = "session-memory_latest.md"
      
      @property
      def snapshot_memory_path(self) -> str: ...
      @property
      def memory_path(self) -> str: ...
      
      # === 核心接口 ===
      @abstractmethod
      async def check_and_compress(self, context, cc_ctx: CompressorContext, force=False) -> CompressionStats: ...
      
      # === 内部方法（SessionMemoryCompressor 实现）===
      # _compute_keep_pivot()
      # _do_extract()（子代理提取）
      # _freeze_session_memory()
      # _rebuild_context()
  ```

  5. 创建 `broca/context_compressor.py` 中的 `SessionMemoryCompressor(ContextCompressor)` 默认实现

- **预期产出**：重构后的 `broca/context_compressor.py`（含 `SessionMemoryCompressor`）
- **验收标准**：
  - [ ] `SessionMemoryCompressor` 实现了 `ContextCompressor` ABC
  - [ ] `check_and_compress()` 完整流程：token 检查 → pivot 计算 → 提取 → 截断 → 冻结 → 重建
  - [ ] 不再需要外部创建 `SessionMemoryManager` 实例
  - [ ] `force_compress()` 跳过 token 检查
  - [ ] 子代理提取机制保持不变（通过 AgentFactory 创建子 agent）

#### Task 3.2: 重构 LoopEngine 的 post-step hooks

- **目标**：`LoopEngine._trigger_post_step_hooks()` 只调用 `ContextCompressor`
- **步骤**：
  1. `LoopEngine.__init__()` 新增 `context_compressor: ContextCompressor` 参数
  2. `_trigger_post_step_hooks()` 修改：
     ```python
     async def _trigger_post_step_hooks(self):
         # 上下文压缩（含 session memory 提取）
         if self.context_compressor:
             await self.context_compressor.check_and_compress(
                 context=self.context,
                 cc_ctx=self._build_compressor_context(),
             )
         # 持久化记忆（通过 MemoryManager 组件）
         if self.memory_manager:
             await self.memory_manager.check_and_extract(context=self.context)
     ```
  3. 删除 `LoopEngine` 中对 `agent.session_memory_manager` 的直接引用
  4. `_build_compressor_context()` 构造 `CompressorContext` Protocol 实例（从 agent 提取需要的属性）

- **预期产出**：修改后的 `broca/loop_engine.py`
- **验收标准**：
  - [ ] `_trigger_post_step_hooks()` 不再引用 `session_memory_manager`
  - [ ] 压缩通过 `self.context_compressor.check_and_compress()` 触发
  - [ ] 持久化记忆通过 `self.memory_manager.check_and_extract()` 触发
  - [ ] `ContextCompressor` 不再接收 `agent` 参数（接收 `CompressorContext`）

#### Task 3.3: 适配 /compact 命令

- **目标**：`/compact` 命令通过 `ContextCompressor.force_compress()` 触发
- **步骤**：
  1. 修改 `broca/commands/builtin/compact/` 中的命令实现
  2. 命令执行时调用 `agent.execution_engine.context_compressor.force_compress(context, cc_ctx)`
  3. 确认 `clear_context` / `clear_all_context` 命令对 session memory 文件的清理逻辑适配新路径

- **预期产出**：修改后的 compact 命令
- **验收标准**：
  - [ ] `/compact` 手动触发强制压缩（跳过 token 检查）
  - [ ] 压缩后 context 正确重建
  - [ ] Session memory 文件路径正确（agent 级路径）

#### Task 3.4: ContextCompressor 测试

- **目标**：更新和新增 ContextCompressor 测试
- **步骤**：
  1. 更新 `broca/tests/test_context_compressor.py`
  2. 新增测试：
     - `test_check_and_compress_below_threshold` — 不触发压缩
     - `test_check_and_compress_above_threshold` — 触发完整压缩流程
     - `test_force_compress` — 强制压缩
     - `test_keep_pivot_no_cross_turn` — 保留边界不跨 turn
     - `test_keep_pivot_within_keep_steps` — 保留最近 N 步
  3. 适配 `broca/tests/test_memory_manager.py`（SessionMemoryManager 标记 deprecated 后，确保测试仍通过）

- **预期产出**：更新后的测试文件
- **验收标准**：
  - [ ] 所有 ContextCompressor 测试通过
  - [ ] 覆盖了 token 阈值触发、强制压缩、pivot 边界计算
  - [ ] 不依赖 `SessionMemoryManager` 实例（使用 `ContextCompressor`）

---

### Phase 4: 核心循环组件化

**目标**：完成 LoopEngine、LLMClient、PermissionProvider、Communicator 的组件化

**阶段验收标准**：
- [ ] `DefaultLoopEngine` 实现 `LoopEngine` ABC
- [ ] `LiteLLMClient` 实现 `LLMClient` ABC
- [ ] `DefaultPermissionProvider` 合并了 PermissionManager + ToolPermissionManager
- [ ] `SocketIOCommunicator` 实现 `Communicator` ABC
- [ ] `DefaultLoopEngine` 的所有依赖通过接口注入
- [ ] 核心循环流程集成测试通过（LLM → 工具 → 结果 → 压缩）

#### Task 4.1: LLMClient 接口化

- **目标**：为 LLM 调用定义抽象接口
- **步骤**：
  1. 在 `broca/components/llm_client.py` 中定义 ABC：
     ```python
     class LLMClient(ABC):
         @abstractmethod
         def parse_message(self, provider: str, model: str, message: Message) -> dict: ...
         
         @abstractmethod
         async def get_stream_response(self, provider, model, messages, tools=None, ...) -> AsyncGenerator[dict, None]: ...
         
         @abstractmethod
         def aggregate_message(self, content_chunks, tool_call_chunks) -> LLMMessage | None: ...
     ```
  2. 现有 `broca/llm.py` 的 `LLMClient` 类改为 `LiteLLMClient(LLMClient)`
  3. `LoopEngine` 通过接口类型引用 LLMClient

- **预期产出**：`broca/components/llm_client.py`（ABC）+ 修改后的 `broca/llm.py`（实现）
- **验收标准**：
  - [ ] `LiteLLMClient` 继承 `LLMClient` ABC
  - [ ] `LoopEngine` 中 LLM 调用通过接口类型
  - [ ] 现有 LLM 测试通过

#### Task 4.2: PermissionProvider 合并

- **目标**：将 `PermissionManager` + `ToolPermissionManager` 合并为统一的 `PermissionProvider` 接口
- **步骤**：
  1. 定义 `PermissionProvider` ABC：
     ```python
     class PermissionProvider(ABC):
         @abstractmethod
         async def request_permission(self, message: str, context: PermissionContext) -> bool: ...
         
         @abstractmethod
         async def request_tool_permission(self, tool_name: str, arguments: str, context: PermissionContext) -> tuple[bool, Optional[str]]: ...
         
         @abstractmethod
         def get_tool_permission(self, tool_name: str) -> str: ...
         # "allow" | "ask" | "forbidden"
         
         @abstractmethod
         def clear_session_overrides(self) -> None: ...
     ```
  2. 创建 `PermissionContext` Protocol：`turn_id`、`agent_id`、`session_id`（替代 `set_state()` 模式）
  3. 实现 `SocketIOPermissionProvider(PermissionProvider)`——合并现有两个类的逻辑
  4. `ToolExecutor` 通过 `PermissionProvider` 接口请求权限（不再直接引用 `ToolPermissionManager`）

- **预期产出**：`broca/components/permission_provider.py`（ABC）+ 合并后的实现
- **验收标准**：
  - [ ] `SocketIOPermissionProvider` 实现了所有权限方法
  - [ ] 不再需要 `set_state()` 模式（通过 `PermissionContext` 参数传递）
  - [ ] ToolExecutor 通过 PermissionProvider 接口检查权限
  - [ ] 权限测试通过

#### Task 4.3: Communicator 接口化

- **目标**：抽象通信层
- **步骤**：
  1. 定义 `Communicator` ABC（核心方法：`send_message`、`send_error`、`send_turn_start/end`、`send_permission_request`、`send_agent_system_message`、`connect`、`disconnect`、`register_event_handler`）
  2. `AgentCommunicator` 改为 `SocketIOCommunicator(Communicator)`
  3. 所有通过 `agent.communicator` 访问通信的地方改为通过接口

- **预期产出**：`broca/components/communicator.py`（ABC）
- **验收标准**：
  - [ ] 所有通信方法通过 `Communicator` 接口
  - [ ] SocketIO 实现作为默认
  - [ ] 通信相关测试通过

#### Task 4.4: LoopEngine 组件化

- **目标**：`LoopEngine` 定义 ABC 接口，`DefaultLoopEngine` 为默认实现
- **步骤**：
  1. 定义 `LoopEngine` ABC：
     ```python
     class LoopEngine(ABC):
         @abstractmethod
         async def execute(self, message: Message, max_steps=None, from_agent=False) -> ExecutionResult: ...
         
         @abstractmethod
         def abort(self) -> None: ...
         
         @abstractmethod
         def reset(self) -> None: ...
     ```
  2. 现有 `LoopEngine` 拆分为 `LoopEngine`（ABC）+ `DefaultLoopEngine(LoopEngine)`（实现）
  3. `LoopEngine.__init__` 的所有参数改为接收接口类型：
     - `agent: Any` → `agent_ref: AgentReference`（Protocol，只包含回调方法）
     - `llm_client: LLMClient`（ABC）
     - `tool_executor: ToolExecutor`（ABC）
     - `context_compressor: ContextCompressor`（ABC）
     - `communicator: Communicator`（ABC）
  4. 定义 `AgentReference` Protocol：
     ```python
     class AgentReference(Protocol):
         agent_id: str
         session_id: str
         turn_id: Optional[str]
         
         async def on_llm_call_completed(self, input_tokens: int, output_tokens: int) -> None: ...
         async def ask_for_permission(self, message: str) -> bool: ...
         async def ask_for_tool_permission(self, tool_name: str, arguments: str) -> tuple[bool, Optional[str]]: ...
     ```
  
  5. **解循环依赖**：`Agent` 不再传入 `self`，而是传入一个实现了 `AgentReference` 的轻量适配器

- **预期产出**：重构后的 `broca/loop_engine.py`
- **验收标准**：
  - [ ] `DefaultLoopEngine` 实现了 `LoopEngine` ABC
  - [ ] `LoopEngine` 不直接引用 `Agent` 类（通过 `AgentReference` Protocol）
  - [ ] 所有依赖通过构造函数注入（接口类型）
  - [ ] 核心循环测试通过（LLM 调用 → 工具执行 → 步骤管理 → 死循环检测）

#### Task 4.5: 核心循环集成测试

- **目标**：编写覆盖完整 Agent 核心循环（LLM → 工具 → 结果 → 压缩）的集成测试，验证组件间协作正确性
- **步骤**：
  1. 创建 `broca/tests/test_execution_engine.py`
  2. 使用 Phase 1 建立的 `conftest.py` fixture（`mock_llm_client`、`mock_communicator`、`mock_permission_provider`、`fresh_registry`）
  3. 测试场景：
     - `test_execute_simple_response` — LLM 返回纯文本，无工具调用
     - `test_execute_single_tool_call` — LLM 返回 1 个工具调用 → ToolExecutor 执行 → 结果返回
     - `test_execute_parallel_tool_calls` — LLM 返回 3 个工具 → 并行执行 → 全部结果汇总
     - `test_execute_with_permission_ask` — 工具权限为 ask → 用户拒绝 → 错误返回 LLM
     - `test_execute_with_permission_forbidden` — 工具权限为 forbidden → 直接返回错误
     - `test_context_compression_triggers` — 构造大 context → 压缩触发 → session memory 提取
     - `test_infinite_loop_detection` — 相同工具+参数重复 N 次 → 触发中断
     - `test_abort_mid_execution` — 执行中 abort → 当前步骤安全终止
     - `test_agent_reference_adapters` — `AgentReferenceAdapter` 正确代理回调（`on_llm_call_completed`、`ask_for_permission`）
  4. 每个测试使用 `ComponentRegistry` 组装完整组件栈（而非手动 `new`），验证 Registry 路径正确

- **预期产出**：`broca/tests/test_execution_engine.py`（≥ 9 个测试函数）
- **验收标准**：
  - [ ] 9 个测试场景全部通过
  - [ ] 测试通过 `ComponentRegistry` 获取所有组件（不直接 `new`）
  - [ ] 验证了 `AgentReferenceAdapter` 的回调代理行为
  - [ ] 并行工具执行测试验证了 `asyncio.Semaphore` 限流

---

### Phase 5: 支撑组件接口化（批量）

**目标**：完成剩余 13 个组件的接口定义和默认实现适配

**阶段验收标准**：
- [ ] 所有 23 个组件都有 ABC 接口 + 默认实现
- [ ] 默认实现类正确继承对应 ABC
- [ ] ComponentRegistry 的 defaults 映射表完整
- [ ] 所有组件的现有测试通过

#### Task 5.1: 持久化/快照组件

- **目标**：MemoryManager、SnapshotManager、SessionManager 接口化
- **步骤**：
  1. `MemoryManager` ABC：`check_and_extract(context)`、`trigger_extraction(context, hint)`
     - 默认实现 `SubAgentMemoryManager`（现有 `PersistentMemoryManager` 重命名）
  2. `SnapshotManager` ABC：`track()`、`calculate_patch(from_hash, to_hash)`、`acquire_lock()`、`release_lock()`
     - 默认实现 `GitSnapshotManager`（合并 `SnapshotTracker` + `PatchCalculator`）
  3. `SessionManager` ABC：`create_session`、`get_messages`、`save_message`、`mark_messages_before_as_truncated` 等
     - 默认实现 `SQLSessionManager`（现有 `SessionManager`）

- **验收标准**：
  - [ ] 三个组件的 ABC 和默认实现就位
  - [ ] 现有调用方通过接口类型引用

#### Task 5.2: 管理/工具组件

- **目标**：AgentFactory、SkillManager、ProcessManager、ContentSecurityScanner 接口化
- **步骤**：
  1. `AgentFactory` ABC：`create_agent(config, session_manager, **kwargs)`、`restore_agent(agent_id, session_manager)`、`restore_agents_from_session(session_id)`
     - 默认实现 `DefaultAgentFactory`（现有 `AgentFactory`）
  2. `SkillManager` ABC：`get_skills(workspace, skill_names=None)`、`load_skill(name)`
     - 默认实现 `FileSkillManager`
  3. `ProcessManager` ABC：`start_process`、`get_status`、`stop_process`、`list_processes`、`cleanup`
     - 默认实现 `LocalProcessManager`
  4. `ContentSecurityScanner` ABC：`scan(content: str) -> Optional[str]`（返回错误信息或 None）
     - 默认实现 `RegexContentScanner`

- **验收标准**：
  - [ ] 四个组件的 ABC 和默认实现就位
  - [ ] 调用方通过接口类型引用

#### Task 5.3: 运行时/协议组件

- **目标**：SessionRunner、ErrorStrategy、ToolManager、MCPClient 接口化
- **步骤**：
  1. `SessionRunner` ABC：`start_session(session_id, **kwargs)`、`stop_session(session_id)`、`send_command(session_id, command)`、`on(event, handler)`
     - 默认实现 `IPCSessionRunner`（现有 `RunnerManager`）
  2. `ErrorStrategy` ABC：`classify(error) -> ErrorCode`、`should_retry(error, attempt) -> bool`、`format_for_user(error) -> str`
     - 默认实现 `DefaultErrorStrategy`
  3. `ToolManager` ABC：`init(workspace)`、`get_tools(tool_names)`、`get_mcp_tools(server_names)`、`load_custom_tools(workspace)`
     - 默认实现 `AutoDiscoverToolManager`（现有 `ToolManager`，去除单例）
  4. `MCPClient` ABC：`connect(servers)`、`get_tools(server_names)`、`disconnect()`
     - 默认实现 `StdMCPClient`

- **验收标准**：
  - [ ] 四个组件的 ABC 和默认实现就位
  - [ ] `ToolManager` 不再是单例（可实例化多个）

#### Task 5.4: 服务/基础设施组件

- **目标**：Scheduler、CommandSystem、TaskManager、ConfigManager、Logger 接口化
- **步骤**：
  1. `Scheduler` ABC：`start()`、`shutdown()`、`add_job(...)`、`remove_job(job_id)`、`pause_job(job_id)`、`resume_job(job_id)`、`list_jobs(session_id)`、`get_job(job_id)`、`execute_job_now(job_id)`
     - 默认实现 `APSchedulerAdapter`
  2. `CommandSystem` ABC：`initialize()`、`parse(content) -> Optional[tuple[str, str]]`、`dispatch(name, args, raw_input, **kwargs)`
     - 默认实现 `FileCommandSystem`（现有 `CommandManager`）
  3. `TaskManager` ABC：`create_task(...)`、`get_task(task_id)`、`update_task(...)`、`search_tasks(query)` 等
     - 默认实现 `DBTaskManager`
  4. `ConfigManager` ABC：`get_configs() -> BrocaConfig`、`get_agent_config(name) -> AgentConfig`、`get_llm_config() -> dict`
     - 默认实现 `FileConfigManager`
  5. `Logger` ABC：`get_logger(name) -> LoggerInstance`、`init(config)`
     - 默认实现 `LoguruLogger`

- **验收标准**：
  - [ ] 五个组件的 ABC 和默认实现就位
  - [ ] 所有 23 个组件在 `defaults.py` 中有映射

#### Task 5.5: 组件兼容性验证测试

- **目标**：为所有 23 个组件编写 ABC-默认实现配对验证测试，确保默认实现完整实现了 ABC 接口
- **步骤**：
  1. 创建 `broca/tests/test_component_compatibility.py`
  2. 参数化测试（`pytest.mark.parametrize`）：遍历 `DEFAULT_IMPLEMENTATIONS` 映射表，对每个 (接口, 默认实现) 对：
     - 验证 `issubclass(impl_cls, interface_cls)`
     - 实例化默认实现（无参构造或最小参数）
     - 验证 ABC 的所有 `@abstractmethod` 在非抽象实现中均已实现（通过 `abc.ABC` 的 `__abstractmethods__` 集合为空）
  3. 对每个组件验证 `ComponentRegistry.resolve(interface)` 返回的类与 `defaults.py` 中注册的一致
  4. 更新 Phase 2~4 中涉及的现有测试文件，确保适配新接口后仍通过：
     - `test_llm.py` → 使用 `LiteLLMClient` 类名
     - `test_permission_manager.py` → 适配 `PermissionProvider` 接口
     - `test_tool_permission_manager.py` → 标记为 deprecated（逻辑已合入 `PermissionProvider`）
     - `test_loop_engine.py` → 适配 `DefaultLoopEngine` + 新参数签名
     - `test_context_compressor.py` → 适配 `CompressorContext` 参数
     - `test_memory_manager.py` → 适配 `SessionMemoryManager` deprecated

- **预期产出**：`broca/tests/test_component_compatibility.py` + 更新后的现有测试文件
- **验收标准**：
  - [ ] 23 个组件的 ABC 兼容性测试全部通过
  - [ ] 所有 `@abstractmethod` 在默认实现中均已覆盖
  - [ ] Phase 2~4 涉及的现有测试文件已适配新接口并全部通过
  - [ ] `pytest broca/tests/ -v` 全量通过

---

### Phase 6: Agent 组合根重构

**目标**：重构 `Agent.create()` 为基于 ComponentRegistry 的组合根，解耦所有循环依赖

**阶段验收标准**：
- [ ] `Agent.create()` 通过 `ComponentRegistry` 获取所有组件实例
- [ ] `Agent` 不再直接 `new` 任何组件
- [ ] `Agent ↔ LoopEngine` 循环依赖已解除（通过 `AgentReference` Protocol）
- [ ] 所有 Agent 创建/恢复流程测试通过
- [ ] 完整的 Agent 执行流程（消息→LLM→工具→结果）端到端测试通过

#### Task 6.1: 重构 Agent.create()

- **目标**：`Agent.create()` 使用 ComponentRegistry 组装所有组件
- **步骤**：
  1. 重构 `Agent.create()` 方法：
     ```python
     @classmethod
     async def create(cls, config, llm_client, session_manager, **kwargs) -> "Agent":
         agent = cls.__new__(cls)
         Agent.__init__(agent, config, llm_client, session_manager, **kwargs)
         
         registry = ComponentRegistry.get_instance()
         
         # 通过注册表获取/创建组件
         agent.context = Context(config, session_manager, **kwargs)
         agent.communicator = registry.get(Communicator, agent_id=agent.agent_id, ...)
         agent.permission_manager = registry.get(PermissionProvider, ...)
         tool_executor = registry.get(ToolExecutor)
         await agent._setup_tools()
         context_compressor = registry.get(ContextCompressor)
         memory_manager = registry.get(MemoryManager)
         tool_manager = registry.get(ToolManager)
         
         # 初始化有依赖关系的组件
         await tool_executor.initialize(agent.tool_mapping, agent.permission_manager, config)
         
         # 组装执行引擎
          agent.execution_engine = registry.get(LoopEngine)
         agent.execution_engine.initialize(
             agent_ref=AgentReferenceAdapter(agent),
             llm_client=llm_client,
             context=agent.context,
             tool_executor=tool_executor,
             context_compressor=context_compressor,
             memory_manager=memory_manager,
             communicator=agent.communicator,
             session_manager=session_manager,
             config=config,
         )
         
         # 命令系统
         command_system = registry.get(CommandSystem)
         agent.command_manager = command_system
         await command_system.initialize(agent)
         
         return agent
     ```
  
  2. 创建 `AgentReferenceAdapter`：
     ```python
     class AgentReferenceAdapter:
         """将 Agent 包装为 AgentReference Protocol 实现，
         仅暴露 LoopEngine 需要的回调方法，避免循环依赖。"""
         def __init__(self, agent: Agent):
             self._agent = agent
         
         @property
         def agent_id(self): return self._agent.agent_id
         @property
         def session_id(self): return self._agent.session_id
         @property
         def turn_id(self): return self._agent.turn_id
         
         async def on_llm_call_completed(self, i, o): await self._agent.on_llm_call_completed(i, o)
         async def ask_for_permission(self, msg): return await self._agent.ask_for_permission(msg)
         async def ask_for_tool_permission(self, name, args): return await self._agent.ask_for_tool_permission(name, args)
     ```

- **预期产出**：重构后的 `broca/agent.py`
- **验收标准**：
  - [ ] `Agent.create()` 不再直接实例化任何组件类
  - [ ] 所有组件通过 `ComponentRegistry.get()` 获取
  - [ ] `AgentReferenceAdapter` 正确实现了 `AgentReference` Protocol
  - [ ] Agent 创建后所有组件正确连接

#### Task 6.2: AgentFactory 组件化

- **目标**：`AgentFactory` 实现 `AgentFactory` ABC
- **步骤**：
  1. 现有 `AgentFactory` 改为 `DefaultAgentFactory(AgentFactory)`
  2. `DefaultAgentFactory` 内部使用 `ComponentRegistry` 创建 Agent
  3. 去除 `AgentFactory` 的单例模式（或保留但通过 Registry 管理）
  4. `SessionRunner`、`MemoryManager`、`SessionMemoryManager`（deprecated）中的 `AgentFactory()` 引用改为通过 Registry

- **预期产出**：修改后的 `broca/agent_manager.py`
- **验收标准**：
  - [ ] `DefaultAgentFactory` 继承 `AgentFactory` ABC
  - [ ] Agent 创建通过 ComponentRegistry
  - [ ] Agent 恢复流程测试通过

#### Task 6.3: Agent 组合集成测试

- **目标**：验证 `Agent.create()` 通过 ComponentRegistry 组装的完整组件栈工作正确，覆盖组件间连接和循环依赖解除
- **步骤**：
  1. 创建 `broca/tests/test_agent_composition.py`
  2. 测试场景：
     - `test_agent_create_with_defaults` — 不配置任何插件 → `Agent.create()` 成功 → 所有组件为默认实现
     - `test_agent_create_with_custom_tool_executor` — 通过 `components.json` 替换 `ToolExecutor` → Agent 创建成功 → 工具执行走自定义实现
     - `test_agent_create_with_custom_llm_client` — 替换 `LLMClient` → LLM 调用走自定义实现
     - `test_agent_reference_adapters` — `AgentReferenceAdapter` 正确代理 `on_llm_call_completed`、`ask_for_permission`、`ask_for_tool_permission`
     - `test_no_circular_import` — 验证 `import broca.agent` 和 `import broca.loop_engine` 不产生循环导入
     - `test_agent_full_lifecycle` — 创建 Agent → 发送消息 → LLM 响应 → 工具执行 → 结果保存 → Agent 关闭
     - `test_agent_restore_from_session` — 从 session 恢复 Agent → 组件栈重建 → 状态正确
  3. 使用 `fresh_registry` fixture 隔离每个测试
  4. 使用 `mock_llm_client` 避免真实 API 调用

- **预期产出**：`broca/tests/test_agent_composition.py`（≥ 7 个测试函数）
- **验收标准**：
  - [ ] 7 个测试场景全部通过
  - [ ] 无循环导入错误
  - [ ] 自定义组件通过 `components.json` 正确替换
  - [ ] `AgentReferenceAdapter` 的 3 个回调方法代理正确

---

### Phase 7: 集成验证

**目标**：全量验证组件化改造后的系统正确性

**阶段验收标准**：
- [ ] `pytest broca/tests/` 全部通过，测试总数 ≥ 600
- [ ] `pytest broca-web/tests/` 全部通过
- [ ] `pytest broca-tui/tests/` 全部通过
- [ ] 核心模块行覆盖率 ≥ 80%（`broca/components/`、`executor.py`、`loop_engine.py`、`context_compressor.py`、`agent.py`）
- [ ] 插件加载机制端到端测试通过（`test_plugin_loading.py`）
- [ ] 10 个 E2E 回归场景全部通过（`test_e2e_scenarios.py`）
- [ ] 手动验证：启动 Broca，执行一轮完整的 Agent 对话（含工具调用、上下文压缩）
- [ ] 组件配置覆盖验证：通过 `components.json` 替换一个组件后系统正常工作

#### Task 7.1: 全量测试 + 覆盖率对比

- **步骤**：
  1. 运行 `pytest broca/tests/ -v --tb=short`，修复所有因接口变更导致的测试失败
  2. 运行 `pytest broca-web/tests/ -v --tb=short`
  3. 运行 `pytest broca-tui/tests/ -v --tb=short`
  4. 运行覆盖率报告：`pytest broca/tests/ --cov=broca --cov-report=term-missing --cov-report=html`
  5. 对比改造前/后覆盖率：
     - 总测试数：522（基线）→ ≥ 600（目标）
     - 核心模块覆盖率（`broca/components/`、`broca/tools/executor.py`、`broca/loop_engine.py`、`broca/context_compressor.py`、`broca/agent.py`）≥ 80%
  6. 特别关注：
     - `test_loop_engine.py`（LoopEngine 接口变更）
     - `test_context_compressor.py`（ContextCompressor 重构）
     - `test_memory_manager.py`（SessionMemoryManager deprecated）
     - `test_llm.py`（LLMClient 接口变更）
     - `test_permission_manager.py`（PermissionProvider 合并）
     - `test_tool_base.py`（Tool 基类不变，但 ToolCallContext 可能有变化）
  7. 检查是否有测试被 `pytest.mark.skip` 跳过——所有跳过必须附带理由和 TODO 注释

- **验收标准**：
  - [ ] `pytest broca/tests/` 全部通过，无跳过（或所有跳过有理由）
  - [ ] `pytest broca-web/tests/` 全部通过
  - [ ] `pytest broca-tui/tests/` 全部通过
  - [ ] 总测试数 ≥ 600
  - [ ] 核心模块行覆盖率 ≥ 80%
  - [ ] 无新增的 `pytest.mark.skip`

#### Task 7.2: 插件加载验证 + E2E 回归测试

- **步骤**：
  1. **插件包测试**：创建 `broca/tests/test_plugin_loading.py`
     - 创建一个最小化的测试插件模块（`MockSandboxToolExecutor`），实现 `ToolExecutor` ABC
     - 测试 entry point 发现：模拟 `entry_points()` 返回测试插件 → `ComponentRegistry` 正确发现
     - 测试配置覆盖：写入 `components.json` → 验证 `ComponentRegistry.resolve()` 返回测试插件
     - 测试默认回退：不配置任何插件 → 验证使用 `DefaultToolExecutor`
     - 测试错误处理：配置了不存在的类名 → 验证抛出 `ComponentError` 且消息清晰
     - 测试多插件冲突：两个 entry point 注册同一接口 → 验证优先级行为
  2. **E2E 回归测试**：执行"测试策略"章节中列出的 10 个关键回归场景：
     - 场景 1-3：基础对话、工具调用、权限 ask
     - 场景 4：并行工具
     - 场景 5-6：上下文压缩、强制压缩
     - 场景 7：死循环检测
     - 场景 8-9：组件替换、插件发现
     - 场景 10：错误恢复
  3. 创建 `broca/tests/test_e2e_scenarios.py`，每个场景一个测试函数
  4. E2E 测试使用 `ComponentRegistry` + mock LLM/Communicator（不依赖真实 SocketIO 连接）

- **预期产出**：`broca/tests/test_plugin_loading.py`、`broca/tests/test_e2e_scenarios.py`
- **验收标准**：
  - [ ] 插件发现、配置覆盖、默认回退、错误处理 5 个场景全部通过
  - [ ] 10 个 E2E 回归场景全部通过
  - [ ] 模拟插件替换 ToolExecutor 后，工具执行走插件实现
  - [ ] 错误配置不会导致系统崩溃（有 fallback）

#### Task 7.3: 文档与示例

- **步骤**：
  1. 更新 `README.md` 添加组件化架构说明
  2. 创建 `docs/plugin-development-guide.md`——第三方插件开发指南
  3. 包含示例：如何创建一个自定义 ToolExecutor（如沙箱执行器）
  4. 包含示例：如何替换 LLMClient 为本地模型

- **预期产出**：文档文件
- **验收标准**：
  - [ ] 开发者能根据文档在 30 分钟内创建一个简单插件
  - [ ] 文档包含完整的代码示例和 pyproject.toml 配置

---

## 风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| 23 个组件接口定义不准确，后续需要修改 | 高——接口变更影响所有实现 | Phase 1 中逐个与现有实现对比方法签名，确保兼容；Task 5.5 自动验证 ABC 兼容性 |
| 循环依赖（Agent ↔ LoopEngine ↔ ToolExecutor）难以完全解除 | 中——可能残留部分引用 | 使用 `AgentReference` Protocol + 适配器模式；Task 6.3 包含 `test_no_circular_import` 测试 |
| SessionMemoryManager 合入 ContextCompressor 后代码量增大 | 低——单一文件可能超过 500 行 | 可拆分为 `context_compressor/` 子包（base + session_memory 实现） |
| 第三方插件与内部状态不兼容（如访问 agent 内部属性） | 中——插件开发者困惑 | 在 `ToolCallContext` 中明确提供所有插件需要的字段，文档中说明 |
| 大规模重构导致回归 bug | 高——影响生产 | 每个 Phase 完成后跑全量测试；Phase 7 包含 10 个 E2E 回归场景 |
| ComponentRegistry 的单例模式在测试中造成状态污染 | 中——测试间互相影响 | 提供 `ComponentRegistry.reset()` 方法 + `fresh_registry` fixture（Task 1.4） |
| 现有用户配置不兼容 | 低——配置格式未变 | 组件配置是新增的，不影响现有 `configs.json` 格式 |
| 组件间接口参数过多，ABC 设计过度或不足 | 中——接口太宽则插件实现困难，太窄则无法扩展 | Phase 1 逐个与现有实现对比；Protocol 使用结构化类型（非继承）降低耦合 |
| litellm API 变化导致 LLMClient 接口不稳定 | 中——接口需要频繁修改 | `LiteLLMClient` 内部封装 litellm 调用细节，ABC 只暴露稳定的 `get_stream_response()` 接口 |
| 测试 mock 与实际行为偏差（如 mock LLM 无法覆盖流式响应边界情况） | 中——测试通过但实际运行有问题 | Phase 4.5/7.2 的 E2E 测试使用接近真实的流式响应模式；保留 1-2 个真实 API 调用的 smoke test（标记 `@pytest.mark.integration`） |
| Phase 2.3 的 Agent.create() 中间状态与 Phase 6.1 最终状态差异大，增加理解成本 | 低——代码可读性 | Phase 2.3 中明确注释"中间步骤，Phase 6.1 将彻底重构"；git commit message 中标注 |

## 未解决的问题

- 无（所有关键设计决策已与用户确认）
