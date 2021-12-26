"""
@Author: Rossi
Created At: 2021-02-13
"""

from importlib import import_module
import json
import os

from Broca.message import BotMessage, UserMessage
from Broca.nlu.parser import RENaturalLanguageParser
from Broca.task_engine.agent import Agent
from Broca.utils import find_class


class Engine:
    def __init__(self, parser_pipeline, dispatcher=None, prompter_dispatcher=None):
        self.parser_pipeline = parser_pipeline
        self.dispatcher = dispatcher
        self.prompter_dispatcher = prompter_dispatcher
        self.agents = []

    def add_agent(self, agent):
        self.agents.append(agent)

    def prompt(self, user_message):
        prompt_message = "不好意思，我不懂你的意思。"
        prompt_triggers = [agent.prompt_trigger for agent in self.agents if agent.prompt_trigger is not None]
        if prompt_triggers:
            prompt_message += "\n请输入提示词看看我能做些什么:\n" + "\n".join(prompt_triggers)
        response = BotMessage(user_message.sender_id, prompt_message)
        return response

    def force_prompt(self, user_message):
        if self.prompter_dispatcher is None:
            return None
        agent = self.prompter_dispatcher.dispatch(self.agents, user_message)
        if agent is not None:
            return agent.handle_message(user_message)
        return None

    def handle_message(self, message):
        self._parse_if_needed(message)
        agent = message.get("agent")
        if agent is None:  # the message has not been dispatched
            agent = self.dispatcher.dispatch(self.agents, message)
        if agent is not None:
            return agent.handle_message(message)
        return []

    def can_handle_message(self, message):
        self._parse_if_needed(message)
        agent = self.dispatcher.dispatch(self.agents, message)
        if agent is not None:
            message.set("agent", agent)
            return True
        return False

    def _parse_if_needed(self, message):
        processed_by = message.get("processed_by")
        if processed_by is None:
            processed_by = set()
            message.set("processed_by", processed_by)
        if "task_engine" in processed_by:
            return
        self.parser_pipeline.parse(message)
        processed_by.add("task_engine")

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
        pipeline_config = config["parser_pipeline"]
        parser_pipeline_cls = find_class(pipeline_config["class"])
        parser_pipeline = parser_pipeline_cls.from_config(pipeline_config)
        dispatcher_config = config.get("dispatcher")
        if dispatcher_config:
            dispatcher_cls = find_class(dispatcher_config["class"])
            dispatcher = dispatcher_cls.from_config(dispatcher_config)
        else:
            dispatcher = None
        dispatcher_config = config.get("prompter_dispatcher")
        if dispatcher_config:
            dispatcher_cls = find_class(dispatcher_config["class"])
            prompter_dispatcher = dispatcher_cls.from_config(dispatcher_config)
        else:
            prompter_dispatcher = None
        return cls(parser_pipeline, dispatcher, prompter_dispatcher)
