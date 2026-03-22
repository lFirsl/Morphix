# Requirements Document

## Introduction

Morphix is a Windows desktop video compression application that wraps ffmpeg to compress video files to a user-specified maximum size in megabytes. It uses two-pass H.264 (libx264) encoding with configurable audio codec and bitrate (defaulting to AAC at 128 kbps), automatic resolution scaling based on bits-per-pixel quality thresholds, and optional GPU-accelerated decoding with multi-vendor support (NVIDIA, AMD, and Intel). Morphix is available as a CLI tool, a Tkinter desktop UI, and a Windows Explorer context menu shell extension, all packaged as an MSIX installer.

The UI supports target size input in MB or GB, converting to MB before passing to the core. The context menu provides two distinct top-level entries: "Compress with Morphix", which prompts the user for a target size (defaulting to 20 MB) and runs compression headlessly, and "Open in Morphix", which launches the full Tkinter UI with the selected file pre-loaded in the input field. The application is designed to be easy to use for non-power users, with sensible defaults for all advanced options.

This document captures the current baseline state of the application as implemented.

## Glossary

- **Compressor**: The core compression engine (`morphix_core/core.py`) responsible for orchestrating ffmpeg two-pass encoding.
- **CLI**: The command-line interface (`morphix_core/cli.py` and `morphix_core/cli_args.py`) that exposes the Compressor via terminal arguments.
- **UI**: The Tkinter desktop graphical interface (`morphix_ui/ui_app.py`) that exposes the Compressor via a windowed form.
- **ContextMenu**: The Windows COM shell extension DLL (`ContextMenuWrl/`) that adds a right-click menu entry in Windows Explorer.
- **Installer**: The MSIX package (`msix/`) that bundles the CLI EXE, UI EXE, and ContextMenu DLL for installation on Windows.
- **ffmpeg**: The external binary used for video encoding and decoding.
- **ffprobe**: The external binary used to inspect video file metadata (duration, resolution, frame rate, streams).
- **Pass1**: The first encoding pass in two-pass encoding, which analyzes the video to generate bitrate statistics without producing output.
- **Pass2**: The second encoding pass that uses Pass1 statistics to produce the final compressed output file.
- **bpp**: Bits per pixel per frame, used as a quality threshold for auto-scaling resolution decisions.
- **hwaccel**: Hardware acceleration for video decoding, supporting NVIDIA (CUDA), AMD, and Intel GPUs, with automatic vendor detection and CPU fallback.
- **passlog**: Temporary log files written by ffmpeg during Pass1 and consumed during Pass2, stored in the `.output/` subdirectory.

---

## Requirements

### Requirement 1: Two-Pass H.264 Video Compression

**User Story:** As a user, I want to compress a video file to a target maximum size in MB, so that I can share or store the video within a file size constraint.

#### Acceptance Criteria

1. WHEN a valid input video path and a target size in MB are provided, THE Compressor SHALL encode the video using two-pass H.264 (libx264) encoding with the `medium` preset.
2. THE Compressor SHALL encode audio using a configurable codec and bitrate, defaulting to AAC at 128 kbps when no audio codec or bitrate is specified.
3. THE Compressor SHALL calculate the target video bitrate using the formula: `video_kbps = ((size_mb * 1_000_000 * 8) / duration_s / 1000) - audio_kbps`, where `audio_kbps` is the configured audio bitrate parameter.
4. THE Compressor SHALL ensure the calculated video bitrate is at least 1 kbps.
5. WHEN Pass1 completes successfully, THE Compressor SHALL execute Pass2 using the passlog data produced by Pass1.
6. WHEN both passes complete successfully, THE Compressor SHALL return the path to the output file.

### Requirement 2: Output File Path Resolution

**User Story:** As a user, I want the output file to have a sensible default name, so that I do not need to specify one manually.

#### Acceptance Criteria

