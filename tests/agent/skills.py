import time

from Broca.task_engine.event import Scene, SlotSetted
from Broca.task_engine.skill import FormSkill, OptionSkill, ReplySkill, Skill


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
        required_slots = [
            {"name": "name", "mapping": [self.from_entity("name")], "utterance": "请问你叫什么名字？"},
            {"name": "age", "mapping": [self.from_entity("age")], "utterance": "请问你多少岁了?"}
        ]
        super().__init__(required_slots)
        self.name = "greet_form"
        self.trigger_intent = "hey"
        self.intent_patterns = ["你好"]

    def _submit(self, tracker_snapshot):
        name = tracker_snapshot["slots"]["name"][0]
        age = tracker_snapshot["slots"]["age"][0]
        self.utter(f"你好呀，{name}，你{age}岁了呀", tracker_snapshot["sender_id"])
        return []


class BookTicketSkill(OptionSkill):
    def __init__(self):
        options = [{"value": "海王", "text": "海王"}, {"value": "魔戒", "text": "魔戒"}]
        required_slots = [
            {
                "name": "movie",
                "options": options,
                "utterance": "你想看哪部电影？"
            }
        ]
        super().__init__(required_slots)
        self.name = "book_form"
        self.trigger_intent = "book_ticket"
        self.intent_patterns = ["我要买电影票"]

    def _submit(self, tracker_snapshot):
        movie = tracker_snapshot["slots"].get("movie")["text"]
        self.utter(f"已为你预定{movie}的票", tracker_snapshot["sender_id"])
        return [SlotSetted("movie", None)]


class ForceSkill(ReplySkill):
    def __init__(self):
        super().__init__()
        self.name = "force_skill"
        self.template = "一定要买"


class TestSceneSkill(Skill):
    def __init__(self):
        super().__init__()
        self.name = "test_scene"
        self.trigger_intent = "test_scene"
        self.intent_patterns = ["^测试场景$"]

    def _perform(self, tracker):
        message = tracker.latest_message
        intent = message.get("intent")
        if intent and intent["name"] == "test_scene":
            self.utter("已进入场景测试", tracker.sender_id)
            return [Scene(self.name, time.time() + 3)]
        elif message.text == "退出":
            self.utter("已退出场景测试", tracker.sender_id)
            return [Scene(None, None)]
        else:
            self.utter("在测试场景呢", tracker.sender_id)
            return [Scene(self.name, time.time() + 3)]
