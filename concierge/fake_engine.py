"""A scripted engine for building the UI and for the practice run, with no model.

It follows the same Engine contract as the real one (see events.py) and
produces every event type, so each part of the UI can be built and clicked
through. No Ollama or model is needed.

What to type to see each flow:
    anything               Noir streams a chat reply
    "make an agent"        a helper worked out by talking, in the order the real
    (or mention documents,   app does it: a Question answered in words, a
    files or a folder)       Question with buttons, a try-out (Result), the
                             AgentCard, Create it, then whether to go through
                             the files already there (Progress, Result)
    a helper's name, a colon and anything
                           ask that helper, as its page's Try this does
    "ask ..."              run the existing agent: Progress, Result with sources
    "translate ...", "screenshot ..." or "idea"
                           an IdeaCard: Noir's verdict on a helper idea
    "error"                an Error event
    "turn on the highlight explainer" or "install Grammar Fixer"
                           adds a ready-made agent (agents/starters.yaml),
                           and switches it on if asked

Conversations are kept in memory (same ChatBook as the real engine), so New
chat, reopening and deleting chats work too, and so does deleting an agent.

The helpers it starts with are made up, and each is a card the way the real app
saves one (agents/parts.py), kept in memory: what their pages, the chores list
and a new helper's card say is written by the same code as in the real app.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path

from . import auto, hardware, usage
from .agents import community, parts
from .agents.builder import CANCEL_WORDS, CARD, CARD_YES, CREATE_IT
from .agents.designer import DESIGN, TRY_OUT, row_line
from .agents.starters import asks_for
from .agents.store import Agent
from .agents.store import slugify as store_slug
from .attachments import read_attachments
from .quick import spot
from .quick.agents import BUBBLE, UNTIL_UNHIGHLIGHT
from .conversations import ChatBook
from .engine import FIRST_PASS, FOLLOW_UPS, GO_THROUGH, ONLY_NEW, WANTS_ON
from .folderwatch import LEFT_BY_RULE, NO_TEXT
from .models import ModelMenu
from .events import (
    AgentCard,
    IdeaCard,
    IdeaStep,
    AgentList,
    NoirDone,
    NoirText,
    Error,
    Event,
    Progress,
    Question,
    Result,
    Source,
    SystemInfo,
    Thinking,
)

# The practice run's own home, made up: nothing here ever names or looks at a real folder.
_HOME = "C:/Users/you"
_BUILT_IN = "Qwen 3.5 4B"  # the made-up built-in model, as startup() names it
# The practice conversation in which a helper is worked out (the real one is
# agents/designer.py). With no model there is nobody to work it out with, so a script
# plays one helper through: what the user types is taken as its rule, word for word, and
# everything else is made up and says so. The questions, the try-out and the card come in
# the order and the shape the real ones do, and the card's lines are written by the same
# code (parts.card), so the practice card never falls behind the real one.
_ASKS_WHAT = ("What should it take off your hands? Tell me what gets in your way now, and what a good result would "
              "look like.")
_ASKS_HOW = "Should it go by what's inside each file, or only by the file's name?"
_PROPOSES = ("Practice: with a model I'd work this out with you. Here I take what you typed as its rule and play a "
             "helper for the new files in Downloads: each one is put in a folder by your rule, and what the rule "
             f"doesn't cover stays where it is. {_ASKS_HOW}")
_SUMS_UP = ("It will watch Downloads, put each new file your rule covers in a folder, and leave the rest alone. "
            "Below is how a try-out looks, on made-up files, and then its card.")
_CHANGED = "I've put that into the rule. Here it is tried again, and its card as it is now."
_LOOKS = (parts.INSIDE_FILE, parts.NAME_ONLY)


class PracticeOllama:
    """Stands in for Ollama in the model menu, so nothing is really fetched or deleted."""

    def __init__(self):
        self.installed = [{"name": "qwen3.5:4b", "size": 3_324_000_000, "details": {"parameter_size": "4.2B"}},
                          {"name": "gemma4:latest", "size": 6_583_000_000, "details": {"parameter_size": "7.5B"}}]

    def models(self) -> list[dict]:
        return list(self.installed)

    def capabilities(self, name: str) -> list[str]:
        return ["completion"]

    def pull(self, tag: str, on_progress) -> None:
        for percent in range(0, 101, 5):
            time.sleep(0.15)
            on_progress("pulling", percent, 100)
        self.installed.append({"name": tag, "size": 2_400_000_000, "details": {}})

    def delete(self, tag: str) -> None:
        self.installed = [model for model in self.installed if model["name"] != tag]


class PracticeKeys:
    """Practice keys: kept in memory, never in the password store."""

    def __init__(self):
        self.keys: dict[str, str] = {}

    def saved_key(self, provider: str) -> str:
        return self.keys.get(provider, "")

    def save_key(self, provider: str, key: str) -> None:
        self.keys[provider] = key

    def forget_key(self, provider: str) -> None:
        self.keys.pop(provider, None)

    def key_refused(self, company, key: str) -> bool:
        return False  # never sent anywhere


def practice_models(words: str = "", sort: str = "downloads", kind: str = "") -> list[dict]:
    """A few pretend Hugging Face models, so the page works with no internet."""
    made = [("Tiny-Chat-3B", 2.1, 910_000, 420), ("Writer-7B", 4.8, 640_000, 380), ("Coder-9B", 5.9, 510_000, 890),
            ("Vision-8B", 5.2, 300_000, 260), ("Giant-90B", 58.0, 120_000, 95), ("Reader-4B", 2.9, 90_000, 70)]
    return [{"id": f"practice/{name}-GGUF", "author": "practice", "name": name, "downloads": downloads, "likes": likes,
             "tag": f"hf.co/practice/{name}-GGUF:Q4_K_M", "size_gb": size, "family": "practice", "license": "mit",
             "vision": name.startswith("Vision")}
            for name, size, downloads, likes in made if words.lower() in name.lower()]


class FakeEngine:
    def __init__(self, delay: float = 0.03, setup: bool = False):
        """setup: play the first-run setup page, fetching nothing (python -m concierge.ui --fake --setup)."""
        # Seconds between streamed pieces and progress steps; 0 for tests.
        self.delay = delay
        now = time.time()
        self.helpers = _practice_helpers()  # the made-up helpers, as cards; never saved
        # The one that works on a folder's new files starts switched on, with two jobs done,
        # so the chores list has something in it.
        watcher = next(agent for agent in self.helpers if parts.watches(agent))
        self.on: set[str] = {watcher.name}
        self.since = {watcher.name: now - 3 * 3600}  # when each helper was last switched on
        self.jobs = _practice_jobs(now, watcher.name)
        self._moved = {job["sort"]: 1 for job in self.jobs}  # how many files each job moved, for Undo
        self.sketch: dict | None = None  # the helper being worked out in the practice conversation
        self.going_through: str | None = None  # the helper just made, waiting for "go through them?"
        self.deleting: str | None = None
        self.auto_last = ""  # Auto's last choice, for follow-ups
        self.answered = ""  # the last plain chat reply, which Shorter and More detail can follow
        self.book = ChatBook(None)
        self.settings: dict = {"base_model": "qwen3.5:4b"}  # practice only: nothing touches the real ones
        usage.in_memory()  # practice numbers never reach the real usage file
        self.setup = PracticeSetup() if setup else None
        self.menu = ModelMenu(PracticeOllama(), lambda: (hardware.detect(), 3.0), load=lambda: dict(self.settings),
                              save=self._keep_settings, keys=PracticeKeys(), browse=practice_models,
                              accounts=PracticeAccounts())

    def _keep_settings(self, settings: dict) -> None:
        self.settings = settings

    # ---------------------------------------------------------- contract

    def startup(self) -> Iterator[Event]:
        yield SystemInfo(
            hardware=[
                "Windows 11 (build 26200), AMD Ryzen 7 9800X3D 8-Core Processor (8 cores)",
                "Memory: 31.1 GB (12.7 GB free right now)",
                "Graphics: NVIDIA GeForce RTX 5080, 15.9 GB, 12.9 GB free",
                "Disk: 833.9 GB free",
            ],
            recommended="Qwen 3.5 4B (qwen3.5:4b)",
            in_use="Qwen 3.5 4B (qwen3.5:4b)",
            device="NVIDIA GeForce RTX 5080",
        )
        yield self._agent_list()
        yield self.book.chat_list()

    def send(self, text: str, think: bool = False) -> Iterator[Event]:
        self.answered = ""

        def with_thinking():
            if self.sketch is not None:
                # A helper is being worked out: what is typed belongs to that conversation and
                # is no chat answer, so it isn't thought about, sent to a plan by Auto, or
                # marked as written by the model picked in the menu.
                yield from self._reply(text)
                return
            chosen = self.menu.chosen()
            here = not chosen or chosen.get("here")
            if chosen and chosen.get("auto"):
                # Auto in practice: decided by code only, no model asked (auto.py).
                cloud = chosen["cloud"]["name"]
                decision = auto.decide(text, base_model=self.settings.get("base_model", ""), after=self.auto_last)
                self.auto_last = decision.where
                yield Thinking(auto.say(decision, cloud, plan=chosen["cloud"]["provider"] in ("codex", "claude_code")))
                if decision.where == auto.CLOUD:
                    yield from self._say(f"Practice: this is where {cloud} would answer.", self._practice_done(False, cloud))
                    return
                done = self._practice_done(True, "Qwen 3.5 4B", instead=cloud)
            else:
                done = self._practice_done(bool(here), "" if here else chosen["name"])
            if think:
                yield Thinking("This is normal conversation, so I'll answer myself.")
                for word in "The user is saying hello, so a short friendly reply fits.".split(" "):
                    yield Thinking(word + " ", "thought")
            for event in self._reply(text):
                yield done if done and isinstance(event, NoirDone) else event
        yield from self.book.record(text, with_thinking())

    def ask_again(self) -> Iterator[Event]:
        chosen = self.menu.chosen() or {}
        cloud = (chosen.get("cloud") or {}).get("name", "")
        if not cloud:
            yield Error("There's nothing to ask again right now.")
            return

        def again():
            yield Thinking(f"Asking {cloud} instead.")
            self.answered = f"Practice: this is where {cloud} would answer."  # so More detail can follow it
            yield from self._say(self.answered, self._practice_done(False, cloud))
        yield from self.book.record(f"Ask {cloud} instead", again())

    def _practice_done(self, here: bool, by: str, instead: str = "") -> NoirDone:
        """The end of a practice answer, with made-up numbers kept in memory, so the
        dot under it and the saved tokens look the way they will for real."""
        chosen = self.menu.chosen() or {}
        source = (chosen.get("cloud") or chosen).get("provider", "")
        if here:
            saved = 0
            if chosen.get("auto"):
                saved = usage.saved_estimate(source, 900, 60)
                usage.record_saved(source, saved)
            return NoirDone(by=by, instead=instead, where=auto.HERE, saved=saved)
        if source in ("codex", "claude_code"):
            # The practice plan counts its tokens and limits. Never a key's model:
            # that one would really go to the company.
            list(self.menu.talker("").chat())
        used = self.menu.plan_used(source) if source in ("codex", "claude_code") else -1.0
        return NoirDone(by=by, where=auto.CLOUD, plan_used=used)

    def choose(self, id: str, choice: str) -> Iterator[Event]:
        self.answered = ""
        yield from self.book.record(choice, self._choice(id, choice))

    def follow_up(self, which: str, think: bool = False) -> Iterator[Event]:
        if which not in FOLLOW_UPS:
            return
        self.answered = ("Practice: the short version would come here." if which == "shorter"
                         else "Practice: more detail would come here, going further than before.")
        yield from self.book.record(FOLLOW_UPS[which], self._say(self.answered))

    def follow_up_words(self, which: str) -> str:
        return FOLLOW_UPS.get(which, "")

    def after_answer(self, reply: str) -> dict:
        return {"follow_ups": bool(self.answered) and reply.strip() == self.answered, "places": False}

    def pictures(self, reply: str) -> list[dict]:
        return []  # the practice app looks nothing up

    def new_chat(self) -> Iterator[Event]:
        self.reset()
        yield from self.book.new()

    def open_chat(self, id: str) -> Iterator[Event]:
        self.sketch = self.going_through = None
        if self.book.open(id) is None:
            yield Error("That conversation could not be found.")
        else:
            yield self.book.transcript()
        yield self.book.chat_list()

    def delete_chat(self, id: str) -> Iterator[Event]:
        yield from self.book.delete(id)

    def toggle_agent(self, name: str) -> Iterator[Event]:
        def flip():
            agent = self._find(name)
            if agent is None or not parts.is_switchable(agent):
                yield Error(f"{name} isn't an agent that can be switched on.")
                return
            self._switch(agent, name not in self.on)
            if name not in self.on:
                yield from self._say(f"{name} is off.")
            elif parts.watches(agent):
                yield from self._say(f"{name} is on. {parts.how(agent)} Only files that land from now on are handled.")
            else:
                yield from self._say(f"{name} is on. Highlight text in any program.")
            yield self._agent_list()
        yield from self.book.record("", flip())

    def send_files(self, text: str, paths: list[str], think: bool = False) -> Iterator[Event]:
        attached = read_attachments(paths)
        said = "\n".join(filter(None, [text, f"Attached: {', '.join(attached.names)}"]))
        yield from self.book.record(said, self._say(f"Practice: I would read {', '.join(attached.names)} now."))

    def set_agent(self, name: str, on: bool) -> Iterator[Event]:
        if (name in self.on) != on:
            yield from self.toggle_agent(name)

    def recipes(self) -> dict:
        have = {agent.name.lower() for agent in self.helpers}
        return {"categories": list(community.CATEGORIES),
                "recipes": [{**asdict(recipe), "added": recipe.name.lower() in have}
                            for recipe in community.recipes(online=False)]}

    def add_recipe(self, id: str) -> Iterator[Event]:
        recipe = community.find(id, online=False)
        if recipe:
            self._add(recipe.name, recipe.instruction, recipe.when, recipe.skip_language)
        yield self._agent_list()

    def post_agent(self, name: str, about: str, category: str, by: str = "") -> dict:
        return {"error": "This is the practice app, so nothing is posted."}

    def switch_agent(self, name: str, on: bool) -> Iterator[Event]:
        recipe = community.find(store_slug(name), online=False)
        if on and self._find(name) is None and recipe:
            self._add(name, recipe.instruction, recipe.when, recipe.skip_language)
        agent = self._find(name)
        if agent and parts.is_switchable(agent):
            self._switch(agent, on)
        yield self._agent_list()

    def activity(self) -> dict[str, int]:
        return {"explained": 34, "polished": 5, "translated": 12, "sorted": 120, "answered": 9, "saved": 12400}

    # Getting to know the user: a made-up portrait. Nothing is read or kept.

    def bring_in_history(self, path: str) -> dict:
        time.sleep(self.delay * 20)
        return {"read": 312, "new": 312, "sources": ["ChatGPT", "Claude"], "total": 312}

    def understand_history(self, progress=None) -> dict:
        for step in ("Sorting 312 chats by what they asked for...", "Looking for what you said about yourself..."):
            if progress:
                progress(step)
            time.sleep(self.delay * 40)
        self._portrait = _practice_portrait()
        return self._portrait

    def look_around(self) -> dict:
        time.sleep(self.delay * 20)
        made = getattr(self, "_portrait", {}) or {"facts": []}
        made["computer"] = {"looked": time.time(), "roles": {"developer": 6, "student": 3},
                            "activities": {"browsing": 6.2, "coding": 4.1, "games": 2.0, "chatting": 1.3},
                            "used": [{"app": "Chrome", "hours": 6.2, "runs": 40, "last": time.time(), "kind": "browsing"},
                                     {"app": "Visual Studio Code", "hours": 4.1, "runs": 22, "last": time.time(), "kind": "coding"}]}
        made["facts"] = [fact for fact in made["facts"] if fact["source"] != "This computer"] + _practice_computer()
        self._portrait = made
        return made

    def bring_in_downloads(self, since: float = 0) -> dict:
        return {"read": 64, "sources": ["Claude"]}

    def what_i_know(self) -> dict:
        return getattr(self, "_portrait", {})

    def keep_fact(self, fact_id: str, kept: bool) -> dict:
        for fact in self.what_i_know().get("facts", []):
            if fact["id"] == fact_id:
                fact["kept"] = bool(kept)
        return self.what_i_know()

    def forget_history(self) -> None:
        self._portrait = {}

    # What the chores lists show, under the names the real engine has for them.

    def chore_agents(self) -> list[dict]:
        """The helpers that work while switched on, the way the real engine lists them:
        each line made from the card alone, whatever the helper is for."""
        lines = []
        for agent in self.helpers:
            on = agent.name in self.on
            if parts.watches(agent):
                lines.append({"name": agent.name, "kind": "files", "on": on, "how": parts.how(agent), "now": "",
                              "since": self.since.get(agent.name, 0) if on else 0, "left": None, "why_off": ""})
            elif parts.is_switchable(agent):
                lines.append({"name": agent.name, "kind": "highlight", "on": on, "how": parts.how(agent)})
        return lines

    def chore_done(self) -> list[dict]:
        """The jobs the made-up helpers did, oldest first, and the ones done in this practice run."""
        return [dict(job) for job in self.jobs]

    def chore_doing(self) -> str:
        return ""  # nothing works on its own in the practice run

    def undo_move(self, id: str) -> int:
        """Undo on a practice job. No file was moved, so only the list changes, the way the
        real one's does: the job can't be undone twice, and putting back is a job too."""
        job = next((job for job in self.jobs if id and job["sort"] == id and job["undo"]), None)
        if job is None:
            return 0
        job["undo"] = False
        back = self._moved.get(id, 1)
        self.jobs.append({"when": time.time(), "text": f"Put {back} file{'' if back == 1 else 's'} back", "undo": False,
                          "details": "", "sort": "", "agent": "", "where": ""})
        return back

    def setup_state(self) -> dict:
        return self.setup.state() if self.setup else {"needed": False}

    def setup_begin(self, smallest: bool = False) -> dict:
        return self.setup.begin(bool(smallest)) if self.setup else {"needed": False}

    def measure(self) -> dict:
        time.sleep(self.delay * 40)
        return {"device": "Practice graphics card · 8 GB", "words_per_second": 45,
                "results": [{"what": "to explain a word you highlight", "seconds": 0.6, "words": 14},
                            {"what": "to polish a messy message", "seconds": 0.9, "words": 22},
                            {"what": "to translate a paragraph", "seconds": 1.7, "words": 40}]}

    def spot_actions(self, text: str, editable: bool) -> list[dict]:
        return spot.actions_for(text, editable, [("Grammar Fixer", "Fix the grammar.")])

    def spot_run(self, action: str, text: str, ask: str = "") -> dict:
        time.sleep(self.delay * 10)
        words = ask or dict((item["id"], item["words"]) for item in spot.actions_for(text, True)).get(action, action)
        return {"text": f"Practice: the answer to \"{words}\" would appear here."}

    def details(self, name: str) -> dict:
        """What a helper's page shows, from its card. Empty if there's no such helper."""
        agent = self._find(name)
        return parts.describe(agent) if agent else {}

    def _find(self, name: str) -> Agent | None:
        return next((agent for agent in self.helpers if agent.name == name), None)

    def _add(self, name: str, instruction: str, when: str, skip_language: str = "") -> Agent:
        """A ready-made or shared helper joins the made-up ones, as the card the real app saves for it."""
        agent = self._find(name)
        if agent is None:
            slots = {"instruction": instruction, "when": when, "show": BUBBLE, "keep": UNTIL_UNHIGHLIGHT, "name": name}
            if skip_language:
                slots["skip_language"] = skip_language
            slots.update(parts.defaults(slots))
            agent = Agent(name, parts.CUSTOM, slots)
            self.helpers.append(agent)
        return agent

    def _switch(self, agent: Agent, on: bool) -> None:
        if on and agent.name not in self.on:
            self.since[agent.name] = time.time()
        self.on = self.on | {agent.name} if on else self.on - {agent.name}

    def _agent_list(self) -> AgentList:
        names = [agent.name for agent in self.helpers]
        return AgentList(names, sorted(agent.name for agent in self.helpers if parts.is_switchable(agent)),
                         sorted(self.on & set(names)))

    def delete_agent(self, name: str) -> Iterator[Event]:
        def ask():
            self.deleting = name
            yield Question("delete_agent", f"Delete {name}? It forgets everything it read.",
                           ["Delete it", "Keep it"])
        yield from self.book.record("", ask())

    def reset(self) -> None:
        self.sketch = self.going_through = None
        self.book.new()

    def close(self) -> None:
        pass

    # ----------------------------------------------------------- scripts

    def _reply(self, text: str) -> Iterator[Event]:
        lowered = text.lower()
        if self.sketch is not None:
            yield from self._design(text)
        elif asked := next((agent for agent in self.helpers if lowered.startswith(f"{agent.name.lower()}:")), None):
            yield from self._ask(asked, text)
        elif starter := asks_for(text):
            agent = self._add(starter.name, starter.instruction, starter.when, starter.skip_language)
            if starter.when != parts.WHILE_ON:
                yield from self._say(f"{starter.name} is ready. Start your message with its name to use it.")
            elif WANTS_ON.search(text):
                self._switch(agent, True)
                yield from self._say(f"{starter.name} is on. Highlight text in any program.")
            else:
                yield from self._say(f"{starter.name} is ready. Use its switch to turn it on.")
            yield self._agent_list()
        elif any(word in lowered for word in ("translate", "shortcut", "screenshot", "idea")):
            yield IdeaCard(
                "idea", "Highlight translator",
                [IdeaStep("When you press a shortcut key (Ctrl+F1)", "not_built"),
                 IdeaStep("The text you highlighted", "not_built"),
                 IdeaStep("Translate text (into Korean)", "not_built"),
                 IdeaStep("Show the result in a small bubble or notification", "not_built")],
                "Easy: the built-in model can do this, nothing extra to download.",
                "Your computer can do this, but the app can't build it yet. Save the idea, and "
                "the most wanted parts get built first.",
                "not_built", ["Save the idea", "Change the idea", "Cancel"],
            )
        elif "error" in lowered:
            yield Error("Ollama is not running. Open the Ollama app and try again.")
        elif lowered.startswith("ask "):
            yield from self._run_agent("Contracts helper", text)
        elif any(word in lowered for word in ("make", "create", "agent", "document", "files", "folder")):
            # A helper is asked for. Nothing is known about it yet and none is offered: the
            # conversation starts from what the user wants, as the real one does.
            self.sketch = {"stage": "wants", "rule": "", "looks_at": parts.INSIDE_FILE,
                           "name": self._free_name("Downloads helper")}
            yield Thinking("Working a helper out is a conversation. With a model, it talks it through with you; "
                           "in the practice run a script plays it.")
            yield Question(DESIGN, _ASKS_WHAT)
        else:
            self.answered = ("This is the fake engine talking. Real replies stream in like this, "
                             "a few words at a time, until the reply is done.")
            yield from self._say(self.answered)

    def _choice(self, id: str, choice: str) -> Iterator[Event]:
        if id == "delete_agent":
            name, self.deleting = self.deleting, None
            agent = self._find(name) if name else None
            if choice == "Delete it" and agent:
                self.helpers.remove(agent)
                self.on.discard(name)
                self.since.pop(name, None)
                yield from self._say(f"Deleted {name}.")
                yield self._agent_list()
            else:
                yield from self._say("Okay, I kept it.")
        elif id == "idea" and choice == "Change the idea":
            yield Question("idea_change", "What should be different?")
        elif id == "idea" and choice == "Save the idea":
            yield from self._say('Saved "Highlight translator" to your ideas (1 saved).')
        elif id == "idea":
            yield from self._say("Okay, I've put that idea aside.")
        elif id == FIRST_PASS:
            name, self.going_through = self.going_through, None
            agent = self._find(name) if name else None
            if choice == GO_THROUGH and agent:
                yield from self._go_through(agent)
            else:
                yield from self._say("Okay, only new files from now on.")
        elif id in (CARD, "looks_at") and self.sketch is None:
            yield from self._say("That question has already been answered.")
        elif id in (CARD, "looks_at") and self.sketch["stage"] == "wants":
            yield from self._open_question()  # a button of an earlier conversation: the open question again
        elif id == "looks_at" and choice in _LOOKS:
            yield from self._looks_at(choice)
        elif id == CARD and choice == CREATE_IT and self.sketch["stage"] in ("card", "change"):
            yield from self._create()
        elif id == CARD and choice == CREATE_IT:
            yield from self._open_question()  # no card is up yet: the open question again
        elif id == CARD and choice == "Change something":
            # A change is said in words, not picked from a list of settings.
            self.sketch["stage"] = "change"
            yield Question(DESIGN, "What should I change?")
        elif id == CARD:
            yield from self._call_off()
        else:
            yield Error(f"Nothing is waiting for an answer to {id!r}.")

    def _say(self, text: str, done: NoirDone | None = None) -> Iterator[Event]:
        for word in text.split(" "):
            time.sleep(self.delay)
            yield NoirText(word + " ")
        yield done or NoirDone()

    # The practice conversation in which a helper is worked out (see _ASKS_WHAT above).

    def _design(self, text: str) -> Iterator[Event]:
        """Something was typed while the practice helper is being worked out."""
        sketch = self.sketch
        whole = text.strip().lower().strip("!. ")
        typed = next((choice for choice in _LOOKS if choice.lower() == whole), None)
        if whole in CANCEL_WORDS or (sketch["stage"] == "card" and whole in ("no", "nope")):
            yield from self._call_off()
        elif sketch["stage"] == "wants":
            sketch["rule"], sketch["stage"] = _as_rule(text), "looks_at"
            yield from self._open_question()
        elif sketch["stage"] == "looks_at" and typed:
            yield from self._looks_at(typed)  # typed word for word instead of clicked
        elif sketch["stage"] == "looks_at":
            yield Question("looks_at", _ASKS_HOW, list(_LOOKS))
        elif sketch["stage"] == "card" and whole in CARD_YES:
            # A plain yes is a yes to the card on screen. Only the whole message counts.
            yield from self._create()
        else:
            # Anything else said at the card is a change. Here it joins the rule as typed,
            # and the try-out and the card come again, as they do after a real change.
            sketch["rule"], sketch["stage"] = _as_rule(f"{sketch['rule'].rstrip('. ')}. {text}"), "card"
            yield from self._say(_CHANGED)
            yield from self._try_out(again=True)
            yield self._card()

    def _open_question(self) -> Iterator[Event]:
        """The question the practice conversation is waiting on."""
        if self.sketch["stage"] == "wants":
            yield Question(DESIGN, _ASKS_WHAT)
        else:
            yield Question("looks_at", _PROPOSES, list(_LOOKS))

    def _looks_at(self, choice: str) -> Iterator[Event]:
        """Nothing needed is missing any more: a few words, the try-out, then the card."""
        self.sketch["looks_at"], self.sketch["stage"] = choice, "card"
        yield from self._say(_SUMS_UP)
        yield from self._try_out()
        yield self._card()

    def _try_out(self, again: bool = False) -> Iterator[Event]:
        """A try-out as the real one reports it (designer.row_line writes each file's line),
        on made-up files. Nothing is read or moved."""
        rows = _practice_rows(self.sketch["looks_at"] == parts.NAME_ONLY)
        yield Thinking("Trying it on what's in Downloads now. Nothing moves.")
        time.sleep(self.delay * 10)
        if again:
            yield Result(TRY_OUT, f"Tried again on the same {len(rows)} files in Downloads. Nothing was moved.\n"
                                  "It came out the same as before.")
            return
        lines = [row_line(row, parts.MOVE) for row in rows]
        yield Result(TRY_OUT, "\n".join([f"Tried on the {len(rows)} newest files in Downloads. Nothing was moved.",
                                         *lines]))

    def _slots(self) -> dict:
        """The practice helper as the card the real app would save: one that works on the
        new files of a folder and moves them by the rule, into folders made as the rule
        calls for them, since the script can't know what folders the user's rule needs."""
        sketch = self.sketch
        return {"when": parts.NEW_FILE, "then": parts.MOVE, "folder": f"{_HOME}/Downloads",
                "looks_at": sketch["looks_at"], "instruction": sketch["rule"], "choices": "",
                "open": parts.OPEN_YES, "into": "", "name": sketch["name"]}

    def _card(self) -> AgentCard:
        """The card, every line written from the slots by the code that writes the real one."""
        slots = self._slots()
        kind, reads, can_do, cannot_do, runs_on = parts.card(slots, _BUILT_IN)
        return AgentCard(id=CARD, name=slots["name"], kind=kind, reads=reads, can_do=can_do, cannot_do=cannot_do,
                         runs_on=runs_on, actions=[CREATE_IT, "Change something", "Cancel"])

    def _create(self) -> Iterator[Event]:
        """The card's button, or a plain yes at the card: the helper joins the made-up ones.
        Then what the real engine does for one that works on a folder's new files: it is
        switched on, and the files already there are asked about, never taken."""
        agent = Agent(self.sketch["name"], parts.CUSTOM, self._slots())
        self.sketch = None
        self.helpers.append(agent)
        self._switch(agent, True)
        yield from self._say(f"{agent.name} is ready.")
        yield self._agent_list()
        rows = _practice_rows(agent.slots["looks_at"] == parts.NAME_ONLY)
        self.going_through = agent.name
        yield Question(FIRST_PASS, "It's on: new files in Downloads are handled as they land, and everything it does "
                                     f"shows in your chores. There are {len(rows)} files there already. Go through "
                                     "them now?", [GO_THROUGH, ONLY_NEW])

    def _call_off(self) -> Iterator[Event]:
        self.sketch = None
        yield from self._say("Okay, I won't create it.")

    def _go_through(self, agent: Agent) -> Iterator[Event]:
        """The first pass over the files already there, as the real one reports it: a line
        for each file while it is looked at, then what moved and what stayed, and one job
        in the chores list that can be undone."""
        by_name = agent.slots.get("looks_at") == parts.NAME_ONLY
        rows = _practice_rows(by_name)
        doing = "Looking at the name of" if by_name else "Reading"
        for index, row in enumerate(rows, 1):
            time.sleep(self.delay * 10)
            yield Progress(f"{doing} {row['name']} ({index} of {len(rows)})...")
        moved = Counter(row["choice"] for row in rows if row["choice"])
        # Why each file that stayed did, by the reason alone, as a real pass counts them.
        left = [row["why"].partition(": ")[0] for row in rows if not row["choice"]]
        count = sum(moved.values())
        files = f"{count} file{'' if count == 1 else 's'}"
        where = " · ".join(f"{folder} {number}" for folder, number in moved.items())
        sort = f"practice-{len(self.jobs) + 1}"
        self._moved[sort] = count
        self.jobs.append({"when": time.time(), "text": f"Moved {files} from Downloads", "undo": True,
                          "details": where, "sort": sort, "agent": agent.name, "where": ""})
        said = f"Moved {files}: {where}."
        if left:
            stayed = "it was" if len(left) == 1 else "they were"
            said += f" {len(left)} left where {stayed}: {', '.join(dict.fromkeys(left))}."
        yield Result(agent.name, f"{said} Undo is in your chores.")

    def _ask(self, agent: Agent, text: str) -> Iterator[Event]:
        """A message that starts with a helper's name and a colon is for that helper, as in
        the real app (a helper's page sends one from its Try this button)."""
        if agent.blueprint == parts.DOCUMENTS_QA:
            yield from self._run_agent(agent.name, text)
        elif not parts.watches(agent):
            yield Result(agent.name, "Practice: this is where its answer would come.")
        elif agent.name in self.on:
            # Nothing lands in the practice run, so a pass asked for finds nothing new.
            folder = parts.shown_place(Path(agent.slots["folder"]))
            yield Result(agent.name, f"Nothing new has landed in {folder} since {agent.name} was switched on. A file "
                                     "is looked at a few seconds after it has finished arriving; ask again in a "
                                     "moment, or say which file.")
        else:
            yield from self._say(f"{agent.name} is switched off right now, so it hasn't been watching.")

    def _free_name(self, base: str) -> str:
        """A name none of the helpers has, the way the real app makes one when none was given."""
        names = {agent.name.lower() for agent in self.helpers}
        name, number = base, 2
        while name.lower() in names:
            name, number = f"{base} {number}", number + 1
        return name

    def _run_agent(self, name: str, question: str) -> Iterator[Event]:
        for step in ("Searching 23 files...", "Reading the 3 best matches..."):
            time.sleep(self.delay * 10)
            yield Progress(step)
        yield Result(
            agent=name,
            text="The Acme contract was signed on 12 March 2026 by Dana Kim.",
            sources=[
                Source("Desktop/Work/contract_acme.pdf", "Signed this 12th day of March 2026"),
                Source("Desktop/Work/contract_acme.pdf", "Dana Kim, Operations Lead"),
            ],
        )
        yield from self._say("Acme's contract was signed on 12 March by Dana Kim.")


def _practice_helpers() -> list[Agent]:
    """The helpers the practice run starts with, each a card as the real app saves one:
    one that answers from a folder's documents, one that works on what is highlighted, and
    one that works on a folder's new files. All made up; nothing is saved or looked at."""
    return [
        Agent("Contracts helper", parts.DOCUMENTS_QA, {"folder": f"{_HOME}/Documents/Contracts", "name": "Contracts helper"},
              contents=["lease.pdf", "offer.docx", "notes.txt"]),
        Agent("Korean translator", parts.CUSTOM, {
            "when": parts.WHILE_ON, "then": parts.SHOW, "instruction": "Translate the text into Korean.",
            "show": BUBBLE, "keep": UNTIL_UNHIGHLIGHT, "skip_language": "Korean", "name": "Korean translator"}),
        Agent("Home papers", parts.CUSTOM, {
            "when": parts.NEW_FILE, "then": parts.MOVE, "folder": f"{_HOME}/Downloads", "looks_at": parts.INSIDE_FILE,
            "instruction": "Put manuals and warranties in Manuals, and anything about a trip in Trips. "
                           "Leave everything else where it is.",
            "choices": "Manuals, Trips", "open": parts.OPEN_NO, "into": "", "name": "Home papers"}),
    ]


def _practice_jobs(now: float, agent: str) -> list[dict]:
    """Two jobs the made-up helper for new files did earlier, as the real record keeps them."""
    def job(number, minutes_ago, file, folder):
        return {"when": now - minutes_ago * 60, "text": f"Put {file} in {folder}", "undo": True,
                "details": f"from Downloads · The rule puts it in {folder}", "sort": f"practice-{number}",
                "agent": agent, "where": f"{_HOME}/Downloads/{folder}"}

    return [job(1, 90, "dishwasher-manual.pdf", "Manuals"), job(2, 30, "ferry-booking.pdf", "Trips")]


def _practice_rows(by_name: bool) -> list[dict]:
    """A try-out's rows as the real one gets them (folderwatch.rehearse), for three made-up
    files: one that would go into a new folder, one into the folder that makes, and one
    that would stay, for the reason the real record gives."""
    stays = f"{LEFT_BY_RULE}: a program" if by_name else NO_TEXT
    return [{"name": "practice-letter.pdf", "choice": "Practice folder", "new": True, "what": "a made-up letter"},
            {"name": "practice-list.txt", "choice": "Practice folder", "new": False, "what": "a made-up list"},
            {"name": "practice-setup.exe", "choice": "", "new": False, "what": "", "why": stays}]


def _as_rule(text: str) -> str:
    """What was typed, as a rule is kept: one paragraph, no longer than a rule may be."""
    return " ".join(text.split())[:parts.MAX_RULE]


def _practice_portrait() -> dict:
    """What a portrait looks like, for building the windows without anyone's chats."""
    def fact(n, about, words, quote, source, seen):
        return {"id": f"practice{n}", "about": about, "fact": words, "quote": quote, "source": source,
                "title": "Practice chat", "when": time.time() - n * 86400 * 9, "seen": seen, "kept": None}

    return {
        "made": time.time(), "chats": {"ChatGPT": 248, "Claude": 64}, "first": time.time() - 86400 * 410,
        "last": time.time() - 86400, "busiest": "in the evening", "languages": {"Korean": 201, "English": 111},
        "kinds": [{"id": "writing", "words": "Writing and polishing messages", "topic": "spot", "count": 96},
                  {"id": "studying", "words": "Studying and homework", "topic": "explain", "count": 71},
                  {"id": "coding", "words": "Code and errors", "topic": "spot", "count": 54},
                  {"id": "translating", "words": "Translating", "topic": "translate", "count": 38},
                  {"id": "planning", "words": "Plans and ideas", "topic": "plan", "count": 21},
                  {"id": "other", "words": "Other", "topic": "", "count": 32}],
        "facts": [fact(1, "study", "Studies computer science at university", "I'm a computer science student", "ChatGPT", 9),
                  fact(2, "tool", "Uses Python and VS Code", "I use Python in VS Code", "Claude", 6),
                  fact(3, "place", "Lives in Seoul", "저는 서울에 살고 있어요", "ChatGPT", 3),
                  fact(4, "goal", "Is preparing for a job interview in English", "I have an interview in English next month", "ChatGPT", 2),
                  fact(5, "interest", "Likes making games", "I love making small games", "Claude", 2)],
    }


def _practice_computer() -> list[dict]:
    """Made-up guesses from looking around a computer."""
    def fact(n, about, words, quote):
        return {"id": f"computer{n}", "about": about, "fact": words, "quote": quote, "source": "This computer",
                "title": "", "when": time.time(), "seen": 1, "kept": None}

    return [fact(1, "tool", "Writes code in Visual Studio Code", "Visual Studio Code is installed"),
            fact(2, "tool", "Makes things in Unity", "Unity Hub is installed"),
            fact(3, "tool", "Writes code, mostly in Python and C#", "5 folders with code, like puzzle-cat"),
            fact(4, "study", "Keeps school files: lectures and assignments", "48 files named like lectures or assignments")]


class PracticeAccounts:
    """ChatGPT and Claude plans for the practice app: Sign in "works" after a moment,
    answers are made up, and no app is started."""

    def __init__(self):
        self.signed = set()

    def overview(self, fresh: bool = False) -> list[dict]:
        return [self.status(app) for app in ("codex", "claude_code")]

    def status(self, app: str, fresh: bool = False) -> dict:
        name, program = ("ChatGPT", "Codex") if app == "codex" else ("Claude", "Claude Code")
        models = [{"id": "practice-1", "name": f"{name} (practice)"}] if app in self.signed else []
        return {"id": app, "name": name, "app": program, "plan": f"your {name} plan", "installed": True,
                "signed_in": app in self.signed, "sign_in": "Pretend to sign in, then come back", "models": models}

    def sign_in(self, app: str) -> None:
        self.signed.add(app)

    def install(self, app: str) -> None:
        pass

    def talker(self, app: str, model: str, system: str):
        def counted():
            # Made-up numbers in memory, so the practice app's usage meter moves.
            used = usage.summary().get(app, {}).get("limits") or [{"id": "five_hour", "used": 0.12},
                                                                 {"id": "seven_day", "used": 0.31}]
            now = time.time()
            usage.record_limits(app, [{"id": w["id"], "used": min(1.0, w["used"] + 0.04),
                                       "resets_at": now + (5 * 3600 if w["id"] == "five_hour" else 4 * 86400)}
                                      for w in used])
            usage.record_tokens(app, model, 21_400, 180)

        class Practice:
            def chat(self, *args, **kwargs):
                counted()
                yield "Practice: this is where your plan's model would answer."

            def chat_parts(self, *args, **kwargs):
                counted()
                yield "text", "Practice: this is where your plan's model would answer."

            def capabilities(self, name):
                return ["completion"]

            def refresh(self, name, keep_alive):
                pass

        return Practice()


class PracticeSetup:
    """The first-run setup page's three steps, played in a few seconds with nothing
    fetched, installed or built, so the page can be tried without touching Ollama."""

    STEPS = (("ollama", "Downloading Ollama from ollama.com...", 0.7), ("ollama", "Installing Ollama...", 0.0),
             ("model", "Downloading Qwen 3.5 4B (3.3 GB)...", 3.3), ("noir", "Building Noir from the model...", 0.0))

    def __init__(self):
        self.done: set[str] = set()
        self.step = self.note = self.error = ""
        self.progress: tuple[int, int] | None = None
        self.smallest = False
        self._thread = None

    def state(self) -> dict:
        working = self._thread is not None and self._thread.is_alive()
        return {"needed": "noir" not in self.done, "hardware": ["Windows 11, a practice computer (8 cores)",
                "Memory: 32 GB (18 GB free right now)", "Graphics: NVIDIA GeForce RTX 5080, 16 GB", "Disk: 420 GB free"],
                "device": "NVIDIA GeForce RTX 5080", "ollama": "running" if "ollama" in self.done else "missing",
                "ollama_gb": 0.7, "can_install": True, "download_page": "https://ollama.com/download",
                "model": {"tag": "qwen3.5:4b", "name": "Qwen 3.5 4B", "download_gb": 3.3, "memory_gb": 3.8,
                          "have": "model" in self.done},
                "fits": True, "reason": "", "noir": "noir" in self.done, "working": working, "step": self.step,
                "note": self.note, "progress": {"done": self.progress[0], "total": self.progress[1]} if self.progress else None,
                "waiting": "", "error": self.error, "mac": False}

    def begin(self, smallest: bool = False) -> dict:
        import threading

        if self._thread is None or not self._thread.is_alive():
            self.error = ""
            self._thread = threading.Thread(target=self._play, daemon=True)
            self._thread.start()
        return self.state()

    def _play(self) -> None:
        import time

        for step, note, gb in self.STEPS:
            if step in self.done and not (step == "ollama" and "Installing" in note):
                continue
            self.step, self.note = step, note
            total = int(gb * 1024 ** 3)
            for tick in range(1, 21):
                time.sleep(0.12)
                self.progress = (total * tick // 20, total) if total else None
            self.progress = None
            self.done.add(step)
        self.step = self.note = ""
