"""The user's own ChatGPT or Claude plan, used through the companies' own apps: Codex
for ChatGPT, Claude Code for Claude. Nothing to copy and no key: they sign in once in
that app, through the company's own page, and Noir hands it each question.

This is the way the companies allow. OpenAI's Codex signs in with a ChatGPT plan.
Anthropic lets people sign in to the unmodified Claude Code program with their own
plan, but doesn't let other apps offer Claude sign-in themselves. So Noir never
sees a login or a token: it runs the app the user installed and signed in to, in
an empty folder where it can't change anything, and reads the answer back.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from collections.abc import Iterator
from pathlib import Path

from .cloud import CloudError, load_providers, record_sent
from .usage import claude_limits, claude_tokens, codex_limits, codex_tokens, record_limits, record_tokens

CODEX, CLAUDE_CODE = "codex", "claude_code"
# What each one is called, where it might live (an app opened from the Mac's Finder
# has almost no PATH, so the usual homes are tried too), and how people get it.
APPS = {
    CODEX: {"name": "ChatGPT", "app": "Codex", "plan": "your ChatGPT plan", "command": "codex",
            "places": ("~/.codex/.sandbox-bin/codex.exe", "~/AppData/Roaming/npm/codex.cmd",
                       "/opt/homebrew/bin/codex", "/usr/local/bin/codex", "~/.npm-global/bin/codex"),
            "get": "https://developers.openai.com/codex",
            "sign_in": "Opens a sign-in page in your browser"},
    CLAUDE_CODE: {"name": "Claude", "app": "Claude Code", "plan": "your Claude plan", "command": "claude",
                  "places": ("~/.local/bin/claude.exe", "~/AppData/Roaming/npm/claude.cmd",
                             "~/.local/bin/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude",
                             "~/.npm-global/bin/claude"),
                  "get": "https://code.claude.com/docs/en/setup",
                  "sign_in": "Opens a sign-in page in your browser"},
}
# Claude Code's installer for Windows, from Anthropic's setup page.
CLAUDE_INSTALL = "irm https://claude.ai/install.ps1 | iex"
# The tools that could change something. The app runs in an empty folder anyway.
CLAUDE_NO_TOOLS = "Bash,Edit,Write,MultiEdit,NotebookEdit,WebFetch,WebSearch,Task"
ANSWER_TIMEOUT = 300
STATUS_SECONDS = 60  # how long a look at whether they're signed in is trusted
NO_WINDOW, NEW_WINDOW = 0x08000000, 0x00000010  # Windows: run quietly, or in a window of its own


class Accounts:
    """Whether each app is here and signed in, its models, and answering through it."""

    def __init__(self, run=subprocess.run, popen=subprocess.Popen, home: Path | None = None):
        self._run, self._popen = run, popen
        self._home = home or Path.home()
        self._seen: dict[str, tuple[float, dict]] = {}

    def find(self, app: str) -> str:
        """The app's program, or "" when it isn't installed."""
        info = APPS[app]
        found = shutil.which(info["command"])
        if found:
            return found
        for place in info["places"]:
            path = self._home / place.removeprefix("~/")
            if path.is_file():
                return str(path)
        return ""

    def status(self, app: str, fresh: bool = False) -> dict:
        """What the windows show: installed, signed in, and the models it offers."""
        seen = self._seen.get(app)
        if seen and not fresh and time.monotonic() - seen[0] < STATUS_SECONDS:
            return seen[1]
        info = APPS[app]
        program = self.find(app)
        signed_in = bool(program) and self._signed_in(app, program)
        status = {"id": app, "name": info["name"], "app": info["app"], "plan": info["plan"],
                  "sign_in": info["sign_in"], "installed": bool(program), "signed_in": signed_in,
                  "models": self._models(app, program) if signed_in else []}
        self._seen[app] = (time.monotonic(), status)
        return status

    def overview(self, fresh: bool = False) -> list[dict]:
        return [self.status(app, fresh) for app in APPS]

    def sign_in(self, app: str) -> None:
        """Open the app's own sign-in, in a window the user can see. For Codex that
        opens ChatGPT's page in the browser; Claude Code asks in its window."""
        program = self.find(app)
        if not program:
            raise CloudError(f"{APPS[app]['app']} isn't installed yet.")
        self._seen.pop(app, None)
        # Claude Code's own "auth login" goes straight to Anthropic's page. Plain "claude"
        # first asks for a colour theme and more, in a terminal people found they couldn't use.
        command = [program, "login"] if app == CODEX else [program, "auth", "login", "--claudeai"]
        self._popen(command, creationflags=NEW_WINDOW if sys.platform == "win32" else 0, cwd=tempfile.gettempdir())

    def install(self, app: str) -> None:
        """Claude Code has an installer to run; Codex comes from OpenAI's own page."""
        self._seen.pop(app, None)
        if app == CLAUDE_CODE and sys.platform == "win32":
            self._popen(["powershell", "-NoExit", "-Command", CLAUDE_INSTALL], creationflags=NEW_WINDOW)
        else:
            webbrowser.open(APPS[app]["get"])

    def talker(self, app: str, model: str, system: str) -> AppModel:
        return AppModel(self, app, model, system)

    # ------------------------------------------------------------ looking

    def _signed_in(self, app: str, program: str) -> bool:
        if app == CODEX:
            done = self._quiet([program, "login", "status"], timeout=20)
            return done is not None and done.returncode == 0 and "logged in" in (done.stdout + done.stderr).lower()
        done = self._quiet([program, "auth", "status", "--json"], timeout=20)
        try:
            return bool(done and json.loads(done.stdout).get("loggedIn"))
        except (ValueError, AttributeError):
            return False

    def _models(self, app: str, program: str) -> list[dict]:
        if app == CLAUDE_CODE:
            # Claude Code takes the same model names as Anthropic's own list (cloud_models.yaml),
            # so the menu offers each one by name, Opus 5.5 and the rest.
            return [{"id": model.id, "name": model.name} for model in load_providers()["anthropic"].models]
        done = self._quiet([program, "debug", "models"], timeout=20)
        try:
            listed = json.loads(done.stdout)["models"] if done else []
        except (ValueError, KeyError):
            listed = []
        return [{"id": m["slug"], "name": m.get("display_name") or m["slug"]} for m in listed
                if m.get("visibility") == "list"]

    def _quiet(self, command: list[str], timeout: float, stdin: str | None = None):
        try:
            return self._run(command, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=timeout, creationflags=NO_WINDOW if sys.platform == "win32" else 0)
        except (OSError, subprocess.TimeoutExpired):
            return None


