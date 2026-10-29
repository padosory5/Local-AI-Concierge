"""Saved agents. Each lives in its own folder in the app's data folder:

    agents/<slug>/agent.yaml   what it is: blueprint, filled-in slots
    agents/<slug>/index.json   the passages read from its files
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from ..elaina import data_dir


@dataclass
class Agent:
    name: str
    blueprint: str
    slots: dict
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    version: int = 1
    signature: str = ""  # folder_signature() when the files were last read
    # File names it reads, so the router knows "the Acme contract" is this agent's.
    contents: list[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return slugify(self.name)

    @property
    def folder(self) -> Path:
        return agents_dir() / self.slug


def agents_dir() -> Path:
    return data_dir() / "agents"


def slugify(name: str) -> str:
    slug = re.sub(r"[^\w]+", "-", name.lower(), flags=re.UNICODE).strip("-")
    return slug or "agent"


def list_agents() -> list[Agent]:
    agents = []
    for path in sorted(agents_dir().glob("*/agent.yaml")):
        try:
            agents.append(Agent(**yaml.safe_load(path.read_text(encoding="utf-8"))))
        except (OSError, TypeError, yaml.YAMLError):
            continue  # a broken file should not hide the other agents
    return agents


def find_agent(name: str) -> Agent | None:
    return next((a for a in list_agents() if a.name.lower() == name.lower()), None)


def name_taken(name: str) -> bool:
    return (agents_dir() / slugify(name)).exists()


def save(agent: Agent, index_rows: list[dict] | None = None) -> None:
    agent.folder.mkdir(parents=True, exist_ok=True)
    (agent.folder / "agent.yaml").write_text(
        yaml.safe_dump(asdict(agent), allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    if index_rows is not None:
        (agent.folder / "index.json").write_text(json.dumps(index_rows, ensure_ascii=False), encoding="utf-8")


def load_index(agent: Agent) -> list[dict]:
    try:
        return json.loads((agent.folder / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def delete(agent: Agent) -> None:
    shutil.rmtree(agent.folder, ignore_errors=True)
