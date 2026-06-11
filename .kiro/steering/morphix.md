# Morphix Project Steering

## Project Overview

Morphix is a Windows desktop video compression app wrapping ffmpeg. It compresses videos to a user-specified max size in MB using two-pass H.264 (libx264) encoding with the `medium` preset. Three entry points share a common core: CLI, Tkinter UI, and a Windows Explorer context menu shell extension (COM DLL). Packaged as MSIX.

## Architecture

- `morphix_core/core.py` is a **re-export facade** — imports from submodules plus one thin `run()` function that instantiates `RunContext` and calls `.execute()`.
- Submodules: `ffmpeg_utils.py`, `gpu_detection.py`, `encoding.py`, `bitrate.py`, `settings.py`, `validation.py`
- `morphix_core/encoding.py` contains the `RunContext` class (all per-run state and execution).
- `morphix_ui/ui_app.py` is the Tkinter GUI (`MorphixUI(tk.Tk)`). Layout in `_build_ui()` and helper methods; event logic in separate methods.
- `morphix_core/cli.py` + `morphix_core/cli_args.py` is the CLI entry point. Entry: `python -m morphix_core.cli` or `Morphix.py` (which imports cli.main).
- `ContextMenuWrl/` is a 64-bit WRL-based C++ COM DLL implementing `IExplorerCommand` (two commands: "Compress with Morphix" and "Open in Morphix").
- `msix/` contains the MSIX manifest, assets, built EXE, and DLL.
- `scripts/build_msix.ps1` handles the full MSIX build+sign pipeline.

## Coding Conventions

- Python 3.13+, conda environment named `env`.
- Uses `ffmpeg-python` library for building ffmpeg command graphs (`ffmpeg.input()`, `ffmpeg.output()`, `ffmpeg.compile()`), but execution is via `subprocess.Popen` for real-time progress parsing and console window suppression.
- All subprocess calls use `popen_no_window_kwargs()` — `CREATE_NO_WINDOW` on Windows, `start_new_session=True` elsewhere.
- Bundled ffmpeg binaries searched in: `_MEIPASS` → Python exe directory → `../ffmpeg/` relative to `core.py` → system PATH via `shutil.which`.
- All computed video dimensions must be even integers (H.264 requirement) via `clamp_even()`.
- Minimum auto-scaled height: 480px.
- Target video bitrate formula: `max(int((size_mb * 1_000_000 * 8) / duration_s / 1000) - audio_kbps, 1)` with default `audio_kbps=128`.
- BPP thresholds: low=0.05, medium=0.07, high=0.10.
- Settings stored at `%APPDATA%\Morphix\settings.json`. Fallback to 20 MB if missing/unreadable.
- Validation (`check_target_exceeds_file_size`, `check_low_compression_ratio`) runs before any ffprobe/ffmpeg call.
- Passlog files go in `.output/` subdirectory under the input file's directory; cleaned up via glob after Pass2.
- GPU detection order: NVIDIA (`nvidia-smi -L`) → AMD (`rocm-smi`/WMI) → Intel (WMI/registry) → CPU fallback. Exceptions are swallowed per-vendor.
- `get_available_devices()` always ends with `("cpu", "CPU")`.
- Pass1 outputs to `NUL` (Windows null device), Pass2 outputs the final file.
- Audio: AAC at 128 kbps (hardcoded). Pass1 uses `an=None` (no audio); Pass2 includes audio if the input has an audio stream.

## Testing

- `pytest` + `hypothesis` for property-based tests (min 100 examples per property).
- Property tests reference design properties: `# Feature: morphix-video-compressor, Property N: <text>`
- Integration tests tagged `@pytest.mark.integration` (require ffmpeg on PATH).
- Tests live in `tests/` directory with files: `test_core.py`, `test_properties.py`, `test_cli.py`, `test_ui.py`, `test_integration.py`.
- `pytest.ini` exists at project root for test configuration.

## Build & Packaging

- CLI EXE: `PyInstaller --onefile -n Morphix_CLI` with hidden imports and bundled ffmpeg binaries.
- UI EXE: `PyInstaller --onefile --noconsole -n Morphix_UI` with add-data and add-binary for morphix_core and ffmpeg.
- COM DLL: built with `msbuild` (Release/x64) from `ContextMenuWrl/MorphixContextMenu.vcxproj`.
- MSIX: packed with `makeappx.exe`, signed with `signtool.exe` using a self-signed cert (`CN=Morphix`).
- `.spec` files exist at project root for PyInstaller configs.

## Key Rules

- Never put logic in `core.py` beyond the thin `run()` wrapper — it is primarily a re-export facade.
- No circular imports between submodules.
- All public functions/classes remain importable from `morphix_core.core` for backward compatibility.
- UI updates from background threads must go through `self.after(0, ...)` for Tkinter thread safety.
- Compression runs in a daemon background thread in the UI.
- The ContextMenu DLL launches EXEs via `ShellExecuteExW` (non-blocking, no Explorer freeze).
- GB-to-MB conversion in UI: `size_mb = size_value * 1000`.
- Default output path: `{input_stem}_{size}mb.{ext}` (CLI/core) or `{input_stem}-morphix-compressed.{ext}` (UI/ContextMenu).
- The UI auto-populates the output field when an input is selected (unless manually edited).
- `RunContext` uses `device_preference` parameter (keys: `"auto"`, `"nvidia"`, `"amd"`, `"intel"`, `"cpu"`).
