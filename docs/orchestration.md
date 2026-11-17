> [← 返回 README](../README.md)

# 多智能体编排

**核心文件**: `broca/orchestration/`

Broca 提供 4 种编排拓扑，支持将多个 Agent 组合为复杂工作流。编排器通过 **共享黑板（Blackboard）** 实现 Agent 间状态共享，Agent 通过内置工具（`task_management`、`write_blackboard`）自主协作，无需编排器"推送"任务。

## 架构概览

编排系统基于 **有向图（Graph）** 模型重新设计，Pipeline 和 Composite 共享 `GraphOrchestrator` 基类。图遍历、路由选择、并行执行、循环控制等通用逻辑由基类统一实现。

```
┌─────────────────────────────────────────────────────────────┐
│                    Orchestrator (ABC)                        │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ CrewContext  │  │ Blackboard   │  │ OrchestrationResult│  │
│  └─────────────┘  └──────────────┘  └───────────────────┘  │
└─────────────────────────┬───────────────────────────────────┘
                          │
          ┌───────────────┴───────────────┐
          │                               │
┌─────────▼──────────┐         ┌──────────▼─────────┐
│  GraphOrchestrator  │         │  RoundTable         │
│  (图遍历基类)        │         │  (自定义流程)        │
└──┬───────────────┬──┘         └─────────────────────┘
   │               │
   ▼               ▼
┌──────┐     ┌──────────┐
│Pipeline│   │Composite │
└───────┘    └──────────┘

┌─────────────────────────────────────────────────────────────┐
│                   SupervisorWorker                           │
│              (独立实现，非图驱动)                              │
└─────────────────────────────────────────────────────────────┘
```

## 拓扑总览

| 拓扑 | 说明 | 适用场景 | 状态 |
|------|------|----------|:----:|
| **Pipeline** | 有向图流水线，支持 TASK/HUMAN 节点，static/agent 路由，并行扇出/汇聚，条件跳转与循环 | 有明确步骤的工作流 | ✅ |
| **Supervisor-Worker** | 主管分解任务，工人执行，主管检查/迭代 | 需要分工协作和质量把控 | ✅ |
| **Round-Table** | 多轮圆桌讨论，Moderator 控制节奏，支持每轮自定义配置 | 头脑风暴、辩论、集体决策 | ✅ |
| **Composite** | 有向图组合嵌套，支持 TASK/HUMAN/CREW 三种节点类型 | 复杂工作流编排 | ✅ |

## 核心概念

### 有向图模型（Graph Model）

所有编排以有向图（Graph）定义，包含节点（Node）和边（Edge）：

**节点类型**：

| 类型 | 说明 | 字段 |
|------|------|------|
| `TASK` | 单 Agent 执行任务 | `agent`, `task`, `context` |
| `HUMAN` | 人在环路（HITL），通过 Agent 向用户提问 | `question`, `response_field`, `timeout` |
| `CREW` | 子编排（仅 Composite 使用） | `crew_ref` |

**边（Edge）**：定义节点间的有向连接，支持条件路由：

```python
@dataclass
class Edge:
    target: str                    # 目标节点名称
    description: str = ""          # 描述
    field: Optional[str] = None    # 黑板字段名（条件路由用）
    operator: str = "eq"           # 比较运算符
    value: Any = None              # 目标值
    context: Optional[Dict] = None # 路由时写入黑板的上下文
```

**路由器（Router）**：控制出边选择策略：

| 模式 | 说明 |
|------|------|
| `static` | 基于黑板值条件匹配，支持多选（并行扇出） |
| `agent` | 由指定的 Evaluator Agent 通过 LLM 决策 |
| `static_then_agent` | 先尝试 static 匹配，失败则回退到 agent 决策 |

**图校验（compile）**：`Graph.compile()` 自动校验：
- 入口存在性
- 所有 edge.target 指向存在的节点
- 所有节点从入口可达（无孤立节点）
- Fan-out 汇聚约束（并行分支必须汇聚到同一节点）
- Human 节点完整性
- Router 完整性
- 循环检测与 max_loop 继承

