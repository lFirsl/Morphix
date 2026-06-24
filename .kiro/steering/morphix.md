# Morphix Project Steering

## Project Overview

Morphix is a Windows desktop video compression app wrapping ffmpeg. It compresses videos to a user-specified max size in MB using intelligent encoder selection (NVENC multipass, libx264 two-pass, or OpenH264 single-pass fallback). Three entry points share a common core: CLI, Tkinter UI, and a Windows Explorer context menu shell extension (COM DLL). Packaged as MSIX.

## Architecture

- `morphix_core/core.py` is a **re-export facade** — imports from submodules plus one thin `run()` function that instantiates `RunContext` and calls `.execute()`.
- Submodules: `ffmpeg_utils.py`, `gpu_detection.py`, `encoding.py`, `encoder_selection.py`, `bitrate.py`, `settings.py`, `validation.py`
- `morphix_core/encoding.py` contains the `RunContext` class (all per-run state and execution).
- `morphix_core/encoder_selection.py` contains encoder priority list, `select_encoder()`, and `OPENH264_WARNING`.
- `morphix_ui/ui_app.py` is the Tkinter GUI (`MorphixUI(tk.Tk)`). Layout in `_build_ui()` and helper methods; event logic in separate methods.
- `morphix_core/cli.py` + `morphix_core/cli_args.py` is the CLI entry point. Entry: `python -m morphix_core.cli` or `Morphix.py` (which imports cli.main).
- `ContextMenuWrl/` is a 64-bit WRL-based C++ COM DLL implementing `IExplorerCommand` (two commands: "Compress with Morphix" and "Open in Morphix").
- `msix/` contains the MSIX manifest, assets, built EXE, and DLL.
- `scripts/build_msix.ps1` handles the full MSIX build+sign pipeline.
- `scripts/download_ffmpeg.py` downloads LGPL ffmpeg binaries from BtbN into `ffmpeg_binaries/bin/`.

## Coding Conventions

- Python 3.13+, conda environment named `morphix`.
- Code style: PEP 8, enforced by **ruff** (config in `ruff.toml`). Line length 88, double quotes, isort-compatible import ordering.
- Lint rules enabled: E (pycodestyle errors), W (warnings), F (pyflakes), I (isort).
- Per-file ignores: `tests/*` ignores E402 (import order) and E501 (line length).
- Run `ruff check .` to lint and `ruff format .` to format. Use `ruff check --fix .` for auto-fixable issues.
- Uses `ffmpeg-python` library for building ffmpeg command graphs (`ffmpeg.input()`, `ffmpeg.output()`, `ffmpeg.compile()`), but execution is via `subprocess.Popen` for real-time progress parsing and console window suppression.
- All subprocess calls use `popen_no_window_kwargs()` — `CREATE_NO_WINDOW` on Windows, `start_new_session=True` elsewhere.
- Bundled ffmpeg binaries searched in: `_MEIPASS` → Python exe directory → `../ffmpeg/` relative to `core.py` → system PATH via `shutil.which`.
- All computed video dimensions must be even integers (H.264 requirement) via `clamp_even()`.
- Minimum auto-scaled height: 480px.
- Target video bitrate formula: `max(int((size_mb * 1_000_000 * 8) / duration_s / 1000) - audio_kbps, 1)` with default `audio_kbps=128`.
- BPP thresholds: low=0.05, medium=0.07, high=0.10.
- Settings stored at `%APPDATA%\Morphix\settings.json`. Fallback to 20 MB if missing/unreadable.
- Validation (`check_target_exceeds_file_size`, `check_low_compression_ratio`, `check_trim_values`) runs before any ffprobe/ffmpeg call.
- Passlog files go in `.output/` subdirectory under the input file's directory; cleaned up via glob after Pass2.
- GPU detection order: NVIDIA (`nvidia-smi -L`) → AMD (`rocm-smi`/WMI) → Intel (WMI/registry) → CPU fallback. Exceptions are swallowed per-vendor.
- `get_available_devices()` always ends with `("cpu", "CPU")`.
- Pass1 outputs to `NUL` (Windows null device), Pass2 outputs the final file.
- Audio: AAC at 128 kbps (hardcoded). Pass1 uses `an=None` (no audio); Pass2 includes audio if the input has an audio stream.

