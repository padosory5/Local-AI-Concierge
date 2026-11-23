"""Decide what a message is: chat with Noir, a request to make a helper, a job
for an agent the user already has, or a change to one.

The router only finds out that a helper is wanted. What the helper is, is
worked out afterwards: in a conversation (designer.py), or, on a computer where
no model can hold one, by the plain questions and the idea planner (builder.py,
planner.py).

The model answers in a forced JSON format whose fields only allow the
blueprints and agents that really exist, so it cannot invent either. Code
handles the clear cases first and checks the model's answer after.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..ollama import Ollama
from . import parts
from .blueprint import Blueprint
from .store import Agent

IDEA_OPTION = "idea: another kind of helper"

# "make the result stay until I unhighlight", "change it to answer more briefly"
WANTS_CHANGE = re.compile(
    r"\b(change|edit|update|rename|make (it|the|my|that)|keep|stay|stays|instead|should|set it|"
    r"switch it to|use the|turn it into|longer|shorter|disappear\w*|vanish\w*|"
    r"fix (the|my|this|that) (agent|helper)|i want (it|her|the agent|my \w+) to)\b|바꿔|변경|수정|유지",
    re.IGNORECASE,
)

# "make me an agent", "set up another helper": always a new agent, never an
# existing one, even when an existing agent reads similar files.
WANTS_NEW = re.compile(
    r"\b(make|create|set ?up|build|add|start)\b.{0,30}\b(agent|helper|assistant)s?\b"
    r"|\b(new|another)\s+(agent|helper)\b|에이전트\s*(만들|생성)",
    re.IGNORECASE,
)

# Standing work on the new files of a folder, asked for plainly: something should happen
# each time one lands. That is a helper to make, whatever it is to do with them, and it is
# decided in code: asked, the model took such a request for chat and offered a web search.
# It says nothing of what the helper is for, which the conversation finds out. A file
# only being new is not enough ("how do I make a new document?").
WATCHES = re.compile(r"\b(when(ever)?|every time|each time|as soon as|once)\b.{0,40}\b(lands?|arrives?|comes? in|appears?|"
                     r"shows? up|is (saved|downloaded|added)|download(s|ed)?)\b|"
                     r"\b(every|each|any) new (file|document|pdf|download|picture|photo)\b|"
                     r"\bas (i|we|they|it|files) (land|arrive|come|download|save)\b", re.IGNORECASE)
# A question about how things are is no request for standing work, even with those words
# in it ("what happens when a file lands in Downloads?").
ASKS_HOW_IT_IS = re.compile(r"^\s*(what|why|how|where|which|who|does|do|did|is|are|was|were)\b", re.IGNORECASE)
# That the message asks for something to be done, in whatever words: "can you", "I want",
# "write me", "put it in", or a sentence that begins by saying what to do with their
# things ("tidy my downloads"). What is asked for is none of the router's business. Without
# it, a sentence with the words above is as likely a story about a problem ("when I
# download the file it shows an error"), and that is left to the model.
ASKS_TO = re.compile(
    r"\b(can|could|would|will) you\b|\bplease\b|\bi(?:'d| would)? (want|need|like)\b|\b(automatically|from now on|for me)\b|"
    r"\b(write|tell|show|send|give|remind|notify|warn|let|make|get|read) me\b|"
    r"\b[a-z]+ (it|them) (in|into|to|under|by|as|up|away|where|somewhere)\b|"
    r"^\s*(?!(?:when(?:ever)?|once|as|every|each|if|why|what|how|where|which|who|is|are|was|were|do|does|did|the|my|a|an|"
    r"i|it|this|that|there)\b)[a-z]+ (my|the|every|each|all|any|new)\b",
    re.IGNORECASE)


@dataclass(frozen=True)
class Route:
    # "chat", "run_agent", "change_agent", or a helper to make: "new_agent" (the words of
    # one blueprint fit it) or "idea" (any other)
    kind: str
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
    if WATCHES.search(text) and (WANTS_NEW.search(text) or (ASKS_TO.search(text) and not ASKS_HOW_IT_IS.match(text))):
        return Route("idea", request=text)

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
    picked = options.get(answer.get("choice"), Route("chat"))
    if picked.kind == "run_agent" and _works_on_text(picked.agent, agents):
        # A helper that works on a piece of text is run from the chat by its name only
        # (decided above, in code, where its name is taken off the text first). Picked by
        # the model for a message that does not name it, it was handed the whole message:
        # its rule was applied to the request and not to the text in it, and a helper
        # that turns text into one language was picked for a request to turn some into
        # another. Such a message is a one-off job on text, which the chat does.
        return Route("chat")
    return picked


def _works_on_text(name: str | None, agents: list[Agent]) -> bool:
    """Whether the agent of this name is a card that does its rule's job on a piece of
    text: one for highlights, or one asked in the chat. Not one that answers from a
    folder's documents, nor one that works on a folder's new files."""
    agent = next((a for a in agents if a.name == name), None)
    return agent is not None and agent.blueprint == parts.CUSTOM and not parts.watches(agent)


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
    """A change to the agent itself, not a job for it: "Word explainer: keep
    calm" is a job (its name and a colon), "make the Word explainer stay
    longer" is a change."""
    if re.match(rf"\s*{re.escape(agent.name)}\s*:", text, re.IGNORECASE):
        return False
    return bool(WANTS_CHANGE.search(text)) and not WANTS_NEW.search(text)


def refers_to(text: str, agents: list[Agent], blueprints: dict[str, Blueprint] | None = None) -> Agent | None:
    """The agent a message is about: named, or the only one whose own words the
    message uses: the words of its name and of what it does ("the explanation"
    for "Explain this word in simple words"). An agent that works on the files of
    a folder is known by its name alone: its rule is whole sentences about
    files, and shares a word with almost anything said about one."""
    named = names_an_agent(text, agents)
    if named:
        return named
    said = _stems(text)
    matches = [a for a in agents
               if _stems(a.name + ("" if parts.watches(a) else " " + str(a.slots.get("instruction") or ""))) & said]
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
