from os import environ
from Broca.task_engine.skill import Skill
from Broca.task_engine.event import BotUttered


class GreetSkill(Skill):
    def __init__(self):
        super().__init__()
        self.name = "greet"
        self.trigger_intent = "greet"
        self.intent_patterns = ["嘿", "hi"]

    def _perform(self, tracker):
        names = tracker.get_slot("name")
        if names:
            name = names[0]
        else:
            name = ""
        self.utter(f"你好呀{name}")
        return []


if __name__ == "__main__":
    skill = GreetSkill()
    events = skill.perform(None)
    assert(len(events)) == 3
    assert isinstance(events[1], BotUttered)
    print(skill.generate_script())
