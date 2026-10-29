"""Terminal front end for the first process: check the computer, pick Elaina's
model, set her up, and chat. A real UI comes later and will reuse the same
modules; nothing here holds logic the UI would need.

    python -m concierge             set up if needed, then chat
    python -m concierge hardware    show what this computer has (--json for raw)
    python -m concierge recommend   show which model Elaina would use and why
    python -m concierge setup       download the model and (re)build Elaina
    python -m concierge chat        talk with Elaina
    python -m concierge measure TAG measure a model's real graphics memory use
"""

from __future__ import annotations

import argparse
import json
import sys

from . import elaina, hardware
from .catalog import Recommendation, recommend
from .ollama import Ollama, OllamaError


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="concierge", description="Local AI Concierge")
    sub = parser.add_subparsers(dest="command")
    hw = sub.add_parser("hardware", help="show what this computer has")
    hw.add_argument("--json", action="store_true", help="print the raw report")
    sub.add_parser("recommend", help="show which model Elaina would use")
    setup = sub.add_parser("setup", help="download the model and build Elaina")
    setup.add_argument("--yes", "-y", action="store_true", help="do not ask before downloading")
    sub.add_parser("chat", help="talk with Elaina")
    measure = sub.add_parser("measure", help="measure a model's real graphics memory use")
    measure.add_argument("tag")
    args = parser.parse_args(argv)

    try:
        if args.command == "hardware":
            return cmd_hardware(args.json)
        if args.command == "recommend":
            return cmd_recommend()
        if args.command == "setup":
            return cmd_setup(assume_yes=args.yes, force=True)
        if args.command == "chat":
            return cmd_chat()
        if args.command == "measure":
            return cmd_measure(args.tag)
        code = cmd_setup(assume_yes=False, force=False)
        return code or cmd_chat()
    except OllamaError as exc:
        print(f"\n{exc}")
        return 1
    except KeyboardInterrupt:
        print()
        return 130


# ------------------------------------------------------------- commands


def cmd_hardware(as_json: bool) -> int:
    report = hardware.detect()
    if as_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_hardware(report)
    return 0


def cmd_recommend() -> int:
    report = hardware.detect()
    _print_hardware(report)
    _print_recommendation(recommend(report))
    return 0


def cmd_setup(assume_yes: bool, force: bool) -> int:
    print("Checking your computer...")
    report = hardware.detect()
    rec = recommend(report)
    ollama = Ollama()
    ollama.ensure_running()

    if not force and rec.model and not elaina.needs_configure(ollama, rec.model, rec, report):
        return 0  # Elaina is already set up for this machine.

    _print_hardware(report)
    _print_recommendation(rec)
    if rec.model is None:
        return 1

    if not ollama.has_model(rec.model.tag):
        if not assume_yes and not _confirm(f"Download {rec.model.name} ({rec.model.download_gb:g} GB) now?"):
            print("Nothing was downloaded.")
            return 1
        ollama.pull(rec.model.tag, on_progress=_progress_printer())
        print()

    print("Setting up Elaina...")
    elaina.configure(ollama, rec.model, rec, report)
    print("Elaina is ready.\n")
    return 0


def cmd_chat() -> int:
    ollama = Ollama()
    ollama.ensure_running()
    if not ollama.has_model(elaina.ELAINA_MODEL):
        print("Elaina is not set up yet. Run: python -m concierge setup")
        return 1

    chat = elaina.ElainaChat(ollama)
    print("Chat with Elaina. Type /reset to start over, /exit to leave.\n")
    while True:
        try:
            text = input("You: ").strip()
        except EOFError:
            print()
            return 0
        if not text:
            continue
        if text in ("/exit", "/quit"):
            return 0
        if text == "/reset":
            chat.reset()
            print("(Started a new conversation.)\n")
            continue
        print("Elaina: ", end="", flush=True)
        try:
            for chunk in chat.send(text):
                print(chunk, end="", flush=True)
        except KeyboardInterrupt:
            print(" (stopped)", end="")
        print("\n")


def cmd_measure(tag: str) -> int:
    """Load a model alone on the card and read the real memory use.

    Ollama's own figure can be far off (1.45 GB reported for gemma4:12b while
    the card used 9.7 GB), so the tested list uses the card's number.
    """
    ollama = Ollama()
    ollama.ensure_running()
    if not ollama.has_model(tag):
        print(f"{tag} is not downloaded. Run: ollama pull {tag}")
        return 1
    for model in ollama.loaded():
        ollama.unload(model["name"])

    before = _nvidia_used_gb()
    ollama._post(
        "/api/generate",
        {"model": tag, "prompt": "", "options": {"num_ctx": elaina.NUM_CTX}, "keep_alive": "2m"},
    )
    after = _nvidia_used_gb()
    reported = next((m for m in ollama.loaded() if m["name"] == tag), {})
    ollama.unload(tag)

    print(f"Ollama reports:   {reported.get('size_vram', 0) / hardware.GB:.2f} GB on the graphics card")
    if before is None or after is None:
        print("No NVIDIA card to measure on; memory_gb stays an estimate.")
        return 0
    used = round(after - before, 2)
    print(f"The card used:    {used:.2f} GB (num_ctx {elaina.NUM_CTX})")
    print(f"\nFor models.yaml:\n    memory_gb: {used:.1f}\n    measured: true")
    return 0


# --------------------------------------------------------------- output


def _print_hardware(report: hardware.HardwareReport) -> None:
    print()
    for line in hardware.describe(report):
        print(f"  {line}")
    print()


def _print_recommendation(rec: Recommendation) -> None:
    if rec.model is None:
        print(f"Elaina cannot run well on this computer yet. {rec.reason}")
        return
    where = {"gpu": "graphics memory", "apple": "shared memory", "cpu": "memory"}[rec.device]
    estimate = "" if rec.model.measured else " (estimate)"
    print(f"Elaina's brain: {rec.model.name} ({rec.model.tag})")
    print(f"  Uses about {rec.model.memory_gb:g} GB of {where}{estimate}, "
          f"leaving {rec.left_free_gb:g} GB for your other apps and agents.")
    print(f"  Download size: {rec.model.download_gb:g} GB")
    print(f"  Why: {rec.reason}\n")


def _confirm(question: str) -> bool:
    answer = input(f"{question} [Y/n] ").strip().lower()
    return answer in ("", "y", "yes")


def _progress_printer():
    last = {"line": ""}

    def show(status: str, completed: int, total: int) -> None:
        if total:
            line = f"  Downloading: {completed / total:5.1%} of {total / hardware.GB:.1f} GB"
        else:
            line = f"  {status}"
        if line != last["line"]:
            print(f"\r{line:<60}", end="", flush=True)
            last["line"] = line

    return show


def _nvidia_used_gb() -> float | None:
    import subprocess

    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout
        return int(out.split()[0]) / 1024
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None
