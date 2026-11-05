"""Decision model client based on typesafe-sdk.

Default implementation of :class:`DecisionProvider` that communicates with
a System One compatible decision model service (Kev, Laya, TypeSafe Jev, or
any ``/v1/systemone`` endpoint) via the official ``typesafe-sdk``.

This module mirrors the structure of ``broca/llm.py`` (LiteLLMClient):
- loads provider/model config from ``decision_config.json``
- exposes a high-level ``decide()`` method
- maps SDK errors to :class:`DecisionError`
- supports multiple providers via the same config file format

The typesafe-sdk is the industry-standard client for decision models (analogous
to ``litellm`` for LLMs). All major open-source JEV models (Kev, Laya,
NeoHorse-Jev) implement the TypeSafe ``/v1/systemone`` API, so the same SDK
works with all of them by simply changing ``base_url``.

Configuration file format (``decision_config.json``)::

    {
        "__default__": {"provider": "kev", "model": "kev-4b"},
        "kev": {
            "base_url": "http://localhost:8009",
            "api_key": "",
            "models": {
                "kev-4b": {
                    "model": "kev-latest",
                    "timeout": 30
                }
            }
        },
        "jev": {
            "base_url": "https://api.typesafe.ai",
            "api_key": "tsf-xxx",
            "models": {
                "jev-latest": {
                    "model": "jev-latest",
                    "timeout": 30
                }
            }
        }
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typesafe_sdk import (
    AsyncTypeSafeClient,
    Choice,
    Noul,
    NoulAnswer,
    Score,
    SystemOneResponse,
    TypeSafeAPIError,
    TypeSafeError,
)

from broca.components.decision_provider import (
    DecisionProvider,
    DecisionQuestion,
    DecisionResult,
    QuestionType,
)
from broca.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Config resolution (mirrors broca.configs.resolve_llm_config_path)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def resolve_decision_config_path(
    explicit_path: str | Path | None = None,
) -> Path:
    """解析 decision_config.json 路径。

    优先级:
    1. BrocaConfig.decision_config_file (显式配置)
    2. 项目 configs/decision_config.json
    3. ~/.broca/configs/decision_config.json
    """
    if explicit_path:
        return Path(explicit_path).expanduser()

    # 1. From BrocaConfig
    try:
        from broca.configs import get_configs

        cfg = get_configs().decision_config_file
        if cfg:
            return Path(cfg).expanduser()
    except Exception:
        pass

    # 2. Project default
    project_config = _PROJECT_ROOT / "configs" / "decision_config.json"
    if project_config.exists():
        return project_config

    # 3. Home directory
    home_config = Path.home() / ".broca" / "configs" / "decision_config.json"
    if home_config.exists():
        return home_config

    # Fallback: project path (file may not exist yet — caller handles it)
    return project_config


def get_decision_defaults() -> tuple[str, str]:
    """读取 decision_config.json 的 __default__ 条目。

    Returns:
        (provider, model) 元组。未配置时返回 ("", "")。
    """
    try:
        path = resolve_decision_config_path()
        if path.exists():
            with open(path) as f:
                config = json.load(f)
            default = config.get("__default__")
            if isinstance(default, dict):
                p = default.get("provider", "")
                m = default.get("model", "")
                return (p or "", m or "")
    except Exception:
        pass
    return ("", "")


# ---------------------------------------------------------------------------
# Exception mapping
# ---------------------------------------------------------------------------

class DecisionError(Exception):
    """决策模型调用错误。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        cause: Exception | None = None,
    ):
        self.status_code = status_code
        self.cause = cause
        super().__init__(message)


# ---------------------------------------------------------------------------
# DecisionClient — concrete DecisionProvider implementation
# ---------------------------------------------------------------------------


