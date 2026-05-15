from collections.abc import AsyncGenerator

from app.core.db import async_session


async def get_db() -> AsyncGenerator:
    async with async_session() as s:
        yield s
