"""The small window that shows a result right above the highlighted text.

It floats over every program but never takes the keyboard focus, so the
user's highlight and typing stay where they were. Clicking it copies the
text; clicking anywhere else, or waiting, closes it.

Tkinter (part of Python) draws it on a thread of its own, since every Tk call
has to come from the thread that made the window. Other threads only put
requests on a queue.
"""

from __future__ import annotations

import ctypes
import queue
import threading
from ctypes import wintypes

from .selection import Rect, set_clipboard_text

GAP = 8  # pixels between the text and the bubble
MAX_WIDTH = 460
COLORS = {"bg": "#2a2a2d", "text": "#ececea", "muted": "#a09f9a", "accent": "#8f7ff0"}

_user32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST = 0x08000000, 0x00000080, 0x00000008


def show_seconds(text: str) -> float:
    """Long enough to read: about a second per 15 characters, 4 to 20 seconds."""
    return min(20.0, max(4.0, len(text) / 15))


class Bubble:
    def __init__(self):
        self._requests: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="bubble", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    # Safe to call from any thread.

    def show(self, text: str, rect: Rect, title: str = "", seconds: float | None = None,
             stay: bool = False) -> None:
        """stay: no timer; it closes on a click elsewhere, a new highlight, or hide()."""
        self._requests.put(("show", text, rect, title, seconds, stay))

    def pressed(self, x: int, y: int) -> None:
        """A mouse press anywhere: closes the bubble unless it was on the bubble."""
        self._requests.put(("pressed", x, y))

    def hide(self) -> None:
        self._requests.put(("hide",))

    def close(self) -> None:
        """Close the bubble and wait (briefly) until its thread has finished."""
        self._requests.put(("close",))
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=2)

    # Everything below runs on the bubble's own thread.

    def _run(self) -> None:
        import tkinter as tk
        import tkinter.font as tkfont

        # Same pixels as the mouse and UI Automation, on any display scaling.
        try:
            _user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            pass
        root = tk.Tk()
        root.withdraw()
        scale = _user32.GetDpiForSystem() / 96 if hasattr(_user32, "GetDpiForSystem") else 1.0

        win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.withdraw()
        frame = tk.Frame(win, bg=COLORS["bg"], highlightthickness=max(1, round(scale)),
                         highlightbackground=COLORS["accent"], padx=round(12 * scale), pady=round(8 * scale))
        frame.pack(fill="both", expand=True)
        self._title = tk.Label(frame, bg=COLORS["bg"], fg=COLORS["muted"], anchor="w", justify="left",
                               font=tkfont.Font(family="Segoe UI", size=-round(11 * scale)))
        self._title.pack(fill="x")
        self._body = tk.Label(frame, bg=COLORS["bg"], fg=COLORS["text"], anchor="w", justify="left",
                              wraplength=round(MAX_WIDTH * scale),
                              font=tkfont.Font(family="Segoe UI", size=-round(15 * scale)))
        self._body.pack(fill="x")
        for widget in (frame, self._title, self._body):
            widget.bind("<Button-1>", lambda _e: self._copy())

        win.update_idletasks()
        self._hwnd = _user32.GetParent(win.winfo_id()) or win.winfo_id()
        style = _user32.GetWindowLongW(self._hwnd, GWL_EXSTYLE)
        _user32.SetWindowLongW(self._hwnd, GWL_EXSTYLE,
                               style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
        self._root, self._win, self._scale = root, win, scale
        self._text = ""
        self._timer = None
        self._shown = False
        # Windows activates a window the first time it is shown, whatever its
        # style. Show it once far off screen now and hand the focus straight
        # back; every later show leaves the focus where it is.
        front = _user32.GetForegroundWindow()
        win.geometry("+-32000+-32000")
        win.deiconify()
        root.update()
        win.withdraw()
        root.update()
        if front:
            _user32.SetForegroundWindow(front)
        self._ready.set()
        root.after(30, self._poll)
        root.mainloop()

    def _poll(self) -> None:
        try:
            while True:
                request = self._requests.get_nowait()
                kind = request[0]
                if kind == "show":
                    self._show(*request[1:])
                elif kind == "pressed":
                    self._pressed(*request[1:])
                elif kind == "hide":
                    self._hide()
                elif kind == "close":
                    self._root.destroy()
                    # Drop every Tk object here, on Tk's own thread: freed
                    # later from another thread, Tcl can crash on exit.
                    self._root = self._win = self._title = self._body = None
                    return
        except queue.Empty:
            pass
        self._root.after(30, self._poll)

    def _show(self, text: str, rect: Rect, title: str, seconds: float | None, stay: bool) -> None:
        self._text = text
        self._title.config(text=title)
        if title:
            self._title.pack(before=self._body, fill="x")
        else:
            self._title.pack_forget()
        self._body.config(text=text)
        self._win.update_idletasks()
        width, height = self._win.winfo_reqwidth(), self._win.winfo_reqheight()
        if rect is None:  # where the text is was not known: next to the mouse
            point = wintypes.POINT()
            _user32.GetCursorPos(ctypes.byref(point))
            rect = (point.x, point.y, point.x, point.y)
        left, top, _right, bottom = rect
        gap = round(GAP * self._scale)
        screen_w = _user32.GetSystemMetrics(78) or self._win.winfo_screenwidth()  # whole desktop
        x = max(0, min(left, screen_w - width))
        y = top - height - gap
        if y < 0:  # no room above: just below the text instead
            y = bottom + gap
        self._win.geometry(f"+{x}+{y}")
        if not self._shown:
            self._win.deiconify()
            self._win.attributes("-topmost", True)
            self._shown = True
        if self._timer:
            self._root.after_cancel(self._timer)
            self._timer = None
        if not stay:
            delay = seconds if seconds is not None else show_seconds(text)
            self._timer = self._root.after(int(delay * 1000), self._hide)

    def _pressed(self, x: int, y: int) -> None:
        if not self._shown:
            return
        rect = wintypes.RECT()
        _user32.GetWindowRect(self._hwnd, ctypes.byref(rect))
        if not (rect.left <= x <= rect.right and rect.top <= y <= rect.bottom):
            self._hide()

    def _copy(self) -> None:
        if self._text:
            set_clipboard_text(self._text)
            self._title.config(text="Copied")
            self._title.pack(before=self._body, fill="x")
            if self._timer:
                self._root.after_cancel(self._timer)
            self._timer = self._root.after(900, self._hide)

    def _hide(self) -> None:
        if self._shown:
            self._win.withdraw()
            self._shown = False
        self._timer = None
