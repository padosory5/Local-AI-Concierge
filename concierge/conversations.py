"""Saved conversations, so "New chat" keeps the old one in a list.

Each conversation is one JSON file in the app's data folder holding two
things: what the chat area shows (the transcript) and what Elaina's model
was told (the history), so a reopened chat carries on where it stopped.
Every exchange is saved straight away; closing the app loses nothing.
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .events import (
    AgentCard,
    ChatList,
    ChatSummary,
    ElainaDone,
    ElainaText,
    Error,
    Event,
    IdeaCard,
    Question,
    Result,
    Source,
    Transcript,
    TranscriptItem,
)

TITLE_CHARS = 42


@dataclass
class Conversation:
    id: str
    title: str
    created: str
    updated: str
    items: list[dict] = field(default_factory=list)  # TranscriptItem fields
    history: list[dict] = field(default_factory=list)  # Elaina's model messages


class ChatBook:
    """The open conversation and the saved ones.

    folder=None keeps everything in memory, for FakeEngine and tests.
    history() returns the model history to save with the conversation.
    """

    def __init__(self, folder: Path | None, history: Callable[[], list[dict]] = list):
        self.folder = folder
        self.history = history
        self.current: Conversation | None = None
        self._memory: dict[str, Conversation] = {}

    # ---------------------------------------------------------- recording

    def record(self, user_text: str, events: Iterator[Event]) -> Iterator[Event]:
        """Pass the engine's events through, writing down what was said.

        Saves once the exchange is done. A new conversation also yields a
        ChatList as soon as it exists, so the sidebar shows it straight away.
        """
        is_new = self.current is None
        self._add("user", user_text)
        if is_new and self.current is not None:
            self.save()
            yield self.chat_list()
            is_new = False
        reply: list[str] = []
        try:
            for event in events:
                if isinstance(event, ElainaText):
                    reply.append(event.text)
                elif isinstance(event, ElainaDone):
                    self._add("elaina", "".join(reply))
                    reply = []
                elif isinstance(event, Question):
                    self._add("elaina", event.text)
                elif isinstance(event, AgentCard):
                    self._add("elaina", f"Suggested agent: {event.name} ({event.kind})")
                elif isinstance(event, IdeaCard):
                    self._add("elaina", f"Idea: {event.title}. {event.verdict}")
                elif isinstance(event, Result):
                    self._add("result", event.text, event.agent, event.sources)
                elif isinstance(event, Error):
                    self._add("error", event.text)
                yield event
        finally:
            self._add("elaina", "".join(reply))  # a reply cut off part way
            self.save()
        if is_new:
            yield self.chat_list()

    def _add(self, role: str, text: str, agent: str = "", sources: list[Source] | None = None) -> None:
        text = text.strip()
        if not text:
            return
        now = _now()
        if self.current is None:
            self.current = Conversation(_new_id(), title_from(text), now, now)
        item = TranscriptItem(role, text, agent, list(sources or []))
        self.current.items.append(asdict(item))
        self.current.updated = now

    # --------------------------------------------------------- navigation

    def new(self) -> list[Event]:
        self.save()
        self.current = None
        return [Transcript(None, []), self.chat_list()]

    def open(self, id: str) -> Conversation | None:
        """Make a saved conversation the open one. None if it is gone."""
        self.save()
        conversation = self._load(id)
        if conversation:
            self.current = conversation
        return conversation

    def delete(self, id: str) -> list[Event]:
        events: list[Event] = []
        if self.current and self.current.id == id:
            self.current = None
            events.append(Transcript(None, []))
        self._memory.pop(id, None)
        if self.folder:
            (self.folder / f"{id}.json").unlink(missing_ok=True)
        return events + [self.chat_list()]

    def transcript(self) -> Transcript:
        if self.current is None:
            return Transcript(None, [])
        items = [
            TranscriptItem(i["role"], i["text"], i.get("agent", ""), [Source(**s) for s in i.get("sources", [])])
            for i in self.current.items
        ]
        return Transcript(self.current.id, items)

    def chat_list(self) -> ChatList:
        chats = sorted(self._all(), key=lambda c: c.updated, reverse=True)
        summaries = [ChatSummary(c.id, c.title, c.updated) for c in chats]
        return ChatList(summaries, self.current.id if self.current else None)

    # ------------------------------------------------------------ storage

    def save(self) -> None:
        if self.current is None:
            return
        self.current.history = list(self.history())
        self._memory[self.current.id] = self.current
        if self.folder:
            self.folder.mkdir(parents=True, exist_ok=True)
            path = self.folder / f"{self.current.id}.json"
            path.write_text(json.dumps(asdict(self.current), ensure_ascii=False, indent=1), encoding="utf-8")

    def _load(self, id: str) -> Conversation | None:
        if not re.fullmatch(r"[\w\-]+", id):
            return None  # never let an id point outside the folder
        if self.folder is None:
            return self._memory.get(id)
        try:
            data = json.loads((self.folder / f"{id}.json").read_text(encoding="utf-8"))
            return Conversation(**data)
        except (OSError, ValueError, TypeError):
            return None

    def _all(self) -> list[Conversation]:
        if self.folder is None:
            return list(self._memory.values())
        conversations = []
        for path in self.folder.glob("*.json"):
            conversation = self._load(path.stem)
            if conversation:
                conversations.append(conversation)
        return conversations


def title_from(text: str) -> str:
    title = re.sub(r"\s+", " ", text).strip()
    return title if len(title) <= TITLE_CHARS else title[: TITLE_CHARS - 3].rstrip() + "..."


def _now() -> str:
    # Milliseconds, so two chats saved in the same second still sort newest first.
    return datetime.now().isoformat(timespec="milliseconds")


def _new_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)
