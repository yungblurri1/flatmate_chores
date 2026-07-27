"""Tiny SQLite layer for tracking which chores are done.

Completion is keyed by (task_id, period_key). Because period_key encodes the week
or month, a new week automatically starts everyone with a clean slate. Nothing to
reset by hand.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = Path(os.environ.get("CHORES_DB", Path(__file__).resolve().parent.parent / "chores.db"))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS completions (
                task_id     TEXT NOT NULL,
                period_key  TEXT NOT NULL,
                done        INTEGER NOT NULL DEFAULT 0,
                done_by     TEXT,
                done_at     TEXT,
                PRIMARY KEY (task_id, period_key)
            )
            """
        )


def done_map(period_keys: list[str]) -> dict[tuple[str, str], sqlite3.Row]:
    """Return {(task_id, period_key): row} for the given periods."""
    if not period_keys:
        return {}
    placeholders = ",".join("?" for _ in period_keys)
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM completions WHERE period_key IN ({placeholders}) AND done = 1",
            period_keys,
        ).fetchall()
    return {(r["task_id"], r["period_key"]): r for r in rows}


def set_done(task_id: str, period_key: str, done: bool, person: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds") if done else None
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO completions (task_id, period_key, done, done_by, done_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(task_id, period_key) DO UPDATE SET
                done = excluded.done,
                done_by = excluded.done_by,
                done_at = excluded.done_at
            """,
            (task_id, period_key, 1 if done else 0, person, now),
        )
