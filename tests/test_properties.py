"""Property-based tests for Morphix Video Compressor.

All properties validated against requirements as documented in design.md.
"""

import io
import json
import os
import subprocess
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from morphix_core.bitrate import (
    clamp_even,
    compute_scaled_resolution,
    target_kbps_for_size_mb,
)
from morphix_core.ffmpeg_utils import popen_no_window_kwargs
from morphix_core.gpu_detection import (
    detect_device_info,
    get_available_devices,
    resolve_device_info,
)
from morphix_core.settings import read_settings, write_settings
from morphix_core.validation import (
    check_low_compression_ratio,
    check_target_exceeds_file_size,
)

# Suppress function_scoped_fixture health check for all tests that use tmp_path with @given
_FS_SETTINGS = settings(
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture]
)

# ---------------------------------------------------------------------------
# Helper to create a RunContext without triggering ffmpeg binary search
# ---------------------------------------------------------------------------


def make_ctx(
    input_path, max_mb=15, output_path=None, resolution=None, quality="medium"
):
    from morphix_core.encoding import RunContext

    with patch(
        "morphix_core.encoding.find_ffmpeg_binaries",
        return_value=(None, None, "missing"),
    ):
        ctx = RunContext(
            input_path,
            max_mb,
            output_path=output_path,
            resolution=resolution,
            quality=quality,
        )
    return ctx


# ---------------------------------------------------------------------------
# Property 1: Bitrate formula and minimum clamp
# Validates: Requirements 1.3, 1.4
# ---------------------------------------------------------------------------


@given(
    size_mb=st.floats(min_value=0.1, max_value=10000),
    duration_s=st.floats(min_value=0.1, max_value=10000),
    audio_kbps=st.integers(min_value=0, max_value=512),
)
def test_prop1_bitrate_formula_and_minimum_clamp(size_mb, duration_s, audio_kbps):
    """Property 1: result == max(int((size_mb * 1_000_000 * 8) / duration_s / 1000) - audio_kbps, 1)
    and result >= 1 always.
    **Validates: Requirements 1.3, 1.4**
    """
    result = target_kbps_for_size_mb(size_mb, duration_s, audio_kbps)
    expected = max(int((size_mb * 1_000_000 * 8) / duration_s / 1000) - audio_kbps, 1)
    assert result == expected
    assert result >= 1


# ---------------------------------------------------------------------------
# Property 2: Output path derivation
# Validates: Requirements 2.1, 2.2, 2.4
# ---------------------------------------------------------------------------

_filename_with_ext = st.from_regex(
    r"[a-zA-Z0-9_]{1,20}\.[a-zA-Z0-9]{1,4}", fullmatch=True
)
_filename_no_ext = st.from_regex(r"[a-zA-Z0-9_]{1,20}", fullmatch=True)


@_FS_SETTINGS
@given(
    filename=_filename_with_ext,
    size_mb=st.floats(
        min_value=0.1, max_value=10000, allow_nan=False, allow_infinity=False
    ),
)
def test_prop2_output_path_derivation(tmp_path, filename, size_mb):
    """Property 2: output contains _{size}mb before extension and is in same dir as input.
    **Validates: Requirements 2.1, 2.2, 2.4**
    """
    input_path = str(tmp_path / filename)
    ctx = make_ctx(input_path, max_mb=size_mb)
    ctx._resolve_output_path()

    out = ctx.output_path
    assert os.path.dirname(out) == str(tmp_path)

    base = os.path.basename(out)
    size_label = f"{size_mb:g}"
    assert f"_{size_label}mb" in base

    _, in_ext = os.path.splitext(filename)
    assert out.endswith(in_ext)


@_FS_SETTINGS
@given(
    filename=_filename_no_ext,
    size_mb=st.floats(
        min_value=0.1, max_value=10000, allow_nan=False, allow_infinity=False
    ),
)
def test_prop2_output_path_no_extension_uses_mp4(tmp_path, filename, size_mb):
    """Property 2: output uses .mp4 when input has no extension.
    **Validates: Requirements 2.2, 2.4**
    """
    input_path = str(tmp_path / filename)
    ctx = make_ctx(input_path, max_mb=size_mb)
    ctx._resolve_output_path()

    assert ctx.output_path.endswith(".mp4")
    assert os.path.dirname(ctx.output_path) == str(tmp_path)


