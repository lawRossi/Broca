from Broca.task_engine.event import Event, Form, SlotSetted, UserUttered


if __name__ == "__main__":
    event = Event.from_parameter_string("user_uttered", 'greet{"name": "罗西"}')
    assert isinstance(event, UserUttered)
    message = event.message
    assert message.get("intent")["name"] == "greet"
    entities = message.get("entities")
    assert len(entities.get("name")) == 1
    assert entities.get("name")[0]["value"] == "罗西"

    events = Event.from_parameter_string("slot", '{"name": "罗西"}')
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, SlotSetted)
    assert event.slot == "name"
    assert event.value == "罗西"

    event = Event.from_parameter_string("form", '{"name": "greet_form"}')
    assert isinstance(event, Form)
    assert event.form == "greet_form"
