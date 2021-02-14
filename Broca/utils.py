"""
@Author: Rossi
Created At: 2021-01-30
"""
import importlib
from elasticsearch_dsl import Document, Text, Keyword, Float, Integer, Date, Q
import datetime
import logging
import inspect


logger = logging.getLogger(__name__)


def find_class(class_path):
    module = class_path[:class_path.rfind(".")]
    class_name = class_path[class_path.rfind(".")+1:]
    ip_module = importlib.import_module(".", module)
    class_ = getattr(ip_module, class_name)
    return class_


def all_subclasses(cls):
    """Returns all known (imported) subclasses of a class."""

    return cls.__subclasses__() + [
        g for s in cls.__subclasses__() for g in all_subclasses(s)
    ]


def list_class(module):
    imported_module = importlib.import_module(".", module)
    for (_, cls) in inspect.getmembers(imported_module, inspect.isclass):
        yield cls


class Entity(Document):
    FIELD_SEP = ";"

    @classmethod
    def get_field(cls, field_name):
        doc_type = getattr(cls, "_doc_type")
        return doc_type.mapping[field_name]

    @classmethod
    def query_entity(cls, intent, slots, start=0, limit=100):
        kwargs = cls._collect_query_args(intent, slots)
        return cls._query_entity(intent, start, limit, **kwargs)
    
    @classmethod
    def _collect_query_args(cls, intent, slots):
        intent_slots = cls.intent_slots_mapping[intent]["slots"]
        kwargs = {}
        for slot in intent_slots:
            fields = cls.slot_fileds_mapping[slot]
            slot_value = slots[slot]
            if slot_value is None:
                default_values = cls.intent_slots_mapping[intent]["default_slot_values"]
                if default_values is not None:
                    default_value = default_values.get(slot, None)
                    slot_value = default_value() if hasattr(default_value, "__call__") else default_value
            if len(fields) == 1:
                kwargs[fields[0]] = slot_value
            else:
                kwargs[cls.FIELD_SEP.join(fields)] = slot_value
        return kwargs

    @classmethod
    def _query_entity(cls, intent, start=0, limit=100, **kwargs):
        s = cls.search()
        for field, value in kwargs.items():
            if value is None:
                continue
            if cls.FIELD_SEP not in field:
                query_type, sub_query = cls._get_sub_query(field, value)
                if query_type == "query":
                    s = s.query(sub_query)
                else:
                    s = s.filter(sub_query)
            else:
                sub_queries = [cls._get_sub_query(field_, value)[1] for field_ in field.split(cls.FIELD_SEP)]
                s = s.query("bool", should=sub_queries, minimum_should_match=1)
        sorting_fields = cls.intent_fields_mapping[intent]["sorting_fields"]
        if sorting_fields is not None:
            s = s.sort(*sorting_fields)
        s = s[start: start+limit]
        logger.debug(s.to_dict())
        s.execute()
        entities = [item for item in s]
        return entities

    @classmethod
    def _get_sub_query(cls, field, value):
        field_type = cls.get_field(field)
        if isinstance(field_type, Text):
            return ("query", Q("match_phrase", **{field: value}))
        elif isinstance(field_type, Keyword):
            if isinstance(value, list):
                return ("filter", Q("terms", **{field: value}))
            else:
                return ("filter", Q("term", **{field: value}))
        elif isinstance(field_type, (Integer, Float, Date)):
            if isinstance(field_type, Date):
                if isinstance(value, list):
                    value = [datetime.datetime.strptime(item, "%Y-%m-%d %H:%M:%S") if isinstance(item, str) else item for item in value]
                elif isinstance(value, str):
                    value = datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            if isinstance(value, list):
                if value[0] is not None and value[1] is not None:
                    return ("filter", Q("range", **{field: {"gte": value[0], "lte": value[1]}}))
                elif value[0] is not None:
                    return ("filter", Q("range", **{field: {"gte": value[0]}}))
                elif value[1] is not None:
                    return ("filter", Q("range", **{field: {"lte": value[1]}}))
            else:
                return ("filter", Q("term", **{field: value}))

    def get_attributes(self, intent):
        attrs = {}
        for field in self.intent_fields_mapping[intent]["fields"]:
            attrs[field] = getattr(self, field)
        return attrs