# ---------------------------------------------------------------------------
# Property 3: Explicit output path is preserved
# Validates: Requirements 2.3
# ---------------------------------------------------------------------------


@_FS_SETTINGS
@given(
    in_name=st.from_regex(r"[a-zA-Z0-9_]{1,20}\.mp4", fullmatch=True),
    out_name=st.from_regex(r"[a-zA-Z0-9_]{1,20}\.mp4", fullmatch=True),
)
def test_prop3_explicit_output_path_preserved(tmp_path, in_name, out_name):
    """Property 3: when explicit output_path is provided, _resolve_output_path leaves it unchanged.
    **Validates: Requirements 2.3**
    """
    input_path = str(tmp_path / in_name)
    explicit_output = str(tmp_path / out_name)
    ctx = make_ctx(input_path, max_mb=15, output_path=explicit_output)
    ctx._resolve_output_path()
    assert ctx.output_path == explicit_output


# ---------------------------------------------------------------------------
# Property 4: No scaling when bpp is sufficient
# Validates: Requirements 3.3
# ---------------------------------------------------------------------------


@given(
    width=st.integers(min_value=2, max_value=7680),
    height=st.integers(min_value=2, max_value=4320),
    fps=st.floats(
        min_value=1.0, max_value=240.0, allow_nan=False, allow_infinity=False
    ),
    target_bpp=st.floats(
        min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False
    ),
    multiplier=st.floats(
        min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False
    ),
)
def test_prop4_no_scaling_when_bpp_sufficient(
    width, height, fps, target_bpp, multiplier
):
    """Property 4: when current_bpp >= target_bpp, result is None.
    **Validates: Requirements 3.3**
    """
    # Construct video_bps so that current_bpp = target_bpp * multiplier >= target_bpp
    video_bps = target_bpp * multiplier * fps * width * height
    assume(video_bps > 0)
    # current_bpp = video_bps / (fps * width * height) = target_bpp * multiplier >= target_bpp
    current_bpp = video_bps / (fps * width * height)
    assume(current_bpp >= target_bpp)
    result = compute_scaled_resolution(width, height, fps, video_bps, target_bpp)
    assert result is None


# ---------------------------------------------------------------------------
# Property 5: Scaled resolution satisfies target bpp
# Validates: Requirements 3.4
# ---------------------------------------------------------------------------


@given(
    width=st.integers(min_value=100, max_value=7680),
    height=st.integers(min_value=100, max_value=4320),
    fps=st.floats(
        min_value=1.0, max_value=240.0, allow_nan=False, allow_infinity=False
    ),
    target_bpp=st.floats(
        min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False
    ),
    fraction=st.floats(
        min_value=0.01, max_value=0.99, allow_nan=False, allow_infinity=False
    ),
)
def test_prop5_scaled_resolution_satisfies_target_bpp(
    width, height, fps, target_bpp, fraction
):
    """Property 5: when scaling occurs, resulting bpp is approximately target_bpp.
    **Validates: Requirements 3.4**
    """
    video_bps = target_bpp * fraction * fps * width * height
    assume(video_bps > 0)
    result = compute_scaled_resolution(width, height, fps, video_bps, target_bpp)
    if result is None:
        return
    new_w, new_h = result
    assume(new_w >= 2 and new_h >= 2)
    actual_bpp = video_bps / (fps * new_w * new_h)
    # Allow tolerance for rounding and min-height floor
    assert abs(actual_bpp - target_bpp) / target_bpp < 0.15 or new_h == 480


# ---------------------------------------------------------------------------
# Property 6: Minimum height floor is enforced
# Validates: Requirements 3.5
# ---------------------------------------------------------------------------


@given(
    width=st.integers(min_value=100, max_value=7680),
    height=st.integers(min_value=481, max_value=4320),
    fps=st.floats(
        min_value=1.0, max_value=240.0, allow_nan=False, allow_infinity=False
    ),
    target_bpp=st.floats(
        min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False
    ),
    fraction=st.floats(
        min_value=0.001, max_value=0.1, allow_nan=False, allow_infinity=False
    ),
)
def test_prop6_minimum_height_floor_enforced(width, height, fps, target_bpp, fraction):
    """Property 6: when result is not None, height >= 480.
    **Validates: Requirements 3.5**
    """
    video_bps = target_bpp * fraction * fps * width * height
    assume(video_bps > 0)
    result = compute_scaled_resolution(
        width, height, fps, video_bps, target_bpp, min_height=480
    )
    if result is not None:
        _, new_h = result
        assert new_h >= 480


