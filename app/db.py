"""Tiny Postgres layer for the chore list and for tracking which chores are done.

Completion is keyed by (task_id, period_key). Because period_key encodes the week
or month, a new week automatically starts everyone with a clean slate. Nothing to
reset by hand.

The task list lives here rather than in config.yaml because chores are editable
from the web UI, and the app runs on a host with an ephemeral filesystem -- writing
edits back to the YAML file would lose them on the next restart or deploy.
config.yaml still seeds the table on first run.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timezone

import psycopg
from dotenv import load_dotenv
from psycopg.rows import DictRow, dict_row

from .rotation import Task

load_dotenv()

_DATABASE_URL = os.environ["DATABASE_URL"]


def _connect() -> psycopg.Connection[DictRow]:
    return psycopg.connect(_DATABASE_URL, row_factory=dict_row)


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id           TEXT PRIMARY KEY,
                name         TEXT NOT NULL,
                frequency    TEXT NOT NULL,
                description  TEXT NOT NULL DEFAULT '',
                slot         INTEGER NOT NULL DEFAULT 0,
                period_key   TEXT,
                starts_on    DATE
            )
            """
        )
        # For tables created before one-off chores and start dates existed. Chores
        # already in the table predate anyone actually doing them, so they start
        # today rather than retroactively counting as missed.
        conn.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS period_key TEXT")
        conn.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS starts_on DATE")
        conn.execute("UPDATE tasks SET starts_on = CURRENT_DATE WHERE starts_on IS NULL")
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


def _slugify(name: str) -> str:
    """Turn a chore name into a URL/id-friendly slug. Falls back to 'chore'."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:40] or "chore"


_SELECT_TASK = """
    SELECT id, name, frequency, description, slot, period_key, starts_on FROM tasks
"""
_TASK_ORDER = " ORDER BY frequency DESC, slot, id"


def _to_task(row: DictRow) -> Task:
    return Task(
        id=row["id"],
        name=row["name"],
        frequency=row["frequency"],
        description=row["description"] or "",
        slot=row["slot"],
        period_key=row["period_key"],
        starts_on=row["starts_on"],
    )


def list_tasks(period_keys: list[str] | None = None) -> list[Task]:
    """Chores visible in the given periods: every recurring one, plus the one-offs
    belonging to those exact periods. Weekly first, each group in slot order.

    With no period_keys you get the recurring chores only -- one-offs are always
    scoped to a period, so asking without one has no sensible answer.
    """
    with _connect() as conn:
        rows = conn.execute(
            _SELECT_TASK + " WHERE period_key IS NULL OR period_key = ANY(%s)" + _TASK_ORDER,
            (period_keys or [],),
        ).fetchall()
    return [_to_task(r) for r in rows]


def list_recurring_tasks() -> list[Task]:
    """The permanent chore list, for the manage page."""
    with _connect() as conn:
        rows = conn.execute(
            _SELECT_TASK + " WHERE period_key IS NULL" + _TASK_ORDER
        ).fetchall()
    return [_to_task(r) for r in rows]


def list_oneoffs() -> list[Task]:
    """Every one-off chore, each carrying the single period it belongs to."""
    with _connect() as conn:
        rows = conn.execute(
            _SELECT_TASK + " WHERE period_key IS NOT NULL" + _TASK_ORDER
        ).fetchall()
    return [_to_task(r) for r in rows]


def all_tasks() -> list[Task]:
    """Every chore of both kinds, for the initial page state."""
    with _connect() as conn:
        rows = conn.execute(_SELECT_TASK + _TASK_ORDER).fetchall()
    return [_to_task(r) for r in rows]


def all_progress() -> tuple[list[str], dict[str, str]]:
    """Everything ticked and everything reassigned, keyed "task_id|period_key".

    The whole history goes to the browser in one payload. It is a handful of rows
    per week, so even years of it is small, and shipping all of it is what lets the
    page change week or recompute the slacking chart without asking the server.
    """
    with _connect() as conn:
        done = [
            f"{r['task_id']}|{r['period_key']}"
            for r in conn.execute(
                "SELECT task_id, period_key FROM completions WHERE done"
            ).fetchall()
        ]
        reassigned = {
            f"{r['task_id']}|{r['period_key']}": r["assigned_to"]
            for r in conn.execute(
                "SELECT task_id, period_key, assigned_to FROM reassignments"
            ).fetchall()
        }
    return done, reassigned


def seed_tasks(tasks: list[Task], starts_on: date) -> None:
    """Populate an empty tasks table from config.yaml. No-op once anything exists.

    Seeding by list position reproduces the pre-database rotation exactly, so an
    existing deployment's roster does not shift when it first picks this up. The
    chores start on `starts_on` -- the rota only begins the day it is set up, so
    the slacking board does not open with a backlog nobody could have done.
    """
    with _connect() as conn:
        if conn.execute("SELECT 1 FROM tasks LIMIT 1").fetchone():
            return
        slots: dict[str, int] = {}
        for task in tasks:
            slot = slots.get(task.frequency, 0)
            slots[task.frequency] = slot + 1
            conn.execute(
                """
                INSERT INTO tasks (id, name, frequency, description, slot, starts_on)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (task.id, task.name, task.frequency, task.description, slot, starts_on),
            )


def next_slot(frequency: str) -> int:
    """The first slot in this frequency group that no chore is using yet."""
    with _connect() as conn:
        return conn.execute(
            "SELECT COALESCE(MAX(slot) + 1, 0) AS next FROM tasks WHERE frequency = %s",
            (frequency,),
        ).fetchone()["next"]


def add_task(
    name: str,
    frequency: str,
    description: str = "",
    slot: int | None = None,
    period_key: str | None = None,
    starts_on: date | None = None,
) -> str:
    """Add a chore and return its generated id.

    `slot` fixes who the chore lands on; leaving it None takes the next free slot,
    which joins the rotation without disturbing who is on any existing chore.
    `period_key` makes it a one-off living in that single week or month, and
    `starts_on` keeps a recurring chore out of the weeks before it was created.
    """
    with _connect() as conn:
        if slot is None:
            slot = conn.execute(
                "SELECT COALESCE(MAX(slot) + 1, 0) AS next FROM tasks WHERE frequency = %s",
                (frequency,),
            ).fetchone()["next"]

        taken = {r["id"] for r in conn.execute("SELECT id FROM tasks").fetchall()}
        base = _slugify(name)
        task_id = base
        suffix = 2
        while task_id in taken:
            task_id = f"{base}-{suffix}"
            suffix += 1

        conn.execute(
            """
            INSERT INTO tasks (id, name, frequency, description, slot, period_key, starts_on)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (task_id, name, frequency, description, slot, period_key, starts_on),
        )
    return task_id


def set_task_slot(task_id: str, slot: int) -> None:
    """Move a chore to a different rotation slot, i.e. change who starts with it."""
    with _connect() as conn:
        conn.execute("UPDATE tasks SET slot = %s WHERE id = %s", (slot, task_id))


def delete_task(task_id: str) -> None:
    """Remove a chore along with its completion and reassignment history.

    Leaving the history behind would resurrect stale ticks if a chore with the
    same name were added again later.
    """
    with _connect() as conn:
        conn.execute("DELETE FROM completions WHERE task_id = %s", (task_id,))
        conn.execute("DELETE FROM reassignments WHERE task_id = %s", (task_id,))
        conn.execute("DELETE FROM tasks WHERE id = %s", (task_id,))


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
