"""Signs on this computer of who the user is: the apps they have, the kinds of files
they keep and the code they're writing, so Noir can guess what kind of user they
are before anyone gives its their chats (history.py, portrait.py).

Only names, kinds and counts are read, never what's inside a file, and nothing is
looked at until the user says yes. Only the summary is kept, never a list of files.
It's plain code with no model: "Makes things in Unity" comes from Unity being
installed and says so beside it, so every guess can be checked, and the user keeps
or drops each one like the facts from their chats.
"""

from __future__ import annotations

import os
import re
import stat
import struct
import sys
import time
from collections import Counter
from pathlib import Path

# Lower-case shortcut names (Start menu, desktop) -> (fact, what it's about, the role
# it points to, or None). {name} is the shortcut's own name; kinds that often come as
# several apps (games, meetings) have one fact, with the apps named beside it.
KNOWN_APPS = (
    (r"visual studio code|^vs ?code$", "Writes code in Visual Studio Code", "tool", "developer"),
    (r"^visual studio 20\d\d|^visual studio (community|professional|enterprise)", "Uses Visual Studio", "tool", "developer"),
    (r"^cursor$", "Writes code in Cursor", "tool", "developer"),
    (r"pycharm", "Writes Python in PyCharm", "tool", "developer"),
    (r"android studio", "Builds Android apps in Android Studio", "tool", "developer"),
    (r"intellij|webstorm|rider|clion|goland", "Writes code in {name}", "tool", "developer"),
    (r"github desktop|^git bash$|^git gui$", "Uses Git", "tool", "developer"),
    (r"^docker desktop$", "Uses Docker", "tool", "developer"),
    (r"^unity hub$|^unity( 20\d\d)?", "Makes things in Unity", "tool", "developer"),
    (r"unreal engine", "Makes things in Unreal Engine", "tool", "developer"),
    (r"^ollama$|^lm studio$|^jan$|^gpt4all$", "Already runs AI on this computer with {name}", "interest", "developer"),
    (r"^blender", "Makes 3D models in Blender", "interest", None),
    (r"photoshop|illustrator|^figma$|clip studio|^krita|indesign", "Draws or designs on the computer", "tool", None),
    (r"premiere|davinci resolve|^capcut$|vegas pro|after effects", "Edits videos", "interest", None),
    (r"^fl studio|ableton|cubase|garageband", "Makes music", "interest", None),
    (r"^obs studio$", "Records or streams with OBS", "interest", None),
    (r"^steam$|battle\.net|^riot client$|league of legends|^ea app$|ubisoft connect", "Plays PC games", "interest", None),
    (r"^(microsoft )?(word|excel|powerpoint|outlook)( 20\d\d)?$", "Uses Microsoft Office", "tool", "office"),
    (r"hancom|^hwp|한컴|^한글", "Writes documents in Hangul (HWP)", "tool", "office"),
    (r"microsoft teams|^teams$|^zoom( workplace)?$|^slack$|webex", "Has video meetings", "work", "office"),
    (r"^notion$|^obsidian$|onenote|evernote", "Takes notes in {name}", "tool", None),
    (r"^anki$", "Studies with Anki flashcards", "study", "student"),
    (r"matlab|rstudio|^spss|^stata|anaconda", "Works with data in {name}", "tool", None),
    (r"autocad|solidworks|fusion 360|sketchup|revit", "Designs with {name}", "tool", None),
)
# Shortcuts that aren't the app itself.
NOT_APPS = re.compile(r"uninstall|help|readme|release notes|website|documentation|manual|license|support", re.IGNORECASE)
FILE_KINDS = {
    "Word": (".doc", ".docx"), "Excel": (".xls", ".xlsx"), "PowerPoint": (".ppt", ".pptx"), "PDF": (".pdf",),
    "Hangul": (".hwp", ".hwpx"), "Photoshop": (".psd",), "Illustrator": (".ai",), "3D": (".blend", ".fbx"),
    "video projects": (".prproj", ".drp", ".aep"), "music projects": (".flp", ".als"),
    "photos": (".jpg", ".jpeg", ".png", ".heic"), "videos": (".mp4", ".mov", ".mkv"), "songs": (".mp3", ".wav", ".flac", ".m4a"),
}
# Which kinds of work the files changed lately are, for "Lately works most on...".
RECENT_GROUPS = {"Word": "documents", "Excel": "documents", "PowerPoint": "documents", "PDF": "documents",
                 "Hangul": "documents", "Photoshop": "design", "Illustrator": "design", "3D": "design",
                 "video projects": "videos", "videos": "videos", "music projects": "music", "songs": "music",
                 "photos": "photos"}
