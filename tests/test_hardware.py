from concierge.hardware import describe, detect, parse_nvidia_smi


def test_parse_nvidia_smi():
    out = "NVIDIA GeForce RTX 5080, 16303, 13500\nNVIDIA GeForce GTX 1050, 2048, 1900\n"
    big, small = parse_nvidia_smi(out)
    assert big.name == "NVIDIA GeForce RTX 5080"
    assert big.vram_total_gb == 15.9
    assert big.vram_free_gb == 13.2
    assert big.usable
    assert not small.usable


def test_parse_nvidia_smi_ignores_garbage():
    assert parse_nvidia_smi("NVIDIA-SMI has failed\n") == []


def test_detect_runs_on_this_machine():
    report = detect()
    assert report.ram_total_gb > 0
    assert report.cpu_threads > 0
    assert report.disk_free_gb > 0
    assert describe(report)
