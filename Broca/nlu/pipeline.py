"""
@Author: Rossi
Created At: 2020-12-13
"""

from Broca.utils import find_class


class ParserPipeline:
    """the pipeline of natural language parsers.
    """

    def __init__(self) -> None:
        self.parsers = []

    def add_parser(self, parser):
        self.parsers.append(parser)

    def parse(self, message):
        """parse the message, the parsers in the pipeline will parse the message one by one

        Args:
            message (UserMessage): the message to be parsed
        """
        for parser in self.parsers:
            parser.parse(message)

    @classmethod
    def from_config(cls, config):
        pipeline = cls()
        for parser_config in config["parsers"]:
            parser_cls = find_class(parser_config["class"])
            pipeline.add_parser(parser_cls.from_config(parser_config))
        return pipeline
