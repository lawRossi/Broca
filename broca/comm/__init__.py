"""
Broca Communication Module

This module provides multi-endpoint communication capabilities using Socket.io,
supporting browser, command-line, VSCode plugin, and browser plugin clients.
"""

from .message_types import MessageType, MessageSubType, MessageStatus, Message, MessageProtocol
from .socketio_server import SocketIOServer
from .socketio_client import SocketIOClient

__all__ = [
    'MessageType',
    'MessageSubType',
    'MessageStatus',
    'Message',
    'MessageProtocol',
    'SocketIOServer',
    'SocketIOClient',
]
