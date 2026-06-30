"""Unit tests for RunContext._resolve_output_path (Requirements 2.1–2.4)."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from morphix_core.config import CompressConfig
from morphix_core.core import RunContext


def make_ctx(input_path, max_mb=15, output_path=None, start=None, end=None):
    """Create a RunContext without triggering ffmpeg binary search side-effects."""
    with patch(
        "morphix_core.encoding.find_ffmpeg_binaries",
        return_value=(None, None, "missing"),
    ):
        config = CompressConfig(
            input_path, max_mb, output_path=output_path, start=start, end=end
        )
        ctx = RunContext(config)
    return ctx


# ---------------------------------------------------------------------------
# Requirement 2.1 – _{size}mb suffix inserted before extension
# ---------------------------------------------------------------------------


def test_suffix_inserted_before_extension(tmp_path):
    """_{size}mb is placed before the file extension, not appended after."""
    input_file = str(tmp_path / "myvideo.mp4")
    ctx = make_ctx(input_file, max_mb=15)
    ctx._resolve_output_path()
    assert ctx.output_path.endswith("myvideo_15mb.mp4")


def test_suffix_uses_correct_size(tmp_path):
    """The numeric size in the suffix matches max_mb."""
    input_file = str(tmp_path / "clip.mp4")
    ctx = make_ctx(input_file, max_mb=50)
    ctx._resolve_output_path()
    assert "_50mb" in os.path.basename(ctx.output_path)


def test_suffix_strips_trailing_zeros_for_integer_size(tmp_path):
    """Integer-valued floats like 15.0 produce _15mb, not _15.0mb."""
    input_file = str(tmp_path / "clip.mp4")
    ctx = make_ctx(input_file, max_mb=15.0)
    ctx._resolve_output_path()
    assert "_15mb" in os.path.basename(ctx.output_path)
    assert "_15.0mb" not in os.path.basename(ctx.output_path)


# ---------------------------------------------------------------------------
# Requirement 2.2 – .mp4 fallback when input has no extension
# ---------------------------------------------------------------------------


def test_mp4_fallback_when_no_extension(tmp_path):
    """Output uses .mp4 when the input file has no extension."""
    input_file = str(tmp_path / "rawvideo")
    ctx = make_ctx(input_file, max_mb=10)
    ctx._resolve_output_path()
    assert ctx.output_path.endswith(".mp4")


def test_mp4_fallback_preserves_suffix(tmp_path):
    """The _{size}mb suffix is still present even when falling back to .mp4."""
    input_file = str(tmp_path / "rawvideo")
    ctx = make_ctx(input_file, max_mb=10)
    ctx._resolve_output_path()
    assert "_10mb.mp4" in os.path.basename(ctx.output_path)


# ---------------------------------------------------------------------------
# Requirement 2.3 – Explicit output path is left unchanged
# ---------------------------------------------------------------------------


def test_explicit_output_path_unchanged(tmp_path):
    """When output_path is provided, _resolve_output_path must not modify it."""
    input_file = str(tmp_path / "myvideo.mp4")
    explicit = str(tmp_path / "custom_output.mp4")
    ctx = make_ctx(input_file, max_mb=15, output_path=explicit)
    ctx._resolve_output_path()
    assert ctx.output_path == explicit


def test_explicit_output_path_different_dir(tmp_path):
    """Explicit output path in a different directory is preserved as-is."""
    input_file = str(tmp_path / "myvideo.mp4")
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    explicit = str(other_dir / "result.mp4")
    ctx = make_ctx(input_file, max_mb=15, output_path=explicit)
    ctx._resolve_output_path()
    assert ctx.output_path == explicit


# ---------------------------------------------------------------------------
# Requirement 2.4 – Default output placed in same directory as input
# ---------------------------------------------------------------------------


def test_output_in_same_dir_as_input(tmp_path):
    """Default output file is placed in the same directory as the input."""
    input_file = str(tmp_path / "myvideo.mp4")
    ctx = make_ctx(input_file, max_mb=15)
    ctx._resolve_output_path()
    assert os.path.dirname(ctx.output_path) == str(tmp_path)


def test_output_in_same_dir_nested(tmp_path):
    """Works correctly when the input is in a nested subdirectory."""
    sub = tmp_path / "sub" / "deep"
    sub.mkdir(parents=True)
    input_file = str(sub / "clip.mkv")
    ctx = make_ctx(input_file, max_mb=20)
    ctx._resolve_output_path()
    assert os.path.dirname(ctx.output_path) == str(sub)


# ---------------------------------------------------------------------------
# Task 4.1 – compute_scaled_resolution and clamp_even
# Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7
# ---------------------------------------------------------------------------

from morphix_core.core import clamp_even, compute_scaled_resolution

BPP_THRESHOLDS = {"low": 0.05, "medium": 0.07, "high": 0.10}


# --- clamp_even ---


def test_clamp_even_already_even():
    """Even integers are returned unchanged."""
    assert clamp_even(100) == 100
    assert clamp_even(0) == 0
    assert clamp_even(480) == 480


def test_clamp_even_odd_rounds_down():
    """Odd integers are rounded down to the nearest even integer."""
    assert clamp_even(101) == 100
    assert clamp_even(481) == 480
    assert clamp_even(1) == 0


def test_clamp_even_float_rounds_to_even():
    """Float values are rounded to nearest int then clamped to even."""
    assert clamp_even(100.6) == 100  # rounds to 101, then -1 → 100
    assert clamp_even(100.4) == 100  # rounds to 100, already even
    assert clamp_even(101.5) == 102  # rounds to 102, already even


# --- No scaling when bpp >= threshold (Requirement 3.3) ---


def test_no_scaling_when_bpp_meets_low_threshold():
    """Returns None when current bpp >= low threshold (0.05)."""
    # 1920x1080 @ 30fps, bpp = 0.05 exactly → no scaling
    fps, w, h = 30, 1920, 1080
    video_bps = int(0.05 * fps * w * h)
    assert (
        compute_scaled_resolution(w, h, fps, video_bps, BPP_THRESHOLDS["low"]) is None
    )


def test_no_scaling_when_bpp_meets_medium_threshold():
    """Returns None when current bpp >= medium threshold (0.07)."""
    fps, w, h = 30, 1280, 720
    video_bps = int(0.07 * fps * w * h)
    assert (
        compute_scaled_resolution(w, h, fps, video_bps, BPP_THRESHOLDS["medium"])
        is None
    )


def test_no_scaling_when_bpp_meets_high_threshold():
    """Returns None when current bpp >= high threshold (0.10)."""
    fps, w, h = 60, 1920, 1080
    video_bps = int(0.10 * fps * w * h)
    assert (
        compute_scaled_resolution(w, h, fps, video_bps, BPP_THRESHOLDS["high"]) is None
    )


def test_no_scaling_when_bpp_exceeds_threshold():
    """Returns None when current bpp is well above the threshold."""
    fps, w, h = 30, 1920, 1080
    # bpp = 0.20, well above any threshold
    video_bps = int(0.20 * fps * w * h)
    assert (
        compute_scaled_resolution(w, h, fps, video_bps, BPP_THRESHOLDS["high"]) is None
    )


# --- Proportional scaling when bpp < threshold (Requirement 3.4) ---


def test_scaling_applied_when_bpp_below_threshold():
    """Returns scaled dimensions when current bpp < target bpp."""
    fps, w, h = 30, 1920, 1080
    # bpp = 0.03, below medium threshold of 0.07
    video_bps = int(0.03 * fps * w * h)
    result = compute_scaled_resolution(w, h, fps, video_bps, BPP_THRESHOLDS["medium"])
    assert result is not None
    new_w, new_h = result
    assert new_w < w
    assert new_h < h


def test_scaling_proportional_formula():
    """Scaled dimensions satisfy the target bpp formula (within rounding)."""
    fps, w, h = 30, 1920, 1080
    target_bpp = 0.07
    # bpp = 0.03, below threshold
    video_bps = int(0.03 * fps * w * h)
    result = compute_scaled_resolution(w, h, fps, video_bps, target_bpp)
    assert result is not None
    new_w, new_h = result
    # The resulting bpp should be approximately target_bpp (within rounding tolerance)
    actual_bpp = video_bps / (fps * new_w * new_h)
    assert abs(actual_bpp - target_bpp) / target_bpp < 0.05  # within 5%


def test_scaling_preserves_aspect_ratio():
    """Scaled width/height preserve the original aspect ratio (within rounding)."""
    fps, w, h = 30, 1920, 1080
    video_bps = int(0.03 * fps * w * h)
    result = compute_scaled_resolution(w, h, fps, video_bps, 0.07)
    assert result is not None
    new_w, new_h = result
    original_ratio = w / h
    scaled_ratio = new_w / new_h
    assert abs(scaled_ratio - original_ratio) / original_ratio < 0.05  # within 5%


# --- Minimum height floor of 480 px (Requirement 3.5) ---


def test_minimum_height_floor_enforced():
    """Height is never below 480 px even when scaling would produce less."""
    # Very low bitrate on a tall video forces height below 480 without the floor
    fps, w, h = 30, 1920, 1080
    # Extremely low bpp to force heavy downscaling
    video_bps = int(0.001 * fps * w * h)
    result = compute_scaled_resolution(w, h, fps, video_bps, 0.07)
    if result is not None:
        _, new_h = result
        assert new_h >= 480


def test_minimum_height_floor_exact_480():
    """When floor kicks in, height is exactly 480 (clamped to even)."""
    fps, w, h = 30, 1920, 1080
    # bpp that would scale height to ~300 without the floor
    target_bpp = 0.07
    # scale = sqrt(target_pixels / (w*h)); target_pixels = video_bps/(fps*target_bpp)
    # We want scale such that h*scale < 480, so scale < 480/1080 ≈ 0.444
    # Use scale = 0.3 → video_bps = 0.3^2 * fps * w * h * target_bpp
    scale = 0.3
    video_bps = int(scale**2 * fps * w * h * target_bpp)
    result = compute_scaled_resolution(w, h, fps, video_bps, target_bpp)
    if result is not None:
        _, new_h = result
        assert new_h == 480


# --- Even-integer rounding via clamp_even (Requirement 3.6) ---


def test_scaled_dimensions_are_even():
    """Both width and height returned by compute_scaled_resolution are even integers."""
    fps, w, h = 30, 1920, 1080
    video_bps = int(0.03 * fps * w * h)
    result = compute_scaled_resolution(w, h, fps, video_bps, 0.07)
    assert result is not None
    new_w, new_h = result
    assert new_w % 2 == 0
    assert new_h % 2 == 0


def test_scaled_dimensions_are_even_for_odd_source():
    """Even-integer rounding works correctly for odd-dimension source videos."""
    fps, w, h = 25, 1921, 1081  # odd dimensions
    video_bps = int(0.03 * fps * w * h)
    result = compute_scaled_resolution(w, h, fps, video_bps, 0.07)
    if result is not None:
        new_w, new_h = result
        assert new_w % 2 == 0
        assert new_h % 2 == 0


# --- Returns None when computed dimensions < 2 px (Requirement 3.7) ---


def test_returns_none_when_dimensions_too_small():
    """Returns None when computed dimensions would be < 2 px."""
    # Tiny video with very low bitrate
    fps, w, h = 30, 4, 4
    # bpp = 0.001, well below threshold; scale ≈ sqrt(0.001/0.07) ≈ 0.12
    # new_w = clamp_even(4 * 0.12) = clamp_even(0.48) = 0 → < 2 → None
    video_bps = int(0.001 * fps * w * h)
    result = compute_scaled_resolution(w, h, fps, video_bps, 0.07)
    assert result is None


# --- BPP threshold values (Requirement 3.2) ---


def test_bpp_threshold_low_is_0_05():
    """Low quality threshold is 0.05: bpp=0.05 → no scale, bpp=0.049 → scale."""
    fps, w, h = 30, 1920, 1080
    # Exactly at threshold → no scaling
    video_bps_at = int(0.05 * fps * w * h)
    assert compute_scaled_resolution(w, h, fps, video_bps_at, 0.05) is None
    # Just below threshold → scaling
    video_bps_below = int(0.049 * fps * w * h)
    assert compute_scaled_resolution(w, h, fps, video_bps_below, 0.05) is not None


def test_bpp_threshold_medium_is_0_07():
    """Medium quality threshold is 0.07: bpp=0.07 → no scale, bpp=0.069 → scale."""
    fps, w, h = 30, 1920, 1080
    video_bps_at = int(0.07 * fps * w * h)
    assert compute_scaled_resolution(w, h, fps, video_bps_at, 0.07) is None
    video_bps_below = int(0.069 * fps * w * h)
    assert compute_scaled_resolution(w, h, fps, video_bps_below, 0.07) is not None


def test_bpp_threshold_high_is_0_10():
    """High quality threshold is 0.10: bpp=0.10 → no scale, bpp=0.099 → scale."""
    fps, w, h = 30, 1920, 1080
    video_bps_at = int(0.10 * fps * w * h)
    assert compute_scaled_resolution(w, h, fps, video_bps_at, 0.10) is None
    video_bps_below = int(0.099 * fps * w * h)
    assert compute_scaled_resolution(w, h, fps, video_bps_below, 0.10) is not None


# ---------------------------------------------------------------------------
# Task 5.1 – RunContext._compute_scaling manual override path
# Requirements: 4.1, 4.2, 4.3, 4.4
# ---------------------------------------------------------------------------


def make_ctx_with_probe(resolution=None, probe_streams=None):
    """Create a RunContext with a pre-populated probe dict for _compute_scaling tests."""
    with patch(
        "morphix_core.encoding.find_ffmpeg_binaries",
        return_value=(None, None, "missing"),
    ):
        config = CompressConfig("/fake/video.mp4", max_mb=15, resolution=resolution)
        ctx = RunContext(config)
    ctx.probe = {"streams": probe_streams or []}
    ctx.video_bps = 1_000_000  # 1 Mbps default
    return ctx


# --- Valid WIDTHxHEIGHT sets scale_filter (Requirement 4.1) ---


def test_valid_resolution_sets_scale_filter():
    """Valid '1280x720' sets scale to (1280, 720)."""
    ctx = make_ctx_with_probe(resolution="1280x720")
    ctx._compute_scaling()
    assert ctx.scale == (1280, 720)


# --- Even-clamping applied to odd dimensions (Requirement 4.2) ---


def test_odd_dimensions_are_clamped_to_even():
    """'1281x721' is clamped to (1280, 720)."""
    ctx = make_ctx_with_probe(resolution="1281x721")
    ctx._compute_scaling()
    assert ctx.scale == (1280, 720)


def test_odd_width_only_clamped():
    """Odd width is clamped; even height unchanged."""
    ctx = make_ctx_with_probe(resolution="1281x720")
    ctx._compute_scaling()
    assert ctx.scale == (1280, 720)


def test_odd_height_only_clamped():
    """Even width unchanged; odd height is clamped."""
    ctx = make_ctx_with_probe(resolution="1280x721")
    ctx._compute_scaling()
    assert ctx.scale == (1280, 720)


# --- Invalid resolution strings leave scale_filter as None (Requirements 4.3, 4.4) ---


def test_no_x_separator_leaves_scale_filter_none():
    """Resolution string without 'x' leaves scale_filter as None."""
    ctx = make_ctx_with_probe(resolution="1280720")
    ctx._compute_scaling()
    assert ctx.scale is None


def test_non_numeric_width_leaves_scale_filter_none():
    """Non-numeric width leaves scale_filter as None."""
    ctx = make_ctx_with_probe(resolution="abcx720")
    ctx._compute_scaling()
    assert ctx.scale is None


def test_non_numeric_height_leaves_scale_filter_none():
    """Non-numeric height leaves scale_filter as None."""
    ctx = make_ctx_with_probe(resolution="1280xabc")
    ctx._compute_scaling()
    assert ctx.scale is None


def test_empty_resolution_leaves_scale_filter_none():
    """Empty resolution string leaves scale_filter as None."""
    ctx = make_ctx_with_probe(resolution="")
    ctx._compute_scaling()
    assert ctx.scale is None


def test_dimension_below_2_leaves_scale_filter_none():
    """Dimensions < 2 after clamping leave scale_filter as None."""
    ctx = make_ctx_with_probe(resolution="1x1")
    ctx._compute_scaling()
    assert ctx.scale is None


def test_zero_dimension_leaves_scale_filter_none():
    """Zero dimension leaves scale_filter as None."""
    ctx = make_ctx_with_probe(resolution="0x720")
    ctx._compute_scaling()
    assert ctx.scale is None


def test_negative_dimension_leaves_scale_filter_none():
    """Negative dimension leaves scale_filter as None."""
    ctx = make_ctx_with_probe(resolution="-1280x720")
    ctx._compute_scaling()
    assert ctx.scale is None


# --- Manual override bypasses auto-scaling (Requirement 4.1) ---


def test_manual_override_bypasses_auto_scaling():
    """Manual resolution override ignores probe data and skips auto-scaling logic."""
    # Provide a video stream that would trigger auto-scaling
    probe_streams = [
        {
            "codec_type": "video",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30/1",
        }
    ]
    ctx = make_ctx_with_probe(resolution="640x360", probe_streams=probe_streams)
    # Set a very low bitrate that would normally trigger auto-scaling to a different resolution
    ctx.video_bps = 100_000
    ctx._compute_scaling()
    # Manual override wins — not the auto-scaled value
    assert ctx.scale == (640, 360)


def test_manual_override_with_no_probe_data():
    """Manual override works even when probe has no video stream."""
    ctx = make_ctx_with_probe(resolution="1280x720", probe_streams=[])
    ctx._compute_scaling()
    assert ctx.scale == (1280, 720)


def test_no_resolution_uses_auto_scaling():
    """When resolution is None, auto-scaling logic is used (not manual override)."""
    probe_streams = [
        {
            "codec_type": "video",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30/1",
        }
    ]
    ctx = make_ctx_with_probe(resolution=None, probe_streams=probe_streams)
    # Very low bitrate → auto-scaling should kick in
    ctx.video_bps = int(0.01 * 30 * 1920 * 1080)
    ctx._compute_scaling()
    # Auto-scaling should produce some scale tuple (not None)
    assert ctx.scale is not None
    assert isinstance(ctx.scale, tuple) and len(ctx.scale) == 2


# ---------------------------------------------------------------------------
# Task 6.1 – Hardware acceleration detection
# Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9
# ---------------------------------------------------------------------------

from morphix_core.core import (
    detect_cuda,
    detect_device_info,
    get_available_devices,
    resolve_device_info,
)

# --- detect_cuda (Requirement 5.1) ---


def test_detect_cuda_returns_true_when_nvidia_smi_exits_0_with_output():
    """NVIDIA detected when nvidia-smi exits 0 with GPU output."""
    mock_result = type(
        "R", (), {"returncode": 0, "stdout": "GPU 0: NVIDIA GeForce RTX 3080\n"}
    )()
    with (
        patch(
            "morphix_core.gpu_detection.shutil.which",
            return_value="/usr/bin/nvidia-smi",
        ),
        patch("morphix_core.gpu_detection.subprocess.run", return_value=mock_result),
    ):
        assert detect_cuda() is True


def test_detect_cuda_returns_false_when_nvidia_smi_not_on_path():
    """NVIDIA not detected when nvidia-smi is absent from PATH."""
    with patch("morphix_core.gpu_detection.shutil.which", return_value=None):
        assert detect_cuda() is False


def test_detect_cuda_returns_false_when_nvidia_smi_exits_nonzero():
    """NVIDIA not detected when nvidia-smi exits with non-zero code."""
    mock_result = type("R", (), {"returncode": 1, "stdout": ""})()
    with (
        patch(
            "morphix_core.gpu_detection.shutil.which",
            return_value="/usr/bin/nvidia-smi",
        ),
        patch("morphix_core.gpu_detection.subprocess.run", return_value=mock_result),
    ):
        assert detect_cuda() is False


def test_detect_cuda_returns_false_when_nvidia_smi_exits_0_but_no_output():
    """NVIDIA not detected when nvidia-smi exits 0 but produces no output."""
    mock_result = type("R", (), {"returncode": 0, "stdout": ""})()
    with (
        patch(
            "morphix_core.gpu_detection.shutil.which",
            return_value="/usr/bin/nvidia-smi",
        ),
        patch("morphix_core.gpu_detection.subprocess.run", return_value=mock_result),
    ):
        assert detect_cuda() is False


def test_detect_cuda_returns_false_on_oserror():
    """NVIDIA detection returns False (not raises) when subprocess raises OSError."""
    with (
        patch(
            "morphix_core.gpu_detection.shutil.which",
            return_value="/usr/bin/nvidia-smi",
        ),
        patch(
            "morphix_core.gpu_detection.subprocess.run",
            side_effect=OSError("not found"),
        ),
    ):
        assert detect_cuda() is False


# --- detect_device_info (Requirements 5.1–5.6) ---


def test_detect_device_info_returns_nvidia_when_cuda_detected():
    """detect_device_info returns ('NVIDIA GPU', 'cuda') when CUDA is available."""
    with patch("morphix_core.gpu_detection.detect_cuda", return_value=True):
        label, hwaccel = detect_device_info()
    assert label == "NVIDIA GPU"
    assert hwaccel == "cuda"


def test_detect_device_info_returns_amd_when_nvidia_fails_amd_succeeds():
    """detect_device_info returns ('AMD GPU', 'amf') when NVIDIA fails but AMD succeeds."""
    with (
        patch("morphix_core.gpu_detection.detect_cuda", return_value=False),
        patch("morphix_core.gpu_detection.detect_amd", return_value=True),
    ):
        label, hwaccel = detect_device_info()
    assert label == "AMD GPU"
    assert hwaccel == "amf"


def test_detect_device_info_returns_intel_when_nvidia_and_amd_fail():
    """detect_device_info returns ('Intel GPU', 'qsv') when NVIDIA and AMD fail but Intel succeeds."""
    with (
        patch("morphix_core.gpu_detection.detect_cuda", return_value=False),
        patch("morphix_core.gpu_detection.detect_amd", return_value=False),
        patch("morphix_core.gpu_detection.detect_intel", return_value=True),
    ):
        label, hwaccel = detect_device_info()
    assert label == "Intel GPU"
    assert hwaccel == "qsv"


def test_detect_device_info_returns_cpu_when_all_fail():
    """detect_device_info returns ('CPU', None) when all vendor detections fail."""
    with (
        patch("morphix_core.gpu_detection.detect_cuda", return_value=False),
        patch("morphix_core.gpu_detection.detect_amd", return_value=False),
        patch("morphix_core.gpu_detection.detect_intel", return_value=False),
    ):
        label, hwaccel = detect_device_info()
    assert label == "CPU"
    assert hwaccel is None


# --- Exception swallowing (Requirement 5.7) ---


def test_detect_device_info_swallows_nvidia_exception_falls_back_to_amd():
    """Exception from NVIDIA detection is caught; AMD is tried next."""
    with (
        patch(
            "morphix_core.gpu_detection.detect_cuda", side_effect=RuntimeError("boom")
        ),
        patch("morphix_core.gpu_detection.detect_amd", return_value=True),
    ):
        label, hwaccel = detect_device_info()
    assert label == "AMD GPU"
    assert hwaccel == "amf"


def test_detect_device_info_swallows_amd_exception_falls_back_to_intel():
    """Exception from AMD detection is caught; Intel is tried next."""
    with (
        patch("morphix_core.gpu_detection.detect_cuda", return_value=False),
        patch(
            "morphix_core.gpu_detection.detect_amd", side_effect=RuntimeError("boom")
        ),
        patch("morphix_core.gpu_detection.detect_intel", return_value=True),
    ):
        label, hwaccel = detect_device_info()
    assert label == "Intel GPU"
    assert hwaccel == "qsv"


def test_detect_device_info_swallows_intel_exception_falls_back_to_cpu():
    """Exception from Intel detection is caught; CPU fallback is used."""
    with (
        patch("morphix_core.gpu_detection.detect_cuda", return_value=False),
        patch("morphix_core.gpu_detection.detect_amd", return_value=False),
        patch(
            "morphix_core.gpu_detection.detect_intel", side_effect=RuntimeError("boom")
        ),
    ):
        label, hwaccel = detect_device_info()
    assert label == "CPU"
    assert hwaccel is None


def test_detect_device_info_swallows_all_exceptions_returns_cpu():
    """All vendor exceptions are caught; CPU fallback is returned without propagating."""
    with (
        patch(
            "morphix_core.gpu_detection.detect_cuda",
            side_effect=Exception("nvidia error"),
        ),
        patch(
            "morphix_core.gpu_detection.detect_amd", side_effect=Exception("amd error")
        ),
        patch(
            "morphix_core.gpu_detection.detect_intel",
            side_effect=Exception("intel error"),
        ),
    ):
        label, hwaccel = detect_device_info()
    assert label == "CPU"
    assert hwaccel is None


# --- get_available_devices (Requirement 5.8) ---


def test_get_available_devices_always_ends_with_cpu():
    """get_available_devices() always ends with ('cpu', 'CPU')."""
    with (
        patch("morphix_core.gpu_detection.detect_cuda", return_value=False),
        patch("morphix_core.gpu_detection.detect_amd", return_value=False),
        patch("morphix_core.gpu_detection.detect_intel", return_value=False),
    ):
        devices = get_available_devices()
    assert devices[-1] == ("cpu", "CPU", True)


def test_get_available_devices_ends_with_cpu_when_nvidia_present():
    """get_available_devices() ends with ('cpu', 'CPU') even when NVIDIA is detected."""
    with (
        patch("morphix_core.gpu_detection.detect_cuda", return_value=True),
        patch("morphix_core.gpu_detection.check_nvenc_usable", return_value=True),
        patch("morphix_core.gpu_detection.detect_amd", return_value=False),
        patch("morphix_core.gpu_detection.detect_intel", return_value=False),
    ):
        devices = get_available_devices()
    assert devices[-1] == ("cpu", "CPU", True)
    assert ("nvidia", "NVIDIA GPU", True) in devices


def test_get_available_devices_gpu_first_cpu_last():
    """GPU entries appear before CPU in get_available_devices()."""
    with (
        patch("morphix_core.gpu_detection.detect_cuda", return_value=True),
        patch("morphix_core.gpu_detection.check_nvenc_usable", return_value=True),
        patch("morphix_core.gpu_detection.detect_amd", return_value=False),
        patch("morphix_core.gpu_detection.detect_intel", return_value=False),
    ):
        devices = get_available_devices()
    keys = [k for k, _, _ in devices]
    assert keys.index("nvidia") < keys.index("cpu")


def test_get_available_devices_only_cpu_when_no_gpu():
    """All devices returned; GPUs marked unavailable when not detected."""
    with (
        patch("morphix_core.gpu_detection.detect_cuda", return_value=False),
        patch("morphix_core.gpu_detection.detect_amd", return_value=False),
        patch("morphix_core.gpu_detection.detect_intel", return_value=False),
    ):
        devices = get_available_devices()
    assert devices[-1] == ("cpu", "CPU", True)
    assert ("nvidia", "NVIDIA GPU (not detected)", False) in devices


def test_get_available_devices_swallows_exceptions_still_ends_with_cpu():
    """Exceptions from GPU detection are swallowed; CPU is still last entry."""
    with (
        patch("morphix_core.gpu_detection.detect_cuda", side_effect=Exception("err")),
        patch("morphix_core.gpu_detection.detect_amd", side_effect=Exception("err")),
        patch("morphix_core.gpu_detection.detect_intel", side_effect=Exception("err")),
    ):
        devices = get_available_devices()
    assert devices[-1] == ("cpu", "CPU", True)


# --- resolve_device_info (Requirement 5.9) ---


def test_resolve_device_info_cpu_preference_returns_cpu():
    """resolve_device_info('cpu') always returns ('CPU', None)."""
    label, hwaccel = resolve_device_info("cpu")
    assert label == "CPU"
    assert hwaccel is None


def test_resolve_device_info_nvidia_available_returns_nvidia():
    """resolve_device_info('nvidia') returns ('NVIDIA GPU', 'cuda') when CUDA available."""
    with patch("morphix_core.gpu_detection.detect_cuda", return_value=True):
        label, hwaccel = resolve_device_info("nvidia")
    assert label == "NVIDIA GPU"
    assert hwaccel == "cuda"


def test_resolve_device_info_nvidia_unavailable_falls_back_to_cpu():
    """resolve_device_info('nvidia') falls back to ('CPU', None) when CUDA unavailable."""
    with patch("morphix_core.gpu_detection.detect_cuda", return_value=False):
        label, hwaccel = resolve_device_info("nvidia")
    assert label == "CPU"
    assert hwaccel is None


def test_resolve_device_info_amd_available_returns_amd():
    """resolve_device_info('amd') returns ('AMD GPU', 'amf') when AMD available."""
    with patch("morphix_core.gpu_detection.detect_amd", return_value=True):
        label, hwaccel = resolve_device_info("amd")
    assert label == "AMD GPU"
    assert hwaccel == "amf"


def test_resolve_device_info_amd_unavailable_falls_back_to_cpu():
    """resolve_device_info('amd') falls back to ('CPU', None) when AMD unavailable."""
    with patch("morphix_core.gpu_detection.detect_amd", return_value=False):
        label, hwaccel = resolve_device_info("amd")
    assert label == "CPU"
    assert hwaccel is None


def test_resolve_device_info_intel_available_returns_intel():
    """resolve_device_info('intel') returns ('Intel GPU', 'qsv') when Intel available."""
    with patch("morphix_core.gpu_detection.detect_intel", return_value=True):
        label, hwaccel = resolve_device_info("intel")
    assert label == "Intel GPU"
    assert hwaccel == "qsv"


def test_resolve_device_info_intel_unavailable_falls_back_to_cpu():
    """resolve_device_info('intel') falls back to ('CPU', None) when Intel unavailable."""
    with patch("morphix_core.gpu_detection.detect_intel", return_value=False):
        label, hwaccel = resolve_device_info("intel")
    assert label == "CPU"
    assert hwaccel is None


def test_resolve_device_info_unknown_key_uses_auto_detection():
    """resolve_device_info with unknown key falls back to detect_device_info()."""
    with (
        patch("morphix_core.gpu_detection.detect_cuda", return_value=False),
        patch("morphix_core.gpu_detection.detect_amd", return_value=False),
        patch("morphix_core.gpu_detection.detect_intel", return_value=False),
    ):
        label, hwaccel = resolve_device_info("unknown_device")
    assert label == "CPU"
    assert hwaccel is None


def test_resolve_device_info_nvidia_exception_falls_back_to_cpu():
    """resolve_device_info('nvidia') falls back to CPU when detect_cuda raises."""
    with patch("morphix_core.gpu_detection.detect_cuda", side_effect=Exception("err")):
        label, hwaccel = resolve_device_info("nvidia")
    assert label == "CPU"
    assert hwaccel is None


# ---------------------------------------------------------------------------
# Task 7.1 – find_ffmpeg_binaries
# Requirements: 6.1, 6.2, 6.3
# ---------------------------------------------------------------------------

from morphix_core.core import find_ffmpeg_binaries


def _make_isfile(present_dirs):
    """Return an os.path.isfile mock that returns True only for paths under present_dirs."""

    def isfile(path):
        for d in present_dirs:
            if path.startswith(d + os.sep) or path.startswith(d + "/"):
                return True
        return False

    return isfile


def test_find_ffmpeg_binaries_returns_bundled_when_meipass_has_both(tmp_path):
    """Returns bundled (MEIPASS) when no user override or PATH exists."""
    bundle = str(tmp_path / "bundle" / "ffmpeg")
    ffmpeg_exe = os.path.join(bundle, "ffmpeg.exe")
    ffprobe_exe = os.path.join(bundle, "ffprobe.exe")

    with (
        patch("morphix_core.ffmpeg_utils.sys") as mock_sys,
        patch("morphix_core.ffmpeg_utils.os.path.isfile") as mock_isfile,
        patch("morphix_core.ffmpeg_utils.shutil.which", return_value=None),
    ):
        mock_sys._MEIPASS = str(tmp_path / "bundle")
        mock_sys.executable = "/some/python.exe"
        mock_isfile.side_effect = lambda p: p in (ffmpeg_exe, ffprobe_exe)

        result = find_ffmpeg_binaries()

    assert result == (ffmpeg_exe, ffprobe_exe, "bundled")


def test_find_ffmpeg_binaries_skips_candidate_missing_ffprobe(tmp_path):
    """Skips a candidate directory that has ffmpeg.exe but not ffprobe.exe."""
    bundle = str(tmp_path / "bundle" / "ffmpeg")
    ffmpeg_exe = os.path.join(bundle, "ffmpeg.exe")
    # ffprobe.exe is absent from bundle

    exe_dir = str(tmp_path / "exedir" / "ffmpeg")
    ffmpeg_exe2 = os.path.join(exe_dir, "ffmpeg.exe")
    ffprobe_exe2 = os.path.join(exe_dir, "ffprobe.exe")

    def isfile(p):
        if p == ffmpeg_exe:
            return True  # bundle has ffmpeg but not ffprobe
        if p in (ffmpeg_exe2, ffprobe_exe2):
            return True  # exe dir has both
        return False

    with (
        patch("morphix_core.ffmpeg_utils.sys") as mock_sys,
        patch("morphix_core.ffmpeg_utils.os.path.isfile", side_effect=isfile),
    ):
        mock_sys._MEIPASS = str(tmp_path / "bundle")
        mock_sys.executable = str(tmp_path / "exedir" / "python.exe")

        result = find_ffmpeg_binaries()

    assert result == (ffmpeg_exe2, ffprobe_exe2, "user")


def test_find_ffmpeg_binaries_skips_candidate_missing_ffmpeg(tmp_path):
    """Skips a candidate directory that has ffprobe.exe but not ffmpeg.exe."""
    bundle = str(tmp_path / "bundle" / "ffmpeg")
    ffprobe_only = os.path.join(bundle, "ffprobe.exe")

    exe_dir = str(tmp_path / "exedir" / "ffmpeg")
    ffmpeg_exe2 = os.path.join(exe_dir, "ffmpeg.exe")
    ffprobe_exe2 = os.path.join(exe_dir, "ffprobe.exe")

    def isfile(p):
        if p == ffprobe_only:
            return True
        if p in (ffmpeg_exe2, ffprobe_exe2):
            return True
        return False

    with (
        patch("morphix_core.ffmpeg_utils.sys") as mock_sys,
        patch("morphix_core.ffmpeg_utils.os.path.isfile", side_effect=isfile),
    ):
        mock_sys._MEIPASS = str(tmp_path / "bundle")
        mock_sys.executable = str(tmp_path / "exedir" / "python.exe")

        result = find_ffmpeg_binaries()

    assert result == (ffmpeg_exe2, ffprobe_exe2, "user")


def test_find_ffmpeg_binaries_falls_back_to_path_when_no_candidate_has_both():
    """Falls back to ('ffmpeg', 'ffprobe', 'path') when no candidate directory has both binaries."""
    with (
        patch("morphix_core.ffmpeg_utils.sys") as mock_sys,
        patch("morphix_core.ffmpeg_utils.os.path.isfile", return_value=False),
        patch(
            "morphix_core.ffmpeg_utils.shutil.which",
            side_effect=lambda name: f"/usr/bin/{name}",
        ),
    ):
        mock_sys._MEIPASS = None
        mock_sys.executable = "/usr/bin/python3"

        result = find_ffmpeg_binaries()

    assert result == ("/usr/bin/ffmpeg", "/usr/bin/ffprobe", "path")


def test_find_ffmpeg_binaries_returns_missing_when_no_binaries_anywhere():
    """Returns (None, None, 'missing') when no bundled or PATH binaries exist."""
    with (
        patch("morphix_core.ffmpeg_utils.sys") as mock_sys,
        patch("morphix_core.ffmpeg_utils.os.path.isfile", return_value=False),
        patch("morphix_core.ffmpeg_utils.shutil.which", return_value=None),
    ):
        mock_sys._MEIPASS = None
        mock_sys.executable = "/usr/bin/python3"

        result = find_ffmpeg_binaries()

    assert result == (None, None, "missing")


def test_find_ffmpeg_binaries_meipass_checked_first(tmp_path):
    """User folder (exe dir) is checked before _MEIPASS bundled."""
    bundle = str(tmp_path / "bundle" / "ffmpeg")
    ffmpeg_bundle = os.path.join(bundle, "ffmpeg.exe")
    ffprobe_bundle = os.path.join(bundle, "ffprobe.exe")

    exe_dir = str(tmp_path / "exedir" / "ffmpeg")
    ffmpeg_exe = os.path.join(exe_dir, "ffmpeg.exe")
    ffprobe_exe = os.path.join(exe_dir, "ffprobe.exe")

    # Both candidates have both binaries; user (exe dir) should win.
    def isfile(p):
        return p in (ffmpeg_bundle, ffprobe_bundle, ffmpeg_exe, ffprobe_exe)

    with (
        patch("morphix_core.ffmpeg_utils.sys") as mock_sys,
        patch("morphix_core.ffmpeg_utils.os.path.isfile", side_effect=isfile),
    ):
        mock_sys._MEIPASS = str(tmp_path / "bundle")
        mock_sys.executable = str(tmp_path / "exedir" / "python.exe")

        result = find_ffmpeg_binaries()

    assert result == (ffmpeg_exe, ffprobe_exe, "user")


def test_find_ffmpeg_binaries_no_meipass_uses_exe_dir(tmp_path):
    """When sys._MEIPASS is absent, Python executable directory is the first candidate."""
    exe_dir = str(tmp_path / "exedir" / "ffmpeg")
    ffmpeg_exe = os.path.join(exe_dir, "ffmpeg.exe")
    ffprobe_exe = os.path.join(exe_dir, "ffprobe.exe")

    def isfile(p):
        return p in (ffmpeg_exe, ffprobe_exe)

    with (
        patch("morphix_core.ffmpeg_utils.sys") as mock_sys,
        patch("morphix_core.ffmpeg_utils.os.path.isfile", side_effect=isfile),
    ):
        # No _MEIPASS attribute at all
        del mock_sys._MEIPASS
        mock_sys.executable = str(tmp_path / "exedir" / "python.exe")

        result = find_ffmpeg_binaries()

    assert result == (ffmpeg_exe, ffprobe_exe, "user")


# ---------------------------------------------------------------------------
# Task 8.1 – RunContext._run_ffmpeg_with_progress / _iter_progress_seconds
# Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
# ---------------------------------------------------------------------------

import io


def make_ctx_for_progress(progress=True, progress_cb=None, duration=100.0):
    """Create a RunContext wired for progress tests (no real ffmpeg needed)."""
    with patch(
        "morphix_core.encoding.find_ffmpeg_binaries",
        return_value=(None, None, "missing"),
    ):
        config = CompressConfig(
            "/fake/video.mp4", max_mb=15, progress=progress, progress_cb=progress_cb
        )
        ctx = RunContext(config)
    ctx.duration = duration
    ctx.log_dir = Path("/tmp/fake_log")
    return ctx


# --- _iter_progress_seconds: parses out_time_ms lines (Requirement 7.1) ---


def test_iter_progress_seconds_parses_out_time_ms():
    """_iter_progress_seconds yields N/1_000_000.0 for out_time_ms=N lines."""
    ctx = make_ctx_for_progress()
    raw = b"out_time_ms=5000000\n"
    stream = io.BytesIO(raw)
    results = list(ctx._iter_progress_seconds(stream))
    assert len(results) == 1
    elapsed, line = results[0]
    assert elapsed == pytest.approx(5.0)
    assert line == raw


def test_iter_progress_seconds_yields_none_for_non_matching_lines():
    """_iter_progress_seconds yields None for lines without out_time_ms."""
    ctx = make_ctx_for_progress()
    raw = b"frame=100\n"
    stream = io.BytesIO(raw)
    results = list(ctx._iter_progress_seconds(stream))
    assert len(results) == 1
    elapsed, line = results[0]
    assert elapsed is None
    assert line == raw


def test_iter_progress_seconds_handles_multiple_lines():
    """_iter_progress_seconds correctly handles a mix of matching and non-matching lines."""
    ctx = make_ctx_for_progress()
    data = b"frame=10\nout_time_ms=2000000\nbitrate=500kbps\nout_time_ms=4000000\n"
    stream = io.BytesIO(data)
    results = list(ctx._iter_progress_seconds(stream))
    assert len(results) == 4
    assert results[0][0] is None  # frame=10
    assert results[1][0] == pytest.approx(2.0)  # out_time_ms=2000000
    assert results[2][0] is None  # bitrate=...
    assert results[3][0] == pytest.approx(4.0)  # out_time_ms=4000000


def test_iter_progress_seconds_zero_value():
    """out_time_ms=0 yields 0.0 seconds."""
    ctx = make_ctx_for_progress()
    stream = io.BytesIO(b"out_time_ms=0\n")
    results = list(ctx._iter_progress_seconds(stream))
    assert results[0][0] == pytest.approx(0.0)


# --- Percentage computation: (elapsed_s / duration_s) * 100 (Requirement 7.2) ---


def test_render_progress_computes_correct_percentage():
    """_render_progress computes pct = (elapsed_s / duration_s) * 100."""
    calls = []
    ctx = make_ctx_for_progress(
        progress_cb=lambda pct, phase: calls.append((pct, phase)), duration=200.0
    )
    ctx._render_progress(50.0, None, "PASS1")
    assert len(calls) == 1
    assert calls[0][0] == pytest.approx(25.0)


def test_render_progress_100_percent_at_end():
    """_render_progress yields 100% when elapsed equals duration."""
    calls = []
    ctx = make_ctx_for_progress(
        progress_cb=lambda pct, phase: calls.append((pct, phase)), duration=60.0
    )
    ctx._render_progress(60.0, None, "PASS2")
    assert calls[0][0] == pytest.approx(100.0)


def test_render_progress_clamps_above_100():
    """_render_progress clamps percentage to 100 even if elapsed > duration."""
    calls = []
    ctx = make_ctx_for_progress(
        progress_cb=lambda pct, phase: calls.append((pct, phase)), duration=60.0
    )
    ctx._render_progress(70.0, None, "PASS1")
    assert calls[0][0] == pytest.approx(100.0)


# --- progress_cb called with correct phase labels (Requirement 7.3) ---


def test_progress_cb_called_with_pass1_label():
    """progress_cb receives 'PASS1' as the phase argument during pass 1."""
    calls = []
    ctx = make_ctx_for_progress(
        progress_cb=lambda pct, phase: calls.append((pct, phase)), duration=100.0
    )
    ctx._render_progress(50.0, None, "PASS1")
    assert calls[0][1] == "PASS1"


def test_progress_cb_called_with_pass2_label():
    """progress_cb receives 'PASS2' as the phase argument during pass 2."""
    calls = []
    ctx = make_ctx_for_progress(
        progress_cb=lambda pct, phase: calls.append((pct, phase)), duration=100.0
    )
    ctx._render_progress(50.0, None, "PASS2")
    assert calls[0][1] == "PASS2"


# --- stdout fallback when progress_cb is None (Requirement 7.4) ---


def test_stdout_fallback_when_progress_cb_is_none(capsys):
    """When progress_cb is None, progress is written to stdout."""
    ctx = make_ctx_for_progress(progress_cb=None, duration=100.0)
    ctx._render_progress(50.0, None, "PASS1")
    captured = capsys.readouterr()
    assert "50.0" in captured.out


def test_stdout_fallback_not_called_when_progress_cb_set(capsys):
    """When progress_cb is set, stdout is not written to."""
    ctx = make_ctx_for_progress(progress_cb=lambda pct, phase: None, duration=100.0)
    ctx._render_progress(50.0, None, "PASS1")
    captured = capsys.readouterr()
    assert captured.out == ""


# --- No stderr parsing when progress is disabled (Requirement 7.5) ---


def test_run_ffmpeg_simple_used_when_progress_disabled():
    """When progress=False, _run_ffmpeg_simple is called instead of _run_ffmpeg_with_progress."""
    ctx = make_ctx_for_progress(progress=False)
    stream = MagicMock()
    with (
        patch.object(ctx, "_run_ffmpeg_simple") as mock_simple,
        patch.object(ctx, "_run_ffmpeg_with_progress") as mock_with_progress,
    ):
        ctx._run_ffmpeg(stream, "PASS1")
    mock_simple.assert_called_once_with(stream)
    mock_with_progress.assert_not_called()


def test_run_ffmpeg_with_progress_used_when_progress_enabled():
    """When progress=True, _run_ffmpeg_with_progress is called."""
    ctx = make_ctx_for_progress(progress=True)
    stream = MagicMock()
    with (
        patch.object(ctx, "_run_ffmpeg_with_progress") as mock_with_progress,
        patch.object(ctx, "_run_ffmpeg_simple") as mock_simple,
    ):
        ctx._run_ffmpeg(stream, "PASS2")
    mock_with_progress.assert_called_once_with(stream, "PASS2")
    mock_simple.assert_not_called()


# ---------------------------------------------------------------------------
# Task 9.1 – RunContext._prepare_logs and _cleanup_logs
# Requirements: 8.1, 8.2, 8.3, 8.4
# ---------------------------------------------------------------------------


def make_ctx_for_logs(input_path):
    """Create a RunContext for log-related tests without triggering ffmpeg search."""
    with patch(
        "morphix_core.encoding.find_ffmpeg_binaries",
        return_value=(None, None, "missing"),
    ):
        config = CompressConfig(input_path, max_mb=15)
        ctx = RunContext(config)
    return ctx


def test_prepare_logs_creates_output_subdir(tmp_path):
    """_prepare_logs creates a .output/ subdirectory under the input file's directory."""
    input_file = str(tmp_path / "video.mp4")
    ctx = make_ctx_for_logs(input_file)
    ctx._prepare_logs()
    assert os.path.isdir(os.path.join(str(tmp_path), ".output"))


