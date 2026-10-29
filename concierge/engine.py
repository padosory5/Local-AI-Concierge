"""The real engine, following the contract in events.py.

Every message goes one of three ways: while an agent is being set up it
answers the setup; otherwise the router decides between chatting with
Elaina, creating a new agent, and running an existing one. Every exchange
is saved as part of a conversation (conversations.py). Elaina must already
be set up (`python -m concierge setup`).
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from . import elaina, hardware
from .agents import runner, store
from .agents.blueprint import load_blueprints
from .agents.builder import AgentBuilder, say
from .agents.router import names_an_agent, route
from .catalog import find_model, recommend
from .conversations import ChatBook
from .events import AgentList, ElainaDone, ElainaText, Error, Event, Question, Result, SystemInfo
from .ollama import Ollama, OllamaError

# "delete the Sample docs helper 2 agent", "remove my contracts helper"
WANTS_DELETE = re.compile(r"\b(delete|remove|get rid of|uninstall)\b|삭제|지워", re.IGNORECASE)
DELETE_AGENT, PICK_AGENT_TO_DELETE = "delete_agent", "pick_agent_to_delete"
DELETE_IT, KEEP_IT = "Delete it", "Keep it"


class ElainaEngine:
    def __init__(self, ollama: Ollama | None = None):
        self.ollama = ollama or Ollama()
        self.chat: elaina.ElainaChat | None = None
        self.builder: AgentBuilder | None = None
        self.blueprints = load_blueprints()
        self.book = ChatBook(elaina.data_dir() / "conversations",
                             history=lambda: self.chat.history if self.chat else [])
        self.deleting: str | None = None  # agent waiting for "Delete it" / "Keep it"

    # ----------------------------------------------------------- contract

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
        yield self.book.chat_list()

    def send(self, text: str) -> Iterator[Event]:
        if self.chat is None:
            yield Error("Elaina is not running. Restart the app after setting her up.")
            return
        yield from self.book.record(text, self._handle(text))

    def choose(self, id: str, choice: str) -> Iterator[Event]:
        if self.chat is None:
            yield Error("Elaina is not running. Restart the app after setting her up.")
            return
        yield from self.book.record(choice, self._handle_choice(id, choice))

    # The book saves the open conversation (with Elaina's memory of it) before
    # switching, so the per-conversation state is only cleared after that.

    def new_chat(self) -> Iterator[Event]:
        events = self.book.new()
        self._clear_conversation_state()
        yield from events

    def open_chat(self, id: str) -> Iterator[Event]:
        conversation = self.book.open(id)
        if conversation is None:
            yield Error("That conversation could not be found.")
            yield self.book.chat_list()
            return
        self._clear_conversation_state()
        if self.chat:
            self.chat.history = list(conversation.history)
        yield self.book.transcript()
        yield self.book.chat_list()

    def delete_chat(self, id: str) -> Iterator[Event]:
        was_open = self.book.current is not None and self.book.current.id == id
        events = self.book.delete(id)
        if was_open:
            self._clear_conversation_state()
        yield from events

    def delete_agent(self, name: str) -> Iterator[Event]:
        # No user line in the transcript: the click on the agent is the context.
        yield from self.book.record("", self._confirm_delete(name))

    def reset(self) -> None:
        self.book.new()
        self._clear_conversation_state()

    def close(self) -> None:
        self.book.save()
        if self.chat:
            self.chat.close()

    # ------------------------------------------------------------ routing

    def _handle(self, text: str) -> Iterator[Event]:
        self.deleting = None  # an unanswered "Delete X?" is dropped by moving on
        try:
            if self.builder.active:
                yield from self.builder.answer(text)
                if self.builder.handoff is None:
                    return
                text, self.builder.handoff = self.builder.handoff, None
            agents = store.list_agents()
            if WANTS_DELETE.search(text) and agents:
                named = names_an_agent(text, agents)
                yield from self._confirm_delete(named.name) if named else self._ask_which_to_delete(agents)
                return
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

    def _handle_choice(self, id: str, choice: str) -> Iterator[Event]:
        if id == PICK_AGENT_TO_DELETE:
            yield from self._confirm_delete(choice) if store.find_agent(choice) else say("Okay, nothing deleted.")
        elif id == DELETE_AGENT:
            yield from self._finish_delete(choice)
        elif self.builder and self.builder.active:
            try:
                yield from self.builder.choose(id, choice)
            except OllamaError as exc:
                yield Error(str(exc))
        else:
            yield Error("Nothing is waiting for an answer right now.")

    def _clear_conversation_state(self) -> None:
        """Unfinished setups, questions and Elaina's memory belong to the
        conversation being left. Call only after the book has saved it."""
        self.deleting = None
        if self.builder:
            self.builder.draft = None
        if self.chat:
            self.chat.reset()

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

    # ------------------------------------------------------ deleting agents

    def _confirm_delete(self, name: str) -> Iterator[Event]:
        agent = store.find_agent(name)
        if agent is None:
            yield Error(f"There is no agent called {name}.")
            return
        self.deleting = agent.name
        folder = agent.slots.get("folder")
        files = f" Your files in {folder} are not touched." if folder else ""
        yield Question(DELETE_AGENT, f"Delete {agent.name}? It forgets everything it read.{files}",
                       [DELETE_IT, KEEP_IT])

    def _ask_which_to_delete(self, agents: list[store.Agent]) -> Iterator[Event]:
        if len(agents) == 1:
            yield from self._confirm_delete(agents[0].name)
            return
        yield Question(PICK_AGENT_TO_DELETE, "Which agent should I delete?",
                       [a.name for a in agents] + ["None of them"])

    def _finish_delete(self, choice: str) -> Iterator[Event]:
        name, self.deleting = self.deleting, None
        agent = store.find_agent(name) if name else None
        if choice != DELETE_IT or agent is None:
            yield from say("Okay, I kept it." if agent else "That question has already been answered.")
            return
        store.delete(agent)
        yield from say(f"Deleted {agent.name}.")
        yield AgentList([a.name for a in store.list_agents()])
