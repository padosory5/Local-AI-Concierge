"""Pictures beside her answers: a photo of a place she names, from Wikipedia.

People look at a picture that shows something and skip one that only decorates, and
a picture helps most right beside the words it shows. So code only ever looks up
places: the bold names in her answer, never the user's own words, and only a
Wikipedia page that is a place (it has map coordinates), has a photo, and whose title
really is the name she wrote. A wrong picture is worse than none, so anything unsure
is left out. Nothing is looked up until the user says yes once (the page asks under
the first plan that names places), and each answer that looked counts on What I see.
"""

from __future__ import annotations

import re

import requests

from . import voice
from .cloud import record_sent

API = "https://{language}.wikipedia.org/w/api.php"
USER_AGENT = "LocalAIConcierge/0.1 (https://github.com/padosory5/elaina-agents)"
TIMEOUT = 4
MAX_PICTURES = 4
MAX_LOOKUPS = 8
PICTURE_PIXELS = 320
# Code, steps and choices are about doing something; a photo there only decorates.
NO_PICTURES = {"code", "how-to", "decide", "shorter"}
BOLD = re.compile(r"\*\*(.+?)\*\*")
# "Day 1:", "Morning ·", "1일차:" in front of the place a label names.
PART = re.compile(
    r"^\s*(?:(?:day|part|morning|afternoon|evening|night)\s*\d*|\d+\s*일\s*차?|첫째\s*날|둘째\s*날|셋째\s*날)"
    r"\s*[:·,\-–—]?\s*",
    re.IGNORECASE,
)
# Between two places in one label: "Haeundae and Gwangalli", "해운대와 광안리".
BETWEEN = re.compile(r"\s+(?:and|&|or)\s+|\s*[,/·+]\s*|(?<=[가-힣])(?:와|과|및)\s+")
# Words a page's title adds to the name she wrote: "Gwangalli" is "Gwangalli Beach".
PLACE_WORDS = {
    "beach", "market", "village", "park", "temple", "island", "tower", "mountain", "bridge", "station",
    "street", "museum", "palace", "castle", "lake", "river", "district", "city", "fortress", "square",
    "port", "harbor", "harbour", "hill", "falls", "national", "culture", "cultural", "the", "of",
}

_found: dict[str, dict | None] = {}  # names already looked up; a failed request is asked again later


def names_in(label: str) -> list[str]:
    """The place names a bold label might hold, most likely first."""
    label = PART.sub("", label).strip(" :.-")
    names = [name.strip() for name in BETWEEN.split(label) if name and name.strip()]
    # A place is a proper name: capitalised in English, or written in Hangul.
    return [name for name in names if name[0].isupper() or re.match(r"[가-힣]", name)][:3]


def _words(text: str) -> set[str]:
    return set(re.findall(r"[\w']+", text.lower()))


def same_place(name: str, title: str) -> bool:
    """Whether a page's title is the name she wrote, not just a page a search found."""
    title = re.sub(r"\s*\(.*?\)", "", title)
    if re.search(r"[가-힣]", name):
        return title.replace(" ", "").startswith(name.replace(" ", ""))
    core = _words(title) - PLACE_WORDS
    return bool(core) and core <= _words(name)


def place(name: str, get=requests.get) -> dict | None:
    """A photo of the place with this name, or None when there's no sure one."""
    if name in _found:
        return _found[name]
    language = "ko" if re.search(r"[가-힣]", name) else "en"
    try:
        reply = get(API.format(language=language), timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, params={
            "action": "query", "format": "json", "formatversion": 2, "redirects": 1,
            "generator": "search", "gsrsearch": name, "gsrlimit": 1,
            "prop": "pageimages|coordinates|description", "piprop": "thumbnail", "pithumbsize": PICTURE_PIXELS})
        reply.raise_for_status()
        pages = reply.json().get("query", {}).get("pages", [])
    except (requests.RequestException, ValueError):
        return None
    page = pages[0] if pages else {}
    picture = (page.get("thumbnail") or {}).get("source")
    found = None
    if picture and page.get("coordinates") and same_place(name, page.get("title", "")):
        found = {"title": page["title"], "image": picture, "about": page.get("description", ""),
                 "page": f"https://{language}.wikipedia.org/wiki/{page['title'].replace(' ', '_')}"}
    _found[name] = found
    return found


def worth_asking(question: str, reply: str) -> bool:
    """Whether to ask about photos under this answer: a plan that names places. Decided
    here, with nothing looked up, because nothing may be until the user says yes."""
    return voice.kind_of(question) == "plan" and any(names_in(label) for label in BOLD.findall(reply))


def for_answer(question: str, reply: str, look=place, sent=record_sent) -> list[dict]:
    """Photos for the places a reply names, each with the bold label it goes beside."""
    if voice.kind_of(question) in NO_PICTURES:
        return []
    shown, pages, lookups = [], set(), 0
    if any(name not in _found for label in BOLD.findall(reply) for name in names_in(label)):
        sent("Wikipedia", "photos of places")  # only who and when, as for cloud models
    for label in dict.fromkeys(BOLD.findall(reply)):
        for name in names_in(label):
            if lookups >= MAX_LOOKUPS:
                return shown
            lookups += 1
            found = look(name)
            if found and found["page"] not in pages:
                pages.add(found["page"])
                shown.append({"label": label, **found})
                break
        if len(shown) >= MAX_PICTURES:
            break
    return shown
