"""Watching a folder: the one machine that runs every card that works on new files.

A card whose WHEN is "When a new file lands in a folder" (agents/parts.py) is run here,
whatever it is for. Only what lands after it was switched on counts: everything already
there is written down as old at that moment, so "only new files from now on" means it.
When a new file has stood still, it is read as far as it can be (documents, code,
spreadsheets, the names inside a zip, a picture through a model that can see), and the
built-in model fills one small form for it by following the user's rule
(agents/worker.py): which folder it goes into, or what to write about it. Code does
everything else. The file moves under a free name and the move is written down so it can
be undone for a week, or a note is added to the end of one notes file; either way the
chores list is told. A file the model isn't sure about stays where it is, with the reason
on record. Nothing asks the user anything while it runs, and nothing leaves the computer.

Nothing here knows what any card is for. What should happen to which files is the card's
rule, which is data: the user and Noir work it out in a conversation
(agents/designer.py), never in code here.
"""

from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from .agents import parts, store, worker
from .agents.files import MARKUP, TEXT_TYPES, read_pages, text_of, without_tags
from .catalog import load_helpers
from .noir import KEEP_ALIVE
from .ollama import Ollama, OllamaError
from .quick.tidy import CLOUD_ONLY, SYSTEM_FILES, can_undo, free_name, record_moves, sorts_on_record, undo_sort

LOOK_SECONDS = 2  # how often a watched folder is looked at: a listing of its names, a few milliseconds
# A new file is read once it has stood still this long: its size and time the same from one
# look to the next, and nothing else holding it open. It used to be twenty seconds by the
# file's time alone, on top of a look every eight: half a minute in which nothing showed,
# and the user couldn't tell whether anything was happening. A download still arriving has
# another name until it is whole (UNFINISHED), or is held open by the program writing it.
SETTLE_SECONDS = 3
# A file that lands has the model loaded while it settles, so reading can start the moment it
# has. Thirty files landing together need one such call, not thirty, and one is enough for a
# while: a model asked to stay stays for noir.KEEP_ALIVE after each call.
WARM_GAP_SECONDS = 20
# A file still growing after this long is a big download, not a file about to be read, and
# one that can't be opened is in use by another program: the lists say which, and the circle
# stops running its line for it. After GIVE_UP_SECONDS of that it is left where it is, with
# the reason on record (a log some program keeps writing would otherwise sit in the lists as
# "just landed" for as long as the app ran); named in the chat, it is looked at again.
ARRIVING_SECONDS = 30
GIVE_UP_SECONDS = 600
ARRIVING, IN_USE = "arriving", "in use"
STILL_CHANGING = "it kept changing, so I left it"
HELD_OPEN = "another program kept it open, so I left it"
# Files with nothing inside a model could read: a program, a recording. One of these is
# never opened, and no model is loaded for it while it settles.
NOTHING_TO_READ = {".exe", ".msi", ".dmg", ".iso", ".dll", ".bin", ".apk", ".mp4", ".mkv", ".mov", ".avi", ".webm",
                   ".mp3", ".wav", ".flac", ".m4a"}
READ_CHARS = worker.READ_CHARS  # how much of a file the model reads to tell what it is
# Only the beginning of a file is kept, so only its beginning is read (read_start). The
# kinds below are the ones read_pages reads whole; one of them bigger than WHOLE_BYTES gives
# its first bytes instead, the way any other text does (text_of). Up to that size a file is
# read exactly as before: a megabyte of text takes 1 to 6 milliseconds, of markup about 20
# (measured).
READ_WHOLE = TEXT_TYPES | MARKUP | {".ipynb"}
WHOLE_BYTES = 1024 * 1024
# Each piece read is cut to this before the spaces in it are closed up. Several times
# READ_CHARS, since the cut to READ_CHARS comes after the closing up: text that is spaces
# and tabs for the most part still fills what the model reads.
PIECE_CHARS = 8 * READ_CHARS
DONE_KEPT = 100
IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}  # read by a model that can see (FolderWatch.seer)
MAX_IMAGE_MB = 8
# A picture is shrunk to this many pixels on its longer side before a model sees it: a
# scanned page of 3300 by 2550 was 8,000 tokens against a room of 4,096, so the call failed
# and a scanned PDF counted as unreadable. Shrunk, a picture is about 1,100 tokens
# (measured), so 4,096 is room enough, and a helper model given 8,192 took 0.6 GB more for
# nothing.
SEE_PIXELS = 1024
SEE_CONTEXT = 4096  # for a helper model; Noir's own keeps the room it was built with
SEE_KEEP_ALIVE = "30s"  # a helper model's stay if the app is killed mid-look; it is freed after each look anyway
SEEN_KEPT = 3000  # file paths remembered per card, so a restart doesn't make a new file old
# The words first, then what it is: asked only to describe a picture, the 4B model said what
# kind of screenshot it was and copied nothing; asked for the words in a field of their own
# it copied every line of six test pictures, small print and a tilted photo included. The
# note it was first measured with went on to list kinds of picture, some of them ones only
# some people's cards would ever meet, and nothing here may know what a card is for. So the
# six pictures were read again by Noir's own model on 19 Nov 2026, with the list, with a
# plainer list, and with none, which is the note below. Each copied all 25 lines there are
# in the six, in about half a second a picture. With a list, `what` came back as "a
# screenshot" for nearly every one; with none it said what the picture was of in a few
# words of its own, which is more for a rule to go by. The helper qwen3-vl:8b, given the
# note below, copied all 25 lines too.
SEE_NOTE = ("Read this picture. In `words`, copy every word, number and code you can read in it, exactly as "
            "written, line by line; leave it empty only if there is no writing at all. In `what`, say in a few words "
            "what kind of picture it is.")
SEE_SCHEMA = {"type": "object", "properties": {"words": {"type": "string"}, "what": {"type": "string"}},
              "required": ["words", "what"]}
# Why a file stayed where it was, in the user's words, kept with each file so "why didn't
# you move the receipt?" has a true answer. The ones that follow from the rule are said with
# what the model took the file for after them ("the rule leaves it: a phone bill").
NO_TEXT = "nothing inside could be read"
NO_MODEL = "the built-in model couldn't be reached"
# A reply that wasn't a form at all came from a model that was there, so it is not said to
# have been out of reach, which every such file once was.
NO_ANSWER = "the built-in model gave no answer it could use"
ALREADY_THERE = "it is in that folder already"
LEFT_BY_RULE = "the rule leaves it"
NOT_SURE_WHERE = "not sure where it goes"
NOTHING_ASKED = "the rule asks for nothing about it"
NO_RULE = "it has no rule to follow"
NOTHING_TO_DO = "it isn't set up to do anything with a file"
NOT_MOVED = "it couldn't be moved"
NOTES_NOT_WRITTEN = "the notes file couldn't be written"
SKIPPED_KEPT = 30
UNFINISHED = {".crdownload", ".part", ".tmp", ".download", ".partial"}
# Files Windows hides or keeps for itself (FILE_ATTRIBUTE_HIDDEN, FILE_ATTRIBUTE_SYSTEM) are
# never the user's files to handle, nor are SYSTEM_FILES by name. On a Windows in another
# language a folder's desktop.ini gives it the name and icon it is shown with: moved, the
# folder looks different, and a file the user has never seen turns up in a folder of theirs.
# An open document's lock file is hidden too.
WINDOWS_OWN = 0x2 | 0x4
# A file that landed while the built-in model couldn't be reached (Ollama closed from the
# tray, or still starting) is tried again, at most once in this many seconds and only once
# Ollama answers, so nothing blinks or is said again while it is still closed.
RETRY_SECONDS = 60
# A try-out for the designer (FolderWatch.rehearse): how many files it is shown on, how many
# of the newest are opened at most to find that many that can be read, and how much of a
# note it would write is shown.
REHEARSE_FILES = 8
REHEARSE_OPENED = 24
REHEARSE_NOTE_CHARS = 400
# The step of a job that says where the rule put the file: the chores list shows it beside
# the move.
DECIDED = "The rule puts it in"
# What the three files were called while this was the file organizer. They are taken over
# once, under their new names, so the moves that can still be undone, the jobs done and
# what was switched on are not lost.
OLD_LOG, OLD_DONE, OLD_STATE = "organizer.json", "organizer_done.json", "organizer_state.json"
STATE_NAME = "folderwatch_state.json"


