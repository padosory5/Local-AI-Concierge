"""Which pages a research job reads: a judge between the search and the workers.

The other apps all put one here. Perplexity scores every result for authority and
relevance before the model sees a word; Open WebUI scores each piece of a page
against the question with a small model. Without one, two of six workers in the
first live runs read a blocked page and a content farm, and a brief leaned on one
supplement site. Here code scores first: the kind of site (sources.yaml, promoting
and never banning), whether the site is the subject's own, how many of the
question's words the snippet holds, and a date for a current question. Her small
model only breaks ties, in one call over all the snippets. The reasons for every
pick and drop are kept, so her thinking can say them.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

TIERS_PATH = Path(__file__).with_name("sources.yaml")
PRIMARY, REFERENCE, ORDINARY, FARM = "primary", "reference", "ordinary", "farm"
TIER_WORDS = {PRIMARY: "official", REFERENCE: "reference", ORDINARY: "other", FARM: "content farm"}
TIER_POINTS = {PRIMARY: 30, REFERENCE: 20, ORDINARY: 10, FARM: 0}
SUBJECT_POINTS = 12  # the subject's own site: "hermes-agent.nousresearch.com" for Hermes
MODEL_POINTS = 8  # her model said the snippet is about the question
FRESH_POINTS = 4  # this year in the snippet, for a question about now
MIN_SNIPPET_MATCH = 1  # question words a snippet must hold to be read without the model's yes
CURRENT_WORDS = re.compile(r"\b(now|current|currently|latest|newest|today|this (year|month|week)|recent|20[23]\d)\b"
                           r"|지금|현재|최신|올해", re.I)
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "at", "by", "with", "is", "are", "was", "were", "be",
    "it", "its", "this", "that", "what", "who", "how", "why", "when", "where", "which", "do", "does", "did", "can",
    "me", "my", "i", "you", "your", "we", "about", "into", "from", "as", "up", "right", "now", "research", "report",
    "write", "look", "find", "out", "tell", "give", "whether", "should", "safe", "new", "best", "vs", "versus",
    "조사해줘", "조사", "알려줘", "리서치", "보고서", "대해", "대한", "관련",
}
# A site name made for search engines: long, hyphen-heavy or numbered.
FARM_LOOKS = re.compile(r"^(?:[^.]*-){3,}[^.]*\.|^[^.]*\d{3,}[^.]*\.|^(?:best|top|cheap|free|easy)\w{0,12}-", re.I)

_tiers: dict[str, list[str]] | None = None


@dataclass
class Choice:
    row: dict
    site: str
    tier: str
    score: int
    kind: str = ""  # "official", "reference", "the subject's own site", "content farm", or "" for other
    reasons: list[str] = field(default_factory=list)
    picked: bool = False
    why_not: str = ""


def load_tiers() -> dict[str, list[str]]:
    global _tiers
    if _tiers is None:
        data = yaml.safe_load(TIERS_PATH.read_text(encoding="utf-8")) or {}
        _tiers = {tier: [str(p).lower() for p in patterns or []] for tier, patterns in (data.get("tiers") or {}).items()}
    return _tiers


def site_of(url: str) -> str:
    return re.sub(r"^www\.", "", re.sub(r"^https?://", "", url).split("/")[0]).lower()


def _matches(site: str, pattern: str) -> bool:
    if pattern.startswith("*."):
        base = pattern[2:]
        return site == base or site.endswith("." + base)
    return site == pattern


def words_of(text: str) -> set[str]:
    return {w for w in re.findall(r"[\w']+", text.lower()) if w not in STOPWORDS and len(w) > 1}


def _own_site(site: str, question: str) -> bool:
    """Whether the site's name is a proper name in the question, or two run together:
    python.org for Python, nousresearch.com for Nous Research. A name that merely
    contains the word (hermesatlas.com) is somebody else's site about it, and a
    plain word (creatine.my for creatine) is a seller's, so only capitalised words
    count: the subject's own site has a name, a topic doesn't."""
    labels = [label.replace("-", "") for label in site.split(".")[:-1] if label not in ("www", "docs", "blog", "en", "ko")]
    proper = [w.lower() for w in re.findall(r"\b[A-Z][\w]{2,}", question)]
    names = set(proper) | {a + b for a, b in zip(proper, proper[1:])}
    return any(label in names for label in labels if len(label) >= 4)


def tier_of(url: str, question: str = "") -> tuple[str, str]:
    """The kind of site, and the word for it: the yaml's tiers, else the subject's own
    site counts as primary, else a name that looks made for search engines as a farm."""
    site = site_of(url)
    for tier in (PRIMARY, REFERENCE, FARM):
        if any(_matches(site, pattern) for pattern in load_tiers().get(tier, [])):
            return tier, TIER_WORDS[tier]
    if question and _own_site(site, question):
        return PRIMARY, "the subject's own site"
    if FARM_LOOKS.search(site):
        return FARM, "looks made for search engines"
    return ORDINARY, ""


def relevance(question: str, title: str, body: str) -> int:
    """How many of the question's words the result's title and snippet hold."""
    return len(words_of(question) & words_of(f"{title} {body}"))


def pick(question: str, rows: list[dict], wanted: int = 6, per_site: int = 2, judge=None) -> list[Choice]:
    """Score every result, ask her model which snippets are about the question when
    there's one to ask, then take the best `wanted`, at most `per_site` from one site.
    Returns every choice, picked or not, with its reasons, best first."""
    current = bool(CURRENT_WORDS.search(question))
    year = str(time.localtime().tm_year)
    choices: list[Choice] = []
    seen: set[str] = set()
    for row in rows:
        url = row.get("href") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        tier, kind = tier_of(url, question)
        title, body = row.get("title") or "", row.get("body") or ""
        hits = relevance(question, title, body)
        score = TIER_POINTS[tier] + min(hits, 6) * 2
        reasons = [kind] if kind else []
        if kind.startswith("the subject"):
            score += SUBJECT_POINTS
        if hits:
            reasons.append(f"{hits} of the question's words")
        if current and year in f"{title} {body}":
            score += FRESH_POINTS
            reasons.append(f"mentions {year}")
        choices.append(Choice(row, site_of(url), tier, score, kind, reasons))
    if judge and len(choices) > 1:
        try:
            about = set(judge(question, [f"{c.row.get('title') or ''}: {c.row.get('body') or ''}" for c in choices]))
        except Exception:
            about = set()
        for number, choice in enumerate(choices):
            if number in about:
                choice.score += MODEL_POINTS
                choice.reasons.append("her model: about the question")
    choices.sort(key=lambda c: c.score, reverse=True)
    taken_per_site: dict[str, int] = {}
    taken = 0

    def about(choice: Choice) -> bool:
        return (relevance(question, choice.row.get("title") or "", choice.row.get("body") or "") >= MIN_SNIPPET_MATCH
                or "her model: about the question" in choice.reasons)

    # Two passes: first only results whose snippet is about the question (an official
    # page about something else once outranked every page that was about it), and
    # content farms last; then, if that left too few, the rest in order of score.
    for pass_number in (1, 2):
        for choice in choices:
            if choice.picked or choice.why_not:
                continue
            if taken >= wanted:
                choice.why_not = f"beyond the best {wanted}"
            elif taken_per_site.get(choice.site, 0) >= per_site:
                choice.why_not = "a third page from the same site"
            elif pass_number == 1 and not about(choice):
                continue  # looked at again in the second pass
            elif pass_number == 1 and choice.tier == FARM and taken >= 3:
                continue
            else:
                choice.picked = True
                taken += 1
                taken_per_site[choice.site] = taken_per_site.get(choice.site, 0) + 1
        if taken >= min(3, wanted):
            break
    for choice in choices:
        if not choice.picked and not choice.why_not:
            choice.why_not = ("a content farm, and better pages were found" if choice.tier == FARM
                              else "nothing about the question in its snippet")
    return choices


JUDGE_NOTE = ("You are given a question and numbered search results. Reply with the numbers of the results that "
              "are about the question, in a form. Leave out results about something else.")
JUDGE_SCHEMA = {"type": "object", "properties": {"about": {"type": "array", "items": {"type": "integer"}}},
                "required": ["about"]}


def judge_with(ask_form):
    """Her model as the tie-break: `ask_form(system, user, schema)` fills the form."""

    def judge(question: str, snippets: list[str]) -> set[int]:
        listed = "\n".join(f"{number}. {snippet[:300]}" for number, snippet in enumerate(snippets))
        filled = ask_form(JUDGE_NOTE, f"QUESTION: {question}\n\nRESULTS:\n{listed}", JUDGE_SCHEMA) or {}
        return {int(n) for n in filled.get("about", []) if isinstance(n, (int, float)) and 0 <= int(n) < len(snippets)}

    return judge


def said(choices: list[Choice]) -> tuple[str, str]:
    """Two plain lines for her thinking: what was picked and why, what was dropped and why."""
    picked = [c for c in choices if c.picked]
    dropped = [c for c in choices if not c.picked]
    kept = ", ".join(f"{c.site} ({c.kind or (c.reasons[0] if c.reasons else 'other')})" for c in picked)
    gone = ", ".join(f"{c.site} ({c.why_not})" for c in dropped[:4])
    more = f", and {len(dropped) - 4} more" if len(dropped) > 4 else ""
    return (f"Picked {len(picked)} of {len(choices)} pages: {kept}.",
            f"Left out: {gone}{more}." if dropped else "")
