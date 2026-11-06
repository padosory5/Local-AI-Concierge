"""A research job (researcher.py): the plan model plans and merges, her own model reads
each page, every step is said with its tokens, and the saving is counted from measured
numbers."""

import json

import pytest

from concierge import elaina, research, researcher, usage
from concierge.agents import store
from concierge.agents.router import Route
from concierge.conversations import ChatBook
from concierge.engine import ElainaEngine
from concierge.events import ElainaDone, ElainaText, Error, Thinking
from tests.test_chat_path import Ollama


def test_code_knows_a_research_request():
    for text in ("research the newest local AI apps for Windows", "can you look into Python 3.15 for me",
                 "write me a report on electric bikes in Seoul", "deep dive on Hallasan hiking", "전기차 보조금 조사해줘"):
        assert researcher.wants_research(text), text
    for text in ("what's the weather in Seoul", "bitcoin price", "explain gravity", "hey how are you"):
        assert not researcher.wants_research(text), text


def test_the_plan_is_a_form_her_model_fills_or_the_question_itself():
    asked = []
    filled = {"queries": ["python 3.15 release", "python 3.15 new features", ""], "goal": "What is new."}
    queries, goal = researcher.plan(lambda system, user, schema: asked.append((system, user, schema)) or filled,
                                    "what's new in python 3.15")
    assert queries == ["python 3.15 release", "python 3.15 new features"] and goal == "What is new."
    assert asked[0][1] == "what's new in python 3.15" and asked[0][2] is researcher.PLAN_SCHEMA
    assert "2 to 4 short search queries" in asked[0][0]
    # A model without forced schemas may answer with JSON in text; nothing usable means the question.
    as_text = '```json\n{"queries": ["a", "b"], "goal": "g"}\n```'
    assert researcher.plan(lambda s, u, schema: as_text, "q") == (["a", "b"], "g")
    assert researcher.plan(lambda s, u, schema: "Sure, some ideas.", "the question") == (["the question"], "the question")


def test_the_planner_is_told_the_date_and_stale_years_are_corrected():
    asked = []
    filled = {"queries": ["Seattle housing market 2024 median price", "Seattle real estate trends Q1 2024"], "goal": "g"}
    queries, _ = researcher.plan(lambda s, u, schema: asked.append(s) or filled, "report on the Seattle housing market right now",
                                 today="Friday 2026-11-06")
    assert asked[0].startswith("Today is Friday 2026-11-06.") and "means 2026, never an older year" in asked[0]
    assert queries == ["Seattle housing market 2026 median price", "Seattle real estate trends Q1 2026"]
    # A year the user named stays; a future year stays.
    assert researcher.fresh_queries(["python 2024 features"], "what came out in 2024", 2026) == ["python 2024 features"]
    assert researcher.fresh_queries(["world cup 2030 hosts"], "world cup hosts", 2026) == ["world cup 2030 hosts"]


def test_gather_reads_pages_once_each_and_skips_what_it_cannot_read():
    rows = {"q1": [{"title": "A", "href": "https://a.example.com", "body": "about the question"},
                   {"title": "P", "href": "https://p.example.com/x.pdf", "body": "about the question"},
                   {"title": "B", "href": "https://b.example.com", "body": "about the question"},
                   {"title": "C", "href": "https://c.example.com", "body": "about the question"}],
            "q2": [{"title": "A", "href": "https://a.example.com", "body": "about the question"},
                   {"title": "D", "href": "https://d.example.com", "body": "about the question, snippet only"}]}
    long = "Words of the page about the question. " * 20
    pages, choices = researcher.gather("the question", ["q1", "q2"], search=lambda q: rows[q],
                                       read=lambda url: "" if "d.example" in url else long + url)
    assert [page.site for page in pages] == ["a.example.com", "b.example.com", "c.example.com"]  # no PDF, no repeat
    thin = next(c for c in choices if c.site == "d.example.com")
    assert not thin.picked and thin.why_not.startswith("the page wouldn't open")  # a thin page is swapped out, never read
    # At most two pages from one site, so a brief never leans on a single source.
    same = [{"title": f"S{i}", "href": f"https://same.example.com/{i}", "body": "s"} for i in range(4)]
    pages, choices = researcher.gather("q", ["q1", "q2"], search=lambda q: same, read=lambda url: long)
    assert len(pages) == 2 and sum(1 for c in choices if c.why_not == "a third page from the same site") == 2
    # A search the burst refused is retried alone only when too few answered.
    calls = []

    def flaky(q):
        calls.append(q)
        if q == "bad" and calls.count("bad") == 1:
            raise OSError("refused")
        return [{"title": q, "href": f"https://{q}.example.com", "body": q}]

    researcher.gather("q", ["bad", "fine"], search=flaky, read=lambda url: long)
    assert calls.count("bad") == 2  # only one of two answered, so "bad" was tried again
    calls.clear()
    researcher.gather("q", ["ok1", "ok2", "bad"], search=flaky, read=lambda url: long)
    assert calls.count("bad") == 1  # two answered: enough, no retry


