"""What the packaged app runs (packaging/noir.spec builds it into Noir.exe or
Noir.app). A windowed program has no terminal, so whatever the app prints goes to
noir.log in its data folder, where it can be read when something goes wrong on a
computer that isn't a developer's."""

from __future__ import annotations

import sys


def _log_to_file() -> None:
    frozen = getattr(sys, "frozen", False)
    if not frozen or (sys.stdout is not None and sys.stdout.isatty()):
        return
    from concierge.noir import data_dir

    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(folder / "noir.log", "a", encoding="utf-8", buffering=1)


if __name__ == "__main__":
    _log_to_file()
    from concierge.ui.window import main

    sys.exit(main())
