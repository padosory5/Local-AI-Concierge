"""Create an agent with the user: offer it, fill in its slots, show the agent
card, and on "Create it" read its files and give it a test drive.

Code drives every step. The model only pulls a folder name out of what the
user typed, and writes the test-drive question.
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
from ..events import AgentCard, AgentList, ElainaDone, ElainaText, Event, Progress, Question, Result
from ..ollama import Ollama, OllamaError
from . import runner, store
from .blueprint import Blueprint
from .files import scan

PLACES = ["Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos"]
CANCEL_WORDS = ("cancel", "never mind", "nevermind", "forget it", "no thanks", "stop", "취소", "그만")
YES_WORDS = ("yes", "yeah", "yep", "sure", "ok", "okay", "create", "do it", "go ahead", "응", "네", "좋아")
# Folders an agent may never read, even if the user names them.
BLOCKED = [Path(os.environ.get(v, "")) for v in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData")]
SKIP_WHILE_SEARCHING = {"appdata", "node_modules", ".git", "$recycle.bin", "library"}

CARD, CHANGE, PICK_FOLDER = "card", "change", "pick_folder"


@dataclass
class Draft:
    blueprint: Blueprint
    slots: dict = field(default_factory=dict)
    waiting: str | None = None  # slot key we asked for, or CARD / PICK_FOLDER / CHANGE
    file_count: int = 0
    file_summary: str = ""


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
        self.draft = Draft(bp)
        yield from say(f"I can make you an agent for that: {bp.name}. {bp.pitch.strip()}")
        if bp.slot("folder"):
            yield from self._take_folder(request, from_request=True)

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
        elif draft.waiting == CARD and any(lowered == w or lowered.startswith(w) for w in YES_WORDS):
            yield from self._create()
        elif draft.waiting == CARD and lowered in ("no", "nope", "아니"):
            yield from self._cancel()
        else:
            # Waiting for a button but the user typed something else: they
            # moved on, so drop the setup and let the engine handle it.
            self.draft = None
            self.handoff = text
            yield from say("I'll leave the agent setup for now.")

    def choose(self, id: str, choice: str) -> Iterator[Event]:
        draft = self.draft
        if id == CARD and choice == "Create it":
            yield from self._create()
        elif id == CARD and choice == "Change something":
            labels = [s.label for s in draft.blueprint.slots if s.changeable]
            draft.waiting = CHANGE
            yield Question(CHANGE, "What would you like to change?", labels + ["Nothing, go back"])
        elif id == CARD:
            yield from self._cancel()
        elif id == CHANGE:
            slot = next((s for s in draft.blueprint.slots if s.label == choice), None)
            if slot is None:
                yield from self._show_card()
            elif slot.key == "folder":
                draft.waiting = "folder"
                yield Question("folder", "Which folder should it read instead?")
            else:
                draft.waiting = slot.key
                yield Question(slot.key, f"What should the {slot.label.lower()} be?")
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
        yield from self._next()

    def _take_name(self, text: str) -> Iterator[Event]:
        name = text.strip().strip("\"'")[:40]
        if not name:
            yield Question("name", "What should it be called?")
            return
        if store.name_taken(name):
            yield from say(f"You already have an agent called {name}.")
            yield Question("name", "What should this one be called?")
            return
        self.draft.slots["name"] = name
        yield from self._next()

    def _next(self) -> Iterator[Event]:
        """Ask for the next empty slot, or show the card when all are filled."""
        draft = self.draft
        for slot in draft.blueprint.slots:
            if slot.key not in draft.slots and slot.ask:
                draft.waiting = slot.key
                yield Question(slot.key, slot.ask)
                return
        yield from self._show_card()

    def _show_card(self) -> Iterator[Event]:
        draft = self.draft
        draft.waiting = CARD
        yield AgentCard(
            id=CARD,
            name=draft.slots["name"],
            kind=draft.blueprint.name,
            reads=[f"{draft.slots['folder']} ({draft.file_summary})"],
            can_do=list(draft.blueprint.can_do),
            cannot_do=list(draft.blueprint.cannot_do),
            runs_on=f"{_model_name()} (Elaina's model, no extra memory)",
        )

    # ------------------------------------------------------------ finish

    def _create(self) -> Iterator[Event]:
        draft = self.draft
        agent = store.Agent(name=draft.slots["name"], blueprint=draft.blueprint.id, slots=dict(draft.slots))
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

    def _cancel(self) -> Iterator[Event]:
        self.draft = None
        yield from say("Okay, I won't create it.")

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
