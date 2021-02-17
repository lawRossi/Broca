from Broca.task_engine.skill import Skill


class ReportDateSkill(Skill):
    def __init__(self):
        super().__init__()
        self.trigger_intent = "ask"
        self.name = "report_date"
    
    def _perform(self, tracker):
        self.utter("今天是15号", tracker.sender_id)


class ReportWeekdaySkill(Skill):
    def __init__(self):
        super().__init__()
        self.name = "report_weekday"

    def _perform(self, tracker):
        self.utter("今天是周五", tracker.sender_id)


class ReportWeatherSkill(Skill):
    def __init__(self):
        super().__init__()
        self.name = "report_weather"

    def _perform(self, tracker, date=None):
        self.utter("今天天气很好", tracker.sender_id)