def test_prepare_logs_passlog_path_under_output(tmp_path):
    """passlog_path is set to a path inside the .output/ subdirectory."""
    input_file = str(tmp_path / "video.mp4")
    ctx = make_ctx_for_logs(input_file)
    ctx._prepare_logs()
    expected_prefix = str(tmp_path / ".output")
    assert str(ctx.passlog_path).startswith(expected_prefix)


def test_cleanup_logs_deletes_log_file(tmp_path):
    """_cleanup_logs removes the .log passlog file after Pass 2."""
    input_file = str(tmp_path / "video.mp4")
    ctx = make_ctx_for_logs(input_file)
    ctx._prepare_logs()
    log_file = str(ctx.passlog_path) + ".log"
    open(log_file, "w").close()  # create the file
    ctx._cleanup_logs()
    assert not os.path.exists(log_file)


def test_cleanup_logs_deletes_mbtree_file(tmp_path):
    """_cleanup_logs removes the .log.mbtree passlog file after Pass 2."""
    input_file = str(tmp_path / "video.mp4")
    ctx = make_ctx_for_logs(input_file)
    ctx._prepare_logs()
    mbtree_file = str(ctx.passlog_path) + ".log.mbtree"
    open(mbtree_file, "w").close()  # create the file
    ctx._cleanup_logs()
    assert not os.path.exists(mbtree_file)


