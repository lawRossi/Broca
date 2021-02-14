"""
@author: Rossi
@time: 2021-01-26
"""
from Broca.message import BotMessage
import json
from Broca.utils import find_class, list_class
from .event import UserUttered, BotUttered
from .skill import FormSkill, ListenSkill, Skill, UndoSkill, DeactivateFormSkill
import re


class Agent:
    def __init__(self, name, parser, tracker_store, policy, intents, slots):
        self.name = name
        self.parser = parser
        tracker_store.agent = self
        self.tracker_store = tracker_store
        self.policy = policy
        self.intents = intents
        self.skills = {}
        self.slots = slots
        self.skill_pattern = re.compile("(?P<name>[a-zA-Z_0-9]+)?(:(?P<parameters>\{.+\})$)?")

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
        return cls(agent_name, parser, tracker_store, policy, intents, slots)

    def can_handle_message(self, message):
        if self.parser:
            self.parser.parse(message)
        uttered = UserUttered(message)
        tracker = self.tracker_store.get_tracker(message.sender_id)
        temp_tracker = tracker.copy()
        temp_tracker.update(uttered)
        self.listen(temp_tracker)
        skill_name = self.policy.pick_skill(temp_tracker)
        return skill_name is not None

    def handle_message(self, message, message_parsed=False):
        if self.parser and not message_parsed:
            self.parser.parse(message)
        uttered = UserUttered(message)
        tracker = self.tracker_store.get_tracker(message.sender_id)
        tracker.update(uttered)
        self.listen(tracker)
        channel = message.channel
        skill_name = self.policy.pick_skill(tracker)
        if skill_name is not None:
            while skill_name is not None:
                skill_name, parameters = self._parse_skill_name(skill_name)
                skill = self.skills[skill_name]()
                for event in skill.perform(tracker, **parameters):
                    tracker.update(event)
                    if isinstance(event, BotUttered):
                        bot_message = event.bot_message
                        channel.send_message(bot_message)
                skill_name = self.policy.pick_skill(tracker)
        else:
            bot_message = BotMessage(message.sender_id, "不好意思，我不懂你的意思")
            channel.send_message(bot_message)
        self.tracker_store.update_tracker(tracker)

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
        return tracker.active_form is not None

    def load_skills(self, skill_module):
        for cls in list_class(skill_module):
            if issubclass(cls, Skill) and cls not in [Skill, FormSkill]:
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
