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
class Thinking:
    """Elaina working something out. Show it faded ("foggy") in the chat, and
    fold it away into one line ("Thought for 12s") as soon as any other event
    arrives; the user can click to open it again.

    kind "step": one of her real decisions, a short line of its own, such as
    "This asks for a new agent: Highlight translator".
    kind "thought": a piece of her model's own thinking, streamed like
    ElainaText; sent only when the user asked her to think it through.
    """

    text: str
    kind: str = "step"


@dataclass(frozen=True)
class ElainaText:
    """A piece of Elaina's reply. Append it to her current message bubble;
    replies stream in many small pieces."""

    text: str


@dataclass(frozen=True)
class ElainaDone:
    """Elaina's current reply is complete.

    With Auto picked in the model menu (auto.py), `by` names the model that wrote
    this reply; show it under the reply instead of the menu's name. `instead` is
    set when Auto kept the reply on this computer: the plan or key model the user
    can ask instead, as a button under the reply calling engine.ask_again().
    Both are empty otherwise.

    For every chat answer, `where` is "here" (written on this computer) or "cloud"
    (a plan or key), for the coloured dot under it; empty for her set phrases.
    `saved`: about how many plan or key tokens an answer written here kept (Auto
    only, 0 otherwise). `plan_used`: how full the plan's fullest window was right
    after a cloud answer (0 to 1), or -1 when there's no plan to measure (a key).
    """

    by: str = ""
    instead: str = ""
    where: str = ""
    saved: int = 0
    plan_used: float = -1.0


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
    whenever an agent is created, deleted, or switched on or off.

    Agents in `switchable` work outside the chat while switched on (such as a
    highlight translator): show them with an on/off switch that calls
    toggle_agent(name). `active` lists the ones switched on right now.
    """

    agents: list[str]
    switchable: list[str] = field(default_factory=list)
    active: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Error:
    """Something went wrong. text is written for the user, not a stack trace."""

    text: str


@dataclass(frozen=True)
class IdeaStep:
    text: str  # e.g. "Translate text (into Korean)"
    status: str  # "ready", "not_built", "not_possible" or "unclear"
    note: str = ""  # shown small, e.g. "Moving files will always show a preview first"


@dataclass(frozen=True)
class IdeaCard:
    """Elaina's honest answer to "could you make a helper that...?".

    Show the title, each step with its status, the difficulty line (does it
    need a bigger model, does that fit this computer) and the verdict, with
    `actions` as buttons calling choose(id, action). Everything on it is
    written by code, not the model. `level` is the overall answer, for a
    colour or icon: "ready", "not_built", "too_big", "not_possible", "unclear".
    """

    id: str
    title: str
    steps: list[IdeaStep]
    difficulty: str
    verdict: str
    level: str
    actions: list[str]


@dataclass(frozen=True)
class ChatSummary:
    id: str
    title: str  # from the first message, e.g. "who signed the Acme contract?"
    updated: str  # ISO date and time of the last message


@dataclass(frozen=True)
class ChatList:
    """Saved conversations, newest first, for the sidebar. Sent by startup()
    and whenever a conversation is created, opened, started or deleted."""

    chats: list[ChatSummary]
    current: str | None  # the open conversation; None for a new one with no messages yet


@dataclass(frozen=True)
class TranscriptItem:
    role: str  # "user", "elaina", "result" (an agent's answer) or "error"
    text: str
    agent: str = ""  # for "result": which agent answered
    sources: list[Source] = field(default_factory=list)
    # For an "elaina" answer, what its ElainaDone said, so a reopened chat shows the
    # same dot and saved tokens: who wrote it, "here" or "cloud", tokens saved, plan used.
    by: str = ""
    where: str = ""
    saved: int = 0
    plan_used: float = -1.0


@dataclass(frozen=True)
class Transcript:
    """Replace everything in the chat area with these messages: after opening
    a saved conversation, or empty after starting a new one. Old questions
    and cards come back as plain messages without buttons."""

    id: str | None
    items: list[TranscriptItem]


Event = Union[
    Thinking, SystemInfo, ElainaText, ElainaDone, Question, AgentCard, Progress, Result, AgentList, Error,
    ChatList, Transcript, IdeaCard,
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
        """Call once when the UI opens. Yields SystemInfo, AgentList, then ChatList."""
        ...

    def send(self, text: str, think: bool = False) -> Iterator[Event]:
        """The user typed a message. The first message of a new conversation
        also yields a ChatList, since the conversation now has a place in it.

        think: the user asked Elaina to think it through (the Think button).
        Her own replies then come after streamed Thinking thoughts, which
        takes much longer (about 20 seconds on a 4B model)."""
        ...

    def choose(self, id: str, choice: str) -> Iterator[Event]:
        """The user clicked a choice on a Question or an action on an AgentCard."""
        ...

    def new_chat(self) -> Iterator[Event]:
        """Keep the current conversation in the list and start an empty one.
        Yields an empty Transcript, then ChatList."""
        ...

    def open_chat(self, id: str) -> Iterator[Event]:
        """Reopen a saved conversation. Yields its Transcript, then ChatList."""
        ...

    def delete_chat(self, id: str) -> Iterator[Event]:
        """Delete a saved conversation (the UI confirms first). Yields ChatList,
        and an empty Transcript first if it was the open one."""
        ...

    def delete_agent(self, name: str) -> Iterator[Event]:
        """The user wants an agent removed. Elaina asks to confirm with a
        Question; answering it through choose() deletes it and yields AgentList."""
        ...

    def toggle_agent(self, name: str) -> Iterator[Event]:
        """Switch a switchable agent on or off. Elaina says what changed, then
        AgentList with the new `active` list."""
        ...

    def reset(self) -> None:
        """Start a new conversation without drawing anything (terminal /reset).
        The current one is kept in the list, like new_chat()."""
        ...

    def close(self) -> None:
        """The UI is closing. Frees Elaina's graphics memory."""
        ...
