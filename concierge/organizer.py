"""Keeping a folder organized: the first chore Noir builds for people (the organizer
blueprint, agents/blueprints/organizer.yaml).

An organizer watches a folder. Only what lands after it was switched on counts:
everything already there is written down as old at that moment (and again at each
start), so "only new files from now on" means it. When a new document has sat still,
the built-in model reads its first pages. With folders the user named, it fills one
form forced by a schema: which of those folders, or "not sure". Deciding as it goes,
it only says what the document is about, as a subject or course name, and whether
it is sure; code matches those words to the folders made so far, or makes a new one.
The model is never asked to pick between "a folder I made" and "a new folder": the
first run showed a small model takes an existing folder every time, and a club guide
became the home of every lab handout. Code moves the file under a free name, writes
the move down so it can be undone for a week, and tells the chores list. A file the
model isn't sure about stays and is said so; anything that isn't a document (a
picture, a video, a .json, a .csv) is never touched. Nothing leaves the computer.

The user and Noir decide the setup together in the builder's questions (which
folder to watch, where the sorted folders go, by content or by name, which folders),
never in code here.
"""

from __future__ import annotations

import base64
import json
import re
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from .agents import store
from .agents.files import read_pages
from .catalog import load_helpers
from .ollama import Ollama, OllamaError
from .places import known_folder
from .quick.tidy import can_undo, free_name, record_moves, undo_sort, sorts_on_record

ORGANIZER = "organizer"  # the blueprint's id
LOOK_SECONDS = 8  # how often a watched folder is looked at
SETTLE_SECONDS = 20  # a file still changing (a download in progress) is left until it has sat still this long
READ_CHARS = 3000  # how much of a file the model reads to tell what it is about
MAX_FOLDER_NAME = 40
DONE_KEPT = 100
DOCUMENTS = {".pdf", ".docx", ".txt", ".md"}
# Code and notebooks are course material too: a practice5.py for CSE 163 once sat in
# Downloads unread because only documents counted.
CODE = {".py", ".ipynb", ".java", ".c", ".cpp", ".h", ".hpp", ".cs", ".js", ".ts", ".sql", ".r", ".m", ".tex", ".go",
        ".rs", ".kt", ".swift", ".rb"}
# Documents and code are sorted as soon as they read as course material. Every other kind
# (a spreadsheet, slides, a picture, a zip, a video...) is read as far as it can be and,
# the first time one reads as material, the user is asked once whether that kind should be
# sorted from then on (Organizer.asking, kinds): the user wanted every kind handled, and a
# yes once is how a surprise is avoided.
KINDS_AUTO = DOCUMENTS | CODE
IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}  # read through a vision model, when one is installed
MAX_IMAGE_MB = 8
SEE_NOTE = ("Describe this picture for filing. Copy any title, heading, course name or code you can read, then say "
            "in one or two lines what it shows: lecture notes, a whiteboard, a screenshot of an assignment, a photo "
            "of people, a receipt, a meme, or whatever it is.")
SEE_SCHEMA = {"type": "object", "properties": {"what": {"type": "string"}}, "required": ["what"]}
KIND_WAITING = "waiting for your yes on {ext} files"
KIND_REFUSED = "{ext} files are left alone, as you said"
CONTENT, BY_NAME = "What's inside each file", "The file's name"
DECIDE = "Decide as you go"
NOT_SURE = "not sure"
SUBJECT, SOMETHING_ELSE = "about one of the folders' subjects", "something else"
# Why a file stayed where it was, in the user's words, kept with each verdict so "why
# didn't you move the receipt?" has a true answer.
NO_TEXT = "nothing inside could be read, and the name alone didn't say"
NOT_MATERIAL = "not material for any of the folders"
NOT_SURE_WHICH = "which folder wasn't clear"
UNSURE_TOPIC = "what it's about wasn't clear"
SKIPPED_KEPT = 30
UNFINISHED = {".crdownload", ".part", ".tmp", ".download", ".partial"}
DECIDE_WORDS = re.compile(r"decide|you (choose|pick|name)|as you go|up to you|whatever|anything", re.IGNORECASE)
SAME_PLACE = re.compile(r"\b(same|there|inside|in) (folder|place|downloads)\b|\bleave them\b|\bno(pe)?\b|\bkeep\b", re.IGNORECASE)
PLACES = {"desktop": "Desktop", "documents": "Documents", "downloads": "Downloads", "pictures": "Pictures", "home": "home"}
CALLED = re.compile(r"\b(?:called|calling it|named|name it|call it|titled)\s+[\"']?([A-Za-z0-9][\w \-]{0,40})", re.IGNORECASE)
PATH = re.compile(r'([A-Za-z]:[\\/][^"\n,]*|~[\\/][^"\n,]*)')
COURSE = re.compile(r"\b([A-Za-z]{2,5})\s?-?(\d{3}[A-Za-z]?)\b")
WATCHED = re.compile(r"\b(?:from|in|watch|read|look at)\s+(?:my\s+|the\s+)?(downloads|desktop|documents|pictures)\b(?!\s+(?:called|calling|named))",
                     re.IGNORECASE)
