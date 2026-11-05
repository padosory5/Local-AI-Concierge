import io
import json
import time

from concierge import accounts, cloud, usage
from concierge.accounts import CLAUDE_CODE, CODEX, Accounts, AppModel
from concierge.fake_engine import FakeEngine

# What Claude Code really sent for one short answer on a Pro plan (trimmed).
CLAUDE_EVENTS = [
    {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi there!"}}},
    {"type": "rate_limit_event", "rate_limit_info": {
        "status": "allowed", "resetsAt": 1793872200, "rateLimitType": "five_hour",
        "unifiedWindows": {"five_hour": {"utilization": 0.26, "resetsAt": 1793872200, "status": "allowed"},
                           "seven_day": {"utilization": 0.14, "resetsAt": 1794384000, "status": "allowed"}}}},
    {"type": "result", "is_error": False, "result": "Hi there!",
     "usage": {"input_tokens": 2, "cache_creation_input_tokens": 9399, "cache_read_input_tokens": 19771,
               "output_tokens": 7}},
]
BEFORE_RESETS = 1793860000  # an hour or so before the 5-hour window above starts again


class Process:
    def __init__(self, lines):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO("\n".join(json.dumps(line) for line in lines) + "\n")
        self.stderr = io.StringIO("")
        self.returncode = 0

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0

    def kill(self):
        pass


def app_answering(monkeypatch, tmp_path, app, lines):
    monkeypatch.setattr(accounts.subprocess, "Popen", lambda command, **kw: Process(lines))
    place = tmp_path / (".local/bin/claude.exe" if app == CLAUDE_CODE else ".codex/.sandbox-bin/codex.exe")
    place.parent.mkdir(parents=True)
    place.write_text("")
    return AppModel(Accounts(home=tmp_path), app, "the-model", "You are Elaina.")


def test_claude_codes_own_limits_and_tokens_are_kept(monkeypatch, tmp_path):
    model = app_answering(monkeypatch, tmp_path, CLAUDE_CODE, CLAUDE_EVENTS)
    assert "".join(model.chat("x", [{"role": "user", "content": "hi"}])) == "Hi there!"
    mine = usage.summary(now=BEFORE_RESETS)[CLAUDE_CODE]
    assert [(w["id"], w["used"]) for w in mine["limits"]] == [("five_hour", 0.26), ("seven_day", 0.14)]
    assert mine["limits"][0]["name"] == "Next 5 hours" and mine["limits"][1]["name"] == "This week"
    # Everything read counts, the cached part of Claude Code's own instructions too.
    assert mine["last"] == {"model": "the-model", "read": 2 + 9399 + 19771, "wrote": 7, "at": mine["last"]["at"]}


def test_codex_tokens_are_kept_and_limits_only_when_it_reports_them(monkeypatch, tmp_path):
    model = app_answering(monkeypatch, tmp_path, CODEX, [
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Hello."}},
        {"type": "turn.completed", "usage": {"input_tokens": 1200, "cached_input_tokens": 800, "output_tokens": 30}}])
    assert "".join(model.chat("x", [{"role": "user", "content": "hi"}])) == "Hello."
    mine = usage.summary()[CODEX]
    assert mine["limits"] == []  # nothing guessed
    assert (mine["today"]["read"], mine["today"]["wrote"], mine["today"]["answers"]) == (1200, 30, 1)


def test_codex_limits_are_read_when_they_come():
    limits = usage.codex_limits({"rate_limits": {
        "primary": {"used_percent": 42.0, "window_minutes": 300, "resets_at": 2000000000},
        "secondary": {"used_percent": 7.5, "window_minutes": 10080, "resets_in_seconds": 3600}}})
    assert [(w["id"], w["used"]) for w in limits] == [("five_hour", 0.42), ("seven_day", 0.075)]
    assert limits[1]["resets_at"] > time.time()


def test_a_window_that_started_again_shows_empty_not_stale():
    usage.record_limits(CLAUDE_CODE, [{"id": "five_hour", "used": 0.9, "resets_at": 1000}])
    window = usage.summary(now=2000)[CLAUDE_CODE]["limits"][0]
    assert window["used"] == 0 and window["resets_at"] == 0 and not window["nearly_full"]


def test_nearly_full_is_marked():
    usage.record_limits(CLAUDE_CODE, [{"id": "seven_day", "used": 0.85, "resets_at": 3000}])
    assert usage.summary(now=2000)[CLAUDE_CODE]["limits"][0]["nearly_full"]


def test_days_add_up_and_old_days_are_dropped():
    day = 86400
    start = time.mktime((2026, 11, 1, 12, 0, 0, 0, 0, -1))
    usage.record_tokens("anthropic", "Claude", 100, 10, when=start - 40 * day)
    usage.record_tokens("anthropic", "Claude", 100, 10, when=start - 3 * day)
    usage.record_tokens("anthropic", "Claude", 50, 5, when=start)
    usage.record_tokens("anthropic", "Claude", 50, 5, when=start + 60)
    mine = usage.summary(now=start + 120)["anthropic"]
    assert mine["today"] == {"read": 100, "wrote": 10, "answers": 2, "saved": 0}
    assert mine["week"] == {"read": 200, "wrote": 20, "answers": 3, "saved": 0}
    assert len(json.loads(usage.usage_path().read_text())["anthropic"]["days"]) == 2


def test_saved_counts_what_the_plans_app_reads_on_top_of_every_question():
    # Before any real answer from the plan, only what her model read and wrote counts.
    assert usage.saved_estimate("claude_code", 300, 40) == 340
    usage.record_tokens("claude_code", "m", 29_172, 7)
    usage.record_tokens("claude_code", "m", 31_000, 500)
    assert usage.saved_estimate("claude_code", 300, 40) == 29_172 + 40  # Claude Code's least, plus the answer
    assert usage.saved_estimate("claude_code", 0, 0) == 0  # nothing measured, nothing claimed
    usage.record_saved("claude_code", 29_212)
    usage.record_saved("claude_code", 0)
    mine = usage.summary()["claude_code"]
    assert mine["today"]["saved"] == mine["week"]["saved"] == 29_212
    assert mine["today"]["answers"] == 2  # saving isn't an answer from the plan


def test_ollama_reports_the_tokens_of_its_last_reply():
    from concierge.ollama import Ollama

    ollama = Ollama()
    ollama._stream = lambda path, body, timeout=None: iter([
        {"message": {"content": "Hi"}}, {"message": {"content": ""}, "done": True, "prompt_eval_count": 812, "eval_count": 9}])
    assert list(ollama.chat("m", [])) == ["Hi"] and ollama.last_tokens == (812, 9)


def test_api_replies_count_their_tokens():
    anthropic = cloud.Provider("anthropic", "Claude", "Anthropic", "anthropic", "https://a.test/v1", "", ())
    assert cloud.tokens_in(anthropic, {"type": "message_start", "message": {"usage": {
        "input_tokens": 12, "cache_read_input_tokens": 100, "output_tokens": 1}}}) == (112, 0)
    assert cloud.tokens_in(anthropic, {"type": "message_delta", "usage": {"output_tokens": 40}}) == (0, 40)
    assert cloud.tokens_in(anthropic, {"type": "content_block_delta", "delta": {"text": "hi"}}) == (0, 0)
    openai = cloud.Provider("openai", "ChatGPT", "OpenAI", "openai", "https://o.test/v1", "", ())
    assert cloud.tokens_in(openai, {"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 3}}) == (9, 3)
    assert cloud.request_for(openai, "m", "", [])[1]["stream_options"] == {"include_usage": True}
    other = cloud.Provider("xai", "Grok", "xAI", "openai", "https://x.test/v1", "", ())
    assert "stream_options" not in cloud.request_for(other, "m", "", [])[1]  # it might refuse it


def test_the_practice_app_counts_in_memory_only():
    engine = FakeEngine(delay=0)
    engine.menu.accounts.sign_in(CLAUDE_CODE)
    talker = engine.menu.accounts.talker(CLAUDE_CODE, "practice-1", "")
    list(talker.chat_parts())
    shown = engine.menu.usage()[CLAUDE_CODE]
    assert shown["today"]["answers"] == 1 and shown["limits"]
    assert not usage.usage_path().exists()