RECENT_DAYS = 30
# Windows' own count, for each program opened from Start or the taskbar, of how often
# and how long it was in front. Read only, never changed; only the top few are kept.
USER_ASSIST = r"Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist"
MAX_APPS_KEPT = 12
MIN_HOURS = 0.1
# What each app is mostly for, by words in its name. Games are also known by their folder.
ACTIVITIES = (
    ("ai", "AI tools", r"claude|chatgpt|codex|copilot|gemini|perplexity|hermes|lm studio|ollama|\bjan\b"),
    ("browsing", "browsing the web", r"chrome|\bedge\b|firefox|whale|brave|opera|\barc\b"),
    ("coding", "writing code", r"visual studio|vs ?code|cursor|pycharm|intellij|webstorm|rider|android studio"
                               r"|terminal|powershell|\bgit\b|unity|unreal|godot|jupyter"),
    ("chatting", "chatting", r"kakao ?talk|discord|slack|teams|telegram|\bline\b|whatsapp|messenger|zoom"),
    ("documents", "documents", r"\bword\b|excel|powerpoint|hwp|hangul|한글|notion|obsidian|onenote|acrobat|outlook"),
    ("design", "design", r"photoshop|illustrator|figma|blender|premiere|davinci|capcut|clip studio|krita"),
    ("music", "music", r"spotify|melon|music|genie"),
    ("video", "videos", r"vlc|potplayer|netflix|youtube|disney|tving|wavve"),
    ("games", "games", r"steam|battle\.net|riot|league of legends|epic games|ubisoft|minecraft|roblox|valorant"),
)
GAME_FOLDERS = re.compile(r"steamapps|[\\/]games[\\/]|riot games|epic games|battle\.net", re.IGNORECASE)
# Folders inside a game that say less than the one above them ("cod.exe" in "Call of Duty HQ").
PLAIN_FOLDERS = re.compile(r"^(bin|bin64|x64|x86|win64|win32|binaries|common|multiexe|game|games|app|current|"
                           r"launcher|steam|steamapps)$", re.IGNORECASE)
# Programs that aren't something the user does: Windows' own parts, installers, Noir itself.
NOT_ACTIVITIES = re.compile(r"^ueme|explorer|^python|^cmd$|conhost|rundll|msiexec|setup|install|update|noir"
                            r"|noiragents|^control$|^mmc$|regedit|task ?manager|taskmgr|snipping|^settings$"
                            r"|^search", re.IGNORECASE)
# Short Windows names people wouldn't recognise.
FRIENDLY = {"code": "Visual Studio Code", "msedge": "Microsoft Edge", "chrome": "Chrome", "firefox": "Firefox",
            "whale": "Naver Whale", "kakaotalk": "KakaoTalk", "kakao talk": "KakaoTalk", "windows terminal": "Terminal",
            "winword": "Word", "powerpnt": "PowerPoint", "excel": "Excel", "hwp": "Hangul"}
CODE = {".py": "Python", ".ipynb": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
        ".tsx": "TypeScript", ".cs": "C#", ".java": "Java", ".kt": "Kotlin", ".cpp": "C++", ".cc": "C++",
        ".c": "C", ".go": "Go", ".rs": "Rust", ".swift": "Swift", ".rb": "Ruby", ".php": "PHP", ".dart": "Dart",
        ".lua": "Lua", ".r": "R", ".m": "MATLAB", ".gd": "GDScript"}
# File names that look like school or like work, counted, never kept.
STUDY_NAMES = re.compile(r"lecture|homework|assignment|syllabus|midterm|final exam|quiz|lab report|week ?\d"
                         r"|강의|과제|중간고사|기말|수업|레포트|시험", re.IGNORECASE)
WORK_NAMES = re.compile(r"invoice|meeting|proposal|minutes|quarterly|report|presentation|회의|보고서|제안서|견적",
                        re.IGNORECASE)
# Folders that say nothing about the person, or hold someone else's code.
SKIP_DIRS = {"appdata", "node_modules", "venv", ".venv", "env", "__pycache__", "site-packages", "dist", "build",
             "target", "bin", "obj", "library", "packages", "vendor", "$recycle.bin", "temp", "tmp", "cache",
             "caches", "logs", "steamapps", "program files", "windows"}
