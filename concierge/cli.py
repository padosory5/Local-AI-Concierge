"""Terminal front end for the first process: check the computer, pick Noir's
model, set it up, and chat. A real UI comes later and will reuse the same
modules; nothing here holds logic the UI would need.

    python -m concierge             show the computer and models, set up if needed, chat
    python -m concierge hardware    show what this computer has (--json for raw)
    python -m concierge recommend   show which model Noir would use and why
    python -m concierge setup       download the model and (re)build Noir
    python -m concierge chat        talk with Noir
    python -m concierge measure TAG measure a model's real graphics memory use
    python -m concierge history ZIP get to know you from a ChatGPT or Claude download
"""

from __future__ import annotations

import argparse
import os
import json
import sys

from . import noir, hardware
from .catalog import Recommendation, find_model, recommend
from .engine import NoirEngine
from .events import (
    AgentCard,
    AgentList,
    NoirDone,
    NoirText,
    Error,
    IdeaCard,
    Thinking,
    Event,
    Progress,
    Question,
    Result,
    SystemInfo,
)
from .ollama import Ollama, OllamaError


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.platform == "win32":
        os.system("")  # switches on colour codes in the classic Windows console
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="concierge", description="Noir Agents")
    sub = parser.add_subparsers(dest="command")
    hw = sub.add_parser("hardware", help="show what this computer has")
    hw.add_argument("--json", action="store_true", help="print the raw report")
    sub.add_parser("recommend", help="show which model Noir would use")
    setup = sub.add_parser("setup", help="download the model and build Noir")
    setup.add_argument("--yes", "-y", action="store_true", help="do not ask before downloading")
    sub.add_parser("chat", help="talk with Noir")
    measure = sub.add_parser("measure", help="measure a model's real graphics memory use")
    measure.add_argument("tag")
    past = sub.add_parser("history", help="get to know you from a ChatGPT or Claude download")
    past.add_argument("paths", nargs="*", help="the zip from Export data, or its conversations.json")
    past.add_argument("--forget", action="store_true", help="forget everything brought in")
    args = parser.parse_args(argv)

    try:
        if args.command == "hardware":
            return cmd_hardware(args.json)
        if args.command == "recommend":
            return cmd_recommend()
        if args.command == "setup":
            return cmd_setup(assume_yes=args.yes)
        if args.command == "chat":
            return cmd_chat(setup_first=False)
        if args.command == "measure":
            return cmd_measure(args.tag)
        if args.command == "history":
            return cmd_history(args.paths, args.forget)
        return cmd_chat(setup_first=True)
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


def cmd_setup(assume_yes: bool) -> int:
    ollama, report, rec = _check_computer()
    code = _ensure_noir(ollama, rec, report, assume_yes, force=True)
    if code == 0:
        _print_in_use(rec)
    return code


def cmd_chat(setup_first: bool) -> int:
    """Show the computer, the recommended model and Noir's model, then chat."""
    ollama, report, rec = _check_computer()
    if setup_first:
        code = _ensure_noir(ollama, rec, report, assume_yes=False, force=False)
        if code:
            return code
    if not ollama.has_model(noir.NOIR_MODEL):
        print("Noir is not set up yet. Run: python -m concierge setup")
        return 1
    _print_in_use(rec)

    engine = NoirEngine(ollama)
    screen = TerminalScreen()
    for event in engine.startup():
        if isinstance(event, Error):
            screen.draw(event)
            return 1
        if not isinstance(event, SystemInfo):  # already shown above
            screen.draw(event)
    _on_window_close(engine.close)
    try:
        return _chat_loop(engine, screen)
    finally:
        engine.close()


