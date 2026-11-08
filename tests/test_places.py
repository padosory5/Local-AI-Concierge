"""Where the user's Desktop and Downloads really are (concierge/places.py), and the
questions about chores that code answers (engine.py)."""

import sys
from pathlib import Path

import pytest

from concierge.engine import WANTS_ORGANIZE, WANTS_STATUS, WANTS_WHERE
from concierge.places import known_folder


def test_a_folder_windows_does_not_know_falls_back_to_the_home_folder(tmp_path):
    assert known_folder("Nope", tmp_path) == tmp_path / "Nope"
    assert known_folder("home", tmp_path) == tmp_path


@pytest.mark.skipif(sys.platform != "win32", reason="asks Windows")
def test_windows_says_where_the_desktop_and_downloads_are():
    desktop, downloads = known_folder("Desktop"), known_folder("Downloads")
    assert desktop.is_dir() and downloads.is_dir()
    # With OneDrive backup on, the Desktop the user sees is not ~/Desktop.
    assert desktop.name and desktop != Path.home() / "nowhere"


def test_the_questions_about_chores_that_code_answers():
    assert WANTS_WHERE.search("wheres the folder")
    assert WANTS_WHERE.search("where is that folder created")
    assert WANTS_WHERE.search("where is the file?")
    assert WANTS_WHERE.search("in which folder did you put that file inside")
    assert not WANTS_WHERE.search("where is Seoul")
    assert WANTS_STATUS.search("what did you do")
    assert WANTS_STATUS.search("did you move anything")
    assert WANTS_STATUS.search("which folders did you make")
    assert not WANTS_STATUS.search("what is the capital of France")
    assert WANTS_ORGANIZE.search("I just downloaded a file")
    assert WANTS_ORGANIZE.search("organize it")
    assert not WANTS_ORGANIZE.search("how are you")
