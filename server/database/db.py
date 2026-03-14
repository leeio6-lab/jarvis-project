"""Database connection management for aiosqlite."""

import aiosqlite

from server.database.models import SCHEMA

_db: aiosqlite.Connection | None = None


async def init_db(path: str = "jarvis.db") -> aiosqlite.Connection:
    global _db
    _db = await aiosqlite.connect(path)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(SCHEMA)
    await _db.commit()
    return _db


async def close_db() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None


def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("Database not initialized - call init_db() first")
    return _db
