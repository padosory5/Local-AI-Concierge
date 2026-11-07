"""Its icon for the packaged app: the same black disc with print dots as the icon by
the clock (concierge/ui/tray.py), drawn big, at the sizes Windows and the Mac want.
Written to packaging/icons/, which the build makes and git ignores."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from concierge.ui.tray import tray_picture  # noqa: E402

ICO_SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
ICNS_SIZES = [16, 32, 64, 128, 256, 512, 1024]


def make(out: Path = ROOT / "packaging" / "icons") -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    picture = tray_picture(1024)
    made = [out / "noir.png", out / "noir.ico"]
    picture.save(made[0])
    picture.save(made[1], sizes=ICO_SIZES)
    if sys.platform == "darwin":
        made.append(_icns(picture, out / "noir.icns"))
    return made


def _icns(picture, path: Path) -> Path:
    """Pillow writes .icns itself; if this one can't, the Mac's own iconutil does."""
    try:
        picture.save(path)
        return path
    except (OSError, ValueError):
        pass
    iconset = Path(tempfile.mkdtemp()) / "noir.iconset"
    iconset.mkdir()
    for size in ICNS_SIZES:
        picture.resize((size, size)).save(iconset / f"icon_{size}x{size}.png")
        if size >= 32:
            picture.resize((size, size)).save(iconset / f"icon_{size // 2}x{size // 2}@2x.png")
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(path)], check=True)
    shutil.rmtree(iconset.parent, ignore_errors=True)
    return path


if __name__ == "__main__":
    for path in make():
        print(path)