STOPWORDS = {"the", "and", "for", "with", "from", "notes", "note", "file", "files", "document", "documents", "guide",
             "report", "handout", "lab", "labs", "practice", "sheet", "homework", "assignment", "week", "midterm",
             "exam", "quiz", "lecture", "class", "course", "intro", "introduction"}
TOPIC_NOTE = (
    "You are filing a document into folders by subject. Say what this document is about, as the name a "
    "folder for it would have: two to four plain words, a subject or a course, like \"Physics 122\", "
    "\"Tax 2026\" or \"Job applications\". Name the subject, never the particular document: \"Physics 122\", "
    "not \"Physics 122 Lab 3 report\". If it belongs with one of the folders listed, give that folder's exact "
    "name. sure: yes only when the subject is clear from the text and the document is material about it "
    "(notes, homework, a lab, a reading, code or a notebook for a course); a bill, a statement, a receipt, a "
    "certificate, a letter, a form, a résumé or a file you can't make out is no."
)
PICK_NOTE = (
    "You are filing a document into one of the user's folders, each named for a subject or a course. First say "
    "what kind of document this is: \"about one of the "
    "folders' subjects\" only when it is material of that subject (lecture notes, a lab, homework, an "
    "assignment, an exam, a syllabus, a reading, a project, code, a notebook, data or a spreadsheet for an "
    "assignment, slides, a photo or scan of notes, for that course); a bill, a "
    "statement, a receipt, a certificate, a letter, a form, a résumé, a CV, a manual, a program or project for "
    "something else, a README or code that names no course, or anything administrative or unrelated is "
    "\"something else\", even if it mentions a course or a subject. When the text does not say which course it "
    "is for, it is \"something else\". Then the folder it belongs in, or \"not sure\". Never guess."
)


def how(agent: store.Agent) -> str:
    """One sentence for the chores list, from the agent's own settings."""
    slots = agent.slots
    by = "what's inside each one" if slots.get("by", CONTENT) == CONTENT else "its name"
    groups = slots.get("groups", DECIDE)
    where = "into folders it names as it goes" if groups == DECIDE else f"into {groups}"
    into = slots.get("into") or ""
    place = f" in {into}" if into else ""
    return (f"Watches {Path(slots.get('folder', '')).name or 'a folder'} and moves each new file {where}{place}, "
            f"by {by}. A kind of file it hasn't sorted before, it asks about once.")


def organizer_card(slots: dict, cannot_do: list[str]) -> tuple[list[str], list[str], list[str]]:
    """(reads, can do, cannot do) for the agent card, from the slots."""
    folder = Path(slots.get("folder", "")).name or "the folder"
    by_content = slots.get("by", CONTENT) == CONTENT
    groups = slots.get("groups", DECIDE)
    into = slots.get("into") or ""
    reads = [f"New files in {folder}"
             + (": documents, code, spreadsheets, slides and zips by what's inside, pictures through a vision model, "
                "the rest by name, all on this computer" if by_content else ", their names only")]
    can_do = [f"Tell what each file is about by {'what is inside it' if by_content else 'its name'}",
              "Ask once about a kind of file it hasn't sorted before (a spreadsheet, a picture), then sort that kind "
              "from then on",
              ("Make folders as it goes, named by what it finds, and reuse them" if groups == DECIDE
               else f"Put each one in the right folder of: {groups}"),
              f"Keep the folders in {into}" if into else f"Keep the folders inside {folder}",
              "Show every move in your chores, with Undo for a week"]
    return reads, can_do, list(cannot_do)


