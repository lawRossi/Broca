"""
@Author: Rossi
Created At: 2021-02-21
"""

import json
import os

from .agent import FAQAgent


class FAQEngine:
    def __init__(self):
        self.agent = None

    @classmethod
    def from_config(cls, config):
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