MAX_ENTRIES = 150_000  # a full look takes a few seconds; a huge disk gets a partial one
MAX_SECONDS = 20
MAX_DEPTH = 7
MAX_PROJECTS_KEPT = 8
REPARSE_POINT = 0x400  # junctions and links, which can loop back on themselves
THIS_COMPUTER = "This computer"


def look_around(home: Path | None = None, start_menus: list[Path] | None = None,
                clock=time.monotonic, use: list[tuple[str, bytes]] | None = None) -> dict:
    """What this computer says about its user, as counts and names only. `use` is
    Windows' own count as (name, record) pairs; read from Windows when not given."""
    home = home or Path.home()
    began = clock()
    apps = installed_apps(start_menus if start_menus is not None else _start_menus(home))
    walked = _walk(_roots(home), began + MAX_SECONDS, clock)
    used = app_use(use if use is not None else _user_assist())
    summary = {"looked": time.time(), "app_names": sorted({name for *_, name in apps}), **walked,
               "used": used[:MAX_APPS_KEPT], "activities": activities(used), "seconds": round(clock() - began, 1)}
    summary["roles"] = _roles(apps, walked, summary["activities"])
    return summary


def app_use(records: list[tuple[str, bytes]]) -> list[dict]:
    """The programs used most, by Windows' own count of hours in front, most first.
    Programs that aren't an activity, or that touch what isn't hers to work out
    (health, money and the like), are left out."""
    from .portrait import SENSITIVE

    found: dict[str, dict] = {}
    for raw, data in records:
        if not isinstance(data, bytes) or len(data) < 68:
            continue
        runs, _, focus_ms = struct.unpack_from("<III", data, 4)
        last = struct.unpack_from("<Q", data, 60)[0]
        name = app_name(raw)
        if not focus_ms or NOT_ACTIVITIES.search(name) or NOT_ACTIVITIES.search(re.split(r"[\\/]", raw)[-1]) \
                or SENSITIVE.search(name):
            continue
        entry = found.setdefault(name, {"app": name, "hours": 0.0, "runs": 0, "last": 0.0, "kind": activity_of(name, raw)})
        entry["hours"] += focus_ms / 3_600_000
        entry["runs"] += runs
        entry["last"] = max(entry["last"], (last - 116_444_736_000_000_000) / 10_000_000 if last else 0.0)
    ranked = sorted(found.values(), key=lambda entry: -entry["hours"])
    return [dict(entry, hours=round(entry["hours"], 1)) for entry in ranked if entry["hours"] >= MIN_HOURS]


def app_name(raw: str) -> str:
    """A readable name from Windows' record: a program's path, or a Store app's id
    ("OpenAI.Codex_2p2nqsd0c76g0!App" is Codex, "Microsoft.VisualStudioCode" is
    Visual Studio Code, a game's .exe is named by its folder)."""
    if "!" in raw:
        family, app = raw.split("!", 1)
        name = app if app.lower() not in ("app", "") else family.split("_")[0].split(".")[-1]
    elif raw.lower().endswith((".exe", ".lnk")):
        parts = re.split(r"[\\/]", raw)
        name = parts[-1][:-4]
        folders = [part for part in parts[:-1] if part and not part.startswith("{") and not PLAIN_FOLDERS.match(part)]
        if raw.lower().endswith(".exe") and folders and GAME_FOLDERS.search(raw):
            name = folders[-1]
    else:
        pieces = raw.split(".")
        name = pieces[-2] if len(pieces) > 1 and pieces[-1].lower() in ("id", "app", "desktop") else pieces[-1]
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name.replace("_", " ")).strip()
    name = re.sub(r"\s+game$", "", name, flags=re.IGNORECASE) or name  # a game's folder is often "<name> Game"
    return FRIENDLY.get(name.lower(), name[:1].upper() + name[1:])


def activity_of(name: str, raw: str = "") -> str:
    if GAME_FOLDERS.search(raw):
        return "games"
    return next((kind for kind, _, pattern in ACTIVITIES if re.search(pattern, name, re.IGNORECASE)), "other")


def activities(used: list[dict]) -> dict[str, float]:
    """Hours in front for each kind of activity, most first, "other" left out."""
    hours = Counter()
    for entry in used:
        if entry["kind"] != "other":
            hours[entry["kind"]] += entry["hours"]
    return {kind: round(total, 1) for kind, total in hours.most_common()}


