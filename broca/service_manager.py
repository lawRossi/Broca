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
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from broca.errors import BrocaError
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


def _load_install_info() -> dict[str, Any]:
    """加载安装信息"""
    if INSTALL_JSON.exists():
        try:
            return json.loads(INSTALL_JSON.read_text())
        except Exception:
            pass
    return {}


# ==================== Supervisor 进程管理 ====================


def _find_supervisord() -> str | None:
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


def _find_supervisorctl() -> str | None:
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


def _is_windows() -> bool:
    """判断当前是否 Windows 平台"""
    return os.name == "nt"


def _is_supervisord_running() -> bool:
    """检查 supervisord 是否在运行"""
    if SUPERVISOR_PID.exists():
        try:
            pid = int(SUPERVISOR_PID.read_text().strip())
            if _is_windows():
                # Windows 上 os.kill(pid, 0) 不可靠，改用 psutil
                import psutil

                return psutil.pid_exists(pid)
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
    """等待 supervisor 就绪（Unix: socket 文件；Windows: TCP 端口）"""
    start = time.time()
    if _is_windows():
        # Windows 使用 inet_http_server (TCP 127.0.0.1:9001)
        import socket as socket_mod

        while time.time() - start < timeout:
            try:
                with socket_mod.create_connection(("127.0.0.1", 9001), timeout=0.5):
                    return True
            except OSError:
                time.sleep(0.2)
        return False
    while time.time() - start < timeout:
        if SUPERVISOR_SOCK.exists():
            return True
        time.sleep(0.2)
    return False


def _call_supervisorctl(args: list[str]) -> tuple[int, str, str]:
    """调用 supervisorctl 并返回 (returncode, stdout, stderr)"""
    cmd = _find_supervisorctl()
    if not cmd:
        raise BrocaError("supervisorctl 未找到，请先执行 'broca service install'")

    full_cmd = (
        cmd.split()
        + [
            "-c",
            str(SUPERVISOR_CONF),
        ]
        + args
    )

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


def _find_nginx() -> str | None:
    """查找 nginx 可执行文件路径"""
    for cmd in [
        "nginx",
        "/usr/sbin/nginx",
        "/usr/local/bin/nginx",
        "/opt/homebrew/bin/nginx",
    ]:
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


def _broca_sites_enabled_dir() -> Path | None:
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
                [nginx_cmd, "-t"],
                capture_output=True,
                timeout=5,
                text=True,
            )
            for line in result.stderr.splitlines():
                # 输出示例: "nginx: the configuration file /etc/nginx/nginx.conf syntax is ok"
                if "configuration file" in line:
                    conf_path = (
                        line.split("configuration file")[-1]
                        .strip()
                        .split()[0]
                        .rstrip(".")
                    )
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


def _enable_broca_site() -> tuple[bool, str]:
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

    # 创建 symlink（尝试: 免sudo → sudo -n 非交互 → 交互式sudo）
    for cmd in [
        ["ln", "-sf", str(site_conf), str(target)],
        ["sudo", "-n", "ln", "-sf", str(site_conf), str(target)],
        ["sudo", "ln", "-sf", str(site_conf), str(target)],
    ]:
        try:
            # 交互式 sudo 需要让终端 I/O 通过，以便用户输入密码
            is_interactive = cmd[0] == "sudo" and cmd[1] != "-n"
            result = subprocess.run(
                cmd,
                capture_output=not is_interactive,
                timeout=10,
                text=True,
            )
            if result.returncode == 0:
                ok, msg = _reload_nginx()
                if ok:
                    return True, "broca 站点已启用"
                return False, f"symlink 已创建，但 nginx 重载失败: {msg}"
            # 安全获取错误信息（capture_output=False 时 stdout/stderr 为 None）
            err_msg = (result.stderr or "").strip() or (result.stdout or "").strip()
            if err_msg:
                last_error = err_msg
        except Exception as e:
            last_error = str(e)

    if not last_error:
        last_error = "操作失败（权限不足或非交互式终端）"

    hint = ""
    if (
        "permission denied" in last_error.lower()
        or " Operation not permitted" in last_error
    ):
        hint = f" (需要 sudo 权限，请手动执行: sudo ln -sf {site_conf} {target} && sudo nginx -s reload)"
    return False, f"启用 broca 站点失败: {last_error}{hint}"


def _disable_broca_site() -> tuple[bool, str]:
    """禁用 broca nginx 站点（删除 symlink + reload）"""
    sites_dir = _broca_sites_enabled_dir()
    if not sites_dir:
        return False, "未找到 nginx sites-enabled 目录"

    target = sites_dir / "broca.conf"
    if not target.exists():
        return True, "broca 站点未启用"

    # 删除 symlink（尝试: 免sudo → sudo -n 非交互 → 交互式sudo）
    for cmd in [
        ["rm", "-f", str(target)],
        ["sudo", "-n", "rm", "-f", str(target)],
        ["sudo", "rm", "-f", str(target)],
    ]:
        try:
            is_interactive = cmd[0] == "sudo" and cmd[1] != "-n"
            result = subprocess.run(
                cmd,
                capture_output=not is_interactive,
                timeout=10,
                text=True,
            )
            if result.returncode == 0:
                ok, msg = _reload_nginx()
                if ok:
                    return True, "broca 站点已禁用"
                return False, f"symlink 已删除，但 nginx 重载失败: {msg}"
            # 安全获取错误信息（capture_output=False 时 stdout/stderr 为 None）
            err_msg = (result.stderr or "").strip() or (result.stdout or "").strip()
            if err_msg:
                last_error = err_msg
        except Exception as e:
            last_error = str(e)

    if not last_error:
        last_error = "操作失败（权限不足或非交互式终端）"
    hint = ""
    if "permission denied" in last_error.lower():
        hint = (
            f" (需要 sudo 权限，请手动执行: sudo rm {target} && sudo nginx -s reload)"
        )
    return False, f"禁用 broca 站点失败: {last_error}{hint}"


