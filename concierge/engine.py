"""The real engine, following the contract in events.py.

Every message goes one of three ways: while an agent is being set up it
answers the setup; otherwise the router decides between chatting with
Elaina, creating a new agent, and running an existing one. Every exchange
is saved as part of a conversation (conversations.py). Elaina must already
be set up (`python -m concierge setup`).
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path

from . import activity, elaina, hardware, history, pictures, portrait, safety, savings, signs, voice
from .agents import community, runner, store
from .agents.blueprint import load_blueprints
from .agents.builder import AgentBuilder, say
from .agents.planner import IDEA, IDEA_CHANGE, MAKE_IT, IdeaPlanner, describe_ideas
from .agents.router import names_an_agent, refers_to, route, wants_change
from .agents.starters import Starter, asks_for, install
from .attachments import NOTHING_SAID, Attached, read_attachments
from .catalog import find_model, recommend
from .conversations import ChatBook
from .events import (AgentList, ElainaDone, ElainaText, Error, Event, IdeaCard, Question, Result, SystemInfo,
                     Thinking)
from .models import ModelMenu
from .ollama import Ollama, OllamaError
from .quick import spot
from .quick.agents import QuickAgents
from .quick.tidy import downloads_dir
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
# What each Spot button counts as on Today.
SPOT_KINDS = {"polish": activity.POLISHED, "shorter": activity.POLISHED, "explain": activity.EXPLAINED,
              "error": activity.EXPLAINED, "code": activity.EXPLAINED, "problems": activity.EXPLAINED,
              "translate": activity.TRANSLATED, "summarize": activity.SUMMED_UP}
# The jobs timed in the first two minutes: real jobs she does every day, small enough to be quick.
MEASURED_JOBS = (
    ("to explain a word you highlight", "Explain this word in simple, everyday words, in one sentence.", "serendipity"),
    ("to polish a messy message", "Rewrite the text so it reads clearly and politely. Keep its meaning.",
     "hey can u send me that report asap, its late and the boss keeps asking"),
    ("to translate a paragraph", "Translate the text into {language}.",
     "The library opens at nine on weekdays and at ten on weekends. Books can be borrowed for three weeks, "
     "and you can renew them online if nobody else is waiting for them."),
)
# The buttons under an answer, and what each says in the chat. Code knows what they
# mean, so they skip the router, where "shorter" could change one of the user's agents.
# "cloud" asks the picked model after all, when the answer was kept on this computer.
FOLLOW_UPS = {"shorter": "Shorter, please.", "more": "Tell me more.", "cloud": "Ask {model} instead."}


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
        self.talker_name = ""  # the model writing her answers, if it isn't her own
        self._talker_here = True  # whether that model runs on this computer
        self._cloud_system = ""  # what goes to a cloud model as her persona, counted in savings
        # What the last answer kept off the picked cloud model, or None (savings.py).
        self.saved: dict | None = None
        self.menu = ModelMenu(self.ollama, self._hardware)
        self.menu.changed = self._use_chosen_model

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
            self.chat.about = portrait.about_you(portrait.load())
            self._use_chosen_model()
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

    # Outside the contract, like details(): the full window's model menu, + button
    # and reservations call these through ChatHub.

    def send_files(self, text: str, paths: list[str], think: bool = False) -> Iterator[Event]:
        """A message with things added to it. They are the point of the message,
        so it goes straight to Elaina instead of through the router."""
        if self.chat is None:
            yield Error("Elaina is not running. Restart the app after setting her up.")
            return
        attached = read_attachments(paths)
        said = "\n".join(filter(None, [text, f"Attached: {', '.join(attached.names)}"]))
        yield from self._full_lists(self.book.record(said, self._with_attachments(text, attached, think)))

    def follow_up(self, which: str, think: bool = False) -> Iterator[Event]:
        """Shorter or More detail, clicked under her last answer (FOLLOW_UPS)."""
        if self.chat is None:
            yield Error("Elaina is not running. Restart the app after setting her up.")
            return
        if which not in FOLLOW_UPS:
            return
        self.deleting = None
        self.fixing = None
        if which in voice.BUDGETS:
            self.chat.kind = which
        yield from self._full_lists(self.book.record(self.follow_up_words(which), self._follow_up(which, think)))

    def follow_up_words(self, which: str) -> str:
        """What a click on a button under an answer says in the chat."""
        return FOLLOW_UPS.get(which, "").format(model=self.talker_name or "the model I picked")

    def _follow_up(self, which: str, think: bool) -> Iterator[Event]:
        try:
            if which == "cloud":
                # The same question again, to the picked model this time.
                if self.saved is None or not self._cloud_picked():
                    return
                question = self._question()
                yield Thinking(f"You asked for {self.talker_name}, so this one goes to {self.talker_name}.")
                yield from self._reply(question, think)
                return
            # Shorter and More detail stay where the answer they follow was made.
            here = self.saved is not None
            yield Thinking("You asked for it shorter, so I'll keep only what matters most." if which == "shorter"
                           else "You asked for more, so I'll go further without repeating myself.")
            yield from self._reply(FOLLOW_UPS[which], think, here=here)
        except OllamaError as exc:
            yield Error(str(exc))

    def after_answer(self, reply: str) -> dict:
        """What can go under a reply the page just showed. Only her answer in the chat
        gets Shorter and More detail, not a setup's message or a switch's note; and only
        a plan that names places gets the one-time question about photos."""
        if not self._answered(reply):
            return {"follow_ups": False, "places": False, "saved": None}
        return {"follow_ups": True, "places": pictures.worth_asking(self._question(), self.chat.history[-1]["content"]),
                "saved": self.saved}

    def pictures(self, reply: str) -> list[dict]:
        """Photos of the places her answer names, for beside their lines (pictures.py).
        The page asks only once the user said yes to photos."""
        if not self._answered(reply):
            return []
        return pictures.for_answer(self._question(), self.chat.history[-1]["content"])

    def _answered(self, reply: str) -> bool:
        history = self.chat.history if self.chat else []
        return bool(reply.strip() and history and history[-1]["role"] == "assistant"
                    and reply.strip().startswith(history[-1]["content"]))

    def _question(self) -> str:
        return self.chat.history[-2]["content"] if len(self.chat.history) > 1 else ""

    def set_agent(self, name: str, on: bool) -> Iterator[Event]:
        yield from self.book.record("", self._toggle(name, on=on))

    def recipes(self) -> dict:
        """The agents to discover, and which of them the user already has."""
        have = {agent.name.lower() for agent in store.list_agents()}
        return {"categories": list(community.CATEGORIES),
                "recipes": [{**asdict(recipe), "added": recipe.name.lower() in have} for recipe in community.recipes()]}

    def add_recipe(self, id: str) -> Iterator[Event]:
        recipe = community.find(id)
        if recipe is None:
            yield Error("I can't find that agent any more.")
            return
        community.install(recipe)
        yield self._agent_list()

    def _helpers(self) -> list[tuple[str, str]]:
        """The user's own agents that work on text when asked, for the Spot's buttons."""
        return [(agent.name, agent.slots.get("instruction", "")) for agent in store.list_agents()
                if agent.blueprint == CUSTOM and not self._switchable(agent) and agent.slots.get("instruction")]

    def spot_actions(self, text: str, editable: bool) -> list[dict]:
        return spot.actions_for(text, editable, self._helpers())

    def spot_run(self, action: str, text: str, ask: str = "") -> dict:
        """One Spot job, always on her own model: the Spot reads from any program."""
        try:
            instruction, words = spot.job(action, ask, text, self._helpers())
        except ValueError:
            return {"error": "I don't know that one."}
        if not words:
            return {"error": "Highlight something first, or tell me what to write."}
        try:
            result = run_instruction(self.ollama, elaina.ELAINA_MODEL, instruction, words, self._quick_think())
        except OllamaError as exc:
            return {"error": str(exc)}
        activity.record(SPOT_KINDS.get(action.split(":")[0], activity.HELPED))
        return {"text": result}

    def switch_agent(self, name: str, on: bool) -> Iterator[Event]:
        """A switch on Help me: adds the ready-made agent if it isn't there yet and
        turns it on or off, with nothing said in the chat."""
        agent = store.find_agent(name)
        if agent is None and on and (recipe := community.find(store.slugify(name))):
            community.install(recipe)
            agent = store.find_agent(name)
        if agent and self.quick and self._switchable(agent):
            self.quick.switch(agent, on)
        yield self._agent_list()

    def activity(self) -> dict[str, int]:
        return activity.this_week()

    # ------------------------------------- getting to know the user (history.py)

    def bring_in_history(self, path: str) -> dict:
        """Read a ChatGPT or Claude download. Outside events.py, like measure: it's
        part of getting to know the user, not of a conversation."""
        try:
            return history.bring_in(Path(path))
        except history.HistoryError as exc:
            return {"error": str(exc)}
        except OSError:
            return {"error": "I couldn't open that file."}

    def understand_history(self, progress=None) -> dict:
        """Read everything brought in and work out what she can about the user.
        Always her own model: these chats never go to a cloud one."""
        chats = history.brought_in()
        if not chats:
            return {"error": "There's nothing brought in yet."}
        try:
            made = portrait.understand(self.ollama, elaina.ELAINA_MODEL, chats, self._quick_think(), progress)
        except OllamaError as exc:
            return {"error": str(exc)}
        self._use_portrait()
        return made

    def look_around(self) -> dict:
        """What this computer says about the user (signs.py): names and counts only,
        and only because they asked."""
        summary = signs.look_around()
        made = portrait.add_computer(summary, signs.facts_from(summary))
        self._use_portrait()
        return made

    def bring_in_downloads(self, since: float = 0) -> dict:
        """Every ChatGPT or Claude download in Downloads not read yet. {} when none."""
        read, sources = 0, set()
        for path in history.find_exports(downloads_dir(), since):
            result = self.bring_in_history(str(path))
            if "error" not in result:
                read += result["read"]
                sources.update(result["sources"])
        return {"read": read, "sources": sorted(sources)} if read else {}

    def what_i_know(self) -> dict:
        return portrait.load()

    def keep_fact(self, fact_id: str, kept: bool) -> dict:
        made = portrait.keep(fact_id, kept)
        self._use_portrait()
        return made

    def forget_history(self) -> None:
        """Everything brought in and everything she worked out from it, gone."""
        history.forget()
        portrait.forget()
        self._use_portrait()

    def _use_portrait(self) -> None:
        if self.chat:
            self.chat.about = portrait.about_you(portrait.load())

    def measure(self) -> dict:
        """What this computer can do, timed on it just now, for the first two minutes.
        Every number is measured; nothing is guessed."""
        report = hardware.detect()
        gpu = report.best_gpu()
        device = f"{gpu.name} · {gpu.vram_total_gb:.0f} GB" if gpu and gpu.vram_total_gb else report.cpu_name
        home = spot.home_language()
        other = "English" if home != "English" else "Korean"
        try:
            think = self._quick_think()
            self.ollama.refresh(elaina.ELAINA_MODEL, elaina.KEEP_ALIVE)  # loading her isn't part of a job
            results = []
            for what, instruction, sample in MEASURED_JOBS:
                began = time.monotonic()
                said = run_instruction(self.ollama, elaina.ELAINA_MODEL, instruction.format(language=other),
                                       sample, think)
                seconds = time.monotonic() - began
                results.append({"what": what, "seconds": round(seconds, 1), "words": len(said.split())})
        except OllamaError as exc:
            return {"device": device, "error": str(exc)}
        # All three jobs together, so one quick answer can't make the speed look odd.
        seconds = sum(job["seconds"] for job in results)
        return {"device": device, "results": results,
                "words_per_second": round(sum(job["words"] for job in results) / seconds) if seconds else None}

    def _quick_think(self) -> bool | None:
        """Thinking off for small jobs, the same as in the chat. Asked of the model itself when
        the page calls before startup has finished, because a thinking model left to its
        default thinks first, and a word took 13 seconds to explain instead of a fraction of one."""
        if self.chat:
            return self.chat.think
        return False if "thinking" in self.ollama.capabilities(elaina.ELAINA_MODEL) else None

    def post_agent(self, name: str, about: str, category: str, by: str = "") -> dict:
        """The page that posts an agent, for the window to open. Nothing is sent from here."""
        agent = store.find_agent(name)
        if agent is None:
            return {"error": "Please pick one of your agents."}
        try:
            address = community.post_address(agent, about, category, by)
        except community.PostError as exc:
            return {"error": str(exc)}
        if not community.can_post():
            return {"error": "Posting isn't open yet, because the shared place for agents hasn't been set up."}
        return {"address": address}

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
        if safety.crisis(text):
            # Before anything else, setups included: this is no moment for a form.
            yield Thinking("This sounds serious, so I'm answering with care, not guessing.")
            yield from say(safety.crisis_reply(text))
            return
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
            else:
                job = self._job_for_here(text)
                if job:
                    yield Thinking(f"I can {savings.JOB_WORDS[job]} myself, so {self.talker_name} isn't needed.")
                else:
                    yield Thinking(f"This is just a chat, so I'll ask {self.talker_name}." if self.talker_name
                                   else "This is just a chat, so I'll answer it myself.")
                if think and not self.chat.can_think and not self.talker_name:
                    yield Thinking("This model can't show its thinking, so here is my answer.")
                yield from self._reply(text, think, here=bool(job))
        except OllamaError as exc:
            yield Error(str(exc))

    def _reply(self, text: str, think: bool, here: bool = False) -> Iterator[Event]:
        """Her answer. `here` keeps it on this computer although a cloud model is picked,
        and counts what that kept off the user's plan (savings.py)."""
        self.saved = None
        talker = self.chat.talker
        if here:
            self.chat.talker = self.ollama
        try:
            if think and self.chat.can_think:
                for kind, piece in self.chat.think_through(text):
                    yield Thinking(piece, "thought") if kind == "thought" else ElainaText(piece)
            else:
                for chunk in self.chat.send(text):
                    yield ElainaText(chunk)
        finally:
            self.chat.talker = talker
        if here:
            tokens = savings.kept(self.chat.recent_messages(), self._cloud_system)
            activity.record(activity.SAVED, tokens)
            self.saved = {"tokens": tokens, "model": self.talker_name}
        if note := safety.caution(text):
            yield ElainaText(f"\n\n{note}")
        activity.record(activity.ANSWERED)
        yield ElainaDone()

    def _with_attachments(self, text: str, attached: Attached, think: bool) -> Iterator[Event]:
        self.deleting = None
        self.fixing = None
        try:
            for name in attached.unread:
                yield Thinking(f"I couldn't read {name}.")
            if attached.folders:
                yield Thinking("A folder is what a documents agent is for, so I'll set one up.")
                yield from self.builder.start_for_folder("documents_qa", Path(attached.folders[0]), text)
                return
            images = attached.images
            if images and not self.chat.can_see:
                images = []
                yield Thinking("The model I'm using can't look at pictures.")
                if not attached.context:
                    yield from say("The model I'm using can't look at pictures. Pick one that can from the model "
                                   "menu, then send it again.")
                    return
            if not attached.context and not images:
                yield from say("I couldn't read that. I can read PDF, Word and text files, and pictures.")
                return
            read = [name for name in attached.names if name not in attached.unread]
            yield Thinking(f"Read {', '.join(read)}.")
            self.chat.attach(attached.context, images)
            job = "" if images else self._job_for_here(text)
            if job:
                yield Thinking(f"I can {savings.JOB_WORDS[job]} myself, so {self.talker_name} isn't needed.")
            yield from self._reply(text or NOTHING_SAID, think, here=bool(job))
        except OllamaError as exc:
            yield Error(str(exc))

    def _use_chosen_model(self) -> None:
        """Only her answers move to the model picked in the menu. Deciding what a
        message is for stays with her own small model, and so do agents that read
        every highlight: those see whatever the user selects, in any program, so
        that must never leave the computer without them asking each time."""
        chosen = self.menu.chosen()
        self.talker_name = chosen["name"] if chosen else ""
        self._talker_here = chosen["here"] if chosen else True
        self.saved = None
        if self.chat is None:
            return
        try:
            system = self.ollama.show(elaina.ELAINA_MODEL).get("system", "") if chosen else ""
        except OllamaError:
            system = ""
        self._cloud_system = system
        self.chat.talker = self.menu.talker(system) or self.ollama

    def _cloud_picked(self) -> bool:
        return bool(self.talker_name) and not self._talker_here

    def _job_for_here(self, text: str) -> str:
        """A job worth keeping on this computer although a cloud model is picked, or ""."""
        return savings.local_job(text) if self._cloud_picked() else ""

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
            result = run_instruction(self.chat.talker, elaina.ELAINA_MODEL, agent.slots.get("instruction", ""),
                                     request, self.chat.think)
            activity.record(activity.HELPED)
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
