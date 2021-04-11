"""
@Author: Rossi
Created At: 2021-02-13
"""
from importlib import import_module
from Broca.task_engine.agent import Agent
from Broca.message import BotMessage
from Broca.nlu.parser import RENaturalLanguageParser
from Broca.utils import find_class
import os
import json


class Engine:
    def __init__(self):
        self.parser_pipeline = None
        self.agents = []

    def add_agent(self, agent):
        self.agents.append(agent)
    
    def _prompt(self):
        prompt_triggers = [agent.prompt_trigger for agent in self.agents if agent.prompt_trigger is not None]
        return "不好意思，我不懂你的意思。\n请输入提示词看看我能做些什么:\n" + "\n".join(prompt_triggers)

    def handle_message(self, message, message_parsed=False):
        if not message_parsed:
            self.parser_pipeline.parse(message)

        for agent in self.agents:
            if agent.is_active(message.sender_id):
                agent.handle_message(message, message_parsed=False)
                return

        intent = message.get("intent")
        agent_name = intent.get("agent") if intent is not None else None
        if agent_name is not None:
            for agent in self.agents:
                if agent.name == agent_name and agent.can_handle_message(message):
                    agent.handle_message(message, message_parsed=True)
                    break 
        else:
            for agent in self.agents:
                if agent.can_handle_message(message):
                    agent.handle_message(message, message_parsed=True)
                    break 
            else:
                channel = message.channel
                prompt_message = self._prompt()
                bot_message = BotMessage(message.sender_id, prompt_message)
                channel.send_message(bot_message)

    def can_handle_message(self, message):
        self.parser_pipeline.parse(message)
        for agent in self.agents:
            if agent.can_handle_message(agent):
                return True
        return False

    def has_active_agent(self, message):
        for agent in self.agents:
            if agent.is_active(message.sender_id):
                return True
        return False

    def load_agents(self, package):
        for dir in os.listdir(package):
            abs_dir = os.path.join(package, dir)
            if os.path.isdir(abs_dir):
                config_file = os.path.join(abs_dir, "agent_config.json")
                script_file = os.path.join(abs_dir, "script.py")
                if os.path.exists(config_file) and os.path.exists(script_file):
                    agent = Agent.from_config_file(config_file)
                    if package != ".":
                        base_package = ".".join([package, dir])
                    else:
                        base_package = dir
                    script_module = import_module(f"{base_package}.script")
                    script = getattr(script_module, "script")
                    agent.set_script(script)
                    skill_module = f"{base_package}.skills"
                    agent.load_skills(skill_module)
                    self.add_agent(agent)

    def collect_intent_patterns(self):
        for parser in self.parser_pipeline.parsers:
            if isinstance(parser, RENaturalLanguageParser):
                for agent in self.agents:
                    for intent, patterns in agent.collect_intent_patterns():
                        parser.add_intent_patterns(intent, patterns)
                break
    
    @classmethod
    def from_config_file(cls, config_file):
        with open(config_file, encoding="utf-8") as fi:
            config = json.load(fi)
            return cls.from_config(config)

    @classmethod
    def from_config(cls, config):
        engine = cls()
        pipeline_config = config["parser_pipeline"]
        parser_pipeline_cls = find_class(pipeline_config["class"])
        parser_pipeline = parser_pipeline_cls.from_config(pipeline_config)
        engine.parser_pipeline = parser_pipeline
        return engine
