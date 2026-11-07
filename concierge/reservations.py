"""Reservations: work the user books for an agent at a time of their choosing.

An agent can be asked to do something, a switch-on agent can be turned on or off,
and the Downloads folder can be sorted, once or again and again.

They only run while Noir is running. Something booked for while it was closed
is never run late without asking, because moving files or answering hours later
could surprise someone; a one-time booking is marked as missed instead.
"""

from __future__ import annotations

import json
import secrets
import threading
import traceback
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

SORT, RUN, TURN_ON, TURN_OFF = "sort", "run", "on", "off"
ONCE, DAILY, WEEKLY = "once", "daily", "weekly"
CHECK_SECONDS = 15
STEPS = {DAILY: timedelta(days=1), WEEKLY: timedelta(days=7)}


class ReservationError(ValueError):
    """Written for the user."""


@dataclass
class Reservation:
    id: str
    agent: str  # empty for sorting Downloads
    action: str
    text: str  # what to ask the agent
    when: str  # the next time, like 2026-11-02T09:00
    repeat: str = ONCE
    active: bool = True
    missed: bool = False
    last_run: str = ""


def _time(text: str) -> datetime:
    return datetime.fromisoformat(text)


class Reservations:
    """path=None keeps them in memory, for the practice run and tests."""

    def __init__(self, path: Path | None = None):
        self.path = path
        self.items: list[Reservation] = self._read()
        self._lock = threading.Lock()
        self._stopping = threading.Event()

    def _read(self) -> list[Reservation]:
        if self.path is None:
            return []
        try:
            return [Reservation(**item) for item in json.loads(self.path.read_text(encoding="utf-8"))]
        except (OSError, ValueError, TypeError):
            return []

    def _save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps([asdict(item) for item in self.items], indent=1), encoding="utf-8")

    def add(self, agent: str, action: str, text: str, when: str, repeat: str = ONCE,
            now: datetime | None = None) -> Reservation:
        try:
            moment = _time(when)
        except ValueError:
            raise ReservationError("Please pick a date and time.") from None
        if moment <= (now or datetime.now()):
            raise ReservationError("Please pick a time in the future.")
        if action == RUN and not text.strip():
            raise ReservationError("Please say what the agent should do.")
        if action != SORT and not agent:
            raise ReservationError("Please pick an agent.")
        item = Reservation(secrets.token_hex(4), agent, action, text.strip(), moment.isoformat(timespec="minutes"), repeat)
        with self._lock:
            self.items.append(item)
            self._save()
        return item

    def remove(self, id: str) -> None:
        with self._lock:
            self.items = [item for item in self.items if item.id != id]
            self._save()

    def set_active(self, id: str, on: bool, now: datetime | None = None) -> None:
        """Switching one back on carries on from its next time, not a past one."""
        with self._lock:
            for item in self.items:
                if item.id == id:
                    item.active = on
                    if on:
                        self._roll_forward(item, now or datetime.now())
            self._save()

    def listing(self) -> list[dict]:
        """Soonest first, for the page."""
        return [asdict(item) for item in sorted(self.items, key=lambda item: (not item.active, item.when))]

    @staticmethod
    def _roll_forward(item: Reservation, now: datetime) -> None:
        step = STEPS.get(item.repeat)
        if step:
            moment = _time(item.when)
            while moment <= now:
                moment += step
            item.when = moment.isoformat(timespec="minutes")

    def catch_up(self, now: datetime | None = None) -> None:
        """Run when the app opens: nothing booked for while it was closed runs late."""
        now = now or datetime.now()
        with self._lock:
            for item in self.items:
                if item.active and _time(item.when) <= now:
                    if item.repeat == ONCE:
                        item.active, item.missed = False, True
                    else:
                        self._roll_forward(item, now)
            self._save()

    def take_due(self, now: datetime | None = None) -> list[Reservation]:
        """What's due now. Each is moved on first, so it can never run twice."""
        now = now or datetime.now()
        due = []
        with self._lock:
            for item in self.items:
                if item.active and _time(item.when) <= now:
                    due.append(Reservation(**asdict(item)))
                    item.last_run = now.isoformat(timespec="minutes")
                    if item.repeat == ONCE:
                        item.active = False
                    else:
                        self._roll_forward(item, now)
            if due:
                self._save()
        return due

    def start(self, run: Callable[[Reservation], None], changed: Callable[[], None] = lambda: None) -> None:
        self.catch_up()
        threading.Thread(target=self._watch, args=(run, changed), name="reservations", daemon=True).start()

    def stop(self) -> None:
        self._stopping.set()

    def _watch(self, run: Callable[[Reservation], None], changed: Callable[[], None]) -> None:
        while not self._stopping.wait(CHECK_SECONDS):
            for item in self.take_due():
                try:
                    run(item)
                except Exception:
                    traceback.print_exc()  # one bad job must not stop the others
                changed()