def _is_nginx_running() -> bool:
    """检查 nginx master 进程是否在运行"""
    # 常见 PID 文件路径
    pid_paths = [
        "/opt/homebrew/var/run/nginx.pid",
        "/usr/local/var/run/nginx.pid",
        "/var/run/nginx.pid",
        "/run/nginx.pid",
    ]
    for pid_path in pid_paths:
        try:
            pid = Path(pid_path).read_text().strip()
            if pid:
                # 尝试 kill -0（普通用户进程）
                for cmd in [
                    ["kill", "-0", pid],
                    ["sudo", "-n", "kill", "-0", pid],
                ]:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        timeout=5,
                    )
                    if result.returncode == 0:
                        return True
                    # "Operation not permitted" 意味着进程存在但属 root，也算在运行
                    if (
                        "operation not permitted"
                        in (result.stderr or b"").decode().lower()
                    ):
                        return True
        except (FileNotFoundError, ValueError, subprocess.TimeoutExpired):
            continue
        except PermissionError:
            # 无权读取 PID 文件，尝试其他方式检测
            break

    # 兜底: ps aux 搜索 nginx master 进程
    try:
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            timeout=5,
            text=True,
        )
        for line in result.stdout.splitlines():
            if "nginx: master process" in line:
                return True
    except Exception:
        pass

    return False


def _ensure_nginx_user() -> None:
    """确保 nginx.conf 中 user 指令设为当前用户（解决 macOS 上 nobody 无权访问家目录的问题）"""
    nginx_conf_paths = [
        "/opt/homebrew/etc/nginx/nginx.conf",
        "/usr/local/etc/nginx/nginx.conf",
        "/etc/nginx/nginx.conf",
    ]
    current_user = os.environ.get("USER", "")
    if not current_user:
        return

    # 获取用户的主组名（nginx 需要 user <name> <group>; 格式）
    current_group = None
    try:
        import grp

        current_group = grp.getgrgid(os.getgid()).gr_name
    except Exception:
        pass

    user_directive = (
        f"user {current_user} {current_group};"
        if current_group
        else f"user {current_user};"
    )

    for conf_path in nginx_conf_paths:
        conf = Path(conf_path)
        if not conf.exists():
            continue
        try:
            content = conf.read_text()

            # 检测所有 user 指令行（包括被注释的 #user 行）
            # 查找所有匹配 user 指令的行
            all_user_lines = list(
                re.finditer(
                    r"^[ \t]*(?:#\s*)?user\s+\S+(?:\s+\S+)?\s*;",
                    content,
                    re.MULTILINE,
                )
            )
            active_user_lines = [
                m for m in all_user_lines if not m.group(0).lstrip().startswith("#")
            ]
            commented_user_lines = [
                m for m in all_user_lines if m.group(0).lstrip().startswith("#")
            ]

            if active_user_lines:
                # 有激活的 user 指令 → 修改它（同时删除其他重复行）
                active = active_user_lines[0]
                existing = re.match(
                    r"^\s*user\s+(\S+)(?:\s+(\S+))?\s*;", active.group(0)
                )
                if existing:
                    eu, eg = existing.group(1), existing.group(2)
                    if (
                        eu == current_user
                        and (not current_group or eg == current_group)
                        and len(active_user_lines) == 1
                    ):
                        return  # 已经是正确的唯一 user 指令
                # 替换所有 user 指令行（激活的和注释的）为正确的一条
                new_content = re.sub(
                    r"^[ \t]*(?:#\s*)?user\s+\S+(?:\s+\S+)?\s*;\n?",
                    "",
                    content,
                    flags=re.MULTILINE,
                )
                # 在 worker_processes 后插入正确的 user 指令
                new_content = re.sub(
                    r"(worker_processes\s+\d+\s*;)",
                    f"\\1\n{user_directive}",
                    new_content,
                    count=1,
                )
            elif commented_user_lines:
                # 只有被注释的 user 指令 → 取消注释并修改
                new_content = re.sub(
                    r"^[ \t]*#\s*user\s+\S+(?:\s+\S+)?\s*;",
                    user_directive,
                    content,
                    count=1,
                    flags=re.MULTILINE,
                )
            else:
                # 完全没有 user 指令 → 在 worker_processes 后添加
                new_content = re.sub(
                    r"(worker_processes\s+\d+\s*;)",
                    f"\\1\n{user_directive}",
                    content,
                    count=1,
                )

            if new_content != content:
                # 写入临时文件后通过 sudo cp 写入目标路径（比 cat > file 更安全）
                import tempfile

                tmp = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".tmp")
                try:
                    tmp.write(new_content)
                    tmp.close()
                    for cmd in [
                        ["cp", tmp.name, str(conf_path)],
                        ["sudo", "-n", "cp", tmp.name, str(conf_path)],
                        ["sudo", "cp", tmp.name, str(conf_path)],
                    ]:
                        is_interactive = cmd[0] == "sudo" and cmd[1] != "-n"
                        try:
                            result = subprocess.run(
                                cmd,
                                capture_output=not is_interactive,
                                timeout=10,
                            )
                            if result.returncode == 0:
                                logger.info(
                                    f"nginx user 已设为 {current_user} (in {conf_path})"
                                )
                                return
                        except Exception:
                            continue
                finally:
                    os.unlink(tmp.name)
        except Exception:
            continue


