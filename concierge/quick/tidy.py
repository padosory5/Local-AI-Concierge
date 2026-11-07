"""Noir notices what could help, asks once, and does the job.

A messy Downloads folder is the first such job, and a lecture on the screen the
second, though summarizing one is not built yet.

Everything here is plain code with no model involved: code can count files and
read a window's title, and it does so without holding any graphics memory.
Nothing is ever deleted or overwritten, and every sort can be undone for a week.

It only notices anything after the user says yes once, and it asks at a break
between tasks, right after they switch to another window, never just because
they stopped typing: a pause is usually someone thinking. Research on helpers
that speak up found that asking sooner and more often turned most people against
them, so there are hours between questions, and every answer is counted, so
the questions people keep saying no to can be found and dropped.
"""

from __future__ import annotations

import ctypes
import json
import sys
import threading
import time
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from ..noir import data_dir

MIN_FILES = 30  # fewer loose files than this isn't a mess worth interrupting for
SETTLE_SECONDS = 600  # a file newer than this may still be downloading
FIRST_LOOK_SECONDS, LOOK_SECONDS = 120, 1800
SNOOZE_DAYS = 7  # after "Not now"
IGNORED_DAYS = 1  # after the question goes away unanswered
BREAK_SECONDS = 20  # a window switch this recent counts as a break between tasks
TYPING_GAP_SECONDS = 1.5  # and the user isn't in the middle of typing
MIN_JOB_SECONDS = 3.5  # even an instant job shows both lights, one after the other
PRACTICE_FIRST_LOOK_SECONDS, PRACTICE_JOB_SECONDS = 6, 5
VIDEO_LOOK_SECONDS, PRACTICE_VIDEO_SECONDS = 15, 3
QUESTION_GAP_SECONDS = 3 * 3600  # between one answer and the next question
PRACTICE_QUESTION_GAP_SECONDS = 4
UNDO_DAYS = 7  # how long a sort can still be undone
# Summarizing lectures isn't built, so the lecture question is only asked in the
# practice run: asking for a Yes that does nothing spends an interruption on nothing.
LECTURE_NOTES_BUILT = False
# Files OneDrive and similar keep only in the cloud. Moving one can make Windows
# fetch it or lose the link to it, so they are never touched.
CLOUD_ONLY = 0x1000 | 0x40000 | 0x400000
YES, NOT_NOW = "Yes", "No"
SORT, VIDEO = "sort", "video"  # which question an answer is for
VIDEO_QUESTION = "Video summarize?"
NO_VIDEO_SUMMARY = "I can't summarize videos yet. That agent isn't built."
PRACTICE_LECTURE = "Practice lecture"
DONE_KEPT = 100  # finished jobs remembered for Today

SHELVES = {
    "Pictures": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".svg", ".tif", ".tiff"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".md", ".hwp", ".hwpx", ".ppt", ".pptx",
                  ".xls", ".xlsx", ".csv"},
    "Videos": {".mp4", ".mov", ".mkv", ".avi", ".webm", ".wmv"},
    "Music": {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Installers": {".exe", ".msi", ".msix"},
}
OTHER_SHELF = "Other"
# Files a browser is still writing, and files Windows keeps for itself.
UNFINISHED = {".crdownload", ".part", ".partial", ".download", ".tmp", ".opdownload"}
SYSTEM_FILES = {"desktop.ini", "thumbs.db"}


def downloads_dir() -> Path:
    return Path.home() / "Downloads"


def log_path() -> Path:
    path = data_dir() / "sorts.json"
    earlier = data_dir() / "last_sort.json"  # where an earlier version kept its one sort
    if earlier.is_file() and not path.exists():
        earlier.rename(path)
    return path


def shelf_for(path: Path) -> str:
    ending = path.suffix.lower()
    return next((name for name, endings in SHELVES.items() if ending in endings), OTHER_SHELF)


def loose_files(folder: Path, now: float | None = None) -> list[Path]:
    """Finished files sitting directly in the folder, not in a folder of their own."""
    now = time.time() if now is None else now
    try:
        entries = list(folder.iterdir())
    except OSError:
        return []
    found = []
    for path in entries:
        try:
            info = path.stat()
            if (path.is_file() and not path.name.startswith(".")
                    and path.name.lower() not in SYSTEM_FILES and path.suffix.lower() not in UNFINISHED
                    and not getattr(info, "st_file_attributes", 0) & CLOUD_ONLY
                    and now - info.st_mtime >= SETTLE_SECONDS):
                found.append(path)
        except OSError:
            continue  # it disappeared or can't be read: leave it alone
    return found


