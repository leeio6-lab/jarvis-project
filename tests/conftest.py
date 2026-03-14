"""Shared test fixtures — in-memory DB, test client."""

import pytest
import aiosqlite
from fastapi.testclient import TestClient

from server.database.models import SCHEMA
from server.database import db as db_module
from server.main import app


@pytest.fixture
async def db():
    """Provide an in-memory aiosqlite connection with schema applied."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA)
    await conn.commit()

    old = db_module._db
    db_module._db = conn
    yield conn
    db_module._db = old
    await conn.close()


@pytest.fixture
def client():
    """API test client with in-memory DB (lifespan-managed)."""
    import unittest.mock as mock
    import server.main as main_module

    original_init = db_module.init_db

    async def _init_memory(path: str = "jarvis.db"):
        return await original_init(":memory:")

    # Patch both the module attribute AND the name imported in main.py
    db_module.init_db = _init_memory
    with mock.patch.object(main_module, "init_db", _init_memory):
        with TestClient(app) as c:
            yield c
    db_module.init_db = original_init
