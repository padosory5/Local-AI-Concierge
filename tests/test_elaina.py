from concierge import elaina
from concierge.ollama import _normalize_url


class FakeOllama:
    def __init__(self, reply="Hi there.", capabilities=("completion", "thinking")):
        self.reply = reply
        self.caps = list(capabilities)
        self.calls = []

    def capabilities(self, name):
        return self.caps

    def chat(self, model, messages, think=None):
        self.calls.append({"messages": list(messages), "think": think})
        yield from self.reply.split(" ")


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
