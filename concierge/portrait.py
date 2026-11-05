"""What Elaina understands about the user from their past chats with ChatGPT and
Claude (history.py): what they ask for most, in which language, and who they are.

Code counts: how many chats, since when, in which languages, at what time of day,
and how many of each kind. Her model does only two small jobs. It sorts each chat
into one kind from a fixed list, and it suggests facts about the person, each
with the exact words they came from. Code drops a fact whose words aren't really
in the messages, and anything about health, money, beliefs, politics, family or
relationships, which aren't hers to work out. The user keeps or drops every fact,
and only kept facts reach her prompt, and only her own model on this computer:
what she knows about someone never goes to a cloud model.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .elaina import data_dir
from .history import PastChat
from .ollama import Ollama
from .quick.translate import LANGUAGES as LANGUAGE_NAMES
from .signs import THIS_COMPUTER
from .quick.translate import looks_like

# id: (what it's called, the Help me line in today.js it points to, "" for none)
KINDS = {
    "writing": ("Writing and polishing messages", "spot"),
    "translating": ("Translating", "translate"),
    "explaining": ("Explaining things", "explain"),
    "studying": ("Studying and homework", "explain"),
    "summarizing": ("Summing up long text", "sum"),
    "coding": ("Code and errors", "spot"),
    "documents": ("Work documents and files", "files"),
    "planning": ("Plans and ideas", "plan"),
    "advice": ("Advice and everyday questions", ""),
    "creative": ("Stories, games and fun", ""),
    # Health, money and relationships are counted under one plain name and never
    # looked into: knowing someone asks about them is enough to be careful.
    "personal": ("Personal matters", ""),
    "other": ("Other", ""),
}
KIND_MEANINGS = (
    "writing: writing or polishing an email, message, post, essay, resume, review reply or interview answer\n"
    "translating: translating text between languages\n"
    "explaining: explaining a word, idea or how something works\n"
    "studying: homework, exams, learning a subject or a language\n"
    "summarizing: summing up an article, document, video or meeting\n"
    "coding: programming, code, errors, software tools, apps and games being built\n"
    "documents: work documents, spreadsheets, slides, reports, files\n"
    "planning: plans, schedules, trips, ideas, decisions\n"
    "advice: everyday life: shopping, gifts, places to go, recommendations, how to do things at home\n"
    "creative: stories, poems, games, jokes, role play\n"
    "personal: health, money, investing, relationships, feelings\n"
    "other: anything else"
)
ABOUT = ("work", "study", "place", "language", "interest", "tool", "goal")
MAX_SORTED = 400  # the newest chats; older ones say less about who someone is now
SORT_BATCH = 20
SORT_PREVIEW_CHARS = 160
MAX_SNIPPETS = 60  # lines where the person talks about themselves
SNIPPET_CHARS = 280
FACT_BATCH = 8
MAX_FACTS = 12
# One line about a project otherwise became four "facts", three of them its details.
FACTS_PER_LINE = 2
QUOTE_MIN_CHARS = 6
FACT_MAX_CHARS = 140
# The person talking about themselves: where facts about them can come from.
SELF_WORDS = re.compile(
    r"\b(i am|i'm|im|i work|i worked|i study|i studied|i teach|i run|i own|i live|i'm from|i come from"
    r"|my job|my work|my company|my team|my boss|my manager|my class|my major|my school|my university"
    r"|my professor|my hobby|my project|my business|my shop|my store|my students|my customers"
    r"|i like|i love|i enjoy|i prefer|i use|i usually|i want to|i plan|work as a|working as a|job as a)\b"
    # "I have an exam" says something about them; "I have to integrate this" is a task.
    r"|\bi have (?!to\b)"
    r"|저는|나는|제가|내가|저희|우리 회사|우리 팀|제 직업|직업이|전공|학생인데|회사에서|학교에서|일하고|살고 있|취미",
    re.IGNORECASE,
)
# Not hers to work out, even when someone mentions it.
SENSITIVE = re.compile(
    r"health|doctor|hospital|sick|illness|disease|diagnos|medic|pill|pregnan|therap|depress|anxiety|cancer"
    r"|headache|\bpain|fever|\bhurts?\b"
    r"|disorder|adhd|autis|surgery|salary|debt|loan|bank|invest|stock|crypto|income|tax|religio|church|pray"
    r"|\bgod\b|faith|politic|election|\bvote|party member|boyfriend|girlfriend|\bwife|husband|dating|divorce"
    r"|\bsex|\bgay\b|lesbian|marriage|breakup|\bson\b|daughter|\bkids?\b|children|pregnant"
    r"|병원|아파|우울|약을|월급|대출|빚|주식|코인|교회|종교|정치|선거|남자친구|여자친구|이혼|연애|결혼|아들|딸",
    re.IGNORECASE,
)
# "The user works as a nurse" and "They work as a nurse" are both shown as
# "Works as a nurse": the same line reads right on her page and in her prompt.
SUBJECT = re.compile(r"^(the user|the person|user|they|he|she)\s+", re.IGNORECASE)
# A fact that's really a request: "Requests course layouts", "Asks about loops".
ASKING = re.compile(r"^(requests|asks|seeks|wants help|needs help|looks for|tries to)\b", re.IGNORECASE)
PARTS_OF_DAY = (("at night", 0, 5), ("in the morning", 5, 12), ("in the afternoon", 12, 17),
                ("in the evening", 17, 22), ("at night", 22, 24))
SCRIPTS = ("Korean", "Japanese", "Chinese", "Russian", "Arabic", "Thai", "Hindi")
# Enough everyday English words that a request in English nearly always has one.
ENGLISH_WORDS = re.compile(
    r"\b(i|i'm|my|me|you|your|the|a|an|and|or|is|are|was|to|of|in|on|for|with|this|that|it|how|what|why"
    r"|can|could|do|does|make|help|write|explain|give|fix|translate|please)\b", re.IGNORECASE)


def portrait_path() -> Path:
    return data_dir() / "portrait.json"


def load() -> dict:
    try:
        return json.loads(portrait_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def forget() -> None:
    portrait_path().unlink(missing_ok=True)


def understand(ollama: Ollama, model: str, chats: list[PastChat], think: bool | None = None,
               progress: Callable[[str], None] | None = None) -> dict:
    """Read the brought-in chats and save what she understands. Facts the user
    already kept or dropped stay that way, so reading a newer download never asks
    about the same thing twice."""
    say = progress or (lambda text: None)
    chats = sorted(chats, key=lambda chat: chat.when, reverse=True)
    newest = chats[:MAX_SORTED]
    say(f"Sorting {len(newest)} chats by what they asked for...")
    kinds = sort_kinds(ollama, model, newest, think)
    say("Looking for what you said about yourself...")
    facts = find_facts(ollama, model, chats, think)
    earlier = load()
    before = {fact["id"]: fact.get("kept") for fact in earlier.get("facts", [])}
    for fact in facts:
        fact["kept"] = before.get(fact["id"])
    from_computer = [fact for fact in earlier.get("facts", []) if fact.get("source") == THIS_COMPUTER]
    made = {
        **earlier,
        "made": time.time(),
        "chats": dict(Counter(chat.source for chat in chats)),
        "first": min(chat.when for chat in chats if chat.when) if any(c.when for c in chats) else 0,
        "last": max(chat.when for chat in chats),
        "busiest": busiest_part_of_day(chats),
        "languages": languages_used(chats),
        "kinds": kinds,
        "facts": facts + from_computer,
    }
    _save(made)
    return made


def add_computer(summary: dict, facts: list[dict]) -> dict:
    """What looking around this computer found (signs.py), beside what came from
    chats. A fact already kept or dropped stays that way."""
    made = load()
    before = {fact["id"]: fact.get("kept") for fact in made.get("facts", [])}
    for fact in facts:
        fact["kept"] = before.get(fact["id"])
    from_chats = [fact for fact in made.get("facts", []) if fact.get("source") != THIS_COMPUTER]
    made.update({"computer": summary, "facts": from_chats + facts})
    _save(made)
    return made


def keep(fact_id: str, kept: bool) -> dict:
    made = load()
    for fact in made.get("facts", []):
        if fact["id"] == fact_id:
            fact["kept"] = bool(kept)
    if made:
        _save(made)
    return made


def about_you(made: dict) -> str:
    """The few lines her own model reads about the user: only what they kept,
    what they ask for most, and the language they write in."""
    kept = [fact["fact"] for fact in made.get("facts", []) if fact.get("kept")]
    kinds = [kind for kind in made.get("kinds", []) if kind["id"] not in ("other", "personal")][:3]
    language = next(iter(made.get("languages", {})), "")
    if not kept and not kinds:
        return ""
    lines = ["WHAT YOU KNOW ABOUT THE USER (from their past chats with other AI tools, kept by them)"]
    lines += [f"- {fact}" for fact in kept]
    if kinds:
        lines.append("- Asked other AI tools most for: " + ", ".join(kind["words"].lower() for kind in kinds))
    if language:
        lines.append(f"- Usually writes in {language}")
    return "\n".join(lines)


# --------------------------------------------------------- counted by code


def busiest_part_of_day(chats: list[PastChat]) -> str:
    hours = Counter(datetime.fromtimestamp(chat.when).hour for chat in chats if chat.when)
    parts = Counter()
    for name, start, end in PARTS_OF_DAY:
        parts[name] += sum(count for hour, count in hours.items() if start <= hour < end)
    return parts.most_common(1)[0][0] if parts and sum(parts.values()) else ""


def languages_used(chats: list[PastChat]) -> dict[str, int]:
    """Which language each chat was started in, most used first."""
    return dict(Counter(language_of(chat.asked[0] if chat.asked else "") for chat in chats).most_common())


def language_of(text: str) -> str:
    """The language a message is written in, by its letters; English only when it
    also has everyday English words, so French or Spanish isn't counted as English."""
    if script := next((name for name in SCRIPTS if looks_like(text, name)), None):
        return script
    letters = [c for c in text if c.isalpha()]
    if letters and sum(c.isascii() for c in letters) / len(letters) > 0.8 and ENGLISH_WORDS.search(text):
        return "English"
    return "Other"