def test_cleanup_logs_removes_output_dir_when_empty(tmp_path):
    """_cleanup_logs removes the .output/ directory when it is empty after cleanup."""
    input_file = str(tmp_path / "video.mp4")
    ctx = make_ctx_for_logs(input_file)
    ctx._prepare_logs()
    # Create and then remove both passlog files so the dir is empty
    for suffix in (".log", ".log.mbtree"):
        open(str(ctx.passlog_path) + suffix, "w").close()
    ctx._cleanup_logs()
    assert not os.path.exists(str(tmp_path / ".output"))


def test_cleanup_logs_silently_skips_missing_passlog_files(tmp_path):
    """_cleanup_logs does not raise an exception when passlog files are absent."""
    input_file = str(tmp_path / "video.mp4")
    ctx = make_ctx_for_logs(input_file)
    ctx._prepare_logs()
    # Do NOT create any passlog files — cleanup should not raise
    ctx._cleanup_logs()  # must not raise


def test_cleanup_logs_does_not_remove_output_dir_when_not_empty(tmp_path):
    """_cleanup_logs leaves .output/ in place when it still contains other files."""
    input_file = str(tmp_path / "video.mp4")
    ctx = make_ctx_for_logs(input_file)
    ctx._prepare_logs()
    # Place an unrelated file in .output/ so it is not empty after cleanup
    other_file = ctx.log_dir / "ffmpeg-error.log"
    open(other_file, "w").close()
    ctx._cleanup_logs()
    assert ctx.log_dir.is_dir()