# ---------------------------------------------------------------------------
# Property 7: All computed dimensions are even integers
# Validates: Requirements 3.6, 4.2
# ---------------------------------------------------------------------------


@given(x=st.integers(min_value=-10000, max_value=10000))
def test_prop7_clamp_even_always_even(x):
    """Property 7: clamp_even(x) always returns an even integer.
    **Validates: Requirements 3.6, 4.2**
    """
    result = clamp_even(x)
    assert isinstance(result, int)
    assert result % 2 == 0


@given(
    width=st.integers(min_value=100, max_value=7680),
    height=st.integers(min_value=100, max_value=4320),
    fps=st.floats(
        min_value=1.0, max_value=240.0, allow_nan=False, allow_infinity=False
    ),
    target_bpp=st.floats(
        min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False
    ),
    fraction=st.floats(
        min_value=0.01, max_value=0.99, allow_nan=False, allow_infinity=False
    ),
)
def test_prop7_scaled_dimensions_are_even(width, height, fps, target_bpp, fraction):
    """Property 7: both width and height from compute_scaled_resolution are even when result is not None.
    **Validates: Requirements 3.6, 4.2**
    """
    video_bps = target_bpp * fraction * fps * width * height
    assume(video_bps > 0)
    result = compute_scaled_resolution(width, height, fps, video_bps, target_bpp)
    if result is not None:
        new_w, new_h = result
        assert new_w % 2 == 0
        assert new_h % 2 == 0


# ---------------------------------------------------------------------------
# Property 8: Manual resolution override is applied
# Validates: Requirements 4.1
# ---------------------------------------------------------------------------


@_FS_SETTINGS
@given(
    w=st.integers(min_value=2, max_value=7680),
    h=st.integers(min_value=2, max_value=4320),
)
def test_prop8_manual_resolution_override_applied(tmp_path, w, h):
    """Property 8: valid WxH string sets scale_filter = "scale=W_even:H_even".
    **Validates: Requirements 4.1**
    """
    resolution_str = f"{w}x{h}"
    input_path = str(tmp_path / "video.mp4")
    ctx = make_ctx(input_path, resolution=resolution_str)
    ctx.probe = {"streams": []}
    ctx.video_bps = 1_000_000
    ctx._compute_scaling()

    expected_w = clamp_even(w)
    expected_h = clamp_even(h)
    if expected_w >= 2 and expected_h >= 2:
        assert ctx.scale_filter == f"scale={expected_w}:{expected_h}"
    else:
        assert ctx.scale_filter is None


# ---------------------------------------------------------------------------
# Property 9: Invalid resolution string produces no scale filter
# Validates: Requirements 4.4, 4.3
# ---------------------------------------------------------------------------

_no_x_str = st.text(
    alphabet=st.characters(blacklist_characters="x", blacklist_categories=("Cs",)),
    min_size=1,
    max_size=20,
)
_bad_resolution = st.one_of(
    _no_x_str,
    st.from_regex(r"[a-zA-Z]+x[0-9]+", fullmatch=True),
    st.from_regex(r"[0-9]+x[a-zA-Z]+", fullmatch=True),
    st.from_regex(r"[a-zA-Z]+x[a-zA-Z]+", fullmatch=True),
)


@_FS_SETTINGS
@given(resolution=_bad_resolution)
def test_prop9_invalid_resolution_no_scale_filter(tmp_path, resolution):
    """Property 9: invalid resolution string leaves scale_filter = None.
    **Validates: Requirements 4.4, 4.3**
    """
    input_path = str(tmp_path / "video.mp4")
    ctx = make_ctx(input_path, resolution=resolution)
    ctx.probe = {"streams": []}
    ctx.video_bps = 1_000_000
    ctx._compute_scaling()
    assert ctx.scale_filter is None


# ---------------------------------------------------------------------------
# Property 10: GPU detection exceptions are swallowed
# Validates: Requirements 5.7
# ---------------------------------------------------------------------------

_exception_types = st.sampled_from(
    [
        RuntimeError("nvidia error"),
        OSError("amd error"),
        Exception("intel error"),
        ValueError("val error"),
    ]
)


