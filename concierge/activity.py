"""What Noir did for the user, counted, so Today can show what it's worth.

Only the kind of job and when it happened are kept, never the words, on this
computer, for a month. People keep tools whose value they can see, and a local
helper working quietly is easy to forget.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

ANSWERED, EXPLAINED, TRANSLATED, POLISHED, SUMMED_UP, HELPED, SORTED, READ = (
    "answered", "explained", "translated", "polished", "summed_up", "helped", "sorted", "read")
KEPT_DAYS = 30
WEEK_DAYS = 7
_lock = threading.Lock()


def _path() -> Path:
    from .noir import data_dir

    return data_dir() / "activity.json"


def _read() -> list[dict]:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def record(kind: str, count: int = 1, now: float | None = None) -> None:
    """One finished job. A full disk mustn't stop the job itself, so problems are swallowed."""
    now = time.time() if now is None else now
    with _lock:
        kept = [item for item in _read() if now - item["when"] < KEPT_DAYS * 86400]
        kept.append({"when": now, "kind": kind, "count": count})
        try:
            _path().parent.mkdir(parents=True, exist_ok=True)
            _path().write_text(json.dumps(kept), encoding="utf-8")
        except OSError:
            pass


def this_week(now: float | None = None) -> dict[str, int]:
    """How many of each kind of job in the last seven days."""
    now = time.time() if now is None else now
    counts: dict[str, int] = {}
    for item in _read():
        if now - item["when"] < WEEK_DAYS * 86400:
            counts[item["kind"]] = counts.get(item["kind"], 0) + item["count"]
    return counts
