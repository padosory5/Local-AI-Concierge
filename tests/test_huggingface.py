import pytest
import requests

from concierge import huggingface
from concierge.huggingface import HubError, best_file, browse, tag_from


def files(*pairs):
    return [{"rfilename": name, "size": size} for name, size in pairs]


class Reply:
    def __init__(self, body, ok=True):
        self.body, self.ok = body, ok

    def json(self):
        return self.body


@pytest.fixture(autouse=True)
def nothing_saved():
    huggingface._cache.clear()


def test_the_usual_version_is_chosen():
    assert best_file(files(("M-BF16.gguf", 18), ("M-Q4_K_M.gguf", 5), ("M-Q8_0.gguf", 9))) == ("Q4_K_M", 5)


def test_a_model_with_other_versions_takes_the_smallest():
    assert best_file(files(("M-Q2_K.gguf", 2), ("M-BF16.gguf", 18))) == ("Q2_K", 2)


def test_a_split_model_counts_all_its_parts():
    assert best_file(files(("M-Q4_K_M-00001-of-00002.gguf", 5), ("M-Q4_K_M-00002-of-00002.gguf", 4))) == ("Q4_K_M", 9)


def test_the_sight_file_and_other_files_are_not_the_model():
    assert best_file(files(("mmproj-M-BF16.gguf", 1), ("README.md", 1), ("config.json", 1))) == ("", 0)


def test_lowercase_names_still_work():
    assert best_file(files(("model.q4_k_m.gguf", 5))) == ("Q4_K_M", 5)


def fake_hub(monkeypatch, rows, details):
    asked = []

    def get(url, params=None, timeout=None):
        asked.append((url, params))
        if url == huggingface.API:
            return Reply(rows)
        return Reply(details[url.removeprefix(f"{huggingface.API}/")])

    monkeypatch.setattr(huggingface.requests, "get", get)
    return asked


GOOD = {"siblings": files(("Good-Q4_K_M.gguf", 5_800_000_000), ("mmproj-Good.gguf", 900_000_000)),
        "gguf": {"architecture": "qwen35"}, "cardData": {"license": "mit"}}


def test_a_model_comes_with_what_ollama_should_fetch(monkeypatch):
    fake_hub(monkeypatch, [{"id": "owner/Good-GGUF", "downloads": 500, "likes": 9}], {"owner/Good-GGUF": GOOD})
    model = browse()[0]
    assert model["tag"] == "hf.co/owner/Good-GGUF:Q4_K_M"
    assert model["name"] == "Good" and model["author"] == "owner"
    assert model["size_gb"] == 5.8 and model["family"] == "qwen35" and model["license"] == "mit"
    assert model["vision"] is True


def test_models_that_ask_for_an_account_are_left_out(monkeypatch):
    fake_hub(monkeypatch, [{"id": "a/Gated"}, {"id": "b/Good"}], {"a/Gated": {**GOOD, "gated": "auto"}, "b/Good": GOOD})
    assert [model["id"] for model in browse()] == ["b/Good"]


def test_a_repository_with_nothing_to_run_is_left_out(monkeypatch):
    fake_hub(monkeypatch, [{"id": "a/Empty"}], {"a/Empty": {"siblings": files(("README.md", 1))}})
    assert browse() == []


def test_searching_and_sorting_are_passed_on(monkeypatch):
    asked = fake_hub(monkeypatch, [], {})
    browse("qwen", "likes", "vision")
    params = asked[0][1]
    assert params["search"] == "qwen" and params["sort"] == "likes"
    assert params["pipeline_tag"] == huggingface.VISION and params["filter"] == "gguf"


def test_the_same_search_isnt_asked_twice(monkeypatch):
    asked = fake_hub(monkeypatch, [], {})
    browse("qwen")
    browse("QWEN ")
    assert len(asked) == 1


def test_no_internet_is_said_plainly(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.ConnectionError("no route")

    monkeypatch.setattr(huggingface.requests, "get", fail)
    with pytest.raises(HubError, match="internet"):
        browse()


def test_hugging_face_being_down_is_said_plainly(monkeypatch):
    monkeypatch.setattr(huggingface.requests, "get", lambda *a, **k: Reply({}, ok=False))
    with pytest.raises(HubError, match="problem"):
        browse()


@pytest.mark.parametrize("text, tag", [
    ("llama3.3", "llama3.3"),
    ("qwen3.5:9b", "qwen3.5:9b"),
    ("https://huggingface.co/owner/Model-GGUF", "hf.co/owner/Model-GGUF"),
    ("https://hf.co/owner/Model-GGUF?download=true", "hf.co/owner/Model-GGUF"),
    ("hf.co/owner/Model-GGUF:Q4_K_M", "hf.co/owner/Model-GGUF:Q4_K_M"),
    ("two words", ""),
    ("name; rm -rf", ""),
    ("", ""),
])
def test_names_and_links_become_what_ollama_fetches(text, tag):
    assert tag_from(text) == tag
