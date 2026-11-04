"""进程层：启动 / 回收 / 内存注册表。

- ``launcher`` —— 子进程启动（argv 列表 + ``sys.executable`` + ``start_new_session``）
- ``reaper``   —— 判活与杀进程（多因子校验，防 PID 复用误杀）
- ``registry`` —— ``RunnerHandle`` + ``RunnerRegistry``（把 7 个并行 dict 收成 1 个对象）
"""
