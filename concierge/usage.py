"""How much of a plan or an API key Elaina's answers have used, for the meter beside
the model button and the Accounts page. Only numbers are kept: which plan or company,
which model, how many tokens, and the plan's own limits as its app reported them.
Never any words.

A plan's limits come from the plan's app itself, the same numbers Claude Code shows
on /usage: how much of the 5-hour window and of the week is used, and when each
starts again. Nothing is estimated here: a plan that doesn't report its limits
shows only the tokens counted on this computer.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import date, timedelta
from pathlib import Path

KEPT_DAYS = 31  # tokens are counted per day, for a month
# The plan windows we know by name, in the order they're shown.
WINDOWS = {"five_hour": "Next 5 hours", "seven_day": "This week",
           "seven_day_opus": "This week, Opus", "seven_day_sonnet": "This week, Sonnet"}
NEARLY_FULL = 0.8  # from here the meter turns amber

_lock = threading.Lock()
_memory: dict | None = None  # the practice app keeps its numbers here, never in a file


def usage_path() -> Path:
    from .elaina import data_dir
    return data_dir() / "usage.json"


def in_memory(on: bool = True) -> None:
    """The practice app: count in memory only."""
    global _memory
    _memory = {} if on else None


def _load() -> dict:
    if _memory is not None:
        return _memory
    try:
        return json.loads(usage_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    global _memory
    if _memory is not None:
        _memory = data
        return
    path = usage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def record_tokens(source: str, model: str, read: int, wrote: int, when: float | None = None) -> None:
    """One answer: `read` is everything the model read (the conversation, her persona,
    and for the apps their own instructions too), `wrote` is the answer."""
    when = time.time() if when is None else when
    day = date.fromtimestamp(when).isoformat()
    with _lock:
        data = _load()
        mine = data.setdefault(source, {})
        days = mine.setdefault("days", {})
        today = days.setdefault(day, {"read": 0, "wrote": 0, "answers": 0})
        today["read"] = today.get("read", 0) + max(0, int(read))
        today["wrote"] = today.get("wrote", 0) + max(0, int(wrote))
        today["answers"] = today.get("answers", 0) + 1
        oldest = (date.fromtimestamp(when) - timedelta(days=KEPT_DAYS)).isoformat()
        mine["days"] = {d: n for d, n in days.items() if d >= oldest}
        mine["last"] = {"model": model, "read": int(read), "wrote": int(wrote), "at": when}
        if read > 0:
            # The least it ever read for one answer: mostly the app's own instructions,
            # sent with every question however short (about 29k for Claude Code).
            mine["least_read"] = min(int(read), mine.get("least_read") or int(read))
        _save(data)


def record_saved(source: str, tokens: int, when: float | None = None) -> None:
    """An answer written on this computer that Auto could have sent to this plan or
    key: about how many of its tokens that kept."""
    if tokens <= 0:
        return
    when = time.time() if when is None else when
    day = date.fromtimestamp(when).isoformat()
    with _lock:
        data = _load()
        today = data.setdefault(source, {}).setdefault("days", {}).setdefault(day, {"read": 0, "wrote": 0, "answers": 0})
        today["saved"] = today.get("saved", 0) + int(tokens)
        _save(data)


def saved_estimate(source: str, read: int, wrote: int) -> int:
    """About what an answer written here would have cost from this plan or key: what
    her model read and wrote, plus what the plan's app reads on top of every question
    (measured from its real answers, never guessed; nothing before there's one)."""
    with _lock:
        least = (_load().get(source) or {}).get("least_read", 0)
    return max(int(read), int(least)) + int(wrote) if (read or wrote) else 0


def record_limits(source: str, windows: list[dict], when: float | None = None) -> None:
    """The plan's own limits, each {"id", "used" (0 to 1), "resets_at" (seconds)}."""
    if not windows:
        return
    with _lock:
        data = _load()
        data.setdefault(source, {})["limits"] = {"windows": windows, "at": time.time() if when is None else when}
        _save(data)


def summary(now: float | None = None) -> dict:
    """For the windows: per plan or company, its limits (dropped once a window has
    started again, since the number would be stale), tokens today and this week,
    and the last answer."""
    now = time.time() if now is None else now
    today = date.fromtimestamp(now)
    week_start = (today - timedelta(days=6)).isoformat()
    shown = {}
    with _lock:
        data = json.loads(json.dumps(_load()))  # a copy: the practice app's lives in memory
    for source, mine in data.items():
        days = mine.get("days", {})
        week = [n for d, n in days.items() if d >= week_start]
        windows = []
        for window in (mine.get("limits") or {}).get("windows", []):
            resets = window.get("resets_at") or 0
            used = 0.0 if resets and resets <= now else float(window.get("used") or 0)
            windows.append({"id": window["id"], "name": WINDOWS.get(window["id"], window.get("name") or window["id"]),
                            "used": round(min(max(used, 0.0), 1.0), 3), "resets_at": resets if resets > now else 0,
                            "nearly_full": used >= NEARLY_FULL})
        windows.sort(key=lambda w: list(WINDOWS).index(w["id"]) if w["id"] in WINDOWS else len(WINDOWS))
        shown[source] = {
            "limits": windows,
            "checked_at": (mine.get("limits") or {}).get("at", 0),
            "today": {"read": 0, "wrote": 0, "answers": 0, "saved": 0, **days.get(today.isoformat(), {})},
            "week": {key: sum(n.get(key, 0) for n in week) for key in ("read", "wrote", "answers", "saved")},
            "last": mine.get("last"),
        }
    return shown


def forget() -> None:
    with _lock:
        _save({})


# ------------------------------------------------- reading what the apps report


def claude_limits(event: dict) -> list[dict]:
    """Claude Code's rate_limit_event: the same windows its /usage screen shows."""
    info = event.get("rate_limit_info") or {}
    windows = info.get("unifiedWindows") or {}
    found = [{"id": key, "used": w.get("utilization") or 0, "resets_at": w.get("resetsAt") or 0}
             for key, w in windows.items() if isinstance(w, dict)]
    if not found and info.get("rateLimitType") and info.get("utilization") is not None:
        found = [{"id": info["rateLimitType"], "used": info["utilization"], "resets_at": info.get("resetsAt") or 0}]
    return found


def claude_tokens(event: dict) -> tuple[int, int]:
    """Claude Code's result event: what was read, cached parts included, and written."""
    used = event.get("usage") or {}
    read = (used.get("input_tokens") or 0) + (used.get("cache_creation_input_tokens") or 0) \
        + (used.get("cache_read_input_tokens") or 0)
    return read, used.get("output_tokens") or 0


def codex_limits(event: dict) -> list[dict]:
    """Codex's limits when it reports them: a primary (5-hour) and secondary (weekly)
    window, each with used_percent and when it starts again."""
    limits = event.get("rate_limits") or (event.get("info") or {}).get("rate_limits") or {}
    found = []
    for key, name in (("primary", "five_hour"), ("secondary", "seven_day")):
        w = limits.get(key)
        if not isinstance(w, dict) or w.get("used_percent") is None:
            continue
        resets = w.get("resets_at") or 0
        if not resets and w.get("resets_in_seconds") is not None:
            resets = time.time() + w["resets_in_seconds"]
        minutes = w.get("window_minutes") or 0
        found.append({"id": "seven_day" if minutes >= 24 * 60 else "five_hour" if minutes else name,
                      "used": w["used_percent"] / 100, "resets_at": resets})
    return found


def codex_tokens(event: dict) -> tuple[int, int]:
    """Codex's turn.completed: input_tokens already counts the cached part."""
    used = event.get("usage") or {}
    return used.get("input_tokens") or 0, used.get("output_tokens") or 0