class Worker(Ollama):
    def chat(self, model, messages, think=None, options=None, keep_alive=None):
        self.asked += 1
        self.last_tokens = (812, 60)
        page = messages[-1]["content"]
        return iter(["NOTHING RELEVANT"] if "empty" in page else ["- Python 3.15.2 was released on 25 October 2026.\n- It is a security release."])

    def chat_json(self, model, messages, schema, think=None, keep_alive=None):
        self.last_tokens = (300, 40)
        return {"queries": ["python 3.15 release", "python 3.15 features"], "goal": "What is new."}


def test_a_worker_summarises_one_page_with_its_tokens():
    own = Worker()
    page = researcher.summarise(own, "elaina", "what's new in python", researcher.Page("https://python.org/x", "T", "Page words"))
    assert page.useful and page.summary.startswith("- Python 3.15.2") and (page.read, page.wrote) == (812, 60)
    assert "PAGE (python.org)" in own.sent_pages()[0] if hasattr(own, "sent_pages") else True
    nothing = researcher.summarise(own, "elaina", "q", researcher.Page("https://e.example.com", "", "empty page"))
    assert not nothing.useful


def test_the_saving_is_counted_from_the_plans_own_measured_overhead(monkeypatch):
    monkeypatch.setattr(usage, "saved_estimate", lambda source, read, wrote: 18000 + read + wrote)  # Claude Code's measured 18k
    account = researcher.Account(source="claude_code", plan_calls=2, plan_read=40000, plan_wrote=900,
                                 local_calls=4, local_read=3200, local_wrote=240)
    researcher.settle(account, "research python 3.15")
    assert account.plan_tokens == 40900
    assert account.if_all_plan == 40900 + 4 * (18000 + 800 + 60)  # each local step as one plan call
    assert account.saved == 4 * 18860 and account.single_ask == 18000 + 5 + 400
    lines = researcher.account_lines(account, "Claude Opus 5.5", "Qwen 3.5 4B")
    assert lines[0].startswith("Tokens on your plan: 2 calls to Claude Opus 5.5, 40,000 read and 900 written")
    assert "Saved about 75,440 tokens" in lines[3]
    alone = researcher.account_lines(researcher.Account(local_calls=6, local_read=5000, local_wrote=600), "Qwen", "Qwen")
    assert alone == ["Tokens: Qwen did every step on this computer, 6 calls, 5,000 read and 600 written. Nothing went to a plan."]


class Plan:
    """A plan model: it only ever gets the merge call, and answers with the brief."""

    def __init__(self):
        self.calls = []

    def chat(self, model, messages, think=None, options=None, keep_alive=None):
        self.calls.append((model, messages))
        text = messages[-1]["content"]
        assert "SUMMARIES:" in text and "[1] python.org" in text
        return iter(["Python 3.15.2 is the newest release, out on 25 October 2026 (python.org).\n- **Security release:** it fixes two issues.\n"])


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    monkeypatch.setattr(elaina, "data_dir", lambda: tmp_path)
    monkeypatch.setattr("concierge.engine.route", lambda *args, **kwargs: Route("chat"))
    monkeypatch.setattr(research, "model_form", lambda ollama, model: lambda text: False)
    elaina.save_state({"base_model": "qwen3.5:4b"})  # so her model has its name in the steps
    made = ElainaEngine(Worker())
    made.book = ChatBook(None)
    made.chat = elaina.ElainaChat(made.ollama)
    from concierge.agents.builder import AgentBuilder
    from concierge.agents.planner import IdeaPlanner
    made.builder = AgentBuilder(made.ollama, "elaina", None, made.blueprints)
    made.planner = IdeaPlanner(made.ollama, "elaina", None, lambda: None, made.blueprints)
    return made


PAGES = [researcher.Page("https://www.python.org/downloads/", "Downloads", "Python 3.15.2 words"),
         researcher.Page("https://blog.python.org/", "Blog", "empty words")]


