"""Everything the model menu offers, and who writes Elaina's answers.

The menu keeps two kinds apart: models on this computer (anything in Ollama) and
API models the user pays for (cloud.py, plus custom ones at any address that talks
the shared way). Whichever is picked only writes her answers. Her own small model
still decides what each message is for (see ElainaEngine._use_chosen_model).
"""

from __future__ import annotations

import re
import secrets
import threading
from collections.abc import Callable
from urllib.parse import urlsplit

from . import accounts as apps
from . import auto, cloud, elaina, huggingface, usage
from .catalog import DISK_HEADROOM_GB, find_model, helper_room
from .ollama import OllamaError

LOCAL, CUSTOM = "local", "custom"
LOOPBACK = ("127.0.0.1", "localhost", "::1")
GB = 1_000_000_000
FITS, SLOW, NO_DISK = "fits", "slow", "no_disk"


class LocalModel:
    """Another model on this computer, answering as Elaina. Her persona is baked
    into her own model only, so here it goes along with each message."""

    def __init__(self, ollama, tag: str, system: str):
        self.ollama, self.tag, self.system = ollama, tag, system
        self.can_think = "thinking" in ollama.capabilities(tag)

    def _asked(self, messages: list[dict]) -> list[dict]:
        return [{"role": "system", "content": self.system}, *messages]

    def _options(self, options: dict | None) -> dict:
        # Her memory is sized for this much. Left alone, some models take far more.
        return {"num_ctx": elaina.NUM_CTX, **(options or {})}

    def chat(self, model, messages, think=None, options=None, keep_alive=None):
        return self.ollama.chat(self.tag, self._asked(messages), think=False if self.can_think else None,
                                options=self._options(options), keep_alive=keep_alive)

    def chat_parts(self, model, messages, think=None, options=None, keep_alive=None):
        return self.ollama.chat_parts(self.tag, self._asked(messages), think=True,
                                      options=self._options(options), keep_alive=keep_alive)

    def capabilities(self, name: str) -> list[str]:
        return self.ollama.capabilities(self.tag)


def nice_name(tag: str) -> str:
    """A name people can read for an Ollama tag."""
    known = find_model(tag)
    if known:
        return known.name
    name = tag.removesuffix(":latest")
    return name.rsplit("/", 1)[-1] if name.startswith("hf.co/") else name


def _address(url: str) -> str:
    """The address of a custom model, without the parts people often paste too."""
    return re.sub(r"/(chat/completions|completions|models)/?$", "", url.strip()).rstrip("/")


def _host(url: str) -> str:
    return urlsplit(url).hostname or url


