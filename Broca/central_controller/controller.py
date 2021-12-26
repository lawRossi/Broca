"""
@Author: Rossi
Created At: 2021-05-04
"""

import random
import os

from Broca.faq_engine.engine import FAQEngine
from Broca.message import UserMessage
from Broca.task_engine.engine import Engine


class Controller:
    def __init__(self):
        self.task_engine = None
        self.faq_engine = None

    def handle_message(self, user_message):
        text = user_message.text
        if "  " in text:
            texts = text.split("  ")
            user_messages = [UserMessage(user_message.sender_id, text, user_message.channel) for text in texts]
            for user_message in user_messages:
                self._handle_single_message(user_message)
        else:
            self._handle_single_message(user_message)

    def _handle_single_message(self, user_message):
        channel = user_message.channel
        if self.task_engine is not None and self.task_engine.can_handle_message(user_message):
            responses = self.task_engine.handle_message(user_message)
            for response in responses:
                channel.send_message(response)
        elif self.faq_engine is not None:
            result = self.faq_engine.handle_message(user_message)
            if "response" in result:
                channel.send_message(result["response"])
            elif "prompt" in result:
                channel.send_message(result["prompt"])
            elif self.task_engine is not None:
                response = self.task_engine.force_prompt(user_message)
                if response is not None:
                    channel.send_message(response)
                elif random.random() < 0.5:
                    response = self.task_engine.prompt(user_message)
                    channel.send_message(response)
            else:
                response = self.faq_engine.prompt(user_message)
                channel.send_message(response)
        else:
            response = self.task_engine.prompt(user_message)
            channel.send_message(response)

    def load_engines(self, package):
        if self._check_task_engine(package):
            self.task_engine = Engine.from_config_file("task_engine_config.json")
            self.task_engine.load_agents(package)
            self.task_engine.collect_intent_patterns()
        if self._check_faq_engine(package):
            self.faq_engine = FAQEngine.from_config_file("faq_engine_config.json")
            self.faq_engine.load_agents(package)

    def _check_task_engine(self, package):
        config_file = os.path.join(package, "task_engine_config.json")
        if os.path.exists(config_file):
            return True
        return False

    def _check_faq_engine(self, package):
        config_file = os.path.join(package, "faq_engine_config.json")
        if os.path.exists(config_file):
            return True
        return False