def test_the_job_runs_plan_workers_merge_and_counts_the_saving(engine, monkeypatch):
    research.allow(True)
    plan = Plan()
    engine.auto_cloud = plan
    engine.talker_name = "Claude Opus 5.5"
    engine.menu.chosen = lambda: {"provider": "auto", "name": "Auto", "cloud": {"provider": "claude_code", "model": "opus"}}
    engine.menu.fast_talker = lambda system: None  # no faster model on this plan: the picked one merges
    monkeypatch.setattr(researcher, "gather", lambda question, queries, judge=None: ([researcher.Page(p.url, p.title, p.text) for p in PAGES], []))
    monkeypatch.setattr(researcher, "plan_tokens_after", lambda source, before: (19000, 150))
    monkeypatch.setattr(usage, "saved_estimate", lambda source, read, wrote: 18000 + read + wrote)
    events = list(engine.send("research what's new in python 3.15"))
    steps = [e.text for e in events if isinstance(e, Thinking)]
    assert steps[0].startswith("Research job: Qwen 3.5 4B plans the searches and reads each page on this computer, then Claude Opus 5.5 merges")
    assert steps[1] == "Qwen 3.5 4B asked for 2 searches: python 3.15 release; python 3.15 features. Goal: What is new."
    assert steps[2].startswith("Worker 1 (Qwen 3.5 4B) read python.org: 812 tokens in, 60 out. - Python 3.15.2 was released")
    assert steps[3].endswith("Nothing relevant on that page.")
    assert steps[4] == "Claude Opus 5.5 merges 1 summaries, checks them against each other and writes the brief."
    assert steps[5].startswith("Tokens on your plan: 1 call to Claude Opus 5.5, 19,000 read and 150 written, 19,150 in all.")
    assert steps[6].startswith("On this computer: 3 calls to Qwen 3.5 4B, 1,924 read and 160 written, free.")
    assert "Saved about" in steps[8]
    assert not [e for e in events if isinstance(e, Error)]
    assert "".join(e.text for e in events if isinstance(e, ElainaText)).startswith("Python 3.15.2 is the newest release")
    done = next(e for e in events if isinstance(e, ElainaDone))
    assert done.by == "Claude Opus 5.5" and done.where == "cloud" and done.saved == 3 * (18000 + 641 + 53)
    assert [s.path for s in done.sources] == ["https://www.python.org/downloads/"]  # only the page that said something
    assert len(plan.calls) == 1 and plan.calls[0][1][0]["role"] == "user"  # one plan call, the note in the question
    assert engine.chat.history[-1]["content"].startswith("Python 3.15.2 is the newest release")  # remembered for follow-ups


def test_with_auto_the_plans_fast_model_merges(engine, monkeypatch):
    research.allow(True)
    slow, fast = Plan(), Plan()
    engine.auto_cloud = slow
    engine.talker_name = "Claude Opus 5.5"
    engine.menu.chosen = lambda: {"provider": "auto", "name": "Auto", "cloud": {"provider": "claude_code", "model": "opus"}}
    engine.menu.fast_talker = lambda system: (fast, {"provider": "claude_code", "model": "claude-sonnet-5-5",
                                                     "name": "Claude Sonnet 5.5", "company": "Anthropic", "here": False})
    monkeypatch.setattr(researcher, "gather", lambda question, queries, judge=None: ([researcher.Page(p.url, p.title, p.text) for p in PAGES[:1]], []))
    monkeypatch.setattr(researcher, "plan_tokens_after", lambda source, before: (12000, 150))
    events = list(engine.send("research what's new in python 3.15"))
    steps = [e.text for e in events if isinstance(e, Thinking)]
    assert "then Claude Sonnet 5.5 merges" in steps[0]
    assert len(fast.calls) == 1 and fast.calls[0][0] == "claude-sonnet-5-5" and slow.calls == []
    assert next(e for e in events if isinstance(e, ElainaDone)).by == "Claude Sonnet 5.5"


def test_the_menu_finds_the_plans_fast_model_only_under_auto():
    from concierge.models import ModelMenu

    class Accounts:
        def __init__(self):
            self.made = []

        def status(self, app, fresh=False):
            return {"id": app, "signed_in": True, "plan": "your Claude plan", "app": "Claude Code",
                    "models": [{"id": "claude-opus-5-5", "name": "Claude Opus 5.5"},
                               {"id": "claude-sonnet-5-5", "name": "Claude Sonnet 5.5"}]}

        def overview(self, fresh=False):
            return [self.status("claude_code")]

        def talker(self, app, model, system):
            self.made.append((app, model, system))
            return ("talker", model)

    state = {"talk_model": {"provider": "auto", "model": ""}, "auto_cloud": {"provider": "claude_code", "model": "claude-opus-5-5"}}
    accounts = Accounts()
    menu = ModelMenu(None, lambda: (None, 0.0), load=lambda: dict(state), save=lambda new: state.update(new), accounts=accounts)
    talker, found = menu.fast_talker("You are Elaina.")
    assert talker == ("talker", "claude-sonnet-5-5") and found["name"] == "Claude Sonnet 5.5"
    assert accounts.made[0][2].startswith("You are Elaina.\n\nRight now your answers are written by Claude Sonnet 5.5")
    # Picked on purpose: used as it is. Sonnet already: nothing faster. Auto off: none.
    state["auto_cloud"] = {"provider": "claude_code", "model": "claude-sonnet-5-5"}
    assert menu.fast_talker("") is None
    state["talk_model"] = {"provider": "claude_code", "model": "claude-opus-5-5"}
    assert menu.fast_talker("") is None


def test_with_no_plan_her_own_model_does_every_step(engine, monkeypatch):
    research.allow(True)
    engine.menu.chosen = lambda: None
    monkeypatch.setattr(researcher, "gather", lambda question, queries, judge=None: ([researcher.Page(p.url, p.title, p.text) for p in PAGES[:1]], []))
    events = list(engine.send("look into python 3.15 for me"))
    steps = [e.text for e in events if isinstance(e, Thinking)]
    assert steps[0].startswith("Research job with no plan connected, so Qwen 3.5 4B does every step")
    done = next(e for e in events if isinstance(e, ElainaDone))
    assert done.where == "here" and done.saved == 0 and done.by == "Qwen 3.5 4B"
    assert steps[-1].startswith("Tokens: Qwen 3.5 4B did every step on this computer, 3 calls")