### 共享黑板（Blackboard）

所有编排器共享同一个 `Blackboard` 实例，Agent 通过 `write_blackboard` / `read_blackboard` 工具读写。黑板支持：
- 嵌套路径（`pipeline.step_1.output`）
- 版本化管理（每次写入生成新版本号）
- 变更事件通知（subscribe）
- 变更日志（get_changes）
- 序列化/反序列化（持久化支持）
- 线程安全（asyncio.Lock）

### 命名空间（Namespace）

每个编排器实例拥有独立命名空间（默认为 Crew 名称），黑板 key 自动以 `{namespace}.` 为前缀，确保多级编排间黑板数据隔离。

### 停止约定（Stop Convention）

Agent 通过黑板约定请求停止整个编排：
- Agent 调用 `write_blackboard(key="orchestration.stop", value={"agent": "...", "reason": "..."})`
- 编排器在每个 Agent 执行完毕后检查黑板，发现信号则抛出 `OrchestrationStopRequest` 异常
- 信号自动清除，防止重复触发

### 共享并行执行器

所有编排器共用 `execute_agents_in_parallel()` 函数，通过 `asyncio.gather` 并行执行 Agent 任务，每个 Agent 独立容错。

### Prompt 模板系统（PromptLoader）

所有编排器的提示词通过 Jinja2 模板管理，实现提示词与代码分离。模板按拓扑类型分组存放在 `broca/orchestration/prompts/` 目录下：

```
prompts/
├── graph/                  # 图编排通用模板（task_context, execute_step, fan_in_agent, human_node, agent_route）
├── supervisor_worker/      # Supervisor-Worker 模板（plan, check_and_plan, synthesize, worker_prompt）
├── round_table/            # Round-Table 模板（discussion, moderator_*）
```


### CrewOrchestratorRunner

`broca/session_runner/orchestrator_runner.py` — 在 Session Runner 子进程中管理编排生命周期：
- 创建 Blackboard 并注入 Agent 工具
- 注册 Agent 实例到 CrewContext
- 根据 `use_history` 配置每次执行前清空 Agent 上下文历史
- 设置进度回调，阶段完成时通过 IPC 推送实时进度
- 黑板事件订阅，推送实时进度更新
- 发送编排生命周期事件（start/complete/error/progress）

## Pipeline 流水线（有向图版）

Pipeline 基于有向图驱动，节点类型为 TASK（单 Agent 任务）和 HUMAN（人在环路）。图遍历逻辑继承自 `GraphOrchestrator`。

**YAML 示例**（完整代码审查流水线）：

```yaml
name: "代码审查流水线"
description: "演示 Pipeline 有向图编排能力"

orchestrator:
  type: pipeline
  extras:
    graph:
      entry: start
      nodes:
        # 入口
        start:
          edges:
            - target: static_analysis

        # Step 1: 静态代码审查
        static_analysis:
          agent: "代码审查员"
          task: "对代码进行全面的静态代码审查..."
          edges:
            - target: triage_reviews

        # Step 2: 路由 — 扇出到安全审查 + 性能审查
        triage_reviews:
          router:
            mode: static
          edges:
            - target: security_audit
              field: has_security_issues
              operator: eq
              value: true
            - target: performance_review
              field: has_performance_issues
              operator: eq
              value: true
            - target: aggregation
              # 无条件兜底

        # 安全审查（并行分支）
        security_audit:
          agent: "安全审计员"
          task: "对代码进行安全审查..."
          edges:
            - target: aggregation

        # 性能审查（并行分支）
        performance_review:
          agent: "性能工程师"
          task: "对代码进行性能审查..."
          edges:
            - target: aggregation

        # Step 3: 汇聚 — Agent 汇聚策略
        aggregation:
          agent: "质量管理员"
          task: "综合所有审查结果..."
          extras:
            aggregation_strategy: agent
          edges:
            - target: quality_gate

        # Step 4: 质量检查 + 条件路由（循环控制）
        quality_gate:
          agent: "审批员"
          task: "判断代码质量是否达标..."
          max_loop: 3
          router:
            mode: static
          edges:
            - target: final_approval
              field: gate_passed
              operator: eq
              value: true
            - target: fix_issues

        # Step 5: 修复问题（循环回到 static_analysis）
        fix_issues:
          agent: "程序员"
          task: "根据审查反馈修复代码问题..."
          max_loop: 3
          edges:
            - target: static_analysis

        # Step 6: 最终批准
        final_approval:
          agent: "审批员"
          task: "输出最终批准报告..."
```

