"""Decide what a message is: chat with Elaina, a request for a new agent, or a
job for an agent the user already has.

The model answers in a forced JSON format whose fields only allow the
blueprints and agents that really exist, so it cannot invent either. Code
handles the clear cases first and checks the model's answer after.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..ollama import Ollama
from .blueprint import Blueprint
from .store import Agent

# "make me an agent", "set up another helper": always a new agent, never an
# existing one, even when an existing agent reads similar files.
WANTS_NEW = re.compile(
    r"\b(make|create|set ?up|build|add|start)\b.{0,30}\b(agent|helper|assistant)s?\b"
    r"|\b(new|another)\s+(agent|helper)\b|에이전트\s*(만들|생성)",
    re.IGNORECASE,
)



@dataclass(frozen=True)
class Route:
    kind: str  # "chat", "new_agent" or "run_agent"
    blueprint: str | None = None
    agent: str | None = None
    request: str = ""  # what to hand the agent: the message without "ask my X agent"


def route(
    ollama: Ollama,
    model: str,
    text: str,
    blueprints: dict[str, Blueprint],
    agents: list[Agent],
    think: bool | None = None,
    evidence: dict[str, list[str]] | None = None,
) -> Route:
    """evidence: for each agent name, words of the message found in its files."""
    named = _names_an_agent(text, agents)
    if named:
        return Route("run_agent", agent=named.name, request=_strip_agent_name(text, named.name))

    # One choice, not separate kind/blueprint/agent fields: a small model
    # would sometimes say "new agent" and then pick no blueprint.
    options = {"chat": Route("chat")}
    for b in blueprints.values():
        options[f"new agent: {b.name}"] = Route("new_agent", blueprint=b.id, request=text)
    if not WANTS_NEW.search(text):
        for a in agents:
            options[f"use agent: {a.name}"] = Route("run_agent", agent=a.name, request=text)

    schema = {
        "type": "object",
        "properties": {"choice": {"enum": list(options)}},
        "required": ["choice"],
    }
    messages = [
        {"role": "system", "content": _prompt(blueprints, agents, evidence or {})},
        {"role": "user", "content": text},
    ]
    answer = ollama.chat_json(model, messages, schema, think=think)
    return options.get(answer.get("choice"), Route("chat"))


def _prompt(blueprints: dict[str, Blueprint], agents: list[Agent], evidence: dict[str, list[str]]) -> str:
    lines = ['- "chat": talk with the assistant. Greetings, general knowledge, advice, '
             "questions about this computer, and small one-off tasks on text the user typed "
             "(rewrite, translate, write a poem). Also anything no other option fits."]
    for b in blueprints.values():
        examples = "; ".join(f'"{e}"' for e in b.examples)
        lines.append(f'- "new agent: {b.name}": create a helper for this job. {b.when.strip()} '
                     f"For example: {examples}")
    for a in agents:
        reads = f" It reads {a.slots['folder']}." if a.slots.get("folder") else ""
        if a.contents:
            more = f" and {len(a.contents) - 12} more" if len(a.contents) > 12 else ""
            reads += f" Files: {', '.join(a.contents[:12])}{more}."
        words = evidence.get(a.name)
        if words:
            reads += f" Its files contain these words from the message: {', '.join(words)}."
        kind = blueprints[a.blueprint].name if a.blueprint in blueprints else a.blueprint
        lines.append(f'- "use agent: {a.name}": the user\'s existing "{kind}" helper.{reads} '
                     "Choose it when the message is about what that helper covers.")
    options = "\n".join(lines)
    return f"""You choose how an assistant app handles the user's message. Pick exactly one option.

{options}

Rules:
- When the user mentions their own files, folder, notes, documents, PDFs, slides, papers or manuals and wants them searched, read or asked about, it is never "chat". Use the existing helper that covers them, otherwise create a new one.
- Asking whether the assistant can do such a job ("can you search my notes?") counts as wanting it.
- Things no option can do (booking, buying, browsing the web) are "chat"."""


def _loose(text: str) -> str:
    """Lowercase with _ and - as spaces, so "sample docs helper" matches "Sample_docs helper"."""
    return re.sub(r"[\s_\-]+", " ", text.lower())


def _names_an_agent(text: str, agents: list[Agent]) -> Agent | None:
    lowered = _loose(text)
    for agent in sorted(agents, key=lambda a: -len(a.name)):
        if _loose(agent.name) in lowered:
            return agent
    return None


def _strip_agent_name(text: str, name: str) -> str:
    """ "Ask Contracts helper: who signed?" -> "who signed?" """
    loose_name = r"[\s_\-]+".join(re.escape(word) for word in re.split(r"[\s_\-]+", name))
    pattern = rf"^\s*(?:hey\s+|please\s+)?(?:ask\s+)?(?:my\s+|the\s+)?{loose_name}(?:\s+agent)?\s*[,:\-]?\s*"
    stripped = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
    return stripped or text
