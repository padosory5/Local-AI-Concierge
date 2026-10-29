import pytest

from concierge.catalog import load_catalog, recommend
from concierge.hardware import GPU, HardwareReport


def machine(ram=16.0, ram_free=8.0, disk=200.0, gpus=(), os="windows", arch="amd64"):
    return HardwareReport(
        os=os,
        os_version="test",
        arch=arch,
        cpu_name="Test CPU",
        cpu_cores=8,
        cpu_threads=16,
        ram_total_gb=ram,
        ram_available_gb=ram_free,
        disk_free_gb=disk,
        disk_path="/",
        gpus=list(gpus),
    )


def nvidia(total, free=None):
    free = total - 1.5 if free is None else free
    return GPU("Test RTX", "nvidia", total, free, total >= 4, "test")


@pytest.mark.parametrize(
    "report, expected",
    [
        (machine(gpus=[nvidia(16)]), "qwen3.5:4b"),
        (machine(gpus=[nvidia(12)]), "qwen3:4b"),
        (machine(gpus=[nvidia(8)]), "qwen3:1.7b"),
        (machine(gpus=[nvidia(6)]), "gemma3:1b"),
        # 8 GB laptop with no graphics card.
        (machine(ram=8, ram_free=4), "gemma3:1b"),
        (machine(ram=16, ram_free=8), "qwen3:1.7b"),
        # A big CPU-only machine is still capped so answers stay quick.
        (machine(ram=64, ram_free=40), "qwen3:1.7b"),
        (machine(ram=16, os="macos", arch="arm64",
                 gpus=[GPU("M2", "apple", 10.7, None, True, "test")]), "qwen3:1.7b"),
        (machine(ram=24, os="macos", arch="arm64",
                 gpus=[GPU("M3", "apple", 16, None, True, "test")]), "qwen3.5:4b"),
    ],
)
def test_picks_largest_model_that_fits(report, expected):
    rec = recommend(report)
    assert rec.model is not None, rec.reason
    assert rec.model.tag == expected


def test_busy_graphics_card_lowers_the_budget():
    # 16 GB card, but a game is using most of it right now.
    rec = recommend(machine(gpus=[nvidia(16, free=3.0)]))
    assert rec.budget_gb == 2.0
    assert rec.model.tag == "gemma3:1b"


def test_unusable_card_falls_back_to_cpu():
    igpu = GPU("Intel UHD", "intel", 0.5, None, False, "test")
    rec = recommend(machine(ram=16, ram_free=8, gpus=[igpu]))
    assert rec.device == "cpu"


def test_too_small_machine_gets_no_model_and_a_reason():
    rec = recommend(machine(ram=4, ram_free=1.5))
    assert rec.model is None
    assert "smallest" in rec.reason


def test_no_disk_space_is_explained():
    rec = recommend(machine(gpus=[nvidia(16)], disk=1.0))
    assert rec.model is None
    assert "disk" in rec.reason


def test_catalog_is_ordered_best_first_by_memory():
    memory = [m.memory_gb for m in load_catalog()]
    assert memory == sorted(memory, reverse=True)
