# Morphix Project Steering

## Project Overview

Morphix is a Windows desktop video compression app wrapping ffmpeg. It compresses videos to a user-specified max size in MB using intelligent encoder selection (NVENC multipass, libx264 two-pass, or OpenH264 single-pass fallback). Three entry points share a common core: CLI, Tkinter UI, and a Windows Explorer context menu shell extension (COM DLL). Packaged as MSIX.

## Architecture

### Core (`morphix_core/`)

- `config.py` — frozen `CompressConfig` dataclass (all user-facing parameters for a run). Also contains `parse_resolution()` utility.
- `core.py` — **re-export facade** for external interfaces. Thin `run()` function accepts `config=` kwarg (a `CompressConfig`) or individual kwargs for backward compat, instantiates `RunContext`, and calls `.execute()`.
- `encoding.py` — `RunContext` class. Accepts a `CompressConfig`, holds mutable runtime state, and orchestrates the full compression pipeline. Contains `_build_output_stream()` / `_build_analysis_stream()` helpers to eliminate repeated ffmpeg stream-building. Strategy dispatch via dict lookup.
- `encoder_selection.py` — frozen `EncoderConfig` dataclass, `ENCODER_PRIORITY` list of `EncoderConfig` instances, `select_encoder()`, `OPENH264_WARNING`, `SAFETY_MARGIN`.
- `ffmpeg_utils.py` — `find_ffmpeg_binaries()`, `ffprobe_media()`, `detect_available_encoders()`, `detect_build_type()`, `get_ffmpeg_version()`, `popen_no_window_kwargs()`.
- `gpu_detection.py` — vendor registry pattern (`_VENDORS` list). Per-vendor detection functions (`detect_cuda`, `detect_amd`, `detect_intel`). Public API: `detect_device_info()`, `resolve_device_info()`, `get_available_devices()`, `check_nvenc_usable()`.
- `bitrate.py` — `target_kbps_for_size_mb()`, `compute_scaled_resolution()`, `parse_fps()`, `clamp_even()`.
- `settings.py` — `MorphixSettings` dataclass, `read_settings()` (returns `MorphixSettings`), `write_settings()` (accepts `MorphixSettings` or float). Stored at `%APPDATA%\Morphix\settings.json`.
- `validation.py` — `check_target_exceeds_file_size()`, `check_low_compression_ratio()`, `check_trim_values()`.
- `cli.py` + `cli_args.py` — CLI entry point. `cli.py` builds a `CompressConfig` from parsed args and calls `run(config=config)`. Entry: `python -m morphix_core.cli` or `Morphix.py`.

### UI (`morphix_ui/`)

- `main_window.py` — `MorphixUI(tk.Tk)` shell class. Contains the tab bar, content area, Compress/Settings buttons, status labels, and `run_compress()`. Delegates all input to tab classes. Contains `MorphixState` dataclass for shared mutable UI state.
- `tabs/` — tab package implementing the `BaseTab` registry pattern:
  - `base.py` — `BaseTab(tk.Frame, ABC)` with abstract methods: `build()`, `collect()`, `validate()`, `set_enabled()`. Class-level `label` attribute.
  - `target_tab.py` — `TargetTab` (input/output/size) + frozen `TargetParams` dataclass.
  - `trim_tab.py` — `TrimTab` (enable/start/end) + frozen `TrimParams` dataclass.
  - `advanced_tab.py` — `AdvancedTab` (device/encoder) + frozen `AdvancedParams` dataclass.
- `validation_chain.py` — Chain of Responsibility validation pipeline: `ValidationHandler` ABC, `FileSizeHandler`, `TrimValuesHandler`, `build_chain()`.
- `time_utils.py` — shared `parse_time()` and `format_time()` (HH:MM:SS ↔ seconds).
- `widgets.py` — reusable Tkinter helpers: `set_widgets_state()`, `show_error()`, `show_warning()`, `set_status()`.
- `dialogs.py` — modal dialogs: `show_settings_dialog()`, `show_about_morphix()`.
- `compression_worker.py` — `CompressionCallbacks` dataclass and `start_compression()` thread launcher.
- `ffmpeg_download.py` — GPL ffmpeg download helper and "About FFmpeg" dialog.

### Other

