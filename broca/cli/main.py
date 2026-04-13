"""
Broca CLI - Command Line Interface Entry Point
"""

import argparse
import asyncio
import subprocess
import sys
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


def get_web_backend_path():
    """Get the web backend directory path"""
    return Path(__file__).parent.parent / "web" / "backend"


def get_web_frontend_path():
    """Get the web frontend directory path"""
    return Path(__file__).parent.parent / "web" / "frontend"


def run_tui():
    """Launch the Text User Interface"""
    try:
        logger.debug("Starting TUI")
        from broca.cli.tui import main as tui_main

        asyncio.run(tui_main())
    except ImportError as e:
        logger.error(f"Error: Could not import TUI module: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nGoodbye!")
    except Exception as e:
        logger.error(f"Error launching TUI: {e}")
        sys.exit(1)


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
                proc.wait(timeout=5)
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


def create_parser():
    """Create the argument parser with all commands and options"""
    parser = argparse.ArgumentParser(
        prog="Broca",
        description=f"Broca {get_version()} - A lightweight agent framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  Broca                    Launch the TUI interface
  Broca web                Start all web services
  Broca web frontend       Start only the frontend
  Broca web backend        Start only the backend
  Broca version            Show version information
        """,
    )

    parser.add_argument("--version", action="version", version=f"Broca {get_version()}")
    parser.add_argument(
        "--server", default="http://localhost:6868", help="Socket.io server URL"
    )
    parser.add_argument("--session", "-s", default=None, help="Session identifier")

    # Web subcommand
    web_parser = parser.add_subparsers(
        dest="command",
        title="commands",
        description="Available commands",
        metavar="command",
    )

    # Web command - start all services by default
    web_sub = web_parser.add_parser(
        "web",
        help="Start the web frontend and/or backend services",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  Broca web                           Start all services
  Broca web --frontend-port 8080      Start with custom frontend port
  Broca web frontend                  Start only frontend
  Broca web backend --port 9000       Start only backend with custom port
""",
    )

    # Add shared options to web (for starting all services without subcommand)
    web_sub.add_argument(
        "--frontend-host",
        default="0.0.0.0",
        help="Frontend host address (default: 0.0.0.0)",
    )
    web_sub.add_argument(
        "--frontend-port",
        type=int,
        default=5166,
        help="Frontend port number (default: 5166)",
    )
    web_sub.add_argument(
        "--backend-host",
        default="127.0.0.1",
        help="Backend host address (default: 127.0.0.1)",
    )
    web_sub.add_argument(
        "--backend-port",
        type=int,
        default=9000,
        help="Backend port number (default: 9000)",
    )
    web_sub.add_argument(
        "--reload", action="store_true", help="Enable backend auto-reload"
    )

    # Second level subparsers for web command
    web_subparsers = web_sub.add_subparsers(
        dest="web_command",
        title="web commands",
        description="Web service commands",
    )

    # Frontend subcommand
    frontend_sub = web_subparsers.add_parser(
        "frontend",
        help="Start only the frontend service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    frontend_sub.add_argument("--host", default="0.0.0.0", help="Frontend host address")
    frontend_sub.add_argument(
        "--port", type=int, default=5166, help="Frontend port number (default: 5166)"
    )

    # Backend subcommand
    backend_sub = web_subparsers.add_parser(
        "backend",
        help="Start only the backend service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    backend_sub.add_argument(
        "--host", default="127.0.0.1", help="Backend host address (default: 127.0.0.1)"
    )
    backend_sub.add_argument(
        "--port", type=int, default=9000, help="Backend port number (default: 9000)"
    )
    backend_sub.add_argument(
        "--no-reload", action="store_true", help="Disable backend auto-reload"
    )

    return parser


def main():
    """Main entry point"""
    parser = create_parser()
    args = parser.parse_args()

    # Handle no command (run TUI)
    if args.command is None:
        run_tui()
        return

    # Route to appropriate handler
    if args.command == "web":
        web_command = getattr(args, "web_command", None)

        if web_command == "frontend":
            run_frontend_only(args.host, args.port)
        elif web_command == "backend":
            run_backend_only(args.host, args.port, args.reload)
        else:
            # No subcommand, start all services
            run_all_services(
                args.frontend_host,
                args.frontend_port,
                args.backend_host,
                args.backend_port,
                args.reload,
            )


if __name__ == "__main__":
    main()
