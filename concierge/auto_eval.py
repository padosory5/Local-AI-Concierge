"""Auto's accuracy with the real model on this computer:

    python -m concierge.auto_eval [model]

First every question in auto_cases.yaml the way the app decides it (code first, the
model only for unclear ones); that must stay at 100%. Then the same questions sorted
by the model alone, for comparison: it shows how much a small model would get wrong
if it judged by itself, which is why code goes first.
"""

from __future__ import annotations

import sys
import time

from . import auto, noir
from .ollama import Ollama

SMALL_MODEL = "qwen3.5:4b"  # the weakest model the answers in the cases are for


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    model = argv[0] if argv else noir.NOIR_MODEL
    ollama = Ollama()
    ollama.ensure_running()
    fill = auto.model_form(ollama, model)
    cases = auto.load_cases()

    print(f"Auto, as the app decides (asking {model} only when unclear):")
    wrong = 0
    for case in cases:
        decision = auto.decide(case["text"], base_model=SMALL_MODEL, after=case.get("after", ""), ask_model=fill)
        if decision.where != case["expect"]:
            wrong += 1
            print(f"  WRONG {decision.where} ({decision.kind}, by {decision.by}), expected {case['expect']}: "
                  f"{_short(case['text'])}")
    print(f"  {len(cases) - wrong}/{len(cases)} right")

    print(f"\n{model} judging alone, for comparison:")
    alone_wrong, started = 0, time.monotonic()
    judged = [case for case in cases if not case.get("after")]
    for case in judged:
        kind = fill(case["text"])
        where = auto.HERE if kind in auto.STAY_HERE[auto.SMALL] else auto.CLOUD
        if where != case["expect"]:
            alone_wrong += 1
            print(f"  would be wrong: {kind} -> {where}, expected {case['expect']}: {_short(case['text'])}")
    seconds = (time.monotonic() - started) / max(len(judged), 1)
    print(f"  {len(judged) - alone_wrong}/{len(judged)} right, {seconds:.2f}s each")
    return 1 if wrong else 0


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= 70 else text[:67] + "..."


if __name__ == "__main__":
    raise SystemExit(main())
