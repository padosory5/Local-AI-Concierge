"""Agents to discover, and sharing your own.

An agent that works on text is only words: a name, one instruction and a few settings,
never code, so it's safe to share and safe to add. An agent that works on a folder, or
answers from one, can't be shared, because it's made of someone's own files and where
they keep them; and nothing that comes from the internet is ever let near a folder.

The list everyone sees is community.json in a public GitHub repository of its own, so
it needs no server and the project's code can stay private. Posting opens a GitHub
page in the browser with the agent filled in, the user presses Submit, and one of the
project's people reads it and adds it to the list. Nothing goes live without someone
looking at it first. Whatever comes from the internet is checked here again before
it's shown, and only known settings are kept.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlencode

import requests

from ..noir import data_dir
from ..quick.agents import BOTH, BUBBLE, CLIPBOARD, FEW_SECONDS, UNTIL_UNHIGHLIGHT
from . import parts, store
from .parts import CUSTOM, IN_CHAT, WHILE_ON
from .recipe import MAX_INSTRUCTION
from .starters import load_starters

REPOSITORY = "padosory5/noir-agents"
INDEX_PATH = Path(__file__).with_name("community.json")
INDEX_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/main/community.json"
POST_URL = f"https://github.com/{REPOSITORY}/issues/new"
TIMEOUT = 6
CACHE_SECONDS = 600
MAX_NAME, MAX_ABOUT, MAX_BY = 40, 140, 40
READY_MADE, COMMUNITY = "Noir", "Community"
CATEGORIES = ("Writing", "Study", "Work", "Languages", "Code", "Everyday")
OTHER_CATEGORY = "Everyday"
# The languages a recipe may say it leaves out text in: the ones the catalog's own setting
# allows, so a recipe can never promise more than a card can do.
_SKIP_LANGUAGES = next(setting.choices for setting in parts.all_settings() if setting.key == "skip_language")


class PostError(ValueError):
    """Written for the user."""


@dataclass(frozen=True)
class Recipe:
    id: str
    name: str
    by: str
    category: str
    about: str
    instruction: str
    when: str
    show: str = BUBBLE
    keep: str = UNTIL_UNHIGHLIGHT
    example: str = ""
    source: str = COMMUNITY
    # Only for one that works while switched on: text already in this language is left out.
    skip_language: str = ""


def _words(value, limit: int) -> str:
    """Plain text on one line, cut to size. Anything else counts as nothing."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\x00-\x1f\x7f]+", " ", value).strip()[:limit]


def clean(raw) -> Recipe | None:
    """A recipe from outside, or None if it isn't one. Settings can only be ones the
    app knows, so an entry can never carry anything but words."""
    if not isinstance(raw, dict):
        return None
    name = _words(raw.get("name"), MAX_NAME)
    instruction = _words(raw.get("instruction"), MAX_INSTRUCTION + 1)
    when = raw.get("when", IN_CHAT)
    show, keep = raw.get("show", BUBBLE), raw.get("keep", UNTIL_UNHIGHLIGHT)
    if not name or not instruction or len(instruction) > MAX_INSTRUCTION:
        return None
    if when not in (WHILE_ON, IN_CHAT) or show not in (BUBBLE, CLIPBOARD, BOTH) or keep not in (UNTIL_UNHIGHLIGHT, FEW_SECONDS):
        return None
    # A language to leave out must be one the app can tell a text is in. Anything else is
    # refused like any other setting it doesn't know, never passed on to be ignored later.
    skip = raw.get("skip_language") or ""
    if skip not in ("", *_SKIP_LANGUAGES):
        return None
    source = READY_MADE if raw.get("source") == READY_MADE else COMMUNITY
    category = raw.get("category") if raw.get("category") in CATEGORIES else OTHER_CATEGORY
    return Recipe(store.slugify(name), name, _words(raw.get("by"), MAX_BY) or "Someone", category,
                  _words(raw.get("about"), MAX_ABOUT) or instruction[:MAX_ABOUT], instruction, when, show, keep,
                  _words(raw.get("example"), MAX_ABOUT), source,
                  skip if when == WHILE_ON else "")  # a setting of that WHEN only


def _starters() -> list[Recipe]:
    # What the Agents page says of each is the starter's own (starters.yaml), like the rest of it.
    made = []
    for starter in load_starters():
        category = starter.category if starter.category in CATEGORIES else OTHER_CATEGORY
        made.append(Recipe(store.slugify(starter.name), starter.name, READY_MADE, category,
                           starter.about or starter.instruction[:MAX_ABOUT], starter.instruction, starter.when,
                           source=READY_MADE, skip_language=starter.skip_language))
    return made