## Testing

- `pytest` + `hypothesis` for property-based tests (min 100 examples per property).
- Property tests reference design properties: `# Feature: morphix-video-compressor, Property N: <text>`
- Integration tests tagged `@pytest.mark.integration` (require ffmpeg on PATH).
- Tests live in `tests/` directory with files: `test_core.py`, `test_properties.py`, `test_cli.py`, `test_ui.py`, `test_integration.py`, `test_validation.py`.
- `pytest.ini` exists at project root for test configuration.

## Build & Packaging

- All builds run from the `morphix` conda environment (`conda run -n morphix ...`).
- CLI EXE: `PyInstaller Morphix_CLI.spec` (onefile, bundles ffmpeg binaries).
- UI EXE: `PyInstaller Morphix_UI.spec` (onefile, noconsole, bundles morphix_core and ffmpeg).
- COM DLL: built with `msbuild` (Release/x64) from `ContextMenuWrl/MorphixContextMenu.vcxproj`.
- MSIX: packed with `makeappx.exe`, signed with `signtool.exe` using a self-signed cert (`CN=Morphix`).
- `.spec` files at project root are the canonical PyInstaller build configs — use them instead of raw CLI flags.

## Trim Feature

- Users provide `start` and `end` (seconds) to extract and compress a specific segment.
- CLI args: `--start` and `--end` (float seconds). UI: "Enable Trim" checkbox with HH:MM:SS entries.
- Trim is applied directly via ffmpeg `-ss` and `-t` input options on the original file during encode — no temporary files.
- When trimming, `trim_duration` (not full video duration) is used for bitrate calculation and progress tracking.
- If the estimated segment size (source bitrate × trim_duration) fits within `max_mb`, a single-pass CRF 18 encode is used (quality-preserving, no bitrate target).
- If the segment exceeds `max_mb`, the normal two-pass encode runs with `-ss`/`-t` in `input_kwargs`.
- Both passes receive identical `-ss`/`-t` values ensuring the two-pass log stays in sync.
- `_estimated_segment_mb()` uses `format.bit_rate` from ffprobe to estimate segment size.
- Validation: `check_trim_values(start, end, full_duration)` ensures both provided, ≥ 0, end > start, and within video duration.

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
- `RunContext` accepts `start` and `end` (float seconds, optional) for trim. `self.trimming` is set in `__init__` based on both being non-None.
- `RunContext` accepts `warning_cb` (callable) and `encoder_override` (str|None).

## Encoder Selection

- Priority: h264_nvenc (nvenc_multipass) > libx264 (two_pass) > libopenh264 (single_pass_cbr).
- `select_encoder()` in `encoder_selection.py` picks the best available encoder based on GPU detection and ffmpeg capabilities.
- NVENC multipass uses full bitrate (no safety margin — its internal two-pass is accurate).
- Single-pass encoders (OpenH264) use `SAFETY_MARGIN = 0.85` + one retry if output exceeds target.
- OpenH264 warning shown once per session via `warning_cb` (popup in UI, stderr in CLI).
- UI "Advanced" section shows Device + Encoder dropdowns; unavailable encoders greyed out with inline reason.
- `detect_available_encoders(ffmpeg_path)` in `ffmpeg_utils.py` probes which encoders the bundled ffmpeg supports.
- `detect_build_type(ffmpeg_path)` returns "gpl" or "lgpl" based on ffmpeg's configuration line.

## CI / CD

- `.github/workflows/ci.yml` — lint (ruff) + unit tests on push/PR to main, only when `.py`, `requirements.txt`, or `ruff.toml` change.
- `.github/workflows/build.yml` — full build on tagged releases (`v*`) or manual dispatch. Downloads LGPL ffmpeg, runs all tests, builds both EXEs, uploads zipped artifacts, and creates a GitHub Release on tags.
- Integration test fixture: `tests/fixtures/test_video.mp4` (15MB synthetic mandelbrot video, committed to repo).
- FFmpeg binaries are gitignored; CI downloads from BtbN `latest` tag with caching.
