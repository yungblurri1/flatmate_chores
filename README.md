# Flatmate Chores

A small, extensible FastAPI web app that rotates cleaning chores between flatmates.
Weekly chores rotate every Monday, monthly chores rotate on the 1st. Everyone can
see who is on what this week and tick things off.

The rotation is a **pure function of the date**. There is no scheduler and no cron
job: given today's date, the people, and the tasks, the app recomputes the whole
roster. That keeps it simple and easy to reason about.

## Project layout

```
flatmate-chores/
├── app/
│   ├── main.py          FastAPI routes (view roster, mark done)
│   ├── rotation.py      Pure rotation logic (unit-tested)
│   ├── config.py        Loads config.yaml
│   ├── db.py            SQLite completion tracking
│   ├── templates/       Jinja2 HTML
│   └── static/          CSS
├── config.yaml          <- edit this: people + chores
├── tests/               pytest for rotation.py
├── requirements.txt
├── run.py               Local entrypoint
└── Dockerfile
```

## Run it locally

Requires Python 3.10+.

```bash
cd flatmate-chores
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python run.py
```

Open http://127.0.0.1:8000. The `--reload` flag in `run.py` picks up code changes
automatically. After editing `config.yaml`, refresh the page.

Run the tests:

```bash
pip install pytest
python -m pytest
```

## Change people and chores

Everything lives in `config.yaml`. No code changes needed.

- `flatmates`: the rotation order.
- `tasks`: each needs a unique `id`, a `name`, and `frequency` (`weekly` or
  `monthly`). `description` is optional.

Add a person or a chore, save, refresh.

## How it works

- `week_index(date)` counts weeks from a fixed Monday; `month_index(date)` counts
  months. Assignment is `people[(period_index + task_offset) % len(people)]`.
- The `task_offset` spreads tasks in the same period across different people.
- Completion is stored per `(task_id, period_key)` where `period_key` is like
  `W-123` or `M-45`. A new week/month starts everyone fresh automatically.

## Ideas to extend

- Auth so people tick off only their own tasks
- A `/history` page reading the `completions` table
- Swap the round-robin for a fairness-aware assignment
- Push/email reminders on Monday morning
- Move from SQLite to Postgres for durable, multi-instance storage

## Deploy it (free options, as of mid-2026)

This is a single always-on web process, so a container/PaaS host fits best.

**Render (simplest free path).** Push the repo to GitHub, create a *Web Service*,
no credit card needed. Build command `pip install -r requirements.txt`, start
command:

```
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

The free tier spins the service down when idle, so the first request after a quiet
spell takes ~1 minute to wake. Fine for a household prototype. $7/mo removes the
spin-down.

**Railway.** Also git-push-to-deploy with automatic Python detection and no credit
card to start. Nicer if you later add a managed Postgres. Free usage is limited by
monthly credit; the ~$5 Hobby plan keeps it always-on.

**PythonAnywhere.** Free tier aimed at small Python apps if you prefer a web
dashboard over Git deploys.

**Google Cloud Run.** Uses the included `Dockerfile`, scales to zero, per-request
billing with a free allowance. Good if you want containerized and mostly-idle.

Note: **Fly.io no longer offers a free tier for new users** (requires a card).

### SQLite caveat on free tiers

The `chores.db` file lives on the container's local disk, which is **ephemeral** on
Render/Railway/Cloud Run free tiers. It resets on redeploy or restart. Because the
roster itself is recomputed from the date, only the "done" ticks are lost, which is
usually acceptable for a prototype. For durable ticks, attach a persistent volume or
switch `db.py` to a managed Postgres.
