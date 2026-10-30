"""Turn the chosen base model into Elaina, and talk with her.

Elaina is an Ollama model of her own ("elaina") built from the base model with
her persona and the facts about this computer as its system prompt. Baking
them in means every chat starts as Elaina, and `ollama run elaina` works too.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

from .catalog import ModelEntry, Recommendation
from .hardware import HardwareReport, describe
from .ollama import Ollama

ELAINA_MODEL = "elaina"
PERSONA_PATH = Path(__file__).parent / "persona" / "elaina_en.txt"
# The context window Elaina's memory figures in models.yaml were sized for.
NUM_CTX = 4096
# Roughly 2,500 tokens of past conversation, leaving room for the system
# prompt and the reply inside NUM_CTX.
HISTORY_CHARS = 9000
# Elaina stays in graphics memory while the program is open, and leaves it
# when the program closes.
#
# A normal exit (/exit, Ctrl+C) unloads her at once when UNLOAD_ON_EXIT is on.
# A program that is killed (window or tab closed, Task Manager, crash) gets no
# chance to do that, so instead it checks in with Ollama every
# HEARTBEAT_SECONDS to keep her loaded; once the check-ins stop, Ollama frees
# her after KEEP_ALIVE.
UNLOAD_ON_EXIT = True
KEEP_ALIVE = "60s"
HEARTBEAT_SECONDS = 20


def system_prompt(base: ModelEntry, rec: Recommendation, report: HardwareReport) -> str:
    persona = PERSONA_PATH.read_text(encoding="utf-8").strip()
    facts = "\n".join(f"- {line}" for line in describe(report, live=False))
    where = "graphics card" if rec.device == "gpu" else "processor" if rec.device == "cpu" else "chip"
    return (
        f"{persona}\n\n"
        f"FACTS ABOUT THIS COMPUTER (read by code, exact)\n{facts}\n"
        f"- Your own brain is {base.name} ({base.tag}), running on the {where}: {rec.device_name}. "
        f"It was chosen to stay small so the computer keeps running smoothly."
    )


def configure(ollama: Ollama, base: ModelEntry, rec: Recommendation, report: HardwareReport) -> None:
    """Create (or replace) the "elaina" model and remember what she was built from."""
    prompt = system_prompt(base, rec, report)
    ollama.create(ELAINA_MODEL, base.tag, prompt, parameters={"num_ctx": NUM_CTX})
    save_state({"base_model": base.tag, "prompt_hash": _hash(prompt)})


def needs_configure(ollama: Ollama, base: ModelEntry, rec: Recommendation, report: HardwareReport) -> bool:
    """True when Elaina is missing or was built from another model or prompt."""
    state = load_state()
    return (
        not ollama.has_model(ELAINA_MODEL)
        or state.get("base_model") != base.tag
        or state.get("prompt_hash") != _hash(system_prompt(base, rec, report))
    )


# Closing lines small models add however often the persona forbids them:
# "Let me know if you need anything else!", "Feel free to ask...".
CLOSING_FILLER = re.compile(
    r"^\s*(let me know|just let me know|feel free|if you need|if you have any|anything else|"
    r"is there anything|hope (this|that) helps|happy to help|더 필요한|궁금한 (점|게)|언제든)",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<=[.!?。])\s+")


def without_closing_filler(chunks: Iterator[str]) -> Iterator[str]:
    """Pass a streamed reply through sentence by sentence, dropping filler
    sentences at its very end. A filler sentence in the middle is kept: it is
    held back only until it is clear more text follows."""
    pending, held, said = "", [], False
    for chunk in chunks:
        pending += chunk
        while match := _SENTENCE_END.search(pending):
            sentence, pending = pending[:match.end()], pending[match.end():]
            if CLOSING_FILLER.match(sentence):
                held.append(sentence)
                continue
            if held:
                yield "".join(held)
                held = []
            yield sentence
            said = True
    if pending.strip() and not CLOSING_FILLER.match(pending):
        yield "".join(held) + pending
    elif not said and (held or pending.strip()):
        yield (held or [pending])[0]  # all filler ("Happy to help!"): never answer with nothing


class ElainaChat:
    """One conversation with Elaina. Independent of the UI that shows it."""

    def __init__(self, ollama: Ollama, model: str = ELAINA_MODEL):
        self.ollama = ollama
        self.model = model
        self.history: list[dict] = []
        # Thinking models (Qwen 3, Qwen 3.5) reason silently before answering,
        # which makes a chat feel slow. Elaina answers directly.
        self.think = False if "thinking" in ollama.capabilities(model) else None
        self._closed = threading.Event()
        # Held while checking in and while unloading, so a check-in cannot
        # load Elaina again right after close() unloaded her.
        self._lock = threading.Lock()
        threading.Thread(target=self._heartbeat, daemon=True).start()

    def send(self, text: str) -> Iterator[str]:
        self.history.append({"role": "user", "content": text})
        reply = []
        try:
            chunks = self.ollama.chat(self.model, self._recent(), think=self.think, keep_alive=KEEP_ALIVE)
            for piece in without_closing_filler(chunks):
                reply.append(piece)
                yield piece
        finally:
            if reply:
                self.history.append({"role": "assistant", "content": "".join(reply).strip()})
            else:
                self.history.pop()

    @property
    def can_think(self) -> bool:
        """Whether this model can show its thinking (Qwen 3 and 3.5 can)."""
        return self.think is False

    def think_through(self, text: str) -> Iterator[tuple[str, str]]:
        """Like send(), but the model thinks first and its thoughts stream too:
        ("thought", piece) pieces, then ("text", piece) pieces of the reply.
        Only the reply goes into her memory of the conversation."""
        self.history.append({"role": "user", "content": text})
        parts = self.ollama.chat_parts(self.model, self._recent(), think=True, keep_alive=KEEP_ALIVE)
        reply = []

        def rest_of_reply():
            for kind, piece in parts:
                if kind == "text":
                    yield piece

        try:
            for kind, piece in parts:
                if kind == "thought":
                    yield "thought", piece
                    continue
                for out in without_closing_filler(itertools.chain([piece], rest_of_reply())):
                    reply.append(out)
                    yield "text", out
                break
        finally:
            if reply:
                self.history.append({"role": "assistant", "content": "".join(reply).strip()})
            else:
                self.history.pop()

    def reset(self) -> None:
        self.history.clear()

    def remember(self, user_text: str, reply: str) -> None:
        """Add an exchange Elaina did not answer herself, such as an agent's answer."""
        self.history += [{"role": "user", "content": user_text}, {"role": "assistant", "content": reply}]

    def close(self) -> None:
        """Stop checking in and unload Elaina, if UNLOAD_ON_EXIT is on. Safe to call twice."""
        with self._lock:
            self._closed.set()
            if not UNLOAD_ON_EXIT:
                return
            try:
                self.ollama.unload(self.model)
            except Exception:
                pass  # Ollama already stopped; nothing is loaded.

    def _heartbeat(self) -> None:
        while not self._closed.wait(HEARTBEAT_SECONDS):
            self.check_in()

    def check_in(self) -> None:
        """Keep Elaina loaded for another KEEP_ALIVE, but only if she is loaded now.

        Never loads her: memory is only taken once the user actually talks.
        """
        with self._lock:
            if self._closed.is_set():
                return
            try:
                if any(m["name"].split(":")[0] == self.model for m in self.ollama.loaded()):
                    self.ollama.refresh(self.model, KEEP_ALIVE)
            except Exception:
                pass  # Ollama is restarting; try again on the next beat.

    def _recent(self) -> list[dict]:
        """The latest messages that fit in HISTORY_CHARS, always starting with the user."""
        kept, size = [], 0
        for message in reversed(self.history):
            size += len(message["content"])
            if kept and size > HISTORY_CHARS:
                break
            kept.append(message)
        kept.reverse()
        while len(kept) > 1 and kept[0]["role"] != "user":
            kept.pop(0)
        return kept


# --------------------------------------------------------------- state


def data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "LocalAIConcierge"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "LocalAIConcierge"
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "local-ai-concierge"


def load_state() -> dict:
    try:
        return json.loads((data_dir() / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    path = data_dir() / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