**汇聚策略（Aggregation）**：

| 策略 | 说明 |
|------|------|
| `concat` | 将所有结果拼接为一个字符串 |
| `merge` | 合并为一个 dict |
| `agent` | 由指定的 Aggregator Agent 调用 LLM 汇聚 |

**执行流程**：
```
static_analysis → triage_reviews (static路由)
  ├──→ security_audit ──┐
  ├──→ performance_review ─┤
  └──→ (无条件兜底) ──────┘
                          ↓
                     aggregation (agent汇聚)
                          ↓
                     quality_gate (条件路由)
                       ├── gate_passed=true → final_approval
                       └── gate_passed=false → fix_issues → static_analysis (循环)
```

## Supervisor-Worker 主管-工人

Supervisor Agent 通过 `task_management` 工具创建子任务，Worker 自主从黑板拉取任务详情并执行，Supervisor 做质量检查（LLM 评估）和最终结果合成。

```yaml
orchestrator:
  type: supervisor-worker
  max_rounds: 3

agents:
  - role: supervisor
    name: "研究主管"
    config: supervisor.md
  - role: worker
    name: "文献研究员"
    config: researcher.md
  - role: worker
    name: "数据分析师"
    config: analyst.md
  - role: worker
    name: "报告撰写人"
    config: writer.md
```

额外选项（orchestrator.extras）：
- `do_synthesis: true/false` — 是否在达标后由 Supervisor LLM 合成最终报告（默认 false）

执行流程：
```
1. Supervisor Agent 通过 task_management.create 创建子任务
2. Supervisor 将 {worker_name: task_id} 映射写入黑板 key 'task_assignments'
3. Worker 自主从黑板读取 task_id，用 task_management.get 获取详情后执行
4. Supervisor LLM 一次性完成：质量检查 + 计划更新（合并步骤）
   - 达标 → [可选] Supervisor LLM 合成最终报告
   - 不达标 → 读取新任务分配，继续下一轮迭代
```

**关键特性**：
- 质量检查与计划更新合并为一次 LLM 调用（`supervisor_check_and_plan.j2`），减少交互轮次
- 支持 `do_synthesis` 开关控制是否合成最终报告

## Round-Table 圆桌讨论

多个参与者围绕议题进行多轮发言，支持三种发言顺序和可选的主持人开场/结束语。参与者通过共享讨论历史互相引用/反驳，Moderator 控制讨论节奏。

**完整示例**（标准辩论赛，来自 `examples/round-table_ai-debate/`）：

