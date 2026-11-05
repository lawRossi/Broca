"""DecisionProvider component interface.

Abstracts decision model API calls across different providers (Kev, Laya,
TypeSafe Jev, or any System One compatible service).  The default
implementation is ``DecisionClient`` (in ``broca/decision.py``), which acts
as a thin HTTP client to a running decision model service.

The interface mirrors the LLM client pattern::

    DecisionProvider (ABC in components/)  ←  like LLMClient
    DecisionClient (impl in broca/)        ←  like LiteLLMClient

Usage::

    provider = registry.get(DecisionProvider)
    results = await provider.decide(
        state="用户请求: 帮我退款",
        questions=[
            DecisionQuestion(name="intent", type="noul",
                             instructions="Is this a refund request?"),
            DecisionQuestion(name="team", type="choice",
                             instructions="Which team handles this?",
                             criteria={"billing": "Refunds", "tech": "Bugs"}),
        ],
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from broca.components.base import BaseComponent


class QuestionType(str, Enum):
    """JEV 三种类型化决策问题原语。"""

    CHOICE = "choice"  # 候选单选
    NOUL = "noul"  # 是非判断 (True/False)
    SCORE = "score"  # 序数评分


@dataclass
class DecisionQuestion:
    """一个类型化决策问题。

    Attributes:
        name: 问题标识符（在结果中用于查找）。
        type: 问题类型 (choice / noul / score)。
        instructions: 问题描述 (prompt)，应清晰描述判断标准。
        criteria: 候选项。
            - Choice: ``{label: description}`` dict
            - Score: ``[level_1, level_2, ...]`` 有序 list
            - Noul: 不需要 (None)
    """

    name: str
    type: QuestionType
    instructions: str
    criteria: dict[str, str] | list[str] | None = None


@dataclass
class DecisionResult:
    """单个问题的决策结果。

    Attributes:
        question_name: 对应的 DecisionQuestion.name。
        type: 问题类型。
        answer: 决策答案。
            - Choice: 选中的 label (str)
            - Noul: True/False (bool)
            - Score: 浮点分数 (float)
        probabilities: 完整概率分布 ``{label: probability}``。
            对于 Noul: ``{"true": 0.9, "false": 0.1}``
            对于 Choice: ``{option: prob, ...}``
            对于 Score: ``{level: prob, ...}``
        confidence: 最大概率值（置信度），0.0-1.0。
        escalate: 置信度是否低于阈值（True 表示建议升级到 LLM/人工）。
    """

    question_name: str
    type: QuestionType
    answer: Any
    probabilities: dict[str, float]
    confidence: float
    escalate: bool = False


class DecisionProvider(BaseComponent, ABC):
    """决策模型提供者接口。

    实现类:
    - ``DecisionClient`` (``broca.decision``) — 默认实现，HTTP 客户端，
      连接 Kev / Laya / TypeSafe Jev 等 System One 兼容服务。
    - 自定义 provider 可通过 ``ComponentRegistry`` 插件机制注册。

    配置来源:
    - 独立的 ``decision_config.json``（格式同 ``llm_config.json``）
    - 通过 ``BrocaConfig.decision_config_file`` 指定路径
    """

    name: str = "decision_provider"  # non-abstract; subclasses may override

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    @abstractmethod
    async def decide(
        self,
        state: str,
        questions: list[DecisionQuestion],
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> list[DecisionResult]:
        """执行一次决策请求（可包含多个问题）。

        Args:
            state: 上下文/状态文本（截断后的）。
            questions: 类型化问题列表。
            provider: 可选，覆盖默认 provider。
            model: 可选，覆盖默认 model。

        Returns:
            按 ``questions`` 顺序排列的决策结果列表。
            调用失败时返回空列表（由调用方决定回退策略）。

        Raises:
            DecisionError: 当请求格式错误或服务不可达时。
        """
        ...

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def initialize(
        self,
        config: Any = None,
    ) -> None:
        """注入配置并初始化客户端。

        Args:
            config: 可选的配置 dict 或 ``DecisionModelConfig`` 实例。
                    未提供时从配置文件加载。
        """
        ...

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """检查决策服务是否可达。

        默认实现返回 True。具体 provider 可覆盖此方法
        实现真实的 ping/health 检查。
        """
        return True

    @property
    def is_available(self) -> bool:
        """决策服务是否已正确初始化并可用。"""
        return False