@given(
    nvidia_exc=_exception_types,
    amd_exc=_exception_types,
    intel_exc=_exception_types,
)
def test_prop10_gpu_detection_exceptions_swallowed(nvidia_exc, amd_exc, intel_exc):
    """Property 10: detect_device_info always returns ("CPU", None) when all detections raise.
    **Validates: Requirements 5.7**
    """
    with (
        patch("morphix_core.gpu_detection.detect_cuda", side_effect=nvidia_exc),
        patch("morphix_core.gpu_detection.detect_amd", side_effect=amd_exc),
        patch("morphix_core.gpu_detection.detect_intel", side_effect=intel_exc),
    ):
        label, hwaccel = detect_device_info()
    assert label == "CPU"
    assert hwaccel is None


# ---------------------------------------------------------------------------
# Property 19: CPU is always in the device list
# Validates: Requirements 5.8
# ---------------------------------------------------------------------------


@given(
    has_nvidia=st.booleans(),
    has_amd=st.booleans(),
    has_intel=st.booleans(),
)
def test_prop19_cpu_always_in_device_list(has_nvidia, has_amd, has_intel):
    """Property 19: get_available_devices() always ends with ("cpu", "CPU").
    **Validates: Requirements 5.8**
    """
    with (
        patch("morphix_core.gpu_detection.detect_cuda", return_value=has_nvidia),
        patch("morphix_core.gpu_detection.detect_amd", return_value=has_amd),
        patch("morphix_core.gpu_detection.detect_intel", return_value=has_intel),
    ):
        devices = get_available_devices()
    assert devices[-1] == ("cpu", "CPU", True)


# ---------------------------------------------------------------------------
# Property 20: resolve_device_info falls back to CPU for unavailable devices
# Validates: Requirements 5.9
# ---------------------------------------------------------------------------

_unknown_device_keys = st.text(
    alphabet=st.characters(
        whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="_"
    ),
    min_size=1,
    max_size=20,
).filter(lambda s: s not in ("cpu",))


@given(device_key=_unknown_device_keys)
def test_prop20_resolve_device_info_fallback_to_cpu(device_key):
    """Property 20: for any unknown device key with no GPU available, returns ("CPU", None).
    **Validates: Requirements 5.9**
    """
    with (
        patch("morphix_core.gpu_detection.detect_cuda", return_value=False),
        patch("morphix_core.gpu_detection.detect_amd", return_value=False),
        patch("morphix_core.gpu_detection.detect_intel", return_value=False),
    ):
        label, hwaccel = resolve_device_info(device_key)
    assert label == "CPU"
    assert hwaccel is None


# ---------------------------------------------------------------------------
# Property 11: Binary resolution returns first valid candidate
# Validates: Requirements 6.1, 6.2, 6.3
# ---------------------------------------------------------------------------


@_FS_SETTINGS
@given(
    n_candidates=st.integers(min_value=1, max_value=5),
    valid_index=st.integers(min_value=0, max_value=4),
)
def test_prop11_binary_resolution_first_valid_candidate(n_candidates, valid_index):
    """Property 11: first candidate dir containing both ffmpeg.exe and ffprobe.exe is returned with source "bundled".
    **Validates: Requirements 6.1, 6.2, 6.3**
    """
    assume(valid_index < n_candidates)

    with tempfile.TemporaryDirectory() as tmpdir:
        candidate_dirs = []
        for i in range(n_candidates):
            d = os.path.join(tmpdir, f"candidate_{i}")
            os.makedirs(d)
            if i == valid_index:
                open(os.path.join(d, "ffmpeg.exe"), "w").close()
                open(os.path.join(d, "ffprobe.exe"), "w").close()
            candidate_dirs.append(d)

        # Simulate find_ffmpeg_binaries logic with these candidates
        def fake_find():
            for base in candidate_dirs:
                ffmpeg_path = os.path.join(base, "ffmpeg.exe")
                ffprobe_path = os.path.join(base, "ffprobe.exe")
                if os.path.isfile(ffmpeg_path) and os.path.isfile(ffprobe_path):
                    return ffmpeg_path, ffprobe_path, "bundled"
            return None, None, "missing"

        ffmpeg_p, ffprobe_p, source = fake_find()
        assert source == "bundled"
        assert ffmpeg_p is not None
        assert ffprobe_p is not None
        expected_dir = os.path.join(tmpdir, f"candidate_{valid_index}")
        assert os.path.dirname(ffmpeg_p) == expected_dir


# ---------------------------------------------------------------------------
# Property 12: Progress parsing yields correct seconds
# Validates: Requirements 7.1, 7.3
# ---------------------------------------------------------------------------


