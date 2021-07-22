from Broca.task_engine.agent import Agent
from Broca.message import UserMessage
from Broca.channel import CollectingOutputChannel
from .test_skill import GreetSkill, GreetFormSkill
from .script import script
from Broca.task_engine.skill import DeactivateFormSkill, Skill


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


def read_scenes(script_file):
    scenes = []
    with open(script_file, encoding="utf-8") as fi:
        lines = fi.readlines()
        scene = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                scenes.append(scene)
                scene = []
                i += 1
            elif line.startswith("user:"):
                user_utterance = line[len("user:"):].strip()
                i += 1
                bot_utterances = []
                while i < len(lines):
                    line = lines[i].strip()
                    if line.startswith("bot:"):
                        bot_utterances.append(line[len("bot:"):].strip())
                        i += 1
                    else:
                        break
                scene.append((user_utterance, bot_utterances))
        if scene:
            scenes.append(scene)
    return scenes
