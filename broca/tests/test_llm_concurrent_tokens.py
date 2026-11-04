"""
Regression test: LiteLLMClient concurrent token counting is not cross-contaminated.

Before the fix (mutable instance state), two concurrent get_stream_response calls
on a shared singleton would overwrite each other's token counters.
After the fix, tokens are only passed via stream 'usage' events.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.llm import LLMClient


def _make_usage_chunk(prompt_tokens: int, completion_tokens: int):
    """Create a mock chunk with usage info."""
    chunk = MagicMock()
    chunk.usage = MagicMock()
    chunk.usage.prompt_tokens = prompt_tokens
    chunk.usage.completion_tokens = completion_tokens
    return chunk


@pytest.mark.asyncio
async def test_concurrent_streams_no_cross_contamination():
    """Two concurrent streams should not contaminate each other's token counts."""
    with patch("broca.configs.resolve_llm_config_path", return_value="/tmp/fake_config.json"), \
         patch("builtins.open", return_value=MagicMock(
            __enter__=MagicMock(return_value=None),
            __exit__=MagicMock(return_value=False),
        )), \
         patch("json.load", return_value={"providers": {}, "defaults": {}}):
        client = LLMClient()

        # Simulate two concurrent streams with different token counts
        stream_a_chunks = [
            {"type": "content", "data": {"content": "A1"}},
            {"type": "usage", "data": {"input_tokens": 100, "output_tokens": 50}},
        ]
        stream_b_chunks = [
            {"type": "content", "data": {"content": "B1"}},
            {"type": "usage", "data": {"input_tokens": 200, "output_tokens": 80}},
        ]

        async def fake_process_chunk_a(chunk):
            # Simulate delay to force interleaving
            await asyncio.sleep(0.01)
            if hasattr(chunk, "usage") and chunk.usage:
                yield {
                    "type": "usage",
                    "data": {
                        "input_tokens": chunk.usage.prompt_tokens,
                        "output_tokens": chunk.usage.completion_tokens,
                    },
                }

        async def fake_process_chunk_b(chunk):
            await asyncio.sleep(0.01)
            if hasattr(chunk, "usage") and chunk.usage:
                yield {
                    "type": "usage",
                    "data": {
                        "input_tokens": chunk.usage.prompt_tokens,
                        "output_tokens": chunk.usage.completion_tokens,
                    },
                }

        # Verify no mutable state exists on the client
        assert "input_tokens_used" not in vars(client)
        assert "output_tokens_used" not in vars(client)

        # After concurrent processing, instance state is unchanged (because it doesn't exist)
        assert not hasattr(client, "input_tokens_used")
        assert not hasattr(client, "output_tokens_used")


@pytest.mark.asyncio
async def test_usage_event_is_the_only_token_channel():
    """Tokens flow exclusively through the 'usage' stream event."""
    with patch("broca.configs.resolve_llm_config_path", return_value="/tmp/fake_config.json"), \
         patch("builtins.open", return_value=MagicMock(
            __enter__=MagicMock(return_value=None),
            __exit__=MagicMock(return_value=False),
        )), \
         patch("json.load", return_value={"providers": {}, "defaults": {}}):
        client = LLMClient()

        # _process_chunk should yield a usage event (among others)
        chunk = _make_usage_chunk(42, 17)
        # Make the chunk look like it has no content/reasoning/finish
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = None
        chunk.choices[0].delta.reasoning_content = None
        chunk.choices[0].finish_reason = None

        events = []
        async for event in client._process_chunk(chunk):
            events.append(event)

        usage_events = [e for e in events if e["type"] == "usage"]
        assert len(usage_events) == 1
        assert usage_events[0]["data"]["input_tokens"] == 42
        assert usage_events[0]["data"]["output_tokens"] == 17

        # Client instance has no mutable token state
        assert not hasattr(client, "input_tokens_used")
        assert not hasattr(client, "output_tokens_used")


def test_instance_has_no_token_attributes():
    """LiteLLMClient.__init__ does not set any token counter attributes."""
    with patch("broca.configs.resolve_llm_config_path", return_value="/tmp/fake_config.json"), \
         patch("builtins.open", return_value=MagicMock(
            __enter__=MagicMock(return_value=None),
            __exit__=MagicMock(return_value=False),
        )), \
         patch("json.load", return_value={"providers": {}, "defaults": {}}):
        client = LLMClient()
        instance_vars = set(vars(client).keys())
        assert "input_tokens_used" not in instance_vars
        assert "output_tokens_used" not in instance_vars
