"""Read the computer's hardware: OS, CPU, memory, disk and graphics cards.

This has to be exact, so it is plain code and never asks the AI. Every number
comes from the operating system or the vendor's own tool (nvidia-smi), and a
value we could not read is left as None instead of guessed.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

import psutil

GB = 1024**3

# Graphics cards with less memory than this are too small to hold even the
# smallest model next to the desktop, so Elaina runs on the CPU instead.
MIN_USABLE_VRAM_GB = 4.0

# Virtual or remote display adapters that show up next to real cards on
# Windows and have no memory of their own.
_VIRTUAL_ADAPTERS = ("basic display", "basic render", "virtual", "parsec", "remote", "idd")


@dataclass
class GPU:
    name: str
    vendor: str  # "nvidia", "amd", "intel", "apple" or "other"
    vram_total_gb: float | None
    vram_free_gb: float | None
    # True when Ollama can run models on this card.
    usable: bool
    # How the numbers were read, so a wrong value can be traced.
    source: str


@dataclass
class HardwareReport:
    os: str  # "windows", "macos" or "linux"
    os_version: str
    arch: str
    cpu_name: str
    cpu_cores: int
    cpu_threads: int
    ram_total_gb: float
    ram_available_gb: float
    disk_free_gb: float
    disk_path: str
    gpus: list[GPU] = field(default_factory=list)

    @property
    def apple_silicon(self) -> bool:
        return self.os == "macos" and self.arch in ("arm64", "aarch64")

    def best_gpu(self) -> GPU | None:
        """The usable card with the most memory, or None to run on the CPU."""
        usable = [g for g in self.gpus if g.usable and g.vram_total_gb]
        return max(usable, key=lambda g: g.vram_total_gb, default=None)

    def to_dict(self) -> dict:
        return asdict(self)


def detect() -> HardwareReport:
    system = _os_name()
    mem = psutil.virtual_memory()
    disk_path = _model_storage_path()
    return HardwareReport(
        os=system,
        os_version=_os_version(system),
        arch=platform.machine().lower(),
        cpu_name=_cpu_name(system),
        cpu_cores=psutil.cpu_count(logical=False) or 0,
        cpu_threads=psutil.cpu_count(logical=True) or 0,
        ram_total_gb=round(mem.total / GB, 1),
        ram_available_gb=round(mem.available / GB, 1),
        disk_free_gb=round(shutil.disk_usage(disk_path).free / GB, 1),
        disk_path=str(disk_path),
        gpus=_detect_gpus(system, mem.total / GB),
    )


# ---------------------------------------------------------------- OS and CPU


def _os_name() -> str:
    return {"Windows": "windows", "Darwin": "macos"}.get(platform.system(), "linux")


def _os_version(system: str) -> str:
    if system == "windows":
        # Windows 11 still reports release "10"; build 22000 and up is 11.
        build = int(platform.version().split(".")[-1] or 0)
        return f"Windows {'11' if build >= 22000 else '10'} (build {build})"
    if system == "macos":
        return f"macOS {platform.mac_ver()[0]}"
    try:
        info = platform.freedesktop_os_release()
        return info.get("PRETTY_NAME", "Linux")
    except OSError:
        return f"Linux {platform.release()}"


def _cpu_name(system: str) -> str:
    try:
        if system == "windows":
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            ) as key:
                return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        if system == "macos":
            return _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return platform.processor() or "Unknown CPU"


def _model_storage_path() -> Path:
    """Where Ollama keeps downloaded models, or the nearest folder that exists."""
    path = Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models")
    while not path.exists():
        path = path.parent
    return path


# -------------------------------------------------------------- graphics


def _detect_gpus(system: str, ram_total_gb: float) -> list[GPU]:
    if system == "macos":
        return _apple_gpus(ram_total_gb)
    gpus = _nvidia_gpus()
    if system == "windows":
        gpus += _windows_other_gpus()
    else:
        gpus += _linux_amd_gpus()
    return gpus


def _nvidia_gpus() -> list[GPU]:
    if not shutil.which("nvidia-smi"):
        return []
    try:
        out = _run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ]
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_nvidia_smi(out)


def parse_nvidia_smi(out: str) -> list[GPU]:
    """Parse `nvidia-smi --query-gpu=name,memory.total,memory.free` CSV (MiB)."""
    gpus = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.rsplit(",", 2)]
        if len(parts) != 3:
            continue
        name, total, free = parts
        try:
            total_gb = round(float(total) / 1024, 1)
            free_gb = round(float(free) / 1024, 1)
        except ValueError:
            continue
        gpus.append(
            GPU(
                name=name,
                vendor="nvidia",
                vram_total_gb=total_gb,
                vram_free_gb=free_gb,
                usable=total_gb >= MIN_USABLE_VRAM_GB,
                source="nvidia-smi",
            )
        )
    return gpus


def _windows_other_gpus() -> list[GPU]:
    """AMD and Intel cards from the registry.

    WMI's AdapterRAM is a 32-bit field that tops out at 4 GB, so the driver's
    64-bit HardwareInformation.qwMemorySize is read instead. Free memory is not
    available this way and stays None. NVIDIA cards are skipped because
    nvidia-smi already reported them with exact numbers.
    """
    import winreg

    gpus = []
    display_class = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, display_class)
    except OSError:
        return []
    with root:
        index = 0
        while True:
            try:
                sub = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            if not sub.isdigit():
                continue
            try:
                with winreg.OpenKey(root, sub) as key:
                    name = str(winreg.QueryValueEx(key, "DriverDesc")[0])
                    vram = _registry_vram_bytes(winreg, key)
            except OSError:
                continue
            vendor = _vendor_from_name(name)
            if vendor == "nvidia" or any(v in name.lower() for v in _VIRTUAL_ADAPTERS):
                continue
            total_gb = round(vram / GB, 1) if vram else None
            gpus.append(
                GPU(
                    name=name,
                    vendor=vendor,
                    vram_total_gb=total_gb,
                    vram_free_gb=None,
                    # Ollama runs on AMD cards through ROCm; Intel cards are
                    # not supported, and integrated chips report a small
                    # shared slice that is too little for a model.
                    usable=vendor == "amd" and (total_gb or 0) >= MIN_USABLE_VRAM_GB,
                    source="windows registry",
                )
            )
    return gpus


def _registry_vram_bytes(winreg, key) -> int | None:
    for value in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
        try:
            raw = winreg.QueryValueEx(key, value)[0]
        except OSError:
            continue
        if isinstance(raw, bytes):
            raw = int.from_bytes(raw, "little")
        if raw:
            return int(raw)
    return None


def _linux_amd_gpus() -> list[GPU]:
    gpus = []
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]*")):
        device = card / "device"
        try:
            if (device / "vendor").read_text().strip() != "0x1002":
                continue
            total = int((device / "mem_info_vram_total").read_text())
            used = int((device / "mem_info_vram_used").read_text())
        except (OSError, ValueError):
            continue
        total_gb = round(total / GB, 1)
        gpus.append(
            GPU(
                name=f"AMD GPU ({card.name})",
                vendor="amd",
                vram_total_gb=total_gb,
                vram_free_gb=round((total - used) / GB, 1),
                usable=total_gb >= MIN_USABLE_VRAM_GB,
                source="sysfs",
            )
        )
    return gpus


def _apple_gpus(ram_total_gb: float) -> list[GPU]:
    if platform.machine().lower() not in ("arm64", "aarch64"):
        return []  # Intel Macs: Ollama runs on the CPU.
    # Apple Silicon shares one pool of memory. macOS lets the GPU use about
    # two thirds of it on smaller machines and three quarters on larger ones.
    share = 0.75 if ram_total_gb > 36 else 2 / 3
    try:
        name = _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
    except (OSError, subprocess.SubprocessError):
        name = "Apple Silicon"
    return [
        GPU(
            name=f"{name} GPU (shared memory)",
            vendor="apple",
            vram_total_gb=round(ram_total_gb * share, 1),
            vram_free_gb=None,
            usable=True,
            source="unified memory",
        )
    ]


def _vendor_from_name(name: str) -> str:
    lowered = name.lower()
    for vendor, marks in (
        ("nvidia", ("nvidia", "geforce", "quadro", "rtx")),
        ("amd", ("amd", "radeon")),
        ("intel", ("intel", "arc", "iris", "uhd")),
    ):
        if any(m in lowered for m in marks):
            return vendor
    return "other"


def _run(cmd: list[str]) -> str:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=10, check=True
    ).stdout


# ---------------------------------------------------------------- output


def describe(report: HardwareReport, live: bool = True) -> list[str]:
    """Plain-language lines about the computer, for people and for Elaina.

    live=False leaves out the figures that change minute to minute (free
    memory and disk), for text that is stored, such as Elaina's prompt.
    """
    memory = f"Memory: {report.ram_total_gb:g} GB"
    if live:
        memory += f" ({report.ram_available_gb:g} GB free right now)"
    lines = [f"{report.os_version}, {report.cpu_name} ({report.cpu_cores} cores)", memory]
    if not report.gpus:
        lines.append("Graphics: no separate graphics card found, AI runs on the processor")
    for gpu in report.gpus:
        size = f"{gpu.vram_total_gb:g} GB" if gpu.vram_total_gb else "unknown memory"
        if live and gpu.vram_free_gb is not None:
            size += f", {gpu.vram_free_gb:g} GB free"
        note = "" if gpu.usable else " (not used for AI)"
        lines.append(f"Graphics: {gpu.name}, {size}{note}")
    if live:
        lines.append(f"Disk: {report.disk_free_gb:g} GB free")
    return lines
