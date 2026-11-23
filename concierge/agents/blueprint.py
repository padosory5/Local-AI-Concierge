"""Load the blueprints (blueprints/*.yaml): the questions asked in the plain way.

What an agent can be made of is the catalog's (parts.py), and an agent is worked out in
a conversation (designer.py). A blueprint is only what is left for a computer where no
model can hold that conversation: the settings the plain questions fill in, one by one
(builder.py), and what tells the router and the idea planner that a request is for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml

BLUEPRINT_DIR = Path(__file__).with_name("blueprints")


@dataclass(frozen=True)
class Slot:
    key: str
    label: str
    type: str  # "folder", "text", "choice" or "instruction"
    ask: str | None
    changeable: bool = False
    choices: list[str] | None = None  # buttons for a "choice" slot
    default: str | None = None  # used when the user does not say


@dataclass(frozen=True)
class Blueprint:
    id: str
    name: str
    pitch: str
    when: str
    examples: list[str]
    slots: list[Slot]
    # The shared template for agents made from parts (custom.yaml): never
    # offered as a kind of agent of its own.
    generic: bool = False
    blocks: list[str] = field(default_factory=list)  # from capabilities.yaml

    def slot(self, key: str) -> Slot | None:
        return next((s for s in self.slots if s.key == key), None)


def load_blueprints(directory: Path = BLUEPRINT_DIR) -> dict[str, Blueprint]:
    blueprints = {}
    known = {item.name for item in fields(Blueprint)}
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) - known:
            # One this version doesn't know, such as one an older version shipped and an
            # install over it left behind: passed over, or the app would not start at all.
            print(f"Left out the blueprint {path.name}: it is not one this version of Noir knows.")
            continue
        slots = [Slot(key=key, **spec) for key, spec in data.pop("slots").items()]
        blueprints[data["id"]] = Blueprint(slots=slots, **data)
    return blueprints
