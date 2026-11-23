"""The chores list: what the app takes care of on its own, and what it did lately,
the way the Notes app lists things, newest day first. Drawn by the drawer and by the
Chores page in the main window, from the same plain data.

A chore is anything that runs without being asked in the chat: keeping Downloads
tidy (tidy.py), a helper that works while it is switched on, or a booking
(reservations.py). Nothing here decides anything, and nothing here knows what any
helper is for: a helper's line is made of what the engine says about it (its name,
whether it is on, how it works in one sentence, what it is doing now, since when it
has been on, the last file it left alone, and why it is off when there is a reason
to give), whatever it is made of.
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
    jobs done lately (the watch's and the helpers'), agents the helpers that work while
    switched on, as the engine lists them (name, kind, on, how, and for one that keeps a
    record of its work: now, since, left, why_off), bookings Reservations.listing()."""
    now = time.time() if now is None else now
    chores = [_tidy_chore(today, done, now)]
    for entry in agents:
        # Its newest job, whether or not it can be undone: a note written about a file has
        # nothing to undo, and counted out for that, the line under a helper that had just
        # written one said nothing new had landed.
        last = next((job for job in reversed(done) if job.get("agent") == entry["name"]), None)
        # "kind" is the list's own (a helper, the watch, a booking), which the pages switch
        # and remove by; what kind of helper the engine calls it is not passed on.
        chores.append({"id": f"{AGENT}:{entry['name']}", "kind": AGENT, "name": entry["name"],
                       "on": bool(entry.get("on")), "how": entry.get("how", ""), "last": _last_line(entry, last, now)})
    for booking in bookings:
        chores.append(_booking_chore(booking))
    return {"chores": chores, "days": days(done, now), "noticed": today.get("noticed"), "working": today.get("working")}


def _last_line(entry: dict, last: dict | None, now: float) -> str:
    """The line under a chore: what it is doing this very moment when it is doing something
    (the engine's own words for it), else the last thing it did since it was switched on,
    else that it is on and nothing new has landed. The user once waited two minutes on a
    list that said nothing, unable to tell whether the agent was working or had seen the
    files. A helper the engine gives no "since" for keeps no such record, and has no line.
    One that is off for a reason the engine gives says that first, for as long as it is
    off: a helper that an update had switched off was simply "Off" in the list, and the one
    time the chat had said why was long scrolled away."""
    if entry.get("why_off") and not entry.get("on"):
        return f"Off: {entry['why_off']}"
    if entry.get("now"):
        return entry["now"]
    since = entry.get("since") or 0
    left = entry.get("left")  # the last file it looked at and left where it was, since then
    did = last if last and last.get("when", 0) >= since else None  # its last job since then
    if left and (did is None or left.get("when", 0) > did["when"]):
        return f"Left {left['name']} where it was: {left['why']} · {ago(left['when'], now)}"
    if did:
        return f"{did['text']} · {ago(did['when'], now)}"
    if entry.get("on") and since:
        return f"On since {clock_time(since, now)}. Nothing new has landed since."
    return f"{last['text']} · {ago(last['when'], now)}" if last else ""


def clock_time(when: float, now: float | None = None) -> str:
    """"1:10 AM" for today, "Nov 12, 9:40 PM" for another day."""
    then = datetime.fromtimestamp(when)
    hour = then.strftime("%I:%M %p").lstrip("0")
    today = datetime.fromtimestamp(time.time() if now is None else now).date()
    return hour if then.date() == today else f"{then.strftime('%b %d').replace(' 0', ' ')}, {hour}"


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
