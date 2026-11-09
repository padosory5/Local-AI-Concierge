"""The real engine, following the contract in events.py.

Every message goes one of three ways: while an agent is being set up it
answers the setup; otherwise the router decides between chatting with
Noir, creating a new agent, and running an existing one. Every exchange
is saved as part of a conversation (conversations.py). Noir must already
be set up (`python -m concierge setup`).
"""

from __future__ import annotations

import re
import sys
import time
from collections.abc import Iterator
from dataclasses import asdict, replace
from pathlib import Path

from . import (activity, auto, chores, cloud, noir, hardware, history, pictures, portrait, research, researcher, safety, signs,
               sources, usage, voice)
from .accounts import APPS
from .agents import community, runner, store
from .agents.blueprint import load_blueprints
from .agents.builder import AgentBuilder, say, YES_WORDS
from .agents.planner import IDEA, IDEA_CHANGE, MAKE_IT, IdeaPlanner, describe_ideas
from .agents.router import WANTS_NEW as WANTS_NEW_AGENT, wants_change, SORTS, SUMS_UP, WATCHES, FILES
from .agents.router import names_an_agent, refers_to, route, wants_change, KIND_WORDS, kinds_named
from .agents.starters import Starter, asks_for, install
from .attachments import NOTHING_SAID, Attached, read_attachments
from .catalog import find_model, recommend
from .conversations import ChatBook
from .events import (AgentList, NoirDone, NoirText, Error, Event, IdeaCard, Progress, Question, Result, SystemInfo,
                     Thinking)
from .models import ModelMenu
from .ollama import Ollama, OllamaError
from .quick import spot
from .quick.agents import QuickAgents
from .quick.tidy import downloads_dir
from .agents.recipe import (BUBBLE, CLIPBOARD, CUSTOM, MECHANICS, WHILE_ON, describe, is_switchable, migrate,
                            needs_language, run_instruction, target_language, with_language)
from .agents.talk import phrase
from .organizer import ORGANIZER, SUMMARIZER, WATCHED_KINDS, Organizer, notes_path
from .organizer import how as organizer_how
from .quick.translate import language_in
from .setup import Setup

# "delete the Sample docs helper 2 agent", "remove my contracts helper"
WANTS_DELETE = re.compile(r"\b(delete|remove|get rid of|uninstall)\b|삭제|지워", re.IGNORECASE)
# "show my ideas", "what ideas did I save?"
WANTS_IDEAS = re.compile(r"\b(my|saved)\s+ideas\b|\bideas\s+(list|i saved)\b|아이디어\s*(목록|보여)",
                         re.IGNORECASE)
# "turn on the Korean translator", "switch off my translator", "번역기 켜줘"
# With a file organizer: where a file went, and "organize it" for what just landed.
WANTS_WHERE = re.compile(r"(\bwhere(?:'s|s)?\b|\bwhich folder\b).*\b(files?|folders?|pdf|documents?|it|that|them|they|these|those|"
                         r"put|moved?|went|go|gone|end(ed)? up|created|made|saved|sorted)\b", re.IGNORECASE)
WANTS_STATUS = re.compile(r"\b(what (did|have) you (do|done|moved?|sorted?)|did you (move|sort|do|put|organi[sz]e) "
                          r"(anything|something|it|them|the|my)|what are you doing|what('s| is) (running|on|going on)|"
                          r"which folders? (do you have|did you make|are there|exist)|how many files)\b", re.IGNORECASE)
WANTS_ORGANIZE = re.compile(r"\borgani[sz]e\b|\bsort (it|this|that|them|these|my|the)\b|\bdownloaded\b|\bfile (it|this|that|them)\b|"
                            r"\bmove (the|my|these|those) (files|documents|pdfs)\b|\bgo through\b", re.IGNORECASE)
# "Why didn't you move the receipt?", "why is my tuition statement still in downloads?":
# answered from the organizer's record of each verdict, never by the chat model.
WANTS_WHY = re.compile(r"\bwhy\b.*\b(move|moved|sort|sorted|organi[sz]ed?|put|filed?|still|left|skip|skipped|touch|touched|"
                       r"ignore|ignored|stay|stayed)\b", re.IGNORECASE)
WHERE_WORDS = re.compile(r"\bwhere(?:'s|s)?\b|\bwhich folder\b", re.IGNORECASE)
# A message about the organizer's own work, which its facts answer here, never the web.
ABOUT_CHORES = re.compile(r"\b(organi[sz]ers?|organi[sz]e[ds]?|organi[sz]ing|watch(es|ing|ed)?|sort(s|ed|ing)?|folders?|"
                          r"files?|pdfs?|documents?|chores?|move[ds]?|moving|downloads|lands?|arrives?|comes? in|"
                          r"something new|new (files?|things?|stuff))\b", re.IGNORECASE)
# A short question with a pronoun soon after an organizer did something ("where did they
# go?") is about that, not about the world.
FOLLOWS_A_CHORE = re.compile(r"\b(it|they|them|that|those|these)\b", re.IGNORECASE)
CHORE_FRESH_SECONDS = 600
# A request for new work ("when a pdf lands, write me a summary"), never a question about a chore.
ASKS_FOR_WORK = re.compile(r"\b(write me|make|create|set ?up|build|start|every time|whenever|from now on|automatically|"
                           r"when (a|an|any|new|each) \w+ (lands|arrives|comes|appears|downloads))\b", re.IGNORECASE)
# A message that asks something rather than tells an agent to do it.
WANTS_ANSWER = re.compile(r"\?|^\s*(which|where|what|why|how|when|who|is|are|was|were|did|do|does|can|could|have|has|"
                          r"will|would|should)\b", re.IGNORECASE)
# A plain no, for the organizer's question about a kind of file (yes is the builder's YES_WORDS).
NO_WORDS = ("no", "nope", "no thanks", "leave it", "leave them", "don't", "dont", "not now", "아니", "아니요", "싫어")
# Words of a question that never name a file.
_ASKING_WORDS = {"why", "did", "didn", "didnt", "not", "you", "the", "file", "files", "pdf", "move", "moved", "sort", "sorted",
                 "still", "downloads", "download", "folder", "folders", "into", "that", "this", "them", "what", "about",
                 "organize", "organise", "left", "behind", "there", "here", "with", "from", "have", "haven", "were", "was",
                 "your", "put", "where", "wheres", "which", "inside", "created", "document", "documents", "and", "for",
                 "are", "its", "how", "all", "any", "one", "now", "yet", "too", "but", "can", "has", "had", "new"}
# "put output.pdf in math", "move the scan to CHEM142": a move the user orders, which also
# teaches the organizer where that course and that kind of file go.
WANTS_PLACE = re.compile(r"^\s*(?:please |can you |could you |just )?(?:put|move|file|place|drop) (.+?) (?:in|into|to|under) "
                         r"(?:the |my |a )?(?:folder (?:called |named )?)?(.+?)(?: folder)?(?:,? please)?\s*[.!]?$", re.IGNORECASE)
WANTS_EVERYTHING = re.compile(r"\b(everything|all (the |of )?(files|documents|of them|of it)|whole folder|all my)\b", re.IGNORECASE)
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
# The jobs timed in the first two minutes: real jobs it does every day, small enough to be quick.
MEASURED_JOBS = (
    ("to explain a word you highlight", "Explain this word in simple, everyday words, in one sentence.", "serendipity"),
    ("to polish a messy message", "Rewrite the text so it reads clearly and politely. Keep its meaning.",
     "hey can u send me that report asap, its late and the boss keeps asking"),
    ("to translate a paragraph", "Translate the text into {language}.",
     "The library opens at nine on weekdays and at ten on weekends. Books can be borrowed for three weeks, "
     "and you can renew them online if nobody else is waiting for them."),
)
# The two buttons under an answer, and what each says in the chat. Code knows what they
# mean, so they skip the router, where "shorter" could change one of the user's agents.
FOLLOW_UPS = {"shorter": "Shorter, please.", "more": "Tell me more."}
# After a file organizer is made: go through what is in the folder already, or not.
ORGANIZE_NOW = "organize_now"
# "Can you create an agent that can handle my files": a helper for files, but which kind
# isn't said, so Noir asks with the kinds as buttons rather than let the model guess.
WHICH_KIND = "which_kind"
SOMETHING_ELSE_KIND = "Something else"
KIND_SHORT = {"organizer": "sort new ones into folders by what they're about",
              "summarizer": "write a few lines about each new one into a notes file",
              "documents_qa": "answer questions about what's in them"}
