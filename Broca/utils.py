"""
@Author: Rossi
Created At: 2021-01-30
"""
import importlib


def find_class(class_path):
    module = class_path[:class_path.rfind(".")]
    class_name = class_path[class_path.rfind(".")+1:]
    ip_module = importlib.import_module(".", module)
    class_ = getattr(ip_module, class_name)
    return class_
