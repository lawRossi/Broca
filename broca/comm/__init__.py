"""
Broca Communication Module

This module provides multi-endpoint communication capabilities using Socket.io,
supporting browser, command-line, VSCode plugin, and browser plugin clients.
"""

from .message_types import MessageType, Message, MessageProtocol
from .socketio_server import SocketIOServer
from .socketio_client import SocketIOClient

__all__ = [
    'MessageType',
    'Message',
    'MessageProtocol',
    'SocketIOServer',
    'SocketIOClient',
]
