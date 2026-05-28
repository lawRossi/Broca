# 代码审查流水线 Demo

一个 Pipeline 流水线编排的 Demo，多个 Agent 按顺序依次执行，前一个 Agent 的输出作为后一个 Agent 的输入。

## 场景

模拟一个完整的代码审查流水线，包含三个步骤：
- **代码审查员**：对提交的代码进行静态分析、检查代码规范、逻辑错误
- **安全审计员**：审查代码是否存在安全漏洞、注入风险、敏感信息泄露
- **质量管理员**：综合前两步结果，给出最终的质量评分和改进建议

## 拓扑特征

- **有序步骤列表**：每个步骤指定 Agent + 任务描述，按严格顺序执行
- **前一步输出自动注入**：后一个 Agent 能访问前一步的结果
- **结果累加**：所有步骤的结果在最终汇总
- **错误中断**：某步骤失败可选择终止整个流水线

## 使用方法

### 方式一：通过 Web UI 创建编排会话

1. 启动 Broca 服务
2. 访问 Web 界面
3. 创建「Agent 编排」类型会话，工作目录指向 `examples/pipeline`
4. 进入编排管理页面
5. 选择预置模板「代码审查流水线」或直接使用 `crew.yaml`
6. 提交执行

### 方式二：通过 API 提交

```bash
curl -X POST http://localhost:9000/api/crews \
  -H "Content-Type: application/json" \
  -d '{
    "yaml_path": "/path/to/examples/pipeline/crew.yaml",
    "session_id": "<your-session-id>"
  }'
```

### 方式三：直接校验配置

```bash
broca run ./examples/pipeline/crew.yaml --validate
```

## 自定义

### 修改审查代码

编辑 `crew.yaml` 中 `blackboard.initial_entries` 下的 `code_to_review` 值。

### 调整审查步骤

修改 `crew.yaml` 中 `orchestrator.extras.steps` 列表，可增删步骤或调整顺序。

### 自定义 Agent

编辑 `.broca/agents/` 下的 Agent 配置文件。

## 文件结构

```
examples/pipeline/
├── README.md                          # 本文件
├── crew.yaml                          # 编排配置（主入口）
└── .broca/agents/
    ├── code_reviewer.md               # 代码审查员 Agent
    ├── security_auditor.md            # 安全审计员 Agent
    └── quality_manager.md             # 质量管理员 Agent
```
