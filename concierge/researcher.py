"""A research job, shared between the plan model and her own model.

"Research X" is more than one lookup. Her own small model turns the request into a
few searches (a form, forced by the schema: its queries were as good as Claude's in
the first live run, in a sixth of the time and for none of the plan), code runs the
searches and reads the pages, all at once, her model reads each page and writes a
short summary of what it says about the question, one page at a time, which is the
kind of job a 4B model does well and the part that eats the most tokens, and the plan
model (Claude or GPT through the user's plan, or a keyed model) is the reviewer: it
merges the summaries into one brief and checks them against each other. With Auto
that is the plan's fast model, since a merge needs care more than depth and Opus took
15 of the first run's 37 seconds; a model the user picked on purpose is used as it is.
Every step is said in her thinking, with its tokens, and the end says what the plan
was charged against what it would have been charged had it done every step itself,
counted from its own measured numbers.

Without a plan connected, her own model merges too, and the brief says so.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

from . import research, usage, voice
from .elaina import without_closing_filler
from .events import Source

_I = re.IGNORECASE
RESEARCH = "research"
RESEARCH_WORDS = re.compile(
    r"\b(research|look into|investigate|dig into|deep dive|find out (everything|all|more) about|"
    r"(write|make|give|do|put together) (me )?(a |an )?(report|brief|briefing|overview|rundown|summary of what)"
    r" (on|about|of)|what do we know about|everything about|gather (sources|articles|information) (on|about))\b"
    r"|조사해|리서치|보고서 (써|만들)|자세히 알아봐", _I)
MAX_QUERIES = 4
PAGES_PER_QUERY = 2
MAX_PAGES = 6
SUMMARY_LINES = 6
SINGLE_ASK_WRITTEN = 400  # about what one plain answer is, for the comparison line
SEARCH_WAIT = 10  # seconds for all the searches together, then all the page reads
ENOUGH_SEARCHES = 2  # searches that answered before a refused one is retried alone
PAGES_PER_SITE = 2  # three of six pages from one supplement site made one brief lean on it
# Her model doesn't know the date: left to itself it searched "Seattle housing 2024" in
# November 2026 and the brief could only say the pages were two years old.
PLAN_NOTE = (
    "Today is {today}. You plan a web research job for an assistant. Turn the user's request into 2 to {max} "
    "short search queries that together cover it (different angles, the newest facts first; anything current "
    "means {year}, never an older year), and one line saying what the brief must answer.")
STALE_YEAR = re.compile(r"\b(20[12]\d)\b")
PLAN_SCHEMA = {
    "type": "object",
    "properties": {"queries": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": MAX_QUERIES},
                   "goal": {"type": "string"}},
    "required": ["queries", "goal"],
}
WORKER_NOTE = (
    "You are given the text of one web page and a question. Write up to {lines} short lines, one fact per "
    "line, with the numbers, names and dates the page gives about the question. Only what this page says, "
    "nothing from memory. If the page says nothing about the question, reply exactly: NOTHING RELEVANT.")
MERGE_NOTE = (
    "You are the reviewer of a research job. Below are summaries written by a small local model, one per "
    "web page, each with the page it came from, and the question. Write the brief for the user:\n"
    "- Start with the answer in one or two plain sentences, then the points that matter, each starting with "
    "its key words in bold, at most 8.\n"
    "- Use only what the summaries say. Drop a claim only one weak page makes if a stronger one contradicts "
    "it, and say so in one line where sources disagree.\n"
    "- Name a source by its site in brackets after the point it supports, like (python.org).\n"
    "- End with one line starting \"Not found:\" for anything the question asked that the pages didn't say, "
    "or leave it out if nothing is missing.\n"
    "- It is {when} now; say \"as of\" that when a fact can change.\n"
    "- No headings, tables or emoji. Under {words} words, in the language the user wrote in.")


@dataclass
class Page:
    url: str
    title: str
    text: str
    summary: str = ""
    read: int = 0
    wrote: int = 0

    @property
    def site(self) -> str:
        return re.sub(r"^www\.", "", re.sub(r"^https?://", "", self.url).split("/")[0])

    @property
    def useful(self) -> bool:
        return bool(self.summary) and "NOTHING RELEVANT" not in self.summary.upper()


@dataclass
class Account:
    """What the job cost, in tokens, counted not guessed."""

    source: str = ""  # the plan or key it ran on, "" when her own model did it all
    plan_calls: int = 0
    plan_read: int = 0
    plan_wrote: int = 0
    local_calls: int = 0
    local_read: int = 0
    local_wrote: int = 0
    if_all_plan: int = 0  # what every step would have cost on the plan
    single_ask: int = 0  # one plain question to the plan, no web

    @property
    def plan_tokens(self) -> int:
        return self.plan_read + self.plan_wrote

    @property
    def saved(self) -> int:
        return max(0, self.if_all_plan - self.plan_tokens)


def wants_research(text: str) -> bool:
    return bool(RESEARCH_WORDS.search(text))


# ---------------------------------------------------------------- the steps


def _json_in(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(match.group(0)) if match else {}
    except ValueError:
        return {}


def fresh_queries(queries: list[str], question: str, year: int | None = None) -> list[str]:
    """A query's year is this year, unless the question itself named one: her model's
    sense of "now" stops at its training."""
    year = year or time.localtime().tm_year
    if STALE_YEAR.search(question):
        return queries
    return [STALE_YEAR.sub(lambda m: str(year) if int(m.group(1)) < year else m.group(1), q) for q in queries]


def plan(ask_form, question: str, today: str = "") -> tuple[list[str], str]:
    """The searches and the goal, as a form her model fills. `ask_form(system, user,
    schema)` returns the filled form as a dict (or a string holding JSON, from a model
    without forced schemas). Nothing usable means one search: the question."""
    today = today or time.strftime("%A %Y-%m-%d")
    reply = ask_form(PLAN_NOTE.format(max=MAX_QUERIES, today=today, year=today.split("-")[0][-4:]), question,
                     PLAN_SCHEMA)
    data = reply if isinstance(reply, dict) else _json_in(str(reply))
    queries = [str(q).strip() for q in data.get("queries", []) if str(q).strip()][:MAX_QUERIES]
    queries = fresh_queries(queries, question, int(today.split("-")[0][-4:]))
    return (queries or [question]), str(data.get("goal") or question).strip()


def _all_at_once(jobs: dict, call, wait: float) -> dict:
    """Run call(value) for every key at the same time; a job that fails or is late is
    left out, and the rest still count."""
    done: dict = {}

    def run(key, value):
        try:
            done[key] = call(value)
        except Exception:
            pass

    threads = [threading.Thread(target=run, args=(key, value), daemon=True) for key, value in jobs.items()]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(wait)
    return done


def gather(queries: list[str], search=research.search, read=research.read_page) -> list[Page]:
    """The pages the searches find, read, without repeats, at most MAX_PAGES. All the
    searches run at once, then all the page reads: one after another they were a third
    of the job. A search that answered nothing to the burst is tried once more alone,
    since the free path sometimes refuses several at a time."""
    found = _all_at_once({query: query for query in queries}, search, SEARCH_WAIT)
    if sum(1 for query in queries if found.get(query)) < ENOUGH_SEARCHES:
        for query in queries:  # too few answered: the refused ones once more, alone
            if not found.get(query):
                try:
                    found[query] = search(query)
                except Exception:
                    found[query] = []
    chosen: list[tuple[str, dict]] = []  # (url, row) in the order the searches rank them
    seen: set[str] = set()
    per_site: dict[str, int] = {}
    for query in queries:
        taken = 0
        for row in found.get(query) or []:
            url = row.get("href") or ""
            site = re.sub(r"^www\.", "", re.sub(r"^https?://", "", url).split("/")[0])
            if (not url or url in seen or research.SKIP_PAGES.search(url) or len(chosen) >= MAX_PAGES
                    or per_site.get(site, 0) >= PAGES_PER_SITE):
                continue
            seen.add(url)
            per_site[site] = per_site.get(site, 0) + 1
            chosen.append((url, row))
            taken += 1
            if taken >= PAGES_PER_QUERY:
                break
    words = _all_at_once({url: url for url, _ in chosen}, read, SEARCH_WAIT)
    pages = []
    for url, row in chosen:
        text = (words.get(url) or "") or (row.get("body") or "")
        if text.strip():
            pages.append(Page(url, (row.get("title") or "").strip(), text))
    return pages


def summarise(ollama, model: str, question: str, page: Page) -> Page:
    """One worker: her model reads one page and writes what it says about the question."""
    messages = [{"role": "system", "content": WORKER_NOTE.format(lines=SUMMARY_LINES)},
                {"role": "user", "content": f"QUESTION: {question}\n\nPAGE ({page.site}):\n{page.text}"}]
    chunks = ollama.chat(model, messages, think=False, options={"temperature": 0.2}, keep_alive="60s")
    page.summary = "".join(chunks).strip()
    page.read, page.wrote = getattr(ollama, "last_tokens", (0, 0))
    return page


def merge(talk, question: str, goal: str, pages: list[Page], when: str) -> Iterator[str]:
    """The reviewer writes the brief from the workers' summaries. `talk(system, user)`
    streams the reply; it comes out in Elaina's shape."""
    words = voice.BUDGETS["plan"][0]
    useful = [page for page in pages if page.useful]
    notes = "\n\n".join(f"[{number}] {page.site} ({page.url})\n{page.summary}" for number, page in enumerate(useful, 1))
    user = f"QUESTION: {question}\nWHAT THE BRIEF MUST ANSWER: {goal}\n\nSUMMARIES:\n{notes}"
    chunks = talk(MERGE_NOTE.format(when=when, words=words), user)
    yield from voice.tidy(without_closing_filler(chunks))


