"""
Broca Communication Module

This module provides multi-endpoint communication capabilities using Socket.io,
supporting browser, command-line, VSCode plugin, and browser plugin clients.
"""

from .socketio_client import SocketIOClient
from .socketio_server import SocketIOServer

__all__ = [
    "SocketIOServer",
    "SocketIOClient",
]
