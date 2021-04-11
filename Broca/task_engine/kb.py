from elasticsearch_dsl import Document, Text, Keyword, Float, Integer, Date, Q
import datetime
import logging


logger = logging.getLogger(__name__)


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
            if isinstance(value, list):
                return ("query", Q("match_phrase", **{field: value[0]}))
            else:
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


cached_entities = {}


def query_entity(sender_id, target_entity_cls, intent, slots, intent_templates_mapping):
    
    entities = target_entity_cls.query_entity(intent, slots)
    if len(entities) == 1:
        cached_entities[sender_id] = entities[0]
    datas = [entity.get_attributes(intent) for entity in entities]
    template = intent_templates_mapping[intent]
    response = template.render(slots=slots, datas=datas)
    return response


def query_entity_attributes(sender_id, intent, slots, intent_templates_mapping):
    entity = cached_entities.get(sender_id, None)
    attrs = None
    if entity is not None:
        attrs = entity.get_attributes(intent)
        print(attrs)
    template = intent_templates_mapping[intent]
    response = template.render(slots=slots, datas=attrs)
    return response