def shrink(picture: bytes, pixels: int = SEE_PIXELS) -> bytes:
    """The picture no wider or taller than `pixels`, as a JPEG; as it came if it is small
    already or can't be read as a picture."""
    import io

    try:
        from PIL import Image

        image = Image.open(io.BytesIO(picture))
        if max(image.size) <= pixels:
            return picture
        image = image.convert("RGB")
        image.thumbnail((pixels, pixels))
        out = io.BytesIO()
        image.save(out, "JPEG", quality=85)
        return out.getvalue()
    except Exception:  # noqa: BLE001 - not a picture Pillow knows: the model gets it as it is
        return picture


def read_start(path: Path) -> Iterable[tuple[int | None, str]]:
    """The beginning of a file, in the pieces read_pages gives. read_pages was made for an
    agent that answers from documents: it reads every word, and of files up to a size.
    Here a file of any size can land and READ_CHARS of it are kept, so a big one is never
    read whole. One was: an export.csv of 301 MB, read to its end and run through a regex
    to keep 3,000 characters of it. That took 7.3 seconds and 1.6 GB of memory (measured
    on 19 Nov 2026) with every other file waiting behind it, and a file ten times the size
    would have run out of memory and been written down as "nothing inside could be read",
    which was untrue. The same file now takes 7 milliseconds. A PDF gives its pages one at
    a time, so whoever reads it can stop after the first few."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _pdf_pages(path)
    if suffix in READ_WHOLE and path.stat().st_size > WHOLE_BYTES:
        start = text_of(path)
        return [(None, without_tags(start) if suffix in MARKUP else start)]
    return read_pages(path)


def _pdf_pages(path: Path) -> Iterator[tuple[int | None, str]]:
    """A PDF's pages as text, each read only when it is asked for. Opening a long PDF
    still costs something, since pypdf lists every page before it gives the first: of a
    made-up one with 600 pages the beginning took 0.9 seconds, against 1.6 with every
    page read (measured)."""
    from pypdf import PdfReader

    for number, page in enumerate(PdfReader(str(path)).pages, 1):
        yield number, page.extract_text() or ""


def shown_folder(agent: store.Agent, folder: str) -> str:
    """How a move is written down: the folder with the place it is kept in before it, when
    the folders live somewhere other than the watched folder."""
    into = agent.slots.get("into") or ""
    return str(Path(Path(into).name) / folder) if into else folder


def _can_open(path: Path) -> bool:
    """Whether a file can be read right now: one that a program is still writing (a copy
    in progress, a document being saved) is held open and can't, so it waits."""
    try:
        with path.open("rb") as file:
            file.read(1)
        return True
    except OSError:
        return False


def _by_name(agent: store.Agent) -> bool:
    """Whether a card goes by the names of files alone, never by what is inside them."""
    return agent.slots.get("looks_at") == parts.NAME_ONLY


def _said(reason: str, what: str) -> str:
    """A reason that follows from the rule, with what the model took the file for."""
    return f"{reason}: {what}" if what else reason


def _already_there(agent: store.Agent, path: Path, folder: str) -> bool:
    """Whether the folder a file would go into is the one it is in. A card that watches a
    folder and keeps its folders beside it may have that very folder among them ("the rest
    stay in Inbox, finished ones go in Done"). Moved there, the file only got a new name in
    the same place, which made it a new file to the next look, and it was renamed again at
    every look, without end."""
    try:
        into = (parts.destination(agent.slots) / folder).resolve()
        return os.path.normcase(str(into)) == os.path.normcase(str(path.parent.resolve()))
    except (OSError, RuntimeError):
        return False


