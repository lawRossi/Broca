"""
Terminal User Interface for Broca CLI

This is the main entry point for the TUI application.
Provides a rich TUI experience with persistent screen layout,
real-time message updates, and connection management.
"""

import argparse
import asyncio
from typing import Optional

from loguru import logger

from broca.session.database import db_manager

from .tui_app import BrocaTUIApp

logger.remove()
logger.add("tui.log", level="DEBUG")


class TUI:
    """
    Terminal User Interface for Broca CLI

    This is a wrapper around the Textual app for backwards compatibility.
    """

    def __init__(
        self,
        server_url: str = "http://localhost:8001",
        client_type: str = "cli",
        client_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        """
        Initialize TUI

        Args:
            server_url: Socket.io server URL
            client_type: Client type
            client_id: Client identifier
            user_id: User identifier
            session_id: Session identifier (if not provided, will generate one and initialize agent)
        """
        self.server_url = server_url
        self.client_type = client_type
        self.client_id = client_id or f"{client_type}_{id(self)}"
        self.user_id = user_id
        self.session_id = session_id

        self.app = BrocaTUIApp(
            server_url=server_url,
            client_type=client_type,
            client_id=client_id,
            user_id=user_id,
            session_id=session_id,
        )

    def register_event_handler(self, event_name: str, func: callable):
        """Register event handler"""
        self.app.register_event_handler(event_name, func)

    async def run(self):
        """Run the TUI"""
        await self.app.run_async()


async def main():
    """Main entry point for TUI"""

    parser = argparse.ArgumentParser(description="Broca CLI - Terminal User Interface")
    parser.add_argument(
        "--server", "-s", default="http://localhost:8001", help="Socket.io server URL"
    )
    parser.add_argument("--client-type", "-t", default="cli", help="Client type")
    parser.add_argument("--client-id", "-c", default=None, help="Client identifier")
    parser.add_argument("--user-id", "-u", default=None, help="User identifier")
    parser.add_argument(
        "--session-id",
        "-i",
        default=None,
        help="Session identifier (if not provided, will generate one and initialize agent)",
    )

    args = parser.parse_args()

    # setup tables
    await db_manager.init_tables()

    # Create and run TUI
    tui = TUI(
        server_url=args.server,
        client_type=args.client_type,
        client_id=args.client_id,
        user_id=args.user_id,
        session_id=args.session_id,
    )

    try:
        await tui.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
