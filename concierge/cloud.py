"""Cloud models, for people who already pay for Claude, ChatGPT, Gemini and others.

Elaina's own small model always stays on the computer and still decides what a
message is for, because that's reliable and free. A cloud model only takes over
writing the answers, so CloudModel talks the same way Ollama does for that one job.

Keys are kept in Windows' own password store, never in a file, and never shown
again once saved. The user's words do leave the computer when a cloud model is
chosen, so the windows always say so.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import requests
import yaml

from .ollama import OllamaError

CATALOG_PATH = Path(__file__).with_name("cloud_models.yaml")
KEY_STORE = "LocalAIConcierge"
MAX_REPLY_TOKENS = 4096
LIST_TIMEOUT = 10
REPLY_TIMEOUT = 300
MORE_MODELS = 40  # the most a company's full list adds to the menu
ANTHROPIC_VERSION = "2023-06-01"
SENT_KEPT = 500  # how many sendings the What I see page can list
NOT_FOR_CHAT = ("embed", "whisper", "tts", "audio", "image", "moderation", "realtime", "transcribe", "rerank", "ocr")


class CloudError(OllamaError):
    """Written for the user; shown like any other problem with a model."""


@dataclass(frozen=True)
class CloudOption:
    id: str
    name: str
    images: bool = True


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    company: str
    kind: str
    url: str
    keys: str
    models: tuple[CloudOption, ...]


@lru_cache(maxsize=1)
def load_providers() -> dict[str, Provider]:
    data = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    return {key: Provider(key, item["name"], item["company"], item["kind"], item["url"], item["keys"],
                          tuple(CloudOption(**model) for model in item["models"]))
            for key, item in data["providers"].items()}


# ------------------------------------------------------------------- keys


def saved_key(provider: str) -> str:
    import keyring

    try:
        return keyring.get_password(KEY_STORE, provider) or ""
    except keyring.errors.KeyringError:
        return ""  # no password store here: the app still works with her own model


def save_key(provider: str, key: str) -> None:
    import keyring

    keyring.set_password(KEY_STORE, provider, key.strip())


def forget_key(provider: str) -> None:
    import keyring

    try:
        keyring.delete_password(KEY_STORE, provider)
    except keyring.errors.PasswordDeleteError:
        pass  # there was nothing saved


# ---------------------------------------------------------------- talking


def _headers(provider: Provider, key: str) -> dict:
    if provider.kind == "anthropic":
        return {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}
    return {"Authorization": f"Bearer {key}"}


def _problem(provider: Provider, status: int) -> CloudError:
    """Plain words for what went wrong. Never the raw reply, which could hold the key."""
    if status in (401, 403):
        return CloudError(f"{provider.company} didn't accept the key. Check it in Settings.")
    if status == 402:
        return CloudError(f"Your {provider.company} account is out of credit.")
    if status == 404:
        return CloudError(f"{provider.company} doesn't have that model any more. Please pick another one.")
    if status == 429:
        return CloudError(f"{provider.company} says you've reached your limit. Try again soon, or check your plan.")
    return CloudError(f"{provider.company} had a problem (code {status}). Please try again.")


def _openai_message(message: dict) -> dict:
    images = message.get("images")
    if not images:
        return {"role": message["role"], "content": message["content"]}
    parts = [{"type": "text", "text": message["content"]}]
    parts += [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}} for image in images]
    return {"role": message["role"], "content": parts}


def _anthropic_message(message: dict) -> dict:
    images = message.get("images")
    if not images:
        return {"role": message["role"], "content": message["content"]}
    parts: list[dict] = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image}}
                         for image in images]
    parts.append({"type": "text", "text": message["content"]})
    return {"role": message["role"], "content": parts}


def request_for(provider: Provider, model: str, system: str, messages: list[dict]) -> tuple[str, dict]:
    """Where to send a conversation and what to send, for this kind of company."""
    if provider.kind == "anthropic":
        body = {"model": model, "max_tokens": MAX_REPLY_TOKENS, "stream": True,
                "messages": [_anthropic_message(m) for m in messages]}
        if system:
            body["system"] = system
        return f"{provider.url}/messages", body
    turns = [{"role": "system", "content": system}] if system else []
    return f"{provider.url}/chat/completions", {"model": model, "stream": True,
                                                "messages": turns + [_openai_message(m) for m in messages]}


def text_in(provider: Provider, event: dict) -> str:
    """The new words in one piece of a streamed reply, if it has any."""
    if provider.kind == "anthropic":
        return event.get("delta", {}).get("text", "") if event.get("type") == "content_block_delta" else ""
    choices = event.get("choices") or [{}]
    return choices[0].get("delta", {}).get("content") or ""


class CloudModel:
    """A cloud model, used where the code would use Ollama to write an answer."""

    def __init__(self, provider: Provider, option: CloudOption, key: str, system: str = ""):
        self.provider, self.option, self.key, self.system = provider, option, key, system

    def chat(self, model: str, messages: list[dict], think=None, options=None, keep_alive=None) -> Iterator[str]:
        url, body = request_for(self.provider, self.option.id, self.system, messages)
        record_sent(self.provider.company, self.option.name)
        try:
            with requests.post(url, json=body, headers=_headers(self.provider, self.key), stream=True,
                               timeout=REPLY_TIMEOUT) as reply:
                if not reply.ok:
                    raise _problem(self.provider, reply.status_code)
                for line in reply.iter_lines():
                    if not line.startswith(b"data:"):
                        continue
                    data = line[5:].strip()
                    if data == b"[DONE]":
                        return
                    piece = text_in(self.provider, json.loads(data))
                    if piece:
                        yield piece
        except requests.RequestException as exc:
            raise CloudError(f"I couldn't reach {self.provider.company}. Check your internet connection.") from exc

    def chat_parts(self, model: str, messages: list[dict], think=None, options=None,
                   keep_alive=None) -> Iterator[tuple[str, str]]:
        for piece in self.chat(model, messages):
            yield "text", piece

    def capabilities(self, name: str) -> list[str]:
        return ["completion", "vision"] if self.option.images else ["completion"]

    def refresh(self, name: str, keep_alive: str) -> None:
        """Nothing to keep loaded: the model lives at the company."""


def key_refused(provider: Provider, key: str) -> bool:
    """True only when the company clearly says no. No internet, or a company
    that has no such list, shouldn't stop someone saving a good key."""
    try:
        return requests.get(f"{provider.url}/models", headers=_headers(provider, key),
                            timeout=LIST_TIMEOUT).status_code == 401
    except requests.RequestException:
        return False