class FolderWatch:
    """Runs every card that works on new files and is switched on: a look at each watched
    folder every LOOK_SECONDS on a thread of its own, and a pass over a folder when asked."""

    def __init__(self, ollama: Ollama, model: str, log: Path, done_path: Path, read: Callable = read_start,
                 clock: Callable[[], float] = time.time, look_seconds: float = LOOK_SECONDS,
                 settle_seconds: float = SETTLE_SECONDS):
        """read, clock and the seconds are replaced in tests."""
        self.ollama, self.model = ollama, model
        self.log, self.done_path = log, done_path
        self._read, self._clock = read, clock
        self._look_seconds, self._settle_seconds = look_seconds, settle_seconds
        self.active: dict[str, store.Agent] = {}
        self.made: dict[str, list[str]] = {}  # the folders made for each card so far
        # Files that were already there when it was switched on, plus files judged since:
        # neither is asked about again, so "only new files from now on" holds.
        self._seen: dict[str, set[str]] = {}
        self._seen_before: dict[str, set[str]] = {}  # from the state file, for the agents coming back on
        # Files left only because the built-in model couldn't be reached, by card. They are
        # not counted as seen: a file that landed while Ollama was closed was once written
        # down as handled for good, and "go through them" said nothing new had landed. A
        # pass asked for in the chat takes them again at once, and the look on its own once
        # the model answers (_model_back).
        self._unreached: dict[str, set[str]] = {}
        self._retry_at = 0.0
        self._failure = ""  # why the last form put to the model got no answer: NO_MODEL or NO_ANSWER
        # Files it read and left, newest last, with why: {"name", "where", "why", "when"}.
        self.skipped: dict[str, list[dict]] = {}
        self.changed: Callable[[], None] = lambda: None  # told whenever the chores list would change
        # Told of each job done while watching, {"name", "folder", "to", "sort", "steps",
        # "text"}: the window shows a small note with Undo, since the user may be looking
        # elsewhere. `text` is the line the record has ("Put a.pdf in Boat", "Wrote about
        # a.pdf in Notes.md"); a note written has no `sort`, since there is nothing to undo.
        self.moved: Callable[[dict], None] = lambda move: None
        # Told while a file is being read and judged (True) and when that is done (False),
        # so the circle can blink and run its line; and of each file that stayed, with the
        # steps, so the small log by the circle can say what was decided and why.
        self.working: Callable[[bool], None] = lambda on: None
        self.stayed: Callable[[dict], None] = lambda report: None
        self._steps: list[str] = []  # what was read and decided about the file in hand
        self.vision = ""  # the model that can see pictures, found once per run: Noir's own when it can
        self._vision_checked = False
        self._helper_seen = False  # a helper model was loaded to see a picture, and is still in memory
        self._take_over_old_files()
        self._done = self._read_done()
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._lock = threading.Lock()
        # One file in hand at a time, whoever asked: the look that runs on its own and a pass
        # asked for in the chat once took the same file in the same second, one moved it and
        # the other told the user "it couldn't be moved".
        self._work = threading.RLock()
        # For the windows (status): files seen arriving that haven't stood still yet, the
        # file being read this moment, and when each card was switched on.
        self._landing: dict[str, dict[str, dict]] = {}
        self._now: dict[str, dict] = {}
        self.since: dict[str, float] = {}
        self._passing = 0  # passes asked for in the chat that are running right now
        self._showing_work = False  # whether the windows were last told there is work in hand
        self._warmed_at = 0.0  # when the model was last asked to be ready, so a batch of files asks once
        self._read_state()

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
                    self._seen[agent.name] = {str(path) for path in self.files(agent, settled=False, away=True)}
                    self.since[agent.name] = self._clock()
                    self._landing.pop(agent.name, None)
                    self._unreached.pop(agent.name, None)  # all of what is there is old now
                self._notes_stay_seen(before)  # changed while on: its notes may be kept somewhere else now
            else:
                self._notes_stay_seen(self.active.pop(agent.name, None))
                self._landing.pop(agent.name, None)
                self._unreached.pop(agent.name, None)  # switched on again, all of what is there is old
        self._write_state()
        if on:
            self._start()

    def forget(self, name: str) -> None:
        """A card was deleted: it is switched off and everything kept about it goes with it
        (what it had seen, the folders made for it, why files stayed). Kept, all of it
        passed to the next agent of the same name, which then began with the old one's
        list of files already seen."""
        # Behind the work lock: a file of its that is being read this second is finished first,
        # or the move would write what it had made back into the state just cleared.
        with self._work, self._lock:
            self._notes_stay_seen(self.active.pop(name, None))
            for kept in (self._seen, self._seen_before, self.made, self.skipped, self._landing, self._now, self.since,
                         self._unreached):
                kept.pop(name, None)
            self._rest_if_idle()
        self._write_state()
        self._tell(self.changed)

    def refresh(self, agents: list[store.Agent]) -> None:
        """Agents changed or were deleted: keep the ones that are on in step, and bring
        back the ones that were on last time the app ran, each with what it had seen by
        then still seen."""
        by_name = {a.name: a for a in agents if parts.watches(a)}
        marked = False
        with self._lock:
            kept, left = {}, []  # left: the cards that are gone, and each one a changed card takes the place of
            for name, before in self.active.items():
                if name not in by_name:
                    left.append(before)
                    continue
                kept[name] = by_name[name]
                if by_name[name] is not before:
                    left.append(before)
                if by_name[name].slots.get("folder") != before.slots.get("folder"):
                    self._seen[name] = {str(path) for path in self.files(by_name[name], settled=False, away=True)}
                    self.since[name] = self._clock()  # a new folder: watched from now, whatever it watched before
                    self._unreached.pop(name, None)
            self.active = kept
            for before in left:
                marked = self._notes_stay_seen(before) or marked
            # Only which cards were on is taken from the file here. The rest of it was read
            # once, when this was made (_read_state).
            was_on = self._state().get("on")
            for name in was_on if isinstance(was_on, list) else []:
                if name in by_name and name not in self.active:
                    self.active[name] = by_name[name]
                    # What it had seen before the restart stays seen, so a file that landed
                    # a moment before the restart is still new, not old: one once became
                    # old that way and "nothing new" was all the user heard. A record with
                    # nothing in it is a record too, of a card switched on in an empty
                    # folder: taken for no record, the first file that landed there became
                    # old at the next start and was never handled, with nothing to say why.
                    # Only a card an older version switched on has none, and for that one
                    # what is in its folder now counts as old.
                    if name in self._seen_before:
                        self._seen[name] = set(self._seen_before[name])
                    else:
                        self._seen[name] = {str(path) for path in self.files(by_name[name], settled=False, away=True)}
                    # Agents switched on before an older version wrote this down have none.
                    self.since.setdefault(name, self._clock())
        if marked:
            self._write_state()  # so a notes file left behind is still no new file after a restart
        if self.active:
            self._start()

    def stop(self) -> None:
        self._stopping.set()

    def _start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stopping.clear()
            self._thread = threading.Thread(target=self._keep_looking, name="folderwatch", daemon=True)
            self._thread.start()

    def _keep_looking(self) -> None:
        while not self._stopping.wait(self._look_seconds):
            try:
                self.look()
            except Exception:  # a broken file must not stop the watching
                import traceback

                traceback.print_exc()

    def _notes_stay_seen(self, agent: store.Agent | None) -> bool:
        """A card that wrote notes has gone off, is gone, or was changed so that it keeps
        its notes somewhere else or writes none. Its notes file was left out of every
        listing only while that card was on and wrote there (files), so from the next look
        it would land as a new file for every card that watches the folder it is in, the
        changed card itself included, and be handled like one: after a card's notes were
        moved to another place, its old notes file was written about in the new one and
        then moved away by a card that moves files. It is written down as seen for those
        cards instead. Called once the card has left `active` or been replaced there;
        returns whether anything was written down."""
        if agent is None or parts.then_of(agent.slots) != parts.NOTE:
            return False
        notes = parts.notes_path(agent.slots)
        now = self.active.get(agent.name)
        if now is not None and parts.then_of(now.slots) == parts.NOTE and parts.notes_path(now.slots) == notes:
            return False  # still on and still writing there: left out of every listing as before
        marked = False
        for name, other in self.active.items():
            if other.slots.get("folder") and Path(other.slots["folder"]) == notes.parent:
                seen = self._seen.setdefault(name, set())
                marked = marked or str(notes) not in seen
                seen.add(str(notes))
        return marked

    # --------------------------------------------------------------- looking

    def look(self) -> None:
        """One look at every watched folder: new, settled files get their job done. Cards
        that write notes go first, since a move takes the file away before it could be
        written about. A file whose job broke is recorded with that reason, never lost in
        silence."""
        agents = sorted(list(self.active.values()), key=lambda a: parts.then_of(a.slots) != parts.NOTE)
        judged = False
        retry = self._model_back()
        for agent in agents:
            for path in self._ready(agent, retry):
                with self._work:
                    if self.active.get(agent.name) is not agent:
                        break  # switched off, changed or deleted a moment ago: not one file more
                    seen = self._seen.setdefault(agent.name, set())
                    if str(path) in seen or not path.is_file():
                        self._landed_done(agent, path)  # a pass asked for in the chat got to it first
                        continue
                    judged = True
                    self._notes_first(agent, path)
                    self._take(agent, path)
        self._rest_if_idle()
        self._release_helper()
        if judged:
            self._write_state()

    def _take(self, agent: store.Agent, path: Path) -> None:
        """One new file in hand while watching (under the work lock): written down as seen
        before it is read, then the card's job is done on it. A job that breaks leaves the
        file with that reason on record."""
        self._seen.setdefault(agent.name, set()).add(str(path))
        self._set_now(agent, path)
        try:
            self._file(agent, path)
        except Exception as exc:  # noqa: BLE001 - one odd file must not stop the watching
            import traceback

            traceback.print_exc()
            self._skip(agent, path, f"something went wrong reading it ({type(exc).__name__})")
        finally:
            # In this order, or the lists show "just landed" again for a blink
            # between the file being read and being done with.
            self._landed_done(agent, path)
            self._clear_now(agent)

    def _notes_first(self, agent: store.Agent, path: Path) -> None:
        """A file is about to be handed to a card that may take it away (under the work
        lock). Every card that writes notes, watches the same folder and has not had this
        file yet does its job on it first, so the note is written before the file leaves.
        Going first in a look is not enough for that. Each card works out for itself, at
        its own moment, which files have stood still, so a file that settled while the
        card that writes notes was busy with another one was moved before that card had
        seen it; and a pass asked for in the chat never waited for it at all. The note
        was then never written, and nothing said why."""
        folder = agent.slots.get("folder")
        if parts.then_of(agent.slots) == parts.NOTE or not folder or path.parent != Path(folder):
            return
        for writer in list(self.active.values()):
            if writer.name == agent.name or parts.then_of(writer.slots) != parts.NOTE:
                continue
            if not writer.slots.get("folder") or Path(writer.slots["folder"]) != Path(folder):
                continue
            if str(path) not in self._seen.setdefault(writer.name, set()):
                self._take(writer, path)

    def _ready(self, agent: store.Agent, retry: bool = False) -> list[Path]:
        """The new files that have stood still and can be read now. A file is noticed the
        moment it is first seen (the windows are told, so the user sees it was), then waits
        until its size and time are the same for SETTLE_SECONDS and nothing holds it open.
        One whose own time is already that old (moved in from another folder, or a download
        that finished a while ago) doesn't wait at all. One left because the built-in model
        couldn't be reached waits, unnoticed, until `retry` (_model_back)."""
        now = self._clock()
        landing = self._landing.setdefault(agent.name, {})
        unreached = self._unreached.get(agent.name, set())
        here, ready = set(), []
        for path in self.new_files(agent, settled=False):
            key = str(path)
            if key in unreached and not retry:
                continue
            here.add(key)
            try:
                found = path.stat()
            except OSError:
                continue
            mark = (found.st_size, found.st_mtime)
            held = landing.get(key)
            grew = held is not None and held["mark"] != mark
            if held is None:
                held = landing[key] = {"name": path.name, "mark": mark, "since": now, "first": now}
                self._noticed(agent, path)
            elif grew:
                held.update(mark=mark, since=now)  # still growing
            still = now - found.st_mtime >= self._settle_seconds or now - held["since"] >= self._settle_seconds
            if still and _can_open(path):
                ready.append(path)
                continue
            waited = now - held["first"]
            if waited >= GIVE_UP_SECONDS:
                # It never stands still (a log some program keeps writing) or is never let go of:
                # left, with the reason on record, so its line doesn't sit in the lists for ever.
                with self._work:
                    self._seen.setdefault(agent.name, set()).add(key)
                    self._skip(agent, path, HELD_OPEN if still else STILL_CHANGING)
                    self._landed_done(agent, path)
                    self._write_state()
            elif waited >= ARRIVING_SECONDS and not held.get("waiting"):
                # A big download, or a file some program has open: the lists say which, and the
                # circle rests, since nothing is about to happen.
                held["waiting"] = IN_USE if still else ARRIVING
                self._rest_if_idle()
                self._tell(self.changed)
        for key in [key for key in landing if key not in here]:
            self._landed_done(agent, Path(key))  # gone again before it was read
        return ready

    def _noticed(self, agent: store.Agent, path: Path) -> None:
        """A new file was just seen: the circle's line runs from now until it is dealt with,
        the lists say it landed, and a model that will be needed starts loading while the
        file settles, so reading can begin the moment it has."""
        # Each file noticed: the circle blinks for it and runs its line. Told again per file
        # on purpose, so a second one landing is seen; it stops when nothing is in hand.
        self._showing_work = True
        self._tell(self.working, True)
        self._tell(self.changed)
        # A program or a recording is left without a model being asked, so none is loaded
        # for it, unless the card goes by names alone and the model judges every name.
        asked = agent.slots.get("looks_at") == parts.NAME_ONLY or path.suffix.lower() not in NOTHING_TO_READ
        if asked and self._clock() - self._warmed_at >= WARM_GAP_SECONDS:
            self._warmed_at = self._clock()
            threading.Thread(target=self._warm, name="folderwatch-warm", daemon=True).start()

    def _landed_done(self, agent: store.Agent, path: Path) -> None:
        """A noticed file has been dealt with, or is gone: it no longer counts as landing."""
        if self._landing.get(agent.name, {}).pop(str(path), None) is None:
            return
        self._rest_if_idle()
        self._tell(self.changed)

    def _in_hand(self) -> bool:
        """Whether there is work in hand this moment: a file being read, a pass running, or a
        file that landed and is about to be read. Worked out from what is there rather than
        counted up and down, so it cannot drift when a file vanishes or a job breaks."""
        if self._now or self._passing:
            return True
        # Copies, since the windows ask from their own threads while files come and go.
        return any(not held.get("waiting") for landing in list(self._landing.values()) for held in list(landing.values()))

    def _rest_if_idle(self) -> None:
        """Tell the windows the work is over, once there is nothing left in hand."""
        if self._showing_work and not self._in_hand():
            self._showing_work = False
            self._tell(self.working, False)

    def _warm(self) -> None:
        """Have the model in memory by the time the file has settled: loading it is the
        longest part of reading one file (2.5 of about 3 seconds, measured)."""
        try:
            self.ollama.refresh(self.model, KEEP_ALIVE)
        except Exception:  # noqa: BLE001 - Ollama not answering: reading the file will say so
            pass

    def _model_back(self) -> bool:
        """Whether the files left because the built-in model couldn't be reached are tried
        again in this look: at most once every RETRY_SECONDS, and only when Ollama answers
        (a listing of its models, which loads nothing)."""
        if self._clock() < self._retry_at or not any(list(self._unreached.values())):
            return False
        self._retry_at = self._clock() + RETRY_SECONDS
        with self._work:  # a pass may be adding to these this moment
            for name, keys in list(self._unreached.items()):
                self._unreached[name] = {key for key in keys if Path(key).is_file()}  # gone since: nothing to try
        if not any(list(self._unreached.values())):
            return False
        try:
            self.ollama.list_models()
        except Exception:  # noqa: BLE001 - still out of reach: tried again later
            return False
        return True

    def _set_now(self, agent: store.Agent, path: Path, index: int = 0, of: int = 0) -> None:
        self._now[agent.name] = {"file": path.name, "index": index, "of": of}
        if not self._showing_work:  # a big download that has finally arrived: the circle had rested
            self._showing_work = True
            self._tell(self.working, True)
        self._tell(self.changed)

    def _clear_now(self, agent: store.Agent) -> None:
        if self._now.pop(agent.name, None) is not None:
            self._rest_if_idle()
            self._tell(self.changed)

    def status(self, name: str) -> str:
        """What a card is doing this very moment, in one plain line, or "" when it is only
        watching: for the chores lists, so the user can tell it is alive and at what."""
        agent = self.active.get(name)
        if agent is None:
            return ""
        # A card that goes by names alone never reads a file, and its lines never say it
        # does: someone who chose names because their files must not be read was told
        # "Reading ... now" while it worked.
        by_name = _by_name(agent)
        now = self._now.get(name)
        if now:
            count = f" ({now['index']} of {now['of']})" if now.get("of", 0) > 1 else ""
            return f"{'Looking at the name of' if by_name else 'Reading'} {now['file']} now{count}"
        landing = list(self._landing.get(name, {}).values())
        coming = [held for held in landing if not held.get("waiting")]
        if coming:
            more = f" and {len(coming) - 1} more" if len(coming) > 1 else ""
            if by_name:
                names = "its name" if len(coming) == 1 else "their names"
                return f"{coming[0]['name']}{more} just landed: looking at {names} in a moment"
            return f"{coming[0]['name']}{more} just landed: reading {'it' if len(coming) == 1 else 'them'} in a moment"
        if landing:
            more = f" and {len(landing) - 1} more" if len(landing) > 1 else ""
            then = "get to it" if by_name else "read it"
            if landing[0].get("waiting") == IN_USE:
                return f"{landing[0]['name']}{more} is open in another program: I'll {then} once it's free"
            return f"{landing[0]['name']}{more} is still arriving: I'll {then} once it's whole"
        return ""

    def doing(self) -> str:
        """The one thing being done right now across every card, as a sentence with the
        agent's name, or "": what the windows show where they show work in progress."""
        for name in list(self.active):
            line = self.status(name)
            if line and (self._now.get(name) or any(not held.get("waiting")
                                                    for held in list(self._landing.get(name, {}).values()))):
                return f"{name}: {line[:1].lower()}{line[1:]}"
        return ""

    def _tell(self, callback: Callable, *args) -> None:
        """A window's callback, which must never break the watching."""
        try:
            callback(*args)
        except Exception:  # noqa: BLE001
            pass

    def _note(self, step: str) -> None:
        """One line of the log about the file in hand."""
        self._steps.append(step)

    def files(self, agent: store.Agent, settled: bool = True, away: bool = False) -> list[Path]:
        """The files loose in the watched folder: every kind, not hidden, not one Windows
        keeps for itself, not a download still arriving, not one kept only in the cloud, and
        (settled) not changed in the last while.

        A file kept only in the cloud (one of OneDrive's that is not on this computer, and
        Desktop and Documents are often OneDrive's) is left alone until it is here, as
        tidy.loose_files has always left it: reading one makes OneDrive download it, and
        moving it out of the OneDrive folder takes it out of the cloud copy, so the user's
        other devices lose it. `away`: those files as well. They are there all the same,
        and the list of what was there when a card was switched on has them, so one brought
        down to this computer later is not taken for a file that just landed."""
        if not agent.slots.get("folder"):
            return []  # no folder chosen: an empty name would be read as the folder the app runs in
        folder = Path(agent.slots["folder"])
        # A notes file is never a file to handle, for the card that writes it or any other:
        # one once got moved into a folder for the document it had been written about.
        notes = {parts.notes_path(a.slots) for a in [*list(self.active.values()), agent]
                 if parts.then_of(a.slots) == parts.NOTE}
        found = []
        try:
            # One listing, with what the folder already knows of each entry: this runs every
            # couple of seconds, and asking the disk about each of a few hundred files again
            # would be most of its cost.
            with os.scandir(folder) as entries:
                for entry in entries:
                    name = entry.name
                    if name.startswith(".") or name.lower() in SYSTEM_FILES or Path(name).suffix.lower() in UNFINISHED:
                        continue
                    try:
                        if not entry.is_file():
                            continue
                        # On Windows what the listing knew already: asking it opens nothing, so
                        # a file kept only in the cloud is not brought down by being asked about.
                        # Elsewhere it is one more call to the disk for each file, and there are
                        # no such marks to read.
                        info = entry.stat() if settled or os.name == "nt" else None
                        marks = getattr(info, "st_file_attributes", 0)
                        if marks & WINDOWS_OWN or (marks & CLOUD_ONLY and not away):
                            continue
                        if settled and self._clock() - info.st_mtime < self._settle_seconds:
                            continue
                    except OSError:
                        continue
                    path = folder / entry.name
                    if path not in notes:
                        found.append(path)
        except OSError:
            return []
        return sorted(found)

    def new_files(self, agent: store.Agent, settled: bool = True) -> list[Path]:
        """Files that landed after it was switched on and haven't been judged."""
        seen = self._seen.setdefault(agent.name, set())
        return [path for path in self.files(agent, settled) if str(path) not in seen]

    def count_files(self, agent: store.Agent) -> int:
        return len(self.files(agent, settled=False))

    def run_once(self, agent: store.Agent, everything: bool = False, only: list[Path] | None = None) -> Iterator[str | dict]:
        """Go through the folder now: what has landed since it was switched on, (everything)
        all of it, the first pass the user is asked about, or (only) the files named, looked
        at again whatever was decided before. Yields what it is doing, then the outcome:
        {"moved", "where": [{"folder", "count"}], "left", "why", "id", "looked", "already"}."""
        moved: list[dict] = []
        left: list[str] = []  # why each file that stayed did
        already = 0  # files the look that runs on its own dealt with while this pass was on its way to them
        # Listed behind the work lock, so a file the look on its own has in hand this second is
        # finished and counted before the pass decides there is nothing new. Without the wait,
        # a pass asked for in the chat answered "nothing new has landed" while a file was being
        # read right then.
        with self._work:
            if only is not None:
                files = [path for path in only if path.is_file()]
            else:
                files = self.files(agent, settled=False) if everything else self.new_files(agent, settled=False)
        self._passing += 1
        self._showing_work = True
        self._tell(self.working, True)
        sort_id = ""
        try:
            for index, path in enumerate(files, 1):
                yield f"{'Looking at the name of' if _by_name(agent) else 'Reading'} {path.name} ({index} of {len(files)})..."
                with self._work:
                    seen = self._seen.setdefault(agent.name, set())
                    if not path.is_file() or (only is None and not everything and str(path) in seen):
                        already += 1
                        continue
                    if only is not None:  # looked at again, whatever was decided before
                        kept = self.skipped.get(agent.name, [])
                        kept[:] = [item for item in kept if item["name"] != path.name]
                    self._notes_first(agent, path)
                    seen.add(str(path))  # before it is read, so the look on its own never takes it too
                    self._set_now(agent, path, index, len(files))
                    try:
                        move = self._file(agent, path, record=False)
                    except Exception as exc:  # noqa: BLE001 - one odd file must not end the pass
                        import traceback

                        traceback.print_exc()
                        self._skip(agent, path, f"something went wrong reading it ({type(exc).__name__})")
                        move = None
                    finally:
                        # In this order, or the lists show "just landed" again for a blink
                        # between the file being read and being done with.
                        self._landed_done(agent, path)
                        self._clear_now(agent)
                if move:
                    moved.append(move)
                else:
                    kept = self.skipped.get(agent.name, [])
                    why = kept[-1]["why"] if kept and kept[-1]["name"] == path.name else NOT_MOVED
                    # Counted by the reason alone, without what each file was taken for, or a
                    # pass over sixty files would give sixty reasons.
                    left.append(why.partition(": ")[0])
        finally:
            self._passing = max(0, self._passing - 1)
            self._rest_if_idle()
            self._release_helper()
            # Written down here, so it is written even when the pass is cut short: the files
            # of a pass are moved without a record each, and a move with no record can't be
            # undone.
            sort_id = self._record_pass(agent, moved)
            if files:
                self._write_state()
            self._tell(self.changed)
        reasons = [{"why": why, "count": left.count(why)} for why in dict.fromkeys(left)]
        yield {"moved": len(moved), "where": self._where(moved), "left": len(left), "why": reasons, "id": sort_id,
               "looked": len(files), "already": already}

    def _record_pass(self, agent: store.Agent, moved: list[dict]) -> str:
        """One line in the done list for a whole pass, and its moves in the log as one job
        that can be undone. Returns that job's id ("" when nothing moved, and for notes)."""
        if not moved:
            return ""
        folder = Path(agent.slots.get("folder", "")).name
        plural = "" if len(moved) == 1 else "s"
        if parts.then_of(agent.slots) == parts.NOTE:
            self._remember(f"Wrote about {len(moved)} file{plural} from {folder}", f"in {Path(moved[0]['to']).name}",
                           "", agent.name, where=moved[0]["to"])
            return ""
        sort_id = record_moves(self.log, moved, agent=agent.name)
        self._remember(f"Moved {len(moved)} file{plural} from {folder}",
                       " · ".join(f"{w['folder']} {w['count']}" for w in self._where(moved)), sort_id, agent.name)
        return sort_id

    def place(self, agent: store.Agent, path: Path, folder: str) -> dict | None:
        """A move the user ordered ("put this file in that folder"): into that folder, made
        if need be, and kept with the card as an example, which the built-in model is shown
        for later files. Returns the move, or None when there was nothing to move."""
        named = parts.choices_of({"choices": [re.sub(r"[,;\n]+", " ", folder)]})  # a list of folders is kept with commas
        with self._work:  # never while the look on its own has that very file in hand
            if not named or not path.is_file() or parts.then_of(agent.slots) != parts.MOVE:
                return None
            # The folder they mean, when the card has it already under a name written another way.
            folder = parts.same_folder(named[0], parts.choices_of(agent.slots)) or named[0]
            self._notes_first(agent, path)
            self._steps = [f"You said to put {path.name} in {folder}"]
            move = self._move(agent, path, folder, record=True, tell=False)
            if move:
                self._learn(agent, folder, example=path.name)
                with self._lock:
                    kept = self.skipped.get(agent.name, [])
                    kept[:] = [item for item in kept if item["name"] != path.name]
            self._seen.setdefault(agent.name, set()).add(str(path))
            self._landed_done(agent, path)
            self._release_helper()
            self._write_state()
        self._tell(self.changed)
        return move

    # ------------------------------------------------------------ one file

    def _file(self, agent: store.Agent, path: Path, record: bool = True) -> dict | None:
        """Do the card's job on one file. Returns what it did (a move, or where a note
        went), or None when nothing was done: the rule leaves the file, the model wasn't
        sure, or nothing could be read. Why is kept on record either way."""
        self._steps = [f"Noticed {path.name} in {path.parent.name}"]
        writes = parts.then_of(agent.slots) == parts.NOTE
        unreached = self._unreached.setdefault(agent.name, set())
        again = str(path) in unreached  # tried before, when the model couldn't be reached
        if again:
            unreached.discard(str(path))
            kept = self.skipped.get(agent.name, [])
            kept[:] = [item for item in kept if item["name"] != path.name]  # that is no longer why
        verdict = self._decide(agent, self.item(agent, path))
        why = verdict["why"]
        if verdict["note"]:
            done = self._write(agent, path, verdict["note"], record)
            if done:
                return done
            why = NOTES_NOT_WRITTEN
        elif verdict["choice"] and _already_there(agent, path, verdict["choice"]):
            why = ALREADY_THERE
        elif verdict["choice"]:
            done = self._move(agent, path, verdict["choice"], record)
            if done:
                if verdict["new"]:
                    self._learn(agent, verdict["choice"])  # a folder the rule called for is one of its folders now
                return done
            why = NOT_MOVED
        self._note(f"Wrote nothing: {why}" if writes else f"Stayed in {path.parent.name}: {why}")
        self._skip(agent, path, why)
        if why == NO_MODEL:
            unreached.add(str(path))
            self._seen.get(agent.name, set()).discard(str(path))  # tried again, not left for good
            self._retry_at = max(self._retry_at, self._clock() + RETRY_SECONDS)
        # A card that writes notes never moves a file, so "it stayed" is no news of its: the
        # reason is on record, and the small log by the circle is not told. Nor is it told
        # twice that the model couldn't be reached about the same file.
        if record and not writes and not (again and why == NO_MODEL):
            self._tell(self.stayed, {"name": path.name, "where": str(path.parent), "why": why, "steps": list(self._steps)})
        return None

    def item(self, agent: store.Agent, path: Path) -> worker.Item:
        """One file as the built-in model is given it: its name, and the beginning of what
        could be read of it. With a card that goes by names alone, nothing inside is looked
        at."""
        if agent.slots.get("looks_at") == parts.NAME_ONLY:
            self._note("Went by its name alone")
            return worker.Item(path.name, "", how="its name only", name_only=True)
        suffix = path.suffix.lower()
        if suffix in NOTHING_TO_READ:
            self._note("A program or a recording: nothing inside to read")
            return worker.Item(path.name, "")
        text = self._text(path)
        how = ""
        if text and suffix in IMAGES:
            how = f"a picture: read {self._seen_how()}"
        elif text and self._steps and self._steps[-1].startswith("A scanned page: read"):
            how = f"a scanned page: read {self._seen_how()}"
        return worker.Item(path.name, text, how=how)

    def _decide(self, agent: store.Agent, item: worker.Item, choices: list[str] | None = None) -> dict:
        """What the card's rule makes of one file, with nothing done about it yet:
        {"what" (what the model took it for), "choice" (the folder it goes into, "" when it
        stays), "new" (that folder is not one of the card's yet), "why" (when nothing is
        done, the reason as the record says it), "note" (what would be written about it)}.
        `choices`: the folders to choose among when they are not the card's own (a try-out
        keeps the ones it would have made by then)."""
        slots = agent.slots
        verdict = {"what": "", "choice": "", "new": False, "why": "", "note": ""}
        if not item.name_only and not item.text.strip():
            # Nothing was read, so nothing is put to the model: judged by a name alone, a file
            # it could not read was once taken for something it was not.
            return {**verdict, "why": NO_TEXT}
        rule = str(slots.get("instruction") or "").strip()
        if not rule:
            return {**verdict, "why": NO_RULE}
        then = parts.then_of(slots)
        known = parts.choices_of(slots)
        self._failure = ""
        if then == parts.NOTE:
            outcome = worker.write_note(self._ask, rule, item)
        elif then == parts.MOVE:
            outcome = worker.choose(self._ask, rule, known if choices is None else choices, item,
                                    open=slots.get("open") == parts.OPEN_YES, examples=slots.get("examples") or ())
        else:
            return {**verdict, "why": NOTHING_TO_DO}
        if outcome is None:
            why = self._failure or NO_MODEL
            self._note("The built-in model couldn't be reached" if why == NO_MODEL else
                       "The built-in model gave no answer it could use")
            return {**verdict, "why": why}
        verdict["what"] = outcome.what
        if outcome.what:
            self._note(f"Read it as: {outcome.what}")
        if then == parts.NOTE:
            if outcome.text:
                return {**verdict, "note": outcome.text}
            return {**verdict, "why": _said(NOTHING_ASKED, outcome.what)}
        if outcome.choice == worker.LEAVE:
            return {**verdict, "why": _said(LEFT_BY_RULE, outcome.what)}
        if outcome.choice in ("", worker.UNSURE):
            return {**verdict, "why": _said(NOT_SURE_WHERE, outcome.what)}
        new = outcome.choice not in known
        self._note(f"{DECIDED} {outcome.choice}" + (", a new folder" if new else ""))
        return {**verdict, "choice": outcome.choice, "new": new}

    def _write(self, agent: store.Agent, path: Path, note: str, record: bool = True) -> dict | None:
        """Add what the rule asked for about one file to the end of the card's notes file,
        under the file's name and the time. Returns where it went, or None when the notes
        file couldn't be written."""
        notes = parts.notes_path(agent.slots)
        try:
            notes.parent.mkdir(parents=True, exist_ok=True)
            with notes.open("a", encoding="utf-8") as out:
                out.write(f"## {path.name} · {time.strftime('%Y-%m-%d %H:%M', time.localtime(self._clock()))}\n"
                          f"{note}\n\n")
        except OSError:
            return None
        done = {"from": str(path), "to": str(notes)}
        self._note(f"Wrote about it in {notes.name}")
        if record:
            text = f"Wrote about {path.name} in {notes.name}"
            self._remember(text, f"from {path.parent.name}", "", agent.name, where=str(notes))
            self._tell(self.moved, {"name": path.name, "folder": notes.name, "to": str(notes), "sort": "",
                                    "steps": list(self._steps), "text": text})
        return done

    def _skip(self, agent: store.Agent, path: Path, why: str) -> None:
        kept = self.skipped.setdefault(agent.name, [])
        kept[:] = [item for item in kept if item["name"] != path.name]
        kept.append({"name": path.name, "where": str(path.parent), "why": why, "when": self._clock()})
        del kept[:-SKIPPED_KEPT]

    def _move(self, agent: store.Agent, path: Path, folder: str, record: bool = True, tell: bool = True) -> dict | None:
        """Move one file into its folder. Returns the move, or None when it couldn't be moved."""
        if not (agent.slots.get("into") or agent.slots.get("folder")):
            return None  # no place of its own: a folder is never made wherever the app happens to run
        if _already_there(agent, path, folder):
            return None  # it would only be given a new name where it is
        into = parts.destination(agent.slots) / folder
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
        self._note(f"Put it in {shown_folder(agent, folder)}")
        if record:
            sort_id = record_moves(self.log, [move], agent=agent.name)
            decided = next((step for step in self._steps if step.startswith(DECIDED)), "")
            text = f"Put {path.name} in {shown_folder(agent, folder)}"
            self._remember(text, f"from {path.parent.name}" + (f" · {decided}" if decided else ""),
                           sort_id, agent.name, where=str(target.parent))
            if tell:
                self._tell(self.moved, {"name": path.name, "folder": shown_folder(agent, folder), "to": str(target.parent),
                                        "sort": sort_id, "steps": list(self._steps), "text": text})
        return move

    def _learn(self, agent: store.Agent, folder: str, example: str = "") -> None:
        """A folder joins the card's own list when it isn't on it yet, and (example) a file
        the user placed there by hand is kept as an example, newest last. Saved with the
        agent, so both are there after a restart.

        Learned onto the card as it is saved now, and onto the one that is switched on,
        never saved from the copy the caller holds. A look works with the card it took
        before the file was read, and a card can be changed in the chat while one of its
        files is in hand: saved from that copy, the change the user had just made was
        written over with the old card plus one folder, and the old card was put back
        here in place of the changed one. A card that is no longer saved was deleted a
        moment ago, and is not written back."""
        try:
            saved = store.find_agent(agent.name)
        except Exception:  # noqa: BLE001 - the saved agents can't be read: it is known for as long as the app runs
            saved = None
        cards = [agent]
        for other in (self.active.get(agent.name), saved):
            if other is not None and all(other is not card for card in cards):
                cards.append(other)
        for card in cards:
            # Only a card that still moves files has folders to learn.
            learned = parts.then_of(card.slots) == parts.MOVE and self._taught(card.slots, folder, example)
            if learned and card is saved:
                try:
                    store.save(saved)
                except OSError:
                    pass  # it can't be saved: it is known for as long as the app runs

    @staticmethod
    def _taught(slots: dict, folder: str, example: str) -> bool:
        """Put a folder, and a file placed there by hand, into one card's slots. Returns
        whether anything was new to it."""
        known = parts.choices_of(slots)
        learned = False
        if folder not in known:
            slots["choices"] = ", ".join([*known, folder])
            learned = True
        if example:
            told = [one for one in (slots.get("examples") or []) if isinstance(one, dict) and one.get("name") != example]
            slots["examples"] = [*told, {"name": example, "choice": folder}][-parts.MAX_EXAMPLES:]
            learned = True
        return learned

    # ------------------------------------------------------------- a try-out

    def rehearse(self, agent: store.Agent, limit: int = REHEARSE_FILES) -> list[dict]:
        """A dry run, for a card still being worked out: what it would do with the newest
        files now in its folder, newest first, with nothing moved, written, counted as seen,
        put on record or told to the windows. The agent need not be saved or switched on.
        Each row: {"name", "ending", "what", "choice" (the folder, "" when it stays), "new",
        "why" (when it stays, as the record would say it), "note" (the beginning of what it
        would write)}."""
        rows: list[tuple[float, dict]] = []
        with self._work:  # the model answers one thing at a time, and a file in hand is finished first
            steps = self._steps
            try:
                newest = []
                for path in self.files(agent, settled=False):
                    try:
                        newest.append((path.stat().st_mtime, path))
                    except OSError:
                        continue
                newest.sort(key=lambda found: found[0], reverse=True)
                # The files that can be read are what a try-out is for; one that can't is only
                # shown when there is room left, so a folder of programs still says something.
                readable, unread = [], []
                for when, path in newest[:max(limit, REHEARSE_OPENED)]:
                    if len(readable) >= limit:
                        break
                    self._steps = []
                    try:
                        item = self.item(agent, path)
                    except Exception:  # noqa: BLE001 - one odd file must not end the try-out
                        item = worker.Item(path.name, "")
                    (readable if item.name_only or item.text.strip() else unread).append((when, path, item))
                tried = [*readable, *unread][:max(0, limit)]
                # Judged oldest first, the way they landed, with the folders it would have made
                # by then: a second file for a new folder goes into that folder, as it would.
                choices = parts.choices_of(agent.slots)
                for when, path, item in sorted(tried, key=lambda found: found[0]):
                    self._steps = []
                    try:
                        verdict = self._decide(agent, item, choices)
                    except Exception as exc:  # noqa: BLE001
                        verdict = {"what": "", "choice": "", "new": False, "note": "",
                                   "why": f"something went wrong reading it ({type(exc).__name__})"}
                    if verdict["choice"] and verdict["choice"] not in choices:
                        choices = [*choices, verdict["choice"]]
                    rows.append((when, {"name": path.name, "ending": path.suffix.lower(), "what": verdict["what"],
                                        "choice": verdict["choice"], "new": verdict["new"], "why": verdict["why"],
                                        "note": verdict["note"][:REHEARSE_NOTE_CHARS]}))
            finally:
                self._steps = steps
                self._release_helper()
        return [row for _, row in sorted(rows, key=lambda found: found[0], reverse=True)]

    # ------------------------------------------------------- reading a file

    def seer(self) -> str:
        """The model that can see pictures, if any: Noir's own when it can, since it is in
        memory already; else the catalog's vision helper, else any installed model Ollama
        says has vision. Looked for once per run. The helper used to come first: 8.1 GB
        beside Noir's 3.9, loaded for two pictures and left there, which with the desktop's
        own share filled 15 of the card's 16 GB. Its own 4B model read the same pictures as
        well, in half a second each."""
        if self._vision_checked:
            return self.vision
        self._vision_checked = True
        try:
            if "vision" in self.ollama.capabilities(self.model):
                self.vision = self.model
                return self.vision
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
        messages = [{"role": "user", "content": SEE_NOTE, "images": [base64.b64encode(shrink(picture)).decode()]}]
        try:
            if tag == self.model:
                # Its own model, as it is loaded: asked for another amount of room, Ollama
                # would load it a second time.
                reply = self.ollama.chat_json(tag, messages, SEE_SCHEMA, think=False, keep_alive=KEEP_ALIVE)
            else:
                self._helper_seen = True
                reply = self.ollama.chat_json(tag, messages, SEE_SCHEMA, think=False, keep_alive=SEE_KEEP_ALIVE,
                                              options={"num_ctx": SEE_CONTEXT})
        except OllamaError:
            return ""
        words = re.sub(r"\s+", " ", str((reply or {}).get("words", ""))).strip()
        what = str((reply or {}).get("what", "")).strip()
        if not words and not what:
            return ""
        return "A picture." + (f" The words in it: {words}." if words else " No words in it.") + (f" What it shows: {what}" if what else "")

    def _release_helper(self) -> None:
        """A helper model that was loaded to see pictures leaves the graphics memory as soon
        as the look or the pass is over, not five minutes later."""
        if not self._helper_seen:
            return
        self._helper_seen = False
        try:
            self.ollama.unload(self.vision)
        except Exception:  # noqa: BLE001 - Ollama busy or gone: it leaves by itself after SEE_KEEP_ALIVE
            pass

    def _scanned(self, path: Path) -> str:
        """A PDF with no text is a scan: its first page's picture is looked at instead."""
        try:
            from pypdf import PdfReader

            for image in PdfReader(str(path)).pages[0].images:
                return self._see(image.data)
        except Exception:  # noqa: BLE001 - whatever pypdf finds odd in a scan: it stays unread
            pass
        return ""

    def _ask(self, system: str, content: str, schema: dict) -> dict | None:
        """One form put to the built-in model (worker.Ask). None when it can't be reached, or
        what it gave back was no form, with which of the two in `_failure`."""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        try:
            # With its own stay, like a chat answer: left to Ollama's five minutes, the model
            # sat in the graphics memory that long after every file.
            return self.ollama.chat_json(self.model, messages, schema, think=False, keep_alive=KEEP_ALIVE)
        except OllamaError as exc:
            # A reply that can't be read as the form (Ollama.chat_json raises that from the
            # ValueError) is not tried again: the same file gives the same reply.
            self._failure = NO_ANSWER if isinstance(exc.__cause__, ValueError) else NO_MODEL
            return None

    def _seen_how(self) -> str:
        return "with the built-in model" if self.vision == self.model else f"through {self.vision}"

    def _text(self, path: Path) -> str:
        """What can be read of a file: its words, a picture's description, a zip's contents."""
        suffix = path.suffix.lower()
        if suffix in IMAGES:
            try:
                # Its size first: a picture too big to show is not read into memory to find that out.
                too_big = path.stat().st_size > MAX_IMAGE_MB * 1024 * 1024
                seen = "" if too_big else self._see(path.read_bytes())[:READ_CHARS]
            except OSError:
                too_big, seen = False, ""
            # Why a picture gave nothing is said as it was. "No model here that can see it"
            # used to be said of every one, also with such a model installed, when the
            # picture was too big for it or the look had failed.
            self._note(f"Looked at the picture {self._seen_how()}" if seen else
                       "A picture, and no model here that can see it" if not self.seer() else
                       "A picture too big to look at" if too_big else
                       "A picture, and it couldn't be looked at just now")
            return seen
        text = ""
        try:
            for _, piece in self._read(path):
                text += piece[:PIECE_CHARS] + "\n"
                if len(text) >= READ_CHARS:
                    break
        except Exception:  # noqa: BLE001 - a broken file of any kind reads as nothing more than was read before it broke
            pass
        text = re.sub(r"[ \t]+", " ", text).strip()[:READ_CHARS]
        if not text and suffix == ".pdf":
            text = self._scanned(path)[:READ_CHARS]
            self._note(f"A scanned page: read it {self._seen_how()}" if text else "A scanned page, and nothing could be read from it")
        elif text:
            self._note("Read its first pages" if suffix in (".pdf", ".docx") else
                       "Read the names of the files inside" if text.startswith("Files inside:") else "Read its first lines")
        else:
            self._note("Nothing inside could be read")
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
        self._tell(self.changed)

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
        """Put one job's files back. 0 when the id isn't one of the jobs on record here.

        Behind the work lock, since Undo is clicked on the window's thread while the look
        may be moving a file: both write the same move log, and a move written down in the
        middle of an Undo was written over, so it could never be undone. A file put back
        is then seen by every card that watches the folder it went back to. It was only
        left alone while it was still on a card's list of files seen, and a card switched
        off and on again, renamed or pointed at another folder makes that list again from
        what is there at that moment: the file put back was moved again at the next look."""
        with self._work:
            sort = next((one for one in sorts_on_record(self.log) if sort_id and one["id"] == sort_id), None)
            if sort is None:
                return 0
            # The files that will go back are the ones undo_sort puts back: still where they
            # were moved to, and nothing in their old place. Another file of the same name
            # that landed there since is not one of them, and stays new.
            going = [Path(move["from"]) for move in sort.get("moves", [])
                     if Path(move["to"]).is_file() and not Path(move["from"]).exists()]
            back = undo_sort(self.log, sort_id)
            returned = {path for path in going if path.is_file()}
            with self._lock:
                for name, agent in self.active.items():
                    folder = agent.slots.get("folder")
                    for path in returned:
                        if folder and path.parent == Path(folder):
                            self._seen.setdefault(name, set()).add(str(path))
            if returned:
                self._write_state()
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
        return self.done_path.with_name(STATE_NAME)

    def _take_over_old_files(self) -> None:
        """The move log, the done list and the state file under the names they had before
        are renamed, each once and only when there is no new one yet."""
        for old, new in ((OLD_LOG, self.log), (OLD_DONE, self.done_path), (OLD_STATE, self._state_path())):
            before = new.with_name(old)
            try:
                if before != new and before.is_file() and not new.exists():
                    before.rename(new)
                    if old == OLD_STATE:
                        self._drop_old_reasons()
            except OSError:
                pass  # it can't be renamed: this starts with nothing rather than not starting

    def _drop_old_reasons(self) -> None:
        """The state file just taken over says why files stayed in the words of what ran
        before: some waited for an answer nobody is asked for any more, and all were given
        by a way of judging that is gone. Told to the user as the reason today they would
        be untrue, so they are not taken over. The rest of the file stays as it is."""
        try:
            state = json.loads(self._state_path().read_text(encoding="utf-8"))
            if isinstance(state, dict) and state.pop("skipped", None):
                self._state_path().write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        except (OSError, ValueError):
            pass

    def _state(self) -> dict:
        """The state file as it is on disk now: {} when there is none or it can't be read."""
        try:
            state = json.loads(self._state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return state if isinstance(state, dict) else {}

    def _read_state(self) -> None:
        """What was kept from the last run, read once, when this is made. It used to be
        read again at every refresh, putting what was on disk in place of what this run
        knew. Why a file stayed is written to disk at the end of a look or a pass, and a
        refresh comes whenever an agent is made, changed or switched, so one that came
        while files were in hand threw away the reasons recorded since the last write:
        those files stayed seen, and "why didn't you move it" had no answer. Anything
        else an older version wrote in the file is left unread, and is gone at the next
        write."""
        state = self._state()
        try:
            made = {name: list(folders) for name, folders in state.get("made", {}).items()}
            seen = {name: set(paths) for name, paths in state.get("seen", {}).items()}
            skipped = {name: list(items) for name, items in state.get("skipped", {}).items()}
            since = {name: float(when) for name, when in state.get("since", {}).items()}
        except (ValueError, AttributeError, TypeError):
            return
        self.made, self._seen_before, self.skipped = made, seen, skipped
        self.since.update(since)

    def _write_state(self) -> None:
        try:
            self._state_path().parent.mkdir(parents=True, exist_ok=True)
            seen = {name: self._seen_to_keep(name, paths) for name, paths in self._seen.items() if name in self.active}
            self._state_path().write_text(json.dumps({"on": list(self.active), "made": self.made, "seen": seen,
                                                      "skipped": self.skipped, "since": self.since},
                                                     ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _seen_to_keep(self, name: str, paths: set[str]) -> list[str]:
        """The paths written down as seen for one card: all of them while they are few.
        Past SEEN_KEPT, every one that is still a file in the watched folder is kept, and
        of the rest (files moved away or deleted since) only as many as still fit. They
        used to be cut by alphabet whatever they were, so in a folder with more loose
        files than SEEN_KEPT the first of them by name were missing after a restart, and
        files that had been there before the card was switched on were handled as new."""
        if len(paths) <= SEEN_KEPT:
            return sorted(paths)
        agent = self.active.get(name)
        here = {str(path) for path in self.files(agent, settled=False, away=True)} & paths if agent else set()
        gone = sorted(paths - here)
        return sorted(here) + (gone[len(here) - SEEN_KEPT:] if len(here) < SEEN_KEPT else [])