1. WHEN no output path is specified, THE Compressor SHALL derive the output path from the input filename by appending `_{size}mb` before the file extension (e.g., `video_15mb.mp4`).
2. WHEN the input file has no extension, THE Compressor SHALL use `.mp4` as the output extension.
3. WHEN an output path is explicitly provided, THE Compressor SHALL use that path without modification.
4. THE Compressor SHALL place the default output file in the same directory as the input file.

### Requirement 3: Automatic Resolution Scaling

**User Story:** As a user, I want the video resolution to be automatically reduced when the target bitrate is too low for the original resolution, so that the output video maintains acceptable visual quality.

#### Acceptance Criteria

1. WHEN no manual resolution override is provided, THE Compressor SHALL compute a scaled resolution based on the target bits-per-pixel-per-frame (bpp) threshold for the selected quality level.
2. THE Compressor SHALL use the following bpp thresholds: `low` = 0.05, `medium` = 0.07, `high` = 0.10.
3. WHEN the current bpp at the original resolution meets or exceeds the target bpp threshold, THE Compressor SHALL not apply any resolution scaling.
4. WHEN scaling is required, THE Compressor SHALL compute the new resolution by scaling width and height proportionally so that the resulting pixel count satisfies the target bpp.
5. THE Compressor SHALL enforce a minimum output height of 480 pixels during auto-scaling, preserving the original aspect ratio.
6. THE Compressor SHALL round all computed dimensions to the nearest even integer for H.264 compatibility.
7. WHEN computed dimensions are less than 2 pixels in either dimension, THE Compressor SHALL not apply scaling.

### Requirement 4: Manual Resolution Override

**User Story:** As a user, I want to specify an exact output resolution, so that I can control the output dimensions regardless of the bitrate-based auto-scaling logic.

#### Acceptance Criteria

1. WHEN a resolution string in the format `WIDTHxHEIGHT` (e.g., `1280x720`) is provided, THE Compressor SHALL apply that resolution as a scale filter, overriding auto-scaling.
2. THE Compressor SHALL clamp the specified width and height to the nearest even integer.
3. WHEN the specified width or height resolves to less than 2 pixels, THE Compressor SHALL not apply the scale filter.
4. WHEN an invalid resolution string is provided, THE Compressor SHALL not apply any scale filter and SHALL proceed with the original resolution.

### Requirement 5: Hardware Acceleration Detection

**User Story:** As a user, I want the application to detect and use my GPU for decoding when available, so that compression is faster on supported hardware.

#### Acceptance Criteria

1. WHEN `nvidia-smi` is present on the system PATH and returns a successful exit code with GPU output, THE Compressor SHALL use CUDA hardware acceleration for video decoding and SHALL report the device label `NVIDIA GPU`.
2. WHEN NVIDIA detection fails or is unavailable, THE Compressor SHALL attempt AMD GPU detection via `rocm-smi` or a WMI/system query for AMD display adapters.
3. WHEN AMD GPU detection succeeds, THE Compressor SHALL use AMD hardware acceleration for video decoding and SHALL report the device label `AMD GPU`.
4. WHEN AMD detection fails or is unavailable, THE Compressor SHALL attempt Intel GPU detection via WMI or registry query for Intel display adapters.
5. WHEN Intel GPU detection succeeds, THE Compressor SHALL use Intel hardware acceleration for video decoding and SHALL report the device label `Intel GPU`.
6. WHEN all vendor-specific detection methods fail or raise OS-level errors, THE Compressor SHALL fall back to CPU-based decoding and SHALL report the device label `CPU`.
7. IF any vendor detection step raises an exception, THEN THE Compressor SHALL catch the exception and proceed to the next vendor detection step without propagating the error.
8. THE Compressor SHALL expose a `get_available_devices()` function that returns a list of `(key, label)` tuples for all detected devices in preferred order, with the best available GPU first and `("cpu", "CPU")` always included as the last entry.
9. THE Compressor SHALL expose a `resolve_device_info(device_preference)` function that accepts a device key string and returns a `(label, hwaccel)` tuple; WHEN the requested device is unavailable, THE Compressor SHALL fall back to CPU and return `("CPU", None)`.

### Requirement 6: ffmpeg Binary Resolution

