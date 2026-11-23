"""Make an agent the plain way: offer it, fill in its settings one question at a
time, show the agent card, and on "Create it" save it and give it a test drive.

An agent is worked out in a conversation, with a model in it (designer.py). This
is what is left for a computer where no model can hold that conversation: an
agent that answers from the documents in a folder, and one that does one job on
a piece of text, can still be made here, and changed. Code drives every step.
The model only pulls a folder name out of what the user typed, writes or
rewrites the one instruction of an agent that works on text, and writes the
test-drive question. What that instruction says is never read by code to find
out what kind of agent it is: the card shows it before anything is made, and
that is the check.

What both ways share lives here too: finding a folder by what people call it,
the folders no agent may read, the card's buttons and the words that say yes to
it, and the making of an agent that answers from documents (create_documents_agent).
"""

from __future__ import annotations

import os
import sys
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from ..catalog import find_model
from ..noir import load_state
from ..events import AgentCard, AgentList, NoirDone, NoirText, Event, Progress, Question, Result, Thinking
from ..ollama import Ollama, OllamaError
from . import parts, runner, store
from .blueprint import Blueprint
from .files import scan
from ..places import known_folder
from .parts import CUSTOM, IN_CHAT, WHILE_ON, short_place
from .recipe import MECHANICS, rewrite_instruction, run_instruction, settings_from_words, write_recipe

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
# "rename it to Lease helper", "call it My reader"
RENAME = re.compile(r"\b(?:rename\b.*?\b(?:to|as)|call it)\s+[\"']?(.+?)[\"']?\s*[.!]?$", re.IGNORECASE)
# A whole message that is a yes to the card on screen. Only the whole message counts
# where an agent is talked through: "ok but put them in Documents" is a change, not a yes.
CARD_YES = (*YES_WORDS, "create it", "yes please", "sounds good", "ok sounds good", "okay sounds good", "looks good",
            "looks right", "perfect", "that's right", "thats right")
MAX_COUNTED = 5000  # files looked at when saying what a folder holds


