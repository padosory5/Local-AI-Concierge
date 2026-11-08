"""Pulling the drawer out of the screen's right edge: Ctrl held, press the mouse at
the very edge, drag left. The drawer follows the mouse and settles open once it has
been pulled far enough; let go early and it slides back. With the drawer open, Ctrl
and a press on it dragged right pushes it back in.

Only the gesture lives here. It reads the mouse and the keyboard through the same
hooks the Spot uses (pynput), and must return from them at once, so it only tells
the window what the mouse is doing and never moves anything itself. Windows only
for now, like the Spot.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from collections.abc import Callable

EDGE_PIXELS = 12  # the press must be this close to the screen's right edge
OPEN_PIXELS = 90  # pulled at least this far, the drawer stays out (or goes back in)

Screen = tuple[int, int, int, int, float]  # left, top, width, height of the work area, and its scale


def screen_at(x: int, y: int) -> Screen:
    """The work area (above the taskbar) of the screen under this point, in real
    pixels, and that screen's scale (1.0 at 100%, 1.5 at 150%)."""
    if sys.platform != "win32":
        return 0, 0, 0, 0, 1.0
    from ctypes import wintypes

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT), ("work", wintypes.RECT),
                    ("flags", wintypes.DWORD)]

    user32 = ctypes.windll.user32
    user32.MonitorFromPoint.restype = ctypes.c_void_p
    monitor = user32.MonitorFromPoint(wintypes.POINT(x, y), 2)  # 2: the nearest screen
    info = MonitorInfo()
    info.size = ctypes.sizeof(MonitorInfo)
    user32.GetMonitorInfoW(ctypes.c_void_p(monitor), ctypes.byref(info))
    dpi = ctypes.c_uint(96)
    try:
        ctypes.windll.shcore.GetDpiForMonitor(ctypes.c_void_p(monitor), 0, ctypes.byref(dpi), ctypes.byref(ctypes.c_uint()))
    except (AttributeError, OSError):
        pass
    work = info.work
    return work.left, work.top, work.right - work.left, work.bottom - work.top, dpi.value / 96


def real_pixels() -> None:
    """The mouse hooks report real pixels; the thread that places the window must think in them too."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass


class EdgePull:
    """Calls on_pull(distance, screen, closing) while the mouse drags with Ctrl held,
    and on_release(distance, screen, closing) when it lets go. `opened` says where the
    drawer is when it is open (left, top, width, height in real pixels), or None."""

    def __init__(self, on_pull: Callable[[int, Screen, bool], None], on_release: Callable[[int, Screen, bool], None],
                 opened: Callable[[], tuple[int, int, int, int] | None], screen: Callable[[int, int], Screen] = screen_at):
        self.on_pull, self.on_release, self.opened = on_pull, on_release, opened
        self._screen_at = screen
        self._ctrl = False
        self._start: tuple[int, int] | None = None  # where the press was, while dragging
        self._screen: Screen | None = None
        self._closing = False
        self._keys = self._mouse = None

    def start(self) -> None:
        from pynput import keyboard, mouse

        if self._keys is None:
            self._keys = keyboard.Listener(on_press=self.pressed, on_release=self.released)
            self._mouse = mouse.Listener(on_click=self.clicked, on_move=self.moved)
            self._keys.start()
            self._mouse.start()

    def stop(self) -> None:
        for listener in (self._keys, self._mouse):
            if listener is not None:
                listener.stop()
        self._keys = self._mouse = None

    @staticmethod
    def _is_ctrl(key) -> bool:
        return getattr(key, "name", "") in ("ctrl", "ctrl_l", "ctrl_r")

    # These run inside Windows' hooks, which must return at once.

    def pressed(self, key, injected: bool = False) -> None:
        if self._is_ctrl(key):
            self._ctrl = True

    def released(self, key, injected: bool = False) -> None:
        if self._is_ctrl(key):
            self._ctrl = False

    def clicked(self, x: int, y: int, button, pressed: bool, injected: bool = False) -> None:
        if getattr(button, "name", "") != "left":
            return
        if not pressed:
            if self._start is not None:
                distance = self._distance(x)
                start, screen, closing = self._start, self._screen, self._closing
                self._start = None
                threading.Thread(target=self.on_release, args=(distance, screen, closing), name="drawer", daemon=True).start()
            return
        if not self._ctrl:
            return
        open_rect = self.opened()
        if open_rect is not None:
            left, top, width, height = open_rect
            if left <= x < left + width and top <= y < top + height:
                self._start, self._screen, self._closing = (x, y), self._screen_at(x, y), True
            return
        screen = self._screen_at(x, y)
        if screen[2] and x >= screen[0] + screen[2] - EDGE_PIXELS:
            self._start, self._screen, self._closing = (x, y), screen, False
            self.on_pull(0, screen, False)

    def moved(self, x: int, y: int, injected: bool = False) -> None:
        if self._start is not None:
            self.on_pull(self._distance(x), self._screen, self._closing)

    def _distance(self, x: int) -> int:
        """How far the mouse has gone the way that matters: left to pull out, right to push in."""
        start_x = self._start[0]
        return max(0, x - start_x if self._closing else start_x - x)
