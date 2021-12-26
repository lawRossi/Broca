"""
@Author: Rossi
Created At: 2021-05-04
"""

import random
import os

from Broca.faq_engine.engine import FAQEngine
from Broca.message import BotMessage, UserMessage
from Broca.task_engine.engine import Engine


class Controller:
    def __init__(self, get_frequent_queries=None):
        self.task_engine = None
        self.faq_engine = None
        self.get_frequent_queries = get_frequent_queries

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
        elif self.faq_engine is not None:
            result = self.faq_engine.handle_message(message)
            if "response" in result:
                channel.send_message(result["response"])
            elif "prompt" in result:
                channel.send_message(result["prompt"])
            elif self.task_engine is not None and random.random() < 0.5:
                response = self.task_engine.prompt(message)
                channel.send_message(response)
            else:
                response = self._prompt(message)
                channel.send_message(response)
        else:
            response = self.task_engine.prompt(message)
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

    def _prompt(self, messae):
        text = "不要意思，我不懂你的意思。大家在问:\n"
        for query in self.get_frequent_queries():
            text += query + "\n"
        text = text.strip()
        response = BotMessage(messae.sender_id, text)
        return response
