"""
@Author: Rossi
Created At: 2021-05-04
"""

from importlib import import_module
import random
import os

from Broca.faq_engine.engine import FAQEngine
from Broca.message import UserMessage
from Broca.task_engine.engine import Engine
from .dispatching_agent import DispatchingAgent


class DialogueEngine:
    def __init__(self, external_process=None, interceptor=None):
        self.task_engine = None
        self.faq_engine = None
        self.external_process = external_process
        self.interceptor = interceptor
        self.dispatching_agent = None

    def handle_message(self, user_message):
        self.task_engine.parse(user_message)
        if self.interceptor is not None:
            responses = self.interceptor.handle_message(user_message)
            if responses is not None:
                return responses
        if self.task_engine.can_handle_message(user_message):
            return self.handel_message_with_engines(user_message)
        elif self.dispatching_agent.can_handle_message(user_message):
            return self._dispatch(user_message)
        else:
            return self.handel_message_with_engines(user_message)

    def _dispatch(self, user_message):
        return self.dispatching_agent.handle_message(user_message)

    def handel_message_with_engines(self, user_message):
        if self.task_engine is not None and self.task_engine.can_handle_message(user_message):
            return self.task_engine.handle_message(user_message)
        elif self.faq_engine is not None:
            result = self.faq_engine.handle_message(user_message)
            if "response" in result:
                return [result["response"]]
            elif "prompt" in result:
                return [result["prompt"]]
            elif self.task_engine is not None:
                responses = self.task_engine.force_prompt(user_message)
                if responses:
                    return responses
                elif random.random() < 0.5:
                    response = self.task_engine.prompt(user_message)
                    return [response]
                else:
                    response = self.faq_engine.prompt(user_message)
                    return [response]
            else:
                response = self.faq_engine.prompt(user_message)
                return [response]
        else:
            if self.external_process is not None and not user_message.is_external:
                response = self.external_process(user_message)
                if response is None:
                    response = self.task_engine.prompt(user_message)
            else:
                response = self.task_engine.prompt(user_message)
            return [response]

    def load_engines(self, package):
        if self._check_task_engine(package):
            config_file = os.path.join(package, "task_engine_config.json")
            self.task_engine = Engine.from_config_file(config_file)
            self.task_engine.load_agents(package)
            self.task_engine.collect_intent_patterns()
        if self._check_faq_engine(package):
            config_file = os.path.join(package, "faq_engine_config.json")
            self.faq_engine = FAQEngine.from_config_file(config_file)
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

    def load_dispatching_agent(self, package):
        agent_config_file = os.path.join(package, "dispatching_agent_config.json")
        dispatching_agent = DispatchingAgent.from_config_file(agent_config_file)
        script_module = package.replace("/", ".") + ".dispatching_script"
        script_module = import_module(script_module.lstrip("."))
        script = getattr(script_module, "script")
        dispatching_agent.set_script(script)
        skill_module = package.replace("/", ".") + ".dispatching_skills"
        dispatching_agent.load_skills(skill_module)
        dispatching_agent.set_dialogue_engine(self)
        self.dispatching_agent = dispatching_agent
