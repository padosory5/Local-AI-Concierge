import io
import json
import subprocess

import pytest

from concierge import accounts, cloud
from concierge.accounts import CLAUDE_CODE, CODEX, Accounts, AppModel, transcript
from concierge.cloud import CloudError
from concierge.fake_engine import FakeEngine
from concierge.models import ModelMenu


@pytest.fixture(autouse=True)
def nothing_on_the_path(monkeypatch, tmp_path):
    monkeypatch.setattr(accounts.shutil, "which", lambda name: None)
    monkeypatch.setattr(cloud, "_sent_path", lambda: tmp_path / "sent.json")


def codex_here(home):
    program = home / ".codex" / ".sandbox-bin" / "codex.exe"
    program.parent.mkdir(parents=True)
    program.write_text("")
    return program


def runner(signed_in=True):
    """Stands in for Codex's own commands: login status and its model list."""
    def run(command, **kwargs):
        if command[1:] == ["login", "status"]:
            return subprocess.CompletedProcess(command, 0 if signed_in else 1, "Logged in using ChatGPT" if signed_in else "Not logged in", "")
        models = {"models": [{"slug": "gpt-hidden", "visibility": "hide"},
                             {"slug": "gpt-5.6-luna", "display_name": "GPT-5.6-Luna", "visibility": "list"}]}
        return subprocess.CompletedProcess(command, 0, json.dumps(models), "")
    return run


def test_a_signed_in_codex_offers_only_the_models_it_lists(tmp_path):
    codex_here(tmp_path)
    status = Accounts(run=runner(), home=tmp_path).status(CODEX)
    assert status["installed"] and status["signed_in"]
    assert status["models"] == [{"id": "gpt-5.6-luna", "name": "GPT-5.6-Luna"}]


def test_not_installed_or_not_signed_in_says_so(tmp_path):
    assert Accounts(run=runner(), home=tmp_path).status(CODEX)["installed"] is False
    codex_here(tmp_path)
    assert Accounts(run=runner(signed_in=False), home=tmp_path).status(CODEX)["signed_in"] is False
    claude = Accounts(home=tmp_path).status(CLAUDE_CODE)
    assert claude["installed"] is False and claude["models"] == []


def test_claude_code_says_itself_whether_it_is_signed_in(tmp_path):
    program = tmp_path / ".local" / "bin" / "claude.exe"
    program.parent.mkdir(parents=True)
    program.write_text("")
    asked = []

    def run(command, **kwargs):
        asked.append(command[1:])
        return subprocess.CompletedProcess(command, 0, json.dumps({"loggedIn": True, "authMethod": "claude.ai"}), "")

    status = Accounts(run=run, home=tmp_path).status(CLAUDE_CODE)
    assert asked == [["auth", "status", "--json"]]
    assert status["signed_in"] and status["models"][0] == {"id": "claude-opus-5-5", "name": "Claude Opus 5.5"}


def test_signing_in_opens_the_apps_own_sign_in_where_it_can_be_seen(tmp_path):
    opened = []
    codex_here(tmp_path)
    Accounts(popen=lambda command, **kw: opened.append(command), home=tmp_path).sign_in(CODEX)
    assert opened[0][1:] == ["login"]
    claude = tmp_path / ".local" / "bin" / "claude.exe"
    claude.parent.mkdir(parents=True)
    claude.write_text("")
    Accounts(popen=lambda command, **kw: opened.append(command), home=tmp_path).sign_in(CLAUDE_CODE)
    assert opened[1][1:] == ["auth", "login", "--claudeai"]  # straight to Anthropic's page, no setup questions
    with pytest.raises(CloudError, match="isn't installed"):
        Accounts(popen=lambda command, **kw: opened.append(command), home=tmp_path / "empty").sign_in(CLAUDE_CODE)


class Process:
    """Stands in for a running Codex or Claude Code: prints the given lines."""

    def __init__(self, lines, code=0, problem=""):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO("\n".join(json.dumps(line) for line in lines) + "\n")
        self.stderr = io.StringIO(problem)
        self.returncode = code

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        pass


