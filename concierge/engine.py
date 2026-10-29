"""The real engine, following the contract in events.py.

For now it only chats: agents are being built (concierge/agents/, coming
next) and will add Question, AgentCard, Progress and Result events here
without changing the contract. Elaina must already be set up
(`python -m concierge setup`).
"""

from __future__ import annotations

from collections.abc import Iterator

from . import elaina, hardware
from .catalog import find_model, recommend
from .events import AgentList, ElainaDone, ElainaText, Error, Event, SystemInfo
from .ollama import Ollama, OllamaError


class ElainaEngine:
    def __init__(self, ollama: Ollama | None = None):
        self.ollama = ollama or Ollama()
        self.chat: elaina.ElainaChat | None = None

    def startup(self) -> Iterator[Event]:
        report = hardware.detect()
        rec = recommend(report)
        tag = elaina.load_state().get("base_model")
        model = find_model(tag) if tag else None
        in_use = f"{model.name} ({tag})" if model else tag or "not set up"
        recommended = f"{rec.model.name} ({rec.model.tag})" if rec.model else None
        note = rec.reason if rec.model is None else ""
        if rec.model and tag and tag != rec.model.tag:
            note = f"Not the recommended {rec.model.name}. Run `python -m concierge setup` to switch."
        yield SystemInfo(hardware.describe(report), recommended, in_use, rec.device_name, note)

        try:
            self.ollama.ensure_running()
            if not self.ollama.has_model(elaina.ELAINA_MODEL):
                yield Error("Elaina is not set up yet. Run: python -m concierge setup")
                return
            self.chat = elaina.ElainaChat(self.ollama)
        except OllamaError as exc:
            yield Error(str(exc))
            return
        yield AgentList([])

    def send(self, text: str) -> Iterator[Event]:
        if self.chat is None:
            yield Error("Elaina is not running. Restart the app after setting her up.")
            return
        try:
            for chunk in self.chat.send(text):
                yield ElainaText(chunk)
        except OllamaError as exc:
            yield Error(str(exc))
        yield ElainaDone()

    def choose(self, id: str, choice: str) -> Iterator[Event]:
        yield Error("Agents are not built yet.")

    def reset(self) -> None:
        if self.chat:
            self.chat.reset()

    def close(self) -> None:
        if self.chat:
            self.chat.close()