# ------------------------------------------------------- with her model


def sort_kinds(ollama: Ollama, model: str, chats: list[PastChat], think: bool | None = None) -> list[dict]:
    """How many chats asked for each kind of help, most first. The model can only
    answer with one of the kinds listed, because the schema says so."""
    counted = Counter()
    for start in range(0, len(chats), SORT_BATCH):
        batch = chats[start:start + SORT_BATCH]
        lines = "\n".join(f"{n}. {_preview(chat)}" for n, chat in enumerate(batch, 1))
        schema = {"type": "object", "required": [str(n) for n in range(1, len(batch) + 1)],
                  "properties": {str(n): {"type": "string", "enum": list(KINDS)} for n in range(1, len(batch) + 1)}}
        messages = [
            {"role": "system", "content": "Sort each numbered conversation by the kind of help the person "
                                          f"wanted. The kinds:\n{KIND_MEANINGS}"},
            {"role": "user", "content": lines},
        ]
        answer = ollama.chat_json(model, messages, schema, think=think)
        for n in range(1, len(batch) + 1):
            counted[answer.get(str(n)) if answer.get(str(n)) in KINDS else "other"] += 1
    order = sorted(counted.items(), key=lambda item: (item[0] == "other", -item[1]))
    return [{"id": kind, "words": KINDS[kind][0], "topic": KINDS[kind][1], "count": count} for kind, count in order]