```yaml
name: "标准辩论赛"
description: "AI Agent 标准辩论赛：正反双方分阶段辩论，评委打分"

orchestrator:
  type: round-table
  max_rounds: 4
  extras:
    moderator_opening: true       # 主持人开场语
    moderator_closing: true       # 主持人结束语
    speaker_order: moderator      # Moderator 动态决定每轮发言顺序

agents:
  - role: moderator
    name: "主持人"
    config: moderator.md

  - role: participant
    name: "正方一辩"
    config: pro1.md
    extras:
      stance: pro                # 立场标记，注入讨论提示词

  - role: participant
    name: "正方二辩"
    config: pro2.md
    extras:
      stance: pro

  - role: participant
    name: "反方一辩"
    config: con1.md
    extras:
      stance: con

  - role: participant
    name: "反方二辩"
    config: con2.md
    extras:
      stance: con

  - role: participant
    name: "评委"
    config: judge.md

blackboard:
  initial_entries:
    - key: topic                  # 讨论议题（必填）
      value: "人工智能对人类社会究竟是利大于弊还是弊大于利？"
    - key: debate_rules           # 讨论规则（可选）
      value: |
        辩论规则：
        1. 立论阶段：每方各发言一轮，阐述核心论点（控制在200字以内）
        2. 攻辩阶段：双方交替发言，可互相反驳（每人发言控制在200字以内）
        3. 总结陈词：每方总结核心观点（控制在200字以内）
        4. 保持理性和建设性的辩论态度
```

**执行流程**：

```
主持人开场语（moderator_opening）
  → 第1轮讨论（Moderator 决定发言顺序）
    → 第2轮讨论
      → ...
        → 主持人结束语（moderator_closing）
```

**发言顺序模式**：

| 模式 | 说明 |
|------|------|
| `fixed` | 按 agents 配置顺序发言（默认） |
| `random` | 每轮随机打乱参与者顺序 |
| `moderator` | Moderator Agent 根据讨论进展动态决定每轮顺序（通过 `moderator_order.j2` 模板） |

**高级特性：每轮自定义配置（rounds）**

通过 `extras.rounds` 可为每一轮单独配置发言人和顺序，实现复杂的多阶段辩论流程（如立论→攻辩→自由辩论→总结）：

```yaml
orchestrator:
  type: round-table
  max_rounds: 4
  extras:
    moderator_opening: true
    moderator_closing: true
    speaker_order: moderator
    rounds:                      # 每轮自定义配置
      - name: "立论"             # 第一轮：正方立论
        speakers: ["正方一辩", "正方二辩", "正方三辩"]
        order: fixed
      - name: "攻辩"             # 第二轮：双方交替攻辩
        speakers: ["正方二辩", "反方二辩", "正方三辩", "反方三辩"]
        order: fixed
      - name: "自由辩论"         # 第三轮：自由辩论
        order: moderator
        order_rule: "交替发言，每人限时"
      - name: "总结"             # 第四轮：总结陈词
        speakers: ["正方四辩", "反方四辩"]
        order: fixed
```

**每轮配置字段**：

| 字段 | 说明 |
|------|------|
| `name` | 轮次名称（如"立论"、"攻辩"），作为 phase 名称 |
| `speakers` | 指定本轮发言的参与者列表（按名称） |
| `roles` | 按角色筛选发言人 |
| `order` | 本轮发言顺序（覆盖全局 `speaker_order` 设置） |
| `order_rule` | 发言顺序规则说明（moderator 模式时传递给 Moderator Agent） |

## Composite 组合嵌套（有向图版）

Composite 基于有向图驱动，支持三种节点类型：TASK（单 Agent 任务）、HUMAN（人在环路）、CREW（子编排）。图遍历逻辑继承自 `GraphOrchestrator`。

**YAML 示例**（产品发布决策流程）：