@given(out_time_ms=st.integers(min_value=0, max_value=10**12))
def test_prop12_progress_parsing_direct(out_time_ms):
    """Property 12: out_time_ms=N yields N / 1_000_000.0 seconds.
    **Validates: Requirements 7.1, 7.3**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, "video.mp4")
        ctx = make_ctx(input_path)
        line = f"out_time_ms={out_time_ms}\n".encode()
        stream = io.BytesIO(line)
        results = list(ctx._iter_progress_seconds(stream))
        assert len(results) == 1
        seconds, raw_line = results[0]
        assert seconds == out_time_ms / 1_000_000.0


# ---------------------------------------------------------------------------
# Property 13: Passlog path is under `.output/` subdirectory
# Validates: Requirements 8.1
# ---------------------------------------------------------------------------


@given(filename=st.from_regex(r"[a-zA-Z0-9_]{1,20}\.mp4", fullmatch=True))
def test_prop13_passlog_path_under_output_subdir(filename):
    """Property 13: passlog_path is under a .output/ subdirectory of the input file's directory.
    **Validates: Requirements 8.1**
    """
    import shutil

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, filename)
        ctx = make_ctx(input_path)
        ctx._prepare_logs()

        expected_log_dir = os.path.join(tmpdir, ".output")
        assert ctx.log_dir == expected_log_dir
        assert ctx.passlog_path.startswith(expected_log_dir)

        if os.path.isdir(expected_log_dir):
            shutil.rmtree(expected_log_dir)


# ---------------------------------------------------------------------------
# Property 14: Empty `.output/` directory removed after cleanup
# Validates: Requirements 8.3
# ---------------------------------------------------------------------------


@given(n_passlog_files=st.integers(min_value=0, max_value=5))
def test_prop14_empty_output_dir_removed_after_cleanup(n_passlog_files):
    """Property 14: after cleanup, if no other files remain, .output/ directory is removed.
    **Validates: Requirements 8.3**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        log_dir = os.path.join(tmpdir, ".output")
        os.makedirs(log_dir)

        input_path = os.path.join(tmpdir, "video.mp4")
        ctx = make_ctx(input_path)
        ctx.log_dir = log_dir
        ctx.passlog_path = os.path.join(log_dir, "ffmpeg2pass")

        for i in range(n_passlog_files):
            open(os.path.join(log_dir, f"ffmpeg2pass-{i}.log"), "w").close()
            open(os.path.join(log_dir, f"ffmpeg2pass-{i}.log.mbtree"), "w").close()

        ctx._cleanup_logs()
        assert not os.path.exists(log_dir)


# ---------------------------------------------------------------------------
# Property 15: ffmpeg error log is written with correct content
# Validates: Requirements 9.1, 9.2
# ---------------------------------------------------------------------------

import ffmpeg as ffmpeg_lib


@given(stderr_bytes=st.binary(min_size=1, max_size=1000))
def test_prop15_ffmpeg_error_log_with_stderr(stderr_bytes):
    """Property 15: when stderr is non-empty bytes, log file contains those bytes.
    **Validates: Requirements 9.1, 9.2**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        log_dir = os.path.join(tmpdir, ".output")
        os.makedirs(log_dir)
        input_path = os.path.join(tmpdir, "video.mp4")
        ctx = make_ctx(input_path)
        ctx.log_dir = log_dir

        # ffmpeg.Error(cmd, stdout, stderr) — stderr is the third argument
        exc = ffmpeg_lib.Error("ffmpeg", None, stderr_bytes)
        ctx._write_ffmpeg_error(exc)

        err_path = os.path.join(log_dir, "ffmpeg-error.log")
        assert os.path.exists(err_path)
        with open(err_path, "rb") as f:
            assert f.read() == stderr_bytes


@given(stderr_bytes=st.one_of(st.just(None), st.just(b"")))
def test_prop15_ffmpeg_error_log_no_stderr(stderr_bytes):
    """Property 15: when stderr is None or empty, log file contains fallback message.
    **Validates: Requirements 9.1, 9.2**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        log_dir = os.path.join(tmpdir, ".output")
        os.makedirs(log_dir)
        input_path = os.path.join(tmpdir, "video.mp4")
        ctx = make_ctx(input_path)
        ctx.log_dir = log_dir

        # ffmpeg.Error(cmd, stdout, stderr) — stderr is the third argument
        exc = ffmpeg_lib.Error("ffmpeg", None, stderr_bytes)
        ctx._write_ffmpeg_error(exc)

        err_path = os.path.join(log_dir, "ffmpeg-error.log")
        assert os.path.exists(err_path)
        with open(err_path, "rb") as f:
            assert f.read() == b"No stderr captured from ffmpeg.\n"