# ---------------------------------------------------------------------------
# Task 10.1 – RunContext._write_ffmpeg_error
# Requirements: 9.1, 9.2, 9.3, 9.4
# ---------------------------------------------------------------------------

import ffmpeg as ffmpeg_lib


def make_ctx_for_error_log(tmp_path):
    """Create a RunContext with log_dir set to a real temp directory."""
    input_file = str(tmp_path / "video.mp4")
    with patch(
        "morphix_core.encoding.find_ffmpeg_binaries",
        return_value=(None, None, "missing"),
    ):
        config = CompressConfig(input_file, max_mb=15)
        ctx = RunContext(config)
    ctx.log_dir = Path(tmp_path / ".output")
    ctx.log_dir.mkdir(parents=True, exist_ok=True)
    return ctx


def _make_ffmpeg_error(stderr_bytes):
    """Construct an ffmpeg.Error with the given stderr bytes."""
    return ffmpeg_lib.Error("ffmpeg", None, stderr_bytes)


# --- Requirement 9.1: stderr bytes written to ffmpeg-error.log ---


def test_write_ffmpeg_error_writes_stderr_bytes(tmp_path):
    """stderr bytes from the exception are written to .output/ffmpeg-error.log."""
    ctx = make_ctx_for_error_log(tmp_path)
    err_bytes = b"ffmpeg: some error occurred\n"
    exc = _make_ffmpeg_error(err_bytes)
    ctx._write_ffmpeg_error(exc)
    log_path = os.path.join(str(ctx.log_dir), "ffmpeg-error.log")
    assert os.path.isfile(log_path)
    assert open(log_path, "rb").read() == err_bytes


