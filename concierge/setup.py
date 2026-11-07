"""First-run setup from inside the window: Ollama, a model that fits, then Noir.

Other local-first apps go one of two ways. Jan, LM Studio and Msty bundle their own
engine, so their installers are big and the engine only changes with the app. Open
WebUI and AnythingLLM send people to install Ollama themselves first, and many never
come back. Noir takes the middle way: one button fetches Ollama's own installer
from ollama.com (about 0.7 GB on Windows, 0.25 GB on a Mac, said before the button),
runs it, picks the model this computer can run (catalog.py), downloads it and builds
it. Nothing of Ollama's is bundled, so it stays Ollama's and updates itself.

Every step is checked, never assumed: Ollama must answer, the model must be in its
list and it must exist before the page moves on. A step that fails says what to do
in plain words, and Try again picks up where it stopped: Ollama keeps the part of a
model it has, and an installer already downloaded isn't fetched twice.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import requests

from . import noir, hardware
from .catalog import ModelEntry, Recommendation, load_catalog, memory_budget, recommend
from .ollama import DOWNLOAD_PAGE, Ollama, OllamaError

OLLAMA, MODEL, NOIR = "ollama", "model", "noir"  # the three steps, in order
# Ollama's own installers, from its download page, and about how big each is in GB.
INSTALLERS = {
    "win32": ("https://ollama.com/download/OllamaSetup.exe", "OllamaSetup.exe", 0.7),
    "darwin": ("https://ollama.com/download/Ollama.dmg", "Ollama.dmg", 0.25),
}
# Inno Setup's switches: no questions, no window, no restart. The installer puts
# Ollama in the user's own Programs folder, so there is no admin prompt either.
SILENT_INSTALL = ("/SP-", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
DOWNLOAD_TIMEOUT = 30  # seconds without a byte before a download is given up
INSTALL_SECONDS = 900  # the installer unpacking, on a slow disk
START_SECONDS = 180  # waiting for Ollama to answer; on a Mac the user may have to click Open
QUICK_START_SECONDS = 10  # an Ollama that is installed but stopped, started while the page asks
CHUNK = 1 << 20
MAC_OPEN = "If your Mac asks whether to open Ollama, choose Open."


class SetupError(RuntimeError):
    """Something the user has to do or know, in their words."""


class Setup:
    """The three steps, run on a thread of their own, and what the page shows about them."""

    def __init__(self, ollama: Ollama, fetch: Callable = requests.get, run: Callable = subprocess.run,
                 popen: Callable = subprocess.Popen, folder: Path | None = None, detect: Callable = hardware.detect):
        """fetch, run, popen, folder and detect are replaced in tests. The installer goes
        to the user's own Downloads folder, so if the quiet install fails they can open it."""
        self.ollama = ollama
        self._fetch, self._run, self._popen, self._detect = fetch, run, popen, detect
        self.folder = folder or Path.home() / "Downloads"
        self.step = ""  # OLLAMA, MODEL or NOIR while working, "" otherwise
        self.note = ""  # what is happening right now, for the page
        self.progress: tuple[int, int] | None = None  # bytes done and in all, while downloading
        self.waiting = ""  # something only the user can do (let the Mac open Ollama)
        self.error = ""
        self.smallest = False  # the user chose the smallest model though none fits comfortably
        self.start_seconds = START_SECONDS
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._computer_cache: tuple[hardware.HardwareReport, Recommendation] | None = None

    # ------------------------------------------------------------- the page

    @property
    def working(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def state(self) -> dict:
        """What the setup page shows: whether anything is missing, what each step will
        do, and how the step running now is getting on. Every line comes from a check
        made just now, not from what was true last time."""
        report, rec = self._computer()
        installed = self.ollama.is_installed()
        running = self.ollama.is_running()
        if installed and not running and not self.working:
            running = self._start_quietly()
        model, _ = self._model(report, rec)
        have_model = running and model is not None and self.ollama.has_model(model.tag)
        have_noir = running and self.ollama.has_model(noir.NOIR_MODEL)
        _, _, installer_gb = INSTALLERS.get(sys.platform, ("", "", 0.0))
        return {
            # Nothing to do when it exists and its model is there (or none fits: it was built once).
            "needed": not (running and have_noir and (have_model or model is None)),
            "hardware": hardware.describe(report),
            "device": rec.device_name,
            "ollama": "running" if running else "stopped" if installed else "missing",
            "ollama_gb": installer_gb,
            "can_install": sys.platform in INSTALLERS,
            "download_page": DOWNLOAD_PAGE,
            "model": {"tag": model.tag, "name": model.name, "download_gb": model.download_gb,
                      "memory_gb": model.memory_gb, "have": have_model} if model else None,
            "fits": rec.model is not None,
            "reason": rec.reason,
            "noir": have_noir,
            "working": self.working,
            "step": self.step,
            "note": self.note,
            "progress": {"done": self.progress[0], "total": self.progress[1]} if self.progress else None,
            "waiting": self.waiting,
            "error": self.error,
            "mac": sys.platform == "darwin",
        }

    def begin(self, smallest: bool = False) -> dict:
        """Do whatever is still missing, in order, on a thread of its own. Try again
        calls this too. smallest: use the smallest model though none fits comfortably."""
        with self._lock:
            if smallest:
                self.smallest = True
            if not self.working:
                self.error = ""
                self._thread = threading.Thread(target=self._work, name="setup", daemon=True)
                self._thread.start()
        return self.state()

    # ------------------------------------------------------------- the steps

    def _work(self) -> None:
        try:
            if not self.ollama.is_running():
                if not self.ollama.is_installed():
                    self._install_ollama()
                self._start_ollama()
            report, rec = self._computer(again=True)  # the install changed what the disk has free
            model, for_model = self._model(report, rec)
            if model is None:
                raise SetupError(f"{rec.reason} You can still use the smallest model; it will be slow.")
            if not self.ollama.has_model(model.tag):
                self._download(model)
            self._build(model, for_model, report)
        except (SetupError, OllamaError) as exc:
            self.error = str(exc)
        except Exception:  # a surprise must still leave the page usable
            traceback.print_exc()
            self.error = ("Something went wrong while setting up. Press Try again; if it keeps happening, "
                          f"install Ollama from {DOWNLOAD_PAGE} and open me again.")
        finally:
            self.step, self.note, self.progress, self.waiting = "", "", None, ""

    def _install_ollama(self) -> None:
        self.step = OLLAMA
        if sys.platform not in INSTALLERS:
            raise SetupError(f"I can only install Ollama for you on Windows and macOS. Install it from "
                             f"{DOWNLOAD_PAGE}, then press Try again.")
        url, name, _ = INSTALLERS[sys.platform]
        path = self.folder / name
        if not path.is_file():  # a download that finished before a failed install is kept
            self.note = "Downloading Ollama from ollama.com..."
            self._download_file(url, path)
        self.note = "Installing Ollama..."
        self.progress = None
        if sys.platform == "win32":
            try:
                result = self._run([str(path), *SILENT_INSTALL], timeout=INSTALL_SECONDS)
            except subprocess.TimeoutExpired:
                raise SetupError("Ollama's installer is taking too long. Open OllamaSetup.exe in your Downloads "
                                 "folder and install it yourself, then press Try again.") from None
            if result.returncode != 0:
                raise SetupError("Ollama's installer stopped before it finished. Open OllamaSetup.exe in your "
                                 "Downloads folder and install it yourself, then press Try again.")
        else:
            self._install_mac(path)
        if not self.ollama.is_installed():
            raise SetupError(f"Ollama was installed, but I can't find it. Install it from {DOWNLOAD_PAGE} "
                             "yourself, then press Try again.")
        path.unlink(missing_ok=True)  # the installer isn't needed again

    def _install_mac(self, dmg: Path) -> None:
        """What dragging the app out of the disk image does, done for the user: mount
        it, copy Ollama into Applications (ditto keeps the app's signature whole), let
        go of it. If any of that fails, the image is opened for them to do the drag."""
        mount = Path(tempfile.mkdtemp(prefix="ollama-"))
        try:
            self._run(["hdiutil", "attach", "-nobrowse", "-quiet", "-mountpoint", str(mount), str(dmg)],
                      check=True, timeout=120)
            app = next(mount.glob("*.app"))
            self._run(["ditto", str(app), str(Path("/Applications") / app.name)], check=True, timeout=300)
        except (OSError, subprocess.SubprocessError, StopIteration):
            self._popen(["open", str(dmg)])
            raise SetupError("I couldn't put Ollama in your Applications folder myself. Drag Ollama from the "
                             "window that opened into Applications, open it once, then press Try again.") from None
        finally:
            try:
                self._run(["hdiutil", "detach", "-quiet", str(mount)], timeout=60)
            except (OSError, subprocess.SubprocessError):
                pass

    def _start_ollama(self) -> None:
        self.step = OLLAMA
        self.note = "Starting Ollama..."
        self.waiting = MAC_OPEN if sys.platform == "darwin" else ""
        self.ollama.start()
        deadline = time.monotonic() + self.start_seconds
        while time.monotonic() < deadline:
            if self.ollama.is_running():
                self.waiting = ""
                return
            time.sleep(1)
        raise SetupError("Ollama is installed but isn't answering. Open the Ollama app yourself, then press "
                         "Try again.")

    def _start_quietly(self) -> bool:
        """An Ollama that is installed but stopped is started while the page asks, so a
        computer that merely has Ollama closed never sees the setup page."""
        try:
            self.ollama.ensure_running(wait_seconds=QUICK_START_SECONDS)
        except OllamaError:
            return False
        return True

    def _download(self, model: ModelEntry) -> None:
        self.step = MODEL
        self.note = f"Downloading {model.name} ({model.download_gb:g} GB)..."

        def progress(status: str, done: int, total: int) -> None:
            if total:
                self.progress = (done, total)

        try:
            self.ollama.pull(model.tag, progress)
        except OllamaError:
            raise SetupError(f"The download of {model.name} stopped. Check your internet connection and press "
                             "Try again; it carries on from where it stopped.") from None
        if not self.ollama.has_model(model.tag):
            raise SetupError(f"Ollama says it downloaded {model.name}, but doesn't list it. Press Try again.")
        self.progress = None

    def _build(self, model: ModelEntry, rec: Recommendation, report: hardware.HardwareReport) -> None:
        self.step = NOIR
        self.note = "Building Noir from the model..."
        noir.configure(self.ollama, model, rec, report)
        if not self.ollama.has_model(noir.NOIR_MODEL):
            raise SetupError("Ollama didn't make the Noir model. Press Try again.")

    # -------------------------------------------------------------- helpers

    def _computer(self, again: bool = False) -> tuple[hardware.HardwareReport, Recommendation]:
        """The hardware and the model for it, read once: the page asks every second
        while a step runs, and reading the graphics card each time would be slow."""
        if self._computer_cache is None or again:
            report = self._detect()
            self._computer_cache = (report, recommend(report))
        return self._computer_cache

    def _model(self, report: hardware.HardwareReport, rec: Recommendation) -> tuple[ModelEntry | None, Recommendation]:
        """The model to set up and a recommendation that names it: the one that fits,
        or the smallest when the user chose that, or none."""
        if rec.model is not None:
            return rec.model, rec
        if not self.smallest:
            return None, rec
        smallest = min(load_catalog(), key=lambda model: model.memory_gb)
        _, _, _, device_total = memory_budget(report)
        return smallest, replace(rec, model=smallest, left_free_gb=round(device_total - smallest.memory_gb, 1),
                                 reason="The smallest tested model, chosen though it doesn't fit comfortably.")

    def _download_file(self, url: str, path: Path) -> None:
        """Fetch one file with the page watching the bytes. A half file is kept apart
        (.part) so a stopped download never looks like a finished installer."""
        part = path.with_name(path.name + ".part")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._fetch(url, stream=True, timeout=DOWNLOAD_TIMEOUT, allow_redirects=True) as reply:
                if not reply.ok:
                    raise SetupError(f"ollama.com didn't give me the installer (it said {reply.status_code}). "
                                     f"Get it from {DOWNLOAD_PAGE} yourself, then press Try again.")
                total = int(reply.headers.get("Content-Length") or 0)
                done = 0
                with part.open("wb") as out:
                    for chunk in reply.iter_content(CHUNK):
                        out.write(chunk)
                        done += len(chunk)
                        self.progress = (done, total)
            part.replace(path)
        except requests.RequestException:
            raise SetupError("The download stopped. Check your internet connection and press Try again.") from None
        except OSError:
            raise SetupError(f"I couldn't save the installer in {path.parent}. Make room there, then press "
                             "Try again.") from None
