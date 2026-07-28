# Flatmate Chores

A small, extensible FastAPI web app that rotates cleaning chores between flatmates.
Weekly chores rotate every Monday, monthly chores rotate on the 1st. Everyone can
see who is on what this week and tick things off.

The rotation is a **pure function of the date**. There is no scheduler and no cron
job: given today's date, the people, and the tasks, the app recomputes the whole
roster. That keeps it simple and easy to reason about.

It is a single-page app: **one GET** returns a shell with the whole state inlined,
and everything after that renders in the browser. Changing week, switching the
slacking range, and opening the manage view make no request at all. Only saving a
change talks to the server.

## Project layout

```
flatmate-chores/
├── app/
│   ├── main.py          App shell + JSON API
│   ├── rotation.py      Pure rotation logic (unit-tested) -- the reference
│   ├── stats.py         Slacking maths (pure, unit-tested) -- the reference
│   ├── config.py        Loads config.yaml
│   ├── db.py            Postgres: the chore list + completion tracking
│   ├── templates/       The shell page
│   └── static/
│       ├── rotation.js  Mirrors rotation.py + stats.py; parity-tested
│       ├── app.js       Views and wiring
│       ├── style.css
│       ├── goofy.ico    Favicon
│       ├── images/      <- weekly banner pictures
│       ├── faces/       <- one portrait per flatmate, named after them
│       └── sounds/      <- done.mp3 plays when a chore is ticked off
├── config.yaml          <- edit this: people (+ the seed chore list)
├── tests/               pytest, incl. a Python<->JS parity suite
├── requirements.txt
├── run.py               Local entrypoint
└── Dockerfile
```

## Pictures

Two folders, both read at startup — restart to pick up new files. Accepted
everywhere: `.jpg`, `.png`, `.gif`, `.webp`, `.avif`, `.svg`.

### The weekly banner — `app/static/images/`

Put in any number of images. One shows per week, in filename order, wrapping round
at the end, and it changes as you page through weeks so each week has "its"
picture. A single file shows every week; an empty folder renders no banner.

It sits as a **thin banner** so it never pushes the chores off the first screen —
**drag its bottom edge** to open it up and see the whole image. The height you pick
is remembered.

### Flatmate portraits — `app/static/faces/`

Name each file after the person: `Giada.png` for Giada. Matching is
case-insensitive, so `giada.jpg` works too. That face then appears wherever the
person does — the roster chips and every chore card — ringed in their colour.

Anyone without a file keeps the plain coloured dot, so you can fill the folder in
one person at a time. The colour ring is deliberate: it means the colour coding
still works when only some people have a photo.

Portraits keep their transparency, so save them as PNG if they are cut out.

### Sound — `app/static/sounds/`

Drop in **`done.mp3`** and it plays whenever a chore is ticked off. `.ogg`, `.wav`,
`.m4a` and `.webm` work too. Un-ticking is silent — it's a reward, not a
notification. An empty folder means the app stays quiet.

### Keep them small

These are served straight to the browser and committed to the repo, so shrink
before adding: the banner is displayed about 860px wide, which 1600px covers even
on a retina screen, and portraits render at 22px. Full-size generated PNGs run 7–8
MB each and will make every page load and every deploy slow.

## Run it locally

Requires Python 3.10+ and a Postgres database.

Start a local Postgres with Docker:

```bash
docker run -d --name chores-db -p 5432:5432 \
  -e POSTGRES_USER=chores -e POSTGRES_PASSWORD=chores -e POSTGRES_DB=chores \
  postgres:16-alpine
```

Then:

```bash
cd flatmate-chores
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export DATABASE_URL=postgresql://chores:chores@localhost:5432/chores
python run.py
```

Open http://127.0.0.1:8000. The `--reload` flag in `run.py` picks up code changes
automatically. After editing `config.yaml`, restart. The tables are created on
startup if they don't exist, and the chore list is seeded from `config.yaml` the
first time it finds an empty one.

The CSS and JS are served with a `?v=` stamp taken from their modification time, so
a browser can never render new markup against a cached old stylesheet. If a change
doesn't show up, that is not the cause — check the server actually restarted.

Run the tests:

```bash
pip install pytest
python -m pytest
```

## Change people and chores

There are two kinds of chore, edited in two different places.

**One-off chores — press `Edit` on the roster.** The cards start wobbling, a `×`
appears on each one to delete it, and a `+` tile appears on each board. Anything
added there belongs to **only the week or month you are looking at** and never comes
back. Good for "the kitchen is a disaster after the party".

**Repeating chores — the `Manage chores` page.** Add weekly or monthly chores that
rotate forever, choose **who starts** with each one (everyone else follows in
order), change the starter later, or delete one. `‹ Back to the roster` returns.

**People: in `config.yaml`.** `flatmates` is the rotation order. Add a person, save,
restart.

The `tasks` list in `config.yaml` only *seeds* the database on first run against an
empty one. Chores live in Postgres after that, because the app is meant to run on a
host with an ephemeral filesystem — writing UI edits back to the YAML file would
lose them on the next deploy. Editing `tasks` in the YAML once the table is
populated has no effect.

