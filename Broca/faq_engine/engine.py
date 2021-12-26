"""
@Author: Rossi
Created At: 2021-02-21
"""

import json
import os

from Broca.utils import find_class

from .agent import FAQAgent
from Broca.message import BotMessage


class FAQEngine:
    def __init__(self):
        self.agent = None
        self.frequent_query_retriever = None

    @classmethod
    def from_config(cls, config):
        engine = cls()
        retriever_config = config.get("retriever_config")
        if retriever_config is not None:
            retriever_cls = find_class(retriever_config["class"])
            engine.frequent_query_retriever = retriever_cls.from_config(retriever_config)
        return cls()

    @classmethod
    def from_config_file(cls, config_file):
        with open(config_file, encoding="utf-8") as fi:
            config = json.load(fi)
            return cls.from_config(config)

    def handle_message(self, user_message):
        return self.agent.handle_message(user_message)

    def load_agents(self, package):
        for dir in os.listdir(package):
            abs_dir = os.path.join(package, dir)
            if os.path.isdir(abs_dir):
                config_file = os.path.join(abs_dir, "faq_agent_config.json")
                if os.path.exists(config_file):
                    agent = FAQAgent.from_config_file(config_file)
                    self.agent = agent

    def prompt(self, messae):
        text = "抱歉，找不到相关信息。"
        if self.frequent_query_retriever is not None:
            frequent_quries = self.get_frequent_queries()
            if frequent_quries:
                text + "\n大家都在问:\n"
                for query in frequent_quries:
                    text += query + "\n"
        text = text.strip()
        response = BotMessage(messae.sender_id, text)
        return response
