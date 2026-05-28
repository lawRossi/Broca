# 多维度竞品分析 Demo

一个 Broadcast 广播编排的 Demo，模拟将同一任务分发给多个 Agent 独立处理，最后聚合结果。

## 场景

对一款产品（智能健身镜）进行多维度的竞品分析：
- **任务分发器（Dispatcher）**：将分析任务分解为多个维度，分发给各专家
- **市场分析师（Worker）**：从市场定位和商业策略角度分析
- **技术专家（Worker）**：从技术架构和功能实现角度分析
- **用户体验专家（Worker）**：从用户交互和体验设计角度分析
- **结果汇总器（Aggregator）**：汇总所有专家的分析，形成综合报告

## 拓扑特征

- **Dispatcher 分解任务**：将主任务拆分为多个并行子任务
- **Worker 并行执行**：所有 Worker 同时独立执行子任务
- **Aggregator 汇总**：收集所有 Worker 结果，整合为统一输出

## 使用方法

### 方式一：通过 Web UI 创建编排会话

1. 启动 Broca 服务
2. 访问 Web 界面
3. 创建「Agent 编排」类型会话，工作目录指向 `examples/broadcast`
4. 进入编排管理页面
5. 选择预置模板「多维度竞品分析」或直接使用 `crew.yaml`
6. 提交执行

### 方式二：通过 API 提交

```bash
curl -X POST http://localhost:9000/api/crews \
  -H "Content-Type: application/json" \
  -d '{
    "yaml_path": "/path/to/examples/broadcast/crew.yaml",
    "session_id": "<your-session-id>"
  }'
```

### 方式三：直接校验配置

```bash
broca run ./examples/broadcast/crew.yaml --validate
```

## 自定义

### 修改分析对象

编辑 `crew.yaml` 中 `blackboard.initial_entries` 下的 `task` 值。

### 增删分析维度

修改 `crew.yaml` 中 `agents` 列表，添加或移除 Worker Agent。

### 自定义 Agent

编辑 `.broca/agents/` 下的 Agent 配置文件。

## 文件结构

```
examples/broadcast/
├── README.md                          # 本文件
├── crew.yaml                          # 编排配置（主入口）
└── .broca/agents/
    ├── dispatcher.md                  # 任务分发器 Agent
    ├── market_analyst.md              # 市场分析师 Agent
    ├── tech_expert.md                 # 技术专家 Agent
    ├── ux_expert.md                   # 用户体验专家 Agent
    └── aggregator.md                  # 结果汇总器 Agent
```
