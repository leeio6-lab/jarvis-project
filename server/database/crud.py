"""CRUD operations for all J.A.R.V.I.S tables."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import aiosqlite


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows_to_dicts(rows: list[aiosqlite.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


# ── app_usage (mobile + pc app usage) ──────────────────────────────────

async def insert_app_usage(
    db: aiosqlite.Connection,
    *,
    device: str,
    package: str,
    app_name: str | None = None,
    started_at: str,
    ended_at: str | None = None,
    duration_s: int | None = None,
) -> int:
    cur = await db.execute(
        "INSERT INTO app_usage (device, package, app_name, started_at, ended_at, duration_s) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (device, package, app_name, started_at, ended_at, duration_s),
    )
    await db.commit()
    return cur.lastrowid  # type: ignore[return-value]


async def get_app_usage(
    db: aiosqlite.Connection,
    *,
    since: str | None = None,
    until: str | None = None,
    device: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses, params = [], []
    if since:
        clauses.append("started_at >= ?")
        params.append(since)
    if until:
        clauses.append("started_at <= ?")
        params.append(until)
    if device:
        clauses.append("device = ?")
        params.append(device)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = await db.execute_fetchall(
        f"SELECT * FROM app_usage {where} ORDER BY started_at DESC LIMIT ?",
        (*params, limit),
    )
    return _rows_to_dicts(rows)


async def get_app_usage_summary(
    db: aiosqlite.Connection,
    *,
    since: str,
    until: str,
    device: str | None = None,
) -> list[dict[str, Any]]:
    """Group by app_name, sum duration_s."""
    device_clause = "AND device = ?" if device else ""
    params: tuple = (since, until, device) if device else (since, until)
    rows = await db.execute_fetchall(
        f"SELECT COALESCE(app_name, package) AS app, device, "
        f"COUNT(*) AS sessions, SUM(duration_s) AS total_seconds "
        f"FROM app_usage WHERE started_at >= ? AND started_at <= ? {device_clause} "
        f"GROUP BY app, device ORDER BY total_seconds DESC",
        params,
    )
    return _rows_to_dicts(rows)


# ── pc_activity ────────────────────────────────────────────────────────

async def insert_pc_activity(
    db: aiosqlite.Connection,
    *,
    window_title: str,
    process_name: str | None = None,
    url: str | None = None,
    started_at: str,
    ended_at: str | None = None,
    duration_s: int | None = None,
    idle: bool = False,
) -> int:
    cur = await db.execute(
        "INSERT INTO pc_activity (window_title, process_name, url, started_at, ended_at, duration_s, idle) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (window_title, process_name, url, started_at, ended_at, duration_s, int(idle)),
    )
    await db.commit()
    return cur.lastrowid  # type: ignore[return-value]


async def get_pc_activity(
    db: aiosqlite.Connection,
    *,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses, params = [], []
    if since:
        clauses.append("started_at >= ?")
        params.append(since)
    if until:
        clauses.append("started_at <= ?")
        params.append(until)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = await db.execute_fetchall(
        f"SELECT * FROM pc_activity {where} ORDER BY started_at DESC LIMIT ?",
        (*params, limit),
    )
    return _rows_to_dicts(rows)


async def get_pc_activity_summary(
    db: aiosqlite.Connection,
    *,
    since: str,
    until: str,
) -> list[dict[str, Any]]:
    rows = await db.execute_fetchall(
        "SELECT process_name, COUNT(*) AS sessions, SUM(duration_s) AS total_seconds "
        "FROM pc_activity WHERE started_at >= ? AND started_at <= ? AND idle = 0 "
        "GROUP BY process_name ORDER BY total_seconds DESC",
        (since, until),
    )
    return _rows_to_dicts(rows)


# ── transcripts ────────────────────────────────────────────────────────

async def insert_transcript(
    db: aiosqlite.Connection,
    *,
    source: str = "mic",
    audio_path: str | None = None,
    text: str,
    summary: str | None = None,
    language: str = "ko",
    duration_s: float | None = None,
    recorded_at: str,
) -> int:
    cur = await db.execute(
        "INSERT INTO transcripts (source, audio_path, text, summary, language, duration_s, recorded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (source, audio_path, text, summary, language, duration_s, recorded_at),
    )
    await db.commit()
    return cur.lastrowid  # type: ignore[return-value]


async def get_transcripts(
    db: aiosqlite.Connection,
    *,
    since: str | None = None,
    until: str | None = None,
    source: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    clauses, params = [], []
    if since:
        clauses.append("recorded_at >= ?")
        params.append(since)
    if until:
        clauses.append("recorded_at <= ?")
        params.append(until)
    if source:
        clauses.append("source = ?")
        params.append(source)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = await db.execute_fetchall(
        f"SELECT * FROM transcripts {where} ORDER BY recorded_at DESC LIMIT ?",
        (*params, limit),
    )
    return _rows_to_dicts(rows)


# ── promises ───────────────────────────────────────────────────────────

async def insert_promise(
    db: aiosqlite.Connection,
    *,
    transcript_id: int | None = None,
    content: str,
    assignee: str | None = None,
    due_date: str | None = None,
) -> int:
    cur = await db.execute(
        "INSERT INTO promises (transcript_id, content, assignee, due_date) VALUES (?, ?, ?, ?)",
        (transcript_id, content, assignee, due_date),
    )
    await db.commit()
    return cur.lastrowid  # type: ignore[return-value]


async def get_promises(
    db: aiosqlite.Connection,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if status:
        rows = await db.execute_fetchall(
            "SELECT * FROM promises WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        )
    else:
        rows = await db.execute_fetchall(
            "SELECT * FROM promises ORDER BY created_at DESC LIMIT ?", (limit,)
        )
    return _rows_to_dicts(rows)


async def update_promise_status(
    db: aiosqlite.Connection, promise_id: int, status: str
) -> bool:
    cur = await db.execute(
        "UPDATE promises SET status = ? WHERE id = ?", (status, promise_id)
    )
    await db.commit()
    return cur.rowcount > 0


# ── email_tracking ─────────────────────────────────────────────────────

async def upsert_email(
    db: aiosqlite.Connection,
    *,
    gmail_id: str,
    subject: str,
    sender: str,
    received_at: str,
    replied: bool = False,
    replied_at: str | None = None,
    priority: str = "normal",
) -> int:
    cur = await db.execute(
        "INSERT INTO email_tracking (gmail_id, subject, sender, received_at, replied, replied_at, priority) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(gmail_id) DO UPDATE SET replied=excluded.replied, replied_at=excluded.replied_at, priority=excluded.priority",
        (gmail_id, subject, sender, received_at, int(replied), replied_at, priority),
    )
    await db.commit()
    return cur.lastrowid  # type: ignore[return-value]


async def get_unreplied_emails(
    db: aiosqlite.Connection, *, limit: int = 50
) -> list[dict[str, Any]]:
    rows = await db.execute_fetchall(
        "SELECT * FROM email_tracking WHERE replied = 0 ORDER BY received_at DESC LIMIT ?",
        (limit,),
    )
    return _rows_to_dicts(rows)


async def mark_email_replied(
    db: aiosqlite.Connection, gmail_id: str, replied_at: str | None = None
) -> bool:
    cur = await db.execute(
        "UPDATE email_tracking SET replied = 1, replied_at = ? WHERE gmail_id = ?",
        (replied_at or _now(), gmail_id),
    )
    await db.commit()
    return cur.rowcount > 0


# ── calendar_events ────────────────────────────────────────────────────

async def upsert_calendar_event(
    db: aiosqlite.Connection,
    *,
    google_event_id: str | None = None,
    title: str,
    description: str | None = None,
    start_time: str,
    end_time: str | None = None,
    location: str | None = None,
    attendees: str | None = None,
    status: str = "confirmed",
) -> int:
    if google_event_id:
        cur = await db.execute(
            "INSERT INTO calendar_events (google_event_id, title, description, start_time, end_time, location, attendees, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(google_event_id) DO UPDATE SET "
            "title=excluded.title, description=excluded.description, start_time=excluded.start_time, "
            "end_time=excluded.end_time, location=excluded.location, attendees=excluded.attendees, status=excluded.status",
            (google_event_id, title, description, start_time, end_time, location, attendees, status),
        )
    else:
        cur = await db.execute(
            "INSERT INTO calendar_events (title, description, start_time, end_time, location, attendees, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title, description, start_time, end_time, location, attendees, status),
        )
    await db.commit()
    return cur.lastrowid  # type: ignore[return-value]


async def get_upcoming_events(
    db: aiosqlite.Connection,
    *,
    since: str | None = None,
    until: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    clauses, params = [], []
    if since:
        clauses.append("start_time >= ?")
        params.append(since)
    if until:
        clauses.append("start_time <= ?")
        params.append(until)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = await db.execute_fetchall(
        f"SELECT * FROM calendar_events {where} ORDER BY start_time ASC LIMIT ?",
        (*params, limit),
    )
    return _rows_to_dicts(rows)


# ── locations ──────────────────────────────────────────────────────────

async def insert_location(
    db: aiosqlite.Connection,
    *,
    latitude: float,
    longitude: float,
    accuracy_m: float | None = None,
    label: str | None = None,
    recorded_at: str,
) -> int:
    cur = await db.execute(
        "INSERT INTO locations (latitude, longitude, accuracy_m, label, recorded_at) VALUES (?, ?, ?, ?, ?)",
        (latitude, longitude, accuracy_m, label, recorded_at),
    )
    await db.commit()
    return cur.lastrowid  # type: ignore[return-value]


async def get_locations(
    db: aiosqlite.Connection,
    *,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    clauses, params = [], []
    if since:
        clauses.append("recorded_at >= ?")
        params.append(since)
    if until:
        clauses.append("recorded_at <= ?")
        params.append(until)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = await db.execute_fetchall(
        f"SELECT * FROM locations {where} ORDER BY recorded_at DESC LIMIT ?",
        (*params, limit),
    )
    return _rows_to_dicts(rows)


# ── briefings ──────────────────────────────────────────────────────────

async def insert_briefing(
    db: aiosqlite.Connection,
    *,
    type: str = "morning",
    content: str,
    locale: str = "ko",
) -> int:
    cur = await db.execute(
        "INSERT INTO briefings (type, content, locale) VALUES (?, ?, ?)",
        (type, content, locale),
    )
    await db.commit()
    return cur.lastrowid  # type: ignore[return-value]


async def get_latest_briefing(
    db: aiosqlite.Connection, *, type: str | None = None
) -> dict[str, Any] | None:
    if type:
        row = await db.execute_fetchall(
            "SELECT * FROM briefings WHERE type = ? ORDER BY created_at DESC LIMIT 1",
            (type,),
        )
    else:
        row = await db.execute_fetchall(
            "SELECT * FROM briefings ORDER BY created_at DESC LIMIT 1"
        )
    return dict(row[0]) if row else None


# ── tasks ──────────────────────────────────────────────────────────────

async def insert_task(
    db: aiosqlite.Connection,
    *,
    title: str,
    description: str | None = None,
    due_date: str | None = None,
    priority: str = "normal",
) -> int:
    cur = await db.execute(
        "INSERT INTO tasks (title, description, due_date, priority) VALUES (?, ?, ?, ?)",
        (title, description, due_date, priority),
    )
    await db.commit()
    return cur.lastrowid  # type: ignore[return-value]


async def get_tasks(
    db: aiosqlite.Connection,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if status:
        rows = await db.execute_fetchall(
            "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        )
    else:
        rows = await db.execute_fetchall(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
        )
    return _rows_to_dicts(rows)


async def update_task(
    db: aiosqlite.Connection, task_id: int, **kwargs: Any
) -> bool:
    allowed = {"title", "description", "due_date", "priority", "status"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False
    updates["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    cur = await db.execute(
        f"UPDATE tasks SET {set_clause} WHERE id = ?",
        (*updates.values(), task_id),
    )
    await db.commit()
    return cur.rowcount > 0


async def delete_task(db: aiosqlite.Connection, task_id: int) -> bool:
    cur = await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    await db.commit()
    return cur.rowcount > 0


# ── drive_files ────────────────────────────────────────────────────────

async def upsert_drive_file(
    db: aiosqlite.Connection,
    *,
    google_file_id: str,
    name: str,
    mime_type: str | None = None,
    size_bytes: int | None = None,
    web_link: str | None = None,
    parent_id: str | None = None,
) -> int:
    cur = await db.execute(
        "INSERT INTO drive_files (google_file_id, name, mime_type, size_bytes, web_link, parent_id) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(google_file_id) DO UPDATE SET "
        "name=excluded.name, mime_type=excluded.mime_type, size_bytes=excluded.size_bytes, "
        "web_link=excluded.web_link, synced_at=datetime('now')",
        (google_file_id, name, mime_type, size_bytes, web_link, parent_id),
    )
    await db.commit()
    return cur.lastrowid  # type: ignore[return-value]


async def get_drive_files(
    db: aiosqlite.Connection, *, limit: int = 50
) -> list[dict[str, Any]]:
    rows = await db.execute_fetchall(
        "SELECT * FROM drive_files ORDER BY synced_at DESC LIMIT ?", (limit,)
    )
    return _rows_to_dicts(rows)


# ── notifications ──────────────────────────────────────────────────────

async def insert_notification(
    db: aiosqlite.Connection,
    *,
    type: str,
    title: str,
    message: str,
    reference_id: int | None = None,
) -> int:
    cur = await db.execute(
        "INSERT INTO notifications (type, title, message, reference_id) VALUES (?, ?, ?, ?)",
        (type, title, message, reference_id),
    )
    await db.commit()
    return cur.lastrowid  # type: ignore[return-value]


async def get_recent_notifications(
    db: aiosqlite.Connection,
    *,
    type: str | None = None,
    since: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    clauses, params = [], []
    if type:
        clauses.append("type = ?")
        params.append(type)
    if since:
        clauses.append("created_at >= ?")
        params.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = await db.execute_fetchall(
        f"SELECT * FROM notifications {where} ORDER BY created_at DESC LIMIT ?",
        (*params, limit),
    )
    return _rows_to_dicts(rows)


async def get_undelivered_notifications(
    db: aiosqlite.Connection, *, limit: int = 50
) -> list[dict[str, Any]]:
    rows = await db.execute_fetchall(
        "SELECT * FROM notifications WHERE delivered = 0 ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    return _rows_to_dicts(rows)


async def mark_notification_delivered(
    db: aiosqlite.Connection, notification_id: int
) -> bool:
    cur = await db.execute(
        "UPDATE notifications SET delivered = 1 WHERE id = ?", (notification_id,)
    )
    await db.commit()
    return cur.rowcount > 0


# ── app_categories ─────────────────────────────────────────────────────

async def upsert_app_category(
    db: aiosqlite.Connection,
    *,
    app_name: str,
    category: str,
    sub_category: str | None = None,
    classified_by: str = "auto",
) -> None:
    await db.execute(
        "INSERT INTO app_categories (app_name, category, sub_category, classified_by) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(app_name) DO UPDATE SET category=excluded.category, "
        "sub_category=excluded.sub_category, classified_by=excluded.classified_by",
        (app_name.lower(), category, sub_category, classified_by),
    )
    await db.commit()


async def get_app_category(
    db: aiosqlite.Connection, app_name: str
) -> dict[str, Any] | None:
    rows = await db.execute_fetchall(
        "SELECT * FROM app_categories WHERE app_name = ?", (app_name.lower(),)
    )
    return dict(rows[0]) if rows else None


async def get_all_app_categories(
    db: aiosqlite.Connection,
) -> dict[str, dict[str, Any]]:
    rows = await db.execute_fetchall("SELECT * FROM app_categories")
    return {r["app_name"]: dict(r) for r in rows}


# ── screen_texts ───────────────────────────────────────────────────────

async def insert_screen_text(
    db: aiosqlite.Connection,
    *,
    app_name: str | None = None,
    window_title: str | None = None,
    extracted_text: str,
    text_length: int | None = None,
    timestamp: str,
) -> int:
    cur = await db.execute(
        "INSERT INTO screen_texts (app_name, window_title, extracted_text, text_length, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        (app_name, window_title, extracted_text, text_length or len(extracted_text), timestamp),
    )
    await db.commit()
    return cur.lastrowid  # type: ignore[return-value]


async def get_screen_texts(
    db: aiosqlite.Connection,
    *,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    clauses, params = [], []
    if since:
        clauses.append("timestamp >= ?")
        params.append(since)
    if until:
        clauses.append("timestamp <= ?")
        params.append(until)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = await db.execute_fetchall(
        f"SELECT * FROM screen_texts {where} ORDER BY timestamp DESC LIMIT ?",
        (*params, limit),
    )
    return _rows_to_dicts(rows)


# ── user_state ─────────────────────────────────────────────────────────

async def get_user_state(db: aiosqlite.Connection) -> dict[str, Any] | None:
    rows = await db.execute_fetchall("SELECT * FROM user_state WHERE id = 1")
    return dict(rows[0]) if rows else None


async def upsert_user_state(db: aiosqlite.Connection, **kwargs: Any) -> None:
    allowed = {"onboarding_stage", "locale", "google_token", "subscription"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    updates["updated_at"] = _now()

    existing = await get_user_state(db)
    if existing:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        await db.execute(
            f"UPDATE user_state SET {set_clause} WHERE id = 1",
            tuple(updates.values()),
        )
    else:
        updates["id"] = 1
        cols = ", ".join(updates.keys())
        placeholders = ", ".join("?" for _ in updates)
        await db.execute(
            f"INSERT INTO user_state ({cols}) VALUES ({placeholders})",
            tuple(updates.values()),
        )
    await db.commit()
