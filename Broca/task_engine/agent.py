"""
@author: Rossi
@time: 2021-01-26
"""
from Broca.message import BotMessage
import json
from Broca.utils import find_class
from .event import UserUttered, BotUttered
from .skill import ListenSkill


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

    def set_script(self, script):
        self.script = script
        self.policy.parse_script(script, self)

    @classmethod
    def from_config(cls, config_file):
        with open(config_file, encoding="utf-8") as fi:
            config = json.load(fi)
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

    def handle_message(self, message):
        if self.parser:
            self.parser.parse(message)
        uttered = UserUttered(message)
        tracker = self.tracker_store.get_tracker(message.sender_id)
        tracker.update(uttered)
        self.listen(tracker)
        channel = message.channel
        skill_name = self.policy.pick_skill(tracker)
        if skill_name is not None:
            while skill_name is not None:
                skill = self.skills[skill_name]()
                for event in skill.perform(tracker):
                    tracker.update(event)
                    if isinstance(event, BotUttered):
                        bot_message = event.bot_message
                        channel.send_message(bot_message)
                skill_name = self.policy.pick_skill(tracker)
        else:
            bot_message = BotMessage("不好意思，我不懂你的意思")
            channel.send_message(bot_message)
        self.tracker_store.update_tracker(tracker)

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
