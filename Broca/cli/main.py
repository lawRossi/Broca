"""
Broca CLI - Command Line Interface Entry Point

This module provides a CLI entry point for the Broca TUI application.
"""

import asyncio
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def main():
    """Main entry point"""
    from Broca.cli.tui import main as tui_main

    try:
        asyncio.run(tui_main())
    except KeyboardInterrupt:
        print("\nGoodbye!")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
