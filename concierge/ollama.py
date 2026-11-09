"""A small client for the local Ollama server, which runs the models."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import requests

# 127.0.0.1, not "localhost": on Windows "localhost" can resolve to the IPv6
# address first, which Ollama does not listen on, and every call then waits
# about two seconds for the fallback.
DEFAULT_URL = "http://127.0.0.1:11434"
DOWNLOAD_PAGE = "https://ollama.com/download"
UNREACHABLE = "I can't reach Ollama, the program that runs my model. Open the Ollama app, or restart me."


class OllamaError(RuntimeError):
    pass


def _normalize_url(host: str) -> str:
    """Turn an OLLAMA_HOST value such as "0.0.0.0" or "localhost:11434" into a URL."""
    if not host.startswith("http"):
        host = f"http://{host}"
    scheme, rest = host.split("://", 1)
    rest = rest.rstrip("/")
    for name in ("0.0.0.0", "localhost"):
        if rest == name or rest.startswith(f"{name}:"):
            rest = "127.0.0.1" + rest[len(name):]
    if ":" not in rest:
        rest += ":11434"
    return f"{scheme}://{rest}"


class Ollama:
    def __init__(self, base_url: str | None = None):
        self.base_url = _normalize_url(base_url or os.environ.get("OLLAMA_HOST") or DEFAULT_URL)

    # ------------------------------------------------------------ server

    def is_running(self) -> bool:
        try:
            return requests.get(f"{self.base_url}/api/version", timeout=2).ok
        except requests.RequestException:
            return False

    def version(self) -> str:
        return self._get("/api/version")["version"]

    @staticmethod
    def find_program() -> str:
        """Ollama's own program: on the PATH, or where its installer puts it. An app
        started from the Start menu or Finder keeps the PATH it was born with, so an
        Ollama installed a minute ago is looked for by name too."""
        found = shutil.which("ollama")
        if found:
            return found
        home = Path.home()
        if sys.platform == "win32":
            places = [Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local")) / "Programs/Ollama/ollama.exe"]
        elif sys.platform == "darwin":
            places = [Path("/Applications/Ollama.app/Contents/Resources/ollama"),
                      home / "Applications/Ollama.app/Contents/Resources/ollama", Path("/usr/local/bin/ollama")]
        else:
            places = [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama")]
        return next((str(place) for place in places if place.is_file()), "")

    @classmethod
    def is_installed(cls) -> bool:
        return bool(cls.find_program())

    def start(self) -> None:
        """Start Ollama without waiting: its own app where there is one (it sits by the
        clock and starts with the computer), else `ollama serve` quietly in the background."""
        program = self.find_program()
        if not program:
            raise OllamaError(
                f"Ollama is not installed. Download it from {DOWNLOAD_PAGE}, "
                "install it, and run this again."
            )
        quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        app = Path(program).with_name("ollama app.exe")
        if sys.platform == "win32" and app.is_file():
            subprocess.Popen([str(app)], creationflags=subprocess.CREATE_NO_WINDOW, **quiet)
            return
        bundle = Path(program).parents[2] if len(Path(program).parents) > 2 else None
        if sys.platform == "darwin" and bundle is not None and bundle.suffix == ".app":
            subprocess.Popen(["open", str(bundle)], **quiet)
            return
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        subprocess.Popen([program, "serve"], creationflags=flags, start_new_session=sys.platform != "win32", **quiet)

    def ensure_running(self, wait_seconds: float = 20) -> None:
        """Start Ollama in the background if it is installed but stopped, and wait for it."""
        if self.is_running():
            return
        self.start()
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if self.is_running():
                return
            time.sleep(0.5)
        raise OllamaError("Ollama is installed but did not start. Open the Ollama app and try again.")

    # ------------------------------------------------------------ models

    def list_models(self) -> list[str]:
        return [m["name"] for m in self._get("/api/tags").get("models", [])]

    def models(self) -> list[dict]:
        """Every installed model, with its size on disk and details."""
        return self._get("/api/tags").get("models", [])

    def delete(self, name: str) -> None:
        try:
            self._check(requests.delete(f"{self.base_url}/api/delete", json={"model": name}, timeout=30))
        except requests.RequestException as exc:
            raise OllamaError(UNREACHABLE) from exc

    def has_model(self, name: str) -> bool:
        wanted = name if ":" in name else f"{name}:latest"
        return wanted in self.list_models()

    def show(self, name: str) -> dict:
        return self._post("/api/show", {"model": name})

    def capabilities(self, name: str) -> list[str]:
        return self.show(name).get("capabilities", [])

    def pull(self, tag: str, on_progress: Callable[[str, int, int], None] | None = None) -> None:
        """Download a model. on_progress(status, completed bytes, total bytes)."""
        for event in self._stream("/api/pull", {"model": tag}):
            if on_progress:
                on_progress(event.get("status", ""), event.get("completed", 0), event.get("total", 0))

    def create(self, name: str, base: str, system: str, parameters: dict | None = None) -> None:
        """Create a named model from a base model with its own system prompt."""
        body = {"model": name, "from": base, "system": system}
        if parameters:
            body["parameters"] = parameters
        for _ in self._stream("/api/create", body):
            pass

    def loaded(self) -> list[dict]:
        """Models in memory right now, with Ollama's own size figures."""
        return self._get("/api/ps").get("models", [])

    def refresh(self, name: str, keep_alive: str) -> None:
        """Restart a loaded model's unload timer. Loads it if it is not loaded."""
        self._post("/api/generate", {"model": name, "keep_alive": keep_alive, "stream": False})

    def unload(self, name: str) -> None:
        # Short timeout: this also runs while Windows is closing the window,
        # which allows a handler only about five seconds.
        self._check(
            requests.post(
                f"{self.base_url}/api/generate", json={"model": name, "keep_alive": 0}, timeout=4
            )
        )

    # -------------------------------------------------------------- chat

    def chat_parts(
        self,
        model: str,
        messages: list[dict],
        think: bool | None = None,
        options: dict | None = None,
        keep_alive: str | None = None,
    ) -> Iterator[tuple[str, str]]:
        """Stream ("thought", text) pieces of the model's thinking, then
        ("text", text) pieces of its reply. Thoughts only come with think=True
        on a model that can think."""
        body = {"model": model, "messages": messages}
        if keep_alive is not None:
            body["keep_alive"] = keep_alive
        if think is not None:
            body["think"] = think
        if options:
            body["options"] = options
        self.last_tokens = (0, 0)
        for event in self._stream("/api/chat", body, timeout=600):
            self._count(event)
            message = event.get("message", {})
            if message.get("thinking"):
                yield "thought", message["thinking"]
            if message.get("content"):
                yield "text", message["content"]

    def chat(
        self,
        model: str,
        messages: list[dict],
        think: bool | None = None,
        options: dict | None = None,
        keep_alive: str | None = None,
    ) -> Iterator[str]:
        """Stream the reply's text as it is generated.

        keep_alive is how long the model stays loaded after this reply, such
        as "10m"; None leaves Ollama's default of five minutes.
        """
        body = {"model": model, "messages": messages}
        if keep_alive is not None:
            body["keep_alive"] = keep_alive
        if think is not None:
            body["think"] = think
        if options:
            body["options"] = options
        self.last_tokens = (0, 0)
        for event in self._stream("/api/chat", body, timeout=300):
            self._count(event)
            text = event.get("message", {}).get("content", "")
            if text:
                yield text

    # Tokens the last chat() or chat_parts() read and wrote, from Ollama's own count in
    # its last piece. For "tokens saved" under answers written on this computer.
    last_tokens: tuple[int, int] = (0, 0)

    def _count(self, event: dict) -> None:
        if event.get("done"):
            self.last_tokens = (event.get("prompt_eval_count") or 0, event.get("eval_count") or 0)

    def chat_json(
        self,
        model: str,
        messages: list[dict],
        schema: dict,
        think: bool | None = None,
        keep_alive: str | None = None,
        options: dict | None = None,
    ) -> dict:
        """One reply forced into a JSON schema. options: Ollama's, such as a bigger
        num_ctx for a picture.

        Ollama constrains the model's output to the schema, so an "enum" field
        can only ever hold one of the listed values. This is how code, not the
        model, decides what the possible answers are.
        """
        body = {"model": model, "messages": messages, "format": schema, "stream": False,
                "options": {"temperature": 0, **(options or {})}}
        if think is not None:
            body["think"] = think
        if keep_alive is not None:
            body["keep_alive"] = keep_alive
        reply = self._post("/api/chat", body)
        # Counted like a streamed answer, so a form its model fills (a research plan)
        # shows up in the tokens a job used.
        self.last_tokens = (reply.get("prompt_eval_count") or 0, reply.get("eval_count") or 0)
        content = reply["message"]["content"]
        try:
            return json.loads(content)
        except ValueError as exc:
            raise OllamaError(f"The model did not return valid JSON: {content[:200]}") from exc

    # --------------------------------------------------------- transport

    # Ollama can stop at any time (closed from the tray, or still starting). That is
    # an OllamaError like any other, so every window shows it in plain words
    # instead of failing on a connection error it doesn't know.

    def _get(self, path: str) -> dict:
        try:
            return self._check(requests.get(f"{self.base_url}{path}", timeout=10))
        except requests.RequestException as exc:
            raise OllamaError(UNREACHABLE) from exc

    def _post(self, path: str, body: dict) -> dict:
        try:
            return self._check(requests.post(f"{self.base_url}{path}", json=body, timeout=120))
        except requests.RequestException as exc:
            raise OllamaError(UNREACHABLE) from exc

    def _stream(self, path: str, body: dict, timeout: float = 60) -> Iterator[dict]:
        try:
            with requests.post(f"{self.base_url}{path}", json=body, stream=True, timeout=timeout) as resp:
                self._check(resp, read_body=False)
                for line in resp.iter_lines():
                    if not line:
                        continue
                    event = json.loads(line)
                    if "error" in event:
                        raise OllamaError(event["error"])
                    yield event
        except requests.RequestException as exc:
            raise OllamaError(UNREACHABLE) from exc

    @staticmethod
    def _check(resp: requests.Response, read_body: bool = True) -> dict:
        if not resp.ok:
            try:
                message = resp.json().get("error", resp.text)
            except ValueError:
                message = resp.text
            raise OllamaError(f"Ollama {resp.status_code}: {message}")
        return resp.json() if read_body else {}