**User Story:** As a user, I want the application to use bundled ffmpeg binaries when available, so that I do not need to install ffmpeg separately.

#### Acceptance Criteria

1. THE Compressor SHALL search for bundled `ffmpeg.exe` and `ffprobe.exe` binaries in the following locations, in order: the PyInstaller `_MEIPASS` bundle directory, the directory containing the Python executable, and the `ffmpeg/` subdirectory relative to `core.py`.
2. WHEN bundled binaries are found at any candidate location, THE Compressor SHALL use those binaries and report the source as `bundled`.
3. WHEN no bundled binaries are found, THE Compressor SHALL fall back to `ffmpeg` and `ffprobe` resolved from the system PATH and report the source as `path`.

### Requirement 7: Progress Reporting

**User Story:** As a user, I want to see compression progress during encoding, so that I know the operation is running and how far along it is.

#### Acceptance Criteria

1. WHEN progress reporting is enabled, THE Compressor SHALL parse `out_time_ms` values from ffmpeg stderr to compute a percentage of completion relative to the total video duration.
2. THE Compressor SHALL report progress separately for Pass1 and Pass2, identified by the phase labels `PASS1` and `PASS2`.
3. WHEN a `progress_cb` callback is provided, THE Compressor SHALL invoke it with `(percentage: float, phase: str)` on each progress update.
4. WHEN no `progress_cb` is provided and progress is enabled, THE Compressor SHALL write progress to stdout as a percentage.
5. WHEN progress reporting is disabled, THE Compressor SHALL not parse ffmpeg stderr for progress data.

### Requirement 8: Two-Pass Log File Management

**User Story:** As a developer, I want temporary two-pass log files to be cleaned up after encoding, so that the working directory is not cluttered with intermediate files.

#### Acceptance Criteria

1. THE Compressor SHALL write passlog files to a `.output/` subdirectory within the input file's directory, creating the directory if it does not exist.
2. WHEN Pass2 completes successfully, THE Compressor SHALL delete the passlog files with `.log` and `.log.mbtree` suffixes.
3. WHEN the `.output/` directory is empty after cleanup, THE Compressor SHALL remove the directory.
4. WHEN a passlog file does not exist during cleanup, THE Compressor SHALL silently skip deletion of that file.

### Requirement 9: ffmpeg Error Logging

**User Story:** As a developer, I want ffmpeg errors to be persisted to a log file, so that I can diagnose compression failures.

#### Acceptance Criteria

1. WHEN ffmpeg exits with a non-zero return code, THE Compressor SHALL write the captured stderr output to `.output/ffmpeg-error.log` in the input file's directory.
2. WHEN no stderr was captured from ffmpeg, THE Compressor SHALL write the message `No stderr captured from ffmpeg.` to the error log.
3. WHEN an ffmpeg error occurs, THE Compressor SHALL print the path to the error log to stdout.
4. WHEN an ffmpeg error occurs, THE Compressor SHALL re-raise the exception after writing the log.

### Requirement 10: Console Window Suppression on Windows

**User Story:** As a Windows user, I want ffmpeg child processes to run without spawning visible console windows, so that the UI experience is not disrupted by terminal popups.

#### Acceptance Criteria

1. WHEN running on Windows, THE Compressor SHALL launch all ffmpeg and ffprobe subprocesses with the `CREATE_NO_WINDOW` creation flag.
2. WHEN running on a non-Windows OS, THE Compressor SHALL launch subprocesses with `start_new_session=True` to avoid attaching to the parent TTY.

### Requirement 11: CLI Interface

**User Story:** As a developer or power user, I want to compress videos from the command line, so that I can integrate Morphix into scripts and automated workflows.

#### Acceptance Criteria

