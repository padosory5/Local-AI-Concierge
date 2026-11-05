import pytest

from concierge import cloud, elaina, huggingface
from concierge.cloud import CloudModel
from concierge.fake_engine import PracticeKeys, PracticeOllama, practice_models
from concierge.hardware import GPU, HardwareReport
from concierge.models import FITS, LOCAL, NO_DISK, SLOW, LocalModel, ModelMenu, nice_name


def report(disk=500.0):
    return HardwareReport("windows", "11", "x86_64", "CPU", 8, 16, 32.0, 16.0, disk, "C:", [GPU("Card", "nvidia", 16.0, 12.0, True, "test")])


class ThinkingOllama(PracticeOllama):
    def __init__(self):
        super().__init__()
        self.sent = None

    def capabilities(self, name):
        return ["completion", "thinking"] if name == "gemma4:latest" else ["completion"]

    def chat(self, model, messages, think=None, options=None, keep_alive=None):
        self.sent = (model, messages, think, options)
        return iter(["hello"])

    def chat_parts(self, model, messages, think=None, options=None, keep_alive=None):
        self.sent = (model, messages, think, options)
        return iter([("text", "hello")])


@pytest.fixture
def menu():
    state = {"base_model": "qwen3.5:4b"}

    def save(new):
        state.clear()
        state.update(new)

    return ModelMenu(ThinkingOllama(), lambda: (report(), 3.0), load=lambda: dict(state), save=save, keys=PracticeKeys(),
                     browse=practice_models)


def test_the_menu_keeps_local_and_api_models_apart(menu):
    info = menu.info()
    assert [item["id"] for item in info["local"]] == ["qwen3.5:4b", "gemma4:latest"]
    assert info["local"][0]["own"] is True  # her own comes first
    assert {company["id"] for company in info["providers"]} >= {"anthropic", "openai", "google"}
    assert info["current"] is None


def test_her_built_model_isnt_listed_twice(menu):
    menu.ollama.installed.append({"name": "elaina:latest", "size": 3_000_000_000, "details": {}})
    assert "elaina:latest" not in [item["id"] for item in menu.info()["local"]]


def test_another_local_model_answers_as_elaina(menu):
    menu.pick(LOCAL, "gemma4:latest")
    assert menu.chosen()["here"] is True
    talker = menu.talker("You are Elaina.")
    assert isinstance(talker, LocalModel)
    assert list(talker.chat("elaina", [{"role": "user", "content": "hi"}])) == ["hello"]
    model, messages, think, options = menu.ollama.sent
    assert model == "gemma4:latest"
    assert "You are Elaina." in messages[0]["content"] and "on this computer" in messages[0]["content"]
    assert think is False  # it can think, and only does when asked
    assert options["num_ctx"] == elaina.NUM_CTX


def test_a_local_model_that_cant_think_is_never_told_about_thinking(menu):
    menu.ollama.installed.append({"name": "plain:latest", "size": 1, "details": {}})
    menu.pick(LOCAL, "plain:latest")
    talker = menu.talker("You are Elaina.")
    assert talker.can_think is False
    list(talker.chat("elaina", []))
    assert menu.ollama.sent[2] is None  # Ollama refuses think=False from a model that can't


def test_a_deleted_model_falls_back_to_her_own(menu):
    menu.pick(LOCAL, "gone:latest")
    assert menu.chosen() is None and menu.talker("x") is None


def test_a_cloud_model_without_its_key_falls_back_to_her_own(menu):
    menu.pick("openai", "gpt-x")
    assert menu.chosen() is None


def test_a_saved_key_makes_a_cloud_model_usable(menu):
    menu.save_key("openai", "the-key")
    info = menu.pick("openai", cloud.load_providers()["openai"].models[0].id)
    assert info["current"]["company"] == "OpenAI" and info["current"]["here"] is False
    assert isinstance(menu.talker("x"), CloudModel)


def test_hiding_only_changes_what_the_menu_shows(menu):
    info = menu.hide(LOCAL, "gemma4:latest", True)
    assert next(item for item in info["local"] if item["id"] == "gemma4:latest")["hidden"] is True
    assert menu.ollama.installed  # nothing was deleted
    assert next(item for item in menu.hide(LOCAL, "gemma4:latest", False)["local"] if item["id"] == "gemma4:latest")["hidden"] is False


def test_hiding_works_for_api_models_too(menu):
    info = menu.hide("openai", "gpt-6.1-sol", True)
    openai = next(company for company in info["providers"] if company["id"] == "openai")
    assert next(model for model in openai["models"] if model["id"] == "gpt-6.1-sol")["hidden"] is True


def test_a_custom_model_at_any_address(menu):
    info = menu.add_custom("My server", "https://example.com/v1/chat/completions/", "mixtral", "secret")
    item = info["custom"][0]
    assert item["url"] == "https://example.com/v1"  # what people often paste too is taken off
    assert item["has_key"] is True and "secret" not in str(info)
    info = menu.pick("custom", item["id"])
    assert info["current"]["company"] == "example.com" and info["current"]["here"] is False
    talker = menu.talker("x")
    assert talker.provider.url == "https://example.com/v1" and talker.option.id == "mixtral" and talker.key == "secret"


