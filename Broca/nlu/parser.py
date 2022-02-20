"""
@Author: Rossi
Created At: 2020-12-13
"""

from collections import defaultdict
import copy
import datetime
import json
from itertools import groupby
from operator import itemgetter
import re

import ahocorasick
import arrow
from time_extractor.extraction import TimeExtractor as Extractor


class NaturalLanguageParser:
    """base class parsers
    """

    def parse(self, message):
        """parse a user message

        Args:
            message (UserMessage): the user message to be parsed
        """
        if message.is_external:
            return
        self._parse(message)

    def _parse(self, message):
        pass

    @classmethod
    def from_config(cls, config):
        """Create a parser according to a configuration

        Args:
            config (dict): the configuration

        Returns:
            NaturalLangeParser: the parser created
        """ 
        return cls()


class RENaturalLanguageParser(NaturalLanguageParser):
    """Regular expression based nl parser. This parser will judge the intent
    of the user message and extract some specified entities from the message.
    """

    def __init__(self, intent_patterns) -> None:
        super().__init__()
        self.intent_patterns = intent_patterns

    def _parse(self, message):
        text = message.text
        for intent, patterns in self.intent_patterns:
            for pattern in patterns:
                m = pattern.match(text)
                if m is not None:
                    intent_name = intent["name"]
                    if intent["agent"] == "public":
                        intent_name = "public:" + intent_name
                    intent = {"name": intent_name, "agent": intent["agent"], "confidence": 1.0}
                    message.set("intent", intent)
                    entities = message.get("entities", defaultdict(list))
                    for k, v in m.groupdict().items():
                        if k[-1].isdigit():
                            k = k[:-1]
                        entities[k].append({"type": k, "value": v, "confidence": 1.0, "start": m.start(), "end": m.end()})
                    message.set("entities", entities)
                    break  # at most one pattern will apply

    @classmethod
    def from_config(cls, config):
        intent_file = config["intent_file"]
        with open(intent_file, encoding="utf-8") as fi:
            json_data = json.load(fi)
        intent_patterns = []
        for item in json_data:
            intent = item["intent"]
            patterns = [re.compile(pattern) for pattern in item["patterns"]]
            intent_patterns.append((intent, patterns))
        return cls(intent_patterns)

    def add_intent_patterns(self, intent, patterns):
        patterns = [re.compile(pattern) for pattern in patterns]
        self.intent_patterns.append((intent, patterns))


class LookupTableEntityExtractor(NaturalLanguageParser):
    def __init__(self, automaton):
        super().__init__()
        self.automaton = automaton
    
    def _parse(self, message) -> None:
        entities = message.get("entities", defaultdict(list))
        for entity in self._extract_entities(message.text):
            entities[entity["type"]].append(entity)
        message.set("entities", entities)

    def _extract_entities(self, text):
        entities = []
        covered = [0] * len(text)
        for pos, match in self._longest_match(self.automaton.iter(text)):
            if covered[pos] != 1:
                ne, type_ = match
                entities.append({
                    "type": type_,
                    "value": ne,
                    "start": pos,
                    "end": pos+len(ne),
                    "confidence": None,
                })
                for i in range(pos, pos+len(ne)):
                    covered[i] = 1
        return entities

    def _longest_match(self, matches):
        matches = [(match[0]-len(match[1][0])+1, match[1]) for match in matches]
        matches = sorted(matches, key=itemgetter(0))
        for _, match_set in groupby(matches, itemgetter(0)):
            yield max(match_set, key=lambda x: len(x[1][0]))

    @classmethod
    def from_config(cls, config):
        automaton = ahocorasick.Automaton()
        with open(config.get("lookup_table_file"), encoding="utf-8") as fi:
            for line in fi:
                ne, type_ = line.strip().split("\t")
                automaton.add_word(ne, (ne, type_))
        automaton.make_automaton()
        return cls(automaton)