def groups_from(text: str) -> str:
    """What the user answered to "which folders": the user's list, tidied, or DECIDE."""
    if DECIDE_WORDS.search(text):
        return DECIDE
    parts = [part.strip(" .") for part in re.split(r",|;|\band\b|/|\n", text) if part.strip(" ./")]
    return ", ".join(dict.fromkeys(parts)) or DECIDE


def courses_in(text: str) -> str:
    """Course codes the user mentioned ("phys122 and cse163"), as folders: "PHYS122, CSE163"."""
    found = []
    for letters, number in COURSE.findall(text):
        code = f"{letters.upper()}{number.upper()}"
        if code not in found:
            found.append(code)
    return ", ".join(found)


def watched_from(text: str, place: Callable[[str, Path], Path] = known_folder) -> Path | None:
    """The folder the user said to watch ("from Downloads", "the files in my Documents"), as the
    real place; None when they didn't say. "on my desktop called College" is a destination, not this."""
    found = WATCHED.search(text)
    return place(found.group(1).capitalize(), Path.home()) if found else None


def destination_from(text: str, home: Path | None = None, place: Callable[[str, Path], Path] = known_folder) -> str | None:
    """Where the user said the sorted folders should go: a path ("Desktop, in a folder
    called College" becomes the real Desktop, OneDrive's if that is where Windows keeps
    it, plus College), "" for inside the watched folder, or None when they didn't say."""
    home = home or Path.home()
    rest = text
    typed = PATH.search(text)
    if typed:
        # A typed path: the longest start that exists is a folder they named (often the
        # one being watched, with the destination said after it in words); a path that
        # doesn't exist yet is the destination itself, up to its first space.
        words = typed.group(1).strip().split(" ")
        existing = next((" ".join(words[:end]) for end in range(len(words), 0, -1)
                         if Path(" ".join(words[:end])).expanduser().is_dir()), None)
        rest = text[:typed.start()] + " " + text[typed.start() + len(existing or words[0]):]
        if not existing:
            return str(Path(words[0].rstrip(".!?")).expanduser())
    if SAME_PLACE.search(rest):
        return ""
    lowered = rest.lower()
    where = next((PLACES[word] for word in PLACES if re.search(rf"\b{word}\b", lowered)), None)
    called = CALLED.search(rest)
    name = re.sub(r"\s+(please|now|thanks)$", "", called.group(1).strip(" .,!?")) if called else ""
    name = name[:1].upper() + name[1:]  # "calling it college" makes a folder called College
    if where is None and not name:
        return str(Path(existing).expanduser()) if typed and existing and not rest.strip(" .,!?") else None
    base = place(where, home) if where else home
    return str(base / name) if name else str(base)


def shown_folder(agent: store.Agent, folder: str) -> str:
    """How a move is written down: "College/PHYS122" when the folders live somewhere else."""
    into = agent.slots.get("into") or ""
    return str(Path(Path(into).name) / folder) if into else folder


def folder_name(name: str) -> str:
    """A safe folder name from the model's words: letters, digits, spaces and a few marks."""
    clean = re.sub(r"[^\w \-&().]+", " ", name, flags=re.UNICODE).strip(" .")
    clean = re.sub(r"\s+", " ", clean)[:MAX_FOLDER_NAME].strip()
    return clean


def words_of(name: str) -> set[str]:
    """The telling words of a folder name or topic: "Physics 122 Lab A03" is {physics, 122}."""
    return {word for word in re.findall(r"[a-z0-9]+", name.lower()) if word not in STOPWORDS and len(word) >= 2}


