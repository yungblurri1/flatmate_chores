"""Load the flatmates and the starting chore list from config.yaml.

Who lives here is still configured by editing this one YAML file. The chores under
`tasks` only seed the database the first time the app runs against an empty one --
after that the live list is in Postgres and is edited from the web UI, so changes
survive a restart on a host with an ephemeral disk. See db.seed_tasks.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from .rotation import Task

# config.yaml lives at the project root, one level above the app/ package.
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


@dataclass(frozen=True)
class AppConfig:
    household_name: str
    people: list[str]
    seed_tasks: list[Task]


def load_config(path: str | os.PathLike | None = None) -> AppConfig:
    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH
    with open(config_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    people = [str(p) for p in raw.get("flatmates", [])]

    tasks: list[Task] = []
    for entry in raw.get("tasks", []):
        frequency = str(entry.get("frequency", "weekly")).lower()
        if frequency not in ("weekly", "monthly"):
            raise ValueError(
                f"Task {entry.get('id')!r} has invalid frequency {frequency!r}. "
                "Use 'weekly' or 'monthly'."
            )
        tasks.append(
            Task(
                id=str(entry["id"]),
                name=str(entry.get("name", entry["id"])),
                frequency=frequency,
                description=str(entry.get("description", "")),
            )
        )

    return AppConfig(
        household_name=str(raw.get("household_name", "Our Flat")),
        people=people,
        seed_tasks=tasks,
    )
