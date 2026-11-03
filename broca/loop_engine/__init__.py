"""Loop Engine 包入口。

包结构：

- ``engine.py`` — ``DefaultLoopEngine``：纯编排器（turn/step 生命周期、Hook
  dispatch 顺序、DB 持久化、广播回调）
- ``strategies/`` — 可插拔策略（``RetryLLMStrategy`` / ``ParallelToolStrategy`` /
  ``SerialToolStrategy`` + 工厂）
- ``hooks/`` — 可组合生命周期 Hook（Snapshot / Communicator / DeadLoop /
  CompressionMemory + 工厂）
- ``compressor_context.py`` — 压缩上下文工厂（供 CompressionMemoryHook 与
  ``/compact`` 命令共用）

命名约定（review 2.2）：
- **ABC** → ``broca.components.LoopEngine``（用于 isinstance / 类型标注 /
  registry 查找）
- **具体类** → ``broca.loop_engine.DefaultLoopEngine``（用于直接构造 / 测试）
- 本包不再导出 ``LoopEngine`` 别名，避免与 ABC 同名造成混淆。
"""

from broca.components.loop_engine import ExecutionResult, ExecutionStatus
from broca.loop_engine.engine import DefaultLoopEngine

__all__ = ["DefaultLoopEngine", "ExecutionResult", "ExecutionStatus"]
