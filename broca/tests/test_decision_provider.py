"""Tests for DecisionProvider interface and DecisionClient implementation (typesafe-sdk based)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from typesafe_sdk import (
    AsyncTypeSafeClient,
    Noul,
    TypeSafeAPIError,
    TypeSafeError,
)

from broca.components.decision_provider import (
    DecisionProvider,
    DecisionQuestion,
    DecisionResult,
    QuestionType,
)
from broca.decision import (
    DecisionClient,
    DecisionError,
    get_decision_defaults,
    resolve_decision_config_path,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def decision_config():
    """Minimal decision_config.json structure for tests."""
    return {
        "__default__": {"provider": "kev", "model": "kev-4b"},
        "kev": {
            "base_url": "http://localhost:8009",
            "api_key": "",
            "models": {
                "kev-4b": {
                    "model": "kev-latest",
                    "timeout": 30,
                }
            },
        },
        "jev": {
            "base_url": "https://api.typesafe.ai",
            "api_key": "tsf-test-key",
            "models": {
                "jev-latest": {
                    "model": "jev-latest",
                    "timeout": 15,
                }
            },
        },
    }


@pytest.fixture
def client(decision_config) -> DecisionClient:
    """DecisionClient with injected test config."""
    c = DecisionClient(config=decision_config)
    return c


def _make_response(choices=None, nouls=None, scores=None):
    """Build a mock SystemOneResponse with typed sub-answers.

    Args:
        choices: dict[name] → (choice_str, confidence_float, probabilities_dict)
        nouls: dict[name] → noul_float (probability of yes)
        scores: dict[name] → (score_float, confidence_float, probabilities_dict)
    """
    resp = Mock()
    resp.choices = {}
    resp.nouls = {}
    resp.scores = {}

    for name, (choice, confidence, probs) in (choices or {}).items():
        answer = Mock()
        answer.choice = choice
        answer.confidence = confidence
        answer.probabilities = probs
        resp.choices[name] = answer

    for name, noul_val in (nouls or {}).items():
        answer = Mock()
        answer.noul = noul_val
        resp.nouls[name] = answer

    for name, (score, confidence, probs) in (scores or {}).items():
        answer = Mock()
        answer.score = score
        answer.confidence = confidence
        answer.probabilities = probs
        resp.scores[name] = answer

    return resp


@contextmanager
def _mock_system_one(client: DecisionClient, provider: str, response: Mock):
    """Patch the typesafe-sdk client's system_one for a given provider."""
    sdk_client = client._clients[provider]
    mock_fn = AsyncMock(return_value=response)
    with patch.object(sdk_client, "system_one", new=mock_fn) as patched:
        yield patched


# ---------------------------------------------------------------------------
# QuestionType enum
# ---------------------------------------------------------------------------


class TestQuestionType:
    def test_values(self):
        assert QuestionType.CHOICE.value == "choice"
        assert QuestionType.NOUL.value == "noul"
        assert QuestionType.SCORE.value == "score"

    def test_all_types(self):
        assert len(QuestionType) == 3


# ---------------------------------------------------------------------------
# DecisionQuestion dataclass
# ---------------------------------------------------------------------------


class TestDecisionQuestion:
    def test_choice_question(self):
        q = DecisionQuestion(
            name="team",
            type=QuestionType.CHOICE,
            instructions="Which team?",
            criteria={"billing": "Refunds", "tech": "Bugs"},
        )
        assert q.name == "team"
        assert q.type == QuestionType.CHOICE
        assert q.criteria == {"billing": "Refunds", "tech": "Bugs"}

    def test_noul_question_no_criteria(self):
        q = DecisionQuestion(
            name="is_refund",
            type=QuestionType.NOUL,
            instructions="Is this a refund request?",
        )
        assert q.criteria is None

    def test_score_question_list_criteria(self):
        q = DecisionQuestion(
            name="risk",
            type=QuestionType.SCORE,
            instructions="Risk level?",
            criteria=["safe", "low", "moderate", "high", "critical"],
        )
        assert q.criteria == ["safe", "low", "moderate", "high", "critical"]


# ---------------------------------------------------------------------------
# DecisionResult dataclass
# ---------------------------------------------------------------------------