- `ContextMenuWrl/` — 64-bit WRL-based C++ COM DLL implementing `IExplorerCommand` (two commands: "Compress with Morphix" and "Open in Morphix").
- `msix/` — MSIX manifest, assets, built EXE, and DLL.
- `scripts/build_msix.ps1` — full MSIX build+sign pipeline.
- `scripts/download_ffmpeg.py` — downloads LGPL ffmpeg binaries from BtbN into `ffmpeg_binaries/bin/`.

## Coding Conventions

- Python 3.13+, conda environment named `morphix`.
- Code style: PEP 8, enforced by **ruff** (config in `ruff.toml`). Line length 88, double quotes, isort-compatible import ordering.
- Lint rules enabled: E (pycodestyle errors), W (warnings), F (pyflakes), I (isort).
- Per-file ignores: `tests/*` ignores E402 (import order) and E501 (line length).
- Run `ruff check .` to lint and `ruff format .` to format. Use `ruff check --fix .` for auto-fixable issues.
- Uses `ffmpeg-python` library for building ffmpeg command graphs (`ffmpeg.input()`, `ffmpeg.output()`, `ffmpeg.compile()`), but execution is via `subprocess.Popen` for real-time progress parsing and console window suppression.
- All subprocess calls use `popen_no_window_kwargs()` — `CREATE_NO_WINDOW` on Windows, `start_new_session=True` elsewhere.
- Bundled ffmpeg binaries searched in: `_MEIPASS` → Python exe directory → `../ffmpeg/` relative to `core.py` → system PATH via `shutil.which`.
- Path manipulation uses `pathlib.Path` throughout core. UI uses `pathlib` where practical.
- All computed video dimensions must be even integers (H.264 requirement) via `clamp_even()`.
- Minimum auto-scaled height: 480px.
- Target video bitrate formula: `max(int((size_mb * 1_000_000 * 8) / duration_s / 1000) - audio_kbps, 1)` with default `audio_kbps=128`.
- BPP thresholds: low=0.05, medium=0.07, high=0.10.
- Validation (`check_target_exceeds_file_size`, `check_low_compression_ratio`, `check_trim_values`) runs before any ffprobe/ffmpeg call.
- Passlog files go in `.output/` subdirectory under the input file's directory; cleaned up via `Path.glob()` after Pass2.
- GPU detection uses a `_VENDORS` registry (string-based function names for mock compatibility). Order: NVIDIA → AMD → Intel → CPU fallback. Exceptions swallowed per-vendor.
- `get_available_devices()` always ends with `("cpu", "CPU", True)`.
- Pass1 outputs to `NUL` (Windows null device), Pass2 outputs the final file.
- Audio: AAC at 128 kbps (hardcoded). Pass1 uses `an=None` (no audio); Pass2 includes audio if the input has an audio stream.
- Core uses `logging` module (`logger = logging.getLogger("morphix")`). CLI configures `logging.basicConfig`. No bare `print()` in core.

## Dataclasses

- `CompressConfig` (frozen) — immutable snapshot of "what the user asked for". Created fresh per run.
  - Fields: `input_path` (Path), `max_mb`, `output_path`, `quality` (Literal), `resolution`, `device_preference` (Literal), `overwrite`, `disable_logs`, `progress`, `progress_cb`, `start`, `end`, `warning_cb`, `encoder_override`.
  - Computed properties: `trimming` (bool), `trim_duration` (float).
- `EncoderConfig` (frozen) — a single encoder option: `name`, `strategy`, `required_device`.
- `MorphixSettings` — user settings: `default_mb` (float, default 20). Serialized to/from JSON.
- `MorphixState` — mutable UI state shared across tabs: `is_running`, `auto_output`, `suppress_output_trace`, `trim_duration_seconds`, `openh264_warned`, `device_label_to_key`, `unavailable_devices`.
- `TargetParams` (frozen) — collected from Target tab: `input_path`, `output_path`, `size_mb`.
- `TrimParams` (frozen) — collected from Trim tab: `enabled`, `start`, `end`.
- `AdvancedParams` (frozen) — collected from Advanced tab: `device_preference`, `encoder_override`.
- `CompressionCallbacks` — callbacks the compression worker invokes: `on_progress`, `on_status`, `on_done`, `on_error`, `on_warning`, `on_encoder_info`.

## RunContext