1. THE CLI SHALL accept a positional `input` argument specifying the path to the input video file.
2. THE CLI SHALL accept a `--max-mb` argument specifying the target maximum output size as a floating-point number of megabytes.
3. THE CLI SHALL accept an optional `--output` argument specifying the output file path.
4. THE CLI SHALL accept a `--quality` argument with choices `low`, `medium`, and `high`, defaulting to `medium`.
5. THE CLI SHALL accept a `--resolution` argument to manually override the output resolution in `WIDTHxHEIGHT` format.
6. THE CLI SHALL accept `--overwrite` / `--no-overwrite` flags, defaulting to overwrite enabled.
7. THE CLI SHALL accept `--progress` / `--no-progress` flags, defaulting to progress enabled.
8. THE CLI SHALL accept `--disable-logs` / `--enable-logs` flags, defaulting to logs disabled.
9. WHEN the `--no-console` flag is provided on Windows, THE CLI SHALL re-launch itself as a new subprocess with the `CREATE_NO_WINDOW` flag and exit the current process.
10. WHEN the `--test` flag is provided, THE CLI SHALL use a hardcoded example input path and a target size of 15 MB if those values are not already specified.
11. WHEN `input` is not provided and `--test` is not specified, THE CLI SHALL exit with an error message indicating the required argument is missing.
12. WHEN `--max-mb` is not provided and `--test` is not specified, THE CLI SHALL exit with an error message indicating the required argument is missing.

### Requirement 12: Tkinter Desktop UI

**User Story:** As a non-technical user, I want a graphical interface to compress videos, so that I can use Morphix without knowing command-line syntax.

#### Acceptance Criteria

1. THE UI SHALL display an input file field with a Browse button that opens a file dialog filtered to common video formats (`.mp4`, `.mov`, `.mkv`, `.avi`, `.webm`).
2. THE UI SHALL display an output file field with a Browse button that opens a save-as dialog defaulting to `.mp4`.
3. WHEN an input file is selected and the output field is empty, THE UI SHALL automatically populate the output field with the input filename suffixed by `-morphix-compressed` before the extension.
4. THE UI SHALL display a target size field pre-populated with `20` and a unit selector defaulting to `MB`.
5. THE UI SHALL display a Compress button that initiates compression.
6. WHEN the Compress button is clicked and no input file is specified, THE UI SHALL display an error dialog.
7. WHEN the Compress button is clicked and no target size is specified, THE UI SHALL display an error dialog.
8. WHEN compression is running, THE UI SHALL disable all input controls and the Compress button.
9. WHEN compression is running, THE UI SHALL display a status label showing the current pass and percentage in the format `Pass 1/2: Analyzing video for bitrate data... X%` and `Pass 2/2: Encoding final output... X%`.
10. WHEN compression completes successfully, THE UI SHALL display `Done.` in the status label and re-enable all controls.
11. WHEN compression fails, THE UI SHALL display the error message in the status label and re-enable all controls.
12. THE UI SHALL display a device status label showing the detected device label (e.g. `Device: CPU`, `Device: NVIDIA GPU`, `Device: AMD GPU`, `Device: Intel GPU`) based on hardware detection at startup.
13. THE UI SHALL display a device selection dropdown populated by `get_available_devices()`, defaulting to the first entry (best available GPU, or CPU if none detected), so that the user can choose which device to use for hardware-accelerated decoding.
14. WHEN compression is running, THE UI SHALL disable the device selection dropdown along with all other input controls.
15. THE UI SHALL display an ffmpeg status label showing the ffmpeg source and version in the format `FFmpeg: bundled (Version: X.Y.Z)` or `FFmpeg: system PATH (Version: X.Y.Z)`, where the version string is retrieved by `get_ffmpeg_version(ffmpeg_path)`.
16. THE UI SHALL run compression in a background thread so that the UI remains responsive during encoding.
17. THE UI SHALL apply all UI updates from background threads via the Tkinter `after` mechanism to ensure thread safety.

### Requirement 13: Windows Explorer Context Menu Extension

**User Story:** As a Windows user, I want to right-click a video file in Explorer and quickly compress it to a configurable default size, so that I can run a headless compression without opening any application manually.

#### Acceptance Criteria

