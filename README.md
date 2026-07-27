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
│   ├── db.py            Postgres completion tracking
│   ├── templates/       Jinja2 HTML
│   └── static/          CSS
├── config.yaml          <- edit this: people + chores
├── tests/               pytest for rotation.py
├── requirements.txt
├── run.py               Local entrypoint
└── Dockerfile
```

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
automatically. After editing `config.yaml`, refresh the page. The `completions`
table is created automatically on startup if it doesn't exist.

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
4. **Deploy.** On first request, `app/db.py` creates the `completions` table
   automatically — no separate migration step needed.

The free web service tier spins down when idle, so the first request after a quiet
spell takes ~1 minute to wake; the Postgres connection reconnects fine after that.
$7/mo on the web service removes the spin-down.