def _read(text: str) -> list[Recipe]:
    try:
        entries = json.loads(text)
    except ValueError:
        return []
    return [recipe for recipe in map(clean, entries if isinstance(entries, list) else []) if recipe]


_saved: tuple[float, list[Recipe]] = (0, [])


def recipes(online: bool = True) -> list[Recipe]:
    """Everything to discover. The list on the internet when it can be read, the
    last one seen when it can't, and the one that came with the app before that."""
    global _saved
    when, found = _saved
    if online and found and time.monotonic() - when < CACHE_SECONDS:
        return found
    copy = data_dir() / "community.json"
    posted: list[Recipe] = []
    if online:
        try:
            reply = requests.get(INDEX_URL, timeout=TIMEOUT)
            posted = _read(reply.text) if reply.ok else []
        except requests.RequestException:
            pass
        if posted:
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_text(reply.text, encoding="utf-8")
        else:
            try:
                posted = _read(copy.read_text(encoding="utf-8"))
            except OSError:
                pass
    posted = posted or _read(INDEX_PATH.read_text(encoding="utf-8"))
    ready = _starters()
    taken = {recipe.id for recipe in ready}
    found = ready + [recipe for recipe in posted if recipe.id not in taken]
    if online:
        _saved = (time.monotonic(), found)
    return found


def find(id: str, online: bool = True) -> Recipe | None:
    return next((recipe for recipe in recipes(online) if recipe.id == id), None)


def install(recipe: Recipe) -> store.Agent:
    """Adds it, unless the user already has one by that name. What's theirs is never replaced."""
    existing = store.find_agent(recipe.name)
    if existing:
        return existing
    slots = {"instruction": recipe.instruction, "when": recipe.when, "show": recipe.show, "keep": recipe.keep,
             "name": recipe.name}
    if recipe.skip_language:
        slots["skip_language"] = recipe.skip_language
    # Whatever a card of its WHEN can say and the recipe doesn't, with its usual value.
    slots.update(parts.defaults(slots))
    agent = store.Agent(recipe.name, CUSTOM, slots)
    store.save(agent)
    return agent


def can_post() -> bool:
    """Whether the shared repository is there and takes posts, so nobody is sent to a dead page."""
    try:
        reply = requests.get(f"https://api.github.com/repos/{REPOSITORY}", timeout=TIMEOUT)
        return reply.ok and bool(reply.json().get("has_issues"))
    except (requests.RequestException, ValueError):
        return False


def post_address(agent: store.Agent, about: str, category: str, by: str = "") -> str:
    """The GitHub page that posts this agent, filled in. Only the recipe goes in it,
    built field by field, so nothing else an agent holds can ever slip out."""
    if agent.blueprint != CUSTOM or parts.watches(agent):
        raise PostError("An agent that works on one of your folders can't be shared, because it's made of your own "
                        "files and where you keep them.")
    about = _words(about, MAX_ABOUT)
    if not about:
        raise PostError("Please say in one line what it does.")
    rule = _words(agent.slots.get("instruction"), parts.MAX_RULE + 1)
    if len(rule) > MAX_INSTRUCTION:
        # A rule worked out by talking can be twice as long as a shared one may be. Said,
        # never cut: half a rule is another rule.
        raise PostError(f"Its rule is too long to share: it is {len(rule)} characters, and a shared one can be at "
                        f"most {MAX_INSTRUCTION}.")
    settings = ("instruction", "when", "show", "keep", "skip_language")
    recipe = clean({**{key: agent.slots.get(key) for key in settings if agent.slots.get(key)},
                    "name": agent.name, "about": about, "category": category, "by": _words(by, MAX_BY) or "Someone"})
    if recipe is None:
        raise PostError("This agent can't be shared as it is.")
    entry = {key: value for key, value in asdict(recipe).items()
             if key not in ("id", "source", "example") and not (key == "skip_language" and not value)}
    body = ("I'd like to share this agent. Please read it, and add it to "
            f"community.json if it looks good.\n\n```json\n{json.dumps(entry, ensure_ascii=False, indent=1)}\n```\n")
    return f"{POST_URL}?{urlencode({'title': f'New agent: {recipe.name}', 'body': body})}"
