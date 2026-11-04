"""Create an agent with the user: offer it, fill in its slots, show the agent
card, and on "Create it" save it and give it a test drive.

Code drives every step. The model only pulls a folder name out of what the
user typed, and writes the test-drive question. Languages are recognised in
code (quick/translate.py).
"""

from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from ..catalog import find_model
from ..elaina import load_state
from ..events import AgentCard, AgentList, ElainaDone, ElainaText, Event, Progress, Question, Result, Thinking
from ..ollama import Ollama, OllamaError
from . import runner, store
from .blueprint import Blueprint
from .files import scan
from ..quick.agents import BOTH, CLIPBOARD
from ..quick.translate import LANGUAGES, language_in
from .recipe import (CUSTOM, IN_CHAT, MECHANICS, WHILE_ON, needs_language, rewrite_instruction, run_instruction,
                     settings_from_words, target_language, with_language, write_recipe)

PLACES = ["Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos"]
CANCEL_WORDS = ("cancel", "never mind", "nevermind", "forget it", "no thanks", "stop", "취소", "그만")
YES_WORDS = ("yes", "yeah", "yep", "sure", "ok", "okay", "create", "do it", "go ahead", "응", "네", "좋아")
# Folders an agent may never read, even if the user names them.
BLOCKED = [Path(os.environ.get(v, "")) for v in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData")]
SKIP_WHILE_SEARCHING = {"appdata", "node_modules", ".git", "$recycle.bin", "library"}

CARD, CHANGE, PICK_FOLDER, DUPLICATE = "card", "change", "pick_folder", "duplicate"
REPLACE, MAKE_ANOTHER = "Replace it", "Make another one"
CREATE_IT, SAVE_CHANGES = "Create it", "Save changes"
TARGET_LANGUAGE = "target_language"  # asked when a translator does not say which language
LANGUAGE_CHOICES = ["Korean", "English", "Japanese", "Chinese", "Spanish"]
# "rename it to Lease helper", "call it My translator"
RENAME = re.compile(r"\b(?:rename\b.*?\b(?:to|as)|call it)\s+[\"']?(.+?)[\"']?\s*[.!]?$", re.IGNORECASE)


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

    @property
    def active(self) -> bool:
        return self.draft is not None

    # ------------------------------------------------------------ entry

    def start(self, blueprint_id: str, request: str) -> Iterator[Event]:
        bp = self.blueprints[blueprint_id]
        self.draft = Draft(bp, request=request)
        yield from say(f"I can make you an agent for that: {bp.name}. {bp.pitch.strip()}")
        self._prefill(request)
        if self.draft.slots:
            found = "; ".join(f"{bp.slot(k).label.lower()}: {v}" for k, v in self.draft.slots.items() if bp.slot(k))
            yield Thinking(f"From your message: {found}.")
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
        """Make an agent from an idea's parts, with no kind of agent behind it:
        the shared template (custom.yaml) filled in from the parts, and an
        instruction Elaina writes for what it does with the text."""
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
        elif draft.waiting == "folder":
            yield from self._take_folder(text)
        elif draft.waiting == "name":
            yield from self._take_name(text)
        elif self._slot_type(draft.waiting) == "language":
            yield from self._take_language(text)
        elif self._slot_type(draft.waiting) == "instruction":
            yield from self._take_instruction(text)
        elif draft.waiting == TARGET_LANGUAGE:
            yield from self._take_target_language(text)
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
        else:
            # Waiting for a button but the user typed something else: they
            # moved on, so drop the setup and let the engine handle it.
            self.draft = None
            self.handoff = text
            yield from say("I'll leave the agent setup for now.")

    def choose(self, id: str, choice: str) -> Iterator[Event]:
        draft = self.draft
        if id == CARD and choice in (CREATE_IT, SAVE_CHANGES):
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
            self.draft = None
            if draft.blueprint.switchable:
                yield from say(f"Okay, keep using {name}. Switch it on in your helpers list.")
            else:
                yield from say(f'Okay, keep using {name}. Ask it anything, like "{name}: what does it say about...".')
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
        elif id == TARGET_LANGUAGE:
            yield from self._take_target_language(choice)
        elif self._slot_type(id) == "language":
            yield from self._take_language(choice)
        elif self._slot_type(id) == "choice":
            yield from self._set_slot(id, choice)
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
        for slot in draft.blueprint.slots:
            if slot.key not in draft.slots and slot.ask:
                draft.waiting = slot.key
                yield Question(slot.key, slot.ask, slot.choices)
                return
            if slot.key not in draft.slots and slot.default:
                draft.slots[slot.key] = slot.default
        if draft.blueprint.default_name and (draft.name_is_auto or "name" not in draft.slots):
            draft.slots["name"] = self._unique_name(_fill(draft.blueprint.default_name, draft.slots))
        yield from self._show_card()

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
            runs_on=f"{_model_name()} (Elaina's model, no extra memory)",
            actions=[SAVE_CHANGES if draft.editing else CREATE_IT, "Change something", "Cancel"],
        )

    def _prefill(self, request: str) -> None:
        """Fill in what the first message already says, so it is not asked again."""
        draft = self.draft
        for slot in draft.blueprint.slots:
            if slot.type == "language" and (language := language_in(request, target_only=True)):
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
        cannot_do = list(cannot_do) + ["Work while it's switched off or Elaina's window is closed"]
    else:
        reads = [f'What you send it in the chat, starting with its name ("{name}: ...")']
        can_do = [f"Does: {slots.get('instruction', '')}", "Answers in the chat"]
        cannot_do = list(cannot_do)
    return reads, can_do, cannot_do


def _fill(template: str, slots: dict) -> str:
    """Put slot values into a blueprint text like "{language} translator"."""
    return re.sub(r"\{(\w+)\}", lambda m: str(slots.get(m.group(1), m.group(0))), template)


def say(text: str) -> Iterator[Event]:
    yield ElainaText(text)
    yield ElainaDone()


def place_dirs(place: str) -> list[Path]:
    home = Path.home()
    if place == "home":
        return [home]
    candidates = [home / place] + [d / place for d in home.glob("OneDrive*") if d.is_dir()]
    return [d for d in candidates if d.is_dir()]


def find_folders(name: str, place: str | None, limit: int = 6) -> list[Path]:
    """Existing folders matching what the user said, best matches first."""
    if name and re.match(r"^([A-Za-z]:[\\/]|~|/)", name):
        path = Path(os.path.expanduser(name))
        return [path] if path.is_dir() else []

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
    return model.name if model else (tag or "Elaina's model")
