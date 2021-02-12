"""
@Author: Rossi
Created At: 2021-01-30
"""
from Broca.utils import all_subclasses
import re
import json
from Broca.message import UserMessage


class Event:
    name = "event"

    def __init__(self):
        self.backup = {}
    
    def apply(self, tracker):
        pass

    def undo(self, tracker):
        pass

    @staticmethod
    def from_parameter_string(event_name, parameter_string):
        event_cls = Event.resolve_by_name(event_name)
        return event_cls.from_parameters(parameter_string)

    @staticmethod
    def resolve_by_name(event_name):
        for cls in all_subclasses(Event):
            if cls.name == event_name:
                return cls
        else:
            raise ValueError(f"Unknown event name '{event_name}'.")

    @classmethod
    def from_parameters(cls, parameter_string=None):
        return cls()


class UserUttered(Event):
    name = "user_uttered"

    LATEST_MESSAGE = "LATEST_MESSAGE"
    def __init__(self, user_message):
        super().__init__()
        self.message = user_message
    
    def apply(self, tracker):
        self.backup[self.LATEST_MESSAGE] = tracker.latest_message
        tracker.add_user_message(self.message)
        tracker.update_states()

    def undo(self, tracker):
        tracker.pop_user_message()
        tracker.pop_past_states()
        tracker.latest_message = self.backup[self.LATEST_MESSAGE]

    @classmethod
    def from_parameters(cls, parameter_string=None):
        message = UserMessage.from_pattern_string(parameter_string)
        return cls(message)


class BotUttered(Event):
    name = "bot_uttered"

    def __init__(self, bot_message) -> None:
        super().__init__()
        self.bot_message = bot_message


class SkillStarted(Event):
    name = "skill_started"


class SkillEnded(Event):
    name = "skill_ended"

    def __init__(self, skill_name):
        super().__init__()
        self.skill_name = skill_name

    def apply(self, tracker):
        self.backup["latest_skill"] = tracker.latest_skill
        tracker.latest_skill = self.skill_name
        tracker.update_states()

    def undo(self, tracker):
        tracker.latest_skill = self.backup["latest_skill"]
        tracker.pop_last_state()


class SlotSetted(Event):
    name = "slot"

    def __init__(self, slot, value):
        super().__init__()
        self.slot = slot
        self.value = value
    
    def apply(self, tracker):
        self.backup[self.slot] = tracker.get_slot(self.slot)
        tracker.set_slot(self.slot, self.value)
    
    def undo(self, tracker):
        tracker.set_slot(self.slot, self.backup[self.slot])
    
    @classmethod
    def from_parameters(cls, parameter_string=None):
        parameters = json.loads(parameter_string)
        events = []
        for k, v in parameters.items():
            events.append(cls(k, v))
        return events


class Form(Event):
    name = "form"

    def __init__(self, form):
        super().__init__()
        self.form = form
    
    def apply(self, tracker):
        self.backup["form"] = tracker.active_form
        tracker.active_form = self.form

    def undo(self, tracker):
        tracker.active_form = self.backup["form"]

    @classmethod
    def from_parameters(cls, parameter_string=None):
        parameters = json.loads(parameter_string)
        return cls(parameters["name"])