- Accepts a single `CompressConfig` via `__init__(self, config)`. Holds only mutable runtime state (duration, video_kbps, probe, scale, passlog_path, etc.).
- `RunContext.execute()` runs the full pipeline and returns the output path.
- Encode strategies dispatched via dict: `{"two_pass": ..., "nvenc_multipass": ..., "single_pass_cbr": ...}`.
- Scale stored as `tuple[int, int] | None` (not a filter string). Passed to `ffmpeg.filter_("scale", w, h)`.

## Tabbed UI Architecture

- `MorphixUI` holds `self.tabs: list[BaseTab]` — currently `[TargetTab, TrimTab, AdvancedTab]`.
- One tab visible at a time, switched via a horizontal button bar at the top.
- Adding a new tab: subclass `BaseTab`, implement `build/collect/validate/set_enabled`, append to `self.tabs` in `__init__`. Nothing else changes.
- Each tab owns its own `tk.StringVar`/`tk.BooleanVar` instances and widgets.
- Each tab produces a frozen dataclass via `collect()` and validates its own slice via `validate() -> str | None`.
- Shared state: all tabs receive `MorphixState` at construction and read/write it as needed.
- `run_compress()` collects from all tabs, runs per-tab validation, then runs the CoR validation chain. Low-ratio warning (askokcancel) handled inline in main_window since it's a soft check.
- `_set_controls_enabled()` iterates tabs and calls `tab.set_enabled()` — no hardcoded widget list.
- File probe callback: `TargetTab` receives `on_file_selected: Callable[[float], None]`; main window forwards duration to `TrimTab.set_end_time()`.

## Validation Chain (CoR)

- `ValidationHandler` ABC — `set_next()`, `handle(params)`, abstract `check(params)`.
- `FileSizeHandler` — wraps `check_target_exceeds_file_size`. Returns error string or None.
- `TrimValuesHandler` — wraps `check_trim_values`. Returns error string or None.
- `build_chain(*handlers)` wires handlers into a linked chain, returns the head.
- `params` dict passed to `handle()` contains: `"Target"` (TargetParams), `"Trim"` (TrimParams), `"Advanced"` (AdvancedParams), `"_trim_duration"` (float).
- Adding a new validation rule: subclass `ValidationHandler`, implement `check()`, insert into `build_chain()` call in main_window.

## Tkinter / PyInstaller Conventions

- Tkinter submodule imports (`filedialog`, `messagebox`) must be at **module level**, not inline inside methods. Inline imports fail silently in frozen PyInstaller bundles.
- All `filedialog.askopenfilename()` / `asksaveasfilename()` calls must pass `parent=self._app` to anchor the dialog to the main window. Without it, the dialog can open behind the window on some Windows setups.
- `tkinter.filedialog` and `tkinter.messagebox` must be listed in `hiddenimports` in the `.spec` file — PyInstaller's static analyser does not always detect them.
- UI updates from background threads must go through `self.after(0, ...)` or helpers in `widgets.py`.

## Testing

- `pytest` + `hypothesis` for property-based tests (min 100 examples per property).
- 296 tests across 7 files: `test_config.py`, `test_core.py`, `test_properties.py`, `test_cli.py`, `test_ui.py`, `test_tabs.py`, `test_validation_chain.py`, `test_integration.py`, `test_validation.py`.
- Property tests reference design properties: `# Feature: morphix-video-compressor, Property N: <text>`
- Integration tests tagged `@pytest.mark.integration` (require ffmpeg on PATH).
- `pytest.ini` exists at project root for test configuration.
- Test helpers construct `CompressConfig` first, then pass to `RunContext`. No direct kwarg construction of `RunContext`.
- UI tests use a headless fake Tkinter (stubs in `test_ui.py` and `test_tabs.py`). Tabs must be compatible with `_FakeWidget`.
- Tab tests patch `morphix_ui.tabs.<module>.<function>` for isolation (e.g. `morphix_ui.tabs.target_tab.filedialog`).
- Path comparisons in tests must use `Path()` normalisation, not raw `os.path.join` strings — avoids Windows 8.3 short-name mismatches on CI runners.

## Build & Packaging

- All builds run from the `morphix` conda environment (`conda run -n morphix ...`).
- CLI EXE: `PyInstaller Morphix_CLI.spec` (onefile, bundles ffmpeg binaries).
- UI EXE: `PyInstaller Morphix_UI.spec` (onefile, noconsole, bundles `morphix_core`, `morphix_ui`, and ffmpeg).
- `hiddenimports` in UI spec must include: all `morphix_core.*` modules, all `morphix_ui.*` and `morphix_ui.tabs.*` modules, `tkinter.filedialog`, `tkinter.messagebox`, `ffmpeg`.
- COM DLL: built with `msbuild` (Release/x64) from `ContextMenuWrl/MorphixContextMenu.vcxproj`.
- MSIX: packed with `makeappx.exe`, signed with `signtool.exe` using a self-signed cert (`CN=Morphix`).
- `.spec` files at project root are the canonical PyInstaller build configs — use them instead of raw CLI flags.