def _sent_path():
    from .elaina import data_dir

    return data_dir() / "sent.json"


def record_sent(company: str, model: str) -> None:
    """Each time words leave the computer, for the What I see page. Only who and
    when, never what was said."""
    try:
        sent = json.loads(_sent_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        sent = []
    sent = [*sent, {"when": time.time(), "company": company, "model": model}][-SENT_KEPT:]
    try:
        _sent_path().parent.mkdir(parents=True, exist_ok=True)
        _sent_path().write_text(json.dumps(sent), encoding="utf-8")
    except OSError:
        pass  # a full disk mustn't stop the answer


def sent_recently(days: float = 7, now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    try:
        sent = json.loads(_sent_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [item for item in sent if now - item["when"] < days * 86400]


def live_models(provider: Provider, key: str) -> list[CloudOption]:
    """The company's own list of models, for what isn't in the popular list.
    Empty if it can't be read, because the popular list still works without it."""
    try:
        reply = requests.get(f"{provider.url}/models", headers=_headers(provider, key), timeout=LIST_TIMEOUT)
        ids = [item["id"].removeprefix("models/") for item in reply.json().get("data", [])] if reply.ok else []
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return []
    known = {model.id for model in provider.models}
    usable = [name for name in ids if name not in known and not any(word in name.lower() for word in NOT_FOR_CHAT)]
    return [CloudOption(name, name) for name in sorted(usable)[:MORE_MODELS]]


def overview(has_key) -> list[dict]:
    """Every company with its models, for the model menu and Settings. Whether
    a key is saved is in here; the key itself never goes near a page."""
    return [{"id": p.id, "name": p.name, "company": p.company, "keys": p.keys, "has_key": bool(has_key(p.id)),
             "models": [{"id": m.id, "name": m.name, "images": m.images} for m in p.models]}
            for p in load_providers().values()]


def find_option(provider: str, model: str) -> CloudOption:
    """A model picked from the menu, or one from the company's full list."""
    for option in load_providers()[provider].models:
        if option.id == model:
            return option
    return CloudOption(model, model)
