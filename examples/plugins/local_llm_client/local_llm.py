"""LocalLLMClient — example plugin that uses a local Ollama model.

This example shows how to replace the cloud LLM (LiteLLM) with a
local model server (Ollama).  No external API keys needed.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any, Optional

from broca.components.llm_client import LLMClient


class LocalLLMClient(LLMClient):
    """LLM client backed by a local Ollama server.

    Default: ``http://localhost:11434`` (Ollama default port).
    """

    def __init__(self, **kwargs) -> None:
        self.base_url: str = kwargs.get("base_url", "http://localhost:11434")
        self.model: str = kwargs.get("model", "llama3")
        self.config: dict = {
            "local": {"models": {self.model: {"meta": {}}}}
        }

    # ------------------------------------------------------------------
    # Message parsing
    # ------------------------------------------------------------------

    def parse_message(self, provider: str, model: str, message) -> dict:
        """Convert internal Message to Ollama format."""
        return {
            "role": getattr(message, "role", "user"),
            "content": getattr(message, "content", ""),
        }

    # ------------------------------------------------------------------
    # Streaming response
    # ------------------------------------------------------------------

    async def get_stream_response(
        self,
        provider: str,
        model: str,
        messages: list,
        tools: Optional[list] = None,
        first_chunk_timeout: Optional[float] = None,
        timeout: Optional[float] = None,
    ) -> AsyncGenerator[dict, None]:
        """Call Ollama's streaming API and yield chunks.

        Yields:
            ``{"type": "content", "data": "<text>"}`` for each token
            ``{"type": "finish", "data": "stop"}`` at the end
        """
        import aiohttp

        # Convert messages to Ollama format
        ollama_messages = []
        for msg in messages:
            if isinstance(msg, dict):
                ollama_messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                })

        payload = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": True,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/api/chat",
                json=payload,
            ) as resp:
                async for line in resp.content:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if data.get("error"):
                        yield {"type": "error", "data": data["error"]}
                        return

                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield {"type": "content", "data": content}

                    if data.get("done", False):
                        break

        yield {"type": "finish", "data": "stop"}

    # ------------------------------------------------------------------
    # Message aggregation
    # ------------------------------------------------------------------

    def aggregate_message(self, content_chunks: list, tool_call_chunks: list) -> Any:
        """Aggregate streaming chunks into a single LLMMessage."""
        from litellm import Message

        content = "".join(
            c["data"] for c in (content_chunks or []) if c.get("type") == "content"
        )
        if not content and not tool_call_chunks:
            return None
        return Message(role="assistant", content=content)
