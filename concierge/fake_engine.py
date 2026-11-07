"""A scripted engine for building the UI before the real agent pipeline exists.

It follows the same Engine contract as the real one (see events.py) and
produces every event type, so each part of the UI can be built and clicked
through. No Ollama or model is needed.

What to type to see each flow:
    anything               Noir streams a chat reply
    "make an agent"        agent setup: Question (typed answer), Question
    (or mention documents,   with buttons, AgentCard, Progress, Result
    files or a folder)
    "ask ..."              run the existing agent: Progress, Result with sources
    "translate ...", "screenshot ..." or "idea"
                           an IdeaCard: Noir's verdict on a helper idea
    "error"                an Error event
    "turn on the highlight explainer" or "install Grammar Fixer"
                           adds a ready-made agent (agents/starters.yaml),
                           and switches it on if asked

Conversations are kept in memory (same ChatBook as the real engine), so New
chat, reopening and deleting chats work too, and so does deleting an agent.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import asdict

from . import auto, hardware, usage
from .agents import community
from .agents.recipe import CUSTOM, WHILE_ON, describe
from .agents.starters import asks_for, load_starters
from .agents.store import Agent
from .agents.store import slugify as store_slug
from .attachments import read_attachments
from .quick import spot
from .conversations import ChatBook
from .engine import FOLLOW_UPS, WANTS_ON
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
)


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
        self.agents = ["Contracts helper", "Korean translator"]
        self.switchable = {"Korean translator"}
        self.on: set[str] = set()
        self.draft: dict = {}
        self.waiting_for: str | None = None  # which typed answer we expect next
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
        from .events import Thinking
        self.answered = ""

        def with_thinking():
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
        from .events import Thinking
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
        self.draft, self.waiting_for = {}, None
        if self.book.open(id) is None:
            yield Error("That conversation could not be found.")
        else:
            yield self.book.transcript()
        yield self.book.chat_list()

    def delete_chat(self, id: str) -> Iterator[Event]:
        yield from self.book.delete(id)

    def toggle_agent(self, name: str) -> Iterator[Event]:
        def flip():
            if name not in self.switchable:
                yield Error(f"{name} isn't an agent that can be switched on.")
                return
            self.on ^= {name}
            state = "on. Highlight text in any program" if name in self.on else "off"
            yield from self._say(f"{name} is {state}.")
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
        have = {name.lower() for name in self.agents}
        return {"categories": list(community.CATEGORIES),
                "recipes": [{**asdict(recipe), "added": recipe.name.lower() in have}
                            for recipe in community.recipes(online=False)]}

    def add_recipe(self, id: str) -> Iterator[Event]:
        recipe = community.find(id, online=False)
        if recipe and recipe.name not in self.agents:
            self.agents.append(recipe.name)
            if recipe.when == WHILE_ON:
                self.switchable.add(recipe.name)
        yield self._agent_list()

    def post_agent(self, name: str, about: str, category: str, by: str = "") -> dict:
        return {"error": "This is the practice app, so nothing is posted."}

    def switch_agent(self, name: str, on: bool) -> Iterator[Event]:
        recipe = community.find(store_slug(name), online=False)
        if on and name not in self.agents and recipe:
            self.agents.append(name)
            if recipe.when == WHILE_ON:
                self.switchable.add(name)
        if name in self.switchable:
            self.on = self.on | {name} if on else self.on - {name}
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
        starter = next((s for s in load_starters() if s.name == name), None)
        if starter:
            return describe(Agent(name, CUSTOM, {"instruction": starter.instruction, "when": starter.when}))
        if name in self.switchable:
            return describe(Agent(name, CUSTOM, {"instruction": "Translate the text into Korean."}))
        return describe(Agent(name, "documents_qa", {"folder": "C:/Users/you/Documents/Contracts"},
                              contents=["lease.pdf", "offer.docx", "notes.txt"]))

    def _agent_list(self) -> AgentList:
        return AgentList(list(self.agents), sorted(self.switchable & set(self.agents)),
                         sorted(self.on & set(self.agents)))

    def delete_agent(self, name: str) -> Iterator[Event]:
        def ask():
            self.deleting = name
            yield Question("delete_agent", f"Delete {name}? It forgets everything it read.",
                           ["Delete it", "Keep it"])
        yield from self.book.record("", ask())

    def reset(self) -> None:
        self.draft = {}
        self.waiting_for = None
        self.book.new()

    def close(self) -> None:
        pass

    # ----------------------------------------------------------- scripts

    def _reply(self, text: str) -> Iterator[Event]:
        lowered = text.lower()
        if self.waiting_for == "folder":
            self.waiting_for = None
            self.draft["folder"] = text.strip()
            yield from self._say("Got it. Should it read every file there, or only some kinds?")
            yield Question("file_types", "Which files should it read?", ["PDF only", "Word only", "Everything"])
        elif starter := asks_for(text):
            if starter.name not in self.agents:
                self.agents.append(starter.name)
                if starter.when == WHILE_ON:
                    self.switchable.add(starter.name)
            if starter.when != WHILE_ON:
                yield from self._say(f"{starter.name} is ready. Start your message with its name to use it.")
            elif WANTS_ON.search(text):
                self.on.add(starter.name)
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
            self.draft = {"name": "Contracts helper" if "contract" in lowered else "Documents helper"}
            self.waiting_for = "folder"
            yield from self._say(
                "I can set up an agent that reads a folder of your files and answers "
                "questions about them, quoting where it found each answer."
            )
            yield Question("folder", "Which folder should it read?")
        else:
            self.answered = ("This is the fake engine talking. Real replies stream in like this, "
                             "a few words at a time, until the reply is done.")
            yield from self._say(self.answered)

    def _choice(self, id: str, choice: str) -> Iterator[Event]:
        if id == "delete_agent":
            name, self.deleting = self.deleting, None
            if choice == "Delete it" and name in self.agents:
                self.agents.remove(name)
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
        elif id == "file_types":
            self.draft["file_types"] = choice
            yield self._card()
        elif id == "card":
            if choice == "Create it":
                yield from self._create()
            elif choice == "Change something":
                yield Question("change", "What would you like to change?", ["Folder", "Which files"])
            else:
                self.draft = {}
                yield from self._say("Okay, I won't create it.")
        elif id == "change" and choice == "Folder":
            self.waiting_for = "folder"
            yield Question("folder", "Which folder should it read instead?")
        elif id == "change":
            yield Question("file_types", "Which files should it read?", ["PDF only", "Word only", "Everything"])
        else:
            yield Error(f"Nothing is waiting for an answer to {id!r}.")

    def _say(self, text: str, done: NoirDone | None = None) -> Iterator[Event]:
        for word in text.split(" "):
            time.sleep(self.delay)
            yield NoirText(word + " ")
        yield done or NoirDone()

    def _card(self) -> AgentCard:
        kinds = {"PDF only": "PDF files", "Word only": "Word files"}
        files = kinds.get(self.draft.get("file_types", ""), "all files")
        return AgentCard(
            id="card",
            name=self.draft.get("name", "Documents helper"),
            kind="Ask my documents",
            reads=[f"{self.draft.get('folder', 'Documents')} ({files}, 23 files)"],
            can_do=["Find and quote passages", "Answer questions about them"],
            cannot_do=["Change, move or delete files", "Use the internet"],
            runs_on="Qwen 3.5 4B (the built-in model, no extra memory)",
        )

    def _create(self) -> Iterator[Event]:
        name = self.draft.get("name", "Documents helper")
        for step in ("Reading 23 files...", "Building the search index...", "Trying it out..."):
            time.sleep(self.delay * 10)
            yield Progress(step)
        yield Result(
            agent=name,
            text="Test question: what are the payment terms? Invoices are due within 30 days.",
            sources=[Source("Desktop/Work/contract_acme.pdf", "Payment is due within thirty (30) days")],
        )
        if name not in self.agents:
            self.agents.append(name)
        self.draft = {}
        yield from self._say(f"{name} is ready. Ask it anything about those files.")
        yield self._agent_list()

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
