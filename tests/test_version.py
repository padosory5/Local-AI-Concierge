"""The version the packaged app carries, and the check a build is started with."""

import subprocess
import sys
import tomllib
from pathlib import Path

from concierge import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_the_version_is_the_same_everywhere():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == __version__


def test_check_loads_every_part_without_a_window():
    result = subprocess.run([sys.executable, "-m", "concierge.ui", "--check"], cwd=ROOT, capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    assert f"Noir {__version__}: every part loads." in result.stdout


def test_version_flag_names_the_version():
    result = subprocess.run([sys.executable, "-m", "concierge.ui", "--version"], cwd=ROOT, capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == 0 and result.stdout.strip() == f"Noir {__version__}"


def test_the_icon_is_drawn_at_any_size():
    from concierge.ui.tray import ICON_SIZE, tray_picture

    assert tray_picture().size == (ICON_SIZE, ICON_SIZE)
    big = tray_picture(512)
    assert big.size == (512, 512)
    assert big.getpixel((256, 256))[3] == 255  # the disc is solid in the middle
    assert big.getpixel((2, 2))[3] == 0  # and the corners are clear
