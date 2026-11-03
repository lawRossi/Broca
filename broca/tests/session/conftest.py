"""conftest for broca/tests/session/ — redirect DB to a temp file.

This prevents test data from leaking into the production database
(~/.broca/data/sessions.db).

Strategy: Override _database_config_cache at conftest module import time
(so it takes effect before any test module loads). Then an async fixture
creates tables in the temp DB before tests run.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

# ─── Module-level: override DB path before any test module is imported ───
# This runs when conftest.py is imported by pytest, which happens before
# any test file in this directory is collected/imported.

from broca.session import database as _db_module

# Create a persistent temp dir (session lifetime) for the test DB
_TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="broca_test_db_"))
_TEST_DB_PATH = str(_TEST_DB_DIR / "test_sessions.db")

# Override the cached config — this takes effect immediately
_db_module._database_config_cache = (str(_TEST_DB_DIR), _TEST_DB_PATH)

# Reset any pre-existing engine (from a previous test run in same process)
from broca.session.database import db_manager as _dm  # noqa: E402

if _dm._engine is not None:
    _dm._engine = None
    _dm._session_factory = None


# ─── Async fixture: create tables in the temp DB ───


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _create_temp_tables():
    """Create all tables in the temp database before tests run."""
    from broca.session.database import db_manager
    from broca.session.models import BaseModel

    db_manager._ensure_initialized()
    async with db_manager._engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)
    yield


@pytest.fixture(scope="session", autouse=True)
def _cleanup_temp_db():
    """Ensure the temp engine is disposed after all tests."""
    yield
    from broca.session.database import db_manager

    if db_manager._engine is not None:
        db_manager._engine = None
        db_manager._session_factory = None
    _db_module._database_config_cache = None
