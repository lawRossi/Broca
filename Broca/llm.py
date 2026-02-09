import json
import warnings
from pathlib import Path

from litellm import Message, acompletion
from loguru import logger

warnings.filterwarnings("ignore")


class LLMClient:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LLMClient, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self.input_tokens_used = 0
            self.output_tokens_used = 0
            config_file = Path(__file__).parent.parent / "configs" / "llm_config.json"
            with open(config_file) as f:
                self.config = json.load(f)

    async def get_response(
        self, messages, tools=None, config_name="minimax"
    ) -> Message:
        response = await acompletion(
            messages=messages, tools=tools, **self.config[config_name]
        )
        logger.debug(
            f"LLM call - input tokens: {response.usage.prompt_tokens}, output tokens: {response.usage.completion_tokens}"
        )
        self.input_tokens_used += response.usage.prompt_tokens
        self.output_tokens_used += response.usage.completion_tokens

        logger.debug(
            f"LLM call - total input tokens: {self.input_tokens_used}, total output tokens: {self.output_tokens_used}"
        )

        return response.choices[0].message


if __name__ == "__main__":
    tools = [
        {
            "type": "function",
            "function": {
                "name": "execute_code",
                "description": "Use this tool to execute code using shell. You can get system time or read files by executing code.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "the code to run",
                        }
                    },
                    "required": ["code"],
                },
            },
        },
    ]

    client = LLMClient()
    messages = [{"role": "user", "content": "现在是什么时间"}]

    # async def test():
    #     message = await client.get_response(messages, tools, "deepseek")
    #     with open("message.json", "w", encoding="utf-8") as f:
    #         json.dump(message.json(), f, ensure_ascii=False, indent=2)
    # import asyncio
    # asyncio.run(test())

    with open("message.json") as fi:
        message_data = json.load(fi)

    from litellm import Message

    message = Message.parse_obj(message_data)
    print(message)
