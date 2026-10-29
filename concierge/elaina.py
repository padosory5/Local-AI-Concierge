"""Turn the chosen base model into Elaina, and talk with her.

Elaina is an Ollama model of her own ("elaina") built from the base model with
her persona and the facts about this computer as its system prompt. Baking
them in means every chat starts as Elaina, and `ollama run elaina` works too.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
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


class ElainaChat:
    """One conversation with Elaina. Independent of the UI that shows it."""

    def __init__(self, ollama: Ollama, model: str = ELAINA_MODEL):
        self.ollama = ollama
        self.model = model
        self.history: list[dict] = []
        # Thinking models (Qwen 3, Qwen 3.5) reason silently before answering,
        # which makes a chat feel slow. Elaina answers directly.
        self.think = False if "thinking" in ollama.capabilities(model) else None

    def send(self, text: str) -> Iterator[str]:
        self.history.append({"role": "user", "content": text})
        reply = []
        try:
            for chunk in self.ollama.chat(self.model, self._recent(), think=self.think):
                reply.append(chunk)
                yield chunk
        finally:
            if reply:
                self.history.append({"role": "assistant", "content": "".join(reply).strip()})
            else:
                self.history.pop()

    def reset(self) -> None:
        self.history.clear()

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
