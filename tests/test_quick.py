import threading
import time
from types import SimpleNamespace

import pytest

from concierge.agents import store
from concierge.agents.recipe import CUSTOM, WHILE_ON
from concierge.quick import agents as quick_agents
from concierge.quick.agents import BOTH, BUBBLE, CLIPBOARD, FEW_SECONDS, UNTIL_UNHIGHLIGHT, QuickAgents
from concierge.quick.selection import SelectionWatcher
from concierge.quick.translate import language_in, looks_like


class FakeOllama:
    """Answers by tagging the text with the instruction's first words, and
    remembers what it was asked."""

    def __init__(self):
        self.asked = []

    def chat(self, model, messages, think=None, options=None, keep_alive=None):
        self.asked.append(messages)
        instruction = messages[0]["content"].split("\n")[0]
        if "into " in instruction:
            yield f"[{instruction.split('into ')[1].split('.')[0]}] {messages[-1]['content']}"
        else:
            yield f"[{instruction[:12]}] {messages[-1]['content']}"

    def refresh(self, model, keep_alive):
        pass


@pytest.fixture(autouse=True)
def agents_home(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")


# ------------------------------------------------------------- languages


@pytest.mark.parametrize("text, target_only, expected", [
    ("translate English sentences into Korean", True, "Korean"),
    ("make me a Japanese translator", True, "Japanese"),
    ("하이라이트한 문장을 한국어로 번역해줘", True, "Korean"),
    ("translate English text for me", True, None),  # English is the source here
    ("Spanish please", False, "Spanish"),
    ("Klingon", False, None),
])
def test_language_in(text, target_only, expected):
    assert language_in(text, target_only) == expected


def test_already_in_the_language():
    assert looks_like("안녕하세요, 반가워요", "Korean")
    assert not looks_like("Good morning", "Korean")
    assert looks_like("The cat is on the table", "English")
    assert looks_like("12:30 - 14:00", "Japanese")  # nothing to translate


# ------------------------------------------------------- switching on


class FakeBubble:
    def __init__(self):
        self.shown, self.closed, self.stays, self.hidden = [], False, [], 0

    def show(self, text, rect, title="", seconds=None, stay=False):
        self.shown.append(text)
        self.stays.append(stay)

    def hide(self):
        self.hidden += 1

    def pressed(self, x, y):
        pass

    def close(self):
        self.closed = True


class FakeWatcher:
    def __init__(self, on_selection, on_press, skip_pids):
        self.on_selection, self.started, self.stopped = on_selection, False, False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def quick():
    made = SimpleNamespace(watchers=[], bubbles=[], clipboard=[], highlight="")

    def watcher(*args):
        made.watchers.append(FakeWatcher(*args))
        return made.watchers[-1]

    def bubble():
        made.bubbles.append(FakeBubble())
        return made.bubbles[-1]

    q = QuickAgents(FakeOllama(), "noir", None, watcher, bubble, made.clipboard.append,
                    lambda: made.highlight)
    return q, made


def agent(show=BUBBLE, instruction="Translate the text into Korean.", name="Korean translator",
          keep=UNTIL_UNHIGHLIGHT):
    return store.Agent(name, CUSTOM, {"instruction": instruction, "when": WHILE_ON, "show": show, "keep": keep})


def test_nothing_listens_until_an_agent_is_switched_on():
    q, made = quick()
    assert made.watchers == []
    q.switch(agent(), True)
    assert made.watchers[0].started and q.is_on("Korean translator")
    q.switch(agent(), False)
    assert made.watchers[0].stopped and made.bubbles[0].closed and not q.is_on("Korean translator")


def test_highlight_runs_the_agents_instruction():
    q, made = quick()
    q.switch(agent(), True)
    q._serial = 1
    q.handle(agent(), 1, "Good morning", (0, 100, 50, 120))
    assert made.bubbles[0].shown == ["Translating...", "[Korean] Good morning"]
    assert made.clipboard == []


def test_any_instruction_works_the_same_way():
    explainer = agent(instruction="Explain this English word in simple Korean.", name="Word explainer")
    q, made = quick()
    q.switch(explainer, True)
    q._serial = 1
    q.handle(explainer, 1, "serendipity", (0, 0, 0, 0))
    assert made.bubbles[0].shown == ["Working on it...", "[Explain this] serendipity"]


def test_clipboard_and_both():
    q, made = quick()
    q.switch(agent(CLIPBOARD), True)
    q._serial = 1
    q.handle(agent(CLIPBOARD), 1, "Good morning", (0, 0, 0, 0))
    assert made.clipboard == ["[Korean] Good morning"]
    assert made.bubbles[0].shown == ["Copied, ready to paste"]
    q.handle(agent(BOTH), 1, "Thank you", (0, 0, 0, 0))
    assert made.clipboard[-1] == "[Korean] Thank you" and made.bubbles[0].shown[-1] == "[Korean] Thank you"


def test_text_already_in_the_target_language_is_left_alone():
    q, made = quick()
    q.switch(agent(), True)
    q.handle(agent(), q._serial, "안녕하세요 반가워요", (0, 0, 0, 0))
    assert made.bubbles[0].shown == [] and q.ollama.asked == []


def test_an_older_highlight_is_dropped_when_a_newer_one_came():
    q, made = quick()
    q.switch(agent(), True)
    q._serial = 2  # the user highlighted again while this one was being worked on
    q.handle(agent(), 1, "Good morning", (0, 0, 0, 0))
    assert made.bubbles[0].shown == ["Translating..."]


def test_worker_thread_handles_highlights():
    q, made = quick()
    q.switch(agent(), True)
    made.watchers[0].on_selection("See you tomorrow", (0, 0, 10, 10))
    deadline = time.monotonic() + 2
    while "[Korean] See you tomorrow" not in made.bubbles[0].shown and time.monotonic() < deadline:
        time.sleep(0.02)
    assert made.bubbles[0].shown[-1] == "[Korean] See you tomorrow"
    q.stop()


def test_bubble_stays_until_the_highlight_is_gone(monkeypatch):
    monkeypatch.setattr(quick_agents, "CHECK_SECONDS", 0.01)
    q, made = quick()
    q.switch(agent(), True)
    made.highlight = "Good morning"  # UI Automation still sees the highlight
    q._serial = 1
    q.handle(agent(), 1, "Good morning", (0, 0, 0, 0))
    assert made.bubbles[0].stays[-1] is True
    time.sleep(0.1)
    assert made.bubbles[0].hidden == 0  # still highlighted: still showing
    made.highlight = ""  # the user clicked away or pressed an arrow key
    deadline = time.monotonic() + 2
    while made.bubbles[0].hidden == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert made.bubbles[0].hidden == 1


def test_a_few_seconds_uses_the_timer():
    q, made = quick()
    q.switch(agent(keep=FEW_SECONDS), True)
    q._serial = 1
    q.handle(agent(keep=FEW_SECONDS), 1, "Good morning", (0, 0, 0, 0))
    assert made.bubbles[0].stays[-1] is False


# ------------------------------------------------------- noticing highlights


def test_drag_and_double_click_count_as_highlights(monkeypatch):
    read = []
    w = SelectionWatcher(lambda text, rect: None)
    monkeypatch.setattr(w, "_read", lambda rect: read.append(rect))
    monkeypatch.setattr(threading, "Thread", lambda target, args, daemon: SimpleNamespace(
        start=lambda: target(*args)))
    left = SimpleNamespace(name="left")

    w._click(10, 10, left, True)
    w._click(200, 14, left, False)  # a drag
    assert read == [(10, 10, 200, 14)]

    w._click(300, 300, left, True)
    w._click(300, 300, left, False)  # a single click: nothing
    assert len(read) == 1
    w._click(300, 300, left, True)
    w._click(301, 300, left, False)  # the second click of a double click
    assert len(read) == 2

    w._click(5, 5, SimpleNamespace(name="right"), True)  # right button: ignored
    assert len(read) == 2