@dataclass
class Draft:
    blueprint: Blueprint
    slots: dict = field(default_factory=dict)
    waiting: str | None = None  # slot key we asked for, or CARD / PICK_FOLDER / CHANGE
    file_count: int = 0
    duplicate_of: str | None = None  # existing agent that reads the same folder
    replaces: str | None = None  # agent to delete when this one is created
    request: str = ""  # the message that started it
    editing: bool = False  # changing an existing agent rather than making one
    example: str = ""  # a piece of text to test an agent that works on text on
    duplicate_asked: bool = False


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
        # What the last Create it or Save changes made, for the engine to carry on from: the
        # card (an agent that answers from documents is finished here, and is never this),
        # whether it was a change to one they had, and the name it had before a change
        # renamed it. The same three the designing conversation keeps (designer.py).
        self.created: store.Agent | None = None
        self.edited = False
        self.replaced: str | None = None

    def take_created(self) -> store.Agent | None:
        """The card made by the last Create it or Save changes, once; None otherwise."""
        created, self.created = self.created, None
        return created

    @property
    def active(self) -> bool:
        return self.draft is not None

    # ------------------------------------------------------------ entry

    def start(self, blueprint_id: str, request: str) -> Iterator[Event]:
        bp = self.blueprints[blueprint_id]
        self.draft = Draft(bp, request=request)
        yield from say(f"I can make you an agent for that: {bp.name}. {bp.pitch.strip()}")
        if bp.slot("folder"):
            yield from self._take_folder(request, from_request=True)
        else:
            yield from self._next()

    def start_for_folder(self, blueprint_id: str, folder: Path, request: str) -> Iterator[Event]:
        """The user already showed which folder, with the + button."""
        bp = self.blueprints[blueprint_id]
        self.draft = Draft(bp, request=request)
        yield from say(f"I can make you an agent for that: {bp.name}. {bp.pitch.strip()}")
        yield from self._use_folder(folder)

    def compose(self, request: str, blocks: list[str]) -> Iterator[Event]:
        """Make an agent that works on text from an idea's parts: the shared template
        (custom.yaml) filled in from the parts, and an instruction Noir writes for what
        it does with the text."""
        self.draft = Draft(self.blueprints[CUSTOM], request=request)
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
        # The instruction is the model's writing, and code does not read it to put it
        # right for one kind of agent or another. Whatever it says, it is on the card
        # before anything is made, and "Change something" changes it: a model told never
        # to guess a language still named one nobody had asked for, and the card is where
        # that shows.
        instruction = recipe["instruction"]
        slots["instruction"] = instruction
        slots["name"] = self._unique_name(recipe["name"])
        self.draft.example = recipe["example"]
        yield Thinking(f'Wrote what it does: "{instruction}"')
        yield from self._next()

    def edit(self, agent: store.Agent, request: str) -> Iterator[Event]:
        """Change an existing agent: apply what the message asks, then show its
        card with Save changes. Nothing is saved until the user says so."""
        bp = self.blueprints.get(agent.blueprint)
        if bp is None or parts.watches(agent):
            # One that works on a folder's files is only changed by talking it through: its
            # settings are not the ones asked about here.
            yield from say(f"I don't know how to change {agent.name}.")
            return
        self.draft = Draft(bp, slots=dict(agent.slots), replaces=agent.name, request=request, editing=True,
                           duplicate_asked=True)
        # Compared with what is stored, so asking for a setting the agent was
        # made without (it only had the default) still counts as a change.
        changes = self._changes(request)
        for slot in bp.slots:  # settings added since the agent was made
            if slot.key not in self.draft.slots and slot.default:
                self.draft.slots[slot.key] = slot.default
        if "folder" in self.draft.slots:
            self.draft.file_count = len(scan(Path(self.draft.slots["folder"])).files)
        already = self._asked_for(request)
        if changes:
            # A setting the plain questions don't ask about is said by the catalog's name
            # for it, and one that was taken off is said too.
            labels = {setting.key: setting.label for setting in parts.all_settings()}
            found = "; ".join(f"{(bp.slot(k).label if bp.slot(k) else labels[k]).lower()} → {v or 'nothing'}"
                              for k, v in changes.items() if bp.slot(k) or k in labels)
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
        elif draft.waiting in ("folder", PICK_FOLDER):
            yield from self._take_folder(text)
        elif draft.waiting == "name":
            yield from self._take_name(text)
        elif self._slot_type(draft.waiting) == "instruction":
            yield from self._take_instruction(text)
        elif self._slot_type(draft.waiting) == "text":
            yield from self._set_slot(draft.waiting, text.strip())
        elif self._slot_type(draft.waiting) == "choice" and self._match_choice(draft.waiting, text):
            yield from self._set_slot(draft.waiting, self._match_choice(draft.waiting, text))
        elif draft.waiting == CARD and _says_yes(lowered):
            yield from self._create()
        elif draft.waiting == CARD and lowered in ("no", "nope", "아니"):
            yield from self._cancel()
        elif draft.waiting in (CARD, CHANGE) and (changes := self._changes(text)):
            # "and make it shorter" typed at the card: change it there.
            draft.slots.update(changes)
            yield from self._show_card()
        else:
            # Waiting for a button but the user typed something else: they
            # moved on, so drop the setup and let the engine handle it.
            self.draft = None
            self.handoff = text
            yield from say("I'll leave the agent setup for now.")

    def choose(self, id: str, choice: str) -> Iterator[Event]:
        draft = self.draft
        if id == CARD and draft.waiting != CARD:
            yield from self._next()  # the card isn't up yet: the open question is asked again
        elif id == CARD and choice in (CREATE_IT, SAVE_CHANGES):
            yield from self._create()
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
            elif slot.type == "choice":
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
            existing = store.find_agent(name)
            self.draft = None
            yield from say(f"Okay, keep using {name}. {_how_to_use(existing)}" if existing else f"Okay, keep using {name}.")
        elif id == DUPLICATE and choice.startswith("Change "):
            existing = store.find_agent(draft.duplicate_of)
            if existing:
                yield from self.edit(existing, draft.request)
        elif id == DUPLICATE and choice == REPLACE:
            draft.replaces = draft.duplicate_of
            draft.slots["name"] = draft.duplicate_of
            yield from say(f"Okay. When you create this one, it replaces {draft.duplicate_of}.")
            yield from self._next()
        elif id == DUPLICATE:
            yield from self._next()
        elif self._slot_type(id) == "choice":
            yield from self._set_slot(id, choice)
        elif self._slot_type(id) == "text":
            yield from self._set_slot(id, choice.strip())
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
        yield Progress(f"Looking in {folder}...")
        files = scan(folder).files
        if not files:
            draft.waiting = "folder"
            yield from say(f"{folder} has no files I can read. I can read PDF, Word and text files.")
            yield Question("folder", "Which other folder should it read?")
            return
        draft.slots["folder"] = str(folder)
        draft.file_count = len(files)
        yield Thinking(f"Found {describe_files(files)} there.")
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
        for slot in draft.blueprint.slots:
            if slot.key not in draft.slots and slot.ask:
                draft.waiting = slot.key
                yield Question(slot.key, slot.ask, slot.choices)
                return
            if slot.key not in draft.slots and slot.default:
                draft.slots[slot.key] = slot.default
        yield from self._show_card()

    def _same_agent(self) -> store.Agent | None:
        """An agent that works on text they already have with the same instruction, word for word."""
        draft = self.draft
        if draft.blueprint.id != CUSTOM or draft.editing:
            return None
        wanted = draft.slots.get("instruction", "").strip().lower()
        return next((a for a in store.list_agents() if a.blueprint == CUSTOM and not parts.watches(a)
                     and str(a.slots.get("instruction") or "").strip().lower() == wanted), None)

    def _changed(self) -> bool:
        old = store.find_agent(self.draft.replaces) if self.draft.replaces else None
        return bool(old) and any(old.slots.get(k) != v for k, v in self.draft.slots.items())

    def _changes(self, text: str) -> dict:
        """The settings a message asks to change, and their new values.

        Code first (choices by their telling words, "rename it to ..."); if
        that finds nothing, the model picks from each setting's allowed
        values, with "no change" always allowed.
        """
        draft = self.draft
        if draft.blueprint.id == CUSTOM:
            return self._custom_changes(text)
        changes = {}
        for slot in draft.blueprint.slots:
            if not slot.changeable:
                continue
            if slot.type == "choice":
                value = self._match_choice(slot.key, text)
            elif slot.key == "name" and (match := RENAME.search(text)):
                value = match.group(1).strip()[:40]
            else:
                value = None
            if value and value != draft.slots.get(slot.key):
                changes[slot.key] = value
        return changes or self._model_changes(text)

    def _custom_changes(self, text: str) -> dict:
        """Changes to an agent that works on text. Settings come from the user's
        words in code; the model only rewrites what it does with the text."""
        draft = self.draft
        current = draft.slots.get("instruction", "")
        changes = {k: v for k, v in settings_from_words(text).items() if v != draft.slots.get(k)}
        if match := RENAME.search(text):
            changes["name"] = match.group(1).strip()[:40]
        if not changes or MECHANICS.search(current):
            new = rewrite_instruction(self.ollama, self.model, current, text, self.think)
            if new:
                changes["instruction"] = new
        if "instruction" in changes and draft.slots.get("skip_language"):
            # The card leaves out text that is already in one language, which went with what
            # it did until now. Nothing here can tell whether it still goes with the new
            # instruction, so the setting goes back to none: kept, a card changed to give
            # another language would pass over text in the old one without a word. With none,
            # the worst is a result for text that needed none.
            changes["skip_language"] = ""
        return changes or self._model_changes(text)

    def _model_changes(self, text: str) -> dict:
        draft = self.draft
        # Only settings the message actually talks about: asked for anything
        # here, the model once flipped "when it works" to the chat.
        words = _stems(text)
        options = {s.key: s for s in draft.blueprint.slots if s.changeable and s.type == "choice"
                   and words & _stems(s.label + " " + " ".join(s.choices or []))}
        if not options:
            return {}
        schema = {
            "type": "object",
            "properties": {key: {"enum": [*s.choices, "no change"]} for key, s in options.items()},
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
        """The card, every line written by the catalog from the settings (parts.card), so
        it reads the same whichever way an agent is made."""
        draft = self.draft
        draft.waiting = CARD
        kind, reads, can_do, cannot_do, runs_on = parts.card(_card_slots(draft), _model_name(),
                                                              draft.file_count if "folder" in draft.slots else None)
        yield AgentCard(id=CARD, name=draft.slots["name"], kind=kind, reads=reads, can_do=can_do, cannot_do=cannot_do,
                        runs_on=runs_on, actions=[SAVE_CHANGES if draft.editing else CREATE_IT, "Change something", "Cancel"])

    def _take_instruction(self, text: str) -> Iterator[Event]:
        """The user described, in their own words, what the agent should do instead.

        A description often mixes the job with when and where ("When I
        highlight a sentence it should display it in Korean above"): the
        settings are taken from it in code, and only the job becomes the
        instruction."""
        changes = self._custom_changes(text)
        new = changes.pop("instruction", None)
        self.draft.slots.update(changes)
        if new:
            self.draft.slots["instruction"] = new
            yield Thinking(f'Rewrote what it does: "{new}"')
        elif not changes:
            yield from say("I couldn't turn that into a change to what it does, so it's the same as before.")
        yield from self._show_card()

    def _set_slot(self, key: str, value: str) -> Iterator[Event]:
        self.draft.slots[key] = value
        yield from self._next()

    def _slot_type(self, key: str | None) -> str | None:
        slot = self.draft.blueprint.slot(key) if (self.draft and key) else None
        return slot.type if slot else None

    def _match_choice(self, key: str, text: str) -> str | None:
        """The choice the user typed: the whole choice, or a telling word from one."""
        slot = self.draft.blueprint.slot(key)
        lowered = text.lower()
        for choice in slot.choices or []:
            if choice.lower() in lowered:
                return choice
        words = {c: {w for w in re.findall(r"[a-z]+", c.lower()) if len(w) >= 5} for c in slot.choices or []}
        hits = [c for c, ws in words.items() if any(w in lowered for w in ws)]
        return hits[0] if len(hits) == 1 else None

    # ------------------------------------------------------------ finish

    def _create(self) -> Iterator[Event]:
        draft = self.draft
        old = store.find_agent(draft.replaces) if draft.replaces else None
        name = draft.slots["name"]
        self.draft = None
        self.edited, self.replaced = draft.editing, None
        if draft.blueprint.id == CUSTOM:
            yield from self._create_custom(draft, old)
            return
        agent = store.Agent(name=name, blueprint=draft.blueprint.id, slots=dict(draft.slots))
        maker = create_documents_agent(self.ollama, self.model, agent, self.think)
        made = False
        while True:
            try:
                event = next(maker)
            except StopIteration as finished:
                made = bool(finished.value)
                break
            if not isinstance(event, AgentList):  # sent below, once the agent it replaces is gone
                yield event
        # The agent it replaces goes only once the new one is made. Deleted first, a folder
        # that couldn't be read left them with neither. (Under the same name the new one
        # is saved over it, so there is nothing left to delete.)
        if made and old and store.slugify(old.name) != store.slugify(name):
            store.delete(old)
            self.replaced = old.name
        elif old and not made:
            yield from say(f"{old.name} is as it was.")
        if made:
            yield AgentList([a.name for a in store.list_agents()])

    def _create_custom(self, draft: Draft, old: store.Agent | None) -> Iterator[Event]:
        """An agent that works on text has nothing to read: save it, then try it once. How
        it is used from here (switching it on, how to ask it) is the engine's to say, the
        same for every card however it was made."""
        slots = dict(draft.slots)
        # Every card says what it does with its result, and for one that works on text
        # that follows from when it works. What the plain questions never ask about gets
        # its usual value, written down, so the card says everything a card can say.
        slots["then"] = parts.SHOW if slots.get("when", WHILE_ON) == WHILE_ON else parts.ANSWER
        slots.update(parts.defaults(slots))
        agent = store.Agent(name=slots["name"], blueprint=CUSTOM, slots=slots)
        if old and store.slugify(old.name) != store.slugify(agent.name):
            store.delete(old)
            self.replaced = old.name
        elif old:
            agent.created = old.created  # the same agent, changed
        store.save(agent)
        self.created = agent
        if draft.editing:
            yield from say(f"Saved the changes to {agent.name}.")
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
        yield from say(f"{agent.name} is ready.")
        yield AgentList([a.name for a in store.list_agents()])

    def _cancel(self) -> Iterator[Event]:
        editing, name = self.draft.editing, self.draft.replaces
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


def _says_yes(lowered: str) -> bool:
    """A yes to the card on screen: the whole message, or one that begins with a yes and
    has no "but" in it. "Ok but make it Japanese" is a change, and "yesterday" is no yes:
    told apart by the first letters alone, both once made the agent."""
    whole = lowered.strip("!. ")
    if whole in CARD_YES:
        return True
    first = re.split(r"[\s,.!]+", whole, maxsplit=1)[0]
    return first in YES_WORDS and not re.search(r"\bbut\b", whole)


def _card_slots(draft: Draft) -> dict:
    """A draft's settings as the catalog reads a card. One that answers from documents is
    not saved as a card, so what it is made of is said here."""
    if draft.blueprint.id == CUSTOM:
        return draft.slots
    return {**draft.slots, "when": IN_CHAT, "then": parts.DOCUMENTS}


def _how_to_use(agent: store.Agent) -> str:
    """One plain line on using an agent they already have."""
    if parts.is_switchable(agent):
        return "It works while it's switched on in your helpers list."
    return f'Ask it anything by starting your message with "{agent.name}:".'


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
    """An existing agent that already answers from this folder. One that works on the new
    files of the same folder is no such agent: it does another job there."""
    wanted = os.path.normcase(str(folder.resolve()))
    for agent in store.list_agents():
        path = agent.slots.get("folder")
        if (agent.blueprint == parts.DOCUMENTS_QA and path
                and os.path.normcase(str(Path(path).resolve())) == wanted):
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
    parts_ = ", ".join(f"{n} {kind}" for kind, n in kinds.most_common())
    return f"{len(files)} files: {parts_}" if len(files) != 1 else f"1 file: {parts_}"


def create_documents_agent(ollama: Ollama, model: str, agent: store.Agent,
                           think: bool | None = None) -> Iterator[Event]:
    """Make an agent that answers from the documents in its folder: read the files (which
    saves it), give it a test drive with one question those files answer, and say how to
    use it. Both ways of making one end here: the plain questions (AgentBuilder._create)
    and the designing conversation (designer.py). A generator that returns whether the
    agent was made (use `yield from`): a folder that can't be read makes nothing."""
    try:
        index = yield from runner.refresh_index(agent)  # reads the files and saves the agent
    except OSError as exc:
        yield from say(f"I couldn't read that folder ({exc.strerror}). Nothing was created.")
        return False

    if index.passages:
        yield Progress("Giving it a test drive...")
        try:
            passage = max(index.passages[:40], key=lambda p: len(p.text))
            schema = {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}
            reply = ollama.chat_json(
                model,
                [{"role": "system", "content": "Write one short, natural question that this passage "
                                               "answers, as a person would ask it. Same language as the passage."},
                 {"role": "user", "content": passage.text}],
                schema, think=think,
            )
            question = reply.get("question", "").strip() or "What are these files about?"
            result = None
            for event in runner.run(ollama, model, agent, question, think):
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
    return True


def _model_name() -> str:
    tag = load_state().get("base_model", "")
    model = find_model(tag) if tag else None
    return model.name if model else (tag or "the built-in model")
