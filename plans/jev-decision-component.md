# JEV 决策组件集成方案

## 1. 背景与动机

### 1.1 JEV 类模型概述

JEV (Judge Evaluation/Verification) 是一类 **System 1 决策模型**，专为高频、窄范围的结构化决策设计：

- **输入**: `state`（上下文）+ `questions`（类型化问题）
- **输出**: 类型化答案 + 校准概率分布（不生成文本）
- **三种原语**:
  - **Choice**: 候选单选（如：选择工具、路由队列）
  - **Noul**: 是非判断（如：是否需要人工审批）
  - **Score**: 序数评分（如：风险等级 1-5）
- **推理模式**: Prefill-only，单次前向传播，不做自回归生成
- **性能**: 29-325x 比 LLM 更便宜，30-220x 更快

### 1.2 开源模型选型对比

| 模型 | 参数量 | 底座 | 许可证 | 本地延迟 | 多语言 | 可训练 | 适用场景 |
|------|--------|------|--------|----------|--------|--------|----------|
| **Kev-0.8B** | 0.8B | Qwen3 | Apache-2.0 | ~22ms | 中/英 | ✅ (LoRA) | 轻量决策，消费级硬件 |
| **Kev-4B** | 4B | Qwen3.5 | Apache-2.0 | ~300ms (Mac) / ~40ms (H100) | 中/英 | ✅ | 均衡精度与速度 |
| **Laya (multilingual)** | 322M | mmBERT-base | Apache-2.0 | ~9ms | 100+ 语言 | ✅ (SFT/LoRA) | 多语言，极轻量 |
| **NeoHorse-Jev-4B** | 4B | Qwen3.5-4B | Apache-2.0 | - | 中/英 | ✅ | 具身智能，图文决策 |
| **Jeff** | 0.8B | - | - | ~22ms | - | ✅ (LoRA 15种任务) | 边缘 AI |

**推荐选型**:
- **首选**: **Kev-4B**（Qwen3.5 底座，与 Broca 的 LLM 生态兼容性最佳，完整训练/部署/评测工具链）
- **轻量替代**: **Laya multilingual**（322M，适合资源受限场景，多语言支持优秀）
- **边缘部署**: **Kev-0.8B** 或 **Jeff**（笔记本/边缘设备）

**推荐理由（Kev）**:
1. 完全兼容 TypeSafe System One API（`/v1/systemone`），TypeSafe SDK 改 `base_url` 即可用
2. 开源训练管线完整（`kev.train` / `kev.serve` / `kev.benchmark`），可基于 Broca 使用场景微调
3. Qwen3 底座与 Broca 已有的 LLM 配置（litellm）技术栈兼容
4. Apache-2.0，商业友好
5. KV cache 支持，state 复用后重复问题极快

---

## 2. 当前项目决策流程分析

### 2.1 现有架构决策点

Broca 的 Agent 执行循环中，以下环节存在高频窄决策需求：

```
Agent.run(message)
  └── LoopEngine.execute()
        ├── _setup_turn()              ← 消息解析
        │   └── [决策点 A]: 消息类型分类 (user/task/command)
        ├── on_turn_start
        │
        ├── ┌─── LLM Loop ───────────────────────────────────────────┐
        │   │                                                         │
        │   │   LLMStrategy.call()                                    │
        │   │   ├── [决策点 B]: 上下文是否需压缩 (当前: token 阈值)  │
        │   │   ├── [决策点 C]: 工具选择 (LLM 决定调哪些工具)       │
        │   │   └── [决策点 D]: LLM 调用重试/降级                   │
        │   │                                                         │
        │   │   ToolExecutionStrategy.execute()                       │
        │   │   ├── [决策点 E]: 权限检查 (当前: 配置+用户确认)      │
        │   │   ├── [决策点 F]: 工具执行顺序 (串行/并行)            │
        │   │   └── [决策点 G]: 执行结果验证/错误处理              │
        │   │                                                         │
        │   │   Hooks:                                                │
        │   │   ├── [决策点 H]: 死循环检测 (当前: 滑动窗口)         │
        │   │   └── [决策点 I]: 是否继续循环 (step limit)           │
        │   └─────────────────────────────────────────────────────────┘
        │
        └── _finalize_turn()
            ├── [决策点 J]: 编排路由 (Graph Orchestrator 下一节点)
            └── [决策点 K]: 子Agent 任务分配
```

