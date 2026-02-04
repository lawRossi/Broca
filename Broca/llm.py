import json
from pathlib import Path
import warnings

from litellm import completion
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

    def get_response(self, messages, tools=None, config_name="minimax"):
        response = completion(messages=messages, tools=tools, **self.config[config_name])
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
                    "required": ["code"]
                },
            }
        },
    ]

    client = LLMClient()
    messages = [
        {"role": "user", "content": "现在是什么时间"}
    ]
    # print(get_response(messages, "deepseek/deepseek-chat-v3.1:free"))
    message = client.get_response(messages, tools, "z-ai")
    print(message)
