"""Golden-file tests for ``RetryLLMStrategy`` stream aggregation.

Each fixture under ``broca/tests/fixtures/llm_streaming/`` is a hand-written
chunk sequence (never recorded from real traffic) with:

- ``chunks``: raw stream chunks as the LLM client would yield them
  (``tool_call.data`` dicts are rehydrated into ``ToolCall`` objects);
- ``expected_message``: expected aggregation result (field-by-field, ``None``
  when the aggregation is empty);
- ``expected_on_chunk_events``: expected ``on_chunk`` emissions in order
  (``message_id`` is ignored — it is random per run).

The strategy is exercised against the **real** ``LiteLLMClient`` aggregation
logic (``aggregate_message``) with only the transport (``get_stream_response``)
replaced, so this suite protects the streaming-aggregation contract (R5).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from litellm.types.utils import ChatCompletionMessageToolCall, Function
from litellm.types.utils import Message as LLMMessage

from broca.llm import LiteLLMClient
from broca.loop_engine.strategies.retry_llm import RetryLLMStrategy

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "llm_streaming"
FIXTURES = sorted(FIXTURE_DIR.glob("*.json"))


class _FakeStreamingClient(LiteLLMClient):
    """Real aggregation logic + scripted stream (no network, no config file)."""

    def __init__(self, chunks: list[dict]) -> None:
        self.input_tokens_used = 10
        self.output_tokens_used = 20
        self._chunks = chunks

    async def get_stream_response(  # type: ignore[override]
        self, provider, model, messages, tools=None, first_chunk_timeout=None, timeout=None
    ):
        for chunk in self._chunks:
            yield chunk
        # Append usage event (mirrors real LLMClient behaviour).
        yield {
            "type": "usage",
            "data": {
                "input_tokens": self.input_tokens_used,
                "output_tokens": self.output_tokens_used,
            },
        }


class _FakeConfig:
    provider = "fake-provider"
    model = "fake-model"

    class _Exec:
        step_max_errors = 1
        llm_retry_delay = 0
        llm_timeout = 30

    execution_config = _Exec()


class _IdlessToolCall:
    """Stand-in for a malformed provider delta that carries no ``id``.

    ``ChatCompletionMessageToolCall`` auto-generates a uuid when ``id`` is
    ``None``, so a plain object is required to reproduce the abnormal stream
    (fixture ``tool_call_without_id``).
    """

    def __init__(self, index: int, function: Function) -> None:
        self.id = None
        self.index = index
        self.type = "function"
        self.function = function


def _rehydrate(chunks: list[dict]) -> list[dict]:
    """Turn fixture dicts into the objects the LLM client would yield."""
    result: list[dict] = []
    for chunk in chunks:
        if chunk["type"] == "tool_call":
            data = chunk["data"]
            function = Function(**data["function"])
            if data.get("id") is None:
                tool_call: Any = _IdlessToolCall(data.get("index", 0), function)
            else:
                tool_call = ChatCompletionMessageToolCall(
                    id=data["id"],
                    index=data.get("index", 0),
                    type=data.get("type", "function"),
                    function=function,
                )
            result.append({"type": "tool_call", "data": tool_call})
        else:
            result.append(dict(chunk))
    return result


def _serialize_tool_calls(message: LLMMessage | None) -> list[dict]:
    if message is None:
        return []
    out = []
    for tool_call in message.tool_calls or []:
        out.append(
            {
                "id": tool_call.id,
                "type": getattr(tool_call, "type", "function"),
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                },
            }
        )
    return out


def _tool_calls_match(message: LLMMessage, expected: list[dict]) -> bool:
    """Compare tool calls field-by-field.

    ``"<any>"`` as an expected ``id`` accepts any non-empty id: litellm's
    aggregation always materialises an id (it generates a uuid when the
    provider delta carried none), so the abnormal-stream fixture cannot pin it.
    """
    actual = _serialize_tool_calls(message)
    if len(actual) != len(expected):
        return False
    for got, want in zip(actual, expected):
        if want["id"] == "<any>":
            if not got["id"]:
                return False
        elif got["id"] != want["id"]:
            return False
        if got["type"] != want["type"]:
            return False
        if got["function"] != want["function"]:
            return False
    return True


def _normalize_event(event: dict) -> dict:
    """Drop ``message_id`` (random per run) and object identity."""
    normalized = {k: v for k, v in event.items() if k not in ("message_id", "data")}
    if event["type"] == "tool_call":
        normalized["id"] = event["data"].id
    else:
        normalized["data"] = event["data"]
    return normalized


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture_path", FIXTURES, ids=lambda p: p.stem)
async def test_golden_streaming_aggregation(fixture_path: Path) -> None:
    fixture: dict[str, Any] = json.loads(fixture_path.read_text(encoding="utf-8"))
    client = _FakeStreamingClient(_rehydrate(fixture["chunks"]))
    strategy = RetryLLMStrategy()
    await strategy.initialize(llm_client=client, config=_FakeConfig())

    events: list[dict] = []

    async def on_chunk(event: dict) -> None:
        events.append(_normalize_event(event))

    result = await strategy.call([], [], on_chunk=on_chunk)

    expected = fixture["expected_message"]
    if expected is None:
        assert result.message is None, fixture["name"]
        assert result.success is False
        assert result.error_code == "LLM_EMPTY_RESPONSE"
    else:
        assert result.message is not None, fixture["name"]
        assert result.success is True
        # Field-by-field comparison of serializable fields only.
        assert (result.message.content or "") == (expected["content"] or "")
        assert (result.message.reasoning_content or "") == (
            expected["reasoning_content"] or ""
        )
        assert _tool_calls_match(result.message, expected["tool_calls"])

    assert events == fixture["expected_on_chunk_events"], fixture["name"]


def test_fixture_matrix_is_complete() -> None:
    """The 20-fixture coverage matrix from the plan must be present."""
    assert len(FIXTURES) == 20, [p.stem for p in FIXTURES]
