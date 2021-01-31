"""
@Author: Rossi
Created At: 2020-12-13
"""

class UserMessage:
    def __init__(self, sender_id, text, channel=None):
        self.sender_id = sender_id
        self.text = text
        self.channel = channel
        self.parsed_data = {}
    
    def set(self, key, value):
        self.parsed_data[key] = value
    
    def get(self, key, default=None):
        return self.parsed_data.get(key, default)

    def to_dict(self):
        return {
            "sender_id": self.sender_id,
            "text": self.text,
            "parsed_data": self.parsed_data
        }


class BotMessage:
    def __init__(self, text, data=None):
        self.text = text
        self.data = data
    
    def set(self, key, value):
        self.data[key] = value
    
    def get(self, key, default=None):
        return self.data.get(key, default)

    def to_dict(self):
        return {
            "text": self.text,
            "data": self.data
        }