def find_facts(ollama: Ollama, model: str, chats: list[PastChat], think: bool | None = None) -> list[dict]:
    """Facts about the person, from the lines where they talk about themselves.
    Each one is checked by code before it's shown."""
    snippets = self_snippets(chats)
    found: list[dict] = []
    for start in range(0, len(snippets), FACT_BATCH):
        batch = snippets[start:start + FACT_BATCH]
        lines = "\n".join(f"{n}. {text}" for n, (text, _) in enumerate(batch, 1))
        schema = {"type": "object", "required": ["facts"], "properties": {"facts": {
            "type": "array", "maxItems": FACT_BATCH, "items": {
                "type": "object", "required": ["about", "fact", "line", "quote"],
                "properties": {"about": {"type": "string", "enum": list(ABOUT)}, "fact": {"type": "string"},
                               "line": {"type": "integer"}, "quote": {"type": "string"}}}}}}
        messages = [
            {"role": "system", "content": (
                "These numbered lines were written by one person. Write short facts about that person that "
                "the lines say plainly: their work or studies, where they live, languages, interests, tools "
                "they use and goals. Start each fact with a verb, like 'Works as a nurse', 'Lives in Busan', "
                "'Uses Excel' or 'Is preparing for a driving test'. Each fact says only what its own words "
                "say. For each fact give the line "
                "number and the exact words it came from. "
                "Nothing about health, money, beliefs, politics, family or relationships. No guesses; "
                "if a line says nothing about the person, skip it.")},
            {"role": "user", "content": lines},
        ]
        answer = ollama.chat_json(model, messages, schema, think=think)
        for suggestion in answer.get("facts") or []:
            fact = checked(suggestion, batch)
            line = batch[int(suggestion["line"]) - 1][0] if fact else ""
            if fact and sum(1 for _, other in found if other == line) < FACTS_PER_LINE:
                found.append((fact, line))
    return merge(confirmed(ollama, model, found, think))[:MAX_FACTS]