# --- Requirement 9.2: fallback message when stderr is None ---


def test_write_ffmpeg_error_fallback_when_stderr_is_none(tmp_path):
    """Fallback message is written when exc.stderr is None."""
    ctx = make_ctx_for_error_log(tmp_path)
    exc = _make_ffmpeg_error(None)
    ctx._write_ffmpeg_error(exc)
    log_path = os.path.join(str(ctx.log_dir), "ffmpeg-error.log")
    assert open(log_path, "rb").read() == b"No stderr captured from ffmpeg.\n"


# --- Requirement 9.2: fallback message when stderr is empty bytes ---


def test_write_ffmpeg_error_fallback_when_stderr_is_empty_bytes(tmp_path):
    """Fallback message is written when exc.stderr is empty bytes b''."""
    ctx = make_ctx_for_error_log(tmp_path)
    exc = _make_ffmpeg_error(b"")
    ctx._write_ffmpeg_error(exc)
    log_path = os.path.join(str(ctx.log_dir), "ffmpeg-error.log")
    assert open(log_path, "rb").read() == b"No stderr captured from ffmpeg.\n"


# --- Requirement 9.3: error log path printed to stdout ---


def test_write_ffmpeg_error_prints_log_path_to_stdout(tmp_path, caplog):
    """The path to the error log is logged at ERROR level."""
    import logging

    ctx = make_ctx_for_error_log(tmp_path)
    exc = _make_ffmpeg_error(b"some error")
    with caplog.at_level(logging.ERROR, logger="morphix"):
        ctx._write_ffmpeg_error(exc)
    expected_path = os.path.join(str(ctx.log_dir), "ffmpeg-error.log")
    assert expected_path in caplog.text


