"""The chores list: what the app takes care of on its own, and what it did lately,
the way the Notes app lists things, newest day first. Drawn by the drawer and by the
Chores page in the main window, from the same plain data.

A chore is anything that runs without being asked in the chat: keeping Downloads
tidy (tidy.py), a switch-on agent that reads highlights (quick/agents.py), or a
booking (reservations.py). Nothing here decides anything; it only puts together what
those already know.
"""

from __future__ import annotations

import time
from datetime import datetime

TIDY, AGENT, BOOKING = "tidy", "agent", "booking"
MAX_JOBS = 60  # finished jobs listed, newest first
REPEAT_WORDS = {"once": "once", "daily": "every day", "weekly": "every week"}
ACTION_WORDS = {"sort": "Sort Downloads", "run": "Ask", "turn_on": "Switch on", "turn_off": "Switch off"}


def listing(today: dict, done: list[dict], agents: list[dict], bookings: list[dict], now: float | None = None) -> dict:
    """{"chores": [...], "days": [...]} for the pages. today is TidyWatch.today(), done the
    jobs done lately (the watch's and the organizers'), agents the switch-on agents as the
    engine lists them (name, kind, on, how), bookings Reservations.listing()."""
    now = time.time() if now is None else now
    chores = [_tidy_chore(today, done, now)]
    for entry in agents:
        last = next((job for job in reversed(done) if job.get("agent") == entry["name"] and job.get("sort")), None)
        chores.append({"id": f"{AGENT}:{entry['name']}", "kind": AGENT, "name": entry["name"],
                       "on": bool(entry.get("on")), "how": entry.get("how", ""),
                       "last": f"{last['text']} · {ago(last['when'], now)}" if last else ""})
    for booking in bookings:
        chores.append(_booking_chore(booking))
    return {"chores": chores, "days": days(done, now), "noticed": today.get("noticed"), "working": today.get("working")}


def _tidy_chore(today: dict, done: list[dict], now: float) -> dict:
    last = next((job for job in reversed(done) if not job.get("agent") and (job.get("sort") or "Sorted" in job.get("text", ""))), None)
    return {"id": TIDY, "kind": TIDY, "name": "Keep Downloads tidy", "on": today.get("noticing") is True,
            "how": "When 30 or more loose files pile up, sort them into folders. Every sort can be undone for a week.",
            "last": f"{last['text']} · {ago(last['when'], now)}" if last else ""}


def _booking_chore(booking: dict) -> dict:
    what = ACTION_WORDS.get(booking.get("action", ""), booking.get("action", ""))
    agent = booking.get("agent") or ""
    name = f"{what} {agent}".strip() if what != "Sort Downloads" else what
    when = booking.get("when", "")
    try:
        at = datetime.fromisoformat(when).strftime("%a %H:%M") if when else ""
    except ValueError:
        at = when
    repeat = REPEAT_WORDS.get(booking.get("repeat", ""), booking.get("repeat", ""))
    how = " · ".join(part for part in (booking.get("text", ""), f"{repeat} at {at}".strip()) if part)
    return {"id": f"{BOOKING}:{booking.get('id', '')}", "kind": BOOKING, "name": name, "on": bool(booking.get("active", True)),
            "how": how, "last": "Missed: the app was closed" if booking.get("missed") else ""}


def days(done: list[dict], now: float) -> list[dict]:
    """Finished jobs grouped by day, newest first: Today, Yesterday, then the date."""
    groups: list[dict] = []
    for job in sorted(done, key=lambda item: item.get("when", 0), reverse=True)[:MAX_JOBS]:
        label = day_label(job.get("when", 0), now)
        if not groups or groups[-1]["day"] != label:
            groups.append({"day": label, "jobs": []})
        groups[-1]["jobs"].append({**job, "time": datetime.fromtimestamp(job.get("when", 0)).strftime("%H:%M")})
    return groups


def day_label(when: float, now: float) -> str:
    then, today = datetime.fromtimestamp(when).date(), datetime.fromtimestamp(now).date()
    gap = (today - then).days
    if gap <= 0:
        return "Today"
    if gap == 1:
        return "Yesterday"
    return then.strftime("%b %d").replace(" 0", " ")


def ago(when: float, now: float | None = None) -> str:
    """"just now", "12 min ago", "2 h ago", "3 days ago"."""
    seconds = max(0, (time.time() if now is None else now) - when)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    days_ago = int(seconds // 86400)
    return f"{days_ago} day{'' if days_ago == 1 else 's'} ago"
