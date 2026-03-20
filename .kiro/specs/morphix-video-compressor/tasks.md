# Implementation Plan: Morphix Video Compressor

## Overview

Incremental implementation tasks covering the Python core, CLI, Tkinter UI, C++ ContextMenu DLL, and MSIX packaging. Each task builds on the previous, ending with full integration. Tests are co-located with the code they validate.

## Tasks

- [x] 1. Set up test infrastructure
  - Create `tests/` directory with `__init__.py` and `conftest.py`
  - Add `pytest` and `hypothesis` to `requirements.txt`
  - Configure hypothesis profile in `conftest.py` (`max_examples=100`, suppress `too_slow`)
  - _Requirements: all_

- [ ] 2. Core bitrate calculation
  - [ ] 2.1 Verify `target_kbps_for_size_mb` in `morphix_core/core.py`
    - Confirm formula: `max(int((size_mb * 1_000_000 * 8) / duration_s / 1000) - audio_kbps, 1)`
    - Ensure minimum clamp to 1 kbps is applied
    - _Requirements: 1.3, 1.4_

  - [ ]* 2.2 Write property test for bitrate formula (Property 1)
    - **Property 1: Bitrate formula and minimum clamp**
    - **Validates: Requirements 1.3, 1.4**
    - Use `floats(min_value=0.1, max_value=10000)` for `size_mb` and `duration_s`
    - Use `integers(min_value=0, max_value=512)` for `audio_kbps`

- [ ] 3. Output path resolution
  - [ ] 3.1 Verify `RunContext._resolve_output_path` in `morphix_core/core.py`
    - Confirm `_{size}mb` suffix is inserted before extension
    - Confirm `.mp4` fallback when input has no extension
    - Confirm explicit output path is left unchanged
    - Confirm output is placed in same directory as input
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [ ]* 3.2 Write property test for output path derivation (Property 2)
    - **Property 2: Output path derivation**
    - **Validates: Requirements 2.1, 2.2, 2.4**
    - Use `text` generators for filenames with extensions, `floats` for size

  - [ ]* 3.3 Write property test for explicit output path preservation (Property 3)
    - **Property 3: Explicit output path is preserved**
    - **Validates: Requirements 2.3**
    - Use `text` generators for both input and explicit output paths

- [ ] 4. Resolution scaling logic
  - [ ] 4.1 Verify `compute_scaled_resolution` and `clamp_even` in `morphix_core/core.py`
    - Confirm no scaling when current bpp >= target bpp threshold
    - Confirm proportional scaling formula when scaling is required
    - Confirm minimum height floor of 480 px
    - Confirm even-integer rounding via `clamp_even`
    - Confirm `None` returned when computed dimensions < 2 px
    - BPP thresholds: `low`=0.05, `medium`=0.07, `high`=0.10
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [ ]* 4.2 Write property test for no scaling when bpp is sufficient (Property 4)
    - **Property 4: No scaling when bpp is sufficient**
    - **Validates: Requirements 3.3**
    - Use `integers` for dimensions/fps, construct `video_bps` to exceed threshold

  - [ ]* 4.3 Write property test for scaled resolution satisfying target bpp (Property 5)
    - **Property 5: Scaled resolution satisfies target bpp**
    - **Validates: Requirements 3.4**
    - Use `integers` for dimensions/fps, construct `video_bps` below threshold

  - [ ]* 4.4 Write property test for minimum height floor (Property 6)
    - **Property 6: Minimum height floor is enforced**
    - **Validates: Requirements 3.5**
    - Use inputs that would scale below 480 px

  - [ ]* 4.5 Write property test for even dimensions (Property 7)
    - **Property 7: All computed dimensions are even integers**
    - **Validates: Requirements 3.6, 4.2**
    - Use `integers(min_value=-10000, max_value=10000)` for `clamp_even`
    - Also verify both width and height from `compute_scaled_resolution` are even

