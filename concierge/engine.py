"""The real engine, following the contract in events.py.

Every message goes one of three ways: while an agent is being set up it
answers the setup; otherwise the router decides between chatting with
Elaina, creating a new agent, and running an existing one. Elaina must
already be set up (`python -m concierge setup`).
"""

from __future__ import annotations

from collections.abc import Iterator

from . import elaina, hardware
from .agents import runner, store
from .agents.blueprint import load_blueprints
from .agents.builder import AgentBuilder
from .agents.router import route
from .catalog import find_model, recommend
from .events import AgentList, ElainaDone, ElainaText, Error, Event, Result, SystemInfo
from .ollama import Ollama, OllamaError


class ElainaEngine:
    def __init__(self, ollama: Ollama | None = None):
        self.ollama = ollama or Ollama()
        self.chat: elaina.ElainaChat | None = None
        self.builder: AgentBuilder | None = None
        self.blueprints = load_blueprints()

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
        self.builder = AgentBuilder(self.ollama, elaina.ELAINA_MODEL, self.chat.think, self.blueprints)
        yield AgentList([a.name for a in store.list_agents()])

    def send(self, text: str) -> Iterator[Event]:
        if self.chat is None:
            yield Error("Elaina is not running. Restart the app after setting her up.")
            return
        try:
            if self.builder.active:
                yield from self.builder.answer(text)
                if self.builder.handoff is None:
                    return
                text, self.builder.handoff = self.builder.handoff, None
            agents = store.list_agents()
            evidence = {a.name: runner.matching_words(a, text) for a in agents}
            where = route(self.ollama, elaina.ELAINA_MODEL, text, self.blueprints, agents,
                          think=self.chat.think, evidence=evidence)
            if where.kind == "new_agent":
                yield from self.builder.start(where.blueprint, text)
            elif where.kind == "run_agent":
                yield from self._run_agent(where.agent, where.request, text)
            else:
                for chunk in self.chat.send(text):
                    yield ElainaText(chunk)
                yield ElainaDone()
        except OllamaError as exc:
            yield Error(str(exc))

    def choose(self, id: str, choice: str) -> Iterator[Event]:
        if not (self.builder and self.builder.active):
            yield Error("Nothing is waiting for an answer right now.")
            return
        try:
            yield from self.builder.choose(id, choice)
        except OllamaError as exc:
            yield Error(str(exc))

    def reset(self) -> None:
        if self.builder:
            self.builder.draft = None
        if self.chat:
            self.chat.reset()

    def close(self) -> None:
        if self.chat:
            self.chat.close()

    def _run_agent(self, name: str, request: str, text: str) -> Iterator[Event]:
        agent = store.find_agent(name)
        if agent is None:
            yield Error(f"I can't find an agent called {name}.")
            return
        for event in runner.run(self.ollama, elaina.ELAINA_MODEL, agent, request, self.chat.think):
            if isinstance(event, Result):
                # Elaina hears the answer too, so "and what about...?" follows on.
                self.chat.remember(text, f"({agent.name} answered) {event.text}")
            yield event
