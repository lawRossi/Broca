from Broca.faq_engine.engine import FAQEngine
from Broca.message import UserMessage


if __name__ == "__main__":
    engine = FAQEngine.from_config_file("tests/data/faq_engine_config.json")
    engine.load_agents("tests")
    result = engine.handle_message(UserMessage("sender", "你来自哪里"))
    print(result["response"].text)
