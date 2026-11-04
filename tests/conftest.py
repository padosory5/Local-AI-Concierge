import pytest

from concierge import activity, cloud


@pytest.fixture(autouse=True, scope="session")
def data_folder_kept_apart(tmp_path_factory):
    """Nothing a test does may reach the user's own data folder, not even a sorting
    job still finishing on its thread after its test has ended and undone the
    fixtures below. One did, and counted 30 practice files on the real Today page."""
    with pytest.MonkeyPatch.context() as patch:
        home = tmp_path_factory.mktemp("appdata")
        patch.setenv("LOCALAPPDATA", str(home))
        patch.setenv("XDG_DATA_HOME", str(home))
        yield


@pytest.fixture(autouse=True)
def sendings_kept_apart(tmp_path, monkeypatch):
    """Pretend cloud replies in tests must never show up in the user's own What I see page."""
    monkeypatch.setattr(cloud, "_sent_path", lambda: tmp_path / "sent.json")


@pytest.fixture(autouse=True)
def work_log_kept_apart(tmp_path, monkeypatch):
    """Jobs done in tests must never be counted on the user's own Today page."""
    monkeypatch.setattr(activity, "_path", lambda: tmp_path / "activity.json")
