"""Noir's small question, next to where it sits in the corner of the screen.

One short line with Yes and No. It floats over every program and never takes
the keyboard, so whatever the user was doing stays where it was. Left alone, it
goes away by itself.
"""

from __future__ import annotations

import ctypes
import gc
import sys
import threading

from .bubble import GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST
from .glow import real_pixels, work_screen

COLORS = {"bg": "#0a090c", "line": "#3a3340", "text": "#fbfafc", "yes": "#c4b4cc", "yes_text": "#000000", "no": "#c4b4cc"}
CIRCLE_ROOM = 84  # kept free at the right, where minimized Noir sits
BOTTOM_GAP = 16
SHOW_SECONDS = 30
CHECK_MS = 200
ARRIVE_STEPS, ARRIVE_MS, ARRIVE_PIXELS = 9, 16, 3  # it slides out from it and fades in
SOLID = 0.97

if sys.platform == "win32":
    _user32 = ctypes.windll.user32
else:  # the note is Windows only for now; elsewhere the module imports and nothing asks
    _user32 = None


def ask(text: str, yes: str, no: str, cancel: threading.Event, seconds: float = SHOW_SECONDS) -> str | None:
    """Show the question and wait. Returns the button clicked, or None if it
    was left alone. All of Tk stays on the calling thread, which owns it."""
    try:
        return _show(text, yes, no, cancel, seconds)
    finally:
        # Every Tk object must be freed on the thread that made it, or Tcl
        # stops the whole app. Some are tied in circles only the garbage
        # collector frees, so it runs here, before any other thread can do it.
        gc.collect()
        gc.enable()


def _show(text: str, yes: str, no: str, cancel: threading.Event, seconds: float) -> str | None:
    import tkinter as tk
    import tkinter.font as tkfont

    real_pixels()
    root = tk.Tk()
    root.withdraw()
    scale = _user32.GetDpiForSystem() / 96 if hasattr(_user32, "GetDpiForSystem") else 1.0
    answer: list[str | None] = [None]

    def font(size: int, family: str = "Segoe UI Semibold") -> tkfont.Font:
        return tkfont.Font(root=root, family=family, size=-round(size * scale))

    def pick(choice: str | None) -> None:
        answer[0] = choice
        root.quit()

    def watch_cancel() -> None:
        if cancel.is_set():
            pick(None)
        else:
            root.after(CHECK_MS, watch_cancel)

    win = tk.Toplevel(root)
    win.overrideredirect(True)
    win.attributes("-alpha", 0.0)
    win.withdraw()
    frame = tk.Frame(win, bg=COLORS["bg"], highlightthickness=max(1, round(scale)), highlightbackground=COLORS["line"],
                     padx=round(16 * scale), pady=round(9 * scale))
    frame.pack(fill="both", expand=True)
    tk.Label(frame, text=text, bg=COLORS["bg"], fg=COLORS["text"], font=font(15)).pack(side="left", padx=(0, round(16 * scale)))
    # Labels, not buttons: a button would take the keyboard when clicked.
    first = tk.Label(frame, text=yes, bg=COLORS["yes"], fg=COLORS["yes_text"], cursor="hand2",
                     padx=round(13 * scale), pady=round(4 * scale), font=font(14))
    first.pack(side="left")
    first.bind("<Button-1>", lambda _e: pick(yes))
    second = tk.Label(frame, text=no, bg=COLORS["bg"], fg=COLORS["no"], cursor="hand2",
                      padx=round(12 * scale), pady=round(4 * scale), font=font(14))
    second.pack(side="left")
    second.bind("<Button-1>", lambda _e: pick(no))

    win.update_idletasks()
    hwnd = _user32.GetParent(win.winfo_id()) or win.winfo_id()
    style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
    corner_preference, rounded = 33, ctypes.c_int(2)  # Windows 11 rounds it; older versions ignore this
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, corner_preference, ctypes.byref(rounded), ctypes.sizeof(rounded))

    # Windows activates a window the first time it is shown, whatever its
    # style (see bubble.py): show it off screen and hand the focus straight back.
    front = _user32.GetForegroundWindow()
    win.geometry("+-32000+-32000")
    win.deiconify()
    root.update()
    win.withdraw()
    root.update()
    if front:
        _user32.SetForegroundWindow(front)

    x, y, width, height = work_screen(whole=False, main=True)
    win.update_idletasks()
    left = x + width - win.winfo_reqwidth() - round(CIRCLE_ROOM * scale)
    top = y + height - win.winfo_reqheight() - round(BOTTOM_GAP * scale)

    def arrive(step: int = 0) -> None:
        share = step / ARRIVE_STEPS
        win.attributes("-alpha", SOLID * share)
        win.geometry(f"+{left + round((ARRIVE_STEPS - step) * ARRIVE_PIXELS * scale)}+{top}")
        if step < ARRIVE_STEPS:
            root.after(ARRIVE_MS, arrive, step + 1)

    arrive()
    win.deiconify()
    win.attributes("-topmost", True)

    root.after(int(seconds * 1000), lambda: pick(None))
    root.after(CHECK_MS, watch_cancel)
    root.mainloop()
    gc.disable()  # until ask() has freed everything itself
    root.destroy()
    return answer[0]