class ModelMenu:
    """load, save and keys are replaced in the practice app, so it never touches
    the real settings or the password store."""

    def __init__(self, ollama, hardware: Callable, load: Callable = None, save: Callable = None, keys=cloud,
                 browse: Callable = None, accounts=None):
        self.ollama = ollama
        self.hardware = hardware  # returns (report, memory Elaina's model takes)
        self.keys = keys
        self.changed: Callable[[], None] = lambda: None
        self._load = load or elaina.load_state
        self._save = save or elaina.save_state
        self._browse = browse or huggingface.browse
        self.accounts = accounts or apps.Accounts()  # ChatGPT and Claude plans, through Codex and Claude Code
        self._pulling: dict[str, dict] = {}
        self._lock = threading.Lock()

    # -------------------------------------------------------------- settings

    def _state(self, name: str, default):
        return self._load().get(name, default)

    def _store(self, name: str, value) -> None:
        self._save({**self._load(), name: value})

    def _custom(self) -> list[dict]:
        return self._state("custom_models", [])

    def _installed(self) -> list[dict]:
        try:
            return self.ollama.models()
        except OllamaError:
            return []

    # ------------------------------------------------------------ who answers

    def chosen(self) -> dict | None:
        """What was picked in the menu, as long as it can still be used. Her own
        model otherwise: a deleted model or a removed key must not stop her talking."""
        choice = self._state("talk_model", None) or {}
        provider, model = choice.get("provider", ""), choice.get("model", "")
        if provider == auto.AUTO:
            # Auto: her own model for small things, this one for the rest (auto.py).
            target = self.auto_target()
            if target is None:
                return None  # no plan or key left to send hard questions to
            return {"provider": auto.AUTO, "model": target["model"], "name": "Auto", "company": target["company"],
                    "here": False, "auto": True, "cloud": target}
        return self._resolve(provider, model)

    def auto_target(self) -> dict | None:
        """The plan or key model Auto sends hard questions to: the last one picked in
        the menu, else a plan's middle model (Sonnet, not Opus: it's about saving the
        plan), else the first model of a company with a key."""
        last = self._state("auto_cloud", None) or {}
        found = self._resolve(last.get("provider", ""), last.get("model", "")) if last else None
        if found and not found["here"]:
            return found
        hidden = self._state("hidden_accounts", [])
        for status in self.accounts.overview():
            if status["id"] in hidden or not status["models"]:
                continue
            middle = next((m for m in status["models"] if "sonnet" in m["id"]), status["models"][0])
            return self._resolve(status["id"], middle["id"])
        for company in cloud.load_providers().values():
            if self.keys.saved_key(company.id) and company.models:
                return self._resolve(company.id, company.models[0].id)
        return None

    def plan_used(self, provider: str) -> float:
        """How full the plan's fullest window is (0 to 1); 0 for a key, which has none."""
        windows = usage.summary().get(provider, {}).get("limits", [])
        return max((w["used"] for w in windows), default=0.0)

    def _resolve(self, provider: str, model: str) -> dict | None:
        if provider == LOCAL and any(item["name"] == model for item in self._installed()):
            return {"provider": LOCAL, "model": model, "name": nice_name(model), "company": "", "here": True}
        if provider == CUSTOM:
            found = next((item for item in self._custom() if item["id"] == model), None)
            if found:
                host = _host(found["url"])
                return {"provider": CUSTOM, "model": model, "name": found["name"], "company": host,
                        "here": host in LOOPBACK}
        if provider in apps.APPS and provider not in self._state("hidden_accounts", []):
            status = self.accounts.status(provider)
            found = next((item for item in status["models"] if item["id"] == model), None)
            if found:
                return {"provider": provider, "model": model, "name": found["name"],
                        "company": f"{status['plan']}, through {status['app']}", "here": False}
        company = cloud.load_providers().get(provider)
        if company and self.keys.saved_key(provider):
            return {"provider": provider, "model": model, "name": cloud.find_option(provider, model).name,
                    "company": company.company, "here": False}
        return None

    def talker(self, system: str):
        """Who writes her answers, or None for her own model. With Auto, the model
        for hard questions: the engine decides each time whether to use it."""
        chosen = self.chosen()
        if chosen is None:
            return None
        if chosen.get("auto"):
            chosen = chosen["cloud"]
        name, model = chosen["name"], chosen["model"]
        if chosen["provider"] == LOCAL:
            return LocalModel(self.ollama, model, f"{system}\n\nRight now your answers are written by {name}, "
                                                  "on this computer.")
        where = f"Right now your answers are written by {name} from {chosen['company']}, over the internet."
        if chosen["provider"] in apps.APPS:
            return self.accounts.talker(chosen["provider"], model, f"{system}\n\n{where}")
        if chosen["provider"] == CUSTOM:
            found = next(item for item in self._custom() if item["id"] == model)
            company = cloud.Provider(CUSTOM, name, chosen["company"], "openai", found["url"], "", ())
            option = cloud.CloudOption(found["model"], name)
            return cloud.CloudModel(company, option, self.keys.saved_key(f"custom-{model}"), f"{system}\n\n{where}")
        company = cloud.load_providers()[chosen["provider"]]
        option = cloud.find_option(company.id, model)
        return cloud.CloudModel(company, option, self.keys.saved_key(company.id), f"{system}\n\n{where}")

    def pick(self, provider: str = "", model: str = "") -> dict:
        self._store("talk_model", {"provider": provider, "model": model})
        picked = self._resolve(provider, model) if provider and provider != auto.AUTO else None
        if picked and not picked["here"]:
            self._store("auto_cloud", {"provider": provider, "model": model})  # what Auto asks from now on
        self.changed()
        return self.info()

    # -------------------------------------------------------------- the menu

    def info(self) -> dict:
        """What the windows show. Keys are never in here, only whether one is saved."""
        own = self._state("base_model", "")
        hidden = set(self._state("hidden_models", []))
        local = []
        for item in self._installed():
            tag, details = item["name"], item.get("details") or {}
            if tag.split(":")[0] == elaina.ELAINA_MODEL:
                continue  # the same model as the one she's built from
            words = [details.get("parameter_size", ""), f"{item.get('size', 0) / GB:.1f} GB"]
            local.append({"id": tag, "name": nice_name(tag), "detail": " · ".join(filter(None, words)),
                          "own": tag == own, "hidden": f"{LOCAL}/{tag}" in hidden})
        local.sort(key=lambda row: (not row["own"], row["name"].lower()))
        companies = cloud.overview(self.keys.saved_key)
        for company in companies:
            for model in company["models"]:
                model["hidden"] = f"{company['id']}/{model['id']}" in hidden
        custom = [{**item, "has_key": bool(self.keys.saved_key(f"custom-{item['id']}")), "here": _host(item["url"]) in LOOPBACK,
                   "hidden": f"{CUSTOM}/{item['id']}" in hidden} for item in self._custom()]
        known = find_model(own) if own else None
        target = self.auto_target()
        return {"own": known.name if known else own or "Elaina's model", "current": self.chosen(),
                "auto": {"cloud": target["name"] if target else "", "company": target["company"] if target else ""},
                "local": local, "accounts": self._accounts_shown(), "providers": companies, "custom": custom}

    def hide(self, provider: str, model: str, hidden: bool) -> dict:
        """Edit models: what shows in the menu. Nothing is removed by this."""
        name = f"{provider}/{model}"
        rest = [item for item in self._state("hidden_models", []) if item != name]
        self._store("hidden_models", rest + ([name] if hidden else []))
        return self.info()

    def more(self, provider: str) -> list[dict]:
        """The rest of what a company offers, once a key is saved."""
        company = cloud.load_providers().get(provider)
        key = self.keys.saved_key(provider) if company else ""
        return [{"id": m.id, "name": m.name, "images": m.images} for m in cloud.live_models(company, key)] if key else []

    # ------------------------------------------------------------------ keys

    def save_key(self, provider: str, key: str) -> dict:
        company = cloud.load_providers().get(provider)
        if company is None or not key.strip():
            return {"error": "Please paste your key first."}
        if self.keys.key_refused(company, key.strip()):
            return {"error": f"{company.company} didn't accept that key. Check it and try again."}
        self.keys.save_key(provider, key)
        self.changed()
        return self.info()

    # -------------------------------------------- plans, through the companies' apps

    def sign_in_account(self, app: str) -> dict:
        """Open Codex's or Claude Code's own sign-in in a window of its own."""
        try:
            self.accounts.sign_in(app)
        except cloud.CloudError as exc:
            return {"error": str(exc)}
        return self.info()

    def install_account(self, app: str) -> dict:
        self.accounts.install(app)
        return self.info()

    def use_account(self, app: str, on: bool) -> dict:
        """Stop or start using a plan here. It doesn't sign anyone out of Codex or Claude
        Code, which people may use on their own."""
        rest = [item for item in self._state("hidden_accounts", []) if item != app]
        self._store("hidden_accounts", rest + ([] if on else [app]))
        self.changed()
        return self.info()

    def _accounts_shown(self) -> list[dict]:
        hidden = set(self._state("hidden_accounts", []))
        return [{**status, "hidden": status["id"] in hidden} for status in self.accounts.overview()]

    def usage(self) -> dict:
        """How much of each plan or key her answers used, for the meter (usage.py)."""
        return usage.summary()

    def check_accounts(self) -> dict:
        """Look again, after the user signed in or installed something."""
        self.accounts.overview(fresh=True)
        self.changed()
        return self.info()

    def forget_key(self, provider: str) -> dict:
        self.keys.forget_key(provider)
        self.changed()
        return self.info()

    # ---------------------------------------------------------- custom models

    def add_custom(self, name: str, url: str, model: str, key: str = "") -> dict:
        """A model at any address that talks the shared way most companies use,
        including programs like LM Studio running on this computer."""
        url, model = _address(url), model.strip()
        if urlsplit(url).scheme not in ("http", "https") or not urlsplit(url).hostname:
            return {"error": "The address should start with http:// or https://"}
        if not model:
            return {"error": "Please say which model to use at that address."}
        id = secrets.token_hex(4)
        self._store("custom_models", [*self._custom(), {"id": id, "name": name.strip() or model, "url": url, "model": model}])
        if key.strip():
            self.keys.save_key(f"custom-{id}", key)
        self.changed()
        return self.info()

    def remove_custom(self, id: str) -> dict:
        self._store("custom_models", [item for item in self._custom() if item["id"] != id])
        self.keys.forget_key(f"custom-{id}")
        self.changed()
        return self.info()

    def delete_local(self, tag: str) -> dict:
        """Frees the disk space. Elaina's own model can't be deleted here: without it she can't run."""
        if tag.split(":")[0] == elaina.ELAINA_MODEL or tag == self._state("base_model", ""):
            return {"error": "That's Elaina's own model, so it has to stay."}
        try:
            self.ollama.delete(tag)
        except OllamaError:
            return {"error": "I couldn't delete that model. Is Ollama running?"}
        self.changed()
        return self.info()

    # ------------------------------------------------------- finding new ones

    @staticmethod
    def _fit(size_gb: float, report, elaina_gb: float) -> str:
        """Whether a model suits this computer, from what was measured: the room
        next to Elaina, and the disk. A model takes at least its file size in memory."""
        if report.disk_free_gb < size_gb + DISK_HEADROOM_GB:
            return NO_DISK
        room, _ = helper_room(report, elaina_gb)
        return FITS if size_gb <= room else SLOW

    def browse(self, words: str = "", sort: str = "downloads", kind: str = "") -> dict:
        try:
            found = self._browse(words, sort, kind)
        except huggingface.HubError as exc:
            return {"error": str(exc)}
        have = {item["name"] for item in self._installed()}
        report, elaina_gb = self.hardware()
        models = [{**model, "fit": self._fit(model["size_gb"], report, elaina_gb), "have": model["tag"] in have}
                  for model in found]
        # The ones that will run well come first; a person can't use the rest as easily.
        return {"models": sorted(models, key=lambda model: model["fit"] != FITS)}

    def download(self, text: str) -> dict:
        """Ollama fetches it, on a thread of its own, because a big model takes minutes."""
        tag = huggingface.tag_from(text)
        if not tag:
            return {"error": "That doesn't look like a model name or a Hugging Face link."}
        with self._lock:
            if tag not in self._pulling or self._pulling[tag]["error"]:
                self._pulling[tag] = {"tag": tag, "done": 0, "total": 0, "error": "", "cancelled": False}
                threading.Thread(target=self._pull, args=(tag,), name="model-download", daemon=True).start()
        return {}

    def _pull(self, tag: str) -> None:
        job = self._pulling[tag]

        def progress(status: str, done: int, total: int) -> None:
            if job["cancelled"]:
                raise InterruptedError
            if total:
                job["done"], job["total"] = done, total

        try:
            self.ollama.pull(tag, progress)
        except InterruptedError:
            pass
        except OllamaError:
            job["error"] = "Ollama couldn't download that model. Check the name and your internet connection."
            return
        with self._lock:
            self._pulling.pop(tag, None)
        self.changed()

    def cancel(self, tag: str) -> None:
        job = self._pulling.get(tag)
        if job:
            job["cancelled"] = True
            if job["error"]:
                with self._lock:
                    self._pulling.pop(tag, None)

    def downloads(self) -> list[dict]:
        return [dict(job) for job in self._pulling.values()]
