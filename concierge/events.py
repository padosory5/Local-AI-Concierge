"""The contract between the chat engine and any UI.

The engine never prints and the UI never decides anything. The UI sends the
user's text (or a button click) to an Engine, gets back a stream of events,
and draws them. Everything Elaina does, from chatting to creating and running
agents, arrives as one of the events below.

Change this file only when both sides agree: the UI and the engine are built
by different people against it.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from typing import Protocol, Union

# ------------------------------------------------------------------ events


@dataclass(frozen=True)
class SystemInfo:
    """What the computer has and which model Elaina runs on. Sent first by
    startup(), for a header or an "about this computer" panel."""

    hardware: list[str]  # plain-language lines, e.g. "Memory: 31.1 GB"
    recommended: str | None  # e.g. "Qwen 3.5 4B (qwen3.5:4b)"; None if nothing fits
    in_use: str  # the model Elaina is actually built from
    device: str  # e.g. "NVIDIA GeForce RTX 5080" or the CPU name
    note: str = ""  # e.g. why in_use differs from recommended


@dataclass(frozen=True)
class ElainaText:
    """A piece of Elaina's reply. Append it to her current message bubble;
    replies stream in many small pieces."""

    text: str


@dataclass(frozen=True)
class ElainaDone:
    """Elaina's current reply is complete."""


@dataclass(frozen=True)
class Question:
    """Elaina needs an answer to continue, e.g. while setting up an agent.

    With choices, show them as buttons and send the picked one with
    engine.choose(id, choice). The user may also just type an answer, which
    goes through engine.send() as usual.
    """

    id: str
    text: str
    choices: list[str] | None = None


@dataclass(frozen=True)
class AgentCard:
    """A proposed agent, shown as a card the user accepts, changes or cancels.

    Every line is filled in by code from the agent's form, not written by the
    model, so the UI can show it as is. Send the clicked action with
    engine.choose(id, action).
    """

    id: str
    name: str
    kind: str  # the blueprint, e.g. "Ask my documents"
    reads: list[str]  # folders or files it may read
    can_do: list[str]
    cannot_do: list[str]
    runs_on: str  # e.g. "Qwen 3.5 4B (Elaina's model, no extra memory)"
    actions: list[str] = field(default_factory=lambda: ["Create it", "Change something", "Cancel"])


@dataclass(frozen=True)
class Progress:
    """Something is working, e.g. "Reading 23 files...". Replace the previous
    Progress line; clear it when any other event arrives."""

    text: str


@dataclass(frozen=True)
class Source:
    path: str
    quote: str = ""


@dataclass(frozen=True)
class Result:
    """An agent finished a job. Show its text and, if any, where it came from."""

    agent: str
    text: str
    sources: list[Source] = field(default_factory=list)


@dataclass(frozen=True)
class AgentList:
    """The user's agents, for a sidebar or menu. Sent by startup() and again
    whenever an agent is created or deleted."""

    agents: list[str]


@dataclass(frozen=True)
class Error:
    """Something went wrong. text is written for the user, not a stack trace."""

    text: str


Event = Union[
    SystemInfo, ElainaText, ElainaDone, Question, AgentCard, Progress, Result, AgentList, Error
]


def to_dict(event: Event) -> dict:
    """The event as plain JSON-ready data with a "type" field, for a UI that
    is not written in Python (web, Electron, Tauri) and talks over a socket."""
    return {"type": type(event).__name__, **asdict(event)}


# ------------------------------------------------------------------ engine


class Engine(Protocol):
    """What every engine offers the UI. FakeEngine (concierge/fake_engine.py)
    and the real one (concierge/engine.py) both follow it, so the UI can be
    built against the fake and switched to the real one with one line."""

    def startup(self) -> Iterator[Event]:
        """Call once when the UI opens. Yields SystemInfo, then AgentList."""
        ...

    def send(self, text: str) -> Iterator[Event]:
        """The user typed a message."""
        ...

    def choose(self, id: str, choice: str) -> Iterator[Event]:
        """The user clicked a choice on a Question or an action on an AgentCard."""
        ...

    def reset(self) -> None:
        """Start a new conversation."""
        ...

    def close(self) -> None:
        """The UI is closing. Frees Elaina's graphics memory."""
        ...
