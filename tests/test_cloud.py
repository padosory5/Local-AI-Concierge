import json

import keyring
import pytest
import requests
from keyring.backend import KeyringBackend

from concierge import cloud, elaina
from concierge.cloud import CloudError, CloudModel, CloudOption, Provider
from concierge.engine import ElainaEngine
from concierge.fake_engine import FakeEngine

ANTHROPIC = Provider("anthropic", "Claude", "Anthropic", "anthropic", "https://a.test/v1", "https://a.test/keys", ())
OPENAI = Provider("openai", "ChatGPT", "OpenAI", "openai", "https://o.test/v1", "https://o.test/keys", ())
OPTION = CloudOption("model-1", "Model One")
HELLO = [{"role": "user", "content": "hello"}]


class Reply:
    def __init__(self, lines=(), status=200, body=None):
        self.lines, self.status_code, self.body = lines, status, body
        self.ok = status < 400

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_lines(self):
        return iter(self.lines)

    def json(self):
        return self.body


def stream(*events):
    return [f"data: {json.dumps(event)}".encode() for event in events] + [b"data: [DONE]"]


class MemoryKeys(KeyringBackend):
    priority = 1

    def __init__(self):
        self.keys = {}

    def get_password(self, service, name):
        return self.keys.get((service, name))

    def set_password(self, service, name, password):
        self.keys[(service, name)] = password

    def delete_password(self, service, name):
        if (service, name) not in self.keys:
            raise keyring.errors.PasswordDeleteError("nothing there")
        del self.keys[(service, name)]


@pytest.fixture
def keys(monkeypatch):
    before = keyring.get_keyring()
    store = MemoryKeys()
    keyring.set_keyring(store)
    yield store
    keyring.set_keyring(before)


def test_every_company_in_the_list_can_be_read():
    providers = cloud.load_providers()
    assert {"anthropic", "openai", "google", "xai", "deepseek", "mistral"} <= set(providers)
    for company in providers.values():
        assert company.kind in ("anthropic", "openai")
        assert company.url.startswith("https://") and company.keys.startswith("https://")
        assert company.models


def test_openai_kind_asks_in_the_shared_way():
    url, body = cloud.request_for(OPENAI, "model-1", "You are Elaina.", HELLO)
    assert url == "https://o.test/v1/chat/completions"
    assert body["messages"][0] == {"role": "system", "content": "You are Elaina."}
    assert body["messages"][1:] == HELLO and body["stream"] is True


def test_anthropic_kind_asks_its_own_way():
    url, body = cloud.request_for(ANTHROPIC, "model-1", "You are Elaina.", HELLO)
    assert url == "https://a.test/v1/messages"
    assert body["system"] == "You are Elaina." and body["messages"] == HELLO
    assert body["max_tokens"] > 0


@pytest.mark.parametrize("provider, image_type", [(OPENAI, "image_url"), (ANTHROPIC, "image")])
def test_pictures_are_sent_the_way_each_company_wants(provider, image_type):
    _, body = cloud.request_for(provider, "model-1", "", [{"role": "user", "content": "what's this?", "images": ["AAAA"]}])
    parts = body["messages"][0]["content"]
    assert {part["type"] for part in parts} == {"text", image_type}


def test_a_reply_streams_in_pieces_from_either_kind(monkeypatch):
    replies = {
        "anthropic": stream({"type": "message_start"},
                            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hel"}},
                            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "lo"}}),
        "openai": stream({"choices": [{"delta": {"content": "Hel"}}]}, {"choices": [{"delta": {"content": "lo"}}]},
                         {"choices": []}),
    }
    for provider in (ANTHROPIC, OPENAI):
        monkeypatch.setattr(cloud.requests, "post", lambda *a, **k: Reply(replies[provider.id]))
        assert list(CloudModel(provider, OPTION, "key").chat("elaina", HELLO)) == ["Hel", "lo"]


def test_headers_carry_the_key_each_companys_way(monkeypatch):
    sent = {}

    def post(url, json, headers, stream, timeout):
        sent.update(headers)
        return Reply()

    monkeypatch.setattr(cloud.requests, "post", post)
    list(CloudModel(ANTHROPIC, OPTION, "the-key").chat("elaina", HELLO))
    assert sent["x-api-key"] == "the-key"
    sent.clear()
    list(CloudModel(OPENAI, OPTION, "the-key").chat("elaina", HELLO))
    assert sent["Authorization"] == "Bearer the-key"


@pytest.mark.parametrize("status, words", [(401, "key"), (403, "key"), (402, "credit"), (404, "another"),
                                           (429, "limit"), (500, "problem")])
def test_problems_are_in_plain_words_and_never_show_the_key(monkeypatch, status, words):
    monkeypatch.setattr(cloud.requests, "post", lambda *a, **k: Reply(status=status))
    with pytest.raises(CloudError) as problem:
        list(CloudModel(OPENAI, OPTION, "secret-key").chat("elaina", HELLO))
    assert words in str(problem.value) and "secret-key" not in str(problem.value)