- [ ] 5. Manual resolution override
  - [ ] 5.1 Verify `RunContext._compute_scaling` manual override path in `morphix_core/core.py`
    - Confirm valid `WIDTHxHEIGHT` string sets `scale_filter = "scale=W:H"` with even-clamped values
    - Confirm invalid resolution string (non-numeric, missing `x`, dimensions < 2) leaves `scale_filter = None`
    - Confirm manual override bypasses auto-scaling logic entirely
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [ ]* 5.2 Write property test for manual resolution override applied (Property 8)
    - **Property 8: Manual resolution override is applied**
    - **Validates: Requirements 4.1**
    - Use `integers(min_value=2, max_value=7680)` for W and H

  - [ ]* 5.3 Write property test for invalid resolution producing no filter (Property 9)
    - **Property 9: Invalid resolution string produces no scale filter**
    - **Validates: Requirements 4.4, 4.3**
    - Use `text` excluding valid `WIDTHxHEIGHT` patterns

- [ ] 6. Hardware acceleration detection
  - [ ] 6.1 Verify `detect_cuda`, `detect_device_info` in `morphix_core/core.py`
    - Confirm NVIDIA detection via `nvidia-smi -L` exit code 0 with output → `cuda` / `NVIDIA GPU`
    - Confirm AMD fallback via `rocm-smi` or WMI query → `amf` / `AMD GPU`
    - Confirm Intel fallback via WMI or registry query → `qsv` / `Intel GPU`
    - Confirm CPU fallback when all vendor detections fail → `None` / `CPU`
    - Confirm per-vendor exceptions are caught and do not propagate
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

  - [ ]* 6.2 Write property test for GPU detection exceptions swallowed (Property 10)
    - **Property 10: GPU detection exceptions are swallowed**
    - **Validates: Requirements 5.7**
    - Mock each vendor detection step to raise arbitrary exceptions; assert `("CPU", None)` returned

- [ ] 7. ffmpeg binary resolution
  - [ ] 7.1 Verify `find_ffmpeg_binaries` in `morphix_core/core.py`
    - Confirm search order: `_MEIPASS`, Python executable directory, `ffmpeg/` relative to `core.py`
    - Confirm first candidate with both `ffmpeg.exe` and `ffprobe.exe` is returned with source `"bundled"`
    - Confirm fallback to `("ffmpeg", "ffprobe", "path")` when no candidate has both binaries
    - _Requirements: 6.1, 6.2, 6.3_

  - [ ]* 7.2 Write property test for binary resolution returning first valid candidate (Property 11)
    - **Property 11: Binary resolution returns first valid candidate**
    - **Validates: Requirements 6.1, 6.2, 6.3**
    - Mock filesystem with varying candidate layouts

- [ ] 8. Progress reporting
  - [ ] 8.1 Verify `RunContext._run_ffmpeg_with_progress` in `morphix_core/core.py`
    - Confirm `out_time_ms=N` lines are parsed from ffmpeg stderr
    - Confirm percentage is computed as `(elapsed_s / duration_s) * 100`
    - Confirm `progress_cb(percentage, phase)` is invoked with `"PASS1"` and `"PASS2"` labels
    - Confirm stdout fallback when `progress_cb` is `None` and progress is enabled
    - Confirm no stderr parsing when progress is disabled
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [ ]* 8.2 Write property test for progress parsing yielding correct seconds (Property 12)
    - **Property 12: Progress parsing yields correct seconds**
    - **Validates: Requirements 7.1, 7.3**
    - Use `integers(min_value=0, max_value=10**12)` for `out_time_ms` values

- [ ] 9. Two-pass log file management
  - [ ] 9.1 Verify `RunContext._prepare_logs` and `_cleanup_logs` in `morphix_core/core.py`
    - Confirm `.output/` subdirectory is created under input file's directory
    - Confirm `passlog_path` is set to a path under `.output/`
    - Confirm `.log` and `.log.mbtree` passlog files are deleted after Pass2
    - Confirm `.output/` directory is removed when empty after cleanup
    - Confirm missing passlog files during cleanup are silently skipped
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [ ]* 9.2 Write property test for passlog path under `.output/` subdirectory (Property 13)
    - **Property 13: Passlog path is under `.output/` subdirectory**
    - **Validates: Requirements 8.1**
    - Use `text` for input paths

  - [ ]* 9.3 Write property test for empty `.output/` directory removed after cleanup (Property 14)
    - **Property 14: Empty `.output/` directory is removed after cleanup**
    - **Validates: Requirements 8.3**
    - Use temp directory with only passlog files

