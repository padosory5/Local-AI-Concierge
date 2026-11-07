"""Build Noir for the system this runs on, the way the release workflow does:

    python packaging/build.py [--no-installer]

Windows: dist/Noir/ (the app folder), then dist/Noir-Setup-<version>.exe with
Inno Setup, if it is installed (it is on GitHub's Windows runners; without it the
folder is the result). Mac: dist/Noir.app, then dist/Noir-<version>.dmg with
the app and an Applications shortcut, which is how Mac apps are handed over.

After PyInstaller, the built app is started with --check, which loads every part
and opens nothing: a build that can't start is caught here, not on someone's
computer. What a packaged app prints goes to noir.log in its data folder.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# This folder first: "packaging" is also the name of a library pip installs, which
# would otherwise win over the folder when make_icons is imported.
sys.path.insert(0, str(ROOT / "packaging"))
sys.path.insert(0, str(ROOT))

from concierge import __version__  # noqa: E402
from make_icons import make as make_icons  # noqa: E402

DIST = ROOT / "dist"
INNO = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    installer = "--no-installer" not in argv
    print(f"Noir {__version__} for {sys.platform}")
    make_icons()
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(ROOT / "packaging" / "noir.spec")])
    check()
    if not installer:
        return 0
    if sys.platform == "win32":
        return windows_installer()
    if sys.platform == "darwin":
        return mac_image()
    print("Only the app folder is made on this system.")
    return 0


def built_program() -> Path:
    if sys.platform == "darwin":
        return DIST / "Noir.app" / "Contents" / "MacOS" / "Noir"
    return DIST / "Noir" / ("Noir.exe" if sys.platform == "win32" else "Noir")


def check() -> None:
    """The built app must load every part. It has no console, so its words are in
    noir.log; the exit code is what decides."""
    from concierge.noir import data_dir

    program = built_program()
    result = subprocess.run([str(program), "--check"], timeout=300)
    log = data_dir() / "noir.log"
    if result.returncode != 0:
        if log.is_file():
            print(log.read_text(encoding="utf-8", errors="replace")[-3000:])
        raise SystemExit(f"The built app failed its check (exit code {result.returncode}).")
    print("The built app loads every part.")


def windows_installer() -> int:
    iscc = shutil.which("iscc") or (str(INNO) if INNO.is_file() else "")
    if not iscc:
        print("Inno Setup isn't installed, so no installer was made; dist/Noir is the app.")
        return 0
    run([iscc, f"/DVersion={__version__}", f"/DSource={DIST / 'Noir'}", f"/O{DIST}", str(ROOT / "packaging" / "noir.iss")])
    print(f"Made {DIST / f'Noir-Setup-{__version__}.exe'}")
    return 0


def mac_image() -> int:
    stage = DIST / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    shutil.copytree(DIST / "Noir.app", stage / "Noir.app", symlinks=True)
    (stage / "Applications").symlink_to("/Applications")
    image = DIST / f"Noir-{__version__}.dmg"
    image.unlink(missing_ok=True)
    run(["hdiutil", "create", "-volname", "Noir", "-srcfolder", str(stage), "-ov", "-format", "UDZO", str(image)])
    shutil.rmtree(stage, ignore_errors=True)
    print(f"Made {image}")
    return 0


def run(command: list[str]) -> None:
    print("+", " ".join(command))
    subprocess.run(command, check=True, cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
