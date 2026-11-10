"""Create an agent with the user: offer it, fill in its slots, show the agent
card, and on "Create it" save it and give it a test drive.

Code drives every step. The model only pulls a folder name out of what the
user typed, and writes the test-drive question. Languages are recognised in
code (quick/translate.py).

A blueprint that says how it works (`facts`) can be talked through instead, when
the engine has a model fit to do it (conductor.py): that model takes each turn and
fills a form, and code here checks every value, keeps the draft and shows the card
(`_conduct`, `_take_form`). The card is still the only thing that makes an agent.
"""

from __future__ import annotations

import json
import os
import sys
import re
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from ..catalog import find_model
from ..noir import load_state
from ..events import AgentCard, AgentList, NoirDone, NoirText, Event, Progress, Question, Result, Thinking
from ..ollama import Ollama, OllamaError
from . import runner, store
from .blueprint import Blueprint, Slot
from .conductor import (CALLED_OFF, CONDUCT, INSIDE, MOVED_ON, NOTHING_MISSING, PLACE_NAMES, PLACE_SLOTS, STILL_ASKING,
                        Conductor, ConductorError, needed)
from .files import scan
from ..organizer import (BY_NAME, CONTENT, ORGANIZER, SUMMARIZER, courses_in, destination_from, folder_name, groups_from,
                         organizer_card, summarizer_card, watched_from)
from ..places import known_folder
from ..quick.agents import BOTH, CLIPBOARD
from ..quick.translate import LANGUAGES, language_in
from .recipe import (CUSTOM, IN_CHAT, MECHANICS, WHILE_ON, needs_language, rewrite_instruction, run_instruction,
                     settings_from_words, target_language, with_language, write_recipe)
from .talk import phrase