def _start_nginx() -> tuple[bool, str]:
    """启动 nginx 服务"""
    nginx_cmd = _find_nginx()
    if not nginx_cmd:
        return False, "nginx 未安装"

    # 确保 nginx worker 以当前用户运行（避免权限问题）
    _ensure_nginx_user()

    # 尝试: nginx → sudo -n nginx → sudo nginx
    for cmd in [
        [nginx_cmd],
        ["sudo", "-n", nginx_cmd],
        ["sudo", nginx_cmd],
    ]:
        try:
            is_interactive = cmd[0] == "sudo" and cmd[1] != "-n"
            result = subprocess.run(
                cmd,
                capture_output=not is_interactive,
                timeout=15,
                text=True,
            )
            if result.returncode == 0:
                return True, "nginx 已启动"
            err_msg = (result.stderr or "").strip() or (result.stdout or "").strip()
            if err_msg:
                last_error = err_msg
        except Exception as e:
            last_error = str(e)

    if not last_error:
        last_error = "操作失败（权限不足或非交互式终端）"
    hint = ""
    if "sudo" in last_error.lower() or "permission denied" in last_error.lower():
        hint = " (需要 sudo 权限，请手动执行: sudo nginx)"
    return False, f"nginx 启动失败: {last_error}{hint}"


def _reload_nginx() -> tuple[bool, str]:
    """重载 nginx 配置（若 nginx 未运行则先启动）"""
    nginx_cmd = _find_nginx()
    if not nginx_cmd:
        return False, "nginx 未安装"

    # 检查 nginx 是否在运行
    if not _is_nginx_running():
        logger.info("nginx 未运行，正在启动...")
        ok, msg = _start_nginx()
        if ok:
            return True, "nginx 已启动"
        # 启动失败，给出提示
        return False, msg

    # nginx 在运行，执行 reload
    for cmd in [
        [nginx_cmd, "-s", "reload"],
        ["sudo", "-n", nginx_cmd, "-s", "reload"],
        ["sudo", nginx_cmd, "-s", "reload"],
    ]:
        try:
            is_interactive = cmd[0] == "sudo" and cmd[1] != "-n"
            result = subprocess.run(
                cmd,
                capture_output=not is_interactive,
                timeout=15,
                text=True,
            )
            if result.returncode == 0:
                return True, "nginx 配置已重载"
            err_msg = (result.stderr or "").strip() or (result.stdout or "").strip()
            if err_msg:
                last_error = err_msg
        except subprocess.TimeoutExpired:
            last_error = "命令超时"
        except Exception as e:
            last_error = str(e)

    if not last_error:
        last_error = "操作失败（权限不足或非交互式终端）"
    hint = ""
    if "sudo" in last_error.lower() or "permission denied" in last_error.lower():
        hint = " (需要 sudo 权限，请手动执行: sudo nginx -s reload)"
    return False, f"nginx 重载失败: {last_error}{hint}"


def _get_frontend_status() -> dict[str, Any]:
    """获取前端服务状态（基于 broca 站点是否启用）"""
    nginx_cmd = _find_nginx()
    if not nginx_cmd:
        return {"available": False, "enabled": False, "error": "nginx 未安装"}

    enabled = _broca_site_enabled()

    # 获取版本号
    version = ""
    try:
        result = subprocess.run(
            [nginx_cmd, "-v"], capture_output=True, timeout=5, text=True
        )
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


def _is_frontend_skipped() -> bool:
    """检查安装时是否跳过了前端部署（从 install.json 读取）"""
    install_info = _load_install_info()
    return install_info.get("skip_frontend", False)


# ==================== Windows 服务管理 ====================
# supervisor 是 Unix 工具（依赖 pwd/grp/fcntl/os.fork 等），Windows 上不可用。
# Windows 优先使用 NSSM 注册的 Windows 服务；若未注册则裸起（subprocess 管理），
# PID 记录在 run/services.json。前端统一使用 nginx（与 Linux 一致）。

SERVICES_STATE = RUN_DIR / "services.json"


def _win_find_nssm() -> str | None:
    """查找 nssm.exe"""
    try:
        import shutil

        found = shutil.which("nssm")
        if found:
            return found
    except Exception:
        pass
    for p in [
        r"C:\nssm\nssm.exe",
        r"C:\tools\nssm\nssm.exe",
        r"C:\Program Files\nssm\nssm.exe",
    ]:
        if Path(p).exists():
            return p
    return None


def _win_nssm_available() -> bool:
    """检查 NSSM 是否可用且 Broca 服务已注册"""
    nssm = _win_find_nssm()
    if not nssm:
        return False
    try:
        result = subprocess.run(
            [nssm, "status", "BrocaBackend"],
            capture_output=True,
            timeout=5,
            text=True,
        )
        return result.returncode in (0, 1, 2, 3)  # 服务存在
    except Exception:
        return False


