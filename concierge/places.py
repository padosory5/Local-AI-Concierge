"""Where Windows and the Mac really keep the user's Desktop, Documents, Downloads and
Pictures. On Windows these are often not under the home folder: with OneDrive
backup on, the Desktop the user sees is C:/Users/me/OneDrive/Desktop, and on a
Korean Windows it is "OneDrive/바탕 화면". Asking Windows (SHGetKnownFolderPath) is
the only way to get it right; the first file organizer put its College folder in
C:/Users/me/Desktop, which the user never sees.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Windows' own ids for the folders people name.
KNOWN = {
    "Desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "Documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "Pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "Music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
    "Videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
}


def known_folder(name: str, home: Path | None = None) -> Path:
    """The real place of a folder people name ("Desktop"), asked of Windows; elsewhere,
    or if Windows can't say, the folder of that name in the home folder."""
    home = home or Path.home()
    if name == "home":
        return home
    if sys.platform == "win32" and name in KNOWN:
        found = _windows_known_folder(KNOWN[name])
        if found:
            return found
    return home / name


def _windows_known_folder(guid: str) -> Path | None:
    import ctypes
    from ctypes import wintypes

    class Guid(ctypes.Structure):
        _fields_ = [("data1", wintypes.DWORD), ("data2", wintypes.WORD), ("data3", wintypes.WORD),
                    ("data4", wintypes.BYTE * 8)]

    out = ctypes.c_wchar_p()
    try:
        parts = guid.strip("{}").split("-")
        folder_id = Guid(int(parts[0], 16), int(parts[1], 16), int(parts[2], 16),
                         (wintypes.BYTE * 8)(*bytes.fromhex(parts[3] + parts[4])))
        shell32 = ctypes.windll.shell32
        shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(Guid), wintypes.DWORD, wintypes.HANDLE,
                                                 ctypes.POINTER(ctypes.c_wchar_p)]
        if shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(out)) != 0:
            return None
        path = Path(out.value) if out.value else None
    except (AttributeError, OSError, ValueError):
        return None
    finally:
        try:
            ctypes.windll.ole32.CoTaskMemFree(out)
        except (AttributeError, OSError):
            pass
    return path if path and path.is_dir() else None