def _chat_loop(engine: NoirEngine, screen: TerminalScreen) -> int:
    print("Chat with Noir. Type /new for a new chat (this one is saved), /think to see its")
    print("thinking (slower), /exit to leave.")
    print('Try: "make me a helper", and say what you would like it to do.\n')
    think = False
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
        if text == "/think":
            think = not think
            print(f"(Think is {'on: the thinking is shown first, which is slower' if think else 'off'}.)\n")
            continue
        if text in ("/new", "/reset"):
            engine.reset()
            screen.pending = None
            print("(Started a new chat. The last one is saved in the app's chat list.)\n")
            continue
        picked = screen.pick(text)
        events = engine.choose(*picked) if picked else engine.send(text, think)
        screen.pending = None
        try:
            for event in events:
                screen.draw(event)
        except KeyboardInterrupt:
            print(" (stopped)\n")
        screen.end_progress()


# Dim and normal text in the terminal (Windows 10 and later understand these).
DIM, PLAIN = "\033[2m", "\033[0m"


class TerminalScreen:
    """Draws engine events as text. Buttons become numbered choices: the user
    types the number (or the choice itself) to click one."""

    def __init__(self):
        self.pending: tuple[str, list[str]] | None = None  # (id, choices) waiting for a pick
        self.in_reply = False
        self.progress = False
        self.thinking = False  # in the middle of a dimmed thinking block

    def pick(self, text: str) -> tuple[str, str] | None:
        if not self.pending:
            return None
        id, choices = self.pending
        if text.isdigit() and 1 <= int(text) <= len(choices):
            return id, choices[int(text) - 1]
        match = next((c for c in choices if c.lower() == text.lower()), None)
        return (id, match) if match else None

    def end_progress(self) -> None:
        if self.progress:
            print("\r" + " " * 78 + "\r", end="", flush=True)
            self.progress = False

    def draw(self, event: Event) -> None:
        if not isinstance(event, Progress):
            self.end_progress()
        if isinstance(event, Thinking):
            # Dimmed, like the window's fog. Steps get a line each; thoughts stream.
            if event.kind == "step":
                print(f"{DIM}  · {event.text}{PLAIN}")
            else:
                if not self.thinking:
                    print(f"{DIM}  (thinking) ", end="")
                    self.thinking = True
                print(event.text, end="", flush=True)
            return
        if self.thinking:
            print(f"{PLAIN}\n")
            self.thinking = False
        if isinstance(event, NoirText):
            if not self.in_reply:
                print("Noir: ", end="")
                self.in_reply = True
            print(event.text, end="", flush=True)
        elif isinstance(event, NoirDone):
            print("\n")
            self.in_reply = False
        elif isinstance(event, Question):
            print(f"Noir: {event.text}")
            self._choices(event.id, event.choices)
            print()
        elif isinstance(event, AgentCard):
            print(f"  +-- {event.name}  ({event.kind})")
            for line in event.reads:
                print(f"  |  Reads:     {line}")
            print(f"  |  Can do:    {'; '.join(event.can_do)}")
            print(f"  |  Can't do:  {'; '.join(event.cannot_do)}")
            print(f"  |  Runs on:   {event.runs_on}")
            print("  +--")
            self._choices(event.id, event.actions)
            print()
        elif isinstance(event, IdeaCard):
            words = {"ready": "ready", "not_built": "not built yet", "not_possible": "not possible",
                     "unclear": "not sure"}
            print(f"  +-- Idea: {event.title}")
            for step in event.steps:
                print(f"  |  [{words.get(step.status, step.status)}] {step.text}")
                if step.note:
                    print(f"  |      {step.note}")
            if event.difficulty:
                print(f"  |  {event.difficulty}")
            print(f"  |  {event.verdict}")
            print("  +--")
            self._choices(event.id, event.actions)
            print()
        elif isinstance(event, Progress):
            print(f"\r  {event.text[:74]:<76}", end="", flush=True)
            self.progress = True
        elif isinstance(event, Result):
            print(f"[{event.agent}] {event.text}")
            for source in event.sources:
                quote = f': "{source.quote}"' if source.quote else ""
                print(f"    from {source.path}{quote}")
            print()
        elif isinstance(event, AgentList):
            if event.agents:
                names = [f"{n} ({'on' if n in event.active else 'off'})" if n in event.switchable else n
                         for n in event.agents]
                print(f"Your agents: {', '.join(names)}\n")
        elif isinstance(event, Error):
            print(f"(Problem) {event.text}\n")

    def _choices(self, id: str, choices: list[str] | None) -> None:
        if choices:
            for number, choice in enumerate(choices, 1):
                print(f"  {number}. {choice}")
            self.pending = (id, choices)


