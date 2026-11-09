"""Noir says things about its agents in its own words, from facts code decided.

Code decides what is true: which folder, which file, how many moved, what to ask, and
writes it as one plain line. The model only puts that line into its own words, so the
same moment never reads the same twice and no sentence about the user's life is written
into the program. The rewording is checked against the line: every fact (names, paths,
numbers, codes, file names, whether given or found in the line) must still be there word
for word, most of the line's own words must survive (a 4B model once turned "sorted from
now on" into "ordered with the new one at the front"), it must stay short and plain, and
a question must still ask. Anything that fails is dropped for the plain line, so nothing
is ever said wrong. Without a model (the tests, the practice run) the plain line is used.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ..ollama import Ollama, OllamaError

MAX_CHARS = 360  # longer than two sentences: the plain line instead
# Only a short line is reworded: an opener, a question, "it's on", "okay". A long one (a
# report of what moved and why) is a record and stays as written: a 4B model turned
# "left alone, as you said" into "since it's not a .png".
MAX_PLAIN = 170
TEMPERATURE = 0.5  # varied words, same meaning
KEPT_SHARE = 0.6  # how many of the line's own words the rewording must keep
ASKING_WORDS = ("which", "what", "where", "how", "who", "when")
PHRASE_NOTE = (
    "You are Noir, a helper that lives on this computer and speaks as I to the person using it (you, your). "
    "Say the line below to them in your own words: one or two short sentences in everyday words, the way a "
    "friend would say it, with exactly the same meaning and about the same length. No greeting, no list, no "
    "emoji, no quotation marks around the whole thing, no offer to help further, and no technical words such as "
    "configure, monitor, directory, process or system. Keep every fact exactly as written (names, paths, numbers, "
    "file names, folder names): copy them, never reword or translate them. Add nothing the line doesn't say and "
    "never make up an example. Same language as the line."
)
QUESTION_NOTE = " It must end as one clear question asking the same thing."
# Words that mean the model slipped into computer talk.
JARGON = re.compile(r"\b(configur\w*|monitor\w*|director(y|ies)|process\w*|system\w*|parameter\w*|execut\w*|"
                    r"implement\w*|functionality|utilize|external)\b", re.IGNORECASE)
UNQUOTED = re.compile(r'^["“”\']+|["“”\']+$')
# What in a line must come through untouched even when nobody listed it: numbers, file
# names, paths, course codes and other capitalised names ("Undo", "Downloads").
FACT_IN_LINE = re.compile(r"[A-Za-z]:[\\/][^\s,;]+|~[\\/][^\s,;]+|\S*\.[A-Za-z0-9]{1,5}\b|\b\d+\b|\b[A-Z]{2,5} ?\d{3}[A-Z]?\b|"
                          r"(?<![.!?] )(?<!^)\b[A-Z][a-z]{2,}\b")
STOPWORDS = {"that", "this", "with", "from", "your", "into", "have", "been", "just", "they", "them", "were", "will",
             "what", "when", "then", "than", "also", "only", "very", "more", "some", "each", "every", "there", "their",
             "where", "which", "about", "would", "could", "should", "okay", "here", "like", "still", "while", "since",
             "yours", "those", "these", "does", "done", "went", "goes", "gets", "lands", "land"}


def phrase(ollama: Ollama, model: str, plain: str, facts: Sequence[str] = (), question: bool = False) -> str:
    """`plain` in Noir's own words, keeping every string in `facts` (and every fact found in
    the line) word for word; `plain` itself whenever the rewording fails a check or there is
    no model to ask."""
    if len(plain) > MAX_PLAIN:
        return plain
    musts = list(dict.fromkeys([fact for fact in facts if fact] + facts_in(plain)))
    note = PHRASE_NOTE + (QUESTION_NOTE if question else "")
    content = plain + ("\n\nKeep exactly:\n" + "\n".join(f"- {fact}" for fact in musts) if musts else "")
    try:
        said = "".join(ollama.chat(model, [{"role": "system", "content": note}, {"role": "user", "content": content}],
                                   think=False, options={"temperature": TEMPERATURE}))
    except (OllamaError, AttributeError, TypeError, OSError, ValueError):
        return plain
    said = UNQUOTED.sub("", re.sub(r"\s+", " ", said).strip())
    if not said or len(said) > max(MAX_CHARS, len(plain) * 2) or JARGON.search(said):
        return plain
    lowered = said.lower()
    if any(fact.lower() not in lowered for fact in musts):
        return plain
    own = words_of(plain)
    if own and len(own & words_of(said)) < len(own) * KEPT_SHARE:
        return plain
    if question and not said.endswith("?"):
        return plain
    first = plain.split()[0].lower().strip("?,.") if plain.split() else ""
    if question and first in ASKING_WORDS and first not in lowered.split():
        return plain  # "Which folder?" must still ask which, not "shall we start with Downloads?"
    return said


def facts_in(plain: str) -> list[str]:
    """The parts of a line that must come through as written."""
    found = []
    for match in FACT_IN_LINE.finditer(plain):
        fact = match.group(0).rstrip(".,;:!?")
        if fact and fact not in found and fact.lower() not in STOPWORDS:
            found.append(fact)
    return found


def words_of(text: str) -> set[str]:
    """A line's own words, as four-letter stems, the small and the common left out."""
    return {word[:4] for word in re.findall(r"[a-z]{4,}", text.lower()) if word not in STOPWORDS}