def free_name(target: Path) -> Path:
    """target, or "name (2).ext" if that name is taken: nothing is ever overwritten."""
    candidate, number = target, 2
    while candidate.exists():
        candidate = target.with_name(f"{target.stem} ({number}){target.suffix}")
        number += 1
    return candidate


def sort_plan(folder: Path, now: float | None = None) -> list[dict]:
    """Where the loose files would go, before anything moves: shelf and count, biggest first."""
    counts: dict[str, int] = {}
    for path in loose_files(folder, now):
        counts[shelf_for(path)] = counts.get(shelf_for(path), 0) + 1
    return [{"shelf": shelf, "count": count} for shelf, count in sorted(counts.items(), key=lambda item: -item[1])]


def _sorts(log: Path, now: float | None = None) -> list[dict]:
    """The sorts that can still be undone, oldest first."""
    now = time.time() if now is None else now
    try:
        saved = json.loads(log.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if saved and "from" in saved[0]:  # one sort saved by an earlier version
        saved = [{"id": "earlier", "when": log.stat().st_mtime, "moves": saved}]
    return [sort for sort in saved if now - sort["when"] < UNDO_DAYS * 86400]


def _keep(log: Path, sorts: list[dict]) -> None:
    if sorts:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(json.dumps(sorts, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        log.unlink(missing_ok=True)


def sort_folder(folder: Path, log: Path, now: float | None = None) -> int:
    """Move each loose file onto its shelf and remember how, for undo_sort.
    A file that can't be moved, because a program has it open, stays put, and
    a move counts only once the file is really in its new place."""
    moved = []
    try:
        for path in loose_files(folder, now):
            shelf = folder / shelf_for(path)
            try:
                shelf.mkdir(exist_ok=True)
                target = free_name(shelf / path.name)
                path.rename(target)
                if target.is_file():
                    moved.append({"from": str(path), "to": str(target)})
            except OSError:
                continue
    finally:
        # Saved even if something went wrong halfway, so what moved can go back.
        if moved:
            when = time.time()
            _keep(log, [*_sorts(log), {"id": str(int(when * 1000)), "when": when, "moves": moved}])
    return len(moved)


def last_sort(log: Path) -> dict | None:
    sorts = _sorts(log)
    return sorts[-1] if sorts else None


def moved_to(sort: dict) -> list[dict]:
    """Where the files of one sort went: shelf and count, biggest first."""
    counts: dict[str, int] = {}
    for move in sort["moves"]:
        shelf = Path(move["to"]).parent.name
        counts[shelf] = counts.get(shelf, 0) + 1
    return [{"shelf": shelf, "count": count} for shelf, count in sorted(counts.items(), key=lambda item: -item[1])]


def can_undo(log: Path, id: str | None = None) -> bool:
    return any(id is None or sort["id"] == id for sort in _sorts(log))


def undo_sort(log: Path, id: str | None = None) -> int:
    """Put the files of one sort back, the newest if no id is given. A file the
    user has since moved or deleted is left as it is, and a file now in the way
    keeps its place."""
    sorts = _sorts(log)
    sort = next((one for one in reversed(sorts) if id is None or one["id"] == id), None)
    if sort is None:
        return 0
    back = 0
    shelves = set()
    for move in sort["moves"]:
        source, target = Path(move["to"]), Path(move["from"])
        shelves.add(source.parent)
        try:
            if source.is_file() and not target.exists():
                source.rename(target)
                back += 1
        except OSError:
            continue
    for shelf in shelves:
        try:
            shelf.rmdir()  # only works when the shelf is empty, so anything else stays
        except OSError:
            pass
    _keep(log, [one for one in sorts if one is not sort])
    return back


class BreakSpotter:
    """Tells a break between tasks: the user switched to another window a moment
    ago and isn't typing. Called about once a second while a question waits,
    which is how it sees the switches."""

    def __init__(self):
        self._window = None
        self._switched = float("-inf")

    def __call__(self) -> bool:
        if sys.platform != "win32":
            return False  # breaks are spotted on Windows only for now, so there is never one
        from .glow import full_screen_in_use

        user32 = ctypes.windll.user32
        window, now = user32.GetForegroundWindow(), time.monotonic()
        if self._window is not None and window != self._window:
            self._switched = now
        self._window = window

        class LastInput(ctypes.Structure):
            _fields_ = [("size", ctypes.c_uint), ("tick", ctypes.c_uint)]

        last = LastInput(ctypes.sizeof(LastInput), 0)
        if not user32.GetLastInputInfo(ctypes.byref(last)):
            return False
        idle = (ctypes.windll.kernel32.GetTickCount() - last.tick) & 0xFFFFFFFF
        return (now - self._switched <= BREAK_SECONDS and idle >= TYPING_GAP_SECONDS * 1000
                and not full_screen_in_use())


class TidyWatch:
    """Notices what could help right now, asks, and does the job.

    It looks at two things: a messy Downloads folder, every so often, and a
    lecture on the screen, every few seconds. Questions take turns, so it
    never asks two things at once.

    practice: nothing is looked at or moved; the questions come soon after
    the window is minimized and the jobs only wait, so everything can be tried
    with FakeEngine.
    """

    def __init__(self, folder: Path | None = None, log: Path | None = None, glow=None,
                 ask: Callable[[str, threading.Event], str | None] | None = None,
                 quiet: Callable[[], bool] | None = None, watching: Callable[[], str] | None = None,
                 practice: bool = False, noticing: bool | None = None):
        """glow, ask, quiet and watching are replaced in tests. noticing: whether the
        user said it may notice things; None means read what they said last time."""
        self.folder = folder or downloads_dir()
        self.log = log or log_path()
        self.practice = practice
        self._glow = glow
        self._ask = ask or _real_ask
        self._quiet = quiet or BreakSpotter()
        self._gap = PRACTICE_QUESTION_GAP_SECONDS if practice else QUESTION_GAP_SECONDS
        self.noticing = True if practice and noticing is None else noticing
        if self.noticing is None:
            self.noticing = self._read_settings().get("noticing")
        if sys.platform != "win32":
            # It notices nothing off Windows for now, so it never asks whether it may.
            self.noticing = False
        self._answers = {} if practice else self._read_answers()
        self._watching = watching or (_practice_lecture if practice else _real_lecture)
        self._asleep_until = 0.0 if practice else self._read_snooze()
        self._video_asleep_until = 0.0
        self._video_seen = PRACTICE_LECTURE if practice else ""  # the lecture on screen at the last look
        self._video_asked: set[str] = set()
        self._video_waiting = False  # it asked about a video and hasn't had an answer
        self._doing: str | None = None  # the job running now, in the user's words
        self._practice_files = 60
        self._done = self._read_done()
        self._stopping = threading.Event()
        self._job = threading.Lock()
        self._turn = threading.Lock()  # one question at a time
        self._question_gone = threading.Event()  # answered somewhere else, so the note can go
        # No answer yet, so the first question needn't wait for the gap. Not 0.0: the
        # clock here counts from boot, so that kept it quiet for the first three
        # hours after every restart of the computer (and hung the tests after one).
        self._last_answer = float("-inf")
        self.asking = False  # a question is on the screen right now
        self.changed: Callable[[], None] = lambda: None  # told whenever today() would say something new
        self.held: Callable[[], bool] = lambda: False  # true while it shouldn't ask anything yet

    # ----------------------------------------------------------- looking

    def start(self) -> None:
        if sys.platform != "win32":
            return  # no looking off Windows for now: jobs still run when asked, with no light
        threading.Thread(target=self._keep_looking, args=(self.look, FIRST_LOOK_SECONDS, LOOK_SECONDS,
                                                          PRACTICE_FIRST_LOOK_SECONDS),
                         name="tidy-watch", daemon=True).start()
        if self.practice or LECTURE_NOTES_BUILT:
            threading.Thread(target=self._keep_looking, args=(self.look_for_video, VIDEO_LOOK_SECONDS,
                                                              VIDEO_LOOK_SECONDS, PRACTICE_VIDEO_SECONDS),
                             name="video-watch", daemon=True).start()

    def stop(self) -> None:
        self._stopping.set()
        self._question_gone.set()
        if self._glow:
            self._glow.close()

    def _keep_looking(self, look: Callable[[], None], first: float, then: float, practice_first: float) -> None:
        wait = practice_first if self.practice else first
        while not self._stopping.wait(wait):
            wait = then
            try:
                look()
            except Exception:
                traceback.print_exc()  # a bad look must never take the app down

    def look(self) -> None:
        """One look at the folder, asking about it if the time is right."""
        count = self._count()
        if not self._worth_asking(count):
            return
        answer = self._put_question(_question(count), lambda: self._worth_asking(self._count()))
        if self._stopping.is_set():
            return
        if answer == YES:
            self._counted(SORT, "yes")
            self.sort_now()
        elif answer == NOT_NOW:
            self._counted(SORT, "no")
            self._snooze(SNOOZE_DAYS)
        elif not self._question_gone.is_set():
            self._counted(SORT, "ignored")
            self._snooze(IGNORED_DAYS)

    def look_for_video(self) -> None:
        """One look at the window in front. It takes two looks in a row, so a
        tab the user is only passing through never gets a question."""
        if not self.noticing:
            return
        title = self._watching()
        seen, self._video_seen = self._video_seen, title
        if (not title or title != seen or title in self._video_asked or self._job.locked()
                or time.time() < self._video_asleep_until):
            return
        self._video_asked.add(title)
        self._video_waiting = True
        self.changed()
        answer = self._put_question(VIDEO_QUESTION, lambda: self._video_waiting)
        if answer and self._video_waiting:
            self.answer(VIDEO, answer == YES)
        elif answer is None and self._video_waiting and not self._question_gone.is_set():
            self._counted(VIDEO, "ignored")

    def _put_question(self, text: str, still_wanted: Callable[[], bool]) -> str | None:
        """Ask when the user can take it, one question at a time. By the time
        that comes, they may already have answered in one of the windows."""
        with self._turn:
            while (self.held() or not self._quiet() or self._job.locked()
                   or time.monotonic() - self._last_answer < self._gap):
                if self._stopping.wait(1):
                    return None
            if not still_wanted():
                return None
            self._question_gone.clear()
            self.asking = True
            self.changed()
            try:
                return self._ask(text, self._question_gone)
            finally:
                self.asking = False
                self._last_answer = time.monotonic()
                self.changed()

    # ------------------------------------------------- asking and counting

    def _settings_path(self) -> Path:
        return self.log.with_name("tidy_settings.json")

    def _read_settings(self) -> dict:
        try:
            return json.loads(self._settings_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def set_noticing(self, on: bool) -> None:
        """The user's answer to "may I notice things?", kept for next time."""
        self.noticing = bool(on)
        if not self.practice:
            self._settings_path().parent.mkdir(parents=True, exist_ok=True)
            self._settings_path().write_text(json.dumps({**self._read_settings(), "noticing": self.noticing}),
                                             encoding="utf-8")
        if not on:
            self._video_waiting = False
            self._question_gone.set()  # a question on the screen goes too
        self.changed()

    def _answers_path(self) -> Path:
        return self.log.with_name("questions.json")

    def _read_answers(self) -> dict:
        try:
            return json.loads(self._answers_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _counted(self, which: str, how: str) -> None:
        """Kept on this computer only, so the questions people don't want can be found."""
        counts = self._answers.setdefault(which, {"yes": 0, "no": 0, "ignored": 0})
        counts[how] += 1
        if not self.practice:
            self._answers_path().parent.mkdir(parents=True, exist_ok=True)
            self._answers_path().write_text(json.dumps(self._answers), encoding="utf-8")

    def answers(self) -> dict:
        return {which: dict(counts) for which, counts in self._answers.items()}

    def _count(self) -> int:
        return self._practice_files if self.practice else len(loose_files(self.folder))

    def _worth_asking(self, count: int) -> bool:
        return (bool(self.noticing) and count >= MIN_FILES and time.time() >= self._asleep_until
                and not self._job.locked())

    def today(self, now: float | None = None) -> dict:
        """What the windows show about these jobs, as plain data for the page."""
        now = time.time() if now is None else now
        midnight = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        count = self._count()
        noticed = None
        if self._video_waiting:
            noticed = {"id": VIDEO, "text": VIDEO_QUESTION}
        elif self._worth_asking(count):
            plan = _practice_plan(count) if self.practice else sort_plan(self.folder)
            noticed = {"id": SORT, "text": _question(count), "plan": plan}
        undoable = [] if self.practice else [sort["id"] for sort in _sorts(self.log)]
        done = [{**job, "undo": job.get("sort") in undoable}
                for job in reversed(self._done) if job["when"] >= midnight]
        return {"working": self._doing, "noticed": noticed, "done": done, "can_undo": bool(undoable),
                "noticing": self.noticing}

    def answer(self, which: str, yes: bool) -> None:
        """The user answered in the note or in one of the windows."""
        self._question_gone.set()
        self._counted(which, "yes" if yes else "no")
        if which == VIDEO:
            self._video_waiting = False
            if yes:
                self.summarize_video()
            else:
                self._video_asleep_until = time.time() + IGNORED_DAYS * 86400
                self.changed()
        elif yes:
            self.sort_now()
        else:
            self._snooze(SNOOZE_DAYS)

    def _snooze_path(self) -> Path:
        return self.log.with_name("tidy_snooze.json")

    def _read_snooze(self) -> float:
        try:
            return float(json.loads(self._snooze_path().read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return 0.0

    def _snooze(self, days: float) -> None:
        self._asleep_until = time.time() + days * 86400
        if not self.practice:
            self._snooze_path().parent.mkdir(parents=True, exist_ok=True)
            self._snooze_path().write_text(json.dumps(self._asleep_until), encoding="utf-8")
        self.changed()

    def _done_path(self) -> Path:
        return self.log.with_name("tidy_done.json")

    def _read_done(self) -> list[dict]:
        if self.practice:  # so the Done today list can be seen in the practice run
            return [{"when": time.time() - 5400, "text": "Sorted 12 screenshots into folders", "undo": False}]
        try:
            return json.loads(self._done_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _remember(self, text: str, undo: bool, details: str = "", sort: str = "") -> None:
        job = {"when": time.time(), "text": text, "undo": undo, "details": details, "sort": sort}
        self._done = [*self._done, job][-DONE_KEPT:]
        if not self.practice:
            self._done_path().parent.mkdir(parents=True, exist_ok=True)
            self._done_path().write_text(json.dumps(self._done, ensure_ascii=False), encoding="utf-8")
        self.changed()

    # ---------------------------------------------------------- the jobs

    def can_undo(self) -> bool:
        return not self.practice and can_undo(self.log)

    def sort_now(self) -> None:
        self._begin("Sorting your Downloads folder", self._sort)

    def undo(self, id: str | None = None) -> None:
        self._begin("Putting your files back", lambda: self._put_back(id))

    def summarize_video(self) -> None:
        if self.practice:
            self._begin("Summarizing your video", self._practice_summary)
        else:
            self._remember(NO_VIDEO_SUMMARY, undo=False)  # no such agent yet, so no light and no pretending

    def _practice_summary(self) -> None:
        self._stopping.wait(PRACTICE_JOB_SECONDS)
        self._remember("Practice: your video's summary would appear here", undo=False)

    def _sort(self) -> None:
        if self.practice:
            self._stopping.wait(PRACTICE_JOB_SECONDS)
            moved, self._practice_files = self._practice_files, 0
            details, sort = _where(_practice_plan(moved)), ""
        else:
            moved = sort_folder(self.folder, self.log)
            if moved:
                from .. import activity

                activity.record(activity.SORTED, moved)
            sort_done = last_sort(self.log)
            details, sort = (_where(moved_to(sort_done)), sort_done["id"]) if moved and sort_done else ("", "")
        if moved:
            self._remember(f"Sorted {moved} file{'' if moved == 1 else 's'} into folders", undo=True,
                           details=details, sort=sort)

    def _put_back(self, id: str | None = None) -> None:
        back = undo_sort(self.log, id)
        self._remember(f"Put {back} file{'' if back == 1 else 's'} back", undo=False)

    def _begin(self, doing: str, job: Callable) -> None:
        """Run a job on a thread of its own; only one at a time."""
        if self._job.acquire(blocking=False):
            self._doing = doing
            self.changed()
            threading.Thread(target=self._run, args=(job,), name="tidy-job", daemon=True).start()

    def _run(self, job: Callable) -> None:
        began = time.monotonic()
        glow = self._glow or self._make_glow()
        glow.started()
        try:
            job()
        except Exception:
            traceback.print_exc()
            glow.failed()  # green would be a lie
        else:
            self._stopping.wait(max(0.0, MIN_JOB_SECONDS - (time.monotonic() - began)))
            glow.finished()
        finally:
            self._doing = None
            self._job.release()
            self.changed()

    def _make_glow(self):
        if sys.platform != "win32":
            return _NoLight()
        from .glow import Glow

        self._glow = Glow()
        return self._glow


class _NoLight:
    """Stands in for the light where there is none yet (the Mac): the job runs, nothing shows."""

    def started(self) -> None:
        pass

    def finished(self) -> None:
        pass

    def failed(self) -> None:
        pass

    def close(self) -> None:
        pass


def _question(count: int) -> str:
    return f"Sort {count} files in Downloads?"


def _where(plan: list[dict]) -> str:
    """"Pictures 20 · Documents 14": where files went, or would go."""
    return " · ".join(f"{part['shelf']} {part['count']}" for part in plan)


def _practice_plan(count: int) -> list[dict]:
    pictures = count // 2
    return [{"shelf": "Pictures", "count": pictures}, {"shelf": "Documents", "count": count - pictures}]


def _real_ask(text: str, cancel: threading.Event) -> str | None:
    from .note import ask

    return ask(text, YES, NOT_NOW, cancel)


def _real_lecture() -> str:
    from .watching import lecture_on_screen

    return lecture_on_screen()


def _practice_lecture() -> str:
    return PRACTICE_LECTURE