class TimeExtractor(NaturalLanguageParser):
    def __init__(self) -> None:
        super().__init__()
        self.extractor = Extractor()

    def _parse(self, message) -> None:
        entities = message.get("entities", defaultdict(list))
        for entity in self._extract_time(message.text):
            entities[entity["type"]].append(entity)
        message.set("entities", entities)

    def _extract_time(self, text):
        entities = []
        for item in self.extractor.extract(text):
            if item is not None:
                type_, value = self.convert_time(item)
                entities.append({
                    "type": "time",
                    "time_type": type_,
                    "value": value,
                    "start": item.match.start(),
                    "end": item.match.end(),
                    "confidence": None,
                    "raw": item.time_str
                })
        return entities

    def convert_time(self, time):
        time = time.to_dict()
        if time["type"] == "Time":
            start, end = self._convert_time(time)
            if end is None:
                return "TimeStamp", start.strftime("%Y-%m-%d %H:%M:%S")
            else:
                return "TimeRange", [start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")]
        elif time["type"] == "TimeRange":
            start = time["start"]
            end = time["end"]
            start1, _ = self._convert_time(start)
            start2, end2 = self._convert_time(end)
            if end2 is not None:
                return "TimeRange", [start1.strftime("%Y-%m-%d %H:%M:%S"), end2.strftime("%Y-%m-%d %H:%M:%S")]
            else:
                return "TimeRange", [start1.strftime("%Y-%m-%d %H:%M:%S"), start2.strftime("%Y-%m-%d %H:%M:%S")]
        elif time["type"] == "TimeDelta":
            now = arrow.now()
            delta = copy.copy(time)
            del delta["type"]
            del delta["raw"]
            for k in list(delta.keys()):
                if delta[k] == 0:
                    del(delta[k])
            return "TimeStamp", now.shift(**delta).format("YYYY-MM-DD HH:mm:ss")
        elif time["type"] == "TimeCycle":
            del time["type"]
            return "TimeCycle", time

    def _convert_time(self, time):
        if time["month"] is None:
            start = datetime.datetime(time["year"], 1, 1)
            end = datetime.datetime(time["year"], 12, 31, 23, 59, 59)
            return (start, end)
        elif time["day"] is None:
            start = datetime.datetime(time["year"], time["month"], 1)
            last_day = self._get_last_day_of_month(time["year"], time["month"])
            end = datetime.datetime(time["year"], time["month"], last_day, 23, 59, 59)
            return (start, end)
        elif time["hour"] is None:
            start = datetime.datetime(time["year"], time["month"], time["day"])
            end = datetime.datetime(time["year"], time["month"], time["day"], 23, 59, 59)
            return (start, end)
        minute = time["minute"] or 0
        second = time["second"] or 0
        return datetime.datetime(time["year"], time["month"], time["day"], time["hour"], minute, second), None

    def _get_last_day_of_month(self, year, month):
        date = datetime.datetime(year, month, 28) + datetime.timedelta(days=4)
        last_day = date - datetime.timedelta(days=date.day)
        return last_day.day

    @classmethod
    def from_config(cls, config):
        return cls()


class EntitySynonymMapper(NaturalLanguageParser):
    def __init__(self, synonyms):
        self.synonyms = synonyms if synonyms else {}

    def _parse(self, message):
        entities = message.get("entities", [])
        self._replace_synonyms(entities)

    @classmethod
    def from_config(cls, config):
        file_name = config.get("synonym_file")
        if not file_name:
            synonyms = None
        with open(file_name, encoding="utf-8") as fi:
            synonyms = json.load(fi)
        return cls(synonyms)

    def _replace_synonyms(self, entities):
        for entity_type, entity_values in entities.items():
            if entity_type in self.synonyms:
                for entity in entity_values:
                    value = str(entity.get("value"))
                    if value in self.synonyms[entity_type]:
                        entity["value"] = self.synonyms[entity_type][value]