1. THE ContextMenu SHALL register as a Windows 11 top-level context menu entry via the `IExplorerCommand` COM interface.
2. THE ContextMenu SHALL display the menu label `Compress with Morphix`.
3. WHEN the menu item is invoked, THE ContextMenu SHALL read the user-configured default compression size from the persisted settings file (as defined in Requirement 20) and launch `Morphix.exe` with the selected file path as input and that size as the `--max-mb` argument, without displaying any dialog or prompt.
4. THE ContextMenu SHALL construct the output path by inserting `-morphix-compressed` before the file extension of the selected file.
5. THE ContextMenu SHALL launch `Morphix.exe` via `ShellExecuteExW` without blocking the Explorer process.
6. THE ContextMenu SHALL be built as a 64-bit COM DLL (`MorphixContextMenu.dll`) using MSVC.

### Requirement 14: MSIX Packaging and Installation

**User Story:** As a Windows user, I want to install Morphix as a packaged application, so that it integrates cleanly with the Windows app ecosystem.

#### Acceptance Criteria

1. THE Installer SHALL bundle the CLI EXE, UI EXE, and ContextMenu DLL into a single MSIX package.
2. THE Installer SHALL be signed with a code-signing certificate so that Windows allows installation via `Add-AppxPackage`.
3. WHEN the MSIX package is installed, THE Installer SHALL register the ContextMenu DLL as a COM server so that Windows Explorer loads it for context menu invocations.
4. THE Installer SHALL include application identity metadata (name, publisher, version) in `AppxManifest.xml`.
5. THE Installer SHALL include application logo assets at the sizes required by the MSIX manifest (`Square44x44Logo`, `Square150x150Logo`, `StoreLogo`).

### Requirement 15: UI Target Size Unit Selection

**User Story:** As a user, I want to enter the target file size in GB as well as MB, so that I can specify large target sizes without manual unit conversion.

#### Acceptance Criteria

1. THE UI SHALL display a unit selector adjacent to the target size field, offering `MB` and `GB` as options, defaulting to `MB`.
2. WHEN the user selects `GB`, THE UI SHALL accept the target size as a decimal number of gigabytes.
3. WHEN the Compress button is clicked, THE UI SHALL convert the entered size to megabytes before passing it to the Compressor, using the conversion `size_mb = size_value * 1000` for GB input.
4. THE Compressor SHALL always receive the target size in megabytes regardless of the unit selected in the UI.

### Requirement 16: Sensible Defaults and Ease of Use

**User Story:** As a non-power user, I want Morphix to work well with minimal configuration, so that I can compress a video by selecting a file and clicking Compress without understanding advanced options.

#### Acceptance Criteria

1. THE UI SHALL require only an input file selection and a Compress button click to perform a compression with all other settings at their defaults.
2. THE UI SHALL pre-populate all optional fields with sensible defaults: target size `20 MB`, unit `MB`, quality `medium`, output path derived from the input filename, and overwrite enabled.
3. WHILE advanced options are available in the UI, THE UI SHALL present them in a way that does not require interaction for the primary compression workflow.
4. THE CLI SHALL provide defaults for all optional arguments so that a minimal invocation requires only `--input` and `--max-mb`.
5. WHEN a user invokes the "Compress with Morphix" ContextMenu item, THE ContextMenu SHALL use the user-configured default compression size from the persisted settings (as defined in Requirement 20), falling back to `20` MB if no setting has been saved.

### Requirement 18: Standalone Windows Installer (Stretch Goal)

**User Story:** As a Windows user, I want to install Morphix using a familiar installer wizard, so that I do not need to manually run `Add-AppxPackage` or understand MSIX packaging.

#### Acceptance Criteria

1. THE Installer SHALL provide a standalone executable (e.g. `.exe` produced by a tool such as Inno Setup, NSIS, or WiX) that guides the user through installation without requiring PowerShell or developer tooling.
2. WHEN the installer runs, IT SHALL install the CLI EXE, UI EXE, and ContextMenu DLL to an appropriate location (e.g. `%ProgramFiles%\Morphix`).
3. WHEN the installer runs, IT SHALL register the ContextMenu COM server so that the Windows Explorer right-click entries are available immediately after installation.
4. THE Installer SHALL provide an uninstaller that removes all installed files and COM registrations.
5. This requirement is a stretch goal and SHALL NOT block the primary Windows MSIX-based release.