def confirmed(ollama: Ollama, model: str, found: list[tuple[dict, str]], think: bool | None = None) -> list[dict]:
    """A second look, asked differently: each fact beside the line it came from,
    and only yes or no. Writing facts and checking them are separate jobs, and a
    small model is far better at the second, so a stretch like "Works as a game
    developer" from "I'm a student and I like making games" gets a no."""
    kept = []
    for start in range(0, len(found), FACT_BATCH):
        batch = found[start:start + FACT_BATCH]
        pairs = "\n\n".join(f'{n}. Line: "{line}"\n   Fact: {fact["fact"]}' for n, (fact, line) in enumerate(batch, 1))
        schema = {"type": "object", "required": [str(n) for n in range(1, len(batch) + 1)],
                  "properties": {str(n): {"type": "string", "enum": ["yes", "no"]} for n in range(1, len(batch) + 1)}}
        messages = [
            {"role": "system", "content": (
                "For each numbered pair, a person wrote the line. Answer yes only if both are true: the line "
                "plainly says the fact, and the fact is something lasting about the person: their work, "
                "studies, where they live, an interest, a tool they use or a goal. Answer no if the fact "
                "adds anything the line doesn't say, or if it's only the task in that one message, like "
                "asking for something, a homework question, or a pasted assignment.")},
            {"role": "user", "content": pairs},
        ]
        answer = ollama.chat_json(model, messages, schema, think=think)
        kept += [fact for n, (fact, _) in enumerate(batch, 1) if answer.get(str(n)) == "yes"]
    return kept


def self_snippets(chats: list[PastChat]) -> list[tuple[str, PastChat]]:
    """At most one line from each chat where the person talks about themselves,
    newest chats first, never one that touches what isn't hers to work out."""
    snippets = []
    for chat in sorted(chats, key=lambda c: c.when, reverse=True):
        for message in chat.asked:
            text = message.replace("’", "'")
            for sentence in re.split(r"(?<=[.!?。])\s+|\n+", text):
                if SELF_WORDS.search(sentence) and not SENSITIVE.search(sentence):
                    snippets.append((sentence.strip()[:SNIPPET_CHARS], chat))
                    break
            else:
                continue
            break
        if len(snippets) >= MAX_SNIPPETS:
            break
    return snippets


