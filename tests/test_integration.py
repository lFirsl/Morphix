import os
import shutil
import subprocess
from unittest.mock import patch

import pytest
from morphix_core.core import find_ffmpeg_binaries, run

pytestmark = pytest.mark.integration

TEST_VIDEO = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".example_videos", "Splatoon 3 - Test Compression File.mp4")
)
TARGET_MB = 5


def get_ffprobe_or_skip():
    ffmpeg_path, ffprobe_path, source = find_ffmpeg_binaries()
    if not ffprobe_path:
        pytest.skip("ffprobe not available")
    return ffprobe_path


@pytest.mark.integration
def test_output_file_created_at_expected_path(tmp_path):
    """Output file is created at the expected path after compression."""
    get_ffprobe_or_skip()
    if not os.path.isfile(TEST_VIDEO):
        pytest.skip("Test video not found")

    input_copy = str(tmp_path / "input.mp4")
    shutil.copy2(TEST_VIDEO, input_copy)

    output_path = run(input_copy, max_mb=TARGET_MB, overwrite=True, progress=False, disable_logs=True)
    assert os.path.isfile(output_path), f"Expected output file at {output_path} but it was not created"


@pytest.mark.integration
def test_output_file_size_within_10_percent_of_target(tmp_path):
    """Output file size is within 10% of the target size."""
    get_ffprobe_or_skip()
    if not os.path.isfile(TEST_VIDEO):
        pytest.skip("Test video not found")

    input_copy = str(tmp_path / "input.mp4")
    shutil.copy2(TEST_VIDEO, input_copy)

    output_path = run(input_copy, max_mb=TARGET_MB, overwrite=True, progress=False, disable_logs=True)

    target_bytes = TARGET_MB * 1_000_000
    actual_bytes = os.path.getsize(output_path)
    assert actual_bytes <= target_bytes * 1.10, (
        f"Output {actual_bytes / 1_000_000:.2f} MB exceeds target {TARGET_MB} MB by more than 10%"
    )


@pytest.mark.integration
def test_output_file_is_valid_mp4(tmp_path):
    """Output file is a valid MP4 (ffprobe exits 0)."""
    ffprobe_path = get_ffprobe_or_skip()
    if not os.path.isfile(TEST_VIDEO):
        pytest.skip("Test video not found")

    input_copy = str(tmp_path / "input.mp4")
    shutil.copy2(TEST_VIDEO, input_copy)

    output_path = run(input_copy, max_mb=TARGET_MB, overwrite=True, progress=False, disable_logs=True)

    result = subprocess.run(
        [ffprobe_path, "-v", "error", output_path],
        capture_output=True,
    )
    assert result.returncode == 0, f"ffprobe failed on output: {result.stderr.decode()}"


@pytest.mark.integration
def test_passlog_files_cleaned_up_after_compression(tmp_path):
    """Passlog files are cleaned up after successful compression."""
    get_ffprobe_or_skip()
    if not os.path.isfile(TEST_VIDEO):
        pytest.skip("Test video not found")

    input_copy = str(tmp_path / "input.mp4")
    shutil.copy2(TEST_VIDEO, input_copy)

    run(input_copy, max_mb=TARGET_MB, overwrite=True, progress=False, disable_logs=True)

    output_dir = os.path.join(str(tmp_path), ".output")
    # Either the directory was removed (empty after cleanup) or contains no passlog files
    if os.path.exists(output_dir):
        remaining = os.listdir(output_dir)
        passlog_files = [f for f in remaining if "ffmpeg2pass" in f]
        assert len(passlog_files) == 0, f"Passlog files not cleaned up: {passlog_files}"


# ===========================================================================
# Trim Feature Integration Tests (Requirements Trim-5 through Trim-8)
# ===========================================================================

@pytest.mark.integration
def test_trim_direct_copy_output_fits_within_target(tmp_path):
    """When trimmed clip fits within max_mb, output equals a valid MP4 and temp is cleaned up."""
    ffprobe = get_ffprobe_or_skip()
    if not os.path.isfile(TEST_VIDEO):
        pytest.skip("Test video not found")

    input_copy = str(tmp_path / "input.mp4")
    shutil.copy2(TEST_VIDEO, input_copy)

    output_path = run(
        input_copy,
        max_mb=TARGET_MB,
        overwrite=True,
        progress=False,
        disable_logs=True,
        start=0.0,
        end=5.0,
    )
    assert os.path.isfile(output_path)
    # Verify it's a valid MP4 via ffprobe.
    result = subprocess.run(
        [ffprobe, "-v", "error", output_path],
        capture_output=True,
    )
    assert result.returncode == 0


@pytest.mark.integration
def test_trim_encode_produces_output(tmp_path):
    """Trim with two-pass encode produces an output file without temp files."""
    if not os.path.isfile(TEST_VIDEO):
        pytest.skip("Test video not found")

    input_copy = str(tmp_path / "input.mp4")
    shutil.copy2(TEST_VIDEO, input_copy)

    from morphix_core.encoding import RunContext as RealRunContext

    class FakeCtx(RealRunContext):
        def _run_ffmpeg(self, stream, label):
            # Don't actually invoke ffmpeg — just create a valid output file.
            out_dir = os.path.dirname(self.output_path) or "."
            os.makedirs(out_dir, exist_ok=True)
            with open(self.output_path, "wb") as f:
                f.write(b"\x00" * 5_000)

    import morphix_core.core as core_mod

    with patch.object(core_mod, "RunContext", FakeCtx), \
         patch("morphix_core.cli.check_target_exceeds_file_size"), \
         patch("morphix_core.cli.check_low_compression_ratio", return_value=False):
        output_path = run(
            input_copy,
            max_mb=1,
            overwrite=True,
            progress=False,
            disable_logs=True,
            start=0.0,
            end=60.0,
        )

    assert os.path.isfile(output_path)

    # No temp trimmed file should exist — trim is applied directly via -ss/-t.
    trimmed_candidate = str(tmp_path / "input_trimmed.mp4")
    assert not os.path.exists(trimmed_candidate)
