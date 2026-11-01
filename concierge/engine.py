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
from .agents.planner import IDEA, IDEA_CHANGE, MAKE_IT, IdeaPlanner, describe_ideas
from .agents.router import names_an_agent, refers_to, route, wants_change
from .agents.starters import Starter, asks_for, install
from .catalog import find_model, recommend
from .conversations import ChatBook
from .events import (AgentList, ElainaDone, ElainaText, Error, Event, IdeaCard, Question, Result, SystemInfo,
                     Thinking)
from .ollama import Ollama, OllamaError
from .quick.agents import QuickAgents
from .agents.recipe import (BUBBLE, CLIPBOARD, CUSTOM, MECHANICS, WHILE_ON, describe, is_switchable, migrate,
                            needs_language, run_instruction, target_language, with_language)
from .quick.translate import language_in

# "delete the Sample docs helper 2 agent", "remove my contracts helper"
WANTS_DELETE = re.compile(r"\b(delete|remove|get rid of|uninstall)\b|삭제|지워", re.IGNORECASE)
# "show my ideas", "what ideas did I save?"
WANTS_IDEAS = re.compile(r"\b(my|saved)\s+ideas\b|\bideas\s+(list|i saved)\b|아이디어\s*(목록|보여)",
                         re.IGNORECASE)
# "turn on the Korean translator", "switch off my translator", "번역기 켜줘"
WANTS_ON = re.compile(r"\b(turn|switch)\s+on\b|\b(start|enable|activate)\b|켜", re.IGNORECASE)
WANTS_OFF = re.compile(r"\b(turn|switch)\s+off\b|\b(stop|disable|deactivate)\b|꺼|끄", re.IGNORECASE)
# "it's not showing anything", "the translator doesn't work", "안 나와"
TROUBLE = re.compile(
    r"\b(not|isn'?t|doesn'?t|don'?t|won'?t|never|no)\b.{0,30}\b(show\w*|work\w*|translat\w*|appear\w*|"
    r"happen\w*|pop\w*|display\w*|see)\b|nothing (happens|shows|appears)|broken|안 ?(돼|나와|보여)|작동",
    re.IGNORECASE,
)
DELETE_AGENT, PICK_AGENT_TO_DELETE = "delete_agent", "pick_agent_to_delete"
FIX_AGENT, FIX_IT, LEAVE_IT = "fix_agent", "Fix it", "Leave it"
DELETE_IT, KEEP_IT = "Delete it", "Keep it"


