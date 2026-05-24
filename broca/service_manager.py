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


def _is_macos() -> bool:
    """检测是否为 macOS"""
    return sys.platform == "darwin"


def _find_nginx() -> Optional[str]:
    """查找 nginx 可执行文件路径"""
    for cmd in ["nginx", "/usr/sbin/nginx", "/usr/local/bin/nginx", "/opt/homebrew/bin/nginx"]:
        try:
            result = subprocess.run([cmd, "-v"], capture_output=True, timeout=5)
            if result.returncode == 0:
                return cmd
        except Exception:
            continue
    return None


def _broca_site_conf() -> Path:
    """broca nginx 站点配置文件路径 (~/.broca/nginx-broca.conf)"""
    return BROCA_HOME / "nginx-broca.conf"


def _broca_sites_enabled_dir() -> Optional[Path]:
    """查找 nginx sites-enabled 目录"""
    candidates = []
    if _is_macos():
        candidates = [
            "/opt/homebrew/etc/nginx/sites-enabled",
            "/usr/local/etc/nginx/sites-enabled",
        ]
    else:
        candidates = ["/etc/nginx/sites-enabled"]

    for d in candidates:
        p = Path(d)
        if p.is_dir():
            return p

    # 如果目录不存在但 nginx 已安装，尝试创建
    nginx_cmd = _find_nginx()
    if nginx_cmd:
        # 通过 nginx -t 找到配置目录
        try:
            result = subprocess.run(
                [nginx_cmd, "-t"], capture_output=True, timeout=5, text=True,
            )
            for line in result.stderr.splitlines():
                # 输出示例: "nginx: the configuration file /etc/nginx/nginx.conf syntax is ok"
                if "configuration file" in line:
                    conf_path = line.split("configuration file")[-1].strip().split()[0].rstrip(".")
                    conf_dir = Path(conf_path).parent
                    sites_dir = conf_dir / "sites-enabled"
                    if sites_dir.is_dir() or conf_dir.is_dir():
                        return sites_dir
        except Exception:
            pass

    return None


def _broca_site_enabled() -> bool:
    """检查 broca 站点是否已启用（symlink 是否存在）"""
    sites_dir = _broca_sites_enabled_dir()
    if not sites_dir:
        return False
    return (sites_dir / "broca.conf").exists()


def _enable_broca_site() -> Tuple[bool, str]:
    """启用 broca nginx 站点（创建 symlink + reload）"""
    site_conf = _broca_site_conf()
    if not site_conf.exists():
        return False, f"nginx 配置文件不存在: {site_conf}"

    sites_dir = _broca_sites_enabled_dir()
    if not sites_dir:
        return False, "未找到 nginx sites-enabled 目录"

    target = sites_dir / "broca.conf"

    # 如果已启用，只需 reload
    if target.exists():
        return _reload_nginx()

    # 创建 symlink（需要 sudo 则尝试）
    for need_sudo in [False, True]:
        try:
            if need_sudo:
                result = subprocess.run(
                    ["sudo", "-n", "ln", "-sf", str(site_conf), str(target)],
                    capture_output=True, timeout=10, text=True,
                )
            else:
                result = subprocess.run(
                    ["ln", "-sf", str(site_conf), str(target)],
                    capture_output=True, timeout=10, text=True,
                )
            if result.returncode == 0:
                ok, msg = _reload_nginx()
                if ok:
                    return True, "broca 站点已启用"
                return False, f"symlink 已创建，但 nginx 重载失败: {msg}"
            last_error = result.stderr.strip() or result.stdout.strip()
        except Exception as e:
            last_error = str(e)

    hint = ""
    if "permission denied" in last_error.lower() or " Operation not permitted" in last_error:
        hint = f" (需要 sudo 权限，请手动执行: sudo ln -sf {site_conf} {target} && sudo nginx -s reload)"
    return False, f"启用 broca 站点失败: {last_error}{hint}"


def _disable_broca_site() -> Tuple[bool, str]:
    """禁用 broca nginx 站点（删除 symlink + reload）"""
    sites_dir = _broca_sites_enabled_dir()
    if not sites_dir:
        return False, "未找到 nginx sites-enabled 目录"

    target = sites_dir / "broca.conf"
    if not target.exists():
        return True, "broca 站点未启用"

    for need_sudo in [False, True]:
        try:
            if need_sudo:
                result = subprocess.run(
                    ["sudo", "-n", "rm", "-f", str(target)],
                    capture_output=True, timeout=10, text=True,
                )
            else:
                result = subprocess.run(
                    ["rm", "-f", str(target)],
                    capture_output=True, timeout=10, text=True,
                )
            if result.returncode == 0:
                ok, msg = _reload_nginx()
                if ok:
                    return True, "broca 站点已禁用"
                return False, f"symlink 已删除，但 nginx 重载失败: {msg}"
            last_error = result.stderr.strip() or result.stdout.strip()
        except Exception as e:
            last_error = str(e)

    hint = ""
    if "permission denied" in last_error.lower():
        hint = f" (需要 sudo 权限，请手动执行: sudo rm {target} && sudo nginx -s reload)"
    return False, f"禁用 broca 站点失败: {last_error}{hint}"


