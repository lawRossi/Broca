"""LLMClient component interface.

Abstracts LLM API calls across different providers (litellm, local models,
etc.).  The default implementation is ``LiteLLMClient`` (renamed from
``LLMClient`` in Phase 4).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Optional, TYPE_CHECKING

from broca.components.base import BaseComponent

if TYPE_CHECKING:
    from broca.session.models import Message


class LLMClient(BaseComponent, ABC):
    """LLM client interface for making API calls to various providers."""

    @abstractmethod
    def parse_message(
        self, provider: str, model: str, message: "Message"
    ) -> dict:
        """Parse an internal ``Message`` into the LLM's expected format.

        Args:
            provider: LLM provider name.
            model: LLM model name.
            message: Internal message object.

        Returns:
            Dict with ``role`` and ``content`` fields (provider-specific).
        """
        ...

    @abstractmethod
    async def get_stream_response(
        self,
        provider: str,
        model: str,
        messages: list,
        tools: Optional[list] = None,
        first_chunk_timeout: Optional[float] = None,
        timeout: Optional[float] = None,
    ) -> AsyncGenerator[dict, None]:
        """Get streaming response from the LLM.

        Args:
            provider: LLM provider name (e.g. "openai", "anthropic").
            model: Model name.
            messages: List of message dicts.
            tools: Optional list of tool definitions.
            first_chunk_timeout: Timeout for the first chunk (seconds).
            timeout: Overall timeout (seconds).

        Yields:
            Dicts with ``type`` ("content" / "tool_call" / "reasoning_content"
            / "finish") and ``data`` fields.
        """
        ...

    @abstractmethod
    def aggregate_message(
        self, content_chunks: list, tool_call_chunks: list
    ) -> Any:
        """Aggregate streamed chunks into a single LLMMessage.

        Args:
            content_chunks: List of content/reasoning chunk dicts.
            tool_call_chunks: List of tool_call chunk objects.

        Returns:
            ``LLMMessage`` instance, or ``None`` if no meaningful content.
        """
        ...
