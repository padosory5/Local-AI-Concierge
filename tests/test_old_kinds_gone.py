"""The kinds of helper that were written by hand are gone: the file organizer, the summary
writer, the conductor that talked their setups through and the rewording of their lines.
A helper is a card, worked out in a conversation that starts from nothing, and nothing in
the app may know one kind of helper again. This reads the app's own files, the way
test_platforms.py does, and names the few lines that still say one of those words, with
why each is there.

The last kind code knew by name was the helper that turns text into another language: it
was told by reading a rule for a word, and got questions, fixes and a routing rule of its
own. What was special about it is one setting any card that works on highlights can have
(skip_language, agents/parts.py), and the second half of this file keeps the rest gone."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The modules, blueprints, evals and tests of those kinds.
GONE = ["concierge/organizer.py", "concierge/agents/conductor.py", "concierge/agents/talk.py",
        "concierge/organizer_eval.py", "concierge/conductor_eval.py",
        "concierge/agents/blueprints/organizer.yaml", "concierge/agents/blueprints/summarizer.yaml",
        "tests/test_organizer.py", "tests/test_organizer_runs.py", "tests/test_organizer_live.py", "tests/test_conductor.py"]
OLD_WORDS = re.compile(r"organi[sz]er|summari[sz]er|summary writer|conduct|WATCHED_KINDS|ask(ing)?_kind|"
                       r"decide as you go|talk\.phrase", re.IGNORECASE)
# The lines that may still say one of them: how many in which file, and why.
STILL_SAID = {
    # Agents saved by the last version are turned into cards once (parts.migrate): the two
    # ids, a text one of their settings was saved with, and the name of their state file.
    "concierge/agents/parts.py": 3,
    # The names its three files had before, taken over once so nothing done can be lost.
    "concierge/folderwatch.py": 2,
    # A lesson about where Windows keeps the Desktop, with what first went wrong.
    "concierge/places.py": 1,
    # "Quick Summarizer" is a ready-made recipe, and a recipe is data: its name and the
    # words people ask for it by, and its line on Help me. (What the Agents page says of it
    # is in the yaml too, beside its recipe, and no longer in code.)
    "concierge/agents/starters.yaml": 2,
    "concierge/ui/web/help.js": 1,
}
READ = {".py", ".yaml", ".yml", ".json", ".js", ".html", ".css", ".txt", ".md", ".toml", ".spec", ".iss"}


def _the_apps_files() -> list[Path]:
    """Everything the app is made of and packaged with. Not the tests and not the eval's
    made-up home (what a made-up person types or keeps is theirs), not other people's code
    in web/vendor, and not CLAUDE.md, which also tells how things came to be."""
    found = [ROOT / "pyproject.toml", ROOT / "README.md", ROOT / "requirements.txt"]
    for folder in ("concierge", "packaging", ".github"):
        found += [path for path in (ROOT / folder).rglob("*")
                  if path.is_file() and path.suffix in READ and not {"vendor", "__pycache__"} & set(path.parts)]
    return [path for path in found if path.is_file() and path.name != "designer_eval.py"]


def test_the_files_of_the_old_kinds_are_gone_and_nothing_can_load_them():
    assert [name for name in GONE if (ROOT / name).exists()] == []
    for module in ("concierge.organizer", "concierge.agents.conductor", "concierge.agents.talk",
                   "concierge.organizer_eval", "concierge.conductor_eval"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module)


def test_nothing_in_the_app_names_an_old_kind_of_helper_but_the_lines_listed_here():
    said: dict[str, list[str]] = {}
    for path in _the_apps_files():
        lines = [f"{number}: {line.strip()}" for number, line in
                 enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1) if OLD_WORDS.search(line)]
        if lines:
            said[path.relative_to(ROOT).as_posix()] = lines
    counted = {name: len(lines) for name, lines in said.items()}
    assert counted == STILL_SAID, (
        "A line names a kind of helper that was written by hand, or one that did was taken out. A helper is a card "
        "now, and no code, yaml or page may know what one is for. Reword the line, or, if it only reads what the "
        "last version saved, count it in STILL_SAID with why:\n"
        + "\n".join(f"  {name}: {line}" for name, lines in sorted(said.items()) for line in lines))


# ------------------------------------------------------------------ the last kind code knew by name

# What code did for that one kind, by name. None of it may come back under any name: a
# rule is never read to find out what kind of helper it belongs to.
GONE_NAMES = ["target_language", "needs_language", "with_language", "TARGET_LANGUAGE", "LANGUAGE_CHOICES",
              "_take_target_language", "_wrong_language", "STARTER_DETAILS"]
THAT_KIND = re.compile("translat|\ubc88\uc5ed", re.IGNORECASE)
# The code that makes, changes, runs and answers for helpers, and what its models read.
# (Not here: the Spot, which has an action of that name of its own; what an answer in the
# chat is sorted by; the pages and the practice run; and the router's made-up requests.)
HELPER_FILES = ["concierge/engine.py", "concierge/folderwatch.py", "concierge/chores.py", "concierge/quick/agents.py",
                "concierge/agents/*.py", "concierge/agents/starters.yaml", "concierge/agents/capabilities.yaml",
                "concierge/agents/community.json", "concierge/agents/blueprints/*.yaml", "concierge/persona/*.txt"]
# The lines there that may still say it: how many in which file, and why.
STILL_SAYS_IT = {
    # The Spot's own button of that name is counted on Today under its own kind of job, and
    # one of the three jobs timed in the first two minutes is that job.
    "concierge/engine.py": 2,
    # A lesson: what a model once made of a request for such a helper.
    "concierge/agents/builder.py": 1,
    # Cards saved before the setting existed are given it once (migrate, _old_skip), and the
    # first kind of helper there ever was is turned into a card: the one place that reads a
    # rule for it. Two of the seven lines only name the module that tells languages apart.
    "concierge/agents/parts.py": 7,
    # Its module's first lines give a request as an example of what people ask for.
    "concierge/agents/planner.py": 1,
    # Worked examples for the built-in model, of requests and of the rules written from them.
    "concierge/agents/recipe.py": 6,
    # The router's note for the built-in model: a one-off job for the chat, and a request for a helper.
    "concierge/agents/router.py": 2,
    # The module that tells languages apart is called that; a note is written in the rule's language.
    "concierge/agents/worker.py": 2,
    # One of the jobs the built-in model can do, among the building blocks the idea planner
    # reads: no code treats it differently from rewriting or summing up.
    "concierge/agents/capabilities.yaml": 2,
    "concierge/agents/blueprints/custom.yaml": 1,
    # Two shared recipes. A recipe is data, and each says in its own settings what it leaves out.
    "concierge/agents/community.json": 2,
}


def _helper_files() -> list[Path]:
    found = [path for pattern in HELPER_FILES for path in sorted(ROOT.glob(pattern))]
    assert all(any(ROOT.glob(pattern)) for pattern in HELPER_FILES)  # a file that moved is not a file that is clean
    return found


def test_what_code_did_for_one_kind_of_helper_is_gone_by_every_name():
    from concierge import engine
    from concierge.agents import builder, community, recipe, router

    for module, names in ((recipe, GONE_NAMES[:3]), (builder, GONE_NAMES[3:5]), (router, ["_wrong_language"]),
                          (community, ["STARTER_DETAILS"]), (engine, ["needs_language", "target_language", "with_language"])):
        for name in names:
            assert not hasattr(module, name), f"{module.__name__}.{name}"
    assert not hasattr(builder.AgentBuilder, "_take_target_language")
    for path in _the_apps_files():
        source = path.read_text(encoding="utf-8", errors="replace")
        assert not [name for name in GONE_NAMES if name in source], path.relative_to(ROOT).as_posix()


def test_nothing_that_makes_or_runs_a_helper_knows_that_kind_but_the_lines_listed_here():
    said: dict[str, list[str]] = {}
    for path in _helper_files():
        lines = [f"{number}: {line.strip()}" for number, line in
                 enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1) if THAT_KIND.search(line)]
        if lines:
            said[path.relative_to(ROOT).as_posix()] = lines
    counted = {name: len(lines) for name, lines in said.items()}
    assert counted == STILL_SAYS_IT, (
        "A line names the one kind of helper code used to know, or one that did was taken out. No code may tell "
        "what kind a helper is by its rule or its name: what was special about that kind is a setting of the card. "
        "Reword the line, or count it in STILL_SAYS_IT with why:\n"
        + "\n".join(f"  {name}: {line}" for name, lines in sorted(said.items()) for line in lines))
    # The code that runs a card on a highlight, the conversation in which one is worked out
    # and what Noir's own model is told about itself say nothing of it at all.
    for clean in ("concierge/quick/agents.py", "concierge/agents/designer.py", "concierge/agents/community.py",
                  "concierge/agents/starters.py", "concierge/persona/noir_en.txt"):
        assert clean not in counted, clean


def test_a_rule_is_read_for_a_language_in_one_place_only():
    """Which language a card leaves out is the card's own setting. The only code that works
    it out from a rule is the part that gives the setting, once, to cards saved before it
    existed; everything that runs a card goes by the setting."""
    from concierge.agents import parts
    from concierge.agents.store import Agent
    from concierge.quick import agents as quick

    readers = []
    for path in _the_apps_files():
        if path.suffix == ".py" and "language_in(" in path.read_text(encoding="utf-8", errors="replace"):
            readers.append(path.relative_to(ROOT).as_posix())
    # parts: _old_skip. worker: the language a note is written in, which the rule may name.
    # translate: where it is defined.
    assert sorted(readers) == ["concierge/agents/parts.py", "concierge/agents/worker.py", "concierge/quick/translate.py"]
    source = (ROOT / "concierge/quick/agents.py").read_text(encoding="utf-8")
    assert "leaves_out(agent.slots, text)" in source and "looks_like" not in source and "language_in" not in source
    # Whatever the rule says: with no language set nothing is left out, and with one set that text is.
    says_so = Agent("One", "custom", {"when": parts.WHILE_ON, "instruction": "Translate the text into Korean."})
    set_so = Agent("Other", "custom", {"when": parts.WHILE_ON, "instruction": "Count the words.", "skip_language": "Korean"})
    korean = "\uc548\ub155\ud558\uc138\uc694"
    assert parts.leaves_out(says_so.slots, korean) == "" and parts.leaves_out(set_so.slots, korean) == "Korean"
    assert {quick.ANSWERED, quick.LEFT_OUT, quick.NO_MODEL, quick.NOTHING_BACK} == {"answered", "left out", "no model",
                                                                                 "nothing back"}