# --- Requirement 9.4: exception is re-raised by _run_ffmpeg ---


def test_run_ffmpeg_reraises_after_writing_error_log(tmp_path):
    """_run_ffmpeg re-raises as RuntimeError after calling _write_ffmpeg_error."""
    input_file = str(tmp_path / "video.mp4")
    with patch(
        "morphix_core.encoding.find_ffmpeg_binaries",
        return_value=(None, None, "missing"),
    ):
        config = CompressConfig(input_file, max_mb=15, progress=False)
        ctx = RunContext(config)
    ctx.log_dir = Path(tmp_path / ".output")
    ctx.log_dir.mkdir(parents=True, exist_ok=True)

    fake_exc = ffmpeg_lib.Error("ffmpeg", None, b"fatal error")

    with patch.object(ctx, "_run_ffmpeg_simple", side_effect=fake_exc):
        with pytest.raises(RuntimeError, match="FFmpeg error: fatal error"):
            ctx._run_ffmpeg(MagicMock(), "PASS1")


# ---------------------------------------------------------------------------
# Task 11.1 – popen_no_window_kwargs
# Requirements: 10.1, 10.2
# ---------------------------------------------------------------------------

import subprocess as _subprocess

from morphix_core.core import popen_no_window_kwargs


def test_popen_no_window_kwargs_returns_create_no_window_on_nt():
    """Returns {'creationflags': CREATE_NO_WINDOW} when os.name == 'nt'."""
    with patch("morphix_core.ffmpeg_utils.os.name", "nt"):
        result = popen_no_window_kwargs()
    assert result == {"creationflags": _subprocess.CREATE_NO_WINDOW}