GO_THROUGH, ONLY_NEW = "Yes, go through them", "Only new files from now on"


def _plain_answer(text: str) -> bool | None:
    """True for a plain yes, False for a plain no, None for anything more."""
    words = text.strip().lower().strip("!. ")
    if words in YES_WORDS:
        return True
    if words in NO_WORDS:
        return False
    return None


def _names_a_folder(text: str, question: dict) -> bool:
    """A short name typed while a new-course question waits ("math207", "Linear algebra"): the
    folder the user wants for it. A question, a greeting or a sentence is not one."""
    if question.get("kind") != "subject":
        return False
    words = text.strip().strip("\"'")
    if not words or len(words.split()) > 3 or words.endswith("?") or len(words) > 40:
        return False
    return not re.search(r"\b(hi|hello|hey|thanks|thank you|what|where|why|how|organi[sz]e|sort|move|stop|wait)\b",
                         words, re.IGNORECASE)


def _question_for_name(text: str, pending: list[dict]) -> dict | None:
    """The new-course question a typed folder name answers: the one whose course the name
    echoes ("math207" for MATH 207), else the newest, since people answer what they just saw."""
    subjects = [q for q in pending if _names_a_folder(text, q)]
    if not subjects:
        return None
    compact = re.sub(r"[\s_\-]+", "", text).upper()
    for question in subjects:
        subject = re.sub(r"[\s_\-]+", "", question["id"].split(":", 2)[-1]).upper()
        if subject and (subject in compact or compact in subject):
            return question
    return subjects[-1]


def _mentions(text: str, name: str) -> bool:
    """Whether a question names this file: a word of the question is in the file's name, so
    "the tuition pdf" finds UWTuitionStatement.pdf and "the receipt" bookstore_receipt.pdf."""
    lowered = name.lower()
    return any(word in lowered for word in re.findall(r"[a-z0-9]{3,}", text.lower()) if word not in _ASKING_WORDS)


