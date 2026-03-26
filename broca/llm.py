import asyncio
import json
import warnings
from pathlib import Path
from typing import AsyncGenerator

from litellm import Message as LLMMessage
from litellm import acompletion
from loguru import logger


class FirstChunkTimeoutError(Exception):
    pass

warnings.filterwarnings("ignore")


class LLMClient:
    """LLM Client for making API calls to various providers"""

    def __init__(self):
        """Initialize LLM Client"""
        self.input_tokens_used = 0
        self.output_tokens_used = 0

        config_file = Path(__file__).parent.parent / "configs" / "llm_config.json"
        with open(config_file) as f:
            self.config = json.load(f)

    async def get_response(self, provider, model, messages, tools=None) -> LLMMessage:
        response = await acompletion(
            base_url=self.config[provider]["base_url"],
            api_key=self.config[provider]["api_key"],
            messages=messages,
            tools=tools,
            **self.config[provider][model],
        )
        logger.debug(
            f"LLM call - input tokens: {response.usage.prompt_tokens}, output tokens: {response.usage.completion_tokens}"
        )
        self.input_tokens_used = response.usage.prompt_tokens
        self.output_tokens_used = response.usage.completion_tokens

        return response.choices[0].message

    async def get_stream_response(
        self, provider, model, messages, tools=None, first_chunk_timeout=60
    ) -> AsyncGenerator[dict, None]:
        response = await acompletion(
            base_url=self.config[provider]["base_url"],
            api_key=self.config[provider]["api_key"],
            messages=messages,
            tools=tools,
            stream=True,
            stream_options={"include_usage": True},
            **self.config[provider][model],
        )

        iterator = response.__aiter__()
        first_chunk_task = asyncio.create_task(iterator.__anext__())

        try:
            first_chunk = await asyncio.wait_for(
                first_chunk_task, timeout=first_chunk_timeout
            )
            async for result in self._process_chunk(first_chunk):
                yield result
        except asyncio.TimeoutError:
            first_chunk_task.cancel()
            try:
                await first_chunk_task
            except asyncio.CancelledError:
                pass
            raise FirstChunkTimeoutError(
                f"First chunk timeout after {first_chunk_timeout} seconds"
            )

        async for chunk in iterator:
            async for result in self._process_chunk(chunk):
                yield result

    async def _process_chunk(self, chunk) -> AsyncGenerator[dict, None]:
        if hasattr(chunk, "usage") and chunk.usage:
            self.input_tokens_used = chunk.usage.prompt_tokens
            self.output_tokens_used = chunk.usage.completion_tokens

        if hasattr(chunk, "choices") and chunk.choices:
            choice = chunk.choices[0]
            if hasattr(choice, "delta") and choice.delta:
                delta = choice.delta
                if hasattr(delta, "content") and delta.content:
                    yield {"type": "content", "data": delta.content}
                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    yield {
                        "type": "reasoning_content",
                        "data": delta.reasoning_content,
                    }
                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    for tool_call in delta.tool_calls:
                        yield {"type": "tool_call", "data": tool_call}
            if hasattr(choice, "finish_reason") and choice.finish_reason:
                yield {"type": "finish", "data": choice.finish_reason}

    def aggregate_message(self, content_chunks, tool_call_chunks) -> LLMMessage:
        content = self.aggregate_content(content_chunks)
        tool_calls = self.aggregate_tool_calls(tool_call_chunks)
        return LLMMessage.parse_obj(
            {
                "role": "assistant",
                "content": content.get("content"),
                "tool_calls": tool_calls,
                "reasoning_content": content.get("reasoning_content"),
                "provider_specific_fields": {
                    "reasoning_content": content.get("reasoning_content")
                },
            }
        )

    def aggregate_content(self, content_chunks) -> dict:
        content = ""
        reasoning_content = ""
        for chunk in content_chunks:
            if chunk["type"] == "content":
                content += chunk["data"]
            elif chunk["type"] == "reasoning_content":
                reasoning_content += chunk["data"]
        return {"content": content, "reasoning_content": reasoning_content}

    def aggregate_tool_calls(self, tool_call_chunks) -> list[dict]:
        tool_calls: dict[int, dict] = {}

        for chunk in tool_call_chunks:
            if hasattr(chunk, "index"):
                index = chunk.index
                if index not in tool_calls:
                    tool_calls[index] = {
                        "id": None,
                        "type": "function",
                        "function": {"name": None, "arguments": ""},
                    }

                if hasattr(chunk, "id") and chunk.id:
                    tool_calls[index]["id"] = chunk.id
                if hasattr(chunk, "function") and chunk.function:
                    if hasattr(chunk.function, "name") and chunk.function.name:
                        tool_calls[index]["function"]["name"] = chunk.function.name
                    if (
                        hasattr(chunk.function, "arguments")
                        and chunk.function.arguments
                    ):
                        tool_calls[index]["function"]["arguments"] += (
                            chunk.function.arguments
                        )

        return list(tool_calls.values())
