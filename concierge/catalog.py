"""Pick Noir's model from the tested list, based on the hardware report.

The AI never makes this choice. The rules below decide how much memory Noir
may take, and models.yaml says how much each model really uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .hardware import HardwareReport

CATALOG_PATH = Path(__file__).with_name("models.yaml")

# How much of the machine Noir's model may use. It stays loaded all the
# time, so most of the memory is left for the user's apps and for the bigger
# model an agent loads when it works.
GPU_SHARE = 0.30  # of a graphics card's memory
APPLE_SHARE = 0.20  # of the memory Apple Silicon shares between CPU and GPU
CPU_SHARE = 0.18  # of system memory when there is no usable graphics card
# On the processor alone, a bigger model answers too slowly to feel like a chat.
CPU_MAX_GB = 3.0
# Memory that must stay free next to Noir for the desktop and open apps.
GPU_HEADROOM_GB = 1.0
RAM_HEADROOM_GB = 2.0
# Free disk space to keep after the download.
DISK_HEADROOM_GB = 2.0


@dataclass
class ModelEntry:
    tag: str
    name: str
    download_gb: float
    memory_gb: float
    measured: bool
    languages: list[str]
    notes: str = ""


@dataclass
class Recommendation:
    model: ModelEntry | None
    device: str  # "gpu", "apple" or "cpu"
    device_name: str
    budget_gb: float
    # Memory on the device that stays free for everything else.
    left_free_gb: float | None
    reason: str


@dataclass
class HelperModel(ModelEntry):
    role: str = "general"  # "general", "vision" or "speech"


# On the processor, a helper model may use up to this share of system
# memory together with Noir; beyond it the whole computer slows down.
CPU_HELPER_SHARE = 0.5


def load_catalog(path: Path = CATALOG_PATH) -> list[ModelEntry]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [ModelEntry(**entry) for entry in data["models"]]


def load_helpers(path: Path = CATALOG_PATH) -> list[HelperModel]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [HelperModel(**entry) for entry in data.get("helpers", [])]


def load_designers(path: Path = CATALOG_PATH) -> list[ModelEntry]:
    """The local models that may work an agent out with the user (agents/designer.py), best
    first: only ones that passed `python -m concierge.designer_eval`."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [ModelEntry(**entry) for entry in data.get("designers", [])]


def helper_room(report: HardwareReport, noir_gb: float) -> tuple[float, bool]:
    """(GB a helper model may use next to Noir, whether it runs on the processor).

    Uses the device's total memory, not what happens to be free right now:
    the question is whether the computer can do the job, not whether it can
    this minute with a game open.
    """
    gpu = report.best_gpu()
    if gpu and gpu.vendor == "apple":
        return round(gpu.vram_total_gb - noir_gb - RAM_HEADROOM_GB, 1), False
    if gpu:
        return round(gpu.vram_total_gb - noir_gb - GPU_HEADROOM_GB, 1), False
    return round(report.ram_total_gb * CPU_HELPER_SHARE - noir_gb, 1), True


def pick_helper(role: str, report: HardwareReport, noir_gb: float) -> tuple[HelperModel | None, float, bool]:
    """The best helper model for a role that fits next to Noir.

    Returns (model or None, room in GB, runs on the processor). Speech models
    are small enough to run on the processor whatever the graphics card.
    """
    room, on_cpu = helper_room(report, noir_gb)
    if role == "speech":
        room, on_cpu = max(room, report.ram_total_gb * CPU_HELPER_SHARE - noir_gb), on_cpu
    for helper in load_helpers():
        if helper.role == role and helper.memory_gb <= room:
            return helper, room, on_cpu
    return None, room, on_cpu


def find_model(tag: str) -> ModelEntry | None:
    return next((m for m in load_catalog() if m.tag == tag), None)


def memory_budget(report: HardwareReport) -> tuple[str, str, float, float]:
    """Return (device, device name, budget in GB, device memory in GB)."""
    gpu = report.best_gpu()
    if gpu and gpu.vendor == "apple":
        return "apple", gpu.name, report.ram_total_gb * APPLE_SHARE, report.ram_total_gb
    if gpu:
        budget = gpu.vram_total_gb * GPU_SHARE
        if gpu.vram_free_gb is not None:
            budget = min(budget, gpu.vram_free_gb - GPU_HEADROOM_GB)
        return "gpu", gpu.name, budget, gpu.vram_total_gb
    budget = min(
        report.ram_total_gb * CPU_SHARE,
        report.ram_available_gb - RAM_HEADROOM_GB,
        CPU_MAX_GB,
    )
    return "cpu", report.cpu_name, budget, report.ram_total_gb


def recommend(report: HardwareReport, catalog: list[ModelEntry] | None = None) -> Recommendation:
    catalog = load_catalog() if catalog is None else catalog
    device, device_name, budget, device_total = memory_budget(report)
    budget = round(max(budget, 0.0), 1)

    too_big_for_disk = []
    for model in catalog:
        if model.memory_gb > budget:
            continue
        if report.disk_free_gb < model.download_gb + DISK_HEADROOM_GB:
            too_big_for_disk.append(model)
            continue
        return Recommendation(
            model=model,
            device=device,
            device_name=device_name,
            budget_gb=budget,
            left_free_gb=round(device_total - model.memory_gb, 1),
            reason=(
                f"Largest tested model that fits in {budget:g} GB, the share of "
                f"{device_name} Noir may use while staying loaded."
            ),
        )

    if too_big_for_disk:
        reason = (
            f"Not enough free disk space: {too_big_for_disk[0].name} needs "
            f"{too_big_for_disk[0].download_gb + DISK_HEADROOM_GB:g} GB free, "
            f"this computer has {report.disk_free_gb:g} GB."
        )
    else:
        reason = (
            f"Even the smallest tested model needs {min(m.memory_gb for m in catalog):g} GB, "
            f"and Noir may only use {budget:g} GB here without slowing the computer down."
        )
    return Recommendation(None, device, device_name, budget, None, reason)