### 2.2 痛点识别

| 痛点 | 现状 | JEV 可优化 |
|------|------|------------|
| **工具选择依赖 LLM** | 每次 LLM 调用都传全量工具定义，token 浪费大 | JEV 预筛选相关工具子集 |
| **权限判断机械化** | 基于工具名的静态配置（allow/ask/forbidden） | JEV 动态评估操作风险，低危自动放行 |
| **上下文压缩阈值固定** | 按 token 数机械触发 | JEV 判断上下文"有效信息密度"，更精准触发 |
| **死循环检测简单** | 滑动窗口检测重复工具调用模式 | JEV 评估"当前进展是否有效"，提前发现 |
| **编排路由依赖 LLM** | Graph Orchestrator 的节点跳转需 LLM 决策 | JEV 轻量路由，减少 LLM 开销 |
| **无置信度分级** | 所有决策路径相同 | JEV 概率输出 → 置信度路由（高置信自动/低置信升级） |

---

## 3. 集成方案设计

### 3.1 组件架构

新增 **`DecisionComponent`** 作为核心决策接口，通过 `ComponentRegistry` 插件体系集成：

```
┌─────────────────────────────────────────────────────────────┐
│                     ComponentRegistry                        │
│                                                             │
│  ┌─────────────────────┐     ┌──────────────────────────┐  │
│  │  DecisionProvider   │     │  DecisionProvider        │  │
│  │  (interface)        │     │  (KevDecisionProvider)   │  │
│  │                     │     │  (LayaDecisionProvider)  │  │
│  │  predict(state,     │     │  (NullDecisionProvider)  │  │
│  │   questions)        │     └──────────────────────────┘  │
│  └─────────────────────┘                                    │
│           ↑                                                  │
│           │ 注入                                             │
│           ↓                                                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              DecisionStrategy (新)                    │   │
│  │  - ToolRoutingStrategy: 预筛选工具集                  │   │
│  │  - RiskAssessmentStrategy: 权限风险动态评估           │   │
│  │  - LoopControlStrategy: 循环控制/死循环检测           │   │
│  │  - OrchestrationRoutingStrategy: 图编排路由           │   │
│  │  - ContextCompressionStrategy: 智能压缩决策           │   │
│  └──────────────────────────────────────────────────────┘   │
│           ↑                                                  │
│           │ 被调用                                           │
│           ↓                                                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │           现有组件 (修改点最小化)                      │   │
│  │  - LoopEngine (hooks 增加 DecisionHook)               │   │
│  │  - ToolExecutor (权限预判)                           │   │
│  │  - CompressionHook (智能触发)                         │   │
│  │  - GraphOrchestrator (路由决策)                       │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 核心接口设计

```python
# broca/components/decision_provider.py

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from broca.components.base import BaseComponent


class QuestionType(Enum):
    CHOICE = "choice"   # 候选单选
    NOUL = "noul"       # 是非判断 (True/False)
    SCORE = "score"     # 序数评分


@dataclass
class DecisionQuestion:
    """一个类型化决策问题。"""
    name: str                       # 标识符
    type: QuestionType              # choice / noul / score
    instructions: str               # 问题描述 (prompt)
    criteria: dict[str, str] | list[str] | None = None  # Choice: {label: desc}; Score: [levels]


@dataclass
class DecisionResult:
    """单个问题的决策结果。"""
    question_name: str
    type: QuestionType
    answer: Any                     # Choice: str | Noul: bool | Score: float
    probabilities: dict[str, float]  # 完整概率分布
    confidence: float                # 最大概率 (置信度)
    # 可选：是否触发升级
    escalate: bool = False          # True = 置信度不足，需要 LLM/人工介入


@dataclass
class DecisionRequest:
    """一次决策请求 (可包含多个问题)。"""
    state: str                      # 上下文 (截断后的)
    questions: list[DecisionQuestion]


