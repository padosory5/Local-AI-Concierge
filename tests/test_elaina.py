from concierge import elaina
from concierge.ollama import _normalize_url


class FakeOllama:
    def __init__(self, reply="Hi there.", capabilities=("completion", "thinking")):
        self.reply = reply
        self.caps = list(capabilities)
        self.calls = []
        self.unloaded = []

    def capabilities(self, name):
        return self.caps

    def chat(self, model, messages, think=None, keep_alive=None):
        self.calls.append({"messages": list(messages), "think": think, "keep_alive": keep_alive})
        yield from self.reply.split(" ")

    def unload(self, name):
        self.unloaded.append(name)

    is_loaded = False
    refreshed = 0

    def loaded(self):
        return [{"name": "elaina:latest"}] if self.is_loaded else []

    def refresh(self, name, keep_alive):
        self.refreshed += 1


def test_check_in_keeps_a_loaded_elaina_loaded():
    chat = elaina.ElainaChat(FakeOllama())
    chat.ollama.is_loaded = True
    chat.check_in()
    assert chat.ollama.refreshed == 1


def test_check_in_never_loads_elaina():
    chat = elaina.ElainaChat(FakeOllama())
    chat.check_in()
    assert chat.ollama.refreshed == 0


def test_no_check_in_after_close():
    chat = elaina.ElainaChat(FakeOllama())
    chat.ollama.is_loaded = True
    chat.close()
    chat.check_in()
    assert chat.ollama.refreshed == 0


def test_close_unloads_elaina():
    chat = elaina.ElainaChat(FakeOllama())
    "".join(chat.send("hello"))
    assert chat.ollama.calls[0]["keep_alive"] == elaina.KEEP_ALIVE
    chat.close()
    assert chat.ollama.unloaded == [elaina.ELAINA_MODEL]


def test_close_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(elaina, "UNLOAD_ON_EXIT", False)
    chat = elaina.ElainaChat(FakeOllama())
    chat.close()
    assert chat.ollama.unloaded == []


def test_thinking_is_turned_off_for_thinking_models():
    chat = elaina.ElainaChat(FakeOllama())
    "".join(chat.send("hello"))
    assert chat.ollama.calls[0]["think"] is False


def test_think_is_not_sent_to_models_without_it():
    chat = elaina.ElainaChat(FakeOllama(capabilities=["completion"]))
    "".join(chat.send("hello"))
    assert chat.ollama.calls[0]["think"] is None


def test_history_keeps_both_sides_and_resets():
    chat = elaina.ElainaChat(FakeOllama())
    "".join(chat.send("one"))
    "".join(chat.send("two"))
    assert [m["role"] for m in chat.history] == ["user", "assistant", "user", "assistant"]
    chat.reset()
    assert chat.history == []


def test_old_history_is_dropped_but_starts_with_the_user():
    chat = elaina.ElainaChat(FakeOllama())
    for i in range(40):
        chat.history += [
            {"role": "user", "content": "q" * 300},
            {"role": "assistant", "content": "a" * 300},
        ]
    chat.history.append({"role": "user", "content": "latest"})
    recent = chat._recent()
    assert recent[-1]["content"] == "latest"
    assert recent[0]["role"] == "user"
    assert sum(len(m["content"]) for m in recent) <= elaina.HISTORY_CHARS


def test_ollama_host_values_become_urls():
    assert _normalize_url("0.0.0.0") == "http://127.0.0.1:11434"
    assert _normalize_url("localhost:11500") == "http://127.0.0.1:11500"
    assert _normalize_url("http://192.168.0.5:11434/") == "http://192.168.0.5:11434"


def test_closing_filler_is_dropped():
    reply = "The capital of Australia is Canberra. Let me know if you need anything else!"
    model = FakeOllama()
    model.chat = lambda *a, **k: iter(word + " " for word in reply.split(" "))  # streamed word by word
    chat = elaina.ElainaChat(model)
    assert "".join(chat.send("capital of Australia?")).strip() == "The capital of Australia is Canberra."
    assert chat.history[-1]["content"] == "The capital of Australia is Canberra."


def test_filler_in_the_middle_is_kept():
    pieces = list(elaina.without_closing_filler(iter(["If you need a spare key, ask the office. ",
                                                       "It opens at 9."])))
    assert "".join(pieces) == "If you need a spare key, ask the office. It opens at 9."


def test_reply_that_is_only_text_without_a_full_stop():
    assert "".join(elaina.without_closing_filler(iter(["Hi there"]))) == "Hi there"


def test_a_reply_that_is_all_filler_keeps_its_first_sentence():
    pieces = elaina.without_closing_filler(iter(["Happy to help! ", "Let me know if you need more."]))
    assert "".join(pieces) == "Happy to help! "