def installed_apps(start_menus: list[Path]) -> list[tuple[str, str, str | None, str]]:
    """(fact, about, role, app name) for each known app with a shortcut (a Start menu
    or desktop shortcut on Windows, an app in the Applications folders on a Mac)."""
    found, seen = [], set()
    for folder in start_menus:
        if not folder.is_dir():
            continue
        shortcuts = folder.rglob("*.lnk") if sys.platform == "win32" else folder.glob("*.app")
        for shortcut in shortcuts:
            name = shortcut.stem.strip()
            if NOT_APPS.search(name) or name.lower() in seen:
                continue
            seen.add(name.lower())
            if known := _known(name):
                found.append((*known, name))
    return found


def facts_from(summary: dict) -> list[dict]:
    """Each guess as a fact with what it came from, for the user to keep or drop."""
    facts: list[tuple[str, str, str]] = []
    apps: dict[str, tuple[str, list[str]]] = {}  # fact: (about, the apps it came from)
    for name in summary.get("app_names", []):
        if known := _known(name):
            apps.setdefault(known[0], (known[1], []))[1].append(name)
    for fact, (about, names) in apps.items():
        facts.append((about, fact, f"{_listed(names[:3])} {'is' if len(names) == 1 else 'are'} installed"))
    projects = summary.get("projects", [])
    if projects:
        languages = Counter(project["language"] for project in projects if project.get("language"))
        top = [language for language, _ in languages.most_common(2)]
        if top:
            facts.append(("tool", f"Writes code, mostly in {' and '.join(top)}",
                          f"{summary.get('project_count', len(projects))} folders with code, like {projects[0]['name']}"))
        facts.append(("work", f"Is working on {projects[0]['name']}", f"its files changed {_ago(projects[0]['latest'])}"))
    if summary.get("study_files", 0) >= 10:
        facts.append(("study", "Keeps school files: lectures and assignments",
                      f"{summary['study_files']} files named like lectures or assignments"))
    files = summary.get("files", {})
    office = [kind for kind in ("Word", "Excel", "PowerPoint") if files.get(kind, 0) >= 10]
    if office:
        facts.append(("work", f"Works with {_listed(office)} files", ", ".join(f"{files[k]} {k}" for k in office)))
    if files.get("Hangul", 0) >= 5:
        facts.append(("work", "Writes documents in Hangul (HWP)", f"{files['Hangul']} HWP files"))
    used = summary.get("used", [])[:3]
    if used:
        hours = _listed([format(entry["hours"], "g") for entry in used])
        facts.append(("tool", f"Spends the most time in {_listed([entry['app'] for entry in used])}",
                      f"{hours} hours in front, by Windows' own count"))
    doing = [kind for kind in summary.get("activities", {})][:3]
    if doing:
        words = [next(said for kind_, said, _ in ACTIVITIES if kind_ == kind) for kind in doing]
        facts.append(("interest", f"Uses the computer most for {_listed(words)}",
                      ", ".join(f"{word} {summary['activities'][kind]:g} hours" for word, kind in zip(words, doing))))
    recent = summary.get("recent", {})
    if recent:
        group, count = max(recent.items(), key=lambda item: item[1])
        if count >= 10:
            facts.append(("work", f"Lately works most on {group}", f"{count} {group} files changed in the last {RECENT_DAYS} days"))
    return [_fact(about, fact, quote) for about, fact, quote in facts]


def role_words(roles: dict) -> list[str]:
    """The one or two roles that clearly fit, strongest first."""
    strong = [role for role, score in sorted(roles.items(), key=lambda item: -item[1]) if score >= 2]
    return strong[:2]


# --------------------------------------------------------------- looking


def _user_assist() -> list[tuple[str, bytes]]:
    """Windows' own count as (program, record) pairs; names are stored in ROT13."""
    if sys.platform != "win32":
        return []
    import codecs
    import winreg

    pairs = []
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, USER_ASSIST)
    except OSError:
        return []
    with root:
        for i in range(winreg.QueryInfoKey(root)[0]):
            try:
                key = winreg.OpenKey(root, winreg.EnumKey(root, i) + "\\Count")
            except OSError:
                continue
            with key:
                for j in range(winreg.QueryInfoKey(key)[1]):
                    raw, data, _ = winreg.EnumValue(key, j)
                    pairs.append((codecs.decode(raw, "rot13"), data))
    return pairs


