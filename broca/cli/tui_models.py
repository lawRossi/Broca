"""
TUI Data Models (简化版本)

包含TUI应用程序的数据结构：
- MessageBuffer: 线程安全的消息缓冲区
- StatusIndicator: 连接状态指示器
- MessageDisplayAdapter: 消息显示适配器
"""

import asyncio
from typing import Any, List, Optional

from broca.session.models import Message


class MessageBuffer:
    """
    线程安全的消息缓冲区

    现在直接存储Message对象
    """

    def __init__(self, max_size: int = 1000):
        self._messages: List[Message] = []
        self._max_size = max_size
        self._lock = asyncio.Lock()

    async def add_message(self, message: Message):
        """添加消息到缓冲区"""
        async with self._lock:
            if len(self._messages) >= self._max_size:
                self._messages.pop(0)
            self._messages.append(message)

    async def get_messages(self) -> List[Message]:
        """获取所有消息"""
        async with self._lock:
            return self._messages.copy()

    async def clear(self):
        """清空缓冲区"""
        async with self._lock:
            self._messages.clear()

    def __len__(self):
        return len(self._messages)


class StatusIndicator:
    """连接状态指示器"""

    def __init__(self):
        # 服务器连接状态
        self.connected = False
        self.connecting = False
        self.session_id: Optional[str] = None
        self.server_url: Optional[str] = None

        # Agent连接状态
        self.agent_connected = False
        self.agent_connecting = False
        self.agent_running = False
        self.agent_id: Optional[str] = None

    def set_connecting(self):
        """设置服务器连接为连接中"""
        self.connecting = True
        self.connected = False

    def set_connected(self, session_id: str, server_url: str):
        """设置服务器连接为已连接"""
        self.connecting = False
        self.connected = True
        self.session_id = session_id
        self.server_url = server_url

    def set_disconnected(self):
        """设置服务器连接为断开"""
        self.connecting = False
        self.connected = False
        self.session_id = None

    def set_agent_connecting(self):
        """设置Agent连接为连接中"""
        self.agent_connecting = True
        self.agent_connected = False

    def set_agent_connected(self, agent_id: str):
        """设置Agent连接为已连接"""
        self.agent_connecting = False
        self.agent_connected = True
        self.agent_running = False
        self.agent_id = agent_id

    def set_agent_disconnected(self):
        """设置Agent连接为断开"""
        self.agent_connecting = False
        self.agent_connected = False
        self.agent_running = False
        self.agent_id = None

    def set_agent_running(self):
        """设置Agent为运行状态（思考中）"""
        self.agent_running = True

    def set_agent_idle(self):
        """设置Agent为空闲状态（思考完成）"""
        self.agent_running = False

    def get_status_text(self) -> str:
        """获取服务器连接状态文本"""
        if self.connecting:
            return "连接中..."
        elif self.connected:
            return f"已连接 [{self.session_id}]"
        else:
            return "未连接"

    def get_status_color(self) -> str:
        """获取服务器连接状态颜色"""
        if self.connecting:
            return "yellow"
        elif self.connected:
            return "green"
        else:
            return "red"

    def get_agent_status_text(self) -> str:
        """获取Agent连接状态文本"""
        if self.agent_connecting:
            return "Agent连接中..."
        elif self.agent_connected and self.agent_running:
            return "Agent运行中"
        elif self.agent_connected:
            return "Agent已连接"
        else:
            return "Agent未连接"

    def get_agent_status_color(self) -> str:
        """获取Agent连接状态颜色"""
        if self.agent_connecting:
            return "yellow"
        elif self.agent_connected and self.agent_running:
            return "cyan"
        elif self.agent_connected:
            return "green"
        else:
            return "red"
