"""Noir minimized: a small circle in the corner, just above the taskbar.

It says what it's doing without words. Print dots drift slowly while it
waits, a line runs round it while a job is going, and rings open out of it
when it has a question. Clicking it opens the see-through window.

Every picture is drawn once at the start, with soft edges no web page could
have on Windows, and shown one after another, so it costs almost nothing while
it sits there. During games, videos and slideshows it steps out of the way.
"""

from __future__ import annotations

import ctypes
import math
import threading
import time
from collections.abc import Callable
from ctypes import wintypes

from ..quick.glow import Layer, full_screen_in_use, pump, real_pixels, work_screen

MINI_SIZE = 72  # the whole picture in logical pixels, with room for its shadow and rings
EDGE_GAP = 8  # from the edges of the screen, above the taskbar
DISC_SHARE = 0.33  # its radius, as a share of the picture
FRAMES = 60
FRAME_SECONDS = 0.05  # 20 pictures a second: slow movement doesn't need more
RESTING, BRIGHT = 225, 255  # how solid it is, and when the mouse is on it
FADE_STEP = 24
FULL_SCREEN_CHECK_SECONDS = 2.0
IDLE, WORKING, ASKING = "idle", "working", "asking"
LILAC, WHITE = (196, 180, 204), (251, 250, 252)

# Soft edges, always on top, out of Alt+Tab, never takes the keyboard.
_STYLE = 0x00080000 | 0x00000008 | 0x00000080 | 0x08000000
_WINDOW_STYLE = 0x80000000 | 0x00000100  # a popup that is told about clicks
_LEFT_BUTTON_UP = 0x0202


def is_click(message: wintypes.MSG, hwnd: int) -> bool:
    return message.message == _LEFT_BUTTON_UP and message.hWnd == hwnd


def premultiplied(picture) -> bytes:
    """Pixels the way Windows wants them: blue first, colours dimmed by their transparency."""
    from PIL import Image, ImageChops

    red, green, blue, alpha = picture.split()
    return Image.merge("RGBA", (ImageChops.multiply(blue, alpha), ImageChops.multiply(green, alpha),
                                ImageChops.multiply(red, alpha), alpha)).tobytes()


def draw_frames(state: str, size: int, count: int = FRAMES) -> list[bytes]:
    """One full turn of its animation. Drawn three times too big, then shrunk,
    which is what makes the edges smooth."""
    from PIL import Image, ImageDraw, ImageFilter

    big = size * 3
    middle, radius = big / 2, big * DISC_SHARE
    shadow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse((middle - radius, middle - radius + big * 0.03,
                                    middle + radius, middle + radius + big * 0.03), fill=(0, 0, 0, 130))
    shadow = shadow.filter(ImageFilter.GaussianBlur(big * 0.04))

    step = radius / 3.6
    spots = [(middle + (column + (row % 2) / 2) * step, middle + row * step * 0.866)
             for row in range(-5, 6) for column in range(-5, 6)]
    frames = []
    for index in range(count):
        turn = index / count * math.tau
        picture = shadow.copy()
        draw = ImageDraw.Draw(picture)
        draw.ellipse((middle - radius, middle - radius, middle + radius, middle + radius), fill=(0, 0, 0, 255))
        # The light on its drifts slowly round, so the dots swell and shrink.
        light_x = middle + math.cos(turn) * radius * 0.38 - radius * 0.1
        light_y = middle + math.sin(turn) * radius * 0.38 - radius * 0.14
        for x, y in spots:
            if math.hypot(x - middle, y - middle) > radius * 0.86:
                continue
            light = max(0.0, 1 - math.hypot(x - light_x, y - light_y) / (radius * 1.25))
            dot = math.sqrt(light) * step * 0.56
            if dot > 1:
                draw.ellipse((x - dot, y - dot, x + dot, y + dot), fill=(*LILAC, 255))
        if state == WORKING:
            start = math.degrees(turn) * 2 - 90
            box = [middle - radius * 1.14, middle - radius * 1.14, middle + radius * 1.14, middle + radius * 1.14]
            draw.arc(box, start, start + 130, fill=(*WHITE, 255), width=round(big * 0.018))
            draw.arc(box, start + 130, start + 210, fill=(*LILAC, 150), width=round(big * 0.012))
        elif state == ASKING:
            for offset in (0.0, 0.5):
                grown = (index / count * 2 + offset) % 1
                reach = radius * (1.06 + grown * 0.4)
                draw.ellipse((middle - reach, middle - reach, middle + reach, middle + reach),
                             outline=(*LILAC, round(210 * (1 - grown))), width=round(big * 0.012))
        frames.append(premultiplied(picture.resize((size, size), Image.LANCZOS)))
    return frames


class Mini:
    """Safe to call from any thread."""

    def __init__(self, on_click: Callable[[], None]):
        self._on_click = on_click
        self._wanted = False
        self._state = IDLE
        self._closing = threading.Event()
        self._thread = threading.Thread(target=self._run, name="mini", daemon=True)
        self._thread.start()

    def show(self) -> None:
        self._wanted = True

    def hide(self) -> None:
        self._wanted = False

    def set_state(self, state: str) -> None:
        self._state = state

    def close(self) -> None:
        self._closing.set()
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=2)

    # Everything below runs on its own thread.

    def _run(self) -> None:
        real_pixels()
        user32 = ctypes.windll.user32
        scale = user32.GetDpiForSystem() / 96 if hasattr(user32, "GetDpiForSystem") else 1.0
        size = round(MINI_SIZE * scale)
        frames = {state: draw_frames(state, size) for state in (IDLE, WORKING, ASKING)}
        layer = Layer(size, size, frames[IDLE][0], _STYLE, _WINDOW_STYLE)
        alpha = 0
        place = (0, 0)
        out_of_the_way = False
        next_check = 0.0

        def clicked(message: wintypes.MSG) -> None:
            if is_click(message, layer.hwnd):
                threading.Thread(target=self._on_click, daemon=True).start()

        try:
            while not self._closing.is_set():
                now = time.monotonic()
                if now >= next_check:
                    next_check = now + FULL_SCREEN_CHECK_SECONDS
                    out_of_the_way = full_screen_in_use()
                    x, y, width, height = work_screen(whole=False, main=True)
                    gap = round(EDGE_GAP * scale)
                    place = (x + width - size - gap, y + height - size - gap)
                target = 0
                if self._wanted and not out_of_the_way:
                    target = BRIGHT if _mouse_near(place, size) else RESTING
                alpha = min(target, alpha + FADE_STEP) if alpha < target else max(target, alpha - FADE_STEP)
                if alpha > 0:
                    layer.draw(frames[self._state][int(now / FRAME_SECONDS) % FRAMES])
                    layer.show(*place, size, size, 0, 0, alpha)
                else:
                    layer.hide()
                pump(clicked)
                time.sleep(FRAME_SECONDS if alpha > 0 else FRAME_SECONDS * 4)
        finally:
            layer.close()


def _mouse_near(place: tuple[int, int], size: int) -> bool:
    point = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return math.hypot(point.x - place[0] - size / 2, point.y - place[1] - size / 2) < size * DISC_SHARE * 1.1
