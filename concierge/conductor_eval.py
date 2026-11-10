"""Setups talked through, with a real model as the conductor, on a made-up home.

Each script is a short conversation the way people really type it: the user's own first
setup (typos, an answer out of order, a worry about old files, bank statements), one
message that says everything, a change of mind at the card, "never mind", a question
about something else, a folder that doesn't exist, the summary writer, and a setup in
Korean. What is checked is what code ended up with and what was never done: the right
folders in the draft, nothing created by talking, nothing moved, never "it's on" before
the card's button. The words are printed to be read, since no check can judge them.

This is how a model gets onto the conductors list in models.yaml: every check must
pass. Everything lives in a temporary folder that stands in for the user's home, and the
app's data goes to a temporary LOCALAPPDATA. Ollama must be running, with Noir set up.

    python -m concierge.conductor_eval [tag ...] [--keep]

With no tag, the conductor the engine would pick on this computer is the one tried.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

from concierge import organizer as org
from concierge.agents import builder as builder_mod
from concierge.agents import store
from concierge.agents.builder import CARD, CREATE_IT
from concierge.agents.conductor import Conductor, local_form
from concierge.engine import ONLY_NEW, ORGANIZE_NOW, NoirEngine
from concierge.events import AgentCard, Error, NoirText, Question, Result, Thinking
from concierge.organizer_eval import OLD, REQUEST, SECOND, drop

# Words that say the agent exists or runs. Before the card's button is pressed that is
# never true, and three of four models said it anyway in the first probe.
SAYS_DONE = re.compile(r"\b(is|it'?s|are) (now |already )?(on|active|running|switched on|turned on|created|up and running)\b"
                       r"|\bi('ve| have)? (just )?(created|switched it on|turned it on|started it|set it up)\b",
                       re.IGNORECASE)
# The same words about later, which claim nothing: "files that arrive while it is running",
# "once it is on". Looked for just in front of a match.
ABOUT_LATER = re.compile(r"\b(while|when|whenever|once|after|if|until|as long as|as soon as)\b[^.!?,;]{0,25}$", re.IGNORECASE)


def claims_done(words: str) -> bool:
    """Whether a line says the agent exists or runs now, not what it will do once it does."""
    return any(not ABOUT_LATER.search(words[:match.start()]) for match in SAYS_DONE.finditer(words))
SAYS_STAYS = re.compile(r"stay|leav|alone|won'?t|will not|not (be )?(mov|touch)|untouched|ignor|only", re.IGNORECASE)
CANT_FIND = re.compile(r"(can'?t|cannot|couldn'?t|could not|unable to|wasn'?t able to) (find|see|locate)|no folder", re.IGNORECASE)
HANGUL = re.compile(r"[가-힣]")


class Trial:
    """One model tried as the conductor: an engine on the made-up home, the scripts, the checks."""

    def __init__(self, root: Path, tag: str | None):
        self.tag = tag
        self.home = root / "home"
        self.downloads = self.home / "Downloads"
        self.desktop = self.home / "OneDrive" / "바탕 화면"  # a Korean Windows with OneDrive backup, like the user's
        self.documents = self.home / "Documents"
        self.appdata = root / "appdata"
        for folder in (self.downloads, self.desktop, self.documents, self.home / "Pictures", self.appdata):
            folder.mkdir(parents=True)
        self.checks: list[bool] = []
        self.said: list[str] = []  # what the conductor said in the script running now
        self.engine: NoirEngine | None = None

    def place(self, name: str, home: Path | None = None) -> Path:
        return {"Desktop": self.desktop, "Downloads": self.downloads}.get(name, self.home / name)

    # ------------------------------------------------------------ plumbing

    def start(self) -> bool:
        os.environ["LOCALAPPDATA"] = str(self.appdata)
        # The made-up home stands in for the user's, so a folder looked for by name is
        # looked for there and nowhere on the real computer.
        os.environ["USERPROFILE"] = os.environ["HOME"] = str(self.home)
        builder_mod.known_folder = self.place
        org.known_folder = self.place
        builder_mod.watched_from = lambda text: org.watched_from(text, place=self.place)
        builder_mod.is_blocked = lambda folder: False  # the temporary folder is under AppData
        drop(self.downloads, OLD)
        self.engine = NoirEngine()
        problems = [event.text for event in self.engine.startup() if isinstance(event, Error)]
        if problems or self.engine.builder is None:
            print("Noir isn't running:", "; ".join(problems))
            return False
        self.engine.organizer._settle_seconds = 1
        if self.tag:
            ollama, tag = self.engine.ollama, self.tag
            self.engine.builder.conductor = lambda: Conductor(local_form(ollama, tag), tag, here=True)
        conductor = self.engine.builder.conductor()
        if conductor is None:
            print("No conductor on this computer: no plan or key model picked, and none of the models on the "
                  "conductors list is installed. Name a tag to try one.")
            return False
        print(f"conductor: {conductor.name} ({'on this computer' if conductor.here else 'off this computer'})")
        return True

    def show(self, events, label: str) -> list:
        print(f"\n  USER  {label}")
        kept, text = [], []
        for event in events:
            kept.append(event)
            if isinstance(event, NoirText):
                text.append(event.text)
                continue
            if text:
                self.spoke("".join(text))
                text = []
            if isinstance(event, Thinking):
                print("        [think]", event.text.strip().replace("\n", " ")[:220])
            elif isinstance(event, Question):
                self.spoke(event.text, f"  {event.choices or ''}")
            elif isinstance(event, AgentCard):
                print(f"        CARD {event.name}: reads {event.reads}; can {event.can_do[:4]}")
            elif isinstance(event, Result):
                print(f"        RESULT ({event.agent}): {event.text[:200]}")
            elif isinstance(event, Error):
                print("        ERROR:", event.text)
        if text:
            self.spoke("".join(text))
        return kept

    def spoke(self, words: str, more: str = "") -> None:
        words = words.strip().replace(str(self.home), "~")
        self.said.append(words)
        print(f"  NOIR  {words}{more}")

    def say(self, text: str) -> list:
        return self.show(self.engine.send(text), text)

    def click(self, id: str, choice: str) -> list:
        return self.show(self.engine.choose(id, choice), f"[clicks {choice}]")

    def check(self, condition: bool, what: str) -> None:
        print(("  OK    " if condition else "  FAIL  ") + what)
        self.checks.append(bool(condition))

    def slots(self) -> dict:
        builder = self.engine.builder
        return dict(builder.draft.slots) if builder and builder.draft else {}

    def active(self) -> bool:
        return bool(self.engine.builder and self.engine.builder.active)

    def untouched(self) -> bool:
        return {p.name for p in self.downloads.iterdir()} == set(OLD)

    def begin(self, title: str) -> None:
        """A clean slate for the next script: no agents, no setup, a new chat."""
        print(f"\n{'-' * 78}\n{title}\n{'-' * 78}")
        for agent in store.list_agents():
            self.engine.organizer.switch(agent, False)
            store.delete(agent)
        for _ in self.engine.new_chat():
            pass
        self.said = []

    def end(self) -> None:
        """What holds for every script: before the button, it never says the agent is on."""
        claims = [words for words in self.said if claims_done(words)]
        self.check(not claims, "it never says the agent is on or created" + (f": {claims[0][:120]}" if claims else ""))
        self.check(self.untouched(), "no file in Downloads moved")

    # ------------------------------------------------------------- scripts

    def the_users_own(self) -> None:
        self.begin("The user's own setup (9 Nov), with a worry and a question in the middle")
        self.say("hey can you create me an agent that can organize my fiels")
        self.check(self.active() and self.engine.builder.draft.conductor is not None, "the setup starts, talked through")
        self.say("ya downloads")
        self.check(self.slots().get("folder") == str(self.downloads), "it watches Downloads")
        self.say("its for school stuff, phys 122 and cse 163")
        events = self.say("put them on my desktop in a folder called College")
        slots = self.slots()
        self.check(slots.get("into") == str(self.desktop / "College"), f"the folders go in College on the real desktop: {slots.get('into')}")
        self.check(slots.get("groups", "").replace(" ", "").upper() == "PHYS122,CSE163", f"the folders are PHYS122 and CSE163: {slots.get('groups')}")
        self.say("wait will it move my old files too? i dont want that")
        self.check(self.active() and not store.list_agents(), "a worry is answered: the setup goes on, nothing is created")
        events = self.say("what about my bank statements and my cv, those have my school name on them")
        self.check(self.active() and not store.list_agents(), "a question is answered: the setup goes on, nothing is created")
        self.check(bool(SAYS_STAYS.search(self.said[-1])), "it says bank statements and CVs stay")
        self.end()
        self.say("ok sounds good")
        if not store.list_agents() and self.active() and self.engine.builder.draft.card_slots is not None:
            self.click(CARD, CREATE_IT)  # it had just asked something, so the yes answered that: the button creates
        elif not store.list_agents():
            self.check(False, "by now the card is up, so it can be created")
        made = store.list_agents()
        self.check(len(made) == 1 and made[0].slots.get("folder") == str(self.downloads)
                   and made[0].slots.get("into") == str(self.desktop / "College"), "the agent is created as agreed")
        self.check(self.untouched(), "creating it moved nothing")
        if self.engine.organizing:
            self.click(ORGANIZE_NOW, ONLY_NEW)
            time.sleep(2)
            self.engine.organizer.look()
            self.check(self.untouched(), "Only new files from now on: the old files are still there")

    def one_message(self) -> None:
        self.begin("One message that says everything")
        events = self.say(REQUEST)
        slots = self.slots()
        self.check(any(isinstance(e, AgentCard) for e in events), "the card comes with the first answer")
        self.check(slots.get("folder") == str(self.downloads), "it watches Downloads, not the destination")
        self.check(slots.get("into") == str(self.desktop / "College"), f"the folders go in College on the desktop: {slots.get('into')}")
        self.check(slots.get("groups", "").replace(" ", "").upper() == "PHYS122,CSE163", f"PHYS122 and CSE163: {slots.get('groups')}")
        self.check(slots.get("by") == org.CONTENT, "it reads what's inside")
        self.check(not store.list_agents(), "nothing is created until the button")
        self.end()
        # A change of mind at the card, said in words.
        events = self.say("actually put the College folder in my documents instead")
        self.check(self.slots().get("into") == str(self.documents / "College"), f"said at the card, the place changes: {self.slots().get('into')}")
        self.check(any(isinstance(e, AgentCard) for e in events), "and the card is shown again with it")
        self.say("ok but can you call the folder School")
        self.check(not store.list_agents(), "\"ok but...\" is a change, not a yes")
        self.check(self.slots().get("into") == str(self.documents / "School"), f"the folder is School now: {self.slots().get('into')}")

    def never_mind(self) -> None:
        self.begin("Never mind")
        self.say("can you make me an agent that sorts my files into folders")
        self.check(self.active(), "the setup starts")
        self.say("hmm actually never mind, i dont need it")
        self.check(not self.active() and not store.list_agents(), "the setup is dropped and nothing is created")
        self.end()

    def something_else(self) -> None:
        self.begin("A question about something else in the middle")
        self.say("can you make me an agent that sorts my files into folders")
        self.say("what's the capital of France?")
        self.check(not self.active(), "the setup steps aside")
        self.check("Paris" in " ".join(self.said), "and the question is answered")

    def a_folder_that_isnt_there(self) -> None:
        self.begin("A folder that doesn't exist")
        events = self.say("make me an agent that sorts the files in my Scool folder into folders by course")
        slots = self.slots()
        self.check(not any(isinstance(e, AgentCard) for e in events), "no card comes while it asks which folder")
        self.check(self.active() and "Scool" not in slots.get("folder", ""), "a folder it can't find is not taken")
        self.check("Scool" not in slots.get("into", ""), f"and it isn't made into a place nobody asked for: {slots.get('into')}")
        self.check(bool(CANT_FIND.search(self.said[-1])) and "?" in self.said[-1], "it says it can't find it, and asks")
        self.say("oops i meant downloads")
        self.check(self.slots().get("folder") == str(self.downloads), "the correction is taken")
        self.end()

    def summary_writer(self) -> None:
        self.begin("A second kind of agent: the summary writer")
        events = self.say(SECOND)
        self.check(self.active() and self.engine.builder.draft.blueprint.id == org.SUMMARIZER, "the summary writer's setup starts")
        if not any(isinstance(e, AgentCard) for e in events):
            events = self.say("the usual notes file is fine")
        card = next((e for e in events if isinstance(e, AgentCard)), None)
        self.check(card is not None and "Summaries.md" in " ".join(card.can_do), "its card says where the summaries go")
        self.check(self.slots().get("folder") == str(self.downloads), "it watches Downloads")
        self.end()
        if card is not None:
            self.click(CARD, CREATE_IT)
            self.check(any(a.blueprint == org.SUMMARIZER for a in store.list_agents()), "the button creates it")

    def in_korean(self) -> None:
        self.begin("In Korean")
        self.say("다운로드 폴더에 있는 파일들을 과목별로 정리해줘")
        if not self.active():
            self.check(False, "the request starts an organizer's setup (the router's own model decides this one)")
            return
        self.check(bool(HANGUL.search(self.said[-1])), "it answers in Korean")
        self.check(self.slots().get("folder") == str(self.downloads), "it watches Downloads")
        events = self.say("phys 122랑 cse 163 폴더로 나눠줘. 바탕화면에 College 폴더 만들어서 거기에 넣어줘")
        slots = self.slots()
        self.check(slots.get("into") == str(self.desktop / "College"), f"College on the desktop: {slots.get('into')}")
        self.check(slots.get("groups", "").replace(" ", "").upper() == "PHYS122,CSE163", f"PHYS122 and CSE163: {slots.get('groups')}")
        self.check(bool(HANGUL.search(self.said[-1])), "and it stays in Korean")
        self.end()

    def go(self) -> bool:
        if not self.start():
            return False
        for script in (self.the_users_own, self.one_message, self.never_mind, self.something_else,
                       self.a_folder_that_isnt_there, self.summary_writer, self.in_korean):
            script()
        self.engine.organizer.stop()
        self.engine.close()
        return all(self.checks)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    tags = [arg for arg in argv if not arg.startswith("--")] or [None]
    passed = True
    for tag in tags:
        root = Path(tempfile.mkdtemp(prefix="noir-conductor-eval-"))
        started = time.time()
        trial = Trial(root, tag)
        print(f"\n{'=' * 78}\n{tag or 'the conductor this computer would use'}\n{'=' * 78}")
        try:
            passed = trial.go() and passed
        finally:
            if "--keep" in argv:
                print(f"\nkept: {root}")
            else:
                shutil.rmtree(root, ignore_errors=True)
        print(f"\n{tag or 'conductor'}: {sum(trial.checks)} of {len(trial.checks)} checks passed in {time.time() - started:.0f}s")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