def answer_with(monkeypatch, tmp_path, app, lines, code=0):
    started = []
    monkeypatch.setattr(accounts.subprocess, "Popen", lambda command, **kw: started.append((command, kw)) or Process(lines, code))
    if app == CODEX:
        codex_here(tmp_path)
    else:
        program = tmp_path / ".local" / "bin" / "claude.exe"
        program.parent.mkdir(parents=True)
        program.write_text("")
    model = AppModel(Accounts(home=tmp_path), app, "the-model", "You are Noir.")
    return model, started


def test_codex_answers_are_read_and_it_can_change_nothing(monkeypatch, tmp_path):
    model, started = answer_with(monkeypatch, tmp_path, CODEX, [
        {"type": "item.completed", "item": {"type": "error", "message": "a warning on the side"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Hello from your plan."}}])
    assert "".join(model.chat("x", [{"role": "user", "content": "hi"}])) == "Hello from your plan."
    command, settings = started[0]
    assert command[command.index("-s") + 1] == "read-only" and "--ephemeral" in command
    assert command[command.index("-C") + 1] == settings["cwd"]  # an empty folder of its own


def test_a_refusal_from_openai_is_said_plainly(monkeypatch, tmp_path):
    wrapped = json.dumps({"error": {"message": "The 'x' model is not supported when using Codex with a ChatGPT account."}})
    model, _ = answer_with(monkeypatch, tmp_path, CODEX, [{"type": "turn.failed", "error": {"message": wrapped}}])
    with pytest.raises(CloudError, match="ChatGPT couldn't answer through Codex: The 'x' model is not supported"):
        list(model.chat("x", [{"role": "user", "content": "hi"}]))


def test_claude_code_streams_pieces_and_has_no_tools_that_change_things(monkeypatch, tmp_path):
    delta = lambda text: {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}}
    model, started = answer_with(monkeypatch, tmp_path, CLAUDE_CODE, [delta("Hel"), delta("lo"), {"type": "result", "result": "Hello"}])
    assert list(model.chat("x", [{"role": "user", "content": "hi"}])) == ["Hel", "lo"]
    command = started[0][0]
    assert "Bash" in command[command.index("--disallowedTools") + 1] and command[command.index("--model") + 1] == "the-model"
    assert command[command.index("--system-prompt") + 1] == "You are Noir."


def test_the_conversation_goes_as_one_question():
    said = transcript([{"role": "user", "content": "My cat is Mochi."}, {"role": "assistant", "content": "Lovely!"},
                       {"role": "user", "content": "What's her name?"}])
    assert "User: My cat is Mochi." in said and "You: Lovely!" in said and said.endswith("What's her name?")


def test_a_plan_picked_in_the_menu_answers_and_falls_back_when_signed_out():
    fake = FakeEngine(delay=0)
    menu = fake.menu
    assert menu.pick("codex", "practice-1")["current"] is None  # not signed in yet: its own model
    menu.sign_in_account("codex")
    assert menu.pick("codex", "practice-1")["current"]["name"] == "ChatGPT (practice)"
    assert "Practice" in "".join(menu.talker("You are Noir.").chat("x", []))
    assert isinstance(ModelMenu(menu.ollama, menu.hardware, load=lambda: {}, save=lambda s: None).accounts, Accounts)


def test_removing_a_plan_only_stops_noir_using_it():
    menu = FakeEngine(delay=0).menu
    menu.sign_in_account("claude_code")
    menu.pick("claude_code", "practice-1")
    info = menu.use_account("claude_code", False)
    assert info["current"] is None  # back to its own model
    assert next(plan for plan in info["accounts"] if plan["id"] == "claude_code")["hidden"] is True
    assert "claude_code" in menu.accounts.signed  # still signed in to the app itself
    assert menu.use_account("claude_code", True)["current"]["name"] == "Claude (practice)"
