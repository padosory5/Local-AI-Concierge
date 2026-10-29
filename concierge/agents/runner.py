"""Run an agent on a request.

For "Ask my documents": code searches the agent's files and gives the model
only the best few passages. The model must answer from them and say which
ones it used, so every answer comes with where it was found.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from ..events import Event, Progress, Result, Source
from ..ollama import Ollama
from . import store
from .files import SearchIndex, folder_signature, passages_of, scan, tokens

TOP_PASSAGES = 4
MAX_CONTENTS = 50  # file names remembered for the router


def run(
    ollama: Ollama, model: str, agent: store.Agent, request: str, think: bool | None = None
) -> Iterator[Event]:
    """Yields Progress while working, then exactly one Result."""
    index = yield from refresh_index(agent)
    yield Progress(f"Searching {agent.name}'s files...")
    hits = index.search(request, TOP_PASSAGES)
    if not hits:
        yield Result(agent.name, f"I couldn't find anything about that in {agent.slots['folder']}.")
        return

    excerpts = "\n\n".join(f"[{i}] From {p.where()}:\n{p.text}" for i, p in enumerate(hits, 1))
    system = (
        "You answer the user's question using only the numbered excerpts from their files below.\n"
        "- If the excerpts do not contain the answer, say you could not find it in the files. Never guess.\n"
        "- Answer every part of the question.\n"
        "- Keep it short: one to three sentences, plain words.\n"
        "- Answer in the language the question is written in.\n"
        "- Put the numbers of the excerpts you used in \"used\", never in the answer text.\n\n"
        f"{excerpts}"
    )
    schema = {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "used": {"type": "array", "items": {"enum": list(range(1, len(hits) + 1))}},
        },
        "required": ["answer", "used"],
    }
    yield Progress("Reading the best matches...")
    reply = ollama.chat_json(
        model, [{"role": "system", "content": system}, {"role": "user", "content": request}],
        schema, think=think,
    )
    answer = clean_answer(reply.get("answer", ""))
    used = sorted({n for n in reply.get("used", []) if 1 <= n <= len(hits)})
    sources = [Source(hits[n - 1].where(), best_sentence(hits[n - 1].text, answer + " " + request))
               for n in used]
    yield Result(agent.name, answer, sources)


_loaded: dict[tuple[str, str], SearchIndex] = {}


def matching_words(agent: store.Agent, text: str) -> list[str]:
    """Words of the message found in the agent's best-matching passage.

    Evidence for the router: "what did we decide about the website
    relaunch?" names no file, but the meeting notes contain "website" and
    "relaunch". Uses the saved index without re-reading the folder.
    """
    key = (agent.slug, agent.signature)
    if key not in _loaded:
        _loaded[key] = SearchIndex.from_json(store.load_index(agent))
    hits = _loaded[key].search(text, 1)
    if not hits:
        return []
    found = set(tokens(hits[0].text)) | set(tokens(hits[0].path))
    return [w for w in dict.fromkeys(tokens(text)) if w in found and w not in STOPWORDS]


def clean_answer(text: str) -> str:
    """Drop excerpt numbers the model leaves in its answer anyway ("[1]", "Excerpt 2 used.")."""
    text = re.sub(r"\s*\(?\bexcerpts?\s*\[?\d[\d,\s\[\]and]*\]?\s*(?:was|were)?\s*used\b\.?\)?", "",
                  text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\[\d+(?:\s*,\s*\d+)*\]", "", text)
    return text.strip()


def refresh_index(agent: store.Agent) -> Iterator[Event]:
    """The agent's search index, re-reading its folder first if files changed.

    A generator that yields Progress and returns the index (use `yield from`).
    """
    folder = Path(agent.slots["folder"])
    files = scan(folder).files
    signature = folder_signature(files)
    rows = store.load_index(agent)
    if rows and signature == agent.signature:
        return SearchIndex.from_json(rows)

    passages = []
    for number, path in enumerate(files, 1):
        yield Progress(f"Reading {number} of {len(files)}: {path.name}")
        passages += passages_of(folder, path)
    index = SearchIndex(passages)
    agent.signature = signature
    agent.contents = [path.relative_to(folder).as_posix() for path in files[:MAX_CONTENTS]]
    store.save(agent, index.to_json())
    return index


STOPWORDS = set("the a an and or of to in on at for is are was were be by with this that it its "
                "what when who which how do does did can i my me you your from as about".split())


def best_sentence(text: str, about: str, limit: int = 220) -> str:
    """The sentence of a passage that shares the most words with the answer and question."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?。])\s+|\n+", text) if s.strip()]
    if not sentences:
        return text[:limit]
    wanted = set(tokens(about)) - STOPWORDS
    best = max(sentences, key=lambda s: len(wanted & set(tokens(s))))
    return best if len(best) <= limit else best[: limit - 3] + "..."