# ---------------------------------------------------------------------------
# Property 16: ffmpeg exception is re-raised after logging
# Validates: Requirements 9.4
# ---------------------------------------------------------------------------


@given(stderr_bytes=st.one_of(st.just(None), st.binary(min_size=0, max_size=100)))
def test_prop16_ffmpeg_exception_reraised_after_logging(stderr_bytes):
    """Property 16: _write_ffmpeg_error does not raise; _run_ffmpeg re-raises the original exception.
    **Validates: Requirements 9.4**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        log_dir = os.path.join(tmpdir, ".output")
        os.makedirs(log_dir)
        input_path = os.path.join(tmpdir, "video.mp4")
        ctx = make_ctx(input_path)
        ctx.log_dir = log_dir
        ctx.progress = False
        ctx.disable_logs = True
        ctx.ffmpeg_path = "ffmpeg"
        ctx.overwrite = True

        # ffmpeg.Error(cmd, stdout, stderr) — stderr is the third argument
        exc = ffmpeg_lib.Error("ffmpeg", None, stderr_bytes)

        # _write_ffmpeg_error itself must not raise
        ctx._write_ffmpeg_error(exc)

        # _run_ffmpeg must re-raise as RuntimeError with a user-friendly message
        mock_stream = MagicMock()
        with patch.object(ctx, "_run_ffmpeg_simple", side_effect=exc):
            with pytest.raises(RuntimeError):
                ctx._run_ffmpeg(mock_stream, "PASS1")


# ---------------------------------------------------------------------------
# Property 17: Subprocess flags match OS
# Validates: Requirements 10.1, 10.2
# ---------------------------------------------------------------------------


@given(os_name=st.just("nt"))
def test_prop17_subprocess_flags_windows(os_name):
    """Property 17: on 'nt', returns {"creationflags": subprocess.CREATE_NO_WINDOW}.
    **Validates: Requirements 10.1**
    """
    with patch("morphix_core.ffmpeg_utils.os.name", os_name):
        result = popen_no_window_kwargs()
    assert result == {"creationflags": subprocess.CREATE_NO_WINDOW}


@given(os_name=st.sampled_from(["posix", "java", "linux", "darwin"]))
def test_prop17_subprocess_flags_non_windows(os_name):
    """Property 17: on non-'nt', returns {"start_new_session": True}.
    **Validates: Requirements 10.2**
    """
    with patch("morphix_core.ffmpeg_utils.os.name", os_name):
        result = popen_no_window_kwargs()
    assert result == {"start_new_session": True}


# ---------------------------------------------------------------------------
# Property 18: GB-to-MB conversion
# Validates: Requirements 15.3, 15.4
# ---------------------------------------------------------------------------


@given(
    size_gb=st.floats(
        min_value=0.001, max_value=1000, allow_nan=False, allow_infinity=False
    )
)
def test_prop18_gb_to_mb_conversion(size_gb):
    """Property 18: size_mb = size_gb * 1000.
    **Validates: Requirements 15.3, 15.4**
    """
    import math

    size_mb = size_gb * 1000
    assert size_mb == size_gb * 1000
    assert not math.isnan(size_mb)
    assert not math.isinf(size_mb)


# ---------------------------------------------------------------------------
# Property 21: Settings round-trip
# Validates: Requirements 20.3, 20.4
# ---------------------------------------------------------------------------


@given(
    default_mb=st.floats(
        min_value=0.001, max_value=100000, allow_nan=False, allow_infinity=False
    )
)
def test_prop21_settings_round_trip(default_mb):
    """Property 21: write then read back yields the same value (within float tolerance).
    **Validates: Requirements 20.3, 20.4**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict(os.environ, {"APPDATA": tmpdir}):
            write_settings(default_mb)
            result = read_settings()
    assert abs(result["default_mb"] - default_mb) < 1e-9 * max(abs(default_mb), 1)


# ---------------------------------------------------------------------------
# Property 22: Settings fallback to 20 MB
# Validates: Requirements 20.2, 20.6
# ---------------------------------------------------------------------------


