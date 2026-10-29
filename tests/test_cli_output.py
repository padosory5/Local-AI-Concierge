from concierge import cli, elaina
from concierge.catalog import recommend
from tests.test_catalog import machine, nvidia


def show(report, monkeypatch, capsys, built_from):
    monkeypatch.setattr(elaina, "load_state", lambda: {"base_model": built_from})
    rec = recommend(report)
    cli._print_recommendation(rec)
    cli._print_in_use(rec)
    return capsys.readouterr().out


def test_laptop_without_graphics_card(monkeypatch, capsys):
    out = show(machine(ram=16, ram_free=8), monkeypatch, capsys, "qwen3:1.7b")
    assert "Recommended for this computer: Qwen 3 1.7B (qwen3:1.7b)" in out
    assert "of memory" in out  # system memory, not graphics memory
    assert "Elaina is using: Qwen 3 1.7B (qwen3:1.7b) on Test CPU" in out
    assert "Not the recommended" not in out


def test_desktop_with_big_graphics_card(monkeypatch, capsys):
    out = show(machine(gpus=[nvidia(16)]), monkeypatch, capsys, "qwen3.5:4b")
    assert "Recommended for this computer: Qwen 3.5 4B (qwen3.5:4b)" in out
    assert "of graphics memory" in out
    assert "Elaina is using: Qwen 3.5 4B (qwen3.5:4b) on Test RTX" in out


def test_says_when_elaina_is_not_on_the_recommended_model(monkeypatch, capsys):
    out = show(machine(gpus=[nvidia(16)]), monkeypatch, capsys, "qwen3:1.7b")
    assert "Elaina is using: Qwen 3 1.7B (qwen3:1.7b)" in out
    assert "Not the recommended Qwen 3.5 4B" in out