class AppModel:
    """Codex or Claude Code, used where the code would use Ollama to write an answer."""

    def __init__(self, accounts: Accounts, app: str, model: str, system: str = ""):
        self.accounts, self.app, self.model, self.system = accounts, app, model, system

    def chat(self, model: str, messages: list[dict], think=None, options=None, keep_alive=None) -> Iterator[str]:
        program = self.accounts.find(self.app)
        if not program:
            raise CloudError(f"{APPS[self.app]['app']} isn't installed any more. Pick another model.")
        record_sent(f"{APPS[self.app]['name']} ({APPS[self.app]['app']})", self.model)
        with tempfile.TemporaryDirectory() as empty:  # nothing there for it to read or change
            if self.app == CODEX:
                yield from self._codex(program, empty, messages)
            else:
                yield from self._claude(program, empty, messages)

    def chat_parts(self, model: str, messages: list[dict], think=None, options=None,
                   keep_alive=None) -> Iterator[tuple[str, str]]:
        for piece in self.chat(model, messages):
            yield "text", piece

    def capabilities(self, name: str) -> list[str]:
        return ["completion"]  # pictures aren't passed to the apps

    def refresh(self, name: str, keep_alive: str) -> None:
        """Nothing to keep loaded: the model lives at the company."""

    # ------------------------------------------------------------ the apps

    def _codex(self, program: str, folder: str, messages: list[dict]) -> Iterator[str]:
        # Codex has its own instructions, so hers go at the top of the question.
        prompt = f"Answer as this assistant:\n{self.system}\n\n{transcript(messages)}" if self.system else transcript(messages)
        command = [program, "exec", "--json", "-m", self.model, "-s", "read-only", "--skip-git-repo-check",
                   "--ephemeral", "-C", folder, "-"]
        for event in self._events(command, prompt, folder):
            if codex_limits(event):  # only when Codex reports them; nothing is guessed
                record_limits(CODEX, codex_limits(event))
            if event.get("type") == "turn.completed":
                record_tokens(CODEX, self.model, *codex_tokens(event))
            if event.get("type") == "item.completed" and (event.get("item") or {}).get("type") == "agent_message":
                yield event["item"].get("text", "")
            elif event.get("type") == "turn.failed":
                raise CloudError(f"ChatGPT couldn't answer through Codex: {_said((event.get('error') or {}).get('message', ''))}")

    def _claude(self, program: str, folder: str, messages: list[dict]) -> Iterator[str]:
        command = [program, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                   "--model", self.model, "--disallowedTools", CLAUDE_NO_TOOLS]
        if self.system:
            command += ["--system-prompt", self.system]
        streamed = False
        for event in self._events(command, transcript(messages), folder):
            inner = event.get("event") or {}
            if event.get("type") == "stream_event" and (inner.get("delta") or {}).get("type") == "text_delta":
                streamed = True
                yield inner["delta"].get("text", "")
            elif event.get("type") == "rate_limit_event":
                # The plan's 5-hour and weekly windows, the same numbers as /usage in Claude Code.
                record_limits(CLAUDE_CODE, claude_limits(event))
            elif event.get("type") == "result":
                record_tokens(CLAUDE_CODE, self.model, *claude_tokens(event))
                if event.get("is_error"):
                    raise CloudError(f"Claude couldn't answer through Claude Code: {_said(str(event.get('result', '')))}")
                if not streamed:  # an older Claude Code that doesn't send pieces
                    yield str(event.get("result", ""))

    def _events(self, command: list[str], prompt: str, folder: str) -> Iterator[dict]:
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, encoding="utf-8", errors="replace", cwd=folder,
                                       creationflags=NO_WINDOW if sys.platform == "win32" else 0)
        except OSError as exc:
            raise CloudError(f"I couldn't start {APPS[self.app]['app']}.") from exc
        try:
            process.stdin.write(prompt)
            process.stdin.close()
            for line in process.stdout:
                line = line.strip()
                if line.startswith("{"):
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue
            process.wait(timeout=ANSWER_TIMEOUT)
        finally:
            if process.poll() is None:
                process.kill()
        if process.returncode not in (0, None):
            problem = process.stderr.read().strip().splitlines()
            if problem:
                raise CloudError(f"{APPS[self.app]['app']} stopped: {_said(problem[-1])}")


def transcript(messages: list[dict]) -> str:
    """The conversation as one piece of text: the apps take one question at a time."""
    if len(messages) == 1:
        return messages[0]["content"]
    said = [f"{'You' if m['role'] == 'assistant' else 'User'}: {m['content']}" for m in messages[:-1]
            if m["role"] in ("user", "assistant")]
    return "The conversation so far:\n" + "\n\n".join(said) + f"\n\nThe user now says:\n{messages[-1]['content']}"


def _said(message: str) -> str:
    """The plain part of an error the app passed on: OpenAI's errors come wrapped in JSON."""
    try:
        inner = json.loads(message)
        message = (inner.get("error") or {}).get("message") or inner.get("message") or message
    except (ValueError, AttributeError):
        pass
    return message.strip()[:300] or "it didn't say why."
