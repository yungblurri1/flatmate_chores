"""FastAPI entrypoint.

Routes:
  GET  /               show the roster for the current week (or an offset week)
  POST /toggle         mark a chore done / not done for its period
  POST /reassign       swap who a chore is assigned to for one period
  GET  /api/slacking   JSON missed-chore counts, used to refresh the chart without a full reload

The roster itself is server-rendered with Jinja2, so it works with no client-side
JS and deploys as a single process. The slacking chart's range picker fetches from
/api/slacking for a snappier, SPA-like update instead of reloading the page.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db, stats
from .config import load_config
from .rotation import assignments_for, week_bounds

BASE_DIR = Path(__file__).resolve().parent

# A stable, readable palette. People are coloured by their position in the roster.
_PALETTE = ["#0f9d76", "#3b6fd6", "#c46a1b", "#8a53c4", "#c23b6b", "#0d8a9c"]


def _person_colors(people: list[str]) -> dict[str, str]:
    return {p: _PALETTE[i % len(_PALETTE)] for i, p in enumerate(people)}


app = FastAPI(title="Flatmate Chores")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


def _target_day(week_offset: int) -> date:
    return date.today() + timedelta(weeks=week_offset)


@app.get("/")
def index(request: Request, week_offset: int = 0, range: str = stats.DEFAULT_RANGE):
    config = load_config()
    day = _target_day(week_offset)
    range_key = range if range in stats.RANGE_OPTIONS else stats.DEFAULT_RANGE

    assignments = assignments_for(day, config.people, config.tasks)
    period_keys = sorted({a.period_key for a in assignments})
    done_lookup = db.done_map(period_keys)
    reassign_map = db.reassignment_map(period_keys)
    assignments = [
        replace(a, person=reassign_map.get((a.task.id, a.period_key), a.person))
        for a in assignments
    ]

    weekly = []
    monthly = []
    for a in assignments:
        done = (a.task.id, a.period_key) in done_lookup
        row = {"assignment": a, "done": done}
        (weekly if a.task.frequency == "weekly" else monthly).append(row)

    monday, sunday = week_bounds(day)

    # Per-person summary for the current week's weekly tasks.
    load_by_person: dict[str, int] = {p: 0 for p in config.people}
    for row in weekly:
        load_by_person[row["assignment"].person] += 1

    colors = _person_colors(config.people)
    missed = stats.missed_by_person(config, range_key)
    slack_labels = sorted(config.people, key=lambda p: missed.get(p, 0), reverse=True)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "household_name": config.household_name,
            "people": config.people,
            "weekly": weekly,
            "monthly": monthly,
            "week_offset": week_offset,
            "monday": monday,
            "sunday": sunday,
            "month_label": day.strftime("%B %Y"),
            "is_current_week": week_offset == 0,
            "load_by_person": load_by_person,
            "person_colors": colors,
            "range_key": range_key,
            "range_options": stats.RANGE_OPTIONS,
            "slack_labels": slack_labels,
            "slack_values": [missed.get(p, 0) for p in slack_labels],
            "slack_colors": [colors[p] for p in slack_labels],
        },
    )


@app.post("/toggle")
def toggle(
    task_id: str = Form(...),
    period_key: str = Form(...),
    person: str = Form(""),
    done: str = Form("0"),
    week_offset: int = Form(0),
    range: str = Form(stats.DEFAULT_RANGE),
):
    db.set_done(task_id, period_key, done == "1", person or None)
    return RedirectResponse(url=f"/?week_offset={week_offset}&range={range}", status_code=303)


@app.post("/reassign")
def reassign(
    task_id: str = Form(...),
    period_key: str = Form(...),
    person: str = Form(...),
    week_offset: int = Form(0),
    range: str = Form(stats.DEFAULT_RANGE),
):
    db.set_reassignment(task_id, period_key, person)
    return RedirectResponse(url=f"/?week_offset={week_offset}&range={range}", status_code=303)


@app.get("/api/slacking")
def slacking(range: str = stats.DEFAULT_RANGE):
    config = load_config()
    range_key = range if range in stats.RANGE_OPTIONS else stats.DEFAULT_RANGE
    colors = _person_colors(config.people)
    missed = stats.missed_by_person(config, range_key)
    labels = sorted(config.people, key=lambda p: missed.get(p, 0), reverse=True)

    return {
        "range_key": range_key,
        "labels": labels,
        "values": [missed.get(p, 0) for p in labels],
        "colors": [colors[p] for p in labels],
    }