def test_a_custom_model_on_this_computer_needs_no_key_and_stays_here(menu):
    item = menu.add_custom("LM Studio", "http://127.0.0.1:1234/v1", "local-model")["custom"][0]
    assert item["here"] is True
    assert menu.pick("custom", item["id"])["current"]["here"] is True


@pytest.mark.parametrize("url, model, words", [("example.com/v1", "m", "http"), ("ftp://example.com", "m", "http"),
                                               ("https://example.com", " ", "which model")])
def test_a_custom_model_that_cant_work_says_why(menu, url, model, words):
    assert words in menu.add_custom("x", url, model)["error"]


def test_removing_a_custom_model_forgets_its_key_and_goes_home(menu):
    item = menu.add_custom("x", "https://example.com", "m", "secret")["custom"][0]
    menu.pick("custom", item["id"])
    info = menu.remove_custom(item["id"])
    assert info["custom"] == [] and info["current"] is None
    assert menu.keys.keys == {}


def test_her_own_model_can_never_be_deleted(menu):
    assert "error" in menu.delete_local("qwen3.5:4b")
    assert "error" in menu.delete_local("elaina:latest")
    assert any(item["name"] == "qwen3.5:4b" for item in menu.ollama.installed)


def test_deleting_another_model(menu):
    menu.delete_local("gemma4:latest")
    assert all(item["name"] != "gemma4:latest" for item in menu.ollama.installed)


def test_whether_a_model_fits_comes_from_this_computer():
    assert ModelMenu._fit(5.0, report(), 3.0) == FITS
    assert ModelMenu._fit(14.0, report(), 3.0) == SLOW  # 16 GB card, less Elaina and some room
    assert ModelMenu._fit(5.0, report(disk=6.0), 3.0) == NO_DISK


def test_browsing_says_what_fits_and_what_is_already_here(menu):
    menu.ollama.installed.append({"name": "hf.co/practice/Coder-9B-GGUF:Q4_K_M", "size": 1, "details": {}})
    found = {model["name"]: model for model in menu.browse()["models"]}
    assert found["Coder-9B"]["have"] is True and found["Tiny-Chat-3B"]["have"] is False
    assert found["Tiny-Chat-3B"]["fit"] == FITS and found["Giant-90B"]["fit"] == SLOW


def test_the_models_that_fit_come_first(menu):
    found = menu.browse()["models"]
    fits = [model["fit"] == FITS for model in found]
    assert fits == sorted(fits, reverse=True) and not all(fits)


def test_no_internet_is_said_plainly(menu, monkeypatch):
    def fail(*args):
        raise huggingface.HubError("I couldn't reach Hugging Face.")

    menu._browse = fail
    assert "Hugging Face" in menu.browse()["error"]


def wait_for(menu, seconds=2):
    import time

    deadline = time.monotonic() + seconds
    while menu.downloads() and not any(job["error"] for job in menu.downloads()) and time.monotonic() < deadline:
        time.sleep(0.01)


def test_a_download_shows_how_far_it_has_got_and_appears_when_done(menu, monkeypatch):
    seen = []
    menu.ollama.pull = lambda tag, progress: (progress("pulling", 50, 100), seen.append(menu.downloads()[0]["done"]),
                                              menu.ollama.installed.append({"name": tag, "size": 1, "details": {}}))
    changed = []
    menu.changed = lambda: changed.append(True)
    assert menu.download("https://huggingface.co/owner/Model-GGUF") == {}
    wait_for(menu)
    assert seen == [50]
    assert menu.downloads() == [] and changed
    assert any(item["id"] == "hf.co/owner/Model-GGUF" for item in menu.info()["local"])


def test_a_download_can_be_stopped(menu):
    import threading

    started, stop = threading.Event(), threading.Event()

    def pull(tag, progress):
        progress("pulling", 1, 100)
        started.set()
        stop.wait(2)
        progress("pulling", 2, 100)  # the next step is where it stops
        raise AssertionError("it should have stopped")

    menu.ollama.pull = pull
    menu.download("some-model")
    assert started.wait(2)
    menu.cancel("some-model")
    stop.set()
    wait_for(menu)
    assert menu.downloads() == []


def test_a_failed_download_says_so_until_dismissed(menu):
    from concierge.ollama import OllamaError

    def pull(tag, progress):
        raise OllamaError("pull failed")

    menu.ollama.pull = pull
    menu.download("some-model")
    wait_for(menu)
    assert "couldn't download" in menu.downloads()[0]["error"]
    menu.cancel("some-model")
    assert menu.downloads() == []


def test_something_that_isnt_a_model_isnt_fetched(menu):
    assert "error" in menu.download("not a model; rm -rf")
    assert menu.downloads() == []


def test_nice_names():
    assert nice_name("gemma4:latest") == "gemma4"
    assert nice_name("hf.co/owner/Model-GGUF:Q4_K_M") == "Model-GGUF:Q4_K_M"
