# 项目结构

> [← 返回 README](../README.md)

完整的目录树与各模块职责说明。

```
Broca/
├── broca/                          # 核心 Python 包
│   ├── cli/                        # CLI 入口
│   │   └── main.py                 # 命令行解析与服务启动
│   ├── communication/              # 通信层
│   │   ├── socketio_server.py      # Socket.IO 服务端
│   │   └── socketio_client.py      # Socket.IO 客户端 + 投递 ACK / 线序控制
│   ├── agent_messenger/            # Agent 间通信
│   │   ├── messenger.py            # DefaultAgentMessenger（request/notify/delegate）
│   │   ├── message_models.py       # AgentCommunication 消息模型
│   │   ├── call_chain.py           # 调用链环检测
│   │   └── audit.py                # JSONL 审计日志
│   ├── media/                      # 媒体引用与按需物化
│   │   ├── ref.py                  # ref:// 引用编解码
│   │   ├── materializer.py         # base64 / file_id 物化决策
│   │   ├── files_api.py            # FilesApiStrategy 抽象 + 注册表
│   │   ├── deepseek_files.py       # DeepSeek Files API 实现
│   │   ├── cache.py                # 每 Agent 持久化缓存（TTL 3 天）
│   │   ├── storage.py              # S3 / HTTP 字节读取
│   │   └── errors.py               # 媒体错误类型
│   ├── session/                    # 会话管理
│   │   ├── database.py             # 数据库连接
│   │   ├── models.py               # 数据模型
│   │   ├── service.py              # CRUD 服务
│   │   ├── session_manager.py      # 会话管理器
│   │   ├── revert_service.py       # 撤销/重做服务
│   │   ├── cleanup_service.py      # 会话删除统一清理（缓存/日志/任务/快照）
│   │   └── db_migration.py         # 数据库迁移
│   ├── components/                 # 组件化插件架构（ABC + Registry）
│   │   ├── base.py                 # BaseComponent 与作用域定义
│   │   ├── registry.py             # ComponentRegistry 单例（三级优先级解析）
│   │   ├── defaults.py             # 默认组件映射与 entry point
│   │   ├── protocols.py            # 轻量 Protocol（CompressorContext / AgentReference 等）
│   │   ├── llm_client.py / llm_strategy.py / tool_strategy.py
│   │   ├── loop_engine.py / loop_hook.py
│   │   ├── agent_factory.py / agent_messenger.py / communicator.py
│   │   ├── context_compressor.py / memory_manager.py / decision_provider.py
│   │   ├── session_manager.py / session_runner.py / snapshot_manager.py
│   │   ├── permission_provider.py / tool_manager.py / tool_executor.py
│   │   ├── mcp_client.py / skill_manager.py / scheduler.py
│   │   ├── command_system.py / task_manager.py / process_manager.py / revert_service.py
│   │   └── orchestrator.py / errors.py
│   ├── persistent_memory/          # 跨会话持久化记忆
│   │   ├── types.py                # 数据结构（MemoryType/MemoryEntry + frontmatter 解析）
│   │   ├── store.py                # 存储管理器（CRUD + 索引 + 新鲜度 + 路径安全）
│   │   ├── state.py                # 提取状态管理
│   │   ├── manager.py              # SubAgentMemoryManager（自动 + /remember 触发）
│   │   └── prompts.py              # 提取子 Agent 提示词（加载提取 Skill）
│   ├── snapshot/                   # 快照系统
│   │   ├── manager.py              # GitSnapshotManager（跨进程文件锁）
│   │   ├── git_manager.py          # Git 操作与忽略规则
│   │   ├── track.py                # 快照捕获
│   │   ├── patch.py                # 变更计算
│   │   └── restore.py              # 文件恢复
│   ├── session_runner/             # 子进程 Runner（分层架构）
│   │   ├── manager.py              # 父进程编排层（进程/事件/监控生命周期）
│   │   ├── runner.py               # 子进程入口（SessionRunnerProcess）
│   │   ├── orchestrator_runner.py  # 编排运行器（管理编排生命周期/进度推送）
│   │   ├── poller.py               # IPC 单线程多路复用 poller（父进程侧，O(1) 线程）
│   │   ├── protocol.py             # 实例级 MessageRouter（命令/响应/事件分发）
│   │   ├── events.py               # 类型化事件 + TaskSet（session_id → 命令任务）
│   │   ├── repository.py           # RunnerRepository（DB 读写批量优化）
│   │   ├── monitor.py              # HeartbeatMonitor（纯策略，不直接写库）
│   │   ├── backpressure.py         # 队列背压（DroppedEvents 计数 + 丢弃策略）
│   │   ├── ipc.py                  # 进程间通信（地址/编解码）
│   │   ├── models.py               # 数据结构
│   │   ├── process/                # 进程管理
│   │   │   ├── launcher.py         # 子进程启动（start_new_session，防 Ctrl+C 串扰）
│   │   │   ├── reaper.py           # 进程回收
│   │   │   └── registry.py         # RunnerHandle / RunnerRegistry
│   │   └── transport/              # IPC 传输层（Unix Socket / Named Pipe）
│   │       ├── base.py             # 传输基类
│   │       ├── server.py           # 父进程端 server
│   │       ├── client.py           # 子进程端 client
│   │       └── addresses.py        # 地址解析
│   ├── tools/                      # 工具系统
│   │   ├── tool.py                 # 工具基类（is_readonly / extra_context_messages）
│   │   ├── tool_manager.py         # 工具管理器（自动发现 + 只读集合）
│   │   ├── tool_permission_manager.py # 工具权限管理
│   │   ├── executor.py             # 默认工具执行器
│   │   ├── mcp_client.py           # MCP 客户端
│   │   ├── filesystem.py           # 文件操作工具（read/edit/write/list/tree/mtime）
│   │   ├── glob.py / grep.py       # 文件搜索工具
│   │   ├── bash.py                 # 命令执行工具
│   │   ├── process.py              # 进程管理工具
│   │   ├── web.py                  # 网络工具（fetch/search）
│   │   ├── image.py                # 图像工具
│   │   ├── task.py / todo.py       # 任务管理工具
│   │   ├── cron.py                 # 定时任务工具
│   │   ├── skill.py                # 技能加载 + 管理工具（LoadSkill / SkillManage）
│   │   ├── blackboard.py           # 黑板读写工具
│   │   ├── agent_interaction.py    # AskUser（人机交互）+ Communicate（Agent 间）
│   │   └── mcp.py                  # MCP 工具加载
│   ├── skill/                      # Skill 系统
│   │   ├── skill_manager.py        # Skill 加载/解析/索引管理
│   │   ├── skill_store.py          # Skill 元数据管理（来源标记/状态/统计/归档恢复）
│   │   └── skill_evolution.py      # 子 Agent Skill 进化工具函数
│   ├── errors/                     # 异常体系
│   │   ├── exceptions.py           # 异常类定义
│   │   ├── types.py                # 错误码枚举
│   │   └── utils.py                # 错误处理工具
│   ├── utils/                      # 工具函数
│   │   ├── content_security.py     # 内容安全检测（提示注入/数据泄露）
│   │   ├── shell_security.py       # Shell 命令安全检测（tree-sitter）
│   │   ├── env.py                  # 用户命令环境重建（剥离 runner 内部变量）
│   │   └── datetime_util.py        # 时间工具
│   ├── agent.py                    # Agent 类（组合根 Agent.create()）
│   ├── agent_configs.py            # Agent 配置（含通信策略/压缩/记忆配置）
│   ├── agent_manager.py            # Agent 工厂（AgentFactory 单例）
│   ├── agent_reference.py          # AgentReferenceAdapter（打破 Agent↔引擎循环引用）
│   ├── orchestration/              # 多 Agent 编排系统
│   │   ├── orchestrator.py         # 编排器基类 + 共享并行执行器 + 工厂 + 条件求值
│   │   ├── crew.py                 # 编排数据结构 (CrewConfig/OrchestratorType/角色/校验器)
│   │   ├── blackboard.py           # 共享黑板（版本化、事件通知、变更日志）
│   │   ├── graph_model.py          # 有向图数据模型 (Node/Edge/Router/Graph/GraphBuilder)
│   │   ├── graph_orchestrator.py   # 有向图编排基类（图遍历/路由/并行/汇聚/HITL）
│   │   ├── pipeline.py             # Pipeline 流水线（有向图版，继承 GraphOrchestrator）
│   │   ├── supervisor_worker.py    # Supervisor-Worker 主管-工人拓扑（独立实现）
│   │   ├── round_table.py          # Round-Table 圆桌讨论拓扑（独立实现，支持每轮自定义配置）
│   │   ├── composite.py            # Composite 组合嵌套（有向图版，继承 GraphOrchestrator，支持 CREW 节点）
│   │   ├── prompt_loader.py        # Jinja2 提示词模板加载器
│   │   ├── templates.py            # 模板辅助函数
│   │   └── prompts/                # 按拓扑分组的 Jinja2 提示词模板
│   │       ├── graph/              #   图编排通用模板（task_context, execute_step, fan_in_agent, human_node, agent_route）
│   │       ├── supervisor_worker/  #   supervisor-worker 模板（plan, check_and_plan, synthesize）
│   │       └── round_table/        #   round-table 模板（discussion, moderator_*）
│   ├── commands/                   # 命令系统
│   │   ├── base.py                 # 命令基类（CommandBase/LocalCommand/PromptCommand）
│   │   ├── registry.py             # 命令注册中心
│   │   ├── loader.py               # 命令自动加载器
│   │   ├── dispatcher.py           # 命令分发器
│   │   ├── manager.py              # 命令管理器
│   │   ├── builtin/                # 内置本地命令（help/abort/undo/redo/compact/clear-*/remember/skill*）
│   │   └── prompt/                 # 内置提示命令（init/plan/debug/review-*/execute-plan）
│   ├── loop_engine/                # 循环执行引擎（Strategy + Hook）
│   │   ├── engine.py               # DefaultLoopEngine（生命周期编排 + 非阻塞排空）
│   │   ├── tool_injected_messages.py # 工具注入消息的持久化与顺序保证
│   │   ├── chunk_flush.py / compressor_context.py
│   │   ├── strategies/             # RetryLLMStrategy / Serial / ParallelToolStrategy / factory
│   │   └── hooks/                  # Snapshot / LifecycleBroadcast / DeadLoop / Compression / ContextCleanup + factory
│   ├── context.py                  # 上下文管理
│   ├── context_compressor.py       # SessionMemoryCompressor（原 session_memory 已合并至此）
│   ├── llm.py                      # LLM 客户端（litellm 封装）
│   ├── decision.py                 # 决策模型客户端（typesafe-sdk 封装）
│   ├── logging_config.py           # 日志配置
│   ├── scheduler.py                # 任务调度器
│   ├── permission_manager.py       # 权限管理
│   ├── process_manager.py          # 进程管理
│   ├── service_manager.py          # 服务管理（supervisor 集成）
│   ├── task_manager.py             # 任务管理
│   ├── alembic/                    # 数据库迁移脚本
│   ├── tests/                      # 测试
│   └── configs.py                  # 全局配置
├── broca-tui/                      # TUI 终端界面（Textual）
│   └── broca_tui/
│       ├── app.py                  # TUI 应用入口
│       ├── config.py               # TUI 配置
│       ├── api/                    # Socket.IO API 客户端
│       ├── screens/                # 屏幕组件（Chat, Sessions, Settings）
│       ├── widgets/                # 小组件（AgentCard, MessageItem, InputBar）
│       ├── stores/                 # 状态管理
│       └── theme/                  # 主题样式
├── broca-web/                      # Web 应用
│   ├── backend/                    # FastAPI 后端
│   │   ├── app/
│   │   │   ├── api/                # REST API 路由
│   │   │   ├── core/               # 核心配置（SocketIO、DB）
│   │   │   ├── models/             # 数据模型
│   │   │   ├── schemas/            # Pydantic schema
│   │   │   ├── services/           # 业务服务
│   │   │   ├── asr/                # 语音识别（ASR）
│   │   │   ├── utils/              # 工具函数
│   │   │   └── main.py             # 应用入口
│   │   ├── alembic/                # 数据库迁移脚本
│   │   ├── alembic.ini             # Alembic 配置
│   │   ├── manage.py               # 管理脚本
│   │   └── pyproject.toml
│   └── frontend/                   # Vue 3 前端
│       └── src/
│           ├── api/                # API 客户端
│           ├── components/         # UI 组件
│           ├── views/              # 页面视图
│           ├── stores/             # Pinia 状态
│           ├── router/             # 路由
│           ├── services/           # 前端服务
│           ├── styles/             # 样式
│           ├── utils/              # 工具函数
│           └── App.vue             # 根组件
├── broca-vscode/                   # VS Code 扩展
│   └── src/
│       ├── extension/              # 扩展主逻辑
│       └── webview/                # Chat Webview
├── alembic/                        # 顶层数据库迁移
├── configs/                        # 配置文件
│   ├── configs.json                # 全局配置（含 execution 段）
│   ├── llm_config.json             # LLM 配置（实际生效）
│   ├── llm_config_template.json    # LLM 配置模板（含媒体 Files API 示例）
│   ├── decision_config.json        # 决策模型配置
│   ├── tool_permission_config.json # 工具权限配置
│   └── agents/                     # Agent 角色配置
├── data/                           # 数据目录（SQLite 数据库）
├── skills/                         # 内置 Skills（含 persistent-memory-extraction）
├── examples/                       # 编排示例
├── plans/                          # 计划文档
├── reports/                        # 执行/评审/性能报告
├── docs/                           # 文档
├── scripts/                        # 安装/部署脚本
├── resource/                       # 资源文件
└── pyproject.toml                  # 项目元数据
```