def checked(suggestion: dict, batch: list[tuple[str, PastChat]]) -> dict | None:
    """A suggested fact, or None if its words aren't really in the line it names,
    if it touches what isn't hers to work out, or if it's too long to be one fact."""
    try:
        line = int(suggestion.get("line", 0))
    except (TypeError, ValueError):
        return None
    fact = SUBJECT.sub("", str(suggestion.get("fact", "")).strip()).rstrip(".")
    quote = str(suggestion.get("quote", "")).strip().strip("\"'")
    if not 1 <= line <= len(batch) or not fact or len(fact) > FACT_MAX_CHARS or len(quote) < QUOTE_MIN_CHARS:
        return None
    text, chat = batch[line - 1]
    if _plain(quote) not in _plain(text) or SENSITIVE.search(fact) or SENSITIVE.search(quote):
        return None
    if ASKING.search(fact):
        return None  # something they asked for once, not something about them
    if suggestion.get("about") not in ABOUT:
        return None
    if _names_a_language(fact) and not _names_a_language(quote):
        return None  # "Speaks Korean" from a line that's merely written in Korean
    if quote.isascii() and not _share_a_word(fact, quote):
        return None  # "Studies computer science" from "I use C# and the new input system"
    fact = fact[0].upper() + fact[1:]
    return {"id": _id(fact), "about": suggestion["about"], "fact": fact, "quote": quote,
            "source": chat.source, "title": chat.title, "when": chat.when, "seen": 1, "kept": None}


def merge(facts: list[dict]) -> list[dict]:
    """The same fact said in several chats becomes one, seen that many times."""
    merged: list[dict] = []
    for fact in facts:
        words = _meaning(fact["fact"])
        twin = next((other for other in merged if other["about"] == fact["about"]
                     and _overlap(words, _meaning(other["fact"])) >= 0.75), None)
        if twin:
            twin["seen"] += 1
            if len(fact["fact"]) > len(twin["fact"]):  # "Works at a cafe" grows into "...in Sinchon"
                twin.update({key: fact[key] for key in ("id", "fact", "quote", "source", "title", "when")})
        else:
            merged.append(fact)
    return sorted(merged, key=lambda fact: (-fact["seen"], -fact["when"]))


# ------------------------------------------------------------- helpers


def _save(made: dict) -> None:
    path = portrait_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(made, ensure_ascii=False), encoding="utf-8")


def _preview(chat: PastChat) -> str:
    first = " ".join(chat.asked[0].split())[:SORT_PREVIEW_CHARS] if chat.asked else ""
    return f"{chat.title}: {first}" if chat.title else first


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s']", " ", text.lower().replace("’", "'")).split())


def _meaning(fact: str) -> set[str]:
    small = {"a", "an", "the", "at", "in", "on", "of", "to", "and", "for", "with", "is", "as"}
    return set(_plain(fact).split()) - small


def _share_a_word(fact: str, quote: str) -> bool:
    """Whether a fact and its quote have a meaningful word in common, counting
    "uses" and "use" or "learns" and "learning" as the same word."""
    said = [word for word in _meaning(quote) if len(word) >= 3]
    return any(a[:4] == b[:4] or a.startswith(b) or b.startswith(a)
               for a in _meaning(fact) if len(a) >= 3 for b in said)


def _overlap(a: set, b: set) -> float:
    """How much two facts say the same: the shorter one's words found in the longer."""
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def _names_a_language(text: str) -> bool:
    lowered = text.lower()
    return any(name in lowered for names in LANGUAGE_NAMES.values() for name in names)


def _id(fact: str) -> str:
    return hashlib.sha1(_plain(fact).encode()).hexdigest()[:12]
