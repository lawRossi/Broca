# 圆桌辩论 Demo

一个多 Agent 圆桌辩论的编排 Demo，使用 Round-Table 拓扑。

## 场景

四个 AI Agent 围绕一个议题进行多轮辩论：
- **主持人**：控制讨论节奏，引导话题，最终总结结论
- **正方**：支持议题的观点
- **反方**：反对议题的观点  
- **中立评估员**：客观分析双方论点，提供中立视角

## 使用方法

### 方式一：通过 Web UI 创建编排会话

1. 启动 Broca 服务
2. 访问 Web 界面
3. 创建「Agent 编排」类型会话，工作目录指向 `examples/debate`
4. 进入编排管理页面
5. 选择预置模板「圆桌辩论」或直接使用 `crew.yaml`
6. 提交执行

### 方式二：通过 CLI 提交

```bash
# 先启动 Broca 服务
broca web

# 通过 API 提交
curl -X POST http://localhost:9000/api/crews \
  -H "Content-Type: application/json" \
  -d '{
    "yaml_path": "/path/to/examples/debate/crew.yaml",
    "session_id": "<your-session-id>"
  }'
```

### 方式三：直接校验配置

```bash
broca run ./examples/debate/crew.yaml --validate
```

## 自定义

### 修改辩论主题

编辑 `crew.yaml` 中 `blackboard.initial_entries` 下的 `topic` 值。

### 调整辩论轮数

修改 `crew.yaml` 中 `orchestrator.max_rounds` 的值。

### 添加更多参与者

在 `crew.yaml` 的 `agents` 列表中添加新的 `participant`，可设置 `extras.stance` 指定立场。

## 文件结构

```
examples/debate/
├── README.md                    # 本文件
├── crew.yaml                    # 编排配置（主入口）
└── .broca/agents/
    ├── moderator.md             # 主持人 Agent 配置
    ├── debater.md               # 辩论员 Agent 配置（正方/反方共用）
    └── analyst.md               # 中立评估员 Agent 配置
```
