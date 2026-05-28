# 方案评估决策 Demo

一个 Consensus 共识编排的 Demo，多个专家独立评估同一方案，通过评分/投票达成共识。

## 场景

对一个「远程办公政策方案」进行多维度评估，由不同角色的专家独立打分，最终汇聚决策：
- **人力资源专家（Reviewer）**：从员工管理、招聘、团队文化角度评估
- **技术经理（Reviewer）**：从技术基础设施、安全合规、效率角度评估
- **财务分析师（Reviewer）**：从成本控制、ROI、预算分配角度评估

## 拓扑特征

- **多个 Reviewer 独立评估**：每个专家独立阅读方案并给出评分
- **多种聚合策略**：支持 average / majority / unanimous / weighted 四种策略
- **通过阈值可配置**：可设定通过所需的最低分数
- **分歧点标记**：自动识别并标记少数派的异议

## 使用方法

### 方式一：通过 Web UI 创建编排会话

1. 启动 Broca 服务
2. 访问 Web 界面
3. 创建「Agent 编排」类型会话，工作目录指向 `examples/consensus`
4. 进入编排管理页面
5. 选择预置模板「方案评估决策」或直接使用 `crew.yaml`
6. 提交执行

### 方式二：通过 API 提交

```bash
curl -X POST http://localhost:9000/api/crews \
  -H "Content-Type: application/json" \
  -d '{
    "yaml_path": "/path/to/examples/consensus/crew.yaml",
    "session_id": "<your-session-id>"
  }'
```

### 方式三：直接校验配置

```bash
broca run ./examples/consensus/crew.yaml --validate
```

## 自定义

### 修改评估方案

编辑 `crew.yaml` 中 `blackboard.initial_entries` 下的 `review_target` 值。

### 调整聚合策略

修改 `crew.yaml` 中 `orchestrator.strategy`（可选：average/majority/unanimous/weighted）。

### 调整权重和阈值

修改 `orchestrator.weights` 和 `orchestrator.threshold` 的值。

### 自定义 Agent

编辑 `.broca/agents/` 下的 Agent 配置文件。

## 文件结构

```
examples/consensus/
├── README.md                          # 本文件
├── crew.yaml                          # 编排配置（主入口）
└── .broca/agents/
    ├── hr_expert.md                   # 人力资源专家 Agent
    ├── tech_manager.md                # 技术经理 Agent
    └── finance_analyst.md             # 财务分析师 Agent
```
