"""IPC 传输层。

拆分自原 ``ipc.py``（394 行）：

- ``addresses``  —— IPC 地址/协议族生成（按剩余预算截断 AF_UNIX 路径）
- ``base``       —— ``_BaseIPC`` 公共实现（编解码 + 收发锁 + 消息工厂）
- ``server``     —— ``IPCServer``（Web 进程侧，含 stale socket 探测）
- ``client``     —— ``IPCClient``（Runner 进程侧，含连接重试）

注意：本 ``__init__`` **不做** eager re-export。``broca.session_runner.models``
需要从 ``transport.addresses`` 反向引用，若此处 eager 导入 ``server``（其又
import models）会形成循环导入。对外导出面统一由 ``broca.session_runner.ipc``
薄壳提供。
"""
