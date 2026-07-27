"""Tiny Postgres layer for tracking which chores are done.

Completion is keyed by (task_id, period_key). Because period_key encodes the week
or month, a new week automatically starts everyone with a clean slate. Nothing to
reset by hand.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import psycopg
from dotenv import load_dotenv
from psycopg.rows import DictRow, dict_row

load_dotenv()

_DATABASE_URL = os.environ["DATABASE_URL"]


def _connect() -> psycopg.Connection[DictRow]:
    return psycopg.connect(_DATABASE_URL, row_factory=dict_row)


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS completions (
                task_id     TEXT NOT NULL,
                period_key  TEXT NOT NULL,
                done        BOOLEAN NOT NULL DEFAULT FALSE,
                done_by     TEXT,
                done_at     TEXT,
                PRIMARY KEY (task_id, period_key)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reassignments (
                task_id      TEXT NOT NULL,
                period_key   TEXT NOT NULL,
                assigned_to  TEXT NOT NULL,
                PRIMARY KEY (task_id, period_key)
            )
            """
        )


def done_map(period_keys: list[str]) -> dict[tuple[str, str], DictRow]:
    """Return {(task_id, period_key): row} for the given periods."""
    if not period_keys:
        return {}
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM completions WHERE period_key = ANY(%s) AND done",
            (period_keys,),
        ).fetchall()
    return {(r["task_id"], r["period_key"]): r for r in rows}


def reassignment_map(period_keys: list[str]) -> dict[tuple[str, str], str]:
    """Return {(task_id, period_key): assigned_to} overrides for the given periods."""
    if not period_keys:
        return {}
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM reassignments WHERE period_key = ANY(%s)",
            (period_keys,),
        ).fetchall()
    return {(r["task_id"], r["period_key"]): r["assigned_to"] for r in rows}


def set_reassignment(task_id: str, period_key: str, person: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO reassignments (task_id, period_key, assigned_to)
            VALUES (%s, %s, %s)
            ON CONFLICT (task_id, period_key) DO UPDATE SET
                assigned_to = excluded.assigned_to
            """,
            (task_id, period_key, person),
        )


def set_done(task_id: str, period_key: str, done: bool, person: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds") if done else None
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO completions (task_id, period_key, done, done_by, done_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (task_id, period_key) DO UPDATE SET
                done = excluded.done,
                done_by = excluded.done_by,
                done_at = excluded.done_at
            """,
            (task_id, period_key, done, person, now),
        )
