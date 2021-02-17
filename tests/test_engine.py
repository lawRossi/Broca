from Broca.task_engine.engine import Engine


if __name__ == "__main__":
    engine = Engine.from_config_file("tests/data/engine_config.json")
    engine.load_agents("tests")
    assert len(engine.agents) == 1
    agent = engine.agents[0]
    assert len(agent.skills) == 5
    engine.collect_intent_patterns()
