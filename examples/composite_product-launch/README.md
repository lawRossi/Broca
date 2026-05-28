# 产品发布决策 Demo

一个 Composite 组合嵌套编排的 Demo，将多种编排拓扑组合使用，模拟完整的产品发布决策流程。

## 场景

模拟一个完整的产品发布决策流程，结合三种编排拓扑：

### 主流程：Supervisor-Worker
**发布协调员**作为主管，统筹整个产品发布决策流程，协调各团队工作。

### 子流程 1：Broadcast（市场调研）
多个研究员同时从不同维度进行市场调研：
- **市场研究员**：分析目标市场规模和竞争格局
- **用户研究员**：分析用户反馈和需求验证
- **技术评估员**：评估产品质量和技术就绪度

### 子流程 2：Consensus（发布决策评审）
多位决策者对发布准备情况进行评估和投票：
- **业务负责人**：从商业价值角度评估
- **质量经理**：从产品质量角度评估
- **风险管理员**：从风险控制角度评估

## 拓扑特征

- **组合嵌套**：主流程 Supervisor-Worker 中的特定步骤嵌入子 Crew
- **子 Crew 独立编排**：每个子 Crew 可以使用不同的编排拓扑
- **黑板共享**：所有子 Crew 共享同一块黑板，数据互通
- **阶段式推进**：只有当前阶段完成后才进入下一阶段

## 使用方法

### 方式一：通过 Web UI 创建编排会话

1. 启动 Broca 服务
2. 访问 Web 界面
3. 创建「Agent 编排」类型会话，工作目录指向 `examples/composite`
4. 进入编排管理页面
5. 选择预置模板「产品发布决策」或直接使用 `crew.yaml`
6. 提交执行

### 方式二：通过 API 提交

```bash
curl -X POST http://localhost:9000/api/crews \
  -H "Content-Type: application/json" \
  -d '{
    "yaml_path": "/path/to/examples/composite/crew.yaml",
    "session_id": "<your-session-id>"
  }'
```

### 方式三：直接校验配置

```bash
broca run ./examples/composite/crew.yaml --validate
```

## 自定义

### 修改产品信息

编辑 `crew.yaml` 中 `blackboard.initial_entries` 下的 `product_info` 和 `objective` 值。

### 调整子流程

修改 `sub_crews` 列表，可增删子 Crew 或更改其拓扑类型。

### 自定义 Agent

编辑 `.broca/agents/` 下的 Agent 配置文件。

## 文件结构

```
examples/composite/
├── README.md                              # 本文件
├── crew.yaml                              # 编排配置（主入口）
└── .broca/agents/
    ├── launch_coordinator.md              # 发布协调员 Agent（Supervisor）
    ├── market_researcher.md               # 市场研究员 Agent
    ├── user_researcher.md                 # 用户研究员 Agent
    ├── tech_assessor.md                   # 技术评估员 Agent
    ├── business_director.md               # 业务负责人 Agent（Reviewer）
    ├── quality_manager.md                 # 质量经理 Agent（Reviewer）
    └── risk_manager.md                    # 风险管理员 Agent（Reviewer）
```