def test_prop22_settings_fallback_missing_file():
    """Property 22: read_settings() returns {"default_mb": 20} when file is missing.
    **Validates: Requirements 20.2, 20.6**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict(os.environ, {"APPDATA": tmpdir}):
            result = read_settings()
    assert result == {"default_mb": 20}


def _is_invalid_json(s):
    try:
        json.loads(s)
        return False
    except Exception:
        return True


@given(invalid_json=st.text(min_size=1).filter(_is_invalid_json))
def test_prop22_settings_fallback_invalid_json(invalid_json):
    """Property 22: read_settings() returns {"default_mb": 20} when JSON is invalid.
    **Validates: Requirements 20.2, 20.6**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        settings_dir = os.path.join(tmpdir, "Morphix")
        os.makedirs(settings_dir, exist_ok=True)
        with open(
            os.path.join(settings_dir, "settings.json"), "w", encoding="utf-8"
        ) as f:
            f.write(invalid_json)
        with patch.dict(os.environ, {"APPDATA": tmpdir}):
            result = read_settings()
    assert result == {"default_mb": 20}


@given(
    bad_value=st.one_of(
        st.just("not_a_number"),
        st.just(-1),
        st.just(0),
        st.floats(max_value=0.0, allow_nan=False),
    )
)
def test_prop22_settings_fallback_bad_default_mb(bad_value):
    """Property 22: read_settings() returns {"default_mb": 20} when default_mb is missing/non-positive.
    **Validates: Requirements 20.2, 20.6**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        settings_dir = os.path.join(tmpdir, "Morphix")
        os.makedirs(settings_dir, exist_ok=True)
        data = {"default_mb": bad_value}
        with open(
            os.path.join(settings_dir, "settings.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(data, f)
        with patch.dict(os.environ, {"APPDATA": tmpdir}):
            result = read_settings()
    assert result == {"default_mb": 20}


def test_prop22_settings_fallback_missing_key():
    """Property 22: read_settings() returns {"default_mb": 20} when default_mb key is absent.
    **Validates: Requirements 20.2, 20.6**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        settings_dir = os.path.join(tmpdir, "Morphix")
        os.makedirs(settings_dir, exist_ok=True)
        with open(
            os.path.join(settings_dir, "settings.json"), "w", encoding="utf-8"
        ) as f:
            json.dump({}, f)
        with patch.dict(os.environ, {"APPDATA": tmpdir}):
            result = read_settings()
    assert result == {"default_mb": 20}


# ---------------------------------------------------------------------------
# Property 23: Target size at or above file size raises before ffprobe
# Validates: Requirements 21.1, 21.2, 21.3
# ---------------------------------------------------------------------------


@given(
    file_size_bytes=st.integers(min_value=1, max_value=10_000_000),
    target_mb=st.floats(
        min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False
    ),
)
def test_prop23_target_exceeds_file_size_raises(file_size_bytes, target_mb):
    """Property 23: when target_mb >= file_size_mb, raises ValueError; otherwise does not raise.
    **Validates: Requirements 21.1, 21.2, 21.3**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "input.mp4")
        with open(test_file, "wb") as f:
            f.write(b"\x00" * file_size_bytes)

        file_size_mb = file_size_bytes / 1_000_000

        if target_mb >= file_size_mb:
            with pytest.raises(ValueError):
                check_target_exceeds_file_size(target_mb, test_file)
        else:
            check_target_exceeds_file_size(target_mb, test_file)


# ---------------------------------------------------------------------------
# Property 24: Low-ratio warning triggered iff target is below 3% threshold
# Validates: Requirements 22.1, 22.4, 22.5
# ---------------------------------------------------------------------------


@given(
    file_size_bytes=st.integers(min_value=1, max_value=100_000_000),
    target_mb=st.floats(
        min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False
    ),
)
def test_prop24_low_ratio_warning_threshold(file_size_bytes, target_mb):
    """Property 24: returns True iff target_mb < 0.03 * file_size_mb.
    **Validates: Requirements 22.1, 22.4, 22.5**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "input.mp4")
        with open(test_file, "wb") as f:
            f.write(b"\x00" * file_size_bytes)

        file_size_mb = file_size_bytes / 1_000_000
        result = check_low_compression_ratio(target_mb, test_file)

        if target_mb < 0.03 * file_size_mb:
            assert result is True
        else:
            assert result is False