def _start_menus(home: Path) -> list[Path]:
    if sys.platform == "darwin":
        places = [Path("/Applications"), home / "Applications"]
    else:
        places = [Path(os.environ.get("ProgramData", "C:/ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
                  Path(os.environ.get("APPDATA", home / "AppData/Roaming")) / "Microsoft/Windows/Start Menu/Programs",
                  home / "Desktop"]
    return [place for place in places if place.is_dir()]


def _roots(home: Path) -> list[Path]:
    """Every folder in the user's own folder, but not the hidden or app ones."""
    try:
        return [entry for entry in home.iterdir() if entry.is_dir() and _worth_a_look(entry.name)
                and not _is_link(entry)]
    except OSError:
        return []


def _walk(roots: list[Path], deadline: float, clock) -> dict:
    files, recent, study, work, entries = Counter(), Counter(), 0, 0, 0
    lately = time.time() - RECENT_DAYS * 86400
    projects: dict[str, dict] = {}
    stack = [(root, 0, None) for root in roots]
    complete = True
    while stack:
        folder, depth, project = stack.pop()
        if entries >= MAX_ENTRIES or clock() > deadline:
            complete = False
            break
        try:
            children = list(os.scandir(folder))
        except OSError:
            continue
        if project is None and any(child.name == ".git" for child in children):
            project = str(folder)
            projects[project] = {"name": Path(folder).name, "code": Counter(), "latest": 0.0}
        for child in children:
            entries += 1
            try:
                info = child.stat(follow_symlinks=False)
            except OSError:
                continue
            if getattr(info, "st_file_attributes", 0) & REPARSE_POINT:
                continue
            if stat.S_ISDIR(info.st_mode):
                if depth < MAX_DEPTH and _worth_a_look(child.name):
                    stack.append((Path(child.path), depth + 1, project))
                continue
            extension = os.path.splitext(child.name)[1].lower()
            kind = next((kind for kind, endings in FILE_KINDS.items() if extension in endings), None)
            if kind:
                files[kind] += 1
                stem = os.path.splitext(child.name)[0]
                study += bool(STUDY_NAMES.search(stem))
                work += bool(WORK_NAMES.search(stem))
                if info.st_mtime >= lately:
                    recent[RECENT_GROUPS[kind]] += 1
            if project and extension in CODE:
                projects[project]["code"][CODE[extension]] += 1
                projects[project]["latest"] = max(projects[project]["latest"], info.st_mtime)
                if info.st_mtime >= lately:
                    recent["code"] += 1
    kept = sorted((p for p in projects.values() if p["code"]), key=lambda p: -p["latest"])
    return {"files": dict(files), "recent": dict(recent), "study_files": study, "work_files": work,
            "project_count": len(kept),
            "projects": [{"name": p["name"], "language": p["code"].most_common(1)[0][0], "latest": p["latest"]}
                         for p in kept[:MAX_PROJECTS_KEPT]],
            "complete": complete, "entries": entries}


def _roles(apps: list, walked: dict, doing: dict[str, float]) -> dict[str, int]:
    roles = Counter(role for _, _, role, _ in apps if role)
    roles["developer"] += min(walked["project_count"], 5) + min(int(doing.get("coding", 0) // 2), 3)
    roles["office"] += min(int(doing.get("documents", 0) // 2), 3)
    roles["student"] += min(walked["study_files"] // 10, 5)
    files = walked["files"]
    roles["office"] += min((files.get("Word", 0) + files.get("Excel", 0) + files.get("PowerPoint", 0)) // 30, 3)
    roles["office"] += min(walked["work_files"] // 10, 2)
    return {role: score for role, score in roles.items() if score}


def _worth_a_look(name: str) -> bool:
    return not name.startswith((".", "$", "~")) and name.lower() not in SKIP_DIRS


def _is_link(path: Path) -> bool:
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & REPARSE_POINT) or path.is_symlink()
    except OSError:
        return True


def _known(name: str) -> tuple[str, str, str | None] | None:
    """(fact, about, role) for an app we know, or None."""
    for pattern, fact, about, role in KNOWN_APPS:
        if re.search(pattern, name.lower()):
            return fact.format(name=name), about, role
    return None


def _fact(about: str, fact: str, quote: str) -> dict:
    from .portrait import _id

    return {"id": _id(fact), "about": about, "fact": fact, "quote": quote, "source": THIS_COMPUTER,
            "title": "", "when": time.time(), "seen": 1, "kept": None}


def _ago(moment: float) -> str:
    days = int((time.time() - moment) // 86400)
    return "today" if days < 1 else "yesterday" if days < 2 else f"{days} days ago"


def _listed(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
