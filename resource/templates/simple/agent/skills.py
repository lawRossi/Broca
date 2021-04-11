from Broca.task_engine.skill import Skill


class HelpSkill(Skill):
    def __init__(self):
        super().__init__()
        self.name = "help_skill"
        self.trigger_intent = "help"
        self.intent_patterns = []

    def _perform(self, tracker):
        help_message = ""
        self.utter(help_message, tracker.sender_id)
        return []
