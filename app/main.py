"""FastAPI entrypoint.

Two routes:
  GET  /         show the roster for the current week (or an offset week)
  POST /toggle   mark a chore done / not done for its period

The UI is server-rendered with Jinja2, so it works with no client-side JS and
deploys as a single process.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db
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
def index(request: Request, week_offset: int = 0):
    config = load_config()
    day = _target_day(week_offset)

    assignments = assignments_for(day, config.people, config.tasks)
    done_lookup = db.done_map(sorted({a.period_key for a in assignments}))

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
            "person_colors": _person_colors(config.people),
        },
    )


@app.post("/toggle")
def toggle(
    task_id: str = Form(...),
    period_key: str = Form(...),
    person: str = Form(""),
    done: str = Form("0"),
    week_offset: int = Form(0),
):
    db.set_done(task_id, period_key, done == "1", person or None)
    return RedirectResponse(url=f"/?week_offset={week_offset}", status_code=303)
