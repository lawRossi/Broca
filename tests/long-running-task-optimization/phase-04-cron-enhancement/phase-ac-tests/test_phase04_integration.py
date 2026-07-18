"""
Phase 4 集成测试: ProcessTool / Agent 查询接口增强
(原 CronTool 进程管理操作拆分至独立 ProcessTool)

Phase AC 1: ProcessTool 提供 track_process / list_processes / stop_process 三个操作
Phase AC 2: Agent 可以查询进程列表、查看特定进程状态和输出路径、取消进程
Phase AC 3: 进程输出通过文件路径暴露，Agent 直接用 read_file 读取
"""

import asyncio
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from broca.process_manager import ProcessManager, ProcessStatus
from broca.tools.process import ProcessTool
from broca.tools.tool import ToolCallContext, ToolStatus


@pytest_asyncio.fixture(autouse=True)
async def clean_pm():
    pm = ProcessManager()
    await pm.cleanup()
    output_dir = Path(ProcessManager.OUTPUT_DIR)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    yield
    await pm.cleanup()


@pytest.mark.asyncio
async def test_phase_ac01_three_new_operations():
    """Phase AC 1: ProcessTool 提供 track_process/list_processes/stop_process 三个操作"""
    pt = ProcessTool()

    # 验证 action 枚举包含三个新操作
    action_enum = pt.parameters["properties"]["action"]["enum"]
    assert "track_process" in action_enum, "action enum should include track_process"
    assert "list_processes" in action_enum, "action enum should include list_processes"
    assert "stop_process" in action_enum, "action enum should include stop_process"

    # 验证参数中有对应的参数
    props = pt.parameters["properties"]
    assert "process_id" in props, "Should have process_id parameter"
    assert "force" in props, "Should have force parameter"

    # 验证三个 handler 存在
    assert hasattr(pt, '_track_process'), "ProcessTool should have _track_process"
    assert hasattr(pt, '_list_processes'), "ProcessTool should have _list_processes"
    assert hasattr(pt, '_stop_process'), "ProcessTool should have _stop_process"


@pytest.mark.asyncio
async def test_phase_ac02_full_agent_scenario():
    """Phase AC 2: Agent 可以查询、查看、取消进程"""
    pm = ProcessManager()
    pt = ProcessTool()
    ctx = ToolCallContext()

    # 1. 启动进程
    info = await pm.start_process("sleep 30")

    # 2. 查询进程列表
    list_result = await pt._list_processes({}, ctx)
    assert list_result.status.value == "success"
    assert info.process_id in list_result.content

    # 3. 查看特定进程状态
    track_result = await pt._track_process({"process_id": info.process_id}, ctx)
    assert track_result.status.value == "success"
    assert "running" in track_result.content.lower()

    # 4. 取消进程
    stop_result = await pt._stop_process({"process_id": info.process_id, "force": True}, ctx)
    assert stop_result.status.value == "success"

    await asyncio.sleep(0.3)
    assert pm.get_status(info.process_id).status == ProcessStatus.KILLED


@pytest.mark.asyncio
async def test_phase_ac03_output_exposed_via_file_path():
    """Phase AC 3: 进程输出通过文件路径暴露，Agent 可用 read_file 读取"""
    pm = ProcessManager()
    info = await pm.start_process("echo phase4_output_test")
    await asyncio.sleep(0.5)

    pt = ProcessTool()
    ctx = ToolCallContext()

    # 通过 track_process 获取文件路径
    track_result = await pt._track_process({"process_id": info.process_id}, ctx)
    assert track_result.status.value == "success"

    # 验证输出文件路径在返回内容中
    content = track_result.content
    assert ".broca/process_outputs" in content or "stdout" in content.lower(), \
        "Should expose output file path"

    # 验证文件可直接用 Path 读取（模拟 read_file 工具的行为）
    stdout_path = Path(info.stdout_path)
    assert stdout_path.exists()
    stdout_content = stdout_path.read_text().strip()
    assert stdout_content == "phase4_output_test", \
        f"stdout should contain expected output, got: {stdout_content}"

    # 验证 meta.json 包含完整信息
    import json
    meta = json.loads(Path(info.meta_path).read_text())
    assert meta["command"] == "echo phase4_output_test"
    assert meta["status"] == "completed"
    assert meta["exit_code"] == 0
