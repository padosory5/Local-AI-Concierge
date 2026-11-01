"""Elaina notices what could help, asks once, and does the job.

A messy Downloads folder is the first such job, and a lecture on the screen the
second, though summarizing one is not built yet.

Everything here is plain code with no model involved: code can count files and
read a window's title, and it does so without holding any graphics memory.
Nothing is ever deleted or overwritten, and the last sort can be undone.
"""

from __future__ import annotations

import ctypes
import json
import threading
import time
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from ..elaina import data_dir

MIN_FILES = 30  # fewer loose files than this isn't a mess worth interrupting for
SETTLE_SECONDS = 600  # a file newer than this may still be downloading
FIRST_LOOK_SECONDS, LOOK_SECONDS = 120, 1800
SNOOZE_DAYS = 7  # after "Not now"
IGNORED_DAYS = 1  # after the question goes away unanswered
QUIET_SECONDS = 4  # no typing or mouse for this long before she asks
MIN_JOB_SECONDS = 3.5  # even an instant job shows both lights, one after the other
PRACTICE_FIRST_LOOK_SECONDS, PRACTICE_JOB_SECONDS = 6, 5
VIDEO_LOOK_SECONDS, PRACTICE_VIDEO_SECONDS = 15, 3
QUESTION_GAP_SECONDS = 4  # between one answer and the next question
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
    return data_dir() / "last_sort.json"


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
            if (path.is_file() and not path.name.startswith(".")
                    and path.name.lower() not in SYSTEM_FILES and path.suffix.lower() not in UNFINISHED
                    and now - path.stat().st_mtime >= SETTLE_SECONDS):
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


