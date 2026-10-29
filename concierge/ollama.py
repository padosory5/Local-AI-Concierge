"""A small client for the local Ollama server, which runs the models."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator

import requests

# 127.0.0.1, not "localhost": on Windows "localhost" can resolve to the IPv6
# address first, which Ollama does not listen on, and every call then waits
# about two seconds for the fallback.
DEFAULT_URL = "http://127.0.0.1:11434"
DOWNLOAD_PAGE = "https://ollama.com/download"


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
    def is_installed() -> bool:
        return shutil.which("ollama") is not None

    def ensure_running(self, wait_seconds: float = 20) -> None:
        """Start `ollama serve` in the background if it is installed but stopped."""
        if self.is_running():
            return
        if not self.is_installed():
            raise OllamaError(
                f"Ollama is not installed. Download it from {DOWNLOAD_PAGE}, "
                "install it, and run this again."
            )
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            start_new_session=sys.platform != "win32",
        )
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if self.is_running():
                return
            time.sleep(0.5)
        raise OllamaError("Ollama is installed but did not start. Open the Ollama app and try again.")

    # ------------------------------------------------------------ models

    def list_models(self) -> list[str]:
        return [m["name"] for m in self._get("/api/tags").get("models", [])]

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
        for event in self._stream("/api/chat", body, timeout=300):
            text = event.get("message", {}).get("content", "")
            if text:
                yield text

    # --------------------------------------------------------- transport

    def _get(self, path: str) -> dict:
        return self._check(requests.get(f"{self.base_url}{path}", timeout=10))

    def _post(self, path: str, body: dict) -> dict:
        return self._check(requests.post(f"{self.base_url}{path}", json=body, timeout=120))

    def _stream(self, path: str, body: dict, timeout: float = 60) -> Iterator[dict]:
        with requests.post(f"{self.base_url}{path}", json=body, stream=True, timeout=timeout) as resp:
            self._check(resp, read_body=False)
            for line in resp.iter_lines():
                if not line:
                    continue
                event = json.loads(line)
                if "error" in event:
                    raise OllamaError(event["error"])
                yield event

    @staticmethod
    def _check(resp: requests.Response, read_body: bool = True) -> dict:
        if not resp.ok:
            try:
                message = resp.json().get("error", resp.text)
            except ValueError:
                message = resp.text
            raise OllamaError(f"Ollama {resp.status_code}: {message}")
        return resp.json() if read_body else {}
