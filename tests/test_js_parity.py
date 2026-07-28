"""The browser computes rosters itself, so rotation.js duplicates rotation.py.

Duplicated logic drifts. These tests run the real JavaScript under Node against
the real Python over the same inputs and require identical answers, which is what
makes the duplication safe to keep. Skipped, not failed, where Node is missing --
the Python is still the reference and its own tests cover it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.rotation import Task, assignments_for, month_index, week_index
from app.stats import RANGE_OPTIONS, missed_by_person, progress_key

ROTATION_JS = Path(__file__).resolve().parent.parent / "app" / "static" / "rotation.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

PEOPLE = ["Alex", "Giada", "Bia"]

TASKS = [
    Task("kitchen", "Kitchen", "weekly", slot=0, starts_on=date(2024, 1, 1)),
    Task("bath", "Bathroom", "weekly", slot=1, starts_on=date(2024, 1, 1)),
    Task("trash", "Trash", "weekly", slot=2, starts_on=date(2025, 6, 11)),
    Task("windows", "Windows", "monthly", slot=0, starts_on=date(2024, 1, 1)),
    Task("fridge", "Fridge", "monthly", slot=1, starts_on=date(2025, 3, 20)),
    Task("guests", "Tidy for guests", "weekly", slot=3, period_key="W-80"),
    Task("party", "Post-party", "monthly", slot=2, period_key="M-18"),
]


def _tasks_json() -> list[dict]:
    return [
        {
            "id": t.id,
            "name": t.name,
            "frequency": t.frequency,
            "slot": t.slot,
            "periodKey": t.period_key,
            "startsOn": t.starts_on.isoformat() if t.starts_on else None,
        }
        for t in TASKS
    ]


def _run_node(script: str, payload: dict) -> dict:
    """Run a snippet with rotation.js loaded as `R` and `INPUT` as the payload."""
    harness = f"""
      const R = require({json.dumps(str(ROTATION_JS))}).Rotation;
      const INPUT = {json.dumps(payload)};
      {script}
    """
    result = subprocess.run(
        ["node", "-e", harness], capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        raise AssertionError(f"node failed:\n{result.stderr}")
    return json.loads(result.stdout)


def test_assignments_match_python_across_three_years():
    """Same people, same tasks, every week for three years -- identical rosters.

    This is the test that would catch a week-numbering or DST bug: the two
    implementations compute Monday boundaries in completely different ways.
    """
    days = [date(2024, 1, 1) + timedelta(days=n) for n in range(0, 1100, 3)]

    expected = {
        d.isoformat(): sorted(
            (a.task.id, a.person, a.period_key) for a in assignments_for(d, PEOPLE, TASKS)
        )
        for d in days
    }

    actual = _run_node(
        """
        const out = {};
        for (const iso of INPUT.days) {
          out[iso] = R.assignmentsFor(R.parseDate(iso), INPUT.people, INPUT.tasks)
            .map(a => [a.task.id, a.person, a.periodKey])
            .sort((x, y) => JSON.stringify(x) < JSON.stringify(y) ? -1 : 1);
        }
        console.log(JSON.stringify(out));
        """,
        {"days": [d.isoformat() for d in days], "people": PEOPLE, "tasks": _tasks_json()},
    )

    assert {k: [list(t) for t in v] for k, v in expected.items()} == actual


def test_missed_counts_match_python_for_every_range():
    today = date(2026, 7, 28)
    done = {
        progress_key("kitchen", "W-134"),
        progress_key("bath", "W-133"),
        progress_key("windows", "M-30"),
    }
    reassigned = {progress_key("bath", "W-132"): "Bia"}

    expected = {
        key: missed_by_person(PEOPLE, TASKS, done, reassigned, key, today=today)
        for key in RANGE_OPTIONS
    }

    actual = _run_node(
        """
        const out = {};
        const done = new Set(INPUT.done);
        for (const [key, range] of Object.entries(INPUT.ranges)) {
          out[key] = R.missedByPerson(
            INPUT.people, INPUT.tasks, done, INPUT.reassigned, range,
            R.parseDate(INPUT.today)
          );
        }
        console.log(JSON.stringify(out));
        """,
        {
            "people": PEOPLE,
            "tasks": _tasks_json(),
            "done": sorted(done),
            "reassigned": reassigned,
            "ranges": RANGE_OPTIONS,
            "today": today.isoformat(),
        },
    )

    assert expected == actual


def test_week_numbering_agrees_around_year_and_dst_boundaries():
    """Dates where naive day arithmetic tends to go wrong by one."""
    days = [
        date(2024, 12, 30), date(2024, 12, 31), date(2025, 1, 1), date(2025, 1, 6),
        date(2025, 3, 30), date(2025, 3, 31), date(2025, 10, 26), date(2025, 10, 27),
        date(2026, 2, 28), date(2026, 3, 1), date(2024, 2, 29),
    ]
    expected = {d.isoformat(): [week_index(d), month_index(d)] for d in days}

    actual = _run_node(
        """
        const out = {};
        for (const iso of INPUT.days) {
          const d = R.parseDate(iso);
          out[iso] = [R.weekIndex(d), R.monthIndex(d)];
        }
        console.log(JSON.stringify(out));
        """,
        {"days": [d.isoformat() for d in days]},
    )

    assert expected == actual
