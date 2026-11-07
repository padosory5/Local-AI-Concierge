import pytest

from concierge import safety
from concierge.agents import store
from concierge.agents.recipe import CUSTOM, IN_CHAT, WHILE_ON
from concierge.engine import NoirEngine
from concierge.events import NoirText, Thinking
from concierge.fake_engine import FakeEngine
from concierge.quick import spot
from concierge.quick.spot import DoubleTap, actions_for, job, kind_of
from concierge.ui.window import SPOT_WIDTH, SpotBridge, place_spot


def words(found):
    return [action["words"] for action in found]


LONG_WRITING = ("hey can u send me that report asap, its late and the boss keeps asking about it every single morning "
                "and i really need it before the meeting")
LONG_READING = "Cells keep their balance through osmosis. " * 10


def test_your_own_writing_gets_polish_and_shorter():
    assert words(actions_for(LONG_WRITING, True, home="Korean")) == ["Polish it", "Make it shorter", "Translate to Korean"]


def test_something_you_read_gets_explain_and_sum_up():
    assert words(actions_for(LONG_READING, False, home="Korean")) == ["Explain simply", "Sum it up", "Translate to Korean"]


def test_short_text_isnt_offered_summing_up_or_shortening():
    """Summing up one sentence gave three bullet points about it."""
    assert words(actions_for("Cells keep their balance.", False, home="Korean")) == ["Explain simply", "Translate to Korean"]
    assert words(actions_for("hey send it", True, home="Korean")) == ["Polish it", "Translate to Korean"]


def test_text_already_in_your_language_is_offered_in_english():
    assert words(actions_for("오늘 회의는 세 시에 시작합니다", True, home="Korean"))[-1] == "Translate to English"


def test_english_on_an_english_computer_has_no_translate_button():
    assert "Translate" not in " ".join(words(actions_for("Please send the report.", True, home="English")))


def test_an_error_message_gets_what_it_means():
    found = actions_for("Traceback (most recent call last):\n  File \"a.py\"", False, home="English")
    assert words(found)[0] == "What this error means"


def test_code_gets_explain_and_find_problems():
    assert words(actions_for("def f(x):\n    return x == 1;\n}", True, home="English")) == [
        "Explain this code", "Find problems"]


def test_nothing_highlighted_means_only_the_line_to_type_on():
    assert actions_for("   ", True) == [] and kind_of("", True) == spot.NOTHING


def test_the_users_own_chat_agents_come_after_the_usual_ones():
    found = actions_for("me and him goes", True, [("Grammar Fixer", "Fix the grammar.")], home="Korean")
    assert found[-1] == {"id": "helper:Grammar Fixer", "words": "Grammar Fixer"}


def test_each_button_has_its_own_job():
    assert job("polish", "", "hi")[0].startswith("Rewrite the text so it reads clearly")
    assert job("translate:Korean", "", "hi")[0] == "Translate the text into Korean."
    assert job("helper:Grammar Fixer", "", "hi", [("Grammar Fixer", "Fix the grammar.")]) == ("Fix the grammar.", "hi")
    assert job("ask", "make it funny", "hi") == ("Do this with the text: make it funny", "hi")


def test_with_nothing_highlighted_what_is_typed_is_the_request():
    assert job("ask", "a thank-you note for my teacher", "") == (spot.WRITE_FOR_ME, "a thank-you note for my teacher")


def test_an_unknown_button_is_refused():
    with pytest.raises(ValueError):
        job("format c:", "", "hi")


def test_very_long_highlights_are_cut():
    assert len(job("polish", "", "x" * 10000)[1]) == spot.MAX_SPOT_CHARS


class Ctrl:
    name = "ctrl_l"


class Letter:
    name = None


def tapper():
    taps, now = [], [0.0]
    watch = DoubleTap(lambda: taps.append(True), clock=lambda: now[0])
    watch.on_tap = lambda: taps.append(True)

    def press(key, at):
        now[0] = at
        watch.pressed(key)

    def release(key, at):
        now[0] = at
        watch.released(key)

    return taps, press, release, watch


def run_tap(monkeypatch):
    # The real one starts a thread; here the call happens at once.
    monkeypatch.setattr(spot.threading, "Thread", lambda target, **kw: type("T", (), {"start": lambda self: target()})())


def test_two_quick_taps_open_it(monkeypatch):
    run_tap(monkeypatch)
    taps, press, release, _ = tapper()
    press(Ctrl, 0.0), release(Ctrl, 0.08), press(Ctrl, 0.2), release(Ctrl, 0.28)
    assert taps == [True]


