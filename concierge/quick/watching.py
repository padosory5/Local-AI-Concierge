"""Is the user watching a lecture? Decided in code, from the window in front.

Only the title and the program name of that one window are read, and only
when Noir looks. Nothing on the screen is read or kept, and no model runs.
"""

from __future__ import annotations

import ctypes
import re
import sys

LECTURE_WORDS = re.compile(
    r"\b(lectures?|lessons?|courses?|seminars?|webinars?|tutorials?|class(es)?)\b|강의|강좌|수업|인강|세미나|특강|튜토리얼",
    re.IGNORECASE,
)
VIDEO_SITES = re.compile(r"youtube|유튜브|vimeo|coursera|udemy|edx|khan academy|inflearn|인프런", re.IGNORECASE)
BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "whale.exe", "opera.exe"}
PLAYERS = {"vlc.exe", "potplayer.exe", "potplayer64.exe", "potplayermini.exe", "potplayermini64.exe", "mpc-hc.exe",
           "mpc-hc64.exe", "mpv.exe", "wmplayer.exe", "kmplayer.exe", "video.ui.exe", "microsoft.media.player.exe"}


def looks_like_lecture(title: str, program: str) -> bool:
    """A lecture in a video player, or on a video site in a browser. A browser
    tab about a lecture that isn't on a video site doesn't count."""
    if program in PLAYERS:
        return bool(LECTURE_WORDS.search(title))
    return program in BROWSERS and bool(VIDEO_SITES.search(title)) and bool(LECTURE_WORDS.search(title))


def lecture_on_screen() -> str:
    """The title of the lecture in front, or "" if there isn't one."""
    if sys.platform != "win32":
        return ""  # the window in front is read on Windows only for now
    from .selection import foreground_app

    user32 = ctypes.WinDLL("user32")
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    title = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(user32.GetForegroundWindow(), title, 512)
    _, program = foreground_app()
    return title.value if looks_like_lecture(title.value, program) else ""
