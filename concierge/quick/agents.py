"""Which switch-on agents are on, and running them when the user highlights text.

The mouse watcher and the bubble only exist while at least one agent is on,
so nothing listens to the mouse while every agent is off. Highlights are
handled one at a time on a worker thread; when the user highlights again
before a translation is done, the older result is dropped.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable

from ..agents.store import Agent
from ..noir import KEEP_ALIVE
from ..ollama import Ollama, OllamaError
from .translate import looks_like

BUBBLE, CLIPBOARD, BOTH = "A bubble above the text", "Copy it to the clipboard", "Both"
UNTIL_UNHIGHLIGHT, FEW_SECONDS = "Until you unhighlight the text", "A few seconds"
# While a bubble waits for its highlight to go away: how often to look, and
# for how long at most.
CHECK_SECONDS, CHECK_FOR_SECONDS = 0.4, 600


class QuickAgents:
    def __init__(self, ollama: Ollama, model: str, think: bool | None,
                 make_watcher: Callable | None = None, make_bubble: Callable | None = None,
                 set_clipboard: Callable[[str], None] | None = None,
                 highlighted: Callable[[], str] | None = None):
        """make_watcher, make_bubble, set_clipboard and highlighted are replaced in tests."""
        self._highlighted = highlighted or _real_highlighted
        self.ollama = ollama
        self.model = model
        self.think = think
        self.active: dict[str, Agent] = {}
        self._make_watcher = make_watcher or _real_watcher
        self._make_bubble = make_bubble or _real_bubble
        self._set_clipboard = set_clipboard or _real_set_clipboard
        self._watcher = None
        self._bubble = None
        self._latest: tuple | None = None  # the newest highlight not handled yet
        self._serial = 0  # counts highlights, to drop results that arrive too late
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._worker: threading.Thread | None = None

    # ------------------------------------------------------------ switching

    def is_on(self, name: str) -> bool:
        return name in self.active

    def switch(self, agent: Agent, on: bool) -> None:
        if on:
            self.active[agent.name] = agent
            self._start()
            # Load the model now, so the first highlight is quick.
            threading.Thread(target=self._warm_up, daemon=True).start()
        else:
            self.active.pop(agent.name, None)
            if not self.active:
                self._stop()

    def stop(self) -> None:
        self.active.clear()
        self._stop()

    def refresh(self, agents: list[Agent]) -> None:
        """Pick up changed settings of agents that are on; drop deleted ones."""
        by_name = {a.name: a for a in agents}
        for name in list(self.active):
            if name in by_name:
                self.active[name] = by_name[name]
            else:
                self.active.pop(name)
        if not self.active:
            self._stop()

    def _start(self) -> None:
        if self._watcher is not None:
            return
        self._stopping.clear()
        self._bubble = self._make_bubble()
        self._watcher = self._make_watcher(self.highlighted, self._bubble.pressed, {os.getpid()})
        self._watcher.start()
        self._worker = threading.Thread(target=self._work, name="quick-agents", daemon=True)
        self._worker.start()

    def _stop(self) -> None:
        if self._watcher is None:
            return
        self._stopping.set()
        self._wake.set()
        self._watcher.stop()
        self._bubble.close()
        self._watcher = self._bubble = None

    def _warm_up(self) -> None:
        try:
            self.ollama.refresh(self.model, KEEP_ALIVE)
        except Exception:
            pass  # the first translation will load it instead

    # ------------------------------------------------------------- running

    def highlighted(self, text: str, rect) -> None:
        """Called by the watcher (on its own thread) for every highlight."""
        self._serial += 1
        self._latest = (self._serial, text, rect)
        self._wake.set()

    def _work(self) -> None:
        while not self._stopping.is_set():
            self._wake.wait()
            self._wake.clear()
            if self._stopping.is_set():
                break
            latest, self._latest = self._latest, None
            if latest is None:
                continue
            for agent in list(self.active.values()):
                self.handle(agent, *latest)

    def handle(self, agent: Agent, serial: int, text: str, rect) -> None:
        """Apply the agent's instruction to a highlight and show the result."""
        from ..agents.recipe import run_instruction, target_language  # agents imports quick

        instruction = agent.slots.get("instruction", "")
        show = agent.slots.get("show", BUBBLE)
        language = target_language(instruction)
        if language and looks_like(text, language):
            return  # a translator, and the text is already in that language
        bubble = self._bubble
        if bubble and show in (BUBBLE, BOTH):
            bubble.show("Translating..." if language else "Working on it...", rect, agent.name, seconds=30)
        try:
            result = run_instruction(self.ollama, self.model, instruction, text, self.think)
        except OllamaError:
            result = "I couldn't do that: Ollama isn't running."
        if serial != self._serial or not result:
            return  # the user has highlighted something newer since
        from .. import activity

        activity.record(activity.TRANSLATED if language else activity.EXPLAINED)
        if show in (CLIPBOARD, BOTH):
            self._set_clipboard(result)
        if bubble and show in (BUBBLE, BOTH):
            stay = agent.slots.get("keep", UNTIL_UNHIGHLIGHT) == UNTIL_UNHIGHLIGHT
            bubble.show(result, rect, f"{agent.name} · click to copy", stay=stay)
            if stay:
                threading.Thread(target=self._close_when_unhighlighted, args=(serial, text),
                                 daemon=True).start()
        elif bubble:
            bubble.show("Copied, ready to paste", rect, agent.name, seconds=1.5)


    def _close_when_unhighlighted(self, serial: int, text: str) -> None:
        """Close the bubble once its text is no longer highlighted.

        Only where UI Automation can see the highlight; elsewhere the bubble
        stays until the user clicks somewhere else or highlights something new.
        """
        if self._highlighted() != text.strip():
            return  # this program does not say what is highlighted
        waited = 0.0
        while waited < CHECK_FOR_SECONDS and serial == self._serial and self._bubble:
            time.sleep(CHECK_SECONDS)
            waited += CHECK_SECONDS
            if serial != self._serial:
                return  # a newer highlight has its own bubble
            if self._highlighted() != text.strip():
                if self._bubble:
                    self._bubble.hide()
                return


def _real_watcher(on_selection, on_press, skip_pids):
    from .selection import SelectionWatcher

    return SelectionWatcher(on_selection, on_press, skip_pids)


def _real_bubble():
    from .bubble import Bubble

    return Bubble()


def _real_highlighted() -> str:
    from .selection import highlighted_text

    return highlighted_text()


def _real_set_clipboard(text: str) -> None:
    from .selection import set_clipboard_text

    set_clipboard_text(text)