class TestDecisionResult:
    def test_choice_result(self):
        r = DecisionResult(
            question_name="team",
            type=QuestionType.CHOICE,
            answer="billing",
            probabilities={"billing": 0.9, "tech": 0.1},
            confidence=0.9,
        )
        assert r.answer == "billing"
        assert r.confidence == 0.9
        assert r.escalate is False

    def test_escalate_on_low_confidence(self):
        r = DecisionResult(
            question_name="team",
            type=QuestionType.CHOICE,
            answer="billing",
            probabilities={"billing": 0.4, "tech": 0.3, "other": 0.3},
            confidence=0.4,
            escalate=True,
        )
        assert r.escalate is True


# ---------------------------------------------------------------------------
# DecisionClient — constructor & config
# ---------------------------------------------------------------------------


class TestDecisionClientInit:
    def test_with_explicit_config(self, decision_config):
        c = DecisionClient(config=decision_config)
        assert c.config == decision_config
        assert not c.is_available

    def test_config_file_not_found(self, tmp_path, monkeypatch):
        """When no config file exists, client still constructs with empty config."""
        with patch("broca.decision.resolve_decision_config_path") as mock_resolve:
            mock_resolve.return_value = tmp_path / "nonexistent_decision.json"
            c = DecisionClient()
        assert c.config == {}
        assert not c.is_available

    def test_config_file_loaded(self, tmp_path, monkeypatch, decision_config):
        """Config file at ~/.broca/configs/decision_config.json is loaded."""
        config_dir = tmp_path / ".broca" / "configs"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "decision_config.json").write_text(
            json.dumps(decision_config)
        )
        monkeypatch.setenv("HOME", str(tmp_path))

        c = DecisionClient()
        assert c.config["__default__"]["provider"] == "kev"


# ---------------------------------------------------------------------------
# DecisionClient — initialize()
# ---------------------------------------------------------------------------


class TestDecisionClientInitialize:
    @pytest.mark.asyncio
    async def test_initialize_sets_available(self, client: DecisionClient):
        with patch("broca.decision.AsyncTypeSafeClient") as mock_sdk:
            mock_client = Mock()
            mock_client.aclose = AsyncMock()
            mock_sdk.return_value = mock_client

            await client.initialize()
            assert client.is_available
            # Should create one client per provider (kev, jev)
            assert mock_sdk.call_count == 2

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, client: DecisionClient):
        with patch("broca.decision.AsyncTypeSafeClient") as mock_sdk:
            mock_client = Mock()
            mock_client.aclose = AsyncMock()
            mock_sdk.return_value = mock_client

            await client.initialize()
            await client.initialize()  # should not raise
            assert client.is_available

    @pytest.mark.asyncio
    async def test_initialize_with_override(self, decision_config):
        c = DecisionClient()
        with patch("broca.decision.AsyncTypeSafeClient") as mock_sdk:
            mock_client = Mock()
            mock_client.aclose = AsyncMock()
            mock_sdk.return_value = mock_client

            await c.initialize(config=decision_config)
            assert c.config == decision_config
            assert c.is_available

    @pytest.mark.asyncio
    async def test_shutdown(self, client: DecisionClient):
        with patch("broca.decision.AsyncTypeSafeClient") as mock_sdk:
            mock_client = Mock()
            mock_client.aclose = AsyncMock()
            mock_sdk.return_value = mock_client

            await client.initialize()
            await client.shutdown()
            assert not client.is_available
            mock_client.aclose.assert_called()

    @pytest.mark.asyncio
    async def test_initialize_passes_correct_args(self, client: DecisionClient):
        """Verify base_url and api_key are passed to AsyncTypeSafeClient."""
        with patch("broca.decision.AsyncTypeSafeClient") as mock_sdk:
            mock_client = Mock()
            mock_client.aclose = AsyncMock()
            mock_sdk.return_value = mock_client

            await client.initialize()

            # First call should be for 'kev' (first non-default provider)
            calls = mock_sdk.call_args_list
            base_urls = [c.kwargs.get("base_url") for c in calls]
            assert "http://localhost:8009" in base_urls
            assert "https://api.typesafe.ai" in base_urls