- [ ] 10. ffmpeg error logging
  - [ ] 10.1 Verify `RunContext._write_ffmpeg_error` in `morphix_core/core.py`
    - Confirm stderr bytes are written to `.output/ffmpeg-error.log`
    - Confirm fallback message `"No stderr captured from ffmpeg.\n"` when stderr is `None` or empty
    - Confirm error log path is printed to stdout
    - Confirm exception is re-raised after writing the log
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [ ]* 10.2 Write property test for ffmpeg error log content (Property 15)
    - **Property 15: ffmpeg error log is written with correct content**
    - **Validates: Requirements 9.1, 9.2**
    - Use `binary` for stderr, `None` for missing case

  - [ ]* 10.3 Write property test for exception re-raised after logging (Property 16)
    - **Property 16: ffmpeg exception is re-raised after logging**
    - **Validates: Requirements 9.4**
    - Assert any `ffmpeg.Error` passed to `_write_ffmpeg_error` propagates from `_run_ffmpeg`

- [ ] 11. Console window suppression
  - [ ] 11.1 Verify `popen_no_window_kwargs` in `morphix_core/core.py`
    - Confirm `{"creationflags": subprocess.CREATE_NO_WINDOW}` returned when `os.name == "nt"`
    - Confirm `{"start_new_session": True}` returned when `os.name != "nt"`
    - Confirm all ffmpeg and ffprobe `Popen` calls use these kwargs
    - _Requirements: 10.1, 10.2_

  - [ ]* 11.2 Write property test for subprocess flags matching OS (Property 17)
    - **Property 17: Subprocess flags match OS**
    - **Validates: Requirements 10.1, 10.2**
    - Parameterize by mocking `os.name` to `"nt"` and non-`"nt"` values

- [ ] 12. Checkpoint — core complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 13. CLI interface
  - [ ] 13.1 Verify argument definitions in `morphix_core/cli_args.py`
    - Confirm positional `input` argument
    - Confirm `--max-mb` float argument
    - Confirm `--output`, `--quality` (choices: low/medium/high, default: medium), `--resolution`
    - Confirm `--overwrite`/`--no-overwrite` flags (default: overwrite)
    - Confirm `--progress`/`--no-progress` flags (default: progress)
    - Confirm `--disable-logs`/`--enable-logs` flags (default: disable)
    - Confirm `--no-console` flag re-launches with `CREATE_NO_WINDOW` on Windows
    - Confirm `--test` flag sets hardcoded input path and 15 MB target
    - Confirm error when `input` missing and `--test` not set
    - Confirm error when `--max-mb` missing and `--test` not set
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 11.9, 11.10, 11.11, 11.12_

  - [ ]* 13.2 Write unit tests for CLI argument parsing
    - Test each argument with specific valid and invalid combinations via `parse_args`
    - Test `--test` flag defaults, `--no-console` re-launch path (mocked subprocess)
    - _Requirements: 11.1–11.12_

