"""Score the router on router_cases.yaml with the real model.

    python -m concierge.agents.eval_router

Run it after changing the router prompt, a blueprint's `when` or `examples`,
or Noir's model. Small models fail quietly, so this number is how we know.

Two numbers. The first counts a case as right only when the route is the one
written down. The second only asks whether the router saw that a helper is
wanted ("new_agent" or "idea") or not: with a model that can work a helper out
by talking, both go to that conversation, so there it is the number that matters.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from ..noir import NOIR_MODEL
from ..ollama import Ollama
from .blueprint import load_blueprints
from .router import route
from .store import Agent

CASES = Path(__file__).with_name("router_cases.yaml")
MAKES = ("new_agent", "idea")  # the routes that mean a helper is to be made


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    data = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    agents = [Agent(**a) for a in data["agents"]]
    blueprints = load_blueprints()
    ollama = Ollama()
    ollama.ensure_running()
    think = False if "thinking" in ollama.capabilities(NOIR_MODEL) else None

    passed = wanted = 0
    for case in data["cases"]:
        got = route(ollama, NOIR_MODEL, case["text"], blueprints, agents, think=think)
        ok = got.kind == case["kind"]
        wanted += (got.kind in MAKES) == (case["kind"] in MAKES)
        if ok and case["kind"] == "new_agent":
            ok = got.blueprint == case.get("blueprint")
        if ok and case["kind"] in ("run_agent", "change_agent"):
            ok = got.agent == case.get("agent")
        passed += ok
        if not ok:
            print(f"MISS  {case['text']!r}\n      wanted {case['kind']}, got {got.kind} "
                  f"(blueprint={got.blueprint}, agent={got.agent})")
    total = len(data["cases"])
    print(f"\nRouter: {passed}/{total} correct ({passed / total:.0%})")
    print(f"Counting only whether a helper is wanted or not: {wanted}/{total}")
    ollama.unload(NOIR_MODEL)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