class ElainaEngine:
    def __init__(self, ollama: Ollama | None = None):
        self.ollama = ollama or Ollama()
        self.chat: elaina.ElainaChat | None = None
        self.builder: AgentBuilder | None = None
        self.planner: IdeaPlanner | None = None
        self.quick: QuickAgents | None = None
        self.blueprints = load_blueprints()
        self.book = ChatBook(elaina.data_dir() / "conversations",
                             history=lambda: self.chat.history if self.chat else [])
        self.deleting: str | None = None  # agent waiting for "Delete it" / "Keep it"
        # A diagnosis waiting for "Fix it": (agent name, settings to change, switch it on)
        self.fixing: tuple[str, dict, bool] | None = None

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
        self.planner = IdeaPlanner(self.ollama, elaina.ELAINA_MODEL, self.chat.think, self._hardware,
                                   self.blueprints)
        self.quick = QuickAgents(self.ollama, elaina.ELAINA_MODEL, self.chat.think)
        migrate()  # agents of retired blueprints become agents made from parts
        yield self._agent_list()
        yield self.book.chat_list()

    def send(self, text: str, think: bool = False) -> Iterator[Event]:
        if self.chat is None:
            yield Error("Elaina is not running. Restart the app after setting her up.")
            return
        yield from self._full_lists(self.book.record(text, self._handle(text, think)))

    def choose(self, id: str, choice: str) -> Iterator[Event]:
        if self.chat is None:
            yield Error("Elaina is not running. Restart the app after setting her up.")
            return
        yield from self._full_lists(self.book.record(choice, self._handle_choice(id, choice)))

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

    def toggle_agent(self, name: str) -> Iterator[Event]:
        yield from self.book.record("", self._toggle(name))

    def reset(self) -> None:
        self.book.new()
        self._clear_conversation_state()

    def close(self) -> None:
        self.book.save()
        if self.quick:
            self.quick.stop()
        if self.chat:
            self.chat.close()

    # ------------------------------------------------------------ routing

    def _handle(self, text: str, think: bool = False) -> Iterator[Event]:
        self.deleting = None  # an unanswered "Delete X?" is dropped by moving on
        self.fixing = None
        try:
            # An agent setup or an idea in progress gets the message first; if
            # the user moved on, it hands the message back for normal routing.
            for flow in (self.builder, self.planner):
                if flow.active:
                    yield from flow.answer(text)
                    if flow.handoff is None:
                        return
                    text, flow.handoff = flow.handoff, None
            agents = store.list_agents()
            switchable = [a for a in agents if self._switchable(a)]
            named = refers_to(text, switchable, self.blueprints)
            if named and (WANTS_ON.search(text) or WANTS_OFF.search(text)) and len(text.split()) <= 8:
                yield Thinking(f"This switches {named.name} {'off' if WANTS_OFF.search(text) else 'on'}.")
                yield from self._toggle(named.name, on=not WANTS_OFF.search(text))
                return
            if starter := asks_for(text):
                yield from self._add_starter(starter, switch_on=bool(WANTS_ON.search(text)))
                return
            if WANTS_DELETE.search(text) and agents:
                named = names_an_agent(text, agents)
                yield from self._confirm_delete(named.name) if named else self._ask_which_to_delete(agents)
                return
            about = refers_to(text, agents, self.blueprints)
            if TROUBLE.search(text) and (about or len(switchable) == 1):
                # "it's not showing anything": find out why, don't change things blindly.
                yield from self._diagnose(about or switchable[0])
                return
            if about and wants_change(text, about):
                # A change to an agent the user already has, decided in code.
                yield Thinking(f"This is a change to your {about.name}, not a new agent.")
                yield from self.builder.edit(about, text)
                return
            if WANTS_IDEAS.search(text):
                yield from say(describe_ideas(*self._hardware(), self.blueprints))
                return
            evidence = {a.name: runner.matching_words(a, text) for a in agents}
            where = route(self.ollama, elaina.ELAINA_MODEL, text, self.blueprints, agents,
                          think=self.chat.think, evidence=evidence)
            for name, words in evidence.items():
                if words and where.kind != "chat":
                    yield Thinking(f"{name}'s files mention: {', '.join(words)}.")
            if where.kind == "new_agent":
                yield Thinking(f"This asks for a new agent: {self.blueprints[where.blueprint].name}.")
                yield from self.builder.start(where.blueprint, text)
            elif where.kind == "idea":
                yield Thinking("This is an idea for a new kind of helper, so I'll check what it needs.")
                yield from self._idea(text, where.request)
            elif where.kind == "change_agent" and (agent := store.find_agent(where.agent)):
                yield Thinking(f"This is a change to your {agent.name}.")
                yield from self.builder.edit(agent, text)
            elif where.kind == "run_agent":
                yield Thinking(f"This is a job for {where.agent}.")
                yield from self._run_agent(where.agent, where.request, text)
            elif think and self.chat.can_think:
                for kind, piece in self.chat.think_through(text):
                    yield Thinking(piece, "thought") if kind == "thought" else ElainaText(piece)
                yield ElainaDone()
            else:
                if think:
                    yield Thinking("This model can't show its thinking, so here is my answer.")
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
        elif id == FIX_AGENT:
            yield from self._apply_fix(choice)
        elif id in (IDEA, IDEA_CHANGE) and self.planner and self.planner.active:
            taken = self.planner.take_plan() if choice == MAKE_IT else None
            try:
                if taken:  # every block is ready: build it
                    yield from self._build(*taken)
                elif choice == MAKE_IT:
                    yield from say("That one can't be made yet.")
                else:
                    yield from self.planner.choose(id, choice)
            except OllamaError as exc:
                yield Error(str(exc))
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
        if self.planner:
            self.planner.draft = None
        if self.chat:
            self.chat.reset()

    # ------------------------------------------------------ switch-on agents

    def _idea(self, text: str, request: str) -> Iterator[Event]:
        """Talk an idea through; when every part already exists, build it at once
        instead of showing the idea card."""
        for event in self._remember_ideas(text, self.planner.start(request)):
            if isinstance(event, IdeaCard) and event.level == "ready":
                yield Thinking("Every part already exists, so I can build it now.")
                yield from self._build(*self.planner.take_plan())
                return
            yield event

    def _build(self, blueprint: str, request: str, blocks: list[str]) -> Iterator[Event]:
        if blueprint == CUSTOM:
            yield from self.builder.compose(request, blocks)
        else:
            yield from self.builder.start(blueprint, request)

    def _add_starter(self, starter: Starter, switch_on: bool) -> Iterator[Event]:
        """A ready-made agent: added at once, and switched on if the user said so."""
        agent = store.find_agent(starter.name)
        if agent is None:
            yield Thinking(f"{starter.name} is ready-made, so there's nothing to set up.")
            agent = install(starter)
        if not self._switchable(agent):
            yield from say(f'{agent.name} is ready. To use it, start your message with its name, like '
                           f'"{agent.name}: your text here".')
        elif switch_on:
            yield from self._toggle(agent.name, on=True)
            return
        else:
            yield from say(f'{agent.name} is ready. Say "turn on {agent.name}" or use its switch, then '
                           "highlight text in any program.")
        yield self._agent_list()

    def _switchable(self, agent: store.Agent) -> bool:
        return is_switchable(agent, self.blueprints)

    def details(self, name: str) -> dict:
        """What an agent's page shows. Empty if there's no such agent."""
        agent = store.find_agent(name)
        return describe(agent) if agent else {}

    def _agent_list(self) -> AgentList:
        agents = store.list_agents()
        return AgentList(
            [a.name for a in agents],
            [a.name for a in agents if self._switchable(a)],
            [a.name for a in agents if self.quick and self.quick.is_on(a.name)],
        )

    def _full_lists(self, events: Iterator[Event]) -> Iterator[Event]:
        """The builder and runner only know agent names; the UI also needs
        which agents can be switched on and which are on."""
        for event in events:
            if isinstance(event, AgentList):
                if self.quick:
                    self.quick.refresh(store.list_agents())  # changed settings apply at once
                event = self._agent_list()
            yield event

    def _toggle(self, name: str, on: bool | None = None) -> Iterator[Event]:
        agent = store.find_agent(name)
        if agent is None or not self._switchable(agent) or self.quick is None:
            yield Error(f"{name} isn't an agent that can be switched on.")
            return
        on = not self.quick.is_on(agent.name) if on is None else on
        self.quick.switch(agent, on)
        if on:
            how = {"Copy it to the clipboard": "and the result is copied, ready to paste",
                   "Both": "and the result appears above it and is copied"}.get(
                       agent.slots.get("show"), "and the result appears right above it")
            yield from say(f"{agent.name} is on. Highlight text in any program {how}. "
                           f'Say "turn off {agent.name}" or use its switch to stop it.')
        else:
            yield from say(f"{agent.name} is off.")
        yield self._agent_list()

    # --------------------------------------------------------- trouble

    def _diagnose(self, agent: store.Agent) -> Iterator[Event]:
        """Why an agent seems not to work, from its settings, with a fix to click."""
        slots = agent.slots
        problems, fixes = [], {}
        if agent.blueprint == CUSTOM and slots.get("when") != WHILE_ON:
            problems.append("it's set to work only when you ask in the chat, so it ignores highlights")
            fixes["when"] = WHILE_ON
        if slots.get("show") == CLIPBOARD:
            problems.append("it copies the result to the clipboard instead of showing it")
            fixes["show"] = BUBBLE
        instruction = slots.get("instruction", "")
        translator = re.search(r"translat|번역", f"{agent.name} {instruction}", re.IGNORECASE)
        if agent.blueprint == CUSTOM and (MECHANICS.search(instruction) or needs_language(instruction)):
            language = target_language(instruction) or language_in(instruction)
            if translator and language:
                problems.append(f'what it does reads "{instruction}" instead of a clear job')
                fixes["instruction"] = with_language("Translate the text.", language)
            elif translator:
                problems.append("it doesn't say which language to translate into")
        on = self.quick.is_on(agent.name) if self.quick else False
        switch_on = not on and (fixes.get("when") == WHILE_ON or self._switchable(agent))
        if problems:
            yield Thinking(f"Checked {agent.name}'s settings: " + "; ".join(problems) + ".")
            fix = ", ".join(_fix_words(fixes))
            if switch_on:
                fix += (", and switch it on" if fix else "switch it on")
            self.fixing = (agent.name, fixes, switch_on)
            if "language" in " ".join(problems) and "instruction" not in fixes:
                yield Question(FIX_AGENT, f"I found why: {problems[-1]}. Which language should it translate into?",
                               ["Korean", "English", "Japanese", "Chinese", "Spanish", LEAVE_IT])
                return
            yield Question(FIX_AGENT, f"I found why: {', and '.join(problems)}. Should I {fix}?", [FIX_IT, LEAVE_IT])
        elif switch_on:
            self.fixing = (agent.name, {}, True)
            yield Question(FIX_AGENT, f"{agent.name} is switched off right now. Switch it on?", ["Switch it on", LEAVE_IT])
        else:
            yield from say(f"{agent.name} is on and set up right. Some programs don't tell me what's highlighted. "
                           "It works in browsers like Edge, Chrome and Whale, and in Word and Notepad. Highlight by "
                           "dragging over the text or double-clicking a word, then wait a second for the bubble.")

    def _apply_fix(self, choice: str) -> Iterator[Event]:
        fixing, self.fixing = self.fixing, None
        agent = store.find_agent(fixing[0]) if fixing else None
        if agent is None or choice == LEAVE_IT:
            yield from say("Okay, I left it as it is." if agent else "That question has already been answered.")
            return
        name, fixes, switch_on = fixing
        if language := language_in(choice):
            fixes = {**fixes, "instruction": with_language("Translate the text.", language)}
        agent.slots.update(fixes)
        store.save(agent)
        if switch_on and self.quick:
            self.quick.switch(agent, True)
        elif self.quick:
            self.quick.refresh(store.list_agents())
        state = "It's on: highlight text in any program to try it." if switch_on or (
            self.quick and self.quick.is_on(name)) else "Switch it on in your helpers list to try it."
        yield from say(f"Fixed. {state}")
        yield self._agent_list()

    def _remember_ideas(self, text: str, events: Iterator[Event]) -> Iterator[Event]:
        """Elaina hears about idea cards too, so a follow-up in the chat makes sense."""
        for event in events:
            if isinstance(event, IdeaCard):
                self.chat.remember(text, f"(Idea card: {event.title}) {event.verdict}")
            yield event

    def _hardware(self) -> tuple[hardware.HardwareReport, float]:
        """This computer, and how much memory Elaina's model takes on it."""
        report = hardware.detect()
        tag = elaina.load_state().get("base_model")
        model = find_model(tag) if tag else recommend(report).model
        return report, model.memory_gb if model else 3.0

    def _run_agent(self, name: str, request: str, text: str) -> Iterator[Event]:
        agent = store.find_agent(name)
        if agent is None:
            yield Error(f"I can't find an agent called {name}.")
            return
        if agent.blueprint == CUSTOM:
            # Asked in the chat ("Word explainer: serendipity"): do its job here.
            result = run_instruction(self.ollama, elaina.ELAINA_MODEL, agent.slots.get("instruction", ""),
                                     request, self.chat.think)
            self.chat.remember(text, f"({agent.name} answered) {result}")
            yield Result(agent.name, result)
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
        if self.quick:
            self.quick.switch(agent, False)
        store.delete(agent)
        yield from say(f"Deleted {agent.name}.")
        yield AgentList([a.name for a in store.list_agents()])


def _fix_words(fixes: dict) -> list[str]:
    """What a fix does, in plain words, for the question that offers it."""
    words = {"when": "make it work on highlights", "show": "show the result in a bubble above the text",
             "instruction": "make it just translate the text"}
    return [words[key] for key in fixes if key in words]