# ---------------------------------------------------------------------------
# DecisionClient — _build_sdk_questions
# ---------------------------------------------------------------------------


class TestBuildSdkQuestions:
    def test_build_choice_question(self):
        from typesafe_sdk import Choice

        c = DecisionClient(config={})
        questions = [
            DecisionQuestion(
                name="team",
                type=QuestionType.CHOICE,
                instructions="Which team handles this?",
                criteria={"billing": "Refunds", "tech": "Bugs"},
            )
        ]
        result = c._build_sdk_questions(questions)
        assert "team" in result
        assert isinstance(result["team"], Choice)
        assert result["team"].instructions == "Which team handles this?"
        assert result["team"].criteria == {"billing": "Refunds", "tech": "Bugs"}

    def test_build_noul_question(self):
        from typesafe_sdk import Noul

        c = DecisionClient(config={})
        questions = [
            DecisionQuestion(
                name="is_refund",
                type=QuestionType.NOUL,
                instructions="Is this a refund request?",
            )
        ]
        result = c._build_sdk_questions(questions)
        assert "is_refund" in result
        assert isinstance(result["is_refund"], Noul)
        assert result["is_refund"].instructions == "Is this a refund request?"

    def test_build_score_question(self):
        from typesafe_sdk import Score

        c = DecisionClient(config={})
        questions = [
            DecisionQuestion(
                name="risk",
                type=QuestionType.SCORE,
                instructions="Risk level?",
                criteria=["safe", "moderate", "critical"],
            )
        ]
        result = c._build_sdk_questions(questions)
        assert "risk" in result
        assert isinstance(result["risk"], Score)
        assert result["risk"].criteria == ["safe", "moderate", "critical"]

    def test_build_multiple_mixed_questions(self):
        c = DecisionClient(config={})
        questions = [
            DecisionQuestion(name="q1", type=QuestionType.NOUL, instructions="Q1?"),
            DecisionQuestion(
                name="q2", type=QuestionType.CHOICE, instructions="Q2?",
                criteria={"a": "A", "b": "B"},
            ),
            DecisionQuestion(name="q3", type=QuestionType.SCORE, instructions="Q3?",
                             criteria=["low", "high"]),
        ]
        result = c._build_sdk_questions(questions)
        assert set(result.keys()) == {"q1", "q2", "q3"}


# ---------------------------------------------------------------------------
# DecisionClient — decide() with mocked SDK client
# ---------------------------------------------------------------------------