class DecisionClient(DecisionProvider):
    """Default DecisionProvider: typesafe-sdk client for System One APIs.

    Wraps ``typesafe_sdk.AsyncTypeSafeClient`` (the industry-standard SDK for
    decision models, analogous to ``litellm`` for LLMs) to provide:
    - built-in retry with exponential backoff
    - typed question/response objects (Choice, Noul, Score)
    - per-provider client management (base_url + api_key)
    - one-liner switching between Kev, Laya, Jev, OpenRouter, etc.

    Usage::

        client = DecisionClient()
        await client.initialize()

        results = await client.decide(
            state="用户请求: 我要退款",
            questions=[
                DecisionQuestion(name="is_refund", type=QuestionType.NOUL,
                                 instructions="Is this a refund request?"),
            ],
        )
    """

    name = "decision_client"

    def __init__(self, config: dict | None = None):
        """Initialize DecisionClient.

        Args:
            config: 可选的决策模型配置 dict。未提供时从配置文件加载。
                    测试中可传入 mock 配置避免读文件。
        """
        self._initialized = False
        self._clients: dict[str, AsyncTypeSafeClient] = {}
        self._default_provider: str = ""
        self._default_model: str = ""
        self._confidence_threshold: float = 0.75

        if config is not None:
            self.config = config
        else:
            config_file = resolve_decision_config_path()
            try:
                with open(config_file) as f:
                    self.config = json.load(f)
            except (OSError, json.JSONDecodeError, FileNotFoundError) as e:
                logger.warning(
                    f"Failed to load decision config from {config_file}: {e}. "
                    f"DecisionClient will be unavailable."
                )
                self.config = {}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """Decision service is properly configured and initialized."""
        return self._initialized and bool(self.config)

    # ------------------------------------------------------------------
    # DecisionProvider interface
    # ------------------------------------------------------------------

    async def initialize(self, config: Any = None) -> None:
        """Initialize SDK clients for all configured providers.

        Args:
            config: Optional config override. If provided, replaces
                the config loaded in ``__init__``.
        """
        if config is not None:
            self.config = config

        # Resolve defaults
        if "__default__" in self.config:
            default = self.config["__default__"]
            self._default_provider = default.get("provider", "")
            self._default_model = default.get("model", "")

        # Confidence threshold from config or default
        threshold = self.config.get("confidence_threshold")
        if isinstance(threshold, (int, float)):
            self._confidence_threshold = float(threshold)

        # Create a typesafe client per provider
        self._clients.clear()
        for provider_name, provider_cfg in self.config.items():
            if provider_name == "__default__" or not isinstance(provider_cfg, dict):
                continue
            base_url = provider_cfg.get("base_url", "")
            if not base_url:
                continue
            api_key = provider_cfg.get("api_key", "")
            # typesafe-sdk requires a non-empty api_key; use "local" for
            # self-hosted providers (Kev, Laya) that don't validate auth.
            if not api_key:
                api_key = "local"
            # Use the first model's timeout as client-level default
            models = provider_cfg.get("models", {})
            timeout = 30.0
            if models:
                first_model = next(iter(models.values()), {})
                timeout = float(first_model.get("timeout", 30.0))

            self._clients[provider_name] = AsyncTypeSafeClient(
                base_url=base_url,
                api_key=api_key,
                timeout=timeout,
            )

        self._initialized = True
        logger.info(
            f"DecisionClient initialized (provider={self._default_provider}, "
            f"model={self._default_model}, "
            f"providers={list(self._clients.keys())})"
        )

    async def shutdown(self) -> None:
        """Close all SDK clients."""
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()
        self._initialized = False

    async def decide(
        self,
        state: str,
        questions: list[DecisionQuestion],
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> list[DecisionResult]:
        """Send a decision request to the decision model service.

        Uses ``typesafe_sdk.AsyncTypeSafeClient.system_one()`` under the hood,
        which provides built-in retry and typed response parsing.

        Args:
            state: Context/state text.
            questions: List of typed decision questions.
            provider: Override the default provider.
            model: Override the default model.

        Returns:
            List of DecisionResult in the same order as ``questions``.
            Returns empty list on failure (logged, not raised).
        """
        provider = provider or self._default_provider
        model = model or self._default_model

        if not provider or not model:
            logger.warning(
                "DecisionClient: no default provider/model configured. "
                "Cannot make decision. Configure decision_config.json."
            )
            return []

        if provider not in self._clients:
            logger.warning(
                f"DecisionClient: provider '{provider}' not initialized. "
                f"Available: {list(self._clients.keys())}"
            )
            return []

        client = self._clients[provider]

        # Resolve model name (map config alias → API model name)
        provider_cfg = self.config.get(provider, {})
        model_cfg = provider_cfg.get("models", {}).get(model, {})
        api_model = model_cfg.get("model", model)
        timeout = model_cfg.get("timeout")

        # Build typesafe-sdk question objects
        sdk_questions = self._build_sdk_questions(questions)

        # Call the SDK (built-in retry handles transient errors)
        try:
            response = await client.system_one(
                state=state,
                questions=sdk_questions,
                model=api_model,
                timeout=float(timeout) if timeout else None,
            )
        except TypeSafeAPIError as e:
            logger.warning(f"DecisionClient API error: {e}")
            return []
        except TypeSafeError as e:
            logger.warning(f"DecisionClient SDK error: {e}")
            return []
        except Exception as e:
            logger.warning(f"DecisionClient unexpected error: {e}")
            return []

        # Parse typed response into DecisionResult
        return self._parse_response(response, questions)

    async def health_check(self) -> bool:
        """Check if the default decision service is reachable.

        Makes a minimal decision call to verify connectivity.
        """
        if not self.is_available or not self._default_provider:
            return False
        if self._default_provider not in self._clients:
            return False

        try:
            provider_cfg = self.config.get(self._default_provider, {})
            api_model = self._default_model
            client = self._clients[self._default_provider]
            response = await client.system_one(
                state="health check",
                questions={
                    "ping": Noul(instructions="Is this a health check?"),
                },
                model=api_model,
                timeout=10.0,
            )
            # If we get any response, the service is alive
            return "ping" in response.nouls
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_sdk_questions(
        self, questions: list[DecisionQuestion]
    ) -> dict[str, Any]:
        """Convert DecisionQuestion list to typesafe-sdk question objects.

        Maps our abstract types to the SDK's typed primitives:
        - QuestionType.CHOICE → Choice(instructions=..., criteria=...)
        - QuestionType.NOUL   → Noul(instructions=...)
        - QuestionType.SCORE  → Score(instructions=..., criteria=...)
        """
        sdk_questions: dict[str, Any] = {}

        for q in questions:
            criteria = q.criteria if q.criteria is not None else None

            if q.type == QuestionType.CHOICE:
                sdk_questions[q.name] = Choice(
                    instructions=q.instructions,
                    criteria=criteria or {},
                )
            elif q.type == QuestionType.NOUL:
                # Noul criteria is optional (bool criteria: true/false descriptions)
                sdk_questions[q.name] = Noul(
                    instructions=q.instructions,
                    **( {"criteria": criteria} if criteria else {} ),
                )
            elif q.type == QuestionType.SCORE:
                sdk_questions[q.name] = Score(
                    instructions=q.instructions,
                    criteria=criteria or {},
                )

        return sdk_questions

    def _parse_response(
        self,
        response: SystemOneResponse,
        questions: list[DecisionQuestion],
    ) -> list[DecisionResult]:
        """Parse SystemOneResponse into DecisionResult objects.

        The typesafe-sdk provides typed response access:
        - ``response.choices[name]`` → ChoiceAnswer (choice, confidence, probabilities)
        - ``response.nouls[name]``   → NoulAnswer (noul: bool)
        - ``response.scores[name]``  → ScoreAnswer (score, confidence, probabilities)
        """
        results: list[DecisionResult] = []

        for q in questions:
            answer, probabilities, confidence = self._extract_answer(response, q)
            escalate = confidence < self._confidence_threshold
            results.append(
                DecisionResult(
                    question_name=q.name,
                    type=q.type,
                    answer=answer,
                    probabilities=probabilities,
                    confidence=confidence,
                    escalate=escalate,
                )
            )

        return results

    @staticmethod
    def _extract_answer(
        response: SystemOneResponse, question: DecisionQuestion
    ) -> tuple[Any, dict[str, float], float]:
        """Extract (answer, probabilities, confidence) for a question.

        Returns a 3-tuple: (answer, probabilities_dict, confidence_float)
        """
        name = question.name

        if question.type == QuestionType.CHOICE:
            data: Any = response.choices.get(name)
            if data is None:
                return "", {}, 0.0
            # ChoiceAnswer: .choice (str), .confidence (float), .probabilities (dict)
            probs = {str(k): float(v) for k, v in (data.probabilities or {}).items()}
            confidence = float(data.confidence or 0.0)
            return data.choice or "", probs, confidence

        elif question.type == QuestionType.NOUL:
            data = response.nouls.get(name)
            if data is None:
                return False, {}, 0.0
            # NoulAnswer: .noul is the probability (0.0-1.0)
            noul_value = data.noul
            # The noul value itself encodes confidence:
            # noul > 0.5 means "yes", noul < 0.5 means "no"
            # The answer is the boolean interpretation
            answer = noul_value > 0.5 if isinstance(noul_value, (int, float)) else bool(noul_value)
            # Probabilities: the noul value IS the probability of "yes"
            probs = {
                "true": float(noul_value) if isinstance(noul_value, (int, float)) else (1.0 if noul_value else 0.0),
                "false": (1.0 - float(noul_value)) if isinstance(noul_value, (int, float)) else (0.0 if noul_value else 1.0),
            }
            confidence = probs["true"] if answer else probs["false"]
            return answer, probs, confidence

        elif question.type == QuestionType.SCORE:
            data = response.scores.get(name)
            if data is None:
                return 0.0, {}, 0.0
            # ScoreAnswer: .score (float), .confidence (float), .probabilities (dict)
            probs = {str(k): float(v) for k, v in (data.probabilities or {}).items()}
            confidence = float(data.confidence or 0.0)
            return float(data.score or 0.0), probs, confidence

        return None, {}, 0.0