- [ ] 14. Tkinter UI updates
  - [ ] 14.1 Verify unit selector (MB/GB) in `morphix_ui/ui_app.py`
    - Confirm `OptionMenu` or equivalent widget adjacent to target size field offers `MB` and `GB`
    - Confirm default selection is `MB`
    - Confirm GB input is converted using `size_mb = size_value * 1000` before calling `run()`
    - _Requirements: 15.1, 15.2, 15.3, 15.4_

  - [ ]* 14.2 Write property test for GB-to-MB conversion (Property 18)
    - **Property 18: GB-to-MB conversion**
    - **Validates: Requirements 15.3, 15.4**
    - Use `floats(min_value=0.001, max_value=1000)` for GB input values

  - [ ] 14.3 Verify pre-fill from CLI argument in `morphix_ui/ui_app.py`
    - Confirm `MorphixUI` accepts an optional positional CLI argument for input file path
    - Confirm input file field is pre-populated when argument is provided at launch
    - _Requirements: 17.4_

  - [ ] 14.4 Verify multi-vendor device label in `morphix_ui/ui_app.py`
    - Confirm device status label displays `Device: NVIDIA GPU`, `Device: AMD GPU`, `Device: Intel GPU`, or `Device: CPU`
    - Confirm label is populated from `detect_device_info()` at startup
    - _Requirements: 12.12_

  - [ ]* 14.5 Write unit tests for UI controls and state
    - Test target size field pre-populated with `20`, unit selector defaults to `MB`
    - Test error dialog when input file missing, error dialog when target size missing
    - Test output field auto-populated from input filename with `-morphix-compressed` suffix
    - Test controls disabled during compression, re-enabled on completion and error
    - _Requirements: 12.1–12.15, 16.1–16.4_

- [ ] 15. Context menu — "Compress with Morphix"
  - [ ] 15.1 Verify `MorphixExplorerCommand` in `ContextMenuWrl/MorphixExplorerCommand.cpp`
    - Confirm `IExplorerCommand` registration as top-level Windows 11 context menu entry
    - Confirm menu label is `Compress with Morphix`
    - Confirm native input dialog is displayed pre-populated with `20`
    - Confirm `Morphix.exe` is launched via `ShellExecuteExW` with `--max-mb <value>` and `--output <path>` on confirm
    - Confirm nothing is launched on cancel
    - Confirm output path inserts `-morphix-compressed` before file extension
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8_

- [ ] 16. Context menu — "Open in Morphix"
  - [ ] 16.1 Verify `MorphixOpenCommand` in `ContextMenuWrl/MorphixExplorerCommand.cpp`
    - Confirm second top-level `IExplorerCommand` entry registered separately from "Compress with Morphix"
    - Confirm menu label is `Open in Morphix`
    - Confirm `Morphix_UI.exe` is launched via `ShellExecuteExW` with selected file path as positional argument
    - Confirm Explorer is not blocked (non-blocking launch)
    - _Requirements: 17.1, 17.2, 17.3, 17.5, 17.6, 17.7_

- [ ] 17. MSIX packaging updates
  - [ ] 17.1 Verify `msix/AppxManifest.xml`
    - Confirm package identity metadata (name, publisher, version) is present
    - Confirm COM server registration for `MorphixContextMenu.dll` covers both `MorphixExplorerCommand` and `MorphixOpenCommand` CLSIDs
    - Confirm both context menu entries are declared as separate top-level `IExplorerCommand` extensions
    - Confirm logo assets are referenced at required sizes (`Square44x44Logo`, `Square150x150Logo`, `StoreLogo`)
    - _Requirements: 14.1, 14.3, 14.4, 14.5_

  - [ ] 17.2 Verify `scripts/build_msix.ps1`
    - Confirm script bundles CLI EXE, UI EXE, and ContextMenu DLL into the MSIX package
    - Confirm signing step is present for `Add-AppxPackage` compatibility
    - _Requirements: 14.1, 14.2_

- [ ] 18. Integration tests
  - [ ]* 18.1 Write integration tests against a real short video file
    - Tag tests with `@pytest.mark.integration` for optional exclusion from fast runs
    - Test: output file created at expected path after compression
    - Test: output file size is within 10% of target size
    - Test: output file is a valid MP4 (ffprobe exits 0)
    - Test: passlog files are cleaned up after successful compression
    - _Requirements: 1.1, 1.5, 1.6, 8.2, 8.3_

- [ ] 19. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties (Properties 1–18 from design doc)
- Unit tests validate specific examples and edge cases
- Integration tests require ffmpeg available on PATH or bundled and are excluded from fast runs via `pytest -m "not integration"`
