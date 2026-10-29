"""Load the blueprint library (blueprints/*.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

BLUEPRINT_DIR = Path(__file__).with_name("blueprints")


@dataclass(frozen=True)
class Slot:
    key: str
    label: str
    type: str  # "folder" or "text"
    ask: str | None
    changeable: bool = False


@dataclass(frozen=True)
class Blueprint:
    id: str
    name: str
    pitch: str
    when: str
    examples: list[str]
    slots: list[Slot]
    can_do: list[str]
    cannot_do: list[str]
    can_change_files: bool = False
    extra: dict = field(default_factory=dict)

    def slot(self, key: str) -> Slot | None:
        return next((s for s in self.slots if s.key == key), None)


def load_blueprints(directory: Path = BLUEPRINT_DIR) -> dict[str, Blueprint]:
    blueprints = {}
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        slots = [Slot(key=key, **spec) for key, spec in data.pop("slots").items()]
        known = {f for f in Blueprint.__dataclass_fields__ if f != "extra"}
        extra = {k: data.pop(k) for k in list(data) if k not in known}
        blueprints[data["id"]] = Blueprint(slots=slots, extra=extra, **data)
    return blueprints