PLACES = ["Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos"]
CANCEL_WORDS = ("cancel", "never mind", "nevermind", "forget it", "no thanks", "stop", "취소", "그만")
YES_WORDS = ("yes", "yeah", "yep", "sure", "ok", "okay", "create", "do it", "go ahead", "응", "네", "좋아")
# Folders an agent may never read, even if the user names them.
BLOCKED = ([Path(os.environ.get(v, "")) for v in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData")]
           if sys.platform == "win32" else
           [Path(p) for p in ("/System", "/Library", "/Applications", "/usr", "/bin", "/sbin", "/etc", "/private",
                              "/var", "/opt")])
SKIP_WHILE_SEARCHING = {"appdata", "node_modules", ".git", "$recycle.bin", "library"}

CARD, CHANGE, PICK_FOLDER, DUPLICATE = "card", "change", "pick_folder", "duplicate"
REPLACE, MAKE_ANOTHER = "Replace it", "Make another one"
CREATE_IT, SAVE_CHANGES = "Create it", "Save changes"
TARGET_LANGUAGE = "target_language"  # asked when a translator does not say which language
LANGUAGE_CHOICES = ["Korean", "English", "Japanese", "Chinese", "Spanish"]
# "rename it to Lease helper", "call it My translator"
RENAME = re.compile(r"\b(?:rename\b.*?\b(?:to|as)|call it)\s+[\"']?(.+?)[\"']?\s*[.!]?$", re.IGNORECASE)
# How an organizer tells files apart, in the user's words.
BY_CONTENT_WORDS = re.compile(r"inside|contents?|what (it|they|the files?)('s| is| are| was)? about|what's in", re.IGNORECASE)
BY_NAME_WORDS = re.compile(r"\bby (their |the |file )?names?\b|filenames?", re.IGNORECASE)
# A whole message that is a yes to the card on screen, in a setup that is talked through.
# Only the whole message counts: "ok but put them in Documents" is a change, not a yes.
CARD_YES = (*YES_WORDS, "create it", "yes please", "sounds good", "ok sounds good", "okay sounds good", "looks good",
            "looks right", "perfect", "that's right", "thats right")
# The user giving the agent itself a name: "call it Homework sorter", "an agent called X".
NAMES_IT = re.compile(r"\b(call|name) (it|this|the (agent|helper|organi[sz]er|assistant))\b|"
                      r"\b(agent|helper|assistant|organi[sz]er|writer) (called|named)\b|\brename (it|the (agent|helper))\b",
                      re.IGNORECASE)
NOT_KNOWN = "not known yet"
A_PATH = re.compile(r"^([A-Za-z]:[\\/]|~|/)")
MAX_COUNTED = 5000  # files looked at when telling the conductor what a folder holds
SYSTEM_FOLDER = "That's a system folder, so for safety a helper can't use it."


@dataclass(frozen=True)
class Refused:
    """A value in the conductor's form that code didn't take."""
    key: str  # the setting
    value: str  # what the form gave, to know it again
    told: str  # for the model: why not, and what would be right
    said: str  # for the user, in plain words, if the model doesn't put it right


@dataclass
class Draft:
    blueprint: Blueprint
    slots: dict = field(default_factory=dict)
    waiting: str | None = None  # slot key we asked for, or CARD / PICK_FOLDER / CHANGE
    file_count: int = 0
    file_summary: str = ""
    duplicate_of: str | None = None  # existing agent that reads the same folder
    replaces: str | None = None  # agent to delete when this one is created
    # The name came from the slots ("Korean translator"), so it follows them
    # when they change; a name the user typed is kept.
    name_is_auto: bool = True
    request: str = ""  # the message that started it
    editing: bool = False  # changing an existing agent rather than making one
    example: str = ""  # a piece of text to test an agent made from parts on
    duplicate_asked: bool = False
    # A setup that is talked through (conductor.py): the model taking the turns, the
    # setup's own conversation, and the settings the card last showed.
    conductor: Conductor | None = None
    turns: list = field(default_factory=list)
    card_slots: dict | None = None
    ignored: set = field(default_factory=set)  # (setting, value) refused twice: passed over from then on


class AgentBuilder:
    def __init__(self, ollama: Ollama, model: str, think: bool | None, blueprints: dict[str, Blueprint]):
        self.ollama = ollama
        self.model = model
        self.think = think
        self.blueprints = blueprints
        self.draft: Draft | None = None
        # Set when the user moved on to something else mid-setup: the engine
        # handles this text normally after the setup has been dropped.
        self.handoff: str | None = None
        # Set by the engine: who talks a setup through right now, or None for the plain
        # questions. Asked at each start, so a change in the model menu applies at once.
        self.conductor: Callable[[], Conductor | None] | None = None
        self.conducted = False  # whether the agent made last was talked through

    def take_created(self) -> store.Agent | None:
        """The agent made by the last Create it, once; None otherwise."""
        created, self.created = getattr(self, "created", None), None
        return created

    @property
    def active(self) -> bool:
        return self.draft is not None

    # ------------------------------------------------------------ entry

    def start(self, blueprint_id: str, request: str) -> Iterator[Event]:
        bp = self.blueprints[blueprint_id]
        self.draft = Draft(bp, request=request)
        conductor = self.conductor() if self.conductor and bp.extra.get("facts") else None
        if conductor is not None:
            yield from self._start_conducted(conductor, request)
            return
        yield from self._say(f"I can make you an agent for that: {bp.name}. {bp.pitch.strip()}", [bp.name])
        self._prefill(request)
        if self.draft.slots:
            found = "; ".join(f"{bp.slot(k).label.lower()}: {v}" for k, v in self.draft.slots.items() if bp.slot(k))
            yield Thinking(f"From your message: {found}.")
        if bp.extra.get("watches") and (watched := watched_from(request)) and watched.is_dir():
            # "from Downloads": the folder to watch, said plainly. Asked as a free question, the
            # model once took "a folder on my desktop called College", the destination, for it.
            yield from self._use_folder(watched)
        elif bp.slot("folder"):
            yield from self._take_folder(request, from_request=True)
        else:
            yield from self._next()

    def start_for_folder(self, blueprint_id: str, folder: Path, request: str) -> Iterator[Event]:
        """The user already showed which folder, with the + button."""
        bp = self.blueprints[blueprint_id]
        self.draft = Draft(bp, request=request)
        yield from self._say(f"I can make you an agent for that: {bp.name}. {bp.pitch.strip()}", [bp.name])
        yield from self._use_folder(folder)

    def compose(self, request: str, blocks: list[str]) -> Iterator[Event]:
        """Make an agent from an idea's parts, with no kind of agent behind it:
        the shared template (custom.yaml) filled in from the parts, and an
        instruction Noir writes for what it does with the text."""
        self.draft = Draft(self.blueprints[CUSTOM], request=request, name_is_auto=False)
        slots = self.draft.slots
        slots["when"] = WHILE_ON if {"while_on", "selected_text"} & set(blocks) else IN_CHAT
        # How it shows the result comes from the user's own words: the model's
        # parts said "clipboard" for "translate my highlighted texts", and the
        # user saw nothing. A highlight helper shows a bubble unless told otherwise.
        slots.update(settings_from_words(request))
        recipe = write_recipe(self.ollama, self.model, request, self.think)
        if not recipe["instruction"]:
            self.draft = None
            yield from say("I couldn't work out what it should do. Could you say it another way?")
            return
        instruction = recipe["instruction"]
        if target_language(instruction) or needs_language(instruction):
            # A translator: the language is the user's to say. Told "never guess",
            # the model still wrote "into English unless another is requested".
            language = language_in(request, target_only=True)
            instruction = with_language(instruction, language) if language else "Translate the text."
        slots["instruction"] = instruction
        slots["name"] = self._unique_name(recipe["name"])
        self.draft.example = recipe["example"]
        yield Thinking(f'Wrote what it does: "{instruction}"')
        if needs_language(instruction):
            # Never guess: the model once picked Spanish for "translate my texts".
            self.draft.waiting = TARGET_LANGUAGE
            yield Question(TARGET_LANGUAGE, "Which language should it translate into?", LANGUAGE_CHOICES)
            return
        yield from self._next()

    def edit(self, agent: store.Agent, request: str) -> Iterator[Event]:
        """Change an existing agent: apply what the message asks, then show its
        card with Save changes. Nothing is saved until the user says so."""
        bp = self.blueprints.get(agent.blueprint)
        if bp is None:
            yield from say(f"I don't know how to change {agent.name}.")
            return
        self.draft = Draft(bp, slots=dict(agent.slots), replaces=agent.name, name_is_auto=False,
                           request=request, editing=True, duplicate_asked=True)
        # Compared with what is stored, so asking for a setting the agent was
        # made without (it only had the default) still counts as a change.
        changes = self._changes(request)
        for slot in bp.slots:  # settings added since the agent was made
            if slot.key not in self.draft.slots and slot.default:
                self.draft.slots[slot.key] = slot.default
        if "folder" in self.draft.slots:
            files = scan(Path(self.draft.slots["folder"])).files
            self.draft.file_count, self.draft.file_summary = len(files), describe_files(files)
        already = self._asked_for(request)
        if changes:
            found = "; ".join(f"{bp.slot(k).label.lower()} → {v}" for k, v in changes.items() if bp.slot(k))
            yield Thinking(f"Changes in your message: {found}.")
            self.draft.slots.update(changes)
            yield from say(f"Here's {agent.name} with that change. Save it to keep it.")
            yield from self._show_card()
        elif already:
            self.draft = None
            settings = "; ".join(f"{label.lower()}: {value.lower()}" for label, value in already)
            yield from say(f"{agent.name} already works that way ({settings}). If it doesn't seem to, "
                           "switch it off and on again in your helpers list.")
        else:
            yield from self._cannot_change(agent.name)

    def _asked_for(self, text: str) -> list[tuple[str, str]]:
        """Settings the message names that the agent already has, as (label, value)."""
        found = []
        for slot in self.draft.blueprint.slots:
            if slot.type == "choice" and slot.changeable:
                value = self._match_choice(slot.key, text)
                if value and value == self.draft.slots.get(slot.key):
                    found.append((slot.label, value))
        return found

    def _cannot_change(self, name: str) -> Iterator[Event]:
        labels = [s.label for s in self.draft.blueprint.slots if s.changeable]
        yield from say(f"That isn't something I can change on {name} yet. I can change: "
                       f"{', '.join(label.lower() for label in labels)}.")
        self.draft.waiting = CHANGE
        yield Question(CHANGE, "What would you like to change?", labels + ["Nothing, go back"])

    def answer(self, text: str) -> Iterator[Event]:
        """The user typed something while an agent is being set up."""
        draft = self.draft
        lowered = text.strip().lower()
        if any(lowered == w or lowered.startswith(w + " ") for w in CANCEL_WORDS):
            yield from self._cancel()
        elif draft.conductor is not None:
            whole = lowered.strip("!. ")
            if draft.waiting == CARD and whole in CARD_YES:
                yield from self._create()
            elif draft.waiting == CARD and whole in ("no", "nope", "아니"):
                yield from self._cancel()
            else:
                draft.turns.append({"role": "user", "content": text})
                yield from self._next()
        elif draft.waiting in ("folder", PICK_FOLDER) and self._answer_any_slot(text):
            yield from self._next()  # answered another question first; the folder is asked again
        elif draft.waiting in ("folder", PICK_FOLDER):
            yield from self._take_folder(text)
        elif draft.waiting == "name":
            yield from self._take_name(text)
        elif self._slot_type(draft.waiting) == "language":
            yield from self._take_language(text)
        elif self._slot_type(draft.waiting) == "instruction":
            yield from self._take_instruction(text)
        elif draft.waiting == TARGET_LANGUAGE:
            yield from self._take_target_language(text)
        elif self._slot_type(draft.waiting) == "text":
            yield from self._set_slot(draft.waiting, self._plain(draft.waiting, text))
        elif self._slot_type(draft.waiting) == "choice" and self._match_choice(draft.waiting, text):
            yield from self._set_slot(draft.waiting, self._match_choice(draft.waiting, text))
        elif draft.waiting == CARD and any(lowered == w or lowered.startswith(w) for w in YES_WORDS):
            yield from self._create()
        elif draft.waiting == CARD and lowered in ("no", "nope", "아니"):
            yield from self._cancel()
        elif draft.waiting in (CARD, CHANGE) and (changes := self._changes(text)):
            # "and make it Japanese" typed at the card: change it there.
            draft.slots.update(changes)
            yield from self._show_card()
        elif self._answer_any_slot(text):
            yield from self._next()
        else:
            # Waiting for a button but the user typed something else: they
            # moved on, so drop the setup and let the engine handle it.
            self.draft = None
            self.handoff = text
            yield from say("I'll leave the agent setup for now.")

    def choose(self, id: str, choice: str) -> Iterator[Event]:
        draft = self.draft
        if draft.conductor is not None and id != CARD:
            draft.turns.append({"role": "user", "content": choice})  # a click is said, like anything typed
        # Talked through, the card can be up and current while Noir has just asked something.
        card_up = draft.conductor is not None and draft.card_slots == draft.slots
        if id == CARD and draft.waiting != CARD and not card_up:
            yield from self._next()  # the card isn't up yet: the open question is asked again
        elif id == CARD and choice in (CREATE_IT, SAVE_CHANGES):
            yield from self._create()
        elif id == CARD and choice == "Change something" and draft.conductor is not None:
            # Talked through, a change is said in words, not picked from a list of settings.
            draft.waiting = CONDUCT
            draft.turns.append({"role": "assistant", "content": "What should I change?"})
            yield Question(CONDUCT, "What should I change?")
        elif id == CARD and choice == "Change something":
            labels = [s.label for s in draft.blueprint.slots if s.changeable]
            draft.waiting = CHANGE
            yield Question(CHANGE, "What would you like to change?", labels + ["Nothing, go back"])
        elif id == CARD:
            yield from self._cancel()
        elif id == CHANGE:
            slot = next((s for s in draft.blueprint.slots if s.label == choice), None)
            if slot is None and draft.editing and not self._changed():
                yield from self._cancel()
            elif slot is None:
                yield from self._show_card()
            elif slot.key == "folder":
                draft.waiting = "folder"
                yield Question("folder", "Which folder should it read instead?")
            elif slot.type in ("language", "choice"):
                draft.waiting = slot.key
                yield Question(slot.key, slot.ask or f"{slot.label}?", slot.choices)
            elif slot.type == "instruction":
                draft.waiting = slot.key
                yield Question(slot.key, "What should it do instead? Describe it in your own words.")
            else:
                draft.waiting = slot.key
                yield Question(slot.key, f"What should the {slot.label.lower()} be?")
        elif id == DUPLICATE and not draft.duplicate_of:
            yield from say("That question has already been answered.")
        elif id == DUPLICATE and choice.startswith("Use "):
            name = draft.duplicate_of
            if draft.conductor is not None:
                draft.conductor.done()
            self.draft = None
            if draft.blueprint.id == ORGANIZER:
                yield from say(f'Okay, keep using {name}. Say "organize it" and it goes through what has landed since '
                               'it was switched on, or "go through everything" for all of it.')
            elif draft.blueprint.switchable:
                yield from say(f"Okay, keep using {name}. Switch it on in your helpers list.")
            else:
                yield from say(f'Okay, keep using {name}. Ask it anything, like "{name}: what does it say about...".')
        elif id == DUPLICATE and choice.startswith("Change "):
            existing = store.find_agent(draft.duplicate_of)
            if draft.conductor is not None:
                draft.conductor.done()  # changing an agent they have is the plain way, for now
            if existing:
                yield from self.edit(existing, draft.request)
        elif id == DUPLICATE and choice == REPLACE:
            draft.replaces = draft.duplicate_of
            draft.slots["name"] = draft.duplicate_of
            yield from say(f"Okay. When you create this one, it replaces {draft.duplicate_of}.")
            yield from self._next()
        elif id == DUPLICATE:
            yield from self._next()
        elif id == TARGET_LANGUAGE:
            yield from self._take_target_language(choice)
        elif self._slot_type(id) == "language":
            yield from self._take_language(choice)
        elif self._slot_type(id) == "choice":
            yield from self._set_slot(id, choice)
        elif self._slot_type(id) == "text":
            yield from self._set_slot(id, self._plain(id, choice))
        elif id == PICK_FOLDER and choice != "None of these":
            yield from self._use_folder(Path(choice))
        elif id == PICK_FOLDER:
            draft.waiting = "folder"
            yield Question("folder", "Which folder should it read? A full path works best.")
        else:
            yield from say("That question has already been answered.")

    # ------------------------------------------------------------ slots

    def _take_folder(self, text: str, from_request: bool = False) -> Iterator[Event]:
        draft = self.draft
        name, place = self._folder_words(text)
        if not (name or place) and not from_request:
            # No folder in it at all: the user moved on ("who signed the Acme
            # deal?"). Drop the setup instead of trapping them in it.
            self.draft = None
            self.handoff = text
            yield from say("I'll leave the agent setup for now.")
            return
        found = find_folders(name, place) if (name or place) else []
        if len(found) == 1:
            yield from self._use_folder(found[0])
        elif len(found) > 1:
            draft.waiting = PICK_FOLDER
            yield Question(PICK_FOLDER, "I found more than one folder like that. Which one?",
                           [str(p) for p in found] + ["None of these"])
        else:
            if not from_request:
                missing = f'a folder called "{name}"' if name else "that folder"
                yield from say(f"I couldn't find {missing}.")
            draft.waiting = "folder"
            yield Question("folder", draft.blueprint.slot("folder").ask)

    def _use_folder(self, folder: Path) -> Iterator[Event]:
        draft = self.draft
        if is_blocked(folder):
            draft.waiting = "folder"
            yield from say("That's a system folder, so for safety an agent can't read it.")
            yield Question("folder", "Which other folder should it read?")
            return
        if draft.blueprint.extra.get("watches") and draft.slots.get("into") and Path(draft.slots["into"]) == folder:
            draft.waiting = "folder"
            yield from self._say(f"{folder.name} is where the sorted folders go, not where new files land.",
                                 [folder.name])
            yield self._question("folder", "Which folder should it watch for new files? Downloads is where most "
                                 "things land.")
            return
        yield Progress(f"Looking in {folder}...")
        files = scan(folder).files
        if draft.blueprint.extra.get("watches"):
            # Watched, not read for answers: it may be empty today, and another kind of
            # agent reading the same folder is no duplicate.
            draft.slots["folder"] = str(folder)
            draft.file_count = len(files)
            draft.file_summary = describe_files(files) if files else "nothing to read yet"
            yield from self._next()
            return
        if not files:
            draft.waiting = "folder"
            yield from say(f"{folder} has no files I can read. I can read PDF, Word and text files.")
            yield Question("folder", "Which other folder should it read?")
            return
        draft.slots["folder"] = str(folder)
        draft.file_count = len(files)
        draft.file_summary = describe_files(files)
        readable = re.sub(r"[_\-]+", " ", folder.name).strip()
        draft.slots.setdefault("name", self._unique_name(f"{readable} helper"))

        existing = agent_for_folder(folder)
        if existing and draft.replaces != existing.name:
            draft.duplicate_of = existing.name
            draft.waiting = DUPLICATE
            yield Question(
                DUPLICATE,
                f"You already have {existing.name}, which reads this folder. What would you like to do?",
                [f"Use {existing.name}", REPLACE, MAKE_ANOTHER],
            )
            return
        yield from self._next()

    def _answer_any_slot(self, text: str) -> bool:
        """An answer typed for a question not asked yet ("just keep them inside that folder"
        while the folder is still being chosen, "decide as you go" to the folder question):
        filled in where it fits, so the setup goes on instead of being dropped. One slot at
        most, and only when the words say which."""
        draft = self.draft
        lowered = text.lower()
        open_slots = [s for s in draft.blueprint.slots if s.key not in draft.slots and s.key not in ("folder", "name")]
        by_phrase = [s for s in open_slots if any(c.lower() in lowered for c in (s.choices or []))]
        if len(by_phrase) == 1:
            slot = by_phrase[0]
            choice = next(c for c in slot.choices if c.lower() in lowered)
            draft.slots[slot.key] = self._plain(slot.key, choice) if slot.type == "text" else choice
            return True
        for slot in open_slots:
            if slot.key == "groups" and groups_from(text) == "Decide as you go":
                draft.slots["groups"] = groups_from(text)
                return True
            if slot.key == "into" and destination_from(text) is not None and re.search(r"\b(in|into|on|inside)\b", lowered):
                draft.slots["into"] = destination_from(text)
                return True
            if slot.key == "by" and BY_CONTENT_WORDS.search(text):
                draft.slots["by"] = CONTENT
                return True
            if slot.key == "by" and BY_NAME_WORDS.search(text):
                draft.slots["by"] = BY_NAME
                return True
        return False

    def _take_name(self, text: str) -> Iterator[Event]:
        name = text.strip().strip("\"'")[:40]
        if not name:
            yield Question("name", "What should it be called?")
            return
        if store.name_taken(name) and name.lower() != (self.draft.replaces or "").lower():
            yield from say(f"You already have an agent called {name}.")
            yield Question("name", "What should this one be called?")
            return
        self.draft.slots["name"] = name
        self.draft.name_is_auto = False
        yield from self._next()

    def _next(self) -> Iterator[Event]:
        """Ask for the next empty slot, or show the card when all are filled."""
        draft = self.draft
        # As soon as it is clear this would repeat an agent the user already
        # has, ask about that first, before any more setup questions.
        existing = None if draft.duplicate_asked else self._same_agent()
        if existing:
            draft.duplicate_asked = True
            draft.duplicate_of = existing.name
            draft.waiting = DUPLICATE
            yield Question(DUPLICATE, f"You already have {existing.name}, which does the same. "
                           "What would you like to do?",
                           [f"Use {existing.name}", f"Change {existing.name}", MAKE_ANOTHER])
            return
        if draft.conductor is not None:
            yield from self._conduct()
            return
        for slot in draft.blueprint.slots:
            if slot.key not in draft.slots and slot.ask:
                draft.waiting = slot.key
                yield self._question(slot.key, slot.ask, slot.choices)
                return
            if slot.key not in draft.slots and slot.default:
                draft.slots[slot.key] = slot.default
        if draft.blueprint.default_name and (draft.name_is_auto or "name" not in draft.slots):
            draft.slots["name"] = self._unique_name(_fill(draft.blueprint.default_name, draft.slots))
        yield from self._show_card()

    # ------------------------------------------------ a setup talked through

    def _start_conducted(self, conductor: Conductor, request: str) -> Iterator[Event]:
        """The first turn of a setup a model talks through. What code can read for sure in
        the request is filled in first (course codes, "from Downloads", "by name"); where
        the folders go is left to the conversation, since any place word in the request
        used to be taken for it."""
        draft = self.draft
        draft.conductor = conductor
        draft.turns.append({"role": "user", "content": request})
        sees = "" if conductor.here else " It sees what you type and your folders' names, never what's in your files."
        yield Thinking(f"Setting up a helper is a conversation, so {conductor.name} talks it through with you.{sees}")
        if conductor.waking():
            yield Thinking(f"Loading {conductor.name} first, which takes a few seconds.")
        self._prefill(request, skip=("into",))
        if draft.blueprint.extra.get("watches") and (watched := watched_from(request)) and watched.is_dir():
            self._set_folder(watched)
        yield from self._next()

    def _conduct(self) -> Iterator[Event]:
        """One turn of a setup that is talked through: the conductor fills its form, code
        checks each value and keeps the draft, and what the model says is shown, with the
        card once nothing needed is missing. A value code refuses goes back to the model
        once, with the reason and what would be right; refused twice, code says its own
        plain line and the value is not listened to again unless the user brings it up.
        Whatever the model says about where things stand, nothing is made here."""
        draft = self.draft
        conductor, bp = draft.conductor, draft.blueprint
        if not draft.turns or draft.turns[-1]["role"] != "user":
            # Nothing new was said (a click on a card that isn't up yet): the open question again.
            last = next((turn["content"] for turn in reversed(draft.turns) if turn["role"] == "assistant"), "")
            yield Question(draft.waiting or CONDUCT, last or "What should it do?")
            return
        first = sum(turn["role"] == "user" for turn in draft.turns) == 1
        before = dict(draft.slots)
        refused: list[Refused] = []
        nudges: list[str] = []
        stumbled = False  # code refused something in this turn, even if the model then put it right
        try:
            for _ in range(2):
                turn = conductor.turn(bp, self._known(), self._facts(), draft.turns,
                                      [refusal.told for refusal in refused] + nudges, first,
                                      card_up=draft.card_slots is not None)
                refused = self._take_form(turn.values)
                stumbled = stumbled or bool(refused)
                missing = self._missing()
                labels = ", ".join(slot.label for slot in missing)
                nudges = []
                if missing and turn.status == NOTHING_MISSING:
                    nudges.append(f"Still not known: {labels}. Don't say it is ready; ask for the first of them.")
                elif missing and turn.status == STILL_ASKING and "?" not in turn.say:
                    nudges.append(f"You asked nothing, and this is still not known: {labels}. Say what you said, "
                                  "then ask for the first of them.")
                if not refused and not nudges:
                    break
        except ConductorError as exc:
            # It keeps talking whatever happens to the model: the plain questions take over.
            yield Thinking(f"{conductor.name} couldn't carry on ({exc}), so I'll ask the plain questions instead.")
            conductor.done()
            draft.conductor = None
            yield from self._next()
            return
        # Refused twice: said once, below, and after that the same value is passed over, or
        # every later answer would be "I can't find a folder called College" again.
        draft.ignored |= {(refusal.key, refusal.value) for refusal in refused}
        if turn.status == CALLED_OFF:
            conductor.done()
            self.draft = None
            yield from say(turn.say or "Okay, I won't create it.")
            return
        if turn.status == MOVED_ON:
            # Their message was about something else: the engine handles it as any message.
            conductor.done()
            self.draft = None
            self.handoff = draft.turns[-1]["content"]
            yield from say("I'll leave the agent setup for now.")
            return
        learned = [f"{slot.label.lower()}: {self._shown(slot)}" for slot in bp.slots
                   if slot.key in draft.slots and before.get(slot.key) != draft.slots[slot.key]]
        if learned:
            yield Thinking("Understood so far: " + "; ".join(learned) + ".")
        missing = self._missing()
        words, asks = turn.say, turn.asks
        if refused or (missing and (nudges or not words)):
            # Refused twice, or still no question: code's own plain words, so nothing wrong is said.
            words = " ".join([refusal.said for refusal in refused] + ([missing[0].ask.strip()] if missing else []))
            asks = missing[0].key if missing else asks
        if not missing and not stumbled:
            # Nothing needed is missing, so the card comes, whatever the model thinks of where
            # things stand: let hold it back to ask once more, it asked about a setting that
            # has a usual value. Its question still shows, above the card, to answer or not.
            # Only a turn in which code refused something waits: asked for "my Scool folder",
            # it said it couldn't find one, asked which folder to watch, and showed a card for
            # Downloads under that, which it had only guessed.
            self._settle_defaults()
            words = words or f"Here is {draft.slots['name']}. Create it if it looks right."
            draft.turns.append({"role": "assistant", "content": words})
            yield from say(words)
            if draft.card_slots != draft.slots:
                draft.card_slots = dict(draft.slots)
                yield from self._show_card()
            # A plain yes typed now is a yes to the card on screen, unless Noir has just asked
            # something: then the yes answers that, and the button is what creates.
            draft.waiting = CONDUCT if "?" in words else CARD
            return
        words = words or "Could you say that another way?"
        draft.turns.append({"role": "assistant", "content": words})
        slot = bp.slot(asks) or (missing[0] if missing else None)
        if "?" not in words:
            draft.waiting = CONDUCT
            yield from say(words)  # an answer to their question, with nothing asked back
            return
        draft.waiting = slot.key if slot else CONDUCT
        yield Question(draft.waiting, words, slot.choices if slot else None)

    def _missing(self) -> list[Slot]:
        """The settings the agent can't be made without that aren't known yet."""
        return [slot for slot in self.draft.blueprint.slots if needed(slot) and slot.key not in self.draft.slots]

    def _settle_defaults(self) -> None:
        """Nothing needed is missing: the rest take their usual values, and it gets its name."""
        draft = self.draft
        for slot in draft.blueprint.slots:
            if slot.key not in draft.slots and slot.default:
                draft.slots[slot.key] = slot.default
        if draft.blueprint.default_name and (draft.name_is_auto or "name" not in draft.slots):
            draft.slots["name"] = self._unique_name(_fill(draft.blueprint.default_name, draft.slots))

    def _take_form(self, values: dict) -> list[Refused]:
        """What the conductor's form says, checked and put into the draft. Returns what
        code refused, each with a line for the model and a line for the user. An empty
        value never erases one that is known, and a value refused in an earlier turn is
        passed over unless the user's last message names it again."""
        draft, refused = self.draft, []
        last = next((turn["content"] for turn in reversed(draft.turns) if turn["role"] == "user"), "").lower()
        for slot in draft.blueprint.slots:
            raw = values.get(slot.key)
            given = json.dumps(raw, sort_keys=True, ensure_ascii=False)
            if (slot.key, given) in draft.ignored and not any(word in last for word in _words_in(raw)):
                continue
            if slot.type == "folder":
                problem = self._form_folder(slot, raw)
            elif slot.key in PLACE_SLOTS:
                problem = self._form_place(slot, raw)
            elif slot.type == "choice":
                if raw in (slot.choices or []):
                    draft.slots[slot.key] = raw
                continue
            else:
                problem = self._form_text(slot, raw)
            if problem:
                refused.append(Refused(slot.key, given, *problem))
        return refused

    def _form_folder(self, slot: Slot, raw) -> tuple[str, str] | None:
        """A folder that must exist (the one to watch), from the form's place and name.
        None when it is taken or nothing was given; else why not, for the model and for
        the user. A setting that was known stays as it was."""
        draft = self.draft
        place, name = _place_and_name(raw)
        if name.lower() in (known.lower() for known in PLACE_NAMES):
            place, name = name.capitalize(), ""  # "downloads" written as a name is the place
        if not place and not name:
            return None
        # A place alone is where Windows says it is; a name is looked for, in that place if one was said.
        found = find_folders(name, place or None) if name else place_dirs(place)[:1]
        if name and place and not found:
            # The place is often the model's guess ("Scool" was looked for in Documents, which
            # nobody said): look everywhere before refusing, and refuse without naming it.
            place, found = "", find_folders(name, None)
        kept = f", so that stays as it was ({slot.label}: {self._shown(slot)})" if slot.key in draft.slots else ""
        if not found:
            # The model is told only that, and to ask. Told as well that a folder which doesn't
            # exist might be where the sorted folders should go, it made a mistyped folder
            # ("my Scool folder") into a new place for them, which nobody had asked for.
            return (f'There is no folder called "{name or place}" on this computer, and `{slot.key}` must be a folder '
                    "that exists. Tell them you can't find it and ask which folder they mean; don't put that name "
                    "in any other setting.",
                    f'I can\'t find a folder called "{name or place}"{kept}.')
        if len(found) > 1:
            which = ", ".join(short_place(path) for path in found[:4])
            return (f'There is more than one folder called "{name}": {which}. Ask which one they mean.',
                    f'I found more than one folder called "{name}": {which}. Which one do you mean?')
        if str(found[0]) == draft.slots.get(slot.key):
            return None
        problem = self._set_folder(found[0])
        return (problem, problem) if problem else None

    def _set_folder(self, folder: Path) -> str:
        """Take the folder to watch, or say why not. The same folder as where the sorted
        folders go only means they go inside it."""
        draft = self.draft
        if is_blocked(folder):
            return SYSTEM_FOLDER
        if draft.slots.get("into") and Path(draft.slots["into"]) == folder:
            draft.slots["into"] = ""
        draft.slots["folder"] = str(folder)
        return ""

    def _form_place(self, slot: Slot, raw) -> tuple[str, str] | None:
        """Where new folders go, from the form's place and name: inside the watched folder
        (kept as ""), a place this computer has, a new folder there, or a path they typed."""
        draft = self.draft
        place, name = _place_and_name(raw)
        if not place and not name:
            return None
        watched = draft.slots.get("folder")
        if A_PATH.match(name):
            value = str(Path(name).expanduser())
        elif place == INSIDE:
            value = str(Path(watched) / folder_name(name)) if name and watched else ""
        elif place in PLACE_NAMES:
            base = known_folder(place)
            value = str(base / folder_name(name)) if folder_name(name) else str(base)
        else:
            places = ", ".join(PLACE_NAMES)
            return (f'A new folder needs a place: ask where the "{name}" folder should be made ({places}, or inside '
                    "the folder it watches).",
                    f'Where should the "{name}" folder go: {places}, or inside the folder it watches?')
        if value and is_blocked(Path(value)):
            return SYSTEM_FOLDER, SYSTEM_FOLDER
        if value and watched and Path(value) == Path(watched):
            value = ""
        draft.slots[slot.key] = value
        return None

    def _form_text(self, slot: Slot, raw) -> tuple[str, str] | None:
        """A setting in words, read the way a typed answer to its question is (`_plain`)."""
        draft = self.draft
        text = raw.strip() if isinstance(raw, str) else ""
        if not text:
            return None
        if slot.key == "name":
            name = text.strip("\"'")[:40]
            told = " ".join(turn["content"] for turn in draft.turns if turn["role"] == "user").lower()
            if name == draft.slots.get("name") or name.lower() not in told or not NAMES_IT.search(told):
                # Only a name they gave it themselves: a model likes to make one up, and
                # "can you call the folder School" once named the agent School.
                return None
            if store.name_taken(name) and name.lower() != (draft.replaces or "").lower():
                return (f"They already have a helper called {name}, so this one needs another name: ask for one.",
                        f"You already have a helper called {name}, so this one needs another name.")
            draft.slots["name"], draft.name_is_auto = name, False
            return None
        value = self._plain(slot.key, text)
        if slot.key == "groups" and (codes := courses_in(value)) and codes.count(",") == value.count(","):
            value = codes  # "phys 122, cse 163" are course codes: PHYS122, CSE163, as when typed in the request
        draft.slots[slot.key] = value
        return None

    def _shown(self, slot: Slot) -> str:
        """A setting as the conductor reads it: places by name, never the whole path."""
        draft = self.draft
        if slot.key not in draft.slots:
            return f"{NOT_KNOWN} (usually: {slot.default})" if slot.default else NOT_KNOWN
        value = draft.slots[slot.key]
        if value == "":
            return slot.choices[0] if slot.choices else INSIDE
        if slot.type == "folder" or slot.key in PLACE_SLOTS:
            return short_place(Path(value))
        return str(value)

    def _known(self) -> list[tuple[str, str]]:
        return [(slot.label, self._shown(slot)) for slot in self.draft.blueprint.slots]

    def _facts(self) -> list[str]:
        """What code can see that the conductor may use instead of asking: the places this
        computer has, how many files of which kinds are in the folder (never their names:
        the conductor may be a model off this computer), and the agents already made."""
        draft = self.draft
        facts = [f"The places it has by name: {', '.join(PLACE_NAMES)}."]
        folders = [known_folder("Downloads")] if draft.blueprint.extra.get("watches") else []
        if draft.slots.get("folder"):
            folders.append(Path(draft.slots["folder"]))
        facts += [files_in(folder) for folder in dict.fromkeys(folders) if folder.is_dir()]
        have = [f"{agent.name} ({self.blueprints[agent.blueprint].name if agent.blueprint in self.blueprints else agent.blueprint})"
                for agent in store.list_agents()]
        facts.append("Helpers they already have: " + (", ".join(have) if have else "none") + ".")
        return facts

    def _same_agent(self) -> store.Agent | None:
        """For a switch-on agent: one of the same kind and language already made."""
        draft = self.draft
        if draft.blueprint.id == CUSTOM and not draft.editing:
            wanted = draft.slots.get("instruction", "").strip().lower()
            return next((a for a in store.list_agents() if a.blueprint == CUSTOM
                         and a.slots.get("instruction", "").strip().lower() == wanted), None)
        if not draft.blueprint.switchable or draft.editing:
            return None
        return next((a for a in store.list_agents() if a.blueprint == draft.blueprint.id
                     and a.slots.get("language") == draft.slots.get("language")), None)

    def _changed(self) -> bool:
        old = store.find_agent(self.draft.replaces) if self.draft.replaces else None
        return bool(old) and any(old.slots.get(k) != v for k, v in self.draft.slots.items())

    def _changes(self, text: str) -> dict:
        """The settings a message asks to change, and their new values.

        Code first (languages, choices by their telling words, "rename it to
        ..."); if that finds nothing, the model picks from each setting's
        allowed values, with "no change" always allowed.
        """
        draft = self.draft
        if draft.blueprint.id == CUSTOM:
            return self._custom_changes(text)
        changes = {}
        for slot in draft.blueprint.slots:
            if not slot.changeable:
                continue
            if slot.type == "language":
                # "into Spanish" first; in a change request a single language
                # named ("make it Spanish") can only be the new target.
                value = language_in(text, target_only=True) or language_in(text)
            elif slot.type == "choice":
                value = self._match_choice(slot.key, text)
            elif slot.key == "name" and (match := RENAME.search(text)):
                value = match.group(1).strip()[:40]
            else:
                value = None
            if value and value != draft.slots.get(slot.key):
                changes[slot.key] = value
        if not changes and draft.blueprint.slot("instruction"):
            new = rewrite_instruction(self.ollama, self.model, draft.slots.get("instruction", ""), text,
                                      self.think)
            if new:
                return {"instruction": new}
        return changes or self._model_changes(text)

    def _custom_changes(self, text: str) -> dict:
        """Changes to an agent made from parts. Settings come from the user's
        words in code; the model only rewrites what it does with the text."""
        draft = self.draft
        current = draft.slots.get("instruction", "")
        changes = {k: v for k, v in settings_from_words(text).items() if v != draft.slots.get(k)}
        if match := RENAME.search(text):
            changes["name"] = match.group(1).strip()[:40]
        language = language_in(text, target_only=True) or language_in(text)
        if target_language(current) or needs_language(current) or MECHANICS.search(current):
            # A translator: "in Korean" changes the language, decided in code.
            if language and language != target_language(current):
                changes["instruction"] = with_language("Translate the text.", language)
        if "instruction" not in changes and (not changes or MECHANICS.search(current)):
            new = rewrite_instruction(self.ollama, self.model, current, text, self.think)
            if new:
                changes["instruction"] = new
        return changes or self._model_changes(text)

    def _model_changes(self, text: str) -> dict:
        draft = self.draft
        # Only settings the message actually talks about: asked for anything
        # here, the model once flipped "when it works" to the chat.
        words = _stems(text)
        options = {s.key: s for s in draft.blueprint.slots if s.changeable and s.type in ("choice", "language")
                   and (s.type == "language" or words & _stems(s.label + " " + " ".join(s.choices or [])))}
        if not options:
            return {}
        schema = {
            "type": "object",
            "properties": {key: {"enum": [*(LANGUAGES if s.type == "language" else s.choices), "no change"]}
                           for key, s in options.items()},
            "required": list(options),
        }
        current = "; ".join(f"{s.label}: {draft.slots.get(k)}" for k, s in options.items())
        system = (f'The user may want to change the settings of their agent "{draft.slots.get("name")}". '
                  f"Current settings: {current}. For each setting, give the new value their message asks "
                  'for, or "no change" if the message does not ask to change it.')
        try:
            reply = self.ollama.chat_json(self.model, [{"role": "system", "content": system},
                                                       {"role": "user", "content": text}],
                                          schema, think=self.think)
        except OllamaError:
            return {}
        return {k: v for k, v in reply.items()
                if k in options and v != "no change" and v != draft.slots.get(k)}

    def _show_card(self) -> Iterator[Event]:
        draft = self.draft
        draft.waiting = CARD
        if draft.blueprint.id == CUSTOM:
            reads, can_do, cannot_do = custom_card(draft.slots, draft.blueprint.cannot_do)
        elif draft.blueprint.id == ORGANIZER:
            reads, can_do, cannot_do = organizer_card(draft.slots, draft.blueprint.cannot_do)
        elif draft.blueprint.id == SUMMARIZER:
            reads, can_do, cannot_do = summarizer_card(draft.slots, draft.blueprint.cannot_do)
        else:
            reads = ([f"{draft.slots['folder']} ({draft.file_summary})"] if "folder" in draft.slots
                     else [draft.blueprint.reads])
            can_do = [_fill(line, draft.slots) for line in draft.blueprint.can_do]
            cannot_do = list(draft.blueprint.cannot_do)
        yield AgentCard(
            id=CARD,
            name=draft.slots["name"],
            kind=draft.blueprint.name,
            reads=reads,
            can_do=can_do,
            cannot_do=cannot_do,
            runs_on=(f"{_model_name()}, reading each file on this computer; pictures through a vision model when one is installed"
                     if draft.blueprint.extra.get("watches") else f"{_model_name()} (the built-in model, no extra memory)"),
            actions=[SAVE_CHANGES if draft.editing else CREATE_IT, "Change something", "Cancel"],
        )

    def _prefill(self, request: str, skip: tuple[str, ...] = ()) -> None:
        """Fill in what the first message already says, so it is not asked again."""
        draft = self.draft
        for slot in draft.blueprint.slots:
            if slot.key in skip:
                continue
            if slot.key == "into" and draft.blueprint.id == ORGANIZER:
                if (into := destination_from(request)) is not None:
                    draft.slots["into"] = into
            elif slot.key == "groups" and draft.blueprint.id == ORGANIZER and courses_in(request):
                draft.slots["groups"] = courses_in(request)
            elif slot.key == "by" and draft.blueprint.id == ORGANIZER:
                if BY_CONTENT_WORDS.search(request):
                    draft.slots["by"] = CONTENT
                elif BY_NAME_WORDS.search(request):
                    draft.slots["by"] = BY_NAME
            elif slot.type == "language" and (language := language_in(request, target_only=True)):
                draft.slots[slot.key] = language
            elif slot.type == "choice" and (choice := self._match_choice(slot.key, request, strict=True)):
                draft.slots[slot.key] = choice

    def _take_language(self, text: str) -> Iterator[Event]:
        language = language_in(text)
        if language:
            yield from self._set_slot(self.draft.waiting or "language", language)
        elif len(text.split()) > 6 or text.strip().endswith("?"):
            # Not an answer to "Which language?": the user moved on.
            self.draft = None
            self.handoff = text
            yield from say("I'll leave the agent setup for now.")
        else:
            slot = self.draft.blueprint.slot(self.draft.waiting or "language")
            yield from say(f"I don't know that language yet. I can translate into {', '.join(LANGUAGES)}.")
            yield Question(slot.key, slot.ask, slot.choices)

    def _take_instruction(self, text: str) -> Iterator[Event]:
        """The user described, in their own words, what the agent should do instead.

        A description often mixes the job with when and where ("When I
        highlight a sentence it should display it in Korean above"): the
        settings are taken from it in code, and only the job becomes the
        instruction."""
        changes = self._custom_changes(text) if self.draft.blueprint.id == CUSTOM else {}
        new = changes.pop("instruction", None) or (
            None if self.draft.blueprint.id == CUSTOM else
            rewrite_instruction(self.ollama, self.model, self.draft.slots.get("instruction", ""), text, self.think))
        self.draft.slots.update(changes)
        if new:
            self.draft.slots["instruction"] = new
            yield Thinking(f'Rewrote what it does: "{new}"')
        elif not changes:
            yield from say("I couldn't turn that into a change to what it does, so it's the same as before.")
        yield from self._show_card()

    def _take_target_language(self, text: str) -> Iterator[Event]:
        language = language_in(text)
        if not language:
            yield from say(f"I don't know that language yet. I can translate into {', '.join(LANGUAGES)}.")
            yield Question(TARGET_LANGUAGE, "Which language should it translate into?", LANGUAGE_CHOICES)
            return
        self.draft.slots["instruction"] = with_language(self.draft.slots["instruction"], language)
        yield Thinking(f'What it does: "{self.draft.slots["instruction"]}"')
        yield from self._next()

    def _set_slot(self, key: str, value: str) -> Iterator[Event]:
        self.draft.slots[key] = value
        yield from self._next()

    @staticmethod
    def _plain(key: str, text: str) -> str:
        """A typed or clicked answer to a plain text slot, read the way the slot means it."""
        if key == "groups":
            return groups_from(text)
        if key == "into":
            where = destination_from(text)
            return "" if where is None or text.strip().lower() == "inside that folder" else where
        if key == "notes":
            # The notes file: the plain choice means the default beside the watched files; a
            # path or a file name is kept as given (a name alone lands in the watched folder).
            words = text.strip().strip("\"'")
            if not words or re.search(r"\b(that|the watched|same) folder\b|^a summaries", words, re.IGNORECASE):
                return ""
            return words
        return text.strip()

    def _slot_type(self, key: str | None) -> str | None:
        slot = self.draft.blueprint.slot(key) if (self.draft and key) else None
        return slot.type if slot else None

    def _match_choice(self, key: str, text: str, strict: bool = False) -> str | None:
        """The choice the user typed: the whole choice, or (not strict) a telling word from one."""
        slot = self.draft.blueprint.slot(key)
        lowered = text.lower()
        for choice in slot.choices or []:
            if choice.lower() == lowered.strip() or (not strict and choice.lower() in lowered):
                return choice
        words = {c: {w for w in re.findall(r"[a-z]+", c.lower()) if len(w) >= 5} for c in slot.choices or []}
        hits = [c for c, ws in words.items() if any(w in lowered for w in ws)]
        return hits[0] if len(hits) == 1 else None

    # ------------------------------------------------------------ finish

    def _create(self) -> Iterator[Event]:
        draft = self.draft
        old = store.find_agent(draft.replaces) if draft.replaces else None
        if old:
            store.delete(old)
        agent = store.Agent(name=draft.slots["name"], blueprint=draft.blueprint.id, slots=dict(draft.slots))
        if draft.blueprint.id == CUSTOM:
            yield from self._create_custom(agent, draft)
            return
        if draft.blueprint.extra.get("watches"):
            store.save(agent)
            self.created = agent
            self.conducted = draft.conductor is not None
            self.draft = None
            if self.conducted:
                # Said as written: reworded by the small model, "is ready" once became
                # "waiting for you to start sorting things", which it doesn't do.
                draft.conductor.done()
                yield from say(f"{agent.name} is ready.")
            else:
                yield from self._say(f"{agent.name} is ready.", [agent.name])
            yield AgentList([a.name for a in store.list_agents()])
            return
        try:
            index = yield from runner.refresh_index(agent)  # reads the files and saves the agent
        except OSError as exc:
            yield from say(f"I couldn't read that folder ({exc.strerror}). Nothing was created.")
            self.draft = None
            return
        self.draft = None

        if index.passages:
            yield Progress("Giving it a test drive...")
            try:
                question = self._test_question(index)
                result = None
                for event in runner.run(self.ollama, self.model, agent, question, self.think):
                    if isinstance(event, Result):
                        result = event
                    else:
                        yield event
                if result:
                    yield Result(result.agent, f"Test question: {question}\n{result.text}", result.sources)
            except OllamaError:
                pass  # The agent is saved; a failed test drive should not undo that.
        else:
            yield from say("Those files had no readable text (scanned PDFs have none), "
                           "so it may not find much.")
        yield from say(f"{agent.name} is ready. To use it, start your message with its name, "
                       f'like "{agent.name}: what does it say about...".')
        yield AgentList([a.name for a in store.list_agents()])

    def _create_custom(self, agent: store.Agent, draft: Draft) -> Iterator[Event]:
        """Agents made from parts have nothing to read: save, then try it once."""
        store.save(agent)
        self.draft = None
        if draft.editing:
            _reads, can_do, _cannot = custom_card(agent.slots, [])
            yield from say(f"Saved. {agent.name} now: " + "; ".join(
                line[:1].lower() + line[1:] for line in can_do) + ".")
            yield AgentList([a.name for a in store.list_agents()])
            return
        if draft.example:
            yield Progress("Giving it a test drive...")
            try:
                result = run_instruction(self.ollama, self.model, agent.slots["instruction"], draft.example,
                                         self.think)
                yield Result(agent.name, f'Test: "{draft.example}"\n{result}')
            except OllamaError:
                pass  # The agent is saved; a failed test drive should not undo that.
        if agent.slots.get("when") == WHILE_ON:
            yield from say(f"{agent.name} is ready. Switch it on in your helpers list, then highlight "
                           f'text in any program. You can also say "turn on {agent.name}".')
        else:
            yield from say(f'{agent.name} is ready. To use it, start your message with its name, like '
                           f'"{agent.name}: {draft.example or "..."}".')
        yield AgentList([a.name for a in store.list_agents()])

    def _say(self, plain: str, facts: list[str] = ()) -> Iterator[Event]:
        """Noir's own words for a line code decided to say (talk.phrase); the plain line
        itself if the rewording loses a fact."""
        yield from say(phrase(self.ollama, self.model, plain, list(facts)))

    def _question(self, id: str, ask: str, choices: list[str] | None = None, facts: list[str] = ()) -> Question:
        """A question in Noir's own words: the blueprint's line says what to ask, not how;
        it is kept as written when the rewording drops a fact or stops asking."""
        return Question(id, phrase(self.ollama, self.model, ask, list(facts), question=True), choices)

    def _cancel(self) -> Iterator[Event]:
        editing, name = self.draft.editing, self.draft.replaces
        if self.draft.conductor is not None:
            self.draft.conductor.done()
        self.draft = None
        yield from say(f"Okay, I left {name} as it was." if editing else "Okay, I won't create it.")

    # ------------------------------------------------------------ model help

    def _folder_words(self, text: str) -> tuple[str, str | None]:
        """(folder name or path, known place like "Desktop" or None) from what the user typed."""
        path = re.search(r'([A-Za-z]:[\\/][^"\n]*|~[\\/][^"\n]*|/[^"\n]+)', text)
        if path:
            return path.group(1).strip().rstrip(".,!?"), None
        schema = {
            "type": "object",
            "properties": {
                "folder": {"type": "string"},
                "place": {"enum": [*PLACES, "home", "not said"]},
            },
            "required": ["folder", "place"],
        }
        system = (
            "The user is naming a folder on their computer. Give the folder's own name exactly as "
            "they wrote it, without words like 'my', 'the' or 'folder'. If they only named a "
            "standard place such as Documents or Downloads, give that as the folder too. If they "
            "named no folder at all, give an empty string. In place, say where it is if they said "
            "(for example 'on my desktop' is Desktop), otherwise 'not said'."
        )
        try:
            reply = self.ollama.chat_json(
                self.model, [{"role": "system", "content": system}, {"role": "user", "content": text}],
                schema, think=self.think,
            )
        except OllamaError:
            return text.strip(), None
        place = reply.get("place")
        folder = reply.get("folder", "").strip().strip("\"'")
        if folder.lower() in ("not said", "none", "unknown", "n/a"):
            folder = ""
        return folder, place if place in [*PLACES, "home"] else None

    def _test_question(self, index) -> str:
        passage = max(index.passages[:40], key=lambda p: len(p.text))
        schema = {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}
        reply = self.ollama.chat_json(
            self.model,
            [{"role": "system", "content": "Write one short, natural question that this passage "
                                           "answers, as a person would ask it. Same language as the passage."},
             {"role": "user", "content": passage.text}],
            schema, think=self.think,
        )
        return reply.get("question", "").strip() or "What are these files about?"

    @staticmethod
    def _unique_name(base: str) -> str:
        base = base[:1].upper() + base[1:]
        name, n = base, 2
        while store.name_taken(name):
            name, n = f"{base} {n}", n + 1
        return name


# ---------------------------------------------------------------- folders


def _stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[a-z]{5,}", text.lower())}


def custom_card(slots: dict, cannot_do: list[str]) -> tuple[list[str], list[str], list[str]]:
    """(reads, can do, cannot do) for an agent made from parts, from its slots."""
    on = slots.get("when", WHILE_ON) == WHILE_ON
    name = slots.get("name", "it")
    if on:
        reads = ["Text you highlight with the mouse in any program, while it's switched on"]
        can_do = [f"Does: {slots.get('instruction', '')}", f"Shows the result: {slots.get('show')}"]
        if slots.get("show") != CLIPBOARD:
            can_do.append(f"The result stays: {slots.get('keep')}")
        cannot_do = list(cannot_do) + ["Work while it's switched off or the Noir window is closed"]
    else:
        reads = [f'What you send it in the chat, starting with its name ("{name}: ...")']
        can_do = [f"Does: {slots.get('instruction', '')}", "Answers in the chat"]
        cannot_do = list(cannot_do)
    return reads, can_do, cannot_do


def _place_and_name(raw) -> tuple[str, str]:
    """The place and the name in a form's folder field, whatever the model put there."""
    if not isinstance(raw, dict):
        return "", ""
    place, name = raw.get("place"), raw.get("name")
    return (place if isinstance(place, str) else ""), (name.strip().strip("\"'") if isinstance(name, str) else "")


def _words_in(raw) -> list[str]:
    """The words of a form's value that a message could name: a folder's name, or the text."""
    text = raw.get("name") if isinstance(raw, dict) else raw
    return re.findall(r"[^\W_]{3,}", text.lower()) if isinstance(text, str) else []


def short_place(path: Path) -> str:
    """A folder the way people say it: "Downloads", "Desktop\\College". The conductor reads
    and says places like this, so a whole path with the user's name in it never goes to a
    model off this computer; a folder outside those places is shown as it is."""
    for place in PLACE_NAMES:
        base = known_folder(place)
        if path == base:
            return place
        if base in path.parents:
            return str(Path(place) / path.relative_to(base))
    return str(path)


def files_in(folder: Path) -> str:
    """One line on what a folder holds right now: how many files, and of which endings."""
    kinds: Counter = Counter()
    try:
        with os.scandir(folder) as entries:
            for number, entry in enumerate(entries):
                if number >= MAX_COUNTED:
                    break
                if entry.is_file() and not entry.name.startswith(".") and entry.name.lower() != "desktop.ini":
                    kinds[Path(entry.name).suffix.lower() or "no ending"] += 1
    except OSError:
        return f"{short_place(folder)} couldn't be looked into."
    total = sum(kinds.values())
    if not total:
        return f"{short_place(folder)} has no files in it right now."
    most = ", ".join(f"{count} {kind}" for kind, count in kinds.most_common(6))
    return f"{short_place(folder)} has {total} file{'' if total == 1 else 's'} in it right now ({most})."


def _fill(template: str, slots: dict) -> str:
    """Put slot values into a blueprint text like "{language} translator"."""
    return re.sub(r"\{(\w+)\}", lambda m: str(slots.get(m.group(1), m.group(0))), template)


def say(text: str) -> Iterator[Event]:
    yield NoirText(text)
    yield NoirDone()


def place_dirs(place: str) -> list[Path]:
    """Where a named place is: what Windows says first (the Desktop may be OneDrive's),
    then the plain and OneDrive folders of that name."""
    home = Path.home()
    if place == "home":
        return [home]
    candidates = [known_folder(place), home / place] + [d / place for d in home.glob("OneDrive*") if d.is_dir()]
    candidates = list(dict.fromkeys(candidates))
    return [d for d in candidates if d.is_dir()]


def find_folders(name: str, place: str | None, limit: int = 6) -> list[Path]:
    """Existing folders matching what the user said, best matches first."""
    if name and re.match(r"^([A-Za-z]:[\\/]|~|/)", name):
        # A path, maybe with more words after it ("C:/Users/me/Downloads by what's inside
        # them"): the longest start that is a folder wins, so a path with spaces still works.
        words = name.split(" ")
        for end in range(len(words), 0, -1):
            path = Path(os.path.expanduser(" ".join(words[:end]).rstrip(".,;:!?")))
            if path.is_dir():
                return [path]
        return []

    for known in [*PLACES, "home"]:
        if name.lower() == known.lower() or (not name and place == known):
            return place_dirs(known)[:limit]

    bases = place_dirs(place) if place else [Path.home()]
    exact, partial, seen = [], [], 0
    wanted = name.casefold()
    for base in bases:
        for root, dirs, _ in os.walk(base):
            depth = len(Path(root).relative_to(base).parts)
            dirs[:] = [] if depth >= 3 else [
                d for d in dirs if not d.startswith((".", "$")) and d.lower() not in SKIP_WHILE_SEARCHING
            ]
            for d in dirs:
                seen += 1
                folded = d.casefold()
                if folded == wanted:
                    exact.append(Path(root) / d)
                elif wanted and wanted in folded:
                    partial.append(Path(root) / d)
            if seen > 20000:
                break
    found = exact or partial
    return sorted(found, key=lambda p: len(p.parts))[:limit]


def agent_for_folder(folder: Path) -> store.Agent | None:
    """An existing agent that already reads this folder."""
    wanted = os.path.normcase(str(folder.resolve()))
    for agent in store.list_agents():
        path = agent.slots.get("folder")
        if path and os.path.normcase(str(Path(path).resolve())) == wanted:
            return agent
    return None


def is_blocked(folder: Path) -> bool:
    resolved = folder.resolve()
    if resolved == Path(resolved.anchor):
        return True  # a whole drive
    for blocked in BLOCKED:
        if str(blocked) not in ("", ".") and resolved.is_relative_to(blocked.resolve()):
            return True
    return "appdata" in (p.lower() for p in resolved.parts)


def describe_files(files: list[Path]) -> str:
    kinds = Counter(
        {".pdf": "PDF", ".docx": "Word"}.get(f.suffix.lower(), "text") for f in files
    )
    parts = ", ".join(f"{n} {kind}" for kind, n in kinds.most_common())
    return f"{len(files)} files: {parts}" if len(files) != 1 else f"1 file: {parts}"


def _model_name() -> str:
    tag = load_state().get("base_model", "")
    model = find_model(tag) if tag else None
    return model.name if model else (tag or "the built-in model")