# ---------------------------------------------------------------- counting


def plan_tokens_after(source: str, before: dict) -> tuple[int, int]:
    """What the plan's app reported for the call just made: its `last` answer in the
    usage records, if it's a new one (the apps report read and written exactly)."""
    last = (usage.summary().get(source) or {}).get("last") or {}
    if not last or last == before:
        return 0, 0
    return int(last.get("read", 0)), int(last.get("wrote", 0))


def last_plan_answer(source: str) -> dict:
    return dict((usage.summary().get(source) or {}).get("last") or {})


def settle(account: Account, question: str) -> Account:
    """What every step would have cost on the plan: each local step as one plan call,
    counted as her model's read and written tokens plus what the plan's app reads on
    top of every question (measured from its real answers), the way the Saved line
    under an answer counts. Tokens are her model's counts; the plan's own tokenizer
    would count a little differently, so it's "about"."""
    if not account.source:
        return account
    local_as_plan = 0
    if account.local_calls:
        per_call_read = account.local_read / account.local_calls
        per_call_wrote = account.local_wrote / account.local_calls
        local_as_plan = sum(usage.saved_estimate(account.source, int(per_call_read), int(per_call_wrote))
                            for _ in range(account.local_calls))
    account.if_all_plan = account.plan_tokens + local_as_plan
    account.single_ask = usage.saved_estimate(account.source, max(1, len(question) // 4), SINGLE_ASK_WRITTEN)
    return account


def account_lines(account: Account, orchestrator: str, own: str) -> list[str]:
    """The tokens, said plainly, for the end of her thinking."""
    if not account.source:
        return [f"Tokens: {own} did every step on this computer, {account.local_calls + account.plan_calls} calls, "
                f"{account.local_read + account.plan_read:,} read and {account.local_wrote + account.plan_wrote:,} "
                "written. Nothing went to a plan."]
    calls = f"{account.plan_calls} call{'s' if account.plan_calls != 1 else ''}"
    return [
        f"Tokens on your plan: {calls} to {orchestrator}, {account.plan_read:,} read and "
        f"{account.plan_wrote:,} written, {account.plan_tokens:,} in all.",
        f"On this computer: {account.local_calls} calls to {own}, {account.local_read:,} read and "
        f"{account.local_wrote:,} written, free.",
        f"Had {orchestrator} done every step itself: about {account.if_all_plan:,} tokens "
        f"({account.plan_calls + account.local_calls} calls, each carrying its app's own instructions, measured).",
        f"Saved about {account.saved:,} tokens of your plan. For comparison, one plain question to {orchestrator} "
        f"with no web reading is about {account.single_ask:,}.",
    ]


def when_now() -> str:
    return time.strftime("%A %Y-%m-%d %H:%M")


def sources_of(pages: list[Page]) -> list[Source]:
    return [Source(page.url, page.title or page.site) for page in pages if page.useful]


__all__ = ["RESEARCH", "RESEARCH_WORDS", "MAX_QUERIES", "PAGES_PER_QUERY", "MAX_PAGES", "SUMMARY_LINES",
           "SINGLE_ASK_WRITTEN", "SEARCH_WAIT", "ENOUGH_SEARCHES", "PAGES_PER_SITE", "PLAN_NOTE", "PLAN_SCHEMA",
           "STALE_YEAR", "WORKER_NOTE", "MERGE_NOTE", "Page", "Account", "wants_research", "fresh_queries",
           "plan", "gather", "summarise", "merge", "plan_tokens_after", "last_plan_answer", "settle",
           "account_lines", "when_now", "sources_of"]
_ = field  # dataclass fields above use defaults only; field is kept for the same import style as the others
