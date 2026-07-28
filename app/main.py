"""FastAPI entrypoint.

The page is a single-page app. One GET returns a shell with the entire state
embedded in it -- chores, tick history, reassignments, people -- and everything
after that is rendered in the browser: changing week, switching the slacking
range, and opening the manage-chores view all happen with no request at all.
Only changes talk to the server, and each one is a small JSON call.

  GET    /                    the app shell, with initial state inlined
  GET    /chores              the same shell; the client opens the manage view

  POST   /api/tasks           add a chore (recurring, or one-off for one period)
  PATCH  /api/tasks/{id}      change who a recurring chore starts with
  DELETE /api/tasks/{id}      remove a chore and its history
  POST   /api/completions     tick / untick a chore for its period
  POST   /api/reassignments   hand a chore to someone else for one period

Rotation itself is a pure function of the date and is mirrored in static/app.js so
the browser can compute a roster for any week offline. rotation.py stays the
reference implementation and is what the tests pin.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from . import db, stats
from .config import load_config
from .rotation import Task, slot_for_starter

BASE_DIR = Path(__file__).resolve().parent

# People are coloured by their position in the roster, and that colour follows
# them everywhere -- chips, cards, chart. So any two people's colours can end up
# side by side, which makes this an all-pairs palette, not an adjacent-pairs one.
#
# These five were picked by validating every candidate subset against colour-vision
# separation: at five they clear all-pairs deficiency separation (worst ΔE 13.0
# protan) and the normal-vision floor (worst 16.3). Slots 4 and 5 fall below 3:1
# against white, which is fine here only because a name is always rendered next to
# the dot -- colour never identifies anyone on its own. A sixth flatmate drops into
# the warn band (red↔magenta ΔE 13.2 normal); the adjacent name is what carries it.
_PALETTE = [
    "#2a78d6",  # blue
    "#008300",  # green
    "#4a3aa7",  # violet
    "#e87ba4",  # magenta
    "#eda100",  # yellow
    "#e34948",  # red -- 6th flatmate, see note above
]


def _person_colors(people: list[str]) -> dict[str, str]:
    return {p: _PALETTE[i % len(_PALETTE)] for i, p in enumerate(people)}


app = FastAPI(title="Flatmate Chores")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    db.seed_tasks(load_config().seed_tasks, date.today())


def _task_json(task: Task) -> dict:
    return {
        "id": task.id,
        "name": task.name,
        "frequency": task.frequency,
        "description": task.description,
        "slot": task.slot,
        "periodKey": task.period_key,
        "startsOn": task.starts_on.isoformat() if task.starts_on else None,
    }


def _asset_version() -> str:
    """Cache-buster for the CSS and JS.

    Both are served with far-future caching by the static mount, so without this a
    browser holding the previous build renders new markup against old styles --
    which looks exactly like a broken deploy.
    """
    static = BASE_DIR / "static"
    assets = ("app.js", "rotation.js", "style.css")
    return str(int(max((static / a).stat().st_mtime for a in assets)))


_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg"}


def _images() -> list[str]:
    """URLs of the pictures in static/images, sorted so the order is stable.

    The client picks one by week, so the whole list ships with the page and the
    picture changes as you browse weeks without asking the server for anything.
    Drop files in, restart, done. One file means that file every week; none means
    the app just doesn't render the picture.
    """
    folder = BASE_DIR / "static" / "images"
    if not folder.is_dir():
        return []
    names = sorted(
        p.name for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in _IMAGE_SUFFIXES
    )
    return [f"/static/images/{n}" for n in names]


def _faces(people: list[str]) -> dict[str, str]:
    """Map each flatmate to their portrait in static/faces, if they have one.

    The file is matched on its name, case-insensitively -- "Giada.png" belongs to
    Giada. Anyone without a file keeps the plain coloured dot, so the folder can be
    filled in one person at a time.
    """
    folder = BASE_DIR / "static" / "faces"
    if not folder.is_dir():
        return {}

    by_stem = {
        p.stem.casefold(): p.name
        for p in sorted(folder.iterdir())
        if p.is_file() and p.suffix.lower() in _IMAGE_SUFFIXES
    }
    return {
        person: f"/static/faces/{by_stem[person.casefold()]}"
        for person in people
        if person.casefold() in by_stem
    }


_SOUND_SUFFIXES = (".mp3", ".ogg", ".wav", ".m4a", ".webm")


def _sounds() -> dict[str, str]:
    """Map a sound name to its file in static/sounds, e.g. {"done": "...mp3"}.

    Named by stem so "done.mp3" is the ticking-off sound. Any of the listed
    extensions works; an empty folder just means the app stays silent.
    """
    folder = BASE_DIR / "static" / "sounds"
    if not folder.is_dir():
        return {}
    return {
        p.stem.casefold(): f"/static/sounds/{p.name}"
        for p in sorted(folder.iterdir())
        if p.is_file() and p.suffix.lower() in _SOUND_SUFFIXES
    }


def _initial_state() -> dict:
    config = load_config()
    done, reassigned = db.all_progress()
    return {
        "householdName": config.household_name,
        "people": config.people,
        "colors": _person_colors(config.people),
        "faces": _faces(config.people),
        "sounds": _sounds(),
        "tasks": [_task_json(t) for t in db.all_tasks()],
        "done": done,
        "reassigned": reassigned,
        # A list, not a dict: JSON objects get key-sorted on the way out, which
        # would shuffle the range pills out of shortest-to-longest order.
        "images": _images(),
        "ranges": [{"key": k, **v} for k, v in stats.RANGE_OPTIONS.items()],
        "defaultRange": stats.DEFAULT_RANGE,
        "today": date.today().isoformat(),
    }


@app.get("/")
@app.get("/chores")
def shell(request: Request):
    """Both routes serve the same app; the client picks a view from the path.

    Serving /chores here rather than only from the client router means a refresh
    or a pasted link lands on the manage view instead of a 404.
    """
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "state": _initial_state(), "asset_version": _asset_version()},
    )


class NewTask(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    frequency: str
    description: str = Field(default="", max_length=140)
    starter: str | None = None
    # Set for a one-off: the single week ("W-123") or month ("M-45") it lives in.
    period_key: str | None = None


class TaskUpdate(BaseModel):
    starter: str


class Completion(BaseModel):
    task_id: str
    period_key: str
    done: bool
    person: str | None = None


class Reassignment(BaseModel):
    task_id: str
    period_key: str
    person: str


def _validated_frequency(frequency: str) -> str:
    if frequency not in ("weekly", "monthly"):
        raise HTTPException(status_code=422, detail="frequency must be weekly or monthly")
    return frequency


@app.post("/api/tasks", status_code=201)
def create_task(body: NewTask) -> dict:
    frequency = _validated_frequency(body.frequency)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")

    people = load_config().people
    today = date.today()

    if body.period_key:
        # A one-off is already pinned to one period, so it needs no start date --
        # and must not get one, or adding it to a past week would hide it.
        slot, starts_on = None, None
    else:
        starts_on = today
        slot = (
            slot_for_starter(today, frequency, people, body.starter)
            if body.starter in people
            else None
        )

    task_id = db.add_task(
        name,
        frequency,
        body.description.strip(),
        slot=slot,
        period_key=body.period_key,
        starts_on=starts_on,
    )
    created = next(t for t in db.all_tasks() if t.id == task_id)
    return _task_json(created)


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: str, body: TaskUpdate) -> dict:
    """Change who a recurring chore starts with, and hand back the updated chore.

    Returning it saves the client from having to re-derive the new slot itself.
    """
    people = load_config().people
    if body.starter not in people:
        raise HTTPException(status_code=422, detail="unknown person")

    task = next((t for t in db.all_tasks() if t.id == task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail="no such chore")

    db.set_task_slot(task_id, slot_for_starter(date.today(), task.frequency, people, body.starter))
    return _task_json(next(t for t in db.all_tasks() if t.id == task_id))


@app.delete("/api/tasks/{task_id}", status_code=204)
def remove_task(task_id: str) -> Response:
    db.delete_task(task_id)
    return Response(status_code=204)


@app.post("/api/completions", status_code=204)
def set_completion(body: Completion) -> Response:
    db.set_done(body.task_id, body.period_key, body.done, body.person)
    return Response(status_code=204)


@app.post("/api/reassignments", status_code=204)
def set_reassignment(body: Reassignment) -> Response:
    if body.person not in load_config().people:
        raise HTTPException(status_code=422, detail="unknown person")
    db.set_reassignment(body.task_id, body.period_key, body.person)
    return Response(status_code=204)