### Requirement 19: Cross-Platform Support (Stretch Goal)

**User Story:** As a user on Linux or Android, I want to use Morphix to compress videos on my platform, so that I am not limited to Windows.

#### Acceptance Criteria

1. THE `morphix_core/core.py` compression engine SHALL remain the single shared business logic layer across all platforms, with no platform-specific code embedded in it beyond OS-level subprocess flag handling already covered by Requirement 10.
2. THE Tkinter desktop UI (`morphix_ui/ui_app.py`) SHOULD run on Linux without modification, given that Tkinter is available on all major desktop platforms.
3. Platform-specific integration features (such as the Windows Explorer context menu) SHALL be implemented as separate, per-platform modules and SHALL NOT be required for the core compression functionality to work on other platforms.
4. WHEN porting to Linux, THE application SHALL support the same CLI interface defined in Requirement 11, with ffmpeg resolved from the system PATH when no bundled binary is present.
5. WHEN porting to Android, THE core compression logic SHALL be invocable from a platform-appropriate UI layer (e.g. a Kivy or BeeWare-based app), with `morphix_core/core.py` used as-is.
6. This requirement is a stretch goal and SHALL NOT block the primary Windows release. Cross-platform work SHALL begin only after a functional Windows version is complete.

### Requirement 17: Windows Explorer "Open in Morphix" Context Menu Entry

**User Story:** As a Windows user, I want to right-click a video file in Explorer and open it directly in the Morphix UI with the file pre-loaded, so that I can configure and run compression using the full graphical interface without manually browsing for the file.

#### Acceptance Criteria

1. THE ContextMenu SHALL register a second top-level Windows 11 context menu entry via the `IExplorerCommand` COM interface, separate from the "Compress with Morphix" entry defined in Requirement 13.
2. THE ContextMenu SHALL display the menu label `Open in Morphix` for this entry, making it immediately distinguishable from the `Compress with Morphix` entry at a glance.
3. WHEN the "Open in Morphix" entry is invoked, THE ContextMenu SHALL launch `Morphix_UI.exe` with the selected file path passed as a positional command-line argument.
4. THE UI SHALL accept an optional positional command-line argument specifying an input file path, and WHEN that argument is provided at launch, THE UI SHALL pre-populate the input file field with the supplied path.
5. THE ContextMenu SHALL register the "Open in Morphix" entry as a separate top-level item and SHALL NOT nest it under the "Compress with Morphix" entry.
6. THE ContextMenu SHALL launch `Morphix_UI.exe` via `ShellExecuteExW` or equivalent non-blocking mechanism so that Explorer is not blocked while the UI starts.
7. WHERE both `IExplorerCommand` implementations are packaged together, THE ContextMenu DLL MAY contain both implementations in a single DLL or they MAY be provided as separate DLLs; the packaging approach is left to the implementation.

### Requirement 20: Configurable Default Context Menu Compression Size

**User Story:** As a Windows user, I want to configure the default file size used by the "Compress with Morphix" context menu entry, so that I can set a target size that suits my typical use case without editing any files manually.

#### Acceptance Criteria

1. THE UI SHALL provide a settings section or settings window where the user can view and change the default compression size used by the "Compress with Morphix" context menu entry.
2. THE Settings SHALL default to `20` MB when no value has been previously saved.
3. WHEN the user enters a new default size, THE Settings SHALL accept any positive numeric value (e.g. `10`, `50`, `100`) in MB.
4. WHEN the user saves the settings, THE Settings SHALL persist the configured default size to a settings file on disk so that the value survives application restarts.
5. WHEN the "Compress with Morphix" context menu entry is invoked, THE ContextMenu SHALL read the persisted settings file and use the stored default size as the `--max-mb` argument passed to `Morphix.exe`.
6. IF the settings file does not exist or cannot be read, THEN THE ContextMenu SHALL fall back to a hardcoded default of `20` MB.
7. THE Settings SHALL store the configuration in a well-known, user-writable location (e.g. `%APPDATA%\Morphix\settings.json`) so that both the UI and the ContextMenu DLL can access it without elevated permissions.