class DecisionProvider(BaseComponent, ABC):
    """决策模型提供者接口。
    
    实现类:
    - KevDecisionProvider: 本地 Kev 模型
    - LayaDecisionProvider: 本地 Laya 模型  
    - NullDecisionProvider: 禁用 (回退到纯 LLM 路径)
    - RemoteDecisionProvider: 远端 API (TypeSafe Jev 或自建)
    """

    name: str = "decision_provider"

    @abstractmethod
    async def decide(self, request: DecisionRequest) -> list[DecisionResult]:
        """执行决策。一次调用可包含多个问题。
        
        Args:
            request: 包含 state 和一组 typed questions
            
        Returns:
            按 questions 顺序排列的决策结果列表
        """
        ...

    @abstractmethod
    async def initialize(
        self,
        *,
        model_name: str | None = None,
        base_url: str | None = None,     # 远端 API 地址
        model_dir: str | None = None,    # 本地模型路径
        device: str = "auto",            # "auto" | "cuda" | "cpu" | "mps"
        threshold: float = 0.7,          # 置信度阈值，低于此值 escalate=True
        config: Any = None,
    ) -> None:
        """注入依赖并加载模型。"""
        ...

    async def health_check(self) -> bool:
        """检查决策模型是否可用。"""
        return True
```

### 3.3 具体策略实现

#### 3.3.1 ToolRoutingStrategy — 工具预筛选

**问题**: 每次 LLM 调用传全量工具定义，token 消耗大，且 LLM 可能选择不相关的工具。

**方案**: 在 LLM 调用前，用 JEV 根据用户意图 + 当前上下文，预筛选相关工具子集。

```python
# broca/loop_engine/strategies/tool_routing.py

class ToolRoutingStrategy:
    """LLM 调用前的工具集预筛选。
    
    使用 DecisionProvider 的 Choice 原语:
    - state = 用户消息 + 最近上下文摘要
    - questions = 每个工具一个 Choice 问题: "这个工具与当前任务相关吗?"
    - 或者: 一个 Choice 问题 "最相关的工具是哪个?" (候选 = 所有工具名)
    """

    def __init__(self, decision_provider: DecisionProvider, min_tools: int = 3):
        self._decision = decision_provider
        self._min_tools = min_tools  # 至少保留 N 个工具 (防止过度裁剪)

    async def filter_tools(
        self,
        all_tools: dict[str, Any],
        user_message: str,
        context_summary: str = "",
    ) -> dict[str, Any]:
        """返回与当前任务相关的工具子集。"""
        # 构建决策问题
        question = DecisionQuestion(
            name="relevant_tools",
            type=QuestionType.CHOICE,
            instructions="Which tools are most relevant to the user's current request?",
            criteria={name: tool.description for name, tool in all_tools.items()},
        )
        state = f"User request: {user_message}\nContext: {context_summary}"
        request = DecisionRequest(state=state, questions=[question])
        
        results = await self._decision.decide(request)
        if not results or not results[0].probabilities:
            return all_tools  # 回退：模型不可用时传全量
        
        # 按概率排序，取 top-k 但保证 min_tools
        ranked = sorted(
            results[0].probabilities.items(),
            key=lambda x: x[1], reverse=True,
        )
        selected = {name: all_tools[name] for name, _ in ranked[:self._min_tools] 
                    if name in all_tools}
        return selected or all_tools
```

#### 3.3.2 RiskAssessmentStrategy — 权限风险预判

**问题**: 当前权限系统是静态的（基于工具名），无法感知操作的实际风险。

**方案**: 在执行高风险工具前，用 JEV 评估操作的实际风险等级，低危自动放行，高危才询问用户。

```python
# broca/components/risk_assessment.py