def test_two_slow_taps_dont(monkeypatch):
    run_tap(monkeypatch)
    taps, press, release, _ = tapper()
    press(Ctrl, 0.0), release(Ctrl, 0.08), press(Ctrl, 1.0), release(Ctrl, 1.08)
    assert taps == []


def test_ctrl_c_twice_doesnt(monkeypatch):
    run_tap(monkeypatch)
    taps, press, release, _ = tapper()
    for start in (0.0, 0.2):
        press(Ctrl, start), press(Letter, start + 0.02), release(Letter, start + 0.04), release(Ctrl, start + 0.06)
    assert taps == []


def test_holding_ctrl_doesnt(monkeypatch):
    run_tap(monkeypatch)
    taps, press, release, _ = tapper()
    press(Ctrl, 0.0), release(Ctrl, 0.08), press(Ctrl, 0.15), release(Ctrl, 0.9)
    assert taps == []


def test_three_taps_open_it_only_once(monkeypatch):
    run_tap(monkeypatch)
    taps, press, release, _ = tapper()
    for start in (0.0, 0.15, 0.3):
        press(Ctrl, start), release(Ctrl, start + 0.05)
    assert taps == [True]


def test_the_spot_sits_under_the_highlight_and_moves_above_near_the_bottom():
    work = (0, 0, 1600, 900)
    assert place_spot(200, (300, 100, 120), work) == (300, 130)
    assert place_spot(200, (300, 800, 820), work) == (300, 590)
    assert place_spot(200, (1500, 100, 120), work)[0] == 1600 - SPOT_WIDTH


class LocalOnly:
    """Its own model on this computer. The Spot must use nothing else."""

    def __init__(self):
        self.asked = []

    def chat(self, model, messages, think=None, options=None, keep_alive=None):
        self.asked.append((model, messages))
        return iter(["Could you send the report?"])


def test_the_spot_always_runs_on_her_own_model(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    local = LocalOnly()
    engine = NoirEngine(local)
    engine.chat = type("Chat", (), {"think": None, "talker": object()})()  # a cloud model picked in the menu
    assert engine.spot_run("polish", "hey send report", "") == {"text": "Could you send the report?"}
    assert local.asked and local.asked[0][0] == "noir"


def test_the_spot_offers_chat_agents_but_not_highlight_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    store.save(store.Agent("Grammar Fixer", CUSTOM, {"instruction": "Fix it.", "when": IN_CHAT}))
    store.save(store.Agent("Korean translator", CUSTOM, {"instruction": "Translate.", "when": WHILE_ON}))
    found = words(NoirEngine(LocalOnly()).spot_actions("me and him goes", True))
    assert "Grammar Fixer" in found and "Korean translator" not in found


def test_nothing_to_work_on_is_said_plainly(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    assert "Highlight something" in NoirEngine(LocalOnly()).spot_run("polish", "  ", "")["error"]


def test_the_practice_spot_answers_without_a_model():
    reply = FakeEngine(delay=0).spot_run("polish", "hey", "")
    assert reply["text"].startswith("Practice")


def test_the_spot_page_sees_only_its_own_calls():
    assert {name for name in dir(SpotBridge(None)) if not name.startswith("_")} == {"run", "put_back", "fit", "close"}


@pytest.mark.parametrize("text", ["I want to kill myself", "sometimes I think about suicide", "요즘 죽고 싶어",
                                  "자해를 했어"])
def test_crisis_words_get_the_fixed_reply_with_numbers_to_call(text):
    assert safety.crisis(text)
    reply = safety.crisis_reply(text)
    assert "109" in reply


@pytest.mark.parametrize("text", ["this bug is killing me", "I died laughing", "kill the process", "죽이는 맛집"])
def test_ordinary_words_are_not_a_crisis(text):
    assert not safety.crisis(text)


def test_the_crisis_reply_comes_before_anything_else(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    engine = NoirEngine(LocalOnly())
    engine.builder = engine.planner = None  # never reached
    events = list(engine._handle("I want to end my life"))
    assert isinstance(events[0], Thinking)
    said = "".join(event.text for event in events if isinstance(event, NoirText))
    assert said == safety.CRISIS_REPLY


def test_health_and_money_answers_get_a_plain_note():
    assert safety.caution("what dose of ibuprofen can I take?") == safety.HEALTH_NOTE
    assert safety.caution("should I buy this stock?") == safety.MONEY_NOTE
    assert safety.caution("what's a good name for a cat?") == ""
