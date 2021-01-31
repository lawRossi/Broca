"""
@Author: Rossi
Created At: 2020-12-13
"""


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
