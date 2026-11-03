"""Tests for the LocalLLMClient example plugin."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from local_llm import LocalLLMClient


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLocalLLMClient:
    def test_init_defaults(self):
        """Default constructor uses Ollama defaults."""
        client = LocalLLMClient()
        assert client.base_url == "http://localhost:11434"
        assert client.model == "llama3"

    def test_init_custom(self):
        """Custom model and URL."""
        client = LocalLLMClient(model="mistral", base_url="http://gpu:11434")
        assert client.model == "mistral"
        assert client.base_url == "http://gpu:11434"

    def test_config_structure(self):
        """Config dict has expected structure."""
        client = LocalLLMClient(model="llama3")
        assert "local" in client.config
        assert "llama3" in client.config["local"]["models"]

    def test_parse_message(self):
        """parse_message converts internal Message to Ollama format."""
        client = LocalLLMClient()

        class FakeMessage:
            role = "user"
            content = "Hello"

        result = client.parse_message("local", "llama3", FakeMessage())
        assert result == {"role": "user", "content": "Hello"}

    def test_stream_response(self):
        """Mock Ollama streaming response."""
        client = LocalLLMClient()

        # Simulate streaming lines
        lines = [
            b'{"message":{"content":"Hello"},"done":false}\n',
            b'{"message":{"content":" world"},"done":false}\n',
            b'{"message":{"content":""},"done":true}\n',
        ]

        class FakeContent:
            def __aiter__(self):
                self._iter = iter(lines)
                return self

            async def __anext__(self):
                try:
                    return next(self._iter)
                except StopIteration:
                    raise StopAsyncIteration

        class FakeResponse:
            content = FakeContent()

            def __init__(self):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        class FakeSession:
            def post(self, url, json=None):
                return FakeResponse()

            def __aenter__(self):
                return self

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        with patch("aiohttp.ClientSession") as mock_cls:
            mock_session = FakeSession()
            # ClientSession() returns an async context manager
            mock_session_ctx = mock_session
            mock_cls.return_value = _AsyncCM(mock_session)

            async def _collect():
                chunks = []
                async for chunk in client.get_stream_response(
                    provider="local",
                    model="llama3",
                    messages=[{"role": "user", "content": "Hi"}],
                ):
                    chunks.append(chunk)
                return chunks

            chunks = asyncio.run(_collect())

        # Should have content chunks + finish
        content_chunks = [c for c in chunks if c["type"] == "content"]
        assert len(content_chunks) >= 1
        assert content_chunks[0]["data"] == "Hello"

        finish_chunks = [c for c in chunks if c["type"] == "finish"]
        assert len(finish_chunks) == 1


    def test_aggregate_message(self):
        """aggregate_message combines content chunks."""
        client = LocalLLMClient()

        content_chunks = [
            {"type": "content", "data": "Hello"},
            {"type": "content", "data": " world"},
        ]

        msg = client.aggregate_message(content_chunks, [])
        assert msg.role == "assistant"
        assert msg.content == "Hello world"

    def test_aggregate_empty(self):
        """Empty chunks produce None."""
        client = LocalLLMClient()
        result = client.aggregate_message([], [])
        assert result is None

    def test_aggregate_with_tool_calls(self):
        """Content chunks with tool calls."""
        client = LocalLLMClient()
        content_chunks = [{"type": "content", "data": "Calling tool"}]
        tool_chunks = [{"id": "call-1", "function": {"name": "test"}}]

        msg = client.aggregate_message(content_chunks, tool_chunks)
        assert msg is not None
        assert msg.content == "Calling tool"


class _AsyncCM:
    """Async context manager wrapper for mocking aiohttp.ClientSession."""

    def __init__(self, inner):
        self._inner = inner

    async def __aenter__(self):
        return self._inner

    async def __aexit__(self, *args):
        return False
