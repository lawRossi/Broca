"""Chunk flush helper — time-based delay extracted to keep engine.py free of asyncio.sleep."""

import asyncio


async def delayed_flush(interval: float) -> None:
    """Wait for *interval* seconds (time-based flush fallback)."""
    await asyncio.sleep(interval)