### Requirement 21: Target Size Exceeds Input File Size Validation

**User Story:** As a user, I want to be warned if I try to compress a video to a size larger than the original file, so that I don't accidentally run a pointless or counterproductive operation.

#### Acceptance Criteria

1. WHEN the user initiates compression and the specified target size in MB is greater than or equal to the actual size of the input file in MB, THE UI SHALL display an error dialog (via `tkinter.messagebox.showerror`) with an appropriate message explaining that the target size is larger than or equal to the original file, and SHALL NOT proceed with compression.
2. WHEN the CLI is used and the specified `--max-mb` value is greater than or equal to the actual size of the input file in MB, THE CLI SHALL print an error message to stderr and exit with a non-zero exit code without running compression.
3. THE file size check SHALL be performed before any ffprobe or ffmpeg invocation.

### Requirement 22: Low Target Size Compression Warning

**User Story:** As a user, I want to be warned when my target size is so small relative to the original that the output quality will likely be unwatchable, so that I can make an informed decision before proceeding.

#### Acceptance Criteria

1. WHEN the specified target size is less than 3% of the original input file size, THE UI SHALL display a warning dialog (via `tkinter.messagebox.askokcancel` or equivalent) informing the user that the compression ratio is very high and the output will very likely look poor, recommending no lower than 5% of the original file size for a viewable result.
2. WHEN the user confirms the warning dialog, THE UI SHALL proceed with compression as normal.
3. WHEN the user cancels the warning dialog, THE UI SHALL abort compression and return to the ready state without any error.
4. WHEN the CLI is used and the target size is less than 3% of the input file size, THE CLI SHALL print a warning message to stderr and continue with compression (non-blocking — the CLI does not prompt interactively).
5. THE warning threshold SHALL be 3% of the original file size. The recommended minimum communicated to the user SHALL be 5% of the original file size.

### Requirement 23: Core Module Decomposition

**User Story:** As a developer, I want the codebase to be split into focused, single-responsibility modules so that I can quickly find and understand relevant code without reading through large monolithic files.

#### Acceptance Criteria

1. THE `morphix_core/` package SHALL be decomposed into focused submodules, each responsible for a single concern. At minimum the following submodules SHALL exist:
   - `morphix_core/ffmpeg_utils.py`: ffmpeg/ffprobe binary resolution, version detection, and subprocess invocation helpers
   - `morphix_core/gpu_detection.py`: all GPU/hardware acceleration detection logic (`detect_cuda`, AMD detection, Intel detection, `get_available_devices`, `resolve_device_info`)
   - `morphix_core/encoding.py`: two-pass encoding orchestration, progress parsing, passlog management, and error logging (the `RunContext` class and its methods)
   - `morphix_core/bitrate.py`: bitrate calculation, resolution scaling, and related math helpers (`target_kbps_for_size_mb`, `compute_scaled_resolution`, `clamp_even`, `parse_fps`)
   - `morphix_core/settings.py`: reading and writing `%APPDATA%\Morphix\settings.json`, including the fallback-to-20-MB logic
   - `morphix_core/validation.py`: input validation logic (target size vs file size check, low-ratio warning threshold calculation)
2. THE `morphix_core/core.py` entry point SHALL remain as the public API surface, re-exporting or delegating to the submodules so that existing callers (`cli.py`, `ui_app.py`) require no import changes.
3. ALL existing public functions and classes SHALL remain importable from `morphix_core.core` for backward compatibility.
4. EACH submodule SHALL contain only functions and classes directly related to its stated concern — cross-cutting imports between submodules are permitted but circular imports are not.
5. THE `morphix_ui/ui_app.py` SHALL be refactored to separate UI layout/widget construction from event handler logic, keeping each section clearly delineated with comments or by extracting helper methods.