class TestDecideWithMockedSDK:
    @pytest.mark.asyncio
    async def test_decide_success_choice(self, client: DecisionClient):
        await client.initialize()

        response = _make_response(
            choices={
                "team": ("billing", 0.85, {"billing": 0.85, "tech": 0.15}),
            }
        )

        with _mock_system_one(client, "kev", response):
            results = await client.decide(
                state="I was charged twice",
                questions=[
                    DecisionQuestion(
                        name="team",
                        type=QuestionType.CHOICE,
                        instructions="Which team?",
                        criteria={"billing": "Refunds", "tech": "Bugs"},
                    )
                ],
            )

        assert len(results) == 1
        assert results[0].question_name == "team"
        assert results[0].type == QuestionType.CHOICE
        assert results[0].answer == "billing"
        assert results[0].confidence == 0.85
        assert results[0].escalate is False

    @pytest.mark.asyncio
    async def test_decide_success_noul(self, client: DecisionClient):
        await client.initialize()

        # noul = 0.92 means "yes" with 92% probability
        response = _make_response(
            nouls={"is_refund": 0.92}
        )

        with _mock_system_one(client, "kev", response):
            results = await client.decide(
                state="Please refund me",
                questions=[
                    DecisionQuestion(
                        name="is_refund",
                        type=QuestionType.NOUL,
                        instructions="Is this a refund request?",
                    )
                ],
            )

        assert len(results) == 1
        assert results[0].answer is True  # 0.92 > 0.5 → yes
        assert results[0].confidence == 0.92

    @pytest.mark.asyncio
    async def test_decide_noul_false(self, client: DecisionClient):
        await client.initialize()

        # noul = 0.2 means "no" (20% probability of yes)
        response = _make_response(
            nouls={"is_refund": 0.2}
        )

        with _mock_system_one(client, "kev", response):
            results = await client.decide(
                state="I want to change my plan",
                questions=[
                    DecisionQuestion(
                        name="is_refund",
                        type=QuestionType.NOUL,
                        instructions="Is this a refund request?",
                    )
                ],
            )

        assert results[0].answer is False  # 0.2 < 0.5 → no
        assert results[0].confidence == 0.8  # confidence = 1 - 0.2

    @pytest.mark.asyncio
    async def test_decide_escalate_on_low_confidence(self, client: DecisionClient):
        await client.initialize()
        # Set a high threshold to force escalation
        client._confidence_threshold = 0.95

        response = _make_response(
            choices={
                "team": ("billing", 0.6, {"billing": 0.6, "tech": 0.4}),
            }
        )

        with _mock_system_one(client, "kev", response):
            results = await client.decide(
                state="ambiguous request",
                questions=[
                    DecisionQuestion(
                        name="team",
                        type=QuestionType.CHOICE,
                        instructions="Which team?",
                        criteria={"billing": "x", "tech": "y"},
                    )
                ],
            )

        assert results[0].confidence == 0.6
        assert results[0].escalate is True

    @pytest.mark.asyncio
    async def test_decide_multiple_questions(self, client: DecisionClient):
        await client.initialize()

        response = _make_response(
            choices={
                "team": ("tech", 0.9, {"tech": 0.9, "billing": 0.1}),
            },
            nouls={
                "urgent": 0.2,  # not urgent
            },
            scores={
                "risk": (2.1, 0.7, {0: 0.3, 1: 0.5, 2: 0.2}),
            },
        )

        with _mock_system_one(client, "kev", response):
            results = await client.decide(
                state="Bug report with moderate frustration",
                questions=[
                    DecisionQuestion(
                        name="team", type=QuestionType.CHOICE,
                        instructions="Which team?",
                        criteria={"tech": "Bugs", "billing": "Refunds"},
                    ),
                    DecisionQuestion(
                        name="urgent", type=QuestionType.NOUL,
                        instructions="Is this urgent?",
                    ),
                    DecisionQuestion(
                        name="risk", type=QuestionType.SCORE,
                        instructions="Risk level?",
                        criteria=["safe", "moderate", "critical"],
                    ),
                ],
            )

        assert len(results) == 3
        assert results[0].answer == "tech"
        assert results[1].answer is False  # noul=0.2 < 0.5
        assert results[2].answer == 2.1
        assert results[2].confidence == 0.7

    @pytest.mark.asyncio
    async def test_decide_no_config_returns_empty(self):
        c = DecisionClient(config={})
        await c.initialize()

        results = await c.decide(state="test", questions=[
            DecisionQuestion(name="q", type=QuestionType.NOUL, instructions="Q?")
        ])
        assert results == []

    @pytest.mark.asyncio
    async def test_decide_unknown_provider_returns_empty(self, client: DecisionClient):
        await client.initialize()

        results = await client.decide(
            state="test",
            questions=[
                DecisionQuestion(name="q", type=QuestionType.NOUL, instructions="Q?")
            ],
            provider="nonexistent",
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_decide_api_error_returns_empty(self, client: DecisionClient):
        """TypeSafeAPIError (e.g. 401) → empty result, no exception raised."""
        await client.initialize()

        with _mock_system_one(client, "kev", None) as mock_fn:
            mock_fn.side_effect = TypeSafeAPIError(
                status=401,
                body={"error": "Unauthorized"},
                headers={},
                message="Unauthorized",
            )

            results = await client.decide(
                state="test",
                questions=[
                    DecisionQuestion(name="q", type=QuestionType.NOUL, instructions="Q?")
                ],
            )
        assert results == []

    @pytest.mark.asyncio
    async def test_decide_connection_error_returns_empty(self, client: DecisionClient):
        """Connection errors (TypeSafeError) → empty result."""
        await client.initialize()

        with _mock_system_one(client, "kev", None) as mock_fn:
            mock_fn.side_effect = TypeSafeError("Connection refused")

            results = await client.decide(
                state="test",
                questions=[
                    DecisionQuestion(name="q", type=QuestionType.NOUL, instructions="Q?")
                ],
            )
        assert results == []

    @pytest.mark.asyncio
    async def test_decide_custom_provider_model(self, client: DecisionClient):
        """Using explicit provider/model routes to the correct SDK client."""
        await client.initialize()

        response = _make_response(
            nouls={"q": 1.0}
        )

        with _mock_system_one(client, "jev", response) as mock_fn:
            results = await client.decide(
                state="test",
                questions=[
                    DecisionQuestion(name="q", type=QuestionType.NOUL, instructions="Q?")
                ],
                provider="jev",
                model="jev-latest",
            )

        assert len(results) == 1
        assert results[0].answer is True
        # Verify the SDK call used the resolved model name
        call_kwargs = mock_fn.call_args.kwargs
        assert call_kwargs["model"] == "jev-latest"

    @pytest.mark.asyncio
    async def test_decide_missing_answer_in_response(self, client: DecisionClient):
        """When the model doesn't answer a question, result has empty values."""
        await client.initialize()

        # Response only has 'answered', not 'missing'
        response = _make_response(
            nouls={"answered": 0.9}
        )

        with _mock_system_one(client, "kev", response):
            results = await client.decide(
                state="test",
                questions=[
                    DecisionQuestion(name="answered", type=QuestionType.NOUL, instructions="Q1?"),
                    DecisionQuestion(name="missing", type=QuestionType.NOUL, instructions="Q2?"),
                ],
            )

        assert len(results) == 2
        assert results[0].answer is True
        assert results[1].answer is False  # default when missing
        assert results[1].confidence == 0.0
        assert results[1].escalate is True


# ---------------------------------------------------------------------------
# DecisionClient — health_check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_not_initialized(self, client: DecisionClient):
        # Not initialized → False
        assert await client.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_success(self, client: DecisionClient):
        await client.initialize()

        response = _make_response(nouls={"ping": 0.99})
        with _mock_system_one(client, "kev", response):
            assert await client.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_unreachable(self, client: DecisionClient):
        await client.initialize()

        with _mock_system_one(client, "kev", None) as mock_fn:
            mock_fn.side_effect = TypeSafeError("Connection refused")

            assert await client.health_check() is False


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------


class TestConfigResolution:
    def test_resolve_explicit_path(self, tmp_path):
        p = tmp_path / "custom_decision.json"
        result = resolve_decision_config_path(str(p))
        assert result == p

    def test_get_decision_defaults_from_file(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".broca" / "configs"
        config_dir.mkdir(parents=True, exist_ok=True)
        config = {
            "__default__": {"provider": "laya", "model": "laya-421m"},
            "laya": {"base_url": "http://localhost:9000", "api_key": "",
                     "models": {"laya-421m": {"model": "laya"}}},
        }
        (config_dir / "decision_config.json").write_text(json.dumps(config))
        monkeypatch.setenv("HOME", str(tmp_path))

        with patch("broca.decision.resolve_decision_config_path",
                   return_value=config_dir / "decision_config.json"):
            provider, model = get_decision_defaults()
        assert provider == "laya"
        assert model == "laya-421m"

    def test_get_decision_defaults_missing_file(self, tmp_path, monkeypatch):
        with patch("broca.decision.resolve_decision_config_path",
                   return_value=tmp_path / "nonexistent.json"):
            provider, model = get_decision_defaults()
        assert provider == ""
        assert model == ""


# ---------------------------------------------------------------------------
# DecisionClient is a DecisionProvider (duck typing)
# ---------------------------------------------------------------------------


class TestInterfaceConformance:
    def test_decision_client_is_provider(self, client: DecisionClient):
        """DecisionClient satisfies the DecisionProvider interface."""
        assert isinstance(client, DecisionProvider)
        assert hasattr(client, "decide")
        assert hasattr(client, "initialize")
        assert hasattr(client, "health_check")
        assert hasattr(client, "is_available")

    def test_decision_client_name(self, client: DecisionClient):
        assert client.name == "decision_client"
