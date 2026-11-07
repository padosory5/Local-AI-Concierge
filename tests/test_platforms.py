"""The app must start on a Mac. Windows is only ever touched inside a function,
or at the top of a module inside an `if sys.platform == "win32":` block, so that
every module imports anywhere. Two checks: the code itself, read as a tree, and a
real import of every module with the platform faked as macOS."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "concierge"

# Modules and names that only exist on Windows. ctypes.wintypes is not one: it
# imports on every system since Python 3.9.
WINDOWS_MODULES = {"winreg", "msvcrt", "_winapi", "uiautomation", "pystray", "pynput", "win32gui", "win32api",
                   "win32con", "win32process", "pywintypes", "comtypes"}
WINDOWS_NAMES = {"windll", "WinDLL", "oledll", "OleDLL", "WINFUNCTYPE", "CREATE_NO_WINDOW", "CREATE_NEW_CONSOLE",
                 "STARTUPINFO"}


def _guarded(node: ast.If) -> bool:
    """An `if` that asks which system this is."""
    test = ast.unparse(node.test)
    return "sys.platform" in test or "platform.system()" in test


def _unguarded(statements: list[ast.stmt]) -> list[str]:
    """Windows-only imports and names reached at import time, as "line: what" strings."""
    found = []
    for statement in statements:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue  # a function body runs only when called
        if isinstance(statement, ast.If) and _guarded(statement):
            continue  # whichever branch this system takes, the author chose it
        if isinstance(statement, ast.Try) and any(
                handler.type is not None and "ImportError" in ast.unparse(handler.type) for handler in statement.handlers):
            continue  # an import tried and caught
        if isinstance(statement, (ast.If, ast.Try, ast.With, ast.For, ast.While, ast.ClassDef)):
            inner = list(statement.body)
            for part in ("orelse", "finalbody", "handlers"):
                for extra in getattr(statement, part, []) or []:
                    inner.extend(getattr(extra, "body", [extra]))
            found.extend(_unguarded(inner))
            continue
        for node in ast.walk(statement):
            if isinstance(node, ast.Import):
                found.extend(f"{node.lineno}: import {alias.name}" for alias in node.names
                             if alias.name.split(".")[0] in WINDOWS_MODULES)
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").split(".")[0] in WINDOWS_MODULES:
                    found.append(f"{node.lineno}: from {node.module} import ...")
            elif isinstance(node, ast.Attribute) and node.attr in WINDOWS_NAMES:
                found.append(f"{node.lineno}: {ast.unparse(node)}")
            elif isinstance(node, ast.Name) and node.id in WINDOWS_NAMES:
                found.append(f"{node.lineno}: {node.id}")
    return found


def _modules() -> list[Path]:
    return sorted(path for path in PACKAGE.rglob("*.py") if "web" not in path.parts)


def test_no_module_touches_windows_at_import_time():
    problems = {}
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if found := _unguarded(tree.body):
            problems[str(path.relative_to(ROOT))] = found
    assert not problems, "Windows reached at import time (wrap it in `if sys.platform == \"win32\":`):\n" + "\n".join(
        f"  {module}: {', '.join(lines)}" for module, lines in problems.items())


def test_every_module_imports_with_the_platform_faked_as_macos():
    """The real thing: a fresh Python says it is a Mac, imports everything, builds the
    window's pieces without opening them, and calls what the Mac path reaches."""
    names = [".".join(path.relative_to(ROOT).with_suffix("").parts) for path in _modules()
             if path.name != "__main__.py"]
    code = "\n".join([
        # Python's own library branches on the platform too (urllib wants the Mac's
        # proxy module), so what the app needs from it is imported before the fake.
        "import importlib, urllib.request, http.cookiejar, subprocess, tempfile, locale, mimetypes, webbrowser",
        "import ctypes.wintypes, requests, psutil, yaml, keyring, PIL.Image",
        "import sys",
        "sys.platform = 'darwin'",
        *[f"importlib.import_module({name!r})" for name in names],
        "from concierge.fake_engine import FakeEngine",
        "from concierge.quick.tidy import BreakSpotter, TidyWatch",
        "from concierge.quick.watching import lecture_on_screen",
        "from concierge.quick.spot import home_language",
        "from concierge.ui.window import Overlay, first_copy, work_area",
        "watch = TidyWatch(practice=True)",
        "watch.start()",  # looks at nothing off Windows
        "assert watch.noticing is False, watch.noticing",
        "assert BreakSpotter()() is False",
        "assert lecture_on_screen() == ''",
        "assert home_language() in ('English', 'Korean')",
        "assert first_copy() is True",
        "overlay = Overlay(FakeEngine(), watch)",
        "assert overlay._tray is None and overlay._mini is None and overlay._tap is None",
        "print('ok')",
    ])
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0 and result.stdout.strip().endswith("ok"), result.stderr[-3000:]
