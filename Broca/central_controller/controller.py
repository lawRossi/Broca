from Broca.task_engine.engine import Engine
from Broca.faq_engine.engine import FAQEngine
from Broca.message import BotMessage, UserMessage
import os


class Controller:
    def __init__(self):
        self.task_engine = None
        self.faq_engine = None

    def handle_message(self, message):
        text = message.text
        if "  " in text:
            texts = text.split("  ")
            messages = [UserMessage(message.sender_id, text, message.channel) for text in texts]
            for message in messages:
                self._handle_single_message(message)
        else:
            self._handle_single_message(message)

    def _handle_single_message(self, message):
        channel = message.channel
        if self.task_engine is not None and self.task_engine.can_handle_message(message):
            responses = self.task_engine.handle_message(message)
            for response in responses:
                channel.send_message(response)
        else:
            result = self.faq_engine.handle_message(message)
            if "response" in result:
                channel.send_message(result["response"])
            elif "prompt" in result:
                channel.send_message(result["prompt"])
            elif self.task_engine is not None:
                response = self.task_engine.prompt(message)
                channel.send_message(response)
            else:
                response = BotMessage(message.sender_id, "没有找到相关问题")
                channel.send_message(response)

    def load_engines(self, package):
        if self._check_task_engine(package):
            self.task_engine = Engine.from_config_file("engine_config.json")
            self.task_engine.load_agents(package)
            self.task_engine.collect_intent_patterns()
        if self._check_faq_engine(package):
            self.faq_engine = FAQEngine.from_config_file("faq_engine_config.json")
            self.faq_engine.load_agents(package)

    def _check_task_engine(self, package):
        for dir in os.listdir(package):
            abs_dir = os.path.join(package, dir)
            if os.path.isdir(abs_dir):
                config_file = os.path.join(abs_dir, "agent_config.json")
                if os.path.exists(config_file):
                    return True

    def _check_faq_engine(self, package):
        for dir in os.listdir(package):
            abs_dir = os.path.join(package, dir)
            if os.path.isdir(abs_dir):
                config_file = os.path.join(abs_dir, "faq_agent_config.json")
                if os.path.exists(config_file):
                    return True