def test_popen_no_window_kwargs_returns_start_new_session_on_posix():
    """Returns {'start_new_session': True} when os.name == 'posix'."""
    with patch("morphix_core.ffmpeg_utils.os.name", "posix"):
        result = popen_no_window_kwargs()
    assert result == {"start_new_session": True}


def test_popen_no_window_kwargs_returns_start_new_session_on_non_nt():
    """Returns {'start_new_session': True} when os.name == 'linux'."""
    with patch("morphix_core.ffmpeg_utils.os.name", "linux"):
        result = popen_no_window_kwargs()
    assert result == {"start_new_session": True}


def test_popen_no_window_kwargs_create_no_window_value_is_correct():
    """On os.name == 'nt', result['creationflags'] equals subprocess.CREATE_NO_WINDOW."""
    with patch("morphix_core.ffmpeg_utils.os.name", "nt"):
        result = popen_no_window_kwargs()
    assert result["creationflags"] == _subprocess.CREATE_NO_WINDOW


# ---------------------------------------------------------------------------
# Trim Feature Tests – Requirements Trim-5 through Trim-8
# ---------------------------------------------------------------------------


def test_trim_disabled_when_no_start():
    """Trimming is not active when start is None."""
    ctx = make_ctx("/fake/video.mp4", start=None, end=50.0)
    assert ctx.config.trimming is False
    assert ctx.config.trim_duration == 0.0


