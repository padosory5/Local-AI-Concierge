"""The desktop chat window: a pywebview window showing ui/web/index.html.

The page sends the user's text and clicks to ChatBridge, which passes them to
the engine and pushes every event it returns back to the page as JSON. The
page only draws; it never decides anything (see CLAUDE.md).

    python -m concierge.ui          chat with the real Elaina
    python -m concierge.ui --fake   chat with FakeEngine, no model needed
"""

from __future__ import annotations

import argparse
import json
import threading
import traceback
from pathlib import Path

from .. import events
from ..engine import ElainaEngine
from ..events import Engine, Error, Event
from ..fake_engine import FakeEngine

WEB_DIR = Path(__file__).parent / "web"
TITLE = "Elaina"
# Shown when the engine fails in a way it did not turn into an Error event,
# such as Ollama dropping the connection halfway through a reply.
UNEXPECTED_ERROR = "Something went wrong on my side. Please try again, or restart the app."


class ChatBridge:
    """What the page can call, as window.pywebview.api.<method>.

    pywebview hands every public attribute to the page, so everything except
    these calls is kept private with a leading underscore.
    """

    def __init__(self, engine: Engine):
        self._engine = engine
        self._window = None
        # pywebview runs each call from the page in its own thread. One engine
        # call at a time keeps two replies from streaming into each other.
        self._lock = threading.Lock()
        self._closed = threading.Event()

    def startup(self) -> None:
        self._run(self._engine.startup)

    def send(self, text: str, think: bool = False) -> None:
        self._run(self._engine.send, text, bool(think))

    def choose(self, id: str, choice: str) -> None:
        self._run(self._engine.choose, id, choice)

    def new_chat(self) -> None:
        self._run(self._engine.new_chat)

    def open_chat(self, id: str) -> None:
        self._run(self._engine.open_chat, id)

    def delete_chat(self, id: str) -> None:
        self._run(self._engine.delete_chat, id)

    def delete_agent(self, name: str) -> None:
        self._run(self._engine.delete_agent, name)

    def toggle_agent(self, name: str) -> None:
        self._run(self._engine.toggle_agent, name)

    def reset(self) -> None:
        with self._lock:
            self._engine.reset()

    def _attach(self, window) -> None:
        self._window = window

    def _close(self) -> None:
        """The window is gone: stop drawing and let the engine free Elaina's memory.

        Does not wait for the lock, so closing never waits for a reply to finish.
        """
        self._closed.set()
        self._engine.close()

    def _run(self, call, *args) -> None:
        """Pass every event to the page as it arrives. Returns when the call is
        done, which is when the page enables the input again."""
        with self._lock:
            try:
                for event in call(*args):
                    if self._closed.is_set():
                        break  # Leaving the loop also stops the reply.
                    self._push(event)
            except Exception:
                traceback.print_exc()
                self._push(Error(UNEXPECTED_ERROR))

    def _push(self, event: Event) -> None:
        if self._window is not None and not self._closed.is_set():
            self._window.run_js(f"app.onEvent({json.dumps(events.to_dict(event))})")


def open_window(engine: Engine, debug: bool = False) -> None:
    """Open the chat window and block until the user closes it."""
    # Imported here so the tests and the terminal app never need a window.
    import webview

    bridge = ChatBridge(engine)
    window = webview.create_window(
        TITLE,
        str(WEB_DIR / "index.html"),
        js_api=bridge,
        width=980,
        height=720,
        min_size=(720, 520),
        background_color="#F7F7F5",
        text_select=True,  # People copy Elaina's answers.
    )
    bridge._attach(window)
    try:
        webview.start(debug=debug)
    finally:
        bridge._close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="concierge.ui", description="Elaina's chat window")
    parser.add_argument("--fake", action="store_true", help="use FakeEngine, no model needed")
    parser.add_argument("--debug", action="store_true", help="open the page's developer tools")
    args = parser.parse_args(argv)

    open_window(FakeEngine() if args.fake else ElainaEngine(), debug=args.debug)
    return 0
