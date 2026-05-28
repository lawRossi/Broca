"""
编排模板

预置的编排模板，可直接用于常见场景。
"""

from broca.orchestration.crew import (
    AgentRole,
    AgentRoleConfig,
    CrewConfig,
    OrchestratorConfig,
    OrchestratorType,
    SubCrewConfig,
    TaskDefinition,
)


def create_debate_template(
    topic: str = "",
    moderator_config: str = "moderator_agent.md",
    pro_config: str = "debater_agent.md",
    con_config: str = "debater_agent.md",
    analyst_config: str = "analyst_agent.md",
    max_rounds: int = 5,
) -> CrewConfig:
    """
    创建圆桌辩论模板

    适用于方案辩论、多角度分析等场景。
    1 个 Moderator + 2-3 个参与者进行多轮讨论。

    Args:
        topic: 辩论主题
        moderator_config: Moderator Agent 配置路径
        pro_config: 正方 Agent 配置路径
        con_config: 反方 Agent 配置路径
        analyst_config: 中立评估员 Agent 配置路径（可选）
        max_rounds: 最大讨论轮数

    Returns:
        CrewConfig 配置
    """
    agents = [
        AgentRoleConfig(
            role=AgentRole.MODERATOR,
            name="主持人",
            config=moderator_config,
        ),
        AgentRoleConfig(
            role=AgentRole.PARTICIPANT,
            name="支持方",
            config=pro_config,
            extras={"stance": "pro"},
        ),
        AgentRoleConfig(
            role=AgentRole.PARTICIPANT,
            name="反对方",
            config=con_config,
            extras={"stance": "con"},
        ),
    ]

    if analyst_config:
        agents.append(
            AgentRoleConfig(
                role=AgentRole.PARTICIPANT,
                name="中立评估员",
                config=analyst_config,
                extras={"stance": "neutral"},
            )
        )

    return CrewConfig(
        name="圆桌辩论",
        description=f"多 Agent 圆桌讨论: {topic}",
        orchestrator=OrchestratorConfig(
            type=OrchestratorType.ROUND_TABLE,
            max_rounds=max_rounds,
        ),
        agents=agents,
        blackboard={
            "initial_entries": [{"key": "topic", "value": topic or "待讨论的主题"}]
        },
    )


def create_deep_research_template(
    objective: str = "",
    coordinator_config: str = "coordinator_agent.md",
    researcher_config: str = "researcher_agent.md",
    analyst_config: str = "analyst_agent.md",
    writer_config: str = "writer_agent.md",
    reviewer_config: str = "reviewer_agent.md",
    max_rounds: int = 3,
) -> CrewConfig:
    """
    创建深度研究模板

    适用于技术调研、市场分析等研究场景。
    Supervisor-Worker 为主流程 + Pipeline 子流程。

    Args:
        objective: 研究目标
        coordinator_config: 协调员配置
        researcher_config: 研究员配置
        analyst_config: 分析师配置
        writer_config: 撰写人配置
        reviewer_config: 审查员配置
        max_rounds: 最大迭代轮数

    Returns:
        CrewConfig 配置
    """
    return CrewConfig(
        name="深度研究",
        description=f"AI Agent 深度研究: {objective}",
        orchestrator=OrchestratorConfig(
            type=OrchestratorType.SUPERVISOR_WORKER,
            max_rounds=max_rounds,
        ),
        agents=[
            AgentRoleConfig(
                role=AgentRole.SUPERVISOR,
                name="研究主管",
                config=coordinator_config,
            ),
            AgentRoleConfig(
                role=AgentRole.WORKER,
                name="文献研究员",
                config=researcher_config,
            ),
            AgentRoleConfig(
                role=AgentRole.WORKER,
                name="数据分析师",
                config=analyst_config,
            ),
            AgentRoleConfig(
                role=AgentRole.WORKER,
                name="报告撰写人",
                config=writer_config,
            ),
            AgentRoleConfig(
                role=AgentRole.WORKER,
                name="质量审查员",
                config=reviewer_config,
            ),
        ],
        blackboard={
            "initial_entries": [
                {"key": "objective", "value": objective or "待研究的目标"}
            ]
        },
        sub_crews=[
            SubCrewConfig(
                name="报告撰写与审查",
                orchestrator=OrchestratorConfig(
                    type=OrchestratorType.PIPELINE,
                ),
                steps=[
                    TaskDefinition(
                        agent="报告撰写人",
                        task="根据黑板上所有调研结果，撰写结构化的研究报告",
                    ),
                    TaskDefinition(
                        agent="质量审查员",
                        task="审查报告的质量、准确性和完整性，给出修改建议",
                    ),
                ],
            )
        ],
    )