def _reload_nginx() -> Tuple[bool, str]:
    """重载 nginx 配置（不启停 nginx 进程本身）"""
    nginx_cmd = _find_nginx()
    if not nginx_cmd:
        return False, "nginx 未安装"

    # 免 sudo → sudo -n
    for need_sudo in [False, True]:
        try:
            if need_sudo:
                result = subprocess.run(
                    ["sudo", "-n", nginx_cmd, "-s", "reload"],
                    capture_output=True, timeout=15, text=True,
                )
            else:
                result = subprocess.run(
                    [nginx_cmd, "-s", "reload"],
                    capture_output=True, timeout=15, text=True,
                )
            if result.returncode == 0:
                return True, "nginx 配置已重载"
            last_error = result.stderr.strip() or result.stdout.strip()
        except subprocess.TimeoutExpired:
            last_error = "命令超时"
        except Exception as e:
            last_error = str(e)

    hint = ""
    if "sudo" in last_error.lower() or "permission denied" in last_error.lower():
        hint = " (需要 sudo 权限，请手动执行: sudo nginx -s reload)"
    return False, f"nginx 重载失败: {last_error}{hint}"


def _get_frontend_status() -> Dict[str, Any]:
    """获取前端服务状态（基于 broca 站点是否启用）"""
    nginx_cmd = _find_nginx()
    if not nginx_cmd:
        return {"available": False, "enabled": False, "error": "nginx 未安装"}

    enabled = _broca_site_enabled()

    # 获取版本号
    version = ""
    try:
        result = subprocess.run([nginx_cmd, "-v"], capture_output=True, timeout=5, text=True)
        version = result.stderr.strip() or result.stdout.strip()
    except Exception:
        pass

    return {
        "available": True,
        "enabled": enabled,
        "version": version,
        "command": nginx_cmd,
        "site_config": str(_broca_site_conf()),
    }


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

    # 添加 nginx 前端服务状态
    nginx_status = _get_frontend_status()
    result["nginx"] = nginx_status
    if nginx_status.get("available"):
        result["services"].append({
            "name": "frontend (nginx)",
            "status": "ENABLED" if nginx_status["enabled"] else "DISABLED",
            "pid": None,
            "uptime": None,
            "detail": nginx_status.get("version", ""),
        })

    return result


def start_services(wait: bool = True) -> Dict[str, Any]:
    """
    启动所有服务 (supervisord + 托管程序 + nginx 前端)

    1. 如果 supervisord 未运行，先启动它
    2. 通过 supervisorctl 启动所有 program
    3. 启动 nginx 前端服务

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

    # Step 4: 启动 nginx 前端
    logger.info("Starting nginx frontend...")
    nginx_ok, nginx_msg = _enable_broca_site()
    if not nginx_ok:
        logger.warning("nginx 启动失败: %s", nginx_msg)

    return {
        "success": True,
        "message": "所有服务已启动",
        "detail": stdout,
        "nginx": {"ok": nginx_ok, "message": nginx_msg},
    }


def stop_services() -> Dict[str, Any]:
    """
    停止所有服务

    1. 通过 supervisorctl 停止所有 program
    2. 停止 supervisord
    3. 停止 nginx 前端服务

    Returns:
        状态字典
    """
    nginx_ok = True
    nginx_msg = ""

    # 先停止 nginx 前端（依赖关系：nginx→backend）
    if _broca_site_enabled():
        logger.info("Disabling broca nginx site...")
        nginx_ok, nginx_msg = _disable_broca_site()

    if not _is_supervisord_running():
        return {
            "success": True,
            "message": "supervisord 未运行，无需停止",
            "nginx": {"ok": nginx_ok, "message": nginx_msg},
        }

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
            "nginx": {"ok": nginx_ok, "message": nginx_msg},
        }

    return {
        "success": True,
        "message": "所有服务已停止",
        "nginx": {"ok": nginx_ok, "message": nginx_msg},
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
        f"environment=PYTHONPATH=\"{BROCA_HOME}/web/backend:$PYTHONPATH\",BROCA_CONFIG=\"{BROCA_HOME}/configs/configs.json\",BROCA_DATABASE_DIR=\"{BROCA_HOME}/data\",BROCA_LLM_CONFIG=\"{BROCA_HOME}/configs/llm_config.json\",BROCA_AGENTS_CONFIG_DIR=\"{BROCA_HOME}/configs/agents\",BROCA_LOG_DIR=\"{BROCA_HOME}/logs\",SQLITE_DATABASE_PATH=\"sqlite:///{BROCA_HOME}/data/backend.db\"",
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
