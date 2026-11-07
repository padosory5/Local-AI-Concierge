"""The first-run setup (concierge/setup.py), with Ollama, the web and the installer faked."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from concierge import noir, setup
from concierge.hardware import GPU, HardwareReport
from concierge.ollama import OllamaError
from concierge.setup import INSTALLERS, SILENT_INSTALL, Setup, SetupError


def report(ram: float = 32.0, vram: float | None = 16.0, disk: float = 400.0) -> HardwareReport:
    gpus = [GPU("NVIDIA GeForce RTX 5080", "nvidia", vram, vram - 1, True, "test")] if vram else []
    return HardwareReport("windows", "Windows 11", "amd64", "A processor", 8, 16, ram, ram * 0.6, disk, "C:", gpus)


class FakeOllama:
    """Installed or not, running or not, with the models it has; records what was asked."""

    def __init__(self, installed: bool = True, running: bool = True, models: set[str] | None = None,
                 pull_fails: int = 0):
        self.installed, self.running = installed, running
        self.models = set(models or [])
        self.pull_fails = pull_fails
        self.pulled: list[str] = []
        self.created: list[tuple[str, str]] = []
        self.starts = 0

    def is_installed(self) -> bool:
        return self.installed

    def is_running(self) -> bool:
        return self.running

    def start(self) -> None:
        self.starts += 1
        if self.installed:
            self.running = True

    def ensure_running(self, wait_seconds: float = 20) -> None:
        self.start()
        if not self.running:
            raise OllamaError("not running")

    def has_model(self, name: str) -> bool:
        return name in self.models

    def pull(self, tag: str, on_progress=None) -> None:
        self.pulled.append(tag)
        if on_progress:
            on_progress("pulling", 50, 100)
        if self.pull_fails:
            self.pull_fails -= 1
            raise OllamaError("pull failed")
        self.models.add(tag)

    def create(self, name: str, base: str, system: str, parameters=None) -> None:
        self.created.append((name, base))
        self.models.add(name)


class FakeReply:
    def __init__(self, body: bytes = b"installer-bytes", ok: bool = True, status: int = 200):
        self.ok, self.status_code = ok, status
        self.headers = {"Content-Length": str(len(body))}
        self._body = body

    def iter_content(self, size):
        for start in range(0, len(self._body), 4):
            yield self._body[start:start + 4]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Recorder:
    """Stands in for subprocess.run and Popen, keeping every command."""

    def __init__(self, returncode: int = 0, fail_on: str = ""):
        self.commands: list[list[str]] = []
        self.returncode, self.fail_on = returncode, fail_on

    def __call__(self, command, **kwargs):
        self.commands.append([str(part) for part in command])
        if self.fail_on and self.fail_on in command[0]:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, self.returncode)


def make(tmp_path, ollama, platform="win32", fetch=None, run=None, popen=None, ram=32.0, vram=16.0, disk=400.0,
         monkeypatch=None):
    monkeypatch.setattr(sys, "platform", platform)
    one = Setup(ollama, fetch=fetch or (lambda url, **kwargs: FakeReply()), run=run or Recorder(),
                popen=popen or Recorder(), folder=tmp_path / "Downloads", detect=lambda: report(ram, vram, disk))
    one.start_seconds = 1
    return one


def finished(one: Setup, smallest: bool = False) -> dict:
    """Press the button and wait for the thread to end."""
    one.begin(smallest)
    one._thread.join(10)
    assert not one.working
    return one.state()


def test_nothing_missing_means_nothing_to_do(tmp_path, monkeypatch):
    ollama = FakeOllama(models={"qwen3.5:4b", noir.NOIR_MODEL})
    state = make(tmp_path, ollama, monkeypatch=monkeypatch).state()
    assert state["needed"] is False
    assert state["ollama"] == "running" and state["noir"] is True and state["model"]["have"] is True
    assert state["hardware"][0].startswith("Windows 11")


def test_a_stopped_ollama_is_started_while_the_page_asks(tmp_path, monkeypatch):
    ollama = FakeOllama(running=False, models={"qwen3.5:4b", noir.NOIR_MODEL})
    state = make(tmp_path, ollama, monkeypatch=monkeypatch).state()
    assert ollama.starts == 1 and state["ollama"] == "running" and state["needed"] is False


def test_the_whole_setup_on_a_bare_windows_computer(tmp_path, monkeypatch):
    ollama = FakeOllama(installed=False, running=False)
    fetched = []

    def fetch(url, **kwargs):
        fetched.append(url)
        ollama.installed = True  # the installer put it there
        return FakeReply()

    run = Recorder()
    one = make(tmp_path, ollama, fetch=fetch, run=run, monkeypatch=monkeypatch)
    before = one.state()
    assert before["needed"] and before["ollama"] == "missing" and before["can_install"]
    assert before["model"]["tag"] == "qwen3.5:4b" and before["ollama_gb"] == INSTALLERS["win32"][2]

    after = finished(one)
    assert fetched == [INSTALLERS["win32"][0]]
    assert run.commands[0][0].endswith("OllamaSetup.exe") and run.commands[0][1:] == list(SILENT_INSTALL)
    assert not (tmp_path / "Downloads" / "OllamaSetup.exe").exists()  # tidied away once installed
    assert ollama.starts == 1 and ollama.pulled == ["qwen3.5:4b"]
    assert ollama.created == [(noir.NOIR_MODEL, "qwen3.5:4b")]
    assert after["error"] == "" and after["needed"] is False and after["noir"] is True
    assert noir.load_state()["base_model"] == "qwen3.5:4b"


def test_a_stopped_download_says_so_and_try_again_carries_on(tmp_path, monkeypatch):
    ollama = FakeOllama(models=set(), pull_fails=1)
    one = make(tmp_path, ollama, monkeypatch=monkeypatch)
    state = finished(one)
    assert "Try again" in state["error"] and "internet" in state["error"]
    assert state["needed"] and state["noir"] is False
    state = finished(one)
    assert state["error"] == "" and state["needed"] is False
    assert ollama.pulled == ["qwen3.5:4b", "qwen3.5:4b"]


def test_an_installer_that_cannot_be_fetched_names_the_download_page(tmp_path, monkeypatch):
    ollama = FakeOllama(installed=False, running=False)
    one = make(tmp_path, ollama, fetch=lambda url, **kwargs: FakeReply(ok=False, status=503), monkeypatch=monkeypatch)
    state = finished(one)
    assert "503" in state["error"] and "ollama.com/download" in state["error"]
    assert ollama.starts == 0 and ollama.pulled == []


def test_an_installer_that_stops_says_to_run_it_by_hand(tmp_path, monkeypatch):
    ollama = FakeOllama(installed=False, running=False)
    one = make(tmp_path, ollama, run=Recorder(returncode=1), monkeypatch=monkeypatch)
    state = finished(one)
    assert "OllamaSetup.exe in your Downloads folder" in state["error"]
    assert (tmp_path / "Downloads" / "OllamaSetup.exe").read_bytes() == b"installer-bytes"  # kept for them


def test_the_mac_gets_the_disk_image_copied_into_applications(tmp_path, monkeypatch):
    ollama = FakeOllama(installed=False, running=False)
    run = Recorder()
    mounted = {}

    def runner(command, **kwargs):
        run(command, **kwargs)
        if command[0] == "hdiutil" and command[1] == "attach":
            mounted["point"] = Path(command[-2])
            (mounted["point"] / "Ollama.app").mkdir(parents=True)
        if command[0] == "ditto":
            ollama.installed = True
        return subprocess.CompletedProcess(command, 0)

    one = make(tmp_path, ollama, platform="darwin", run=runner, monkeypatch=monkeypatch)
    assert one.state()["ollama_gb"] == INSTALLERS["darwin"][2] and one.state()["mac"] is True
    state = finished(one)
    names = [command[0] for command in run.commands]
    assert names == ["hdiutil", "ditto", "hdiutil"]
    assert run.commands[1][1].endswith("Ollama.app") and Path(run.commands[1][2]) == Path("/Applications/Ollama.app")
    assert run.commands[2][:2] == ["hdiutil", "detach"]
    assert state["error"] == "" and state["needed"] is False
    assert ollama.starts == 1


def test_a_mac_copy_that_fails_opens_the_image_for_the_user(tmp_path, monkeypatch):
    ollama = FakeOllama(installed=False, running=False)
    popen = Recorder()
    one = make(tmp_path, ollama, platform="darwin", run=Recorder(fail_on="hdiutil"), popen=popen, monkeypatch=monkeypatch)
    state = finished(one)
    assert popen.commands == [["open", str(tmp_path / "Downloads" / "Ollama.dmg")]]
    assert "Drag Ollama" in state["error"]


def test_linux_is_sent_to_the_download_page(tmp_path, monkeypatch):
    ollama = FakeOllama(installed=False, running=False)
    one = make(tmp_path, ollama, platform="linux", monkeypatch=monkeypatch)
    assert one.state()["can_install"] is False
    state = finished(one)
    assert "Windows and macOS" in state["error"] and "ollama.com/download" in state["error"]


def test_a_computer_nothing_fits_can_still_take_the_smallest(tmp_path, monkeypatch):
    ollama = FakeOllama(models=set())
    one = make(tmp_path, ollama, ram=4.0, vram=None, monkeypatch=monkeypatch)
    state = one.state()
    assert state["fits"] is False and state["model"] is None and "smallest" in state["reason"].lower() or state["reason"]
    state = finished(one)
    assert "smallest model" in state["error"]
    state = finished(one, smallest=True)
    assert state["error"] == "" and state["needed"] is False
    assert ollama.pulled == [min(setup.load_catalog(), key=lambda model: model.memory_gb).tag]


def test_an_ollama_that_never_answers_says_to_open_it(tmp_path, monkeypatch):
    class Silent(FakeOllama):
        def start(self):
            self.starts += 1  # installed, started, never answers

    ollama = Silent(installed=True, running=False)
    one = make(tmp_path, ollama, monkeypatch=monkeypatch)
    one.state()  # the quiet start fails, which is fine
    state = finished(one)
    assert "Open the Ollama app" in state["error"]


def test_a_surprise_leaves_the_page_usable(tmp_path, monkeypatch):
    ollama = FakeOllama(models=set())
    one = make(tmp_path, ollama, monkeypatch=monkeypatch)
    ollama.pull = lambda *args, **kwargs: (_ for _ in ()).throw(ZeroDivisionError("boom"))
    state = finished(one)
    assert "Try again" in state["error"] and state["working"] is False


def test_the_practice_setup_plays_every_step_quickly():
    from concierge.fake_engine import FakeEngine

    engine = FakeEngine(setup=True)
    assert engine.setup_state()["needed"] is True
    engine.setup_begin()
    engine.setup._thread.join(20)
    state = engine.setup_state()
    assert state["needed"] is False and state["noir"] and state["model"]["have"] and state["ollama"] == "running"
    assert FakeEngine().setup_state() == {"needed": False}
