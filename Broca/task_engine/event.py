"""
@Author: Rossi
Created At: 2021-01-30
"""


class Event:
    def __init__(self):
        self.backup = {}
    
    def apply(self, tracker):
        pass

    def undo(self, tracker):
        pass


class UserUttered(Event):
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


class BotUttered(Event):
    def __init__(self, bot_message) -> None:
        super().__init__()
        self.bot_message = bot_message


class SkillStarted(Event):
    pass


class SkillEnded(Event):
    def apply(self, tracker):
        tracker.update_states()
    
    def undo(self, tracker):
        tracker.pop_past_states()


class SlotSetted(Event):
    def __init__(self, slot, value):
        super().__init__()
        self.slot = slot
        self.value = value
    
    def apply(self, tracker):
        self.backup[self.slot] = tracker.get_slot(self.slot)
        tracker.set_slot(self.slot, self.value)
    
    def undo(self, tracker):
        tracker.set_slot(self.slot, self.backup[self.slot])


class Form(Event):
    def __init__(self, form):
        super().__init__()
        self.form = form
    
    def apply(self, tracker):
        self.backup["form"] = tracker.active_form
        tracker.active_form = self.form

    def undo(self, tracker):
        tracker.active_form = self.backup["form"]