class RiskAssessmentStrategy:
    """动态权限风险评估。
    
    集成点: ToolExecutor 在执行前调用
    原流程: permission_config(tool_name) → ask/allow/forbidden
    新流程: permission_config → JEV risk assessment → 动态决定
    """

    def __init__(self, decision_provider: DecisionProvider, auto_approve_threshold: float = 0.85):
        self._decision = decision_provider
        self._threshold = auto_approve_threshold

    async def assess_risk(
        self,
        tool_name: str,
        arguments: dict,
        context: str,
    ) -> tuple[str, float]:
        """评估操作风险。
        
        Returns:
            (action, confidence): action ∈ {"auto_approve", "ask_user", "deny"}
        """
        question = DecisionQuestion(
            name="risk_level",
            type=QuestionType.SCORE,
            instructions="How risky is this operation? 1=safe read, 5=destructive/irreversible",
            criteria=["safe", "low", "moderate", "high", "critical"],
        )
        state = (
            f"Tool: {tool_name}\n"
            f"Arguments: {json.dumps(arguments, ensure_ascii=False)[:500]}\n"
            f"Context: {context[:500]}"
        )
        
        results = await self._decision.decide(
            DecisionRequest(state=state, questions=[question])
        )
        
        if not results:
            return ("ask_user", 0.0)  # 回退到原逻辑
        
        risk_score = results[0].answer  # float 1-5
        confidence = results[0].confidence
        
        if risk_score <= 1.5 and confidence >= self._threshold:
            return ("auto_approve", confidence)
        elif risk_score >= 4.0:
            return ("deny", confidence)  # 或直接 ask_user
        else:
            return ("ask_user", confidence)
```

#### 3.3.3 LoopControlStrategy — 智能循环控制

**问题**: 当前死循环检测基于简单的重复模式匹配，可能误杀有效操作或放过真正的死循环。

**方案**: 增加 JEV 辅助判断"当前进展是否有效"。

```python
# broca/loop_engine/hooks/decision_loop_hook.py

class DecisionLoopHook(LoopHook):
    """JEV 辅助的循环控制 Hook。
    
    在 on_step_end 时，除了 DeadLoopHook 的模式检测，
    额外用 JEV 评估 "agent 是否在有效推进任务"。
    """
    name = "decision_loop"

    def __init__(self, decision_provider: DecisionProvider, 
                 steps_before_check: int = 3):
        self._decision = decision_provider
        self._steps_since_check = 0
        self._interval = steps_before_check

    async def on_step_end(self, ctx: StepContext) -> None:
        self._steps_since_check += 1
        if self._steps_since_check < self._interval:
            return
        
        self._steps_since_check = 0
        # 只在步数较多时触发（避免浪费）
        if ctx.step_count < 3:
            return

        question = DecisionQuestion(
            name="progress",
            type=QuestionType.NOUL,
            instructions="Is the agent making meaningful progress toward the goal? "
                        "Answer False only if the agent is clearly stuck in a loop.",
        )
        state = f"""Goal: {ctx.turn_context.raw_input[:200]}
Recent actions: {self._format_recent_actions(ctx)}"""

        results = await self._decision.decide(
            DecisionRequest(state=state, questions=[question])
        )
        if results and results[0].answer is False and results[0].confidence > 0.8:
            # 触发 abort
            ctx.abort_requested = True
            ctx.abort_reason = "Decision model detected ineffective loop"
```

#### 3.3.4 OrchestrationRoutingStrategy — 编排路由

**问题**: GraphOrchestrator 的节点跳转需要 LLM 决策，成本高且慢。

**方案**: 对于简单的路由判断（条件分支），使用 JEV 代替 LLM。

```python
# broca/orchestration/decision_router.py

class DecisionRouter:
    """Graph Orchestrator 中的 JEV 路由节点。
    
    替代原有 "LLM 决定下一节点" 的模式，
    当路由选项 ≤ 10 个且判断条件明确时，用 JEV 替代。
    """

    def __init__(self, decision_provider: DecisionProvider):
        self._decision = decision_provider

    async def route(
        self,
        current_state: str,
        available_nodes: dict[str, str],  # {node_name: description}
    ) -> str:
        """选择下一个编排节点。"""
        question = DecisionQuestion(
            name="next_node",
            type=QuestionType.CHOICE,
            instructions="Which node should be executed next based on the current state?",
            criteria=available_nodes,
        )
        results = await self._decision.decide(
            DecisionRequest(state=current_state, questions=[question])
        )
        if results and results[0].confidence > 0.7:
            return results[0].answer
        return None  # 回退到 LLM 路由
