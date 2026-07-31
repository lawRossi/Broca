"""
Broca CLI - Command Line Interface Entry Point

用法:
  Broca                     启动 TUI 界面
  Broca web [...]           Web 服务 (开发模式)
  Broca service install     一键安装
  Broca service start       启动生产服务
  Broca service stop        停止生产服务
  Broca service restart     重启生产服务
  Broca service status      查看服务状态
  Broca version             显示版本
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from broca.logging_config import get_logger

logger = get_logger(__name__)


def get_version():
    """Get the current version of Broca"""
    try:
        version_file = Path(__file__).parent.parent.parent / "pyproject.toml"
        if version_file.exists():
            for line in version_file.read_text().splitlines():
                if line.startswith("version"):
                    return line.split("=")[1].strip().strip('"')
    except Exception:
        pass
    return "0.1.0"


# 延迟导入用于 Crew 编排
def _import_crew_config():
    from broca.orchestration.crew import CrewConfig, CrewConfigValidator
    return CrewConfig, CrewConfigValidator


def get_web_backend_path():
    """Get the web backend directory path"""
    return Path(__file__).parent.parent.parent / "broca-web" / "backend"


def get_web_frontend_path():
    """Get the web frontend directory path"""
    return Path(__file__).parent.parent.parent / "broca-web" / "frontend"


def check_pnpm():
    """Check if pnpm is installed"""
    try:
        subprocess.run(["pnpm", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def run_frontend(host: str = "127.0.0.1", port: int = 5166):
    """Start the frontend development server"""
    frontend_path = get_web_frontend_path()

    if not frontend_path.exists():
        print(f"Error: Frontend not found at {frontend_path}")
        return None

    if not check_pnpm():
        print("Error: pnpm is not installed. Please install pnpm first.")
        print("Visit: https://pnpm.io/installation")
        return None

    print(f"Starting frontend at http://{host}:{port}")

    try:
        cmd = ["sudo", "pnpm", "dev", "--host", host, "--port", str(port)]
        process = subprocess.Popen(
            cmd,
            cwd=frontend_path,
            stdout=None,  # 继承父进程 stdout
            stderr=None,  # 继承父进程 stderr
        )
        return process
    except Exception as e:
        print(f"Error starting frontend: {e}")
        return None


def run_backend(host: str = "127.0.0.1", port: int = 9000, reload: bool = True):
    """Start the backend service"""
    backend_path = get_web_backend_path()

    if not backend_path.exists():
        print(f"Error: Backend not found at {backend_path}")
        return None

    try:
        cmd = [
            "poetry",
            "run",
            "uvicorn",
            "app.main:app",
            "--host",
            host,
            "--port",
            str(port),
        ]

        if reload:
            cmd.append("--reload")

        print(f"Starting backend at http://{host}:{port}")

        process = subprocess.Popen(
            cmd,
            cwd=str(backend_path),
            stdout=None,  # 继承父进程 stdout
            stderr=None,  # 继承父进程 stderr
        )

        return process
    except Exception as e:
        print(f"Error starting backend: {e}")
        return None


def run_all_services(
    frontend_host="127.0.0.1",
    frontend_port=5166,
    backend_host="127.0.0.1",
    backend_port=9000,
    reload=False,
):
    """Start both frontend and backend services"""
    import time

    frontend_process = None
    backend_process = None

    try:
        print("=" * 50)
        print("Starting Broca Web Services")
        print("=" * 50)
        print()

        frontend_process = run_frontend(frontend_host, frontend_port)
        if not frontend_process:
            sys.exit(1)

        backend_process = run_backend(backend_host, backend_port, reload)
        if not backend_process:
            if frontend_process and frontend_process.poll() is None:
                frontend_process.terminate()
            sys.exit(1)

        print()
        print("=" * 50)
        print("Services started successfully!")
        print("=" * 50)
        print()
        print(f"Frontend: http://{frontend_host}:{frontend_port}")
        print(f"Backend:  http://{backend_host}:{backend_port}")
        print()
        print("Press Ctrl+C to stop all services")
        print("=" * 50)
        print()

        while True:
            frontend_exited = frontend_process.poll() is not None
            backend_exited = backend_process.poll() is not None

            if frontend_exited or backend_exited:
                if frontend_exited:
                    print("Frontend process stopped unexpectedly")
                if backend_exited:
                    print("Backend process stopped unexpectedly")

                # 终止仍在运行的进程
                if frontend_process and frontend_process.poll() is None:
                    print("Stopping frontend...")
                    frontend_process.terminate()
                    try:
                        frontend_process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        print("Frontend did not stop, forcing...")
                        frontend_process.kill()

                if backend_process and backend_process.poll() is None:
                    print("Stopping backend...")
                    backend_process.terminate()
                    try:
                        backend_process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        print("Backend did not stop, forcing...")
                        backend_process.kill()

                break

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\nShutting down services...")
    finally:
        # 优雅终止所有进程
        processes = []
        if frontend_process and frontend_process.poll() is None:
            processes.append(("Frontend", frontend_process))
        if backend_process and backend_process.poll() is None:
            processes.append(("Backend", backend_process))

        for name, proc in processes:
            print(f"Stopping {name}...")
            proc.terminate()
            try:
                proc.wait(timeout=15)
                print(f"{name} stopped")
            except subprocess.TimeoutExpired:
                print(f"{name} did not stop, forcing...")
                proc.kill()
                try:
                    proc.wait(timeout=2)
                    print(f"{name} killed")
                except subprocess.TimeoutExpired:
                    print(f"{name} could not be stopped")

        print("All services stopped")


def run_frontend_only(host="127.0.0.1", port=5166):
    """Start only the frontend service"""
    import time

    if not check_pnpm():
        print("Error: pnpm is not installed. Please install pnpm first.")
        print("Visit: https://pnpm.io/installation")
        sys.exit(1)

    frontend_process = None

    try:
        print("=" * 50)
        print("Starting Broca Frontend")
        print("=" * 50)

        frontend_process = run_frontend(host, port)
        if not frontend_process:
            sys.exit(1)

        print()
        print("=" * 50)
        print(f"Frontend started at http://{host}:{port}")
        print("Press Ctrl+C to stop")
        print("=" * 50)

        while frontend_process.poll() is None:
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\nShutting down frontend...")
    finally:
        if frontend_process and frontend_process.poll() is None:
            print("Stopping frontend...")
            frontend_process.terminate()
            try:
                frontend_process.wait(timeout=5)
                print("Frontend stopped")
            except subprocess.TimeoutExpired:
                print("Frontend did not stop, forcing...")
                frontend_process.kill()
                try:
                    frontend_process.wait(timeout=2)
                    print("Frontend killed")
                except subprocess.TimeoutExpired:
                    print("Frontend could not be stopped")


def run_backend_only(host="127.0.0.1", port=9000, reload=False):
    """Start only the backend service"""
    import time

    backend_process = None

    try:
        print("=" * 50)
        print("Starting Broca Backend")
        print("=" * 50)

        backend_process = run_backend(host, port, reload)
        if not backend_process:
            sys.exit(1)

        print()
        print("=" * 50)
        print(f"Backend started at http://{host}:{port}")
        print("Press Ctrl+C to stop")
        print("=" * 50)

        while backend_process.poll() is None:
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\nShutting down backend...")
    finally:
        if backend_process and backend_process.poll() is None:
            print("Stopping backend...")
            backend_process.terminate()
            try:
                backend_process.wait(timeout=5)
                print("Backend stopped")
            except subprocess.TimeoutExpired:
                print("Backend did not stop, forcing...")
                backend_process.kill()
                try:
                    backend_process.wait(timeout=2)
                    print("Backend killed")
                except subprocess.TimeoutExpired:
                    print("Backend could not be stopped")


# ======================================================================
# Service Management (基于 supervisor 的生产环境服务管理)
# ======================================================================


def cmd_service_install():
    """执行一键安装"""
    install_script = Path(__file__).parent.parent.parent / "scripts" / "install.sh"
    if not install_script.exists():
        print(f"Error: 安装脚本未找到: {install_script}")
        sys.exit(1)

    print("=" * 60)
    print("  Broca 一键安装")
    print("=" * 60)
    print()

    # 以交互方式运行安装脚本
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        ["bash", str(install_script)],
        stdout=None,
        stderr=None,
        env=env,
    )
    proc.wait()

    if proc.returncode != 0:
        print(f"\n安装失败 (exit code: {proc.returncode})")
        sys.exit(proc.returncode)

    print()
    print("=" * 60)
    print("  安装完成！使用以下命令管理服务：")
    print()
    print("    Broca service start     启动服务")
    print("    Broca service stop      停止服务")
    print("    Broca service restart   重启服务")
    print("    Broca service status    查看状态")
    print("=" * 60)


def cmd_service_start(args):
    """启动生产环境服务"""
    # 延迟导入，允许在未安装时也能查看帮助
    from broca.service_manager import start_services, status_services

    print("正在启动 Broca 服务...")

    # 先检查服务是否已运行，如果已运行则直接启动托管程序
    status = status_services()
    if status.get("supervisord_running"):
        print("服务已在运行，检查托管程序...")
    else:
        print("启动 Broca 服务管理器...")

    result = start_services(wait=True)

    if result.get("success"):
        print(f"✅ {result['message']}")
        if result.get("detail"):
            for line in result["detail"].splitlines():
                if line.strip():
                    print(f"   {line.strip()}")

        # 显示 nginx 状态
        nginx_info = result.get("nginx", {})
        if nginx_info.get("ok"):
            print(f"   ✅ {nginx_info['message']}")
        elif not nginx_info.get("ok") and nginx_info.get("message"):
            print(f"   ⚠ {nginx_info['message']}")

        # 显示最终状态
        print()
        time.sleep(1)
        cmd_service_status(args)
    else:
        print(f"❌ 启动失败: {result.get('error')}")
        if result.get("stdout"):
            print(result["stdout"])
        sys.exit(1)


def cmd_service_stop(args):
    """停止生产环境服务"""
    from broca.service_manager import stop_services

    print("正在停止 Broca 服务...")
    result = stop_services()

    if result.get("success"):
        print(f"✅ {result['message']}")
        # 显示 nginx 状态
        nginx_info = result.get("nginx", {})
        if nginx_info.get("message"):
            print(f"   {nginx_info['message']}")
    else:
        print(f"❌ 停止失败: {result.get('error')}")
        sys.exit(1)


def cmd_service_restart(args):
    """重启生产环境服务 (基于 supervisor)"""
    from broca.service_manager import restart_services

    print("正在重启 Broca 服务...")
    result = restart_services()

    if result.get("success"):
        print(f"✅ {result['message']}")

        # 显示最终状态
        print()
        time.sleep(1)
        cmd_service_status(args)
    else:
        print(f"❌ 重启失败: {result.get('error')}")
        sys.exit(1)


def cmd_service_status(args):
    """查看服务状态"""
    from broca.service_manager import status_services

    result = status_services()

    print()
    print("=" * 50)
    print("  Broca 服务状态")
    print("=" * 50)
    print()

    if result.get("error"):
        print(f"⚠  {result['error']}")
        print()
        return

    if not result.get("supervisord_running"):
        print("⚠  服务未运行")
        print()
        print("  使用 Broca service start 启动服务")
        return

    print("  服务管理器:  ✅ 运行中")
    print()
    print(f"  {'服务名':<15} {'状态':<12} {'PID':<8} {'运行时间'}")
    print(f"  {'------':<15} {'------':<12} {'---':<8} {'--------'}")

    services = result.get("services", [])
    if not services:
        print("  (没有已注册的服务)")
    else:
        for svc in services:
            name = svc.get("name", "?")
            status = svc.get("status", "?")
            pid = svc.get("pid", "-")
            pid_str = str(pid) if pid else "-"
            uptime = svc.get("uptime", "")

            # 状态颜色标识
            if status.upper() in ("RUNNING",):
                status_display = f"✅ {status}"
            elif status.upper() in ("STOPPED", "EXITED", "FATAL"):
                status_display = f"❌ {status}"
            elif status.upper() == "STARTING":
                status_display = f"⏳ {status}"
            else:
                status_display = f"❓ {status}"

            print(f"  {name:<15} {status_display:<12} {pid_str:<8} {uptime}")

    # 前端状态（仅 Linux 的 nginx 模式有该字段）
    nginx = result.get("nginx", {})
    if nginx.get("available"):
        nginx_status = "✅ 已启用" if nginx.get("enabled") else "⏸ 未启用"
        nginx_version = nginx.get("version", "")
        print()
        print("  前端服务 (nginx 站点):")
        print(f"    状态: {nginx_status}")
        if nginx_version:
            print(f"    版本: {nginx_version}")
        print(f"    配置文件: {nginx.get('site_config', '-')}")
    else:
        print()
        print("  前端服务: ⚠ nginx 未安装（静态文件需其他方式托管）")

    print()
    print("  提示: Broca service restart 重启所有服务")
    print()


def cmd_create_user(args):
    """创建 Web 后端管理员账户"""
    # 优先查找项目源码目录（开发模式）
    setup_script = (
        Path(__file__).parent.parent.parent
        / "broca-web" / "backend" / "scripts" / "setup_admin.py"
    )
    # 如果源码目录找不到，尝试 ~/.broca/web/（安装脚本部署的位置）
    if not setup_script.exists():
        setup_script = (
            Path.home() / ".broca" / "web" / "backend" / "scripts" / "setup_admin.py"
        )
    # 最后尝试 site-packages 同级目录（pip install 安装 broca-web 的情况）
    if not setup_script.exists():
        setup_script = (
            Path(__file__).parent.parent.parent
            / "broca_web" / "backend" / "scripts" / "setup_admin.py"
        )
    if not setup_script.exists():
        print("❌ 未找到 setup_admin.py")
        print("   请确保 broca-web/backend/scripts/setup_admin.py 存在。")
        print("   或先运行: broca service install")
        sys.exit(1)

    cmd = [sys.executable, str(setup_script)]
    if args.username:
        cmd.extend(["--username", args.username])
    if args.password:
        cmd.extend(["--password", args.password])
    if args.db:
        cmd.extend(["--db", args.db])

    if args.username and args.password:
        cmd.append("--non-interactive")

    print("=" * 50)
    print("  创建管理员账户")
    print("=" * 50)
    print()

    env = os.environ.copy()
    proc = subprocess.run(cmd, env=env)
    sys.exit(proc.returncode)


# ======================================================================
# Argument Parser
# ======================================================================


def create_parser():
    """Create the argument parser with all commands and options"""
    parser = argparse.ArgumentParser(
        prog="Broca",
        description=f"Broca {get_version()} - A lightweight agent framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  Broca                          Launch the TUI interface
  Broca web                      Start all web services (dev mode)
  Broca service install          One-click installation
  Broca service start            Start production services
  Broca service stop             Stop production services
  Broca service restart          Restart production services
  Broca service status           Show service status
  Broca create-user              Create an admin user for the Web backend
  Broca version                  Show version information
        """,
    )

    parser.add_argument("--version", action="version", version=f"Broca {get_version()}")
    parser.add_argument(
        "--server", default="http://localhost:6868", help="Socket.io server URL"
    )
    parser.add_argument("--session", "-s", default=None, help="Session identifier")

    # Subparsers
    sub = parser.add_subparsers(
        dest="command",
        title="commands",
        description="Available commands",
        metavar="command",
    )

    # ---- web command (dev mode) ----
    web_sub = sub.add_parser(
        "web",
        help="Start the web frontend and/or backend services (dev mode)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  Broca web                           Start all services
  Broca web --frontend-port 8080      Start with custom frontend port
  Broca web frontend                  Start only frontend
  Broca web backend --port 9000       Start only backend with custom port
""",
    )
    web_sub.add_argument(
        "--frontend-host", default="0.0.0.0", help="Frontend host address (default: 0.0.0.0)"
    )
    web_sub.add_argument(
        "--frontend-port", type=int, default=5166, help="Frontend port number (default: 5166)"
    )
    web_sub.add_argument(
        "--backend-host", default="127.0.0.1", help="Backend host address (default: 127.0.0.1)"
    )
    web_sub.add_argument(
        "--backend-port", type=int, default=9000, help="Backend port number (default: 9000)"
    )
    web_sub.add_argument(
        "--reload", action="store_true", help="Enable backend auto-reload"
    )
    web_sub.subcommands = web_sub.add_subparsers(
        dest="web_command", title="web commands",
    )
    frontend_sub = web_sub.subcommands.add_parser("frontend", help="Start only the frontend service")
    frontend_sub.add_argument("--host", default="0.0.0.0", help="Frontend host address")
    frontend_sub.add_argument("--port", type=int, default=5166, help="Frontend port number")
    backend_sub = web_sub.subcommands.add_parser("backend", help="Start only the backend service")
    backend_sub.add_argument("--host", default="127.0.0.1", help="Backend host address")
    backend_sub.add_argument("--port", type=int, default=9000, help="Backend port number")
    backend_sub.add_argument("--no-reload", action="store_true", help="Disable backend auto-reload")

    # ---- run command (crew orchestration) ----
    run_sub = sub.add_parser(
        "run",
        help="Run a Crew orchestration from a YAML configuration file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  Broca run ./discussion.yaml              Run a round-table discussion
  Broca run ./research.yaml                Run a research workflow
  Broca run --validate ./config.yaml       Validate a crew config without running
""",
    )
    run_sub.add_argument(
        "yaml_file",
        help="Path to the Crew YAML configuration file",
    )
    run_sub.add_argument(
        "--validate", action="store_true",
        help="Only validate the configuration, don't execute",
    )
    run_sub.add_argument(
        "--server", default="http://localhost:6868",
        help="Socket.io server URL (default: http://localhost:6868)",
    )

    # ---- service command (production mode) ----
    svc_sub = sub.add_parser(
        "service",
        help="Manage Broca production services (based on supervisor)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  Broca service install          One-click installation
  Broca service start            Start all services
  Broca service stop             Stop all services
  Broca service restart          Restart all services
  Broca service status           Show service status
""",
    )
    svc_sub.subcommands = svc_sub.add_subparsers(
        dest="service_command",
        title="service commands",
        description="Available service commands",
    )

    # service install
    svc_sub.subcommands.add_parser("install", help="One-click installation of Broca")

    # service start
    svc_start = svc_sub.subcommands.add_parser("start", help="Start all services")
    svc_start.add_argument(
        "--backend-port", type=int, default=9000,
        help="Backend port (default: 9000)"
    )
    svc_start.add_argument(
        "--frontend-port", type=int, default=5166,
        help="Frontend port (default: 5166)"
    )

    # service stop
    svc_sub.subcommands.add_parser("stop", help="Stop all services")
    # service restart
    svc_sub.subcommands.add_parser("restart", help="Restart all services")
    # service status
    svc_sub.subcommands.add_parser("status", help="Show service status")

    # ---- create-user command ----
    create_user_sub = sub.add_parser(
        "create-user",
        help="Create an admin user for the Web backend",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  Broca create-user                      Interactive mode
  Broca create-user --username admin     Specify username
  Broca create-user --username admin --password mypass  Non-interactive
""",
    )
    create_user_sub.add_argument(
        "--username", default=None, help="Admin username (default: admin, prompts if empty)"
    )
    create_user_sub.add_argument(
        "--password", default=None, help="Admin password (prompts if empty)"
    )
    create_user_sub.add_argument(
        "--db", default=None, help="Database URL (e.g. sqlite:///path/to/backend.db)"
    )

    # ---- tui command ----
    tui_sub = sub.add_parser(
        "tui",
        help="Launch the Terminal User Interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  Broca tui                        Launch TUI with session list
  Broca tui --session <id>         Open specific session directly
  Broca tui --server <url>         Connect to custom server
""",
    )
    tui_sub.add_argument(
        "--session", "-s", default=None, help="Session ID to open directly"
    )
    tui_sub.add_argument(
        "--server", default=None, help="Socket.IO server URL"
    )

    return parser


def main():
    """Main entry point"""
    # 自动将当前 Python 所在目录（即虚拟环境的 bin/）加入 PATH
    # 这样子进程（如 uvicorn、supervisord 等）无需手动激活虚拟环境即可找到
    venv_bin = str(Path(sys.executable).parent)
    current_path = os.environ.get("PATH", "")
    if venv_bin not in current_path.split(os.pathsep):
        os.environ["PATH"] = f"{venv_bin}{os.pathsep}{current_path}"

    parser = create_parser()
    args = parser.parse_args()

    command = getattr(args, "command", None)

    # ---- service commands ----
    if command == "service":
        svc_cmd = getattr(args, "service_command", None)

        if svc_cmd == "install":
            cmd_service_install()
        elif svc_cmd == "start":
            cmd_service_start(args)
        elif svc_cmd == "stop":
            cmd_service_stop(args)
        elif svc_cmd == "restart":
            cmd_service_restart(args)
        elif svc_cmd == "status":
            cmd_service_status(args)
        else:
            # 没有子命令时显示帮助
            parser.parse_args(["service", "--help"])

    # ---- web commands ----
    elif command == "web":
        web_command = getattr(args, "web_command", None)

        if web_command == "frontend":
            run_frontend_only(args.host, args.port)
        elif web_command == "backend":
            run_backend_only(args.host, args.port, not args.no_reload)
        else:
            run_all_services(
                args.frontend_host,
                args.frontend_port,
                args.backend_host,
                args.backend_port,
                args.reload,
            )

    # ---- create-user command ----
    elif command == "create-user":
        cmd_create_user(args)

    # ---- tui command ----
    elif command == "tui":
        _launch_tui(session_id=args.session, server_url=getattr(args, "server", None))

    # ---- run commands ----
    elif command == "run":
        yaml_file = args.yaml_file
        server = getattr(args, "server", "http://localhost:6868")

        if not os.path.exists(yaml_file):
            print(f"Error: YAML file not found: {yaml_file}")
            sys.exit(1)

        if args.validate:
            # 仅校验模式
            from broca.orchestration.crew import CrewConfig, CrewConfigValidator

            print(f"Validating: {yaml_file}")
            errors = CrewConfigValidator.validate_yaml_file(yaml_file)
            if errors:
                print("❌ Validation failed:")
                for err in errors:
                    print(f"  - {err}")
                sys.exit(1)
            else:
                print("✅ Configuration is valid")
                # 显示配置预览
                config = CrewConfig.from_yaml_file(yaml_file)
                print(f"\nCrew: {config.name}")
                print(f"  Description: {config.description}")
                print(f"  Orchestrator: {config.orchestrator.type.value}")
                print(f"  Agents ({len(config.agents)}):")
                for a in config.agents:
                    print(f"    - {a.name} ({a.role.value})")
                sys.exit(0)
        else:
            # 执行模式
            print(f"Starting crew orchestration from: {yaml_file}")
            print(f"Server: {server}")
            print()
            print("Note: Crew orchestration requires a running Broca session.")
            print("Use 'broca run' in an active agent session or via the Web API.")
            print()
            print("To run via Web API:")
            print('  curl -X POST http://localhost:9000/api/crews \\')
            print('    -H "Content-Type: application/json" \\')
            print(f'    -d \'{{"yaml_path": "{yaml_file}"}}\'')
            print()

            # 尝试通过 Web API 提交
            import json
            import urllib.request

            try:
                data = json.dumps({"yaml_path": os.path.abspath(yaml_file)}).encode()
                req = urllib.request.Request(
                    f"{server.replace(':6868', ':9000')}/api/crews",
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    result = json.loads(resp.read())
                    print("✅ Crew submitted successfully!")
                    print(f"  Execution ID: {result.get('execution_id', 'N/A')}")
                    print(f"  Status: {result.get('status', 'N/A')}")
            except Exception as e:
                print(f"⚠ Could not submit via Web API: {e}")
                print()
                print("Alternative: Start an agent session and use load_skill + execute-tasks")

    # ---- no command (TUI) ----
    elif command is None:
        # 默认行为：启动 TUI（如果存在）
        _launch_tui(session_id=args.session, server_url=getattr(args, "server", None))

    else:
        parser.print_help()


def _launch_tui(session_id=None, server_url=None):
    """Launch the Broca Terminal User Interface.

    Args:
        session_id: Optional session ID to open directly
        server_url: Optional Socket.IO server URL override
    """
    import os

    # Set server URL via environment variable if provided
    if server_url:
        os.environ["BROCA_SOCKET_SERVER_URL"] = server_url

    try:
        from broca_tui.app import BrocaTUIApp
        app = BrocaTUIApp(session_id=session_id)
        app.run()
    except ImportError as e:
        print(f"Error: TUI not available ({e})")
        print()
        print("Install broca-tui with:")
        print("  pip install -e broca-tui/")
        print()
        print("Or install from the project root:")
        print("  cd /path/to/broca && pip install -e broca-tui/")
        sys.exit(1)


if __name__ == "__main__":
    main()
