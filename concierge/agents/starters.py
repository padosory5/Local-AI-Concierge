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
from . import parts, store
from .recipe import CUSTOM

STARTERS_PATH = Path(__file__).parent / "starters.yaml"
# "install the grammar fixer", "add Highlight Explainer", "turn on the
# explainer", "요약기 추가해줘". Longer messages are about something else.
WANTS_ADD = re.compile(r"\b(install|add|get|enable|activate|start)\b|\b(turn|switch)\s+on\b|설치|추가|켜",
                       re.IGNORECASE)
MAX_WORDS = 8
# What may stand around a starter's word in a message that asks for that starter and for
# nothing more: "add the explainer", "can you turn on the explainer please".
_ASKING = {"install", "add", "get", "enable", "activate", "start", "turn", "switch", "on", "the", "a", "an", "my", "me",
           "please", "can", "could", "you", "i", "want", "would", "like", "to", "one", "it", "now", "too", "also",
           "helper", "agent", "for", "설치", "추가", "켜"}


@dataclass(frozen=True)
class Starter:
    name: str
    words: tuple[str, ...]
    instruction: str
    when: str
    about: str = ""  # what the Agents page says of it
    category: str = ""  # where the Agents page lists it
    skip_language: str = ""  # one that works while switched on: text already in this language is left out


@lru_cache(maxsize=1)
def load_starters() -> tuple[Starter, ...]:
    data = yaml.safe_load(STARTERS_PATH.read_text(encoding="utf-8"))
    return tuple(Starter(s["name"], tuple(s["words"]), s["instruction"], s["when"], s.get("about", ""),
                         s.get("category", ""), s.get("skip_language", "")) for s in data["starters"])


def asks_for(text: str) -> Starter | None:
    """The starter a short message asks to add or switch on, if any: one it names by its
    whole name, or by one of its words with nothing else said. A message that says what
    the helper should do is a helper to work out, never a ready-made one picked by a word:
    asked for one that sums up what lands in the downloads folder, they were given one that
    answers in the chat, and "get me an explainer for error messages" one for highlights."""
    if not WANTS_ADD.search(text) or len(text.split()) > MAX_WORDS:
        return None
    lowered = text.lower()
    for starter in load_starters():
        if starter.name.lower() in lowered:
            return starter
        for word in starter.words:
            if word in lowered:
                left = [w for w in re.findall(r"[a-z가-힣']+", lowered.replace(word, " ")) if w not in _ASKING]
                if not left:
                    return starter
    return None


def install(starter: Starter) -> store.Agent:
    slots = {
        "instruction": starter.instruction,
        "when": starter.when,
        "show": BUBBLE,
        "keep": UNTIL_UNHIGHLIGHT,
        "name": starter.name,
    }
    if starter.skip_language:
        slots["skip_language"] = starter.skip_language
    # Whatever a card of its WHEN can say and the recipe doesn't, with its usual value.
    slots.update(parts.defaults(slots))
    agent = store.Agent(starter.name, CUSTOM, slots)
    store.save(agent)
    return agent