```

### 3.4 组件注册与配置

#### 注册到 ComponentRegistry

```python
# broca/components/defaults.py 新增

# 在 _DEFAULT_IMPLS 中新增
DecisionProvider: "broca.components.decision_provider:NullDecisionProvider"

# 在 COMPONENT_SCOPES 中新增  
DecisionProvider: "singleton"  # 模型加载重，全局共享

# 在 ENTRY_POINT_NAMES 中新增
"decision_provider": DecisionProvider,
```

#### 用户配置

```json
// ~/.broca/components.json
{
    "decision_provider": "broca.components.kev_provider:KevDecisionProvider"
}
```

```json
// configs/llm_config.json 新增
{
    "decision_model": {
        "provider": "kev",              // "kev" | "laya" | "remote" | "null"
        "model_name": "kev-4b",         // 模型标识
        "base_url": null,              // 远端 API (provider="remote" 时)
        "model_dir": null,             // 本地路径 (provider="kev"/"laya" 时)
        "device": "auto",              // "auto" | "cuda" | "mps" | "cpu"
        "confidence_threshold": 0.75,  // 低于此值 escalate 到 LLM
        "enabled_strategies": ["tool_routing", "risk_assessment", "loop_control"]
    }
}
```

### 3.5 集成流程图

```
用户消息
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ Agent.run()                                                  │
│   │                                                          │
│   ├─ [可选] DecisionProvider.decide()                         │
│   │  └─ 消息分类: user_question / task / command / chitchat   │
│   │     → 简单寒暄直接回复，不进入 LLM 循环                   │
│   │                                                          │
│   ▼                                                          │
│ LoopEngine.execute()                                          │
│   │                                                          │
│   ├─ _setup_turn()                                           │
│   │                                                          │
│   ├─ Loop iteration:                                         │
│   │   │                                                      │
│   │   ├─ [NEW] ToolRoutingStrategy.filter_tools()            │
│   │   │  └─ JEV: 根据意图筛选相关工具子集                      │
│   │   │                                                      │
│   │   ├─ LLMStrategy.call(filtered_tools)                    │
│   │   │  └─ 只传相关工具 → 减少 token + 提高准确率              │
│   │   │                                                      │
│   │   ├─ ToolExecutionStrategy.execute()                     │
│   │   │   ├─ [NEW] RiskAssessmentStrategy.assess_risk()     │
│   │   │   │  └─ JEV: 动态风险评估                             │
│   │   │   │     → auto_approve: 直接执行                      │
│   │   │   │     → ask_user: 弹窗询问                          │
│   │   │   │     → deny: 拒绝执行                              │
│   │   │   └─ 执行工具                                         │
│   │   │                                                      │
│   │   ├─ [NEW] DecisionLoopHook.on_step_end()               │
│   │   │  └─ JEV: 进展有效性检测                               │
│   │   │                                                      │
│   │   ├─ CompressionMemoryHook (增强)                         │
│   │   │  └─ [可选] JEV 判断"信息密度"辅助压缩决策              │
│   │   │                                                      │
│   │   └─ 继续/结束                                            │
│   │                                                          │
│   └─ _finalize_turn()                                        │
│      └─ [可选] DecisionRouter (编排场景)                      │
└──────────────────────────────────────────────────────────────┘
```

---

## 4. 实施计划

### Phase 1: 核心接口 + 基础设施 (Week 1-2)

- [ ] 新建 `broca/components/decision_provider.py` — 接口定义
- [ ] 新建 `broca/components/kev_provider.py` — Kev 实现（HTTP client + 本地推理）
- [ ] 新建 `broca/components/null_provider.py` — 空实现（默认禁用）
- [ ] 注册到 `ComponentRegistry` (`defaults.py`)
- [ ] 配置系统扩展 (`configs.py` 新增 `DecisionModelConfig`)
- [ ] 基础测试: `test_decision_provider.py` (mock + null + kev client)

### Phase 2: 策略实现 (Week 3-4)

- [ ] `ToolRoutingStrategy` + 集成到 `LLMStrategy` 调用前
- [ ] `RiskAssessmentStrategy` + 集成到 `ToolExecutor`
- [ ] `DecisionLoopHook` + 注册到 hook factory
- [ ] 策略配置开关 (per-agent 可独立启用/禁用)
- [ ] 每个策略的独立测试

### Phase 3: 高级集成 (Week 5-6)

- [ ] `DecisionRouter` 集成到 `GraphOrchestrator`
- [ ] 上下文压缩增强 (JEV 辅助判断)
- [ ] Laya provider 实现 (多语言场景)
- [ ] 远端 API provider (TypeSafe Jev / 自建 Kev 服务)
- [ ] 端到端集成测试

### Phase 4: 微调与优化 (Week 7-8)

- [ ] 基于 Broca 使用场景构建微调数据集
- [ ] 用 `kev.train` 微调 Kev-4B 适配工具路由/风险评估
- [ ] 性能基准测试 (延迟/准确率/成本对比)
- [ ] 文档 + 用户指南

---

## 5. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| JEV 模型精度不足 (Kev-8B 域外 79.6% vs Jev 85.7%) | 误判导致体验下降 | **置信度门控**: 低于阈值自动 escalate 到 LLM/人工，NEVER 做唯一决策源 |
| 本地推理延迟 (Kev-4B ~300ms on Mac) | 增加每步延迟 | 异步非阻塞 + 仅在关键路径使用 (如工具执行前)；边缘场景用 Kev-0.8B |
| 模型依赖增加部署复杂度 | 部署/维护成本 | 可选组件 (默认 NullProvider)，通过 `components.json` 启用；支持远端 API 模式 |
| 多语言场景 (中文 state) | 开源模型中文能力弱 | 用 Laya multilingual (100+ 语言)；或微调 Kev 中文工具路由场景 |
| 候选集变化 (工具动态加载) | Choice 候选需动态传入 | JEV 的 Choice 支持热换候选 (候选写在请求里，不需重训) |

### 关键设计原则

1. **永不阻塞**: JEV 调用失败或超时时，必须回退到纯 LLM/原有逻辑路径
2. **置信度门控**: 所有 JEV 决策都有 `confidence` 字段，低置信 → escalate
3. **可插拔**: 默认 `NullDecisionProvider` (完全禁用)，通过配置启用
4. **渐进式**: 策略可独立开关，用户可按需启用 (如只开 tool_routing 不开 loop_control)
5. **不替代 LLM**: JEV 只做窄决策 (选择/判断/评分)，所有生成任务仍走 LLM

---

## 6. 文件结构变更预览

```
broca/
├── components/
│   ├── decision_provider.py    # [NEW] DecisionProvider 接口 + QuestionType + DecisionRequest/Result
│   ├── kev_provider.py         # [NEW] KevDecisionProvider (HTTP client + 可选本地推理)
│   ├── laya_provider.py        # [NEW] LayaDecisionProvider
│   ├── null_provider.py        # [NEW] NullDecisionProvider (默认禁用)
│   ├── risk_assessment.py      # [NEW] RiskAssessmentStrategy
│   └── defaults.py             # [MOD] 注册 DecisionProvider
│
├── loop_engine/
│   ├── strategies/
│   │   └── tool_routing.py     # [NEW] ToolRoutingStrategy
│   └── hooks/
│       ├── decision_loop_hook.py # [NEW] DecisionLoopHook
│       └── factory.py          # [MOD] 支持注入 DecisionProvider
│
├── orchestration/
│   └── decision_router.py      # [NEW] DecisionRouter for GraphOrchestrator
│
├── configs.py                  # [MOD] DecisionModelConfig
│
└── tests/
    ├── test_decision_provider.py   # [NEW] 接口 + null + mock 测试
    ├── test_kev_provider.py        # [NEW] Kev HTTP client 测试
    ├── test_tool_routing.py        # [NEW] 工具路由策略测试
    ├── test_risk_assessment.py     # [NEW] 风险评估策略测试
    └── test_decision_loop_hook.py  # [NEW] 循环控制 hook 测试
```
