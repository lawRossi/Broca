"""
Broca 服务管理器

基于 supervisor 库实现进程管理。
通过 XML-RPC 与 supervisord 通信，提供统一的 start/stop/restart/status 接口。

目录结构 (~/.broca/):
  supervisor/supervisord.conf   - supervisord 配置
  supervisor/supervisor.sock    - Unix Socket (运行时)
  logs/supervisord.log          - supervisord 日志
  logs/backend.out.log          - 后端 stdout 日志
  logs/backend.err.log          - 后端 stderr 日志
  logs/frontend.out.log         - 前端 stdout 日志
  logs/frontend.err.log         - 前端 stderr 日志
  run/supervisord.pid           - PID 文件
  install.json                  - 安装信息
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from broca.logging_config import get_logger

logger = get_logger(__name__)

# ==================== 路径常量 ====================

BROCA_HOME = Path.home() / ".broca"
SUPERVISOR_DIR = BROCA_HOME / "supervisor"
SUPERVISOR_CONF = SUPERVISOR_DIR / "supervisord.conf"
SUPERVISOR_SOCK = SUPERVISOR_DIR / "supervisor.sock"
RUN_DIR = BROCA_HOME / "run"
SUPERVISOR_PID = RUN_DIR / "supervisord.pid"
LOG_DIR = BROCA_HOME / "logs"
INSTALL_JSON = BROCA_HOME / "install.json"


def _get_project_root() -> Path:
    """获取项目根目录"""
    return Path(__file__).parent.parent


def _load_install_info() -> Dict[str, Any]:
    """加载安装信息"""
    if INSTALL_JSON.exists():
        try:
            return json.loads(INSTALL_JSON.read_text())
        except Exception:
            pass
    return {}


# ==================== Supervisor 进程管理 ====================


def _find_supervisord() -> Optional[str]:
    """查找 supervisord 可执行文件路径"""
    # 优先使用 module 方式
    python = sys.executable
    try:
        result = subprocess.run(
            [python, "-m", "supervisor.supervisord", "--help"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return f"{python} -m supervisor.supervisord"
    except Exception:
        pass

    # 尝试直接查找
    for cmd in ["supervisord", f"{python} -m supervisor.supervisord"]:
        try:
            result = subprocess.run(
                cmd.split(), capture_output=True, timeout=5, text=True
            )
            if "supervisord" in result.stdout or "supervisord" in result.stderr:
                return cmd
        except Exception:
            continue
    return None


def _find_supervisorctl() -> Optional[str]:
    """查找 supervisorctl 可执行文件路径"""
    python = sys.executable
    try:
        result = subprocess.run(
            [python, "-m", "supervisor.supervisorctl", "--help"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return f"{python} -m supervisor.supervisorctl"
    except Exception:
        pass
    return None


def _ensure_dirs() -> None:
    """确保必要的目录存在"""
    SUPERVISOR_DIR.mkdir(parents=True, exist_ok=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _is_supervisord_running() -> bool:
    """检查 supervisord 是否在运行"""
    if SUPERVISOR_PID.exists():
        try:
            pid = int(SUPERVISOR_PID.read_text().strip())
            os.kill(pid, 0)  # 检查进程是否存在
            return True
        except (ValueError, OSError, ProcessLookupError):
            # PID 文件过期
            try:
                SUPERVISOR_PID.unlink(missing_ok=True)
            except Exception:
                pass
    return False


def _wait_for_socket(timeout: float = 5.0) -> bool:
    """等待 supervisor Unix socket 就绪"""
    start = time.time()
    while time.time() - start < timeout:
        if SUPERVISOR_SOCK.exists():
            return True
        time.sleep(0.2)
    return False


def _call_supervisorctl(args: List[str]) -> Tuple[int, str, str]:
    """调用 supervisorctl 并返回 (returncode, stdout, stderr)"""
    cmd = _find_supervisorctl()
    if not cmd:
        raise RuntimeError("supervisorctl 未找到，请先执行 'broca service install'")

    full_cmd = cmd.split() + [
        "-c",
        str(SUPERVISOR_CONF),
    ] + args

    try:
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            timeout=30,
            text=True,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)


# ==================== 公开 API ====================


def status_services() -> Dict[str, Any]:
    """
    查询所有服务的状态

    Returns:
        {
            "supervisord_running": bool,
            "services": [
                {"name": str, "status": str, "pid": int|None, "uptime": str|None},
                ...
            ]
        }
    """
    result: Dict[str, Any] = {
        "supervisord_running": False,
        "services": [],
    }

    # 检查 supervisord 是否运行
    if not _is_supervisord_running():
        result["error"] = "supervisord 未运行，请执行 'broca service start'"
        return result

    result["supervisord_running"] = True

    # 通过 supervisorctl 获取状态
    ret, stdout, stderr = _call_supervisorctl(["status"])

    if ret != 0:
        result["error"] = stderr or stdout
        result["raw"] = stdout
        return result

    # 解析输出
    # 输出格式: <name> <status> <pid> <uptime>
    services = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 4:
            services.append({
                "name": parts[0],
                "status": parts[1],
                "pid": int(parts[2]) if parts[2].isdigit() else None,
                "uptime": " ".join(parts[3:]) if len(parts) > 3 else None,
            })
        else:
            services.append({
                "name": parts[0] if parts else "?",
                "status": " ".join(parts[1:]) if len(parts) > 1 else "?",
                "pid": None,
                "uptime": None,
            })

    result["services"] = services
    return result


def start_services(wait: bool = True) -> Dict[str, Any]:
    """
    启动所有服务 (supervisord + 托管程序)

    1. 如果 supervisord 未运行，先启动它
    2. 通过 supervisorctl 启动所有 program

    Args:
        wait: 是否等待服务就绪

    Returns:
        状态字典
    """
    _ensure_dirs()

    # 检查配置文件
    if not SUPERVISOR_CONF.exists():
        return {
            "success": False,
            "error": f"supervisor 配置文件不存在: {SUPERVISOR_CONF}\n请先执行 'broca service install'",
        }

    # Step 1: 启动 supervisord (如果未运行)
    if not _is_supervisord_running():
        logger.info("Starting supervisord...")
        supervisord_cmd = _find_supervisord()
        if not supervisord_cmd:
            return {
                "success": False,
                "error": "supervisord 未找到，请先执行 'broca service install'",
            }

        try:
            subprocess.run(
                supervisord_cmd.split() + ["-c", str(SUPERVISOR_CONF)],
                capture_output=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            pass  # 正常
        except Exception as e:
            return {"success": False, "error": f"启动 supervisord 失败: {e}"}

        # 等待 socket 就绪
        if not _wait_for_socket(timeout=5.0):
            return {
                "success": False,
                "error": "supervisord 启动超时 (socket 未就绪)",
            }

        logger.info("supervisord started")

    # Step 2: 等待 supervisord 就绪
    if wait:
        time.sleep(1)

    # Step 3: 启动所有托管程序
    logger.info("Starting all services via supervisorctl...")
    ret, stdout, stderr = _call_supervisorctl(["start", "all"])

    if ret != 0:
        return {
            "success": False,
            "error": stderr or stdout,
            "stdout": stdout,
        }

    return {
        "success": True,
        "message": "所有服务已启动",
        "detail": stdout,
    }


def stop_services() -> Dict[str, Any]:
    """
    停止所有服务

    1. 通过 supervisorctl 停止所有 program
    2. 停止 supervisord

    Returns:
        状态字典
    """
    if not _is_supervisord_running():
        return {"success": True, "message": "supervisord 未运行，无需停止"}

    # Step 1: 停止所有托管程序
    logger.info("Stopping all services...")
    _call_supervisorctl(["stop", "all"])

    # Step 2: 停止 supervisord
    ret, stdout, stderr = _call_supervisorctl(["shutdown"])

    # 等待进程退出
    for _ in range(10):
        if not _is_supervisord_running():
            break
        time.sleep(0.5)

    # 强制清理 PID 文件
    try:
        SUPERVISOR_PID.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        SUPERVISOR_SOCK.unlink(missing_ok=True)
    except Exception:
        pass

    if _is_supervisord_running():
        return {
            "success": False,
            "error": "supervisord 未能正常停止，请手动 kill 进程",
        }

    return {
        "success": True,
        "message": "所有服务已停止",
    }


def restart_services() -> Dict[str, Any]:
    """
    重启所有服务

    Returns:
        状态字典
    """
    stop_result = stop_services()
    if not stop_result.get("success"):
        return stop_result

    # 等待完全停止
    time.sleep(1)

    return start_services(wait=True)


def _generate_supervisor_config(
    backend_port: int = 9000,
) -> str:
    """
    生成 supervisor 配置内容（nginx 代理模式）

    Args:
        backend_port: 后端端口

    Returns:
        配置文本
    """
    user = os.environ.get("USER", "root")

    lines = [
        "; Broca - Supervisor 配置",
        f"; 安装目录: {BROCA_HOME}",
        f"; 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "[unix_http_server]",
        f"file={SUPERVISOR_DIR}/supervisor.sock",
        "chmod=0700",
        "",
        "[supervisord]",
        f"logfile={LOG_DIR}/supervisord.log",
        "logfile_maxbytes=50MB",
        "logfile_backups=10",
        "loglevel=info",
        f"pidfile={RUN_DIR}/supervisord.pid",
        "nodaemon=false",
        f"user={user}",
        "",
        "[rpcinterface:supervisor]",
        "supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface",
        "",
        "[supervisorctl]",
        f"serverurl=unix://{SUPERVISOR_DIR}/supervisor.sock",
        "",
        "; ====================",
        "; Backend (FastAPI / Uvicorn)",
        "; ====================",
        "[program:backend]",
        f"command=uvicorn app.main:app --host 127.0.0.1 --port {backend_port} --log-level info",
        f"directory={BROCA_HOME}/web/backend",
        f"user={user}",
        "autostart=true",
        "autorestart=true",
        "startretries=3",
        f"stderr_logfile={LOG_DIR}/backend.err.log",
        f"stdout_logfile={LOG_DIR}/backend.out.log",
        "stdout_logfile_maxbytes=20MB",
        "stderr_logfile_maxbytes=20MB",
        f"environment=PYTHONPATH=\"{BROCA_HOME}/web/backend:$PYTHONPATH\",BROCA_CONFIG=\"{BROCA_HOME}/configs.json\",BROCA_DATABASE_DIR=\"{BROCA_HOME}/data\",BROCA_LLM_CONFIG=\"{BROCA_HOME}/llm_config.json\",BROCA_AGENTS_CONFIG_DIR=\"{BROCA_HOME}/configs/agents\",BROCA_LOG_DIR=\"{BROCA_HOME}/logs\",SQLITE_DATABASE_PATH=\"sqlite:///{BROCA_HOME}/data/backend.db\"",
        "stopasgroup=true",
        "killasgroup=true",
    ]

    return "\n".join(lines)


def write_supervisor_config(
    backend_port: int = 9000,
) -> str:
    """
    生成并写入 supervisor 配置文件

    Returns:
        配置文件路径
    """
    _ensure_dirs()

    config_text = _generate_supervisor_config(
        backend_port=backend_port,
    )

    SUPERVISOR_CONF.write_text(config_text)
    logger.info("Supervisor config written to %s", SUPERVISOR_CONF)
    return str(SUPERVISOR_CONF)