### What add and delete do to the rotation

Each chore carries a `slot`: a stable rotation offset within its frequency group,
rather than its position in the list. Adding a chore takes the next free slot and
deleting one leaves a gap, so in both cases **every other chore keeps the same
person in every week, past and present**. If the offset were the list index instead,
deleting one chore would silently re-shuffle responsibility for all the chores after
it, retroactively, across the whole slacking history.

Deleting a chore also drops its completion and reassignment rows, so it disappears
from the "who's slacking" board rather than leaving a permanent mark against whoever
last skipped it. Deleting is not undoable — re-adding a chore with the same name
starts it fresh.

### Nothing counts before a chore existed

Every chore stores a `starts_on` date and simply does not exist in any period before
it. A chore added today is not "missed" for all of last year, so the slacking board
opens empty on a fresh rota instead of with a backlog nobody could have done. Chores
seeded from `config.yaml` start the day the table is first created; an existing
deployment backfills them to the day it picks this up.

## How it works

- `week_index(date)` counts weeks from a fixed Monday; `month_index(date)` counts
  months. Assignment is `people[(period_index + task_offset) % len(people)]`.
- The `task_offset` is the chore's stored `slot`, which spreads tasks in the same
  period across different people and stays put when chores are added or deleted.
- Completion is stored per `(task_id, period_key)` where `period_key` is like
  `W-123` or `M-45`. A new week/month starts everyone fresh automatically.
- A one-off chore is a row with that same `period_key` set on the chore itself, so
  it exists in exactly one period. `NULL` means it repeats.

### The duplicated rotation logic

Rendering offline means the rotation maths exists twice: `rotation.py`/`stats.py`
and `static/rotation.js`. **Python is the reference** — change it there first.
`tests/test_js_parity.py` runs the real JavaScript under Node against the real
Python over three years of dates and every slacking range, and fails if they
disagree, so the copies cannot drift silently. It skips if Node isn't installed.

### Light and dark

Light is pink, dark is violet. The theme button cycles **Auto → Light → Dark**;
Auto follows the device, and only an explicit choice is stored (in `localStorage`),
so a phone that switches to dark at sunset still switches with it. The saved theme
is stamped onto `<html>` by a tiny inline script in `<head>` — any later and the
page flashes the wrong colours on every load.

Colours live entirely in CSS custom properties, and the chart reads the same tokens
off the document rather than hardcoding hex, so the canvas follows the theme too.
The dark block is deliberately written twice: once under `prefers-color-scheme` for
the device, once under `[data-theme]` for the button, because the button has to win
in both directions.

### Person colours

The colours in `main.py` are not arbitrary. A person's colour follows them
everywhere, so any two can appear side by side — an *all-pairs* palette problem,
not an adjacent-pairs one. Candidates were validated for colour-vision separation
rather than picked by eye.

There are two lists. The hue **order** is shared, so nobody's colour identity
changes when you switch theme; only the step differs, chosen against its own
surface rather than lightened mechanically from the other. Blue/magenta/green leads
because it is the one order clearing both gates in *both* modes — light worst ΔE
13.0 (CVD) and 27.5 (normal), dark 13.0 and 26.5.

Light stays clean to five people; **dark only to three**, past which its violet
closes on its blue (ΔE 1.9 — effectively identical). A name is always rendered next
to the dot, so colour never identifies anyone on its own, which is what makes the
degradation survivable rather than broken.

## Ideas to extend

- Auth so people tick off only their own tasks
- A `/history` page reading the `completions` table
- Swap the round-robin for a fairness-aware assignment
- Push/email reminders on Monday morning

## Deploy it on Render

This is a single always-on web process plus a Postgres database.

1. **Create the database.** In the Render dashboard: *New → Postgres*. Pick the
   free plan for a prototype (note: Render's free Postgres is deleted after 30
   days — upgrade to the cheapest paid plan for anything you want to keep).
2. **Create the web service.** *New → Web Service*, connect this repo.
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Or skip both and let Render use the included `Dockerfile`.
3. **Wire up `DATABASE_URL`.** On the web service's *Environment* tab, add
   `DATABASE_URL` and set it to the Postgres instance's **Internal Database URL**
   (found on the database's page). Using the internal URL keeps traffic inside
   Render's network and avoids the connection limit on the external one. If the
   two are in the same Render account/region you can also add the database as an
   "Environment Group" or link it directly so Render injects the URL for you.
4. **Deploy.** On startup, `app/db.py` creates the `tasks`, `completions` and
   `reassignments` tables automatically and seeds `tasks` from `config.yaml` — no
   separate migration step needed. An already-running deployment picks this up on
   its next deploy: the seed reproduces the existing rotation exactly, so nobody's
   chores move.

The free web service tier spins down when idle, so the first request after a quiet
spell takes ~1 minute to wake; the Postgres connection reconnects fine after that.
$7/mo on the web service removes the spin-down.
