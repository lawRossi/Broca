"""
@Author: Rossi
Created At: 2020-12-13
"""
from collections import defaultdict
import re
import json


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

    @classmethod
    def from_pattern_string(cls, pattern_string):
        pattern = re.compile("^(?P<intent>([a-zA-Z\d_]+))(?P<parameters>\{.+\})?$")
        match = pattern.match(pattern_string)
        intent_name = match.group("intent")
        intent = {"name": intent_name}
        parsed_data = {"intent": intent}
        parameters = match.group("parameters")
        if parameters:
            parameters = json.loads(parameters)
            entities = defaultdict(list)
            for k, v in parameters.items():
                if isinstance(v, list):
                    entities[k].extend([{"type": k, "value": item} for item in v])
                entities[k].append({"type": k, "value": v})
            parsed_data["entities"] = entities
        message = cls(None, None)
        message.parsed_data = parsed_data
        return message


class BotMessage:
    def __init__(self, receiver_id, text, data=None):
        self.receiver_id = receiver_id
        self.text = text
        self.data = data

    def set(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)

    def to_dict(self):
        return {
            "receiver_id": self.receiver_id,
            "text": self.text,
            "data": self.data
        }