def closest(topic: str, known: list[str]) -> str | None:
    """The known folder that shares the most telling words with the topic, if any."""
    mine = words_of(topic)
    best, score = None, 0
    for name in known:
        shared = len(mine & words_of(name))
        if shared > score:
            best, score = name, shared
    return best


class Organizer:
    """Runs every organizer that is switched on: a look at each watched folder every
    LOOK_SECONDS on a thread of its own, and a pass over a folder when asked."""

    def __init__(self, ollama: Ollama, model: str, log: Path, done_path: Path, read: Callable = read_pages,
                 clock: Callable[[], float] = time.time, look_seconds: float = LOOK_SECONDS,
                 settle_seconds: float = SETTLE_SECONDS):
        """read, clock and the seconds are replaced in tests."""
        self.ollama, self.model = ollama, model
        self.log, self.done_path = log, done_path
        self._read, self._clock = read, clock
        self._look_seconds, self._settle_seconds = look_seconds, settle_seconds
        self.active: dict[str, store.Agent] = {}
        self.made: dict[str, list[str]] = {}  # folders each organizer made, so it reuses them
        # Files that were already there when it was switched on, plus files judged since:
        # neither is asked about again, so "only new files from now on" holds.
        self._seen: dict[str, set[str]] = {}
        # Files it read and left, newest last, with why: {"name", "where", "why", "when"}.
        self.skipped: dict[str, list[dict]] = {}
        self.changed: Callable[[], None] = lambda: None  # told whenever the chores list would change
        # Told of each file moved while watching, {"name", "folder", "to", "sort"}: the window
        # shows a small note with Undo, since the user may be looking elsewhere.
        self.moved: Callable[[dict], None] = lambda move: None
        # Kinds of file beyond documents and code, per organizer: ext -> "yes" or "no", as the
        # user answered; and the questions waiting for an answer, each with the files held back.
        self.kinds: dict[str, dict[str, str]] = {}
        self.asking: list[dict] = []
        self.asked: Callable[[dict], None] = lambda question: None  # told of each new question
        self.vision = ""  # the installed model that can see pictures, found once per run
        self._vision_checked = False
        self._done = self._read_done()
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------ switching

    def is_on(self, name: str) -> bool:
        return name in self.active

    def switch(self, agent: store.Agent, on: bool) -> None:
        """On: the agent as it is now, with everything in its folder counted as old when it
        wasn't on before or now watches another folder (a changed agent once kept the old
        folder's baseline and filed all of the new one)."""
        with self._lock:
            if on:
                before = self.active.get(agent.name)
                self.active[agent.name] = agent
                if before is None or before.slots.get("folder") != agent.slots.get("folder"):
                    self._seen[agent.name] = {str(path) for path in self.files(agent, settled=False)}
            else:
                self.active.pop(agent.name, None)
        self._write_state()
        if on:
            self._start()

    def refresh(self, agents: list[store.Agent]) -> None:
        """Agents changed or were deleted: keep the ones that are on in step, and bring
        back the ones that were on last time the app ran, counting what is in their
        folders now as old."""
        by_name = {a.name: a for a in agents if a.blueprint == ORGANIZER}
        with self._lock:
            kept = {}
            for name, before in self.active.items():
                if name not in by_name:
                    continue
                kept[name] = by_name[name]
                if by_name[name].slots.get("folder") != before.slots.get("folder"):
                    self._seen[name] = {str(path) for path in self.files(by_name[name], settled=False)}
            self.active = kept
            for name in self._read_state().get("on", []):
                if name in by_name and name not in self.active:
                    self.active[name] = by_name[name]
                    self._seen[name] = {str(path) for path in self.files(by_name[name], settled=False)}
        if self.active:
            self._start()

    def stop(self) -> None:
        self._stopping.set()

    def _start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stopping.clear()
            self._thread = threading.Thread(target=self._keep_looking, name="organizer", daemon=True)
            self._thread.start()

    def _keep_looking(self) -> None:
        while not self._stopping.wait(self._look_seconds):
            try:
                self.look()
            except Exception:  # a broken file must not stop the watching
                import traceback

                traceback.print_exc()

    # --------------------------------------------------------------- looking

    def look(self) -> None:
        """One look at every watched folder: new, settled documents get filed."""
        for agent in list(self.active.values()):
            for path in self.new_files(agent):
                self._seen[agent.name].add(str(path))
                self._file(agent, path)

    def files(self, agent: store.Agent, settled: bool = True) -> list[Path]:
        """The documents loose in the watched folder: document kinds only, not hidden, not
        a download still arriving, and (settled) not changed in the last while."""
        folder = Path(agent.slots.get("folder", ""))
        if not folder.is_dir():
            return []
        found = []
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.name.startswith(".") or path.suffix.lower() in UNFINISHED:
                continue
            try:
                if settled and self._clock() - path.stat().st_mtime < self._settle_seconds:
                    continue
            except OSError:
                continue
            found.append(path)
        return found

    def new_files(self, agent: store.Agent, settled: bool = True) -> list[Path]:
        """Documents that landed after it was switched on and haven't been judged."""
        seen = self._seen.setdefault(agent.name, set())
        return [path for path in self.files(agent, settled) if str(path) not in seen]

    def count_files(self, agent: store.Agent) -> int:
        return len(self.files(agent, settled=False))

    def run_once(self, agent: store.Agent, everything: bool = False) -> Iterator[str | dict]:
        """Go through the folder now: what has landed since it was switched on, or
        (everything) all of it, the first pass the user is asked about. Yields what it is
        doing, then the outcome: {"moved", "where": [{"folder", "count"}], "left", "fresh", "id"}."""
        moved: list[dict] = []
        left: list[str] = []  # why each file that stayed did
        files = self.files(agent, settled=False) if everything else self.new_files(agent, settled=False)
        for index, path in enumerate(files, 1):
            yield f"Reading {path.name} ({index} of {len(files)})..."
            move = self._file(agent, path, record=False)
            if move:
                moved.append(move)
            else:
                kept = self.skipped.get(agent.name, [])
                left.append(kept[-1]["why"] if kept and kept[-1]["name"] == path.name else "it couldn't be moved")
            self._seen.setdefault(agent.name, set()).add(str(path))
        sort_id = ""
        if moved:
            sort_id = record_moves(self.log, moved, agent=agent.name)
            where = self._where(moved)
            self._remember(f"Sorted {len(moved)} document{'' if len(moved) == 1 else 's'} in "
                           f"{Path(agent.slots.get('folder', '')).name}",
                           " · ".join(f"{w['folder']} {w['count']}" for w in where), sort_id, agent.name)
        reasons = [{"why": why, "count": left.count(why)} for why in dict.fromkeys(left)]
        yield {"moved": len(moved), "where": self._where(moved), "left": len(left), "why": reasons, "id": sort_id,
               "looked": len(files)}

    def _file(self, agent: store.Agent, path: Path, record: bool = True) -> dict | None:
        """Judge one file and move it. Returns the move, or None when it stayed: not material,
        or a kind the user hasn't said yes to yet (then it is asked), or said no to."""
        folder, why = self.verdict(agent, path)
        if folder:
            ext = path.suffix.lower()
            said = self.kinds.get(agent.name, {}).get(ext)
            if ext not in KINDS_AUTO and said != "yes":
                if said == "no":
                    why = KIND_REFUSED.format(ext=ext)
                else:
                    self._ask_kind(agent, path, folder)
                    why = KIND_WAITING.format(ext=ext)
                folder = None
        if not folder:
            self._skip(agent, path, why)
            return None
        return self._move(agent, path, folder, record)

    def _skip(self, agent: store.Agent, path: Path, why: str) -> None:
        kept = self.skipped.setdefault(agent.name, [])
        kept[:] = [item for item in kept if item["name"] != path.name]
        kept.append({"name": path.name, "where": str(path.parent), "why": why, "when": self._clock()})
        del kept[:-SKIPPED_KEPT]

    def _move(self, agent: store.Agent, path: Path, folder: str, record: bool = True, tell: bool = True) -> dict | None:
        """Move one file into its folder. Returns the move, or None when it couldn't be moved."""
        into = Path(agent.slots.get("into") or agent.slots.get("folder", "")) / folder
        try:
            into.mkdir(parents=True, exist_ok=True)
            target = free_name(into / path.name)
            path.rename(target)
            if not target.is_file():
                return None
        except OSError:
            return None
        if folder not in self.made.get(agent.name, []):
            self.made.setdefault(agent.name, []).append(folder)
            self._write_state()
        move = {"from": str(path), "to": str(target)}
        if record:
            sort_id = record_moves(self.log, [move], agent=agent.name)
            self._remember(f"Put {path.name} in {shown_folder(agent, folder)}", f"from {path.parent.name}",
                           sort_id, agent.name, where=str(target.parent))
            if tell:
                try:
                    self.moved({"name": path.name, "folder": shown_folder(agent, folder), "to": str(target.parent),
                                "sort": sort_id})
                except Exception:  # noqa: BLE001 - a note that can't be shown must never undo the move
                    pass
        return move

    # ------------------------------------------------- kinds the user is asked about once

    def _ask_kind(self, agent: store.Agent, path: Path, folder: str) -> None:
        """A file of a kind it hasn't sorted before reads as material: hold it and ask once,
        for the kind. More files of that kind join the same question."""
        ext = path.suffix.lower()
        with self._lock:
            for question in self.asking:
                if question["agent"] == agent.name and question["ext"] == ext:
                    if all(item["path"] != str(path) for item in question["files"]):
                        question["files"].append({"path": str(path), "folder": folder})
                        self._write_state()
                    return
            question = {"id": f"kind:{agent.name}:{ext}", "agent": agent.name, "ext": ext,
                        "text": f"{path.name} looks like {folder} material. Sort {ext} files like it from now on?",
                        "files": [{"path": str(path), "folder": folder}], "when": self._clock()}
            self.asking.append(question)
            self._write_state()
        self.changed()
        try:
            self.asked(dict(question))
        except Exception:  # noqa: BLE001 - the question waits in the windows whatever the note did
            pass

    def questions(self) -> list[dict]:
        """The questions waiting for an answer, oldest first: {"id", "text", "count"}."""
        with self._lock:
            return [{"id": q["id"], "text": q["text"], "count": len(q["files"])} for q in self.asking]

    def answer(self, id: str, yes: bool) -> int:
        """The user's answer about a kind of file: yes sorts the files held back and every
        such file from now on; no leaves that kind alone. Returns how many moved."""
        with self._lock:
            question = next((q for q in self.asking if q["id"] == id), None)
            if question is None:
                return 0
            self.asking.remove(question)
            self.kinds.setdefault(question["agent"], {})[question["ext"]] = "yes" if yes else "no"
            self._write_state()
        agent = self.active.get(question["agent"]) or store.find_agent(question["agent"])
        moved = 0
        for item in question["files"]:
            path = Path(item["path"])
            if agent is None or not path.is_file():
                continue
            if yes:
                if self._move(agent, path, item["folder"], record=True, tell=False):
                    moved += 1
                    kept = self.skipped.get(agent.name, [])
                    kept[:] = [entry for entry in kept if entry["name"] != path.name]
            else:
                self._skip(agent, path, KIND_REFUSED.format(ext=question["ext"]))
        self.changed()
        return moved

    def seer(self) -> str:
        """The installed model that can see pictures, if any: the catalog's vision helper
        first, else any model Ollama says has vision. Looked for once per run."""
        if self._vision_checked:
            return self.vision
        self._vision_checked = True
        try:
            installed = self.ollama.list_models()
            for tag in [h.tag for h in load_helpers() if h.role == "vision"]:
                if tag in installed or f"{tag}:latest" in installed:
                    self.vision = tag
                    return tag
            for tag in installed:
                if tag.split(":")[0] == self.model.split(":")[0]:
                    continue
                if "vision" in self.ollama.capabilities(tag):
                    self.vision = tag
                    return tag
        except (OllamaError, OSError, ValueError, AttributeError):
            pass
        return ""

    def _see(self, picture: bytes) -> str:
        """What a picture shows, from the vision model: its text and what it is."""
        tag = self.seer()
        if not tag or not picture or len(picture) > MAX_IMAGE_MB * 1024 * 1024:
            return ""
        try:
            reply = self.ollama.chat_json(tag, [{"role": "user", "content": SEE_NOTE,
                                                 "images": [base64.b64encode(picture).decode()]}], SEE_SCHEMA, think=False)
        except OllamaError:
            return ""
        what = str((reply or {}).get("what", "")).strip()
        return f"A picture. What it shows: {what}" if what else ""

    def _scanned(self, path: Path) -> str:
        """A PDF with no text is a scan: its first page's picture is looked at instead."""
        try:
            from pypdf import PdfReader

            for image in PdfReader(str(path)).pages[0].images:
                return self._see(image.data)
        except Exception:  # noqa: BLE001 - whatever pypdf finds odd in a scan: it stays unread
            pass
        return ""

    def judge(self, agent: store.Agent, path: Path) -> str | None:
        """The folder this file belongs in, or None."""
        return self.verdict(agent, path)[0]

    def verdict(self, agent: store.Agent, path: Path) -> tuple[str | None, str]:
        """The folder this file belongs in, or None and why not, in the user's words. The
        user's folders are a forced choice; deciding as it goes, the model only names the
        subject and code places it."""
        slots = agent.slots
        by_content = slots.get("by", CONTENT) == CONTENT
        text = self._text(path) if by_content else ""
        unread = by_content and not text  # a video, a program, a picture with no vision model: the name must do
        by_name = "" if by_content else "from its name alone, "
        groups = slots.get("groups", DECIDE)
        content = f"File name: {path.name}\n" + (f"First lines:\n{text}" if text else "")
        if unread:
            content += ("(Nothing inside could be read. Judge by the name alone, and say \"something else\" or not "
                        "sure unless the name clearly says what it is for.)")
        if groups == DECIDE:
            known = list(self.made.get(agent.name, []))
            schema = {"type": "object", "properties": {"topic": {"type": "string"}, "sure": {"enum": ["yes", "no"]}},
                      "required": ["topic", "sure"]}
            listed = "\n".join(f"- {name}" for name in known) or "- (none yet)"
            reply = self._ask(f"{TOPIC_NOTE}\n\nFolders so far:\n{listed}", content, schema)
            if reply is None or reply.get("sure") != "yes":
                return None, NO_TEXT if unread else by_name + UNSURE_TOPIC
            topic = folder_name(str(reply.get("topic", "")))
            if len(topic) < 2:
                return None, NO_TEXT if unread else by_name + UNSURE_TOPIC
            return closest(topic, known) or topic, ""
        known = [group.strip() for group in groups.split(",") if group.strip()]
        schema = {"type": "object",
                  "properties": {"kind": {"enum": [SUBJECT, SOMETHING_ELSE]}, "folder": {"enum": [*known, NOT_SURE]}},
                  "required": ["kind", "folder"]}
        # The folders by name only: a few file names already in each, tried as a hint, made
        # the 4B model call hw2_pandas.py "something else"; bare names got five of five right.
        listed = "\n".join(f"- {name}" for name in known)
        reply = self._ask(f"{PICK_NOTE}\n\nFolders:\n{listed}", content, schema)
        if not reply or reply.get("kind") != SUBJECT:
            return None, NO_TEXT if unread else by_name + NOT_MATERIAL  # a bill, a form, a CV: whatever it mentions
        chosen = reply.get("folder", NOT_SURE)
        return (chosen, "") if chosen in known else (None, NO_TEXT if unread else by_name + NOT_SURE_WHICH)

    def _ask(self, system: str, content: str, schema: dict) -> dict | None:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        try:
            return self.ollama.chat_json(self.model, messages, schema, think=False)
        except OllamaError:
            return None

    def _text(self, path: Path) -> str:
        """What can be read of a file: its words, a picture's description, a zip's contents."""
        suffix = path.suffix.lower()
        if suffix in IMAGES:
            try:
                return self._see(path.read_bytes())[:READ_CHARS]
            except OSError:
                return ""
        try:
            pages = self._read(path)
        except Exception:  # noqa: BLE001 - a broken file of any kind reads as nothing
            pages = []
        text = ""
        for _, piece in pages:
            text += piece + "\n"
            if len(text) >= READ_CHARS:
                break
        text = re.sub(r"[ \t]+", " ", text).strip()[:READ_CHARS]
        if not text and suffix == ".pdf":
            text = self._scanned(path)[:READ_CHARS]
        return text

    # ---------------------------------------------------------- the record

    @staticmethod
    def _where(moved: list[dict]) -> list[dict]:
        counts: dict[str, int] = {}
        for move in moved:
            folder = Path(move["to"]).parent.name
            counts[folder] = counts.get(folder, 0) + 1
        return [{"folder": folder, "count": count} for folder, count in sorted(counts.items(), key=lambda item: -item[1])]

    def _remember(self, text: str, details: str, sort_id: str, agent: str, where: str = "") -> None:
        job = {"when": self._clock(), "text": text, "undo": True, "details": details, "sort": sort_id,
               "agent": agent, "where": where}
        # Read back first: the list on disk may have been tidied while the app ran.
        self._done = [*self._read_done(), job][-DONE_KEPT:]
        self._write_done()
        self.changed()

    def done_lately(self) -> list[dict]:
        """Every job remembered, oldest first, with undo still true only while the move can go back."""
        return [{**job, "undo": bool(job.get("sort")) and can_undo(self.log, job["sort"])} for job in self._done]

    def last_moves(self, limit: int = 5) -> list[dict]:
        """The newest moves still on record, newest first: {"name", "to" (the whole folder), "when"},
        from the move log itself, so the files of a pass count as much as one that landed."""
        moves = []
        for sort in reversed(sorts_on_record(self.log)):
            for move in reversed(sort.get("moves", [])):
                target = Path(move["to"])
                moves.append({"name": target.name, "to": str(target.parent), "when": sort["when"]})
                if len(moves) >= limit:
                    return moves
        return moves

    def last_skipped(self, limit: int = 5) -> list[dict]:
        """The newest files it read and left where they were, newest first, with why."""
        skipped = [item for items in self.skipped.values() for item in items]
        skipped.sort(key=lambda item: item["when"], reverse=True)
        return skipped[:limit]

    def undo(self, sort_id: str) -> int:
        """Put one job's files back. 0 when the id isn't one of this organizer's."""
        if not sort_id or not can_undo(self.log, sort_id):
            return 0
        back = undo_sort(self.log, sort_id)
        self._remember(f"Put {back} file{'' if back == 1 else 's'} back", "", "", "")
        return back

    def _read_done(self) -> list[dict]:
        try:
            return json.loads(self.done_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _write_done(self) -> None:
        try:
            self.done_path.parent.mkdir(parents=True, exist_ok=True)
            self.done_path.write_text(json.dumps(self._done, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _state_path(self) -> Path:
        return self.done_path.with_name("organizer_state.json")

    def _read_state(self) -> dict:
        try:
            state = json.loads(self._state_path().read_text(encoding="utf-8"))
            self.made = {name: list(folders) for name, folders in state.get("made", {}).items()}
            self.kinds = {name: dict(said) for name, said in state.get("kinds", {}).items()}
            # A question comes back after a restart, less the files that are gone meanwhile.
            self.asking = []
            for question in state.get("asking", []):
                files = [item for item in question.get("files", []) if Path(item.get("path", "")).is_file()]
                if files:
                    self.asking.append({**question, "files": files})
            return state
        except (OSError, ValueError):
            return {}

    def _write_state(self) -> None:
        try:
            self._state_path().parent.mkdir(parents=True, exist_ok=True)
            self._state_path().write_text(json.dumps({"on": list(self.active), "made": self.made, "kinds": self.kinds,
                                                      "asking": self.asking}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