class NoirEngine:
    def __init__(self, ollama: Ollama | None = None):
        self.ollama = ollama or Ollama()
        self.chat: noir.NoirChat | None = None
        self.builder: AgentBuilder | None = None
        self.planner: IdeaPlanner | None = None
        self.quick: QuickAgents | None = None
        self.blueprints = load_blueprints()
        self.book = ChatBook(noir.data_dir() / "conversations",
                             history=lambda: self.chat.history if self.chat else [])
        self.deleting: str | None = None  # agent waiting for "Delete it" / "Keep it"
        # A diagnosis waiting for "Fix it": (agent name, settings to change, switch it on)
        self.fixing: tuple[str, dict, bool] | None = None
        self.talker_name = ""  # the model writing its answers, if it isn't its own
        # Auto (auto.py): its own model answers, and this one gets the hard questions.
        self.auto_cloud = None
        self.auto_last = ""  # where the last chat answer came from, for "why?" and "go on"
        self.auto_kind = ""  # what the last one kept here was, counted if asked again
        # Looking things up on the web (research.py): the message waiting for the user's
        # first yes, and what the last lookup found, for the sources under the answer.
        self.pending_lookup: tuple[str, bool, str] | None = None
        self.found: research.Findings | None = None
        # File organizers (organizer.py) run on every system, so they are made here, not at startup.
        self.organizer = Organizer(self.ollama, noir.NOIR_MODEL, noir.data_dir() / "organizer.json",
                                   noir.data_dir() / "organizer_done.json")
        self.organizing: str | None = None  # the organizer just made, waiting for "go through them?"
        self.asking_kind: str | None = None  # the request for a helper for files, waiting for which kind
        self.chore_spoken_at = 0.0  # when an organizer last said or did something in this chat
        self.menu = ModelMenu(self.ollama, self._hardware)
        self.menu.changed = self._use_chosen_model
        self.setup = Setup(self.ollama)  # the first run's one button (setup.py)

    # ----------------------------------------------------------- contract

    def startup(self) -> Iterator[Event]:
        report = hardware.detect()
        rec = recommend(report)
        tag = noir.load_state().get("base_model")
        model = find_model(tag) if tag else None
        in_use = f"{model.name} ({tag})" if model else tag or "not set up"
        recommended = f"{rec.model.name} ({rec.model.tag})" if rec.model else None
        note = rec.reason if rec.model is None else ""
        if rec.model and tag and tag != rec.model.tag:
            note = f"Not the recommended {rec.model.name}. Run `python -m concierge setup` to switch."
        yield SystemInfo(hardware.describe(report), recommended, in_use, rec.device_name, note)

        try:
            self.ollama.ensure_running()
            if not self.ollama.has_model(noir.NOIR_MODEL):
                yield Error("Noir isn't set up on this computer yet.")
                return
            if model and self.ollama.has_model(model.tag) and noir.needs_configure(self.ollama, model, rec, report):
                # Its prompt changed with the program (how it talks is part of it), so
                # it is rebuilt from the same base model before the first message. It
                # takes a moment, and without it a fix to its words never reaches the app.
                noir.configure(self.ollama, model, rec, report)
            self.chat = noir.NoirChat(self.ollama)
            self.chat.about = portrait.about_you(portrait.load())
            self._use_chosen_model()
        except OllamaError as exc:
            yield Error(str(exc))
            return
        self.builder = AgentBuilder(self.ollama, noir.NOIR_MODEL, self.chat.think, self.blueprints)
        self.planner = IdeaPlanner(self.ollama, noir.NOIR_MODEL, self.chat.think, self._hardware,
                                   self.blueprints)
        # Switch-on agents read highlights through Windows; on a Mac there are none yet.
        self.quick = QuickAgents(self.ollama, noir.NOIR_MODEL, self.chat.think) if sys.platform == "win32" else None
        migrate()  # agents of retired blueprints become agents made from parts
        self.organizer.refresh(store.list_agents())
        yield self._agent_list()
        yield self.book.chat_list()

    def send(self, text: str, think: bool = False) -> Iterator[Event]:
        if self.chat is None:
            yield Error("Noir is not running. Restart the app after setting it up.")
            return
        yield from self._full_lists(self.book.record(text, self._handle(text, think)))

    def choose(self, id: str, choice: str) -> Iterator[Event]:
        if self.chat is None:
            yield Error("Noir is not running. Restart the app after setting it up.")
            return
        yield from self._full_lists(self.book.record(choice, self._handle_choice(id, choice)))

    # The book saves the open conversation (with Noir's memory of it) before
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
        so it goes straight to Noir instead of through the router."""
        if self.chat is None:
            yield Error("Noir is not running. Restart the app after setting it up.")
            return
        attached = read_attachments(paths)
        said = "\n".join(filter(None, [text, f"Attached: {', '.join(attached.names)}"]))
        yield from self._full_lists(self.book.record(said, self._with_attachments(text, attached, think)))

    def follow_up(self, which: str, think: bool = False) -> Iterator[Event]:
        """Shorter or More detail, clicked under its last answer (FOLLOW_UPS)."""
        if self.chat is None:
            yield Error("Noir is not running. Restart the app after setting it up.")
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
        return FOLLOW_UPS.get(which, "")

    def _follow_up(self, which: str, think: bool) -> Iterator[Event]:
        try:
            yield Thinking("You asked for it shorter, so I'll keep only what matters most." if which == "shorter"
                           else "You asked for more, so I'll go further without repeating myself.")
            yield from self._reply(FOLLOW_UPS[which], think)
        except OllamaError as exc:
            yield Error(str(exc))

    def after_answer(self, reply: str) -> dict:
        """What can go under a reply the page just showed. Only its answer in the chat
        gets Shorter and More detail, not a setup's message or a switch's note; and only
        a plan that names places gets the one-time question about photos."""
        if not self._is_her_answer(reply):
            return {"follow_ups": False, "places": False}
        return {"follow_ups": True, "places": pictures.worth_asking(self._question(), self.chat.history[-1]["content"])}

    def pictures(self, reply: str) -> list[dict]:
        """Photos of the places its answer names, for beside their lines (pictures.py).
        The page asks only once the user said yes to photos."""
        if not self._is_her_answer(reply):
            return []
        return pictures.for_answer(self._question(), self.chat.history[-1]["content"])

    def _is_her_answer(self, reply: str) -> bool:
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
        """One Spot job, always on its own model: the Spot reads from any program."""
        try:
            instruction, words = spot.job(action, ask, text, self._helpers())
        except ValueError:
            return {"error": "I don't know that one."}
        if not words:
            return {"error": "Highlight something first, or tell me what to write."}
        try:
            result = run_instruction(self.ollama, noir.NOIR_MODEL, instruction, words, self._quick_think())
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
        if agent and agent.blueprint in WATCHED_KINDS:
            self.organizer.switch(agent, on)
        elif agent and self.quick and self._switchable(agent):
            self.quick.switch(agent, on)
        yield self._agent_list()

    def activity(self) -> dict[str, int]:
        """This week's jobs for Today, with the tokens Auto kept off the user's plans
        and keys (usage.py), so the week's sentence can say "and saved about 12,400 tokens"."""
        counts = activity.this_week()
        saved = sum(plan["week"]["saved"] for plan in usage.summary().values())
        if saved:
            counts["saved"] = saved
        return counts

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
        """Read everything brought in and work out what it can about the user.
        Always its own model: these chats never go to a cloud one."""
        chats = history.brought_in()
        if not chats:
            return {"error": "There's nothing brought in yet."}
        try:
            made = portrait.understand(self.ollama, noir.NOIR_MODEL, chats, self._quick_think(), progress)
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
        """Everything brought in and everything it worked out from it, gone."""
        history.forget()
        portrait.forget()
        self._use_portrait()

    def _use_portrait(self) -> None:
        if self.chat:
            self.chat.about = portrait.about_you(portrait.load())

    # First-run setup from inside the window (setup.py): the page asks how far it is,
    # presses one button, and starts it again when done (ChatHub.restart).

    def setup_state(self) -> dict:
        return self.setup.state()

    def setup_begin(self, smallest: bool = False) -> dict:
        return self.setup.begin(bool(smallest))

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
            self.ollama.refresh(noir.NOIR_MODEL, noir.KEEP_ALIVE)  # loading its isn't part of a job
            results = []
            for what, instruction, sample in MEASURED_JOBS:
                began = time.monotonic()
                said = run_instruction(self.ollama, noir.NOIR_MODEL, instruction.format(language=other),
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
        return False if "thinking" in self.ollama.capabilities(noir.NOIR_MODEL) else None

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
        self.organizer.stop()
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
        yield from self._waking()
        try:
            # An agent setup or an idea in progress gets the message first; if
            # the user moved on, it hands the message back for normal routing.
            for flow in (self.builder, self.planner):
                if flow.active:
                    yield from (self._building(flow.answer(text)) if flow is self.builder else flow.answer(text))
                    if flow.handoff is None:
                        return
                    text, flow.handoff = flow.handoff, None
            if self.asking_kind:
                # "sort them into folders" typed under "which kind?": the request and the answer
                # together say what to make; anything else means the user moved on.
                request, self.asking_kind = self.asking_kind, None
                if len(text.split()) <= 12 and (kinds_named(text, self.blueprints) or FILES.search(text)):
                    text = f"{request}. {text}"
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
            organizers = [a for a in agents if a.blueprint in WATCHED_KINDS]
            if organizers and self._follows_a_chore(text):
                text_about = True  # "where did they go?" a moment after a sort: about the files, never the web
            else:
                text_about = False
            pending = self.organizer.questions() if organizers else []
            named = _question_for_name(text, pending) if pending else None
            if pending and ((said := _plain_answer(text)) is not None or named):
                # "yes" to "hw3.xlsx looks like CSE163 material. Sort .xlsx files like it from now on?"
                # answers the question the windows show (the oldest); a folder name typed for
                # "math207_hw2.pdf looks like a new course, MATH 207" finds its question by the name.
                question = named if said is None else pending[0]
                name = text.strip() if said is None else ""
                said = True if said is None else said
                moved = self.organizer.answer(question["id"], said, name)
                what = question["id"].split(":", 2)[-1]
                yield Thinking(f"That answers the organizer's question about {what}.")
                yield from self._say(self._answered_line(question, said, name, moved))
                return
            if organizers and WANTS_WHY.search(text) and not WANTS_NEW_AGENT.search(text):
                yield Thinking("This asks why a file stayed or moved: the organizer kept its reason for each one.")
                yield from self._say_why(text, organizers)
                return
            asks_where = WANTS_WHERE.search(text) or (WHERE_WORDS.search(text) and (self._names_a_file(text) or text_about))
            if organizers and asks_where and not WANTS_NEW_AGENT.search(text):
                self.chore_spoken_at = time.time()
                yield Thinking("This asks where a file or folder is, which the organizer's own record answers.")
                yield from self._say_where(text, organizers)
                return
            if organizers and WANTS_STATUS.search(text):
                self.chore_spoken_at = time.time()
                yield Thinking("This asks what the organizer has been doing: its record answers, not a guess.")
                yield from self._say_status(organizers)
                return
            if organizers and (placed := WANTS_PLACE.match(text)) and not WANTS_NEW_AGENT.search(text):
                self.chore_spoken_at = time.time()
                yield from self._place(placed.group(1), placed.group(2), organizers)
                return
            if organizers and WANTS_ORGANIZE.search(text) and len(text.split()) <= 20 and not WANTS_NEW_AGENT.search(text):
                chosen = next((a for a in organizers if Path(a.slots.get("folder", "")).name.lower() in text.lower()), organizers[0])
                everything = bool(WANTS_EVERYTHING.search(text))
                self.chore_spoken_at = time.time()
                yield Thinking(f"This is a job for {chosen.name}: "
                               + ("everything in its folder." if everything else "what has landed since it was switched on."))
                yield from self._organize_now(chosen, everything=everything, text=text)
                return
            if organizers and (ABOUT_CHORES.search(text) or text_about) and WANTS_ANSWER.search(text) \
                    and not ASKS_FOR_WORK.search(text) and not WANTS_NEW_AGENT.search(text) \
                    and not any(wants_change(text, a) for a in organizers):
                self.chore_spoken_at = time.time()
                # "can you also sort pictures?": a question about the chore. Sent on, the router
                # once took it for an idea and began a second organizer for Pictures.
                yield from self._answer_about_chores(text, think)
                return
            if WANTS_IDEAS.search(text):
                yield from say(describe_ideas(*self._hardware(), self.blueprints))
                return
            if researcher.wants_research(text):
                yield from self._with_lookup(text, think, researcher.RESEARCH)
                return
            if lookup := self._lookup_kind(text):
                # A question that needs the web is a chat: the router's model call
                # would only say so, a second or two later.
                yield from self._with_lookup(text, think, lookup)
                return
            evidence = {a.name: runner.matching_words(a, text) for a in agents}
            where = route(self.ollama, noir.NOIR_MODEL, text, self.blueprints, agents,
                          think=self.chat.think, evidence=evidence)
            for name, words in evidence.items():
                if words and where.kind != "chat":
                    yield Thinking(f"{name}'s files mention: {', '.join(words)}.")
            if where.kind == "new_agent":
                yield Thinking(f"This asks for a new agent: {self.blueprints[where.blueprint].name}.")
                yield from self._building(self.builder.start(where.blueprint, text))
            elif where.kind == "ask_kind":
                yield Thinking("This asks for a helper for files, but not which kind, so I'll ask rather than guess.")
                yield from self._ask_kind(text)
            elif where.kind == "idea":
                yield Thinking("This is an idea for a new kind of helper, so I'll check what it needs.")
                yield from self._idea(text, where.request)
            elif where.kind == "change_agent" and (agent := store.find_agent(where.agent)):
                yield Thinking(f"This is a change to your {agent.name}.")
                yield from self.builder.edit(agent, text)
            elif where.kind == "run_agent":
                yield Thinking(f"This is a job for {where.agent}.")
                yield from self._run_agent(where.agent, where.request, text, think)
            else:
                if not self.auto_cloud:  # with Auto, _reply says who answers and why
                    yield Thinking(f"This is just a chat, so I'll ask {self.talker_name}." if self.talker_name
                                   else "This is just a chat, so I'll answer it myself.")
                if think and not self.chat.can_think and not self.talker_name:
                    yield Thinking("This model can't show its thinking, so here is my answer.")
                yield from self._reply(text, think)
        except OllamaError as exc:
            yield Error(str(exc))

    def _reply(self, text: str, think: bool, attached_chars: int = 0, where: str = "") -> Iterator[Event]:
        """where: auto.CLOUD to skip Auto's decision ("Ask Claude instead")."""
        done = NoirDone()
        if self.auto_cloud is not None:
            done = yield from self._auto_choose(text, attached_chars, where)
        said = False
        here = self._writes_here()
        try:
            for event in self._answer(text, think):
                said = said or isinstance(event, NoirText)
                yield event
        except cloud.CloudError as exc:
            if said or self.chat.talker is self.ollama or not self.auto_cloud:
                raise
            # The plan said no (signed out, used up, no internet) before a word was
            # written: Auto exists to keep it talking, so it answers itself.
            yield Thinking(f"{self.talker_name} couldn't answer ({exc}), so I'll answer myself.")
            self.chat.talker = self.ollama
            self.auto_last = auto.HERE
            done, here = NoirDone(by=self._own_name()), True
            yield from self._answer(text, think)
        finally:
            if self.auto_cloud is not None:
                self.chat.talker = self.ollama  # agents and the router stay here with Auto
        if note := safety.caution(text):
            yield NoirText(f"\n\n{note}")
        activity.record(activity.ANSWERED)
        if getattr(self, "found", None) is not None:  # the sources and pictures go under this answer
            done = replace(done, sources=list(self.found.sources), images=list(self.found.images))
            self.found = None
        yield self._answered(done, here)

    def _writes_here(self) -> bool:
        """Whether the model about to answer is on this computer."""
        if self.chat.talker is self.ollama:
            return True
        if self.auto_cloud is not None:
            return False  # with Auto, anything but its own model is the plan
        chosen = self.menu.chosen()
        return not chosen or bool(chosen.get("here"))

    def _answered(self, done: NoirDone, here: bool) -> NoirDone:
        """The reply's NoirDone with where it was written, for the dot under it:
        the tokens an answer written here saved (Auto only, since only then was
        there a plan it would have gone to), or how full the plan is after one from it."""
        chosen = self.menu.chosen() or {}
        source = (chosen.get("cloud") or chosen).get("provider", "")
        if here:
            saved = 0
            if self.auto_cloud is not None and source:
                saved = usage.saved_estimate(source, *getattr(self.ollama, "last_tokens", (0, 0)))
                usage.record_saved(source, saved)
            return replace(done, where=auto.HERE, saved=saved)
        plan_used = self.menu.plan_used(source) if source in APPS else -1.0
        return replace(done, where=auto.CLOUD, plan_used=plan_used, by=done.by or self.talker_name)

    # ----------------------------------------------------------- the web

    def _lookup_kind(self, text: str) -> str | None:
        """Whether this message needs the web, and for what. Code decides from the
        words; only a question code can't place is put to its model, as one word."""
        if ASKS_FOR_WORK.search(text) or (WATCHES.search(text) and (SUMS_UP.search(text) or SORTS.search(text))):
            return None  # a request for new work ("when a pdf lands, write me a summary") is never a lookup
        if ABOUT_CHORES.search(text) and any(a.blueprint in WATCHED_KINDS for a in store.list_agents()):
            # "is the organizer still on?", "can you also sort pictures?": about its own chore,
            # answered here from its facts; "pictures" would otherwise send it to an image search.
            return None
        kind = research.wants_lookup(text)
        if kind is None and research.allowed() is not False and research.unsure(text):
            kind = research.SEARCH if research.model_form(self.ollama, noir.NOIR_MODEL)(text) else None
        return kind

    def _with_lookup(self, text: str, think: bool, kind: str) -> Iterator[Event]:
        """Answer from the web: after the user's one-time yes, look it up, hand it what
        was found along with the question, and put the sources under its answer."""
        may = research.allowed()
        if may is None:
            self.pending_lookup = (text, think, kind)
            yield Thinking("This can change from day to day, so I'd rather look it up than guess.")
            yield Question(research.WEB, research.WEB_QUESTION, [research.YES_LOOK, research.NO_LOOK])
            return
        if not may:
            yield Thinking("This may have changed since I learned it, and you've asked me not to look things "
                           "up on the web, so this is from memory.")
            yield from self._reply(text, think)
            return
        if kind == researcher.RESEARCH:
            yield from self._research_job(text, think)
            return
        what = {research.WEATHER: "the weather", research.IMAGES: "pictures", research.PRICE: "the price"}.get(kind, "this")
        yield Thinking(f"This changes from day to day, so I'm looking {what} up on the web.")
        yield Progress("Looking it up on the web...")
        try:
            self.found = research.look_up(text, kind)
        except Exception as exc:  # the web, not Ollama: whatever failed, it still answers
            self.found = None
            yield Thinking(f"The web didn't answer ({type(exc).__name__}), so this is from memory and may be "
                           "out of date.")
            yield from self._reply(text, think)
            return
        self.chat.attach(research.note(self.found), [])
        # With Auto, pages worth of findings go to the plan, which reads long text far
        # better than its 4B model; the weather or a price is short and stays here.
        yield from self._reply(text, think, attached_chars=len(self.found.text))

    def _research_job(self, text: str, think: bool) -> Iterator[Event]:
        """"Research X" (researcher.py): the plan model plans the searches and at the end
        merges the summaries and checks them; its own model reads each page. Every step
        is said in its thinking with its tokens, and the end counts what the plan paid
        against what it would have paid doing every step itself."""
        chosen = self.menu.chosen() or {}
        target = chosen.get("cloud") or chosen
        talker = self.auto_cloud or (self.chat.talker if self.chat.talker is not self.ollama else None)
        model = target.get("model", "")
        boss = self.talker_name
        if talker is not None and self.auto_cloud is not None:
            # With Auto, the plan's fast model merges: care matters here, depth doesn't,
            # and the slow one took 15 of the first job's 37 seconds.
            try:
                system = self.ollama.show(noir.NOIR_MODEL).get("system", "")
            except OllamaError:
                system = ""
            if fast := self.menu.fast_talker(system):
                talker, found = fast
                model, boss = found["model"], found["name"]
        source = target.get("provider", "") if talker is not None else ""
        own = self._own_name()
        boss = boss if talker is not None else own
        account = researcher.Account(source=source)

        def talk(system: str, user: str) -> Iterator[str]:
            """One call to the reviewer, streamed, its tokens counted once it ends."""
            if talker is None:
                messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
                yield from self.ollama.chat(noir.NOIR_MODEL, messages, think=False, keep_alive=noir.KEEP_ALIVE)
                read, wrote = getattr(self.ollama, "last_tokens", (0, 0))
                account.local_calls, account.local_read, account.local_wrote = (
                    account.local_calls + 1, account.local_read + read, account.local_wrote + wrote)
                return
            # The plan's apps take one question at a time and drop system messages
            # (accounts.transcript), so the note goes in front of the question.
            before = researcher.last_plan_answer(source)
            yield from talker.chat(model, [{"role": "user", "content": f"{system}\n\n{user}"}])
            read, wrote = researcher.plan_tokens_after(source, before)
            account.plan_calls, account.plan_read, account.plan_wrote = (
                account.plan_calls + 1, account.plan_read + read, account.plan_wrote + wrote)

        def form(system: str, user: str, schema: dict) -> dict:
            """Its own model fills the plan: as good as the plan model's, six times faster, free."""
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            filled = self.ollama.chat_json(noir.NOIR_MODEL, messages, schema, think=False)
            read, wrote = getattr(self.ollama, "last_tokens", (0, 0))
            account.local_calls, account.local_read, account.local_wrote = (
                account.local_calls + 1, account.local_read + read, account.local_wrote + wrote)
            return filled

        try:
            if talker is None:
                yield Thinking(f"Research job with no plan connected, so {own} does every step: plan the searches, "
                               "read each page, then merge and check.")
            else:
                yield Thinking(f"Research job: {own} plans the searches and reads each page on this computer, "
                               f"then {boss} merges the summaries and checks them.")
            yield Progress("Planning the searches...")
            queries, goal = researcher.plan(form, text)
            yield Thinking(f"{own} asked for {len(queries)} search{'es' if len(queries) != 1 else ''}: "
                           f"{'; '.join(queries)}. Goal: {goal}")
            yield Progress(f"Running {len(queries)} search{'es' if len(queries) != 1 else ''} at once, picking the "
                           "pages worth reading...")
            pages, choices = researcher.gather(text, queries, judge=sources.judge_with(form))
            picked_line, dropped_line = sources.said(choices)
            if choices:
                yield Thinking(picked_line)
            if dropped_line:
                yield Thinking(dropped_line)
            if not pages:
                yield Thinking("The searches found no page I could read, so this is from memory.")
                yield from self._reply(text, think)
                return
            for number, page in enumerate(pages, 1):
                yield Progress(f"Worker {number} of {len(pages)} reads {page.site}...")
                researcher.summarise(self.ollama, noir.NOIR_MODEL, text, page)
                account.local_calls, account.local_read, account.local_wrote = (
                    account.local_calls + 1, account.local_read + page.read, account.local_wrote + page.wrote)
                first = page.summary.splitlines()[0][:120] if page.summary else ""
                yield Thinking(f"Worker {number} ({own}) read {page.site}: {page.read:,} tokens in, {page.wrote:,} out. "
                               f"{first if page.useful else 'Nothing relevant on that page.'}")
            useful = [page for page in pages if page.useful]
            if not useful:
                yield Thinking("None of the pages said anything about it, so this is from memory.")
                yield from self._reply(text, think)
                return
            yield Thinking(f"{boss} merges {len(useful)} summaries, checks them against each other and writes the brief.")
            yield Progress("Writing the brief...")
            said: list[str] = []
            for piece in researcher.merge(talk, text, goal, useful, researcher.when_now()):
                said.append(piece)
                yield NoirText(piece)
        except cloud.CloudError as exc:
            yield Error(f"{boss} couldn't finish the research ({exc}). Try again, or pick another model.")
            return
        brief = "".join(said).strip()
        if note := safety.caution(text):  # health and money, the same plain note as any answer
            yield NoirText(f"\n\n{note}")
        researcher.settle(account, text)
        for line in researcher.account_lines(account, boss, own):
            yield Thinking(line)
        self.chat.remember(text, brief)
        activity.record(activity.ANSWERED)
        activity.record(activity.READ, len(useful))
        if source and account.saved:
            usage.record_saved(source, account.saved)
        yield NoirDone(by=boss, where=auto.CLOUD if source else auto.HERE, saved=account.saved,
                         plan_used=self.menu.plan_used(source) if source in APPS else -1.0,
                         sources=researcher.sources_of(useful))

    def _waking(self) -> Iterator[Event]:
        """Its model isn't in memory yet (the first message after the app opens, or after
        a while away), so the first word takes a few seconds longer: say so, or the window
        sits silent and looks stuck."""
        try:
            loaded = {m["name"].split(":")[0] for m in self.ollama.loaded()}
        except Exception:
            return  # Ollama didn't answer; the message itself will say what's wrong
        if noir.NOIR_MODEL not in loaded:
            yield Thinking("Loading my model into memory first, which takes a few seconds.")

    def _answer(self, text: str, think: bool) -> Iterator[Event]:
        self.chat.jobs = self._chores_note()
        # Small talk gets no thinking: its model thought to its limit over "how are you",
        # then wrote the answer a second time, so a greeting took the longest of all.
        if think and self.chat.can_think and voice.kind_of(text) != "small_talk":
            for kind, piece in self.chat.think_through(text):
                yield Thinking(piece, "thought") if kind == "thought" else NoirText(piece)
        else:
            for chunk in self.chat.send(text):
                yield NoirText(chunk)

    def _auto_choose(self, text: str, attached_chars: int, where: str):
        """Auto: its own model or the plan, for this one message. Says which and why,
        and returns the NoirDone that names who answered."""
        chosen = self.menu.chosen() or {}
        target = chosen.get("cloud") or {}
        if where == auto.CLOUD:
            decision = auto.Decision(auto.CLOUD, "asked", "user")
        else:
            decision = auto.decide(text, base_model=noir.load_state().get("base_model", ""), after=self.auto_last,
                                   plan_used=self.menu.plan_used(target.get("provider", "")),
                                   attached_chars=attached_chars,
                                   ask_model=auto.model_form(self.ollama, noir.NOIR_MODEL))
            if getattr(self, "found", None) is not None and decision.where == auto.CLOUD:
                yield Thinking(f"Auto: there's a lot to read from the web, so {self.talker_name} reads it.")
            else:
                yield Thinking(auto.say(decision, self.talker_name, plan=target.get("provider") in APPS))
        self.auto_last = decision.where
        if decision.where == auto.CLOUD:
            self.chat.talker = self.auto_cloud
            return NoirDone(by=self.talker_name)
        self.chat.talker = self.ollama
        self.auto_kind = decision.kind
        auto.record(decision.kind)
        return NoirDone(by=self._own_name(), instead=self.talker_name)

    def _own_name(self) -> str:
        tag = noir.load_state().get("base_model", "")
        model = find_model(tag) if tag else None
        return model.name if model else "Noir"

    def ask_again(self) -> Iterator[Event]:
        """"Ask Claude instead" under an answer Auto kept on this computer: the same
        question again, from the plan, and counted so wrongly placed kinds show up."""
        history = self.chat.history if self.chat else []
        if not self.auto_cloud or len(history) < 2 or history[-1]["role"] != "assistant":
            yield Error("There's nothing to ask again right now.")
            return
        text = history[-2]["content"]
        del history[-2:]  # replaced by the new answer, so it doesn't remember both
        auto.record(self.auto_kind or "unclear", asked_again=True)

        def again() -> Iterator[Event]:
            yield Thinking(f"Asking {self.talker_name} instead.")
            try:
                yield from self._reply(text, False, where=auto.CLOUD)
            except OllamaError as exc:
                yield Error(str(exc))

        yield from self._full_lists(self.book.record(f"Ask {self.talker_name} instead", again()))

    def _with_attachments(self, text: str, attached: Attached, think: bool) -> Iterator[Event]:
        self.deleting = None
        self.fixing = None
        yield from self._waking()
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
            yield from self._reply(text or NOTHING_SAID, think, attached_chars=len(attached.context))
        except OllamaError as exc:
            yield Error(str(exc))

    def _use_chosen_model(self) -> None:
        """Only its answers move to the model picked in the menu. Deciding what a
        message is for stays with its own small model, and so do agents that read
        every highlight: those see whatever the user selects, in any program, so
        that must never leave the computer without them asking each time."""
        chosen = self.menu.chosen()
        is_auto = bool(chosen and chosen.get("auto"))
        self.talker_name = (chosen["cloud"]["name"] if is_auto else chosen["name"]) if chosen else ""
        self.auto_last = ""
        if self.chat is None:
            return
        try:
            system = self.ollama.show(noir.NOIR_MODEL).get("system", "") if chosen else ""
        except OllamaError:
            system = ""
        talker = self.menu.talker(system) or self.ollama
        # With Auto its own model is the one in use; the plan only answers what
        # _auto_choose sends it, one message at a time.
        self.auto_cloud = talker if is_auto else None
        self.chat.talker = self.ollama if is_auto else talker
        # A plan or key model draws well enough to add a drawing unasked; its own 4B
        # model only draws when asked to (voice.DRAW_WORDS).
        self.chat.draws = talker is not self.ollama and not is_auto

    def _handle_choice(self, id: str, choice: str) -> Iterator[Event]:
        if id == research.WEB:
            research.allow(choice == research.YES_LOOK)
            pending, self.pending_lookup = self.pending_lookup, None
            if pending:
                try:
                    yield from self._with_lookup(*pending)
                except OllamaError as exc:
                    yield Error(str(exc))
            else:
                yield from say("Okay." if choice == research.YES_LOOK else "Okay, I'll answer from what I know.")
        elif id == PICK_AGENT_TO_DELETE:
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
        elif id.startswith(("kind:", "subject:")):
            # One of the organizer's questions, re-asked in the chat with buttons.
            pending = {q["id"]: q for q in self.organizer.questions()}
            if id not in pending:
                yield from say("That question has already been answered.")
            else:
                yes = choice != "No"
                moved = self.organizer.answer(id, yes)
                yield from self._say(self._answered_line(pending[id], yes, "", moved))
        elif id == WHICH_KIND:
            request, self.asking_kind = self.asking_kind or "", None
            kind = next((b.id for b in self.blueprints.values() if b.name == choice), None)
            if kind and request:
                yield Thinking(f"So it's a {choice}.")
                yield from self._building(self.builder.start(kind, request))
            elif choice.startswith("Use ") and store.find_agent(choice[4:]):
                yield from self._run_agent(choice[4:], request, request or choice)
            elif request:
                yield Thinking("Another kind of helper, so I'll check what it needs.")
                yield from self._idea(request, request)
            else:
                yield from say("That question has already been answered.")
        elif id == ORGANIZE_NOW:
            name, self.organizing = self.organizing, None
            agent = store.find_agent(name) if name else None
            if choice == GO_THROUGH and agent:
                yield from self._organize_now(agent, everything=True)
            else:
                yield from say("Okay, only new files from now on.")
        elif self.builder and self.builder.active:
            try:
                yield from self._building(self.builder.choose(id, choice))
            except OllamaError as exc:
                yield Error(str(exc))
        else:
            yield Error("Nothing is waiting for an answer right now.")

    def _clear_conversation_state(self) -> None:
        """Unfinished setups, questions and Noir's memory belong to the
        conversation being left. Call only after the book has saved it."""
        self.deleting = None
        self.asking_kind = None
        if self.builder:
            self.builder.draft = None
        if self.planner:
            self.planner.draft = None
        if self.chat:
            self.chat.reset()

    # ------------------------------------------------------ switch-on agents

    def _ask_kind(self, request: str) -> Iterator[Event]:
        """Which kind of helper for files the user means, as buttons: each kind's name with
        what it does, an existing helper of those kinds to use instead, and Something else."""
        self.asking_kind = request
        kinds = [self.blueprints[k] for k in KIND_SHORT if k in self.blueprints]
        what = ", ".join(f"{KIND_SHORT[b.id]} ({b.name})" for b in kinds)
        existing = [a for a in store.list_agents() if a.blueprint in KIND_WORDS]
        choices = [b.name for b in kinds] + [f"Use {a.name}" for a in existing[:2]] + [SOMETHING_ELSE_KIND]
        plain = f"What should it do with your files: {what}?"
        yield Question(WHICH_KIND, phrase(self.ollama, noir.NOIR_MODEL, plain, [b.name for b in kinds], question=True),
                       choices)

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
            yield from self._building(self.builder.start(blueprint, request))

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

    def _is_on(self, agent: store.Agent) -> bool:
        if agent.blueprint in WATCHED_KINDS:
            return self.organizer.is_on(agent.name)
        return bool(self.quick and self.quick.is_on(agent.name))

    def _building(self, events: Iterator[Event]) -> Iterator[Event]:
        """The builder's events, then what happens once an agent is made: a watched-folder
        agent is switched on at once and offered a first pass over its folder."""
        yield from events
        created = self.builder.take_created() if self.builder else None
        if created is None or created.blueprint not in WATCHED_KINDS:
            return
        self.organizer.refresh(store.list_agents())
        self.organizer.switch(created, True)
        yield self._agent_list()
        folder = Path(created.slots.get("folder", "")).name
        count = self.organizer.count_files(created)
        if created.blueprint == SUMMARIZER:
            notes = Path(notes_path(created.slots)).name
            on = f"It's on: each new document in {folder} gets a few lines in {notes}, and every one shows in your chores."
            facts = [folder, notes]
            now = "Sum them up now?"
        else:
            on = f"It's on: new files in {folder} get sorted as they land, and every move shows in your chores with Undo."
            facts = [folder]
            now = "Go through them now?"
        yield Thinking("What each file is about is a job for the built-in model: it reads text well, and the "
                       "files never leave this computer.")
        if count:
            self.organizing = created.name
            there = f"There {'is' if count == 1 else 'are'} {count} file{'' if count == 1 else 's'} there already."
            yield Question(ORGANIZE_NOW, phrase(self.ollama, noir.NOIR_MODEL, f"{on} {there} {now}",
                                                [*facts, str(count)], question=True), [GO_THROUGH, ONLY_NEW])
        else:
            yield from self._say(on, facts)

    def _places(self, organizers: list[store.Agent]) -> str:
        """Where each organizer keeps its folders, as whole paths."""
        return " ".join(f"{a.name} keeps its folders in {a.slots.get('into') or a.slots.get('folder', '')}"
                        f" ({a.slots.get('groups', '')})." for a in organizers)

    def _say_where(self, text: str, organizers: list[store.Agent]) -> Iterator[Event]:
        """Where the organizer put a file, and where its folders are, from its own record
        and settings, never from the model's memory. Always the whole path."""
        moves = self.organizer.last_moves(50)
        named = [m for m in moves if _mentions(text, m["name"])]
        stayed = [s for s in self.organizer.last_skipped(30) if _mentions(text, s["name"])]
        if stayed and not named:
            yield from self._say("; ".join(f"{s['name']} is still in {s['where']}, where it stayed: {s['why']}"
                                           for s in stayed[:3]) + ".",
                                 [s["name"] for s in stayed[:3]] + [s["where"] for s in stayed[:3]])
            return
        about_folder = bool(re.search(r"\bfolders?\b", text, re.IGNORECASE)) and not re.search(r"\bfiles?\b|\.pdf\b", text, re.IGNORECASE)
        if (about_folder and not named) or not moves:
            where = self._places(organizers)
            facts = [a.slots.get("into") or a.slots.get("folder", "") for a in organizers]
            if moves:
                where += f" The last file, {moves[0]['name']}, went to {moves[0]['to']} ({chores.ago(moves[0]['when'])})."
                facts += [moves[0]["name"], moves[0]["to"]]
            else:
                where += (" Nothing has been moved yet: a download needs about 20 seconds to settle before I read "
                          "it, and only files that land after the organizer was switched on count.")
            yield from self._say(where, facts)
            return
        picked = named[:3] or moves[:3]
        lines = [f"{m['name']} is in {m['to']} ({chores.ago(m['when'])})" for m in picked]
        yield from self._say(("" if len(lines) == 1 else "The last ones: ") + "; ".join(lines) + ". Undo is in your chores.",
                             [m["name"] for m in picked] + [m["to"] for m in picked])

    def _follows_a_chore(self, text: str) -> bool:
        """A short question with a pronoun within CHORE_FRESH_SECONDS of an organizer's last
        word or move in this chat: it means the files, not the world."""
        fresh = time.time() - self.chore_spoken_at < CHORE_FRESH_SECONDS
        return fresh and len(text.split()) <= 10 and bool(FOLLOWS_A_CHORE.search(text))

    def _names_a_file(self, text: str) -> bool:
        """Whether the message names a file the organizer moved or left ("the physics lab")."""
        return any(_mentions(text, item["name"])
                   for item in [*self.organizer.last_moves(50), *self.organizer.last_skipped(30)])

    def _say_why(self, text: str, organizers: list[store.Agent]) -> Iterator[Event]:
        """Why a file stayed, or why it moved, from the organizer's own record of each verdict."""
        skipped = self.organizer.last_skipped(30)
        moves = self.organizer.last_moves(50)
        left = [s for s in skipped if _mentions(text, s["name"])]
        moved = [m for m in moves if _mentions(text, m["name"])]
        if left:
            lines = [f"{s['name']} stayed in {s['where']}: {s['why']}." for s in left[:3]]
            yield from self._say(" ".join(lines) + " I only move what clearly reads as material for one of the "
                                 "folders; if it belongs in one, drag it there.",
                                 [s["name"] for s in left[:3]] + [s["where"] for s in left[:3]])
        elif moved:
            lines = [f"I put {m['name']} in {m['to']} because its text reads as material for that folder "
                     f"({chores.ago(m['when'])})." for m in moved[:3]]
            yield from self._say(" ".join(lines) + " Undo is in your chores if that was wrong.",
                                 [m["name"] for m in moved[:3]] + [m["to"] for m in moved[:3]])
        elif skipped:
            yield from self._say("These stayed where they were: "
                                 + "; ".join(f"{s['name']} ({s['why']})" for s in skipped[:4]) + ".",
                                 [s["name"] for s in skipped[:4]])
        elif moves:
            yield from self._say(f"Nothing has been left behind: everything I read went into a folder. The last, "
                                 f"{moves[0]['name']}, went to {moves[0]['to']}.", [moves[0]["name"], moves[0]["to"]])
        else:
            yield from self._say("Nothing has been looked at yet: only files that land after the organizer was switched "
                                 "on count, and a download needs about 20 seconds to settle. Say \"organize it\" to go "
                                 "through what has landed, or \"go through everything\" for all of it.")

    def _say_status(self, organizers: list[store.Agent]) -> Iterator[Event]:
        """What the watched-folder agents are and did lately, from their records."""
        parts, facts = [], []
        for agent in organizers:
            on = self.organizer.is_on(agent.name)
            parts.append(f"{agent.name} is {'on' if on else 'off'}: {organizer_how(agent)[:1].lower()}{organizer_how(agent)[1:]}")
            facts.append(agent.name)
        moves = self.organizer.last_moves(3)
        if moves:
            parts.append("Lately: " + "; ".join(f"{m['name']} went to {m['to']} ({chores.ago(m['when'])})" for m in moves)
                         + ". Undo is in your chores.")
            facts += [m["name"] for m in moves] + [m["to"] for m in moves]
        else:
            parts.append("Nothing has been moved yet.")
        by_why: dict[str, list[str]] = {}
        for item in self.organizer.last_skipped(6):
            by_why.setdefault(item["why"], []).append(item["name"])
        if by_why:
            parts.append("Left where they were: "
                         + "; ".join(f"{', '.join(names)} ({why})" for why, names in by_why.items()) + ".")
            facts += [name for names in by_why.values() for name in names]
        for question in self.organizer.questions():
            parts.append(f"Waiting for your answer: {question['text']}")
            facts.append(question["text"])
        yield from self._say(" ".join(parts), facts)

    def _chores_note(self) -> str:
        """What the chat model is told about the organizers before each answer, so a question
        it gets anyway is answered from facts, with whole paths, not from what it imagines."""
        organizers = [a for a in store.list_agents() if a.blueprint in WATCHED_KINDS]
        if not organizers:
            return ""
        lines = ["YOUR CHORES RIGHT NOW (facts: when asked where a file or folder is, give the whole path from here, "
                 "and never say you can't move files, since this chore does)"]
        for agent in organizers:
            lines.append(f"- {agent.name} is {'on' if self.organizer.is_on(agent.name) else 'off'}: it watches "
                         f"{agent.slots.get('folder', '')}. {organizer_how(agent)}"
                         + (f" Its folders are in {agent.slots.get('into')}." if agent.slots.get("into") else ""))
        for move in self.organizer.last_moves(3):
            lines.append(f"- {move['name']} was put in {move['to']} ({chores.ago(move['when'])}).")
        for item in self.organizer.last_skipped(3):
            lines.append(f"- {item['name']} stayed in {item['where']}: {item['why']}.")
        lines.append("- It reads documents, code, spreadsheets, slides, zips (by the files inside) and pictures (through "
                     "a vision model, when one is installed), all on this computer, and the rest by name. Documents and "
                     "code it sorts at once; a kind it hasn't sorted before (a spreadsheet, a picture) it asks about "
                     "once, then sorts from then on.")
        seer = self.organizer.seer()
        lines.append(f"- A vision model is installed ({seer}), so pictures are read and sorted too." if seer
                     else "- No vision model is installed, so a picture goes by its file name only.")
        for question in self.organizer.questions():
            lines.append(f"- Waiting for the user's yes or no: {question['text']} (they can answer yes or no here)")
        return "\n".join(lines)

    def _organize_now(self, agent: store.Agent, everything: bool = False, text: str = "") -> Iterator[Event]:
        """Go through the agent's folder now, saying how it goes: what has landed since it
        was switched on, (everything) all of it, or the file the message names, looked at
        again. When nothing is new, what waits is said and asked instead of "wait"."""
        named = [p for p in self.organizer.files(agent, settled=False) if text and _mentions(text, p.name)]
        outcome: dict = {"moved": 0, "where": [], "left": 0, "why": [], "looked": 0}
        for step in self.organizer.run_once(agent, everything=everything, only=named or None):
            if isinstance(step, str):
                yield Progress(step)
            else:
                outcome = step
        if outcome["moved"] and agent.blueprint == ORGANIZER:
            activity.record(activity.SORTED, outcome["moved"])
        elif outcome["moved"]:
            activity.record(activity.SUMMED_UP, outcome["moved"])
        moved, left = outcome["moved"], outcome["left"]
        folder = Path(agent.slots.get("folder", "")).name
        facts = []
        if not outcome["looked"]:
            yield from self._nothing_new(agent, folder)
            return
        if agent.blueprint == SUMMARIZER:
            notes = Path(notes_path(agent.slots)).name
            text = (f"Summed up {moved} document{'' if moved == 1 else 's'} into {notes}." if moved else "Nothing summed up.")
            facts = [notes, str(moved)] if moved else []
        else:
            where = " · ".join(f"{w['folder']} {w['count']}" for w in outcome["where"])
            text = (f"Sorted {moved} document{'' if moved == 1 else 's'}: {where}." if moved else "Nothing moved.")
            facts = [w["folder"] for w in outcome["where"]] + ([str(moved)] if moved else [])
        if left:
            reasons = ", ".join(f"{r['why']} ({r['count']})" if len(outcome["why"]) > 1 else r["why"] for r in outcome["why"])
            text += f" {left} left where {'it was' if left == 1 else 'they were'}: {reasons}."
            facts.append(str(left))
        if moved and agent.blueprint == ORGANIZER:
            text += " Undo is in your chores."
        said = phrase(self.ollama, noir.NOIR_MODEL, text, facts)
        self.chat.remember(f"{agent.name}: organize now", f"({agent.name} answered) {said}")
        yield Result(agent.name, said)
        yield from self._pending_questions(agent)

    def _nothing_new(self, agent: store.Agent, folder: str) -> Iterator[Event]:
        """Nothing has landed since the agent was switched on: say what was looked at already
        and why it stayed, re-ask what waits, and only then suggest waiting."""
        skipped = [s for s in self.organizer.last_skipped(5)]
        pending = [q for q in self.organizer.questions() if q["id"].split(":")[1] == agent.name]
        parts = [f"Nothing new has landed in {folder} since {agent.name} was switched on."]
        if skipped:
            parts.append("Looked at already: " + "; ".join(f"{s['name']} ({s['why']})" for s in skipped[:3])
                         + '. Say "put <file> in <folder>" to place one yourself, or "organize <file>" to look at it again.')
        if not skipped and not pending:
            parts.append("A download needs about 20 seconds to settle before I read it; ask again in a moment, or say which file.")
        text = " ".join(parts)
        self.chat.remember(f"{agent.name}: organize now", f"({agent.name} answered) {text}")
        yield Result(agent.name, text)
        yield from self._pending_questions(agent)

    def _pending_questions(self, agent: store.Agent) -> Iterator[Event]:
        """The organizer's questions still waiting, asked in the chat with buttons."""
        for question in self.organizer.questions():
            if question["id"].split(":")[1] != agent.name:
                continue
            if question["kind"] == "subject":
                choices = [f"Call it {question['guess']}", "No"] if question.get("guess") else ["Yes", "No"]
            else:
                choices = ["Yes", "No"]
            yield Question(question["id"], question["text"], choices)

    def _place(self, what: str, folder: str, organizers: list[store.Agent]) -> Iterator[Event]:
        """"Put output.pdf in math": the file the words name, moved where the user says and
        learned from. The file must be in a watched folder; the folder is made if need be."""
        for agent in (a for a in organizers if a.blueprint == ORGANIZER):
            found = [p for p in self.organizer.files(agent, settled=False) if _mentions(what, p.name)]
            if not found:
                continue
            yield Thinking(f"You're placing {found[0].name} yourself, so I'll move it and remember the course and kind.")
            move = self.organizer.place(agent, found[0], folder)
            if move:
                target = Path(move["to"])
                yield from self._say(f"Put {found[0].name} in {target.parent}. Files of that course and kind go there from now on. "
                                     "Undo is in your chores.", [found[0].name, str(target.parent)])
            else:
                yield from self._say(f"I couldn't move {found[0].name}.", [found[0].name])
            return
        folders = ", ".join(Path(a.slots.get("folder", "")).name for a in organizers)
        yield from self._say(f"I can't see a file like that in {folders}. Which file do you mean? Its name is enough.", [folders])

    def _answer_about_chores(self, text: str, think: bool) -> Iterator[Event]:
        """A question about the chores. With a plan or key model set up, that model gets the
        organizer's record and the question, so the user can check and talk through what
        went wrong with the better model; else its own model answers from the same record."""
        talker = self.auto_cloud or (self.chat.talker if self.chat and self.chat.talker is not self.ollama else None)
        if talker is None:
            yield Thinking("This asks about your chores, so I'll answer from the organizer's own record.")
            yield from self._answer(text, think)
            return
        yield Thinking(f"This asks about your chores: {self.talker_name} gets the organizer's record and your question, "
                       "so it can check what happened and explain.")
        yield from self._reply(f"{self._chores_note()}\n\nThe user asks: {text}", think, where=auto.CLOUD)

    def organizer_questions(self) -> list[dict]:
        """The organizers' questions waiting for an answer, for the drawer and Today."""
        return self.organizer.questions()

    def organizer_answer(self, id: str, yes: bool, name: str = "") -> int:
        """The user's answer to one, from any window: yes or no, and for a new course the
        folder name they chose. Returns how many files moved."""
        return self.organizer.answer(id, bool(yes), name or "")

    def _answered_line(self, question: dict, yes: bool, name: str, moved: int) -> str:
        """The plain line after an answer, phrased by _say."""
        went = f"{moved} just went in; Undo is in your chores." if moved else "Nothing to move right now."
        if question.get("kind") == "subject":
            folder = name or question.get("guess", "")
            if yes:
                return f"Okay: {question['text'].split(' looks like')[0]} and every {folder} file from now on go in {folder}. {went}"
            return f"Okay, files for that course stay where they land."
        ext = question["id"].rsplit(":", 1)[-1]
        if yes:
            return f"Okay: {ext} files are sorted from now on. {went}"
        return f"Okay, {ext} files stay where they land."

    def _say(self, plain: str, facts: list[str] = ()) -> Iterator[Event]:
        """A line about a chore in Noir's own words (talk.phrase), the plain line if a fact is lost."""
        yield from say(phrase(self.ollama, noir.NOIR_MODEL, plain, list(facts)))

    def chore_agents(self) -> list[dict]:
        lines = []
        for agent in store.list_agents():
            if agent.blueprint in WATCHED_KINDS:
                lines.append({"name": agent.name, "kind": agent.blueprint, "on": self.organizer.is_on(agent.name),
                              "how": organizer_how(agent)})
            elif self._switchable(agent) and self.quick:
                lines.append({"name": agent.name, "kind": "highlight", "on": self.quick.is_on(agent.name),
                              "how": "While it's on, what you highlight in any program goes through it, and the "
                                     "answer shows above the text."})
        return lines

    def organizer_done(self) -> list[dict]:
        return self.organizer.done_lately()

    def undo_move(self, id: str) -> int:
        return self.organizer.undo(id)

    def details(self, name: str) -> dict:
        """What an agent's page shows. Empty if there's no such agent."""
        agent = store.find_agent(name)
        return describe(agent) if agent else {}

    def _agent_list(self) -> AgentList:
        agents = store.list_agents()
        return AgentList(
            [a.name for a in agents],
            [a.name for a in agents if self._switchable(a) and (a.blueprint in WATCHED_KINDS or self.quick)],
            [a.name for a in agents if self._is_on(a)],
        )

    def _full_lists(self, events: Iterator[Event]) -> Iterator[Event]:
        """The builder and runner only know agent names; the UI also needs
        which agents can be switched on and which are on."""
        for event in events:
            if isinstance(event, AgentList):
                self.organizer.refresh(store.list_agents())
                if self.quick:
                    self.quick.refresh(store.list_agents())  # changed settings apply at once
                event = self._agent_list()
            yield event

    def _toggle(self, name: str, on: bool | None = None) -> Iterator[Event]:
        agent = store.find_agent(name)
        if agent is not None and agent.blueprint in WATCHED_KINDS:
            on = not self.organizer.is_on(agent.name) if on is None else on
            self.organizer.switch(agent, on)
            if on:
                yield from self._say(f"{agent.name} is on. {organizer_how(agent)}", [agent.name])
            else:
                yield from self._say(f"{agent.name} is off.", [agent.name])
            yield self._agent_list()
            return
        if agent is not None and self._switchable(agent) and self.quick is None:
            yield Error(f"Switch-on helpers work on Windows for now. You can still ask {agent.name} in the chat.")
            return
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
        """Noir hears about idea cards too, so a follow-up in the chat makes sense."""
        for event in events:
            if isinstance(event, IdeaCard):
                self.chat.remember(text, f"(Idea card: {event.title}) {event.verdict}")
            yield event

    def _hardware(self) -> tuple[hardware.HardwareReport, float]:
        """This computer, and how much memory Noir's model takes on it."""
        report = hardware.detect()
        tag = noir.load_state().get("base_model")
        model = find_model(tag) if tag else recommend(report).model
        return report, model.memory_gb if model else 3.0

    def _run_agent(self, name: str, request: str, text: str, think: bool = False) -> Iterator[Event]:
        agent = store.find_agent(name)
        if agent is None:
            yield Error(f"I can't find an agent called {name}.")
            return
        if agent.blueprint in WATCHED_KINDS:
            if WANTS_ORGANIZE.search(text) or not WANTS_ANSWER.search(text):
                yield from self._organize_now(agent)
            else:
                # A question about it ("which folder is the physics lab in now?"), sent here by
                # the router: answered with the facts note in front, not run as a pass.
                yield from self._answer_about_chores(text, think)
            return
        if agent.blueprint == CUSTOM:
            # Asked in the chat ("Word explainer: serendipity"): do its job here.
            result = run_instruction(self.chat.talker, noir.NOIR_MODEL, agent.slots.get("instruction", ""),
                                     request, self.chat.think)
            activity.record(activity.HELPED)
            self.chat.remember(text, f"({agent.name} answered) {result}")
            yield Result(agent.name, result)
            return
        for event in runner.run(self.ollama, noir.NOIR_MODEL, agent, request, self.chat.think):
            if isinstance(event, Result):
                # Noir hears the answer too, so "and what about...?" follows on.
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