def _win_nssm_service_status(nssm: str, svc: str) -> tuple[bool, str]:
    """查询 NSSM 服务状态，返回 (是否运行, 状态描述)"""
    try:
        result = subprocess.run(
            [nssm, "status", svc], capture_output=True, timeout=5, text=True
        )
        # NSSM status 退出码: 0=RUNNING, 1=STOPPED, 2=START_PENDING, 3=STOP_PENDING
        code = result.returncode
        status_map = {
            0: "RUNNING",
            1: "STOPPED",
            2: "STARTING",
            3: "STOPPING",
        }
        status = status_map.get(code, f"UNKNOWN({code})")
        return code == 0, status
    except Exception as e:
        return False, f"ERROR: {e}"


def _win_nssm_run(nssm: str, action: str, svc: str) -> tuple[int, str, str]:
    """执行 nssm 命令"""
    try:
        result = subprocess.run(
            [nssm, action, svc], capture_output=True, timeout=30, text=True
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def _win_nssm_start_services(wait: bool = True) -> dict[str, Any]:
    """Windows (NSSM): 通过 Windows 服务启动后端和前端"""
    nssm = _win_find_nssm()
    details = []

    # 后端
    running, status = _win_nssm_service_status(nssm, "BrocaBackend")
    if running:
        details.append("后端服务已在运行")
    else:
        ret, out, err = _win_nssm_run(nssm, "start", "BrocaBackend")
        if ret != 0:
            return {"success": False, "error": f"启动后端服务失败: {err or out}"}
        details.append("后端服务已启动")

    # 前端 (nginx)
    running, status = _win_nssm_service_status(nssm, "BrocaFrontend")
    if running:
        details.append("前端服务 (nginx) 已在运行，http://localhost:5166")
    else:
        ret, out, err = _win_nssm_run(nssm, "start", "BrocaFrontend")
        if ret != 0:
            details.append(f"前端服务启动失败: {err or out}")
            details.append(
                "  提示: 请确认 nginx 已安装且 install.bat 已注册 BrocaFrontend 服务"
            )
        else:
            details.append("前端服务 (nginx) 已启动，http://localhost:5166")

    return {
        "success": True,
        "message": "所有服务已启动",
        "detail": "\n".join(details),
        "nginx": {"ok": _win_frontend_running(), "message": "nginx 前端服务 (NSSM)"},
    }


def _win_nssm_stop_services() -> dict[str, Any]:
    """Windows (NSSM): 通过 Windows 服务停止后端和前端"""
    nssm = _win_find_nssm()
    details = []

    for svc, label in [
        ("BrocaBackend", "后端服务"),
        ("BrocaFrontend", "前端服务 (nginx)"),
    ]:
        running, status = _win_nssm_service_status(nssm, svc)
        if running:
            ret, out, err = _win_nssm_run(nssm, "stop", svc)
            if ret == 0:
                details.append(f"{label}已停止")
            else:
                details.append(f"{label}停止失败: {err or out}")
        else:
            details.append(f"{label}未运行")

    return {
        "success": True,
        "message": "所有服务已停止",
        "detail": "\n".join(details),
        "nginx": {"ok": True, "message": "前端服务已停止"},
    }


def _win_nssm_status_services() -> dict[str, Any]:
    """Windows (NSSM): 查询服务状态"""
    nssm = _win_find_nssm()
    services = []
    any_running = False

    for svc, label in [
        ("BrocaBackend", "backend (NSSM)"),
        ("BrocaFrontend", "frontend (NSSM)"),
    ]:
        running, status = _win_nssm_service_status(nssm, svc)
        if running:
            any_running = True
        services.append(
            {
                "name": label,
                "status": status,
                "pid": None,
                "uptime": None,
            }
        )

    return {
        "supervisord_running": any_running,
        "services": services,
    }


def _win_load_state() -> dict[str, Any]:
    """加载 Windows 服务状态 (PID 记录)"""
    if SERVICES_STATE.exists():
        try:
            return json.loads(SERVICES_STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"backend": None, "frontend": None}


def _win_save_state(state: dict[str, Any]) -> None:
    """保存 Windows 服务状态"""
    try:
        SERVICES_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("保存服务状态失败: %s", e)


def _win_get_python() -> str:
    """获取 venv 中的 python.exe 路径"""
    install_info = _load_install_info()
    venv = install_info.get("venv_path", "")
    if venv:
        cand = Path(venv) / "Scripts" / "python.exe"
        if cand.exists():
            return str(cand)
    # 回退：~/.broca/venv/
    cand = BROCA_HOME / "venv" / "Scripts" / "python.exe"
    if cand.exists():
        return str(cand)
    return sys.executable


def _win_is_process_alive(pid: int | None) -> bool:
    """检查进程是否存活"""
    if not pid:
        return False
    try:
        import psutil

        return psutil.pid_exists(pid)
    except ImportError:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _win_stop_process(pid: int | None) -> None:
    """停止进程（含子进程树）"""
    if not pid or not _win_is_process_alive(pid):
        return
    try:
        import psutil

        try:
            p = psutil.Process(pid)
            for child in p.children(recursive=True):
                try:
                    child.kill()
                except Exception:
                    pass
            p.kill()
        except psutil.NoSuchProcess:
            pass
    except ImportError:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def _win_backend_env(backend_dir: Path) -> dict[str, str]:
    """构造后端进程环境变量"""
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(backend_dir),
            "BROCA_CONFIG": str(BROCA_HOME / "configs" / "configs.json"),
            "BROCA_DATABASE_DIR": str(BROCA_HOME / "data"),
            "BROCA_LLM_CONFIG": str(BROCA_HOME / "configs" / "llm_config.json"),
            "BROCA_AGENTS_CONFIG_DIR": str(BROCA_HOME / "configs" / "agents"),
            "BROCA_LOG_DIR": str(LOG_DIR),
            "SQLITE_DATABASE_PATH": f"sqlite:///{BROCA_HOME}/data/backend.db",
        }
    )
    return env


