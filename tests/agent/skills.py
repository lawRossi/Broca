from Broca.task_engine.skill import Skill, FormSkill
from collections import OrderedDict


class ReportDateSkill(Skill):
    def __init__(self):
        super().__init__()
        self.name = "report_date"
    
    def _perform(self, tracker):
        self.utter("今天是15号", tracker)


class ReportWeekdaySkill(Skill):
    def __init__(self):
        super().__init__()
        self.name = "report_weekday"

    def _perform(self, tracker):
        self.utter("今天是周五", tracker)


class ReportWeatherSkill(Skill):
    def __init__(self):
        super().__init__()
        self.name = "report_weather"

    def _perform(self, tracker, date=None):
        self.utter("今天天气很好", tracker)



class GreetSkill(Skill):
    def __init__(self):
        super().__init__()
        self.name = "greet"
        self.trigger_intent = "greet"
        self.intent_patterns = ["^嘿$", "hi"]

    def _perform(self, tracker):
        names = tracker.get_slot("name")
        if names:
            name = names[0]
        else:
            name = ""
        self.utter(f"你好呀{name}", tracker.sender_id)
        return []


class GreetFormSkill(FormSkill):
    def __init__(self):
        super().__init__()
        self.name = "greet_form"
        self.trigger_intent = "hey"
        self.intent_patterns = ["你好"]
        self.required_slots = OrderedDict({"name": {"prefilled": True}, "age": {"prefilled": False}})

    def slot_mappings(self):
        return {"name": [self.from_entity("name")], "age": [self.from_entity("age")]}
    
    def utter_ask_name(self, tracker):
        return "请问你叫什么名字？"

    def utter_ask_age(self, tracker):
        return "请问你多少岁了?"
    
    def _submit(self, tracker_snapshot):
        name = tracker_snapshot["slots"]["name"][0]
        age = tracker_snapshot["slots"]["age"][0]
        self.utter(f"你好呀，{name}，你{age}岁了呀", tracker_snapshot["sender_id"])
        return []
