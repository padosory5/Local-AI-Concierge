"""A small icon by the clock, for what doesn't belong on the circle.

    click the icon        the full window opens
    right-click it        Open Noir, Sort my Downloads, Undo sorting, Quit
"""

from __future__ import annotations

import math
from collections.abc import Callable

ICON_SIZE = 64
INK, DOTS = (0, 0, 0, 255), (196, 180, 204, 255)  # the app's black and lilac


def tray_picture(size: int = ICON_SIZE):
    """A small black disc shaded with print dots, as in the rest of the app. Drawn
    at any size: the packaged app's icon is the same picture, big (packaging/make_icons.py)."""
    from PIL import Image, ImageDraw

    scale = size / ICON_SIZE
    picture = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(picture)
    draw.ellipse((2 * scale, 2 * scale, size - 3 * scale, size - 3 * scale), fill=INK)
    middle, step = size / 2, 7.0 * scale
    for row in range(12):
        y = 4 * scale + row * step * 0.866
        for column in range(12):
            x = 4 * scale + column * step + (step / 2 if row % 2 else 0)
            if math.hypot(x - middle, y - middle) > size * 0.42:
                continue
            light = max(0.0, 1 - math.hypot(x - size * 0.36, y - size * 0.32) / (size * 0.72))
            radius = math.sqrt(light) * step * 0.62
            if radius > 0.6 * scale:
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=DOTS)
    return picture


class Tray:
    def __init__(self, open_app: Callable[[], None], quit_app: Callable[[], None], watch=None):
        import pystray

        def run(action: Callable[[], None]):
            return lambda _icon, _item: action()

        items = [pystray.MenuItem("Open Noir", run(open_app), default=True)]
        if watch:
            items += [pystray.Menu.SEPARATOR,
                      pystray.MenuItem("Sort my Downloads", run(watch.sort_now)),
                      pystray.MenuItem("Undo sorting", run(watch.undo), enabled=lambda _item: watch.can_undo())]
        items += [pystray.Menu.SEPARATOR, pystray.MenuItem("Quit", run(quit_app))]
        self._icon = pystray.Icon("Noir", tray_picture(), "Noir", pystray.Menu(*items))

    def start(self) -> None:
        self._icon.run_detached()

    def refresh(self) -> None:
        """Whether Undo sorting can be clicked may have changed."""
        self._icon.update_menu()

    def stop(self) -> None:
        self._icon.stop()
