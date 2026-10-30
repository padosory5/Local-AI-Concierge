"""Decide what a message is: chat with Elaina, a request for a new agent, a
job for an agent the user already has, or an idea for another kind of helper
(which the idea planner talks through, see planner.py).

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

IDEA_OPTION = "idea: another kind of helper"

# "make the translation stay until I unhighlight", "change it to Japanese"
WANTS_CHANGE = re.compile(
    r"\b(change|edit|update|rename|make (it|the|my|that)|keep|stay|stays|instead|should|set it|"
    r"switch it to|use the|turn it into|longer|shorter|disappear\w*|vanish\w*|"
    r"fix (the|my|this|that) (agent|translator|helper)|i want (it|her|the agent|my \w+) to)\b|바꿔|변경|수정|유지",
    re.IGNORECASE,
)

# "make me an agent", "set up another helper": always a new agent, never an
# existing one, even when an existing agent reads similar files.
WANTS_NEW = re.compile(
    r"\b(make|create|set ?up|build|add|start)\b.{0,30}\b(agent|helper|assistant)s?\b"
    r"|\b(new|another)\s+(agent|helper)\b|에이전트\s*(만들|생성)",
    re.IGNORECASE,
)



@dataclass(frozen=True)
class Route:
    kind: str  # "chat", "new_agent", "run_agent", "change_agent" or "idea"
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
    named = None if WANTS_NEW.search(text) else names_an_agent(text, agents)
    if named and wants_change(text, named):
        return Route("change_agent", agent=named.name, request=text)
    if named:
        return Route("run_agent", agent=named.name, request=_strip_agent_name(text, named.name))

    # One choice, not separate kind/blueprint/agent fields: a small model
    # would sometimes say "new agent" and then pick no blueprint.
    options = {"chat": Route("chat")}
    for b in blueprints.values():
        if not b.generic:  # the shared template for agents made from parts is no kind of agent
            options[f"new agent: {b.name}"] = Route("new_agent", blueprint=b.id, request=text)
    options[IDEA_OPTION] = Route("idea", request=text)
    if not WANTS_NEW.search(text):
        for a in agents:
            options[f"use agent: {a.name}"] = Route("run_agent", agent=a.name, request=text)
            options[f"change agent: {a.name}"] = Route("change_agent", agent=a.name, request=text)

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
    chosen = options.get(answer.get("choice"), Route("chat"))
    if chosen.kind == "run_agent" and _wrong_language(text, chosen.agent, agents):
        return Route("chat")  # "into Japanese" is never a job for the Korean translator
    return chosen


def _wrong_language(text: str, name: str, agents: list[Agent]) -> bool:
    """A translating agent asked to translate into a different language."""
    from ..quick.translate import language_in
    from .recipe import target_language

    agent = next((a for a in agents if a.name == name), None)
    target = target_language(agent.slots.get("instruction", "")) if agent else None
    asked = language_in(text, target_only=True)
    return bool(target and asked and asked != target)


def _prompt(blueprints: dict[str, Blueprint], agents: list[Agent], evidence: dict[str, list[str]]) -> str:
    lines = ['- "chat": talk with the assistant. Greetings, general knowledge, advice, '
             "questions about this computer, and small one-off tasks on text the user typed "
             "(rewrite, translate, write a poem). Also anything no other option fits."]
    for b in (b for b in blueprints.values() if not b.generic):
        examples = "; ".join(f'"{e}"' for e in b.examples)
        lines.append(f'- "new agent: {b.name}": create a helper for this job. {b.when.strip()} '
                     f"For example: {examples}")
    lines.append(f'- "{IDEA_OPTION}": the user wants a helper, agent, shortcut or automation for any '
                 "other job, or asks whether you could make one. Not for finding things in or asking about "
                 "their own files: that is the documents helper. For example: translate what I "
                 "highlight when I press a key; copy every screenshot; sort my Downloads folder; "
                 "turn my recordings into notes; remind me to stretch every hour; an agent that "
                 "books flights; fix the grammar of what I write.")
    for a in agents:
        reads = f" It reads {a.slots['folder']}." if a.slots.get("folder") else ""
        if a.slots.get("instruction"):
            reads += f" What it does: {a.slots['instruction']}"
        if a.contents:
            more = f" and {len(a.contents) - 12} more" if len(a.contents) > 12 else ""
            reads += f" Files: {', '.join(a.contents[:12])}{more}."
        words = evidence.get(a.name)
        if words:
            reads += f" Its files contain these words from the message: {', '.join(words)}."
        kind = blueprints[a.blueprint].name if a.blueprint in blueprints else a.blueprint
        lines.append(f'- "use agent: {a.name}": the user\'s existing "{kind}" helper.{reads} '
                     "Choose it when the message asks that helper to do its job.")
        lines.append(f'- "change agent: {a.name}": the user wants {a.name} itself to work or look '
                     "differently: its settings, how it shows results, how long they stay, its "
                     "language, its name.")
    options = "\n".join(lines)
    return f"""You choose how an assistant app handles the user's message. Pick exactly one option.

{options}

Rules:
- When the user mentions their own files, folder, notes, documents, PDFs, slides, papers or manuals and wants them searched, read or asked about, it is never "chat". Use the existing helper that covers them, otherwise create a new one.
- Asking whether the assistant can do such a job ("can you search my notes?") counts as wanting it.
- Finding things in or asking about the user's own files is always the documents helper (an existing one, or a new one), never "{IDEA_OPTION}".
- Asking for a one-off thing right now (rewrite this sentence, book me a flight) is "chat". Asking for a helper or agent that would do it is "{IDEA_OPTION}"."""


def _loose(text: str) -> str:
    """Lowercase with _ and - as spaces, so "sample docs helper" matches "Sample_docs helper"."""
    return re.sub(r"[\s_\-]+", " ", text.lower())


def wants_change(text: str, agent: Agent) -> bool:
    """A change to the agent itself, not a job for it: "Korean translator: keep
    calm" is a job (its name and a colon), "make the Korean translator stay
    longer" is a change."""
    if re.match(rf"\s*{re.escape(agent.name)}\s*:", text, re.IGNORECASE):
        return False
    return bool(WANTS_CHANGE.search(text)) and not WANTS_NEW.search(text)


def refers_to(text: str, agents: list[Agent], blueprints: dict[str, Blueprint]) -> Agent | None:
    """The agent a message is about: named, or the only one of a kind the
    message mentions ("the translation", "the bubble" when there is one
    highlight translator)."""
    named = names_an_agent(text, agents)
    if named:
        return named
    lowered = text.lower()
    for blueprint in blueprints.values():
        if any(word in lowered for word in blueprint.words):
            of_kind = [a for a in agents if a.blueprint == blueprint.id]
            if len(of_kind) == 1:
                return of_kind[0]
    # Agents made from parts have no kind words: use the words of their name
    # and of what they do ("the translation" for "Translate the text into Korean").
    matches = [a for a in agents if _stems(a.name + " " + a.slots.get("instruction", "")) & _stems(text)]
    return matches[0] if len(matches) == 1 else None


def _stems(text: str) -> set[str]:
    """The first five letters of each longer word: "explain", "explainer" and
    "explanation" all become "expla"."""
    common = {"the", "text", "this", "that", "with", "into", "your", "what", "when", "agent", "helper"}
    words = re.findall(r"[a-z]{5,}|[가-힣]{2,}", text.lower())
    return {w[:5] for w in words if w not in common}


def names_an_agent(text: str, agents: list[Agent]) -> Agent | None:
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
