import os
import shutil
import subprocess
import pytest
from morphix_core.core import find_ffmpeg_binaries, run

pytestmark = pytest.mark.integration


def get_ffmpeg_or_skip():
    ffmpeg_path, ffprobe_path, source = find_ffmpeg_binaries()
    if not ffmpeg_path or not ffprobe_path:
        pytest.skip("ffmpeg/ffprobe not available")
    return ffmpeg_path, ffprobe_path


TEST_VIDEO = os.path.join(os.path.dirname(__file__), "..", ".example_videos", "Rainmaker Pre-Pop WipeOut.mp4")
TARGET_MB = 15


@pytest.mark.integration
def test_output_file_created_at_expected_path(tmp_path):
    ffmpeg_path, ffprobe_path = get_ffmpeg_or_skip()
    if not os.path.isfile(TEST_VIDEO):
        pytest.skip("Test video not found")

    input_copy = str(tmp_path / "input.mp4")
    shutil.copy2(TEST_VIDEO, input_copy)

    output_path = run(input_copy, max_mb=TARGET_MB, overwrite=True, progress=False, disable_logs=True)
    assert os.path.isfile(output_path)


@pytest.mark.integration
def test_output_file_size_within_10_percent_of_target(tmp_path):
    ffmpeg_path, ffprobe_path = get_ffmpeg_or_skip()
    if not os.path.isfile(TEST_VIDEO):
        pytest.skip("Test video not found")

    input_copy = str(tmp_path / "input.mp4")
    shutil.copy2(TEST_VIDEO, input_copy)

    output_path = run(input_copy, max_mb=TARGET_MB, overwrite=True, progress=False, disable_logs=True)

    target_bytes = TARGET_MB * 1_000_000
    actual_bytes = os.path.getsize(output_path)
    # Output should not exceed target by more than 10%
    assert actual_bytes <= target_bytes * 1.10, (
        f"Output {actual_bytes} bytes exceeds target {target_bytes} bytes by more than 10%"
    )


@pytest.mark.integration
def test_output_file_is_valid_mp4(tmp_path):
    ffmpeg_path, ffprobe_path = get_ffmpeg_or_skip()
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
    ffmpeg_path, ffprobe_path = get_ffmpeg_or_skip()
    if not os.path.isfile(TEST_VIDEO):
        pytest.skip("Test video not found")

    input_copy = str(tmp_path / "input.mp4")
    shutil.copy2(TEST_VIDEO, input_copy)

    run(input_copy, max_mb=TARGET_MB, overwrite=True, progress=False, disable_logs=True)

    output_dir = os.path.join(str(tmp_path), ".output")
    # Either the directory doesn't exist (cleaned up) or it's empty
    if os.path.exists(output_dir):
        remaining = os.listdir(output_dir)
        passlog_files = [f for f in remaining if "ffmpeg2pass" in f]
        assert len(passlog_files) == 0, f"Passlog files not cleaned up: {passlog_files}"