def cmd_history(paths: list[str], forget: bool = False) -> int:
    """Bring in ChatGPT or Claude downloads, then show what Noir understood and
    ask about each fact. The same steps the app's windows take."""
    engine = NoirEngine()
    if forget:
        engine.forget_history()
        print("Forgotten: every chat brought in, and everything worked out from them.")
        return 0
    for path in paths:
        result = engine.bring_in_history(path)
        if "error" in result:
            print(result["error"])
            return 1
        print(f"Brought in {result['read']} chats from {' and '.join(result['sources'])} "
              f"({result['new']} new, {result['total']} in all).")
    Ollama().ensure_running()
    made = engine.understand_history(progress=lambda text: print(f"{DIM}{text}{PLAIN}"))
    if "error" in made:
        print(made["error"])
        return 1
    _show_portrait(made)
    undecided = [fact for fact in made["facts"] if fact.get("kept") is None]
    if undecided:
        print()
        print("Is this right? y keeps it, n drops it, Enter decides later.")
    for fact in undecided:
        answer = input(f"  {fact['fact']}  {DIM}(\"{fact['quote']}\", {fact['source']}){PLAIN} ").strip().lower()
        if answer in ("y", "n"):
            engine.keep_fact(fact["id"], answer == "y")
    kept = [fact["fact"] for fact in engine.what_i_know().get("facts", []) if fact.get("kept")]
    print()
    print(f"Noir will remember {len(kept)} thing{'s' if len(kept) != 1 else ''} about you, on this computer only.")
    return 0


def _show_portrait(made: dict) -> None:
    from datetime import datetime

    chats = " and ".join(f"{source} {count} times" for source, count in made["chats"].items())
    since = datetime.fromtimestamp(made["first"]).strftime("%B %Y") if made.get("first") else "the start"
    print()
    print(f"You've talked with {chats}, since {since}", end="")
    print(f", mostly {made['busiest']}." if made.get("busiest") else ".")
    if made.get("languages"):
        print("You write in " + ", ".join(f"{name} ({count})" for name, count in made["languages"].items()) + ".")
    print()
    print("What you ask for most:")
    for kind in made["kinds"][:6]:
        print(f"  {kind['count']:4}  {kind['words']}")
    print()
    print("What I think I know about you:" if made["facts"] else "I didn't find anything you said about yourself.")
    for fact in made["facts"]:
        mark = {True: "kept", False: "dropped", None: ""}[fact.get("kept")]
        print(f"  {fact['fact']}  {DIM}seen in {fact['seen']} chat{'s' if fact['seen'] != 1 else ''} {mark}{PLAIN}")


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
        {"model": tag, "prompt": "", "options": {"num_ctx": noir.NUM_CTX}, "keep_alive": "2m"},
    )
    after = _nvidia_used_gb()
    reported = next((m for m in ollama.loaded() if m["name"] == tag), {})
    ollama.unload(tag)

    print(f"Ollama reports:   {reported.get('size_vram', 0) / hardware.GB:.2f} GB on the graphics card")
    if before is None or after is None:
        print("No NVIDIA card to measure on; memory_gb stays an estimate.")
        return 0
    used = round(after - before, 2)
    print(f"The card used:    {used:.2f} GB (num_ctx {noir.NUM_CTX})")
    print(f"\nFor models.yaml:\n    memory_gb: {used:.1f}\n    measured: true")
    return 0


