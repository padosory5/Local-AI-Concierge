"""A small icon by the clock, for what doesn't belong on the circle.

    click the icon        the full window opens
    right-click it        Open Elaina, Sort my Downloads, Undo sorting, Quit
"""

from __future__ import annotations

import math
from collections.abc import Callable

ICON_SIZE = 64
INK, DOTS = (0, 0, 0, 255), (196, 180, 204, 255)  # the app's black and lilac


def tray_picture():
    """A small black disc shaded with print dots, as in the rest of the app."""
    from PIL import Image, ImageDraw

    picture = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(picture)
    draw.ellipse((2, 2, ICON_SIZE - 3, ICON_SIZE - 3), fill=INK)
    middle, step = ICON_SIZE / 2, 7.0
    for row in range(12):
        y = 4 + row * step * 0.866
        for column in range(12):
            x = 4 + column * step + (step / 2 if row % 2 else 0)
            if math.hypot(x - middle, y - middle) > ICON_SIZE * 0.42:
                continue
            light = max(0.0, 1 - math.hypot(x - ICON_SIZE * 0.36, y - ICON_SIZE * 0.32) / (ICON_SIZE * 0.72))
            radius = math.sqrt(light) * step * 0.62
            if radius > 0.6:
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=DOTS)
    return picture


class Tray:
    def __init__(self, open_app: Callable[[], None], quit_app: Callable[[], None], watch=None):
        import pystray

        def run(action: Callable[[], None]):
            return lambda _icon, _item: action()

        items = [pystray.MenuItem("Open Elaina", run(open_app), default=True)]
        if watch:
            items += [pystray.Menu.SEPARATOR,
                      pystray.MenuItem("Sort my Downloads", run(watch.sort_now)),
                      pystray.MenuItem("Undo sorting", run(watch.undo), enabled=lambda _item: watch.can_undo())]
        items += [pystray.Menu.SEPARATOR, pystray.MenuItem("Quit", run(quit_app))]
        self._icon = pystray.Icon("Elaina", tray_picture(), "Elaina", pystray.Menu(*items))

    def start(self) -> None:
        self._icon.run_detached()

    def refresh(self) -> None:
        """Whether Undo sorting can be clicked may have changed."""
        self._icon.update_menu()

    def stop(self) -> None:
        self._icon.stop()