```yaml
name: "产品发布决策"
description: "AI Agent 组合编排：产品发布前的全面评估与决策"

orchestrator:
  type: composite
  extras:
    graph:
      entry: start
      nodes:
        start:
          edges:
            - target: kickoff

        # Step 1: TASK 节点 — 发布协调员启动调研
        kickoff:
          agent: "发布协调员"
          task: "启动产品发布评估流程..."
          edges:
            - target: market_research

        # Step 2: CREW 节点 — 市场调研分析（子编排）
        market_research:
          type: crew
          crew_ref: "市场调研分析"
          context:
            plan: "{{ blackboard.assessment_plan }}"
          edges:
            - target: decision_review

        # Step 3: CREW 节点 — 发布决策评审（子编排）
        decision_review:
          type: crew
          crew_ref: "发布决策评审"
          context:
            research_results: "{{ blackboard.market_research }}"
          edges:
            - target: final_report

        # Step 4: TASK 节点 — 发布协调员撰写最终报告
        final_report:
          agent: "发布协调员"
          task: "综合所有调研和评审结果，撰写最终报告..."

sub_crews:
  # 子 Crew 1: 市场调研分析（Pipeline）
  - name: "市场调研分析"
    orchestrator:
      type: pipeline
      extras:
        graph:
          entry: start
          nodes:
            start:
              edges:
                - target: market
            market:
              agent: "市场研究员"
              task: "分析产品市场前景..."
              edges:
                - target: user
            user:
              agent: "用户研究员"
              task: "进行用户研究分析..."
              edges:
                - target: tech
            tech:
              agent: "技术评估员"
              task: "进行技术评估..."
    agents:
      - role: worker
        name: "市场研究员"
        config: market_researcher.md
      - role: worker
        name: "用户研究员"
        config: user_researcher.md
      - role: worker
        name: "技术评估员"
        config: tech_assessor.md

  # 子 Crew 2: 发布决策评审（Pipeline）
  - name: "发布决策评审"
    orchestrator:
      type: pipeline
      extras:
        graph:
          entry: start
          nodes:
            start:
              edges:
                - target: business_review
            business_review:
              agent: "业务负责人"
              task: "从业务角度评审..."
              edges:
                - target: quality_review
            quality_review:
              agent: "质量经理"
              task: "从质量角度评审..."
              edges:
                - target: risk_review
            risk_review:
              agent: "风险管理员"
              task: "从风险角度评审..."
    agents:
      - role: worker
        name: "业务负责人"
        config: business_director.md
      - role: worker
        name: "质量经理"
        config: quality_manager.md
      - role: worker
        name: "风险管理员"
        config: risk_manager.md
```

**子 Crew 配置字段**：

| 字段 | 说明 |
|------|------|
| `name` | 子 Crew 名称，用于 `crew_ref` 引用 |
| `orchestrator` | 子 Crew 编排器配置（支持 pipeline/round-table/supervisor-worker） |
| `agents` | 子 Crew 的 Agent 角色配置 |
| `graph` | 子 Crew 的有向图定义（Pipeline 类型使用） |

**执行流程**：
```
kickoff (TASK: 发布协调员)
  → market_research (CREW: 市场调研分析 Pipeline)
    → market → user → tech
  → decision_review (CREW: 发布决策评审 Pipeline)
    → business_review → quality_review → risk_review
  → final_report (TASK: 发布协调员)
```

## 图校验与循环控制

**图校验（Graph.compile()）**：自动执行以下校验：
1. 入口节点存在性
2. 所有 edge.target 指向存在的节点
3. 所有节点从入口可达（无孤立节点）
4. Fan-out 汇聚约束（并行分支必须汇聚到同一节点）
5. Human 节点完整性（必须有 question 和 response_field）
6. Router 完整性（agent 模式必须有 evaluator）
7. 循环检测与 max_loop 继承

**循环控制**：
- `max_loop`：节点最大执行次数，防止无限循环
- 循环检测：Tarjan 算法自动识别强连通分量（SCC）
- max_loop 继承：循环中未显式设置 max_loop 的节点自动继承同环中其他节点的值

## 完整 Demo 示例

项目提供 4 个完整的编排 Demo：

| Demo | 拓扑 | 说明 |
|------|------|------|
| `examples/pipeline_code-review/` | Pipeline | 代码审查流水线：审查→扇出→汇聚→质量门禁→修复循环→批准 |
| `examples/supervisor-worker_research-report/` | Supervisor-Worker | 研究报告生成：主管分解→工人执行→检查迭代 |
| `examples/round-table_ai-debate/` | Round-Table | AI 辩论赛：多角色辩论，每轮自定义配置 |
| `examples/composite_product-launch/` | Composite | 产品发布决策：TASK + CREW 节点组合 |

