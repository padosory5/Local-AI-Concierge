"""A scripted engine for building the UI before the real agent pipeline exists.

It follows the same Engine contract as the real one (see events.py) and
produces every event type, so each part of the UI can be built and clicked
through. No Ollama or model is needed.

What to type to see each flow:
    anything               Elaina streams a chat reply
    "make an agent"        agent setup: Question (typed answer), Question
    (or mention documents,   with buttons, AgentCard, Progress, Result
    files or a folder)
    "ask ..."              run the existing agent: Progress, Result with sources
    "error"                an Error event
"""

from __future__ import annotations

import time
from collections.abc import Iterator

from .events import (
    AgentCard,
    AgentList,
    ElainaDone,
    ElainaText,
    Error,
    Event,
    Progress,
    Question,
    Result,
    Source,
    SystemInfo,
)


class FakeEngine:
    def __init__(self, delay: float = 0.03):
        # Seconds between streamed pieces and progress steps; 0 for tests.
        self.delay = delay
        self.agents = ["Contracts helper"]
        self.draft: dict = {}
        self.waiting_for: str | None = None  # which typed answer we expect next

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
        yield AgentList(list(self.agents))

    def send(self, text: str) -> Iterator[Event]:
        lowered = text.lower()
        if self.waiting_for == "folder":
            self.waiting_for = None
            self.draft["folder"] = text.strip()
            yield from self._say("Got it. Should it read every file there, or only some kinds?")
            yield Question("file_types", "Which files should it read?", ["PDF only", "Word only", "Everything"])
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
            yield from self._say(
                "This is the fake engine talking. Real replies stream in like this, "
                "a few words at a time, until the reply is done."
            )

    def choose(self, id: str, choice: str) -> Iterator[Event]:
        if id == "file_types":
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

    def reset(self) -> None:
        self.draft = {}
        self.waiting_for = None

    def close(self) -> None:
        pass

    # ----------------------------------------------------------- scripts

    def _say(self, text: str) -> Iterator[Event]:
        for word in text.split(" "):
            time.sleep(self.delay)
            yield ElainaText(word + " ")
        yield ElainaDone()

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
            runs_on="Qwen 3.5 4B (Elaina's model, no extra memory)",
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
        yield AgentList(list(self.agents))

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
