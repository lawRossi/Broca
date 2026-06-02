# 研究报告生成 Demo

一个 Supervisor-Worker 编排的 Demo，模拟团队协作完成研究报告的生成流程。

## 场景

模拟一个研究团队协作完成一份「AI 在医疗领域的应用」研究报告：
- **研究主管（Supervisor）**：分解任务、制定研究计划、质量检查、合成最终报告
- **文献研究员（Worker）**：收集和整理相关文献资料
- **数据分析师（Worker）**：分析行业数据和趋势
- **报告撰写人（Worker）**：将研究成果撰写为结构化报告

## 拓扑特征

- **Supervisor 计划生成**：主管将目标分解为子任务
- **Worker 并行执行**：多个 Worker 同时执行子任务
- **质量检查与迭代**：Supervisor 检查结果，决定是否进入下一轮优化
- **结果汇总合成**：所有 Worker 结果被合成最终输出

## 使用方法

### 方式一：通过 Web UI 创建编排会话

1. 启动 Broca 服务
2. 访问 Web 界面
3. 创建「Agent 编排」类型会话，工作目录指向 `examples/supervisor-worker`
4. 进入编排管理页面
5. 选择预置模板「研究报告生成」或直接使用 `crew.yaml`
6. 提交执行

## 自定义

### 修改研究主题

编辑 `crew.yaml` 中 `blackboard.initial_entries` 下的 `objective` 值。

### 调整迭代轮数

修改 `crew.yaml` 中 `orchestrator.max_rounds` 的值。

### 自定义 Agent

编辑 `.broca/agents/` 下的 Agent 配置文件。

## 文件结构

```
examples/supervisor-worker/
├── README.md                               # 本文件
├── crew.yaml                               # 编排配置（主入口）
└── .agents/agents/
    ├── research_director.md                # 研究主管 Agent
    ├── literature_researcher.md            # 文献研究员 Agent
    ├── data_analyst.md                     # 数据分析师 Agent
    └── report_writer.md                    # 报告撰写人 Agent
```