def _win_start_backend() -> tuple[bool, str, int | None]:
    """启动后端 (uvicorn)"""
    python = _win_get_python()
    backend_dir = BROCA_HOME / "web" / "backend"
    if not backend_dir.exists():
        return False, f"后端目录不存在: {backend_dir}", None

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_out = open(LOG_DIR / "backend.out.log", "ab")
    log_err = open(LOG_DIR / "backend.err.log", "ab")

    try:
        proc = subprocess.Popen(
            [
                python,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "9000",
                "--log-level",
                "info",
            ],
            cwd=str(backend_dir),
            env=_win_backend_env(backend_dir),
            stdout=log_out,
            stderr=log_err,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        return True, f"后端已启动 (PID: {proc.pid})", proc.pid
    except Exception as e:
        return False, f"后端启动失败: {e}", None


def _win_find_nginx() -> str | None:
    """查找 nginx 可执行文件"""
    # 1. 优先使用 ~/.broca/nginx/ 下的独立安装
    cand = BROCA_HOME / "nginx" / "nginx.exe"
    if cand.exists():
        return str(cand)
    # 2. PATH 中查找
    try:
        import shutil

        found = shutil.which("nginx")
        if found:
            return found
    except Exception:
        pass
    # 3. 常见安装位置
    for p in [
        r"C:\nginx\nginx.exe",
        r"C:\tools\nginx\nginx.exe",
        r"C:\Program Files\nginx\nginx.exe",
    ]:
        if Path(p).exists():
            return p
    return None


def _win_prepare_nginx() -> tuple[bool, str, str | None]:
    """准备 nginx 独立运行环境（prefix 隔离，不影响系统 nginx）。

    布局:
      ~/.broca/nginx/
        nginx.exe          (复制自 nginx 安装目录)
        conf/nginx.conf    (Broca 主配置)
        conf/mime.types    (复制自 nginx 安装目录)
        logs/  temp/
    """
    nginx_exe = _win_find_nginx()
    if not nginx_exe:
        return (
            False,
            "未找到 nginx。请安装 nginx for Windows:\n"
            "  winget install nginx 或 https://nginx.org/en/download.html\n"
            "  安装后请重新运行 install.bat admin",
            None,
        )

    nginx_src = Path(nginx_exe)
    nginx_home = BROCA_HOME / "nginx"

    # 复制 nginx.exe 到独立目录（若来源不是该目录）
    if nginx_src.parent != nginx_home:
        try:
            nginx_home.mkdir(parents=True, exist_ok=True)
            target_exe = nginx_home / "nginx.exe"
            if not target_exe.exists():
                import shutil

                shutil.copy2(nginx_src, target_exe)
            nginx_exe = str(target_exe)
        except Exception as e:
            # 复制失败则直接使用原路径
            logger.warning("复制 nginx.exe 失败，直接使用原路径: %s", e)
            nginx_exe = str(nginx_src)

    # 复制 mime.types（若不存在）
    conf_dir = nginx_home / "conf"
    conf_dir.mkdir(parents=True, exist_ok=True)
    src_mime = nginx_src.parent / "conf" / "mime.types"
    if src_mime.exists() and not (conf_dir / "mime.types").exists():
        import shutil

        shutil.copy2(src_mime, conf_dir / "mime.types")

    # 生成主配置（含 Broca server 块，与 Linux nginx 站点配置保持一致）
    nginx_conf = conf_dir / "nginx.conf"
    install_info = _load_install_info()
    dist_dir = install_info.get("frontend_dist") or ""
    # nginx 配置中统一使用正斜杠
    dist_dir_nix = str(dist_dir).replace("\\", "/")

    config_text = f"""worker_processes  1;

events {{
    worker_connections  1024;
}}

http {{
    include       mime.types;
    default_type  application/octet-stream;

    log_format  main  '$remote_addr - $remote_user [$time_local] "$request" '
                      '$status $body_bytes_sent "$http_referer" '
                      '"$http_user_agent" "$http_x_forwarded_for"';

    access_log  {str(nginx_home / "logs" / "access.log").replace(os.sep, "/")}  main;
    error_log   {str(nginx_home / "logs" / "error.log").replace(os.sep, "/")};

    sendfile        on;
    keepalive_timeout  65;

    # ---- Broca Web 站点 ----
    server {{
        listen       5166;
        server_name  _;

        # 前端静态文件
        root {dist_dir_nix};
        index index.html;

        # gzip 压缩
        gzip on;
        gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;

        # API 反向代理 (后端)
        location /api/ {{
            proxy_pass http://127.0.0.1:9000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }}

        # Socket.IO 反向代理
        location /socket.io/ {{
            proxy_pass http://127.0.0.1:6868;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }}

        # SPA 路由: 所有非文件请求返回 index.html
        location / {{
            try_files $uri $uri/ /index.html;
        }}
    }}
}}
"""
    try:
        nginx_conf.write_text(config_text, encoding="utf-8")
    except Exception as e:
        return False, f"生成 nginx 配置失败: {e}", None

    # 日志目录
    (nginx_home / "logs").mkdir(parents=True, exist_ok=True)
    (nginx_home / "temp").mkdir(parents=True, exist_ok=True)

    return True, f"nginx 配置就绪: {nginx_conf}", nginx_exe


def _win_start_frontend() -> tuple[bool, str, int | None]:
    """启动前端 (nginx 部署，与 Linux 一致)"""
    install_info = _load_install_info()
    dist_dir = install_info.get("frontend_dist")
    if not dist_dir or not Path(dist_dir).exists():
        return False, "前端 dist 目录不存在", None

    # 准备 nginx 独立环境
    ok, msg, nginx_exe = _win_prepare_nginx()
    if not ok:
        return False, msg, None

    nginx_home = BROCA_HOME / "nginx"
    try:
        proc = subprocess.Popen(
            [
                nginx_exe,
                "-p",
                str(nginx_home).replace("\\", "/") + "/",
                "-c",
                "conf/nginx.conf",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # nginx 启动后自己会 daemonize，Popen 立即返回
        time.sleep(1)
        # 检查端口是否就绪
        import socket as socket_mod

        for _ in range(10):
            try:
                with socket_mod.create_connection(("127.0.0.1", 5166), timeout=0.5):
                    return True, "前端 (nginx) 已启动，http://localhost:5166", None
            except OSError:
                time.sleep(0.5)

        # 端口未就绪，读取 nginx 错误日志
        err_log = nginx_home / "logs" / "error.log"
        err_detail = ""
        if err_log.exists():
            err_detail = err_log.read_text(encoding="utf-8", errors="replace")[-1000:]
        return False, f"nginx 启动失败（端口 5166 未就绪）\n{err_detail}", None
    except Exception as e:
        return False, f"nginx 启动失败: {e}", None


def _win_stop_frontend() -> tuple[bool, str]:
    """停止前端 (nginx)"""
    nginx_exe = _win_find_nginx()
    nginx_home = BROCA_HOME / "nginx"

    # 方式1: nginx -s stop 优雅停止
    if nginx_exe:
        try:
            subprocess.run(
                [
                    nginx_exe,
                    "-p",
                    str(nginx_home).replace("\\", "/") + "/",
                    "-s",
                    "stop",
                ],
                capture_output=True,
                timeout=10,
            )
            time.sleep(1)
        except Exception:
            pass

    # 方式2: 检查端口，若仍占用则 kill 进程
    import socket as socket_mod

    try:
        with socket_mod.create_connection(("127.0.0.1", 5166), timeout=0.5):
            # 端口仍占用，强制 kill nginx 进程
            try:
                import psutil

                for proc in psutil.process_iter(["name", "cmdline"]):
                    try:
                        if proc.info["name"] and "nginx" in proc.info["name"].lower():
                            proc.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except ImportError:
                subprocess.run(
                    ["taskkill", "/F", "/IM", "nginx.exe"],
                    capture_output=True,
                    timeout=10,
                )
            return True, "前端 (nginx) 已停止"
    except OSError:
        return True, "前端 (nginx) 已停止"


def _win_frontend_running() -> bool:
    """检查前端 (nginx) 是否在运行"""
    import socket as socket_mod

    try:
        with socket_mod.create_connection(("127.0.0.1", 5166), timeout=0.5):
            return True
    except OSError:
        return False


def _win_bare_start_services(wait: bool = True) -> dict[str, Any]:
    """Windows (裸起): 启动后端和前端进程"""
    _ensure_dirs()
    state = _win_load_state()
    details = []

    # --- 后端 ---
    backend_pid = state.get("backend")
    if _win_is_process_alive(backend_pid):
        details.append(f"后端已在运行 (PID: {backend_pid})")
    else:
        ok, msg, pid = _win_start_backend()
        details.append(msg)
        if not ok:
            return {"success": False, "error": msg, "detail": "\n".join(details)}
        state["backend"] = pid

    # 等待后端端口就绪
    if wait:
        import socket as socket_mod

        for _ in range(20):  # 最多 10 秒
            try:
                with socket_mod.create_connection(("127.0.0.1", 9000), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.5)

    # --- 前端 (nginx) ---
    install_info = _load_install_info()
    if install_info.get("frontend_dist"):
        if _win_frontend_running():
            details.append("前端 (nginx) 已在运行，http://localhost:5166")
        else:
            ok, msg, pid = _win_start_frontend()
            details.append(msg)
            if not ok:
                details.append("  提示: 可稍后手动执行 broca service start 重试")
                # 前端失败不阻塞后端
    else:
        details.append("前端已跳过（安装时未构建）")

    _win_save_state(state)

    return {
        "success": True,
        "message": "后端服务已启动",
        "detail": "\n".join(details),
        "nginx": {"ok": _win_frontend_running(), "message": "nginx 前端服务"},
    }


def _win_bare_stop_services() -> dict[str, Any]:
    """Windows (裸起): 停止所有服务进程"""
    state = _win_load_state()
    details = []

    # 停止后端
    backend_pid = state.get("backend")
    if _win_is_process_alive(backend_pid):
        _win_stop_process(backend_pid)
        details.append(f"后端已停止 (PID: {backend_pid})")
    state["backend"] = None

    # 停止前端 (nginx)
    if _win_frontend_running():
        ok, msg = _win_stop_frontend()
        details.append(msg)
    else:
        details.append("前端 (nginx) 未运行")

    _win_save_state(state)

    if not details:
        details.append("没有运行中的服务")

    return {
        "success": True,
        "message": "所有服务已停止",
        "detail": "\n".join(details),
        "nginx": {"ok": True, "message": "前端 (nginx) 已停止"},
    }


def _win_bare_status_services() -> dict[str, Any]:
    """Windows (裸起): 查询服务状态"""
    state = _win_load_state()
    services = []

    # 后端
    backend_pid = state.get("backend")
    backend_alive = _win_is_process_alive(backend_pid)
    services.append(
        {
            "name": "backend",
            "status": "RUNNING" if backend_alive else "STOPPED",
            "pid": backend_pid if backend_alive else None,
            "uptime": None,
        }
    )

    # 前端 (nginx)
    frontend_alive = _win_frontend_running()
    services.append(
        {
            "name": "frontend (nginx)",
            "status": "RUNNING" if frontend_alive else "STOPPED",
            "pid": None,
            "uptime": None,
        }
    )

    return {
        "supervisord_running": backend_alive or frontend_alive,
        "services": services,
    }


# ---- Windows 分发入口：优先 NSSM 服务，否则裸起 ----


def _win_start_services(wait: bool = True) -> dict[str, Any]:
    """Windows: 启动服务（有 NSSM 服务用服务，否则裸起）"""
    if _win_nssm_available():
        logger.info("使用 NSSM Windows 服务管理")
        return _win_nssm_start_services(wait=wait)
    logger.info("未检测到 NSSM 服务，使用裸起进程管理")
    return _win_bare_start_services(wait=wait)


def _win_stop_services() -> dict[str, Any]:
    """Windows: 停止服务（有 NSSM 服务用服务，否则裸起）"""
    if _win_nssm_available():
        logger.info("使用 NSSM Windows 服务管理")
        return _win_nssm_stop_services()
    logger.info("未检测到 NSSM 服务，使用裸起进程管理")
    return _win_bare_stop_services()


def _win_status_services() -> dict[str, Any]:
    """Windows: 查询状态（有 NSSM 服务用服务，否则裸起）"""
    if _win_nssm_available():
        return _win_nssm_status_services()
    return _win_bare_status_services()


# ==================== 公开 API ====================


def status_services() -> dict[str, Any]:
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
    # Windows 使用原生进程管理
    if _is_windows():
        return _win_status_services()

    result: dict[str, Any] = {
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
            services.append(
                {
                    "name": parts[0],
                    "status": parts[1],
                    "pid": int(parts[2]) if parts[2].isdigit() else None,
                    "uptime": " ".join(parts[3:]) if len(parts) > 3 else None,
                }
            )
        else:
            services.append(
                {
                    "name": parts[0] if parts else "?",
                    "status": " ".join(parts[1:]) if len(parts) > 1 else "?",
                    "pid": None,
                    "uptime": None,
                }
            )

    result["services"] = services

    # 添加 nginx 前端服务状态（仅当安装时未跳过前端）
    if not _is_frontend_skipped():
        nginx_status = _get_frontend_status()
        result["nginx"] = nginx_status
        if nginx_status.get("available"):
            result["services"].append(
                {
                    "name": "frontend (nginx)",
                    "status": "ENABLED" if nginx_status["enabled"] else "DISABLED",
                    "pid": None,
                    "uptime": None,
                    "detail": nginx_status.get("version", ""),
                }
            )
    else:
        result["nginx"] = {
            "available": False,
            "enabled": False,
            "note": "安装时跳过了前端部署",
        }

    return result


def start_services(wait: bool = True) -> dict[str, Any]:
    """
    启动所有服务

    Linux: supervisord + 托管程序 + nginx 前端
    Windows: 原生 subprocess 进程管理（uvicorn + http.server）

    Args:
        wait: 是否等待服务就绪

    Returns:
        状态字典
    """
    # Windows 使用原生进程管理（supervisor 不支持 Windows）
    if _is_windows():
        return _win_start_services(wait=wait)

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
            # Windows 上 nodaemon=true，supervisord 在前台运行，必须用 Popen 后台启动
            proc = subprocess.Popen(
                supervisord_cmd.split() + ["-c", str(SUPERVISOR_CONF)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as e:
            return {"success": False, "error": f"启动 supervisord 失败: {e}"}

        # 等待 socket 就绪
        if not _wait_for_socket(timeout=8.0):
            # 收集 supervisord 启动错误信息
            err_detail = ""
            try:
                if proc.poll() is not None:
                    # 进程已退出，读取错误输出
                    _, stderr = proc.communicate(timeout=2)
                    err_detail = f"\nsupervisord 退出码: {proc.returncode}"
                    if stderr:
                        err_detail += f"\nstderr: {stderr.decode('utf-8', errors='replace')[:2000]}"
                else:
                    # 进程还在但 socket 未就绪
                    proc.terminate()
                    err_detail = (
                        "\nsupervisord 进程仍在运行但未监听端口，可能配置有问题"
                    )
            except Exception:
                pass
            return {
                "success": False,
                "error": f"supervisord 启动超时 (socket 未就绪){err_detail}",
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

    # Step 4: 启动 nginx 前端（仅当安装时未跳过前端）
    if not _is_frontend_skipped():
        logger.info("Starting nginx frontend...")
        nginx_ok, nginx_msg = _enable_broca_site()
        if not nginx_ok:
            logger.warning("nginx 启动失败: %s", nginx_msg)
    else:
        nginx_ok, nginx_msg = True, "前端已跳过（未安装 nginx）"

    return {
        "success": True,
        "message": "所有服务已启动",
        "detail": stdout,
        "nginx": {"ok": nginx_ok, "message": nginx_msg},
    }


def stop_services() -> dict[str, Any]:
    """
    停止所有服务

    Linux: 停止 supervisord 托管程序 + nginx
    Windows: 停止原生管理的进程

    Returns:
        状态字典
    """
    # Windows 使用原生进程管理
    if _is_windows():
        return _win_stop_services()

    nginx_ok = True
    nginx_msg = ""

    # 先停止 nginx 前端（仅当安装时未跳过前端）
    if not _is_frontend_skipped():
        if _broca_site_enabled():
            logger.info("Disabling broca nginx site...")
            nginx_ok, nginx_msg = _disable_broca_site()
    else:
        nginx_msg = "前端已跳过（未安装 nginx）"

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


def restart_services() -> dict[str, Any]:
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
    生成 supervisor 配置内容（nginx 代理模式，支持 Windows/Linux）

    Args:
        backend_port: 后端端口

    Returns:
        配置文本
    """
    win = _is_windows()

    # 检测后端启动命令（优先级: install.json 记录的 venv > ~/.broca/venv/ > 系统路径）
    install_info = _load_install_info()
    venv_path_str = install_info.get("venv_path", "")

    if win:
        # Windows: 使用 venv 中的 python.exe -m uvicorn
        python_cmd = None
        if venv_path_str:
            candidate = Path(venv_path_str) / "Scripts" / "python.exe"
            if candidate.exists():
                python_cmd = str(candidate)
        if not python_cmd:
            candidate = BROCA_HOME / "venv" / "Scripts" / "python.exe"
            if candidate.exists():
                python_cmd = str(candidate)
        if not python_cmd:
            python_cmd = sys.executable
        uvicorn_cmd = f"{python_cmd} -m uvicorn"
        backend_dir = BROCA_HOME / "web" / "backend"
        env_sep = ";"  # Windows PATH 分隔符
        env_prefix = f'PYTHONPATH="{backend_dir}"'
    else:
        # Unix/Linux: 使用 bin/uvicorn
        uvicorn_cmd = "uvicorn"  # 默认
        if venv_path_str:
            candidate = Path(venv_path_str) / "bin" / "uvicorn"
            if candidate.exists():
                uvicorn_cmd = str(candidate)
        if uvicorn_cmd == "uvicorn":
            candidate = BROCA_HOME / "venv" / "bin" / "uvicorn"
            if candidate.exists():
                uvicorn_cmd = str(candidate)
        backend_dir = BROCA_HOME / "web" / "backend"
        env_sep = ":"
        env_prefix = f'PYTHONPATH="{backend_dir}:$PYTHONPATH"'

    # 公共配置段
    if win:
        http_section = [
            "[inet_http_server]",
            "port = 127.0.0.1:9001",
        ]
        supervisor_section = [
            "[supervisord]",
            f"logfile={LOG_DIR}\\supervisord.log",
            "logfile_maxbytes=50MB",
            "logfile_backups=10",
            "loglevel=info",
            f"pidfile={RUN_DIR}\\supervisord.pid",
            # Windows 无 os.fork()，必须以非守护模式运行
            "nodaemon=true",
        ]
        ctl_url = "http://127.0.0.1:9001"
        user_line = None
    else:
        http_section = [
            "[unix_http_server]",
            f"file={SUPERVISOR_DIR}/supervisor.sock",
            "chmod=0700",
        ]
        supervisor_section = [
            "[supervisord]",
            f"logfile={LOG_DIR}/supervisord.log",
            "logfile_maxbytes=50MB",
            "logfile_backups=10",
            "loglevel=info",
            f"pidfile={RUN_DIR}/supervisord.pid",
            "nodaemon=false",
            f"user={os.environ.get('USER', 'root')}",
        ]
        ctl_url = f"unix://{SUPERVISOR_DIR}/supervisor.sock"
        user_line = f"user={os.environ.get('USER', 'root')}"

    lines = (
        [
            "; Broca - Supervisor 配置",
            f"; 安装目录: {BROCA_HOME}",
            f"; 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]
        + http_section
        + [
            "",
        ]
        + supervisor_section
        + [
            "",
            "[rpcinterface:supervisor]",
            "supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface",
            "",
            "[supervisorctl]",
            f"serverurl={ctl_url}",
            "",
            "; ====================",
            "; Backend (FastAPI / Uvicorn)",
            "; ====================",
            "[program:backend]",
            f"command={uvicorn_cmd} app.main:app --host 127.0.0.1 --port {backend_port} --log-level info",
            f"directory={backend_dir}",
        ]
    )
    if user_line:
        lines.append(user_line)
    lines += [
        "autostart=true",
        "autorestart=true",
        "startretries=3",
        f"stderr_logfile={LOG_DIR}/backend.err.log",
        f"stdout_logfile={LOG_DIR}/backend.out.log",
        "stdout_logfile_maxbytes=20MB",
        "stderr_logfile_maxbytes=20MB",
        f'environment={env_prefix},BROCA_CONFIG="{BROCA_HOME}/configs/configs.json",BROCA_DATABASE_DIR="{BROCA_HOME}/data",BROCA_LLM_CONFIG="{BROCA_HOME}/configs/llm_config.json",BROCA_AGENTS_CONFIG_DIR="{BROCA_HOME}/configs/agents",BROCA_LOG_DIR="{BROCA_HOME}/logs",SQLITE_DATABASE_PATH="sqlite:///{BROCA_HOME}/data/backend.db"',
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
    if not _is_windows():
        SUPERVISOR_CONF.chmod(0o600)  # 限制权限，防止路径/配置泄露（Unix 专用）
    logger.info("Supervisor config written to %s", SUPERVISOR_CONF)
    return str(SUPERVISOR_CONF)