def test_trim_disabled_when_no_end():
    """Trimming is not active when end is None."""
    ctx = make_ctx("/fake/video.mp4", start=10.0, end=None)
    assert ctx.config.trimming is False
    assert ctx.config.trim_duration == 0.0


def test_trim_enabled_with_both_values():
    """Trimming is active when both start and end are provided."""
    ctx = make_ctx("/fake/video.mp4", start=10.0, end=60.0)
    assert ctx.config.trimming is True
    assert ctx.config.trim_duration == 50.0


def test_trimming_disabled_when_no_start():
    """Trimming is inactive when start is not set."""
    ctx = make_ctx("/fake/video.mp4", max_mb=15, start=None, end=50.0)
    assert ctx.config.trimming is False


def test_trimming_disabled_when_no_end():
    """Trimming is inactive when end is not set."""
    ctx = make_ctx("/fake/video.mp4", max_mb=15, start=10.0, end=None)
    assert ctx.config.trimming is False


def test_estimated_segment_mb():
    """_estimated_segment_mb uses source bitrate * trim_duration."""
    ctx = make_ctx("/fake/video.mp4", max_mb=15, start=10.0, end=30.0)
    ctx.probe = {
        "format": {"duration": "120.0", "bit_rate": "8000000"},  # 8 Mbps
        "streams": [{"codec_type": "video"}],
    }
    # 8_000_000 bps * 20s / 8 / 1_000_000 = 20 MB
    assert ctx._estimated_segment_mb() == 20.0


def test_probe_media_uses_trim_duration_for_bitrate():
    """Bitrate calculation uses trimmed duration when trimming is active."""
    with patch(
        "morphix_core.encoding.find_ffmpeg_binaries",
        return_value=(None, None, "missing"),
    ):
        config = CompressConfig("/fake/video.mp4", max_mb=15, start=10.0, end=60.0)
        ctx = RunContext(config)

    ctx.probe = {
        "format": {"duration": "300.0"},
        "streams": [{"codec_type": "video"}],
    }

    # trimming is True, trim_duration is 50.0
    assert ctx.config.trimming is True
    assert ctx.config.trim_duration == 50.0
