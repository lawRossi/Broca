"""
@Author: Rossi
Created At: 2021-01-30
"""

class MessageChannel:
    def send_message(self, bot_message):
        pass


class CollectingOutputChannel(MessageChannel):
    def __init__(self) -> None:
        super().__init__()
        self.messages = []

    def send_message(self, bot_message):
        self.messages.append(bot_message)
