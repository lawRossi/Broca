from Broca.task_engine.skill import Skill, FormSkill
from Broca.task_engine.event import BotUttered, UserUttered
from Broca.task_engine.agent import Agent
from Broca.task_engine.tracker import DialogueStateTracker
from Broca.message import UserMessage


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


class GreetFormSkill(FormSkill):
    def __init__(self):
        super().__init__()
        self.name = "greet_form"
        self.trigger_intent = "greet"
        self.intent_patterns = ["你好"]
        self.required_slots = {"name": {"prefilled": True}, "age": {"prefilled": True}}

    def slot_mappings(self):
        return {"name": [self.from_entity("name")], "age": [self.from_entity("age")]}
    
    def utter_ask_name(self, tracker):
        return "请问你叫什么名字？"

    def utter_ask_age(self, tracker):
        return "请问你多少岁了?"
    
    def _submit(self, tracker_snapshot):
        name = tracker_snapshot["slots"]["name"][0]
        age = tracker_snapshot["slots"]["age"][0]
        self.utter(f"你好呀，{name}，你{age}岁了呀")
        return []

 
if __name__ == "__main__":
    # skill = GreetSkill()
    # events = skill.perform(None)
    # assert(len(events)) == 3
    # assert isinstance(events[1], BotUttered)
    # print(skill.generate_script())

    agent = Agent.from_config("tests/data/agent_config.json")
    tracker = DialogueStateTracker("", agent)
    agent.add_skill(GreetFormSkill)

    message = UserMessage("", "嘿")
    agent.parser.parse(message)
    event = UserUttered(message)
    tracker.update(event)

    skill = GreetFormSkill()
    events = skill.perform(tracker)
    for event in events:
        tracker.update(event)
    for event in events:
        if isinstance(event, BotUttered):
            print(event.bot_message.text)
    
    message = UserMessage("", "我是罗西")
    agent.parser.parse(message)
    event = UserUttered(message)
    tracker.update(event)

    skill = GreetFormSkill()
    events = skill.perform(tracker)
    for event in events:
        tracker.update(event)

    for event in events:
        if isinstance(event, BotUttered):
            print(event.bot_message.text)

    message = UserMessage("", "我29岁")
    agent.parser.parse(message)
    event = UserUttered(message)
    tracker.update(event)

    skill = GreetFormSkill()
    events = skill.perform(tracker)
    for event in events:
        tracker.update(event)

    for event in events:
        if isinstance(event, BotUttered):
            print(event.bot_message.text)
