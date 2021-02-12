"""
@Author: Rossi
Created At: 2021-01-30
"""
import importlib
from re import S


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
