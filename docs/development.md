# Development Guide

## Setup

Create and activate the conda environment:

```bash
conda create --name morphix python=3.13
conda activate morphix
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### FFmpeg binaries

The bundled ffmpeg binaries are gitignored. Run the download script to fetch the LGPL build:

```bash
python scripts/download_ffmpeg.py
```

Alternatively, install ffmpeg via Chocolatey (`choco install ffmpeg`) — the app falls back to system PATH.

## Usage (development)

### CLI

```bash
python Morphix.py input.mp4 --max-mb 8
python Morphix.py input.mp4 --max-mb 8 --start 10 --end 30 --output trimmed.mp4
```

### UI

```bash
python morphix_ui/main_window.py
```

## Building

Builds use `.spec` files at the project root. Run from the `morphix` conda environment:

```bash
conda run -n morphix python -m PyInstaller Morphix_CLI.spec
conda run -n morphix python -m PyInstaller Morphix_UI.spec
conda run -n morphix python -m PyInstaller Morphix_UI_Portable.spec
```

Output lands in `dist/`.

## Linting & Testing

```bash
ruff check .
pytest tests/ -x --tb=short -q
```

Integration tests require ffmpeg on PATH or in `ffmpeg_binaries/bin/`:

```bash
pytest tests/ -m integration
```

## CI

- **`.github/workflows/ci.yml`** — lint + unit tests on every push/PR to main (only when `.py` files change)
- **`.github/workflows/build.yml`** — full build on tagged releases (`v*`) or manual dispatch; attaches EXEs to the GitHub Release

## Project Structure

```
morphix_core/       Core compression logic (encoding, bitrate, GPU detection, encoder selection)
morphix_ui/         Tkinter GUI
tests/              Unit, property-based, and integration tests
ContextMenuWrl/     Windows Explorer context menu COM DLL (C++)
msix/               MSIX packaging (see docs/msix.md)
ffmpeg_binaries/    Gitignored; place ffmpeg.exe + ffprobe.exe in bin/
scripts/            Download helpers and build scripts
```

## Context Menu & MSIX Packaging

See [docs/msix.md](docs/msix.md) for COM DLL build instructions, MSIX packaging, and certificate setup.

## AI Assistance

This project was developed with the assistance of AI agents. Steering files are provided in `.kiro/` to help developers, maintainers, and contributors work with AI tooling on this codebase.
