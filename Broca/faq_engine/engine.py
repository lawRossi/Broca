"""
@Author: Rossi
Created At: 2021-02-21
"""


import json


class FAQEngine:
    @classmethod
    def from_config(cls, config):
        es_index = config["es_index"]
        faiss_index_dir = config["faiss_index"]
        

    @classmethod
    def from_config_file(cls, config_file):
        with open(config_file, "w", encoding="utf-8") as fi:
            config = json.load(fi)
            return cls.from_config(config)

    def retrive(self, user_message):
        query = user_message.text
        return