# ----------------------------------------------------------------- steps


def _check_computer() -> tuple[Ollama, hardware.HardwareReport, Recommendation]:
    """Steps 1 and 2: read the hardware and pick a model, and show both."""
    print("Checking your computer...")
    report = hardware.detect()
    rec = recommend(report)
    ollama = Ollama()
    ollama.ensure_running()
    _print_hardware(report)
    _print_recommendation(rec, downloaded=bool(rec.model) and ollama.has_model(rec.model.tag))
    return ollama, report, rec


def _ensure_noir(
    ollama: Ollama, rec: Recommendation, report: hardware.HardwareReport, assume_yes: bool, force: bool
) -> int:
    """Step 3: build Noir from the recommended model if it is missing or
    out of date. Returns 0 when there is an Noir to talk to."""
    has_noir = ollama.has_model(noir.NOIR_MODEL)
    if rec.model is None:
        return 0 if has_noir else 1
    if not force and not noir.needs_configure(ollama, rec.model, rec, report):
        return 0

    if not ollama.has_model(rec.model.tag):
        if not assume_yes and not _confirm(f"Download {rec.model.name} ({rec.model.download_gb:g} GB) now?"):
            if has_noir:
                print("Nothing was downloaded. Noir keeps the model it already has.\n")
                return 0
            print("Nothing was downloaded.")
            return 1
        ollama.pull(rec.model.tag, on_progress=_progress_printer())
        print()

    print("Setting up Noir...")
    noir.configure(ollama, rec.model, rec, report)
    print("Noir is ready.\n")
    return 0


# --------------------------------------------------------------- output


def _print_hardware(report: hardware.HardwareReport) -> None:
    print()
    for line in hardware.describe(report):
        print(f"  {line}")
    print()


def _print_recommendation(rec: Recommendation, downloaded: bool = False) -> None:
    if rec.model is None:
        print(f"No model recommended: Noir cannot run well on this computer yet. {rec.reason}\n")
        return
    where = {"gpu": "graphics memory", "apple": "shared memory", "cpu": "memory"}[rec.device]
    estimate = "" if rec.model.measured else " (estimate)"
    print(f"Recommended for this computer: {rec.model.name} ({rec.model.tag})")
    print(f"  Uses about {rec.model.memory_gb:g} GB of {where}{estimate}, "
          f"leaving {rec.left_free_gb:g} GB for your other apps and agents.")
    if not downloaded:
        print(f"  Download size: {rec.model.download_gb:g} GB")
    print(f"  Why: {rec.reason}\n")


def _print_in_use(rec: Recommendation) -> None:
    """The model Noir is actually built from, which can differ from the
    recommendation when the user declined to download a new one."""
    tag = noir.load_state().get("base_model")
    model = find_model(tag) if tag else None
    name = f"{model.name} ({tag})" if model else tag or "an unknown model"
    print(f"Noir is using: {name} on {rec.device_name}")
    if rec.model and tag != rec.model.tag:
        print(f"  Not the recommended {rec.model.name}. Run `python -m concierge setup` to switch.")
    print()


_close_handlers = []  # Keeps the Windows callback alive while the program runs.


def _on_window_close(callback) -> None:
    """Run callback when the terminal window is closed, not only on /exit.

    Closing the window skips Python's normal shutdown, so `finally` blocks
    never run. Windows sends a close event first and allows about five
    seconds; macOS and Linux send SIGHUP.
    """
    if sys.platform == "win32":
        import ctypes

        close_events = (2, 5, 6)  # window closed, user logged off, shutdown

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)
        def handler(event):
            if event in close_events:
                callback()
            return False  # Let Windows (and Python's Ctrl+C handling) carry on.

        _close_handlers.append(handler)
        ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True)
    else:
        import signal

        def on_hangup(signum, frame):
            callback()
            sys.exit(0)

        signal.signal(signal.SIGHUP, on_hangup)


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
