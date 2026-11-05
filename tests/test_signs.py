import os
import time

from concierge import signs
from concierge.signs import THIS_COMPUTER


def make_home(tmp_path):
    """A small made-up home folder: two projects, school and work files, an app's
    own folder that must be skipped, and a hidden one."""
    home = tmp_path / "home"
    game = home / "localProj" / "puzzle-cat"
    (game / ".git").mkdir(parents=True)
    for n in range(3):
        (game / f"player{n}.cs").write_text("class Player {}")
    site = home / "Documents" / "site"
    (site / ".git").mkdir(parents=True)
    (site / "app.py").write_text("print('hi')")
    (site / "node_modules" / "lib").mkdir(parents=True)
    for n in range(40):
        (site / "node_modules" / "lib" / f"x{n}.js").write_text("")  # someone else's code
    lectures = home / "Documents" / "school"
    lectures.mkdir(parents=True)
    for n in range(12):
        (lectures / f"Lecture {n}.pdf").write_text("")
    for n in range(10):
        (home / "Documents" / f"meeting notes {n}.docx").write_text("")
    (home / "AppData" / "Roaming").mkdir(parents=True)
    (home / "AppData" / "Roaming" / "secret.docx").write_text("")
    (home / ".hidden").mkdir()
    menu = tmp_path / "menu"
    (menu / "Unity").mkdir(parents=True)
    for name in ("Unity Hub", "Visual Studio Code", "Steam", "Battle.net", "Uninstall Steam", "Zoom Workplace"):
        (menu / f"{name}.lnk").write_text("")
    return home, [menu]


def test_looking_around_counts_names_and_kinds_only(tmp_path):
    home, menus = make_home(tmp_path)
    summary = signs.look_around(home, menus)
    assert summary["complete"] and summary["project_count"] == 2
    assert {p["name"]: p["language"] for p in summary["projects"]} == {"puzzle-cat": "C#", "site": "Python"}
    assert summary["files"] == {"PDF": 12, "Word": 10}  # nothing from AppData
    assert summary["study_files"] == 12 and summary["work_files"] == 10
    assert "Uninstall Steam" not in summary["app_names"] and "Unity Hub" in summary["app_names"]
    assert "lecture 0" not in str(summary).lower()  # file names are counted, never kept


def test_every_guess_says_what_it_came_from(tmp_path):
    home, menus = make_home(tmp_path)
    facts = {fact["fact"]: fact["quote"] for fact in signs.facts_from(signs.look_around(home, menus))}
    assert facts["Plays PC games"] == "Battle.net and Steam are installed"  # one fact for both
    assert facts["Makes things in Unity"] == "Unity Hub is installed"
    code = next(fact for fact in facts if fact.startswith("Writes code, mostly in"))
    assert "C#" in code and "Python" in code and facts[code].startswith("2 folders with code, like")
    assert facts["Keeps school files: lectures and assignments"] == "12 files named like lectures or assignments"
    assert "Has video meetings" in facts
    assert all(fact["source"] == THIS_COMPUTER and fact["kept"] is None for fact in signs.facts_from(signs.look_around(home, menus)))


def test_the_roles_it_points_to(tmp_path):
    home, menus = make_home(tmp_path)
    roles = signs.look_around(home, menus)["roles"]
    assert signs.role_words(roles)[0] == "developer" and roles["student"] >= 1


def test_a_huge_disk_gets_a_partial_look_not_a_long_wait(tmp_path):
    home, menus = make_home(tmp_path)
    ticks = iter(range(0, 10_000, 30))
    summary = signs.look_around(home, menus, clock=lambda: next(ticks))
    assert summary["complete"] is False


def test_a_folder_link_is_never_followed(tmp_path):
    home, menus = make_home(tmp_path)
    try:
        os.symlink(home / "Documents", home / "Documents" / "loop", target_is_directory=True)
    except OSError:
        return  # this computer doesn't allow links without admin rights
    summary = signs.look_around(home, menus)
    assert summary["files"]["PDF"] == 12


def test_nothing_known_is_said_plainly():
    assert signs.facts_from({"app_names": [], "projects": [], "files": {}, "study_files": 0}) == []
    assert signs.role_words({}) == []


def test_it_is_quick(tmp_path):
    home, menus = make_home(tmp_path)
    began = time.monotonic()
    signs.look_around(home, menus)
    assert time.monotonic() - began < 5


def record(hours, runs=3, last=133_000_000_000_000_000):
    """One of Windows' own records (UserAssist): run count at 4, time in front in ms at 12."""
    import struct

    data = bytearray(72)
    struct.pack_into("<III", data, 4, runs, runs, int(hours * 3_600_000))
    struct.pack_into("<Q", data, 60, last)
    return bytes(data)


def test_apps_are_named_the_way_people_know_them():
    assert signs.app_name("OpenAI.Codex_2p2nqsd0c76g0!App") == "Codex"
    assert signs.app_name("Claude_pzs8sxrjxfjjc!Claude") == "Claude"
    assert signs.app_name("Microsoft.VisualStudioCode") == "Visual Studio Code"
    assert signs.app_name("com.squirrel.Discord.Discord") == "Discord"
    assert signs.app_name("notion.id") == "Notion"
    assert signs.app_name("Naver_Whale") == "Naver Whale"
    assert signs.app_name(r"{7C5A40EF}\Steam\steamapps\common\Call of Duty HQ\cod.exe") == "Call of Duty HQ"
    assert signs.app_name(r"D:\games\ZenlessZoneZero Game\ZenlessZoneZero.exe") == "Zenless Zone Zero"


def test_what_is_used_most_comes_from_windows_own_count():
    used = signs.app_use([("Naver_Whale", record(5.2)), ("Claude_x!Claude", record(4.4)),
                          (r"{X}\Steam\steamapps\common\Hollow Knight\hollow_knight.exe", record(1.0)),
                          ("UEME_CTLSESSION", record(14)), (r"{X}\Python311\python.exe", record(0.4)),
                          ("LocalAIConcierge.Elaina", record(0.4)), ("Barely.Used", record(0.01)),
                          ("MyBank.Banking_x!App", record(3.0))])
    assert [(entry["app"], entry["kind"]) for entry in used] == [("Naver Whale", "browsing"), ("Claude", "ai"),
                                                                ("Hollow Knight", "games")]
    assert signs.activities(used) == {"browsing": 5.2, "ai": 4.4, "games": 1.0}


def test_what_you_use_and_do_most_become_facts_that_say_where_from(tmp_path):
    home, menus = make_home(tmp_path)
    summary = signs.look_around(home, menus, use=[("Naver_Whale", record(5.2)), ("Microsoft.VisualStudioCode", record(3.0))])
    facts = {fact["fact"]: fact["quote"] for fact in signs.facts_from(summary)}
    assert facts["Spends the most time in Naver Whale and Visual Studio Code"] == "5.2 and 3 hours in front, by Windows' own count"
    assert facts["Uses the computer most for browsing the web and writing code"] == "browsing the web 5.2 hours, writing code 3 hours"
    assert summary["recent"]["documents"] == 22  # the made-up files were all just made
    assert facts["Lately works most on documents"] == "22 documents files changed in the last 30 days"