def sort_folder(folder: Path, log: Path, now: float | None = None) -> int:
    """Move each loose file onto its shelf and remember how, for undo_sort.
    A file that can't be moved, because a program has it open, stays put."""
    moved = []
    try:
        for path in loose_files(folder, now):
            shelf = folder / shelf_for(path)
            try:
                shelf.mkdir(exist_ok=True)
                target = free_name(shelf / path.name)
                path.rename(target)
                moved.append({"from": str(path), "to": str(target)})
            except OSError:
                continue
    finally:
        # Saved even if something went wrong halfway, so what moved can go back.
        if moved:
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(json.dumps(moved, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(moved)


def can_undo(log: Path) -> bool:
    return log.is_file()


def undo_sort(log: Path) -> int:
    """Put the files back. A file the user has since moved or deleted is left
    as it is, and a file now in the way keeps its place."""
    if not log.is_file():
        return 0
    back = 0
    shelves = set()
    for move in json.loads(log.read_text(encoding="utf-8")):
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
    log.unlink()
    return back


def user_is_quiet() -> bool:
    """Not typing or moving the mouse, and no game or video in front."""
    from .glow import full_screen_in_use

    class LastInput(ctypes.Structure):
        _fields_ = [("size", ctypes.c_uint), ("tick", ctypes.c_uint)]

    last = LastInput(ctypes.sizeof(LastInput), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(last)):
        return False
    idle = (ctypes.windll.kernel32.GetTickCount() - last.tick) & 0xFFFFFFFF
    return idle >= QUIET_SECONDS * 1000 and not full_screen_in_use()


class TidyWatch:
    """Notices what could help right now, asks, and does the job.

    It looks at two things: a messy Downloads folder, every so often, and a
    lecture on the screen, every few seconds. Questions take turns, so she
    never asks two things at once.

    practice: nothing is looked at or moved; the questions come soon after
    the window is minimized and the jobs only wait, so everything can be tried
    with FakeEngine.
    """

    def __init__(self, folder: Path | None = None, log: Path | None = None, glow=None,
                 ask: Callable[[str, threading.Event], str | None] | None = None,
                 quiet: Callable[[], bool] | None = None, watching: Callable[[], str] | None = None,
                 practice: bool = False):
        """glow, ask, quiet and watching are replaced in tests."""
        self.folder = folder or downloads_dir()
        self.log = log or log_path()
        self.practice = practice
        self._glow = glow
        self._ask = ask or _real_ask
        self._quiet = quiet or user_is_quiet
        self._watching = watching or (_practice_lecture if practice else _real_lecture)
        self._asleep_until = 0.0 if practice else self._read_snooze()
        self._video_asleep_until = 0.0
        self._video_seen = PRACTICE_LECTURE if practice else ""  # the lecture on screen at the last look
        self._video_asked: set[str] = set()
        self._video_waiting = False  # she asked about a video and hasn't had an answer
        self._doing: str | None = None  # the job running now, in the user's words
        self._practice_files = 60
        self._done = self._read_done()
        self._stopping = threading.Event()
        self._job = threading.Lock()
        self._turn = threading.Lock()  # one question at a time
        self._question_gone = threading.Event()  # answered somewhere else, so the note can go
        self._last_answer = 0.0
        self.asking = False  # a question is on the screen right now
        self.changed: Callable[[], None] = lambda: None  # told whenever today() would say something new
        self.held: Callable[[], bool] = lambda: False  # true while she shouldn't ask anything yet

    # ----------------------------------------------------------- looking

    def start(self) -> None:
        threading.Thread(target=self._keep_looking, args=(self.look, FIRST_LOOK_SECONDS, LOOK_SECONDS,
                                                          PRACTICE_FIRST_LOOK_SECONDS),
                         name="tidy-watch", daemon=True).start()
        threading.Thread(target=self._keep_looking, args=(self.look_for_video, VIDEO_LOOK_SECONDS, VIDEO_LOOK_SECONDS,
                                                          PRACTICE_VIDEO_SECONDS),
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
            self.sort_now()
        elif answer == NOT_NOW:
            self._snooze(SNOOZE_DAYS)
        elif not self._question_gone.is_set():
            self._snooze(IGNORED_DAYS)

    def look_for_video(self) -> None:
        """One look at the window in front. It takes two looks in a row, so a
        tab the user is only passing through never gets a question."""
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

    def _put_question(self, text: str, still_wanted: Callable[[], bool]) -> str | None:
        """Ask when the user can take it, one question at a time. By the time
        that comes, they may already have answered in one of the windows."""
        with self._turn:
            while (self.held() or not self._quiet() or self._job.locked()
                   or time.monotonic() - self._last_answer < QUESTION_GAP_SECONDS):
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

    def _count(self) -> int:
        return self._practice_files if self.practice else len(loose_files(self.folder))

    def _worth_asking(self, count: int) -> bool:
        return count >= MIN_FILES and time.time() >= self._asleep_until and not self._job.locked()

    def today(self, now: float | None = None) -> dict:
        """What the windows show about these jobs, as plain data for the page."""
        now = time.time() if now is None else now
        midnight = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        count = self._count()
        noticed = None
        if self._video_waiting:
            noticed = {"id": VIDEO, "text": VIDEO_QUESTION}
        elif self._worth_asking(count):
            noticed = {"id": SORT, "text": _question(count)}
        return {"working": self._doing, "noticed": noticed,
                "done": [job for job in reversed(self._done) if job["when"] >= midnight],
                "can_undo": self.can_undo()}

    def answer(self, which: str, yes: bool) -> None:
        """The user answered in the note or in one of the windows."""
        self._question_gone.set()
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

    def _remember(self, text: str, undo: bool) -> None:
        self._done = [*self._done, {"when": time.time(), "text": text, "undo": undo}][-DONE_KEPT:]
        if not self.practice:
            self._done_path().parent.mkdir(parents=True, exist_ok=True)
            self._done_path().write_text(json.dumps(self._done, ensure_ascii=False), encoding="utf-8")
        self.changed()

    # ---------------------------------------------------------- the jobs

    def can_undo(self) -> bool:
        return not self.practice and can_undo(self.log)

    def sort_now(self) -> None:
        self._begin("Sorting your Downloads folder", self._sort)

    def undo(self) -> None:
        self._begin("Putting your files back", self._put_back)

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
        else:
            moved = sort_folder(self.folder, self.log)
        if moved:
            self._remember(f"Sorted {moved} file{'' if moved == 1 else 's'} into folders", undo=True)

    def _put_back(self) -> None:
        back = undo_sort(self.log)
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
        from .glow import Glow

        self._glow = Glow()
        return self._glow


def _question(count: int) -> str:
    return f"Sort {count} files in Downloads?"


def _real_ask(text: str, cancel: threading.Event) -> str | None:
    from .note import ask

    return ask(text, YES, NOT_NOW, cancel)


def _real_lecture() -> str:
    from .watching import lecture_on_screen

    return lecture_on_screen()


def _practice_lecture() -> str:
    return PRACTICE_LECTURE
