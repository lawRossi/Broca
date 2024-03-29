"""
@author: Rossi
@time: 2021-01-26
"""

import json
import re

from Broca.message import UserMessage
from Broca.utils import find_class, list_class
from .event import AgentTriggered, UserUttered, BotUttered
from .skill import DeactivateFormSkill, FormSkill, ListenSkill
from .skill import OptionSkill, ReplySkill, Skill, UndoSkill


class Agent:
    skill_pattern = re.compile("(?P<name>[a-zA-Z_0-9]+)?(:(?P<parameters>\{.+\})$)?")

    def __init__(self, name, parser, tracker_store, policy, intents, slots, prompt_trigger=None):
        self.name = name
        self.parser = parser
        tracker_store.agent = self
        self.tracker_store = tracker_store
        self.policy = policy
        self.intents = intents
        self.skills = {}
        self.slots = slots
        self.prompt_trigger = prompt_trigger

    def set_script(self, script):
        self.script = script
        self.policy.parse_script(script, self)

    @classmethod
    def from_config_file(cls, config_file):
        with open(config_file, encoding="utf-8") as fi:
            config = json.load(fi)
            return cls.from_config(config)

    @classmethod
    def from_config(cls, config):
        parser_config = config.get("parser")
        if parser_config:
            parser_cls = find_class(parser_config["class"])
            parser = parser_cls.from_config(parser_config)
        else:
            parser = None
        tracker_store_config = config["tracker_store"]
        tracker_store_cls = find_class(tracker_store_config["class"])
        tracker_store = tracker_store_cls.from_config(tracker_store_config)
        policy_config = config["policy"]
        policy_cls = find_class(policy_config["class"])
        policy = policy_cls.from_config(policy_config)
        agent_name = config["agent_name"]
        intents = config["intents"]
        slots = []
        for slot_config in config["slots"]:
            slot_cls = find_class(slot_config["class"])
            slots.append(slot_cls.from_config(slot_config))
        prompt_trigger = config.get("prompt_trigger", None)
        return cls(agent_name, parser, tracker_store, policy, intents, slots, prompt_trigger)

    def can_handle_message(self, message):
        self._parse_if_needed(message)
        uttered = UserUttered(message)
        tracker = self.tracker_store.get_tracker(message.sender_id)
        temp_tracker = tracker.copy()
        temp_tracker.update(uttered)
        self.listen(temp_tracker)
        skill_name = self.policy.pick_skill(temp_tracker)
        return skill_name is not None

    def handle_message(self, message):
        self._parse_if_needed(message)
        uttered = UserUttered(message)
        tracker = self.tracker_store.get_tracker(message.sender_id)
        tracker.update(uttered)
        self.listen(tracker)
        skill_name = self.policy.pick_skill(tracker)
        triggered_event = None
        responses = []
        if skill_name is not None:
            skills = []
            while skill_name is not None:
                skills.append(skill_name)
                skill_name, parameters = self._parse_skill_name(skill_name)
                skill = self.skills[skill_name]()
                for event in skill.perform(tracker, **parameters):
                    tracker.update(event)
                    if isinstance(event, BotUttered):
                        bot_message = event.bot_message
                        responses.append(bot_message)
                    elif isinstance(event, AgentTriggered):
                        triggered_event = event
                skill_name = self.policy.pick_skill(tracker)
            message.set("skills", skills)

        elif "help_skill" in self.skills:  # perform help skill
            help_skill = self.skills["help_skill"]()
            for event in help_skill.perform(tracker):
                tracker.update(event)
                if isinstance(event, BotUttered):
                    bot_message = event.bot_message
                    responses.append(bot_message)
            message.set("skills", ["help_kill"])

        self.tracker_store.update_tracker(tracker)

        if triggered_event is not None:
            new_message = UserMessage(
                message.sender_id,
                triggered_event.text,
                external_intent=triggered_event.intent,
                external_entities=triggered_event.entities
            )
            responses.extend(self.handle_message(new_message))
            message.parsed_data.update(new_message.parsed_data)

        return responses

    def parse(self, message):
        self._parse_if_needed(message)

    def _parse_if_needed(self, message):
        processed_by = message.get("processed_by")
        if processed_by is None:
            processed_by = set()
            message.set("processed_by", processed_by)
        if self.name in processed_by:
            return
        if self.parser is not None:
            self.parser.parse(message)
        processed_by.add(self.name)

    def _parse_skill_name(self, skill_name):
        match = self.skill_pattern.match(skill_name)
        if not match:
            raise RuntimeError("invalid skill name")
        else:
            skill_name = match.group("name")
            parameters = match.group("parameters")
            if parameters:
                parameters = json.loads(parameters)
            else:
                parameters = {}
            return skill_name, parameters

    def add_skill(self, skill_cls):
        skill = skill_cls()
        self.skills[skill.name] = skill_cls
        if skill.trigger_intent:
            mappings = self.script.get("mappings")
            script = skill.generate_script()
            mappings.update(script)
            self.intents[skill.trigger_intent] = {"name": skill.trigger_intent, "use_entities": []}

    def listen(self, tracker):
        events = ListenSkill().perform(tracker)
        for event in events:
            tracker.update(event)

    def is_active(self, sender_id):
        tracker = self.tracker_store.get_tracker(sender_id)
        return tracker.active_form is not None or tracker.active_scene is not None

    def load_skills(self, skill_module):
        for cls in list_class(skill_module):
            if issubclass(cls, Skill) and cls not in \
                    [Skill, FormSkill, ReplySkill, OptionSkill]:
                self.add_skill(cls)
        self.add_skill(UndoSkill)
        self.add_skill(DeactivateFormSkill)

    def collect_intent_patterns(self):
        intent_patterns = []
        for skill_cls in self.skills.values():
            skill = skill_cls()
            if skill.trigger_intent and skill.intent_patterns:
                intent = {"name": skill.trigger_intent, "agent": self.name}
                intent_patterns.append((intent, skill.intent_patterns))
        return intent_patterns
