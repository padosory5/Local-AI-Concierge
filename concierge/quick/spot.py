"""The Spot: help right where the user is working, opened by tapping Ctrl twice.

Whatever is highlighted in any program is read, code decides which few actions
fit it (your own writing gets polish and shorten, something you're reading gets
explain and translate, an error message gets what it means), and the answer
goes straight back into the program. Nothing to copy into another window.

The job always runs on Noir's own model, on this computer, whatever is picked
in the model menu: the Spot can be opened over anything in any program, so what
it reads is never sent to a cloud model.
"""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable

from .translate import looks_like

DOUBLE_TAP_SECONDS = 0.4  # between the two taps
TAP_SECONDS = 0.3  # a Ctrl held longer than this is being held, not tapped
MAX_SPOT_CHARS = 4000
MAX_HELPERS = 3  # the user's own agents offered beside the usual actions
# Summing up one sentence gave three bullet points about it, so short text isn't offered that.
SUM_UP_CHARS, SHORTEN_CHARS = 300, 120
WRITING, READING, ERROR, CODE, NOTHING = "writing", "reading", "error", "code", "nothing"
ERROR_WORDS = re.compile(r"Traceback|Exception|\b\w*Error\b|error:|\bfailed\b|\bat line \d+|stack trace|0x[0-9a-fA-F]{6,}")
CODE_SIGNS = re.compile(r"[{};]\s*$|^\s*(def|class|function|import|from|const|let|var|return|public|private)\b|=>|!=|==",
                        re.MULTILINE)
WRITE_FOR_ME = "Write what is asked. Reply with the text only, ready to paste, with no notes."
# Each job: the words on its button, and the instruction its model is given.
ACTIONS = {
    "polish": ("Polish it", "Rewrite the text so it reads clearly and politely. Keep its meaning and its language."),
    "shorter": ("Make it shorter", "Rewrite the text in fewer words. Keep every important point and its language."),
    "explain": ("Explain simply", "Explain this text in simple, everyday words, in two or three short sentences."),
    "summarize": ("Sum it up", "Summarize the text in three short bullet points."),
    "error": ("What this error means", "Explain what this error message means and the most likely fix, in plain words."),
    "code": ("Explain this code", "Explain what this code does in plain words, step by step."),
    "problems": ("Find problems", "Point out likely mistakes in this code and how to fix each one, in plain words."),
    "translate": ("Translate to {language}", "Translate the text into {language}."),
}


def home_language() -> str:
    """The language the computer shows itself in: Korean on a Korean computer, English otherwise."""
    if sys.platform == "win32":
        try:
            return "Korean" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x12 else "English"
        except (AttributeError, OSError):
            return "English"
    first = ""
    if sys.platform == "darwin":
        # The Mac's own list, first language first. An app opened from Finder has no LANG to read.
        try:
            listed = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True,
                                    text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            listed = ""
        found = re.search(r'"([A-Za-z]+)', listed)
        first = found.group(1) if found else ""
    code = (first or os.environ.get("LANG", ""))[:2].lower()
    return "Korean" if code == "ko" else "English"


def kind_of(text: str, editable: bool) -> str:
    """What the highlighted text is, decided in code from the text itself."""
    if not text.strip():
        return NOTHING
    if ERROR_WORDS.search(text):
        return ERROR
    if len(CODE_SIGNS.findall(text)) >= 2:
        return CODE
    return WRITING if editable else READING


def _translate_to(text: str, home: str) -> str | None:
    """Into the user's own language, or out of it into English; None when there's nowhere to go."""
    if not looks_like(text, home):
        return home
    return "English" if home != "English" else None


def actions_for(text: str, editable: bool, helpers: list[tuple[str, str]] = (), home: str | None = None) -> list[dict]:
    """The buttons for this text: a few that fit, then the user's own chat agents."""
    home = home or home_language()
    kind = kind_of(text, editable)
    if kind == NOTHING:
        return []
    long = len(text) >= SUM_UP_CHARS
    ids = {WRITING: ["polish"] + (["shorter"] if len(text) >= SHORTEN_CHARS else []),
           READING: ["explain"] + (["summarize"] if long else []),
           ERROR: ["error", "explain"], CODE: ["code", "problems"]}[kind]
    found = [{"id": job, "words": ACTIONS[job][0]} for job in ids]
    language = _translate_to(text, home) if kind in (WRITING, READING) else None
    if language:
        found.append({"id": f"translate:{language}", "words": ACTIONS["translate"][0].format(language=language)})
    found += [{"id": f"helper:{name}", "words": name} for name, _ in helpers[:MAX_HELPERS]]
    return found


