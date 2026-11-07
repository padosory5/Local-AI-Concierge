"""Notice when the user highlights text with the mouse, in any program, and read it.

A highlight is a mouse drag or a double click. The text is read first through
UI Automation, Windows' accessibility interface, which also says where the
text is on screen and leaves the clipboard alone. Programs that do not offer
that are read by pressing Ctrl+C for the user and putting their clipboard
back afterwards, except in terminals, where Ctrl+C would stop the program
running in them.

Windows only for now.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from collections.abc import Callable
from ctypes import wintypes

import psutil

DRAG_PIXELS = 8
DOUBLE_CLICK_SECONDS = 0.45
MIN_CHARS, MAX_CHARS = 2, 1500
# Programs where Ctrl+C is unsafe to press for the user: in a terminal it
# stops the running program. Highlights there are read only through UI
# Automation, or not at all.
NO_COPY_APPS = {
    "windowsterminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "conhost.exe", "openconsole.exe",
    "wsl.exe", "bash.exe", "mintty.exe", "putty.exe", "code.exe", "cursor.exe", "idea64.exe", "pycharm64.exe",
}

Rect = tuple[int, int, int, int]  # left, top, right, bottom in screen pixels

if sys.platform == "win32":
    _user32 = ctypes.windll.user32
else:  # highlights are read on Windows only for now; elsewhere the module imports and reads nothing
    _user32 = None


def foreground_app() -> tuple[int, str]:
    """(process id, lower-case program name) of the window in front."""
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(_user32.GetForegroundWindow(), ctypes.byref(pid))
    try:
        return pid.value, psutil.Process(pid.value).name().lower()
    except (psutil.Error, ValueError):
        return pid.value, ""


class SelectionWatcher:
    """Calls on_selection(text, rect) after the user highlights text.

    on_press(x, y) is called on every left mouse press, so a bubble can close
    when the user clicks elsewhere. Highlights in skip_pids (Noir's own
    window) are ignored.
    """

    def __init__(
        self,
        on_selection: Callable[[str, Rect], None],
        on_press: Callable[[int, int], None] | None = None,
        skip_pids: set[int] | None = None,
    ):
        self.on_selection = on_selection
        self.on_press = on_press
        self.skip_pids = set(skip_pids or ())
        self._listener = None
        self._down: tuple[int, int] | None = None
        self._last_up = (0, 0, 0.0)
        self._reading = threading.Lock()

    @property
    def running(self) -> bool:
        return self._listener is not None

    def start(self) -> None:
        from pynput import mouse

        if self._listener is None:
            self._listener = mouse.Listener(on_click=self._click)
            self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def _click(self, x: int, y: int, button, pressed: bool) -> None:
        # Runs inside Windows' mouse hook, which must return at once: anything
        # slow goes to its own thread.
        if button.name != "left":
            return
        if pressed:
            self._down = (x, y)
            if self.on_press:
                self.on_press(x, y)
            return
        if self._down is None:
            return
        down_x, down_y = self._down
        dragged = abs(x - down_x) > DRAG_PIXELS or abs(y - down_y) > DRAG_PIXELS
        last_x, last_y, last_t = self._last_up
        now = time.monotonic()
        double = now - last_t < DOUBLE_CLICK_SECONDS and abs(x - last_x) < 6 and abs(y - last_y) < 6
        self._last_up = (x, y, now)
        if dragged or double:
            fallback = (min(x, down_x), min(y, down_y), max(x, down_x), max(y, down_y))
            threading.Thread(target=self._read, args=(fallback,), daemon=True).start()

    def _read(self, fallback: Rect) -> None:
        if not self._reading.acquire(blocking=False):
            return  # still reading the last highlight
        try:
            time.sleep(0.12)  # let the program finish selecting
            pid, app = foreground_app()
            if pid in self.skip_pids:
                return
            text, rect = read_selection(app)
            text = (text or "").strip()
            if MIN_CHARS <= len(text) <= MAX_CHARS:
                self.on_selection(text, rect or fallback)
        except Exception:
            pass  # a program that cannot be read is skipped, never a crash
        finally:
            self._reading.release()


def read_selection(app: str) -> tuple[str, Rect | None]:
    text, rect = _uia_selection()
    if text or app in NO_COPY_APPS:
        return text, rect
    return _copy_selection(), None


def highlighted_text() -> str:
    """What is highlighted right now, as far as UI Automation can tell ("" if
    nothing, or if the program does not say)."""
    try:
        return _uia_selection()[0].strip()
    except Exception:
        return ""


def _uia_selection() -> tuple[str, Rect | None]:
    import uiautomation as auto

    with auto.UIAutomationInitializerInThread():
        control = auto.GetFocusedControl()
        for _ in range(6):  # the focused part, or the document around it
            if control is None:
                break
            pattern = control.GetPattern(auto.PatternId.TextPattern)
            if pattern:
                ranges = pattern.GetSelection()
                if not ranges:
                    return "", None
                rects = ranges[0].GetBoundingRectangles()
                rect = (rects[0].left, rects[0].top, rects[-1].right, rects[-1].bottom) if rects else None
                return ranges[0].GetText(-1), rect
            control = control.GetParentControl()
    return "", None


# ------------------------------------------------------------- clipboard

# Formats that are handles to drawings rather than memory: Windows makes them
# again from the formats that are kept (CF_BITMAP from CF_DIB, and so on).
_HANDLE_FORMATS = {2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E}
CF_UNICODETEXT = 13


def _open_clipboard(win32clipboard) -> bool:
    for _ in range(10):
        try:
            win32clipboard.OpenClipboard()
            return True
        except Exception:
            time.sleep(0.02)  # another program has it open
    return False


def save_clipboard() -> list[tuple[int, bytes]]:
    import win32clipboard

    saved: list[tuple[int, bytes]] = []
    if not _open_clipboard(win32clipboard):
        return saved
    try:
        fmt = win32clipboard.EnumClipboardFormats(0)
        while fmt:
            if fmt not in _HANDLE_FORMATS:
                try:
                    handle = win32clipboard.GetClipboardDataHandle(fmt)
                    saved.append((fmt, win32clipboard.GetGlobalMemory(handle)))
                except Exception:
                    pass
            fmt = win32clipboard.EnumClipboardFormats(fmt)
    finally:
        win32clipboard.CloseClipboard()
    return saved


def restore_clipboard(saved: list[tuple[int, bytes]]) -> None:
    import win32clipboard

    if not _open_clipboard(win32clipboard):
        return
    try:
        win32clipboard.EmptyClipboard()
        for fmt, data in saved:
            try:
                win32clipboard.SetClipboardData(fmt, data)
            except Exception:
                pass
    finally:
        win32clipboard.CloseClipboard()


def set_clipboard_text(text: str) -> None:
    import win32clipboard

    if not _open_clipboard(win32clipboard):
        return
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


def _copy_selection() -> str:
    """Press Ctrl+C for the user, read the text, and put their clipboard back."""
    import win32clipboard
    from pynput.keyboard import Controller, Key

    saved = save_clipboard()
    before = win32clipboard.GetClipboardSequenceNumber()
    keyboard = Controller()
    with keyboard.pressed(Key.ctrl):
        keyboard.press("c")
        keyboard.release("c")
    deadline = time.monotonic() + 0.4
    while win32clipboard.GetClipboardSequenceNumber() == before and time.monotonic() < deadline:
        time.sleep(0.02)
    if win32clipboard.GetClipboardSequenceNumber() == before:
        return ""  # nothing was copied
    text = ""
    if _open_clipboard(win32clipboard):
        try:
            if win32clipboard.IsClipboardFormatAvailable(CF_UNICODETEXT):
                text = win32clipboard.GetClipboardData(CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
    restore_clipboard(saved)
    return text
