"""Ready-made agents the user can add with a click or a few words.

A starter is only a filled-in form for the shared template (custom.yaml), so
adding one needs no model and cannot go wrong the way writing a new
instruction can. Code recognises the request; the router is never asked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from ..quick.agents import BUBBLE, UNTIL_UNHIGHLIGHT
from . import store
from .recipe import CUSTOM

STARTERS_PATH = Path(__file__).parent / "starters.yaml"
# "install the grammar fixer", "add Highlight Explainer", "turn on the
# explainer", "요약기 추가해줘". Longer messages are about something else.
WANTS_ADD = re.compile(r"\b(install|add|get|enable|activate|start)\b|\b(turn|switch)\s+on\b|설치|추가|켜",
                       re.IGNORECASE)
MAX_WORDS = 8


@dataclass(frozen=True)
class Starter:
    name: str
    words: tuple[str, ...]
    instruction: str
    when: str


@lru_cache(maxsize=1)
def load_starters() -> tuple[Starter, ...]:
    data = yaml.safe_load(STARTERS_PATH.read_text(encoding="utf-8"))
    return tuple(Starter(s["name"], tuple(s["words"]), s["instruction"], s["when"]) for s in data["starters"])


def asks_for(text: str) -> Starter | None:
    """The starter a short message asks to add or switch on, if any."""
    if not WANTS_ADD.search(text) or len(text.split()) > MAX_WORDS:
        return None
    lowered = text.lower()
    return next((s for s in load_starters() if any(word in lowered for word in s.words)), None)


def install(starter: Starter) -> store.Agent:
    agent = store.Agent(starter.name, CUSTOM, {
        "instruction": starter.instruction,
        "when": starter.when,
        "show": BUBBLE,
        "keep": UNTIL_UNHIGHLIGHT,
        "name": starter.name,
    })
    store.save(agent)
    return agent
