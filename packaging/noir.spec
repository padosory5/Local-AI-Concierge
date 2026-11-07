# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller's recipe for Noir, the same on Windows and the Mac; packaging/build.py
runs it. One folder, not one file: a one-file build unpacks itself at every start,
which takes seconds, and the folder is what the installer and the disk image carry."""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent  # SPECPATH is PyInstaller's: the folder this spec is in
sys.path.insert(0, str(ROOT))
from concierge import __version__  # noqa: E402

# Everything under concierge/ that isn't Python: the pages, their fonts and vendor
# libraries, the yaml lists, her persona and the blueprints. Each lands where
# __file__ expects it, so no module needs to know it is packaged.
datas = [(str(path), str(path.parent.relative_to(ROOT)))
         for path in (ROOT / "concierge").rglob("*")
         if path.is_file() and path.suffix not in (".py", ".pyc") and "__pycache__" not in path.parts]
datas += collect_data_files("webview") + collect_data_files("certifi")
hiddenimports = ["tkinter", "tkinter.font", *collect_submodules("keyring.backends")]
icons = ROOT / "packaging" / "icons"

if sys.platform == "win32":
    hiddenimports += ["webview.platforms.winforms", "webview.platforms.edgechromium", "clr", "pystray._win32",
                      "pynput.keyboard._win32", "pynput.mouse._win32", "uiautomation", "comtypes", "comtypes.client"]
    datas += collect_data_files("uiautomation")
    icon = str(icons / "noir.ico")
elif sys.platform == "darwin":
    hiddenimports += ["webview.platforms.cocoa"]
    icon = str(icons / "noir.icns")
else:
    hiddenimports += ["webview.platforms.gtk"]
    icon = None

a = Analysis(
    [str(ROOT / "packaging" / "noir.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "matplotlib", "numpy", "IPython"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="Noir",
    console=False,
    icon=icon,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Noir")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Noir.app",
        icon=icon,
        bundle_identifier="com.noiragents.noir",
        version=__version__,
        info_plist={
            "CFBundleName": "Noir",
            "CFBundleDisplayName": "Noir",
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            "LSApplicationCategoryType": "public.app-category.productivity",
        },
    )
