from Broca.task_engine.event import Form, SkillEnded, SlotSetted
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


class PraiseSkill(Skill):
    def __init__(self):
        super().__init__()
        self.name = "praise"

    def _perform(self, tracker):
        confirmed = tracker.get_slot("confirmed_slot")
        if confirmed:
            self.utter("你真棒", tracker.sender_id)
        return []


class BookTicketSkill(FormSkill):
    def __init__(self):
        super().__init__()
        self.name = "book_form"
        self.trigger_intent = "book_ticket"
        self.intent_patterns = ["我要买电影票"]
        self.required_slots = OrderedDict({"movie": {"prefilled": True}})

    def slot_mappings(self):
        return {"movie": [self.from_text()]}

    def validate_movie(self, value, tracker):
        options = tracker.get_slot("options_slot")
        if options is None:
            self.events.append(SlotSetted("form_utterance", "你想看哪部电影？"))
            self._show_options_form(tracker, [{"value": "海王"}, {"value": "魔戒"}])
        option = tracker.get_slot("option_slot")
        if option is not None:
            self._hide_options_form(tracker)
            return option["value"]
        else:
            return None

    def utter_ask_movie(self, tracker):
        return None

    def _submit(self, tracker_snapshot):
        movie = tracker_snapshot["slots"].get("movie")
        self.utter(f"已为你预定{movie}的票", tracker_snapshot["sender_id"])
        return [SlotSetted("options_slot", None), SlotSetted("option_slot", None)]
