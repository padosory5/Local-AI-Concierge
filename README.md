# Local-AI-Concierge

Elaina: a simple app that sets up local AI for anyone. She checks your
computer, picks a model that fits it, and chats with you, all on your own
machine.

## What works now (first process)

1. **Check the computer** (`concierge/hardware.py`). Plain code reads the OS,
   CPU, memory, disk and graphics cards. NVIDIA through `nvidia-smi`, AMD and
   Intel through the Windows registry or Linux sysfs, Apple Silicon through
   its shared memory. Nothing is guessed.
2. **Pick Elaina's model** (`concierge/catalog.py`, `concierge/models.yaml`).
   Elaina stays loaded all the time, so she may only use a small share of the
   machine: 30% of a graphics card, 20% of a Mac's shared memory, or 18% of
   RAM (at most 3 GB) on the processor. The first model in the tested list
   that fits wins.
3. **Make it Elaina** (`concierge/elaina.py`, `concierge/persona/`). Creates an
   Ollama model named `elaina` from the chosen model, with her persona and the
   facts about this computer baked in. It is rebuilt automatically when the
   persona, the hardware or the chosen model changes.
4. **Chat** (`ElainaChat` in `concierge/elaina.py`). Streams replies, keeps the
   recent conversation, and turns off "thinking" so answers come quickly. The
   terminal chat in `cli.py` is temporary; the real UI will reuse `ElainaChat`.

## Setup

You need [Python 3.11](https://www.python.org/downloads/) and
[Ollama](https://ollama.com/download).

```bash
git clone https://github.com/padosory5/Local-AI-Concierge.git
cd Local-AI-Concierge
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

On macOS or Linux use `python3.11 -m venv .venv` and `source .venv/bin/activate`.

## Run

```bash
python -m concierge             # set up if needed, then chat
python -m concierge hardware    # what this computer has (--json for raw)
python -m concierge recommend   # which model Elaina would use, and why
python -m concierge setup       # download the model and rebuild Elaina
python -m concierge chat        # talk with Elaina
python -m concierge measure TAG # real graphics memory a model uses
pytest                          # run the tests
```

## Growing the tested model list

`models.yaml` is the list Elaina picks from, best first. Ollama's own memory
figure is often wrong (it claimed 2.92 GB for qwen3.5:4b; the card used
3.84 GB), so every entry should be measured on a real card:

```bash
ollama pull gemma3:1b
python -m concierge measure gemma3:1b
```

Copy the printed `memory_gb` into `models.yaml` and set `measured: true`.
Entries still marked `measured: false` are estimates.

## Project layout

```text
concierge/
  hardware.py     step 1: read the computer
  catalog.py      step 2: pick a model from models.yaml
  models.yaml     the tested model list
  elaina.py       step 3 and 4: build Elaina, chat session
  persona/        Elaina's persona prompt
  ollama.py       small client for the local Ollama server
  cli.py          temporary terminal front end
tests/            pytest suite, no Ollama needed
```

## Working together

- Pull before you start: `git pull`.
- One branch per feature (`git switch -c feature/<name>`), then a pull request.
- New package? Add it to `requirements.txt` in the same commit.
- Natural split right now: one person on hardware detection and the tested
  model list (measuring models on different machines), the other on Elaina's
  persona and the chat session.
