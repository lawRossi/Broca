"""
@Author: Rossi
Created At: 2021-01-30
"""
import importlib
import inspect

from mako.template import Template


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


def load_templates(template_path=None):
    if template_path is None:
        template_path = "templates.md"
    templates_mapping = {}
    with open(template_path, encoding="utf-8") as fi:
        intent = None
        template = ""
        for line in fi:
            if not line.strip():
                continue
            elif line.startswith("##"):
                if intent is not None:
                    templates_mapping[intent] = Template(template)
                    template = ""
                intent = line[2:].strip()
            else:
                template += line
        if intent is not None:
            templates_mapping[intent] = Template(template)
        return templates_mapping