## Trim Feature

- Users provide `start` and `end` (seconds) to extract and compress a specific segment.
- CLI args: `--start` and `--end` (float seconds). UI: "Enable Trim" checkbox in the Trim tab with HH:MM:SS entries.
- Trim is applied directly via ffmpeg `-ss` and `-t` input options on the original file during encode — no temporary files.
- When trimming, `config.trim_duration` (not full video duration) is used for bitrate calculation and progress tracking.
- If the estimated segment size (source bitrate × trim_duration) fits within `max_mb`, a single-pass CRF 18 encode is used (quality-preserving, no bitrate target).
- If the segment exceeds `max_mb`, the normal two-pass encode runs with `-ss`/`-t` in `input_kwargs`.
- Both passes receive identical `-ss`/`-t` values ensuring the two-pass log stays in sync.
- `_estimated_segment_mb()` uses `format.bit_rate` from ffprobe to estimate segment size.
- Validation: `check_trim_values(start, end, full_duration)` ensures both provided, ≥ 0, end > start, and within video duration.
- Time parsing/formatting shared via `morphix_ui/time_utils.py` (`parse_time`, `format_time`).

## Key Rules

- Never put logic in `core.py` beyond the thin `run()` wrapper — it is primarily a re-export facade.
- No circular imports between submodules.
- All public functions/classes remain importable from `morphix_core.core` for backward compatibility.
- Compression runs in a daemon background thread via `compression_worker.start_compression()`.
- The ContextMenu DLL launches EXEs via `ShellExecuteExW` (non-blocking, no Explorer freeze).
- GB-to-MB conversion in UI: `size_mb = size_value * 1000`.
- Default output path: `{input_stem}_{size}mb.{ext}` (CLI/core) or `{input_stem}-morphix-compressed.{ext}` (UI/ContextMenu).
- The UI auto-populates the output field when an input is selected (unless manually edited).
- `CompressConfig.device_preference` accepts: `"auto"`, `"nvidia"`, `"amd"`, `"intel"`, `"cpu"`.
- `CompressConfig.trimming` and `CompressConfig.trim_duration` are computed properties (not stored fields).
- `CompressConfig` is frozen — a new instance is created per compression run.
- CLI builds `CompressConfig` directly from argparse args — no kwargs-based `run()` call.

## Encoder Selection

- Priority: h264_nvenc (nvenc_multipass) > libx264 (two_pass) > libopenh264 (single_pass_cbr).
- `ENCODER_PRIORITY` is a list of `EncoderConfig` frozen dataclass instances.
- `select_encoder()` in `encoder_selection.py` picks the best available encoder based on GPU detection and ffmpeg capabilities.
- NVENC multipass uses full bitrate (no safety margin — its internal two-pass is accurate).
- Single-pass encoders (OpenH264) use `SAFETY_MARGIN = 0.85` + one retry if output exceeds target.
- OpenH264 warning shown once per session via `warning_cb` (popup in UI, logged in CLI).
- UI Advanced tab shows Device + Encoder dropdowns; unavailable encoders greyed out with inline reason.
- `detect_available_encoders(ffmpeg_path)` in `ffmpeg_utils.py` probes which encoders the bundled ffmpeg supports.
- `detect_build_type(ffmpeg_path)` returns "gpl" or "lgpl" based on ffmpeg's configuration line.

## CI / CD

- `.github/workflows/ci.yml` — lint (ruff) + unit tests on push/PR to main, only when `.py`, `requirements.txt`, or `ruff.toml` change.
- `.github/workflows/build.yml` — full build on tagged releases (`v*`) or manual dispatch. Downloads LGPL ffmpeg, runs all tests, builds both EXEs, uploads zipped artifacts, and creates a GitHub Release on tags.
- Integration test fixture: `tests/fixtures/test_video.mp4` (15MB synthetic mandelbrot video, committed to repo).
- FFmpeg binaries are gitignored; CI downloads from BtbN `latest` tag with caching.
