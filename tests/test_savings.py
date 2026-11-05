"""A cloud model is picked, but jobs a small model does well stay on this computer,
and what that kept off the user's plan is counted (savings.py)."""

import pytest

from concierge import activity, elaina, savings
from concierge.agents import store
from concierge.agents.router import Route
from concierge.conversations import ChatBook
from concierge.engine import ElainaEngine
from concierge.events import ElainaText, Thinking
from concierge.fake_engine import FakeEngine


@pytest.mark.parametrize("text, job", [
    ("Translate this into Korean: see you tomorrow", "translate"),
    ("번역해줘: see you tomorrow", "translate"),
    ("Summarize this article for me: ...", "sum up"),
    ("Fix the grammar: me and him goes to school", "rewrite"),
    ("Make it shorter: we would like to kindly inform you...", "rewrite"),
    ("What does osmosis mean?", "explain"),
    ("Explain this paragraph in simple words: ...", "explain"),
])
def test_jobs_on_the_users_own_text_stay_on_this_computer(text, job):
    assert savings.local_job(text) == job


@pytest.mark.parametrize("text", [
    "How do I translate a PDF in Word?",  # a how-to, not a translation
    "What's the capital of Peru?",  # a fact: a small model guesses at those
    "Should I learn Python or Rust?",  # advice
    "Why does this code throw a KeyError?",  # code
    "Plan a three-day trip to Busan",
    "Tell me about yourself",  # plain chat with nothing to work on
])
def test_everything_else_goes_to_the_picked_model(text):
    assert savings.local_job(text) == ""


def test_tokens_are_estimated_by_script():
    assert savings.tokens_in("hello world") == 3  # about four letters a token
    assert savings.tokens_in("안녕하세요") == 5  # about one a character
    assert savings.tokens_in("") == 0


def test_what_a_cloud_call_would_take_counts_everything_sent_and_the_answer():
    messages = [{"role": "user", "content": "x" * 400}, {"role": "assistant", "content": "y" * 200}]
    assert savings.kept(messages, system="z" * 80) == 100 + 50 + 20 + savings.GUIDE_TOKENS


class Ollama:
    """Her own model: answers in Korean, like a translator would."""

    def __init__(self):
        self.asked = 0

    def chat(self, model, messages, think=None, options=None, keep_alive=None):
        self.asked += 1
        return iter(["내일 봐요."])

    def capabilities(self, name):
        return ["completion"]

    def show(self, name):
        return {"system": "You are Elaina."}

    def models(self):
        return []

    def refresh(self, *args):
        pass


class Cloud(Ollama):
    """The picked model, which must only be asked when it's really needed."""

    def chat(self, model, messages, think=None, options=None, keep_alive=None):
        self.asked += 1
        return iter(["The cloud's answer."])


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    monkeypatch.setattr(elaina, "data_dir", lambda: tmp_path)
    monkeypatch.setattr("concierge.engine.route", lambda *args, **kwargs: Route("chat"))
    made = ElainaEngine(Ollama())
    made.book = ChatBook(None)
    made.chat = elaina.ElainaChat(made.ollama)
    from concierge.agents.builder import AgentBuilder
    from concierge.agents.planner import IdeaPlanner
    made.builder = AgentBuilder(made.ollama, "elaina", None, made.blueprints)
    made.planner = IdeaPlanner(made.ollama, "elaina", None, lambda: None, made.blueprints)
    return made


def pick_cloud(engine, monkeypatch, cloud):
    monkeypatch.setattr(engine.menu, "chosen", lambda: {"provider": "anthropic", "model": "claude", "name": "Claude Sonnet 5.5",
                                                        "company": "Anthropic", "here": False})
    monkeypatch.setattr(engine.menu, "talker", lambda system: cloud)
    engine._use_chosen_model()


def words(events):
    return "".join(e.text for e in events if isinstance(e, ElainaText))


def thoughts(events):
    return [e.text for e in events if isinstance(e, Thinking)]


def test_a_translation_is_done_here_and_what_it_kept_is_counted(engine, monkeypatch):
    cloud = Cloud()
    pick_cloud(engine, monkeypatch, cloud)
    events = list(engine.send("Translate this into Korean: see you tomorrow"))
    assert "I can translate this myself, so Claude Sonnet 5.5 isn't needed." in thoughts(events)
    assert words(events) == "내일 봐요."
    assert cloud.asked == 0 and engine.ollama.asked == 1
    assert engine.chat.talker is cloud  # back to the picked model for the next message
    saved = engine.after_answer("내일 봐요.")["saved"]
    assert saved["model"] == "Claude Sonnet 5.5" and saved["tokens"] > savings.GUIDE_TOKENS
    assert activity.this_week()["saved"] == saved["tokens"]
    assert "You are Elaina." not in words(events)  # the persona only counts, it isn't shown


def test_a_question_that_needs_the_big_model_still_goes_there(engine, monkeypatch):
    cloud = Cloud()
    pick_cloud(engine, monkeypatch, cloud)
    events = list(engine.send("What's the capital of Peru?"))
    assert words(events) == "The cloud's answer." and cloud.asked == 1
    assert engine.after_answer("The cloud's answer.")["saved"] is None
    assert "saved" not in activity.this_week()


def test_ask_the_picked_model_instead_sends_the_same_question_there(engine, monkeypatch):
    cloud = Cloud()
    pick_cloud(engine, monkeypatch, cloud)
    list(engine.send("Translate this into Korean: see you tomorrow"))
    assert engine.follow_up_words("cloud") == "Ask Claude Sonnet 5.5 instead."
    events = list(engine.follow_up("cloud"))
    assert cloud.asked == 1 and words(events) == "The cloud's answer."
    assert engine.chat.history[-2]["content"] == "Translate this into Korean: see you tomorrow"
    assert engine.after_answer("The cloud's answer.")["saved"] is None
    assert list(engine.follow_up("cloud")) == []  # nothing left to send on


def test_shorter_and_more_stay_where_the_answer_was_made(engine, monkeypatch):
    cloud = Cloud()
    pick_cloud(engine, monkeypatch, cloud)
    list(engine.send("Translate this into Korean: see you tomorrow"))
    list(engine.follow_up("shorter"))
    assert cloud.asked == 0 and engine.ollama.asked == 2
    assert engine.after_answer("내일 봐요.")["saved"] is not None
    list(engine.send("What's the capital of Peru?"))
    list(engine.follow_up("more"))
    assert cloud.asked == 2


def test_with_her_own_model_nothing_is_saved_or_said_about_it(engine):
    events = list(engine.send("Translate this into Korean: see you tomorrow"))
    assert "This is just a chat, so I'll answer it myself." in thoughts(events)
    assert engine.after_answer("내일 봐요.")["saved"] is None
    assert "saved" not in activity.this_week()


def test_the_practice_app_shows_the_saved_line_once_a_cloud_model_is_picked():
    fake = FakeEngine(delay=0)
    fake.menu.keys.save_key("anthropic", "practice-key")
    fake.menu.pick("anthropic", "claude-sonnet-5-5")
    events = list(fake.send("Translate this into Korean: see you tomorrow"))
    reply = words(events)
    assert "Claude Sonnet 5.5 would stay out of it" in reply
    assert fake.after_answer(reply)["saved"] == {"tokens": 640, "model": "Claude Sonnet 5.5"}
    assert fake.follow_up_words("cloud") == "Ask Claude Sonnet 5.5 instead."
    assert "Claude Sonnet 5.5" in words(fake.follow_up("cloud"))
    assert fake.activity()["saved"] == 12400
