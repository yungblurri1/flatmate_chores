"""Load the flatmates and tasks from config.yaml.

Editing the roster means editing one YAML file. No code changes needed to add a
person or a chore, which is the main thing that keeps this app extensible.
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
    tasks: list[Task]


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
        tasks=tasks,
    )