def create_code_review_template(
    code_content: str = "",
    senior_config: str = "senior_dev_agent.md",
    security_config: str = "security_agent.md",
    junior_config: str = "junior_dev_agent.md",
    threshold: float = 0.7,
) -> CrewConfig:
    """
    创建代码审查模板

    适用于代码审查、质量评估等场景。
    使用 Consensus 拓扑，多个 Reviewer 独立评估后汇聚结果。

    Args:
        code_content: 待审查的代码内容
        senior_config: 高级开发者配置
        security_config: 安全工程师配置
        junior_config: 初级开发者配置
        threshold: 通过阈值

    Returns:
        CrewConfig 配置
    """
    agents = [
        AgentRoleConfig(
            role=AgentRole.REVIEWER,
            name="高级架构师",
            config=senior_config,
        ),
        AgentRoleConfig(
            role=AgentRole.REVIEWER,
            name="安全工程师",
            config=security_config,
        ),
    ]

    if junior_config:
        agents.append(
            AgentRoleConfig(
                role=AgentRole.REVIEWER,
                name="初级开发",
                config=junior_config,
            )
        )

    return CrewConfig(
        name="代码审查",
        description="多维度代码审查与质量评估",
        orchestrator=OrchestratorConfig(
            type=OrchestratorType.CONSENSUS,
            strategy="weighted",
            threshold=threshold,
            weights={
                "高级架构师": 1.5,
                "安全工程师": 1.2,
                "初级开发": 0.8,
            },
        ),
        agents=agents,
        blackboard={
            "initial_entries": [
                {"key": "review_target", "value": code_content or "待审查的代码"}
            ]
        },
    )


def create_multi_source_research_template(
    query: str = "",
    dispatcher_config: str = "dispatcher_agent.md",
    researcher_configs: list = None,
    aggregator_config: str = "aggregator_agent.md",
) -> CrewConfig:
    """
    创建多源信息搜集模板

    适用于竞品分析、多维度信息搜集等场景。
    使用 Broadcast 拓扑，并行执行后聚合。

    Args:
        query: 搜索/研究查询
        dispatcher_config: 分发器配置
        researcher_configs: 研究 Agent 配置列表 [(name, config)]
        aggregator_config: 聚合器配置

    Returns:
        CrewConfig 配置
    """
    if researcher_configs is None:
        researcher_configs = [
            ("市场研究员", "researcher_agent.md"),
            ("技术分析师", "analyst_agent.md"),
            ("用户体验专家", "ux_agent.md"),
        ]

    agents = [
        AgentRoleConfig(
            role=AgentRole.DISPATCHER,
            name="任务分发器",
            config=dispatcher_config,
        ),
    ]

    for name, cfg in researcher_configs:
        agents.append(
            AgentRoleConfig(
                role=AgentRole.WORKER,
                name=name,
                config=cfg,
            )
        )

    agents.append(
        AgentRoleConfig(
            role=AgentRole.AGGREGATOR,
            name="结果汇总器",
            config=aggregator_config,
        )
    )

    return CrewConfig(
        name="多源信息搜集",
        description=f"多维度信息搜集与分析: {query}",
        orchestrator=OrchestratorConfig(
            type=OrchestratorType.BROADCAST,
        ),
        agents=agents,
        blackboard={
            "initial_entries": [{"key": "task", "value": query or "待研究的问题"}]
        },
    )


# 模板注册表
TEMPLATE_REGISTRY = {
    "debate": {
        "name": "圆桌辩论",
        "description": "多 Agent 圆桌讨论，适合方案辩论、头脑风暴",
        "create_func": create_debate_template,
        "required_params": ["topic"],
    },
    "deep-research": {
        "name": "深度研究",
        "description": "Supervisor-Worker + Pipeline 组合，适合技术调研、市场分析",
        "create_func": create_deep_research_template,
        "required_params": ["objective"],
    },
    "code-review": {
        "name": "代码审查",
        "description": "多 Reviewer 独立评估 + 加权聚合，适合代码质量审查",
        "create_func": create_code_review_template,
        "required_params": ["code_content"],
    },
    "multi-source-research": {
        "name": "多源信息搜集",
        "description": "Broadcast 并行分发 + 聚合，适合竞品分析、多维度调研",
        "create_func": create_multi_source_research_template,
        "required_params": ["query"],
    },
}


def list_templates() -> list:
    """列出所有可用的编排模板"""
    return [
        {
            "id": tid,
            "name": t["name"],
            "description": t["description"],
            "required_params": t["required_params"],
        }
        for tid, t in TEMPLATE_REGISTRY.items()
    ]


def create_from_template(template_id: str, **kwargs) -> CrewConfig:
    """
    从模板创建 CrewConfig

    Args:
        template_id: 模板 ID（见 TEMPLATE_REGISTRY）
        **kwargs: 模板参数

    Returns:
        CrewConfig

    Raises:
        ValueError: 模板不存在或缺少必填参数
    """
    if template_id not in TEMPLATE_REGISTRY:
        raise ValueError(
            f"Unknown template '{template_id}'. "
            f"Available: {list(TEMPLATE_REGISTRY.keys())}"
        )

    template = TEMPLATE_REGISTRY[template_id]
    required = template["required_params"]

    missing = [p for p in required if p not in kwargs or not kwargs[p]]
    if missing:
        raise ValueError(
            f"Missing required parameters for template '{template_id}': {missing}"
        )

    return template["create_func"](**kwargs)