def job(action: str, ask: str, text: str, helpers: list[tuple[str, str]] = ()) -> tuple[str, str]:
    """(instruction, text to work on) for a button or for what the user typed.
    With nothing highlighted, what they typed is the whole request."""
    text = text.strip()[:MAX_SPOT_CHARS]
    if action == "ask" or not action:
        return (f"Do this with the text: {ask.strip()}", text) if text else (WRITE_FOR_ME, ask.strip())
    if action.startswith("translate:"):
        return ACTIONS["translate"][1].format(language=action.split(":", 1)[1]), text
    if action.startswith("helper:"):
        name = action.split(":", 1)[1]
        instruction = next((words for helper, words in helpers if helper == name), "")
        if instruction:
            return instruction, text
    if action in ACTIONS:
        return ACTIONS[action][1], text
    raise ValueError(f"No such action: {action}")


def caret_box() -> tuple[int, int, int] | None:
    """(left, top, bottom) of the blinking text cursor in the window in front, in
    screen pixels, or None when there isn't one. Programs you can type into keep one."""
    from ctypes import wintypes

    class ThreadInfo(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("flags", wintypes.DWORD), ("active", wintypes.HWND),
                    ("focus", wintypes.HWND), ("capture", wintypes.HWND), ("menu", wintypes.HWND),
                    ("moving", wintypes.HWND), ("caret", wintypes.HWND), ("box", wintypes.RECT)]

    try:
        user32 = ctypes.windll.user32
        info = ThreadInfo(size=ctypes.sizeof(ThreadInfo))
        thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
        if not user32.GetGUIThreadInfo(thread, ctypes.byref(info)) or not info.caret:
            return None
        corner = wintypes.POINT(info.box.left, info.box.top)
        user32.ClientToScreen(info.caret, ctypes.byref(corner))
        return corner.x, corner.y, corner.y + (info.box.bottom - info.box.top)
    except (AttributeError, OSError):
        return None


def selection_editable() -> bool:
    """Whether the highlighted text is in something the user can type into, so the
    answer can replace it. Asked through UI Automation first; programs that don't
    say are judged by whether they show a text cursor."""
    try:
        import uiautomation as auto

        with auto.UIAutomationInitializerInThread():
            control = auto.GetFocusedControl()
            if control is not None:
                value = control.GetPattern(auto.PatternId.ValuePattern)
                if value is not None:
                    return not value.IsReadOnly
                if control.ControlTypeName in ("EditControl", "DocumentControl") and control.IsKeyboardFocusable:
                    return True
    except Exception:
        pass
    return caret_box() is not None


class DoubleTap:
    """Calls on_tap when Ctrl is tapped twice on its own, quickly. Ctrl used for
    anything else, like Ctrl+C or holding it down, never counts."""

    def __init__(self, on_tap: Callable[[], None], clock: Callable[[], float] = time.monotonic):
        self.on_tap = on_tap
        self._clock = clock
        self._down_at: float | None = None
        self._used = False  # another key went down while Ctrl was held
        self._last_tap = float("-inf")
        self._listener = None

    def start(self) -> None:
        from pynput import keyboard

        if self._listener is None:
            self._listener = keyboard.Listener(on_press=self.pressed, on_release=self.released)
            self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    @staticmethod
    def _is_ctrl(key) -> bool:
        return getattr(key, "name", "") in ("ctrl", "ctrl_l", "ctrl_r")

    # These run inside Windows' keyboard hook, which must return at once.

    def pressed(self, key, injected: bool = False) -> None:
        if self._is_ctrl(key):
            if self._down_at is None:
                self._down_at, self._used = self._clock(), False
        else:
            self._used = True
            self._last_tap = float("-inf")

    def released(self, key, injected: bool = False) -> None:
        if not self._is_ctrl(key) or self._down_at is None:
            return
        held, self._down_at = self._clock() - self._down_at, None
        if self._used or held > TAP_SECONDS:
            self._last_tap = float("-inf")
            return
        now = self._clock()
        if now - self._last_tap <= DOUBLE_TAP_SECONDS:
            self._last_tap = float("-inf")
            threading.Thread(target=self.on_tap, name="spot", daemon=True).start()
        else:
            self._last_tap = now