def test_no_internet_is_said_plainly(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.ConnectionError("no route, key=secret-key")

    monkeypatch.setattr(cloud.requests, "post", fail)
    with pytest.raises(CloudError) as problem:
        list(CloudModel(OPENAI, OPTION, "secret-key").chat("elaina", HELLO))
    assert "internet" in str(problem.value) and "secret-key" not in str(problem.value)


def test_a_cloud_model_says_if_it_can_see_pictures():
    assert "vision" in CloudModel(OPENAI, OPTION, "k").capabilities("elaina")
    assert "vision" not in CloudModel(OPENAI, CloudOption("m", "M", images=False), "k").capabilities("elaina")


def test_the_full_list_leaves_out_what_cant_chat_and_what_is_already_offered(monkeypatch):
    company = Provider("openai", "ChatGPT", "OpenAI", "openai", "https://o.test/v1", "", (OPTION,))
    body = {"data": [{"id": "model-1"}, {"id": "model-2"}, {"id": "text-embedding-3"}, {"id": "whisper-1"}]}
    monkeypatch.setattr(cloud.requests, "get", lambda *a, **k: Reply(body=body))
    assert [model.id for model in cloud.live_models(company, "k")] == ["model-2"]


def test_the_popular_list_still_works_if_the_full_list_cant_be_read(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.ConnectionError("no internet")

    monkeypatch.setattr(cloud.requests, "get", fail)
    assert cloud.live_models(OPENAI, "k") == []
    assert cloud.key_refused(OPENAI, "k") is False  # can't tell, so it isn't refused


def test_only_a_clear_no_refuses_a_key(monkeypatch):
    monkeypatch.setattr(cloud.requests, "get", lambda *a, **k: Reply(status=401))
    assert cloud.key_refused(OPENAI, "k") is True
    monkeypatch.setattr(cloud.requests, "get", lambda *a, **k: Reply(status=404))
    assert cloud.key_refused(OPENAI, "k") is False


def test_keys_go_in_the_password_store_and_can_be_forgotten(keys):
    cloud.save_key("openai", "  the-key  ")
    assert cloud.saved_key("openai") == "the-key"
    cloud.forget_key("openai")
    assert cloud.saved_key("openai") == ""
    cloud.forget_key("openai")  # nothing there: no problem


def test_the_menu_says_whether_a_key_is_saved_but_never_holds_one(keys):
    cloud.save_key("openai", "the-key")
    menu = cloud.overview(cloud.saved_key)
    assert next(company for company in menu if company["id"] == "openai")["has_key"] is True
    assert next(company for company in menu if company["id"] == "google")["has_key"] is False
    assert "the-key" not in json.dumps(menu)


class FakeChat:
    def __init__(self, ollama):
        self.ollama = ollama
        self.talker = ollama
        self.history = []
        self.think = None


class FakeOllama:
    def show(self, name):
        return {"system": "You are Elaina."}

    def models(self):
        return []


@pytest.fixture
def engine(keys, tmp_path, monkeypatch):
    monkeypatch.setattr(elaina, "data_dir", lambda: tmp_path)
    made = ElainaEngine(FakeOllama())
    made.chat = FakeChat(made.ollama)
    return made


def test_picking_a_cloud_model_moves_only_her_answers(engine, monkeypatch):
    cloud.save_key("openai", "the-key")
    info = engine.menu.pick("openai", cloud.load_providers()["openai"].models[0].id)
    assert isinstance(engine.chat.talker, CloudModel)
    assert info["current"]["company"] == "OpenAI"
    assert "You are Elaina." in engine.chat.talker.system
    assert "over the internet" in engine.chat.talker.system
    assert engine.ollama is not engine.chat.talker  # deciding what a message is for stays here


def test_picking_her_own_model_brings_everything_home(engine):
    cloud.save_key("openai", "the-key")
    engine.menu.pick("openai", "gpt-x")
    info = engine.menu.pick()
    assert engine.chat.talker is engine.ollama and info["current"] is None


def test_removing_the_key_goes_back_to_her_own_model(engine):
    cloud.save_key("openai", "the-key")
    engine.menu.pick("openai", "gpt-x")
    assert engine.menu.forget_key("openai")["current"] is None
    assert engine.chat.talker is engine.ollama


def test_a_refused_key_is_not_saved(engine, monkeypatch):
    monkeypatch.setattr(cloud, "key_refused", lambda company, key: True)
    assert "didn't accept" in engine.menu.save_key("openai", "bad-key")["error"]
    assert cloud.saved_key("openai") == ""


def test_an_empty_key_is_not_saved(engine):
    assert "error" in engine.menu.save_key("openai", "   ")


def test_the_choice_is_remembered_with_her_other_settings(engine):
    elaina.save_state({"base_model": "qwen3.5:4b"})
    cloud.save_key("openai", "the-key")
    engine.menu.pick("openai", "gpt-x")
    state = elaina.load_state()
    assert state["base_model"] == "qwen3.5:4b" and state["talk_model"]["model"] == "gpt-x"
    assert "the-key" not in json.dumps(state)


def test_highlight_agents_never_go_to_the_cloud(engine):
    """They see whatever is selected in any program, so they stay on the computer."""
    from concierge.quick.agents import QuickAgents

    engine.quick = QuickAgents(engine.ollama, elaina.ELAINA_MODEL, None)
    cloud.save_key("openai", "the-key")
    engine.menu.pick("openai", "gpt-x")
    assert engine.quick.ollama is engine.ollama


def test_the_practice_engine_never_touches_the_password_store(keys):
    fake = FakeEngine(delay=0)
    fake.menu.save_key("openai", "practice")
    assert keys.keys == {}
    info = fake.menu.pick("openai", cloud.load_providers()["openai"].models[0].id)
    assert info["current"]["company"] == "OpenAI"
    assert fake.menu.forget_key("openai")["current"] is None
